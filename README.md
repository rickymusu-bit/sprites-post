# Sprite Postprocess — editor, alignment, masked repairs

A reusable **local-first** toolkit for extracting frames from spritesheets, aligning them using body landmarks, reviewing animation with onion skin and loops, and applying deterministic edits and externally generated masked image repairs. It is **not coupled to any game engine** and does not call image generation services itself.

**Status:** standalone-source migration snapshot from [Hellscape](https://github.com/rickymusu-bit/quiz), 31 October 2026. The tools already exist and have been tested in their original project; the relocated repository's CI must be rerun after import. This branch does **not** create the destination GitHub repository.

## Requirements

- Python 3.10 or later.
- Pillow 11.3.0 for the core tool and local visual editor.
- Optional: Playwright/Chromium for browser regression tests, not for normal operation.
- No mandatory Node.js runtime, hosted service, ImageGen API or network connection.

Install dependencies:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## CLI — export diagnostic frames

```bash
python3 scripts/sprite_postprocess.py input.png \
  --columns 4 --rows 2 \
  --out artifacts/alignment-001
```

Start the **local visual editor** with:

```bash
python3 scripts/sprite_postprocess.py input.png \
  --columns 4 --rows 2 \
  --editor --out artifacts/editor-001
```

Open the `http://127.0.0.1:<port>` address printed in the terminal. Bind locally; do not expose the editing server to the Internet. Check `--help` for extraction, landmark, alignment, masking and patch operations.

## Local repairs and external generation

Original PNGs are immutable inputs. A mask describes the **only pixels that may change**, and a larger crop supplies context. Export a repair request, edit the crop externally (e.g. with an image generator or illustrator), import the candidate, validate the transformed anchors and keep RGBA pixels **outside** the mask unchanged. Inspect neighboring frames; a technical pass is not visual approval.

Read the versioned usage manuals:

- [CLI and alignment](docs/SPRITE_POSTPROCESS_v1.0.0_20261030.md)
- [Editor](docs/SPRITE_EDITOR_v1.2.0_20261031.md)
- [Masked-patch workflow](docs/SPRITE_LOCAL_PATCHES_v1.1.0_20261031.md)
- [Patch validation audit](docs/SPRITE_LOCAL_PATCH_AUDIT_v1.1.0_20261031.md)

The historical document examples may depict an asset from the original Hellscape project; they are examples **only**, not dependencies or default behaviors. The core scripts and UI do not require Hellscape at runtime.

## Tests

```bash
pip install -r requirements-test.txt
python3 -m unittest discover -s tests -p 'test_sprite*.py' -v
python3 -m playwright install chromium
python3 tests/sprite_editor_browser.py
python3 tests/sprite_local_edits_browser.py
python3 tests/sprite_patches_browser.py
python3 tests/sprite_patch_workflow_browser.py
```

The browser tests use a **test-only legacy image fixture**, relocated under `tests/fixtures/example-creature`, never part of the runtime release. Unit tests create synthetic sheets. An older one-off browser test tied to a specific unreleased ImageGen candidate was **not transferred**.

## Repository separation

Only production code, generic documents, automated tests and small regression fixtures belong here. Game logic, vehicle/demon code, assets used by Hellscape runtime, and Hellscape-specific release requirements stay in their own repository.

- A change to this tool should be reviewed and tested here first.
- Consumers may use a pinned release/commit, install a package, or vendor an explicitly versioned copy.
- Before deleting the original scripts from a consumer repository, verify that all source references, tests, CI paths and historical reproduction recipes remain valid; never delete canonical source artwork or historical evidence with the tool.
- Keep a source-to-destination hash manifest during migration.

## License and provenance

The original code was in a public repository but **no separate license was added by this migration**. Select a license explicitly before advertising third-party redistribution permissions. The example-creature images are regression inputs derived from the existing public project and are not offered as a separate asset library.
