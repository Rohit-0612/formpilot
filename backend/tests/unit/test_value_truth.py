"""The fill eval's value check (eval/value_truth.py, fill_eval.value_right) on synthetic boxes.

No real form, label or persona is used.
"""

from datetime import date
from typing import Any

from app.ir.models import BBox, Field, FieldKind, ValueSource
from app.ir.semantic_types import SemanticType as T
from eval import run_eval
from eval.fill_eval import value_right
from eval.labelling.schema import LabelField, LabelKind
from eval.value_truth import Role, part_right, roles, same_text

BORN = date(1998, 3, 7)
PROFILE = {"date_of_birth": "1998-03-07", "full_name": "Asha Verma", "passing_year": "2016"}
TODAY = date(2026, 1, 1)


def _box(i: int, x0: float, y0: float, x1: float, y1: float) -> LabelField:
    return LabelField(id=f"p0_l{i:03d}", page=0, bbox=(x0, y0, x1, y1), kind=LabelKind.TEXT)


def test_stacked_cells_of_one_type_are_repeated_rows() -> None:
    """An education table: the year column has three rows; the name above it is a single field."""
    fields = [
        _box(0, 100, 40, 300, 54),  # name
        _box(1, 300, 100, 360, 118), _box(2, 300, 118, 360, 136), _box(3, 300, 136, 360, 154),
        _box(4, 300, 300, 360, 318),  # the same type far below: not a row of the table
    ]  # fmt: skip
    reference = {"p0_l000": T.FULL_NAME} | {f"p0_l00{i}": T.PASSING_YEAR for i in (1, 2, 3, 4)}

    got = roles(fields, reference)

    assert set(got) == {"p0_l001", "p0_l002", "p0_l003"}
    assert all(r.repeated for r in got.values())


def test_one_date_split_over_a_row_is_day_month_year() -> None:
    fields = [_box(0, 100, 50, 124, 62), _box(1, 126, 50, 150, 62), _box(2, 152, 50, 200, 62)]
    reference = {f.id: T.DATE_OF_BIRTH for f in fields}

    got = roles(fields, reference)

    assert [got[f.id].part for f in fields] == ["day", "month", "year"]


def test_a_single_date_has_no_role() -> None:
    assert roles([_box(0, 100, 50, 200, 62)], {"p0_l000": T.DATE_OF_FILLING}) == {}


def test_date_parts_compare_by_number_month_name_and_short_year() -> None:
    assert part_right("07", BORN, "day") and part_right("7", BORN, "day")
    assert part_right("03", BORN, "month") and part_right("March", BORN, "month")
    assert part_right("1998", BORN, "year") and part_right("98", BORN, "year")
    assert not part_right("07/03/1998", BORN, "day")  # the whole date in the day box
    assert not part_right("08", BORN, "day")


def test_text_compares_without_case_and_spacing() -> None:
    assert same_text("ASHA  VERMA", "Asha Verma")
    assert not same_text("ASHA", "Asha Verma")


def _filled(value: str, semantic_type: T, uppercase: bool = False, **extra: Any) -> Field:
    return Field(
        id="p0_f000", kind=FieldKind.TEXT, native_name=None, label_text="x", context_text=None,
        bbox=BBox(page=0, x0=0, y0=0, x1=60, y1=14), semantic_type=semantic_type, value=value,
        value_source=ValueSource.PROFILE, uppercase=uppercase, **extra,
    )  # fmt: skip


def _compared(reference: T, role: Role | None = None) -> run_eval.Compared:
    return run_eval.Compared(
        "form", "p0_l000", reference, reference, "rule", None, "p0_f000", 0.95, role or Role()
    )


def test_value_right_reads_the_reference_layout() -> None:
    year = _filled("2016", T.PASSING_YEAR)
    assert value_right(_compared(T.PASSING_YEAR), year, PROFILE, TODAY)
    # a table row: the profile's one passing year is not this row's
    assert not value_right(_compared(T.PASSING_YEAR, Role(repeated=True)), year, PROFILE, TODAY)
    whole = _filled("07/03/1998", T.DATE_OF_BIRTH)
    assert not value_right(_compared(T.DATE_OF_BIRTH, Role(part="day")), whole, PROFILE, TODAY)
    day = _filled("07", T.DATE_OF_BIRTH)
    assert value_right(_compared(T.DATE_OF_BIRTH, Role(part="day")), day, PROFILE, TODAY)
    today = _filled("2026", T.DATE_OF_FILLING)
    assert value_right(_compared(T.DATE_OF_FILLING, Role(part="year")), today, PROFILE, TODAY)


def test_value_right_compares_the_printed_value() -> None:
    upper = _filled("Asha Verma", T.FULL_NAME, uppercase=True)

    assert value_right(_compared(T.FULL_NAME), upper, PROFILE, TODAY)
