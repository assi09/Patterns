# Strain and stress scores (proposed)

Two new daily scores, our own and deterministic like the [recovery score](product.md#recovery-score):
**strain** (how much load the heart carried today) and **stress** (how many physical signs of
stress the body showed). Every person sees them on Today. A supervisor sees their weekly levels
only for people who opted in ([teams.md](teams.md)). Status: the scores and their inputs are built
(`backend/app/analysis/day.py`, `backend/app/sync/daily.py`), served by `/days` and shown on
Today with a page each. The constants were calibrated on 60 days of the owner's data (below). They are
versioned and may move once more people use the app.

Like every score in the app, they describe the person's own data against their own baseline.
They are not medical measurements. "Stress" means physical signs only, never a mental state or a
diagnosis.

## What others do

| Product | Strain / load | Stress |
|---|---|---|
| WHOOP | 0-21, from heart rate (how high and how long, relative to the person's own max) plus muscular load; the exact formula is not published, the scale is bounded and grows slower near the top | — |
| Garmin (Firstbeat) | training load from heart rate | 0-100 from beat-to-beat HRV against the person's baseline |
| Oura | — | daytime stress from HRV, heart rate, motion and skin temperature, only while awake and still, against personal baselines |
| Fitbit | Active Zone Minutes, cardio load | Stress Management Score 1-100: heart rate and HRV, EDA where available, exertion balance, sleep |
| Research | Banister's and Edwards' TRIMP: time at each heart-rate intensity times a weight. The two agree closely in most studies; weaker for stop-and-go sports, and both depend on a good maximum heart rate | Daytime HRV and heart rate above what movement explains are the common signals |

## What the API gives us (checked 2026-10-26)

A read-only check on 7 days of the owner's account, recording only counts, timings and field
names:

| Data type | Request | Result | Use |
|---|---|---|---|
| `time-in-heart-rate-zone` | daily roll-up | one point per day with seconds in `LIGHT`, `MODERATE`, `VIGOROUS` (and `PEAK` when reached); 7 days in 1.6 s, 14 days per request | strain |
| `heart-rate` | roll-up in 60 s windows | about 1,440 points per day (average, min, max), **one request per day**, 1.4 s | stress |
| `heart-rate` | list of samples | 38,550 samples for one day, 5.5 s | not used: too heavy |
| `activity-level` | list | about 900 intervals a day, each with `activityLevelType`; recorded only while worn and awake (already read for wear time) | stress: awake and still |

We cannot read EDA, daytime HRV or Fitbit's own stress score (in Takeout that is almost always
`NO_DATA`).

## Strain (`strain_v1`), 0 to 21

1. **Load from Fitbit's own heart-rate zones.** Fitbit sets these zones from heart-rate reserve,
   using the wearer's resting heart rate and age. So the daily zone roll-up already reflects how
   hard the effort was for this person, which settles the maximum-heart-rate question without
   asking anyone's age. `MODERATE`, `VIGOROUS` and `PEAK` are Fitbit's fat-burn, cardio and peak
   zones: together they reproduce Active Zone Minutes. Load is the minutes in each zone times a
   weight, as in Edwards' TRIMP: `MODERATE` 2, `VIGOROUS` 3, `PEAK` 4. `LIGHT` holds 99% of a
   day's zone time, so it is everyday heart rate, not exercise. Weighted 1 it made every day "all
   out", so it counts **0.04**, enough to give a rest day a few points, as WHOOP does.
2. **Bounded scale.** `strain = 21 × (1 − exp(−load / 200))`, so each extra minute adds less near
   the top, as with WHOOP. Bands: 0-9 light, 10-13 moderate, 14-17 high, 18-21 all out.
3. **No zone minutes that day** (the Takeout history, or days synced before zones were added):
   load is estimated from Active Zone Minutes, at the person's own ratio of load to AZM on days
   with both (2 when there are fewer than 7 such days). With neither there is no strain, not a
   zero. The day records which method was used.
4. **Later (`strain_v2`):** a muscular part for strength workouts, from logged
   strength-training minutes, since heart rate undercounts lifting.

## Stress (`stress_v1`), 0 to 100, higher means more signs of stress

Recovery already covers the overnight signals. To avoid scoring the same thing twice, stress is
weighted toward **daytime**:

1. **Heart rate while still, beyond what exercise explains (60% of the weight).** Still minutes
   are awake minutes labeled sedentary, not within 10 minutes after a moderately or very active
   minute. The sync stores their mean heart rate above that day's resting rate. The score then
   takes its distance from a line fitted on the person's 28 days before (still heart rate against
   log zone load), and that distance is the input. This is the movement-adjusted heart rate
   behind Oura's and Fitbit's responsiveness signals, without EDA.
2. **Nightly HRV below the person's usual and resting heart rate above it (12.5% each),** shared
   with recovery.
3. **Sleep shortfall against the person's usual (15%).**

Each input becomes its share of the person's 28 days before that it beat, in the direction of more
stress (ties count half), exactly as recovery ranks its inputs. The shares are combined with the
fixed weights above, renormalized over the inputs present, so 50 is a typical day. There is no
score without the daytime input: under 4 hours of still, awake wear that day, or under 7 earlier
days to compare with. Each score lists its parts, so the app and the agent can explain it.

**Ground truth.** Nothing we can read measures stress directly, so the score is to be checked
against the person: an optional evening check-in ("how stressful was today?", 1-5) next to the
morning one. The evaluation reports the rank correlation between the score and those ratings, as
a pilot with one or two people. A raised heart rate while still also comes from caffeine, heat,
illness or a standing desk, and the score's explanation says so.

## How the constants were chosen

On 60 days of the owner's live data, read-only, recording only counts and ratios:

| Tried | Result | Kept |
|---|---|---|
| `LIGHT` zone weighted 1 (Edwards) | every one of 60 days "all out": `LIGHT` is 99% of zone time | weight 0.04, scale 200: 39 light, 11 moderate, 6 high and 4 all-out days; a quiet day about 6 |
| A still minute waits 10 minutes after any non-sedentary minute | only 15 of 60 days reached 4 hours still: levels come a minute at a time, so walking to the kitchen restarted the wait | wait only after moderately or very active minutes: 56 of 60 days |
| Share of still minutes above resting + 10 bpm | 85% of still minutes on a median day: Fitbit's resting rate is measured asleep, and sitting runs 10-20 bpm above it | the mean above resting, no cutoff (it ranks days the same as a +25 bpm cutoff, rank correlation 0.86) |
| That mean as it is | stress followed strain (rank correlation 0.63): active days read as stressful. Waiting 30 minutes after exercise left 13 days with a score, 60 minutes none | the distance from the person's own line against exercise: rank correlation with strain 0.09, 42 days with a score |

With all of this, stress ranks days almost independently of recovery (rank correlation 0.04), so
the two scores say different things. A test over 20 made-up people checks that a heart rate raised
only by exercise does not raise stress.

## On Today

The key numbers are Recovery, Strain, Sleep and Stress: two by two on phones, one row on wide
screens, each opening its page. Strain shows its band, the others where they sit against the
usual range. Steps leads the Activity section. Today's strain and stress say "so far", as both add
up through the day. Strain's page lists the zone minutes and what each counts; stress's lists each
input's share of the 28 days before. Stress has its own color.

## In Ask

The chat gives the agent the scores as daily metrics. Strain and the zone minutes belong to the
activity expert; recovery, stress and the still-time inputs to the recovery expert, whose notes
say they are the app's own estimates built from other metrics, and that stress means signs in
the data, never a feeling or a condition. The router knows both words. One synthetic run is in
[experiments.md](experiments.md#the-apps-own-scores-in-ask-2026-10-26).

## Storage and computation

The same as recovery: the sync stores the **inputs** as ordinary daily metrics from the same
source, and the scores are computed from them when read. A new formula therefore never needs a
resync.

- `hr_zone_light_minutes`, `hr_zone_moderate_minutes`, `hr_zone_vigorous_minutes`,
  `hr_zone_peak_minutes`: from the zone roll-up, 90 days per request.
- `still_minutes` and `still_hr_above_resting`: from the minute heart-rate roll-up (about one
  request per day; 60 days sync in under 2 minutes) and the activity-level intervals already read
  for wear time.
- `strain` and `stress_score` are computed in `backend/app/analysis/day.py` next to recovery.
  `/days/{date}` returns them with their parts, like `recovery`, and `/metrics/strain` and
  `/metrics/stress_score` give their days. The inputs are not screened as findings themselves.
- Days stored before this change have no inputs until they are synced again: later syncs reread
  only the last 3 days. `python -m app.sync pull --email <account> --days <n>` rewrites a range
  from the API. Until then strain uses the Active Zone Minutes estimate and stress is missing.

Minute heart rate is never stored, only the daily values.

## Next

- **The evening stress check-in**, as ground truth.
- **Backfill** for people already connected: resync the whole history once when new inputs
  appear.

## Open

- Whether stress also uses skin temperature, as Oura does. It is nightly only in the API.
- The constants rest on one person's 60 days; revisit them with more people.
- **Validation is incomplete.** The PMData evaluation found median within-person correlation of −0.03 between the physical stress score and reported stress. Strain versus perceived effort and validation against pilot check-ins remain open. See [the team evaluation](evaluation.md#the-team-agent-privacy-attacks-planted-changes-real-people-2026-11-12).
