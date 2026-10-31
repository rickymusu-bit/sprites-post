"""Exercise the local editor on the saved Cerbero sheet and capture its real UI."""

from io import BytesIO
import json
import os
from pathlib import Path
import sys
import threading

from PIL import Image
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sprite_postprocess as core
from sprite_editor_server import EditorSession, make_server

BASE = ROOT / "tests/fixtures/example-creature"
OUT = ROOT / "artifacts/sprite-editor/review"
OUT.mkdir(parents=True, exist_ok=True)
args = core.parser().parse_args([str(BASE / "source-sheet.png"), "--columns", "4", "--rows", "2",
    "--landmarks", str(BASE / "landmarks.json"), "--editor", "--out", str(OUT / "project")])
session = EditorSession(args)
original_hash = core.digest(BASE / "source-sheet.png")
report = {"viewport": [1460, 980], "type": "real Chromium UI capture of local sprite editor",
          "source_sha256": original_hash, "page_errors": [], "requests": [], "checks": []}
frames, durations = [], []


def ready(page):
    page.wait_for_function("document.getElementById('busy').hidden && !document.getElementById('export').disabled")


def capture(page, duration=500):
    frames.append(Image.open(BytesIO(page.screenshot())).convert("RGB"))
    durations.append(duration)


with make_server(session) as server:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            chromium_path = os.environ.get("CHROMIUM_PATH") or ("/usr/bin/chromium" if Path("/usr/bin/chromium").exists() else playwright.chromium.executable_path)
            browser = playwright.chromium.launch(executable_path=chromium_path,
                args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = browser.new_page(viewport={"width": 1460, "height": 980}, device_scale_factor=1)
            page.on("pageerror", lambda e: report["page_errors"].append(str(e)))
            page.on("request", lambda r: report["requests"].append(r.url))
            page.goto(f"http://127.0.0.1:{server.server_port}")
            ready(page)
            expect(page.locator("#timeline button")).to_have_count(8)
            page.get_by_role("button", name="Mostra frame 4", exact=True).click()
            expect(page.locator("#frame-label")).to_have_text("FRAME 04 / 08")
            capture(page, 750)

            # Drag a true landmark using the actual source->staged matrix and
            # current CSS zoom; verify the source-space movement numerically.
            preview = session.cache[max(session.cache)]
            point = session.project["frames"][3]["points"]["shoulder_mass_center"]["xy"]
            source_box = session.sprites[3].box
            _, dx, dy = preview.raw_transforms[3]
            canvas = page.locator("#raw-canvas")
            box = canvas.bounding_box()
            width, height = preview.raw[3].size
            px = point[0] - source_box[0] + dx
            py = point[1] - source_box[1] + dy
            x, y = box["x"] + px * box["width"] / width, box["y"] + py * box["height"] / height
            previous_x = float(page.locator("#point-x").input_value())
            previous_y = float(page.locator("#point-y").input_value())
            page.mouse.move(x, y)
            page.mouse.down()
            page.mouse.move(x + 10, y - 7, steps=5)
            page.mouse.up()
            ready(page)
            changed_x = float(page.locator("#point-x").input_value())
            changed_y = float(page.locator("#point-y").input_value())
            assert abs(changed_x - previous_x - 10 * width / box["width"]) < 0.2
            assert abs(changed_y - previous_y + 7 * height / box["height"]) < 0.2
            report["checks"].append("pointer drag respects source coordinates and CSS zoom")
            capture(page, 650)

            page.get_by_role("button", name="↶ Annulla", exact=True).click()
            ready(page)
            assert float(page.locator("#point-x").input_value()) == previous_x
            page.locator("#redo").click()
            ready(page)
            assert float(page.locator("#point-x").input_value()) == changed_x
            page.locator("#undo").click()
            ready(page)
            report["checks"].append("undo and redo restore exact annotations")

            # A zoomed, scrolled canvas must use the same source coordinates.
            page.locator("#zoom").fill("150")
            page.locator("#zoom").dispatch_event("input")
            expect(page.locator("#zoom-value")).to_have_text("150%")
            preview = session.cache[max(session.cache)]
            _, dx, dy = preview.raw_transforms[3]
            px, py = point[0] - source_box[0] + dx, point[1] - source_box[1] + dy
            page.locator("#raw-viewport").evaluate("(view,p)=>{view.scrollLeft=p[0]*1.5-view.clientWidth/2;view.scrollTop=p[1]*1.5-view.clientHeight/2}", [px, py])
            box = canvas.bounding_box()
            x, y = box["x"] + px * 1.5, box["y"] + py * 1.5
            page.mouse.move(x, y)
            page.mouse.down()
            page.mouse.move(x + 12, y + 9, steps=4)
            page.mouse.up()
            ready(page)
            assert abs(float(page.locator("#point-x").input_value()) - previous_x - 8) < 0.2
            assert abs(float(page.locator("#point-y").input_value()) - previous_y - 6) < 0.2
            page.locator("#undo").click()
            ready(page)
            page.get_by_role("button", name="Adatta", exact=True).click()
            report["checks"].append("drag at 150 percent zoom after scrolling remains accurate")

            page.get_by_role("button", name="Sovrapposti", exact=True).click()
            page.get_by_label("Onion skin", exact=True).check()
            page.locator("#opacity").fill("0.45")
            page.locator("#opacity").dispatch_event("input")
            expect(page.locator("#opacity-value")).to_have_text("45%")
            capture(page, 650)
            report["checks"].append("before/after overlay and configurable onion skin")

            page.get_by_role("button", name="Salva progetto", exact=True).click()
            expect(page.locator("#save-state")).to_have_text("Progetto salvato")
            saved = json.loads((session.output / "project.json").read_text())
            assert saved["frames"][3]["points"]["shoulder_mass_center"]["xy"] == point
            page.locator("#project-file").set_input_files(session.output / "project.json")
            ready(page)
            assert float(page.locator("#point-x").input_value()) == previous_x
            report["checks"].append("saved project reloads without coordinate drift")

            # Stale annotations must be rejected without replacing the project.
            stale = dict(saved, source_sha256="different-source")
            stale_file = OUT / "wrong-source.json"
            stale_file.write_text(json.dumps(stale))
            page.locator("#project-file").set_input_files(stale_file)
            expect(page.locator("#error")).to_contain_text("un'altra immagine")
            assert float(page.locator("#point-x").input_value()) == previous_x
            report["checks"].append("wrong-source project rejected in UI")
            page.get_by_role("button", name="Salva progetto", exact=True).click()
            expect(page.locator("#error")).to_be_hidden()

            page.get_by_role("button", name="Esporta PNG e GIF ↗", exact=True).click()
            expect(page.locator("#notice")).to_contain_text("PNG, GIF e dati", timeout=30000)
            exports = sorted(session.output.glob("export-*"))
            assert exports
            export_manifest = json.loads((exports[-1] / "manifest.json").read_text())
            assert export_manifest["source_sha256"] == original_hash
            report["checks"].append("PNG/GIF export completes locally with source hash")

            page.locator("#next").click()
            expect(page.locator("#frame-label")).to_have_text("FRAME 05 / 08")
            page.keyboard.press("ArrowLeft")
            expect(page.locator("#frame-label")).to_have_text("FRAME 04 / 08")
            page.get_by_role("button", name="Affiancati", exact=True).click()
            page.get_by_label("Onion skin", exact=True).uncheck()
            page.get_by_role("button", name="Mostra frame 1", exact=True).click()
            page.clock.install()
            page.clock.pause_at(page.evaluate("Date.now()+100"))
            page.get_by_role("button", name="Riproduci animazione", exact=True).click()
            for i in range(16):
                assert page.locator("#frame-label").inner_text() == f"FRAME {i % 8 + 1:02d} / 08"
                capture(page, 100)
                page.clock.run_for(100)
            page.get_by_role("button", name="Ferma animazione", exact=True).click()
            report["checks"].append("playback preserves 100ms poses and wraps 8 to 1")
            page.get_by_role("button", name="Mostra frame 4", exact=True).click()
            page.get_by_label("Onion skin", exact=True).check()
            capture(page, 900)
            page.screenshot(path=str(OUT / "editor.png"))
            report["browser_version"] = browser.version
            assert not report["page_errors"], report["page_errors"]
            assert all(url.startswith(f"http://127.0.0.1:{server.server_port}/") for url in report["requests"])
            assert core.digest(BASE / "source-sheet.png") == original_hash
            report["checks"].append("source unchanged; no external requests or GitHub uploads")
            browser.close()
    finally:
        server.shutdown()
        thread.join()

# Only encode screenshots that were actually acquired from Chromium.
samples = Image.new("RGB", (200 * len(frames), 130))
for i, frame in enumerate(frames):
    image = frame.copy()
    image.thumbnail((200, 130))
    samples.paste(image, (200 * i, 0))
palette = samples.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
converted = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
converted[0].save(OUT / "editor-demo.gif", save_all=True, append_images=converted[1:],
                  duration=durations, loop=0, disposal=2, optimize=False)
report.update(gif="editor-demo.gif", duration_ms=sum(durations), screenshot="editor.png")
(OUT / "browser-report.json").write_text(json.dumps(report, indent=2) + "\n")
print(f"PASS: {len(report['checks'])} browser checks, actual editor GIF ({sum(durations)} ms), no uploads")
