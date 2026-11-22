# Agentic Fitbit Data Analysis

EECE 503P/798S course project (Fall 2026) — Karim Assi, Jad Harakeh.

Fitbit shows daily scores, but answering questions like *"why was my sleep worse this month?"* or
*"did my new training routine change my recovery?"* still means scrolling through screens and comparing
numbers by hand. This project builds an agent that analyzes months of a user's Fitbit data, decides
which metrics and time windows are worth investigating, and reports trends, changes and relationships —
with every insight backed by a computed statistic the user can inspect.

## Quickstart

Needs Python 3.12+, Node 22 and Docker. Commands run from the repository root unless they `cd`.

**1. The app alone, on made-up data** (no backend, no keys):

```bash
cd mobile && npm ci && npm run web     # http://localhost:8081
```

Sign in as `demo@patterns.app` / `demo-password`. Every screen works on the in-memory mock.

**2. The whole stack locally:**

```bash
cp .env.example .env
# In .env: set FA_TOKEN_KEY (the command that makes one is in the file) and
# FA_ADMIN_EMAILS=["you@example.com"]. FA_OPENAI_API_KEY is needed only for chat answers.
docker compose up -d db                       # Postgres on localhost:5433
python3 -m venv .venv && source .venv/bin/activate
pip install -e "backend[dev]"
alembic -c backend/alembic.ini upgrade head
uvicorn app.api.main:app --app-dir backend --reload   # API on :8000, its docs on /docs
```

In a second terminal, the app against that API:

```bash
cd mobile && npm ci && EXPO_PUBLIC_API_URL=http://127.0.0.1:8000 npm run web
```

Sign up in the browser with the email from `FA_ADMIN_EMAILS`, then approve it:
`python -m app.auth approve you@example.com`. Data comes from Google Health (Settings → Connect,
after the [Google sign-in setup](#google-health-sign-in-live-data)) or a Takeout export in
`FA_EXPORT_DIR`. Without an OpenAI key, Ask answers `503 agent_unavailable`; everything else
works.

**3. The checks CI runs** (no keys, no paid calls; tests build their own SQLite database):

```bash
(source .venv/bin/activate && cd backend && ruff check . && ruff format --check . && pytest -q)
(cd mobile && npm run lint && npm run typecheck && npm test && npx expo export --platform web)
```

**4. The evaluation.** Methods, results and the command behind each result are in
[docs/evaluation.md](docs/evaluation.md) and [docs/test-results.md](docs/test-results.md).
Most scripts in `eval/` call paid models on purpose: read [docs/costs.md](docs/costs.md) first.
The deployed setup (Railway and Vercel) is in [docs/deployment.md](docs/deployment.md), the API
in [docs/api.md](docs/api.md).

## Repository layout

| Path | Contents |
|---|---|
| `backend/` | FastAPI service: data ingestion, analysis tools, agent, API |
| `mobile/` | Expo (React Native) app for iOS, Android and web |
| `eval/` | Benchmark and evaluation scripts for PHIA, baselines, routing, retrieval, verifier checks, logging and team privacy. See [evaluation results](docs/evaluation.md) before running paid scripts |
| `docs/` | [Status](docs/status.md) (start here), [plan](docs/plan.md), [API reference](docs/api.md), [architecture](docs/architecture.md), [evaluation](docs/evaluation.md), [deployment](docs/deployment.md), product, metrics |

## Contributing

Work goes through short-lived branches and pull requests into a protected `main`. See
[AGENTS.md](AGENTS.md) for the workflow, the verification checklist and the project's rules; AI
coding agents read it automatically (`CLAUDE.md` points to it).

## Data and privacy

Personal Fitbit exports (Google Takeout) are **never committed**. Unzip an export into `Takeout/`
(git-ignored) and point `FA_EXPORT_DIR` at it to run the pipeline locally.

## Setup

### Backend

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e "backend[dev]"
(cd backend && pytest -q)
```

Run the API on a local export. Run it **from the repository root** with the virtual environment
active; the export path is relative to where you run it. Settings can also go in `.env` (see
`.env.example`).

```bash
source .venv/bin/activate
FA_EXPORT_DIR=Takeout FA_TIMEZONE=Asia/Beirut uvicorn app.api.main:app --app-dir backend --reload
```

It listens on `http://127.0.0.1:8000`. Interactive API docs are at `/docs`. Data, chat and
Google endpoints need a signed-in, approved account (see *Accounts* below).

### Accounts

People sign up with an email and password. Addresses on the configured pilot invite list are approved at sign-up. Other sign-ups wait for the owner.
Put the owner's email in `.env` as `FA_ADMIN_EMAILS=["you@example.com"]`, then:

```bash
python -m app.auth pending                    # sign-ups waiting
python -m app.auth approve you@example.com    # also how the owner approves their own account
python -m app.auth set-password you@example.com   # sets a password (asked without echo)
python -m app.auth set-role you@example.com supervisor   # may create teams (or: member)
python -m app.teams demo-members <team code>   # made-up members to try a team report locally
```

`set-password` is how the owner claims the account `python -m app.sync pull` created, and how a
forgotten password is replaced until there is a reset by email. Approving someone does not add
them as a Google test user: do that in the Google Cloud console too.

### Database

Postgres runs in Docker for local development (port 5433, so it does not clash with a Postgres
already on 5432). Schema changes are Alembic migrations in `backend/migrations/`.

```bash
docker compose up -d db                       # start Postgres
alembic -c backend/alembic.ini upgrade head   # create or update the tables
```

Tests do not need Postgres: they build a SQLite database by running the same migrations.

### Google Health sign-in (live data)

Live data comes from the Google Health API. It needs a Google Cloud project of your own:

1. Create a project and enable the **Google Health API**.
2. Under **Google Auth Platform**, create the consent screen (audience **External**, status
   **Testing**) and add the Google account your Fitbit uses as a **test user**.
3. Under **Data access**, add the read-only scopes `googlehealth.activity_and_fitness`,
   `googlehealth.health_metrics_and_measurements`, `googlehealth.sleep` and
   `googlehealth.nutrition` (each `https://www.googleapis.com/auth/<scope>.readonly`).
4. Under **Clients**, create an OAuth client of type **Desktop app** and put its ID and secret in
   `.env` as `FA_GOOGLE_CLIENT_ID` and `FA_GOOGLE_CLIENT_SECRET`.

Then, from the repository root:

```bash
source .venv/bin/activate
python -m app.sync connect      # signs in through the browser
python -m app.sync check        # confirms each kind of data can be read
python -m app.sync compare --export Takeout   # how closely the API matches a Takeout export
python -m app.sync pull --email you@example.com  # store the last 120 days in the database
```

The sign-in is stored in `data/google_token.json` (git-ignored, readable only by you). These
scopes are restricted, so the app stays in Testing mode: only test users can sign in, and Google
expires the sign-in after 7 days, after which `connect` has to be run again.

**From the app** (any approved person): Settings → *Google Health* → **Connect**. This needs
`FA_TOKEN_KEY` in `.env` (see `.env.example`), and the browser and the API on the same machine:
Google sends the browser back to `FA_PUBLIC_URL/google/callback` (`http://127.0.0.1:8000` by
default), which phones can only reach once the backend is deployed.

**Logging food and workouts** (from the Ask screen): the agent prepares a draft, and nothing is
written to Google until the person confirms it in the app. Writes also need
`FA_GOOGLE_WRITES_ENABLED=true` in `.env` (off by default) and the write-only scope
(`googlehealth.nutrition.writeonly` or `googlehealth.activity_and_fitness.writeonly`), which the
app asks for the first time someone logs. Add both scopes to the consent screen's data access.
Any of Google's workout types can be logged; the server adds what the tracker recorded during it
(calories, heart rate and zones, and steps, distance or swim lengths where Fitbit records them).
See [docs/workouts.md](docs/workouts.md).

### Mobile app

Requires Node 22. The app runs on mock data by default (sign in as `demo@patterns.app` /
`demo-password`, a made-up owner). Set `EXPO_PUBLIC_API_URL` (e.g. `http://127.0.0.1:8000`) to use
a running backend: accounts, data, chat and Google come from it; reminders stay on mock data.

```bash
cd mobile
npm install
npm start             # then scan the QR code with the Expo Go app (iOS/Android)
npm run web           # web version in the browser
npm run lint && npm run typecheck && npm test
```

To try it on a phone that is not on the same Wi-Fi (for example a friend's), run
`npx expo start --tunnel` and have them scan the QR code with Expo Go.
