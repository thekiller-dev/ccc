from __future__ import annotations

import shutil
from pathlib import Path

import pytest


@pytest.fixture
def demo_project(tmp_path: Path) -> Path:
    source = Path(__file__).parents[1] / "examples" / "demo-ts"
    destination = tmp_path / "demo-ts"
    shutil.copytree(source, destination)
    return destination
