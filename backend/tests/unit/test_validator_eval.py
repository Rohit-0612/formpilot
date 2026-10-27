"""Validator eval (PLAN Phase 4 acceptance): the invalid inputs file is rejected at the expected
rate, and no persona value is falsely rejected. Uses the committed synthetic files only."""

import json

from eval import validator_eval
from eval.labelling.schema import REPO_ROOT


def test_invalid_inputs_are_caught_except_the_known_limits_and_personas_pass() -> None:
    data = validator_eval.evaluate(validator_eval.INVALID_INPUTS, REPO_ROOT / "eval" / "personas")
    inputs = json.loads(validator_eval.INVALID_INPUTS.read_text())["inputs"]
    # Expected misses: the vectors that say what a format rule cannot check.
    expected_misses = [
        {"semantic_type": i["semantic_type"], "why": i["why"]}
        for i in inputs
        if "is not checked" in i["why"]
    ]

    assert data["missed"] == expected_misses
    assert data["caught"] == len(inputs) - len(expected_misses)
    assert data["false_rejects"] == [] and data["persona_values_checked"] > 0
