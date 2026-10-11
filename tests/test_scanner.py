from __future__ import annotations

from pathlib import Path

from codegraph.scanner import SOURCE_EXTENSIONS, scan_project


def test_scanner_discovers_supported_extensions_and_ignores_dependency_trees(
    tmp_path: Path,
) -> None:
    for index, extension in enumerate(sorted(SOURCE_EXTENSIONS)):
        (tmp_path / f"source{index}{extension}").write_text("export {};\n", encoding="utf-8")
    for directory in (".git", "node_modules", "dist", "build", "coverage", ".cache"):
        ignored = tmp_path / directory
        ignored.mkdir()
        (ignored / "ignored.ts").write_text("export const no = 1;", encoding="utf-8")
    (tmp_path / ".env").write_text("TOKEN=not-code", encoding="utf-8")

    result = scan_project(tmp_path)

    assert {Path(item.path).suffix for item in result.files} == SOURCE_EXTENSIONS
    assert result.discovered_files == len(SOURCE_EXTENSIONS)
    assert not any(
        directory in item.path for item in result.files for directory in ("node_modules", "dist")
    )


def test_scanner_excludes_sensitive_files_and_private_key_markers(tmp_path: Path) -> None:
    (tmp_path / "safe.ts").write_text("export const ok = true;", encoding="utf-8")
    (tmp_path / ".env.local.ts").write_text("export const token = 'secret';", encoding="utf-8")
    (tmp_path / "secrets.ts").write_text("export const token = 'secret';", encoding="utf-8")
    (tmp_path / "private_key.ts").write_text("export const key = 'not indexed';", encoding="utf-8")
    (tmp_path / "embedded.ts").write_text(
        "const key = `-----BEGIN PRIVATE KEY-----`;", encoding="utf-8"
    )

    result = scan_project(tmp_path)

    assert [item.path for item in result.files] == ["safe.ts"]
    assert {issue.reason for issue in result.issues} == {
        "sensitive_file",
        "private_key_detected",
    }
    assert all("not indexed" not in item.source.decode() for item in result.files)


def test_scanner_enforces_size_limit_and_reports_decode_errors(tmp_path: Path) -> None:
    (tmp_path / "large.ts").write_text("x" * 100, encoding="utf-8")
    (tmp_path / "invalid.ts").write_bytes(b"export const x = '\xff';")
    (tmp_path / "ok.ts").write_text("export const x = 1;", encoding="utf-8")

    result = scan_project(tmp_path, max_file_size_bytes=50)

    assert [item.path for item in result.files] == ["ok.ts"]
    assert {(issue.path, issue.reason) for issue in result.issues} == {
        ("large.ts", "file_too_large"),
        ("invalid.ts", "decode_error"),
    }


def test_scanner_skips_symlinks_to_paths_outside_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.ts"
    outside.write_text("export const outside = true;", encoding="utf-8")
    (project / "inside.ts").write_text("export const inside = true;", encoding="utf-8")
    (project / "external.ts").symlink_to(outside)

    result = scan_project(project)

    assert [item.path for item in result.files] == ["inside.ts"]
    assert [(issue.path, issue.reason) for issue in result.issues] == [
        ("external.ts", "symlink_skipped")
    ]
