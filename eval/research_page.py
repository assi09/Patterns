"""A read-only page of two real-data weekly reports, for showing what the app does on real people.

Run after `eval/varied_teams.py run`, from the repository root:

    python eval/research_page.py

It reads the local experiment database (data/eval/varied_teams/run.db, never committed) and writes
data/eval/varied_teams/research_page.html. Nothing goes to production and nothing is uploaded.

Two teams, both from the rubric-development set; the reserved teams stay out. Both are groups we
formed from real LifeSnaps research participants, not real teams:
- LifeSnaps 11, week of 19 July 2021: a ready report with a real finding (steps fell);
- LifeSnaps 4, the same week: withheld. Only the app's own reason is shown; a withheld report keeps
  no team figures, and none are shown here.

The page shows team aggregates only: each section's sentence, contributor count, comparison period
and its evidence record. No participant id, account or daily value appears.
"""

import html
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

PRIVATE = Path("data/eval/varied_teams")
WEEK = "2021-07-19"
SHOWN = {"lifesnaps-11": "Group A", "lifesnaps-4": "Group B"}
RESERVED = {"lifesnaps-13", "lifesnaps-6", "pmdata-5", "pmdata-6"}
DATASET = "https://zenodo.org/records/7229547"
LICENSE = "https://creativecommons.org/licenses/by/4.0/"
CITATION = (
    "Yfantidou, S. et al. (2022). LifeSnaps, a 4-month multi-modal dataset capturing unobtrusive "
    "snapshots of our lives in the wild. Scientific Data 9, 663."
)
# Fields of an evidence record that are team aggregates; anything else is left out of the page.
SHOWN_FIELDS = {"id", "tool", "metrics", "windows", "n", "sufficient", "stats"}


def _day(text: str) -> str:
    d = date.fromisoformat(text)
    return f"{d.day} {d:%b %Y}"


def _period(window: dict) -> str:
    return f"{_day(window['start'])} to {_day(window['end'])}"


def _report(db: sqlite3.Connection, name: str) -> dict:
    row = db.execute(
        """select r.status, r.members_total, r.members_included, r.headline, r.body, r.evidence
           from team_reports r join teams t on t.id = r.team_id
           where t.name = ? and r.week_start = ?""",
        (f"Research {name} (real data)", WEEK),
    ).fetchone()
    if row is None:
        sys.exit(f"no report for {name} in the week of {WEEK}: run eval/varied_teams.py first")
    status, total, included, headline, body, evidence = row
    return {
        "status": status,
        "total": total,
        "included": included,
        "headline": headline,
        "body": json.loads(body or "{}"),
        "evidence": json.loads(evidence or "{}"),
    }


def _ready_card(label: str, report: dict) -> str:
    rows = []
    for section in report["body"].get("sections", []):
        record = report["evidence"].get(section.get("evidence_id"), {})
        shown = {k: v for k, v in record.items() if k in SHOWN_FIELDS}
        windows = record.get("windows") or []
        rows.append(
            f"""<tr class="{html.escape(section.get("status", ""))}">
<td>{html.escape(section["text"])}</td>
<td class="n">{record.get("n", "–")}</td>
<td>{html.escape(_period(windows[1])) if len(windows) > 1 else "–"}</td>
<td><details><summary>evidence</summary><pre>{html.escape(json.dumps(shown, indent=1))}</pre>
</details></td></tr>"""
        )
    priorities = report["body"].get("priorities", [])
    briefing = (
        "The briefing led with: " + html.escape(priorities[0]["text"])
        if priorities
        else "The briefing had no item: it raises only changes found by the four-week team scan, "
        "which measures each week against one fixed earlier baseline, and the scan found none."
    )
    finding = next(
        (s for s in report["body"].get("sections", []) if s.get("status") == "changed"), None
    )
    record = report["evidence"].get(finding["evidence_id"], {}) if finding else {}
    windows = record.get("windows") or []
    lead = (
        f"""<div class="finding"><p class="k">Finding</p><p>{html.escape(finding["text"])}</p>
<p class="meta">{record.get("n")} contributors · week {html.escape(_period(windows[0]))} ·
compared with {html.escape(_period(windows[1]))} ·
evidence <code>{html.escape(record.get("id", ""))}</code></p></div>"""
        if finding
        else ""
    )
    return f"""<section class="card">
<h2>{label}: {report["total"]} people, week of {_day(WEEK)}</h2>
<p class="meta">Ready. {report["included"]} of {report["total"]} had enough data this week; each
metric below needs at least 5 of them.</p>
<h3>{html.escape(report["headline"])}</h3>
{lead}
<p>{briefing}</p>
<table><thead><tr><th>Section, as the supervisor reads it</th><th>Contributors</th>
<th>Compared with</th><th></th></tr></thead><tbody>{"".join(rows)}</tbody></table>
</section>"""


def _withheld_card(label: str, report: dict) -> str:
    return f"""<section class="card withheld">
<h2>{label}: {report["total"]} people, week of {_day(WEEK)}</h2>
<p class="meta">Withheld.</p>
<h3>{html.escape(report["headline"])}</h3>
<p>No team figure exists for this week: the app computes none below 5 people, so there is nothing
to inspect, and the supervisor sees only this sentence.</p>
</section>"""


PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Patterns on real research data (read-only)</title>
<style>
:root {{ --ink:#1d1b18; --muted:#6b645b; --line:#e6dfd4; --bg:#f7f2ea; --card:#fff;
  --accent:#8a3b12; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --ink:#f1ece4; --muted:#a59d92; --line:#3a352f; --bg:#171512; --card:#211e1a;
    --accent:#f0a274; }}
}}
body {{ margin:0; padding:32px 16px; background:var(--bg); color:var(--ink);
  font:15px/1.5 -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; }}
main {{ max-width:980px; margin:0 auto; }}
.banner {{ border:1px solid var(--accent); border-radius:10px; padding:12px 16px;
  margin:16px 0 24px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
  padding:20px 22px; margin:0 0 20px; }}
.meta, .k {{ color:var(--muted); font-size:13px; margin:4px 0; }}
.k {{ text-transform:uppercase; letter-spacing:.6px; }}
.finding {{ border-left:3px solid var(--accent); padding:4px 12px; margin:12px 0; }}
table {{ width:100%; border-collapse:collapse; margin-top:12px; font-size:14px; }}
th, td {{ text-align:left; vertical-align:top; padding:8px 6px; border-top:1px solid var(--line); }}
th {{ color:var(--muted); font-weight:600; }}
td.n {{ text-align:right; }}
tr.changed td:first-child {{ font-weight:600; }}
tr.not_enough_data td:first-child {{ color:var(--muted); }}
pre {{ white-space:pre-wrap; font-size:12px; margin:6px 0 0; }}
footer {{ color:var(--muted); font-size:13px; }}
a {{ color:var(--accent); }}
</style></head><body><main>
<h1>Patterns on real research data</h1>
<p class="banner"><strong>Groups constructed from real research participants.</strong> These are
not real teams or colleagues: we grouped LifeSnaps participants at random with a fixed seed.
Read-only: these reports exist only on this computer, not in the app or on production. Every
figure is a team aggregate; no participant is identified.</p>
{cards}
<footer><p>Data: LifeSnaps, {citation} <a href="{dataset}">{dataset}</a>, licensed
<a href="{license}">CC BY 4.0</a>. Changes: daily values were grouped into constructed teams and
summarised into weekly team figures by Patterns' report code. Built by
<code>eval/research_page.py</code> from the varied-team experiment.</p></footer>
</main></body></html>
"""


def main() -> None:
    assert not RESERVED & set(SHOWN), "a reserved team must stay out of the demo"
    db = sqlite3.connect(PRIVATE / "run.db")
    cards = []
    for name, label in SHOWN.items():
        report = _report(db, name)
        card = _ready_card if report["status"] == "ready" else _withheld_card
        cards.append(card(label, report))
    out = PRIVATE / "research_page.html"
    out.write_text(
        PAGE.format(
            cards="\n".join(cards), citation=html.escape(CITATION), dataset=DATASET, license=LICENSE
        )
    )
    print("written", out)


if __name__ == "__main__":
    main()
