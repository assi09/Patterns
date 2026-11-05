"""Rules for text that comes from outside the code: memory, earlier turns, anything quoted to the
model. Shared by the context builder and the memory write path, and free of other imports so the
database layer can use it.
"""

import re

CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
# Text that reads like an instruction to the model, or points elsewhere.
INSTRUCTION_LIKE = re.compile(
    r"ignore (?:all |any )?(?:the )?(?:previous|prior|above|earlier) (?:instructions|messages)"
    r"|disregard (?:all |the )?(?:previous|prior|above)"
    r"|system prompt|developer message|you are now|new instructions"
    r"|^\s*(?:system|assistant|developer|user)\s*:"
    r"|<\|?/?(?:system|im_start|im_end)"
    r"|https?://|www\.",
    re.IGNORECASE | re.MULTILINE,
)


WORD = re.compile(r"[a-z0-9]+")
STEM = 5  # enough to match "nights" with "night" and "training" with "train"
COMMON = {"they", "their", "have", "want", "wants", "will", "this", "that", "with", "from"}


def stems(text: str) -> set[str]:
    """The words that say what a text is about, cut short so forms of a word match."""
    return {w[:STEM] for w in WORD.findall(text.casefold()) if len(w) >= 4 and w not in COMMON}


def clean(text: str | None, limit: int) -> str:
    """Without control characters and surrounding space, at most `limit` characters."""
    return CONTROL.sub(" ", text or "").strip()[:limit]


def reads_like_instruction(text: str) -> bool:
    return bool(INSTRUCTION_LIKE.search(text or ""))
