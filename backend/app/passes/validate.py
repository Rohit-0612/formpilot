"""Validation pass (SPEC §6.6): deterministic checks on every field that has a value.

The results replace the field's earlier validator results (the fit pass owns `fits_box`). A
failed check sets status NEEDS_REVIEW; messages and trace never contain the value.
"""

from app.ir.models import FieldStatus, FormIR, TraceEvent
from app.passes.context import PassContext
from app.validators import validate_field

STAGE = "validate"
FIT_VALIDATOR = "fits_box"


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
        if failed:
            update["status"] = FieldStatus.NEEDS_REVIEW
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
