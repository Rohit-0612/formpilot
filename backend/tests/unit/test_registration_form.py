"""A registration form end to end (Phase 5, decision P5-D8): frontend -> understanding (rules,
the model scripted) -> match -> questions -> answers, on the synthetic fixture
`flat_registration`. No real form or person is used."""

import json
import uuid
from datetime import UTC, datetime

import pymupdf

from app.frontends import flat
from app.frontends.detect import detect
from app.ir.models import FieldKind, FieldStatus, FormIR, ValueSource
from app.ir.semantic_types import SemanticType as T
from app.llm.fake import FakeProvider
from app.llm.provider import LLMRequest
from app.passes import answers, fit, match, understand, validate
from app.passes.answers import Answer
from app.passes.context import PassContext
from app.passes.questions import CHOICES, TABLE_ROW, InputKind, plan
from app.validators.dates import date_format_for
from tests.fixtures import pdfs

NOW = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
PROFILE = {
    "first_name": "Asha",
    "last_name": "Verma",
    "father_name": "Ravi Verma",
    "date_of_birth": "1998-03-07",
    "passing_year": "2016",
    "percentage_or_cgpa": "88",
}
INSTRUCTION = "Please fill in CAPITAL LETTERS only."


def _other(request: LLMRequest) -> str:
    """The model types every field it is asked about as `other`, unsure."""
    fields = json.loads(request.user.split("\n\n")[0])["fields"]
    items = [{"id": f["id"], "semantic_type": "other", "confidence": 0.5} for f in fields]
    return json.dumps({"fields": items})


def _ctx(profile: dict[str, str]) -> PassContext:
    return PassContext(clock=lambda: NOW, provider=FakeProvider(_other), profile=profile)


def _filled(profile: dict[str, str]) -> FormIR:
    with pymupdf.open("pdf", pdfs.get("flat_registration").data) as doc:
        ir = flat.run(doc, detect(doc), uuid.uuid4(), NOW)
    ctx = _ctx(profile)
    return fit.run(validate.run(match.run(understand.run(ir, ctx), ctx), ctx), ctx)


def _by_label(ir: FormIR, label: str) -> list:
    return [f for f in ir.fields if f.label_text == label]


def test_no_question_asks_about_the_instruction() -> None:
    ir = _filled({})

    for q in plan(ir, match.policy_for(_ctx({}))):
        assert INSTRUCTION not in (q.prompt, q.form_text)
        assert all(INSTRUCTION not in (p.label, p.form_label) for p in q.parts)


def test_name_parts_and_date_parts_are_filled_from_the_profile() -> None:
    ir = _filled(PROFILE)

    (first,) = _by_label(ir, "FIRST NAME")
    (last,) = _by_label(ir, "LAST NAME")
    assert (first.semantic_type, first.value) == (T.FIRST_NAME, "Asha")
    assert (last.semantic_type, last.value) == (T.LAST_NAME, "Verma")
    assert fit.printed(first) == "ASHA"  # the page asks for capitals
    dob = _by_label(ir, "4. Date of Birth")
    assert [(f.date_part, f.value, f.status) for f in dob] == [
        ("day", "07", FieldStatus.FILLED),
        ("month", "03", FieldStatus.FILLED),
        ("year", "1998", FieldStatus.FILLED),
    ]
    assert all(r.ok for f in dob for r in f.validations)


def test_no_table_row_is_filled_from_the_profile() -> None:
    """The profile has one passing year and one percentage; the table has three classes."""
    ir = _filled(PROFILE)

    rows = [f for f in ir.fields if f.group_id is not None and f.kind is FieldKind.TEXT]
    assert len(rows) == 9
    assert {f.semantic_type for f in _by_label(ir, "Year of Passing")} == {T.PASSING_YEAR}
    assert all(f.value is None and f.status is FieldStatus.NEEDS_INPUT for f in rows)


def test_each_table_row_is_one_card_and_tick_rows_one_choice() -> None:
    ir = _filled(PROFILE)

    questions = plan(ir, match.policy_for(_ctx(PROFILE)))

    cards = [q for q in questions if q.group == TABLE_ROW]
    assert [q.prompt for q in cards] == [
        "12. Previous Education \u2013 Class X",
        "12. Previous Education \u2013 Class XII",
        "12. Previous Education \u2013 Graduation",
    ]
    assert all(
        [p.label for p in q.parts] == ["Board/University", "Year of Passing", "% / CGPA"]
        for q in cards
    )
    assert not any(q.can_save for q in cards)
    choices = [q for q in questions if q.group == CHOICES]
    assert [(q.form_text or q.prompt) for q in choices] == [
        "Which applies to you for “5. Gender”?",
        "Which applies to you for “13. Hostel Required?”?",
    ]
    assert [c.label for c in choices[1].parts[0].choices] == ["Yes", "No"]


def test_one_date_question_fills_the_three_boxes() -> None:
    ir = _filled({})
    ctx = _ctx({})
    questions = plan(ir, match.policy_for(ctx))

    (dob,) = [q for q in questions if any(p.semantic_type is T.DATE_OF_BIRTH for p in q.parts)]
    assert dob.parts[0].input is InputKind.DATE and len(dob.field_ids) == 3
    answered = answers.run(ir, ctx, [Answer(question_id=dob.id, value="07/03/1998")], questions)

    by_id = {f.id: f for f in answered.fields}
    assert [by_id[i].value for i in dob.field_ids] == ["07", "03", "1998"]


def test_a_choice_ticks_one_box_of_the_row() -> None:
    ir = _filled({})
    ctx = _ctx({})
    questions = plan(ir, match.policy_for(ctx))
    (hostel,) = [q for q in questions if "Hostel" in q.prompt]
    yes, no = hostel.parts[0].field_ids

    answered = answers.run(ir, ctx, [Answer(question_id=hostel.id, value=yes)], questions)

    by_id = {f.id: f for f in answered.fields}
    assert (by_id[yes].value, by_id[yes].status) == ("Yes", FieldStatus.FILLED)
    assert (by_id[no].value, by_id[no].status) == (None, FieldStatus.FILLED)
    assert by_id[yes].value_source is ValueSource.USER_ANSWER


def test_a_two_digit_year_box_gets_two_digits() -> None:
    (year,) = [f for f in _filled({}).fields if f.date_part == "year"]

    assert date_format_for(year.model_copy(update={"max_chars": 2})) == "%y"
    assert date_format_for(year) == "%Y"
