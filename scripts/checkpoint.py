#!/usr/bin/env python3
"""Human-in-the-loop checkpoint inbox for lane agents (see CLAUDE.md → "Human checkpoints").

A lane agent that reaches a checkpoint posts its packet here, then ends its turn and waits.
The inbox is ONE file in the main checkout (gitignored `INBOX.md`), so every lane — whichever
worktree or branch it runs in — writes to the same place the user reads.

    python scripts/checkpoint.py post --lane 11 --cp CP0 --summary "Plan ready" < packet.md
    python scripts/checkpoint.py resolve --lane 11 --cp CP0 --note "go, option (a)"
    python scripts/checkpoint.py list

Env: LANES_INBOX overrides the inbox path; CHECKPOINT_NO_NOTIFY=1 skips the macOS notification.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

CHECKPOINTS = {
    "CP0": "kickoff",
    "CP1": "demo",
    "CP2": "merge",
    "SPEND": "spend approval",
}
OPEN_MARK = "## ⏳ OPEN"
RESOLVED_MARK = "## ✅ RESOLVED"
ENTRY_SEPARATOR = "\n---\n"
INBOX_HEADER = (
    "# Lane inbox — what is waiting on you\n\n"
    "Entries are posted by lane agents at their human checkpoints (CLAUDE.md → "
    '"Human checkpoints"). Answer in the lane\'s tmux window; the agent resolves the entry.\n'
)


def _run(cmd: list[str]) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return ""
    return result.stdout.strip()


def inbox_path() -> Path:
    """The single inbox file: `$LANES_INBOX`, else `INBOX.md` in the main checkout's root."""
    override = os.environ.get("LANES_INBOX")
    if override:
        return Path(override)
    common_dir = _run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"])
    if not common_dir:
        sys.exit("checkpoint: not inside a git repository (set LANES_INBOX to override)")
    return Path(common_dir).parent / "INBOX.md"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _heading(lane: str, cp: str) -> str:
    return f"Lane {lane} · {cp} {CHECKPOINTS[cp]}"


def _context_line() -> str:
    branch = _run(["git", "branch", "--show-current"]) or "?"
    worktree = _run(["git", "rev-parse", "--show-toplevel"]) or "?"
    window = _run(["tmux", "display-message", "-p", "#W"]) if os.environ.get("TMUX") else ""
    where = f"tmux window `{window}`" if window else "the lane's session"
    return f"**Branch:** `{branch}` · **Worktree:** `{worktree}` · **Answer in:** {where}"


def _read_inbox(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else INBOX_HEADER


def _notify(title: str, message: str) -> None:
    if os.environ.get("CHECKPOINT_NO_NOTIFY") or sys.platform != "darwin":
        return
    script = "on run argv\ndisplay notification (item 2 of argv) with title (item 1 of argv)"
    _run(["osascript", "-e", script + ' sound name "Glass"\nend run', title, message])


def post(lane: str, cp: str, summary: str, body: str) -> int:
    path = inbox_path()
    entry = (
        f"\n{OPEN_MARK} · {_heading(lane, cp)} · {_now()}\n\n"
        f"**Summary:** {summary}\n\n{_context_line()}\n\n{body.strip()}\n{ENTRY_SEPARATOR}"
    )
    path.write_text(_read_inbox(path) + entry, encoding="utf-8")
    _notify(f"forged · {_heading(lane, cp)}", summary)
    print(f"Posted to {path}. Now end your turn and wait for the user's answer.")
    return 0


def resolve(lane: str, cp: str, note: str) -> int:
    path = inbox_path()
    text = _read_inbox(path)
    target = f"{OPEN_MARK} · {_heading(lane, cp)}"
    index = text.rfind(target)
    if index == -1:
        print(f"No open entry for {_heading(lane, cp)} in {path}.", file=sys.stderr)
        return 1
    suffix = f" — {note}" if note else ""
    replacement = f"{RESOLVED_MARK} {_now()}{suffix} · {_heading(lane, cp)}"
    path.write_text(text[:index] + replacement + text[index + len(target) :], encoding="utf-8")
    print(f"Resolved {_heading(lane, cp)}.")
    return 0


def list_open() -> int:
    text = _read_inbox(inbox_path())
    open_lines = [line for line in text.splitlines() if line.startswith(OPEN_MARK)]
    if not open_lines:
        print("Nothing is waiting on you.")
        return 0
    for line in open_lines:
        print(line.removeprefix("## "))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    post_p = sub.add_parser("post", help="post a checkpoint packet and notify the user")
    post_p.add_argument("--lane", required=True)
    post_p.add_argument("--cp", required=True, choices=sorted(CHECKPOINTS))
    post_p.add_argument("--summary", required=True, help="one line: what you need from the user")
    post_p.add_argument("--body", help="the packet (markdown); read from stdin if omitted")

    resolve_p = sub.add_parser("resolve", help="mark the lane's open checkpoint as answered")
    resolve_p.add_argument("--lane", required=True)
    resolve_p.add_argument("--cp", required=True, choices=sorted(CHECKPOINTS))
    resolve_p.add_argument("--note", default="", help="the user's decision, in a few words")

    sub.add_parser("list", help="show what is waiting on the user")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "post":
        body = args.body if args.body is not None else sys.stdin.read()
        return post(args.lane, args.cp, args.summary, body)
    if args.command == "resolve":
        return resolve(args.lane, args.cp, args.note)
    return list_open()


if __name__ == "__main__":
    sys.exit(main())
