"""Tree-sitter parser selection for JavaScript, JSX, TypeScript, and TSX."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

import tree_sitter_javascript
import tree_sitter_typescript
from tree_sitter import Language, Parser

from .models import ParsedFile, ScanIssue, ScannedFile

_LANGUAGES = {
    ".js": ("javascript", Language(tree_sitter_javascript.language())),
    ".jsx": ("javascript", Language(tree_sitter_javascript.language())),
    ".mjs": ("javascript", Language(tree_sitter_javascript.language())),
    ".cjs": ("javascript", Language(tree_sitter_javascript.language())),
    ".ts": ("typescript", Language(tree_sitter_typescript.language_typescript())),
    ".mts": ("typescript", Language(tree_sitter_typescript.language_typescript())),
    ".cts": ("typescript", Language(tree_sitter_typescript.language_typescript())),
    ".tsx": ("tsx", Language(tree_sitter_typescript.language_tsx())),
}


def _first_error(root: Any) -> Any | None:
    pending = [root]
    while pending:
        node = pending.pop()
        if node.is_error or node.is_missing:
            return node
        pending.extend(reversed(node.named_children))
    return None


def parse_file(source_file: ScannedFile) -> ParsedFile:
    """Parse one scanned file; syntax errors are recorded, not raised."""

    extension = PurePosixPath(source_file.path).suffix.lower()
    if extension not in _LANGUAGES:
        raise ValueError(f"Unsupported source extension: {extension}")
    language_name, language = _LANGUAGES[extension]
    tree = Parser(language).parse(source_file.source)
    issues: tuple[ScanIssue, ...] = ()
    if tree.root_node.has_error:
        error_node = _first_error(tree.root_node)
        line = error_node.start_point.row + 1 if error_node is not None else None
        issues = (
            ScanIssue(
                path=source_file.path,
                reason="syntax_error",
                message="Tree-sitter recovered from a syntax error; extracted data may be partial.",
                line=line,
            ),
        )
    return ParsedFile(source_file, language_name, tree, issues)
