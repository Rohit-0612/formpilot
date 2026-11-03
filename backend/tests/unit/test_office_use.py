"""Office-use fields are never filled (decision P3-D1), also when the text layer garbles the Hindi
heading ("कार्यालय" extracted as "कायाथलय", dev form #30) and when the note is in the field's
enclosing box rather than its nearest heading."""

import uuid
from datetime import UTC, datetime

import pymupdf
import pytest

from app.frontends import flat
from app.frontends.detect import detect
from app.ir.models import (
    BBox,
    Field,
    FieldKind,
    FieldStatus,
    FormIR,
    PageInfo,
    SourceKind,
    TextLayer,
)
from app.ir.phrases import filled_by_others, mentions_office_use
from app.passes import understand
from app.passes.context import PassContext
from tests.fixtures import pdfs

NOW = datetime(2026, 10, 27, tzinfo=UTC)


@pytest.mark.parametrize(
    "text",
    [
        "For Office Use Only",
        "(कार्यालय उपयोग हेतु)",
        "(कायाथलय उपयोग हेतु)",  # the garbled text layer of dev form #30
        "केवल कार्यालय प्रयोग हेतु",
        "Karyalaya upyog ke liye",
    ],
)
def test_office_use_phrases_match_also_when_garbled(text: str) -> None:
    assert mentions_office_use(text)


@pytest.mark.parametrize(
    "text",
    [
        "कार्य उपयोग",  # "work use": a shorter word
        "विद्यालय उपयोग हेतु",  # "for school use"
        "कार्यालय का पता",  # "office address"
        "Our office uses this address",  # English is matched exactly only
        "Office address",
        None,
        "",
    ],
)
def test_other_text_is_not_office_use(text: str | None) -> None:
    assert not mentions_office_use(text)


def _ir(context: str) -> FormIR:
    field = Field(
        id="p0_f000",
        kind=FieldKind.TEXT,
        native_name=None,
        label_text="नामाांकन सांख्या",
        context_text=context,
        bbox=BBox(page=0, x0=457, y0=80, x1=551, y1=100),
    )
    return FormIR(
        document_id=uuid.uuid4(),
        source_kind=SourceKind.FLAT_TEXT,
        pages=[PageInfo(width=595, height=842, text_layer=TextLayer.OK)],
        fields=[field],
    )


def test_understanding_marks_a_field_under_a_garbled_office_use_heading() -> None:
    out = understand.run(_ir("(कायाथलय उपयोग हेतु)"), PassContext(clock=lambda: NOW))

    assert out.fields[0].no_fill_reason == "office_use"
    assert out.fields[0].status is FieldStatus.SKIPPED


def test_the_frontend_marks_a_field_inside_an_office_use_box() -> None:
    fixture = pdfs.get("flat_office_use_box")
    with pymupdf.open("pdf", fixture.data) as doc:
        ir = flat.run(doc, detect(doc), uuid.uuid4(), NOW)

    name, reference = ir.fields
    assert reference.context_text == "APPLICANT DETAILS"  # the heading does not say it
    assert reference.no_fill_reason == "office_use"
    assert name.no_fill_reason is None
    out = understand.run(ir, PassContext(clock=lambda: NOW))
    assert out.fields[1].status is FieldStatus.SKIPPED and out.fields[0].no_fill_reason is None


def test_a_page_frame_is_not_an_office_use_box() -> None:
    """A frame around the whole page holding the words must not mark every field."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.draw_rect(pymupdf.Rect(20, 20, 575, 822), color=(0, 0, 0))
    page.insert_text((72, 120), "Name: " + "_" * 30, fontname="helv", fontsize=10)
    page.insert_text((72, 800), "For office use only: checked by", fontname="helv", fontsize=10)
    with doc:
        ir = flat.run(doc, detect(doc), uuid.uuid4(), NOW)

    assert ir.fields and all(f.no_fill_reason is None for f in ir.fields if f.label_text == "Name")


@pytest.mark.parametrize(
    "text",
    [
        "(To be filled by BPM/SPM or PLI-CPC Official and Handed Over to Insurant or as the case",
        "(to be filled by Admission Cell)",
        "To be filled in by the Bank",
        "To be completed by the Postmaster",
        "to be filled up by the issuing authority",
    ],
)
def test_parts_for_someone_other_than_the_applicant(text: str) -> None:
    """P5-D15: who fills the part is named after "by", and the applicant is not among them."""
    assert filled_by_others(text)


@pytest.mark.parametrize(
    "text",
    [
        "(to be completed by the Claimant & CBS Post Office)",  # the applicant fills it too
        "(To be filled in by the person legally entitled to the policy moneys)",
        "To be filled by the applicant",
        "Roll No. of the student",
        "The office will be closed",  # no "to be filled by"
        "Fields to be filled are marked *",  # no "by"
        None,
    ],
)
def test_parts_the_applicant_fills(text: str | None) -> None:
    assert not filled_by_others(text)


def _slip(heading: str, x: float | None = None) -> FormIR:
    """An applicant's line, then a heading (centred unless x is given) and two lines below it."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 120), "Applicant name: " + "_" * 30, fontname="helv", fontsize=10)
    width = pymupdf.get_text_length(heading, fontname="helv", fontsize=10)
    page.insert_text(
        (x if x is not None else (595 - width) / 2, 300), heading, fontname="helv", fontsize=10
    )
    page.insert_text((72, 360), "Date: " + "_" * 20, fontname="helv", fontsize=10)
    page.insert_text((300, 400), "Name: " + "_" * 25, fontname="helv", fontsize=10)
    with doc:
        return flat.run(doc, detect(doc), uuid.uuid4(), NOW)


def test_fields_below_a_centred_heading_for_an_official_are_never_filled() -> None:
    """P5-D15 (dev form #41): the acknowledgement slip is filled in by the post office."""
    ir = _slip("(To be filled by BPM/SPM or PLI-CPC Official and Handed Over to Insurant)")

    applicant, *slip = ir.fields
    assert applicant.no_fill_reason is None
    assert len(slip) == 2 and all(f.no_fill_reason == "office_use" for f in slip)
    changes = {e.change for e in ir.trace if e.field_id == slip[0].id}
    assert "no_fill_reason office_use (below a heading for an official)" in changes


@pytest.mark.parametrize(
    ("heading", "x"),
    [
        ("(To be completed by the Claimant & CBS Post Office)", None),  # the applicant too
        ("(to be filled by the Bank)", 72.0),  # not centred: a field's own note, not a heading
    ],
)
def test_other_headings_leave_the_fields_below_alone(heading: str, x: float | None) -> None:
    assert all(f.no_fill_reason is None for f in _slip(heading, x).fields)


def test_understanding_marks_a_field_whose_label_names_an_official() -> None:
    out = understand.run(
        _ir("Roll No. of the student (to be filled by Admission Cell)"),
        PassContext(clock=lambda: NOW),
    )

    assert out.fields[0].no_fill_reason == "office_use"
