"""Bounded Chromium PDF-to-PNG worker used only as a subprocess by receipt_refresh."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

MAX_PAGES = 12
VIEW_WIDTH = 1200
MAX_HEIGHT = 8000


def main() -> int:
    if len(sys.argv) not in (3, 4):
        return 2
    source, output = Path(sys.argv[1]), Path(sys.argv[2])
    executable = sys.argv[3] if len(sys.argv) == 4 else None
    if not source.is_file() or not source.read_bytes()[:5] == b"%PDF-":
        return 2
    output.mkdir(parents=True, exist_ok=False)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return 3
    paths: list[str] = []
    with sync_playwright() as playwright:
        browser = (
            playwright.chromium.launch(
                headless=True, chromium_sandbox=True, executable_path=executable
            )
            if executable is not None
            else playwright.chromium.launch(
                headless=True, chromium_sandbox=True, channel="chromium"
            )
        )
        context = browser.new_context(
            viewport={"width": VIEW_WIDTH, "height": 1800}, device_scale_factor=1
        )
        context.route("http://**/*", lambda route: route.abort())
        context.route("https://**/*", lambda route: route.abort())
        page = context.new_page()
        page.goto(source.resolve().as_uri() + "#toolbar=0&navpanes=0&view=FitH", wait_until="load")
        viewer = None
        dimensions = None
        for _ in range(60):
            frames = [frame for frame in page.frames if frame.locator("pdf-viewer").count()]
            if frames:
                viewer = frames[0].locator("pdf-viewer")
                dimensions = viewer.evaluate("el => el.documentDimensions")
                if dimensions:
                    break
            page.wait_for_timeout(200)
        if viewer is None or not isinstance(dimensions, dict):
            browser.close()
            return 4
        page_dimensions = dimensions.get("pageDimensions")
        if not isinstance(page_dimensions, list) or not 1 <= len(page_dimensions) <= MAX_PAGES:
            browser.close()
            return 5
        for number, dimension in enumerate(page_dimensions):
            width = dimension.get("width")
            height = dimension.get("height")
            if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
                return 5
            viewport_height = math.ceil(VIEW_WIDTH * height / width) + 50
            if width <= 0 or height <= 0 or viewport_height > MAX_HEIGHT:
                return 5
            page.set_viewport_size({"width": VIEW_WIDTH, "height": max(1000, viewport_height)})
            viewer.evaluate(
                "(el, n) => {el.viewport_.fitToWidth(); el.viewport_.goToPage(n)}", number
            )
            page.wait_for_timeout(400)
            rect = viewer.evaluate("(el, n) => el.viewport_.getPageScreenRect(n)", number)
            if rect["y"] < 0 or rect["y"] + rect["height"] > max(1000, viewport_height):
                return 5
            target = output / f"page-{number + 1}.png"
            page.screenshot(path=str(target), clip=rect)
            paths.append(target.name)
        browser.close()
    print(json.dumps({"pages": paths}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
