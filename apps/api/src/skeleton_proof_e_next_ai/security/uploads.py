"""Upload intake: uploads are hostile (05/SG6, W42).

Allowlisted types only; the declared Content-Type AND the file's magic bytes must agree (each alone is
insufficient); size is capped while streaming. Archives are not accepted, so there is nothing to
decompress; adding one needs a decompressed-size cap and sandboxed parsing (tier E).
"""

from __future__ import annotations

from ..domain.errors import DomainError

# media type -> (magic bytes prefix, stored extension)
ALLOWED: dict[str, tuple[bytes, str]] = {
    "image/png": (b"\x89PNG\r\n\x1a\n", ".png"),
    "image/jpeg": (b"\xff\xd8\xff", ".jpg"),
    "application/pdf": (b"%PDF-", ".pdf"),
}


class UploadTooLarge(DomainError):
    code = "upload-too-large"
    status = 413


class UploadRejected(DomainError):
    code = "upload-type-rejected"
    status = 415


def validate(declared: str, data: bytes) -> str:
    """Return the extension to store under, or raise. `declared` is the request's Content-Type."""
    media_type = declared.partition(";")[0].strip().lower()
    if media_type not in ALLOWED:
        raise UploadRejected(f"'{media_type or 'unknown'}' is not an accepted file type.")
    magic, extension = ALLOWED[media_type]
    if not data.startswith(magic):
        raise UploadRejected("The file's contents don't match its declared type.")
    return extension
