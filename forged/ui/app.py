"""Gradio wiring for the front door: widgets → `FrontDoor` steps → widget updates.

No behaviour lives here — every button calls one `FrontDoor` method (see
`front_door.py`, unit-tested without a browser). Gradio (not Streamlit) because its
event model maps one-to-one onto those step functions and `gr.State` keeps the frozen
`Session` per browser tab in server memory; Streamlit's rerun-the-script model would
have put the gate loop in module-level control flow.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

# Gradio phones home for usage analytics unless told not to; this app is local-only.
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

import gradio as gr  # noqa: E402 - must follow the analytics opt-out above

from forged.service import (  # noqa: E402
    EDIT_OPS,
    LESSON_MODES,
    DryRunLauncher,
    ForgeService,
    SubprocessLauncher,
    enum_choices,
)

from .front_door import FormValues, FrontDoor, Session, View  # noqa: E402

EDIT_LABELS = {
    "merge": "Merge two modules",
    "drop": "Drop module(s)",
    "reorder": "Reorder (full new order)",
    "force_single": "Make it a single lesson",
    "set_mode": "Set a module's lesson mode",
}
_CSS = """
.gradio-container { max-width: 1100px !important; margin: 0 auto; }
#fd-header h1 { font-size: 2.1rem; letter-spacing: -0.02em; margin-bottom: 0.1rem; }
#fd-header p { opacity: 0.75; margin-top: 0; }
.fd-step h2 { border-left: 4px solid var(--color-accent); padding-left: 0.6rem; }
#fd-message { min-height: 1.5rem; }
#fd-plan { border: 1px solid var(--border-color-primary); border-radius: 10px;
           padding: 0.75rem 1rem; background: var(--block-background-fill); }
"""


def build_app(door: FrontDoor, *, demo: bool = False) -> gr.Blocks:
    """Build the Blocks app. `demo` labels the offline `--fake-llm` mode loudly."""
    defaults = FormValues.defaults()
    with gr.Blocks(title="forgeducation", analytics_enabled=False, css=_CSS) as app:
        session = gr.State(Session())
        gr.Markdown(
            "# forgeducation\nCompose a lesson, check the plan and its cost, then launch "
            "the build. Runs locally; your key never leaves this process.",
            elem_id="fd-header",
        )
        if demo:
            gr.Markdown(
                "> 🧪 **Offline demo mode** (`--fake-llm`): plans are canned, no API is "
                "called, and *Launch* is a dry run.",
                elem_id="fd-demo-banner",
            )

        with gr.Accordion("API key (bring your own)", open=True):
            api_key = gr.Textbox(
                label="OpenAI API key", type="password", placeholder="sk-…",
                elem_id="fd-api-key",
                info="Held in memory for this tab only; handed to the planner and the build "
                     "process via their environment. Never saved, never logged.",
            )
            key_status = gr.Markdown(FrontDoor.key_status(""), elem_id="fd-key-status")

        with gr.Group(elem_classes="fd-step"):
            gr.Markdown("## 1 · What do you want to learn?")
            topic = gr.Textbox(
                label="Topic", placeholder="e.g. How a hash map works", elem_id="fd-topic"
            )
            with gr.Accordion("Learner profile — who is learning", open=False):
                with gr.Row():
                    name = gr.Textbox(label="Name", value=defaults.name, elem_id="fd-name")
                    environment = _enum("environment", defaults.environment, "Environment")
                with gr.Row():
                    density = _enum("material_density", defaults.material_density, "Density")
                    style = _enum("learning_style", defaults.learning_style, "Learning style")
                description = gr.Textbox(label="Description", value=defaults.description)
                prior = _rows("Prior knowledge", defaults.prior_knowledge, "fd-prior")
                background = gr.Textbox(
                    label="Background", value=defaults.background_context, lines=2
                )
            with gr.Accordion("Topic specification — what is taught", open=True):
                title = gr.Textbox(
                    label="Title", placeholder="defaults to the topic", elem_id="fd-title"
                )
                with gr.Row():
                    scope = _enum("scope", defaults.scope, "Scope")
                    depth = _enum("depth", defaults.depth, "Depth")
                objectives = _rows("Learning objectives", [], "fd-objectives")
                prerequisites = _rows("Prerequisites", defaults.prerequisites, "fd-prereqs")
                focus = _rows("Focus areas", defaults.focus_areas, "fd-focus")
                constraints = gr.Textbox(label="Constraints", value=defaults.constraints)
            plan_btn = gr.Button(
                "Plan it  (one cheap planner call)", variant="primary", elem_id="fd-plan-btn"
            )

        message = gr.Markdown(elem_id="fd-message")

        with gr.Group(elem_classes="fd-step"):
            gr.Markdown("## 2 · Review and edit the plan")
            plan_md = gr.Markdown("_No plan yet._", elem_id="fd-plan")
            with gr.Row():
                edit_op = gr.Dropdown(
                    [(EDIT_LABELS[op], op) for op in EDIT_OPS], value="merge",
                    label="Edit", elem_id="fd-edit-op", scale=2,
                )
                targets = gr.Textbox(
                    label="Module number(s)", placeholder="e.g. 0, 1", elem_id="fd-targets",
                    scale=1,
                )
                mode = gr.Dropdown(
                    list(LESSON_MODES), value=None, label="Mode (for set mode)",
                    elem_id="fd-mode", scale=1,
                )
                edit_btn = gr.Button("Apply edit", elem_id="fd-edit-btn", scale=1)
            with gr.Row():
                sentence = gr.Textbox(
                    label="…or describe a change",
                    placeholder="e.g. focus more on collision handling",
                    elem_id="fd-sentence", scale=4,
                )
                adjust_btn = gr.Button("Ask the planner", elem_id="fd-adjust-btn", scale=1)
            with gr.Row():
                undo_btn = gr.Button("↩ Undo", interactive=False, elem_id="fd-undo-btn")
                cancel_btn = gr.Button("Cancel", variant="stop", elem_id="fd-cancel-btn")
                confirm_btn = gr.Button(
                    "Confirm plan", variant="primary", interactive=False,
                    elem_id="fd-confirm-btn",
                )

        with gr.Group(elem_classes="fd-step"):
            gr.Markdown("## 3 · Launch the build")
            with gr.Row():
                max_modules = gr.Number(
                    value=None, label="Max modules to build (blank or 0 = all)",
                    precision=0, minimum=0,
                    elem_id="fd-max-modules",
                )
                provision = gr.Checkbox(
                    label="Provision a per-lesson environment", value=True,
                    elem_id="fd-provision",
                )
            with gr.Row():
                launch_btn = gr.Button(
                    "Launch build", variant="primary", interactive=False,
                    elem_id="fd-launch-btn",
                )
                status_btn = gr.Button("Check status", elem_id="fd-status-btn")
            launch_md = gr.Markdown(elem_id="fd-launch")

        form = [
            topic, name, description, prior, environment, density, style, background,
            title, scope, depth, objectives, prerequisites, focus, constraints,
        ]
        outputs = [session, message, plan_md, launch_md, confirm_btn, launch_btn, undo_btn]

        api_key.change(FrontDoor.key_status, api_key, key_status)
        plan_btn.click(
            lambda s, k, *values: _emit(*door.plan(s, k, FormValues(*values))),
            [session, api_key, *form], outputs,
        )
        edit_btn.click(
            lambda s, op, t, m: _emit(*door.edit(s, op, t, m)),
            [session, edit_op, targets, mode], outputs,
        )
        adjust_btn.click(
            lambda s, k, text: _emit(*door.adjust(s, k, text)),
            [session, api_key, sentence], outputs,
        )
        undo_btn.click(lambda s: _emit(*door.undo(s)), session, outputs)
        cancel_btn.click(lambda s: _emit(*door.cancel(s)), session, outputs)
        confirm_btn.click(lambda s: _emit(*door.confirm(s)), session, outputs)
        for control in (max_modules, provision):
            control.change(
                lambda s, n, p: _emit(*door.set_options(s, n, p)),
                [session, max_modules, provision], outputs,
            )
        launch_btn.click(
            lambda s, k: _emit(*door.launch(s, k)), [session, api_key], outputs
        )
        status_btn.click(lambda s: _emit(*door.status(s)), session, outputs)
    return app


def _enum(field_name: str, value: str, label: str) -> gr.Dropdown:
    return gr.Dropdown(
        list(enum_choices(field_name)), value=value, label=label, elem_id=f"fd-{field_name}"
    )


def _rows(label: str, values: Sequence[str], elem_id: str) -> gr.Dropdown:
    """A list-of-strings field: type a row and press Enter to add it; × removes it."""
    return gr.Dropdown(
        choices=list(values), value=list(values), multiselect=True, allow_custom_value=True,
        label=label, info="Type a row and press Enter to add it; × removes it.",
        elem_id=elem_id,
    )


def _emit(session: Session, view: View) -> tuple[Any, ...]:
    """Map a (session, view) step result onto the shared output widgets."""
    return (
        session,
        view.message,
        view.plan_markdown or "_No plan yet._",
        view.launch_markdown,
        gr.update(interactive=view.has_plan and not view.confirmed),
        gr.update(interactive=view.can_launch),
        gr.update(interactive=view.can_undo),
    )


def make_service(runs: Path, fake_llm: bool) -> ForgeService:
    """The real service, or the offline demo one (canned LLM + dry-run launcher)."""
    if fake_llm:
        from .fake_llm import FakeLLM

        fake = FakeLLM()
        return ForgeService(
            runs_root=runs, llm_factory=lambda _model: fake, launcher=DryRunLauncher()
        )
    return ForgeService(runs_root=runs, launcher=SubprocessLauncher())


def serve(host: str, port: int, runs: Path, fake_llm: bool) -> None:
    """Start the app (blocking). Local-only by default; no share link, no API page."""
    app = build_app(FrontDoor(make_service(runs, fake_llm)), demo=fake_llm)
    app.queue().launch(
        server_name=host, server_port=port, share=False, show_api=False, inbrowser=False
    )


def main(argv: list[str] | None = None) -> int:
    """`python -m forged.ui [...]` — delegates to `forged ui [...]` (one parser)."""
    import sys

    from forged import cli

    return cli.main(["ui", *(sys.argv[1:] if argv is None else argv)])
