from __future__ import annotations

import json
from pathlib import Path

from codegraph.cli import main


def test_cli_scan_stats_export_and_report(demo_project: Path, capsys) -> None:
    assert main(["scan", str(demo_project)]) == 0
    scan_output = capsys.readouterr().out
    assert "Scan complete" in scan_output
    graph_path = demo_project / ".codegraph" / "graph.json"
    report_path = demo_project / ".codegraph" / "report.md"
    assert graph_path.exists() and report_path.exists()

    assert main(["stats", str(demo_project)]) == 0
    stats = json.loads(capsys.readouterr().out)
    assert stats["files"] >= 5

    export_path = demo_project.parent / "export.json"
    assert main(["export", str(demo_project), "--output", str(export_path)]) == 0
    capsys.readouterr()
    assert json.loads(export_path.read_text(encoding="utf-8"))["schema_version"] == "1.0"

    report_out = demo_project.parent / "custom-report.md"
    assert main(["report", str(demo_project), "--report-output", str(report_out)]) == 0
    capsys.readouterr()
    assert "CodeGraph" in report_out.read_text(encoding="utf-8")
