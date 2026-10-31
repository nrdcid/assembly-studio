# (c) Copyright Riverlane 2025-2026. All rights reserved.
"""Exercise the interactive syndrome view against actual compiler output."""

import argparse
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
        page.screenshot(path=str(artifact / "syndrome-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(artifact / "syndrome-mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not errors, errors
        browser.close()


if __name__ == "__main__":
    main()
