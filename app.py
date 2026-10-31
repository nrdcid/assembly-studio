# (c) Copyright Riverlane 2025-2026. All rights reserved.
"""A small, stateless web editor for sequential logical-assembly memory programs."""

from pathlib import Path
from typing import Annotated, Literal

from deltakit_compile.frontend.logasm import LogAsmBuilder, RotatedPlanarPatch
from deltakit_visualise import (
    LogicalAssemblyVisualiser,
    PatchVisualisationPipeline,
    SpacetimePipeline,
    get_visualisation_data,
)
from deltakit_visualise.constants import JS_HOME_DIR
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from xdsl.utils.exceptions import VerifyException

from qec.topology import extract_topology

BASE_DIR = Path(__file__).resolve().parent
MAX_ROUNDS = 64


class StrictModel(BaseModel):
    """Reject unknown fields and implicit numeric conversions in project files."""

    model_config = ConfigDict(extra="forbid", strict=True)


class Patch(StrictModel):
    """A bounded, rectangular rotated-planar surface-code patch."""

    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,31}$")
    name: str = Field(min_length=1, max_length=48)
    width: int = Field(ge=3, le=11)
    height: int = Field(ge=3, le=11)
    x: int = Field(ge=0, le=29)
    y: int = Field(ge=0, le=29)
    vertical_z: bool = True

    @field_validator("width", "height")
    @classmethod
    def odd_dimensions(cls, value: int) -> int:
        """Keep the pilot within the tested odd-distance surface-code family."""
        if value % 2 == 0:
            msg = "Patch dimensions must be odd (3, 5, 7, 9, or 11)."
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def fits_workspace(self) -> "Patch":
        """Prevent imported patches from extending outside the editor grid."""
        if self.x + self.width > 32 or self.y + self.height > 32:
            msg = "Patches must fit inside the 32 x 32 workspace."
            raise ValueError(msg)
        return self


class BasisOperation(StrictModel):
    """Logical preparation or destructive measurement in an implemented basis."""

    kind: Literal["prepare", "measure"]
    patch: str = Field(max_length=32)
    basis: Literal["X", "Z"]


class MemoryOperation(StrictModel):
    """A fixed number of stabiliser-measurement rounds."""

    kind: Literal["memory"]
    patch: str = Field(max_length=32)
    rounds: int = Field(ge=1, le=MAX_ROUNDS)


Operation = Annotated[BasisOperation | MemoryOperation, Field(discriminator="kind")]


class ErrorInjection(StrictModel):
    """An analysis-only Pauli applied before a patch measurement round."""

    id: str = Field(min_length=1, max_length=128)
    patch: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,31}$")
    qubit: str = Field(min_length=1, max_length=128)
    pauli: Literal["X", "Y", "Z"]
    before_patch_round: int = Field(ge=1, le=MAX_ROUNDS)


class Experiment(StrictModel):
    """Error scenario, kept separate from the exported logical assembly."""

    errors: list[ErrorInjection] = Field(max_length=1024)

    @model_validator(mode="after")
    def unique_ids(self) -> "Experiment":
        """Keep injection identity unambiguous for editing and removal."""
        if len({error.id for error in self.errors}) != len(self.errors):
            msg = "Error injection IDs must be unique."
            raise ValueError(msg)
        return self


class Project(StrictModel):
    """The editable source of truth, independent of generated rendering data."""

    version: Literal[2]
    experiment: Experiment = Field(default_factory=lambda: Experiment(errors=[]))
    name: str = Field(min_length=1, max_length=80)
    patches: list[Patch] = Field(min_length=1, max_length=8)
    operations: list[Operation] = Field(min_length=1, max_length=64)

    @model_validator(mode="before")
    @classmethod
    def migrate_v1(cls, value):
        """Upgrade legacy files without modifying the caller's input."""
        if isinstance(value, dict) and value.get("version") == 1:
            if "experiment" in value:
                msg = "Experiments require project version 2."
                raise ValueError(msg)
            return {**value, "version": 2}
        return value

    @model_validator(mode="after")
    def valid_assembly(self) -> "Project":  # noqa: PLR0912
        """Check references, patch lifetimes, geometry, and the expansion budget."""
        ids = {patch.id for patch in self.patches}
        if len(ids) != len(self.patches):
            msg = "Patch IDs must be unique."
            raise ValueError(msg)
        for index, first in enumerate(self.patches):
            for second in self.patches[index + 1 :]:
                if (
                    first.x < second.x + second.width
                    and second.x < first.x + first.width
                    and first.y < second.y + second.height
                    and second.y < first.y + first.height
                ):
                    msg = f"Patches {first.name!r} and {second.name!r} overlap."
                    raise ValueError(msg)
        states = dict.fromkeys(ids, "declared")
        total_rounds = 0
        for index, operation in enumerate(self.operations, start=1):
            prefix = f"Operation {index}: "
            if operation.patch not in ids:
                raise ValueError(prefix + f"Unknown patch {operation.patch!r}.")
            state = states[operation.patch]
            if state == "measured":
                raise ValueError(prefix + "this patch has already been measured.")
            if operation.kind == "prepare":
                if state == "prepared":
                    raise ValueError(prefix + "this patch is already prepared.")
                states[operation.patch] = "prepared"
            elif state != "prepared":
                raise ValueError(prefix + "Prepare the patch before using it.")
            elif operation.kind == "measure":
                states[operation.patch] = "measured"
            else:
                total_rounds += operation.rounds
        if total_rounds == 0:
            msg = "Add at least one stabiliser-measurement operation to preview rounds."
            raise ValueError(msg)
        if total_rounds > MAX_ROUNDS:
            msg = f"The pilot supports at most {MAX_ROUNDS} total stabiliser rounds."
            raise ValueError(msg)
        return self


def build_program(project: Project):
    """Build a fresh compiler program and matching executable Python export."""
    builder = LogAsmBuilder()
    patches: dict[str, RotatedPlanarPatch] = {}
    variables: dict[str, str] = {}
    lines = [
        "# Exported from Assembly Studio. Operations execute sequentially.",
        "from deltakit_compile.frontend.logasm import LogAsmBuilder, RotatedPlanarPatch",
        "from deltakit_visualise import LogicalAssemblyVisualiser",
        "",
        "builder = LogAsmBuilder()",
    ]
    for index, spec in enumerate(project.patches):
        patch = builder.declare_patch(
            RotatedPlanarPatch(
                spec.width, spec.height, location=(spec.x, spec.y), vertical_z=spec.vertical_z
            )
        )
        patch.ssa.name_hint = spec.id
        patches[spec.id] = patch
        variable = f"patch_{index}"
        variables[spec.id] = variable
        lines.extend(
            [
                f"{variable} = builder.declare_patch(RotatedPlanarPatch(",
                f"    {spec.width}, {spec.height}, location=({spec.x}, {spec.y}), "
                f"vertical_z={spec.vertical_z}))",
                f"{variable}.ssa.name_hint = {spec.id!r}",
            ]
        )
    lines.append("")
    for operation in project.operations:
        patch = patches[operation.patch]
        variable = variables[operation.patch]
        if operation.kind == "prepare":
            patch.prepare(operation.basis)
            lines.append(f"{variable}.prepare({operation.basis!r})")
        elif operation.kind == "memory":
            patch.measure_stabilisers(operation.rounds)
            lines.append(f"{variable}.measure_stabilisers({operation.rounds})")
        else:
            patch.measure(operation.basis)
            lines.append(f"{variable}.measure({operation.basis!r})")
    lines.extend(
        [
            "",
            "program = builder.build_program()",
            "",
            'if __name__ == "__main__":',
            "    print(LogicalAssemblyVisualiser(program).module)",
            "",
        ]
    )
    return builder.build_program(), "\n".join(lines)


def compile_project(project: Project) -> dict:
    """Generate linked views on separate IR clones, without opening a local browser."""
    program, python_source = build_program(project)
    visualiser = LogicalAssemblyVisualiser(program)
    module = visualiser.module
    module.verify()
    mlir = str(module)
    spacetime = module.clone()
    SpacetimePipeline().apply(visualiser.context, spacetime)
    spacetime.verify()
    # The compiler's current multi-patch lowering can place allocations inside
    # nested circuits that fail HasProgramParent verification. Independent memory
    # patches can be lowered and verified individually without changing semantics.
    # Remap their local rounds to the original sequential assembly's round numbers.
    global_rounds: dict[str, list[int]] = {patch.id: [] for patch in project.patches}
    current_round = 0
    for operation in project.operations:
        if operation.kind == "memory":
            global_rounds[operation.patch].extend(
                range(current_round + 1, current_round + operation.rounds + 1)
            )
            current_round += operation.rounds
    patch_items = []
    topology = []
    for spec in project.patches:
        if not global_rounds[spec.id]:
            continue
        individual = Project(
            version=2,
            name=project.name,
            patches=[spec],
            operations=[op for op in project.operations if op.patch == spec.id],
        )
        patch_program, _ = build_program(individual)
        patch_visualiser = LogicalAssemblyVisualiser(patch_program)
        patch_module = patch_visualiser.module
        patch_module.verify()
        PatchVisualisationPipeline().apply(patch_visualiser.context, patch_module)
        patch_module.verify()
        for item in get_visualisation_data(patch_module)["ops"]:
            patch_round = item["round"]
            item["round"] = global_rounds[spec.id][patch_round - 1]
            topology.append(extract_topology(item, patch_id=spec.id, patch_round=patch_round))
            patch_items.append(item)
    patch_items.sort(key=lambda item: item["round"])
    topology.sort(key=lambda item: item["round"])
    for error in project.experiment.errors:
        target = next(
            (
                item
                for item in topology
                if item["patch_id"] == error.patch
                and item["patch_round"] == error.before_patch_round
            ),
            None,
        )
        if target is None:
            msg = f"Error {error.id}: unknown patch or invalid injection round."
            raise ValueError(msg)
        if error.qubit not in {q["id"] for q in target["data_qubits"]}:
            msg = f"Error {error.id}: unknown data qubit {error.qubit!r}."
            raise ValueError(msg)
    return {
        "spacetime": get_visualisation_data(spacetime),
        "patches": {"type": "logical_patch", "ops": patch_items},
        "topology": topology,
        "rounds": sum(op.rounds for op in project.operations if op.kind == "memory"),
        "python": python_source,
        "mlir": mlir,
    }


app = FastAPI(title="Assembly Studio", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/")
def editor() -> FileResponse:
    """Serve the browser editor."""
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/viewer")
def viewer() -> FileResponse:
    """Serve an isolated instance of the existing Deltakit renderer."""
    return FileResponse(BASE_DIR / "static" / "viewer.html")


@app.get("/renderer.js")
def renderer() -> FileResponse:
    """Use the pinned pilot bundle, or an existing wheel's bundled assets."""
    for path in (
        BASE_DIR / "vendor" / "deltakit-visualise.umd.js",
        JS_HOME_DIR / "dist" / "deltakit-visualise.umd.js",
    ):
        if path.is_file():
            return FileResponse(path, media_type="text/javascript")
    raise HTTPException(503, "Renderer missing. Run python setup_renderer.py.")


@app.post("/api/compile")
def compile_endpoint(project: Project) -> dict:
    """Compile bounded structured input; every request owns its program and results."""
    try:
        return compile_project(project)
    except (ValueError, RuntimeError, NotImplementedError, VerifyException) as exc:
        raise HTTPException(422, f"Deltakit could not compile this assembly: {exc}") from exc
