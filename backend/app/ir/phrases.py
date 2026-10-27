"""Phrases that mark fields FormPilot never fills (decision P3-D1), matched in printed text.

Shared by the flat frontend (the text of a field's enclosing box) and the understanding pass
(label and heading). English phrases match exactly (after cleaning). Hindi phrases also match
when a legacy-font text layer has garbled the conjuncts ("कार्यालय" extracted as "कायाथलय"):
word by word, each word of similar length and at least 75 % alike. English is not matched
loosely: "our office uses" must not count.
"""

import unicodedata
from difflib import SequenceMatcher

OFFICE_USE_PHRASES = (
    "for office use",
    "office use only",
    "for official use",
    "for bank use",
    "bank use only",
    "karyalaya upyog",
    "कार्यालय उपयोग",
    "कार्यालय प्रयोग",
)
WORD_SIMILARITY = 0.75
MAX_LENGTH_GAP = 2


def clean_text(text: str) -> str:
    """Lower case; letters (any script, with their vowel signs), digits and apostrophes kept."""
    text = unicodedata.normalize("NFC", text.lower()).replace("\u2019", "'").replace("`", "'")
    chars = [ch if ch == "'" or unicodedata.category(ch)[0] in "LNM" else " " for ch in text]
    return " ".join("".join(chars).split())


def _devanagari(text: str) -> bool:
    return any("ऀ" <= ch <= "ॿ" for ch in text)


def _alike(word: str, wanted: str) -> bool:
    if abs(len(word) - len(wanted)) > MAX_LENGTH_GAP:
        return False
    return SequenceMatcher(None, word, wanted).ratio() >= WORD_SIMILARITY


def mentions(text: str | None, phrases: tuple[str, ...]) -> bool:
    cleaned = clean_text(text or "")
    if not cleaned:
        return False
    words = cleaned.split()
    for phrase in phrases:
        wanted = clean_text(phrase)
        if wanted in cleaned:
            return True
        if not _devanagari(wanted):
            continue
        parts = wanted.split()
        for start in range(len(words) - len(parts) + 1):
            window = words[start : start + len(parts)]
            if all(_alike(w, p) for w, p in zip(window, parts, strict=True)):
                return True
    return False


def mentions_office_use(text: str | None) -> bool:
    return mentions(text, OFFICE_USE_PHRASES)
