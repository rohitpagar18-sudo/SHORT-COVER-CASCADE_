"""Acceptance test: a no-op PUT must leave config.yaml byte-identical.

This proves that:
  1. ruamel.yaml round-trip preserves comments, blank lines, and ordering.
  2. ON/OFF boolean style survives the GET → JSON → PUT cycle.
  3. The atomic write produces the exact same bytes.

Run from repo root:
    cd frontend/api
    ../../venv/Scripts/python.exe -m pytest tests/test_roundtrip_noop.py -v

IMPORTANT: this test writes to the REAL config/config.yaml via the API,
then verifies the bytes are unchanged. If bytes differ, the original is
restored before the assertion error is raised.
"""
from __future__ import annotations

import difflib
import sys
from pathlib import Path

import pytest

# Make `app` importable when running from frontend/api/
sys.path.insert(0, str(Path(__file__).parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.paths import CONFIG_PATH  # noqa: E402

client = TestClient(app)


def test_roundtrip_noop() -> None:
    """GET full config → PUT it back unchanged → assert file is byte-identical."""
    original_bytes = CONFIG_PATH.read_bytes()

    # GET
    r_get = client.get("/api/config")
    assert r_get.status_code == 200, f"GET /api/config failed: {r_get.status_code} {r_get.text[:200]}"
    config_json = r_get.json()

    # PUT (no-op: every value is the same as currently on disk)
    r_put = client.put("/api/config", json=config_json)
    if r_put.status_code != 200:
        # Restore before failing
        CONFIG_PATH.write_bytes(original_bytes)
        pytest.fail(f"PUT /api/config failed: {r_put.status_code} {r_put.text[:400]}")

    after_bytes = CONFIG_PATH.read_bytes()

    if original_bytes != after_bytes:
        # Restore the original so the repo stays clean
        CONFIG_PATH.write_bytes(original_bytes)

        a_lines = original_bytes.decode("utf-8", errors="replace").splitlines()
        b_lines = after_bytes.decode("utf-8", errors="replace").splitlines()
        diff = "\n".join(
            list(difflib.unified_diff(a_lines, b_lines, fromfile="before", tofile="after", lineterm="", n=3))[:80]
        )
        pytest.fail(
            "config.yaml changed after a no-op PUT — ON/OFF style or comments not preserved!\n\n"
            + diff
        )
