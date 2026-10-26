from typing import Any

from pydantic import BaseModel, model_validator

from app.ir.models import FormIR
from app.services.masking import mask_ir_data


class MaskedFormIR(FormIR):
    """The only form in which a Form IR leaves the API (SPEC §8): values are masked whenever an
    instance is built, from a FormIR, a dict or stored JSON alike (app/services/masking.py).

    A test checks that no route's response model contains a plain FormIR.
    """

    @model_validator(mode="before")
    @classmethod
    def _mask_values(cls, data: Any) -> Any:
        if isinstance(data, BaseModel):
            data = data.model_dump()
        if isinstance(data, dict):
            return mask_ir_data(data)
        return data  # anything else fails the normal validation
