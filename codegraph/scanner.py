"""Secure recursive discovery of JavaScript and TypeScript source files."""

from __future__ import annotations

import os
import re
from pathlib import Path

from .models import ScanIssue, ScannedFile, ScanResult

DEFAULT_MAX_FILE_SIZE_BYTES = 1_000_000
SOURCE_EXTENSIONS = frozenset({".ts", ".tsx", ".js", ".jsx", ".mts", ".cts", ".mjs", ".cjs"})
IGNORED_DIRECTORIES = frozenset(
    {
        ".git",
        ".venv",
        "node_modules",
        "dist",
        "build",
        "coverage",
        "__pycache__",
        "pycache",
        ".cache",
        ".next",
        ".turbo",
        ".vite",
        ".parcel-cache",
        ".codegraph",
        ".output",
        ".nuxt",
        ".svelte-kit",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".nox",
        ".tox",
        ".pnpm-store",
        ".yarn",
        "bower_components",
        "jspm_packages",
        "vendor",
        "out",
        "target",
    }
)
_PRIVATE_KEY_MARKER = re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", flags=re.IGNORECASE)
_PRIVATE_KEY_FILENAMES = frozenset(
    {
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "private_key",
        "privatekey",
        "secrets",
        "secret",
        "credentials",
    }
)
_PRIVATE_KEY_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".ppk", ".der", ".jks")


def _sensitive_filename(path: Path) -> bool:
    name = path.name.lower()
    stem = path.stem.lower()
    if name == ".env" or name.startswith(".env."):
        return True
    if name.startswith(".secret") or name.startswith("credentials."):
        return True
    return stem in _PRIVATE_KEY_FILENAMES or any(
        stem.endswith(suffix) for suffix in _PRIVATE_KEY_SUFFIXES
    )


def _walk_error(error: OSError, root: Path, issues: list[ScanIssue]) -> None:
    failed_path = Path(error.filename) if error.filename else root
    try:
        relative = failed_path.relative_to(root).as_posix() or "."
    except ValueError:
        relative = "."
    issues.append(
        ScanIssue(
            path=relative,
            reason="directory_read_error",
            message="A project directory could not be read.",
        )
    )


def scan_project(
    root: str | Path,
    max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES,
) -> ScanResult:
    """Discover supported source files without following any project symlink."""

    if max_file_size_bytes <= 0:
        raise ValueError("max_file_size_bytes must be greater than zero")
    project_root = Path(root).expanduser().resolve(strict=True)
    if not project_root.is_dir():
        raise NotADirectoryError("Project path must be a directory.")

    source_files: list[ScannedFile] = []
    issues: list[ScanIssue] = []
    discovered = 0

    def on_error(error: OSError) -> None:
        _walk_error(error, project_root, issues)

    for current, directories, filenames in os.walk(
        project_root, topdown=True, followlinks=False, onerror=on_error
    ):
        current_path = Path(current)
        directories[:] = sorted(
            name
            for name in directories
            if name.lower() not in IGNORED_DIRECTORIES and not (current_path / name).is_symlink()
        )
        for filename in sorted(filenames):
            path = current_path / filename
            if path.suffix.lower() not in SOURCE_EXTENSIONS:
                continue
            discovered += 1
            relative = path.relative_to(project_root).as_posix()

            if path.is_symlink():
                issues.append(
                    ScanIssue(
                        relative,
                        "symlink_skipped",
                        "Symbolic-link files are not followed.",
                    )
                )
                continue
            if _sensitive_filename(path):
                issues.append(
                    ScanIssue(
                        relative,
                        "sensitive_file",
                        "A secret- or private-key-like source file was excluded.",
                    )
                )
                continue

            try:
                size = path.stat().st_size
                if size > max_file_size_bytes:
                    issues.append(
                        ScanIssue(
                            relative,
                            "file_too_large",
                            f"File exceeds the {max_file_size_bytes}-byte limit.",
                        )
                    )
                    continue
                with path.open("rb") as stream:
                    content = stream.read(max_file_size_bytes + 1)
            except OSError:
                issues.append(ScanIssue(relative, "read_error", "Source file could not be read."))
                continue

            if len(content) > max_file_size_bytes:
                issues.append(
                    ScanIssue(
                        relative,
                        "file_too_large",
                        f"File exceeded the {max_file_size_bytes}-byte limit while reading.",
                    )
                )
                continue
            if _PRIVATE_KEY_MARKER.search(content):
                issues.append(
                    ScanIssue(
                        relative,
                        "private_key_detected",
                        "Source containing a private-key marker was excluded.",
                    )
                )
                continue
            try:
                normalized = content.decode("utf-8-sig").encode("utf-8")
            except UnicodeDecodeError:
                issues.append(
                    ScanIssue(
                        relative,
                        "decode_error",
                        "Source is not valid UTF-8 and was excluded.",
                    )
                )
                continue
            source_files.append(ScannedFile(relative, normalized))

    source_files.sort(key=lambda item: item.path)
    issues.sort(key=lambda issue: (issue.path, issue.reason, issue.line or 0))
    return ScanResult(
        root=project_root,
        files=tuple(source_files),
        issues=tuple(issues),
        discovered_files=discovered,
        max_file_size_bytes=max_file_size_bytes,
    )
