"""Check the approval gate, export the page and commit docs/.

The only script that writes to docs/. It refuses a date whose brief is not approved by a
named reviewer, and refuses to export if an evidence quote has reached the page data.
"""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

import config

SCRIPT = "publish"
exporter = importlib.import_module("6_export_for_web")
log = logging.getLogger(SCRIPT)


class GateError(RuntimeError):
    """Publication refused."""


def check_gate(cfg: dict[str, Any], day: date) -> Path:
    """Return the brief's path if it may be published; raise GateError otherwise."""
    path = config.path(cfg, "review_dir") / f"brief_{day.isoformat()}.md"
    if not path.exists():
        raise GateError(f"no brief for {day.isoformat()}")
    meta, _ = exporter.split_front_matter(path.read_text(encoding="utf-8"))
    if meta.get("status") != "approved":
        raise GateError(f"{path.name} has status {meta.get('status') or 'missing'}, not approved")
    if not meta.get("reviewed_by"):
        raise GateError(f"{path.name} has no reviewed_by name")
    return path


def check_no_quotes(cfg: dict[str, Any], data: dict[str, Any]) -> None:
    """Raise GateError if any stored evidence quote appears in the page data.

    A quote that is part of a coded story's headline is skipped: headlines may be published,
    for headline-only stories the model can only quote the headline, and one outlet's quote
    is sometimes another outlet's headline for the same event.
    """
    coded = config.path(cfg, "coded_jsonl")
    if not coded.exists():
        return
    payload = json.dumps(data, ensure_ascii=False)
    with coded.open(encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh]
    headlines = "\n".join(row.get("title") or "" for row in rows)
    for row in rows:
        quote = row["extraction"].get("evidence_quote", "")
        if quote and quote in headlines:
            continue
        if quote and len(quote) > 20 and quote in payload:
            raise GateError(f"an evidence quote reached the page data: {quote[:40]}...")


def commit(cfg: dict[str, Any], day: date) -> None:
    """Commit docs/ only; do nothing if unchanged."""
    docs = str(config.path(cfg, "docs_dir"))
    subprocess.run(["git", "add", docs], check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet", "--", docs]).returncode == 0:
        log.info("docs/ unchanged; nothing to commit")
        return
    subprocess.run(["git", "commit", "-m", f"Publish brief for {day.isoformat()}", "--", docs], check=True)


def run(cfg: dict[str, Any], day: date, do_commit: bool = True) -> None:
    """Publish one approved date."""
    check_gate(cfg, day)
    data = exporter.build(cfg)
    check_no_quotes(cfg, data)
    exporter.write(cfg, data)
    shutil.copyfile(config.path(cfg, "web_template"), config.path(cfg, "docs_dir") / "index.html")
    if do_commit:
        commit(cfg, day)
    log.info("Published %s", day.isoformat())


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", type=date.fromisoformat, help="brief date (default today)")
    parser.add_argument("--no-commit", action="store_true", help="write docs/ but do not commit")
    args = parser.parse_args()
    cfg = config.get_config()
    config.setup_logging(SCRIPT, cfg)
    try:
        run(cfg, args.date or config.now(cfg).date(), do_commit=not args.no_commit)
    except GateError as exc:
        log.error("Not published: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
