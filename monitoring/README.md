# Member B Deliverables

This directory contains the observability stack for the team project:

- Prometheus configured to scrape the Flask app and NGINX exporter.
- Grafana with provisioned Prometheus and Loki datasources.
- A pre-built Grafana dashboard for the Flask application.
- Loki + Promtail for container log aggregation.
- A Compose fragment ready to merge into the final `docker-compose.yml`.

## Project layout

- `compose.member-b.yml`: Compose fragment with all observability services (Member A merges this).
- `prometheus/prometheus.yml`: Scrape configs for Flask app and NGINX exporter.
- `grafana/datasources.yml`: Pre-configures Prometheus and Loki as data sources in Grafana.
- `grafana/dashboards.yml`: Dashboard provider config pointing to the `dashboards/` folder.
- `grafana/dashboards/flask-app.json`: A ready-to-use dashboard showing request rate, latency, error rate, and visit count.
- `loki/local-config.yaml`: Loki server settings (in-memory ring, filesystem storage).
- `promtail/config.yml`: Promtail configuration that discovers all running containers via Docker socket and ships logs to Loki.
- `README.md`: This file.

## Observability endpoints

Once the final stack is running, the following will be available:

| Service    | Port  | URL                       | Description                        |
|------------|-------|---------------------------|------------------------------------|
| Prometheus | 9090  | `http://localhost:9090`   | Metrics query & alerting UI        |
| Grafana    | 3000  | `http://localhost:3000`   | Dashboards (login: `admin`/`admin`)|
| Loki       | 3100  | (internal only)           | Log aggregation backend            |
| Promtail   | —     | (internal only)           | Log collector (must access Docker socket) |

The Flask app `/metrics` endpoint is scraped by Prometheus at `http://app:8000/metrics`.
The NGINX exporter is expected at `http://nginx-exporter:9113/metrics` (Member A must include it).

Container logs are automatically collected by Promtail and indexed into Loki.  
In Grafana, explore logs with a query like `{container="flask-app"} |= ""`.

## Local / standalone test

The observability services cannot run meaningfully without the application and NGINX,
but you can start them together with Member C’s app to verify Prometheus targets:

```bash
# Start the whole team stack (Member A's merged compose) or test with Member C's fragment:
docker compose -f ../compose.member-c.yml -f compose.member-b.yml up -d