"""Behavioral tests for the Assembly Studio pilot, using real compiler passes."""

import copy
import subprocess
import sys

import pytest
from deltakit_visualise import LogicalAssemblyVisualiser
from xdsl.parser import Parser

from app import Project, compile_project


def test_memory_compiles_into_both_real_visualisation_payloads(client, project):
    response = client.post("/api/compile", json=project)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["spacetime"]["type"] == "spacetime"
    assert any(op["type"] == "side" for op in result["spacetime"]["ops"])
    assert result["patches"]["type"] == "logical_patch"
    assert [op["round"] for op in result["patches"]["ops"]] == [1, 2, 3]
    assert all(op["qubits"] and op["patches"] for op in result["patches"]["ops"])
    assert result["rounds"] == 3
    assert "log_asm.meas_stab<3>" in result["mlir"]


def test_changed_geometry_and_basis_reach_the_compiler(client, project):
    project["patches"][0].update(width=5, x=7, vertical_z=False)
    project["operations"][0]["basis"] = "X"
    result = client.post("/api/compile", json=project).json()
    surface = result["spacetime"]["ops"][0]
    assert surface["size"] == [5, 3]
    assert surface["location"] == [7, 0]
    assert result["spacetime"]["ops"][1]["colour"] == "RED"


def test_python_export_recreates_the_same_logical_ir(client, project):
    result = client.post("/api/compile", json=project).json()
    namespace = {"__name__": "export_test"}
    exec(result["python"], namespace)
    module = LogicalAssemblyVisualiser(namespace["program"]).module
    module.verify()
    assert str(module) == result["mlir"]


def test_mlir_export_parses_and_verifies(client, project):
    result = client.post("/api/compile", json=project).json()
    module = Parser(LogicalAssemblyVisualiser.make_context(), result["mlir"]).parse_module()
    module.verify()


def test_python_export_runs_as_a_script_without_starting_a_server(project, tmp_path):
    result = compile_project(Project.model_validate(project))
    script = tmp_path / "export.py"
    script.write_text(result["python"], encoding="utf-8")
    run = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, timeout=5, check=False
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip() == result["mlir"]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda p: p["operations"][1].update(patch="missing"), "Unknown patch"),
        (lambda p: p["operations"].pop(0), "Prepare"),
        (
            lambda p: p["operations"].append({"kind": "memory", "patch": "p0", "rounds": 1}),
            "measured",
        ),
        (
            lambda p: p["operations"].insert(1, {"kind": "prepare", "patch": "p0", "basis": "X"}),
            "already prepared",
        ),
        (lambda p: p["patches"].append({**p["patches"][0], "id": "p1"}), "overlap"),
        (lambda p: p["patches"].append({**p["patches"][0], "x": 10}), "unique"),
        (lambda p: p.update(operations=[p["operations"][0]]), "stabiliser"),
    ],
)
def test_invalid_assemblies_return_actionable_errors(client, project, mutation, message):
    mutation(project)
    response = client.post("/api/compile", json=project)
    assert response.status_code == 422
    assert message.lower() in response.text.lower()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p["patches"][0].update(width=4),
        lambda p: p["patches"][0].update(width=101),
        lambda p: p["patches"][0].update(x=-1),
        lambda p: p["patches"][0].update(x=31),
        lambda p: p["operations"][1].update(rounds=0),
        lambda p: p["operations"][1].update(rounds=65),
        lambda p: p["operations"][0].update(basis="Y"),
        lambda p: p["operations"][1].update(kind="python", code="print('bad')"),
        lambda p: p.update(version=3),
        lambda p: p.update(patches=[]),
        lambda p: p.update(operations=p["operations"] * 30),
        lambda p: p["operations"][1].update(rounds=3.5),
        lambda p: p.update(unexpected=True),
    ],
)
def test_schema_rejects_unsupported_or_unbounded_inputs(client, project, mutation):
    mutation(project)
    assert client.post("/api/compile", json=project).status_code == 422


def test_total_round_budget_is_checked(client, project):
    project["operations"] = [
        project["operations"][0],
        {"kind": "memory", "patch": "p0", "rounds": 40},
        {"kind": "memory", "patch": "p0", "rounds": 40},
    ]
    response = client.post("/api/compile", json=project)
    assert response.status_code == 422
    assert "64" in response.text


def test_projects_are_isolated_and_recompilation_is_deterministic(client, project):
    original = copy.deepcopy(project)
    first = client.post("/api/compile", json=project).json()
    other = copy.deepcopy(project)
    other["patches"][0]["x"] = 10
    second = client.post("/api/compile", json=other).json()
    third = client.post("/api/compile", json=project).json()
    assert first == third
    assert first["spacetime"] != second["spacetime"]
    assert project == original


def test_two_disjoint_patches_compile_in_timeline_order(client, project):
    project["patches"].append({**project["patches"][0], "id": "p1", "x": 4})
    project["operations"].extend(
        [
            {"kind": "prepare", "patch": "p1", "basis": "X"},
            {"kind": "memory", "patch": "p1", "rounds": 2},
            {"kind": "measure", "patch": "p1", "basis": "X"},
        ]
    )
    response = client.post("/api/compile", json=project)
    assert response.status_code == 200, response.text
    assert response.json()["rounds"] == 5
    assert [op["round"] for op in response.json()["patches"]["ops"]] == [1, 2, 3, 4, 5]


def test_interleaved_memory_rounds_preserve_patch_identity_and_position(client, project):
    project["patches"].append({**project["patches"][0], "id": "p1", "x": 6})
    project["operations"] = [
        {"kind": "prepare", "patch": "p0", "basis": "Z"},
        {"kind": "prepare", "patch": "p1", "basis": "X"},
        {"kind": "memory", "patch": "p0", "rounds": 2},
        {"kind": "memory", "patch": "p1", "rounds": 1},
        {"kind": "memory", "patch": "p0", "rounds": 1},
    ]
    response = client.post("/api/compile", json=project)
    assert response.status_code == 200, response.text
    items = response.json()["patches"]["ops"]
    assert [item["round"] for item in items] == [1, 2, 3, 4]
    assert [min(q["coordinates"][0] for q in item["qubits"]) for item in items] == [0, 0, 6, 0]


def test_editor_and_renderer_pages_are_served(client):
    assert "Assembly Studio" in client.get("/").text
    assert "Deltakit" in client.get("/viewer").text
    assert client.get("/static/app.js").status_code == 200
