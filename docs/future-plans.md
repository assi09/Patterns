# Future plans: the team feature

Ideas discussed on 2026-11-22 after the supervisor chat was retired (#213) and planned changes
shipped (#214). None is built. Each is written down with the problem it solves, what an agent
adds that code cannot, and how it would be proven first. The rule from this project's own results
holds for all of them: **code computes and counts, the model only judges or rewrites text**. Free
investigation by the model did worse than code every time we measured it (the crunch warning came
in 1 of 4 runs; "why" answers went from 16 to 28 of 33 only once code tested every cause). See
[teams.md](teams.md) for what exists.

## 1. Anonymous team voice (next, if anything is built)

**Problem.** The dashboard shows *what* changed (time asleep −38 min for 7 of 8) but not *why*.
People rarely tell their manager what is wearing them down, so the supervisor sees the symptom,
guesses the cause, and picks a change blind.

**Feature.** One optional weekly question beside the nightly pulse: "Anything that made work
heavier this week?" The supervisor never sees an answer, only themes, each with how many people
raised it: "Late calls with the US client (6 people)", "Too many meetings on Wednesdays (5)". A
theme shows only at 5 or more people, never with quotes.

**What only an agent can do.**
- Group answers by meaning: "back-to-back calls", "my calendar is full" and "no time to actually
  work" are one complaint, which keyword rules cannot group reliably.
- Anonymize free text: in a team of eight, "since I joined in March" or "as the only designer"
  identifies someone, and no pattern rule catches every such detail.

**Where code stays in charge.** The model only tags each answer with a theme (or none) and rewrites
it in neutral team-level words. Code counts the tags, applies the floor of 5, refuses medical
words and anything about one person, and never shows an answer's own words.

**How it helps.** The supervisor learns the cause, the playbook can follow it (a "late calls"
theme points to no meetings after 5 pm), and members get a voice without being exposed.

**Proof before building.** Made-up answer sets with planted themes in varied wording, noise,
identifying details, medical mentions and instructions hidden in the text. Compare the agent with
a keyword-clustering baseline on theme recall, false themes and leaks (target zero). A few cents.

**Limits.** With a floor of 5, a team of eight sees only what most people share; quieter problems
stay invisible by design. Members have to bother to write. The join consent text needs a line about
the question before it goes live.

## 2. Which note explains which change (on hold)

**Problem.** `lined_up()` in `app/teams/reports.py` matches notes to changes by date only. A week
with "Release 2.0 (Nov 2)", "Moved to the new building (Nov 3)" and "Q4 offsite (Oct 28)" and two
changes (sleep down, steps up) is told that both changes lined up with all three notes.

**What an agent adds.** Judging which note could plausibly relate to which change (the move to
steps, the release to sleep, the offsite to neither) without a hand-written rule for every event
anyone might write.

**Coincidence is code's job.** One team, one event and one change can be chance. Three code checks
would set how strongly a link is worded: how often this team changes this much anyway (a base
rate), whether the same kind of event was followed by the same change before (`note_aftermath`),
and whether the change started around the event. "First time; changes this size happen about 1
week in 5 here" against "Lower sleep followed each of the last 3 releases".

**Proof before building.** About 40 made-up weeks with planted changes, 2 to 4 notes each (the
true cause in varied wording, decoys in the same dates, weeks where no note explains anything) and
pure-noise changes next to plausible notes. Agent against date overlap plus keyword rules, on
right and false matches; the key number is how often it "explains" noise. About $0.10 to $0.30.

## 3. The team's week (on hold)

**Problem.** Playbook changes name meetings and schedules ("no meetings after 5 pm"), but the agent
knows nothing about this team's actual meetings, hours or rotations.

**Feature.** The supervisor describes the team's shared routine in plain words or pastes a calendar
export: working hours, office and remote days, regular meetings (name, day, time, length), on-call
rotations, the release or sprint cycle. The agent turns it into a structured list the supervisor
confirms; anything about one person is refused. Code then lines patterns up with it ("sleep is 25
min lower on nights after sprint review, 7 of 8"), and suggestions name real meetings ("move the
Wednesday 6 pm review to Thursday 10 am"), checked by code to point at an item that exists.

**Later, optional.** Read-only access to a shared team calendar (times, titles, attendee counts
only), if the pilot asks for it: another OAuth scope and a privacy review.

## Smaller items

- **Alert checks in code.** Before an alert, check for a drop in how many people synced, a public
  holiday or clock change, one weekday driving the change, and other areas moving with it. These
  are thresholds, not agent work.
- **Halfway check on a running change.** Say when a new deadline note lands mid-change (the result
  will be muddied) or when the metric is already back to usual.
- **Changes from the team's own patterns.** Draft a change from the weekday pattern and notes when
  the playbook does not fit, checked by code to be team-level, measurable and safe. Better after the
  team's week (3) exists.
- **The dashboard's week picker and 4 or 12 week views** from the design canvas, not built in #214.
