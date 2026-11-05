"""Every knowledge card through the medical guard. Run from the repository root:
`PYTHONPATH=backend python eval/knowledge_guard.py`. Calls Jev (under $0.001); prints the count and
any card flagged, each of which needs rewording before it ships."""

from app.agent.guard import MAX_TEXTS, JevGuard
from app.agent.jev import JevClient
from app.agent.knowledge import load_cards
from app.config import settings

cards = load_cards()
guard = JevGuard(JevClient.from_settings(settings))
flagged, cost = [], 0.0
for i in range(0, len(cards), MAX_TEXTS):
    batch = cards[i : i + MAX_TEXTS]
    judgement = guard.judge([card.text for card in batch])
    cost += judgement.cost_usd
    flagged += [c.id for c, bad in zip(batch, judgement.flagged, strict=True) if bad]
print(f"{len(cards)} cards, {len(flagged)} flagged: {flagged}")
print(f"Jev cost: ${cost:.6f}")
