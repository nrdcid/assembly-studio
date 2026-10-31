# (c) Copyright Riverlane 2025-2026. All rights reserved.
"""Exercise the real editor and Deltakit renderer against a running pilot server."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ARTIFACTS = Path(__file__).resolve().parents[1] / "artifacts"


def main() -> None:
    """Verify the complete browser workflow and capture desktop/mobile screenshots."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8010")
    parser.add_argument("--browser", help="Optional path to an existing Chromium executable.")
    args = parser.parse_args()
    ARTIFACTS.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=args.browser,
            args=[
                "--enable-webgl",
                "--use-gl=angle",
                "--use-angle=swiftshader",
                "--enable-unsafe-swiftshader",
            ],
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1050})
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(args.url)
        expect(page.locator("#compile-status strong")).to_have_text("Assembly compiled")
        # Existing browser storage is upgraded in place, using the original key.
        page.evaluate("""() => {
            const key = 'assembly-studio.project.v1';
            const legacy = JSON.parse(localStorage.getItem(key));
            legacy.version = 1;
            delete legacy.experiment;
            localStorage.setItem(key, JSON.stringify(legacy));
        }""")
        page.reload()
        expect(page.locator("#compile-status strong")).to_have_text("Assembly compiled")
        migrated = page.evaluate("JSON.parse(localStorage.getItem('assembly-studio.project.v1'))")
        assert migrated["version"] == 2
        assert migrated["experiment"] == {"errors": []}
        expect(page.locator("#compile-status strong + span")).to_contain_text(
            "Both visualization pipelines verified"
        )
        expect(page.locator("#compile-status .status-dot")).to_have_text("")
        expect(page.frame_locator("#viewer").locator("canvas").first).to_be_visible()
        page.screenshot(path=str(ARTIFACTS / "desktop.png"), full_page=True)

        patch_bounds = page.locator('[data-layout-patch="p0"]').bounding_box()
        assert patch_bounds is not None
        unit = page.locator("#layout").evaluate("svg => svg.getScreenCTM().a * 20")
        x = patch_bounds["x"] + patch_bounds["width"] / 2
        y = patch_bounds["y"] + patch_bounds["height"] / 2
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + unit, y, steps=4)
        page.mouse.up()
        expect(page.locator("#patch-x")).to_have_value("3")
        page.locator("#undo").click()
        expect(page.locator("#patch-x")).to_have_value("2")

        page.locator("#patch-x").fill("6")
        page.locator("#patch-x").press("Tab")
        expect(page.locator("#compile-status strong")).to_have_text("Uncompiled changes")
        expect(page.locator("#viewer-badge")).to_contain_text("PREVIEW OUTDATED")
        expect(page.locator("#round-slider")).to_be_disabled()
        page.locator("#undo").click()
        expect(page.locator("#patch-x")).to_have_value("2")
        page.locator("#redo").click()
        expect(page.locator("#patch-x")).to_have_value("6")
        page.locator("#compile").click()
        expect(page.locator("#compile-status strong")).to_have_text("Assembly compiled")

        page.locator("#tab-patches").click()
        expect(page.frame_locator("#viewer").locator("canvas").first).to_be_visible()
        page.locator("#round-slider").fill("2")
        expect(page.locator("#round-value")).to_have_text("02")
        expect(page.frame_locator("#viewer").locator("canvas").first).to_be_visible()
        page.screenshot(path=str(ARTIFACTS / "surface-code.png"), full_page=True)
        page.locator("#play-rounds").click()
        expect(page.locator("#round-value")).to_have_text("03")
        page.locator("#play-rounds").click()
        expect(page.locator("#play-rounds")).to_have_attribute("aria-label", "Play rounds")

        page.locator("#export-project").click()
        expect(page.locator("#export-dialog")).to_be_visible()
        expect(page.locator("#export-code")).to_contain_text("measure_stabilisers(3)")
        page.locator("#export-mlir-tab").click()
        expect(page.locator("#export-code")).to_contain_text("log_asm.meas_stab<3>")
        with page.expect_download() as download_info:
            page.locator("#download-code").click()
        download_info.value.save_as(str(ARTIFACTS / "export.mlir"))
        page.get_by_role("button", name="Close export").click()

        with page.expect_download() as download_info:
            page.locator("#save-project").click()
        download_info.value.save_as(str(ARTIFACTS / "project.json"))
        saved = json.loads((ARTIFACTS / "project.json").read_text())
        assert saved["patches"][0]["x"] == 6
        assert saved["version"] == 2
        saved["experiment"] = {
            "errors": [
                {
                    "id": "e1",
                    "patch": "p0",
                    "qubit": "p0:d:6.5,2.5",
                    "pauli": "Y",
                    "before_patch_round": 2,
                }
            ]
        }
        (ARTIFACTS / "project.json").write_text(json.dumps(saved))

        page.locator("#add-patch").click()
        expect(page.locator(".patch-item")).to_have_count(2)
        expect(page.locator(".operation-row")).to_have_count(6)
        page.locator("#compile").click()
        expect(page.locator("#compile-status strong")).to_have_text("Assembly compiled")
        expect(page.locator("#round-total")).to_have_text("06")

        page.locator('[data-move-op="0"][data-direction="1"]').click()
        page.locator("#compile").click()
        expect(page.locator("#compile-status strong")).to_have_text("Assembly needs attention")
        expect(page.locator("#compile-status")).to_contain_text("Prepare")
        page.locator("#project-file").set_input_files(str(ARTIFACTS / "project.json"))
        expect(page.locator("#compile-status strong")).to_have_text("Assembly compiled")
        expect(page.locator(".patch-item")).to_have_count(1)
        expect(page.locator("#patch-x")).to_have_value("6")

        page.locator("#patch-name").fill('<img src=x onerror="alert(1)">')
        page.locator("#patch-name").press("Tab")
        assert page.locator("#patch-list img").count() == 0
        page.reload()
        expect(page.locator("#patch-name")).to_have_value('<img src=x onerror="alert(1)">')
        expect(page.locator("#compile-status strong")).to_have_text("Assembly compiled")
        restored = page.evaluate("JSON.parse(localStorage.getItem('assembly-studio.project.v1'))")
        assert restored["experiment"] == saved["experiment"]
        with page.expect_download() as download_info:
            page.locator("#save-project").click()
        download_info.value.save_as(str(ARTIFACTS / "experiment.json"))
        assert (
            json.loads((ARTIFACTS / "experiment.json").read_text())["experiment"]
            == saved["experiment"]
        )

        page.locator("#load-example").click()
        expect(page.locator("#patch-name")).to_have_value("Memory patch")
        expect(page.locator("#compile-status strong")).to_have_text("Assembly compiled")
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(ARTIFACTS / "mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert not errors, errors
        browser.close()
    print("Browser workflow passed; desktop, surface-code, and mobile screenshots captured.")


if __name__ == "__main__":
    main()
