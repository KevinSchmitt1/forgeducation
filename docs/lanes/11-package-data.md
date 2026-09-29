# Lane 11 — Package data: make a wheel install work (CODE, touches a hot directory)

**Branch:** `fix/package-data` · **Type:** code + packaging · **Depends on:** Lane 8 merged (#63)
**Status:** not started. Small. **Serialize:** cannot run while any lane edits `personas/`.
**Process:** see "Lane workflow" in root `CLAUDE.md`.

## Why this lane exists
Found while building Lane 8: after the package-list fix in #63, a **non-editable** install
(`pip install .`, a wheel) imports every `forged.*` module, but `cli.DEFAULT_PERSONAS` /
`DEFAULT_CONFIG` resolve to `site-packages/personas` and `site-packages/config`, which do not exist —
the bundled personas, pipeline configs and templates live at the repo root, outside the package, and
`cli.PACKAGE_ROOT` is computed as "the directory above `forged/`". Only editable installs work, so
the Dockerfile installs editable as a workaround, and "bundled defaults ship with the package" (the
`cli.py` docstring) is false for a wheel.

## Scope
1. Pick and justify one approach (write the choice in the PR):
   - **(a)** move `personas/`, `config/` (and `templates/`?) under `forged/` as package data
     (`[tool.setuptools.package-data]`), resolve them via `importlib.resources`; or
   - **(b)** keep the repo layout and ship them as data files with a resolver that finds them in
     both layouts. (a) is the conventional fix; (b) avoids moving a hot directory.
2. Update every path consumer (`cli.PACKAGE_ROOT`/`DEFAULT_*`, `forged.service`, tests that point
   at `personas/`, docs that cite `personas/*.md` paths — CLAUDE.md, README, `docs/lanes/*`).
3. Switch the `Dockerfile` to a non-editable install once it works.

## Files you own
`pyproject.toml`, `forged/cli.py` (path constants only), the moved directories (if (a)), path
references in tests/docs, `Dockerfile`. **Hot-directory rule:** if (a), no persona lane may be in
flight — coordinate with whoever owns `personas/` next.

## Human checkpoints
Post each with `scripts/checkpoint.py` and end the turn (CLAUDE.md → "Human checkpoints").
- **CP0 kickoff:** approach (a) move under `forged/` vs (b) resolver over the repo layout — with a
  recommendation and what each moves; the user picks. (a) freezes persona lanes while in flight.
- **CP1 demo:** commands to build a wheel into a fresh temp venv and run `forged ui --fake-llm` from
  outside the repo (and the Docker image, if the daemon is up).
- **CP2 merge:** review packet (standard contents).
- **SPEND:** none — this lane makes no billable calls.

## Verification
- A test that builds a wheel into a temp venv and runs `python -m forged.cli ui --help` **and** a
  fake-LLM plan (`forged.service.ForgeService(llm_factory=FakeLLM)`) from outside the repo — proves
  the personas are found from `site-packages`. Mark it `integration`; keep it < 60 s.
- Docker: image builds with a non-editable install and serves `forged ui --fake-llm`.
- Three CI gates green; *exercised* rung.

## Done means
`pip install .` in a fresh venv → `forged ui --fake-llm` plans successfully from any cwd; Docker no
longer needs `-e`; PR opened.

## Checkpoint log
<!-- one line per answered checkpoint: YYYY-MM-DD · CPn · the user's decision -->
