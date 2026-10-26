"""Schema of a human-written label file, eval/labels/<form>.json (SPEC §10).

Label files are ground truth written by a human: produced by the converter from the human's
Label Studio export, never created or edited by hand-written code or by Claude (CLAUDE.md §6).

Coordinates follow the IR: PDF points, origin top-left of the displayed page. Only pages listed
in `labelled_pages` were labelled; the detection eval scores those and lists the others.
"""

import json
import math
import re
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ir.semantic_types import SemanticType

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "eval" / "dataset"
LABELS_DIR = REPO_ROOT / "eval" / "labels"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class LabelKind(StrEnum):
    TEXT = "text"
    CHECKBOX = "checkbox"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LabelPage(_Model):
    width: float = Field(gt=0, allow_inf_nan=False)
    height: float = Field(gt=0, allow_inf_nan=False)


class LabelField(_Model):
    id: str = Field(pattern=r"^p\d+_l\d{3,}$")
    page: int = Field(ge=0)
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1
    kind: LabelKind
    comb: bool = False  # a row of per-character cells (decision D8)
    max_chars: int | None = Field(default=None, gt=0)
    semantic_type: SemanticType | None = None  # added blind in Phase 3

    @model_validator(mode="after")
    def _box(self) -> Self:
        x0, y0, x1, y1 = self.bbox
        if not all(math.isfinite(v) for v in self.bbox) or not (x0 < x1 and y0 < y1):
            raise ValueError(f"field {self.id}: bbox must be finite with x0 < x1 and y0 < y1")
        if self.comb and self.kind is not LabelKind.TEXT:
            raise ValueError(f"field {self.id}: only text fields can be comb rows")
        return self


class LabelFile(_Model):
    schema_version: Literal[1] = 1
    form: str = Field(min_length=1)  # PDF file stem in eval/dataset/<split>/
    pdf_sha256: str
    verified_by_human: bool
    prefilled_from: str | None  # detector version used for pre-annotation; None = from scratch
    source: str  # tool and export file the labels came from
    labelled_pages: list[int]
    pages: list[LabelPage]  # every page of the PDF, labelled or not
    fields: list[LabelField] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if not _SHA256.fullmatch(self.pdf_sha256):
            raise ValueError("pdf_sha256 must be 64 lower-case hex characters")
        if self.labelled_pages != sorted(set(self.labelled_pages)):
            raise ValueError("labelled_pages must be sorted and unique")
        if any(not 0 <= p < len(self.pages) for p in self.labelled_pages):
            raise ValueError("labelled_pages refers to a page that does not exist")
        ids = [f.id for f in self.fields]
        if len(ids) != len(set(ids)):
            raise ValueError("field ids must be unique")
        labelled = set(self.labelled_pages)
        for f in self.fields:
            if f.page not in labelled:
                raise ValueError(f"field {f.id} is on page {f.page}, which is not labelled")
            page = self.pages[f.page]
            x0, y0, x1, y1 = f.bbox
            tol = 0.5
            if x0 < -tol or y0 < -tol or x1 > page.width + tol or y1 > page.height + tol:
                raise ValueError(f"field {f.id} lies outside its page")
        return self


def load_label_file(path: Path) -> LabelFile:
    return LabelFile.model_validate_json(path.read_text(encoding="utf-8"))


def dump_label_file(label_file: LabelFile) -> str:
    return json.dumps(label_file.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
