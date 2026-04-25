import pytest

from app.services.paths import build_object_key, sanitize_file_name


@pytest.mark.unit
def test_sanitize_strips_control_chars_and_separators() -> None:
    assert "\\" not in sanitize_file_name("a\\b.mp4")
    assert "/" not in sanitize_file_name("a/b.mp4")


@pytest.mark.unit
def test_build_object_key_prefixes_file_id() -> None:
    key = build_object_key("main", "file123", "clip.mp4")
    assert key == "main/file123_clip.mp4"
