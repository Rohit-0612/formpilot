"""Free-text address eval (Phase 5): how well the answers pass splits a one-line address into the
address parts (prompt answers_v1.md), on 30 synthetic addresses (eval/addresses/dev.json,
Claude-written, frozen).

    make eval-address PROVIDER=groq MODEL=openai/gpt-oss-120b   # replays the recorded answers
    make eval-address PROVIDER=ollama MODEL=qwen3:8b RECORD=1     # asks the model and records

Values are compared after normalising case, spaces and punctuation; a PIN code by its digits.
- **All parts right**: addresses whose every part is right; also with the two address lines
  joined, since where line 1 ends and line 2 starts is often a matter of taste.
- **Per-part accuracy**.
- **Invented values**: parts filled where the text holds nothing for them (of the parts expected
  empty), and values that are not in the text at all (of the values given). The prompt forbids
  both.

Model answers go through a record / replay cache (eval/llm_cache/answers/); a replay that misses
it is refused. A unit test replays the committed recordings in CI.
"""

import argparse
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.config import GroqSettings
from app.ir.semantic_types import SemanticType
from app.llm.cache import CachedProvider, CacheMode
from app.llm.groq import GroqProvider
from app.llm.ollama import OllamaProvider
from app.llm.provider import LLMProvider
from app.logging import configure_logging
from app.passes.answers import PROMPT_FILE, split_free_text
from eval import run_eval
from eval.labelling.schema import REPO_ROOT
from eval.labelling.tasks import detector_version

DATASET = REPO_ROOT / "eval" / "addresses" / "dev.json"
CACHE_DIR = REPO_ROOT / "eval" / "llm_cache" / "answers"
DISCLOSURE = (
    "Addresses: synthetic, with the expected split written by Claude Code (claude-opus-5-5) by "
    "the rules of the prompt, not by a human."
)
_PUNCTUATION = re.compile(r"[,.;:\-/]+")
_LINES = ("address_line1", "address_line2")


@dataclass(frozen=True)
class AddressResult:
    id: str
    text: str
    expected: dict[str, str | None]
    got: dict[str, str] | None  # None: the model's answer was unusable twice


def load(path: Path = DATASET) -> list[dict[str, object]]:
    return json.loads(path.read_text())["items"]


def evaluate(items: Sequence[Mapping[str, object]], provider: LLMProvider) -> list[AddressResult]:
    counting = run_eval._Counting(provider)
    results = []
    for item in items:
        expected: dict[str, str | None] = item["expected"]  # type: ignore[assignment]
        types = [SemanticType(key) for key in expected]
        split = split_free_text(str(item["text"]), types, counting)
        got = None if split is None else {t.value: v for t, v in split.items()}
        results.append(AddressResult(str(item["id"]), str(item["text"]), expected, got))
    replaying = isinstance(provider, CachedProvider) and provider.mode == "replay"
    if counting.errors and replaying:
        raise run_eval.EvalError(f"replay: {counting.errors} model requests are not in the cache")
    return results


def norm(key: str, value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    if key.endswith("_pincode"):
        return "".join(ch for ch in value if ch.isdigit())
    return " ".join(_PUNCTUATION.sub(" ", value.casefold()).split())


def _right(key: str, expected: str | None, got: Mapping[str, str]) -> bool:
    return norm(key, expected) == norm(key, got.get(key))


def _joined_lines(values: Mapping[str, str | None], keys: Sequence[str]) -> str | None:
    lines = [k for k in keys if k.endswith(_LINES)]
    return norm(lines[0], " ".join(v for k in lines if (v := values.get(k)))) if lines else None


def metrics(results: Sequence[AddressResult]) -> dict[str, object]:
    per_part: dict[str, list[int]] = {}
    all_right = all_right_joined = failed = 0
    expected_empty = invented_empty = given = not_in_text = 0
    for r in results:
        got = r.got or {}
        failed += r.got is None
        rights = {k: _right(k, v, got) for k, v in r.expected.items()}
        for key, ok in rights.items():
            part = key.split("_", 1)[1]
            per_part.setdefault(part, [0, 0])
            per_part[part][0] += ok
            per_part[part][1] += 1
        all_right += all(rights.values())
        keys = list(r.expected)
        lines_ok = _joined_lines(r.expected, keys) == _joined_lines(got, keys)
        all_right_joined += lines_ok and all(
            ok for k, ok in rights.items() if not k.endswith(_LINES)
        )
        text_norm = norm("text", r.text) or ""
        text_digits = "".join(ch for ch in r.text if ch.isdigit())
        for key, value in r.expected.items():
            if value is None:
                expected_empty += 1
                invented_empty += norm(key, got.get(key)) is not None
        for key, value in got.items():
            if norm(key, value) is None:
                continue
            given += 1
            haystack = text_digits if key.endswith("_pincode") else text_norm
            not_in_text += norm(key, value) not in haystack  # type: ignore[operator]
    n = len(results)
    return {
        "addresses": n,
        "failed": failed,
        "all_parts_right": all_right,
        "all_parts_right_rate": all_right / n if n else None,
        "all_parts_right_lines_joined": all_right_joined,
        "all_parts_right_lines_joined_rate": all_right_joined / n if n else None,
        "per_part": {
            part: {"right": right, "total": total, "accuracy": right / total}
            for part, (right, total) in sorted(per_part.items())
        },
        "invented_where_empty": invented_empty,
        "expected_empty": expected_empty,
        "values_not_in_text": not_in_text,
        "values_given": given,
    }


def _pct(value: object) -> str:
    return "—" if value is None else f"{100 * float(value):.1f} %"  # type: ignore[arg-type]


def markdown(data: Mapping[str, object]) -> str:
    m: Mapping[str, object] = data["metrics"]  # type: ignore[assignment]
    per_part: Mapping[str, Mapping[str, object]] = m["per_part"]  # type: ignore[assignment]
    lines = [
        f"# Free-text address eval — provider `{data['provider']}`",
        "",
        f"> **{DISCLOSURE}**",
        "",
        f"- Prompt `{data['prompt']}`; created {data['created_at']}; {m['addresses']} addresses"
        f"; unusable answers: {m['failed']}.",
        f"- **All parts right: {m['all_parts_right']} of {m['addresses']}** "
        f"({_pct(m['all_parts_right_rate'])}); with the two address lines joined: "
        f"{m['all_parts_right_lines_joined']} ({_pct(m['all_parts_right_lines_joined_rate'])}).",
        f"- **Invented values**: {m['invented_where_empty']} of {m['expected_empty']} parts "
        f"expected empty were filled; {m['values_not_in_text']} of {m['values_given']} values "
        "given are not in the text.",
        "",
        "| Part | Right | Accuracy |",
        "|---|--:|--:|",
    ]
    lines += [
        f"| {part} | {p['right']}/{p['total']} | {_pct(p['accuracy'])} |"
        for part, p in per_part.items()
    ]
    wrong: Sequence[Mapping[str, object]] = data["wrong"]  # type: ignore[assignment]
    if wrong:
        lines += ["", "## Addresses with a wrong part", ""]
        for w in wrong:
            lines.append(f"- `{w['id']}` {w['text']}: " + "; ".join(
                f"{k} expected {v['expected']!r}, got {v['got']!r}"
                for k, v in w["parts"].items()  # type: ignore[attr-defined]
            ))  # fmt: skip
    return "\n".join(lines) + "\n"


def report(results: Sequence[AddressResult], provider: str, created_at: str) -> dict[str, object]:
    wrong = []
    for r in results:
        got = r.got or {}
        bad = {
            k: {"expected": v, "got": got.get(k)}
            for k, v in r.expected.items()
            if not _right(k, v, got)
        }
        if bad:
            wrong.append({"id": r.id, "text": r.text, "parts": bad})
    return {
        "kind": "address",
        "provider": provider,
        "prompt": PROMPT_FILE.name,
        "created_at": created_at,
        "addresses": DISCLOSURE,
        "metrics": metrics(results),
        "wrong": wrong,
    }


def _provider(name: str, model: str, cache: CacheMode | None) -> LLMProvider:
    inner: LLMProvider
    if name == "groq":
        inner = GroqProvider(GroqSettings().groq_api_key, model)  # a replay sends nothing
    else:
        inner = OllamaProvider("http://localhost:11434", model, timeout_seconds=600)
    return inner if cache is None else CachedProvider(inner, CACHE_DIR, cache)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Free-text address eval (Phase 5).")
    parser.add_argument("--provider", choices=["ollama", "groq"], default="groq")
    parser.add_argument("--model", default="openai/gpt-oss-120b")
    parser.add_argument("--cache", choices=["record", "replay"], default="replay")
    args = parser.parse_args(argv)
    configure_logging("WARNING", json=False)

    provider = _provider(args.provider, args.model, args.cache)
    try:
        results = evaluate(load(), provider)
    except run_eval.EvalError as exc:
        print(f"eval refused: {exc}")  # noqa: T201 - CLI output
        return 1
    created = datetime.now(UTC).isoformat(timespec="seconds")
    data = report(results, f"{provider.name}:{provider.model}", created)
    slug = data["provider"].replace("/", "-").replace(":", "-")  # type: ignore[union-attr]
    commit = detector_version().removeprefix("flat@")
    stamp = created[:10].replace("-", "")
    base = run_eval.REPORTS_DIR / f"phase5-address-dev-{slug}-{stamp}-{commit}"
    base.with_suffix(".json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    base.with_suffix(".md").write_text(markdown(data), encoding="utf-8")
    m = data["metrics"]
    print(  # noqa: T201 - CLI output
        f"all parts right {m['all_parts_right']}/{m['addresses']}\n{base.with_suffix('.md')}"  # type: ignore[index]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
