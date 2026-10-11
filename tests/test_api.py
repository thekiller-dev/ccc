from __future__ import annotations

import shutil
from pathlib import Path
from urllib.parse import quote

from fastapi.testclient import TestClient

from codegraph.api import create_app


def test_api_health_scan_graph_stats_and_node_lookup(demo_project: Path, tmp_path: Path) -> None:
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    project_path = allowed_root / "demo"
    shutil.copytree(demo_project, project_path)
    client = TestClient(create_app(allowed_root))

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["schema_version"] == "1.0"

    scan = client.post("/api/scan", json={"path": "demo"})
    assert scan.status_code == 200
    project_id = scan.json()["project_id"]
    assert scan.json()["stats"]["files"] >= 5

    graph_response = client.get(f"/api/projects/{project_id}/graph")
    assert graph_response.status_code == 200
    graph = graph_response.json()
    assert graph["schema_version"] == "1.0"
    assert any(node["type"] == "interface" for node in graph["nodes"])

    stats = client.get(f"/api/projects/{project_id}/stats")
    assert stats.status_code == 200
    assert stats.json()["calls"]["resolved"] >= 1

    node_id = "function:src/main.ts::main"
    node_response = client.get(f"/api/projects/{project_id}/nodes/{quote(node_id, safe=':')}")
    assert node_response.status_code == 200
    assert node_response.json()["id"] == node_id
    assert client.get(f"/api/projects/{project_id}/nodes/unknown").status_code == 404
    assert client.post("/api/exec", json={"command": "anything"}).status_code == 404


def test_api_rejects_path_traversal_and_symlink_escape(tmp_path: Path) -> None:
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "index.ts").write_text("export {};", encoding="utf-8")
    (allowed_root / "escape").symlink_to(outside, target_is_directory=True)
    client = TestClient(create_app(allowed_root))

    traversal = client.post("/api/scan", json={"path": "../outside"})
    symlink = client.post("/api/scan", json={"path": "escape"})
    non_directory = client.post("/api/scan", json={"path": "escape/index.ts"})

    assert traversal.status_code == 400
    assert symlink.status_code == 403
    assert non_directory.status_code == 403
