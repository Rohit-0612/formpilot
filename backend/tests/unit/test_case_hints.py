"""Capital-letter hints (Phase 5): set by the frontends, measured upper-case by the fit pass."""

import uuid
from datetime import UTC, datetime

import pymupdf
import pytest

from app.frontends import flat
from app.frontends.detect import detect
from app.ir.models import BBox, Field, FieldKind, FormIR, PageInfo, SourceKind, TextLayer
from app.ir.phrases import asks_upper_case, instructs_upper_case
from app.passes import fit
from app.passes.context import PassContext
from tests.fixtures import pdfs

NOW = datetime(2026, 10, 27, tzinfo=UTC)


@pytest.mark.parametrize(
    "label",
    [
        "Name (in BLOCK LETTERS)",
        "Student name as per 10 certificate (Block Letters)",
        "13. E-mail (Only Capital Letters)",  # dev form #25 asks for the e-mail in capitals
        "प्रार्ी का नाम (Applicant name in English) (Capital letters)",
        "नाम (बड़े अक्षरों में)",
        "Surname in UPPER CASE",
    ],
)
def test_labels_asking_for_capitals(label: str) -> None:
    assert asks_upper_case(label)


@pytest.mark.parametrize(
    "label",
    [
        "Signatures should not be in capital or block letters",
        "Block Name & No.",  # a building block, not a case hint
        "Name of the capital city",
        "Letters of credit",
        None,
    ],
)
def test_labels_not_asking_for_capitals(label: str | None) -> None:
    assert not asks_upper_case(label)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Please Ĥll up in BLOCK letters only and use black ink for signature", True),
        ("All entries must be written in capital letters", True),
        ("कृपया बड़े अक्षरों में भरें", True),
        ("(in Block Letters)", False),  # the second line of a label, not an instruction
        ("Signatures should not be in capital or block letters. Each account", False),
    ],
)
def test_page_instructions(line: str, expected: bool) -> None:
    assert instructs_upper_case(line) is expected


def test_the_flat_frontend_marks_the_page_and_the_labelled_field() -> None:
    fixture = pdfs.get("flat_case_hints")
    with pymupdf.open("pdf", fixture.data) as doc:
        ir = flat.run(doc, detect(doc), uuid.uuid4(), NOW)

    assert {(f.label_text, f.uppercase) for f in ir.fields} == {
        ("Full name", True),
        ("City", True),
        ("Name (in capital letters)", True),
        ("Place", False),
    }
    hints = sorted(t.change for t in ir.trace if t.change.startswith("uppercase"))
    assert hints == ["uppercase (label hint)"] + ["uppercase (page hint)"] * 2


def _field(value: str, uppercase: bool) -> Field:
    return Field(
        id="p0_f000", kind=FieldKind.TEXT, native_name=None, label_text="Name", context_text=None,
        bbox=BBox(page=0, x0=0, y0=0, x1=60, y1=14), value=value, uppercase=uppercase,
    )  # fmt: skip


def test_printed_value_is_upper_case_only_when_asked() -> None:
    assert fit.printed(_field("asha verma", uppercase=True)) == "ASHA VERMA"
    assert fit.printed(_field("asha verma", uppercase=False)) == "asha verma"


def test_the_fit_pass_measures_the_upper_case_value() -> None:
    """Capitals are wider: the same value gets a smaller font size when written upper-case."""

    def size(uppercase: bool) -> float | None:
        ir = FormIR(
            document_id=uuid.uuid4(), source_kind=SourceKind.FLAT_TEXT,
            pages=[PageInfo(width=595, height=842, text_layer=TextLayer.OK)],
            fields=[_field("asha verma kumari", uppercase)],
        )  # fmt: skip
        return fit.run(ir, PassContext(clock=lambda: NOW)).fields[0].font_size

    assert size(uppercase=True) < size(uppercase=False)  # type: ignore[operator]
