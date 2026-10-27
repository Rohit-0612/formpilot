"""Format-independent checks (SPEC §6.6): email, dates, options, length. Messages never contain
the value."""

from datetime import date

from email_validator import EmailNotValidError, validate_email

from app.ir.models import Field
from app.validators.dates import date_format_for, format_date, parse_in_format


def email_format(value: str) -> str | None:
    try:
        validate_email(value.strip(), check_deliverability=False)
    except EmailNotValidError:
        return "This is not a valid email address."
    return None


def date_valid(value: str, field: Field) -> str | None:
    fmt = date_format_for(field)
    if parse_in_format(value, fmt) is not None:
        return None
    example = format_date(date(2001, 12, 31), fmt)
    return f"Enter a real date in the form's format (e.g. {example})."


def dob_not_future(value: str, field: Field, today: date) -> str | None:
    parsed = parse_in_format(value, date_format_for(field))
    if parsed is None or parsed <= today:
        return None  # an unreadable date is reported by date_valid only
    return "A date of birth cannot be in the future."


def option_valid(value: str, field: Field) -> str | None:
    allowed = {o.value for o in field.options}
    if not allowed or value in allowed:
        return None
    return "Choose one of the form's options."


def max_chars(value: str, field: Field) -> str | None:
    if field.max_chars is None or len(value) <= field.max_chars:
        return None
    return f"The form has room for {field.max_chars} characters here."
