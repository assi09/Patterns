# App and UI plan

Agreed with the user on 2026-10-25. The goal: an app that feels complete and better than Fitbit's
(now Google Health) or Bevel's, everything free, with the AI still its strongest point. Simple and
neat, not a stack of rounded boxes. Each step below ships as its own pull request
([AGENTS.md](../AGENTS.md)); this page is updated as steps land.

## Decisions

| Topic | Decision |
|---|---|
| Tabs | **Today · Journal · Ask · Reminders · Settings**. The Data tab moves into Settings. |
| Look | **Flatten the current look**: keep the "Track day" palette and fonts; replace most boxes with plain sections, hairline dividers and large numbers. Cards stay only for things you act on (logging drafts, suggestions). Each color means one metric everywhere. |
| Biological age | **Fitness age plus habits**: an estimate from published age norms of cardio fitness, with how habits moved it. Labeled as an estimate with its confidence, never health advice. |
| Reminders | **Phone notifications** scheduled from approved reminders. Fitbit alarms cannot be set: Google's new API has no alarm endpoint and the old Fitbit one shuts down on 2026-11-02. Fitbit mirrors phone notifications to the watch when the person turns that on, so reminders still reach the wrist. |
| Premium features | All free: fitness age, journal, habit impact, workout summaries. |

## What the research showed

- **WHOOP** ([design breakdown](https://www.925studios.co/blog/whoop-design-breakdown)): three big
  numbers on the home screen; each screen answers one question; detail hidden until asked for; a
  narrow palette where each color keeps one meaning; coaching inside the data views, not in a
  separate tab.
- **Google Health app** (Fitbit's successor, [announcement](https://store.google.com/us/magazine/google-health-app?hl=en-US)):
  Today, Fitness, Sleep and Health tabs; a customizable Today with focus metrics and weekly cardio
  load; coach insights on Today.
- **Bevel** ([Bevel 3](https://gadgetsandwearables.com/2026/05/16/bevel-3/), [App Store](https://apps.apple.com/app/id6456176249)):
  recovery, strain, sleep and fitness; Biological Age updated weekly with a confidence level; a
  Journal for habits (hydration, sunlight, screen time) and how they relate to sleep and recovery.
  Its users [point out](https://feedback.bevel.health/feature-requests/p/add-journal-entries-stats)
  that a habit is compared with all days rather than a fair subset: **our deterministic tools can
  do that comparison properly, which is where the AI beats it.**
- **Apple Health** [criticism](https://cio.de/a/apple-s-health-app-really-needs-a-redesign,3105399):
  colors picked per card and thin low-contrast text. Avoid both.
- **Data we have:** daily steps, active minutes, calories, distance, sleep (stages, bedtime),
  resting heart rate, HRV, respiratory rate, skin temperature, wear time; workouts with their
  summaries ([workouts.md](workouts.md)). **No VO2 max** for the owner through the API (both
  `vo2-max` and `daily-vo2-max` return nothing), so fitness age needs the fallback below.

## Design principles

1. **Numbers first.** The day's key values are large type, read at arm's length; labels and units
   small and quiet. Every number is compared with the person's own usual (their last 28 days), the
   way the agent already reasons.
2. **Sections, not boxes.** A screen is a column of sections: a small caps header, then rows
   separated by hairlines. No background panel unless the thing is interactive. Fewer shadows,
   fewer radii; spacing does the grouping.
3. **One color per metric**, the same on Today, charts, journal and evidence (the existing
   `METRIC_COLORS`). Status colors (good, watch) only where a value is compared with usual.
4. **Detail on demand.** Today shows the summary; tapping a value opens its page: a 30-day chart,
   the usual range, and the agent's take with its evidence.
5. **The AI is woven in, not a tab you have to visit**: the agent's note for the day on Today,
   "Ask about this" on every metric page, habit impact in the Journal, workout summaries written by
   the agent from computed numbers. Every sentence still cites evidence; no medical advice.
6. **Quiet motion and states.** Loading as skeleton lines, not spinners; empty states that say what
   will appear and when; errors in one line with a retry.

## Screens

### Today

**Redesigned 2026-11-16 as widgets**, Karim's choice after mockups of two directions (Bevel-style
rings and tiles, Google Health-style coach feed): the rings and tiles, with the feed's sleep card
(the night stage by stage, read live from Google Health, `GET /days/{day}/sleep`) and its heart
and body card (each value as a dot on the usual range). The earlier "no boxes" decision is replaced
for Today. From the top: rings for recovery, strain and sleep; the newest finding with "Why?";
steps by hour; sleep; heart and body; stress gauge, zone minutes, distance, calories; workouts; the
check-in; context questions; what changed, as chips. Desktop: rings across, then two columns.

The list below is the earlier plan, kept for the record.

- Header: the date with previous/next day (swipe or arrows), and the sync time.
- **The agent's note for the day**: one or two sentences from the daily run (what stands out and
  why), with its evidence chips; "Ask about this" opens Ask with the context.
- **Three key numbers** in large type: Sleep (time asleep), Activity (active zone minutes or steps
  vs usual), Heart (resting heart rate vs usual). Later Recovery once the score exists.
- **Sleep**: time asleep, bedtime and wake time, a thin stages bar, vs usual.
- **Activity**: steps, active zone minutes, calories, distance; an hourly steps strip.
- **Heart**: resting heart rate, HRV, respiratory rate, skin temperature vs baseline.
- **Workouts**: the day's workouts as rows (type, time, duration, the key metrics), each opening a
  workout page.
- **Today's reminders** and the morning check-in, as rows.

### Workout page and summaries

- A workout: the metrics from [workouts.md](workouts.md), time in each heart-rate zone as one bar,
  a heart-rate line if intraday data allows, and comparison with similar past workouts ("your
  third tennis session this month; average heart rate 6 bpm lower than the first").
- Weekly summary on Journal: count, total time, active zone minutes by type; the agent writes one
  paragraph from computed numbers.

### Journal

- **Calendar**: a month grid where each day's shade is its activity (active zone minutes), with
  sleep and workouts as small marks; tap a day for that day's Today view.
- **Habits**: tags per day (alcohol, late caffeine, late screen, hydration, sunlight, stress, sick,
  travel, plus custom ones), logged in one tap on Today or the day page, or told to the agent.
- **Habit impact (the AI's edge)**: for each habit with enough days, compare the nights or days
  after it with comparable days without it (same weekday mix, matched wear), using the existing
  deterministic tests with the multiple-testing correction. The agent explains the significant
  ones; non-significant ones say "no clear effect yet, n days".

### Fitness age

- If a device gives cardio fitness (VO2 max), use it; otherwise estimate it from resting heart
  rate and age (Uth et al. 2004: VO2 max = 15.3 x maximum HR / resting HR, maximum HR from age by
  Tanaka et al. 2001). Fitness age is the age whose norm matches that value (HUNT fitness study
  norms by sex). Needs birth year and sex in Settings; without them, the card asks for them.
- Updated weekly, with a confidence level (how many days of resting heart rate, how stable).
- "What moved it": the changes in its inputs over the last weeks (resting heart rate, active
  minutes), with evidence. Wording: an estimate from published norms; not a health assessment.

### Ask

- Keep the conversation; flatten the bubbles and chips; suggested questions drawn from today's
  data; entry from any metric or workout page carries that context.

### Reminders

- Kinds: wind-down before a target bedtime, move nudges after long sedentary periods, planned
  workouts, logging check-ins (food, habits), sync reminders.
- The agent proposes reminders with their evidence ("later bedtimes went with lower efficiency");
  nothing is scheduled until approved. Each has a schedule editor, quiet hours and a daily cap.
- Delivered as phone notifications (`expo-notifications`, scheduled locally). Afterwards the app
  checks whether a reminder changed anything (bedtime before and after), with a test.
- Today the reminders screen runs on the mock API; the backend storage comes first.

### Settings

- Profile: name, birth year and sex (only for fitness age norms), units, time zone.
- Appearance: System, Light, Dark.
- Data source: Google Health connect, sync, disconnect, coverage and low-wear days (today's Data
  tab), logging permissions.
- Notifications: allow, quiet hours, daily cap.
- Privacy: what is stored, export my data, delete my data and account.
- Account: change password, sign out; for the owner, access requests.
- About: what the app is and is not ("patterns in your own data, not medical advice").

## Backend this needs

- `GET /days/{date}`: one day's metrics with the person's usual range (from the daily table).
- Workouts synced into the database (the exercise list, with summaries) and `GET /workouts`,
  `GET /workouts/{id}`; comparison with similar workouts as a deterministic tool.
- Intraday strips for a day (hourly steps, heart rate) with range roll-ups, cached.
- Journal: habit tags table and endpoints; a `habit_impact` analysis tool returning `Evidence`.
- Profile: birth year, sex, units; `fitness_age` tool returning `Evidence`.
- Reminders: storage, endpoints and the agent's proposal tool (approval like logging drafts).
- A daily run after sync that writes the agent's note for the day.

## Steps (each a pull request)

Steps 4–7 are scheduled in [plan.md](plan.md): reminders (step 5) and the agent on Today (step 7)
in weeks 2–3; the journal, the weekly workout summary and fitness age only if time allows.

1. **Design foundation and tabs**: type scale with large numerals, section and row components,
   hairline dividers, fewer cards; the five tabs; Settings with the Data tab's content, profile
   and appearance. No new data yet. **Done**: `Section`, `Row` and `Stat` (`components/list.tsx`)
   and a `hero` figure style; Settings replaces the Data tab (`/data` redirects there, and so does
   Google's return); logged entries moved to their own page as rows. The Journal tab is added with
   step 4, so no tab ships empty; profile fields come with step 6, which needs them.
2. **Today with the day's numbers**: `GET /days/{date}`, the day switcher, sleep/activity/heart
   sections vs usual, metric pages with a 30-day chart. **Done**: `GET /days/{date|latest}` and
   `GET /metrics/{metric}` (`app/analysis/day.py`): each value with the middle half of the 28 days
   before (at least 7 days; low-wear days left out of activity) and its last 14 days. Today: the day
   with arrows (swipe on phones, arrow keys on the web), three key numbers with trend lines, Sleep
   with a stages bar and wake time, Activity, Heart and body, and what changed lately, in two
   columns on wide screens. Today's running totals say "so far" instead of "below usual". Each
   value opens a metric page: 7, 30 or 90 days with the usual band, average, lowest, highest, the
   days one by one, and "Ask about" with the metric attached.
3. **Workouts**: sync and list, workout page, weekly summary. **Partly done** (#69): the day's
   workouts on Today, read live from Google, and a page each; the weekly summary is left.
4. **Journal**: calendar, habit tags, habit impact tool and its explanations.
5. **Reminders for real**: backend, agent proposals, phone notifications.
6. **Fitness age**: profile fields, the tool, its card and page.
7. **The agent on Today**: the daily note from the daily run, "Ask about this" everywhere, Ask
   restyled. **Partly done:** "Ask about" on metric, evidence and workout pages; the daily note is
   skipped for now at the user's request.

Also done on 2026-10-25, beyond the steps: Today's recovery score (our own, its parts on its page;
the user chose it over waiting), the morning check-in and steps by hour (#69); the evidence page
(#65); Ask with separate conversations sharing memory, a collapsible sidebar, pin, rename, delete,
copy, edit and retry, and attach as a popup on the web (#66-#68).

Every UI step: mock, types and http client together; light and dark, phone and desktop, clicked
through with Playwright; empty and error states.

## Trade-offs to keep in mind

- The course gives the agent and evaluation the largest weight (40%). The app has since deployed and the benchmark has results. Current work focuses on conversational reliability ahead of the December 5 presentations. See the [plan](plan.md).
- Types the owner never did, and fitness age's fallback, are estimates; each is labeled as such.
