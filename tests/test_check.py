import json
import os

import pytest

from locked_digest.__main__ import main
from locked_digest.check import check
from locked_digest.template import Template

T = "# Digest {{date:date}}\n{{items:list}}\nOn time: {{a:int}} of {{b:int}}\nNote: {{note:text}}\n"
V = {"date": "2026-03-05", "items": ["one"], "a": 2, "b": 3, "note": "fine"}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_clean_digest_passes():
    t = Template(T)
    assert check(t, t.fill(V)).ok


@pytest.mark.parametrize("note,label", [
    ("mail ops@example.org", "email"),
    ("acct 1234 5678 9012", "digit run"),
    ("host 10.0.0.12", "IPv4"),
    ("token ghp_abcdefghijklmnop", "secret"),
    ("see /home/alice/notes", "home-directory"),
])
def test_deny_patterns(note, label):
    t = Template(T)
    res = check(t, t.fill(dict(V, note=note)))
    assert not res.ok and any(label in p for p in res.problems)


def test_dates_are_not_digit_runs():
    t = Template(T)
    assert check(t, t.fill(dict(V, note="due 2026-04-01"))).ok


def test_rules_cross_check():
    t = Template(T)
    res = check(t, t.fill(dict(V, a=5)), rules=[("a", "<=", "b")])
    assert not res.ok and "rule: a <= b is false" in res.problems[0]
    assert check(t, t.fill(V), rules=[("a", "<=", "b")]).ok


def test_rule_on_unknown_field_is_a_problem():
    t = Template(T)
    assert not check(t, t.fill(V), rules=[("a", "<=", "zzz")]).ok


def test_max_chars():
    t = Template(T)
    assert not check(t, t.fill(V), max_chars=10).ok


def test_custom_deny_replaces_defaults():
    t = Template(T)
    assert check(t, t.fill(dict(V, note="ops@example.org")), deny={}).ok
    assert not check(t, t.fill(dict(V, note="secret project")), deny={"codename": "secret"}).ok


@pytest.fixture
def files(tmp_path):
    tpl = tmp_path / "t.md"
    tpl.write_text(T)
    vals = tmp_path / "v.json"
    vals.write_text(json.dumps(V))
    sink = tmp_path / "sent.txt"
    send = tmp_path / "send.sh"
    send.write_text(f"#!/bin/sh\ncat > {sink}\n")
    os.chmod(send, 0o755)
    return tpl, vals, sink, send, tmp_path


def test_cli_requires_lock(files):
    tpl, vals, *_ = files
    assert main(["fill", str(tpl), "--values", str(vals)]) == 1


def test_cli_send_ok(files):
    tpl, vals, sink, send, tmp = files
    assert main(["lock", str(tpl)]) == 0
    assert main(["send", str(tpl), "--values", str(vals), "--send-cmd", str(send)]) == 0
    assert sink.read_text().startswith("# Digest 2026-03-05")


def test_cli_send_held_on_deny(files):
    tpl, vals, sink, send, tmp = files
    vals.write_text(json.dumps(dict(V, note="call 2125550123 now")))
    main(["lock", str(tpl)])
    held = tmp / "held"
    rc = main(["send", str(tpl), "--values", str(vals), "--send-cmd", str(send), "--held-dir", str(held)])
    assert rc == 3 and not sink.exists()
    assert (held / "digest-held.md").exists()


def test_cli_send_bad_value_exit_1(files):
    tpl, vals, sink, send, tmp = files
    vals.write_text(json.dumps(dict(V, a="two")))
    main(["lock", str(tpl)])
    assert main(["send", str(tpl), "--values", str(vals), "--send-cmd", str(send)]) == 1
    assert not sink.exists()


def test_cli_check_hand_edited_digest(files):
    tpl, vals, sink, send, tmp = files
    main(["lock", str(tpl)])
    out = tmp / "d.md"
    assert main(["fill", str(tpl), "--values", str(vals), "--out", str(out)]) == 0
    assert main(["check", str(tpl), str(out)]) == 0
    out.write_text(out.read_text().replace("On time:", "On-time:"))
    assert main(["check", str(tpl), str(out)]) == 3


def test_cli_send_cmd_failure_exit_1(files):
    tpl, vals, sink, send, tmp = files
    send.write_text("#!/bin/sh\nexit 7\n")
    main(["lock", str(tpl)])
    assert main(["send", str(tpl), "--values", str(vals), "--send-cmd", str(send)]) == 1


def test_example_files_pass(capsys):
    ex = os.path.join(ROOT, "examples")
    rc = main(["fill", os.path.join(ex, "daily-digest.md"), "--values", os.path.join(ex, "values.json"),
               "--rules", os.path.join(ex, "rules.json")])
    assert rc == 0
    assert "On time: 11 of 12" in capsys.readouterr().out
