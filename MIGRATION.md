# Migration log — 2026-10-31

**Source repository:** [rickymusu-bit/quiz](https://github.com/rickymusu-bit/quiz)  
**Pinned source snapshot:** [commit 1783ea8](https://github.com/rickymusu-bit/quiz/commit/1783ea86087503e2624fd0c244bf0066095115ff) on a branch containing only 43 reusable tool files.  
**New repository:** [rickymusu-bit/sprites-post](https://github.com/rickymusu-bit/sprites-post)  
**Integration PR:** [#1](https://github.com/rickymusu-bit/sprites-post/pull/1)

## Import and integrity

- The source was cloned at the exact pinned revision, never from a moving branch during the import.
- The 43 regular files, including three binary PNG test fixtures, were imported without alterations; the Git blob SHA is identical between source and destination for **every** file.
- The initial import workflow ran Python unit tests and all four Chromium browser regression scripts **successfully before its commit was pushed**. That one-off import workflow has been removed.
- The reusable GitHub Actions workflow is now `.github/workflows/ci.yml`. Re-run and review its status on the final PR head and again on `main`.
- Browser tests use a creature example as a *test-only fixture*, not a required runtime dependency on Hellscape.
- The game code, canonical art, runtime assets and an extra one-off ImageGen test requiring an unavailable image candidate were not imported.
- Python 3.10+ and Pillow are runtime requirements; Playwright is a test-only dependency.

## Integration back into Hellscape

A separate, intentionally **draft** cleanup PR [rickymusu-bit/quiz #99](https://github.com/rickymusu-bit/quiz/pull/99) removes the duplicated tool from the game repository **only after** this repository is validated in its own `main`. The game's asset/manifests and historical reproduction snapshots are preserved.

Users and other applications may import the tool from a fixed tag/commit, not an implicitly changing `main` branch. The local HTTP editor must be kept bound to loopback. This migration has not introduced a public hosted service or direct ImageGen API dependency.

## Licensing

Public visibility does not grant a reuse license by itself. No open-source license has been selected by this migration; do not claim rights to redistribute the source, documentation, or creature sample artwork without an explicit licensing decision.
