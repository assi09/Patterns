# The individual check-in alert: design choices

Status: **decided 2026-11-25; the backend is built** (`app/teams/checkin.py`, `app/api/checkins.py`,
migration 0033); the screens come next. The second gateway of the team product
([pivot.md](pivot.md)): when one person's own data shows a sustained, extreme change, the people
responsible for them are asked to check in. The first gateway, team aggregates with at least 5
people, is unchanged ([teams.md](teams.md)).

This page records each choice with the options we considered, so a choice can be changed later
without redesigning the rest. **Current** marks what is built; the others are kept on purpose.

## 1. Who receives it

| Option | What it means | For | Against |
|---|---|---|---|
| A. HR only | the team's HR contact | one trained recipient | HR may not know the person's work |
| B. Supervisor only | the team's supervisor | knows the workload behind it | a manager holding health-derived signals about a report |
| **C. HR and the supervisor** (current) | both, at the same time, the same message | the professor's proposal: HR acts, the supervisor can change the workload | two people learn of it |
| D. A contact the person picks | a colleague, HR or the supervisor | the most respectful of the person | the person may pick no one |
| E. The person only | a nudge to themselves | no one else learns anything | not a team feature; Today already does this (smart alarms) |

The owner gives an account the HR role (`python -m app.auth set-role <email> hr`); the team's
supervisor then names it as the team's HR contact (`PUT /teams/{id}/hr`). An HR account sees
only the check-in alerts of teams it is the contact for, never team reports or named levels.

**Roles, not people.** Alerts go to whoever holds the supervisor and HR-contact roles when the
alert goes out. One rule decides who holds a role, for delivery and for every later access
(`current_holder`): the account assigned to the team for it, still carrying the matching account
role. Someone who leaves a role (replaced as the team's HR contact, or an HR or supervisor account
demoted while still assigned) loses access to that team's alerts at once: they can no longer list, open or mark them,
even through an old link, and get no reminder. Their delivery record (the mark) stays for the
audit. `tests/test_checkin.py` covers this as a regression test.

## 2. Consent

| Option | Notes |
|---|---|
| **Separate opt-in, off by default** (current) | a third switch after "join the team" and "show my weekly levels", with its own versioned consent text, given to the roles "your supervisor and the team's HR contact"; member screens never name who holds them, and a change of who holds a role needs no fresh consent |
| On for every member | simpler, but sends health-derived signals about people who never agreed |
| Required to join | turns joining into a condition of the job |

Turning it off stops any alert not yet sent, and is logged. The consent text states the one hour
(below).

## 3. Does the person see it first

| Option | Notes |
|---|---|
| **Told at once; sent one hour later unless they stop it, or sooner if they send it** (current) | checked after each successful Google Health sync; the person is told at once with the exact time it goes out, sees the evidence, and can **send it now** or **stop this alert** (check-in alerts stay on). A later sync never restarts the hour or raises a second alert (the 28-day cooldown, and one waiting alert per person and team in the database). The server checks for due alerts every minute |
| Told at once; sent after 24 hours | the first design; too slow for someone in trouble |
| Told at the same time as the recipients | no window; fewer chances to stop a false alarm |
| Told first and must approve | the strongest control for the person, but someone in trouble may not answer |
| Not told | not acceptable: a hidden report about a person |

## 4. What counts as extreme

Decided by code from the person's own history, never by a model, and never against population or
medical cut-offs. A **sustained** change across **several** signals, so one bad night, one cold or
one trip does not raise it:

- the last 7 days against the 28 before (the same windows as the team report);
- at least 5 of the 7 days **confirmed worn**: a recorded wear time of at least 10 hours (awake
  wear, from activity-level minutes). A day without a wear time does not count, even with other
  readings, because the rule can send a name to HR; the reported "days worn" counts only these;
- in at least **2** of: time asleep, recovery, HRV, resting heart rate, stress score, at least
  **5 of the confirmed-worn days** past the worse edge of the person's usual range (the middle half of the 28
  days) by its full width; only the worse direction counts (less sleep, lower recovery and HRV,
  higher resting heart rate and stress);
- not again within 28 days of the last one.

The rule and its numbers live in one place (`app/teams/checkin.py`, rule `checkin-v1`), so a
change is one diff with its test results. The gap counted as "far" has a floor per signal for
narrow ranges: 45 minutes of sleep, 15 recovery points, 8 ms of HRV, 5 bpm, 15 stress points.

Measured in `tests/test_checkin.py` on synthetic people: on 100 calm people and over 10,000 weekly
windows, under 0.5% of windows raise one; a planted week of sleep 3 hours and HRV 30 ms below
usual is found in at least 95 of 100. One signal alone, one bad night, three bad days, a barely
worn week, old data and under 14 days of history raise nothing. The same check on real people
(PMData, LifeSnaps) is part of the weekend's testing.

## 5. What the recipients see

| Option | Notes |
|---|---|
| **On the Check-ins screen: the person's name and "please check in with them"**, the team and when it was sent (current) | no metric, value, direction or reason; shown only after checking the reader still holds the role |
| Which signals moved | more useful to HR; tells an employer about someone's sleep or heart rate |
| The full evidence | as the person sees it; far too much for an employer |

**Notifications never carry the name.** The inbox entry (and any email) says only "You have a
check-in request", so the name is read only behind the role check: someone who leaves a role
cannot read it back from an old notification. Recipients are chosen when the alert goes out, each
checked for still holding their role at that moment (still the team's supervisor with a supervisor
account, still its HR contact with an HR account), so a demotion during the hour means nothing
reaches that account.

The person always sees the full evidence behind their own alert. Leaving the team or turning
check-in alerts off withdraws a waiting alert at once, and Send now checks again that the person
is still in the team with check-in alerts on.

## 6. What the recipients do

HR and the supervisor each mark it **checked in** or **not needed**, optionally with a note
(stored, never shown to a model). An alert nobody marks within 3 days is shown again once, to
whoever still holds the role. Every step (raised, withdrawn, sent, opened, marked, reminded) is
written to an append-only log with who and
when, and no health data.

## 7. What never touches it

- **No language model** sees, writes or explains a check-in alert.
- **Not through the MCP server** ([pivot.md](pivot.md)): a harness cannot list or read check-in
  alerts, for a supervisor or anyone else.
- Not in team reports, the briefing, team evidence or emails beyond "you have a check-in alert,
  open the app".
