from __future__ import annotations

import logging
from typing import Any

from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


class GoogleDriveClient:
    """Synchronous Google Drive client (run from threads or Celery workers)."""

    def __init__(self, credentials_path: str, folder_id: str) -> None:
        creds = service_account.Credentials.from_service_account_file(
            credentials_path,
            scopes=["https://www.googleapis.com/auth/drive.readonly"],
        )
        self._creds = creds
        self.folder_id = folder_id
        self.service = build(
            "drive",
            "v3",
            credentials=creds,
            cache_discovery=False,
        )
        self._http = AuthorizedSession(creds)

    def list_videos(self) -> list[dict[str, Any]]:
        query = (
            f"'{self.folder_id}' in parents and trashed = false "
            "and mimeType contains 'video/'"
        )
        items: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            try:
                resp = (
                    self.service.files()
                    .list(
                        q=query,
                        spaces="drive",
                        fields="nextPageToken, files(id, name, mimeType, md5Checksum, size)",
                        pageToken=page_token,
                        pageSize=200,
                        supportsAllDrives=True,
                        includeItemsFromAllDrives=True,
                    )
                    .execute()
                )
            except HttpError:
                logger.exception("Drive files.list failed for folder_id=%s", self.folder_id)
                raise
            for f in resp.get("files", []):
                mime = f.get("mimeType") or ""
                if "video/" not in mime:
                    continue
                items.append(f)
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return items

    def get_file_metadata(self, file_id: str) -> dict[str, Any]:
        return (
            self.service.files()
            .get(
                fileId=file_id,
                fields="id, name, mimeType, md5Checksum, size",
                supportsAllDrives=True,
            )
            .execute()
        )

    def open_media_stream(self, file_id: str):
        """Return a streaming ``requests.Response`` (caller must close)."""
        url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&supportsAllDrives=true"
        resp = self._http.get(url, stream=True)
        resp.raise_for_status()
        return resp
