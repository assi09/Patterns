# The individual check-in alert: design choices

Status: **decided 2026-11-25, not built yet.** The second gateway of the team product
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

The HR contact is set per team by the owner (`python -m app.auth set-role <email> hr`, then the
team's HR contact). An HR account sees only the check-in alerts of teams it is the contact for,
never team reports or named levels.

## 2. Consent

| Option | Notes |
|---|---|
| **Separate opt-in, off by default** (current) | a third switch after "join the team" and "show my weekly levels", with its own versioned consent text; the screen shows exactly the message the recipients would get |
| On for every member | simpler, but sends health-derived signals about people who never agreed |
| Required to join | turns joining into a condition of the job |

Turning it off stops any alert not yet sent, and is logged.

## 3. Does the person see it first

| Option | Notes |
|---|---|
| **Told at once; sent after 24 hours unless they turn the alert off** (current) | they learn of it before anyone else, see the evidence behind it, and keep the choice; nothing is sent while the window is open |
| Told at the same time as the recipients | no window; fewer chances to stop a false alarm |
| Told first and must approve | the strongest control for the person, but someone in trouble may not answer |
| Not told | not acceptable: a hidden report about a person |

## 4. What counts as extreme

Decided by code from the person's own history, never by a model, and never against population or
medical cut-offs. A **sustained** change across **several** signals, so one bad night, one cold or
one trip does not raise it:

- the last 7 days against the 28 before (the same windows as the team report);
- at least 5 of the 7 days worn;
- in at least **2** of: time asleep, recovery, HRV, resting heart rate, stress score, at least
  **5 of the 7 days** past the worse edge of the person's usual range (the middle half of the 28
  days) by its full width; only the worse direction counts (less sleep, lower recovery and HRV,
  higher resting heart rate and stress);
- not again within 28 days of the last one.

The thresholds are tuned on real people (PMData, LifeSnaps) and calm synthetic people for a false
alarm rate, reported per person-year, and on planted sustained drops for detection. The rule and
its numbers live in one place in the code so a change is one diff with its test results.

## 5. What the recipients see

| Option | Notes |
|---|---|
| **The person's name and "please check in with them"**, the date, and that it was raised by the agreed rule (current) | no metric, value, direction or reason |
| Which signals moved | more useful to HR; tells an employer about someone's sleep or heart rate |
| The full evidence | as the person sees it; far too much for an employer |

The person always sees the full evidence behind their own alert.

## 6. What the recipients do

HR and the supervisor each mark it **checked in** or **not needed**, optionally with a note
(stored, never shown to a model). An alert nobody marks within 3 days is shown again once. Every
step (raised, told, withdrawn, sent, opened, marked) is written to an append-only log with who and
when, and no health data.

## 7. What never touches it

- **No language model** sees, writes or explains a check-in alert.
- **Not through the MCP server** ([pivot.md](pivot.md)): a harness cannot list or read check-in
  alerts, for a supervisor or anyone else.
- Not in team reports, the briefing, team evidence or emails beyond "you have a check-in alert,
  open the app".
