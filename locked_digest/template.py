"""Locked markdown templates with typed slots.

Slot syntax: ``{{name:type}}`` or ``{{name:type:max=N}}``.

Types:
  text            one line of text (default max 200 chars)
  int / number    an integer / a decimal number
  date            YYYY-MM-DD
  enum(a,b,c)     one of the listed words
  list            one or more "- item" lines ("- none" when empty), each item max 200 chars

Everything outside the slots is locked: the self-check rebuilds a strict regex
from the template and the filled digest must match it exactly.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

SLOT = re.compile(r"\{\{\s*([a-z][a-z0-9_]*)\s*:\s*(text|int|number|date|list|enum\([a-z0-9_,\- ]+\))"
                  r"(?:\s*:\s*max=(\d+))?\s*\}\}")
ANY_BRACES = re.compile(r"\{\{|\}\}")
DEFAULT_MAX = 200
MAX_LIST_ITEMS = 50


class TemplateError(ValueError):
    pass


class FillError(ValueError):
    pass


@dataclass(frozen=True)
class Slot:
    name: str
    kind: str
    max_len: int
    choices: tuple[str, ...] = ()

    def pattern(self) -> str:
        if self.kind == "int":
            return r"-?\d{1,15}"
        if self.kind == "number":
            return r"-?\d{1,15}(?:\.\d{1,6})?"
        if self.kind == "date":
            return r"\d{4}-\d{2}-\d{2}"
        if self.kind == "enum":
            return "(?:" + "|".join(re.escape(c) for c in self.choices) + ")"
        item = r"[^\n{}]{1,%d}" % self.max_len
        if self.kind == "list":
            return r"- %s(?:\n- %s){0,%d}" % (item, item, MAX_LIST_ITEMS - 1)
        return item  # text

    def render(self, value) -> str:
        if self.kind == "list":
            if value is None or value == []:
                return "- none"
            if not isinstance(value, list):
                raise FillError(f"{self.name}: expected a list")
            if len(value) > MAX_LIST_ITEMS:
                raise FillError(f"{self.name}: more than {MAX_LIST_ITEMS} items")
            return "\n".join("- " + self._line(v) for v in value)
        if value is None:
            raise FillError(f"{self.name}: missing value")
        if self.kind == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise FillError(f"{self.name}: expected an integer")
            return str(value)
        if self.kind == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise FillError(f"{self.name}: expected a number")
            return f"{value:.6f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)
        s = self._line(value)
        if self.kind == "date" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            raise FillError(f"{self.name}: expected YYYY-MM-DD")
        if self.kind == "enum" and s not in self.choices:
            raise FillError(f"{self.name}: {s!r} not in {self.choices}")
        return s

    def _line(self, value) -> str:
        s = " ".join(str(value).split())  # collapse newlines/tabs: no structure injection
        if not s:
            raise FillError(f"{self.name}: empty value")
        if ANY_BRACES.search(s) or "{" in s or "}" in s:
            raise FillError(f"{self.name}: braces are not allowed in values")
        if len(s) > self.max_len:
            raise FillError(f"{self.name}: longer than {self.max_len} chars")
        return s


class Template:
    def __init__(self, text: str):
        self.text = text
        self.slots: list[Slot] = []
        self._parts: list[str | Slot] = []
        pos = 0
        for m in SLOT.finditer(text):
            self._parts.append(text[pos:m.start()])
            name, kind, mx = m.group(1), m.group(2), m.group(3)
            choices: tuple[str, ...] = ()
            if kind.startswith("enum("):
                choices = tuple(c.strip() for c in kind[5:-1].split(",") if c.strip())
                kind = "enum"
            if any(s.name == name for s in self.slots):
                raise TemplateError(f"slot {name!r} appears twice")
            slot = Slot(name, kind, int(mx) if mx else DEFAULT_MAX, choices)
            if kind == "list" and not (m.start() == 0 or text[m.start() - 1] == "\n"):
                raise TemplateError(f"list slot {name!r} must start a line")
            self.slots.append(slot)
            self._parts.append(slot)
            pos = m.end()
        self._parts.append(text[pos:])
        leftovers = [p for p in self._parts if isinstance(p, str) and ANY_BRACES.search(p)]
        if leftovers:
            raise TemplateError("malformed slot (check name/type spelling): "
                                + leftovers[0][max(0, leftovers[0].find("{{")):][:60])
        if not self.slots:
            raise TemplateError("template has no slots")
        self.regex = re.compile("".join(
            f"(?P<{p.name}>{p.pattern()})" if isinstance(p, Slot) else re.escape(p) for p in self._parts))

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    def fill(self, values: dict) -> str:
        names = {s.name for s in self.slots}
        extra = sorted(set(values) - names)
        if extra:
            raise FillError(f"unknown fields: {', '.join(extra)}")
        return "".join(p.render(values.get(p.name)) if isinstance(p, Slot) else p for p in self._parts)

    def match(self, digest: str):
        return self.regex.fullmatch(digest)


def write_lock(template_path: str) -> str:
    with open(template_path, encoding="utf-8") as f:
        t = Template(f.read())
    with open(template_path + ".lock", "w", encoding="utf-8") as f:
        json.dump({"sha256": t.sha256, "slots": [s.name for s in t.slots]}, f, indent=1)
        f.write("\n")
    return t.sha256


def load_locked(template_path: str) -> Template:
    with open(template_path, encoding="utf-8") as f:
        t = Template(f.read())
    try:
        with open(template_path + ".lock", encoding="utf-8") as f:
            lock = json.load(f)
    except FileNotFoundError:
        raise TemplateError("no .lock file: run `lock` once after reviewing the template")
    if lock.get("sha256") != t.sha256:
        raise TemplateError("template changed since it was locked (sha256 mismatch); review and re-lock")
    return t
