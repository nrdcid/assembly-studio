import test from "node:test";
import assert from "node:assert/strict";
import {
  createHistory,
  memoryExample,
  normaliseProject,
  deletePatch,
} from "../static/state.mjs";

test("undo and redo preserve independent project snapshots", () => {
  const history = createHistory(memoryExample());
  history.edit((project) => {
    project.patches[0].x = 4;
  });
  assert.equal(history.current.patches[0].x, 4);
  history.undo();
  assert.equal(history.current.patches[0].x, 2);
  history.redo();
  assert.equal(history.current.patches[0].x, 4);
  history.undo();
  history.edit((project) => {
    project.name = "A new branch";
  });
  assert.equal(history.canRedo, false);
});

test("deleting a patch also removes its operations", () => {
  const project = memoryExample();
  deletePatch(project, project.patches[0].id);
  assert.deepEqual(project.patches, []);
  assert.deepEqual(project.operations, []);
});

test("saved projects round trip without losing operations or geometry", () => {
  const project = memoryExample();
  assert.deepEqual(
    normaliseProject(JSON.parse(JSON.stringify(project))),
    project,
  );
});

test("malformed and unsupported project files are rejected before changing the editor", () => {
  for (const project of [
    null,
    {},
    { version: 2, patches: [], operations: [] },
    { ...memoryExample(), patches: [{ id: "<script>" }] },
    { ...memoryExample(), operations: [{ kind: "eval", patch: "p0" }] },
    {
      ...memoryExample(),
      operations: [{ kind: "memory", patch: "p0", rounds: 10000 }],
    },
  ]) {
    assert.throws(() => normaliseProject(project));
  }
});

const error = {id: "e1", patch: "p0", qubit: "p0:d:2.5,2.5", pauli: "Y", before_patch_round: 2};

test("v1 imports migrate to v2 with an empty experiment without modifying input", () => {
  const legacy = memoryExample();
  legacy.version = 1;
  delete legacy.experiment;
  const before = structuredClone(legacy);
  const migrated = normaliseProject(legacy);
  assert.equal(migrated.version, 2);
  assert.deepEqual(migrated.experiment, {errors: []});
  assert.deepEqual(legacy, before);
});

test("v2 experiments survive JSON persistence, undo, redo, removal and clearing", () => {
  const project = {...memoryExample(), version: 2, experiment: {errors: [error]}};
  const saved = normaliseProject(JSON.parse(JSON.stringify(project)));
  assert.deepEqual(saved, project);
  saved.experiment.errors[0].pauli = "Z";
  assert.equal(project.experiment.errors[0].pauli, "Y");
  const history = createHistory(project);
  history.edit((p) => p.experiment.errors.push({...error, id: "e2"}));
  history.edit((p) => { p.experiment.errors = p.experiment.errors.filter((e) => e.id !== "e1"); });
  assert.deepEqual(history.current.experiment.errors.map((e) => e.id), ["e2"]);
  history.edit((p) => { p.experiment.errors = []; });
  assert.deepEqual(history.current.experiment.errors, []);
  history.undo();
  assert.equal(history.current.experiment.errors.length, 1);
  history.undo();
  assert.equal(history.current.experiment.errors.length, 2);
  history.redo();
  assert.equal(history.current.experiment.errors.length, 1);
});

test("v2 experiment is optional but malformed experiments cannot be silently lost", () => {
  const project = {...memoryExample(), version: 2};
  delete project.experiment;
  assert.deepEqual(normaliseProject(project).experiment, {errors: []});
  for (const experiment of [null, [], {}, {errors: null}, {errors: [{}]},
    {errors: [{...error, pauli: "I"}]}, {errors: [{...error, before_patch_round: 0}]},
    {errors: [error, error]}]) {
    assert.throws(() => normaliseProject({...project, experiment}));
  }
  assert.throws(() => normaliseProject({...project, version: 1, experiment: {errors: [error]}}));
});
