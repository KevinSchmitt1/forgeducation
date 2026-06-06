"""Artifacts and the per-run store.

An *artifact* is one typed piece of content passed between stages (a lesson plan,
a notebook, an execution report). A *run* is one full pipeline invocation; all of
its artifacts live in a single timestamped directory so any run is fully
reproducible and inspectable after the fact.

Artifacts are immutable: producing a new version means creating a new Artifact,
never mutating an existing one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Artifact:
    """An immutable named piece of content with a kind tag.

    `kind` is a coarse content type ("text", "notebook", "json") used to decide
    file extension and how downstream agents should read it. `name` is the stable
    key stages use to reference each other's outputs (matches StageConfig.output).
    """

    name: str
    kind: str
    content: str

    EXTENSIONS = {"text": ".md", "notebook": ".ipynb", "json": ".json"}

    @property
    def filename(self) -> str:
        return f"{self.name}{self.EXTENSIONS.get(self.kind, '.txt')}"


class ArtifactStore:
    """Reads and writes artifacts for a single run directory.

    The store also keeps a manifest.json recording run metadata and the order in
    which artifacts were produced — the audit trail for reproducibility.
    """

    def __init__(self, run_dir: Path):
        self._run_dir = run_dir
        self._artifacts: dict[str, Artifact] = {}
        self._history: list[str] = []

    @classmethod
    def create(cls, runs_root: str | Path, pipeline_name: str) -> ArtifactStore:
        """Create a fresh, uniquely-named run directory under `runs_root`."""
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        safe_name = pipeline_name.replace(" ", "-").lower()
        run_dir = Path(runs_root) / f"{stamp}_{safe_name}"
        run_dir.mkdir(parents=True, exist_ok=False)
        return cls(run_dir)

    @property
    def run_dir(self) -> Path:
        return self._run_dir

    def put(self, artifact: Artifact) -> Artifact:
        """Persist an artifact to disk and register it. Returns it unchanged so
        callers can write-and-use in one expression."""
        path = self._run_dir / artifact.filename
        path.write_text(artifact.content, encoding="utf-8")
        self._artifacts[artifact.name] = artifact
        self._history.append(artifact.name)
        return artifact

    def get(self, name: str) -> Artifact:
        if name not in self._artifacts:
            raise KeyError(
                f"Artifact '{name}' not in store. Produced so far: "
                f"{sorted(self._artifacts)}"
            )
        return self._artifacts[name]

    def has(self, name: str) -> bool:
        return name in self._artifacts

    def write_file(self, filename: str, content: str) -> Path:
        """Write an auxiliary file into the run dir (e.g. SUMMARY.md, lesson.ipynb)
        that is not a pipeline artifact. Returns the path."""
        path = self._run_dir / filename
        path.write_text(content, encoding="utf-8")
        return path

    def read_file(self, filename: str) -> str:
        return (self._run_dir / filename).read_text(encoding="utf-8")

    def finalize(self, keep_filenames: set[str]) -> list[str]:
        """Delete every file in the run dir except those named in `keep_filenames`.

        Used on a successful run to drop agent-to-agent plumbing (raw JSON reports,
        intermediate notebooks) and keep only the human-facing deliverables. Failed
        runs skip this so everything stays available for debugging. Returns the list
        of removed filenames.
        """
        removed = []
        for path in self._run_dir.iterdir():
            if path.is_file() and path.name not in keep_filenames:
                path.unlink()
                removed.append(path.name)
        return removed

    def write_manifest(self, pipeline_name: str, extra: dict | None = None) -> None:
        """Snapshot run metadata to manifest.json (the reproducibility record)."""
        manifest = {
            "pipeline": pipeline_name,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "artifact_order": list(self._history),
            "artifacts": {
                name: art.filename for name, art in self._artifacts.items()
            },
            **(extra or {}),
        }
        (self._run_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
