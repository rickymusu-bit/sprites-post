"""Real browser capture: imported masked fixture through existing editor.

The candidate is deliberately synthetic, NOT ImageGen or an approved correction.
"""
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import sys
import threading

from PIL import Image
from playwright.sync_api import sync_playwright, expect
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sprite_postprocess as core
from sprite_editor_server import EditorSession, make_server
from sprite_patches.materials import prepare, dump
from sprite_patches.workflow import import_candidate

BASE = ROOT / "tests/fixtures/example-creature"
OUT = ROOT / "artifacts/sprite-editor/patch-review"
OUT.mkdir(parents=True, exist_ok=True)
work = OUT / "work"
if work.exists():
    shutil.rmtree(work)
work.mkdir()
args = core.parser().parse_args([str(BASE / "source-sheet.png"), "--columns", "4", "--rows", "2",
    "--landmarks", str(BASE / "landmarks.json"), "--editor", "--out", str(work / "editor")])
session = EditorSession(args)
original_hash = core.digest(BASE / "source-sheet.png")
request = work / "patch-001"
spec = {"frame": 1, "error_type": "missing_detail", "defect": "TECHNICAL FIXTURE, not a diagnosed production defect",
    "subject": "Cerbero: technical demonstration only", "correction": "Synthetic orange calibration stroke on tail",
    "geometry": "Fixed source coordinates", "connections": "Unchanged", "preserve": "Every pixel outside mask",
    "prompt": "SYNTHETIC TEST ONLY. No ImageGen request made. Candidate contains deliberate color changes outside mask.",
    "mask_polygon": [[40, 223], [70, 213], [80, 224], [50, 238]], "context_padding": 30,
    "references": [{"path": str(BASE / "references/original-A.png"), "revision": "4876d1a066f31453e844a8932cb12d94529db2ae",
        "role": "Existing approved reference; not sent to any generator in this fixture", "approved": True}]}
# Resolve canonical filenames from the checked-in source fascicle.
if not Path(spec["references"][0]["path"]).exists():
    refs = sorted((BASE / "references").glob("*.png"))
    spec["references"][0]["path"] = str(refs[0])
prepare(session, session.project, spec, request, ROOT)
crop = Image.open(request / "context.png").convert("RGBA")
# Corrupt ALL context deliberately: the saved final frame must remain masked.
overlay = Image.new("RGBA", crop.size, (255, 170, 40, 160))
candidate = Image.alpha_composite(crop, overlay)
candidate.save(work / "simulated-external.png")
dump(work / "generation.json", {"service": "SYNTHETIC TEST FIXTURE; NOT ImageGen", "output_provenance": "Pillow test-only calibration overlay",
    "prompt_confirmed_exact": True, "supplied_files": ["original-frame.png", "context.png", "references/001.png"]})
attempt = import_candidate(request, work / "simulated-external.png", generation_path=work / "generation.json")
project = json.loads((attempt / "project-patched.json").read_text())
project["frames"][0]["edits"][-1]["name"] = "TEST esterno · solo maschera"
fixture_project = work / "fixture-project.json"
dump(fixture_project, project)
report = {"type": "real browser recording of masked import fixture; NOT generated content or an approved pose",
    "viewport": [1460, 980], "source_sha256": original_hash, "page_errors": [], "requests": [], "checks": []}
shots, durations = [], []


def ready(page):
    page.wait_for_function("document.getElementById('busy').hidden && !document.getElementById('export').disabled")


def screen(page, duration=600):
    shots.append(Image.open(BytesIO(page.screenshot())).convert("RGB"))
    durations.append(duration)


with make_server(session) as server:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            executable = os.environ.get("CHROMIUM_PATH") or ("/usr/bin/chromium" if Path("/usr/bin/chromium").exists() else playwright.chromium.executable_path)
            browser = playwright.chromium.launch(executable_path=executable, args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = browser.new_page(viewport={"width": 1460, "height": 980}, device_scale_factor=1)
            page.on("pageerror", lambda e: report["page_errors"].append(str(e)))
            page.on("request", lambda r: report["requests"].append(r.url))
            page.goto(f"http://127.0.0.1:{server.server_port}")
            ready(page)
            screen(page)
            page.locator("#project-file").set_input_files(str(fixture_project))
            ready(page)
            page.get_by_role("button", name="Correggi", exact=True).click()
            page.get_by_role("button", name="Modifica TEST esterno · solo maschera", exact=True).click()
            ready(page)
            expect(page.locator("#local-help")).to_contain_text("Correzione esterna mascherata")
            screen(page, 1000)
            page.screenshot(path=str(OUT / "browser.png"))
            preview = session.cache[max(session.cache)]
            expected = Image.open(attempt / "diagnostics/aligned/001.png").convert("RGBA")
            assert preview.aligned[0].tobytes() == expected.tobytes()
            report["checks"].append("external correction loaded as shared recipe; browser preview equals CLI pixels")
            page.get_by_label("Attiva TEST esterno · solo maschera", exact=True).uncheck()
            ready(page)
            original_preview = session.compute(session.project)
            assert session.cache[max(session.cache)].aligned[0].tobytes() == original_preview.aligned[0].tobytes()
            screen(page, 800)
            page.get_by_label("Attiva TEST esterno · solo maschera", exact=True).check()
            ready(page)
            screen(page, 800)
            report["checks"].append("disable restores pre-patch frame; re-enable restores exact correction")
            # Real clock-driven animation at the preserved per-frame duration.
            page.locator("#play").click()
            for _ in range(8):
                page.wait_for_timeout(110)
                screen(page, 110)
            page.locator("#play").click()
            report["checks"].append("animation plays through real browser clock; diagnostic only")
            before = set((work / "editor").glob("export-*"))
            page.locator("#export").click()
            ready(page)
            page.wait_for_function("document.getElementById('notice').textContent.includes('PNG, GIF')")
            after = set((work / "editor").glob("export-*"))
            exported = (after - before).pop()
            assert core.digest(exported / "aligned/001.png") == core.digest(attempt / "diagnostics/aligned/001.png")
            report["checks"].append("browser export matches same CLI import PNG byte for byte")
            assert not report["page_errors"], report["page_errors"]
            assert all(url.startswith(f"http://127.0.0.1:{server.server_port}/") for url in report["requests"])
            report["checks"].append("no external requests or JavaScript errors")
            browser.close()
    finally:
        server.shutdown()
        thread.join()
assert core.digest(BASE / "source-sheet.png") == original_hash
report["checks"].append("approved source file unchanged")
report["pixel_verification"] = json.loads((attempt / "verification.json").read_text())
report["duration_ms"] = sum(durations)
shots[0].save(OUT / "browser-demo.gif", save_all=True, append_images=shots[1:], duration=durations, loop=0)
shutil.copyfile(attempt / "before-after.png", OUT / "before-after.png")
shutil.copyfile(attempt / "diagnostics/aligned.gif", OUT / "diagnostic-fixture.gif")
dump(OUT / "browser-report.json", report)
print(json.dumps({"checks": len(report["checks"]), "gif": str(OUT / "browser-demo.gif"), "duration_ms": report["duration_ms"]}))
