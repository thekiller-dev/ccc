"""Command-line interface backed by the same analysis engine as the API."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .engine import analyze_project
from .exporter import export_json
from .report import graph_stats, render_report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codegraph",
        description="Statically scan JavaScript and TypeScript projects.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("scan", "stats", "export", "report"):
        child = commands.add_parser(command, help=f"{command} a project")
        child.add_argument("path", type=Path, help="project directory")
        if command in {"scan", "export"}:
            child.add_argument("--output", type=Path, help="graph JSON destination")
        if command in {"scan", "report"}:
            child.add_argument("--report-output", type=Path, help="Markdown report destination")
        child.add_argument(
            "--max-file-size",
            type=int,
            default=1_000_000,
            metavar="BYTES",
            help="maximum source file size (default: 1000000)",
        )
    return parser


def _output_dir(project_path: Path) -> Path:
    return project_path.expanduser().resolve() / ".codegraph"


def _run(args: argparse.Namespace) -> int:
    if args.max_file_size <= 0:
        print("codegraph: --max-file-size must be greater than zero", file=sys.stderr)
        return 2
    try:
        graph = analyze_project(args.path, max_file_size_bytes=args.max_file_size)
        stats = graph_stats(graph)
        default_dir = _output_dir(args.path)

        if args.command == "stats":
            print(json.dumps(stats, ensure_ascii=False, indent=2, sort_keys=True))
            return 0

        if args.command in {"scan", "export"}:
            output = args.output or (default_dir / "graph.json")
            path = export_json(graph, output)
            if args.command == "export":
                print(f"Graph JSON written to {path}")
                return 0

        if args.command in {"scan", "report"}:
            report_path = args.report_output or (default_dir / "report.md")
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(render_report(graph), encoding="utf-8")
            if args.command == "report":
                print(f"Markdown report written to {report_path.resolve()}")
                return 0
            print(
                f"Scan complete: {stats['files']} files, {stats['symbols']} symbols, "
                f"{stats['relations']} relations, {stats['issues']} issue(s)."
            )
            print(f"Graph JSON: {(args.output or default_dir / 'graph.json').resolve()}")
            print(f"Markdown report: {report_path.resolve()}")
            return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(f"codegraph: {error}", file=sys.stderr)
        return 2
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
