"""Stored Form IR versions (SPEC §7) with sensitive and phone values encrypted (decision P4-D5).

Before an IR is stored, the value of every field whose semantic type is sensitive (D2) or a phone
type, or whose value looks like a D2 identifier (the masking rule's defence in depth), is
replaced by `SEALED_PREFIX` + a Fernet token made with the vault key. The rest of the IR stays
plain JSON and expires with the document (24 h). A value that happens to start with the prefix
is sealed too, so every stored value with the prefix is a token.

Loading reverses it. Versions are append-only and numbered 1, 2, 3, ... per document.
"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FormIRVersion
from app.ir.models import FormIR
from app.ir.semantic_types import PHONE_TYPES, SENSITIVE_TYPES, SemanticType
from app.services.masking import looks_sensitive
from app.vault.crypto import VaultCipher

SEALED_PREFIX = "enc:fernet:"
SEALED_TYPES: frozenset[SemanticType] = SENSITIVE_TYPES | PHONE_TYPES


def must_seal(value: str | None, semantic_type: SemanticType) -> bool:
    if value is None:
        return False
    return (
        semantic_type in SEALED_TYPES
        or looks_sensitive(value, semantic_type)
        or value.startswith(SEALED_PREFIX)
    )


def seal(ir: FormIR, cipher: VaultCipher) -> dict[str, Any]:
    """The IR as JSON for the database, with sensitive and phone values encrypted."""
    data = ir.model_dump(mode="json")
    for field in data["fields"]:
        if must_seal(field["value"], SemanticType(field["semantic_type"])):
            field["value"] = SEALED_PREFIX + cipher.encrypt(field["value"])
    return data


def unseal(data: dict[str, Any], cipher: VaultCipher) -> dict[str, Any]:
    """A copy of stored IR JSON with the encrypted values decrypted (raises VaultError)."""
    fields = []
    for field in data["fields"]:
        value = field.get("value")
        if isinstance(value, str) and value.startswith(SEALED_PREFIX):
            field = {**field, "value": cipher.decrypt(value.removeprefix(SEALED_PREFIX))}
        fields.append(field)
    return {**data, "fields": fields}


async def add_version(
    session: AsyncSession, document_id: uuid.UUID, ir: FormIR, cipher: VaultCipher
) -> int:
    """Adds the next version (not committed). The unique (document, version) key stops a race."""
    latest = await session.scalar(
        select(func.max(FormIRVersion.version)).where(FormIRVersion.document_id == document_id)
    )
    version = (latest or 0) + 1
    session.add(FormIRVersion(document_id=document_id, version=version, ir_json=seal(ir, cipher)))
    return version


async def latest_data(
    session: AsyncSession, document_id: uuid.UUID, cipher: VaultCipher
) -> dict[str, Any] | None:
    """The latest IR as plain JSON (values decrypted); mask it before it leaves the API."""
    stored = await session.scalar(
        select(FormIRVersion.ir_json)
        .where(FormIRVersion.document_id == document_id)
        .order_by(FormIRVersion.version.desc())
        .limit(1)
    )
    return None if stored is None else unseal(stored, cipher)


async def latest(
    session: AsyncSession, document_id: uuid.UUID, cipher: VaultCipher
) -> FormIR | None:
    data = await latest_data(session, document_id, cipher)
    return None if data is None else FormIR.model_validate(data)
