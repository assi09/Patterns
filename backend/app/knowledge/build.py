"""Builds the passages the agent can retrieve from, out of public sources. Run by hand:

    python -m app.knowledge.build           # parse and filter what is in data/rag_raw/
    python -m app.knowledge.build --guard   # and list what the medical guard would flag

The result is committed (`index/passages.jsonl`, `index/manifest.json`), so the server and CI never
need the sources, `pdftotext` or a network. Only everyday habits go in: anything on illness,
treatment, medication, supplements, diets, pregnancy or children is cut when the index is built,
sentence by sentence, and a passage that loses too much is dropped whole. What was cut is counted in
the manifest, because a filter nobody can inspect is a filter nobody can trust.
"""

import hashlib
import html
import json
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.etree import ElementTree

from app.agent.guard import MAX_TEXTS
from app.agent.sanitize import reads_like_instruction
from app.agent.verifier import MEDICAL

RAW_DIR = Path("data/rag_raw")
INDEX_DIR = Path(__file__).parent / "index"
CARDS_DIR = Path(__file__).parent

MAX_WORDS = 300  # about 400 tokens
MIN_WORDS = 40
KEEP_SHARE = 0.6  # a passage losing more of its sentences than this no longer reads as one

OFF_LIMITS = re.compile(
    r"\b(medicines?|medications?|drugs?|supplements?|fasting|pregnan\w*|breast-?feed\w*|lactat\w*|"
    r"infants?|toddlers?|child(?:ren)?|adolescents?|teens?|teenagers?|cancers?|diabet\w*|"
    r"prediabet\w*|cholesterol|hypertension|blood pressure|heart (?:disease|attacks?)|strokes?|"
    r"obes\w*|overweight|surgery|weight[- ]loss|dementia|alzheimer\w*|arthritis|osteoporosis|"
    r"doctors?|physicians?|health ?care (?:provider|professional)s?|clinics?|clinical|therap\w*|"
    r"narcolepsy|restless legs|snor\w*|opioids?|melatonin|sleeping pills?|suicid\w*|patients?|"
    r"illness\w*|chronic|symptoms?|your provider|medical problems?|dieti[ct]ians?|side effects?|"
    r"doses?|alcoholism|diseases?|treatments?|disorders?|infections?|fractures?|decongestants?|"
    r"steroids?|lose weight|Trump|Make America)\b",
    re.IGNORECASE,
)
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z“\"])")
REFERENCE = re.compile(
    r"\[\d+(?:[,-]\s*\d+)*\]|\((?:see )?(?:figure|table)\s*[\w.-]+\)|"
    r"(?<=[.!?])\s\d+(?:,\s*\d+)*(?=\s[A-Z])",
    re.IGNORECASE,
)
RUNNING_LINE = re.compile(r"^(?:Chapter \d+\.|Appendix \d+\.|.*\| \d+$)")
BULLET = re.compile(r"^\s*(?:[•·▪l+-]||)\s+")


class BuildError(RuntimeError):
    """A source is missing or could not be read: better no index than a silently partial one."""


@dataclass(frozen=True)
class Section:
    title: str
    text: str


@dataclass(frozen=True)
class Source:
    key: str
    name: str  # as an answer credits it
    url: str
    license: str
    area: str


@dataclass(frozen=True)
class Passage:
    id: str
    title: str
    text: str
    source: str
    url: str
    license: str
    area: str  # sleep, recovery, activity, nutrition or exercise
    kind: str  # guideline, exercise or card
    metrics: tuple[str, ...] = ()
    levers: tuple[str, ...] = ()


US_GOVERNMENT = "US government work, public domain"
PAG = Source(
    "pag",
    "Physical Activity Guidelines for Americans, 2nd edition (HHS)",
    "https://odphp.health.gov/our-work/nutrition-physical-activity/physical-activity-guidelines",
    US_GOVERNMENT,
    "activity",
)
DGA = Source(
    "dga",
    "Dietary Guidelines for Americans, 2025-2030 (USDA and HHS)",
    "https://realfood.gov",
    US_GOVERNMENT,
    "nutrition",
)
SLEEP = Source(
    "sleep",
    "Your Guide to Healthy Sleep (NHLBI, NIH)",
    "https://www.nhlbi.nih.gov/resources/your-guide-healthy-sleep",
    US_GOVERNMENT,
    "sleep",
)
NIOSH = Source(
    "niosh",
    "NIOSH, CDC",
    "https://www.cdc.gov/niosh/work-hour-training-for-nurses/",
    US_GOVERNMENT,
    "sleep",
)
MEDLINE = Source(
    "medlineplus",
    "MedlinePlus, National Library of Medicine",
    "https://medlineplus.gov",
    US_GOVERNMENT,
    "nutrition",
)
EXERCISES = Source(
    "exercises",
    "free-exercise-db",
    "https://github.com/yuhonas/free-exercise-db",
    "Unlicense",
    "exercise",
)

SLEEP_START, SLEEP_END = 10, 35
# PDF page ranges (from 1, inclusive) that are guidance for adults, not reports or policy.
PDF_PAGES = {
    "pag": ((57, 67), (68, 79), (89, 95), (110, 114)),  # adults, older adults, safety, intensity
    "dga": ((3, 10),),  # after the title page and the Secretaries' letter
    "sleep": ((SLEEP_START, SLEEP_END),),  # what sleep does, how much, habits; not the disorders
}
# Topics about everyday habits. An allow-list, because 950 of the 1,017 are about illnesses.
MEDLINE_TOPICS = {
    "Benefits of Exercise": "activity",
    "Caffeine": "sleep",
    "Calcium": "nutrition",
    "Carbohydrates": "nutrition",
    "Dietary Fats": "nutrition",
    "Dietary Fiber": "nutrition",
    "Dietary Proteins": "nutrition",
    "Drinking Water": "nutrition",
    "Ergonomics": "activity",
    "Exercise and Physical Fitness": "activity",
    "Exercise for Older Adults": "activity",
    "Food Labeling": "nutrition",
    "Health Risks of an Inactive Lifestyle": "activity",
    "Healthy Living": "activity",
    "Healthy Sleep": "sleep",
    "How Much Exercise Do I Need?": "activity",
    "Iron": "nutrition",
    "Minerals": "nutrition",
    "Nutrition": "nutrition",
    "Nutrition for Older Adults": "nutrition",
    "Potassium": "nutrition",
    "Sodium": "nutrition",
    "Sports Fitness": "activity",
    "Sports Safety": "activity",
    "Stress": "recovery",
    "Vegetarian Diet": "nutrition",
}
LINKING = {"a", "an", "and", "at", "for", "from", "in", "of", "on", "or", "the", "to", "with", "is"}
RECOVERY_TITLE = re.compile(r"\b(rest|recover\w*|nap\w*|fatigue|stress|tired)\b", re.IGNORECASE)
SKIPPED_PAGE = re.compile(
    r"\b(references|questions|answers|quiz|contents|acknowledg\w*|objectives|diseases?|disorders?|"
    r"symptoms?|test dose|otc|epworth|liabilities|supervisor|fatigue risk management|"
    r"organizational|periodic assessments|workload|positive atmosphere|employers|metabolism|immune|following)\b",
    re.IGNORECASE,
)
# Exercise instructions use these in their everyday sense: a medicine ball, the prescribed reps.
EVERYDAY = re.compile(r"medicine ball|prescribed", re.IGNORECASE)
VIGNETTE = re.compile(r"^[A-Z’'.-]{3,}$")  # a first name in capitals heads a personal story


OFF_LIMITS_SECTION = re.compile(r"childhood|infant|toddler|pregnan|lactat|chronic disease", re.I)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def pdf_pages(path: Path) -> list[str]:
    """The text of each page."""
    try:
        done = subprocess.run(
            ["pdftotext", str(path), "-"], capture_output=True, check=True, text=True
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BuildError(f"Could not read {path.name}") from exc
    pages = done.stdout.split("\f")
    if not any(page.strip() for page in pages):
        raise BuildError(f"{path.name} has no text")
    return pages


def _is_heading(line: str) -> bool:
    words = line.split()
    capitals = sum(w[0].isupper() or w.lower() in LINKING for w in words) if words else 0
    return (
        0 < len(words) <= 9
        and line[0].isupper()
        and line[-1] not in ".,;:—-"
        and capitals / len(words) >= 0.75  # a wrapped sentence is mostly lower case
        and not BULLET.match(line)
        and not line.replace(" ", "").isdigit()
    )


def _repeated_lines(pages: list[str]) -> set[str]:
    """Running headers and footers: the same short line on many pages."""
    seen = Counter(
        line.strip() for page in pages for line in set(page.splitlines()) if line.strip()
    )
    return {line for line, count in seen.items() if count >= 4 and len(line.split()) <= 12}


def sections_from_pages(pages: Iterable[str], running: set[str] = frozenset()) -> list[Section]:
    """Paragraphs joined back from wrapped lines, under the heading above them."""
    found: list[Section] = []
    title, body, skipping = "", [], False

    def close() -> None:
        nonlocal body
        if body:
            found.append(Section(title, " ".join(body)))
        body = []

    for page in pages:
        for block in re.split(r"\n\s*\n", page):
            lines = [
                line.strip()
                for line in block.splitlines()
                if line.strip()
                and line.strip() not in running
                and not line.strip().isdigit()
                and not RUNNING_LINE.match(line.strip())
            ]
            if not lines:
                continue
            if len(lines) > 2 and _is_heading(lines[0]) and BULLET.match(lines[1]):
                close()  # a heading set directly on its bullet list
                title, lines = lines[0], lines[1:]
            text = re.sub(r"-\s+(?=[a-z])", "", " ".join(BULLET.sub("", line) for line in lines))
            if len(lines) <= 2 and _is_heading(text):
                close()
                skipping = bool(VIGNETTE.match(text))
                title = text
            elif skipping:
                continue
            else:
                # A sentence running over the page break is one paragraph, so do not split here.
                body.append(text)
    close()
    return found


def clean(text: str) -> tuple[str, Counter]:
    """Without sentences on what is off limits; empty if too little of it survives."""
    text = re.sub(r"\s+", " ", REFERENCE.sub("", text)).strip()
    sentences = [s for s in SENTENCE.split(text) if s.strip()]
    cut: Counter = Counter()
    kept = []
    for sentence in sentences:
        if MEDICAL.search(sentence) or OFF_LIMITS.search(sentence):
            cut["sentence_off_limits"] += 1
        elif reads_like_instruction(sentence):
            cut["sentence_instruction"] += 1
        else:
            kept.append(sentence)
    if not sentences or len(kept) / len(sentences) < KEEP_SHARE:
        cut["passage_mostly_off_limits"] += 1
        return "", cut
    return " ".join(kept), cut


def _short_enough(sentences: Iterable[str]) -> Iterable[str]:
    """A bullet list arrives as one long "sentence": cut it into pieces a passage can hold."""
    for sentence in sentences:
        words = sentence.split()
        for start in range(0, len(words), MAX_WORDS // 2):
            yield " ".join(words[start : start + MAX_WORDS // 2])


def chunk(text: str) -> list[str]:
    """Pieces of at most `MAX_WORDS`, whole sentences, each opening with the last one before it."""
    pieces, current, count = [], [], 0
    for sentence in _short_enough(SENTENCE.split(text)):
        words = len(sentence.split())
        if current and count + words > MAX_WORDS:
            pieces.append(" ".join(current))
            current, count = current[-1:], len(current[-1].split())
        current.append(sentence)
        count += words
    if current and (not pieces or count > len(current[0].split())):
        pieces.append(" ".join(current))
    return pieces


def passages_from(sections: Iterable[Section], source: Source, stats: Counter) -> list[Passage]:
    found = []
    for section in sections:
        if OFF_LIMITS_SECTION.search(section.title):
            stats["section_off_limits"] += 1
            continue
        area = source.area
        if source.key == "niosh" or RECOVERY_TITLE.search(section.title):
            area = "recovery" if RECOVERY_TITLE.search(section.title) else area
        text, cut = clean(section.text)
        stats.update(cut)
        for piece in chunk(text) if text else ():
            if len(piece.split()) < MIN_WORDS:
                stats["too_short"] += 1
                continue
            found.append(
                Passage(
                    id=f"{source.key}-{_digest(piece)}",
                    title=section.title[:120] or source.name,
                    text=piece,
                    source=source.name,
                    url=source.url,
                    license=source.license,
                    area=area,
                    kind="guideline",
                )
            )
    return found


def _strip_html(markup: str) -> str:
    text = re.sub(r"(?is)<(script|style|nav|header|footer).*?</\1>", " ", markup)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def medline_sections(path: Path) -> list[tuple[Section, str]]:
    """The allow-listed English topics, each with its area."""
    try:
        root = ElementTree.parse(path).getroot()
    except (ElementTree.ParseError, OSError) as exc:
        raise BuildError(f"Could not read {path.name}") from exc
    found = []
    for topic in root.findall("health-topic"):
        title = topic.get("title", "")
        if topic.get("language") == "English" and title in MEDLINE_TOPICS:
            summary = _strip_html(topic.findtext("full-summary") or "")
            if summary:
                found.append((Section(title, summary), MEDLINE_TOPICS[title]))
    return found


def niosh_sections(folder: Path) -> list[Section]:
    found = []
    for path in sorted(folder.glob("*.html")):
        markup = path.read_text(encoding="utf8", errors="ignore")
        match = re.search(r"(?is)<title>(.*?)</title>", markup)
        title = _strip_html(match.group(1)).split("|")[0].strip() if match else ""
        main = re.search(r"(?is)<main.*?</main>", markup)
        if not title or SKIPPED_PAGE.search(title):
            continue
        text = _strip_html(main.group(0) if main else markup)
        # The page repeats its title and print controls before the content.
        text = re.sub(r"^.*?Print Minus Related Pages\s*", "", text)
        text = re.sub(r"\s*PREVIOUS\b.*$", "", text)
        title = re.sub(r"^Module \d+\.\s*|\s*\(Cont(?:inued|\.)\)|\s+pt \d+$", "", title).strip()
        found.append(Section(title.split(", ")[-1], text))
    return found


def exercise_passages(path: Path, stats: Counter) -> list[Passage]:
    try:
        records = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise BuildError(f"Could not read {path.name}") from exc
    found = []
    for record in records:
        steps = " ".join(step.strip() for step in record.get("instructions") or [])
        if not record.get("name") or not steps:
            stats["exercise_without_steps"] += 1
            continue
        muscles = ", ".join(record.get("primaryMuscles") or []) or "several muscles"
        equipment = record.get("equipment") or "no equipment"
        text = (
            f"{record['name']}: a {record.get('level', '')} {record.get('category', '')} exercise "
            f"for {muscles}, with {equipment}. {steps}"
        )
        plain = EVERYDAY.sub("", text)
        if MEDICAL.search(plain) or OFF_LIMITS.search(plain) or reads_like_instruction(text):
            stats["exercise_off_limits"] += 1
            continue
        found.append(
            Passage(
                id=f"exercises-{_digest(record['name'])}",
                title=record["name"],
                text=re.sub(r"\s+", " ", text),
                source=EXERCISES.name,
                url=EXERCISES.url,
                license=EXERCISES.license,
                area="exercise",
                kind="exercise",
            )
        )
    return found


def card_passages() -> list[Passage]:
    """The hand-written cards go in as they are: they are the only passages tied to habits."""
    from app.agent.knowledge import load_cards

    return [
        Passage(
            id=card.id,
            title=card.title,
            text=card.text,
            source=card.source,
            url=card.url,
            license="our own words",
            area="recovery" if "recovery_score" in card.metrics else "sleep",
            kind="card",
            metrics=card.metrics,
            levers=card.levers,
        )
        for card in load_cards()
    ]


def _pdf_sections(key: str) -> list[Section]:
    pages = pdf_pages(RAW_DIR / f"{key}.pdf")
    running = _repeated_lines(pages)
    chosen = [page for start, end in PDF_PAGES[key] for page in pages[start - 1 : end]]
    return sections_from_pages(chosen, running)


def build() -> tuple[list[Passage], dict]:
    stats: Counter = Counter()
    sources: dict[str, int] = {}
    passages = card_passages()
    sources["cards"] = len(passages)
    for source in (PAG, DGA, SLEEP):
        found = passages_from(_pdf_sections(source.key), source, stats)
        sources[source.key] = len(found)
        passages += found
    found = passages_from(niosh_sections(RAW_DIR / "niosh"), NIOSH, stats)
    sources["niosh"] = len(found)
    passages += found
    medline = 0
    for section, area in medline_sections(RAW_DIR / "medlineplus.xml"):
        topic = Source(MEDLINE.key, MEDLINE.name, MEDLINE.url, MEDLINE.license, area)
        found = passages_from([section], topic, stats)
        medline += len(found)
        passages += found
    sources["medlineplus"] = medline
    found = exercise_passages(RAW_DIR / "exercises.json", stats)
    sources["exercises"] = len(found)
    passages += found
    unique = list({p.id: p for p in passages}.values())
    stats["duplicates"] = len(passages) - len(unique)
    manifest = {
        "passages": len(unique),
        "by_source": sources,
        "by_area": dict(Counter(p.area for p in unique)),
        "by_kind": dict(Counter(p.kind for p in unique)),
        "cut": dict(sorted(stats.items())),
        "raw_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()[:16]
            for path in sorted(RAW_DIR.glob("*"))
            if path.is_file() and path.suffix in (".pdf", ".xml", ".json")
        },
        "sources": [asdict(s) for s in (PAG, DGA, SLEEP, NIOSH, MEDLINE, EXERCISES)],
    }
    return unique, manifest


def flagged_by_guard(passages: list[Passage], guard) -> tuple[list[Passage], float]:
    """What the medical guard would flag, for a person to read. It is built for sentences about
    someone's own data, so it also flags plain guidance ("eat whole grains", night-shift tips):
    on 2026-11-08 most of what it flagged was the useful part. So it reports, and the filters above
    decide. It still checks every answer before it is shown."""
    flagged, cost = [], 0.0
    for start in range(0, len(passages), MAX_TEXTS):
        batch = passages[start : start + MAX_TEXTS]
        judgement = guard.judge([passage.text for passage in batch])
        cost += judgement.cost_usd
        flagged += [p for p, bad in zip(batch, judgement.flagged, strict=True) if bad]
    return flagged, cost


def main() -> int:
    if not RAW_DIR.exists():
        print(f"Put the sources in {RAW_DIR} first.", file=sys.stderr)
        return 1
    passages, manifest = build()
    if "--guard" in sys.argv:
        from app.agent.guard import JevGuard
        from app.agent.jev import JevClient
        from app.config import settings

        guard = JevGuard(JevClient.from_settings(settings))
        flagged, cost = flagged_by_guard(passages, guard)
        manifest["guard_flagged_for_review"] = len(flagged)
        print(f"Guard flagged {len(flagged)} for review, ${cost:.4f}")
        for passage in flagged:
            print(f"  {passage.id} | {passage.title[:40]} | {passage.text[:100]}")
    INDEX_DIR.mkdir(exist_ok=True)
    with (INDEX_DIR / "passages.jsonl").open("w") as file:
        for passage in passages:
            file.write(json.dumps(asdict(passage), ensure_ascii=False) + "\n")
    (INDEX_DIR / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(
        json.dumps({k: manifest[k] for k in ("passages", "by_source", "by_area", "cut")}, indent=1)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
