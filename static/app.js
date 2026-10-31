import {
  createHistory,
  memoryExample,
  normaliseProject,
  deletePatch,
  projectErrorIssues,
  nextPatchId,
} from "./state.mjs";
import { calculateHistory, findErrorIssues } from "./syndrome.mjs";
import { createSyndromeView } from "./syndrome-view.mjs";

const $ = (id) => document.getElementById(id);
const escape = (value) =>
  String(value).replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        char
      ],
  );
const STORAGE_KEY = "assembly-studio.project.v1";
let initial = memoryExample();
try {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) initial = normaliseProject(JSON.parse(saved));
} catch {
  /* Keep the working example if storage is unavailable or invalid. */
}
let history = createHistory(initial);
let selected = initial.patches[0]?.id;
let compiled = null;
let compiledSource = "";
let compilePromise = null;
let activeView = "spacetime";
let round = 1;
let playing = null;
let viewerReady = false;
let viewerRevision = 0;
let exportFormat = "python";
let toastTimer;
let drag = null;
const syndromeView = createSyndromeView($("syndrome-panel"), {
  onRound(nextRound) {
    if (!isFresh()) return;
    stopPlayback();
    round = nextRound;
    updateRound();
  },
  onInject(qubit, pauli, snapshot) {
    if (!isFresh()) return;
    edit((project) => {
      project.experiment.errors.push({
        id: crypto.randomUUID(), patch: snapshot.patch_id, qubit, pauli,
        before_patch_round: snapshot.patch_round,
      });
    });
  },
  onRemove(id) {
    edit((project) => {
      project.experiment.errors = project.experiment.errors.filter((error) => error.id !== id);
    });
  },
  onClear() {
    edit((project) => { project.experiment.errors = []; });
  },
});

function toast(message) {
  $("toast").textContent = message;
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    $("toast").hidden = true;
  }, 4500);
}

function status(title, message, state = "") {
  $("compile-status").className = `compile-status ${state}`;
  $("compile-status").querySelector("strong").textContent = title;
  $("compile-status").querySelector("strong + span").textContent = message;
}

function currentSource() {
  // Experiment changes use the compiled topology locally; only assembly edits
  // invalidate geometry and exports, including when traversing undo/redo.
  const { experiment, ...assembly } = history.current;
  return JSON.stringify(assembly);
}
function isFresh() {
  return compiled && compiledSource === currentSource();
}

function updatePreviewBadge() {
  $("viewer-badge").textContent = isFresh()
    ? activeView === "spacetime"
      ? "SPACE + TIME"
      : activeView === "syndrome" ? "SYNDROME" : "SURFACE CODE"
    : "PREVIEW OUTDATED · COMPILE TO UPDATE";
}

function persist() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(history.current));
    $("save-status").textContent = "Saved on this device";
  } catch {
    $("save-status").textContent = "Download a project to save";
  }
}

function changed() {
  stopPlayback();
  persist();
  renderEditor();
  $("round-slider").disabled = !isFresh();
  $("play-rounds").disabled = !isFresh();
  updatePreviewBadge();
  renderSyndrome();
  if (!isFresh())
    status(
      "Uncompiled changes",
      "Compile to refresh both views and code exports.",
      "stale",
    );
  else
    status(
      "Assembly compiled",
      `${compiled.rounds} stabiliser rounds · Both visualization pipelines verified.`,
    );
}

function edit(change) {
  history.edit(change);
  changed();
}

function renderEditor() {
  const project = history.current;
  if (!project.patches.some((p) => p.id === selected))
    selected = project.patches[0]?.id;
  $("project-name").value = project.name;
  $("patch-count").textContent = `${project.patches.length} / 8`;
  $("add-patch").disabled =
    project.patches.length >= 8 || project.operations.length > 61;
  $("undo").disabled = !history.canUndo;
  $("redo").disabled = !history.canRedo;
  $("patch-list").innerHTML = project.patches.length
    ? project.patches
        .map(
          (p) =>
            `<button class="patch-item ${p.id === selected ? "selected" : ""}" data-patch="${p.id}" aria-pressed="${p.id === selected}"><span class="patch-swatch"></span><span class="patch-label">${escape(p.name)}</span><span class="mono">${p.width} × ${p.height}</span></button>`,
        )
        .join("")
    : '<p class="empty-list">Add a patch to get started.</p>';
  const patch = project.patches.find((p) => p.id === selected);
  $("patch-properties").hidden = !patch;
  if (patch) {
    $("selected-id").textContent = patch.id;
    for (const field of ["name", "width", "height", "x", "y"])
      $(`patch-${field}`).value = patch[field];
    $("patch-orientation").value = String(patch.vertical_z);
  }
  $("op-patch").innerHTML = project.patches
    .map((p) => `<option value="${p.id}">${escape(p.name)}</option>`)
    .join("");
  $("op-patch").value = selected || "";
  $("add-operation").querySelector("button").disabled =
    !project.patches.length || project.operations.length >= 64;
  $("operation-count").textContent = `${project.operations.length} OPERATIONS`;
  let start = 0;
  $("operation-list").innerHTML = project.operations.length
    ? project.operations
        .map((op, index) => {
          const patch = project.patches.find((p) => p.id === op.patch);
          const name = {
            prepare: "Prepare logical",
            memory: "Measure stabilisers",
            measure: "Measure logical",
          }[op.kind];
          const symbol = { prepare: "|ψ⟩", memory: "↻", measure: "M" }[op.kind];
          const description =
            op.kind === "memory"
              ? `${op.rounds} rounds · R${start + 1}–${start + op.rounds}`
              : `${op.basis} basis`;
          const highlighted =
            op.kind === "memory" &&
            isFresh() &&
            round > start &&
            round <= start + op.rounds;
          if (op.kind === "memory") start += op.rounds;
          return `<div class="operation-row ${highlighted ? "current" : ""}" data-operation="${index}"><span class="op-number">${String(index + 1).padStart(2, "0")}</span><span class="op-symbol ${op.kind}">${symbol}</span><div class="op-description">${name}<span>${escape(patch?.name || op.patch)} · ${description}</span></div>${op.kind === "memory" ? `<input type="number" min="1" max="64" value="${op.rounds}" data-edit-rounds="${index}" aria-label="Rounds for operation ${index + 1}">` : `<select data-edit-basis="${index}" aria-label="Basis for operation ${index + 1}"><option ${op.basis === "Z" ? "selected" : ""}>Z</option><option ${op.basis === "X" ? "selected" : ""}>X</option></select>`}<div class="op-arrows"><button class="icon-button" data-move-op="${index}" data-direction="-1" aria-label="Move operation ${index + 1} up" ${index === 0 ? "disabled" : ""}>↑</button><button class="icon-button" data-move-op="${index}" data-direction="1" aria-label="Move operation ${index + 1} down" ${index === project.operations.length - 1 ? "disabled" : ""}>↓</button><button class="icon-button" data-delete-op="${index}" aria-label="Remove operation ${index + 1}">×</button></div></div>`;
        })
        .join("")
    : '<p class="empty-list">Define a patch’s lifetime with preparation, stabiliser rounds, and measurement.</p>';
  renderLayout();
}

function renderLayout() {
  const project = history.current;
  const extent = Math.max(
    16,
    ...project.patches.flatMap((p) => [p.x + p.width + 2, p.y + p.height + 2]),
  );
  const size = extent * 20 + 40;
  $("layout").setAttribute("viewBox", `0 0 ${size} ${size}`);
  const marks = [];
  for (
    let coordinate = 0;
    coordinate <= Math.min(extent, 32);
    coordinate += 2
  ) {
    marks.push(
      `<text x="${20 + coordinate * 20}" y="12" text-anchor="middle" fill="#b4beca" font-size="7" font-family="monospace">${coordinate}</text><text x="9" y="${23 + coordinate * 20}" text-anchor="middle" fill="#b4beca" font-size="7" font-family="monospace">${coordinate}</text>`,
    );
  }
  const patches = project.patches
    .map((p, index) => {
      const x = p.x * 20 + 20,
        y = p.y * 20 + 20,
        w = p.width * 20,
        h = p.height * 20;
      const selectedPatch = p.id === selected;
      const fill = index % 2 ? "#deebe8" : "#e3ebfa";
      const stroke = index % 2 ? "#71a296" : "#7595cc";
      const qubits = [];
      for (let row = 0; row < p.height; row++)
        for (let column = 0; column < p.width; column++)
          qubits.push(
            `<circle cx="${x + column * 20 + 10}" cy="${y + row * 20 + 10}" r="2" fill="${stroke}"/>`,
          );
      return `<g class="layout-patch" data-layout-patch="${p.id}" tabindex="0" role="button" aria-label="${escape(p.name)}, ${p.width} by ${p.height}, position ${p.x}, ${p.y}"><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="3" fill="${fill}" fill-opacity=".7" stroke="${selectedPatch ? "#41649e" : stroke}" stroke-width="${selectedPatch ? 1.7 : 1}"/>${qubits.join("")}<line x1="${x + (p.vertical_z ? 0 : 3)}" y1="${y + (p.vertical_z ? 3 : 0)}" x2="${p.vertical_z ? x : x + w - 3}" y2="${p.vertical_z ? y + h - 3 : y}" stroke="#bc8093" stroke-width="3"/><line x1="${p.vertical_z ? x + w : x + 3}" y1="${p.vertical_z ? y + 3 : y + h}" x2="${x + w - (p.vertical_z ? 0 : 3)}" y2="${y + h - (p.vertical_z ? 3 : 0)}" stroke="#bc8093" stroke-width="3"/><text x="${x + w / 2}" y="${y + h + 11}" text-anchor="middle" font-size="8" fill="#6c809e" font-family="monospace">${escape(p.id)} · ${p.width}×${p.height}</text></g>`;
    })
    .join("");
  $("layout").innerHTML =
    `<defs><pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse" x="20" y="20"><circle cx="10" cy="10" r=".7" fill="#cbd4de"/></pattern></defs><rect x="20" y="20" width="${Math.min(extent, 32) * 20}" height="${Math.min(extent, 32) * 20}" fill="url(#grid)"/>${marks.join("")}${patches}`;
  $("layout-summary").textContent =
    `${project.patches.length} ${project.patches.length === 1 ? "patch" : "patches"} · ${project.patches.reduce((sum, p) => sum + p.width * p.height, 0)} data qubits`;
  const overlaps = project.patches.some((p, i) =>
    project.patches
      .slice(i + 1)
      .some(
        (q) =>
          p.x < q.x + q.width &&
          q.x < p.x + p.width &&
          p.y < q.y + q.height &&
          q.y < p.y + p.height,
      ),
  );
  $("geometry-status").textContent = overlaps
    ? "PATCHES OVERLAP"
    : "GEOMETRY READY";
  $("geometry-status").style.color = overlaps ? "#b56c6c" : "";
}

function errorMessage(body) {
  if (typeof body.detail === "string") return body.detail;
  if (Array.isArray(body.detail))
    return body.detail
      .map((error) => error.msg.replace(/^Value error, /, ""))
      .join(" ");
  return "Compilation failed. Check the operation sequence and try again.";
}

async function compile() {
  if (compilePromise) return compilePromise;
  const project = history.current;
  const source = currentSource();
  $("compile").disabled = true;
  $("compile").textContent = "Compiling…";
  status(
    "Compiling assembly",
    "Generating spacetime geometry and per-round surface codes…",
  );
  compilePromise = (async () => {
    try {
      const response = await fetch("/api/compile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // Compile geometry even when saved injections need repair. Validate the
        // current experiment below against the returned authoritative topology.
        body: JSON.stringify({ ...project, experiment: { errors: [] } }),
      });
      const result = await response.json();
      if (source !== currentSource()) {
        status(
          "Uncompiled changes",
          "The assembly changed during compilation. Compile again to refresh.",
          "stale",
        );
        return false;
      }
      if (!response.ok) throw new Error(errorMessage(result));
      compiled = result;
      compiledSource = source;
      round = Math.min(round, compiled.rounds);
      $("preview-empty").hidden = true;
      $("round-slider").max = compiled.rounds;
      $("round-slider").disabled = false;
      $("play-rounds").disabled = false;
      $("round-total").textContent = String(compiled.rounds).padStart(2, "0");
      status(
        "Assembly compiled",
        `${compiled.rounds} stabiliser rounds · Both visualization pipelines verified.`,
      );
      updatePreviewBadge();
      renderEditor();
      updateRound();
      refreshViewer();
      return true;
    } catch (error) {
      status("Assembly needs attention", error.message, "error");
      return false;
    } finally {
      compilePromise = null;
      $("compile").disabled = false;
      $("compile").innerHTML =
        'Compile assembly <span aria-hidden="true">→</span>';
    }
  })();
  return compilePromise;
}

function payload() {
  if (!compiled || activeView === "syndrome") return null;
  return activeView === "spacetime"
    ? compiled.spacetime
    : {
        type: "logical_patch",
        ops: compiled.patches.ops.filter((op) => op.round === round),
      };
}

function sendToViewer() {
  const data = payload();
  if (viewerReady && data)
    $("viewer").contentWindow.postMessage(
      { type: "studio-render", payload: data },
      location.origin,
    );
}

function refreshViewer() {
  if (activeView === "syndrome") return;
  // A fresh iframe releases the previous renderer's canvas, listeners, and WebGL context.
  viewerReady = false;
  $("viewer").src = `/viewer?revision=${++viewerRevision}`;
}

function roundOwner() {
  let end = 0;
  for (const op of history.current.operations) {
    if (op.kind === "memory") {
      end += op.rounds;
      if (round <= end) return op.patch;
    }
  }
  return "";
}

function updateRound() {
  $("round-value").textContent = String(round).padStart(2, "0");
  $("round-slider").value = round;
  $("round-patch").textContent = roundOwner();
  renderEditor();
  renderSyndrome();
}

function renderSyndrome() {
  const snapshot = compiled?.topology.find((item) => item.round === round);
  const drawing = compiled?.patches.ops.find((item) => item.round === round);
  const errors = history.current.experiment.errors;
  const issues = isFresh()
    ? findErrorIssues(compiled.topology, errors)
    : projectErrorIssues(history.current);
  let result = null, message = "", measurements = [];
  if (issues.length) message = "Invalid injections are listed below. Undo the assembly edit or remove them to continue.";
  if (isFresh() && snapshot && !issues.length) {
    try {
      measurements = calculateHistory(compiled.topology, errors, snapshot.patch_id);
      result = measurements.find((item) => item.patch_round === snapshot.patch_round);
    } catch (error) {
      message = error.message + " Remove or clear invalid injections to continue.";
    }
  }
  syndromeView.render({ snapshot, drawing, result, measurements, errors, issues, fresh: isFresh(), message });
}

function switchView(view) {
  activeView = view;
  for (const key of ["spacetime", "patches", "syndrome"]) {
    $(`tab-${key}`).classList.toggle("active", view === key);
    $(`tab-${key}`).setAttribute("aria-selected", String(view === key));
  }
  $("viewer").hidden = view === "syndrome";
  $("syndrome-panel").hidden = view !== "syndrome";
  $("viewer").title =
    view === "spacetime"
      ? "Deltakit spacetime visualization"
      : "Deltakit surface-code visualization";
  updatePreviewBadge();
  $("preview-note").textContent =
    view === "spacetime"
      ? "Inspect the geometry in 3D. Drag to orbit; scroll to zoom."
      : view === "syndrome"
        ? "Select a qubit or check. Errors apply before the selected patch round."
        : "Stabilisers and qubits for the patch active at this round.";
  renderSyndrome();
  refreshViewer();
}

function stopPlayback() {
  clearInterval(playing);
  playing = null;
  $("play-rounds").textContent = "▶";
  $("play-rounds").setAttribute("aria-label", "Play rounds");
}
function download(content, name, type) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function filename() {
  return (
    history.current.name.replace(/[^a-z0-9_-]+/gi, "-").replace(/^-|-$/g, "") ||
    "assembly"
  );
}
function showExport(format) {
  exportFormat = format;
  $("export-code").textContent = compiled[format];
  $("download-code").textContent =
    `Download .${format === "python" ? "py" : "mlir"} ↓`;
  $("export-python-tab").className =
    `button ${format === "python" ? "dark" : "ghost"}`;
  $("export-mlir-tab").className =
    `button ${format === "mlir" ? "dark" : "ghost"}`;
}

$("patch-list").addEventListener("click", (event) => {
  const target = event.target.closest("[data-patch]");
  if (target) {
    selected = target.dataset.patch;
    renderEditor();
  }
});
$("project-name").addEventListener("change", (event) => {
  const name = event.target.value.trim();
  if (name)
    edit((project) => {
      project.name = name;
    });
  else renderEditor();
});
for (const field of ["name", "width", "height", "x", "y"]) {
  $(`patch-${field}`).addEventListener("change", (event) => {
    const value =
      field === "name" ? event.target.value.trim() : Number(event.target.value);
    const patch = history.current.patches.find((p) => p.id === selected);
    const max = field === "x" ? 32 - patch.width : 32 - patch.height;
    if (
      (!value && field === "name") ||
      (field !== "name" &&
        (!Number.isInteger(value) ||
          value < 0 ||
          (["x", "y"].includes(field) && value > max)))
    ) {
      renderEditor();
      toast("Enter a valid value inside the workspace.");
      return;
    }
    if (
      ["width", "height"].includes(field) &&
      patch[field === "width" ? "x" : "y"] + value > 32
    ) {
      renderEditor();
      toast("Move the patch before increasing its size.");
      return;
    }
    edit((project) => {
      project.patches.find((p) => p.id === selected)[field] = value;
    });
  });
}
$("patch-orientation").addEventListener("change", (event) =>
  edit((project) => {
    project.patches.find((p) => p.id === selected).vertical_z =
      event.target.value === "true";
  }),
);
$("delete-patch").addEventListener("click", () =>
  edit((project) => deletePatch(project, selected)),
);
$("add-patch").addEventListener("click", () => {
  const project = history.current;
  const id = nextPatchId(project);
  const index = Number(id.slice(1));
  let position;
  for (let y = 2; y <= 28 && !position; y += 4)
    for (let x = 2; x <= 28 && !position; x += 4) {
      if (
        !project.patches.some(
          (p) =>
            x < p.x + p.width &&
            p.x < x + 3 &&
            y < p.y + p.height &&
            p.y < y + 3,
        )
      )
        position = { x, y };
    }
  if (!position) {
    toast("Make room in the workspace before adding a patch.");
    return;
  }
  selected = id;
  edit((p) => {
    p.patches.push({
      id,
      name: `Patch ${index + 1}`,
      width: 3,
      height: 3,
      ...position,
      vertical_z: true,
    });
    p.operations.push(
      { kind: "prepare", patch: id, basis: "Z" },
      { kind: "memory", patch: id, rounds: 3 },
      { kind: "measure", patch: id, basis: "Z" },
    );
  });
});
$("operation-list").addEventListener("click", (event) => {
  const remove = event.target.closest("[data-delete-op]");
  const move = event.target.closest("[data-move-op]");
  if (remove)
    edit((project) => {
      project.operations.splice(Number(remove.dataset.deleteOp), 1);
    });
  if (move)
    edit((project) => {
      const index = Number(move.dataset.moveOp);
      const next = index + Number(move.dataset.direction);
      [project.operations[index], project.operations[next]] = [
        project.operations[next],
        project.operations[index],
      ];
    });
});
$("operation-list").addEventListener("change", (event) => {
  if (event.target.matches("[data-edit-rounds]")) {
    const value = Number(event.target.value);
    if (!Number.isInteger(value) || value < 1 || value > 64) {
      renderEditor();
      toast("Choose between 1 and 64 rounds.");
      return;
    }
    edit((project) => {
      project.operations[Number(event.target.dataset.editRounds)].rounds =
        value;
    });
  }
  if (event.target.matches("[data-edit-basis]"))
    edit((project) => {
      project.operations[Number(event.target.dataset.editBasis)].basis =
        event.target.value;
    });
});
function updateComposer() {
  $("op-basis-label").hidden = $("op-kind").value === "memory";
  $("op-rounds-label").hidden = $("op-kind").value !== "memory";
}
$("op-kind").addEventListener("change", updateComposer);
$("add-operation").addEventListener("submit", (event) => {
  event.preventDefault();
  if (
    !history.current.patches.length ||
    history.current.operations.length >= 64
  )
    return;
  const kind = $("op-kind").value;
  const patch = $("op-patch").value;
  const op =
    kind === "memory"
      ? { kind, patch, rounds: Number($("op-rounds").value) }
      : { kind, patch, basis: $("op-basis").value };
  edit((project) => {
    project.operations.push(op);
  });
});
$("undo").addEventListener("click", () => {
  history.undo();
  changed();
});
$("redo").addEventListener("click", () => {
  history.redo();
  changed();
});
document.addEventListener("keydown", (event) => {
  if (
    event.target.matches("input,select,textarea") ||
    document.querySelector("dialog[open]")
  )
    return;
  if (
    (event.ctrlKey || event.metaKey) &&
    ["z", "y"].includes(event.key.toLowerCase())
  ) {
    event.preventDefault();
    if (event.shiftKey || event.key.toLowerCase() === "y") history.redo();
    else history.undo();
    changed();
  }
});
function svgPoint(event) {
  const point = $("layout").createSVGPoint();
  point.x = event.clientX;
  point.y = event.clientY;
  return point.matrixTransform($("layout").getScreenCTM().inverse());
}
$("layout").addEventListener("pointerdown", (event) => {
  const target = event.target.closest("[data-layout-patch]");
  if (!target || event.button !== 0) return;
  event.preventDefault();
  selected = target.dataset.layoutPatch;
  renderEditor();
  const patch = history.current.patches.find((p) => p.id === selected);
  drag = {
    patch,
    start: svgPoint(event),
    x: patch.x,
    y: patch.y,
    id: event.pointerId,
  };
  $("layout").setPointerCapture(event.pointerId);
});
$("layout").addEventListener("pointermove", (event) => {
  if (!drag) return;
  const point = svgPoint(event);
  drag.x = Math.max(
    0,
    Math.min(
      32 - drag.patch.width,
      drag.patch.x + Math.round((point.x - drag.start.x) / 20),
    ),
  );
  drag.y = Math.max(
    0,
    Math.min(
      32 - drag.patch.height,
      drag.patch.y + Math.round((point.y - drag.start.y) / 20),
    ),
  );
  $("layout")
    .querySelector(`[data-layout-patch="${drag.patch.id}"]`)
    .setAttribute(
      "transform",
      `translate(${(drag.x - drag.patch.x) * 20} ${(drag.y - drag.patch.y) * 20})`,
    );
});
$("layout").addEventListener("pointerup", () => {
  if (!drag) return;
  const moved = drag;
  drag = null;
  edit((project) => {
    const patch = project.patches.find((p) => p.id === moved.patch.id);
    patch.x = moved.x;
    patch.y = moved.y;
  });
});
$("layout").addEventListener("pointercancel", () => {
  drag = null;
  renderLayout();
});
$("layout").addEventListener("keydown", (event) => {
  const target = event.target.closest("[data-layout-patch]");
  if (!target) return;
  if (["Enter", " "].includes(event.key)) {
    event.preventDefault();
    selected = target.dataset.layoutPatch;
    renderEditor();
  }
  const offset = {
    ArrowLeft: [-1, 0],
    ArrowRight: [1, 0],
    ArrowUp: [0, -1],
    ArrowDown: [0, 1],
  }[event.key];
  if (offset) {
    event.preventDefault();
    selected = target.dataset.layoutPatch;
    edit((project) => {
      const patch = project.patches.find((p) => p.id === selected);
      patch.x = Math.max(0, Math.min(32 - patch.width, patch.x + offset[0]));
      patch.y = Math.max(0, Math.min(32 - patch.height, patch.y + offset[1]));
    });
    $("layout").querySelector(`[data-layout-patch="${selected}"]`)?.focus();
  }
});
$("compile").addEventListener("click", compile);
$("tab-spacetime").addEventListener("click", () => switchView("spacetime"));
$("tab-patches").addEventListener("click", () => switchView("patches"));
$("tab-syndrome").addEventListener("click", () => switchView("syndrome"));
$("round-slider").addEventListener("input", (event) => {
  stopPlayback();
  round = Number(event.target.value);
  updateRound();
  if (activeView === "patches") refreshViewer();
});
$("play-rounds").addEventListener("click", () => {
  if (playing) {
    stopPlayback();
    return;
  }
  if (!isFresh()) return;
  if (activeView === "spacetime") switchView("patches");
  $("play-rounds").textContent = "Ⅱ";
  $("play-rounds").setAttribute("aria-label", "Pause rounds");
  playing = setInterval(() => {
    round = (round % compiled.rounds) + 1;
    updateRound();
    refreshViewer();
  }, 1200);
});
window.addEventListener("message", (event) => {
  if (
    event.origin !== location.origin ||
    event.source !== $("viewer").contentWindow
  )
    return;
  if (event.data?.type === "studio-viewer-ready") {
    viewerReady = true;
    sendToViewer();
  }
  if (event.data?.type === "studio-renderer-error")
    status("Preview unavailable", event.data.message, "error");
});
$("load-example").addEventListener("click", () => {
  edit((project) => {
    Object.assign(project, memoryExample());
  });
  selected = "p0";
  round = 1;
  renderEditor();
  compile();
});
$("save-project").addEventListener("click", () => {
  download(
    JSON.stringify(history.current, null, 2),
    `${filename()}.json`,
    "application/json",
  );
  toast("Project downloaded.");
});
$("open-project").addEventListener("click", () => $("project-file").click());
$("project-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    if (file.size > 1000000)
      throw new Error("Project files must be smaller than 1 MB.");
    const project = normaliseProject(JSON.parse(await file.text()));
    edit((current) => {
      Object.assign(current, project);
    });
    selected = project.patches[0]?.id;
    round = 1;
    renderEditor();
    toast("Project opened.");
    compile();
  } catch (error) {
    toast(error.message);
  }
  event.target.value = "";
});
$("export-project").addEventListener("click", async () => {
  if (!isFresh() && !(await compile())) return;
  if (!isFresh()) return;
  showExport("python");
  $("export-dialog").showModal();
});
$("export-python-tab").addEventListener("click", () => showExport("python"));
$("export-mlir-tab").addEventListener("click", () => showExport("mlir"));
$("download-code").addEventListener("click", () =>
  download(
    compiled[exportFormat],
    `${filename()}.${exportFormat === "python" ? "py" : "mlir"}`,
    "text/plain",
  ),
);
$("copy-code").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(compiled[exportFormat]);
    toast("Code copied.");
  } catch {
    toast("Select the code and copy it with Ctrl/⌘ C.");
  }
});
$("help").addEventListener("click", () => $("help-dialog").showModal());
document
  .querySelectorAll("[data-close]")
  .forEach((button) =>
    button.addEventListener("click", () => $(button.dataset.close).close()),
  );
document.querySelectorAll("dialog").forEach((dialog) =>
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) {
      const bounds = dialog.getBoundingClientRect();
      if (
        event.clientX < bounds.left ||
        event.clientX > bounds.right ||
        event.clientY < bounds.top ||
        event.clientY > bounds.bottom
      )
        dialog.close();
    }
  }),
);

updateComposer();
renderEditor();
persist();
$("preview-empty").hidden = true;
$("round-slider").disabled = true;
$("play-rounds").disabled = true;
compile();
