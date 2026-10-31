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
