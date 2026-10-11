from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.scanner import scan_project


def test_scanner_rejects_invalid_size_limit(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        scan_project(tmp_path, max_file_size_bytes=0)


def test_scanner_reports_read_error_and_continues(tmp_path: Path, monkeypatch) -> None:
    readable = tmp_path / "a.ts"
    unreadable = tmp_path / "b.ts"
    readable.write_text("export const a = 1;", encoding="utf-8")
    unreadable.write_text("export const b = 2;", encoding="utf-8")
    original_open = Path.open

    def controlled_open(self: Path, *args, **kwargs):
        if self == unreadable:
            raise PermissionError("permission denied")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", controlled_open)
    result = scan_project(tmp_path)

    assert [item.path for item in result.files] == ["a.ts"]
    assert [(issue.path, issue.reason) for issue in result.issues] == [("b.ts", "read_error")]
