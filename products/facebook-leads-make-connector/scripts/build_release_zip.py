#!/usr/bin/env python3
"""Builds the zip a one-time buyer downloads. Run at Docker image build time
(see Dockerfile) so the served zip always matches what's actually deployed
-- never hand-built and committed, and never includes secrets: .env is
excluded on purpose, only .env.example ships."""

from __future__ import annotations

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "dist" / "leadbridge-src.zip"

INCLUDE = ["src", "tests", "docs", "README.md", "pyproject.toml", ".env.example", "Dockerfile"]
EXCLUDE_DIR_NAMES = {"__pycache__", ".venv", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
EXCLUDE_SUFFIXES = {".sqlite3", ".pyc"}


def _should_skip(path: Path) -> bool:
    return any(part in EXCLUDE_DIR_NAMES for part in path.parts) or path.suffix in EXCLUDE_SUFFIXES


def build() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in INCLUDE:
            source = ROOT / name
            if source.is_file():
                zf.write(source, arcname=f"leadbridge/{name}")
                continue
            for file_path in source.rglob("*"):
                if file_path.is_file() and not _should_skip(file_path):
                    zf.write(file_path, arcname=f"leadbridge/{file_path.relative_to(ROOT)}")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    build()
