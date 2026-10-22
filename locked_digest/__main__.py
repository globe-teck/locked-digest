"""CLI: python -m locked_digest lock|fill|check|send"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys

from .check import check
from .template import FillError, TemplateError, load_locked, write_lock

EXIT_OK, EXIT_ERR, EXIT_HELD = 0, 1, 3


def _rules(path):
    if not path:
        return None
    with open(path, encoding="utf-8") as f:
        return [tuple(r) for r in json.load(f)]


def _report(res, out=sys.stderr):
    for p in res.problems:
        print(f"HOLD {p}", file=out)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="locked_digest")
    sub = p.add_subparsers(dest="cmd", required=True)
    lk = sub.add_parser("lock", help="record the reviewed template's sha256 in <template>.lock")
    lk.add_argument("template")
    for name in ("fill", "check", "send"):
        s = sub.add_parser(name)
        s.add_argument("template")
        if name == "check":
            s.add_argument("digest")
        else:
            s.add_argument("--values", required=True, help="JSON file with one value per slot")
            s.add_argument("--out", default=None, help="write the digest here")
        s.add_argument("--rules", default=None, help="JSON list of [field, op, field] cross-checks")
        s.add_argument("--max-chars", type=int, default=8000)
        if name == "send":
            s.add_argument("--send-cmd", required=True, help="command that gets the digest on stdin (no shell)")
            s.add_argument("--held-dir", default="held", help="where a failed digest is kept for review")
    a = p.parse_args(argv)

    try:
        if a.cmd == "lock":
            print(write_lock(a.template))
            return EXIT_OK
        t = load_locked(a.template)
        if a.cmd == "check":
            with open(a.digest, encoding="utf-8") as f:
                digest = f.read()
        else:
            with open(a.values, encoding="utf-8") as f:
                digest = t.fill(json.load(f))
    except (TemplateError, FillError, OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_ERR

    res = check(t, digest, max_chars=a.max_chars, rules=_rules(a.rules))
    if getattr(a, "out", None):
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(digest)
    if not res.ok:
        _report(res)
        if a.cmd == "send":
            os.makedirs(a.held_dir, exist_ok=True)
            path = os.path.join(a.held_dir, "digest-held.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(digest)
            print(f"not sent; kept for review at {path}", file=sys.stderr)
        return EXIT_HELD
    if a.cmd == "send":
        rc = subprocess.run(shlex.split(a.send_cmd), input=digest, text=True, timeout=120).returncode
        print(f"sent (send-cmd exit {rc})", file=sys.stderr)
        return EXIT_OK if rc == 0 else EXIT_ERR
    if a.cmd == "fill" and not a.out:
        sys.stdout.write(digest)
    print("check passed", file=sys.stderr)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
