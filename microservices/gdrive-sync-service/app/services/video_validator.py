"""Video integrity validation using ffprobe + ffmpeg frame extraction.

Flow:
    1. Size check (instant, no I/O).
    2. ffprobe on a presigned MinIO URL — verifies container/codec/duration.
       Uses ``-f hevc`` fallback to bypass libgme 50 MB HTTP size limit.
    3. Multi-point sampling: download HEVC_PROBE_BYTES from 3 offsets
       (0%, 33%, 66% of file size) → temp files for frame decode.
       Sampling multiple points catches corruption that only appears mid-video
       (e.g. green/incomplete frames at minute 30 of a 1-hour game).
    4. ffmpeg frame extraction from each temp file.
    5. Pixel variance check on each frame — rejects green / gray / black frames.
       File is rejected if ANY sample point fails the variance check.
"""
from __future__ import annotations

import io
import json
import logging
import statistics
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from app.core.settings import Settings
from app.services.minio_client import MinioObjectStore

logger = logging.getLogger(__name__)

# Bytes downloaded per sample point (10 MB ≈ 16s at 5 Mbps camera bitrate).
HEVC_PROBE_BYTES = 10 * 1024 * 1024

# Relative offsets into the file where we sample frames.
# 0.0 = start, 0.33 = first-third, 0.66 = two-thirds.
# We skip the very end (>0.8) because HEVC streams often have incomplete
# trailing GOPs that produce false positives.
SAMPLE_OFFSETS = (0.0, 0.33, 0.66)


@dataclass
class VideoValidationResult:
    ok: bool
    reason: str | None = None
    duration_sec: float | None = None
    codec: str | None = None
    width: int | None = None
    height: int | None = None
    variance: float | None = None


def _ffprobe(url: str, *, timeout: int, force_hevc: bool = False) -> dict:
    """Run ffprobe against an HTTP URL, return parsed JSON.

    Falls back to ``-f hevc`` to bypass the libgme demuxer that rejects HTTP
    streams larger than 50 MB.
    """
    cmd = ["ffprobe", "-v", "quiet"]
    if force_hevc:
        cmd += ["-f", "hevc"]
    cmd += ["-print_format", "json", "-show_streams", "-show_format", url]
    result = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if result.returncode != 0:
        if not force_hevc:
            return _ffprobe(url, timeout=timeout, force_hevc=True)
        stderr = result.stderr.decode(errors="replace")[:500]
        raise ValueError(f"ffprobe exit={result.returncode}: {stderr}")
    data = json.loads(result.stdout)
    if not data.get("streams") and not force_hevc:
        return _ffprobe(url, timeout=timeout, force_hevc=True)
    return data


def _extract_frame_from_file(path: str, *, seek_sec: float, timeout: int) -> bytes:
    """Extract one JPEG frame from a local raw-HEVC file.

    We use ``-f hevc`` to tell ffmpeg the input format explicitly (avoids the
    libgme format prober), and place ``-ss`` *after* ``-i`` so the seek is
    performed by decoding (accurate for raw streams that lack seek tables).
    """
    cmd = [
        "ffmpeg", "-v", "quiet",
        "-f", "hevc",   # input format hint — bypasses libgme probing
        "-i", path,
        "-ss", f"{seek_sec:.3f}",   # accurate (post-input) seek
        "-vframes", "1", "-f", "image2", "-vcodec", "mjpeg", "pipe:1",
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if result.returncode != 0 or len(result.stdout) < 100:
        # Fallback: extract first frame (no seek) for streams without keyframes at offset
        cmd_fallback = [
            "ffmpeg", "-v", "quiet",
            "-f", "hevc", "-i", path,
            "-vframes", "1", "-f", "image2", "-vcodec", "mjpeg", "pipe:1",
        ]
        result = subprocess.run(cmd_fallback, capture_output=True, timeout=timeout)
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

    # ── 4. Multi-point frame extraction ─────────────────────────────────────
    # Raw HEVC over HTTP cannot be seeked efficiently — ffmpeg would have to
    # read the entire file sequentially.  Instead, download HEVC_PROBE_BYTES
    # from several byte offsets (start / 33% / 66%) and extract one frame from
    # each chunk.  This catches corruption that only appears mid-video
    # (green / incomplete frames not present in the first 16 seconds).
    last_variance: float | None = None
    for rel_offset in SAMPLE_OFFSETS:
        byte_offset = int(file_size * rel_offset)
        # Align to nearest MB to improve chance of landing near a keyframe.
        byte_offset = (byte_offset // (1024 * 1024)) * (1024 * 1024)

        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".hevc", delete=False) as tmp:
                tmp_path = tmp.name
                response = store._client.get_object(
                    store.bucket,
                    object_name,
                    offset=byte_offset,
                    length=HEVC_PROBE_BYTES,
                )
                try:
                    for chunk in response.stream(amt=65536):
                        tmp.write(chunk)
                finally:
                    response.close()
                    response.release_conn()
        except Exception as exc:  # noqa: BLE001
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)
            logger.warning(
                "video_validator: MinIO download failed at offset=%d for %s: %s",
                byte_offset, object_name, exc,
            )
            continue  # skip this sample point, don't fail the whole file

        try:
            # For non-zero offsets we don't know where keyframes are — extract
            # the first decodable frame from the chunk (no seek).
            seek_sec = 0.0 if rel_offset > 0.0 else settings.video_frame_seek_sec
            if duration_sec is not None and seek_sec >= duration_sec:
                seek_sec = 0.0
            frame_bytes = _extract_frame_from_file(
                tmp_path,
                seek_sec=seek_sec,
                timeout=settings.video_frame_timeout_sec,
            )
        except ValueError as exc:
            logger.warning(
                "video_validator: frame extraction failed at offset=%.0f%% for %s: %s",
                rel_offset * 100, object_name, exc,
            )
            Path(tmp_path).unlink(missing_ok=True)
            continue  # codec error at this offset — skip, don't penalise
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        # ── 5. Pixel variance per sample ─────────────────────────────────────
        variance = _pixel_variance(frame_bytes)
        last_variance = variance
        if variance < settings.video_frame_min_variance:
            return VideoValidationResult(
                ok=False,
                reason=(
                    f"frame variance too low at {rel_offset*100:.0f}%: "
                    f"{variance:.1f} < {settings.video_frame_min_variance}"
                    " (green / gray / black frame)"
                ),
                duration_sec=duration_sec,
                codec=codec,
                width=width,
                height=height,
                variance=variance,
            )
        logger.debug(
            "video_validator: sample offset=%.0f%% variance=%.1f OK",
            rel_offset * 100, variance,
        )

    logger.info(
        "video valid: codec=%s dur=%s res=%dx%d variance=%.1f object=%s",
        codec,
        f"{duration_sec:.1f}s" if duration_sec is not None else "?",
        width,
        height,
        last_variance or 0.0,
        object_name,
    )
    return VideoValidationResult(
        ok=True,
        duration_sec=duration_sec,
        codec=codec,
        width=width,
        height=height,
        variance=last_variance,
    )
