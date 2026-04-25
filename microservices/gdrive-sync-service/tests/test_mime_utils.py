import pytest

from app.services.mime_utils import is_video_like


@pytest.mark.unit
def test_is_video_like_mime() -> None:
    assert is_video_like("video/mp4", "x.bin")
    assert is_video_like("video/hevc", "x.h265")


@pytest.mark.unit
def test_is_video_like_h265_extension() -> None:
    assert is_video_like("application/octet-stream", "clip.h265")
    assert is_video_like("", "foo.H265")


@pytest.mark.unit
def test_is_video_like_rejects_random() -> None:
    assert not is_video_like("application/pdf", "doc.pdf")
