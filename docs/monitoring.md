# Monitoring: Prometheus and Grafana

How the deployed API is watched while the pilot runs. Two views, each for what it is good at:

| View | Where | What it shows |
|---|---|---|
| **Grafana** (this page) | Grafana Cloud, or Prometheus and Grafana on a laptop | the live service: whether the API and database are up, requests and their speed by route, answers by outcome, answer time, verifier rejections, tool errors, spending against the caps, Google syncs, accounts, the daily questions, with alerts |
| **Operations page** | the app, Settings → Operations (admins) | the agent's quality for a period: accuracy against the answer key, recall of changes, thumbs, success, latency, cost per answer and per person, response rates ([PR #183](https://github.com/assi09/Patterns/pull/183)) |

Grafana cannot read the database (it has no public port), so the quality checks that need each
person's data stay in the app. Neither view names a person or shows anything they wrote.

## What the API exposes

`GET /metrics` (`backend/app/api/prometheus.py`), in Prometheus' text format, **only when
`FA_METRICS_TOKEN` is set**, and only to `Authorization: Bearer <that token>`.

- **Counted as they happen** (reset on a redeploy, which `rate()` and `increase()` handle):
  `patterns_http_requests_total{method, route, status}` and
  `patterns_http_request_seconds{method, route}`. `route` is the pattern (`/days/{day}`), never a
  real date or id; scrapes of `/metrics` are not counted.
- **Read from the database at each scrape** (so they survive redeploys; one read per 30 s):
  answers by outcome and question type, answers in the last 24 h and their time by quantile,
  verifier rejections, answers with tool errors or repairs, model and tool calls, thumbs, spending
  by kind, today's spending (everyone and the heaviest person) and the caps, people at their daily
  cap, Google syncs by status and their time, accounts and Google connections by status, check-ins
  and evening answers, and `patterns_database_up`.

The dashboard is `monitoring/grafana/dashboards/patterns.json` (24 panels in four rows: at a glance,
the agent, cost and caps, data, people and the API); `monitoring/patterns-dashboard-import.json` is
the same dashboard for importing into another Grafana.

## Step 1: give the API a token (once)

1. Make a token: `openssl rand -hex 32`. Keep it out of git, chat and screenshots.
2. Railway → project `patterns` → `api` → Variables → add `FA_METRICS_TOKEN` with it. The API
   redeploys; `curl -s -o /dev/null -w "%{http_code}" https://api-production-eccff.up.railway.app/metrics`
   should then print `401` (before: `404`).

## Option A: Grafana Cloud (recommended: always on, alerts, a link to share)

1. Create a free account at grafana.com and a stack (any region).
2. In the stack: **Connections → Add new connection → Metrics Endpoint**. Scrape URL
   `https://api-production-eccff.up.railway.app/metrics`, authentication **Bearer**, the token from
   step 1, interval 1 minute. Test the connection, then save.
3. **Dashboards → New → Import**, upload `monitoring/patterns-dashboard-import.json`, and choose the
   stack's Prometheus data source (`grafanacloud-…-prom`).
4. Alerts worth adding (**Alerting → Alert rules → New**, each on the stack's Prometheus):
   - the API is unreachable: `up{job=~".*patterns.*"} == 0` for 5 minutes;
   - the database is unreadable: `patterns_database_up == 0` for 5 minutes;
   - the day's spending passes 80% of its cap:
     `patterns_spend_today_usd{who="everyone"} > 0.8 * patterns_spend_cap_usd{cap="daily_total"}`;
   - Google syncs failing: `increase(patterns_sync_runs_total{status="failed"}[1h]) > 3`;
   - answers getting slow: `patterns_answer_latency_seconds{quantile="0.5"} > 30` for 15 minutes.
   Send them to Karim's email (the default contact point).

## Option B: on a laptop (for working offline, or without an account)

```bash
echo -n "<the token from step 1>" > monitoring/metrics-token   # git-ignored
docker compose --profile monitoring up -d                      # Prometheus and Grafana
open http://localhost:3001                                     # the dashboard opens first
```

Prometheus keeps its data in a Docker volume on the laptop and scrapes production every 30 s, but
only while the laptop is on: closed hours are gaps, and nothing alerts. `docker compose --profile
monitoring down` stops it. `docker compose up -d db` still starts only Postgres.

## How it was checked (2026-11-17)

- `backend/tests/test_prometheus.py`: no token configured means no endpoint; a wrong or missing
  token gets 401; the database's numbers come out right on made-up data; requests are counted by
  route pattern and no label holds an email, a date from a path or a message's words; a database
  outage gives `patterns_database_up 0` instead of a failed scrape.
- End to end on a laptop: a local API with a made-up token and database, scraped by this repo's
  Prometheus (target `up`), the dashboard provisioned in Grafana and each headline query returning
  the expected value on planted data (success 100%, median answer time 8.4 s, question types 4/4/4,
  one account waiting, $0.132 spent today).
