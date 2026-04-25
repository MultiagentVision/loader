from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class DriveConfig(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    folder_id: str = Field(min_length=1)
    credentials_path: Path
    #: MinIO key prefix (no leading slash), e.g. ``video/Rehovot``. If unset, ``name`` is used.
    object_prefix: str | None = Field(default=None, max_length=512)


class DrivesRootConfig(BaseModel):
    drives: list[DriveConfig]


def load_drives_config(path: Path) -> list[DriveConfig]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    parsed = DrivesRootConfig.model_validate(raw)
    return list(parsed.drives)
