import test from "node:test";
import assert from "node:assert/strict";
import { pauliToBits, composePaulis, calculateSyndrome } from "../static/syndrome.mjs";

const snapshot = (patch, patchRound, round) => ({
  patch_id: patch, patch_round: patchRound, round,
  data_qubits: [0, 1, 2].map((n) => ({ id: `${patch}:d:${n}`, position: [n, 0] })),
  checks: [
    { id: `${patch}:X:a`, basis: "X", weight: 2, data_qubits: [`${patch}:d:0`, `${patch}:d:1`] },
    { id: `${patch}:Z:a`, basis: "Z", weight: 2, data_qubits: [`${patch}:d:0`, `${patch}:d:1`] },
    { id: `${patch}:Z:b`, basis: "Z", weight: 1, data_qubits: [`${patch}:d:2`] },
  ],
});
const topology = [snapshot("p0", 1, 1), snapshot("p1", 1, 2),
  snapshot("p0", 2, 3), snapshot("p1", 2, 4), snapshot("p0", 3, 5)];
const injection = (pauli, qubit = "p0:d:0", round = 1, id = "e1", patch = "p0") =>
  ({ id, patch, qubit, pauli, before_patch_round: round });
const calculate = (errors = [], round = 1, patch = "p0") =>
  calculateSyndrome(topology, errors, patch, round);

test("binary representation and all Pauli compositions ignore global phase", () => {
  const paulis = ["I", "X", "Z", "Y"];
  const table = ["IXZY", "XIYZ", "ZYIX", "YZXI"];
  assert.deepEqual(paulis.map(pauliToBits), [{x:0,z:0}, {x:1,z:0}, {x:0,z:1}, {x:1,z:1}]);
  paulis.forEach((a, i) => paulis.forEach((b, j) => {
    assert.equal(composePaulis(a, b), table[i][j]);
  }));
  for (const invalid of ["A", "x", null, "toString"]) {
    assert.throws(() => pauliToBits(invalid));
    assert.throws(() => composePaulis("X", invalid));
  }
});

test("no errors yields an identity frame and all-zero syndrome", () => {
  const result = calculate();
  assert.deepEqual(result.frame, {"p0:d:0": {x:0,z:0}, "p0:d:1": {x:0,z:0}, "p0:d:2": {x:0,z:0}});
  assert.deepEqual(result.syndrome, {"p0:X:a": 0, "p0:Z:a": 0, "p0:Z:b": 0});
  assert.deepEqual(result.affectedChecks, []);
});

for (const [pauli, affected] of [["X", ["p0:Z:a"]], ["Z", ["p0:X:a"]], ["Y", ["p0:X:a", "p0:Z:a"]]]) {
  test(`${pauli} flips exactly the anticommuting overlapping checks`, () => {
    assert.deepEqual(calculate([injection(pauli)]).affectedChecks, affected);
  });
}

test("repeated errors cancel, X plus Z makes Y, and two-qubit syndromes XOR", () => {
  const first = injection("X");
  assert.deepEqual(calculate([first, {...first, id: "e2"}]).frame, calculate().frame);
  assert.deepEqual(calculate([first, injection("Z", "p0:d:0", 1, "e2")]).frame["p0:d:0"], {x:1,z:1});
  for (const qubit of ["p0:d:1", "p0:d:2"]) {
    const second = injection("X", qubit, 1, "e2");
    const combined = calculate([first, second]);
    for (const id of Object.keys(combined.syndrome)) {
      assert.equal(combined.syndrome[id], calculate([first]).syndrome[id] ^ calculate([second]).syndrome[id]);
    }
  }
});

test("errors persist from their patch-local round; interleaving and query order have no effect", () => {
  const errors = [injection("X", "p0:d:0", 2), injection("X", "p0:d:0", 3, "e2")];
  assert.deepEqual(calculate(errors, 3).affectedChecks, []);
  assert.deepEqual(calculate(errors, 1).affectedChecks, []);
  assert.deepEqual(calculate(errors, 2).affectedChecks, ["p0:Z:a"]);
  assert.equal(calculate(errors, 2).round, 3);
  assert.deepEqual(calculate(errors, 2, "p1").affectedChecks, []);
  assert.deepEqual(calculate([injection("X", "p0:d:0", 3)], 2).affectedChecks, []);
  assert.deepEqual(calculate([injection("X", "p0:d:0", 3)], 3).affectedChecks, ["p0:Z:a"]);
  assert.deepEqual(calculate([injection("X")], 3).affectedChecks, ["p0:Z:a"]);
  assert.deepEqual(calculate([...errors].reverse(), 2), calculate(errors, 2));
});

test("invalid references, Pauli types, rounds, and duplicate injection IDs are rejected", () => {
  for (const mutation of [
    {patch: "missing"}, {qubit: "p1:d:0"}, {qubit: "ancilla"}, {pauli: "I"},
    {pauli: "A"}, {before_patch_round: 0}, {before_patch_round: 4},
    {before_patch_round: 1.5}, {before_patch_round: "2"}, {id: ""},
  ]) assert.throws(() => calculate([{...injection("X"), ...mutation}]));
  assert.throws(() => calculate([injection("X"), injection("Z")]));
  assert.throws(() => calculate([injection("X", "missing", 3)])); // Validate future errors too.
  for (const round of [0, 4, 1.5, "1"]) assert.throws(() => calculate([], round));
  assert.throws(() => calculate([], 1, "missing"));
});

test("calculation never mutates topology, errors, or previously returned frames", () => {
  const errors = [injection("Y")];
  const before = JSON.stringify({topology, errors});
  const first = calculate(errors);
  first.frame["p0:d:0"].x = 0;
  calculate(errors, 3);
  assert.equal(JSON.stringify({topology, errors}), before);
  assert.deepEqual(calculate(errors).frame["p0:d:0"], {x:1,z:1});
});
