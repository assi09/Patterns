# API reference

The HTTP API the Patterns app talks to: FastAPI in `backend/app/api`, deployed on Railway
([deployment.md](deployment.md)). The mobile and web app reach it only through the contract in
`mobile/src/api/types.ts` (with `http.ts` and the in-memory `mock.ts`); a change to the contract
updates those files and `backend/app/api/schemas.py` together.

The endpoint, error-code and schema sections below are **generated** from FastAPI's own OpenAPI
schema and the code by `python -m app.api.reference` (run from the repository root with `.venv`
active). `tests/test_api_reference.py` fails when a route or schema changes without regenerating
this page. The interactive version is at `/docs` (Swagger UI) and `/openapi.json` on a running
server.

## Base URLs

| Where | Address |
|---|---|
| Local | `http://127.0.0.1:8000` (`uvicorn app.api.main:app --app-dir backend --reload`, or `docker compose --profile app up`; see the [README](../README.md#quickstart)) |
| Deployed | `https://<api>`, the Railway service's address (see [deployment.md](deployment.md)) |

Browsers may call the API only from the origins in `FA_CORS_ORIGINS` (by default
`http://localhost:8081`, the Expo web server).

## Authentication

1. `POST /auth/signup` or `POST /auth/login` with `{"email", "password"}` returns
   `{"token", "account"}`.
2. Every other call sends `Authorization: Bearer <token>`. A session lasts `FA_SESSION_DAYS`
   (30 by default); `POST /auth/logout` ends it.
3. A new account is `pending` until the owner approves it (`python -m app.auth approve`, or
   `POST /admin/access-requests/{user_id}/approve`), unless its email is on the pilot invite list.

The **Access** column of each endpoint says who may call it:

| Access | Who |
|---|---|
| public | anyone (health check, sign-up, log-in) |
| signed in | any valid session, approved or not (`GET /auth/me`, log-out) |
| approved | an approved account; it only ever sees **its own** data |
| supervisor | an approved account with the `supervisor` role (creating teams) |
| owner | an approved account whose email is in `FA_ADMIN_EMAILS` |

Team routes also check, inside the handler, that the team is the caller's own: a team's reports,
chat, notes, alerts and actions are for its supervisor only, and every team figure comes from at
least five people ([teams.md](teams.md)). A route called with another person's id answers `404` (or
`403`) and never returns or changes their record (`tests/test_privacy_isolation.py`).
After five failed log-ins for an email within 15 minutes, log-ins for it answer
`429 too_many_attempts` until the window passes (kept in memory, per server process).

## Errors

Every error has one shape, whatever raised it:

```json
{"error": {"code": "daily_limit", "message": "You've reached today's limit for questions. Try again tomorrow."}}
```

`code` is stable and meant for the app's logic; `message` is safe to show to the person as is.
Besides the codes listed under [Error codes](#error-codes):

| Status | Code | When |
|---|---|---|
| 401 | `signed_out` | no token, or the session has ended |
| 404 | `not_found` | unknown route, or a record that is missing or someone else's |
| 422 | `invalid_request` | the body or a parameter fails validation (details are not echoed) |
| 503 | `storage_unavailable` | a database error (its details are never logged or returned) |
| 503 | `data_unavailable` | the person's Fitbit data could not be loaded |

## Conventions

- **JSON in camelCase** (`evidenceIds`, `conversationId`), as `types.ts` expects.
- **Days** are `YYYY-MM-DD` in the person's own time zone (`PUT /me/timezone`); timestamps are
  ISO 8601 with an offset.
- **Evidence.** Every number in an answer cites an `Evidence` record (`evidenceIds` on a chat
  message); `GET /evidence/{evidence_id}` returns the statistic, its windows and its test.
- **Spending caps.** `POST /chat` answers `429 daily_limit` once the person's model spending for
  the day reaches `FA_CHAT_DAILY_CAP_PER_USER_USD`, and `429 app_daily_limit` once everyone's
  together reaches `FA_CHAT_DAILY_CAP_TOTAL_USD` ([costs.md](costs.md)).
- **Writes to Google** happen only through `POST /actions/{action_id}/confirm` on a draft the
  person reviewed, and only with `FA_GOOGLE_WRITES_ENABLED=true` and the write scope granted
  ([agent-actions.md](agent-actions.md)).

## Routes not in the schema

| Route | Purpose |
|---|---|
| `GET /google/callback` | where Google sends the browser after the sign-in; the `state` ties it to the person who started it, then it redirects to the app's Settings with `?google=<result>` |
| `GET /metrics` | Prometheus metrics, only when `FA_METRICS_TOKEN` is set and sent as a Bearer token ([monitoring.md](monitoring.md)) |
| `POST /alerts/grafana` | Grafana's alert webhook (same token), forwarded to the owners by email |

<!-- generated: start (python -m app.api.reference) -->

## Endpoints

104 operations, grouped by area.

### meta

| Method | Path | Access | Parameters | Body | Returns | Notes |
|---|---|---|---|---|---|---|
| `GET` | `/health` | public |  |  | map[string, string] |  |

### actions

| Method | Path | Access | Parameters | Body | Returns | Notes |
|---|---|---|---|---|---|---|
| `GET` | `/actions` | approved |  |  | list[[Action](#action)] |  |
| `GET` | `/actions/{action_id}` | approved | `action_id` |  | [Action](#action) |  |
| `POST` | `/actions` | approved |  | [NewDraft](#newdraft) | 201: [Action](#action) |  |
| `POST` | `/actions/{action_id}/revise` | approved | `action_id` | [RevisedDraft](#reviseddraft) | [Action](#action) |  |
| `POST` | `/actions/{action_id}/cancel` | approved | `action_id` | [Version](#version) | [Action](#action) |  |
| `POST` | `/actions/{action_id}/confirm` | approved | `action_id` | [Version](#version) | [Action](#action) |  |
| `POST` | `/actions/{action_id}/undo` | approved | `action_id` | [Version](#version) | [Action](#action) |  |

### alarms

| Method | Path | Access | Parameters | Body | Returns | Notes |
|---|---|---|---|---|---|---|
| `GET` | `/alarms` | approved |  |  | list[[AlarmOut](#alarmout)] | The latest alarms that reached the person, newest first. |
| `POST` | `/alarms/{alarm_id}/feedback` | approved | `alarm_id` | [Feedback](#feedback) | [AlarmOut](#alarmout) |  |
| `GET` | `/alarm-settings` | approved |  |  | [AlarmSettings](#alarmsettings) |  |
| `PUT` | `/alarm-settings` | approved |  | [AlarmSettings](#alarmsettings) | [AlarmSettings](#alarmsettings) |  |

### auth

| Method | Path | Access | Parameters | Body | Returns | Notes |
|---|---|---|---|---|---|---|
| `POST` | `/auth/signup` | public |  | [Credentials](#credentials) | 201: [SignedIn](#signedin) |  |
| `POST` | `/auth/login` | public |  | [Credentials](#credentials) | [SignedIn](#signedin) |  |
| `POST` | `/auth/logout` | public |  |  | 204, no body |  |
| `GET` | `/auth/me` | signed in |  |  | [Account](#account) |  |
| `GET` | `/admin/access-requests` | owner |  |  | list[[AccessRequest](#accessrequest)] |  |
| `POST` | `/admin/access-requests/{user_id}/approve` | owner | `user_id` | [Approval](#approval) or null | [Account](#account) |  |
| `POST` | `/admin/access-requests/{user_id}/reject` | owner | `user_id` |  | [Account](#account) |  |

### calendar

| Method | Path | Access | Parameters | Body | Returns | Notes |
|---|---|---|---|---|---|---|
| `GET` | `/calendar/status` | approved |  |  | [CalendarStatus](#calendarstatus) |  |
| `GET` | `/me/calendar` | approved |  |  | list[[CalendarDay](#calendarday)] | The person's own daily counts: the last four weeks and what is planned ahead. |
| `GET` | `/teams/{team_id}/calendar` | supervisor | `team_id`, `week`? |  | [TeamCalendar](#teamcalendar) | The team's meeting load for a Monday-to-Sunday week (the last full one by default). |

### chat

| Method | Path | Access | Parameters | Body | Returns | Notes |
|---|---|---|---|---|---|---|
| `GET` | `/chat` | approved | `conversation`? |  | list[[ChatMessage](#chatmessage)] | A conversation's messages; without `conversation`, the most recently used one. |
| `GET` | `/conversations` | approved |  |  | list[[Conversation](#conversation)] |  |
| `POST` | `/conversations` | approved |  |  | 201: [Conversation](#conversation) |  |
| `PATCH` | `/conversations/{conversation_id}` | approved | `conversation_id` | [ConversationUpdate](#conversationupdate) | [Conversation](#conversation) | Renames or pins a conversation; pinned ones are listed first. |
| `PUT` | `/chat/{message_id}/rating` | approved | `message_id` | [RatingIn](#ratingin) | [ChatMessage](#chatmessage) | The person's thumbs up or down on one of their answers, counted in the pilot report. |
| `DELETE` | `/conversations/{conversation_id}` | approved | `conversation_id` |  | 204, no body | Deletes the conversation, its messages and its episode; facts and findings stay. |
| `POST` | `/chat` | approved |  | [Question](#question) | list[[ChatMessage](#chatmessage)] |  |

### checkins

| Method | Path | Access | Parameters | Body | Returns | Notes |
|---|---|---|---|---|---|---|
| `POST` | `/me/teams/{team_id}/checkin` | approved | `team_id` | [ShareCheckin](#sharecheckin) | [Membership](#membership) | Turns check-in alerts on or off for one team; off withdraws any alert still waiting. |
| `GET` | `/me/checkins` | approved |  |  | list[[OwnCheckin](#owncheckin)] |  |
| `POST` | `/me/checkins/{alert_id}/send` | approved | `alert_id` |  | [OwnCheckin](#owncheckin) | The person sends their own waiting alert now, before the hour is up. |
| `POST` | `/me/checkins/{alert_id}/stop` | approved | `alert_id` |  | [OwnCheckin](#owncheckin) | The person stops this alert. Check-in alerts stay on; the switch turns them off. |
| `GET` | `/checkins` | approved |  |  | list[[ReceivedCheckin](#receivedcheckin)] |  |
| `POST` | `/checkins/{alert_id}/open` | approved | `alert_id` |  | [ReceivedCheckin](#receivedcheckin) |  |
| `POST` | `/checkins/{alert_id}/mark` | approved | `alert_id` | [MarkCheckin](#markcheckin) | [ReceivedCheckin](#receivedcheckin) |  |
| `PUT` | `/teams/{team_id}/hr` | supervisor | `team_id` | [TeamHr](#teamhr) | [TeamHr](#teamhr) | Names the team's HR contact. An existing HR account is linked at once; an address without an account is emailed an invitation to sign up as this team's HR; none removes it. |

### google

| Method | Path | Access | Parameters | Body | Returns | Notes |
|---|---|---|---|---|---|---|
| `GET` | `/google/status` | approved |  |  | [GoogleStatus](#googlestatus) |  |
| `POST` | `/google/connect` | approved |  | [ConnectOptions](#connectoptions) or null | [ConnectStart](#connectstart) |  |
| `POST` | `/google/sync` | approved |  | [Body_sync_now_google_sync_post](#body_sync_now_google_sync_post) | 202: [GoogleStatus](#googlestatus) |  |
| `POST` | `/google/disconnect` | approved |  |  | [GoogleStatus](#googlestatus) | Forgets the sign-in. The days already synced stay, so the history is kept. |

### data

| Method | Path | Access | Parameters | Body | Returns | Notes |
|---|---|---|---|---|---|---|
| `GET` | `/data/status` | approved |  |  | [DataStatus](#datastatus) |  |

### days

| Method | Path | Access | Parameters | Body | Returns | Notes |
|---|---|---|---|---|---|---|
| `GET` | `/days/latest` | approved |  |  | [Day](#day) | The newest day with data: what Today opens on. |
| `GET` | `/days/{day}` | approved | `day` |  | [Day](#day) |  |
| `GET` | `/days/{day}/workouts` | approved | `day` |  | [DayWorkouts](#dayworkouts) | The workouts that started on this local day, as the tracker or an app recorded them. |
| `GET` | `/days/{day}/hourly` | approved | `day` |  | [HourlySteps](#hourlysteps) | The day's steps in each local hour. |
| `GET` | `/days/{day}/sleep` | approved | `day` |  | [NightStages](#nightstages) | The night that ended on this local day, stage by stage: the main sleep, the longest if there are two, as the daily totals choose it. Read live, like the hourly steps. |
| `GET` | `/checkins/{day}` | approved | `day` |  | [CheckIn](#checkin) or null |  |
| `PUT` | `/checkins/{day}` | approved | `day` | [CheckIn](#checkin) | [CheckIn](#checkin) | Sets or changes today's check-in: how the person feels, 1 to 5, and optional tags. |
| `GET` | `/metrics/{metric}` | approved | `metric`, `end`?, `days`? |  | [MetricSeries](#metricseries) |  |

### notifications

| Method | Path | Access | Parameters | Body | Returns | Notes |
|---|---|---|---|---|---|---|
| `GET` | `/notifications` | approved |  |  | [Inbox](#inbox) |  |
| `POST` | `/notifications/{notification_id}/read` | approved | `notification_id` |  | [NotificationOut](#notificationout) |  |
| `POST` | `/notifications/read-all` | approved |  |  | 204, no body |  |

### memory

| Method | Path | Access | Parameters | Body | Returns | Notes |
|---|---|---|---|---|---|---|
| `GET` | `/memory` | approved |  |  | [MemoryOut](#memoryout) |  |
| `POST` | `/memory/facts/{fact_id}/decision` | approved | `fact_id` | [Decision](#decision) | [FactOut](#factout) |  |
| `PATCH` | `/memory/facts/{fact_id}` | approved | `fact_id` | [Wording](#wording) | [FactOut](#factout) |  |
| `POST` | `/memory/interests` | approved |  | [Opened](#opened) | 204, no body | The person opened a metric's page; anything else is ignored. |
| `DELETE` | `/memory/interests/{topic}` | approved | `topic` |  | 204, no body |  |
| `DELETE` | `/memory/episodes/{episode_id}` | approved | `episode_id` |  | 204, no body |  |
| `DELETE` | `/memory/facts/{fact_id}` | approved | `fact_id` |  | 204, no body |  |

### feedback

| Method | Path | Access | Parameters | Body | Returns | Notes |
|---|---|---|---|---|---|---|
| `POST` | `/feedback` | approved |  | [FeedbackIn](#feedbackin) | 201: [FeedbackOut](#feedbackout) |  |
| `GET` | `/admin/feedback` | owner |  |  | list[[FeedbackRow](#feedbackrow)] | The latest feedback, newest first, for the operations page. |

### metrics

| Method | Path | Access | Parameters | Body | Returns | Notes |
|---|---|---|---|---|---|---|
| `GET` | `/admin/metrics` | owner | `days`?, `include_admins`? |  | object | Totals for the operations page; cached a minute, as the accuracy check reads everyone's data. |

### reminders

| Method | Path | Access | Parameters | Body | Returns | Notes |
|---|---|---|---|---|---|---|
| `GET` | `/reminders` | approved |  |  | list[[ReminderOut](#reminderout)] |  |
| `POST` | `/reminders` | approved |  | [NewReminder](#newreminder) | 201: [ReminderOut](#reminderout) |  |
| `PATCH` | `/reminders/{reminder_id}` | approved | `reminder_id` | [ReminderChange](#reminderchange) | [ReminderOut](#reminderout) |  |
| `DELETE` | `/reminders/{reminder_id}` | approved | `reminder_id` |  | 204, no body |  |
| `GET` | `/notification-settings` | approved |  |  | [NotificationSettings](#notificationsettings) |  |
| `PUT` | `/notification-settings` | approved |  | [NotificationSettings](#notificationsettings) | [NotificationSettings](#notificationsettings) |  |
| `PUT` | `/me/timezone` | approved |  | [TimeZone](#timezone) | 204, no body |  |

### reports

| Method | Path | Access | Parameters | Body | Returns | Notes |
|---|---|---|---|---|---|---|
| `GET` | `/reports/latest` | approved |  |  | [Report](#report) |  |
| `GET` | `/evidence/{evidence_id}` | approved | `evidence_id` |  | [Evidence](#evidence) |  |

### teams

| Method | Path | Access | Parameters | Body | Returns | Notes |
|---|---|---|---|---|---|---|
| `POST` | `/teams` | supervisor |  | [NewTeam](#newteam) | 201: [Team](#team) |  |
| `GET` | `/teams` | supervisor |  |  | list[[Team](#team)] |  |
| `GET` | `/teams/{team_id}` | supervisor | `team_id` |  | [Team](#team) |  |
| `POST` | `/teams/{team_id}/invite-code` | supervisor | `team_id` |  | [Team](#team) | A new code; the old one stops working, people already in the team stay. |
| `GET` | `/pulse/today` | approved |  |  | [PulseToday](#pulsetoday) |  |
| `PUT` | `/pulse/today` | approved |  | [PulseAnswer](#pulseanswer) | [PulseToday](#pulsetoday) |  |
| `GET` | `/teams/{team_id}/pulse` | supervisor | `team_id` |  | [TeamPulse](#teampulse) | Weekly team figures only, each from at least five people; never a person or a day. |
| `GET` | `/teams/{team_id}/reports` | supervisor | `team_id` |  | list[[TeamReportSummary](#teamreportsummary)] |  |
| `GET` | `/teams/{team_id}/reports/{week}` | supervisor | `team_id`, `week` |  | [TeamReport](#teamreport) |  |
| `POST` | `/teams/{team_id}/reports` | supervisor | `team_id` | [GenerateReport](#generatereport) | [TeamReport](#teamreport) | The report for a full week, made now if it was not made yet; never for a week in progress. |
| `GET` | `/teams/{team_id}/chat` | supervisor | `team_id` |  | list[[TeamChatMessage](#teamchatmessage)] |  |
| `PUT` | `/teams/{team_id}/chat/{message_id}/rating` | supervisor | `team_id`, `message_id` | [RatingIn](#ratingin) | [TeamChatMessage](#teamchatmessage) | The supervisor's thumbs up or down on one of the team agent's answers. |
| `GET` | `/teams/{team_id}/notes` | supervisor | `team_id` |  | list[[TeamNote](#teamnote)] |  |
| `POST` | `/teams/{team_id}/notes` | supervisor | `team_id` | [TeamNoteIn](#teamnotein) | 201: [TeamNote](#teamnote) |  |
| `DELETE` | `/teams/{team_id}/notes/{note_id}` | supervisor | `team_id`, `note_id` |  | 204, no body |  |
| `GET` | `/teams/{team_id}/observed` | supervisor | `team_id` |  | [TeamObserved](#teamobserved) | What the team's latest night and day looked like, from the first sync: each figure from at least 5 members with a reading, none while the team's figures are paused. |
| `GET` | `/teams/{team_id}/alerts` | supervisor | `team_id` |  | list[[TeamAlert](#teamalert)] |  |
| `GET` | `/teams/{team_id}/actions` | supervisor | `team_id` |  | list[[TeamAction](#teamaction)] |  |
| `GET` | `/teams/{team_id}/playbook` | supervisor | `team_id` |  | list[[TeamPlay](#teamplay)] | The changes a supervisor can start; their own is also possible (play "custom"). |
| `POST` | `/teams/{team_id}/actions` | supervisor | `team_id` | [TeamActionIn](#teamactionin) | 201: [TeamActionDecision](#teamactiondecision) | A change the supervisor starts: approved as made, and every member is told. |
| `POST` | `/teams/{team_id}/actions/{action_id}/{decision}` | supervisor | `team_id`, `action_id`, `decision` |  | [TeamActionDecision](#teamactiondecision) |  |
| `POST` | `/teams/preview` | approved |  | [TeamCode](#teamcode) | [TeamPreview](#teampreview) | What joining the team means, for the person to read before agreeing. |
| `POST` | `/teams/join` | approved |  | [JoinTeam](#jointeam) | 201: [Membership](#membership) |  |
| `GET` | `/me/teams` | approved |  |  | list[[Membership](#membership)] |  |
| `POST` | `/me/teams/{team_id}/levels` | approved | `team_id` | [ShareLevels](#sharelevels) | [Membership](#membership) | Turns on or off showing one's own named weekly levels to the supervisor. |
| `POST` | `/me/teams/{team_id}/leave` | approved | `team_id` |  | 204, no body |  |

### harness

| Method | Path | Access | Parameters | Body | Returns | Notes |
|---|---|---|---|---|---|---|
| `POST` | `/me/tokens` | approved |  | [NewToken](#newtoken) | 201: [MadeToken](#madetoken) |  |
| `GET` | `/me/tokens` | approved |  |  | list[[TokenOut](#tokenout)] |  |
| `DELETE` | `/me/tokens/{token_id}` | approved | `token_id` |  | 204, no body |  |
| `GET` | `/me/harness` | approved |  |  | list[[SubmissionOut](#submissionout)] | What a harness sent that waits for this person's approval. |
| `POST` | `/me/harness/{submission_id}/approve` | approved | `submission_id` |  | [SubmissionOut](#submissionout) |  |
| `POST` | `/me/harness/{submission_id}/decline` | approved | `submission_id` |  | [SubmissionOut](#submissionout) |  |

## Error codes

Raised in the code with a fixed status and code (the message varies by case).

| Status | Code |
|---|---|
| 400 | `invite_invalid` |
| 400 | `invite_other_email` |
| 401 | `invalid_credentials` |
| 401 | `signed_out` |
| 403 | `forbidden` |
| 403 | `not_approved` |
| 403 | `not_supervisor` |
| 403 | `write_scope_needed` |
| 404 | `no_data` |
| 404 | `not_found` |
| 404 | `unknown_code` |
| 404 | `unknown_metric` |
| 409 | `already_decided` |
| 409 | `already_member` |
| 409 | `already_sent` |
| 409 | `busy` |
| 409 | `consent_changed` |
| 409 | `duplicate_log` |
| 409 | `email_taken` |
| 409 | `not_changeable` |
| 409 | `not_connected` |
| 409 | `not_hr` |
| 409 | `not_in_team` |
| 409 | `not_logged` |
| 409 | `not_supervisor` |
| 409 | `own_team` |
| 409 | `paused` |
| 409 | `reconnect_needed` |
| 409 | `request_conflict` |
| 409 | `stale_action` |
| 409 | `too_many_tokens` |
| 409 | `version_conflict` |
| 409 | `week_not_over` |
| 422 | `bad_change` |
| 422 | `bad_start` |
| 422 | `in_the_past` |
| 422 | `invalid_checkin` |
| 422 | `invalid_email` |
| 422 | `invalid_log` |
| 422 | `invalid_pulse` |
| 422 | `invalid_reminder` |
| 422 | `invalid_request` |
| 422 | `invalid_timezone` |
| 422 | `unsafe_change` |
| 422 | `unsafe_note` |
| 422 | `weak_password` |
| 429 | `app_daily_limit` |
| 429 | `daily_limit` |
| 429 | `too_many_attempts` |
| 502 | `email_failed` |
| 503 | `agent_unavailable` |
| 503 | `google_unavailable` |
| 503 | `writes_disabled` |
| 504 | `still_answering` |

## Schemas

Field names are as sent on the wire (camelCase where the app expects it).
A field not marked required may be left out.

### AccessRequest

| Field | Type | Required | Limits |
|---|---|---|---|
| `id` | string | yes |  |
| `email` | string | yes |  |
| `requestedAt` | string (date-time) | yes |  |

### Account

| Field | Type | Required | Limits |
|---|---|---|---|
| `email` | string | yes |  |
| `status` | `pending` \| `approved` \| `rejected` | yes |  |
| `isAdmin` | boolean | yes |  |
| `role` | `member` \| `supervisor` \| `hr` |  | default `member` |
| `personalFeatures` | boolean |  | default `False` |

### Action

| Field | Type | Required | Limits |
|---|---|---|---|
| `id` | string | yes |  |
| `version` | integer | yes |  |
| `status` | `draft` \| `executing` \| `succeeded` \| `failed` \| `unknown` \| `cancelled` \| `undoing` \| `undone` | yes |  |
| `log` | any | yes |  |
| `error` | string or null | yes |  |
| `pendingOperation` | `create` \| `delete` or null | yes |  |
| `createdAt` | string | yes |  |
| `updatedAt` | string | yes |  |

### AlarmOut

| Field | Type | Required | Limits |
|---|---|---|---|
| `id` | string | yes |  |
| `kind` | `day` \| `streak` \| `finding` \| `data` | yes |  |
| `metric` | string or null | yes |  |
| `day` | string (date) | yes |  |
| `title` | string | yes |  |
| `body` | string | yes |  |
| `link` | string | yes |  |
| `evidenceIds` | list[string] | yes |  |
| `status` | `pending` \| `sent` \| `suppressed` \| `expired` | yes |  |
| `reason` | string or null | yes |  |
| `feedback` | `useful` \| `not_useful` or null | yes |  |
| `createdAt` | string (date-time) | yes |  |
| `sentAt` | string (date-time) or null | yes |  |

### AlarmSettings

| Field | Type | Required | Limits |
|---|---|---|---|
| `enabled` | boolean | yes |  |
| `mutedKinds` | list[`day` \| `streak` \| `finding` \| `data`] |  |  |
| `sensitivity` | `fewer` \| `normal` \| `more` | yes |  |

### Approval

| Field | Type | Required | Limits |
|---|---|---|---|
| `role` | `member` \| `supervisor` \| `hr` |  | default `member` |

### AttachmentIn

| Field | Type | Required | Limits |
|---|---|---|---|
| `kind` | `finding` \| `metric` | yes |  |
| `id` | string or null |  |  |
| `metric` | string or null |  |  |

### Body_sync_now_google_sync_post

| Field | Type | Required | Limits |
|---|---|---|---|
| `force` | boolean |  | default `False` |

### BriefingItem

| Field | Type | Required | Limits |
|---|---|---|---|
| `evidenceIds` | list[string] |  |  |
| `text` | string | yes |  |
| `kind` | string | yes |  |
| `metric` | string or null |  |  |

### CalendarDay

| Field | Type | Required | Limits |
|---|---|---|---|
| `date` | string (date) | yes |  |
| `meetingMinutes` | number | yes |  |
| `meetings` | number | yes |  |
| `afterHoursMinutes` | number | yes |  |
| `backToBack` | number | yes |  |
| `focusMinutes` | number | yes |  |
| `outOfOffice` | number | yes |  |

### CalendarStatus

| Field | Type | Required | Limits |
|---|---|---|---|
| `connected` | boolean | yes |  |
| `lastSync` | string (date-time) or null | yes |  |
| `lastError` | string or null | yes |  |
| `days` | integer | yes |  |

### ChangeResult

How the team's metric went during an ended change, against the 28 days before it.

| Field | Type | Required | Limits |
|---|---|---|---|
| `verdict` | `better` \| `worse` \| `changed` \| `no_change` \| `unclear` | yes |  |
| `text` | string | yes |  |
| `evidence` | [Evidence](#evidence) | yes |  |

### ChatMessage

| Field | Type | Required | Limits |
|---|---|---|---|
| `id` | string | yes |  |
| `role` | `user` \| `assistant` | yes |  |
| `text` | string | yes |  |
| `sources` | list[[SourceLink](#sourcelink)] or null |  |  |
| `evidenceIds` | list[string] | yes |  |
| `actionIds` | list[string] or null |  |  |
| `reminderIds` | list[string] or null |  |  |
| `attachment` | object or null |  |  |
| `answeredBy` | string or null |  |  |
| `routed` | boolean or null |  |  |
| `consulted` | list[string] or null |  |  |
| `refused` | boolean or null |  |  |
| `conversationId` | string or null |  |  |
| `rating` | `up` \| `down` or null |  |  |
| `createdAt` | string (date-time) | yes |  |

### CheckIn

| Field | Type | Required | Limits |
|---|---|---|---|
| `day` | string (date) | yes |  |
| `rating` | integer | yes | ≥ 1.0, ≤ 5.0 |
| `tags` | list[string] |  | default `[]` |

### CheckinEvidence

One signal behind a person's own check-in alert; shown to that person only.

| Field | Type | Required | Limits |
|---|---|---|---|
| `id` | string | yes |  |
| `metric` | string | yes |  |
| `direction` | `up` \| `down` | yes |  |
| `usualLow` | number | yes |  |
| `usualHigh` | number | yes |  |
| `margin` | number | yes |  |
| `daysFar` | integer | yes |  |
| `daysWorn` | integer | yes |  |
| `recentMean` | number | yes |  |
| `usual` | [Window](#window) | yes |  |
| `recent` | [Window](#window) | yes |  |

### CheckinMark

| Field | Type | Required | Limits |
|---|---|---|---|
| `role` | `hr` \| `supervisor` | yes |  |
| `outcome` | `checked_in` \| `not_needed` or null | yes |  |
| `markedAt` | string (date-time) or null | yes |  |

### ConnectOptions

| Field | Type | Required | Limits |
|---|---|---|---|
| `capability` | `food_logging` \| `workout_logging` \| `calendar` | yes |  |

### ConnectStart

| Field | Type | Required | Limits |
|---|---|---|---|
| `url` | string | yes |  |

### ContextQuestion

| Field | Type | Required | Limits |
|---|---|---|---|
| `id` | string | yes |  |
| `prompt` | string | yes |  |
| `date` | string (date) | yes |  |
| `options` | list[string] | yes |  |
| `answer` | string or null | yes |  |

### Conversation

| Field | Type | Required | Limits |
|---|---|---|---|
| `id` | string | yes |  |
| `title` | string | yes |  |
| `pinned` | boolean | yes |  |
| `messages` | integer | yes |  |
| `createdAt` | string (date-time) | yes |  |
| `updatedAt` | string (date-time) | yes |  |

### ConversationUpdate

| Field | Type | Required | Limits |
|---|---|---|---|
| `title` | string or null |  |  |
| `pinned` | boolean or null |  |  |

### Credentials

| Field | Type | Required | Limits |
|---|---|---|---|
| `email` | string | yes | max length 1000 |
| `password` | string | yes | max length 1000 |
| `hrInvite` | string or null |  |  |

### DataStatus

| Field | Type | Required | Limits |
|---|---|---|---|
| `source` | `takeout` \| `google_health` \| `none` | yes |  |
| `lastSync` | string (date-time) or null | yes |  |
| `range` | [Window](#window) or null | yes |  |
| `coverage` | list[[MetricCoverage](#metriccoverage)] | yes |  |
| `lowWearDays` | list[string (date)] | yes |  |

### Day

| Field | Type | Required | Limits |
|---|---|---|---|
| `date` | string (date) | yes |  |
| `partial` | boolean | yes |  |
| `lowWear` | boolean | yes |  |
| `first` | string (date) | yes |  |
| `last` | string (date) | yes |  |
| `metrics` | list[[DayMetric](#daymetric)] | yes |  |
| `recovery` | [Recovery](#recovery) or null |  |  |
| `strain` | [Strain](#strain) or null |  |  |
| `stress` | [Stress](#stress) or null |  |  |

### DayMetric

| Field | Type | Required | Limits |
|---|---|---|---|
| `metric` | string | yes |  |
| `value` | number or null | yes |  |
| `usual` | [Usual](#usual) or null | yes |  |
| `recent` | list[number or null] | yes |  |

### DayWorkouts

| Field | Type | Required | Limits |
|---|---|---|---|
| `available` | boolean | yes |  |
| `workouts` | list[[Workout](#workout)] | yes |  |

### Decision

| Field | Type | Required | Limits |
|---|---|---|---|
| `keep` | boolean | yes |  |

### EpisodeOut

| Field | Type | Required | Limits |
|---|---|---|---|
| `id` | string | yes |  |
| `day` | string (date) | yes |  |
| `text` | string | yes |  |

### Evidence

| Field | Type | Required | Limits |
|---|---|---|---|
| `id` | string | yes |  |
| `tool` | string | yes |  |
| `metrics` | list[string] | yes |  |
| `windows` | list[[Window](#window)] | yes |  |
| `n` | integer | yes |  |
| `sufficient` | boolean | yes |  |
| `stats` | object | yes |  |

### FactOut

| Field | Type | Required | Limits |
|---|---|---|---|
| `id` | string | yes |  |
| `kind` | string | yes |  |
| `text` | string | yes |  |
| `status` | string | yes |  |
| `action` | `keep` \| `forget` |  | default `keep` |
| `forgets` | string or null |  |  |
| `start` | string (date) or null | yes |  |
| `end` | string (date) or null | yes |  |
| `createdAt` | string (date-time) | yes |  |

### Feedback

| Field | Type | Required | Limits |
|---|---|---|---|
| `useful` | boolean | yes |  |

### FeedbackIn

| Field | Type | Required | Limits |
|---|---|---|---|
| `kind` | `report` \| `feedback` | yes |  |
| `text` | string | yes | min length 1, max length 2000 |
| `conversationId` | string (uuid) or null |  |  |
| `messageId` | string (uuid) or null |  |  |

### FeedbackOut

| Field | Type | Required | Limits |
|---|---|---|---|
| `id` | string (uuid) | yes |  |
| `kind` | string | yes |  |
| `text` | string | yes |  |
| `createdAt` | string (date-time) | yes |  |
| `quoted` | string or null |  |  |

### FeedbackRow

The admin's view: who wrote it, so the team can follow up.

| Field | Type | Required | Limits |
|---|---|---|---|
| `id` | string (uuid) | yes |  |
| `kind` | string | yes |  |
| `text` | string | yes |  |
| `createdAt` | string (date-time) | yes |  |
| `quoted` | string or null |  |  |
| `email` | string | yes |  |

### Finding

| Field | Type | Required | Limits |
|---|---|---|---|
| `id` | string | yes |  |
| `title` | string | yes |  |
| `summary` | string | yes |  |
| `metric` | string | yes |  |
| `unit` | string | yes |  |
| `direction` | `up` \| `down` \| `none` | yes |  |
| `change` | string | yes |  |
| `series` | list[[Point](#point)] | yes |  |
| `highlight` | [Window](#window) or null | yes |  |
| `evidenceIds` | list[string] | yes |  |

### FoodLog

| Field | Type | Required | Limits |
|---|---|---|---|
| `kind` | `food` |  | default `food` |
| `foodName` | string | yes | min length 1, max length 160 |
| `consumedAt` | string (date-time) | yes |  |
| `mealType` | `BREAKFAST` \| `LUNCH` \| `DINNER` \| `SNACK` | yes |  |
| `energyKcal` | number or null |  |  |
| `proteinG` | number or null |  |  |
| `carbohydrateG` | number or null |  |  |
| `fatG` | number or null |  |  |
| `provenance` | `user_entered` \| `estimated` |  | default `user_entered` |
| `estimateSource` | string or null |  |  |

### GenerateReport

| Field | Type | Required | Limits |
|---|---|---|---|
| `week` | string (date) or null |  |  |

### GoogleStatus

| Field | Type | Required | Limits |
|---|---|---|---|
| `status` | `none` \| `active` \| `reconnect_needed` | yes |  |
| `syncing` | boolean | yes |  |
| `lastSync` | string (date-time) or null | yes |  |
| `lastError` | string or null | yes |  |
| `missingScopes` | list[string] | yes |  |

### HourlySteps

| Field | Type | Required | Limits |
|---|---|---|---|
| `available` | boolean | yes |  |
| `steps` | list[integer or null] | yes |  |

### Inbox

| Field | Type | Required | Limits |
|---|---|---|---|
| `items` | list[[NotificationOut](#notificationout)] | yes |  |
| `unread` | integer | yes |  |

### InterestOut

| Field | Type | Required | Limits |
|---|---|---|---|
| `topic` | string | yes |  |
| `label` | string | yes |  |

### JoinTeam

| Field | Type | Required | Limits |
|---|---|---|---|
| `code` | string | yes | min length 1, max length 32 |
| `consentVersion` | string | yes |  |

### MadeToken

| Field | Type | Required | Limits |
|---|---|---|---|
| `id` | string | yes |  |
| `name` | string | yes |  |
| `createdAt` | string (date-time) | yes |  |
| `lastUsedAt` | string (date-time) or null | yes |  |
| `revokedAt` | string (date-time) or null | yes |  |
| `token` | string | yes |  |

### MarkCheckin

| Field | Type | Required | Limits |
|---|---|---|---|
| `outcome` | `checked_in` \| `not_needed` | yes |  |
| `note` | string or null |  |  |

### Measured

What the tracker recorded during the workout. Only the server fills this in.

| Field | Type | Required | Limits |
|---|---|---|---|
| `status` | `measured` \| `no_data` \| `unavailable` | yes |  |
| `steps` | integer or null |  |  |
| `distanceKm` | number or null |  |  |
| `caloriesKcal` | number or null |  |  |
| `averageHeartRate` | integer or null |  |  |
| `zoneSeconds` | [ZoneSeconds](#zoneseconds) or null |  |  |
| `activeZoneMinutes` | integer or null |  |  |
| `swimLengths` | integer or null |  |  |
| `overlaps` | list[[Overlap](#overlap)] |  | max items 20 |

### Membership

| Field | Type | Required | Limits |
|---|---|---|---|
| `teamId` | string | yes |  |
| `team` | string | yes |  |
| `supervisor` | string | yes |  |
| `joinedAt` | string (date-time) | yes |  |
| `shareLevels` | boolean | yes |  |
| `levelsConsent` | string | yes |  |
| `levelsConsentVersion` | string | yes |  |
| `checkinAlerts` | boolean |  | default `False` |
| `checkinConsent` | string |  | default `` |
| `checkinConsentVersion` | string |  | default `` |

### MemoryOut

| Field | Type | Required | Limits |
|---|---|---|---|
| `waiting` | list[[FactOut](#factout)] | yes |  |
| `kept` | list[[FactOut](#factout)] | yes |  |
| `noticed` | list[[FactOut](#factout)] | yes |  |
| `interests` | list[[InterestOut](#interestout)] | yes |  |
| `episodes` | list[[EpisodeOut](#episodeout)] | yes |  |

### MetricCoverage

| Field | Type | Required | Limits |
|---|---|---|---|
| `metric` | string | yes |  |
| `label` | string | yes |  |
| `fractionPresent` | number | yes |  |

### MetricSeries

| Field | Type | Required | Limits |
|---|---|---|---|
| `metric` | string | yes |  |
| `points` | list[[Point](#point)] | yes |  |
| `usual` | [Usual](#usual) or null | yes |  |

### NarrativeParagraph

| Field | Type | Required | Limits |
|---|---|---|---|
| `text` | string | yes |  |
| `kind` | `change` \| `no_change` \| `pattern` | yes |  |
| `metric` | string | yes |  |
| `evidenceIds` | list[string] | yes |  |

### NewDraft

| Field | Type | Required | Limits |
|---|---|---|---|
| `requestKey` | string (uuid) | yes |  |
| `log` | any | yes |  |

### NewReminder

| Field | Type | Required | Limits |
|---|---|---|---|
| `title` | string | yes | min length 1, max length 80 |
| `message` | string |  | max length 280, default `` |
| `schedule` | any | yes |  |
| `channels` | list[`email` \| `in_app`] |  | min items 1 |

### NewTeam

| Field | Type | Required | Limits |
|---|---|---|---|
| `name` | string | yes | min length 1, max length 80 |
| `reportEmail` | string or null |  |  |

### NewToken

| Field | Type | Required | Limits |
|---|---|---|---|
| `name` | string | yes | min length 1, max length 60 |

### NightStages

The night ending on a day, stage by stage, as the tracker scored it.

| Field | Type | Required | Limits |
|---|---|---|---|
| `available` | boolean | yes |  |
| `start` | string (date-time) or null |  |  |
| `end` | string (date-time) or null |  |  |
| `staged` | boolean |  | default `False` |
| `stages` | list[[SleepStage](#sleepstage)] |  | default `[]` |

### NotificationOut

| Field | Type | Required | Limits |
|---|---|---|---|
| `id` | string | yes |  |
| `kind` | string | yes |  |
| `title` | string | yes |  |
| `body` | string | yes |  |
| `link` | string or null | yes |  |
| `alarmId` | string or null | yes |  |
| `alarmFeedback` | string or null | yes |  |
| `factId` | string or null | yes |  |
| `createdAt` | string (date-time) | yes |  |
| `readAt` | string (date-time) or null | yes |  |

### NotificationSettings

| Field | Type | Required | Limits |
|---|---|---|---|
| `quietHours` | [QuietHours](#quiethours) or null | yes |  |
| `maxPerDay` | integer | yes | ≥ 1.0, ≤ 10.0 |
| `email` | boolean | yes |  |

### Once

| Field | Type | Required | Limits |
|---|---|---|---|
| `kind` | `once` | yes |  |
| `date` | string (date) | yes |  |
| `time` | string (time) | yes |  |

### Opened

| Field | Type | Required | Limits |
|---|---|---|---|
| `topic` | string | yes | min length 1, max length 64 |

### Overlap

An exercise already recorded over part of the workout, by the tracker or another app.

| Field | Type | Required | Limits |
|---|---|---|---|
| `exerciseType` | string | yes |  |
| `startTime` | string (date-time) | yes |  |
| `endTime` | string (date-time) | yes |  |

### OwnCheckin

| Field | Type | Required | Limits |
|---|---|---|---|
| `id` | string | yes |  |
| `teamId` | string | yes |  |
| `team` | string | yes |  |
| `status` | `waiting` \| `withdrawn` \| `sent` | yes |  |
| `raisedAt` | string (date-time) | yes |  |
| `sendAfter` | string (date-time) | yes |  |
| `sentAt` | string (date-time) or null | yes |  |
| `withdrawnAt` | string (date-time) or null | yes |  |
| `recipients` | string | yes |  |
| `evidence` | list[[CheckinEvidence](#checkinevidence)] | yes |  |

### Point

| Field | Type | Required | Limits |
|---|---|---|---|
| `date` | string (date) | yes |  |
| `value` | number or null | yes |  |

### PulseAnswer

| Field | Type | Required | Limits |
|---|---|---|---|
| `rating` | integer | yes | ≥ 1.0, ≤ 5.0 |

### PulseToday

The nightly team question for the signed-in person.

| Field | Type | Required | Limits |
|---|---|---|---|
| `asked` | boolean | yes |  |
| `day` | string (date) | yes |  |
| `question` | string | yes |  |
| `scale` | list[string] | yes |  |
| `rating` | integer or null |  |  |

### PulseWeek

| Field | Type | Required | Limits |
|---|---|---|---|
| `start` | string (date) | yes |  |
| `end` | string (date) | yes |  |
| `respondents` | integer | yes |  |
| `mean` | number or null |  |  |

### Question

| Field | Type | Required | Limits |
|---|---|---|---|
| `text` | string | yes | min length 1, max length 2000 |
| `expert` | `auto` \| `sleep` \| `recovery` \| `activity` \| `nutrition` |  | default `auto` |
| `depth` | `quick` \| `deep` |  | default `quick` |
| `attachment` | [AttachmentIn](#attachmentin) or null |  |  |
| `conversationId` | string (uuid) or null |  |  |
| `replaces` | string (uuid) or null |  |  |

### QuietHours

| Field | Type | Required | Limits |
|---|---|---|---|
| `start` | string | yes |  |
| `end` | string | yes |  |

### RatingIn

Thumbs up or down on an answer; null takes it back.

| Field | Type | Required | Limits |
|---|---|---|---|
| `rating` | `up` \| `down` or null | yes |  |

### ReceivedCheckin

A sent alert as HR or the supervisor sees it: who, which team, when; never why.

| Field | Type | Required | Limits |
|---|---|---|---|
| `id` | string | yes |  |
| `person` | string | yes |  |
| `team` | string | yes |  |
| `sentAt` | string (date-time) | yes |  |
| `mine` | [CheckinMark](#checkinmark) | yes |  |
| `others` | list[[CheckinMark](#checkinmark)] | yes |  |
| `note` | string or null | yes |  |

### Recovery

| Field | Type | Required | Limits |
|---|---|---|---|
| `score` | number | yes |  |
| `parts` | map[string, number] | yes |  |

### ReminderChange

| Field | Type | Required | Limits |
|---|---|---|---|
| `version` | integer | yes | ≥ 1.0 |
| `status` | `active` \| `paused` \| `declined` or null |  |  |
| `title` | string or null |  |  |
| `message` | string or null |  |  |
| `schedule` | any or null |  |  |
| `channels` | list[`email` \| `in_app`] or null |  |  |

### ReminderOut

| Field | Type | Required | Limits |
|---|---|---|---|
| `id` | string | yes |  |
| `title` | string | yes |  |
| `message` | string | yes |  |
| `schedule` | any | yes |  |
| `scheduleText` | string | yes |  |
| `timezone` | string | yes |  |
| `channels` | list[`email` \| `in_app`] | yes |  |
| `status` | `proposed` \| `active` \| `paused` \| `declined` \| `done` | yes |  |
| `source` | `person` \| `agent` | yes |  |
| `reason` | string or null | yes |  |
| `evidenceId` | string or null | yes |  |
| `nextDueAt` | string (date-time) or null | yes |  |
| `version` | integer | yes |  |
| `createdAt` | string (date-time) | yes |  |

### Report

| Field | Type | Required | Limits |
|---|---|---|---|
| `id` | string | yes |  |
| `period` | [Window](#window) | yes |  |
| `createdAt` | string (date-time) | yes |  |
| `headline` | string | yes |  |
| `findings` | list[[Finding](#finding)] | yes |  |
| `questions` | list[[ContextQuestion](#contextquestion)] | yes |  |
| `evidence` | map[string, [Evidence](#evidence)] | yes |  |

### ReportFinding

What the week's report leads with: a worthwhile team change, in reading order.

| Field | Type | Required | Limits |
|---|---|---|---|
| `metric` | string | yes |  |
| `label` | string | yes |  |
| `kind` | `concern` \| `improvement` \| `change` | yes |  |
| `status` | `lasting` \| `new` | yes |  |
| `text` | string | yes |  |
| `evidenceId` | string | yes |  |

### ReportSection

| Field | Type | Required | Limits |
|---|---|---|---|
| `metric` | string | yes |  |
| `label` | string or null |  |  |
| `status` | `changed` \| `steady` \| `not_enough_data` or null |  |  |
| `text` | string | yes |  |
| `evidenceId` | string | yes |  |

### RevisedDraft

| Field | Type | Required | Limits |
|---|---|---|---|
| `version` | integer | yes | ≥ 1.0 |
| `log` | any | yes |  |

### ShareCheckin

| Field | Type | Required | Limits |
|---|---|---|---|
| `share` | boolean | yes |  |
| `consentVersion` | string or null |  |  |

### ShareLevels

| Field | Type | Required | Limits |
|---|---|---|---|
| `share` | boolean | yes |  |
| `consentVersion` | string or null |  |  |

### SharedLevels

One member who chose to share, with their week against their own usual.

| Field | Type | Required | Limits |
|---|---|---|---|
| `member` | string | yes |  |
| `levels` | map[string, [TeamWeekLevel](#teamweeklevel)] | yes |  |

### SignedIn

| Field | Type | Required | Limits |
|---|---|---|---|
| `token` | string | yes |  |
| `account` | [Account](#account) | yes |  |

### SleepStage

| Field | Type | Required | Limits |
|---|---|---|---|
| `start` | string (date-time) | yes |  |
| `end` | string (date-time) | yes |  |
| `stage` | `awake` \| `light` \| `deep` \| `rem` \| `asleep` \| `restless` | yes |  |

### SourceLink

| Field | Type | Required | Limits |
|---|---|---|---|
| `title` | string | yes |  |
| `source` | string | yes |  |
| `url` | string | yes |  |

### Strain

| Field | Type | Required | Limits |
|---|---|---|---|
| `score` | number | yes |  |
| `band` | `light` \| `moderate` \| `high` \| `all_out` | yes |  |
| `load` | number | yes |  |
| `method` | `zones` \| `active_zone_minutes` | yes |  |

### Stress

| Field | Type | Required | Limits |
|---|---|---|---|
| `score` | number | yes |  |
| `parts` | map[string, number] | yes |  |

### SubmissionOut

| Field | Type | Required | Limits |
|---|---|---|---|
| `id` | string | yes |  |
| `kind` | `calendar_days` \| `team_event` | yes |  |
| `status` | `pending` \| `approved` \| `declined` | yes |  |
| `payload` | object | yes |  |
| `teamId` | string or null | yes |  |
| `createdAt` | string (date-time) | yes |  |

### Team

| Field | Type | Required | Limits |
|---|---|---|---|
| `id` | string | yes |  |
| `name` | string | yes |  |
| `inviteCode` | string | yes |  |
| `members` | integer | yes |  |
| `minimumMembers` | integer | yes |  |
| `reportEmail` | string or null | yes |  |
| `hrEmail` | string or null |  |  |
| `hrInvited` | string or null |  |  |
| `paused` | string or null |  |  |
| `createdAt` | string (date-time) | yes |  |

### TeamAction

| Field | Type | Required | Limits |
|---|---|---|---|
| `id` | string | yes |  |
| `kind` | `challenge` \| `message` | yes |  |
| `title` | string | yes |  |
| `body` | string | yes |  |
| `metric` | string or null |  |  |
| `startsOn` | string (date) or null |  |  |
| `endsOn` | string (date) or null |  |  |
| `status` | `proposed` \| `approved` \| `declined` | yes |  |
| `source` | `agent` \| `supervisor` |  | default `agent` |
| `play` | string or null |  |  |
| `result` | [ChangeResult](#changeresult) or null |  |  |
| `proposedAt` | string (date-time) | yes |  |
| `decidedAt` | string (date-time) or null |  |  |

### TeamActionDecision

| Field | Type | Required | Limits |
|---|---|---|---|
| `membersTold` | integer | yes |  |
| `action` | [TeamAction](#teamaction) | yes |  |

### TeamActionIn

A change the supervisor plans: one from the playbook, or their own ("custom").

| Field | Type | Required | Limits |
|---|---|---|---|
| `play` | string | yes | min length 1, max length 32 |
| `title` | string or null |  |  |
| `body` | string or null |  |  |
| `metric` | string or null |  |  |
| `startsOn` | string (date) or null |  |  |
| `days` | integer or null |  |  |

### TeamAlert

| Field | Type | Required | Limits |
|---|---|---|---|
| `id` | string | yes |  |
| `metric` | string | yes |  |
| `label` | string | yes |  |
| `direction` | `up` \| `down` | yes |  |
| `kind` | `concern` \| `improvement` \| `change` |  | default `change` |
| `text` | string | yes |  |
| `raisedAt` | string (date-time) | yes |  |
| `resolvedAt` | string (date-time) or null |  |  |

### TeamBriefing

Weekly highlights and upcoming event warnings, each linked to the report evidence.

| Field | Type | Required | Limits |
|---|---|---|---|
| `summary` | string | yes |  |
| `items` | list[[BriefingItem](#briefingitem)] | yes |  |
| `proposals` | integer |  | default `0` |
| `madeAt` | string (date-time) | yes |  |

### TeamCalendar

| Field | Type | Required | Limits |
|---|---|---|---|
| `week` | [Window](#window) | yes |  |
| `connected` | integer | yes |  |
| `minimumMembers` | integer | yes |  |
| `metrics` | list[[TeamCalendarMetric](#teamcalendarmetric)] | yes |  |
| `generatedAt` | string (date-time) | yes |  |

### TeamCalendarMetric

| Field | Type | Required | Limits |
|---|---|---|---|
| `metric` | string | yes |  |
| `label` | string | yes |  |
| `unit` | `min` \| `count` | yes |  |
| `members` | integer | yes |  |
| `sufficient` | boolean | yes |  |
| `medianWeek` | number or null |  |  |
| `q1Week` | number or null |  |  |
| `q3Week` | number or null |  |  |
| `medianChange` | number or null |  |  |
| `membersUp` | integer or null |  |  |
| `membersDown` | integer or null |  |  |
| `medianPlanned` | number or null |  |  |
| `evidenceId` | string | yes |  |

### TeamChatMessage

| Field | Type | Required | Limits |
|---|---|---|---|
| `id` | string | yes |  |
| `role` | `supervisor` \| `agent` | yes |  |
| `text` | string | yes |  |
| `evidence` | list[[Evidence](#evidence)] |  |  |
| `rating` | `up` \| `down` or null |  |  |
| `createdAt` | string (date-time) | yes |  |

### TeamCode

| Field | Type | Required | Limits |
|---|---|---|---|
| `code` | string | yes | min length 1, max length 32 |

### TeamHr

| Field | Type | Required | Limits |
|---|---|---|---|
| `email` | string or null | yes |  |
| `invited` | boolean |  | default `False` |

### TeamNote

| Field | Type | Required | Limits |
|---|---|---|---|
| `id` | string | yes |  |
| `text` | string | yes |  |
| `startsOn` | string (date) or null |  |  |
| `endsOn` | string (date) or null |  |  |
| `createdAt` | string (date-time) | yes |  |

### TeamNoteIn

| Field | Type | Required | Limits |
|---|---|---|---|
| `text` | string | yes | min length 1, max length 300 |
| `startsOn` | string (date) or null |  |  |
| `endsOn` | string (date) or null |  |  |

### TeamObserved

| Field | Type | Required | Limits |
|---|---|---|---|
| `figures` | list[[TeamObservedFigure](#teamobservedfigure)] | yes |  |
| `minimumMembers` | integer | yes |  |

### TeamObservedFigure

What the team's latest night or day looked like; never a change from usual.

| Field | Type | Required | Limits |
|---|---|---|---|
| `metric` | string | yes |  |
| `day` | string (date) | yes |  |
| `median` | number | yes |  |
| `members` | integer | yes |  |
| `text` | string | yes |  |
| `evidenceId` | string | yes |  |

### TeamPlay

| Field | Type | Required | Limits |
|---|---|---|---|
| `id` | string | yes |  |
| `title` | string | yes |  |
| `body` | string | yes |  |
| `metrics` | list[string] | yes |  |
| `days` | integer | yes |  |

### TeamPreview

What joining means, shown before the person agrees.

| Field | Type | Required | Limits |
|---|---|---|---|
| `team` | string | yes |  |
| `supervisor` | string | yes |  |
| `consent` | string | yes |  |
| `consentVersion` | string | yes |  |

### TeamPulse

| Field | Type | Required | Limits |
|---|---|---|---|
| `question` | string | yes |  |
| `minimum` | integer | yes |  |
| `weeks` | list[[PulseWeek](#pulseweek)] | yes |  |

### TeamReport

| Field | Type | Required | Limits |
|---|---|---|---|
| `week` | [Window](#window) | yes |  |
| `status` | `ready` \| `withheld` | yes |  |
| `headline` | string | yes |  |
| `membersIncluded` | integer | yes |  |
| `createdAt` | string (date-time) | yes |  |
| `membersTotal` | integer | yes |  |
| `minimumMembers` | integer | yes |  |
| `sections` | list[[ReportSection](#reportsection)] | yes |  |
| `weekdays` | list[[ReportSection](#reportsection)] | yes |  |
| `priorities` | list[[ReportFinding](#reportfinding)] |  |  |
| `alerts` | list[string] |  |  |
| `challenges` | list[[ReportSection](#reportsection)] |  |  |
| `narrative` | list[[NarrativeParagraph](#narrativeparagraph)] | yes |  |
| `evidence` | map[string, [Evidence](#evidence)] | yes |  |
| `generatedBy` | `template` \| `model` | yes |  |
| `levels` | list[[SharedLevels](#sharedlevels)] | yes |  |
| `briefing` | [TeamBriefing](#teambriefing) or null |  |  |

### TeamReportSummary

| Field | Type | Required | Limits |
|---|---|---|---|
| `week` | [Window](#window) | yes |  |
| `status` | `ready` \| `withheld` | yes |  |
| `headline` | string | yes |  |
| `membersIncluded` | integer | yes |  |
| `createdAt` | string (date-time) | yes |  |

### TeamWeekLevel

| Field | Type | Required | Limits |
|---|---|---|---|
| `mean` | number or null | yes |  |
| `level` | `below` \| `usual` \| `above` or null | yes |  |

### TimeZone

| Field | Type | Required | Limits |
|---|---|---|---|
| `timezone` | string | yes | min length 1, max length 64 |

### TokenOut

| Field | Type | Required | Limits |
|---|---|---|---|
| `id` | string | yes |  |
| `name` | string | yes |  |
| `createdAt` | string (date-time) | yes |  |
| `lastUsedAt` | string (date-time) or null | yes |  |
| `revokedAt` | string (date-time) or null | yes |  |

### Usual

| Field | Type | Required | Limits |
|---|---|---|---|
| `median` | number | yes |  |
| `low` | number | yes |  |
| `high` | number | yes |  |
| `days` | integer | yes |  |

### Version

| Field | Type | Required | Limits |
|---|---|---|---|
| `version` | integer | yes | ≥ 1.0 |

### Weekly

| Field | Type | Required | Limits |
|---|---|---|---|
| `kind` | `weekly` | yes |  |
| `time` | string (time) | yes |  |
| `weekdays` | list[integer] | yes | min items 1, max items 7 |

### Window

| Field | Type | Required | Limits |
|---|---|---|---|
| `start` | string (date) | yes |  |
| `end` | string (date) | yes |  |

### Wording

| Field | Type | Required | Limits |
|---|---|---|---|
| `text` | string | yes | min length 1, max length 120 |

### Workout

| Field | Type | Required | Limits |
|---|---|---|---|
| `id` | string | yes |  |
| `exerciseType` | string | yes |  |
| `name` | string | yes |  |
| `start` | string (date-time) | yes |  |
| `end` | string (date-time) | yes |  |
| `activeSeconds` | integer or null | yes |  |
| `steps` | integer or null |  |  |
| `distanceKm` | number or null |  |  |
| `caloriesKcal` | number or null |  |  |
| `averageHeartRate` | integer or null |  |  |
| `activeZoneMinutes` | integer or null |  |  |
| `zoneSeconds` | map[string, number] or null |  |  |
| `source` | string or null |  |  |

### WorkoutLog

| Field | Type | Required | Limits |
|---|---|---|---|
| `kind` | `workout` |  | default `workout` |
| `exerciseType` | `AEROBIC_WORKOUT` \| `ARCHERY` \| `ASSAULT_BIKE` \| `BACKPACKING` \| `BADMINTON` \| `BALLET` \| `BALLROOM_DANCE` \| `BARRE_CLASS` \| `BASEBALL` \| `BASKETBALL` \| `BIKING` \| `BILLIARDS` \| `BODY_WEIGHT` \| `BOOTCAMP` \| `BOWLING` \| `BOXING` \| `BREAKDANCING` \| `CALISTHENICS` \| `CANOEING` \| `CARDIO_SCULPT` \| `CARDIO_WORKOUT` \| `CARPENTRY` \| `CHEERLEADING` \| `CIRCUIT_TRAINING` \| `CLEANING` \| `CLIMBING` \| `CORE_TRAINING` \| `CRICKET` \| `CROQUET` \| `CROSS_COUNTRY_SKI` \| `CROSS_TRAINING` \| `CROSSFIT` \| `CURLING` \| `DANCING` \| `DIVING` \| `ELECTRIC_BIKE` \| `ELECTRIC_SCOOTER` \| `ELLIPTICAL` \| `EQUESTRIAN_SPORTS` \| `EXERCISE_CLASS` \| `FENCING` \| `FIELD_HOCKEY` \| `FISHING` \| `FITNESS_GAMING` \| `FOILING` \| `FOOTBALL_AMERICAN` \| `FOOTBALL_AUSTRALIAN` \| `FREE_WEIGHTS` \| `FRISBEE_PLAYING_GENERAL` \| `FUNCTIONAL_STRENGTH_TRAINING` \| `GARDENING` \| `GOLF` \| `GYMNASTICS` \| `HANDBALL` \| `HAND_CYCLING` \| `HIIT` \| `HIKING` \| `HIP_HOP` \| `HOCKEY` \| `HOEING` \| `HOUSEHOLD_CHORES` \| `HUNTING` \| `ICE_SKATING` \| `INCLINE_RUN` \| `INCLINE_WALK` \| `INDOOR_CLIMBING` \| `INTERVAL_WORKOUT` \| `JAZZ_DANCE` \| `JIU_JITSU` \| `JUMPING_ROPE` \| `KARATE` \| `KAYAKING` \| `KICKBOXING` \| `KITESURFING` \| `LACROSSE` \| `MARTIAL_ARTS` \| `MEDITATE` \| `MODERN_DANCE` \| `MOTOCROSS` \| `MOTORCYCLE` \| `MOUNTAIN_BIKE` \| `MOWING_LAWN` \| `MUAY_THAI` \| `MULTISPORT` \| `MUSICAL_PERFORMANCE` \| `NORDIC_WALKING` \| `ORIENTEERING` \| `OTHER` \| `OUTDOOR_BIKE` \| `OUTDOOR_WORKOUT` \| `PADDLEBOARDING` \| `PADEL` \| `PAINTING` \| `PARAGLIDING` \| `PARKOUR` \| `PICKELBALL` \| `PILATES` \| `POLO` \| `POWERLIFTING` \| `POWER_WALKING` \| `RACKET_SPORTS` \| `RACQUETBALL` \| `RESISTANCE_BANDS` \| `ROCK_CLIMBING` \| `ROLLERBLADING` \| `ROLLER_SKATING` \| `ROWING` \| `ROWING_MACHINE` \| `RUCKING` \| `RUGBY` \| `RUNNING` \| `SAILING` \| `SCOOTERING` \| `SCUBA_DIVING` \| `SHOOTING` \| `SHOVELING` \| `SKATEBOARDING` \| `SKATING` \| `SKIING` \| `SKYDIVING` \| `SNORKELING` \| `SNOWBOARDING` \| `SNOWMOBILING` \| `SNOWSHOEING` \| `SNOW_SPORT` \| `SOCCER` \| `SOFTBALL` \| `SPEED_SKATING` \| `SPINNING` \| `SPORT` \| `SQUASH` \| `STAIRCLIMBER` \| `STATIONARY_BIKE` \| `STEP_TRAINING` \| `STRENGTH_TRAINING` \| `STRETCHING` \| `STROLLER_WALK` \| `SURFING` \| `SWIMMING` \| `SWIMMING_OPEN_WATER` \| `SWIMMING_POOL` \| `SYNCHRONIZED_SWIMMING` \| `TABATA_WORKOUT` \| `TABLE_TENNIS` \| `TAEKWONDO` \| `TAI_CHI` \| `TANGO` \| `TENNIS` \| `TRACK_AND_FIELD` \| `TRAIL_RUN` \| `TRAMPOLINE` \| `TREADMILL` \| `TREADMILL_WALK` \| `TRX` \| `ULTIMATE_FRISBEE` \| `UNICYCLING` \| `VOLLEYBALL` \| `VOLLEYBALL_BEACH` \| `WAKEBOARDING` \| `WALKING` \| `WALK_WITH_WEIGHTS` \| `WATER_AEROBICS` \| `WATER_JOGGING` \| `WATER_POLO` \| `WATER_SKIING` \| `WATER_SPORT` \| `WATER_VOLLEYBALL` \| `WEEDING` \| `WEIGHTLIFTING` \| `WEIGHT_MACHINES` \| `WEIGHTS` \| `WHEELCHAIR` \| `WINDSURFING` \| `WORKOUT` \| `WRESTLING` \| `YOGA` \| `YOGA_BIKRAM` \| `YOGA_HATHA` \| `YOGA_POWER` \| `YOGA_VINYASA` \| `ZUMBA` | yes |  |
| `startTime` | string (date-time) | yes |  |
| `endTime` | string (date-time) | yes |  |
| `activeSeconds` | integer | yes |  |
| `distanceKm` | number or null |  |  |
| `provenance` | `user_entered` |  | default `user_entered` |
| `measured` | [Measured](#measured) or null |  |  |

### ZoneSeconds

Seconds in each of Fitbit's heart-rate zones.

| Field | Type | Required | Limits |
|---|---|---|---|
| `light` | number |  | ≥ 0.0, default `0` |
| `moderate` | number |  | ≥ 0.0, default `0` |
| `vigorous` | number |  | ≥ 0.0, default `0` |
| `peak` | number |  | ≥ 0.0, default `0` |

<!-- generated: end -->
