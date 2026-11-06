"""Storage service for handling secure file uploads, validation, and storage operations."""

import os
import re
import hashlib
from pathlib import Path
from typing import Tuple, Optional
from fastapi import UploadFile

from kwuo.core.config import settings


class StorageError(Exception):
    """Base error for storage operations."""
    pass


class FileTooLargeError(StorageError):
    """Raised when an uploaded file exceeds the configured size limit."""
    pass


class InvalidExtensionError(StorageError):
    """Raised when an uploaded file extension is not permitted."""
    pass


class StorageFileNotFoundError(StorageError):
    """Raised when a requested file does not exist on disk."""
    pass


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent directory traversal and filesystem attacks."""
    # Strip paths
    clean_name = os.path.basename(filename)
    # Remove control characters, quotes, and dangerous shell symbols
    clean_name = re.sub(r'[^\w\s\.-]', '_', clean_name).strip()
    # Collapse consecutive spaces or dots
    clean_name = re.sub(r'\s+', '_', clean_name)
    clean_name = re.sub(r'\.+', '.', clean_name)
    if not clean_name or clean_name.startswith('.'):
        clean_name = f"attachment_{clean_name}" if clean_name else "attachment.dat"
    return clean_name


def get_file_extension(filename: str) -> str:
    """Return lowercase file extension without dot."""
    if "." in filename:
        return filename.rsplit(".", 1)[1].lower()
    return ""


def validate_file_metadata(filename: str, content_length: Optional[int] = None) -> str:
    """Validate filename extension and optional content length before saving."""
    ext = get_file_extension(filename)
    if not ext or ext not in settings.ALLOWED_UPLOAD_EXTENSIONS:
        allowed = ", ".join(sorted(settings.ALLOWED_UPLOAD_EXTENSIONS))
        raise InvalidExtensionError(
            f"File extension '.{ext}' is not permitted. Allowed extensions: {allowed}"
        )
    
    if content_length is not None and content_length > settings.MAX_UPLOAD_SIZE_BYTES:
        max_mb = settings.MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)
        raise FileTooLargeError(f"File size exceeds the {max_mb}MB limit.")
    
    return ext


def get_storage_base_dir() -> Path:
    """Get absolute Path to base storage directory, ensuring it exists."""
    base_dir = Path(settings.UPLOAD_DIR).resolve()
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def resolve_file_path(relative_file_path: str) -> Path:
    """Resolve relative file path and verify it stays inside base storage directory."""
    base_dir = get_storage_base_dir()
    resolved = (base_dir / relative_file_path).resolve()
    if not resolved.is_relative_to(base_dir):
        raise StorageError("Invalid file path: path traversal detected.")
    return resolved


async def save_upload_file(
    tournament_id: str,
    attachment_id: str,
    upload_file: UploadFile,
) -> Tuple[str, str, int, str, str]:
    """Save an uploaded file in chunked streams with size enforcement and hashing.
    
    Returns:
        Tuple of (clean_filename, relative_file_path, file_size, mime_type, sha256_hash)
    """
    raw_filename = upload_file.filename or "attachment.dat"
    validate_file_metadata(raw_filename)
    clean_filename = sanitize_filename(raw_filename)

    base_dir = get_storage_base_dir()
    tourn_dir = base_dir / tournament_id
    tourn_dir.mkdir(parents=True, exist_ok=True)

    dest_filename = f"{attachment_id}_{clean_filename}"
    dest_path = tourn_dir / dest_filename
    relative_path = f"{tournament_id}/{dest_filename}"

    sha256 = hashlib.sha256()
    total_size = 0
    chunk_size = 64 * 1024  # 64KB chunks

    try:
        with open(dest_path, "wb") as f:
            while chunk := await upload_file.read(chunk_size):
                total_size += len(chunk)
                if total_size > settings.MAX_UPLOAD_SIZE_BYTES:
                    max_mb = settings.MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)
                    raise FileTooLargeError(
                        f"File size exceeded maximum limit of {max_mb}MB."
                    )
                sha256.update(chunk)
                f.write(chunk)
    except Exception:
        # Clean up partial file on any failure
        if dest_path.exists():
            dest_path.unlink(missing_ok=True)
        raise

    mime_type = upload_file.content_type or "application/octet-stream"
    file_hash = sha256.hexdigest()

    return clean_filename, relative_path, total_size, mime_type, file_hash


def delete_stored_file(relative_file_path: str) -> bool:
    """Delete a stored file from the filesystem."""
    try:
        target = resolve_file_path(relative_file_path)
        if target.exists() and target.is_file():
            target.unlink()
            return True
        return False
    except StorageError:
        return False
