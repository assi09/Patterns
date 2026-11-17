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

## How it is protected

- **The API's numbers:** `/metrics` exists only when `FA_METRICS_TOKEN` is set, and answers only to
  that bearer token (401 otherwise). The token lives in Railway variables and git-ignored files,
  never in the repository or an image.
- **Prometheus:** no public address. On Railway it has no domain, so only services in the project
  reach it over the private network; on a laptop it listens on 127.0.0.1 only.
- **Grafana:** sign-in required. No anonymous access, no sign-ups, no new organisations, no public
  snapshots; the admin password is `GF_SECURITY_ADMIN_PASSWORD`, set as a secret, never committed.
  Without signing in, the API answers 401 and pages redirect to the login.

## How the history is kept

Prometheus stores its history on a volume mounted at `/prometheus` and keeps 90 days
(`RETENTION`). Grafana keeps its users and settings on a volume at `/var/lib/grafana`; the
dashboard and the data source are provisioned from the image, so a fresh volume recreates them.
Restarts, rebuilds and redeploys keep both. Prometheus' scraping pauses while it is down; the
agent, spending and sync numbers come from the API's database, so once it is back they are right
again, and only the per-minute shape of that gap is missing.

## Option A: on Railway, always on (recommended)

Two services in the `patterns` project, both from this repository, each with a volume.

1. **The API's token:** `api` → Variables → `FA_METRICS_TOKEN` = `${{secret(48)}}` (Railway generates
   it; nobody has to see it). After the redeploy,
   `curl -s -o /dev/null -w "%{http_code}" https://api-production-eccff.up.railway.app/metrics` prints
   `401`.
2. **Prometheus:** New → GitHub repo → this repository; name it `prometheus`.
   - Settings: root directory `monitoring/prometheus` (so the API's `railway.json` does not apply).
   - Variables:
     `METRICS_TOKEN` = `${{api.FA_METRICS_TOKEN}}`; `RAILWAY_RUN_UID` = `0` (Railway volumes belong
     to root; Prometheus' image runs as `nobody` and could not write otherwise).
   - Volume: mount path `/prometheus`.
   - Networking: **no** public domain.
3. **Grafana:** New → GitHub repo → this repository; name it `grafana`.
   - Settings: root directory `monitoring/grafana`.
   - Variables:
     `PROMETHEUS_URL` = `http://prometheus.railway.internal:9090`;
     `GF_SECURITY_ADMIN_PASSWORD` = `${{secret(24)}}`; `GF_SERVER_ROOT_URL` = the domain from the
     next line; `GF_SECURITY_COOKIE_SECURE` = `true`; `PORT` = `3000`.
   - Volume: mount path `/var/lib/grafana`.
   - Networking: generate a domain (port 3000). Sign in as `admin` with the generated password
     (Variables → reveal).
4. Alerts (Grafana → Alerting → Alert rules → New, on the Prometheus data source), sent to Karim's
   email:
   - the API is unreachable: `up{job="patterns-api"} == 0` for 5 minutes;
   - the database is unreadable: `patterns_database_up == 0` for 5 minutes;
   - the day's spending passes 80% of its cap:
     `patterns_spend_today_usd{who="everyone"} > 0.8 * patterns_spend_cap_usd{cap="daily_total"}`;
   - Google syncs failing: `increase(patterns_sync_runs_total{status="failed"}[1h]) > 3`;
   - answers getting slow: `patterns_answer_latency_seconds{quantile="0.5"} > 30` for 15 minutes.
   Grafana's email needs SMTP settings (`GF_SMTP_*`); until then, alerts show on its Alerting page.

Railway bills the two services and their volumes by use: small, a few dollars a month at this load.

## Option B: Grafana Cloud (no services of ours)

Grafana's free hosted stack keeps the history itself. In the stack: Connections → Add new connection
→ **Metrics Endpoint**, URL `https://api-production-eccff.up.railway.app/metrics`, Bearer
authentication with the API's token, every minute; then Dashboards → Import
`monitoring/patterns-dashboard-import.json`. Grafana Cloud accounts require sign-in.

## Option C: on a laptop

```bash
cp monitoring/monitoring.env.example monitoring/monitoring.env   # git-ignored: fill in both values
docker compose --profile monitoring up -d --build prometheus grafana
open http://localhost:3001                                        # sign in as admin
```

The same images as on Railway, the history in Docker volumes (kept across restarts and rebuilds),
both bound to 127.0.0.1. It only scrapes while the laptop is on. `docker compose up -d db` still
starts only Postgres.

## How it was checked (2026-11-17)

- `backend/tests/test_prometheus.py`: no token configured means no endpoint; a wrong or missing
  token gets 401; the database's numbers come out right on made-up data; requests are counted by
  route pattern and no label holds an email, a date from a path or a message's words; a database
  outage gives `patterns_database_up 0` instead of a failed scrape.
- End to end on a laptop: a local API with a made-up token and database, scraped by this repo's
  Prometheus (target `up`), the dashboard provisioned in Grafana and each headline query returning
  the expected value on planted data (success 100%, median answer time 8.4 s, question types 4/4/4,
  one account waiting, $0.132 spent today).
- Protection, on the built images: Grafana's API answers 401 and its dashboard redirects to the
  login without signing in, and lists the dashboard with the admin password.
- History: the stored samples went 3, then 4 after a restart, then 5 after rebuilding the container
  (a lost history would start again at 1).
