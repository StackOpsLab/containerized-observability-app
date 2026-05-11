#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_ROOT/backups}"
SERVICE_NAME="${POSTGRES_SERVICE_NAME:-postgres}"
DB_NAME="${POSTGRES_DB:-app_db}"
DB_USER="${POSTGRES_USER:-app_user}"
DB_PASSWORD="${POSTGRES_PASSWORD:-app_password}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
OUTPUT_FILE="$BACKUP_DIR/${DB_NAME}_${TIMESTAMP}.sql.gz"

COMPOSE_ARGS=()
if [[ -n "${COMPOSE_FILE_PATH:-}" ]]; then
  COMPOSE_ARGS=(-f "$COMPOSE_FILE_PATH")
elif [[ -f "$PROJECT_ROOT/docker-compose.yml" ]]; then
  COMPOSE_ARGS=(-f "$PROJECT_ROOT/docker-compose.yml")
elif [[ -f "$PROJECT_ROOT/docker-compose.yaml" ]]; then
  COMPOSE_ARGS=(-f "$PROJECT_ROOT/docker-compose.yaml")
elif [[ -f "$PROJECT_ROOT/compose.yml" ]]; then
  COMPOSE_ARGS=(-f "$PROJECT_ROOT/compose.yml")
elif [[ -f "$PROJECT_ROOT/compose.yaml" ]]; then
  COMPOSE_ARGS=(-f "$PROJECT_ROOT/compose.yaml")
elif [[ -f "$PROJECT_ROOT/compose.member-c.yml" ]]; then
  COMPOSE_ARGS=(-f "$PROJECT_ROOT/compose.member-c.yml")
fi

mkdir -p "$BACKUP_DIR"

docker compose "${COMPOSE_ARGS[@]}" exec -T \
  -e PGPASSWORD="$DB_PASSWORD" \
  "$SERVICE_NAME" \
  pg_dump \
  --username="$DB_USER" \
  --dbname="$DB_NAME" \
  --clean \
  --if-exists \
  --no-owner \
  --no-privileges \
  | gzip > "$OUTPUT_FILE"

echo "Backup created: $OUTPUT_FILE"
