"""Free-text address eval (eval/address_eval.py) with a scripted model. No real address."""

import json
from pathlib import Path

import pytest

from app.llm.cache import CachedProvider
from app.llm.fake import FakeProvider
from app.llm.provider import LLMRequest
from eval import address_eval, run_eval

ITEMS = [
    {
        "id": "a01",
        "text": "Flat 4, Rose Villa, MG Road, Pune 411 001",
        "expected": {
            "current_address_line1": "Flat 4, Rose Villa, MG Road",
            "current_address_line2": None,
            "current_city": "Pune",
            "current_state": None,
            "current_pincode": "411001",
        },
    },
    {
        "id": "a02",
        "text": "12 Park Street, Ballygunge, Kolkata 700019",
        "expected": {
            "current_address_line1": "12 Park Street",
            "current_address_line2": "Ballygunge",
            "current_city": "Kolkata",
            "current_state": None,
        },
    },
]
ANSWERS = {
    # case, spaces and punctuation differ but count as right; the PIN code by its digits
    "a01": {"current_address_line1": "flat 4 rose villa mg road", "current_address_line2": None,
            "current_city": "PUNE", "current_state": None, "current_pincode": "411001"},
    # line 2 moved into line 1 (right when joined), and an invented state
    "a02": {"current_address_line1": "12 Park Street, Ballygunge", "current_address_line2": None,
            "current_city": "Kolkata", "current_state": "West Bengal"},
}  # fmt: skip


def _model(request: LLMRequest) -> str:
    text = json.loads(request.user.split("\n\n")[0])["text"]
    item = next(i for i in ITEMS if i["text"] == text)
    return json.dumps(ANSWERS[item["id"]])  # type: ignore[index]


def test_metrics_normalise_join_lines_and_count_invented_values() -> None:
    m = address_eval.metrics(address_eval.evaluate(ITEMS, FakeProvider(_model)))

    assert (m["all_parts_right"], m["all_parts_right_lines_joined"]) == (1, 1)
    assert m["per_part"]["city"] == {"right": 2, "total": 2, "accuracy": 1.0}  # type: ignore[index]
    assert m["per_part"]["state"]["right"] == 1  # type: ignore[index]
    # expected empty: a01's line 2 and state, a02's state; the model invented a02's state
    assert (m["invented_where_empty"], m["expected_empty"]) == (1, 3)
    assert (m["values_not_in_text"], m["values_given"]) == (1, 6)  # "West Bengal"


def test_a_replay_that_misses_the_cache_is_refused(tmp_path: Path) -> None:
    provider = CachedProvider(FakeProvider(_model), tmp_path, "replay")

    with pytest.raises(run_eval.EvalError, match="not in the cache"):
        address_eval.evaluate(ITEMS, provider)


def test_the_report_lists_wrong_parts_and_discloses_the_dataset() -> None:
    results = address_eval.evaluate(ITEMS, FakeProvider(_model))
    data = address_eval.report(results, "fake:fake", "2026-10-27T00:00:00+00:00")

    assert [w["id"] for w in data["wrong"]] == ["a02"]  # type: ignore[index]
    assert address_eval.DISCLOSURE in address_eval.markdown(data)


def test_the_dataset_is_well_formed() -> None:
    items = address_eval.load()

    assert len(items) == 30
    for item in items:
        expected: dict[str, str | None] = item["expected"]  # type: ignore[assignment]
        text = str(item["text"])
        for key, value in expected.items():
            if value is not None and not key.endswith("_pincode"):
                assert address_eval.norm(key, value) in (address_eval.norm("text", text) or "")
