from __future__ import annotations

import json
from pathlib import Path

import networkx as nx

from codegraph.engine import analyze_project
from codegraph.exporter import export_json, graph_to_dict
from codegraph.report import graph_stats, render_report


def test_graph_contains_required_types_and_typed_confident_relations(demo_project: Path) -> None:
    graph = analyze_project(demo_project)
    document = graph_to_dict(graph)
    node_types = {node["type"] for node in document["nodes"]}
    relation_types = {relation["type"] for relation in document["relations"]}

    assert isinstance(graph, nx.MultiDiGraph)
    assert {"project", "file", "module", "function", "class", "interface", "type"} <= node_types
    assert {"CONTAINS", "DEFINES", "IMPORTS", "CALLS", "EXTENDS", "IMPLEMENTS"} <= relation_types
    assert all(
        {"type", "provenance", "confidence", "certainty", "origin", "inferred"} <= relation.keys()
        and {"path", "start_line", "end_line", "evidence", "method"}
        <= relation["provenance"].keys()
        for relation in document["relations"]
    )
    assert all(0.0 <= relation["confidence"] <= 1.0 for relation in document["relations"])
    assert any(relation["origin"] == "direct" for relation in document["relations"])
    assert any(relation["origin"] == "inferred" for relation in document["relations"])
    assert document["schema_version"] == "1.0"


def test_import_calls_extends_implements_and_unknowns_are_conservative(
    demo_project: Path,
) -> None:
    graph = analyze_project(demo_project)
    main_id = "function:src/main.ts::main"
    greet_id = "function:src/utils/greet.ts::greet"
    class_id = "class:src/greeter.ts::Greeter"
    base_id = "class:src/base.ts::BaseThing"
    interface_id = "interface:src/types.ts::Greeting"

    assert graph.has_edge(main_id, greet_id, key=next(iter(graph[main_id][greet_id])))
    assert graph.has_edge(class_id, base_id, key=next(iter(graph[class_id][base_id])))
    assert graph.has_edge(class_id, interface_id, key=next(iter(graph[class_id][interface_id])))
    assert graph.graph["metadata"]["unresolved_imports"] == [
        {"path": "src/main.ts", "specifier": "./missing", "line": 3}
    ]
    # A direct new Greeter() receiver resolves to its unique greet method.
    method_id = "function:src/greeter.ts::Greeter.greet"
    assert graph.has_edge(main_id, method_id)
    assert graph.graph["metadata"]["calls_resolved"] == graph.graph["metadata"]["calls_total"]


def test_resolver_handles_index_files_and_js_to_ts_extension_substitution(tmp_path: Path) -> None:
    (tmp_path / "src" / "folder").mkdir(parents=True)
    (tmp_path / "src" / "entry.ts").write_text(
        'import { fromIndex } from "./folder";\n'
        'import { fromMappedJs } from "./mapped.js";\n'
        "export function run() { return fromIndex() + fromMappedJs(); }\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "folder" / "index.ts").write_text(
        "export function fromIndex() { return 1; }\n", encoding="utf-8"
    )
    (tmp_path / "src" / "mapped.ts").write_text(
        "export function fromMappedJs() { return 2; }\n", encoding="utf-8"
    )

    graph = analyze_project(tmp_path)
    entry_module = "module:src/entry.ts"

    assert graph.has_edge(entry_module, "module:src/folder/index.ts")
    assert graph.has_edge(entry_module, "module:src/mapped.ts")
    assert graph.graph["metadata"]["imports_resolved"] == 2
    assert graph.graph["metadata"]["calls_resolved"] == 2


def test_stable_ids_json_serialization_and_markdown_report(
    demo_project: Path, tmp_path: Path
) -> None:
    first = graph_to_dict(analyze_project(demo_project))
    second = graph_to_dict(analyze_project(demo_project))
    assert [node["id"] for node in first["nodes"]] == [node["id"] for node in second["nodes"]]
    assert [relation["id"] for relation in first["relations"]] == [
        relation["id"] for relation in second["relations"]
    ]
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    output = export_json(analyze_project(demo_project), tmp_path / "graph.json")
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["schema_version"] == "1.0"
    assert len(saved["nodes"]) == first["metadata"]["node_count"]
    assert all(relation["provenance"]["path"] for relation in saved["relations"])

    stats = graph_stats(analyze_project(demo_project))
    report = render_report(analyze_project(demo_project))
    assert stats["imports"]["total"] > stats["imports"]["resolved"]
    assert stats["calls"]["resolved"] >= 1
    assert "## Limites et sécurité" in report
    assert "Imports non résolus" in report
    assert "jamais exécuté" in report
