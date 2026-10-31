# Assembly Studio

A small browser editor for Deltakit Logical Assembly programs. FastAPI serves a
plain JavaScript/SVG editor; the existing Deltakit compiler generates both views,
and the pinned Deltakit JavaScript renderer displays them. No frontend build step,
database, or cloud account is required.

## Run locally

Run from the `assembly-studio` repository root with Python 3.10–3.14 and `uv` installed:

```bash
uv venv --python 3.13
uv pip install -r requirements.txt
.venv/bin/python setup_renderer.py
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8010
```

Open <http://127.0.0.1:8010>. Node.js/npm is needed only by the renderer setup
script. That script downloads `deltakit-visualise@0.7.0`, verifies its SHA-256,
and copies the self-contained lite bundle and licence notices to ignored
`vendor/`. It does not install npm dependencies. An existing
Python wheel's bundled renderer is also accepted as a fallback.

Python runtime dependencies are declared in `requirements.txt`, including the published
`deltakit-visualise==0.4.0` and `deltakit-compile==0.1.0` packages. No sibling
checkout is required. Development dependencies are in `requirements-dev.txt`.

## Use the editor

1. Start with the quantum-memory example. Drag its patch or edit its coordinates,
   odd dimensions, and Z-boundary orientation.
2. Edit X/Z preparation and measurement bases and stabiliser-round counts. Add,
   delete, or reorder operations. Adding a patch creates a default memory lifetime.
3. Compile to refresh the 3D spacetime view and 2D per-round surface-code view.
   Switch tabs, scrub the round slider, or play the rounds. The active timeline
   operation is highlighted. Drag the 3D view to orbit; scroll to zoom.
4. Save/open project JSON, or export executable Python and Logical Assembly MLIR.
   Undo/redo works with buttons and Ctrl/⌘ Z / Ctrl/⌘ Shift Z.

The editable project is the source of truth. Changes invalidate the current
preview; export recompiles when needed. Projects auto-save in this browser's
local storage. Download JSON to move a project between browsers or devices.

Running an exported Python file prints its Logical Assembly IR. Its `program`
variable can also be imported into a Deltakit compilation or visualization workflow.

## Deliberate pilot scope

- Sequential quantum-memory assemblies with up to eight nonoverlapping rectangular
  rotated-planar patches on a 32 × 32 grid.
- Patch widths/heights of 3, 5, 7, 9, or 11; X and Z preparation/measurement bases.
- Up to 64 operations and 64 total stabiliser rounds. Logical measurement ends
  the patch's lifetime; preparation is required before subsequent operations.
- The per-round view displays the patch being operated on at that round, rather
  than a simultaneous snapshot of all declared patches.
- Geometry/lifecycle validation and compiler IR verification. These checks do
  **not** establish fault tolerance, logical correctness, or logical error rates.
- No parallel scheduling, lattice surgery, noise simulation, decoding, arbitrary
  Python execution/import, accounts, or shared project storage.

`POST /api/compile` accepts bounded structured project JSON and returns `spacetime`,
`patches`, `topology`, `rounds`, `python`, and `mlir`. It builds a fresh program per request,
clones the IR for spacetime rendering, and does not use the library's
shared HTML cache or start a separate server per project. Project errors return
HTTP 422 with an explanation. The pilot binds to localhost by default.

The current compiler's combined lowering of independent patches can produce nested
allocations that fail IR verification. This pilot lowers each independent memory
patch separately, verifies the resulting IR, and maps its snapshots back to global
timeline rounds. The full logical assembly still drives spacetime and code exports.

`topology` is a list sorted by global `round`. Each entry contains `patch_id`,
the one-based global `round`, the one-based `patch_round` (counting only that
patch's stabilizer measurements), `data_qubits`, and `checks`:

- Data qubits have an `id` and a two-dimensional `position` in compiler workspace
  coordinates. IDs use `patch_id:d:x,y`; moving a patch changes these IDs.
- Checks have an `id`, explicit `basis` (`X` or `Z`), `weight`, and a sorted list
  of `data_qubits` IDs. Their IDs encode the patch, basis, and sorted support.
  IDs survive round changes and renderer element reordering or renumbering.
- Supports come directly from compiler plaquettes, with drawing ancillas removed.
  The compiler's red/blue mapping becomes X/Z; unsupported colors, unknown qubit
  references, and inconsistent weights raise compilation errors.

This is topology only: error injection and syndrome calculations are not yet
implemented. Existing renderer payloads and Python/MLIR exports are unchanged.

## Verify

```bash
uv pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests -q
node tests/state.test.mjs
.venv/bin/ruff check --config ruff.toml .
.venv/bin/ruff format --check --config ruff.toml .
```

The tests compile actual programs, verify both payloads and geometry changes,
round-trip Python/MLIR exports, reject malformed or unsupported assemblies, and
check isolated requests. Node tests cover undo/redo, patch deletion, and project
file handling.

For browser verification, start the server, then:

```bash
.venv/bin/python -m playwright install chromium
.venv/bin/python tests/browser_smoke.py
```

The browser check exercises compilation, geometry editing, undo/redo, round
scrubbing, both real renderers, errors, project downloads/import, and code exports.
Screenshots are saved under ignored `artifacts/`.
