# (c) Copyright Riverlane 2025-2026. All rights reserved.
"""Shared API client and legacy project for compiler and migration tests."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def project():
    return {
        "version": 1,
        "name": "Quantum memory",
        "patches": [
            {
                "id": "p0",
                "name": "Memory",
                "width": 3,
                "height": 3,
                "x": 0,
                "y": 0,
                "vertical_z": True,
            },
        ],
        "operations": [
            {"kind": "prepare", "patch": "p0", "basis": "Z"},
            {"kind": "memory", "patch": "p0", "rounds": 3},
            {"kind": "measure", "patch": "p0", "basis": "Z"},
        ],
    }
