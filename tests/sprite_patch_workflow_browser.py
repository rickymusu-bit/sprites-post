"""Actual browser round trip: prepare/upload/native landmarks/review/restore.

Candidate and approval evidence are explicitly synthetic UI fixtures, not an
ImageGen output or an artistic acceptance of any production asset.
"""
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import zipfile

from PIL import Image
from playwright.sync_api import expect, sync_playwright
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sprite_postprocess as core
from sprite_editor_server import EditorSession, make_server
from sprite_patches.materials import dump

BASE = ROOT / "tests/fixtures/example-creature"
OUT = ROOT / "artifacts/sprite-editor/patch-browser-v1.1/synthetic-ui"
OUT.mkdir(parents=True, exist_ok=True)
work = OUT / "work"
if work.exists():
    shutil.rmtree(work)
args = core.parser().parse_args([str(BASE / "source-sheet.png"), "--columns", "4", "--rows", "2",
    "--landmarks", str(BASE / "landmarks.json"), "--out", str(work)])
session = EditorSession(args)
source_hash = core.digest(BASE / "source-sheet.png")
report = {"type": "real browser recording with SYNTHETIC candidate and review declarations; not ImageGen or artistic approval",
    "viewport": [1460, 980], "checks": [], "errors": [], "requests": []}
shots, durations = [], []


def ready(page):
    page.wait_for_function("document.getElementById('busy').hidden && !document.getElementById('export').disabled")


def idle(page):
    page.wait_for_function("!document.getElementById('patch-dialog').hasAttribute('aria-busy')")


def screen(page, duration=650):
    shots.append(Image.open(BytesIO(page.screenshot())).convert("RGB"))
    durations.append(duration)


def source_click(page, point):
    preview = session.cache[max(session.cache)]
    s, dx, dy = preview.raw_transforms[0]
    sprite = session.sprites[0]
    canvas = page.locator("#raw-canvas").bounding_box()
    x, y = s*(point[0]-sprite.box[0])+dx, s*(point[1]-sprite.box[1])+dy
    page.mouse.click(canvas["x"]+x*canvas["width"]/preview.raw[0].width, canvas["y"]+y*canvas["height"]/preview.raw[0].height)


def native_click(page, identifier, point):
    canvas = page.locator("#" + identifier)
    canvas.evaluate("(canvas,p)=>{const parent=canvas.parentElement;parent.scrollLeft=Math.max(0,p[0]*canvas.clientWidth/canvas.width-parent.clientWidth/2);parent.scrollTop=Math.max(0,p[1]*canvas.clientHeight/canvas.height-parent.clientHeight/2);}", point)
    box = canvas.bounding_box()
    size = canvas.evaluate("c=>[c.width,c.height]")
    page.mouse.click(box["x"] + point[0]*box["width"]/size[0], box["y"] + point[1]*box["height"]/size[1])


with make_server(session) as server:
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        with sync_playwright() as playwright:
            executable = os.environ.get("CHROMIUM_PATH") or ("/usr/bin/chromium" if Path("/usr/bin/chromium").exists() else playwright.chromium.executable_path)
            browser = playwright.chromium.launch(executable_path=executable, args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = browser.new_page(viewport={"width":1460,"height":980},device_scale_factor=1)
            page.on("pageerror",lambda e:report["errors"].append(str(e)))
            page.on("request",lambda r:report["requests"].append(r.url))
            page.goto(f"http://127.0.0.1:{server.server_port}"); ready(page)
            page.locator("#local-mode").click()
            for p in [[40,223],[70,213],[80,224],[50,238]]:
                source_click(page,p)
            page.locator("#finish-mask").click(); ready(page)
            page.locator("#patch-open").click(); idle(page)
            expect(page.locator("#patch-selection")).to_contain_text("Frame 1")
            for key,value in {"subject":"Cerbero · TEST DI INTERFACCIA", "defect":"Fixture sintetica per test del flusso, non difetto di produzione",
                "correction":"Un solo dettaglio sintetico di calibrazione", "geometry":"Posizioni e proporzioni fisse", "connections":"Tutti gli attacchi restano fissi",
                "preserve":"Tutti i pixel esterni, palette, luce, materiali e anatomia"}.items():
                page.locator("#patch-"+key).fill(value)
            page.locator("#patch-error-type").select_option("position")
            expect(page.locator("#patch-prepare")).to_be_disabled()
            page.locator("#patch-error-type").select_option("missing_detail")
            page.locator("#patch-compose").click()
            page.locator("#patch-prepare").click(); idle(page)
            expect(page.locator("#patch-error")).to_contain_text("Conferma")
            page.locator("#patch-references-approved").check()
            screen(page)
            page.locator("#patch-prepare").click(); idle(page)
            expect(page.locator("#patch-import-panel")).to_be_visible()
            request_id = page.locator("#patch-request").input_value()
            request_folder = work / "patches" / request_id
            request = json.loads((request_folder/"request.json").read_text())
            response = page.request.get(f"http://127.0.0.1:{server.server_port}" + page.locator("#patch-download").get_attribute("href"))
            assert response.ok
            with zipfile.ZipFile(BytesIO(response.body())) as bundle:
                assert bundle.read("prompt.txt").decode() == request["specification"]["prompt"]
                assert "mask-crop.png" in bundle.namelist()
            report["checks"].append("browser prepares sealed request and exact prompt; classification and reference confirmation enforced; ZIP downloads")
            original = Image.open(request_folder/"context.png").convert("RGBA")
            candidate = original.resize((original.width*3,original.height*3),Image.Resampling.NEAREST)
            candidate = Image.alpha_composite(candidate,Image.new("RGBA",candidate.size,(255,150,40,100)))
            candidate.save(OUT/"SYNTHETIC-candidate.png")
            page.locator("#patch-candidate").set_input_files(str(OUT/"SYNTHETIC-candidate.png")); idle(page)
            page.locator("#patch-preview").click(); idle(page)
            expect(page.locator("#patch-error")).to_contain_text("Dimensioni")
            expect(page.locator("#patch-apply")).to_be_disabled()
            page.locator("#patch-mapping").select_option("fit")
            for target in ([20,20],[original.width-20,20],[20,original.height-20]):
                native_click(page,"patch-target-canvas",target)
                native_click(page,"patch-generated-canvas",[3*v for v in target])
            assert page.locator(".patch-point-row").count()==3
            page.locator("#patch-allow-scale").check()
            page.locator("#patch-preview").click(); idle(page)
            expect(page.locator("#patch-transform")).to_contain_text("0 pixel modificati fuori maschera")
            expect(page.locator("#patch-apply")).to_be_enabled()
            page.screenshot(path=str(OUT/"mapping.png"));screen(page,1000)
            report["checks"].append("different-size output blocked until explicit mapping; three native landmark pairs survive zoom and scrolling; preview preserves outside pixels")
            page.locator("#patch-service").fill("SYNTHETIC UI TEST; not ImageGen")
            page.locator("#patch-provenance").fill("Pillow fixture for interface regression only")
            page.locator("#patch-prompt-confirmed").check()
            for name in ["original-frame.png","context.png"]+[r["file"] for r in request["references"]]:
                page.locator(f'#patch-supplied-files input[value="{name}"]').check()
            page.locator("#patch-apply").click(); idle(page); ready(page)
            expect(page.locator("#patch-review-status")).to_contain_text("Da verificare")
            attempt_id=page.locator("#patch-attempt").input_value(); attempt_folder=work/"patches"/attempt_id
            pixels=json.loads((attempt_folder/"verification.json").read_text())
            assert pixels["outside_mask_changed_pixels"]==0
            assert pixels["inside_mask_changed_pixels"]>0
            report["checks"].append("candidate imported through shared recipe; generated PNG, transform, native frame and diagnostics retained")
            page.locator("#patch-reviewer").fill("SYNTHETIC UI TEST")
            page.locator("#patch-review-notes").fill("State transition test only; not artistic acceptance")
            page.locator("#patch-approve").click(); idle(page)
            expect(page.locator("#patch-error")).to_contain_text("controlli")
            for box in page.locator("#patch-review-checks input").all(): box.check()
            page.locator("#patch-review-evidence").fill("Synthetic browser fixture: declarations exercise the form, not production quality")
            page.locator("#patch-approve").click(); idle(page)
            expect(page.locator("#patch-review-status")).to_contain_text("Approvata")
            screen(page)
            page.locator("#patch-close").click()
            expect(page.locator("#edit-list")).to_contain_text("approvata")
            page.locator("#save-project").click()
            page.wait_for_function("document.getElementById('notice').textContent.includes('Salvato localmente')")
            page.reload();ready(page)
            page.locator("#local-mode").click()
            expect(page.locator("#edit-list")).to_contain_text("approvata")
            report["checks"].append("approval requires all visual declarations and evidence; bound status survives reload without changing source or candidate")
            page.locator("#patch-open").click();idle(page)
            page.locator("#patch-tab-review").click()
            page.locator("#patch-reviewer").fill("SYNTHETIC UI TEST")
            page.locator("#patch-review-notes").fill("Test rejection and exact restoration")
            page.locator("#patch-reject").click();idle(page);ready(page)
            expect(page.locator("#patch-review-status")).to_contain_text("Scartata")
            assert (attempt_folder/"review-001.json").exists() and (attempt_folder/"review-002.json").exists()
            assert (attempt_folder/"generated.png").exists()
            restored=session.cache[max(session.cache)].project
            assert restored["frames"][0]["edits"]==json.loads((request_folder/"project.json").read_text())["frames"][0]["edits"]
            report["checks"].append("rejection restores exact predecessor recipe; candidate and both decisions remain archived")
            page.locator("#patch-close").click();screen(page)
            page.locator("#play").click()
            for _ in range(8): page.wait_for_timeout(110);screen(page,110)
            page.locator("#play").click()
            assert not report["errors"],report["errors"]
            assert all(url.startswith((f"http://127.0.0.1:{server.server_port}/","data:")) for url in report["requests"])
            assert core.digest(BASE/"source-sheet.png")==source_hash
            report["checks"].append("real clock-driven browser animation; no external requests/errors; approved source unchanged")
            browser.close()
    finally:
        server.shutdown();thread.join()
report["duration_ms"]=sum(durations)
shots[0].save(OUT/"browser-demo.gif",save_all=True,append_images=shots[1:],duration=durations,loop=0)
dump(OUT/"browser-report.json",report)
print(json.dumps({"checks":len(report["checks"]),"duration_ms":report["duration_ms"]}))
