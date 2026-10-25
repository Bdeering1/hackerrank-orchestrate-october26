from __future__ import annotations

import re
import typing

if typing.TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[a-z]+")
EMAIL_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
STABLE_REFERENCE_PATTERN = re.compile(r"user_\d+")
PHONE_PATTERN = re.compile(r"\+[\d\s().-]{6,}")
IDENTIFIERS_IN_TEXT_PATTERN = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+|user_\d+")
IDENTIFIER_FIELDS = ("email", "phone", "email_hash")


def normalized_identifier(value: str) -> str | None:
    """Return the normalized identifier a value carries, or None for non-identifiers."""
    text = value.strip().lower()
    if PHONE_PATTERN.fullmatch(text):
        return "".join(character for character in text if character.isdigit())
    is_identifier = any(
        pattern.fullmatch(text)
        for pattern in (EMAIL_PATTERN, EMAIL_HASH_PATTERN, STABLE_REFERENCE_PATTERN)
    )
    return text if is_identifier else None


def identifiers_in_text(text: str) -> frozenset[str]:
    """Return the emails and stable user references mentioned in free text."""
    return frozenset(match[0].lower() for match in IDENTIFIERS_IN_TEXT_PATTERN.finditer(text))


def identifiers_by_identifier(
    identities: Iterable[Mapping[str, str]],
    audit_log: Iterable[Mapping[str, str]],
) -> dict[str, frozenset[str]]:
    """Map each current or historical identifier to every identifier of the same user."""
    values_by_user: dict[str, set[str]] = {}
    for identity in identities:
        values = values_by_user.setdefault(identity["user_id"], {identity["user_id"]})
        values.update(identity[field] for field in IDENTIFIER_FIELDS)
    for change in audit_log:
        if change["field_name"] in IDENTIFIER_FIELDS:
            values = values_by_user.setdefault(change["user_id"], {change["user_id"]})
            values.update((change["old_value"], change["new_value"]))

    user_identifiers_by_identifier: dict[str, frozenset[str]] = {}
    for values in values_by_user.values():
        identifiers = frozenset(
            identifier
            for value in values
            if (identifier := normalized_identifier(value)) is not None
        )
        for identifier in identifiers:
            user_identifiers_by_identifier.setdefault(identifier, identifiers)
    return user_identifiers_by_identifier
