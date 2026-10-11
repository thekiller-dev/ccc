"""Typed models shared by the scanner, Tree-sitter pipeline, graph, and API."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class NodeType(StrEnum):
    PROJECT = "project"
    FILE = "file"
    FUNCTION = "function"
    CLASS = "class"
    INTERFACE = "interface"
    TYPE = "type"
    MODULE = "module"


class RelationType(StrEnum):
    CONTAINS = "CONTAINS"
    IMPORTS = "IMPORTS"
    DEFINES = "DEFINES"
    CALLS = "CALLS"
    EXTENDS = "EXTENDS"
    IMPLEMENTS = "IMPLEMENTS"


@dataclass(frozen=True, slots=True)
class ScannedFile:
    """A bounded, UTF-8 JavaScript or TypeScript source file."""

    path: str
    source: bytes


@dataclass(frozen=True, slots=True)
class ScanIssue:
    """A safe-to-display scanner or parser diagnostic."""

    path: str
    reason: str
    message: str
    line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "reason": self.reason,
            "message": self.message,
            "line": self.line,
        }


@dataclass(frozen=True, slots=True)
class ScanResult:
    root: Path
    files: tuple[ScannedFile, ...]
    issues: tuple[ScanIssue, ...]
    discovered_files: int
    max_file_size_bytes: int


@dataclass(frozen=True, slots=True)
class ParsedFile:
    source_file: ScannedFile
    language: str
    tree: Any
    issues: tuple[ScanIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class SymbolInfo:
    node: GraphNode
    parent_id: str
    parent_type: str
    class_id: str | None = None
    exported_names: tuple[str, ...] = ()
    is_static: bool = False


@dataclass(frozen=True, slots=True)
class ImportBinding:
    imported_name: str
    local_name: str


@dataclass(frozen=True, slots=True)
class ImportSpec:
    specifier: str
    bindings: tuple[ImportBinding, ...]
    line: int
    end_line: int
    evidence: str
    syntax: str = "import"
    type_only: bool = False


@dataclass(frozen=True, slots=True)
class CallSite:
    caller_id: str
    callee: str
    line: int
    end_line: int
    class_id: str | None = None
    shadowed_names: frozenset[str] = frozenset()
    evidence: str = ""
    receiver_name: str | None = None
    member_name: str | None = None
    receiver_type_name: str | None = None
    receiver_reassigned: bool = False


@dataclass(frozen=True, slots=True)
class InheritanceSpec:
    source_id: str
    name: str
    relation_type: str
    line: int
    end_line: int
    evidence: str


@dataclass(frozen=True, slots=True)
class FileAnalysis:
    path: str
    file_node: GraphNode
    module_node: GraphNode
    symbols: tuple[SymbolInfo, ...]
    imports: tuple[ImportSpec, ...]
    calls: tuple[CallSite, ...]
    inheritance: tuple[InheritanceSpec, ...]
    issues: tuple[ScanIssue, ...]
    export_aliases: tuple[tuple[str, str], ...] = ()
    reassigned_names: frozenset[str] = frozenset()

    @property
    def nodes(self) -> tuple[GraphNode, ...]:
        return (self.file_node, self.module_node, *(item.node for item in self.symbols))

    @property
    def exports(self) -> dict[str, tuple[GraphNode, ...]]:
        exported: dict[str, list[GraphNode]] = {}
        for symbol in self.symbols:
            for exported_name in symbol.exported_names:
                exported.setdefault(exported_name, []).append(symbol.node)
        by_local_name: dict[str, list[GraphNode]] = {}
        for symbol in self.symbols:
            if symbol.parent_type == "module":
                by_local_name.setdefault(symbol.node.name, []).append(symbol.node)
        for local_name, exported_name in self.export_aliases:
            matches = by_local_name.get(local_name, [])
            if len(matches) == 1:
                exported.setdefault(exported_name, []).append(matches[0])
        return {name: tuple(nodes) for name, nodes in exported.items()}


@dataclass(frozen=True, slots=True)
class Provenance:
    path: str
    start_line: int | None
    end_line: int | None
    evidence: str
    method: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "evidence": self.evidence,
            "method": self.method,
        }


@dataclass(frozen=True, slots=True)
class GraphNode:
    id: str
    type: str
    name: str
    path: str
    start_line: int | None = None
    end_line: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class GraphRelation:
    id: str
    source: str
    target: str
    type: str
    provenance: Provenance
    confidence: float
    inferred: bool

    @classmethod
    def create(
        cls,
        source: str,
        target: str,
        relation_type: str,
        provenance: Provenance,
        confidence: float,
        inferred: bool,
    ) -> GraphRelation:
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("Relation confidence must be between zero and one.")
        identity = json.dumps(
            {
                "source": source,
                "target": target,
                "type": relation_type,
                "provenance": provenance.to_dict(),
                "confidence": confidence,
                "inferred": inferred,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        relation_id = "relation:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        return cls(
            id=relation_id,
            source=source,
            target=target,
            type=relation_type,
            provenance=provenance,
            confidence=confidence,
            inferred=inferred,
        )

    @property
    def certainty(self) -> str:
        if not self.inferred and self.confidence >= 1.0:
            return "direct"
        if self.confidence >= 0.9:
            return "high"
        if self.confidence >= 0.7:
            return "medium"
        return "low"

    @property
    def origin(self) -> str:
        return "inferred" if self.inferred else "direct"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "type": self.type,
            "provenance": self.provenance.to_dict(),
            "confidence": self.confidence,
            "certainty": self.certainty,
            "origin": self.origin,
            "inferred": self.inferred,
        }


class ScanRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
