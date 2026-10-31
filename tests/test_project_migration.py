# (c) Copyright Riverlane 2025-2026. All rights reserved.
"""Version migration and analysis-only experiment persistence."""

import copy
import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from app import Project, compile_project


def scenario(project):
    return {
        **project,
        "version": 2,
        "experiment": {
            "errors": [
                {
                    "id": "e1",
                    "patch": "p0",
                    "qubit": "p0:d:0.5,0.5",
                    "pauli": "Y",
                    "before_patch_round": 2,
                }
            ]
        },
    }


def test_v1_migrates_without_mutating_source(project):
    original = copy.deepcopy(project)
    parsed = Project.model_validate(project)
    assert parsed.version == 2
    assert parsed.model_dump()["experiment"] == {"errors": []}
    assert project == original


def test_v2_round_trip_and_exports_ignore_experiment(project, client):
    value = scenario(project)
    parsed = Project.model_validate(value)
    assert parsed.model_dump() == value
    assert Project.model_validate_json(parsed.model_dump_json()) == parsed
    expected = compile_project(Project.model_validate(project))
    response = client.post("/api/compile", json=value)
    assert response.status_code == 200, response.text
    assert response.json() == expected
    assert Project.model_validate({**project, "version": 2}).experiment.errors == []


@pytest.mark.parametrize(
    "mutation",
    [
        {"pauli": "I"},
        {"pauli": "A"},
        {"before_patch_round": 0},
        {"before_patch_round": 1.5},
        {"before_patch_round": "2"},
        {"id": ""},
    ],
)
def test_invalid_error_schema_is_rejected(project, mutation):
    value = scenario(project)
    value["experiment"]["errors"][0].update(mutation)
    with pytest.raises(ValidationError):
        Project.model_validate(value)


@pytest.mark.parametrize(
    "mutation",
    [
        {"patch": "missing"},
        {"qubit": "p0:d:missing"},
        {"qubit": "p0:a:0,0"},
        {"before_patch_round": 4},
    ],
)
def test_compile_rejects_invalid_scenario_references(project, client, mutation):
    value = scenario(project)
    value["experiment"]["errors"][0].update(mutation)
    response = client.post("/api/compile", json=value)
    assert response.status_code == 422


def test_duplicate_error_ids_and_v1_experiment_rejected(project):
    value = scenario(project)
    value["experiment"]["errors"] *= 2
    with pytest.raises(ValidationError, match="unique"):
        Project.model_validate(value)
    value = scenario(project)
    value["version"] = 1
    with pytest.raises(ValidationError):
        Project.model_validate(value)


@pytest.mark.parametrize("distance", [3, 5])
@pytest.mark.parametrize("vertical_z", [True, False])
def test_javascript_syndromes_agree_with_compiler_support(project, distance, vertical_z):
    project["patches"][0].update(width=distance, height=distance, vertical_z=vertical_z)
    topology = compile_project(Project.model_validate(project))["topology"]
    script = """
        import assert from 'node:assert/strict';
        import { readFileSync } from 'node:fs';
        import { calculateSyndrome } from './static/syndrome.mjs';
        const topology = JSON.parse(readFileSync(0, 'utf8'));
        const snapshot = topology[0];
        for (const qubit of snapshot.data_qubits) {
          for (const pauli of ['X', 'Y', 'Z']) {
            const errors = [{id: 'e1', patch: snapshot.patch_id, qubit: qubit.id,
                             pauli, before_patch_round: 2}];
            const expected = snapshot.checks.filter(c =>
              c.data_qubits.includes(qubit.id) && c.basis !== pauli).map(c => c.id).sort();
            assert.deepEqual(calculateSyndrome(topology, errors, snapshot.patch_id, 1)
              .affectedChecks, []);
            for (const round of [2, 3]) {
              assert.deepEqual(calculateSyndrome(topology, errors, snapshot.patch_id, round)
                .affectedChecks, expected);
            }
          }
        }
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        input=json.dumps(topology),
        text=True,
        capture_output=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("mutation", [{"patch": "deleted"}, {"before_patch_round": 4}])
def test_project_validation_rejects_scenario_lifetime_references(project, mutation):
    value = scenario(project)
    value["experiment"]["errors"][0].update(mutation)
    with pytest.raises(ValidationError, match="e1"):
        Project.model_validate(value)


def test_shrinking_patch_rejects_removed_data_qubit_without_reassignment(project, client):
    value = scenario(project)
    value["patches"][0].update(width=5, height=5)
    value["experiment"]["errors"][0]["qubit"] = "p0:d:4.5,4.5"
    assert client.post("/api/compile", json=value).status_code == 200
    value["patches"][0].update(width=3, height=3)
    response = client.post("/api/compile", json=value)
    assert response.status_code == 422
    assert "e1" in response.text
    assert "4.5,4.5" in response.text
