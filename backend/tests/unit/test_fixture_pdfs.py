"""The synthetic PDF fixtures contain what their ground truth says (tests/fixtures/pdfs.py).

These tests check the fixtures themselves, using PyMuPDF directly, so later frontend tests can
trust the ground truth.
"""

import json
import re
from pathlib import Path

import pymupdf
import pytest

from app.ir.models import BBox, FieldKind, SourceKind, TextLayer
from tests.fixtures import pdfs

ALL = pdfs.NAMES
DETERMINISTIC = [name for name in ALL if not pdfs.get(name).encrypted]
LEADER_CHARS = "_.…"
KRUTI_TOKEN = re.compile(r"[A-Za-z]*[\[\]{};%`~|][A-Za-z]+|[A-Za-z]+[\[\]{}%`~|]")


def _open(name: str) -> pymupdf.Document:
    return pymupdf.open("pdf", pdfs.get(name).data)


def _non_space_chars(page: pymupdf.Page) -> int:
    return sum(1 for char in page.get_text() if not char.isspace())


def _image_area_share(page: pymupdf.Page) -> float:
    area = sum(abs(rect) for image in page.get_images() for rect in page.get_image_rects(image[0]))
    return area / abs(page.rect)


def _leader_runs(page: pymupdf.Page, min_length: int = 5) -> set[tuple[float, float, float]]:
    """(x0, x1, baseline) of each run of underscores/dots, from PyMuPDF's character boxes."""
    runs: set[tuple[float, float, float]] = set()
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                run: list[dict] = []
                for char in [*span["chars"], None]:
                    if char is not None and char["c"] in LEADER_CHARS:
                        run.append(char)
                        continue
                    if len(run) >= min_length:
                        runs.add(
                            (
                                round(run[0]["bbox"][0], 2),
                                round(run[-1]["bbox"][2], 2),
                                round(run[0]["origin"][1], 2),
                            )
                        )
                    run = []
    return runs


def _drawn_rects(page: pymupdf.Page) -> list[tuple[float, float, float, float]]:
    return [
        tuple(round(v, 2) for v in item[1])
        for drawing in page.get_drawings()
        for item in drawing["items"]
        if item[0] == "re"
    ]


def _rounded(box: tuple[float, float, float, float]) -> tuple[float, ...]:
    return tuple(round(v, 2) for v in box)


# --- every fixture ------------------------------------------------------------------------


@pytest.mark.parametrize("name", ALL)
def test_fixture_opens_with_its_page_count(name: str) -> None:
    fixture = pdfs.get(name)
    with _open(name) as doc:
        if fixture.encrypted:
            assert doc.needs_pass
            return
        assert not doc.needs_pass
        assert doc.page_count == len(fixture.text_layers)


@pytest.mark.parametrize("name", DETERMINISTIC)
def test_fixture_bytes_are_deterministic(name: str) -> None:
    builder = pdfs.BUILDERS[name]

    assert builder().data == builder().data


@pytest.mark.parametrize("name", ALL)
def test_ground_truth_boxes_are_valid_ir_boxes_inside_the_page(name: str) -> None:
    fixture = pdfs.get(name)
    if fixture.encrypted:
        return
    with _open(name) as doc:
        for field in fixture.fields:
            page = doc[field.page]
            boxes = [field.bbox] + [option.bbox for option in field.options if option.bbox]
            for x0, y0, x1, y1 in boxes:
                BBox(page=field.page, x0=x0, y0=y0, x1=x1, y1=y1)  # validates
                assert x0 >= 0 and x1 <= page.rect.width
                assert y0 >= 0 and y1 <= page.rect.height
            if field.kind is FieldKind.CHECKBOX:
                x0, y0, x1, y1 = field.bbox
                assert abs((x1 - x0) - (y1 - y0)) < 1, "checkboxes are square"


@pytest.mark.parametrize("name", ALL)
def test_fields_only_on_ok_pages(name: str) -> None:
    fixture = pdfs.get(name)

    for field in fixture.fields:
        assert fixture.text_layers[field.page] is TextLayer.OK


def test_every_source_kind_and_text_layer_is_covered() -> None:
    fixtures = [pdfs.get(name) for name in ALL]

    assert {f.source_kind for f in fixtures} >= {
        SourceKind.FILLABLE,
        SourceKind.FLAT_TEXT,
        SourceKind.SCANNED,
    }
    assert {layer for f in fixtures for layer in f.text_layers} == set(TextLayer)


# --- line-type entries: the ground truth matches PyMuPDF's character boxes -----------------


@pytest.mark.parametrize(
    "name",
    ["flat_underscores", "flat_dot_leaders", "text_layer_sparse_signature", "mixed_mostly_flat"],
)
def test_leader_ground_truth_matches_extracted_characters(name: str) -> None:
    fixture = pdfs.get(name)
    with _open(name) as doc:
        for field in fixture.fields:
            x0, y0, x1, y1 = field.bbox
            assert (round(x0, 2), round(x1, 2), round(y1, 2)) in _leader_runs(doc[field.page])
            assert y1 - y0 == pytest.approx(pdfs.ROW_HEIGHT)


def test_sentence_ending_dots_are_not_a_leader_run() -> None:
    with _open("flat_dot_leaders") as doc:
        with_short_runs = _leader_runs(doc[0], min_length=3)
        leader_runs = _leader_runs(doc[0])

    entries = len(pdfs.get("flat_dot_leaders").fields)
    assert len(with_short_runs) == entries + 1  # the sentence's "..." is a 3-dot run
    assert len(leader_runs) == entries


def test_ellipsis_leader_extracts_as_unicode_ellipsis() -> None:
    """Real forms use "……" leaders; the fixture must produce U+2026, not a look-alike."""
    with _open("flat_dot_leaders") as doc:
        text = doc[0].get_text()

    assert pdfs.ELLIPSIS * 15 in text


def test_attached_underscores_extract_as_one_word_with_the_label() -> None:
    with _open("flat_underscores") as doc:
        words = [word[4] for word in doc[0].get_text("words")]

    assert "No:" + "_" * 15 in words


# --- drawn entries ------------------------------------------------------------------------


def test_lines_fixture_draws_two_entry_lines_and_a_heading_underline() -> None:
    with _open("flat_lines") as doc:
        items = [item for d in doc[0].get_drawings() for item in d["items"]]

    lines = [item for item in items if item[0] == "l"]
    rects = [item[1] for item in items if item[0] == "re"]
    assert len(lines) == 2  # entry line + heading underline
    assert [round(r.height, 2) for r in rects] == [0.6]  # thin filled rectangle used as a line


@pytest.mark.parametrize("name", ["flat_boxes", "flat_checkboxes"])
def test_rect_entries_are_drawn_rectangles(name: str) -> None:
    fixture = pdfs.get(name)
    with _open(name) as doc:
        rects = _drawn_rects(doc[0])
        lines = [i for d in doc[0].get_drawings() for i in d["items"] if i[0] == "l"]

    table_cells = [f for f in fixture.fields if f.label in ("Bank name", "Branch", "IFSC")]
    for field in fixture.fields:
        if field not in table_cells:
            assert _rounded(field.bbox) in rects
    if table_cells:
        assert len(lines) == 4 + 3  # table drawn with lines, not rectangles


def test_comb_ground_truth_is_the_union_of_its_cells() -> None:
    fixture = pdfs.get("flat_comb")
    with _open("flat_comb") as doc:
        cells = [pymupdf.Rect(r) for r in _drawn_rects(doc[0])]
        separators = [w for w in doc[0].get_text("words") if w[4] == "/"]

    assert len(cells) == sum(f.max_chars or 0 for f in fixture.fields)
    for field in fixture.fields:
        box = pymupdf.Rect(field.bbox)
        inside = [cell for cell in cells if box.contains(cell)]
        assert len(inside) == field.max_chars
        union = pymupdf.Rect(inside[0])
        for cell in inside[1:]:
            union |= cell
        assert _rounded(tuple(union)) == _rounded(field.bbox)
    assert len(separators) == 2  # DD / MM / YYYY


def test_rotated_fixture() -> None:
    with _open("flat_rotated") as doc:
        page = doc[0]
        assert page.rotation == 90
        assert (page.rect.width, page.rect.height) == (842, 595)


# --- text-layer fixtures (decision D1) ----------------------------------------------------


def test_image_only_page_has_no_text_and_is_covered_by_an_image() -> None:
    with _open("text_layer_image_only") as doc:
        assert _non_space_chars(doc[0]) == 0
        assert _image_area_share(doc[0]) > 0.9


def test_sparse_signature_page_has_little_text_and_no_image() -> None:
    with _open("text_layer_sparse_signature") as doc:
        assert _non_space_chars(doc[0]) < 50
        assert doc[0].get_images() == []


def test_sparse_page_with_small_logo_is_mostly_not_image() -> None:
    with _open("text_layer_sparse_small_logo") as doc:
        assert _non_space_chars(doc[0]) < 50
        assert 0 < _image_area_share(doc[0]) < 0.05


def test_kruti_page_has_legacy_tokens_and_enough_text() -> None:
    with _open("text_layer_garbled_kruti") as doc:
        text = doc[0].get_text()

    tokens = text.split()
    kruti = [token for token in tokens if KRUTI_TOKEN.search(token)]
    assert len(kruti) >= 15 and len(kruti) / len(tokens) >= 0.03
    assert sum(1 for c in text if not c.isspace()) >= 50


def test_mojibake_page_has_latin_extended_letters() -> None:
    with _open("text_layer_garbled_mojibake") as doc:
        text = doc[0].get_text()

    letters = [c for c in text if c.isalpha()]
    extended = [c for c in letters if 0x00C0 <= ord(c) <= 0x024F]
    assert len(extended) >= 20 and len(extended) / len(letters) >= 0.02


# --- fillable fixture ---------------------------------------------------------------------


def test_fillable_widgets_match_ground_truth() -> None:
    fixture = pdfs.get("fillable_basic")
    # One widget per field, except a radio group: one widget per option.
    expected_boxes: set[tuple[str | None, tuple[float, ...]]] = set()
    for field in fixture.fields:
        if field.kind is FieldKind.RADIO:
            expected_boxes |= {
                (field.native_name, _rounded(o.bbox)) for o in field.options if o.bbox
            }
        else:
            expected_boxes.add((field.native_name, _rounded(field.bbox)))

    # Widget properties read the open document, so all checks stay inside the block.
    with _open("fillable_basic") as doc:
        page = doc[0]
        widgets = list(page.widgets())
        assert (page.rect.width, page.rect.height) == (592, 762)  # offset CropBox
        assert {(w.field_name, _rounded(tuple(w.rect))) for w in widgets} == expected_boxes

        by_name = {w.field_name: w for w in widgets}
        assert by_name["full_name"].field_label == "Full name of the applicant"
        assert by_name["mobile_no"].field_label is None
        assert by_name["mobile_no"].text_maxlen == 10
        assert "Agreed" in by_name["agree"].button_states()["normal"]
        radio_states = {
            state
            for w in widgets
            if w.field_name == "gender"
            for state in w.button_states()["normal"]
        }
        assert radio_states == {"Male", "Female", "Off"}
        assert by_name["state"].choice_values == [("UP", "Uttar Pradesh"), ("MH", "Maharashtra")]


# --- upload-path fixtures -----------------------------------------------------------------


def test_too_many_pages_is_one_over_the_limit() -> None:
    with _open("too_many_pages") as doc:
        assert doc.page_count == 51


# --- CLI ----------------------------------------------------------------------------------


def test_cli_writes_pdf_and_ground_truth_for_every_fixture(tmp_path: Path) -> None:
    names = ["flat_comb", "fillable_basic"]  # a representative pair keeps the test fast

    written = pdfs.write_all(tmp_path, names)

    assert sorted(p.name for p in written) == sorted(
        [f"{n}.pdf" for n in names] + [f"{n}.json" for n in names]
    )
    truth = json.loads((tmp_path / "flat_comb.json").read_text())
    assert truth["source_kind"] == "flat_text"
    assert truth["text_layers"] == ["ok"]
    assert len(truth["fields"]) == len(pdfs.get("flat_comb").fields)
    assert (tmp_path / "flat_comb.pdf").read_bytes() == pdfs.get("flat_comb").data


def test_cli_main_writes_every_fixture(tmp_path: Path) -> None:
    assert pdfs.main(["--out", str(tmp_path)]) == 0

    assert {p.stem for p in tmp_path.glob("*.pdf")} == set(ALL)
    assert {p.stem for p in tmp_path.glob("*.json")} == set(ALL)
