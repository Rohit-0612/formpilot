"""Validation pass (SPEC §6.6): deterministic checks on every field that has a value.

The results replace the field's earlier validator results (the fit pass owns `fits_box`). A
failed check sets status NEEDS_REVIEW, except for a suggested value (it needs the user's confirm
either way) and a value the user confirmed despite the warning; messages and trace never contain
the value.
"""

from app.ir.models import FieldStatus, FormIR, TraceEvent
from app.passes.context import PassContext
from app.validators import validate_field

STAGE = "validate"
FIT_VALIDATOR = "fits_box"
# Statuses a failed check does not change: the user decides on these values (Phase 5).
USER_DECIDES = frozenset({FieldStatus.SUGGESTED, FieldStatus.CONFIRMED})


def run(ir: FormIR, ctx: PassContext) -> FormIR:
    today = ctx.today()
    trace: list[TraceEvent] = []
    fields = []
    for field in ir.fields:
        if field.no_fill_reason is not None or not field.value:
            fields.append(field)
            continue
        results = validate_field(field, today)
        kept = [r for r in field.validations if r.validator == FIT_VALIDATOR]
        failed = [r.validator for r in results if not r.ok]
        update: dict[str, object] = {"validations": results + kept}
        if failed and field.status not in USER_DECIDES:
            update["status"] = FieldStatus.NEEDS_REVIEW
        if failed:
            trace.append(
                TraceEvent(
                    pass_name=STAGE,
                    field_id=field.id,
                    change=f"failed {', '.join(failed)}",
                    at=ctx.clock(),
                )
            )
        fields.append(field.model_copy(update=update))
    return ir.model_copy(update={"fields": fields, "trace": ir.trace + trace})
