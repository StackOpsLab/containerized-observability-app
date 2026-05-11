import argparse
import asyncio
import json
import os
import random
import statistics
import time
import uuid
from collections import Counter

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate mixed read/write traffic for dashboards and logs."
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("TARGET_URL", "http://localhost:8000"),
        help="Base URL of the reverse proxy or application.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=float(os.getenv("LOAD_DURATION", "60")),
        help="How long to generate traffic, in seconds.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=int(os.getenv("LOAD_CONCURRENCY", "10")),
        help="Number of concurrent async workers.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=float(os.getenv("LOAD_INTERVAL", "0.1")),
        help="Sleep interval between requests for each worker.",
    )
    parser.add_argument(
        "--write-ratio",
        type=float,
        default=float(os.getenv("LOAD_WRITE_RATIO", "0.35")),
        help="Probability of sending POST /api/messages requests.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("LOAD_TIMEOUT", "5")),
        help="Per-request timeout in seconds.",
    )
    args = parser.parse_args()
    if args.concurrency < 1:
        parser.error("--concurrency must be greater than 0")
    if args.duration <= 0:
        parser.error("--duration must be greater than 0")
    if args.interval < 0:
        parser.error("--interval must be greater than or equal to 0")
    if not 0 <= args.write_ratio <= 1:
        parser.error("--write-ratio must be between 0 and 1")
    return args


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * ratio))))
    return round(ordered[index], 2)


async def issue_request(
    client: httpx.AsyncClient,
    base_url: str,
    write_ratio: float,
    worker_id: int,
) -> tuple[str, int, float]:
    roll = random.random()
    request_headers = {
        "User-Agent": "sna-loadtester/1.0",
        "X-Request-ID": f"load-{worker_id}-{uuid.uuid4()}",
    }

    if roll < write_ratio:
        endpoint = "/api/messages"
        method = "POST"
        request_kwargs = {
            "json": {
                "message": f"synthetic traffic message from worker-{worker_id}",
            }
        }
    elif roll < min(write_ratio + 0.45, 1):
        endpoint = "/api/visits"
        method = "GET"
        request_kwargs = {}
    else:
        endpoint = "/"
        method = "GET"
        request_kwargs = {}

    started_at = time.perf_counter()
    response = await client.request(
        method,
        f"{base_url}{endpoint}",
        headers=request_headers,
        **request_kwargs,
    )
    latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
    return endpoint, response.status_code, latency_ms


async def worker(
    worker_id: int,
    args: argparse.Namespace,
    stats: Counter,
    latency_samples: list[float],
    lock: asyncio.Lock,
    deadline: float,
) -> None:
    async with httpx.AsyncClient(timeout=args.timeout) as client:
        while time.perf_counter() < deadline:
            try:
                endpoint, status_code, latency_ms = await issue_request(
                    client=client,
                    base_url=args.base_url.rstrip("/"),
                    write_ratio=args.write_ratio,
                    worker_id=worker_id,
                )
                async with lock:
                    stats["requests_total"] += 1
                    stats[f"endpoint:{endpoint}"] += 1
                    stats[f"status:{status_code}"] += 1
                    latency_samples.append(latency_ms)
            except Exception:
                async with lock:
                    stats["errors_total"] += 1

            if args.interval > 0:
                await asyncio.sleep(args.interval)


async def main() -> None:
    args = parse_args()
    stats: Counter = Counter()
    latency_samples: list[float] = []
    lock = asyncio.Lock()
    deadline = time.perf_counter() + args.duration

    started_at = time.perf_counter()
    await asyncio.gather(
        *[
            worker(
                worker_id=index + 1,
                args=args,
                stats=stats,
                latency_samples=latency_samples,
                lock=lock,
                deadline=deadline,
            )
            for index in range(args.concurrency)
        ]
    )
    elapsed_seconds = round(time.perf_counter() - started_at, 2)

    successful_requests = stats["requests_total"]
    requests_per_second = round(successful_requests / elapsed_seconds, 2) if elapsed_seconds else 0.0

    summary = {
        "base_url": args.base_url,
        "duration_seconds": elapsed_seconds,
        "concurrency": args.concurrency,
        "interval_seconds": args.interval,
        "write_ratio": args.write_ratio,
        "requests_total": successful_requests,
        "errors_total": stats["errors_total"],
        "requests_per_second": requests_per_second,
        "latency_ms": {
            "min": round(min(latency_samples), 2) if latency_samples else 0.0,
            "mean": round(statistics.mean(latency_samples), 2)
            if latency_samples
            else 0.0,
            "p50": percentile(latency_samples, 0.50),
            "p95": percentile(latency_samples, 0.95),
            "max": round(max(latency_samples), 2) if latency_samples else 0.0,
        },
        "status_codes": {
            key.split(":", 1)[1]: value
            for key, value in sorted(stats.items())
            if key.startswith("status:")
        },
        "endpoint_distribution": {
            key.split(":", 1)[1]: value
            for key, value in sorted(stats.items())
            if key.startswith("endpoint:")
        },
    }

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
