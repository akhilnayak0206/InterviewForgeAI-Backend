from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)


def _get_upload_root() -> Path:
    return Path(settings.UPLOAD_DIR).resolve()


def _get_user_dir(user_id: uuid.UUID) -> Path:
    user_dir = _get_upload_root() / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def generate_storage_filename(original_filename: str) -> str:
    suffix = Path(original_filename).suffix.lower()
    return f"{uuid.uuid4()}{suffix}"


def save_file(
    *,
    user_id: uuid.UUID,
    storage_filename: str,
    file_bytes: bytes,
) -> str:
    user_dir = _get_user_dir(user_id)
    file_path = user_dir / storage_filename

    file_path.write_bytes(file_bytes)

    # Return path relative to upload root
    relative_path = f"{user_id}/{storage_filename}"

    logger.info(
        "File saved | user=%s | path=%s | size=%d bytes",
        user_id,
        relative_path,
        len(file_bytes),
    )

    return relative_path


def delete_file(storage_path: str) -> bool:
    file_path = _get_upload_root() / storage_path

    if file_path.exists():
        file_path.unlink()
        logger.info("File deleted | path=%s", storage_path)
        return True

    logger.warning("File not found for deletion | path=%s", storage_path)
    return False


def get_absolute_path(storage_path: str) -> Path:
    return _get_upload_root() / storage_path


def compute_checksum(file_bytes: bytes) -> str:
    """Compute SHA-256 hex digest of file content.

    Used for duplicate detection: if two files have the same checksum,
    they are byte-for-byte identical.
    """
    return hashlib.sha256(file_bytes).hexdigest()