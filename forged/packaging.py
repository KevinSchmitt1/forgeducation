"""Turn a finished run directory into a self-contained, learner-facing deliverable.

A run used to ship ``lesson.ipynb`` + ``SUMMARY.md`` and nothing else actionable: no
dependency manifest and no guide for the learner the lesson is *for* (SUMMARY.md is a
pipeline status report). See docs/architecture/10-output-quality-remediation.md, P6.

write_package() fixes that. From the lesson plan it materializes, deterministically:
  - ``requirements.txt`` — pip-parseable, the environment Phase 5 will provision.
  - ``README.md``        — what the lesson teaches, who it's for, how to set up and run.

Pure and offline: no LLM, no network. The only side effect is writing two files into
the run dir; everything else is string templating over the plan markdown.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from forged.pipeline.dependencies import RequirementSet, extract_requirements

REQUIREMENTS_FILE = "requirements.txt"
README_FILE = "README.md"

# The deliverable is always a Jupyter notebook, so a fresh learner venv needs ipykernel
# to register itself as a selectable kernel — even when the lesson imports nothing else.
# This is appended to the learner's requirements.txt only; it is NOT part of the parsed
# RequirementSet, so the provisioning cache's content hash stays stable.
KERNEL_DEP = "ipykernel>=6"


@dataclass(frozen=True)
class PackageContext:
    """The learner-facing facts the README needs that the plan does not carry.

    Sourced from the run's inputs (topic + learner profile), not the plan, so the
    README can address the learner directly.
    """

    topic: str
    learner_name: str = "the learner"
    learner_description: str = ""


@dataclass(frozen=True)
class PackageResult:
    """What write_package produced: the files written + the resolved requirement set.

    requirement_set is returned so callers can record its content-addressed hash in
    the run manifest (and Phase 5 can key its venv cache on it) without re-parsing.
    """

    filenames: tuple[str, ...]
    requirement_set: RequirementSet


# ── Plan section extraction ────────────────────────────────────────────────────


def _extract_section(plan_markdown: str, heading: str) -> str:
    """Return the body under a ``## <heading>`` section, up to the next ``## ``.

    Empty string when the section is absent. Any fenced ```` ``` ```` blocks inside the
    section are stripped — machine-readable blocks (e.g. ```requirements) belong in
    their own file, never inlined into prose.
    """
    pattern = re.compile(
        rf"^##\s+{re.escape(heading)}\s*\n(.*?)(?=^##\s|\Z)",
        re.DOTALL | re.MULTILINE | re.IGNORECASE,
    )
    match = pattern.search(plan_markdown)
    if match is None:
        return ""
    body = re.sub(r"```.*?```", "", match.group(1), flags=re.DOTALL)
    return body.strip()


def _kernel_slug(topic: str) -> str:
    """A short, filesystem/CLI-safe kernel name derived from the topic."""
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
    return (slug[:40].rstrip("-") or "lesson")


def render_learner_requirements(requirement_set: RequirementSet) -> str:
    """Render requirements.txt for the learner, ensuring ipykernel is present.

    The parsed RequirementSet only covers the lesson's imports (correct for the
    provisioning cache). The human running the notebook in a fresh venv also needs
    ipykernel to register a kernel, so append it here — without mutating the
    RequirementSet, so its content-addressed hash is unaffected.
    """
    base = requirement_set.render_txt()
    if "ipykernel" in base.lower():
        return base
    return (
        base
        + "# ipykernel: register this environment as a Jupyter kernel (see README).\n"
        + f"{KERNEL_DEP}\n"
    )


# ── README ───────────────────────────────────────────────────────────────────────


def build_readme(
    plan_markdown: str, ctx: PackageContext, requirement_set: RequirementSet
) -> str:
    """Render the learner-facing README.md as markdown text.

    Pulls "what this teaches" from the plan's ``## Learning objectives`` and the setup
    prose from ``## Prerequisites``; falls back to sensible defaults when a section is
    missing, so the document is always usable.
    """
    objectives = _extract_section(plan_markdown, "Learning objectives")
    prerequisites = _extract_section(plan_markdown, "Prerequisites")

    who = ctx.learner_name
    if ctx.learner_description:
        who = f"{ctx.learner_name} — {ctx.learner_description}"

    install_block = (
        "```bash\npip install -r requirements.txt\n```"
        if requirement_set.requirements
        else "_This lesson needs no third-party packages._"
    )

    slug = _kernel_slug(ctx.topic)
    display_name = f"Python ({slug})"
    run_steps = (
        "1. Create and activate a virtual environment:\n"
        "   ```bash\n"
        "   python -m venv .venv\n"
        "   source .venv/bin/activate      # Windows: .venv\\Scripts\\activate\n"
        "   ```\n"
        "2. Install dependencies:\n"
        "   ```bash\n"
        "   pip install -r requirements.txt\n"
        "   ```\n"
        "3. Register this environment as a Jupyter kernel so your editor can find it:\n"
        "   ```bash\n"
        f"   python -m ipykernel install --user --name {slug} --display-name \"{display_name}\"\n"
        "   ```\n"
        "4. Open `lesson.ipynb` (run `jupyter notebook lesson.ipynb`, or open it in VS Code) "
        f"and **select the `{display_name}` kernel** you just registered.\n"
        "5. Run the cells from top to bottom."
    )
    troubleshooting = (
        "## If the kernel doesn't show up\n\n"
        "A newly registered kernel only appears after the editor rescans:\n"
        "- **VS Code:** run *Developer: Reload Window*, then re-open the kernel picker "
        "(or pick the interpreter at `.venv/bin/python` directly).\n"
        "- **Jupyter:** restart the `jupyter notebook`/Lab server.\n"
        f"You can confirm it was registered with `jupyter kernelspec list` (look for `{slug}`)."
    )

    sections = [
        f"# {ctx.topic}",
        "> Auto-generated learner guide. Open `lesson.ipynb` and run the cells top to bottom.",
        "## What this teaches",
        objectives or f"A hands-on lesson on **{ctx.topic}**.",
        "## Who this is for",
        who,
        "## Environment setup",
        prerequisites or "Any recent Python 3 environment with Jupyter.",
        install_block,
        "## How to run",
        run_steps,
        troubleshooting,
    ]
    return "\n\n".join(sections) + "\n"


# ── Entry point ───────────────────────────────────────────────────────────────────


def write_package(
    run_dir: Path, plan_markdown: str, ctx: PackageContext
) -> PackageResult:
    """Write requirements.txt + README.md into run_dir from the lesson plan.

    Args:
        run_dir: the run directory the notebook already lives in.
        plan_markdown: the planner's lesson plan (source of deps + prose).
        ctx: learner-facing context the plan does not carry.

    Returns:
        PackageResult with the filenames written and the resolved RequirementSet.
    """
    requirement_set = extract_requirements(plan_markdown)
    (run_dir / REQUIREMENTS_FILE).write_text(
        render_learner_requirements(requirement_set), encoding="utf-8"
    )
    (run_dir / README_FILE).write_text(
        build_readme(plan_markdown, ctx, requirement_set), encoding="utf-8"
    )
    return PackageResult(
        filenames=(REQUIREMENTS_FILE, README_FILE),
        requirement_set=requirement_set,
    )
