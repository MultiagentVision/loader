import pytest

from app.db.repositories import files_repo
from app.db.repositories.files_repo import FileRepository


class RecordingSession:
    def __init__(self) -> None:
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_upsert_discovered_uses_drive_object_prefix(monkeypatch) -> None:
    calls = []

    def fake_build_object_key(drive_name, file_id, file_name, *, object_prefix=None):
        calls.append(
            {
                "drive_name": drive_name,
                "file_id": file_id,
                "file_name": file_name,
                "object_prefix": object_prefix,
            }
        )
        return "video/Rehovot/file123_clip.mp4"

    monkeypatch.setattr(files_repo, "build_object_key", fake_build_object_key)
    session = RecordingSession()
    repo = FileRepository(session)  # type: ignore[arg-type]

    await repo.upsert_discovered(
        drive_name="rehovot",
        file_id="file123",
        file_name="clip.mp4",
        checksum="abc",
        size=123,
        object_prefix="video/Rehovot",
    )

    assert calls == [
        {
            "drive_name": "rehovot",
            "file_id": "file123",
            "file_name": "clip.mp4",
            "object_prefix": "video/Rehovot",
        }
    ]
    assert session.statements
