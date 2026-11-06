"""Secrets sealed at rest (05/SG12): AES-256-GCM, bound to where they belong.

The context (tenant, server, field) is authenticated with every secret, so a sealed value copied to another tenant's
row, or to another field, fails to open instead of working there. The key comes from the secret manager through
`APP_MCP_SECRETS_KEY` (32 bytes, base64); without it nothing can be connected, and nothing falls back to plain text.
Rotate by adding a new key id: values name the key that sealed them.
"""

from __future__ import annotations

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_ID = "k1"


class SealBroken(Exception):
    """A sealed value is damaged, was moved, or was sealed with another key."""


class SecretBox:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("the sealing key is 32 bytes (base64 of 32 random bytes)")
        self._aead = AESGCM(key)

    @classmethod
    def from_setting(cls, value: str | None) -> SecretBox | None:
        if not value:
            return None
        try:
            return cls(base64.b64decode(value, validate=True))
        except binascii.Error as exc:
            raise ValueError("APP_MCP_SECRETS_KEY is not base64") from exc

    def seal(self, plaintext: str, *, context: str) -> str:
        nonce = os.urandom(12)
        sealed = self._aead.encrypt(nonce, plaintext.encode(), context.encode())
        return f"{KEY_ID}:{base64.b64encode(nonce + sealed).decode()}"

    def open(self, value: str, *, context: str) -> str:
        key_id, _, body = value.partition(":")
        if key_id != KEY_ID:
            raise SealBroken(f"sealed with key {key_id!r}, not {KEY_ID!r}")
        try:
            raw = base64.b64decode(body, validate=True)
            return self._aead.decrypt(raw[:12], raw[12:], context.encode()).decode()
        except (binascii.Error, InvalidTag, ValueError) as exc:
            raise SealBroken("the sealed value does not open here") from exc
