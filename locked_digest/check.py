"""Self-check a filled digest before it is sent."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .template import Template

# Patterns that should never appear in a digest that leaves the machine.
DEFAULT_DENY = {
    "email address": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "long digit run (account/card/phone number?)": r"(?<![\d.])\d(?:[ -]?\d){7,}(?![\d])",
    "IPv4 address": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    "secret-looking token": r"(?:ghp_|github_pat_|xox[bap]-|sk-[A-Za-z0-9]{16}|AKIA[0-9A-Z]{16}|BEGIN [A-Z ]*PRIVATE KEY)",
    "home-directory path": r"(?:/home/|/Users/)[A-Za-z0-9._-]+",
}


_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")  # dates are allowed; they look like digit runs


@dataclass
class CheckResult:
    ok: bool
    problems: list[str] = field(default_factory=list)


def check(t: Template, digest: str, deny: dict[str, str] | None = None, max_chars: int = 8000,
          rules: list[tuple[str, str, str]] | None = None) -> CheckResult:
    """``rules``: (field_a, op, field_b) numeric cross-checks, op in <=, <, ==, >=, >."""
    problems: list[str] = []
    m = t.match(digest)
    if m is None:
        problems.append("structure: digest does not match the locked template (locked text edited, "
                        "a slot value has the wrong type, or extra/missing lines)")
    if len(digest) > max_chars:
        problems.append(f"length: {len(digest)} chars > {max_chars}")
    for label, pat in (DEFAULT_DENY if deny is None else deny).items():
        hit = next((h for h in re.finditer(pat, digest) if not _ISO_DATE.fullmatch(h.group(0))), None)
        if hit:
            line = digest.count("\n", 0, hit.start()) + 1
            problems.append(f"deny: {label} on line {line}")
    if m is not None and rules:
        ops = {"<=": float.__le__, "<": float.__lt__, "==": float.__eq__, ">=": float.__ge__, ">": float.__gt__}
        for a, op, b in rules:
            try:
                if not ops[op](float(m.group(a)), float(m.group(b))):
                    problems.append(f"rule: {a} {op} {b} is false ({m.group(a)} vs {m.group(b)})")
            except (IndexError, KeyError, ValueError) as e:
                problems.append(f"rule: cannot evaluate {a} {op} {b} ({e})")
    return CheckResult(ok=not problems, problems=problems)
