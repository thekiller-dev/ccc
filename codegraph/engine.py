"""Shared end-to-end analysis pipeline used by the CLI and HTTP API."""

from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PurePosixPath

import networkx as nx

from ._isolation import analyze_jsx_files
from .extractor import extract_file
from .graph_builder import build_graph
from .parser import parse_file
from .resolver import resolve_relationships
from .scanner import DEFAULT_MAX_FILE_SIZE_BYTES, scan_project

_TREE_SITTER_ISOLATION_THRESHOLD = (0, 26, 0)


def _requires_isolated_jsx_analysis() -> bool:
    """Guard the known native traversal regression in Tree-sitter 0.26 and later."""

    try:
        installed_version = version("tree-sitter")
    except PackageNotFoundError:
        return True
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", installed_version)
    if match is None:
        return True
    parsed_version = tuple(int(component) for component in match.groups())
    return parsed_version >= _TREE_SITTER_ISOLATION_THRESHOLD


def analyze_project(
    path: str | Path,
    *,
    max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES,
) -> nx.MultiDiGraph:
    """Scan, parse, extract, resolve, and build a project graph exactly once."""

    scan_result = scan_project(path, max_file_size_bytes=max_file_size_bytes)
    isolate_native_jsx = _requires_isolated_jsx_analysis()
    isolated_files = tuple(
        source_file
        for source_file in scan_result.files
        if isolate_native_jsx and PurePosixPath(source_file.path).suffix.lower() in {".jsx", ".tsx"}
    )
    isolated_analyses = {analysis.path: analysis for analysis in analyze_jsx_files(isolated_files)}
    analyses = tuple(
        isolated_analyses[source_file.path]
        if source_file.path in isolated_analyses
        else extract_file(parse_file(source_file))
        for source_file in scan_result.files
    )
    resolution = resolve_relationships(analyses, project_root=scan_result.root)
    return build_graph(scan_result, analyses, resolution)
