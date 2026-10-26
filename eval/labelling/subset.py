"""The labelling subset: which dev pages are scored by the detection eval (human, 2026-10-17).

The human labelled whole forms except #1 and #3, where only some pages are in the subset. A
label file may still mark other pages as labelled (a page submitted instead of skipped); the eval
does not score those and lists them. Changing the subset is a human decision; record it in
docs/decisions/phase-2.md.
"""

from collections.abc import Mapping
from typing import Literal

ALL: Literal["all"] = "all"

type PageSelection = Literal["all"] | tuple[int, ...]

# PDF stem in eval/dataset/dev/ -> pages to score, 1-based as in a PDF viewer, or ALL.
# #1 pages 5, 8 and 9 were added with labels v5 (human, 2026-10-22) as a held-out check of
# labelling rule 3's precision (Step 11, fix 4).
DEV_SUBSET: Mapping[str, PageSelection] = {
    "01_sbi_account_opening_form": (1, 4, 5, 8, 9),
    "02_sbi_kyc_annexure_a": ALL,
    "03_sbi_kyc_annexure_b": (2,),
    "06_union_bank_nomination_form": ALL,
    "21_india_post_pmjjby_claim_form": ALL,
    "23_lic_claim_form_a_3783": ALL,
    "25_cdlsiet_btech_admission_form": ALL,
    "30_allahabad_univ_enrollment_form": ALL,
    "32_niftem_student_declaration_form": ALL,
    "39_cebs_joining_report": ALL,
    "41_india_post_pli_name_change_form": ALL,
}


class SubsetError(ValueError):
    pass


def subset_pages(subset: Mapping[str, PageSelection], form: str, page_count: int) -> frozenset[int]:
    """The form's pages in the subset, 0-based like label files. Empty if the form is not in it."""
    selection = subset.get(form)
    if selection is None:
        return frozenset()
    if selection == ALL:
        return frozenset(range(page_count))
    if any(not 1 <= page <= page_count for page in selection):
        raise SubsetError(f"subset for {form}: a page is outside 1..{page_count}")
    return frozenset(page - 1 for page in selection)
