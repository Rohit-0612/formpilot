"""Phrases that mark fields FormPilot never fills (decision P3-D1), matched in printed text.

Shared by the flat frontend (the text of a field's enclosing box) and the understanding pass
(label and heading). English phrases match exactly (after cleaning). Hindi phrases also match
when a legacy-font text layer has garbled the conjuncts ("कार्यालय" extracted as "कायाथलय"):
word by word, each word of similar length and at least 75 % alike. English is not matched
loosely: "our office uses" must not count.

Format hints (Phase 5): `asks_upper_case` for a field's own label ("Name (Block Letters)"),
`instructs_upper_case` for a page instruction ("Please fill up in BLOCK letters only"); a negated
hint ("Signatures should not be in capital letters") never counts.

`readable_english` decides whether a text may be shown as the main text of a question (decision
P5-D6): Hindi and text garbled into other scripts or symbols never is.
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
UPPER_CASE_PHRASES = (
    "capital letters",
    "capital letter",
    "block letters",
    "block capitals",
    "in capitals",
    "upper case",
    "uppercase",
    "बड़े अक्षरों",
    "कैपिटल अक्षरों",
)
# A page instruction is a sentence telling the reader how to fill in the form. "ĥll": a text
# layer that extracts the "fi" ligature as "Ĥ" (dev form #01).
_INSTRUCTION_PREFIXES = ("fill", "ĥll", "writ", "complet", "entries", "भर", "लिख")
_NEGATIONS = frozenset({"not", "never", "don't", "nahi", "नहीं", "मत"})
WORD_SIMILARITY = 0.75
MAX_LENGTH_GAP = 2
# Besides printable ASCII, an English question may hold typographic quotes, dashes and ellipses.
_TYPOGRAPHIC = frozenset("\u2018\u2019\u201c\u201d\u2013\u2014\u2026")


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


def asks_upper_case(text: str | None) -> bool:
    """The text asks for capital letters and does not say "not"."""
    if not mentions(text, UPPER_CASE_PHRASES):
        return False
    return not _NEGATIONS & set(clean_text(text or "").split())


def instructs_upper_case(line: str | None) -> bool:
    """A page instruction to write in capital letters (has a verb such as "fill" or "write")."""
    words = clean_text(line or "").split()
    return asks_upper_case(line) and any(w.startswith(_INSTRUCTION_PREFIXES) for w in words)


def readable_english(text: str | None) -> bool:
    """Printable ASCII (and typographic punctuation) with at least one word: no Devanagari, no
    other script, no replacement or private-use characters. Scrambled English word order is not
    detected."""
    if text is None or not text.strip():
        return False
    if any(not (ch.isascii() and ch.isprintable()) and ch not in _TYPOGRAPHIC for ch in text):
        return False
    return any(ch.isalpha() for ch in text)
