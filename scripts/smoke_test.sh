#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:${NGINX_HTTP_PORT:-80}}"
PROMETHEUS_URL="${PROMETHEUS_URL:-http://localhost:9090}"
GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"
LOKI_URL="${LOKI_URL:-http://localhost:3100}"
EXPORTER_URL="${EXPORTER_URL:-http://localhost:${NGINX_EXPORTER_PORT:-9113}}"

retry() {
  local attempts="$1"
  local delay_seconds="$2"
  shift 2

  local attempt
  for attempt in $(seq 1 "$attempts"); do
    if "$@" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$delay_seconds"
  done

  return 1
}

assert_json_field() {
  local json_payload="$1"
  local field_path="$2"
  local expected="$3"

  JSON_PAYLOAD="$json_payload" FIELD_PATH="$field_path" EXPECTED_VALUE="$expected" python3 - <<'PY'
import json
import os
import sys

payload = json.loads(os.environ["JSON_PAYLOAD"])
expected = os.environ["EXPECTED_VALUE"]
value = payload
for part in os.environ["FIELD_PATH"].split("."):
    value = value[part]

if str(value) != expected:
    raise SystemExit(f"Expected {os.environ['FIELD_PATH']}={expected!r}, got {value!r}")
PY
}

echo "Waiting for public application endpoints..."
retry 30 2 curl -fsS "${BASE_URL}/health" >/dev/null
retry 30 2 curl -fsS "${BASE_URL}/ready" >/dev/null

root_response="$(curl -fsS "${BASE_URL}/")"
health_response="$(curl -fsS "${BASE_URL}/health")"
ready_response="$(curl -fsS "${BASE_URL}/ready")"

assert_json_field "$root_response" "status" "ok"
assert_json_field "$health_response" "status" "ok"
assert_json_field "$ready_response" "status" "ready"

echo "Checking write/read API flow..."
review_message="smoke-test-$(date +%s)"
create_response="$(curl -fsS -X POST "${BASE_URL}/api/messages" -H 'Content-Type: application/json' -d "{\"message\":\"${review_message}\"}")"
assert_json_field "$create_response" "message.message" "$review_message"

messages_response="$(curl -fsS "${BASE_URL}/api/messages?limit=20")"
JSON_PAYLOAD="$messages_response" EXPECTED_SUBSTRING="$review_message" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["JSON_PAYLOAD"])
needle = os.environ["EXPECTED_SUBSTRING"]
messages = [item["message"] for item in payload["messages"]]
if needle not in messages:
    raise SystemExit(f"Message {needle!r} not found in recent messages")
PY

echo "Checking load balancing across replicas..."
instance_sample_file="$(mktemp)"
for _ in $(seq 1 9); do
  curl -fsSI "${BASE_URL}/" | tr -d '\r' | awk '/^X-App-Instance:/ {print $2}' >> "$instance_sample_file"
done

unique_instances="$(sort -u "$instance_sample_file" | sed '/^$/d' | wc -l | tr -d ' ')"
if [[ "$unique_instances" -lt 3 ]]; then
  echo "Expected traffic to hit 3 replicas, got ${unique_instances}" >&2
  sort -u "$instance_sample_file" >&2
  exit 1
fi
rm -f "$instance_sample_file"

echo "Checking NGINX rate limiting..."
rate_limit_summary="$(BASE_URL="$BASE_URL" python3 - <<'PY'
import collections
import concurrent.futures
import json
import os
import urllib.error
import urllib.parse
import urllib.request

base_url = os.environ["BASE_URL"].rstrip("/")

def issue_request() -> int:
    try:
        with urllib.request.urlopen(f"{base_url}/api/visits", timeout=10) as response:
            return response.getcode()
    except urllib.error.HTTPError as exc:
        return exc.code

counter = collections.Counter()
with concurrent.futures.ThreadPoolExecutor(max_workers=60) as executor:
    for status_code in executor.map(lambda _: issue_request(), range(60)):
        counter[status_code] += 1

print(json.dumps(counter))
PY
)"

JSON_PAYLOAD="$rate_limit_summary" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["JSON_PAYLOAD"])
if int(payload.get("429", 0)) <= 0:
    raise SystemExit(f"Expected at least one 429 response, got: {payload}")
if int(payload.get("200", 0)) <= 0:
    raise SystemExit(f"Expected successful API responses alongside 429s, got: {payload}")
PY

echo "Checking Prometheus targets and app metrics..."
retry 30 2 curl -fsS "${PROMETHEUS_URL}/-/healthy" >/dev/null
PROMETHEUS_URL="$PROMETHEUS_URL" python3 - <<'PY'
import json
import os
import time
import urllib.request

prometheus_url = os.environ["PROMETHEUS_URL"].rstrip("/")
required_jobs = {"flask-app", "nginx-exporter", "node-exporter", "cadvisor"}

def query(expr: str):
    with urllib.request.urlopen(
        f"{prometheus_url}/api/v1/query?query={urllib.parse.quote(expr, safe='')}",
        timeout=10,
    ) as response:
        return json.load(response)

deadline = time.time() + 60
while time.time() < deadline:
    up_payload = query("up")
    targets = {
        (item["metric"]["job"], item["metric"]["instance"]): item["value"][1]
        for item in up_payload["data"]["result"]
    }
    seen_jobs = {job for job, _ in targets}
    node_payload = query("node_cpu_seconds_total")
    cadvisor_payload = query("container_cpu_usage_seconds_total")
    docker_container_payload = query(
        'count(container_last_seen{id=~"/docker/[a-f0-9]+"})'
    )
    docker_container_count = 0
    if docker_container_payload["data"]["result"]:
        docker_container_count = int(float(docker_container_payload["data"]["result"][0]["value"][1]))

    if (
        required_jobs.issubset(seen_jobs)
        and all(value == "1" for value in targets.values())
        and node_payload["data"]["result"]
        and cadvisor_payload["data"]["result"]
        and docker_container_count > 0
    ):
        break
    time.sleep(2)
else:
    raise SystemExit(
        "Prometheus did not expose all required jobs, metrics, and Docker container IDs within 60 seconds"
    )
PY

curl -fsS "${EXPORTER_URL}/metrics" >/dev/null

echo "Checking Grafana provisioning..."
retry 30 2 curl -fsS "${GRAFANA_URL}/api/health" >/dev/null
datasources_response="$(curl -fsS -u admin:admin "${GRAFANA_URL}/api/datasources")"
dashboards_response="$(curl -fsS -u admin:admin "${GRAFANA_URL}/api/search")"

JSON_PAYLOAD="$datasources_response" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["JSON_PAYLOAD"])
names = {item["name"] for item in payload}
required = {"Prometheus", "Loki"}
missing = required - names
if missing:
    raise SystemExit(f"Missing Grafana datasources: {sorted(missing)}")
PY

JSON_PAYLOAD="$dashboards_response" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["JSON_PAYLOAD"])
titles = {item["title"] for item in payload}
required = {"Flask App Dashboard", "Infrastructure Overview"}
missing = required - titles
if missing:
    raise SystemExit(f"Missing Grafana dashboards: {sorted(missing)}")
PY

echo "Checking Loki ingestion..."
retry 30 2 curl -fsS "${LOKI_URL}/ready" >/dev/null
loki_labels="$(curl -fsS "${LOKI_URL}/loki/api/v1/label/compose_service/values")"

JSON_PAYLOAD="$loki_labels" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["JSON_PAYLOAD"])
services = set(payload["data"])
required_services = {"app1", "app2", "app3", "nginx"}
missing = required_services - services
if missing:
    raise SystemExit(f"Missing Loki compose_service labels: {sorted(missing)}")
PY

echo "Checking PostgreSQL backup flow..."
./scripts/backup_postgres.sh >/dev/null
latest_backup="$(ls -1t backups/*.sql.gz | head -n 1)"
if [[ -z "$latest_backup" || ! -f "$latest_backup" ]]; then
  echo "Backup file was not created" >&2
  exit 1
fi

echo "Smoke test passed."
