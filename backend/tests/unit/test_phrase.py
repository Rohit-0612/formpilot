"""Phrase pass (decisions P5-D6, P5-D9): English questions for the fields asked about the form's
own text. FakeProvider only; the registration fixture is synthetic."""

import json
from datetime import timedelta

from app.ir.models import FieldStatus, FormIR
from app.llm.fake import FakeProvider
from app.llm.provider import LLMError, LLMRequest
from app.passes import phrase
from app.passes.context import PassContext
from app.passes.match import policy_for
from app.passes.questions import CHOICES, TABLE_ROW, plan
from tests.unit.test_registration_form import NOW, PROFILE, _filled

CTX = PassContext(clock=lambda: NOW)


def _fields(request: LLMRequest) -> list[dict]:
    return json.loads(request.user.split("\n\n")[0])["fields"]


def _asking(request: LLMRequest) -> str:
    """Asks "What goes in <label> (<row>)?" for every field."""
    questions = [
        {
            "id": f["id"],
            "question": f"What goes in {f['label']}{' for ' + f['row'] if f['row'] else ''}?",
        }
        for f in _fields(request)
    ]
    return json.dumps({"questions": questions})


def _ctx(script: object, **extra: object) -> PassContext:
    return PassContext(clock=lambda: NOW, provider=FakeProvider(script), **extra)  # type: ignore[arg-type]


def test_only_fields_asked_about_the_form_text_are_phrased() -> None:
    ir = _filled(PROFILE)

    items = phrase.items(ir, CTX)

    ids = {i["id"] for i in items}
    by_id = {f.id: f for f in ir.fields}
    assert all(by_id[i].status is FieldStatus.NEEDS_INPUT for i in ids)
    assert not any(by_id[i].label_text in ("FIRST NAME", "4. Date of Birth") for i in ids)
    rows = [i for i in items if i["row"] is not None]
    assert len(rows) == 9 and {i["row"] for i in rows} == {"Class X", "Class XII", "Graduation"}
    choices = [i for i in items if i["kind"] == "choice"]
    assert [(c["label"], c["options"]) for c in choices] == [
        ("5. Gender", ["Male", "Female", "Other"]),
        ("13. Hostel Required?", ["Yes", "No"]),
    ]


def test_requests_hold_form_text_only() -> None:
    seen: list[str] = []

    def script(request: LLMRequest) -> str:
        seen.append(request.user)
        return _asking(request)

    phrase.run(_filled(PROFILE), _ctx(script))

    assert seen and not any(value in user for user in seen for value in PROFILE.values())


def test_questions_land_on_the_fields_and_in_the_plan() -> None:
    ir = phrase.run(_filled({}), _ctx(_asking))

    questions = plan(ir, policy_for(CTX))

    card = next(q for q in questions if q.group == TABLE_ROW)
    assert card.parts[0].label == "What goes in Board/University for Class X?"
    choice = next(q for q in questions if q.group == CHOICES)
    assert choice.prompt == "What goes in 5. Gender?"
    assert all(e.change == "question_text (llm)" for e in ir.trace if e.pass_name == "phrase")


def test_a_question_that_is_not_english_is_asked_again_then_dropped() -> None:
    calls: list[int] = []

    def script(request: LLMRequest) -> str:
        calls.append(1)
        return json.dumps(
            {"questions": [{"id": f["id"], "question": "आपका नाम?"} for f in _fields(request)]}
        )

    ir = phrase.run(_filled({}), _ctx(script))

    assert len(calls) == 2  # one retry
    assert all(f.question_text is None for f in ir.fields)
    assert any("LLM retried" in e.change for e in ir.trace)


def test_a_failing_model_leaves_the_fields_unphrased() -> None:
    def script(request: LLMRequest) -> str:
        raise LLMError("down")

    ir = phrase.run(_filled({}), _ctx(script))

    assert all(f.question_text is None for f in ir.fields)
    assert any("LLM failed" in e.change for e in ir.trace)


def test_no_batch_after_the_deadline() -> None:
    def script(request: LLMRequest) -> str:
        raise AssertionError("no call after the deadline")

    ir = phrase.run(_filled({}), _ctx(script, deadline=NOW - timedelta(seconds=1)))

    assert any(e.change == "LLM time budget used up" for e in ir.trace)


def test_without_a_model_nothing_changes_but_the_trace() -> None:
    before: FormIR = _filled({})

    after = phrase.run(before, CTX)

    assert after.fields == before.fields
    assert after.trace[-1].change == "no LLM provider"
