import { normaliseErrors } from "./syndrome.mjs";

export function memoryExample() {
  return {
    version: 2,
    experiment: { errors: [] },
    name: "Quantum memory",
    patches: [
      {
        id: "p0",
        name: "Memory patch",
        width: 3,
        height: 3,
        x: 2,
        y: 2,
        vertical_z: true,
      },
    ],
    operations: [
      { kind: "prepare", patch: "p0", basis: "Z" },
      { kind: "memory", patch: "p0", rounds: 3 },
      { kind: "measure", patch: "p0", basis: "Z" },
    ],
  };
}

export function normaliseProject(value) {
  const fail = () => {
    throw new Error(
      "This is not a supported Assembly Studio project (version 1 or 2).",
    );
  };
  const integer = (n, min, max) => Number.isInteger(n) && n >= min && n <= max;
  if (
    !value ||
    ![1, 2].includes(value.version) ||
    typeof value.name !== "string" ||
    !value.name.trim() ||
    value.name.length > 80 ||
    !Array.isArray(value.patches) ||
    value.patches.length > 8 ||
    !Array.isArray(value.operations) ||
    value.operations.length > 64
  )
    fail();
  const ids = new Set();
  for (const patch of value.patches) {
    if (
      !patch ||
      typeof patch.id !== "string" ||
      !/^[A-Za-z][A-Za-z0-9_]{0,31}$/.test(patch.id) ||
      ids.has(patch.id) ||
      typeof patch.name !== "string" ||
      !patch.name.trim() ||
      patch.name.length > 48 ||
      !integer(patch.width, 3, 11) ||
      patch.width % 2 !== 1 ||
      !integer(patch.height, 3, 11) ||
      patch.height % 2 !== 1 ||
      !integer(patch.x, 0, 29) ||
      !integer(patch.y, 0, 29) ||
      patch.x + patch.width > 32 ||
      patch.y + patch.height > 32 ||
      typeof patch.vertical_z !== "boolean"
    )
      fail();
    ids.add(patch.id);
  }
  for (const op of value.operations) {
    if (
      !op ||
      !ids.has(op.patch) ||
      !["prepare", "memory", "measure"].includes(op.kind)
    )
      fail();
    if (
      op.kind === "memory"
        ? !integer(op.rounds, 1, 64)
        : !["X", "Z"].includes(op.basis)
    )
      fail();
  }
  if (value.version === 1 && Object.hasOwn(value, "experiment")) fail();
  const experiment = Object.hasOwn(value, "experiment")
    ? value.experiment : { errors: [] };
  if (!experiment || typeof experiment !== "object" || Array.isArray(experiment)) fail();
  const errors = normaliseErrors(experiment.errors);
  // Pick only project fields; never persist UI state or generated output.
  return {
    version: 2,
    experiment: { errors },
    name: value.name,
    patches: value.patches.map((p) => ({
      id: p.id,
      name: p.name,
      width: p.width,
      height: p.height,
      x: p.x,
      y: p.y,
      vertical_z: p.vertical_z,
    })),
    operations: value.operations.map((op) =>
      op.kind === "memory"
        ? { kind: op.kind, patch: op.patch, rounds: op.rounds }
        : { kind: op.kind, patch: op.patch, basis: op.basis },
    ),
  };
}

export function deletePatch(project, id) {
  project.patches = project.patches.filter((patch) => patch.id !== id);
  project.operations = project.operations.filter((op) => op.patch !== id);
}

export function createHistory(project) {
  let snapshots = [structuredClone(project)];
  let index = 0;
  return {
    get current() {
      return structuredClone(snapshots[index]);
    },
    get canUndo() {
      return index > 0;
    },
    get canRedo() {
      return index < snapshots.length - 1;
    },
    edit(change) {
      const next = structuredClone(snapshots[index]);
      change(next);
      if (JSON.stringify(next) === JSON.stringify(snapshots[index])) return;
      snapshots = snapshots.slice(0, index + 1);
      snapshots.push(next);
      if (snapshots.length > 100) snapshots.shift();
      index = snapshots.length - 1;
    },
    undo() {
      if (index > 0) index--;
    },
    redo() {
      if (index < snapshots.length - 1) index++;
    },
  };
}
