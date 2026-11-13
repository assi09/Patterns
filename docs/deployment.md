# Deployment

How Patterns goes online: the API and Postgres on Railway, the weekly team email as a Railway
cron job, the web app on Vercel, and phones through the web app added to the home screen (or
Expo Go). Everything in the repository is ready (`Dockerfile`, `railway.json`,
`railway.cron.json`, `mobile/vercel.json`, `mobile/public/`); the steps below need the owner's
accounts and are done once.

```
phone / browser ──HTTPS──> Vercel: the web app (mobile/, static)
        │
        └──────HTTPS──> Railway: API (Dockerfile, one process) ──> Railway Postgres
                         Railway cron: python -m app.teams weekly, Mondays 06:00 UTC ──> Resend
Google sign-in ──> https://<api>/google/callback
```

## What is in the repository

- **`Dockerfile`** (repository root): Python 3.12, the backend package, its migrations. On start it
  runs `alembic upgrade head`, then one Uvicorn process on Railway's `PORT`. One process on purpose:
  Google sign-ins in progress, running syncs and the log-in lock live in memory. Checked locally:
  a fresh database migrates through all ten migrations, `/health` answers and sign-up works.
- **`.dockerignore`** lets in only `backend/` code and migrations. `Takeout/`, `data/`, the zips,
  `.env` and the app never reach the image.
- **`railway.json`**: build from the Dockerfile, health check on `/health`, one replica, restart on
  failure.
- **`railway.cron.json`**: the cron service's settings as a record (`python -m app.teams weekly`,
  Mondays 06:00 UTC, no restarts). Railway no longer accepts a second config file per service, so
  these are set on the service itself (done on 2026-10-26). Each report is made and emailed once,
  so a rerun is harmless.
- **`FA_DATABASE_URL`** may be Railway's `postgresql://…`; the app adds the psycopg driver itself.
- **`mobile/vercel.json`**: Vercel builds the web app with `npx expo export --platform web` and sends
  every path to `index.html` (the app does its own routing).
- **`mobile/public/`**: the web page template with what "Add to Home Screen" needs on an iPhone
  (icon, full screen without the browser bar, theme colors) and a web app manifest.

## 1. Railway: the API and Postgres

1. Sign in at railway.com with GitHub. New Project → **Deploy from GitHub repo** →
   `assi09/Patterns`. It finds `railway.json` and builds the `Dockerfile`; the first deploy fails
   until the variables below exist.
2. In the project: **+ New → Database → PostgreSQL**.
3. API service → **Settings → Networking → Generate Domain** (e.g.
   `patterns-api-production.up.railway.app`). This is `<api>` below.
4. API service → **Variables** (secrets only here and in your local `.env`, never in git):

   | Variable | Value |
   |---|---|
   | `FA_DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (Railway fills it in) |
   | `FA_PUBLIC_URL` | `https://<api>` |
   | `FA_APP_URL` | `https://<web>` (from step 3 of Vercel; set it after) |
   | `FA_CORS_ORIGINS` | `["https://<web>"]` |
   | `FA_ADMIN_EMAILS` | `["your@email"]` |
   | `FA_TIMEZONE` | `Asia/Beirut` |
   | `FA_TOKEN_KEY` | a **new** key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
   | `FA_GOOGLE_CLIENT_ID`, `FA_GOOGLE_CLIENT_SECRET` | the **Web application** client from step 2 |
   | `FA_OPENAI_API_KEY`, `FA_TYPESAFE_API_KEY` | as in `.env` |
   | `FA_EMAIL_BACKEND` | `resend` |
   | `FA_EMAIL_API_KEY`, `FA_EMAIL_FROM` | as in `.env` |

   Spending caps (`FA_CHAT_DAILY_CAP_*`, `FA_LLM_SPEND_CAP_USD`) keep their defaults unless set.
5. Redeploy; the log shows the migrations, then `Uvicorn running`. `https://<api>/health` answers
   `{"status":"ok"}`.
6. **The weekly email:** **+ New → GitHub Repo** → the same repository, then on the service:
   start command `python -m app.teams weekly`, cron schedule `0 6 * * 1`, restart policy never.
   Variables: `FA_DATABASE_URL`, `FA_TIMEZONE`, `FA_EMAIL_BACKEND`, `FA_APP_URL` and its own sealed
   `FA_EMAIL_API_KEY`, nothing else. It runs on Mondays and stops; its log prints counts only.

## Secrets on Railway

Railway disclosed on 2026-10-21 that customers' environment variables may have been read by an
attacker, and asked everyone to rotate them. Patterns' secrets went in only after that, under
these rules:

- **Production keys only**: an OpenAI project key, TypeSafe key, Resend key and Google Web client
  made for this deployment, never the local ones, so any of them can be revoked alone.
- **A hard spending limit at each provider**, the real protection if a key leaks: the OpenAI
  production project has a monthly budget of a few dollars; Resend's key can only send (100 a day
  on the free plan). The app's own caps (`docs/costs.md`) sit under those.
- **Sealed** in Railway (the variable's menu → Seal): no one can read the value back from the
  dashboard or API. This does not protect against a breach of Railway itself.
- **Each secret only on the service that uses it**: the email job holds the Resend key and nothing
  else.
- **`FA_TOKEN_KEY` exists only on Railway** and encrypts people's Google sign-ins in the database;
  the access is read-only, and in Testing mode it lapses after 7 days.
- **The database has no public port**: the API and the email job reach it over Railway's private
  network.
- Two-factor sign-in on Railway and GitHub, and Railway's GitHub app limited to the repositories it
  deploys.
- After any provider incident: rotate the affected keys and check each provider's usage page.

## 2. Google Cloud: a Web application sign-in

The local setup uses a "Desktop app" OAuth client, which only returns to `127.0.0.1`. Online:

1. Google Cloud console → APIs & Services → Credentials → **Create credentials → OAuth client ID →
   Web application**.
2. **Authorized redirect URIs**: `https://<api>/google/callback`.
3. Put its ID and secret in the Railway variables above.
4. The OAuth app stays in **Testing**: every person who connects must be listed under **OAuth
   consent screen → Test users**, and their sign-in lasts 7 days (the app asks them to connect
   again).

## 3. Vercel: the web app

1. Sign in at vercel.com with GitHub. **Add New → Project** → `assi09/Patterns`.
2. **Root Directory**: `mobile`. Framework preset: **Other** (the build command and output come from
   `mobile/vercel.json`).
3. **Environment Variables**: `EXPO_PUBLIC_API_URL` = `https://<api>`. It is built into the app, so
   changing it needs a redeploy.
4. Deploy. The address (e.g. `patterns.vercel.app`) is `<web>`: put it in Railway's `FA_APP_URL`
   and `FA_CORS_ORIGINS`, and redeploy the API.

## 4. First sign-in online

1. Open `https://<web>`, sign up with the email in `FA_ADMIN_EMAILS`.
2. Approve it once from Railway: API service → the **⋮** menu → **SSH** (or `railway ssh` with the
   Railway CLI), then `python -m app.auth approve your@email`. After that, approvals happen in the
   app (Settings → Access requests), including **Approve as supervisor**.
3. Settings → **Connect Google Health**. The whole history syncs from Google; the local Takeout
   export is never uploaded (one source per history).

## Deleting an account

When someone asks for their data to be deleted, run, in the same SSH session on the API service,
`python -m app.auth delete their@email` and type the email again when asked. Everything held
about them goes: synced days, check-ins, chats and their traces, memory, reminders, spending,
team memberships, and the teams they supervise. Afterwards, remove them as a test user on the
OAuth consent screen; they can also remove the app from their Google Account's third-party access.

## Phones without paying Apple

| Way | Cost | Who | Notes |
|---|---|---|---|
| **Add to Home Screen** (recommended) | free | anyone with the link | Safari → `https://<web>` → Share → **Add to Home Screen**. Opens full screen with its own icon; it is the same web app. Android: Chrome → **Install app**. |
| **Expo Go** | free | people you add to your Expo account | Publish with `eas update` (needs an Expo project ID in `app.json`); on iOS, Expo Go only opens projects of accounts the person belongs to. To set up when wanted. |
| TestFlight / App Store | $99 a year (Apple Developer Program) | up to 10,000 testers | The only way to a real installed iPhone app for other people. |
| Xcode on your own Mac | free | your own iPhone only | The app expires after 7 days and needs rebuilding. |

The web app needs no store and updates for everyone on each Vercel deploy. What it cannot do on an
iPhone is send push notifications unless installed to the home screen (iOS 16.4+); reminders do not
send notifications yet anyway.

## Checks after each deploy

- `https://<api>/health` answers; the Railway log has no tracebacks.
- Sign in on `https://<web>` on a phone; Today loads; Ask answers one question (a real model call,
  within the daily caps).
- Connecting Google Health returns to the app's Settings with "connected".
- After a Monday: the cron log says how many reports were made and emailed.

## Costs

Railway bills by usage after its trial credit (an always-on small API and Postgres; check the
current plan on railway.com). Vercel's free plan covers the web app. Resend's free plan allows 100
emails a day. Model spending is capped in the app (`docs/costs.md`).
