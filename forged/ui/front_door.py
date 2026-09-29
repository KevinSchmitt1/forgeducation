"""The UI controller: each button is a pure step `(session, widget values) → (session, view)`.

Gradio-free on purpose, so every behaviour is unit-tested without a browser and `app.py`
is only wiring. `Session` is frozen and replaced on every step; it never holds the API
key — the key is a widget value passed into the one call that needs it (plan, adjust,
launch) and handed on to the service, which scopes it to that call.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from forged.service import (
    BuildOptions,
    ForgeService,
    InputError,
    Launch,
    RunInputs,
    default_inputs,
    inputs_from_dict,
    key_in_environment,
)

from .render import launch_markdown, plan_markdown

_LOG = logging.getLogger(__name__)

# Undo depth: plenty for a gate session, bounded so a long session can't grow forever.
MAX_UNDO = 20
_KEY_SHAPED = re.compile(r"sk-[A-Za-z0-9_\-*]{8,}")


def redact(text: str, api_key: str = "") -> str:
    """Strip the user's key (and anything key-shaped) from text bound for the UI or logs.
    Provider errors can echo a (partially masked) key back; none of it is shown."""
    key = (api_key or "").strip()
    if key:
        text = text.replace(key, "[redacted]")
    return _KEY_SHAPED.sub("[redacted]", text)


@dataclass(frozen=True)
class FormValues:
    """The raw values of the input form's widgets, one field per widget."""

    topic: str
    name: str
    description: str
    prior_knowledge: Sequence[str]
    environment: str
    material_density: str
    learning_style: str
    background_context: str
    title: str
    scope: str
    depth: str
    learning_objectives: Sequence[str]
    prerequisites: Sequence[str]
    focus_areas: Sequence[str]
    constraints: str

    @classmethod
    def defaults(cls, topic: str = "") -> FormValues:
        inputs = default_inputs(topic)
        profile, spec = asdict(inputs.learner_profile), asdict(inputs.topic_spec)
        return cls(topic=topic, **profile, **spec)

    def to_inputs(self) -> RunInputs:
        """Validate at the boundary (raises InputError listing every problem)."""
        values = asdict(self)
        profile_keys = (
            "name", "description", "prior_knowledge", "environment", "material_density",
            "learning_style", "background_context",
        )
        return inputs_from_dict(
            {
                "topic": values.pop("topic"),
                "learner_profile": {k: values.pop(k) for k in profile_keys},
                "topic_spec": values,
            }
        )


@dataclass(frozen=True)
class Session:
    inputs: RunInputs | None = None
    plan: dict[str, Any] | None = None
    history: tuple[dict[str, Any], ...] = ()
    confirmed: bool = False
    launch: Launch | None = None
    options: BuildOptions = field(default_factory=BuildOptions)


@dataclass(frozen=True)
class View:
    message: str = ""
    plan_markdown: str = ""
    has_plan: bool = False
    confirmed: bool = False
    can_launch: bool = False
    can_undo: bool = False
    launch_markdown: str = ""


@dataclass(frozen=True)
class FrontDoor:
    service: ForgeService

    # ── Views ───────────────────────────────────────────────────────────────────

    def view(self, session: Session, message: str = "") -> View:
        if session.plan is None or session.inputs is None:
            return View(message=message)
        preview = self.service.preview(session.plan, session.inputs, session.options.max_modules)
        launch_md = ""
        if session.launch is not None:
            launch_md = launch_markdown(session.launch, self.service.status(session.launch))
        return View(
            message=message,
            plan_markdown=plan_markdown(preview),
            has_plan=True,
            confirmed=session.confirmed,
            can_launch=session.confirmed and preview.can_build and session.launch is None,
            can_undo=bool(session.history),
            launch_markdown=launch_md,
        )

    @staticmethod
    def key_status(api_key: str) -> str:
        if (api_key or "").strip():
            return "🔑 Using the key you entered — held in memory only, never saved."
        if key_in_environment():
            return "🔑 No key entered — using the key already set in this app's environment."
        return "⚠️ No API key yet — paste one to plan (or start with `--fake-llm` to try it)."

    # ── Steps ───────────────────────────────────────────────────────────────────

    def plan(self, session: Session, api_key: str, form: FormValues) -> tuple[Session, View]:
        try:
            inputs = form.to_inputs()
        except InputError as exc:
            return session, self.view(session, _problems("Please fix the inputs:", exc))
        try:
            plan = self.service.plan(inputs, api_key)
        except InputError as exc:
            return session, self.view(session, _problems("Please fix:", exc))
        except Exception as exc:  # noqa: BLE001 - any planner failure is shown, not raised
            return session, self.view(session, self._failure("Planning failed", exc, api_key))
        new = Session(inputs=inputs, plan=plan, options=session.options)
        return new, self.view(new, "✅ Plan ready — review it, edit it, then confirm.")

    def edit(
        self, session: Session, op: str, targets_text: str, mode: str | None
    ) -> tuple[Session, View]:
        if session.plan is None:
            return session, self.view(session, "Plan a topic first.")
        try:
            targets = _parse_targets(targets_text)
            outcome = self.service.edit(session.plan, op, targets, mode)
        except ValueError as exc:
            return session, self.view(session, f"⚠️ Could not apply that change: {exc}")
        new = self._with_plan(session, outcome.plan)
        return new, self.view(new, outcome.warning or f"✅ Applied: {op.replace('_', ' ')}.")

    def adjust(self, session: Session, api_key: str, sentence: str) -> tuple[Session, View]:
        if session.plan is None or session.inputs is None:
            return session, self.view(session, "Plan a topic first.")
        try:
            outcome = self.service.adjust(session.plan, sentence, session.inputs, api_key)
        except InputError as exc:
            return session, self.view(session, _problems("Please fix:", exc))
        except ValueError as exc:
            return session, self.view(session, f"⚠️ Could not apply that change: {exc}")
        except Exception as exc:  # noqa: BLE001 - classifier/re-plan failure keeps the plan
            failure = self._failure("Adjusting failed; the plan is unchanged", exc, api_key)
            return session, self.view(session, failure)
        if outcome.confirmed:
            return self.confirm(session)
        if outcome.cancelled:
            return self.cancel(session)
        new = self._with_plan(session, outcome.plan)
        message = "✅ Re-planned with your guidance." if outcome.replanned else (
            outcome.warning or f"✅ Applied: {outcome.op.replace('_', ' ')}."
        )
        return new, self.view(new, message)

    def undo(self, session: Session) -> tuple[Session, View]:
        if not session.history:
            return session, self.view(session, "Nothing to undo.")
        new = replace(
            session, plan=session.history[-1], history=session.history[:-1],
            confirmed=False, launch=None,
        )
        return new, self.view(new, "↩️ Undid the last edit.")

    def confirm(self, session: Session) -> tuple[Session, View]:
        if session.plan is None or session.inputs is None:
            return session, self.view(session, "Plan a topic first, then confirm it.")
        preview = self.service.preview(session.plan, session.inputs, session.options.max_modules)
        if not preview.can_build:
            return session, self.view(session, f"⛔ Cannot confirm: {preview.block_reason}")
        new = replace(session, confirmed=True)
        return new, self.view(new, "✅ Plan confirmed — nothing has been spent yet. Launch below.")

    def cancel(self, session: Session) -> tuple[Session, View]:
        new = Session(options=session.options)
        return new, self.view(new, "Cancelled — nothing was run.")

    def set_options(
        self, session: Session, max_modules: float | None, provision: bool
    ) -> tuple[Session, View]:
        # Blank and 0 both mean "build every module" (a Number widget reports 0 when cleared).
        if max_modules is not None and (max_modules < 0 or max_modules != int(max_modules)):
            return session, self.view(
                session, "⚠️ Max modules must be a whole number (blank or 0 = all)."
            )
        options = BuildOptions(
            max_modules=int(max_modules) if max_modules else None,
            provision=bool(provision),
        )
        new = replace(session, options=options)
        return new, self.view(new)

    def launch(self, session: Session, api_key: str) -> tuple[Session, View]:
        if session.plan is None or session.inputs is None or not session.confirmed:
            return session, self.view(session, "Confirm the plan before launching the build.")
        if session.launch is not None:
            return session, self.view(session, "This plan was already launched.")
        try:
            launch = self.service.build(session.plan, session.inputs, api_key, session.options)
        except InputError as exc:
            return session, self.view(session, _problems("Please fix:", exc))
        except Exception as exc:  # noqa: BLE001 - a failed launch is shown, never raised
            return session, self.view(session, self._failure("Launch failed", exc, api_key))
        new = replace(session, launch=launch)
        return new, self.view(new, "🚀 Launched.")

    def status(self, session: Session) -> tuple[Session, View]:
        return session, self.view(session)

    # ── Helpers ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _with_plan(session: Session, plan: dict[str, Any]) -> Session:
        history = (*session.history, session.plan) if session.plan is not None else ()
        return replace(
            session, plan=plan, history=history[-MAX_UNDO:], confirmed=False, launch=None
        )

    @staticmethod
    def _failure(prefix: str, exc: Exception, api_key: str) -> str:
        detail = redact(str(exc), api_key)
        _LOG.warning("%s: %s", prefix, detail)
        return f"❌ {prefix}: {detail}"


def _parse_targets(text: str) -> tuple[int, ...]:
    stripped = (text or "").strip()
    if not stripped:
        return ()
    parts = re.split(r"\s*,\s*|\s+", stripped)
    if not all(part.isdigit() for part in parts):
        raise ValueError(f"enter module numbers like `0, 2` (got {text!r})")
    return tuple(int(part) for part in parts)


def _problems(heading: str, exc: InputError) -> str:
    return "\n".join([f"⚠️ {heading}", *(f"- {problem}" for problem in exc.problems)])
