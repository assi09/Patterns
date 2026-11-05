"""Looking things up outside the person's data: food values from USDA, and an allowlisted web.

What comes back is a quoted result, **never `Evidence`**: the verifier still allows only computed
numbers in claims about the person. A looked-up number reaches them only with its source, in a reply
checked against that result (`app/agent/world.py`), or as a labelled estimate on a draft they
confirm.

Nothing about the person leaves: a query is refused if it looks personal or medical, and the
model never sees their data when it writes one. Web results are untrusted: links are stripped, text
that reads like an instruction is dropped, and a result citing nothing on the allowlist counts as
nothing found. A person gets `WEB_PER_DAY` searches a day; any result is reused for a day, across
people, which is safe because a query holds nothing personal.
"""

import re
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlparse

import httpx2
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.llm import LLM, Budget, BudgetExceeded, LLMError
from app.agent.sanitize import clean, reads_like_instruction
from app.agent.verifier import MEDICAL
from app.db.models import OutsideLookup

FDC_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"
FDC_SOURCE = "USDA FoodData Central"
FDC_DOMAIN = "fdc.nal.usda.gov"
FDC_TIMEOUT_S = 8
FDC_TYPES = "Foundation,SR Legacy"  # measured reference foods, not branded products
NUTRIENTS = {1008: "energy_kcal", 1003: "protein_g", 1005: "carbohydrate_g", 1004: "fat_g"}
MAX_FOODS = 3
MAX_GRAMS = 2_000
ALLOWED_DOMAINS = (
    "fdc.nal.usda.gov",
    "usda.gov",
    "wikipedia.org",
    "support.google.com",
    "help.fitbit.com",
    "nhs.uk",
    "cdc.gov",
)
WEB_PER_DAY = 5
CACHE_FOR = timedelta(days=1)
MAX_QUERY_CHARS = 200
MAX_ANSWER_CHARS = 600

EMAIL = re.compile(r"\S+@\S+")
PERSONAL = re.compile(r"\b(?:i|i'm|im|me|my|mine|we|our)\b", re.IGNORECASE)
# Beyond the verifier's list: what a person might ask the web about themselves.
HEALTH_WORDS = re.compile(
    r"\b(symptoms?|cure|treat\w*|side effects?|dose|doses|supplements?|vitamins?|pills?|"
    r"diet\w*|weight loss|lose weight|fasting|diabet\w*|cholesterol|blood pressure|cancer|"
    r"pregnan\w*|anxiety|adhd|allerg\w*|melatonin|drugs?)\b",
    re.IGNORECASE,
)
LINK = re.compile(r"\(?\[([^\]]*)\]\(https?://[^)]*\)\)?|\(?https?://\S+\)?")

Sessions = Callable[[], AbstractContextManager[Session]]


class LookupRefused(ValueError):
    """A query that may not be sent; the message is safe to show to the model."""


def query_problem(query: str) -> str | None:
    """Why this query may not leave the app, or None."""
    if EMAIL.search(query) or PERSONAL.search(query):
        return "A search must be general and say nothing about the person."
    if MEDICAL.search(query) or HEALTH_WORDS.search(query):
        return "Patterns does not look up medical questions."
    if reads_like_instruction(query):
        return "This is not a search."
    return None


def allowed(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return any(host == domain or host.endswith(f".{domain}") for domain in ALLOWED_DOMAINS)


def _plain(text: str) -> str:
    """Web text without links: a link in a reply reads like an instruction when quoted back."""
    return LINK.sub(lambda match: match.group(1) or "", text)


@dataclass(frozen=True)
class FoodData:
    """The USDA FoodData Central search API."""

    api_key: str
    http: httpx2.Client

    @classmethod
    def from_settings(cls, settings) -> "FoodData | None":
        key = settings.fdc_api_key.get_secret_value().strip() if settings.fdc_api_key else ""
        return cls(key, httpx2.Client(timeout=FDC_TIMEOUT_S)) if key else None

    def search(self, query: str) -> list[dict]:
        """The best matches, each with its values per 100 g; [] when none or on any failure."""
        params = {
            "api_key": self.api_key,
            "query": query,
            "dataType": FDC_TYPES,
            "pageSize": MAX_FOODS,
        }
        try:
            response = self.http.get(FDC_URL, params=params)
            response.raise_for_status()
            foods = response.json().get("foods", [])
        except (httpx2.HTTPError, ValueError, AttributeError):
            return []  # the error text holds the URL, and so the key: never pass it on
        found = []
        for food in foods[:MAX_FOODS] if isinstance(foods, list) else ():
            if not isinstance(food, dict):
                continue
            values = {
                NUTRIENTS[n["nutrientId"]]: n.get("value")
                for n in food.get("foodNutrients", ())
                if n.get("nutrientId") in NUTRIENTS
            }
            if food.get("description") and "energy_kcal" in values:
                found.append({"food": clean(food["description"], 120), "per_100g": values})
        return found


@dataclass
class Outside:
    """One person's way out, for one answer."""

    sessions: Sessions
    user_id: uuid.UUID
    now: datetime
    day_start: datetime
    food_data: FoodData | None = None

    def _cached(self, kind: str, query: str) -> dict | None:
        with self.sessions() as db:
            return db.scalar(
                select(OutsideLookup.answer)
                .where(
                    OutsideLookup.kind == kind,
                    OutsideLookup.query == query,
                    OutsideLookup.created_at >= self.now - CACHE_FOR,
                )
                .order_by(OutsideLookup.created_at.desc())
                .limit(1)
            )

    def _save(self, kind: str, query: str, answer: dict, cost_usd: float) -> None:
        with self.sessions() as db:
            db.add(
                OutsideLookup(
                    user_id=self.user_id,
                    kind=kind,
                    query=query,
                    answer=answer,
                    cost_usd=cost_usd,
                    created_at=self.now,
                )
            )

    def _web_used_today(self) -> int:
        with self.sessions() as db:
            return db.scalar(
                select(func.count())
                .select_from(OutsideLookup)
                .where(
                    OutsideLookup.user_id == self.user_id,
                    OutsideLookup.kind == "web",
                    OutsideLookup.created_at >= self.day_start,
                )
            )

    def food(self, query: str, grams: float | None = None) -> dict:
        """Food values with their source, and scaled to `grams` by code when given."""
        text = _query(query)
        if self.food_data is None:
            return {"error": "Food data is not set up."}
        result = self._cached("food", text)
        if result is None:
            foods = self.food_data.search(text)
            if not foods:
                return {"error": "Nothing found."}
            result = {"foods": foods, "source": FDC_SOURCE, "domain": FDC_DOMAIN}
            self._save("food", text, result, 0.0)
        if grams is not None and 0 < grams <= MAX_GRAMS:
            for food in result["foods"]:
                food[f"for_{grams:g}g"] = {
                    name: round(value * grams / 100, 1)
                    for name, value in food["per_100g"].items()
                    if value is not None
                }
        return result

    def web(self, llm: LLM, query: str, budget: Budget) -> dict:
        """A short answer from allowlisted sites, or an error; the search is charged to `budget`."""
        text = _query(query)
        if (result := self._cached("web", text)) is not None:
            return result
        if self._web_used_today() >= WEB_PER_DAY:
            return {"error": "Today's web lookups are used up."}
        try:
            found = llm.search(text, ALLOWED_DOMAINS, budget=budget)
        except (LLMError, BudgetExceeded):
            return {"error": "The lookup failed."}
        sources = [url for url in found.urls if allowed(url)]
        answer = clean(_plain(found.text), MAX_ANSWER_CHARS)
        result = {"error": "Nothing found on the allowed sites."}
        if sources and answer and not reads_like_instruction(answer):
            host = (urlparse(sources[0]).hostname or "").removeprefix("www.")
            result = {"answer": answer, "source": host, "domain": host}
        self._save("web", text, result, found.cost_usd)
        return result


def _query(query: str) -> str:
    text = " ".join(clean(query, MAX_QUERY_CHARS).casefold().split())
    if not text:
        raise LookupRefused("A search needs words.")
    if problem := query_problem(text):
        raise LookupRefused(problem)
    return text
