# Migration log — 2026-10-31

**Origin:** `rickymusu-bit/quiz`, commit `a0efe419c1c045c7f5f3c990fd1c6137e0576869`. **Destination proposed:** `rickymusu-bit/sprite-postprocess` (not created by this staging branch).

- Source Python scripts, editor HTML/CSS/JS and test implementations were copied from the origin repository by their Git blob identity.
- The four Chromium regression tests replace only the path to a test-only fixture (`assets/hell-race/production/cerbero/run-stabilized-v1` → `tests/fixtures/example-creature`). The fixture retains the exact original image and landmark bytes.
- The game, original asset production directories, historical reports and one-off tests requiring an unavailable generated candidate are deliberately not included.
- `requirements-test.txt` is preserved; `requirements.txt`, `.gitignore`, `AGENTS.md`, `README.md` and dedicated CI are new.
- All copied source blobs must be verified after import. The standalone branch is a **staging snapshot**, not evidence of a separate GitHub repository or of successful independent CI.
- Do not delete the source tool from Hellscape until a new repository exists, tests pass in that repository, and integration references are migrated.
