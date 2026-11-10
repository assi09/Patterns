"""Does the answer key agree with the app's own statistics on the real people? Costs nothing.

Run from the repository root: `PYTHONPATH=backend:eval python eval/check_oracle.py`. They are
written separately and should nearly always agree; any disagreement is read before anything is graded.
Prints counts only.
"""

from datetime import timedelta

import oracle
import real_data
from app.analysis.day import with_scores
from app.analysis.evidence import ToolError, Window
from app.analysis.tools import compare_windows, correlate
from real_eval import LINKS, usable


def verdict(evidence) -> str | None:
    if not evidence.sufficient or evidence.stats.get("p_value") is None:
        return None
    if evidence.stats["p_value"] >= oracle.ALPHA:
        return "none"
    return "up" if evidence.stats["mean_recent"] > evidence.stats["mean_baseline"] else "down"


people = real_data.choose_lifesnaps(real_data.load_lifesnaps())
if real_data.PMDATA.exists():
    people |= real_data.load_pmdata()
score_failures = change_same = change_total = link_same = link_total = 0
for name, frame in people.items():
    try:
        with_scores(frame)
    except Exception as error:
        score_failures += 1
        print("scores failed:", name, type(error).__name__, str(error)[:120])
    end = frame.index.max()
    for metric in usable(frame):
        recent = Window(start=(end - timedelta(days=13)).date(), end=end.date())
        baseline = Window(
            start=(end - timedelta(days=41)).date(), end=(end - timedelta(days=14)).date()
        )
        try:
            mine = verdict(compare_windows(frame, metric, recent, baseline))
        except ToolError:
            continue
        theirs = oracle.change(frame, metric, end, 14, 28)
        if mine and theirs:
            change_total += 1
            change_same += mine == theirs
    window = Window(start=frame.index.min().date(), end=end.date())
    for driver, target, lag in LINKS:
        if driver in usable(frame) and target in usable(frame) and lag == 0:
            try:
                evidence = correlate(frame, driver, target, window, 0)
            except ToolError:
                continue
            theirs = oracle.link(frame, driver, target, 0)
            if evidence.sufficient and theirs and evidence.stats.get("p_value") is not None:
                mine = (
                    "none"
                    if evidence.stats["p_value"] >= oracle.ALPHA
                    else ("positive" if evidence.stats["rho"] > 0 else "negative")
                )
                link_total += 1
                link_same += mine == theirs
print(f"people {len(people)}, score failures {score_failures}")
print(f"change: agree {change_same}/{change_total}")
print(f"link: agree {link_same}/{link_total}")
