// The interactive SVG stays in the parent document, outside the Deltakit iframe.
const NS = "http://www.w3.org/2000/svg";
const svgElement = (tag, attributes = {}, text) => {
  const element = document.createElementNS(NS, tag);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
  if (text !== undefined) element.textContent = text;
  return element;
};

export function createSyndromeView(root, { onInject, onRemove, onClear }) {
  const $ = (id) => root.querySelector(`#${id}`);
  let selection = null;
  let current = null;
  const choose = (kind, id) => {
    if (!current?.fresh || !current.result) return;
    selection = { kind, id };
    render(current);
  };
  $("syndrome-svg").addEventListener("click", (event) => {
    const target = event.target.closest("[data-qubit], [data-check], [data-ancilla]");
    if (!target) return;
    for (const kind of ["qubit", "check", "ancilla"])
      if (target.dataset[kind]) choose(kind, target.dataset[kind]);
  });
  $("syndrome-svg").addEventListener("keydown", (event) => {
    if (!["Enter", " "].includes(event.key)) return;
    const target = event.target.closest("[role=button]");
    if (!target) return;
    event.preventDefault();
    target.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    // Rendering replaces SVG elements. Restore focus to the same identity.
    const kind = ["qubit", "check", "ancilla"].find((key) => target.dataset[key]);
    [...$("syndrome-svg").querySelectorAll(`[data-${kind}]`)]
      .find((element) => element.dataset[kind] === target.dataset[kind])?.focus();
  });
  $("inject-error").addEventListener("click", () => {
    if (!current?.fresh || !current.result || selection?.kind !== "qubit") return;
    onInject(selection.id, $("inject-pauli").value, current.snapshot);
  });
  $("clear-errors").addEventListener("click", onClear);

  function render(state) {
    current = state;
    const { snapshot, drawing, result, errors, fresh, message = "" } = state;
    const svg = $("syndrome-svg");
    svg.replaceChildren();
    svg.setAttribute("aria-disabled", String(!fresh || !result));
    $("syndrome-message").textContent = !fresh
      ? "Compile the assembly to inspect qubits and inject errors."
      : message;
    $("syndrome-round").textContent = snapshot
      ? `${snapshot.patch_id} · Patch round ${snapshot.patch_round} · Global round ${snapshot.round}` : "";
    $("inject-error").disabled = true;
    $("inject-pauli").disabled = !fresh || !result;
    $("clear-errors").disabled = !errors.length;
    $("syndrome-errors").replaceChildren();
    for (const error of errors) {
      const row = document.createElement("li");
      const description = document.createElement("span");
      description.textContent = `${error.pauli} · ${error.qubit} · before patch round ${error.before_patch_round}`;
      const remove = document.createElement("button");
      remove.className = "button ghost";
      remove.dataset.removeError = error.id;
      remove.textContent = "Remove";
      remove.setAttribute("aria-label", `Remove injection ${error.id}`);
      remove.addEventListener("click", () => onRemove(error.id));
      row.append(description, remove);
      $("syndrome-errors").append(row);
    }
    const inspector = $("syndrome-inspector");
    inspector.replaceChildren();
    if (!snapshot || !drawing) {
      inspector.textContent = "Compile a patch to explore its stabilizers.";
      return;
    }
    const positions = new Map(snapshot.data_qubits.map((q) => [q.id, q.position]));
    const ancillas = drawing.qubits.filter((q) => q.type === "ancilla").map((q) => ({
      id: `${snapshot.patch_id}:a:${q.coordinates.join(",")}`, position: q.coordinates,
    }));
    const selectedCheck = selection?.kind === "check"
      ? snapshot.checks.find((c) => c.id === selection.id) : null;
    const selectedQubit = selection?.kind === "qubit"
      ? snapshot.data_qubits.find((q) => q.id === selection.id) : null;
    const selectedAncilla = selection?.kind === "ancilla"
      ? ancillas.find((q) => q.id === selection.id) : null;
    if (!selectedCheck && !selectedQubit && !selectedAncilla) selection = null;
    const coordinates = [...positions.values(), ...ancillas.map((q) => q.position)];
    const xs = coordinates.map(([x]) => x), ys = coordinates.map(([, y]) => y);
    const x = Math.min(...xs) - 0.55, y = Math.min(...ys) - 0.55;
    svg.setAttribute("viewBox", `${x} ${y} ${Math.max(...xs) - x + 0.55} ${Math.max(...ys) - y + 0.55}`);
    const interactive = (kind, id, label) => {
      const group = svgElement("g", {
        [`data-${kind}`]: id, role: "button", tabindex: fresh && result ? 0 : -1,
        "aria-label": label, "aria-pressed": String(selection?.id === id),
        "aria-disabled": String(!fresh || !result),
      });
      group.append(svgElement("title", {}, label));
      return group;
    };
    const rawQubits = new Map(drawing.qubits.map((q) => [q.id, q]));
    for (const check of snapshot.checks) {
      // Match the compiler drawing by data support, never by plaquette index.
      // Boundary polygons include the drawing ancilla; Pauli support does not.
      const supportKey = check.data_qubits.map((id) => positions.get(id).join(",")).sort().join(";");
      const plaquette = drawing.patches.flatMap((patch) => patch.plaquettes).find((p) =>
        p.coordinates.filter((id) => rawQubits.get(id).type === "data")
          .map((id) => rawQubits.get(id).coordinates.join(",")).sort().join(";") === supportKey);
      const points = plaquette.coordinates.map((id) => rawQubits.get(id).coordinates);
      const cx = points.reduce((sum, p) => sum + p[0], 0) / points.length;
      const cy = points.reduce((sum, p) => sum + p[1], 0) / points.length;
      points.sort((a, b) => Math.atan2(a[1] - cy, a[0] - cx) - Math.atan2(b[1] - cy, b[0] - cx));
      const bit = result?.syndrome[check.id] ?? 0;
      const group = interactive("check", check.id, `${check.basis} check, weight ${check.weight}, syndrome ${bit}`);
      group.dataset.syndrome = bit;
      group.classList.add("syndrome-check", `basis-${check.basis}`);
      group.append(svgElement("polygon", { points: points.map((p) => p.join(",")).join(" ") }));
      group.append(svgElement("text", { x: cx, y: cy - 0.15, "text-anchor": "middle" }, `${check.basis}${bit ? " !" : ""}`));
      svg.append(group);
    }
    for (const ancilla of ancillas) {
      const [cx, cy] = ancilla.position;
      const group = interactive("ancilla", ancilla.id, `Ancilla ${ancilla.position.join(", ")}`);
      group.classList.add("syndrome-ancilla");
      group.append(svgElement("path", { d: `M ${cx} ${cy - 0.09} l .09 .09 l -.09 .09 l -.09 -.09 Z` }));
      svg.append(group);
    }
    for (const qubit of snapshot.data_qubits) {
      const [cx, cy] = qubit.position;
      const group = interactive("qubit", qubit.id, `Data qubit ${qubit.position.join(", ")}`);
      group.classList.add("syndrome-qubit");
      group.classList.toggle("in-support", Boolean(selectedCheck?.data_qubits.includes(qubit.id)));
      group.append(svgElement("circle", { cx, cy, r: 0.20, class: "qubit-hit" }));
      group.append(svgElement("circle", { cx, cy, r: 0.09, class: "qubit-dot" }));
      const bits = result?.frame[qubit.id];
      if (bits && (bits.x || bits.z)) {
        const pauli = bits.x ? (bits.z ? "Y" : "X") : "Z";
        group.append(svgElement("text", { x: cx + 0.15, y: cy - 0.12, class: "error-marker" }, pauli));
      }
      svg.append(group);
    }
    if (selectedCheck) {
      const heading = document.createElement("strong");
      heading.textContent = `${selectedCheck.basis} stabilizer · ${snapshot.patch_id}`;
      const details = document.createElement("p");
      details.textContent = `Weight ${selectedCheck.weight} · Syndrome bit ${result?.syndrome[selectedCheck.id] ?? "unavailable"}`;
      const support = document.createElement("p");
      support.textContent = `Data support: ${selectedCheck.data_qubits.join("; ")}`;
      inspector.append(heading, details, support);
    } else if (selectedQubit || selectedAncilla) {
      const qubit = selectedQubit || selectedAncilla;
      const heading = document.createElement("strong");
      heading.textContent = `${selectedQubit ? "Data qubit" : "Ancilla"} · ${snapshot.patch_id} · (${qubit.position.join(", ")})`;
      inspector.append(heading);
      if (selectedQubit) {
        const label = document.createElement("p");
        label.textContent = "Associated checks:";
        inspector.append(label);
        for (const check of snapshot.checks.filter((c) => c.data_qubits.includes(qubit.id))) {
          const button = document.createElement("button");
          button.className = "button ghost";
          button.textContent = `${check.basis} · weight ${check.weight}`;
          button.disabled = !fresh || !result;
          button.addEventListener("click", () => choose("check", check.id));
          inspector.append(button);
        }
        $("inject-error").disabled = !fresh || !result || errors.length >= 1024;
      } else {
        const note = document.createElement("p");
        note.textContent = "Ancillas can be inspected; injections apply to data qubits only.";
        inspector.append(note);
      }
    } else inspector.textContent = "Select a data qubit or stabilizer to inspect it.";
  }
  return { render };
}
