from __future__ import annotations

import re
import unicodedata


def sanitize_file_name(name: str, max_component_len: int = 200) -> str:
    name = unicodedata.normalize("NFC", name or "")
    name = name.replace("\x00", "")
    name = re.sub(r"[\\/]+", "_", name)
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    name = name.strip() or "unnamed"
    if len(name) > max_component_len:
        root, dot, ext = name.rpartition(".")
        if dot and len(ext) <= 16:
            keep = max_component_len - len(ext) - 1
            name = f"{root[:keep]}.{ext}"
        else:
            name = name[:max_component_len]
    return name


def build_object_key(
    drive_name: str,
    file_id: str,
    file_name: str,
    *,
    object_prefix: str | None = None,
) -> str:
    safe = sanitize_file_name(file_name)
    prefix = (object_prefix if object_prefix is not None else drive_name).strip().strip("/")
    return f"{prefix}/{file_id}_{safe}"


def object_name_in_bucket(object_key: str) -> str:
    """Object key inside the configured bucket (no leading slash)."""
    return object_key.lstrip("/")
