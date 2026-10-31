// Deterministic error-induced syndromes, independent of DOM and rendering.
// These are Pauli-frame calculations, not sampled measurement outcomes.

export function pauliToBits(pauli) {
  switch (pauli) {
    case "I": return { x: 0, z: 0 };
    case "X": return { x: 1, z: 0 };
    case "Z": return { x: 0, z: 1 };
    case "Y": return { x: 1, z: 1 };
    default: throw new Error(`Unsupported Pauli: ${String(pauli)}.`);
  }
}

export function composePaulis(first, second) {
  const a = pauliToBits(first);
  const b = pauliToBits(second);
  return ["I", "X", "Z", "Y"][(a.x ^ b.x) + 2 * (a.z ^ b.z)];
}

// Structural validation also serves project loading, before topology is available.
// Return fresh records so imported experiments cannot alias history snapshots.
export function normaliseErrors(errors) {
  if (!Array.isArray(errors) || errors.length > 1024)
    throw new Error("Experiment errors must be an array of at most 1024 injections.");
  const ids = new Set();
  return errors.map((error) => {
    if (!error || typeof error !== "object" ||
        Object.keys(error).some((key) => !["id", "patch", "qubit", "pauli", "before_patch_round"].includes(key)) ||
        typeof error.id !== "string" || !error.id.length || error.id.length > 128 ||
        ids.has(error.id) || typeof error.patch !== "string" ||
        !/^[A-Za-z][A-Za-z0-9_]{0,31}$/.test(error.patch) ||
        typeof error.qubit !== "string" || !error.qubit.length || error.qubit.length > 128 ||
        !["X", "Y", "Z"].includes(error.pauli) ||
        !Number.isInteger(error.before_patch_round) ||
        error.before_patch_round < 1 || error.before_patch_round > 64)
      throw new Error("Invalid error injection: use unique IDs, X/Y/Z, and an integer patch round from 1 to 64.");
    ids.add(error.id);
    return { id: error.id, patch: error.patch, qubit: error.qubit,
      pauli: error.pauli, before_patch_round: error.before_patch_round };
  });
}

export function validateErrors(topology, errors) {
  const validated = normaliseErrors(errors);
  const issues = findErrorIssues(topology, validated);
  if (issues.length) throw new Error(issues.map((issue) => `Error ${issue.id}: ${issue.message}`).join(" "));
  return validated;
}

export function findErrorIssues(topology, errors) {
  return normaliseErrors(errors).flatMap((error) => {
    if (!topology.some((item) => item.patch_id === error.patch))
      return [{ id: error.id, message: `Unknown patch ${error.patch} or no measurement rounds.` }];
    const target = topology.find((item) => item.patch_id === error.patch &&
      item.patch_round === error.before_patch_round);
    if (!target)
      return [{ id: error.id, message: `Invalid patch round ${error.before_patch_round}.` }];
    if (!target.data_qubits.some((q) => q.id === error.qubit))
      return [{ id: error.id, message: `Unknown data qubit ${error.qubit}.` }];
    return [];
  });
}

// Query any patch measurement directly. Recomputing from injections makes scrubbing
// independent of query order; an error persists until another Pauli changes it.
export function calculateSyndrome(topology, errors, patchId, patchRound) {
  const validated = validateErrors(topology, errors);
  const selected = topology.find((item) => item.patch_id === patchId &&
    item.patch_round === patchRound);
  if (!Number.isInteger(patchRound) || !selected)
    throw new Error("Select an existing patch measurement round.");
  return calculateRound(selected, validated);
}

function calculateRound(selected, validated) {
  const { patch_id: patchId, patch_round: patchRound } = selected;
  const frame = Object.fromEntries(selected.data_qubits.map((q) => [q.id, pauliToBits("I")]));
  for (const error of validated) {
    if (error.patch !== patchId || error.before_patch_round > patchRound) continue;
    if (!Object.hasOwn(frame, error.qubit))
      throw new Error(`Error ${error.id}: data qubit is absent at the selected round.`);
    const bits = pauliToBits(error.pauli);
    frame[error.qubit].x ^= bits.x;
    frame[error.qubit].z ^= bits.z;
  }
  const syndrome = Object.fromEntries(selected.checks.map((check) => {
    if (!["X", "Z"].includes(check.basis))
      throw new Error(`Unsupported check basis: ${check.basis}.`);
    const stabilizer = pauliToBits(check.basis);
    let bit = 0;
    for (const qubit of check.data_qubits) {
      if (!Object.hasOwn(frame, qubit))
        throw new Error(`Check ${check.id}: unknown data qubit ${qubit}.`);
      bit ^= (stabilizer.x & frame[qubit].z) ^ (stabilizer.z & frame[qubit].x);
    }
    return [check.id, bit];
  }));
  return { patch_id: patchId, patch_round: patchRound, round: selected.round,
    frame, syndrome, affectedChecks: Object.keys(syndrome).filter((id) => syndrome[id] === 1).sort() };
}

// Ideal zero-error preparation reference: s(i,0) = 0. Compare measurements of
// this patch only. These changes are not a noisy-circuit detector model.
export function calculateHistory(topology, errors, patchId) {
  const validated = validateErrors(topology, errors);
  const rounds = topology.filter((item) => item.patch_id === patchId)
    .sort((a, b) => a.patch_round - b.patch_round);
  if (!rounds.length) throw new Error("Select a patch with measurement rounds.");
  let previous = {};
  return rounds.map((snapshot) => {
    const result = calculateRound(snapshot, validated);
    const detection = Object.fromEntries(Object.entries(result.syndrome)
      .map(([id, bit]) => [id, bit ^ (previous[id] ?? 0)]));
    const events = Object.keys(detection).filter((id) => detection[id]).sort()
      .map((id) => ({ check_id: id, patch_id: patchId,
        patch_round: snapshot.patch_round, round: snapshot.round }));
    previous = result.syndrome;
    return { ...result, detection, events };
  });
}
