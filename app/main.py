import logging
import os
import socket
import time
import uuid
from datetime import date, datetime
from typing import Any

from flask import Flask, g, jsonify, request
from prometheus_client import Counter
from prometheus_flask_exporter import PrometheusMetrics
from psycopg_pool import ConnectionPool
from pythonjsonlogger.jsonlogger import JsonFormatter

INSTANCE_ID = os.getenv("APP_INSTANCE_ID") or socket.gethostname()
VISIT_EVENTS_COUNTER = Counter(
    "app_visit_events_total",
    "Number of visit events persisted by the application.",
)
MESSAGES_CREATED_COUNTER = Counter(
    "app_messages_created_total",
    "Number of messages created by the application.",
)


def configure_logging() -> logging.Logger:
    handler = logging.StreamHandler()
    handler.setFormatter(
        JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

    return logging.getLogger("sna_demo_app")


def build_database_url() -> str:
    explicit_url = os.getenv("DATABASE_URL")
    if explicit_url:
        return explicit_url

    user = os.getenv("POSTGRES_USER", "app_user")
    password = os.getenv("POSTGRES_PASSWORD", "app_password")
    host = os.getenv("POSTGRES_HOST", "postgres")
    port = os.getenv("POSTGRES_PORT", "5432")
    database = os.getenv("POSTGRES_DB", "app_db")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def create_connection_pool(database_url: str, logger: logging.Logger) -> ConnectionPool:
    retries = int(os.getenv("DB_CONNECT_RETRIES", "20"))
    delay_seconds = float(os.getenv("DB_CONNECT_DELAY", "2"))
    max_pool_size = int(os.getenv("DB_POOL_MAX_SIZE", "10"))

    for attempt in range(1, retries + 1):
        pool = ConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=max_pool_size,
            open=False,
            kwargs={"autocommit": True},
        )
        try:
            pool.open()
            with pool.connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1;")
                    cursor.fetchone()
            logger.info(
                "database connection established",
                extra={"database_url": database_url, "attempt": attempt},
            )
            return pool
        except Exception as exc:
            pool.close()
            logger.warning(
                "database connection attempt failed",
                extra={
                    "attempt": attempt,
                    "retries": retries,
                    "error": str(exc),
                },
            )
            if attempt == retries:
                raise
            time.sleep(delay_seconds)

    raise RuntimeError("Failed to initialize the database connection pool.")


def ensure_schema(pool: ConnectionPool) -> None:
    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS visit_events (
                    id BIGSERIAL PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    instance_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_visit_events_created_at
                ON visit_events (created_at DESC);
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id BIGSERIAL PRIMARY KEY,
                    message TEXT NOT NULL,
                    instance_id TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_messages_created_at
                ON messages (created_at DESC);
                """
            )


def serialize_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def create_app() -> Flask:
    logger = configure_logging()
    app = Flask(__name__)
    app.config["APP_NAME"] = os.getenv("APP_NAME", "sna-demo-app")
    app.config["INSTANCE_ID"] = INSTANCE_ID

    database_url = build_database_url()
    pool = create_connection_pool(database_url, logger)
    ensure_schema(pool)
    app.extensions["db_pool"] = pool

    metrics = PrometheusMetrics(app, path="/metrics")
    metrics.info(
        "app_build_info",
        "Application metadata",
        app_name=app.config["APP_NAME"],
        instance_id=INSTANCE_ID,
    )

    @app.before_request
    def before_request() -> None:
        g.request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        g.started_at = time.perf_counter()

    @app.after_request
    def after_request(response):  # type: ignore[no-untyped-def]
        started_at = getattr(g, "started_at", time.perf_counter())
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        response.headers["X-Request-ID"] = g.request_id
        response.headers["X-App-Instance"] = INSTANCE_ID

        logger.info(
            "request completed",
            extra={
                "request_id": g.request_id,
                "method": request.method,
                "path": request.path,
                "status_code": response.status_code,
                "remote_addr": request.headers.get(
                    "X-Forwarded-For", request.remote_addr
                ),
                "duration_ms": duration_ms,
                "user_agent": request.user_agent.string,
            },
        )
        return response

    @app.get("/")
    def index():
        return jsonify(
            {
                "app": app.config["APP_NAME"],
                "status": "ok",
                "instance_id": INSTANCE_ID,
                "hostname": socket.gethostname(),
                "time": datetime.utcnow().isoformat() + "Z",
                "endpoints": {
                    "health": "/health",
                    "ready": "/ready",
                    "metrics": "/metrics",
                    "visits": "/api/visits",
                    "messages": "/api/messages",
                },
            }
        )

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "instance_id": INSTANCE_ID})

    @app.get("/ready")
    def ready():
        pool = app.extensions["db_pool"]
        try:
            with pool.connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1;")
                    cursor.fetchone()
            return jsonify({"status": "ready", "instance_id": INSTANCE_ID})
        except Exception as exc:
            logger.exception("readiness check failed")
            return (
                jsonify(
                    {
                        "status": "not_ready",
                        "instance_id": INSTANCE_ID,
                        "error": str(exc),
                    }
                ),
                503,
            )

    @app.get("/api/visits")
    def register_visit():
        pool = app.extensions["db_pool"]
        with pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO visit_events (request_id, instance_id, path)
                    VALUES (%s, %s, %s)
                    RETURNING id, request_id, instance_id, path, created_at;
                    """,
                    (g.request_id, INSTANCE_ID, request.path),
                )
                created_record = cursor.fetchone()
                cursor.execute("SELECT COUNT(*) FROM visit_events;")
                total_visits = cursor.fetchone()[0]

        VISIT_EVENTS_COUNTER.inc()
        return jsonify(
            {
                "visit": {
                    "id": created_record[0],
                    "request_id": created_record[1],
                    "instance_id": created_record[2],
                    "path": created_record[3],
                    "created_at": serialize_value(created_record[4]),
                },
                "total_visits": total_visits,
            }
        )

    @app.get("/api/messages")
    def list_messages():
        requested_limit = request.args.get("limit", default="10")
        try:
            limit = max(1, min(int(requested_limit), 100))
        except ValueError:
            return jsonify({"error": "limit must be an integer between 1 and 100"}), 400

        pool = app.extensions["db_pool"]
        with pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, message, instance_id, created_at
                    FROM messages
                    ORDER BY created_at DESC
                    LIMIT %s;
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()

        messages = [
            {
                "id": row[0],
                "message": row[1],
                "instance_id": row[2],
                "created_at": serialize_value(row[3]),
            }
            for row in rows
        ]
        return jsonify({"count": len(messages), "messages": messages})

    @app.post("/api/messages")
    def create_message():
        payload = request.get_json(silent=True) or {}
        raw_message = str(payload.get("message", "")).strip()
        message = raw_message[:500] or f"auto-generated message from {INSTANCE_ID}"

        pool = app.extensions["db_pool"]
        with pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO messages (message, instance_id)
                    VALUES (%s, %s)
                    RETURNING id, message, instance_id, created_at;
                    """,
                    (message, INSTANCE_ID),
                )
                row = cursor.fetchone()

        MESSAGES_CREATED_COUNTER.inc()
        return (
            jsonify(
                {
                    "message": {
                        "id": row[0],
                        "message": row[1],
                        "instance_id": row[2],
                        "created_at": serialize_value(row[3]),
                    }
                }
            ),
            201,
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
