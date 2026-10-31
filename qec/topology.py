# (c) Copyright Riverlane 2025-2026. All rights reserved.
"""Extract physical stabilizers from Deltakit's per-round drawing payload.

Coordinates, not renderer-local IDs, identify data qubits. Check identities encode
basis and sorted support, so reordering or renumbering drawing elements has no
physical effect. Coordinates are in the compiler's workspace coordinate system.
"""


def extract_topology(item: dict, *, patch_id: str, patch_round: int) -> dict:
    """Return one owned round without modifying the compiler's renderer payload.

    ``item['round']`` is the global timeline round; ``patch_round`` counts only
    measurements of this patch. Both are one-based. Red means X and blue means Z
    in the pinned compiler's VisualiseSurfaceCodes pass. Boundary drawing ancillas
    must be excluded before interpreting plaquette weight as Pauli support.
    """
    qubits = {q["id"]: q for q in item["qubits"]}
    data_ids = {}
    data_qubits = []
    for local_id, qubit in qubits.items():
        if qubit["type"] != "data":
            continue
        x, y = qubit["coordinates"]
        stable_id = f"{patch_id}:d:{x:g},{y:g}"
        data_ids[local_id] = stable_id
        data_qubits.append({"id": stable_id, "position": [x, y]})

    checks = []
    for patch in item["patches"]:
        for plaquette in patch["plaquettes"]:
            colour = plaquette["colour"]
            if colour not in {"red", "blue"}:
                msg = f"Unsupported stabilizer colour: {colour!r}."
                raise ValueError(msg)
            basis = {"red": "X", "blue": "Z"}[colour]
            if any(ref not in qubits for ref in plaquette["coordinates"]):
                msg = "Stabilizer has an unknown qubit reference."
                raise ValueError(msg)
            support = sorted({data_ids[ref] for ref in plaquette["coordinates"] if ref in data_ids})
            if not support or len(support) != plaquette["weight"]:
                msg = "Stabilizer weight does not match its data-qubit support."
                raise ValueError(msg)
            checks.append(
                {
                    "id": f"{patch_id}:{basis}:" + ";".join(support),
                    "basis": basis,
                    "weight": len(support),
                    "data_qubits": support,
                }
            )

    return {
        "patch_id": patch_id,
        "round": item["round"],
        "patch_round": patch_round,
        "data_qubits": sorted(data_qubits, key=lambda q: q["id"]),
        "checks": sorted(checks, key=lambda c: c["id"]),
    }
