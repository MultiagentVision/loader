from __future__ import annotations


def is_video_like(mime: str, file_name: str) -> bool:
    """Drive may label raw H.265 as ``application/octet-stream``; accept by extension."""
    m = (mime or "").lower()
    if m.startswith("video/"):
        return True
    if m == "application/vnd.google-apps.video":
        return True
    n = (file_name or "").lower()
    for ext in (".h265", ".hevc", ".265", ".mp4", ".mov", ".mkv", ".webm", ".m4v"):
        if n.endswith(ext):
            return True
    return False
