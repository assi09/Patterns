# Monitoring: Prometheus and Grafana

How the deployed API is watched while the pilot runs. Three views, each for what it is good at:

| View | Where | What it shows |
|---|---|---|
| **Grafana** (this page) | Grafana Cloud, or Prometheus and Grafana on a laptop | the live service: whether the API and database are up, requests and their speed by route, answers by outcome, answer time, verifier rejections, tool errors, spending against the caps, Google syncs, accounts, the daily questions, with alerts |
| **Sentry** ([below](#errors-sentry)) | sentry.io, when `FA_SENTRY_DSN` is set | where the API fails: each unhandled exception and each logged error with its type, stack and release, grouped, with an email for a new kind; never a message, value, body or person |
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

**Live since 2026-11-17:** Grafana at https://grafana-production-9dd0690c.up.railway.app (sign in
as `admin`; the password is the `grafana` service's `GF_SECURITY_ADMIN_PASSWORD` in Railway →
Variables). Prometheus has no public address. Both secrets were generated straight into Railway.

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
     next line; `GF_SECURITY_COOKIE_SECURE` = `true`; `PORT` = `3000`; `GF_SERVER_HTTP_ADDR` =
     `0.0.0.0` (**not** `::`: Grafana 10.4 exits at once with code 255 on `::`);
     `RAILWAY_RUN_UID` = `0` (as for Prometheus: the volume belongs to root).
   - Volume: mount path `/var/lib/grafana`.
   - Networking: generate a domain (port 3000). Sign in as `admin` with the generated password
     (Variables → reveal).
4. **Alerts** are provisioned from `monitoring/grafana/provisioning/alerting/patterns.yml` (in the image,
   so they come back on every deploy). Railway blocks outgoing email ports (Grafana's own email timed
   out on 465 and 2465), so Grafana posts each alert to the API's `POST /alerts/grafana` with the
   metrics token, and the API emails the admins (`FA_ADMIN_EMAILS`) through Resend's HTTPS API, like
   the Monday team email. Grafana variable: `ALERT_WEBHOOK_TOKEN` = `${{api.FA_METRICS_TOKEN}}`.

   | Alert | Fires when | Why it matters |
   |---|---|---|
   | API down | `up` < 1 for 5 min (also when the scrape is missing) | testers cannot use the app |
   | Database down | `patterns_database_up` < 1 for 5 min | nothing loads |
   | Server errors | more than 5 responses 5xx in 15 min | something is breaking |
   | Answers failing | over 30% of an hour's answers failed, with at least 5 answers | the agent is struggling |
   | Answers slow | typical answer time over 30 s for 15 min | the app feels broken |
   | Daily spend high | today's spending over 80% of the daily cap | chat stops for everyone at 100% |
   | Overall budget | all spending over 80% of the overall cap | the pilot budget is nearly gone |
   | Tester at daily limit | someone reached their daily cap | they are blocked until tomorrow |
   | Google syncs failing | more than 3 failed syncs in an hour | data stops arriving |
   | Reconnect needed | a Google sign-in expired, for 1 h | a tester's data has stopped |
   | Waiting for approval | an account waiting over 2 h | someone is stuck at the door |

   Checked 2026-11-18: all 11 load in Grafana 10.4 from the file, and each query runs on the live
   Prometheus (none firing: API and database up, no errors, 0.5% of the overall budget).

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

## Errors: Sentry

Grafana counts failures; Sentry says where they happen (`backend/app/observability.py`). It is off
until `FA_SENTRY_DSN` is set, and sends errors only (no performance tracing).

**What is sent:** exceptions the API does not handle (a 500) and every `logger.error` or
`logger.exception` record, which is how the chat and the background passes (syncs, alarms, team
alerts, reminders) report failures. Each event keeps the exception type, the stack (files, lines,
functions, the public source around them), the route, the release (`RAILWAY_GIT_COMMIT_SHA`) and
the log template ("Sync failed").

**What is not:** exception messages (replaced by `[removed]`), local variables, log arguments,
breadcrumbs, request bodies, query strings, cookies, headers other than content type and length,
host and user agent, and any user. `tests/test_observability.py` sends a failure carrying a made-up
value, email and session token through a real Sentry client into memory and checks none of them
leave; with the scrubbing switched off, it fails.

**Turning it on** (Sentry's free plan is enough for this project):

1. Sign up at sentry.io, create a **FastAPI** project, copy its DSN.
2. Railway → the `api` service → Variables: `FA_SENTRY_DSN` = the DSN (and optionally
   `FA_SENTRY_ENVIRONMENT`, `production` by default). Railway redeploys.
3. In Sentry → Alerts, keep the default "new issue" email alert (it emails on each new kind of
   error).

Locally it stays off unless the DSN is put in `.env`.

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
- **On Railway (2026-11-17):** Prometheus scrapes the API every 30 s with the token (the API's log
  shows `GET /metrics` 200 from `Prometheus/2.51.2`); Grafana reads Prometheus over the private
  network (`up` = 1, `patterns_database_up` = 1, 40 series); without signing in Grafana's API
  answers 401, the dashboard redirects to the login and sign-up is refused (401); a redeploy of
  Prometheus kept its history (114 stored samples before, 126 after).
- **What Railway needed beyond the images:** each service built from its own folder (the root
  `railway.json` is the API's), no `VOLUME` in the Dockerfiles, `RAILWAY_RUN_UID=0` for both, and
  `GF_SERVER_HTTP_ADDR=0.0.0.0` for Grafana.
