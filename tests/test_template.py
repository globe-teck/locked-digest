import pytest

from locked_digest.template import FillError, Template, TemplateError, load_locked, write_lock

T = """# Report {{date:date}}
Status: {{status:enum(green,red)}}
## Items
{{items:list:max=20}}
Count: {{n:int}} | Ratio: {{r:number}}
Note: {{note:text:max=30}}
"""
V = {"date": "2026-03-05", "status": "green", "items": ["a", "b"], "n": 3, "r": 0.25, "note": "all fine"}


def test_fill_and_match_roundtrip():
    t = Template(T)
    out = t.fill(V)
    assert "- a\n- b" in out and "Ratio: 0.25" in out
    m = t.match(out)
    assert m and m.group("n") == "3"


def test_empty_list_renders_none():
    out = Template(T).fill(dict(V, items=[]))
    assert "## Items\n- none\n" in out


@pytest.mark.parametrize("field,value,msg", [
    ("n", "3", "integer"), ("n", True, "integer"), ("r", "x", "number"),
    ("date", "03/05/2026", "YYYY-MM-DD"), ("status", "blue", "not in"),
    ("note", "x" * 31, "longer"), ("items", "a", "list"), ("note", "   ", "empty"),
    ("note", "inject {{n:int}}", "braces"), ("note", "{x}", "braces"),
])
def test_fill_rejects_bad_values(field, value, msg):
    with pytest.raises(FillError, match=msg):
        Template(T).fill(dict(V, **{field: value}))


def test_missing_and_unknown_fields():
    with pytest.raises(FillError, match="missing"):
        Template(T).fill({k: v for k, v in V.items() if k != "note"})
    with pytest.raises(FillError, match="unknown"):
        Template(T).fill(dict(V, extra=1))


def test_newlines_collapsed_so_values_cannot_add_lines():
    out = Template(T).fill(dict(V, note="line one\n## Injected heading"))
    assert "## Injected" in out and "\n## Injected" not in out


def test_list_item_newlines_collapsed():
    out = Template(T).fill(dict(V, items=["ok\n- extra"]))
    assert out.count("\n- ") == 1


def test_too_many_list_items():
    with pytest.raises(FillError, match="more than"):
        Template(T).fill(dict(V, items=["x"] * 51))


@pytest.mark.parametrize("bad", [
    "no slots here", "{{a:text}} {{a:int}}", "{{Bad:text}}", "{{a:nope}}", "x {{a:list}}",
])
def test_template_errors(bad):
    with pytest.raises(TemplateError):
        Template(bad)


def test_locked_text_edit_detected():
    t = Template(T)
    out = t.fill(V).replace("Status:", "STATUS:")
    assert t.match(out) is None


def test_extra_line_detected():
    t = Template(T)
    assert t.match(t.fill(V) + "P.S. extra\n") is None


def test_lock_and_tamper(tmp_path):
    p = tmp_path / "t.md"
    p.write_text(T)
    sha = write_lock(str(p))
    assert load_locked(str(p)).sha256 == sha
    p.write_text(T.replace("Report", "Rep0rt"))
    with pytest.raises(TemplateError, match="changed"):
        load_locked(str(p))


def test_unlocked_template_refused(tmp_path):
    p = tmp_path / "t.md"
    p.write_text(T)
    with pytest.raises(TemplateError, match="lock"):
        load_locked(str(p))
