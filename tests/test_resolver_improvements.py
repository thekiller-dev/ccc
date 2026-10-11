from __future__ import annotations

from pathlib import Path

from codegraph.engine import analyze_project


def _has_relation(graph, source: str, target: str, relation_type: str) -> bool:
    return any(
        relation["type"] == relation_type
        for relation in graph.get_edge_data(source, target, default={}).values()
    )


def test_named_and_star_reexports_propagate_through_multiple_barrels(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "original.ts").write_text(
        "export function original() { return 1; }\n", encoding="utf-8"
    )
    (source / "first.ts").write_text(
        'import { original } from "./original";\nexport { original as renamed };\n',
        encoding="utf-8",
    )
    (source / "star.ts").write_text('export * from "./first";\n', encoding="utf-8")
    (source / "final.ts").write_text(
        'export { renamed as publicName } from "./star";\n', encoding="utf-8"
    )
    (source / "classes.ts").write_text(
        "export class Runner { run() { return 2; } }\n", encoding="utf-8"
    )
    (source / "runner.ts").write_text(
        'export { Runner as PublicRunner } from "./classes";\n', encoding="utf-8"
    )
    (source / "main.ts").write_text(
        'import { publicName } from "./final";\n'
        'import { PublicRunner } from "./runner";\n'
        "export function run() { return publicName(); }\n"
        "export function runMethod() { const runner = new PublicRunner(); return runner.run(); }\n",
        encoding="utf-8",
    )

    graph = analyze_project(tmp_path)
    target = "function:src/original.ts::original"

    assert _has_relation(graph, "module:src/main.ts", target, "IMPORTS")
    assert _has_relation(graph, "function:src/main.ts::run", target, "CALLS")
    assert _has_relation(
        graph,
        "module:src/main.ts",
        "class:src/classes.ts::Runner",
        "IMPORTS",
    )
    assert _has_relation(
        graph,
        "function:src/main.ts::runMethod",
        "function:src/classes.ts::Runner.run",
        "CALLS",
    )
    assert graph.graph["metadata"]["unresolved_imports"] == []
    assert graph.graph["metadata"]["unresolved_calls"] == []


def test_star_reexport_cycles_terminate_and_preserve_unique_exports(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "a.ts").write_text(
        'export * from "./b";\nexport function fromA() { return 1; }\n', encoding="utf-8"
    )
    (source / "b.ts").write_text(
        'export * from "./a";\nexport function fromB() { return 2; }\n', encoding="utf-8"
    )
    (source / "main.ts").write_text(
        'import { fromB } from "./a";\nexport function run() { return fromB(); }\n',
        encoding="utf-8",
    )

    graph = analyze_project(tmp_path)

    assert _has_relation(
        graph,
        "function:src/main.ts::run",
        "function:src/b.ts::fromB",
        "CALLS",
    )
    assert graph.graph["metadata"]["unresolved_calls"] == []


def test_ambiguous_star_exports_remain_unresolved(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "left.ts").write_text("export function duplicate() { return 1; }\n", encoding="utf-8")
    (source / "right.ts").write_text(
        "export function duplicate() { return 2; }\n", encoding="utf-8"
    )
    (source / "barrel.ts").write_text(
        'export * from "./left";\nexport * from "./right";\n', encoding="utf-8"
    )
    (source / "main.ts").write_text(
        'import { duplicate } from "./barrel";\nexport function run() { return duplicate(); }\n',
        encoding="utf-8",
    )

    graph = analyze_project(tmp_path)
    left_target = "function:src/left.ts::duplicate"
    right_target = "function:src/right.ts::duplicate"

    assert not _has_relation(graph, "module:src/main.ts", left_target, "IMPORTS")
    assert not _has_relation(graph, "module:src/main.ts", right_target, "IMPORTS")
    assert not _has_relation(graph, "function:src/main.ts::run", left_target, "CALLS")
    assert not _has_relation(graph, "function:src/main.ts::run", right_target, "CALLS")
    assert graph.graph["metadata"]["unresolved_imports"] == []
    assert graph.graph["metadata"]["unresolved_calls"] == [
        {"path": "src/main.ts", "callee": "duplicate", "line": 2}
    ]


def test_only_unique_unreassigned_direct_instance_methods_resolve(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "classes.ts").write_text(
        "export class Worker { run() { return 1; } static runStatic() { return 3; } }\n"
        "export class Other { run() { return 2; } }\n"
        "export class Derived extends Worker {}\n",
        encoding="utf-8",
    )
    (source / "main.ts").write_text(
        'import { Derived, Other, Worker } from "./classes";\n'
        "export function direct() { const worker = new Worker(); return worker.run(); }\n"
        "export function conditional(flag: boolean) {\n"
        "  const worker = flag ? new Worker() : new Other();\n"
        "  return worker.run();\n"
        "}\n"
        "export function reassigned() {\n"
        "  let worker = new Worker();\n"
        "  worker = new Other();\n"
        "  return worker.run();\n"
        "}\n"
        "export function parameter(worker: Worker) { return worker.run(); }\n"
        "export function inherited() { const worker = new Derived(); return worker.run(); }\n"
        "export function staticMethod() { const worker = new Worker(); "
        "return worker.runStatic(); }\n"
        "export function beforeDeclaration() { worker.run(); const worker = new Worker(); }\n"
        "export function closureReassigned() {\n"
        "  let worker = new Worker();\n"
        "  const replace = () => { worker = new Other(); };\n"
        "  replace();\n"
        "  return worker.run();\n"
        "}\n",
        encoding="utf-8",
    )

    graph = analyze_project(tmp_path)
    run_id = "function:src/classes.ts::Worker.run"
    resolved_callers = {
        source_id
        for source_id, target_id, data in graph.edges(data=True)
        if target_id == run_id and data["type"] == "CALLS"
    }

    assert resolved_callers == {"function:src/main.ts::direct"}
    assert graph.graph["metadata"]["unresolved_calls"] == [
        {"path": "src/main.ts", "callee": "worker.run", "line": 5},
        {"path": "src/main.ts", "callee": "worker.run", "line": 10},
        {"path": "src/main.ts", "callee": "worker.run", "line": 12},
        {"path": "src/main.ts", "callee": "worker.run", "line": 13},
        {"path": "src/main.ts", "callee": "worker.runStatic", "line": 14},
        {"path": "src/main.ts", "callee": "worker.run", "line": 15},
        {"path": "src/main.ts", "callee": "replace", "line": 19},
        {"path": "src/main.ts", "callee": "worker.run", "line": 20},
    ]


def test_tree_sitter_026_and_unknown_versions_require_jsx_isolation(monkeypatch) -> None:
    import codegraph.engine as engine

    monkeypatch.setattr(engine, "version", lambda _: "0.25.2")
    assert not engine._requires_isolated_jsx_analysis()
    monkeypatch.setattr(engine, "version", lambda _: "0.26.0")
    assert engine._requires_isolated_jsx_analysis()
    monkeypatch.setattr(engine, "version", lambda _: "unknown")
    assert engine._requires_isolated_jsx_analysis()


def test_tsx_analysis_uses_the_isolated_worker(tmp_path: Path, monkeypatch) -> None:
    import codegraph.engine as engine

    monkeypatch.setattr(engine, "_requires_isolated_jsx_analysis", lambda: True)
    source = tmp_path / "src"
    source.mkdir()
    (source / "Card.tsx").write_text(
        "export function Card() { return <article />; }\n", encoding="utf-8"
    )
    (source / "App.tsx").write_text(
        'import { Card } from "./Card";\nexport function App() { return <Card />; }\n',
        encoding="utf-8",
    )

    graph = analyze_project(tmp_path)

    assert "function:src/App.tsx::App" in graph
    assert "function:src/Card.tsx::Card" in graph
    assert _has_relation(
        graph,
        "module:src/App.tsx",
        "function:src/Card.tsx::Card",
        "IMPORTS",
    )
    assert graph.graph["metadata"]["issues"] == []


def test_native_worker_crash_is_contained_per_jsx_file(monkeypatch) -> None:
    import codegraph._isolation as isolation
    from codegraph.extractor import extract_file
    from codegraph.models import ScannedFile
    from codegraph.parser import parse_file

    broken = ScannedFile("src/Broken.tsx", b"export function Broken() { return <div />; }")
    healthy = ScannedFile("src/Healthy.tsx", b"export function Healthy() { return <main />; }")
    calls: list[tuple[str, ...]] = []

    def fake_worker(files: tuple[ScannedFile, ...]):
        calls.append(tuple(source.path for source in files))
        if len(files) > 1 or files[0].path == broken.path:
            raise isolation._WorkerFailure("native_analysis_crash", "SIGSEGV")
        return (extract_file(parse_file(files[0])),)

    monkeypatch.setattr(isolation, "_run_worker", fake_worker)
    analyses = isolation.analyze_jsx_files((broken, healthy))
    by_path = {analysis.path: analysis for analysis in analyses}

    assert calls == [(broken.path, healthy.path), (broken.path,), (healthy.path,)]
    assert by_path[broken.path].file_node.id == "file:src/Broken.tsx"
    assert by_path[broken.path].issues[0].reason == "native_analysis_crash"
    assert [symbol.node.name for symbol in by_path[healthy.path].symbols] == ["Healthy"]
    assert by_path[healthy.path].issues == ()
