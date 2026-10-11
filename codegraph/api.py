"""Local HTTP API for scanning and querying in-memory project graphs."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

import networkx as nx
from fastapi import FastAPI, HTTPException

from . import SCHEMA_VERSION
from .engine import analyze_project
from .exporter import graph_to_dict
from .models import ScanRequest
from .report import graph_stats


@dataclass(frozen=True, slots=True)
class _ProjectState:
    path: Path
    graph: nx.MultiDiGraph


def _project_identifier(relative_path: str) -> str:
    return hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:20]


def create_app(project_root: str | Path | None = None) -> FastAPI:
    """Create an API instance restricted to one explicitly allowed directory."""

    configured_root = project_root or os.environ.get("CODEGRAPH_PROJECTS_ROOT") or Path.cwd()
    allowed_root = Path(configured_root).expanduser().resolve(strict=True)
    if not allowed_root.is_dir():
        raise NotADirectoryError("The configured projects root must be a directory.")

    projects: dict[str, _ProjectState] = {}
    project_lock = RLock()
    app = FastAPI(
        title="CodeGraph API",
        version="0.2.0",
        description="Local, static JavaScript and TypeScript code graph analysis.",
    )

    def validate_path(value: str) -> Path:
        if "\x00" in value:
            raise HTTPException(status_code=422, detail="Invalid project path.")
        requested = Path(value).expanduser()
        if ".." in requested.parts:
            raise HTTPException(
                status_code=400,
                detail="Parent-directory traversal is not allowed.",
            )
        candidate = requested if requested.is_absolute() else allowed_root / requested
        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="Project path was not found.") from error
        except (OSError, RuntimeError) as error:
            raise HTTPException(
                status_code=400,
                detail="Project path could not be validated.",
            ) from error
        if not resolved.is_relative_to(allowed_root):
            raise HTTPException(status_code=403, detail="Project path is outside the allowed root.")
        if not resolved.is_dir():
            raise HTTPException(status_code=422, detail="Project path must be a directory.")
        return resolved

    def get_project(project_id: str) -> _ProjectState:
        with project_lock:
            state = projects.get(project_id)
        if state is None:
            raise HTTPException(status_code=404, detail="Unknown project id.")
        return state

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "schema_version": SCHEMA_VERSION}

    @app.post("/api/scan")
    def scan(request: ScanRequest) -> dict[str, Any]:
        project_path = validate_path(request.path)
        try:
            graph = analyze_project(project_path)
        except (OSError, ValueError, RuntimeError) as error:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Project could not be analysed; inspect scanner diagnostics and file limits."
                ),
            ) from error
        relative_path = project_path.relative_to(allowed_root).as_posix() or "."
        project_id = _project_identifier(relative_path)
        graph.graph.setdefault("metadata", {})["project_id"] = project_id
        graph.graph["metadata"]["project_path"] = relative_path
        with project_lock:
            projects[project_id] = _ProjectState(project_path, graph)
        return {"project_id": project_id, "stats": graph_stats(graph)}

    @app.get("/api/projects/{project_id}/graph")
    def graph_document(project_id: str) -> dict[str, Any]:
        state = get_project(project_id)
        return graph_to_dict(state.graph)

    @app.get("/api/projects/{project_id}/stats")
    def stats(project_id: str) -> dict[str, Any]:
        return graph_stats(get_project(project_id).graph)

    @app.get("/api/projects/{project_id}/nodes/{node_id:path}")
    def node(project_id: str, node_id: str) -> dict[str, Any]:
        graph = get_project(project_id).graph
        if node_id not in graph:
            raise HTTPException(status_code=404, detail="Unknown node id.")
        return dict(graph.nodes[node_id])

    return app


app = create_app()


def run() -> None:
    """Start Uvicorn on loopback unless an explicit host override is provided."""

    import uvicorn

    host = os.environ.get("CODEGRAPH_API_HOST", "127.0.0.1")
    port = int(os.environ.get("CODEGRAPH_API_PORT", "8000"))
    uvicorn.run("codegraph.api:app", host=host, port=port, reload=False)
