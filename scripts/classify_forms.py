"""Phase 0 helper: classify the blank forms in eval/incoming/ (not part of the app).

For every PDF it reports the page count, the number of form widgets, the average number of
extracted text characters per page, and a type:

    fillable  at least one form widget (AcroForm)
    flat      no widgets, and on average >= 50 text characters per page
    scanned   otherwise

It also flags files that fail to open or are encrypted, pages with no text layer, and text that
looks garbled (possibly a legacy non-Unicode Hindi font such as Kruti Dev). The garbled-text
check is a heuristic for a human to verify, not a verdict.

Usage (PyMuPDF is a dev dependency of the backend project):

    uv run --project backend python scripts/classify_forms.py [FOLDER] [--json]
"""

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pymupdf

FLAT_MIN_CHARS_PER_PAGE = 50

# Garbled-text heuristics (see _garbled_reasons).
# Letters from Latin-1 Supplement / Latin Extended-A/B (U+00C0-U+024F, e.g. runs of O-umlaut
# and u-umlaut in place of Hindi words): legacy Hindi fonts map Devanagari glyphs onto these.
MOJIBAKE_MIN_CHARS = 20
MOJIBAKE_MIN_SHARE = 0.02
# Kruti Dev-style tokens: ASCII letters with punctuation inside a word ("[kkrk", "gsrq%", "k;")
# because those fonts map Devanagari glyphs onto ASCII punctuation.
KRUTI_TOKEN = re.compile(r"[A-Za-z]*[\[\]{};%`~|][A-Za-z]+|[A-Za-z]+[\[\]{}%`~|]")
KRUTI_MIN_TOKENS = 15
KRUTI_MIN_SHARE = 0.03


@dataclass
class FormReport:
    file: str
    pages: int | None = None
    widgets: int | None = None
    avg_chars_per_page: float | None = None
    type: str | None = None
    flags: list[str] = field(default_factory=list)


def _is_mojibake_letter(char: str) -> bool:
    return 0x00C0 <= ord(char) <= 0x024F and unicodedata.category(char).startswith("L")


def _garbled_reasons(text: str) -> list[str]:
    reasons: list[str] = []
    letters = [c for c in text if c.isalpha()]
    if letters:
        mojibake = sum(1 for c in letters if _is_mojibake_letter(c))
        if mojibake >= MOJIBAKE_MIN_CHARS and mojibake / len(letters) >= MOJIBAKE_MIN_SHARE:
            reasons.append(f"{mojibake} Latin-extended letters mixed into the text")
    tokens = text.split()
    if tokens:
        kruti = sum(1 for token in tokens if KRUTI_TOKEN.search(token))
        if kruti >= KRUTI_MIN_TOKENS and kruti / len(tokens) >= KRUTI_MIN_SHARE:
            reasons.append(f"{kruti} words with punctuation inside (Kruti Dev-style)")
    return reasons


def classify(path: Path) -> FormReport:
    report = FormReport(file=path.name)
    try:
        doc = pymupdf.open(path)
    except Exception as exc:  # corrupt or not a PDF
        report.flags.append(f"open failed ({type(exc).__name__})")
        return report

    with doc:
        if doc.needs_pass:
            report.flags.append("encrypted (password required, not analysed)")
            return report
        if doc.is_encrypted:
            report.flags.append("encrypted (opens without a password)")

        report.pages = doc.page_count
        widgets = 0
        chars = 0
        texts: list[str] = []
        pages_without_text = 0
        for page in doc:
            widgets += sum(1 for _ in page.widgets())
            text = page.get_text()
            texts.append(text)
            page_chars = sum(1 for c in text if not c.isspace())
            chars += page_chars
            if page_chars == 0:
                pages_without_text += 1

    report.widgets = widgets
    report.avg_chars_per_page = round(chars / report.pages, 1) if report.pages else 0.0
    if widgets > 0:
        report.type = "fillable"
    elif report.avg_chars_per_page >= FLAT_MIN_CHARS_PER_PAGE:
        report.type = "flat"
    else:
        report.type = "scanned"

    if pages_without_text:
        report.flags.append(f"no text layer on {pages_without_text}/{report.pages} pages")
    garbled = _garbled_reasons("\n".join(texts))
    if garbled:
        report.flags.append("garbled text, possible legacy Hindi font: " + "; ".join(garbled))
    return report


def _markdown(reports: list[FormReport]) -> str:
    lines = [
        "| File | Pages | Widgets | Avg chars/page | Type | Flags |",
        "|---|--:|--:|--:|---|---|",
    ]
    for r in reports:
        cells = [
            r.file,
            "" if r.pages is None else str(r.pages),
            "" if r.widgets is None else str(r.widgets),
            "" if r.avg_chars_per_page is None else f"{r.avg_chars_per_page:.1f}",
            r.type or "",
            "; ".join(r.flags),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    counts: dict[str, int] = {}
    for r in reports:
        key = r.type or "not analysed"
        counts[key] = counts.get(key, 0) + 1
    lines.append("")
    lines.append(
        "Counts: "
        + ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        + f" (total {len(reports)})"
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("folder", nargs="?", default="eval/incoming", type=Path)
    parser.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    args = parser.parse_args(argv)

    paths = sorted(p for p in args.folder.iterdir() if p.suffix.lower() == ".pdf")
    if not paths:
        sys.stderr.write(f"no PDFs found in {args.folder}\n")
        return 1
    reports = [classify(path) for path in paths]
    if args.json:
        sys.stdout.write(json.dumps([asdict(r) for r in reports], indent=2) + "\n")
    else:
        sys.stdout.write(_markdown(reports))
    return 0


if __name__ == "__main__":
    sys.exit(main())
