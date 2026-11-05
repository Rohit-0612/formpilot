"""Match pass (SPEC §6.3) and the precision-first fill policy (decision P4-D2). Synthetic data."""

import uuid
from datetime import UTC, datetime
from typing import Literal

import pytest

from app.ir.models import (
    BBox,
    Field,
    FieldGroup,
    FieldKind,
    FieldStatus,
    FormIR,
    Option,
    PageInfo,
    SourceKind,
    TextLayer,
    ValueSource,
)
from app.ir.semantic_types import SemanticType as T
from app.passes import match
from app.passes.context import PassContext
from app.passes.match import FillPolicy
from app.services.review import confirm_all

NOW = datetime(2026, 10, 27, 6, 0, tzinfo=UTC)
PROFILE = {
    "full_name": "Asha Verma",
    "first_name": "Asha",
    "last_name": "Verma",
    "date_of_birth": "1999-03-05",
    "phone_mobile": "9876543210",
    "gender": "Female",
    "pan": "ABCDE1234F",
}
# A looser policy than the default, so each test isolates one rule.
CTX = PassContext(
    clock=lambda: NOW, profile=PROFILE, fill_min_confidence=0.95, fill_once_per_form=False
)


def _f(
    i: int,
    t: T,
    method: Literal["rule", "llm", "user", "none"] = "rule",
    confidence: float = 0.95,
    **extra: object,
) -> Field:
    return Field(
        id=f"p0_f{i:03d}",
        kind=extra.pop("kind", FieldKind.TEXT),  # type: ignore[arg-type]
        native_name=None,
        label_text=extra.pop("label", None),  # type: ignore[arg-type]
        context_text=None,
        bbox=BBox(page=0, x0=10, y0=10 + 20 * i, x1=200, y1=24 + 20 * i),
        semantic_type=t,
        semantic_method=method,
        semantic_confidence=confidence,
        **extra,  # type: ignore[arg-type]
    )


def _ir(*fields: Field) -> FormIR:
    return FormIR(
        document_id=uuid.uuid4(),
        source_kind=SourceKind.FLAT_TEXT,
        pages=[PageInfo(width=595, height=842, text_layer=TextLayer.OK)],
        fields=list(fields),
    )


def test_rule_typed_fields_are_filled_from_the_profile() -> None:
    out = match.run(_ir(_f(0, T.FULL_NAME), _f(1, T.PHONE_MOBILE), _f(2, T.PAN)), CTX)

    assert [f.value for f in out.fields] == ["Asha Verma", "9876543210", "ABCDE1234F"]
    assert all(f.status is FieldStatus.FILLED for f in out.fields)
    assert all(f.value_source is ValueSource.PROFILE for f in out.fields)
    assert out.trace[0].change == "filled full_name (profile)"
    assert "Asha" not in out.model_dump_json(include={"trace"})


def test_llm_types_fill_only_at_or_above_the_confidence_floor() -> None:
    sure = _f(0, T.FULL_NAME, "llm", 0.95)
    unsure = _f(1, T.PHONE_MOBILE, "llm", 0.94)

    out = match.run(_ir(sure, unsure), CTX)

    assert out.fields[0].value == "Asha Verma"
    assert out.fields[1].value is None and out.fields[1].status is FieldStatus.NEEDS_INPUT


def test_rules_only_policy_never_fills_from_llm_types() -> None:
    out = match.run(_ir(_f(0, T.FULL_NAME, "llm", 1.0)), CTX, FillPolicy(min_llm_confidence=None))

    assert out.fields[0].value is None


def test_once_per_form_fills_only_the_first_person_field_of_a_type() -> None:
    policy = FillPolicy(once_per_form=frozenset({T.FULL_NAME}))

    out = match.run(_ir(_f(0, T.FULL_NAME), _f(1, T.FULL_NAME), _f(2, T.PAN)), CTX, policy)

    assert [f.value for f in out.fields] == ["Asha Verma", None, "ABCDE1234F"]


def test_derived_values_age_today_and_full_name_from_parts() -> None:
    ctx = PassContext(
        clock=lambda: NOW, profile={k: PROFILE[k] for k in PROFILE if k != "full_name"}
    )
    fields = [
        _f(0, T.AGE),
        _f(1, T.DATE_OF_FILLING, label="Date (DD-MM-YYYY)"),
        _f(2, T.FULL_NAME),
        _f(3, T.DATE_OF_BIRTH, label="Date of Birth"),
    ]

    out = match.run(_ir(*fields), ctx)

    assert [f.value for f in out.fields] == ["27", "27-10-2026", "Asha Verma", "05/03/1999"]
    assert [f.value_source for f in out.fields] == [
        ValueSource.DERIVED,
        ValueSource.DERIVED,
        ValueSource.DERIVED,
        ValueSource.PROFILE,
    ]


def test_choice_fields_pick_the_matching_option_or_stay_empty() -> None:
    letters = [Option(value="M", label="M"), Option(value="F", label="F")]
    words = [Option(value="1", label="Male"), Option(value="2", label="Female")]
    other = [Option(value="x", label="Transgender")]

    out = match.run(
        _ir(
            _f(0, T.GENDER, kind=FieldKind.CHOICE, options=letters),
            _f(1, T.GENDER, kind=FieldKind.CHOICE, options=words),
            _f(2, T.GENDER, kind=FieldKind.CHOICE, options=other),
        ),
        CTX,
    )

    assert [f.value for f in out.fields] == ["F", "2", None]


@pytest.mark.parametrize("kind", [FieldKind.CHECKBOX, FieldKind.RADIO])
def test_a_tick_is_never_set_from_the_profile(kind: FieldKind) -> None:
    """P5-D12: a tick box or radio is asked, even when the profile has a value for its type."""
    options = [Option(value="M", label="M"), Option(value="F", label="F")]
    rule = _f(0, T.GENDER, kind=kind, options=options)
    llm = _f(1, T.GENDER, "llm", 0.99, kind=kind, options=options)

    out = match.run(_ir(rule, llm), CTX)

    assert all(f.value is None and f.status is FieldStatus.NEEDS_INPUT for f in out.fields)
    assert all(e.pass_name != match.STAGE for e in out.trace)


def test_missing_profile_values_never_fill_and_other_types_are_asked() -> None:
    out = match.run(_ir(_f(0, T.FATHER_NAME), _f(1, T.OTHER), _f(2, T.UNKNOWN, "none", 0)), CTX)

    assert all(f.value is None and f.status is FieldStatus.NEEDS_INPUT for f in out.fields)


def test_never_fill_fields_and_existing_values_are_left_alone() -> None:
    signature = _f(0, T.SIGNATURE, no_fill_reason="signature", status=FieldStatus.SKIPPED)
    answered = _f(1, T.FULL_NAME, value="A. Verma", value_source=ValueSource.USER_ANSWER)

    out = match.run(_ir(signature, answered), CTX)

    assert out.fields == [signature, answered]


def test_the_default_policy_is_the_one_chosen_on_dev() -> None:
    """LLM confidence >= 0.99, person and date types once per form (P4-D2 tuning session)."""
    ctx = PassContext(clock=lambda: NOW, profile=PROFILE)
    fields = [
        _f(0, T.FULL_NAME, "llm", 0.99),
        _f(1, T.FULL_NAME, "llm", 1.0),  # a second name on the form: asked
        _f(2, T.PHONE_MOBILE, "llm", 0.98),  # not sure enough
        _f(3, T.PAN, "llm", 0.99),
    ]

    out = match.run(_ir(*fields), ctx)

    assert [f.value for f in out.fields] == ["Asha Verma", None, None, "ABCDE1234F"]


def test_once_per_form_counts_each_part_of_a_date_once() -> None:
    """P5-D8: DD | MM | YYYY of the first date of birth are filled, a second date is not."""
    policy = FillPolicy(once_per_form=frozenset({T.DATE_OF_BIRTH}))
    parts = [
        _f(i, T.DATE_OF_BIRTH, date_part=part, max_chars=width)
        for i, (part, width) in enumerate(
            [("day", 2), ("month", 2), ("year", 4), ("day", 2), ("month", 2), ("year", 4)]
        )
    ]

    out = match.run(_ir(*parts), CTX, policy)

    assert [f.value for f in out.fields] == ["05", "03", "1999", None, None, None]


def test_grouped_fields_are_never_filled_or_suggested() -> None:
    """P5-D8: a table row is one instance of many; a row of tick boxes is asked as a choice."""
    ir = FormIR(
        document_id=uuid.uuid4(),
        source_kind=SourceKind.FLAT_TEXT,
        pages=[PageInfo(width=595, height=842, text_layer=TextLayer.OK)],
        fields=[_f(0, T.FULL_NAME, group_id="p0_g000"), _f(1, T.FULL_NAME, "llm", 0.97)],
        groups=[FieldGroup(id="p0_g000", kind="table_row", label="Class X")],
    )
    ctx = PassContext(clock=lambda: NOW, profile=PROFILE, suggest_min_confidence=0.95)

    out = match.run(ir, ctx, FillPolicy())

    assert out.fields[0].value is None and out.fields[0].status is FieldStatus.NEEDS_INPUT
    assert out.fields[1].status is FieldStatus.SUGGESTED  # the same type outside a group


def _date(*parts: tuple[T, str, str, float]) -> list[Field]:
    """One date in DD | MM | YYYY boxes side by side: (type, part, method, confidence) each."""
    widths = {"day": 26.0, "month": 26.0, "year": 52.0}
    fields, x = [], 100.0
    for i, (t, part, method, confidence) in enumerate(parts):
        width = widths[part]
        f = _f(i, t, method, confidence, date_part=part, max_chars=int(width / 13))  # type: ignore[arg-type]
        box = BBox(page=0, x0=x, y0=100, x1=x + width, y1=113)
        fields.append(f.model_copy(update={"bbox": box}))
        x += width
    return fields


def test_a_date_with_a_part_left_empty_is_not_filled_at_all() -> None:
    """P5-D13 (dev form #03, section F): only the DD part was typed as the date of filling."""
    parts = _date(
        (T.DATE_OF_FILLING, "day", "rule", 0.95),
        (T.OTHER, "month", "llm", 0.7),
        (T.OTHER, "year", "llm", 0.7),
    )

    out = match.run(_ir(*parts), CTX)

    assert all(f.value is None and f.status is FieldStatus.NEEDS_INPUT for f in out.fields)
    assert out.fields[0].value_source is ValueSource.NONE
    changes = [e.change for e in out.trace if e.field_id == "p0_f000"]
    assert changes == [
        "filled date_of_filling (derived)",
        "not filled: the date's other parts have no value",
    ]


def test_a_date_with_every_part_known_is_filled_whole() -> None:
    parts = _date(*((T.DATE_OF_BIRTH, p, "rule", 0.95) for p in ("day", "month", "year")))

    out = match.run(_ir(*parts), CTX)

    assert [f.value for f in out.fields] == ["05", "03", "1999"]
    assert {f.status for f in out.fields} == {FieldStatus.FILLED}


def test_a_date_with_one_suggested_part_is_suggested_whole() -> None:
    """A date is confirmed and printed whole: "confirm all" must not print two of its parts."""
    parts = _date(
        (T.DATE_OF_BIRTH, "day", "rule", 0.95),
        (T.DATE_OF_BIRTH, "month", "llm", 0.96),
        (T.DATE_OF_BIRTH, "year", "rule", 0.95),
    )
    ctx = PassContext(clock=lambda: NOW, profile=PROFILE, suggest_min_confidence=0.95)

    out = match.run(_ir(*parts), ctx)

    assert [f.value for f in out.fields] == ["05", "03", "1999"]
    assert {f.status for f in out.fields} == {FieldStatus.SUGGESTED}


def _name_row(lead: tuple[T, str], *parts: tuple[T, str]) -> list[Field]:
    """A name in part boxes side by side: the lead (type, label), then (type, hint label) each."""
    fields, x = [], 72.0
    for i, (t, label) in enumerate((lead, *parts)):
        f = _f(i, t, label=label, max_chars=12)
        box = BBox(page=0, x0=x, y0=370, x1=x + 150, y1=383)
        fields.append(f.model_copy(update={"bbox": box}))
        x += 150
    return fields


def _guardian(name: str) -> PassContext:
    return PassContext(clock=lambda: NOW, profile={**PROFILE, "guardian_name": name})


def test_a_guardians_name_is_split_over_the_part_boxes_as_suggestions() -> None:
    """P5-D16 (dev form #01): never the whole name in the FIRST NAME part, never the applicant's
    own middle or last name in the guardian's row."""
    row = _name_row(
        (T.GUARDIAN_NAME, "9.Name of Guardian"),
        (T.MIDDLE_NAME, "MIDDLE NAME"),
        (T.LAST_NAME, "LAST NAME"),
    )

    out = match.run(_ir(*row), _guardian("Ramesh Verma"))

    assert [f.value for f in out.fields] == ["Ramesh", None, "Verma"]
    assert [f.status for f in out.fields] == [
        FieldStatus.SUGGESTED, FieldStatus.NEEDS_INPUT, FieldStatus.SUGGESTED,
    ]  # fmt: skip
    confirmed, _ = confirm_all(out, CTX)
    assert all(f.status is not FieldStatus.CONFIRMED for f in confirmed.fields)
    assert all("Ramesh" not in e.change and "Verma" not in e.change for e in out.trace)


def test_three_words_fill_a_row_with_three_parts() -> None:
    row = _name_row(
        (T.GUARDIAN_NAME, "FIRST NAME"), (T.MIDDLE_NAME, "MIDDLE NAME"), (T.LAST_NAME, "SURNAME")
    )
    row[0] = row[0].model_copy(update={"label_text": "Name of Guardian"})

    out = match.run(_ir(*row), _guardian("Ramesh Kumar Verma"))

    assert [f.value for f in out.fields] == ["Ramesh", "Kumar", "Verma"]


def test_an_unclear_split_leaves_the_parts_empty_and_asks() -> None:
    row = _name_row((T.GUARDIAN_NAME, "Name of Guardian"), (T.LAST_NAME, "LAST NAME"))

    for name in ("Ramesh Kumar Verma", "Ramesh", "Ramesh Kumar Singh Verma"):
        out = match.run(_ir(*row), _guardian(name))
        assert all(f.value is None and f.status is FieldStatus.NEEDS_INPUT for f in out.fields)


def test_the_applicants_own_name_parts_are_filled_as_before() -> None:
    row = _name_row(
        (T.FIRST_NAME, "FIRST NAME"), (T.MIDDLE_NAME, "MIDDLE NAME"), (T.LAST_NAME, "LAST NAME")
    )
    profile = {**PROFILE, "first_name": "Asha", "middle_name": "Kumari", "last_name": "Verma"}

    out = match.run(_ir(*row), PassContext(clock=lambda: NOW, profile=profile))

    assert [f.value for f in out.fields] == ["Asha", "Kumari", "Verma"]
    assert {f.status for f in out.fields} == {FieldStatus.FILLED}


@pytest.mark.parametrize(
    "label",
    [
        "with Registration No./ Enrolment number",
        "Roll No. of the student",
        "Application Number",
        "Membership ID",
        "Enrollment No",
    ],
)
def test_numbers_an_institution_gives_are_always_asked(label: str) -> None:
    """P5-D20 (dev form #25): a profile's enrolment number is another institution's."""
    typed = _f(0, T.ENROLLMENT_NUMBER, label=label)
    other_type = _f(1, T.PAN, label=label)
    profile = {**PROFILE, "enrollment_number": "EIT2014CS001", "pan": "ABCDE1234F"}

    out = match.run(_ir(typed, other_type), PassContext(clock=lambda: NOW, profile=profile))

    assert all(f.value is None and f.status is FieldStatus.NEEDS_INPUT for f in out.fields)


@pytest.mark.parametrize("label", ["Date of Admission", "Name of the applicant", "Mobile No."])
def test_other_labels_are_no_institution_number(label: str) -> None:
    from app.ir.phrases import names_institution_number

    assert not names_institution_number(label)
