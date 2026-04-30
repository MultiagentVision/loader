"""Video integrity validation using ffprobe + ffmpeg frame extraction.

Flow:
    1. Size check (instant, no I/O).
    2. ffprobe on a presigned MinIO URL — verifies container/codec/duration.
    3. ffmpeg frame extraction at seek offset — verifies the stream is decodable.
    4. Pixel variance check — rejects green / gray / black frames.
"""
from __future__ import annotations

import io
import json
import logging
import statistics
import subprocess
from dataclasses import dataclass, field
from datetime import timedelta

from app.core.settings import Settings
from app.services.minio_client import MinioObjectStore

logger = logging.getLogger(__name__)


@dataclass
class VideoValidationResult:
    ok: bool
    reason: str | None = None
    duration_sec: float | None = None
    codec: str | None = None
    width: int | None = None
    height: int | None = None
    variance: float | None = None


def _ffprobe(url: str, *, timeout: int) -> dict:
    """Run ffprobe against an HTTP URL, return parsed JSON."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")[:500]
        raise ValueError(f"ffprobe exit={result.returncode}: {stderr}")
    return json.loads(result.stdout)


def _extract_frame(url: str, *, seek_sec: float, timeout: int) -> bytes:
    """Extract one JPEG frame from *url* at *seek_sec* via ffmpeg."""
    cmd = [
        "ffmpeg",
        "-v", "quiet",
        "-ss", f"{seek_sec:.3f}",
        "-i", url,
        "-vframes", "1",
        "-f", "image2",
        "-vcodec", "mjpeg",
        "pipe:1",
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if result.returncode != 0 or len(result.stdout) < 100:
        stderr = result.stderr.decode(errors="replace")[:400]
        raise ValueError(
            f"ffmpeg frame exit={result.returncode} size={len(result.stdout)}: {stderr}"
        )
    return result.stdout


def _pixel_variance(jpeg_bytes: bytes) -> float:
    """Return pixel intensity std-dev of a JPEG frame (grayscale).

    Green / gray / black frames typically have std-dev < 5.
    A real chess-board scene is usually > 20.
    Uses Pillow only (no numpy dependency).
    """
    try:
        from PIL import Image  # noqa: PLC0415
        img = Image.open(io.BytesIO(jpeg_bytes)).convert("L")
        pixels = list(img.getdata()) if not hasattr(img, "get_flattened_data") else list(img.get_flattened_data())
        if len(pixels) < 2:
            return 0.0
        return statistics.stdev(pixels)
    except Exception as exc:  # noqa: BLE001
        logger.warning("pixel_variance: PIL unavailable or error: %s", exc)
        return 999.0  # assume OK when we can't check


def validate_video(
    store: MinioObjectStore,
    object_name: str,
    *,
    file_size: int,
    settings: Settings,
) -> VideoValidationResult:
    """Validate a video that has already been uploaded to MinIO.

    Returns a :class:`VideoValidationResult` with ``ok=True`` when the file
    passes all checks, or ``ok=False`` with a human-readable ``reason``.
    """
    # ── 1. Size check ────────────────────────────────────────────────────────
    if file_size < settings.video_min_size_bytes:
        return VideoValidationResult(
            ok=False,
            reason=f"file too small: {file_size:,} B < {settings.video_min_size_bytes:,} B",
        )

    # ── 2. Presigned URL ─────────────────────────────────────────────────────
    try:
        url = store.presigned_get_object(
            object_name,
            expires=timedelta(seconds=settings.video_presign_expiry_sec),
        )
    except Exception as exc:  # noqa: BLE001
        return VideoValidationResult(ok=False, reason=f"presign failed: {exc}")

    # ── 3. ffprobe ───────────────────────────────────────────────────────────
    try:
        probe = _ffprobe(url, timeout=settings.video_ffprobe_timeout_sec)
    except Exception as exc:  # noqa: BLE001
        return VideoValidationResult(ok=False, reason=f"ffprobe failed: {exc}")

    video_stream = next(
        (s for s in probe.get("streams", []) if s.get("codec_type") == "video"),
        None,
    )
    if video_stream is None:
        return VideoValidationResult(ok=False, reason="ffprobe: no video stream found")

    codec = video_stream.get("codec_name", "unknown")
    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)

    raw_dur = probe.get("format", {}).get("duration") or video_stream.get("duration")
    duration_sec: float | None = None
    if raw_dur:
        try:
            duration_sec = float(raw_dur)
        except (TypeError, ValueError):
            pass

    if duration_sec is not None and duration_sec < settings.video_min_duration_sec:
        return VideoValidationResult(
            ok=False,
            reason=f"duration too short: {duration_sec:.1f}s < {settings.video_min_duration_sec}s",
            duration_sec=duration_sec,
            codec=codec,
            width=width,
            height=height,
        )

    if not settings.video_frame_check_enabled:
        return VideoValidationResult(
            ok=True,
            duration_sec=duration_sec,
            codec=codec,
            width=width,
            height=height,
        )

    # ── 4. Frame extraction ──────────────────────────────────────────────────
    seek = settings.video_frame_seek_sec
    # For very short videos clamp seek to avoid overshooting
    if duration_sec is not None and seek >= duration_sec:
        seek = max(0.0, duration_sec * 0.3)

    try:
        frame_bytes = _extract_frame(url, seek_sec=seek, timeout=settings.video_frame_timeout_sec)
    except ValueError as exc:
        # One retry at seek=0 (some HEVC streams need decoder warm-up from start)
        logger.debug("frame extraction at %.1fs failed, retrying at 0s: %s", seek, exc)
        try:
            frame_bytes = _extract_frame(url, seek_sec=0.0, timeout=settings.video_frame_timeout_sec)
        except ValueError as exc2:
            return VideoValidationResult(
                ok=False,
                reason=f"frame extraction failed: {exc2}",
                duration_sec=duration_sec,
                codec=codec,
                width=width,
                height=height,
            )

    # ── 5. Pixel variance ────────────────────────────────────────────────────
    variance = _pixel_variance(frame_bytes)
    if variance < settings.video_frame_min_variance:
        return VideoValidationResult(
            ok=False,
            reason=(
                f"frame variance too low: {variance:.1f} < {settings.video_frame_min_variance}"
                " (green / gray / black frame)"
            ),
            duration_sec=duration_sec,
            codec=codec,
            width=width,
            height=height,
            variance=variance,
        )

    logger.info(
        "video valid: codec=%s dur=%s res=%dx%d variance=%.1f object=%s",
        codec,
        f"{duration_sec:.1f}s" if duration_sec is not None else "?",
        width,
        height,
        variance,
        object_name,
    )
    return VideoValidationResult(
        ok=True,
        duration_sec=duration_sec,
        codec=codec,
        width=width,
        height=height,
        variance=variance,
    )
