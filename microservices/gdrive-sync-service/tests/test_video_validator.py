"""Unit tests for video_validator — no real ffmpeg/ffprobe/MinIO required."""
from __future__ import annotations

import io
import json
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.video_validator import (
    VideoValidationResult,
    _pixel_variance,
    validate_video,
)


def _make_settings(
    *,
    enabled=True,
    min_size=5 * 1024 * 1024,
    min_dur=5.0,
    frame_check=True,
    frame_seek=2.0,
    frame_min_variance=8.0,
    ffprobe_timeout=30,
    frame_timeout=60,
    presign_expiry=900,
):
    s = SimpleNamespace(
        video_validation_enabled=enabled,
        video_min_size_bytes=min_size,
        video_min_duration_sec=min_dur,
        video_ffprobe_timeout_sec=ffprobe_timeout,
        video_frame_check_enabled=frame_check,
        video_frame_seek_sec=frame_seek,
        video_frame_timeout_sec=frame_timeout,
        video_frame_min_variance=frame_min_variance,
        video_presign_expiry_sec=presign_expiry,
    )
    return s


def _make_store(presign_url="http://minio/test.h265"):
    store = MagicMock()
    store.presigned_get_object.return_value = presign_url
    return store


def _good_probe_output():
    return json.dumps({
        "streams": [{"codec_type": "video", "codec_name": "hevc", "width": 1920, "height": 1080}],
        "format": {"duration": "3600.0"},
    }).encode()


def _make_completed_process(returncode=0, stdout=b"", stderr=b""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# ─── size check ──────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_validate_rejects_too_small_file():
    store = _make_store()
    settings = _make_settings(min_size=5 * 1024 * 1024)
    result = validate_video(store, "video/test.h265", file_size=1 * 1024 * 1024, settings=settings)
    assert result.ok is False
    assert "too small" in result.reason
    store.presigned_get_object.assert_not_called()


# ─── ffprobe failures ─────────────────────────────────────────────────────────

@pytest.mark.unit
def test_validate_rejects_ffprobe_failure():
    store = _make_store()
    settings = _make_settings()
    with patch("app.services.video_validator.subprocess.run") as mock_run:
        mock_run.return_value = _make_completed_process(returncode=1, stderr=b"invalid data")
        result = validate_video(store, "video/test.h265", file_size=50 * 1024 * 1024, settings=settings)
    assert result.ok is False
    assert "ffprobe" in result.reason


@pytest.mark.unit
def test_validate_rejects_no_video_stream():
    store = _make_store()
    settings = _make_settings()
    probe_out = json.dumps({"streams": [{"codec_type": "audio"}], "format": {}}).encode()
    with patch("app.services.video_validator.subprocess.run") as mock_run:
        mock_run.return_value = _make_completed_process(stdout=probe_out)
        result = validate_video(store, "video/test.h265", file_size=50 * 1024 * 1024, settings=settings)
    assert result.ok is False
    assert "no video stream" in result.reason


@pytest.mark.unit
def test_validate_rejects_too_short_duration():
    store = _make_store()
    settings = _make_settings(min_dur=10.0)
    probe_out = json.dumps({
        "streams": [{"codec_type": "video", "codec_name": "hevc", "width": 1920, "height": 1080}],
        "format": {"duration": "3.5"},
    }).encode()
    with patch("app.services.video_validator.subprocess.run") as mock_run:
        mock_run.return_value = _make_completed_process(stdout=probe_out)
        result = validate_video(store, "video/test.h265", file_size=50 * 1024 * 1024, settings=settings)
    assert result.ok is False
    assert "duration too short" in result.reason
    assert result.duration_sec == pytest.approx(3.5)


# ─── frame check ─────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_validate_rejects_frame_extraction_failure():
    store = _make_store()
    settings = _make_settings()
    fake_jpeg = b"\xff\xd8" + b"\x00" * 200  # minimal fake JPEG stub

    call_count = 0

    def side_effect(cmd, **kwargs):
        nonlocal call_count
        call_count += 1
        if "ffprobe" in cmd[0]:
            return _make_completed_process(stdout=_good_probe_output())
        # Both ffmpeg calls fail
        return _make_completed_process(returncode=1, stderr=b"decode error")

    with patch("app.services.video_validator.subprocess.run", side_effect=side_effect):
        result = validate_video(store, "video/test.h265", file_size=50 * 1024 * 1024, settings=settings)

    assert result.ok is False
    assert "frame extraction failed" in result.reason


@pytest.mark.unit
def test_validate_rejects_low_variance_frame():
    store = _make_store()
    settings = _make_settings(frame_min_variance=8.0)
    fake_jpeg = b"\xff\xd8\xff" + b"\x11" * 500  # tiny fake JPEG bytes

    def side_effect(cmd, **kwargs):
        if "ffprobe" in cmd[0]:
            return _make_completed_process(stdout=_good_probe_output())
        return _make_completed_process(returncode=0, stdout=fake_jpeg)

    with patch("app.services.video_validator.subprocess.run", side_effect=side_effect):
        with patch("app.services.video_validator._pixel_variance", return_value=2.5):
            result = validate_video(store, "video/test.h265", file_size=50 * 1024 * 1024, settings=settings)

    assert result.ok is False
    assert "variance" in result.reason


@pytest.mark.unit
def test_validate_passes_good_video():
    store = _make_store()
    settings = _make_settings()
    fake_jpeg = b"\xff\xd8\xff" + b"\xaa" * 500

    def side_effect(cmd, **kwargs):
        if "ffprobe" in cmd[0]:
            return _make_completed_process(stdout=_good_probe_output())
        return _make_completed_process(returncode=0, stdout=fake_jpeg)

    with patch("app.services.video_validator.subprocess.run", side_effect=side_effect):
        with patch("app.services.video_validator._pixel_variance", return_value=42.0):
            result = validate_video(store, "video/test.h265", file_size=100 * 1024 * 1024, settings=settings)

    assert result.ok is True
    assert result.codec == "hevc"
    assert result.duration_sec == pytest.approx(3600.0)
    assert result.width == 1920
    assert result.height == 1080
    assert result.variance == pytest.approx(42.0)


@pytest.mark.unit
def test_validate_skips_frame_check_when_disabled():
    store = _make_store()
    settings = _make_settings(frame_check=False)

    with patch("app.services.video_validator.subprocess.run") as mock_run:
        mock_run.return_value = _make_completed_process(stdout=_good_probe_output())
        result = validate_video(store, "video/test.h265", file_size=100 * 1024 * 1024, settings=settings)

    assert result.ok is True
    assert mock_run.call_count == 1  # only ffprobe, no ffmpeg


# ─── pixel variance ───────────────────────────────────────────────────────────

@pytest.mark.unit
def test_pixel_variance_returns_high_for_varied_image():
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("Pillow not installed")

    img = Image.new("L", (64, 64))
    pixels = [i % 256 for i in range(64 * 64)]
    img.putdata(pixels)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    variance = _pixel_variance(buf.getvalue())
    assert variance > 50


@pytest.mark.unit
def test_pixel_variance_returns_low_for_solid_color():
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("Pillow not installed")

    img = Image.new("L", (64, 64), color=80)  # solid gray
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    variance = _pixel_variance(buf.getvalue())
    assert variance < 5
