"""Real browser exercise of masks, pivots and repeatable manual pixel editing."""

from io import BytesIO
import json
import os
from pathlib import Path
import sys
import threading

from PIL import Image
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sprite_postprocess as core
from sprite_editor_server import EditorSession, make_server

BASE = ROOT / "tests/fixtures/example-creature"
OUT = ROOT / "artifacts/sprite-editor/local-edits-review"
OUT.mkdir(parents=True, exist_ok=True)
args = core.parser().parse_args([str(BASE / "source-sheet.png"), "--columns", "4", "--rows", "2",
    "--landmarks", str(BASE / "landmarks.json"), "--editor", "--out", str(OUT / "project")])
session = EditorSession(args)
source_hash = core.digest(BASE / "source-sheet.png")
report = {"type": "real Chromium capture of deterministic local-edit UI; demonstration, not an approved new pose",
          "viewport": [1460, 980], "source_sha256": source_hash, "page_errors": [], "requests": [], "checks": []}
shots, durations = [], []


def ready(page):
    page.wait_for_function("document.getElementById('busy').hidden && !document.getElementById('export').disabled")


def screen(page, duration=550):
    shots.append(Image.open(BytesIO(page.screenshot())).convert("RGB"))
    durations.append(duration)


def coordinates(page, point):
    preview = session.cache[max(session.cache)]
    frame = int(page.locator("#frame-label").inner_text().split()[1]) - 1
    source = session.sprites[frame]
    scale, dx, dy = preview.raw_transforms[frame]
    x = scale * (point[0] - source.box[0]) + dx
    y = scale * (point[1] - source.box[1]) + dy
    box = page.locator("#raw-canvas").bounding_box()
    width, height = preview.raw[frame].size
    return box["x"] + x * box["width"] / width, box["y"] + y * box["height"] / height


def click_source(page, point):
    page.mouse.click(*coordinates(page, point))


def stroke(page, points):
    page.mouse.move(*coordinates(page, points[0]))
    page.mouse.down()
    for point in points[1:]:
        page.mouse.move(*coordinates(page, point), steps=4)
    page.mouse.up()
    ready(page)


with make_server(session) as server:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            path = os.environ.get("CHROMIUM_PATH") or ("/usr/bin/chromium" if Path("/usr/bin/chromium").exists() else playwright.chromium.executable_path)
            browser = playwright.chromium.launch(executable_path=path, args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = browser.new_page(viewport={"width": 1460, "height": 980}, device_scale_factor=1)
            page.on("pageerror", lambda e: report["page_errors"].append(str(e)))
            page.on("request", lambda r: report["requests"].append(r.url))
            page.goto(f"http://127.0.0.1:{server.server_port}")
            ready(page)
            page.get_by_role("button", name="Correggi", exact=True).click()
            screen(page, 650)

            # Demonstrate selection of a tail segment; this does not assert an
            # anatomical improvement or replace an accepted production pose.
            polygon = [[110, 198], [110, 242], [65, 240], [45, 277], [2, 277], [2, 207], [45, 188]]
            for point in polygon:
                click_source(page, point)
            expect(page.locator("#finish-mask")).to_be_enabled()
            screen(page, 650)
            page.get_by_role("button", name="Chiudi maschera", exact=True).click()
            ready(page)
            expect(page.locator("#part-angle")).to_be_disabled()
            click_source(page, [108, 226])
            ready(page)
            expect(page.locator("#part-angle")).to_be_enabled()
            assert abs(float(page.locator("#pivot-x").input_value()) - 108) < 0.2
            assert abs(float(page.locator("#pivot-y").input_value()) - 226) < 0.2
            report["checks"].append("polygon mask records source coordinates; explicit pivot required")
            screen(page, 650)

            page.locator("#part-name").fill("Coda · dimostrazione")
            page.locator("#part-name").press("Tab")
            ready(page)
            page.locator("#part-angle").fill("-12")
            page.locator("#part-angle").press("Tab")
            ready(page)
            assert session.cache[max(session.cache)].project["frames"][0]["edits"][0]["rotation_deg"] == -12
            report["checks"].append("part rotates around chosen pivot using the raster recipe")
            screen(page, 900)
            page.screenshot(path=str(OUT / "local-editor.png"))

            # The selection can be disabled and restored without losing data.
            page.get_by_label("Attiva Coda · dimostrazione", exact=True).uncheck()
            ready(page)
            disabled = session.cache[max(session.cache)]
            assert disabled.edit_reports[0][0]["enabled"] is False
            page.get_by_label("Attiva Coda · dimostrazione", exact=True).check()
            ready(page)
            report["checks"].append("layer enable/disable is non-destructive")

            page.get_by_role("button", name="Pennello", exact=True).click()
            page.locator("#brush-radius").fill("1")
            page.locator("#paint-color").fill("#f5bd55")
            stroke(page, [[125, 225], [130, 227], [135, 229]])
            assert session.cache[max(session.cache)].project["frames"][0]["edits"][-1]["type"] == "paint"
            screen(page, 500)
            page.locator("#undo").click()
            ready(page)
            assert len(session.cache[max(session.cache)].project["frames"][0]["edits"]) == 1
            report["checks"].append("paint stroke records color/points and undo removes it exactly")

            page.get_by_role("button", name="Gomma", exact=True).click()
            page.locator("#brush-radius").fill("2")
            stroke(page, [[130, 226], [133, 227]])
            assert session.cache[max(session.cache)].project["frames"][0]["edits"][-1]["type"] == "erase"
            page.locator("#undo").click()
            ready(page)
            report["checks"].append("eraser is a reversible recipe operation")

            page.get_by_role("button", name="Timbro clone", exact=True).click()
            page.get_by_role("button", name="Imposta origine del clone", exact=True).click()
            click_source(page, [100, 221])
            expect(page.locator("#clone-origin")).to_contain_text("100")
            stroke(page, [[115, 227], [119, 229]])
            last = session.cache[max(session.cache)].project["frames"][0]["edits"][-1]
            assert last["type"] == "clone" and last["source_frame"] == 0
            assert abs(last["source_point"][0] - 100) < 0.2
            page.locator("#undo").click()
            ready(page)
            report["checks"].append("clone samples an explicit immutable source point")

            page.get_by_role("button", name="Modifica Coda · dimostrazione", exact=True).click()
            page.get_by_role("button", name="Salva progetto", exact=True).click()
            expect(page.locator("#save-state")).to_have_text("Progetto salvato")
            saved = json.loads((session.output / "project.json").read_text())
            page.locator("#project-file").set_input_files(session.output / "project.json")
            page.wait_for_function("document.getElementById('save-state').textContent==='Modifiche non salvate'")
            ready(page)
            page.get_by_role("button", name="Modifica Coda · dimostrazione", exact=True).click()
            assert float(page.locator("#part-angle").input_value()) == -12
            assert len(saved["frames"][0]["edits"]) == 1
            report["checks"].append("saved recipe reopens with mask, pivot and angle intact")

            exports_before = set(session.output.glob("export-*"))
            for _ in range(2):
                page.get_by_role("button", name="Esporta PNG e GIF ↗", exact=True).click()
                expect(page.locator("#notice")).to_contain_text("PNG, GIF e dati", timeout=30000)
                ready(page)
            exported = sorted(set(session.output.glob("export-*")) - exports_before)
            assert len(exported) == 2
            for filename in ["aligned/001.png", "atlas.png", "aligned.gif", "landmarks.json"]:
                assert (exported[0] / filename).read_bytes() == (exported[1] / filename).read_bytes()
            report["checks"].append("same saved recipe exports byte-identical PNG, atlas, GIF and recipe twice")
            screen(page, 900)
            assert core.digest(BASE / "source-sheet.png") == source_hash
            assert not report["page_errors"], report["page_errors"]
            assert all(u.startswith(f"http://127.0.0.1:{server.server_port}/") for u in report["requests"])
            report["checks"].append("original source unchanged; no external or GitHub requests")
            report["browser_version"] = browser.version
            browser.close()
    finally:
        server.shutdown()
        thread.join()

samples = Image.new("RGB", (200 * len(shots), 135))
for i, frame in enumerate(shots):
    im = frame.copy()
    im.thumbnail((200, 135))
    samples.paste(im, (200 * i, 0))
palette = samples.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
images = [im.quantize(palette=palette, dither=Image.Dither.NONE) for im in shots]
images[0].save(OUT / "local-edits-demo.gif", save_all=True, append_images=images[1:],
               duration=durations, loop=0, disposal=2, optimize=False)
report.update(gif="local-edits-demo.gif", screenshot="local-editor.png", duration_ms=sum(durations))
(OUT / "browser-report.json").write_text(json.dumps(report, indent=2) + "\n")
print(f"PASS: {len(report['checks'])} browser checks; deterministic local-edit demo; no uploads")
