"""Construction of the typed, directed NetworkX knowledge graph."""

from __future__ import annotations

from collections import Counter

import networkx as nx

from . import SCHEMA_VERSION, __version__
from .models import (
    FileAnalysis,
    GraphNode,
    GraphRelation,
    NodeType,
    Provenance,
    RelationType,
    ScanResult,
)
from .resolver import ResolutionResult


def _add_node(graph: nx.MultiDiGraph, node: GraphNode) -> None:
    graph.add_node(node.id, **node.to_dict())


def _add_relation(graph: nx.MultiDiGraph, relation: GraphRelation) -> None:
    graph.add_edge(
        relation.source,
        relation.target,
        key=relation.id,
        **relation.to_dict(),
    )


def _direct_relation(
    source: str,
    target: str,
    relation_type: RelationType,
    path: str,
    line: int | None,
    end_line: int | None,
    evidence: str,
    method: str,
    *,
    confidence: float = 1.0,
    inferred: bool = False,
) -> GraphRelation:
    return GraphRelation.create(
        source=source,
        target=target,
        relation_type=relation_type.value,
        provenance=Provenance(path, line, end_line, evidence, method),
        confidence=confidence,
        inferred=inferred,
    )


def build_graph(
    scan_result: ScanResult,
    analyses: tuple[FileAnalysis, ...] | list[FileAnalysis],
    resolution: ResolutionResult,
) -> nx.MultiDiGraph:
    """Combine extracted syntax and conservative resolutions into a MultiDiGraph."""

    project_name = scan_result.root.name or "project"
    project_node = GraphNode(
        id="project:root",
        type=NodeType.PROJECT.value,
        name=project_name,
        path=".",
        metadata={"language": "javascript-typescript"},
    )
    graph = nx.MultiDiGraph()
    _add_node(graph, project_node)

    for analysis in analyses:
        for node in analysis.nodes:
            _add_node(graph, node)

    structural_relations: list[GraphRelation] = []
    for analysis in analyses:
        structural_relations.append(
            _direct_relation(
                project_node.id,
                analysis.file_node.id,
                RelationType.CONTAINS,
                analysis.path,
                None,
                None,
                "Scanner discovered this source file.",
                "filesystem-scan",
            )
        )
        structural_relations.append(
            _direct_relation(
                analysis.file_node.id,
                analysis.module_node.id,
                RelationType.DEFINES,
                analysis.path,
                None,
                None,
                "The source file is represented as a module by its relative path.",
                "relative-module-path",
                confidence=0.96,
                inferred=True,
            )
        )
        for symbol in analysis.symbols:
            relation_type = (
                RelationType.DEFINES if symbol.parent_type == "module" else RelationType.CONTAINS
            )
            structural_relations.append(
                _direct_relation(
                    symbol.parent_id,
                    symbol.node.id,
                    relation_type,
                    analysis.path,
                    symbol.node.start_line,
                    symbol.node.end_line,
                    f"Tree-sitter declaration: {symbol.node.type} {symbol.node.name}.",
                    "tree-sitter-ast",
                )
            )

    for relation in (*structural_relations, *resolution.relations):
        if relation.source in graph and relation.target in graph:
            _add_relation(graph, relation)

    issues = [*scan_result.issues]
    for analysis in analyses:
        issues.extend(analysis.issues)
    issues.sort(key=lambda item: (item.path, item.reason, item.line or 0))
    language_counts = Counter(
        analysis.module_node.metadata.get("language", "unknown") for analysis in analyses
    )
    graph.graph["schema_version"] = SCHEMA_VERSION
    graph.graph["metadata"] = {
        "tool": "codegraph",
        "tool_version": __version__,
        "project_root": ".",
        "discovered_files": scan_result.discovered_files,
        "analyzed_files": len(scan_result.files),
        "max_file_size_bytes": scan_result.max_file_size_bytes,
        "languages": dict(sorted(language_counts.items())),
        "imports_total": resolution.imports_total,
        "imports_resolved": resolution.imports_resolved,
        "calls_total": resolution.calls_total,
        "calls_resolved": resolution.calls_resolved,
        "inheritance_total": resolution.inheritance_total,
        "inheritance_resolved": resolution.inheritance_resolved,
        "unresolved_imports": list(resolution.unresolved_imports),
        "unresolved_calls": list(resolution.unresolved_calls),
        "issues": [issue.to_dict() for issue in issues],
        "node_count": graph.number_of_nodes(),
        "relation_count": graph.number_of_edges(),
    }
    return graph
