"""Versioned JSON export of CodeGraph's NetworkX graph."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import networkx as nx

from . import SCHEMA_VERSION


def graph_to_dict(graph: nx.MultiDiGraph) -> dict[str, Any]:
    """Return deterministic JSON-compatible data using schema version 1.0."""

    nodes = [dict(data) for _, data in sorted(graph.nodes(data=True), key=lambda item: item[0])]
    relations: list[dict[str, Any]] = []
    for source, target, key, data in graph.edges(keys=True, data=True):
        relations.append(
            {
                "id": data.get("id", str(key)),
                "source": source,
                "target": target,
                "type": data.get("type"),
                "provenance": dict(data.get("provenance", {})),
                "confidence": data.get("confidence"),
                "certainty": data.get("certainty"),
                "origin": data.get("origin"),
                "inferred": data.get("inferred"),
            }
        )
    relations.sort(
        key=lambda item: (item["source"], item["target"], item["type"] or "", item["id"])
    )
    return {
        "schema_version": graph.graph.get("schema_version", SCHEMA_VERSION),
        "metadata": dict(graph.graph.get("metadata", {})),
        "nodes": nodes,
        "relations": relations,
    }


def export_json(graph: nx.MultiDiGraph, destination: str | Path) -> Path:
    """Write graph JSON as UTF-8 and return the absolute destination path."""

    output = Path(destination).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    document = json.dumps(
        graph_to_dict(graph),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    output.write_text(document + "\n", encoding="utf-8")
    return output.resolve()
