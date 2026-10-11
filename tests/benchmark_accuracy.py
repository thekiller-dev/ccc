"""Reproducible, fixture-only CodeGraph precision and robustness benchmark.

Run from the repository root with:
    .venv/bin/python tests/benchmark_accuracy.py --iterations 7

The score covers only the explicitly hand-labelled IMPORTS, CALLS, EXTENDS,
and IMPLEMENTS facts in the JSON manifest. JSX rendering is reported as an
out-of-schema expectation, not silently included in recall.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import signal
import statistics
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from codegraph.engine import analyze_project
from codegraph.exporter import graph_to_dict
from codegraph.report import graph_stats
from codegraph.scanner import scan_project

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE_ROOT = _REPO_ROOT / "tests" / "fixtures" / "benchmark"
_MANIFEST_PATH = _FIXTURE_ROOT / "expected.json"
_SCORED_RELATIONS = {"IMPORTS", "CALLS", "EXTENDS", "IMPLEMENTS"}
_RELATION_KEYS = {
    "id",
    "source",
    "target",
    "type",
    "provenance",
    "confidence",
    "certainty",
    "origin",
    "inferred",
}
_NODE_KEYS = {"id", "type", "name", "path", "start_line", "end_line", "metadata"}
_DOCUMENT_KEYS = {"schema_version", "metadata", "nodes", "relations"}


def _relation_key(relation: dict[str, Any]) -> tuple[str, str, str, str, int | None]:
    provenance = relation["provenance"]
    return (
        relation["type"],
        relation["source"],
        relation["target"],
        provenance["path"],
        provenance["start_line"],
    )


def _expected_relation_key(relation: dict[str, Any]) -> tuple[str, str, str, str, int | None]:
    return (
        relation["type"],
        relation["source"],
        relation["target"],
        relation["path"],
        relation["line"],
    )


def _key_tuple(item: dict[str, Any], fields: tuple[str, ...]) -> tuple[Any, ...]:
    return tuple(item[field] for field in fields)


def _measure(project: Path, iterations: int) -> tuple[dict[str, Any], list[float]]:
    first = graph_to_dict(analyze_project(project))
    second = graph_to_dict(analyze_project(project))
    stable = first == second

    # One warm-up is excluded; measurements include scanning, parsing,
    # extraction, resolution, and graph construction, but not JSON export.
    analyze_project(project)
    samples_ms = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        graph = analyze_project(project)
        samples_ms.append((time.perf_counter_ns() - started) / 1_000_000)
    return {
        "graph": graph,
        "stable_ids_and_export": stable,
        "stats": graph_stats(graph),
    }, samples_ms


def _accuracy_result(
    graph: Any, document: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    expected_nodes = {"project:root", *expected["expected_symbols"]}
    for path in expected["source_paths"]:
        expected_nodes.update({f"file:{path}", f"module:{path}"})
    actual_nodes = set(graph.nodes)

    expected_relations = Counter(
        _expected_relation_key(item) for item in expected["expected_relations"]
    )
    actual_relation_data = [
        relation for relation in document["relations"] if relation["type"] in _SCORED_RELATIONS
    ]
    actual_relations = Counter(_relation_key(item) for item in actual_relation_data)
    true_positives = expected_relations & actual_relations
    false_negatives = expected_relations - actual_relations
    false_positives = actual_relations - expected_relations

    expected_imports = Counter(
        _key_tuple(item, ("path", "specifier", "line"))
        for item in expected["expected_unresolved_imports"]
    )
    actual_imports = Counter(
        _key_tuple(item, ("path", "specifier", "line"))
        for item in graph.graph["metadata"]["unresolved_imports"]
    )
    expected_calls = Counter(
        _key_tuple(item, ("path", "callee", "line"))
        for item in expected["expected_unresolved_calls"]
    )
    actual_calls = Counter(
        _key_tuple(item, ("path", "callee", "line"))
        for item in graph.graph["metadata"]["unresolved_calls"]
    )
    expected_issues = Counter(
        _key_tuple(item, ("path", "reason")) for item in expected["expected_issues"]
    )
    actual_issues = Counter(
        _key_tuple(item, ("path", "reason")) for item in graph.graph["metadata"]["issues"]
    )

    absent_site_results = []
    for site in expected["no_relation_sites"]:
        matches = []
        for relation in actual_relation_data:
            provenance = relation["provenance"]
            if (
                relation["type"] == site["type"]
                and relation["source"] == site["source"]
                and provenance["path"] == site["path"]
                and provenance["start_line"] == site["line"]
                and ("target" not in site or relation["target"] == site["target"])
            ):
                matches.append(relation)
        absent_site_results.append(
            {
                **site,
                "correctly_absent": not matches,
                "unexpected_relations": matches,
            }
        )

    actual_source_paths = {
        data["path"] for _, data in graph.nodes(data=True) if data.get("type") in {"file", "module"}
    }
    schema_valid = (
        set(document) == _DOCUMENT_KEYS
        and document["schema_version"] == "1.0"
        and all(set(item) == _NODE_KEYS for item in document["nodes"])
        and all(set(item) == _RELATION_KEYS for item in document["relations"])
    )

    expected_relation_by_key = {
        _expected_relation_key(item): item for item in expected["expected_relations"]
    }
    actual_relation_by_key = {_relation_key(item): item for item in actual_relation_data}
    actual_relation_summary = [
        {
            "type": item["type"],
            "source": item["source"],
            "target": item["target"],
            "path": item["provenance"]["path"],
            "line": item["provenance"]["start_line"],
            "method": item["provenance"]["method"],
        }
        for item in actual_relation_data
    ]

    expected_count = sum(expected_relations.values())
    actual_count = sum(actual_relations.values())
    tp_count = sum(true_positives.values())
    fp_count = sum(false_positives.values())
    fn_count = sum(false_negatives.values())
    return {
        "nodes": {
            "expected_count": len(expected_nodes),
            "actual_count": len(actual_nodes),
            "missing": sorted(expected_nodes - actual_nodes),
            "unexpected": sorted(actual_nodes - expected_nodes),
        },
        "relations": {
            "expected_count": expected_count,
            "actual_count": actual_count,
            "true_positives": tp_count,
            "incorrect": [
                actual_relation_by_key[key]
                for key, count in sorted(false_positives.items())
                for _ in range(count)
            ],
            "missing": [
                expected_relation_by_key[key]
                for key, count in sorted(false_negatives.items())
                for _ in range(count)
            ],
            "precision": tp_count / (tp_count + fp_count) if tp_count + fp_count else None,
            "recall": tp_count / (tp_count + fn_count) if tp_count + fn_count else None,
            "by_type": {
                relation_type: {
                    "expected": sum(
                        count
                        for key, count in expected_relations.items()
                        if key[0] == relation_type
                    ),
                    "actual": sum(
                        count for key, count in actual_relations.items() if key[0] == relation_type
                    ),
                    "tp": sum(
                        count for key, count in true_positives.items() if key[0] == relation_type
                    ),
                    "fp": sum(
                        count for key, count in false_positives.items() if key[0] == relation_type
                    ),
                    "fn": sum(
                        count for key, count in false_negatives.items() if key[0] == relation_type
                    ),
                }
                for relation_type in sorted(_SCORED_RELATIONS)
                if any(key[0] == relation_type for key in expected_relations)
                or any(key[0] == relation_type for key in actual_relations)
            },
            "actual_facts": actual_relation_summary,
        },
        "unresolved_imports": {
            "expected": expected["expected_unresolved_imports"],
            "actual": graph.graph["metadata"]["unresolved_imports"],
            "missing": list(expected_imports - actual_imports),
            "unexpected": list(actual_imports - expected_imports),
        },
        "unresolved_calls": {
            "expected": expected["expected_unresolved_calls"],
            "actual": graph.graph["metadata"]["unresolved_calls"],
            "missing": list(expected_calls - actual_calls),
            "unexpected": list(actual_calls - expected_calls),
        },
        "no_relation_sites": absent_site_results,
        "issues": {
            "expected": expected["expected_issues"],
            "actual": graph.graph["metadata"]["issues"],
            "missing": list(expected_issues - actual_issues),
            "unexpected": list(actual_issues - expected_issues),
        },
        "excluded_paths": {
            "expected": expected["excluded_paths"],
            "incorrectly_present": sorted(set(expected["excluded_paths"]) & actual_source_paths),
        },
        "schema_version": document["schema_version"],
        "schema_valid": schema_valid,
        "provenance_present": all(
            bool(item["provenance"].get("path"))
            and item["provenance"].get("start_line") is not None
            and bool(item["provenance"].get("evidence"))
            and bool(item["provenance"].get("method"))
            for item in actual_relation_data
        ),
        "unsupported_expectations": expected.get("unsupported_expectations", []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=7)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--isolated-project", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("--iterations must be at least 1")
    if args.isolated_project is not None:
        measured, samples_ms = _measure(args.isolated_project, args.iterations)
        print(
            json.dumps(
                {
                    "stats": measured["stats"],
                    "stable_ids_and_export": measured["stable_ids_and_export"],
                    "timing_ms": {
                        "median": statistics.median(samples_ms),
                        "min": min(samples_ms),
                        "max": max(samples_ms),
                        "samples": samples_ms,
                    },
                },
                ensure_ascii=False,
            )
        )
        return 0

    manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    results: dict[str, Any] = {
        "environment": {
            "python": platform.python_version(),
            "iterations": args.iterations,
            "timing_scope": "analyze_project only; excludes export/CLI serialization",
        },
        "fixtures": {},
        "local_projects": {},
    }

    for name, expected in manifest.items():
        project = _FIXTURE_ROOT / name
        measured, samples_ms = _measure(project, args.iterations)
        document = graph_to_dict(measured["graph"])
        results["fixtures"][name] = {
            "stats": measured["stats"],
            "stable_ids_and_export": measured["stable_ids_and_export"],
            "accuracy": _accuracy_result(measured["graph"], document, expected),
            "timing_ms": {
                "median": statistics.median(samples_ms),
                "min": min(samples_ms),
                "max": max(samples_ms),
                "samples": samples_ms,
            },
        }

    demo_project = _REPO_ROOT / "examples" / "demo-ts"
    measured, samples_ms = _measure(demo_project, args.iterations)
    results["local_projects"]["examples_demo_ts"] = {
        "stats": measured["stats"],
        "stable_ids_and_export": measured["stable_ids_and_export"],
        "timing_ms": {
            "median": statistics.median(samples_ms),
            "min": min(samples_ms),
            "max": max(samples_ms),
            "samples": samples_ms,
        },
    }

    # The larger local frontend is isolated in a child process: a native
    # Tree-sitter segmentation fault must be reported, not terminate the
    # controlled-fixture results or corrupt this benchmark report.
    frontend = _REPO_ROOT / "frontend"
    scan_samples_ms = []
    scan_result = scan_project(frontend)
    for _ in range(args.iterations):
        started = time.perf_counter_ns()
        scan_result = scan_project(frontend)
        scan_samples_ms.append((time.perf_counter_ns() - started) / 1_000_000)
    child_env = dict(os.environ)
    child_env["PYTHONFAULTHANDLER"] = "1"
    child = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--isolated-project",
            str(frontend),
            "--iterations",
            str(args.iterations),
        ],
        cwd=_REPO_ROOT,
        env=child_env,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    if child.returncode == 0:
        frontend_analysis = json.loads(child.stdout)
    else:
        frontend_analysis = {
            "status": "crashed" if child.returncode < 0 else "failed",
            "returncode": child.returncode,
            "signal": (signal.Signals(-child.returncode).name if child.returncode < 0 else None),
            "stderr": child.stderr.strip(),
        }
    results["local_projects"]["frontend"] = {
        "analysis": frontend_analysis,
        "scanner": {
            "discovered_files": scan_result.discovered_files,
            "analyzed_files": len(scan_result.files),
            "source_bytes": sum(len(item.source) for item in scan_result.files),
            "issues": [issue.to_dict() for issue in scan_result.issues],
            "timing_ms": {
                "median": statistics.median(scan_samples_ms),
                "min": min(scan_samples_ms),
                "max": max(scan_samples_ms),
                "samples": scan_samples_ms,
            },
        },
    }

    expected_total = sum(
        item["accuracy"]["relations"]["expected_count"] for item in results["fixtures"].values()
    )
    actual_total = sum(
        item["accuracy"]["relations"]["actual_count"] for item in results["fixtures"].values()
    )
    tp_total = sum(
        item["accuracy"]["relations"]["true_positives"] for item in results["fixtures"].values()
    )
    fp_total = sum(
        len(item["accuracy"]["relations"]["incorrect"]) for item in results["fixtures"].values()
    )
    fn_total = sum(
        len(item["accuracy"]["relations"]["missing"]) for item in results["fixtures"].values()
    )
    results["aggregate"] = {
        "expected_relations": expected_total,
        "actual_relations": actual_total,
        "tp": tp_total,
        "fp": fp_total,
        "fn": fn_total,
        "precision": tp_total / (tp_total + fp_total) if tp_total + fp_total else None,
        "recall": tp_total / (tp_total + fn_total) if tp_total + fn_total else None,
    }

    encoded = json.dumps(results, indent=2, ensure_ascii=False, sort_keys=True)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
