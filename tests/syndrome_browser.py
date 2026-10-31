# (c) Copyright Riverlane 2025-2026. All rights reserved.
"""Exercise the interactive syndrome view against actual compiler output."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():  # noqa: PLR0915
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8011")
    parser.add_argument("--browser", required=True)
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.browser)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        errors = []
        requests = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: requests.append(request.url))
        page.goto(args.url)
        expect(page.locator("#compile-status strong")).to_have_text("Assembly compiled")
        page.locator("#tab-syndrome").click(timeout=2000)
        expect(page.locator("#syndrome-svg")).to_be_visible()
        expect(page.locator("#viewer")).to_be_hidden()
        expect(page.locator("[data-qubit]")).to_have_count(9)
        expect(page.locator("[data-check]")).to_have_count(8)
        expect(page.locator("[data-ancilla]")).to_have_count(8)
        page.locator("#round-slider").fill("2")
        expect(page.locator("#syndrome-round")).to_contain_text("Patch round 2")
        page.locator('[data-qubit="p0:d:2.5,2.5"]').click()
        expect(page.locator("#syndrome-inspector")).to_contain_text("2.5, 2.5")
        expect(page.locator("#syndrome-inspector")).to_contain_text("Associated checks")
        before = len(requests)
        for pauli in ["X", "Y", "Z"]:
            page.locator("#inject-pauli").select_option(pauli)
            page.locator("#inject-error").click()
            expect(page.locator("#syndrome-errors li")).to_have_count(1)
            result = page.evaluate("""async () => {
                const project = JSON.parse(localStorage.getItem('assembly-studio.project.v1'));
                const compiled = await fetch('/api/compile', {method:'POST',
                    headers:{'Content-Type':'application/json'}, body:JSON.stringify(project)}
                ).then(r => r.json());
                const {calculateSyndrome} = await import('/static/syndrome.mjs');
                return {snapshot:compiled.topology[1], ...calculateSyndrome(compiled.topology,
                    project.experiment.errors, 'p0', 2)};
            }""")
            flipped = page.locator('[data-check][data-syndrome="1"]')
            assert (
                sorted(flipped.evaluate_all("els => els.map(e => e.dataset.check)"))
                == result["affectedChecks"]
            )
            marker = page.locator('[data-qubit="p0:d:2.5,2.5"] .error-marker')
            expect(marker).to_have_text(pauli)
            check = result["snapshot"]["checks"][0]
            page.locator("[data-check]").filter(has_text=check["basis"]).first.click()
            expect(page.locator("#syndrome-inspector")).to_contain_text("Weight")
            expect(page.locator("#syndrome-inspector")).to_contain_text("Syndrome bit")
            selected_id = page.locator('[data-check][aria-pressed="true"]').get_attribute(
                "data-check"
            )
            selected_check = next(c for c in result["snapshot"]["checks"] if c["id"] == selected_id)
            highlighted = page.locator("[data-qubit].in-support").evaluate_all(
                "els => els.map(e => e.dataset.qubit)"
            )
            assert sorted(highlighted) == sorted(selected_check["data_qubits"])
            page.locator("#clear-errors").click()
            page.locator('[data-qubit="p0:d:2.5,2.5"]').click()
        # The only compilation requests above are the explicit test oracle queries.
        assert sum(url.endswith("/api/compile") for url in requests[before:]) == 3
        assert not any("/viewer?" in url for url in requests[before:])
        page.locator("#inject-error").click()
        page.locator("#round-slider").fill("1")
        expect(page.locator('[data-check][data-syndrome="1"]')).to_have_count(0)
        page.locator("#round-slider").fill("3")
        assert page.locator('[data-check][data-syndrome="1"]').count() > 0
        page.locator("#undo").click()
        expect(page.locator("#syndrome-errors li")).to_have_count(0)
        page.locator("#redo").click()
        expect(page.locator("#syndrome-errors li")).to_have_count(1)
        page.locator("[data-remove-error]").click()
        expect(page.locator("#syndrome-errors li")).to_have_count(0)
        page.locator("[data-ancilla]").first.click()
        expect(page.locator("#syndrome-inspector")).to_contain_text("Ancilla")
        expect(page.locator("#inject-error")).to_be_disabled()
        page.locator("[data-qubit]").first.focus()
        page.keyboard.press("Enter")
        expect(page.locator("#inject-error")).to_be_enabled()
        page.locator("#patch-x").fill("6")
        page.locator("#patch-x").press("Tab")
        expect(page.locator("#inject-error")).to_be_disabled()
        expect(page.locator("#syndrome-message")).to_contain_text("Compile")
        expect(page.locator("#syndrome-svg")).to_have_attribute("aria-disabled", "true")
        page.locator("#compile").click()
        expect(page.locator("#compile-status strong")).to_have_text("Assembly compiled")
        expect(page.locator('[data-qubit="p0:d:2.5,2.5"]')).to_have_count(0)
        page.locator("[data-qubit]").first.click()
        expect(page.locator("#inject-error")).to_be_enabled()
        page.locator("#inject-error").click()
        page.reload()
        expect(page.locator("#compile-status strong")).to_have_text("Assembly compiled")
        page.locator("#tab-syndrome").click()
        expect(page.locator("#syndrome-errors li")).to_have_count(1)
        page.locator("#clear-errors").click()
        page.locator("#add-patch").click()
        page.locator("#compile").click()
        expect(page.locator("#compile-status strong")).to_have_text("Assembly compiled")
        page.locator("#round-slider").fill("4")
        expect(page.locator("#syndrome-round")).to_contain_text("p1 · Patch round 1")
        expect(page.locator("#inject-error")).to_be_disabled()
        page.locator("[data-qubit]").first.click()
        page.locator("#inject-error").click()
        page.locator("#round-slider").fill("1")
        expect(page.locator('[data-check][data-syndrome="1"]')).to_have_count(0)
        page.locator("#round-slider").fill("4")
        artifact = Path(__file__).resolve().parents[1] / "artifacts"
        artifact.mkdir(exist_ok=True)
        verify_history(page)
        page.screenshot(path=str(artifact / "syndrome-history.png"), full_page=True)
        verify_lifecycle(page)
        verify_compiler_geometry(page)
        verify_pending_compile(page)
        artifact = Path(__file__).resolve().parents[1] / "artifacts"
        artifact.mkdir(exist_ok=True)
        page.screenshot(path=str(artifact / "syndrome-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(artifact / "syndrome-mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not errors, errors
        browser.close()


def verify_history(page):
    """History navigation and playback agree with direct round selection."""
    page.locator("#load-example").click()
    expect(page.locator("#compile-status strong")).to_have_text("Assembly compiled")
    page.locator("#round-slider").fill("2")
    page.locator('[data-qubit="p0:d:2.5,2.5"]').click()
    page.locator("#inject-pauli").select_option("X")
    page.locator("#inject-error").click()
    count = page.locator('[data-check][data-detection="1"]').count()
    assert count > 0
    expect(page.locator("[data-history-check]")).to_have_count(count)
    page.locator("#round-slider").fill("3")
    expect(page.locator('[data-check][data-detection="1"]')).to_have_count(0)
    expect(page.locator('[data-check][data-syndrome="1"]')).to_have_count(count)
    expected = page.locator("#syndrome-summary").inner_text()
    page.locator('[data-history-round="2"]').first.click()
    expect(page.locator("#round-value")).to_have_text("02")
    expect(page.locator('[data-check][data-detection="1"]')).to_have_count(count)
    page.locator("#play-rounds").click()
    expect(page.locator("#round-value")).to_have_text("03")
    page.locator("#play-rounds").click()
    expect(page.locator("#tab-syndrome")).to_have_attribute("aria-selected", "true")
    expect(page.locator("#syndrome-summary")).to_have_text(expected)
    page.locator("#inject-error").click()
    expect(page.locator('[data-check][data-syndrome="1"]')).to_have_count(0)
    expect(page.locator('[data-check][data-detection="1"]')).to_have_count(count)
    expect(page.locator('[data-history-round="3"]').first).to_have_text("0 ◆")
    page.locator("#add-patch").click()
    page.locator("#compile").click()
    expect(page.locator("#compile-status strong")).to_have_text("Assembly compiled")
    page.locator("#round-slider").fill("4")
    expect(page.locator("[data-history-check]")).to_have_count(0)
    page.locator("#round-slider").fill("3")
    expect(page.locator("[data-history-check]")).to_have_count(count)


def verify_lifecycle(page):
    """Invalid experiments remain visible, repairable, and persistent."""
    page.locator("#load-example").click()
    expect(page.locator("#compile-status strong")).to_have_text("Assembly compiled")
    page.locator("#patch-width").select_option("5")
    page.locator("#compile").click()
    expect(page.locator("#compile-status strong")).to_have_text("Assembly compiled")
    page.locator('[data-qubit="p0:d:6.5,2.5"]').click()
    page.locator("#inject-error").click()
    page.locator("#patch-width").select_option("3")
    expect(page.locator("#syndrome-svg")).to_have_attribute("aria-disabled", "true")
    page.locator("#compile").click()
    expect(page.locator(".injection-issue")).to_contain_text("Unknown data qubit")
    expect(page.locator("#inject-error")).to_be_disabled()
    page.reload()
    expect(page.locator("#compile-status strong")).to_have_text("Assembly compiled")
    page.locator("#tab-syndrome").click()
    expect(page.locator(".injection-issue")).to_contain_text("Unknown data qubit")
    page.locator("[data-remove-error]").click()
    expect(page.locator(".injection-issue")).to_have_count(0)
    page.locator("#round-slider").fill("3")
    page.locator("[data-qubit]").first.click()
    page.locator("#inject-error").click()
    page.locator("[data-edit-rounds]").fill("2")
    page.locator("[data-edit-rounds]").press("Tab")
    expect(page.locator(".injection-issue")).to_contain_text("round 3")
    page.locator("#undo").click()
    expect(page.locator(".injection-issue")).to_have_count(0)
    expect(page.locator("#inject-error")).to_be_enabled()
    page.locator("#redo").click()
    page.locator("#compile").click()
    expect(page.locator(".injection-issue")).to_contain_text("round 3")
    expect(page.locator("#syndrome-svg")).to_have_attribute("aria-disabled", "true")
    page.locator("#delete-patch").click()
    expect(page.locator(".injection-issue")).to_contain_text("Unknown patch p0")
    page.locator("#add-patch").click()
    expect(page.locator("#selected-id")).to_have_text("p1")
    page.locator("#compile").click()
    expect(page.locator(".injection-issue")).to_contain_text("Unknown patch p0")
    page.locator("#clear-errors").click()
    expect(page.locator("#syndrome-svg")).to_have_attribute("aria-disabled", "false")
    # A maximal supported experiment can exceed the old 100 KB upload limit.
    project = page.evaluate("JSON.parse(localStorage.getItem('assembly-studio.project.v1'))")
    qubit = page.locator("[data-qubit]").first.get_attribute("data-qubit")
    project["experiment"]["errors"] = [
        {
            "id": f"error_{index:04d}_" + "a" * 100,
            "patch": "p1",
            "qubit": qubit,
            "pauli": "X",
            "before_patch_round": 1,
        }
        for index in range(1024)
    ]
    payload = json.dumps(project).encode()
    assert len(payload) > 100000
    page.locator("#project-file").set_input_files(
        {"name": "large.json", "mimeType": "application/json", "buffer": payload}
    )
    expect(page.locator("#syndrome-errors li")).to_have_count(1024)
    expect(page.locator("#compile-status strong")).to_have_text("Assembly compiled")
    page.locator("#clear-errors").click()


def verify_compiler_geometry(page):
    """Compare SVG vertices and highlighted data support to real plaquettes."""
    page.locator("#load-example").click()
    expect(page.locator("#compile-status strong")).to_have_text("Assembly compiled")
    for distance in [3, 5]:
        for orientation in ["true", "false"]:
            page.locator("#patch-width").select_option(str(distance))
            page.locator("#patch-height").select_option(str(distance))
            page.locator("#patch-orientation").select_option(orientation)
            page.locator("#compile").click()
            expect(page.locator("#compile-status strong")).to_have_text("Assembly compiled")
            mismatches = page.evaluate("""async () => {
                const project = JSON.parse(localStorage.getItem('assembly-studio.project.v1'));
                const compiled = await fetch('/api/compile', {method:'POST',
                    headers:{'Content-Type':'application/json'}, body:JSON.stringify(project)}
                ).then(r => r.json());
                const raw = compiled.patches.ops[0];
                const snapshot = compiled.topology[0];
                const positions = new Map(snapshot.data_qubits.map(q => [q.id, q.position]));
                const qubits = new Map(raw.qubits.map(q => [q.id, q]));
                const canonical = points => points.map(p => p.join(',')).sort().join(';');
                const mismatches = [];
                for (const p of raw.patches[0].plaquettes) {
                    const points = p.coordinates.map(id => qubits.get(id).coordinates);
                    const support = p.coordinates.filter(id => qubits.get(id).type === 'data')
                        .map(id => qubits.get(id).coordinates);
                    const basis = p.colour === 'red' ? 'X' : 'Z';
                    const group = [...document.querySelectorAll('[data-check]')].find(g =>
                        g.classList.contains('basis-' + basis) &&
                        canonical([...g.querySelector('polygon').points].map(p => [p.x, p.y]))
                            === canonical(points));
                    if (!group) { mismatches.push('Missing compiler polygon'); continue; }
                    group.dispatchEvent(new MouseEvent('click', {bubbles:true}));
                    const highlighted = [...document.querySelectorAll('[data-qubit].in-support')]
                        .map(q => positions.get(q.dataset.qubit));
                    if (canonical(highlighted) !== canonical(support))
                        mismatches.push('Incorrect support');
                }
                return mismatches;
            }""")
            assert mismatches == []


def verify_pending_compile(page):
    """An older compile response cannot enable interaction after a newer edit."""
    pending = []

    def hold_response(route):
        pending.append(route)

    page.route("**/api/compile", hold_response)
    page.locator("#patch-width").select_option("3")
    with page.expect_request("**/api/compile"):
        page.locator("#compile").click()
    expect(page.locator("#compile")).to_have_text("Compiling…")
    page.locator("#patch-width").select_option("7")
    assert pending
    route = pending.pop()
    route.fulfill(response=route.fetch())
    expect(page.locator("#compile-status strong")).to_have_text("Uncompiled changes")
    expect(page.locator("#syndrome-svg")).to_have_attribute("aria-disabled", "true")
    expect(page.locator("#inject-error")).to_be_disabled()
    page.unroute("**/api/compile", hold_response)
    page.locator("#compile").click()
    expect(page.locator("#compile-status strong")).to_have_text("Assembly compiled")
    expect(page.locator("#syndrome-svg")).to_have_attribute("aria-disabled", "false")
    # A failed lowering must leave the old topology disabled as well.
    page.locator('[data-move-op="0"][data-direction="1"]').click()
    page.locator("#compile").click()
    expect(page.locator("#compile-status strong")).to_have_text("Assembly needs attention")
    expect(page.locator("#syndrome-svg")).to_have_attribute("aria-disabled", "true")
    page.locator("#undo").click()
    expect(page.locator("#syndrome-svg")).to_have_attribute("aria-disabled", "false")


if __name__ == "__main__":
    main()
