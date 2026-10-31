# Development instructions — Sprite Postprocess

This repository contains a standalone sprite post-processing toolkit, not game logic.

- Keep the original RGBA source image immutable; export derived revisions and record hashes, transforms and provenance.
- Preserve deterministic replay of local edits, masks, crop registration and per-frame anchors.
- Changes that affect extraction/alignment must be covered by unit tests; editor/patch behavior requires browser regression tests.
- Do not invent access to external ImageGen APIs or claim test fixtures are generated artwork.
- Do not require any Hellscape asset or browser runtime for production operation.
- Keep experimental outputs, screenshots and GIFs under ignored `artifacts/`; version source code, meaningful test inputs, docs and canonical fixtures.
- Use versioned docs and PRs for changes; avoid duplicate code paths and avoid merge before the required reviews.
- When the tool is imported into another application, integration details go in that application's documentation, not in this general tool's core rules.
