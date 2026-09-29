"""Markdown for the UI's plan preview and launch panel (pure functions)."""

from __future__ import annotations

import os

from forged.service import Launch, PlanPreview

_DEFAULT_LANGFUSE = "http://localhost:3000"
_FIDELITY_BADGE = {
    "covered": "✅ every requested capability is covered",
    "dropped": "⚠️ some requested capabilities are no longer covered",
    "not_assessed": "ⓘ not assessed — no discrete capabilities to check against",
}


def plan_markdown(preview: PlanPreview) -> str:
    count = len(preview.modules)
    shape = "a single lesson" if preview.shape == "lesson" else f"a {count}-module course"
    lines = [f"### {preview.title}", f"**Shape:** {shape}"]
    if preview.building < count:
        lines[-1] += f" — building {preview.building} of {count} (capped by max modules)"
    if preview.rationale:
        lines.extend(["", f"_{preview.rationale}_"])
    lines.append("")
    for module in preview.modules:
        lines.extend(_module_lines(module, preview))
    lines.append(f"**{preview.estimate}**")
    lines.append("")
    lines.append(f"**Fidelity:** {_FIDELITY_BADGE[preview.fidelity_status]}")
    lines.extend(f"- dropped: {capability}" for capability in preview.missing)
    lines.extend(f"\n> ⓘ {note}" for note in preview.notes)
    if not preview.can_build:
        lines.append(f"\n> ⛔ **Cannot build this plan:** {preview.block_reason}")
    return "\n".join(lines)


def _module_lines(module, preview: PlanPreview) -> list[str]:
    number_by_title = {m.title: m.number for m in preview.modules}
    mode = f"`{module.lesson_mode}`" if module.lesson_mode else "_mode: planner decides_"
    header = f"**[{module.number}] {module.title}** · {mode} · {module.depth} {module.scope}"
    if module.builds_on:
        refs = ", ".join(
            f"[{number_by_title[t]}]" if t in number_by_title else t for t in module.builds_on
        )
        header += f" · builds on {refs}"
    if not module.built:
        header += " · **NOT BUILT** (max modules)"
    bullets = [f"  - {objective}" for objective in module.objectives] or [
        "  - (no objectives stated)"
    ]
    return [f"- {header}", *bullets, ""]


def launch_markdown(launch: Launch, status: str) -> str:
    return "\n".join(
        [
            "### Build launched" if launch.pid is not None else "### Build (dry run)",
            f"- **Status:** {status}",
            f"- **Run directory:** `{launch.run_dir}`",
            f"- **Launch log:** `{launch.log_path}`",
            f"- **Build request:** `{launch.request_path}` (no API key in it)",
            "",
            _langfuse_line(),
            "",
            "The UI's job ends here: open the notebook(s) in Jupyter when the run finishes.",
        ]
    )


def _langfuse_line() -> str:
    host = os.environ.get("LANGFUSE_HOST") or os.environ.get("LANGFUSE_BASE_URL")
    if os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"):
        return f"**Watch it live in Langfuse:** {host or _DEFAULT_LANGFUSE}"
    return (
        "**Watch it live in Langfuse:** tracing is not configured in this process — start "
        f"the local stack (`docker-compose.observability.yml`, {_DEFAULT_LANGFUSE}) and set "
        "`LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`. Meanwhile, the launch log above "
        "shows progress."
    )
