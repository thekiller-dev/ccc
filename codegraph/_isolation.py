"""Process isolation for native Tree-sitter analysis of JSX-family sources."""

from __future__ import annotations

import base64
import json
import os
import signal
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from .models import (
    CallSite,
    FileAnalysis,
    GraphNode,
    ImportBinding,
    ImportSpec,
    InheritanceSpec,
    ScanIssue,
    ScannedFile,
    SymbolInfo,
)

_WORKER_TIMEOUT_SECONDS = 30
_WORKER_MODULE = "codegraph._isolation_worker"


class _WorkerFailure(RuntimeError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def _node_to_data(node: GraphNode) -> dict[str, Any]:
    return node.to_dict()


def _analysis_to_data(analysis: FileAnalysis) -> dict[str, Any]:
    return {
        "path": analysis.path,
        "file_node": _node_to_data(analysis.file_node),
        "module_node": _node_to_data(analysis.module_node),
        "symbols": [
            {
                "node": _node_to_data(symbol.node),
                "parent_id": symbol.parent_id,
                "parent_type": symbol.parent_type,
                "class_id": symbol.class_id,
                "exported_names": list(symbol.exported_names),
                "is_static": symbol.is_static,
            }
            for symbol in analysis.symbols
        ],
        "imports": [
            {
                "specifier": spec.specifier,
                "bindings": [
                    {"imported_name": binding.imported_name, "local_name": binding.local_name}
                    for binding in spec.bindings
                ],
                "line": spec.line,
                "end_line": spec.end_line,
                "evidence": spec.evidence,
                "syntax": spec.syntax,
                "type_only": spec.type_only,
            }
            for spec in analysis.imports
        ],
        "calls": [
            {
                "caller_id": call.caller_id,
                "callee": call.callee,
                "line": call.line,
                "end_line": call.end_line,
                "class_id": call.class_id,
                "shadowed_names": sorted(call.shadowed_names),
                "evidence": call.evidence,
                "receiver_name": call.receiver_name,
                "member_name": call.member_name,
                "receiver_type_name": call.receiver_type_name,
                "receiver_reassigned": call.receiver_reassigned,
            }
            for call in analysis.calls
        ],
        "inheritance": [
            {
                "source_id": spec.source_id,
                "name": spec.name,
                "relation_type": spec.relation_type,
                "line": spec.line,
                "end_line": spec.end_line,
                "evidence": spec.evidence,
            }
            for spec in analysis.inheritance
        ],
        "issues": [issue.to_dict() for issue in analysis.issues],
        "export_aliases": [list(alias) for alias in analysis.export_aliases],
        "reassigned_names": sorted(analysis.reassigned_names),
    }


def _node_from_data(data: dict[str, Any]) -> GraphNode:
    return GraphNode(
        id=data["id"],
        type=data["type"],
        name=data["name"],
        path=data["path"],
        start_line=data["start_line"],
        end_line=data["end_line"],
        metadata=data["metadata"],
    )


def _analysis_from_data(data: dict[str, Any]) -> FileAnalysis:
    return FileAnalysis(
        path=data["path"],
        file_node=_node_from_data(data["file_node"]),
        module_node=_node_from_data(data["module_node"]),
        symbols=tuple(
            SymbolInfo(
                node=_node_from_data(item["node"]),
                parent_id=item["parent_id"],
                parent_type=item["parent_type"],
                class_id=item["class_id"],
                exported_names=tuple(item["exported_names"]),
                is_static=item["is_static"],
            )
            for item in data["symbols"]
        ),
        imports=tuple(
            ImportSpec(
                specifier=item["specifier"],
                bindings=tuple(ImportBinding(**binding) for binding in item["bindings"]),
                line=item["line"],
                end_line=item["end_line"],
                evidence=item["evidence"],
                syntax=item["syntax"],
                type_only=item["type_only"],
            )
            for item in data["imports"]
        ),
        calls=tuple(
            CallSite(
                caller_id=item["caller_id"],
                callee=item["callee"],
                line=item["line"],
                end_line=item["end_line"],
                class_id=item["class_id"],
                shadowed_names=frozenset(item["shadowed_names"]),
                evidence=item["evidence"],
                receiver_name=item["receiver_name"],
                member_name=item["member_name"],
                receiver_type_name=item["receiver_type_name"],
                receiver_reassigned=item["receiver_reassigned"],
            )
            for item in data["calls"]
        ),
        inheritance=tuple(InheritanceSpec(**item) for item in data["inheritance"]),
        issues=tuple(ScanIssue(**item) for item in data["issues"]),
        export_aliases=tuple(tuple(alias) for alias in data["export_aliases"]),
        reassigned_names=frozenset(data["reassigned_names"]),
    )


def _run_worker(files: tuple[ScannedFile, ...]) -> tuple[FileAnalysis, ...]:
    request = {
        "protocol_version": 1,
        "files": [
            {"path": source.path, "source_base64": base64.b64encode(source.source).decode("ascii")}
            for source in files
        ],
    }
    package_root = str(Path(__file__).resolve().parent.parent)
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (package_root, existing_pythonpath) if part
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-m", _WORKER_MODULE],
            input=json.dumps(request, separators=(",", ":")),
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
            timeout=_WORKER_TIMEOUT_SECONDS,
            env=environment,
        )
    except subprocess.TimeoutExpired as error:
        raise _WorkerFailure(
            "analysis_worker_timeout",
            f"Isolated JSX analysis exceeded {_WORKER_TIMEOUT_SECONDS} seconds.",
        ) from error
    except OSError as error:
        raise _WorkerFailure(
            "analysis_worker_unavailable", "The isolated JSX analysis worker could not start."
        ) from error

    if completed.returncode != 0:
        if completed.returncode < 0:
            try:
                signal_name = signal.Signals(-completed.returncode).name
            except ValueError:
                signal_name = f"signal {-completed.returncode}"
            raise _WorkerFailure(
                "native_analysis_crash",
                f"The isolated native analysis worker terminated with {signal_name}.",
            )
        raise _WorkerFailure(
            "analysis_worker_error", "The isolated JSX analysis worker returned an error."
        )

    try:
        response = json.loads(completed.stdout)
        if response.get("protocol_version") != 1 or not isinstance(response.get("analyses"), list):
            raise ValueError("invalid worker response")
        analyses = tuple(_analysis_from_data(item) for item in response["analyses"])
    except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise _WorkerFailure(
            "analysis_worker_protocol_error", "The isolated JSX worker returned invalid data."
        ) from error

    if tuple(analysis.path for analysis in analyses) != tuple(source.path for source in files):
        raise _WorkerFailure(
            "analysis_worker_protocol_error", "The isolated JSX worker returned mismatched paths."
        )
    return analyses


def _failed_analysis(source: ScannedFile, failure: _WorkerFailure) -> FileAnalysis:
    source_path = PurePosixPath(source.path)
    language = "tsx" if source_path.suffix.lower() == ".tsx" else "javascript"
    file_node = GraphNode(
        id=f"file:{source.path}",
        type="file",
        name=source_path.name,
        path=source.path,
        metadata={"language": language},
    )
    module_node = GraphNode(
        id=f"module:{source.path}",
        type="module",
        name=source_path.with_suffix("").as_posix(),
        path=source.path,
        metadata={"language": language},
    )
    issue = ScanIssue(
        path=source.path,
        reason=failure.reason,
        message=f"{failure} Source symbols and relations were skipped.",
    )
    return FileAnalysis(
        path=source.path,
        file_node=file_node,
        module_node=module_node,
        symbols=(),
        imports=(),
        calls=(),
        inheritance=(),
        issues=(issue,),
    )


def analyze_jsx_files(files: tuple[ScannedFile, ...]) -> tuple[FileAnalysis, ...]:
    """Analyze JSX-family files in a child process and salvage healthy files on failure."""

    if not files:
        return ()
    try:
        return _run_worker(files)
    except _WorkerFailure:
        recovered: list[FileAnalysis] = []
        for source in files:
            try:
                recovered.extend(_run_worker((source,)))
            except _WorkerFailure as failure:
                recovered.append(_failed_analysis(source, failure))
        return tuple(recovered)
