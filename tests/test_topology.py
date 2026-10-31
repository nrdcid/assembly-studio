# (c) Copyright Riverlane 2025-2026. All rights reserved.
"""Topology contracts checked against real compiler geometry."""

import copy
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import Project, app, compile_project
from qec.topology import extract_topology


def memory_project(distance=3, vertical_z=True):
    return Project.model_validate(
        {
            "version": 1,
            "name": "Topology",
            "patches": [
                {
                    "id": "p0",
                    "name": "Memory",
                    "width": distance,
                    "height": distance,
                    "x": 2,
                    "y": 3,
                    "vertical_z": vertical_z,
                }
            ],
            "operations": [
                {"kind": "prepare", "patch": "p0", "basis": "Z"},
                {"kind": "memory", "patch": "p0", "rounds": 3},
            ],
        }
    )


def binary_rank(rows):
    pivots = {}
    for original in rows:
        row = original
        while row:
            pivot = row.bit_length()
            if pivot not in pivots:
                pivots[pivot] = row
                break
            row ^= pivots[pivot]
    return len(pivots)


@pytest.mark.parametrize("distance", [3, 5])
@pytest.mark.parametrize("vertical_z", [True, False])
def test_real_compiler_support_and_independent_generators(distance, vertical_z):
    result = compile_project(memory_project(distance, vertical_z))
    topology = result["topology"]
    assert [t["round"] for t in topology] == [1, 2, 3]
    assert [t["patch_round"] for t in topology] == [1, 2, 3]
    first = topology[0]
    assert first["patch_id"] == "p0"
    assert len(first["data_qubits"]) == distance**2
    assert len(first["checks"]) == distance**2 - 1
    positions = {q["id"]: tuple(q["position"]) for q in first["data_qubits"]}
    raw = result["patches"]["ops"][0]
    raw_data = {q["id"]: tuple(q["coordinates"]) for q in raw["qubits"] if q["type"] == "data"}
    assert set(positions.values()) == set(raw_data.values())
    expected = {
        (
            {"red": "X", "blue": "Z"}[p["colour"]],
            p["weight"],
            frozenset(raw_data[q] for q in p["coordinates"] if q in raw_data),
        )
        for patch in raw["patches"]
        for p in patch["plaquettes"]
    }
    actual = {
        (c["basis"], c["weight"], frozenset(positions[q] for q in c["data_qubits"]))
        for c in first["checks"]
    }
    assert actual == expected
    assert {c["weight"] for c in first["checks"]} == {2, 4}
    rows = []
    for check in first["checks"]:
        assert check["weight"] == len(check["data_qubits"])
        offset = 0 if check["basis"] == "X" else len(positions)
        rows.append(
            sum(
                1 << (index + offset)
                for index, q in enumerate(positions)
                if q in check["data_qubits"]
            )
        )
        for other in first["checks"]:
            if check["basis"] != other["basis"]:
                assert len(set(check["data_qubits"]) & set(other["data_qubits"])) % 2 == 0
    assert binary_rank(rows) == distance**2 - 1
    for later in topology[1:]:
        assert later["checks"] == first["checks"]
        assert later["data_qubits"] == first["data_qubits"]


def test_api_interleaved_round_ownership_and_patch_isolation():
    project = memory_project().model_dump()
    project["patches"].append({**project["patches"][0], "id": "p1", "x": 10})
    project["operations"] = [
        {"kind": "prepare", "patch": "p0", "basis": "Z"},
        {"kind": "prepare", "patch": "p1", "basis": "X"},
        {"kind": "memory", "patch": "p0", "rounds": 2},
        {"kind": "memory", "patch": "p1", "rounds": 1},
        {"kind": "memory", "patch": "p0", "rounds": 1},
    ]
    client = TestClient(app)
    response = client.post("/api/compile", json=project)
    assert response.status_code == 200, response.text
    topology = response.json()["topology"]
    assert [(t["patch_id"], t["round"], t["patch_round"]) for t in topology] == [
        ("p0", 1, 1),
        ("p0", 2, 2),
        ("p1", 3, 1),
        ("p0", 4, 3),
    ]
    for field in ("checks", "data_qubits"):
        assert topology[0][field] == topology[3][field]
        assert not ({v["id"] for v in topology[0][field]} & {v["id"] for v in topology[2][field]})
    assert client.post("/api/compile", json=project).json() == response.json()


def test_extraction_ignores_rendering_ids_order_and_does_not_mutate():
    raw = compile_project(memory_project())["patches"]["ops"][0]
    original = copy.deepcopy(raw)
    first = extract_topology(raw, patch_id="p0", patch_round=1)
    assert raw == original
    renamed = {q["id"]: f"renamed_{i}" for i, q in enumerate(raw["qubits"])}
    for q in raw["qubits"]:
        q["id"] = renamed[q["id"]]
    raw["qubits"].reverse()
    for patch in raw["patches"]:
        patch["plaquettes"].reverse()
        for p in patch["plaquettes"]:
            p["id"] = 999
            p["coordinates"] = [renamed[q] for q in reversed(p["coordinates"])]
    assert extract_topology(raw, patch_id="p0", patch_round=1) == first
    other = extract_topology(raw, patch_id="p1", patch_round=1)
    for field in ("checks", "data_qubits"):
        assert not ({v["id"] for v in first[field]} & {v["id"] for v in other[field]})


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("colour", "green", "colour"),
        ("weight", 99, "weight"),
        ("coordinates", ["missing"], "reference"),
    ],
)
def test_unsupported_compiler_plaquettes_fail_explicitly(field, value, message):
    raw = compile_project(memory_project())["patches"]["ops"][0]
    raw["patches"][0]["plaquettes"][0][field] = value
    with pytest.raises(ValueError, match=message):
        extract_topology(raw, patch_id="p0", patch_round=1)
