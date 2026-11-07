from __future__ import annotations

import os
from datetime import datetime

from cliui.schema.argv import (
    argv_preview,
    build_argv,
    build_form_defaults,
    collect_scopes,
    parse_command,
)


def node(entry, path):
    for item in entry.nodes.values():
        if item.path == path:
            return item
    raise AssertionError(path)


def defaults(node):
    scopes = collect_scopes(node)
    return scopes, build_form_defaults(node, scopes)


def test_default_argv_for_nested_command(fixture_entry):
    run = node(fixture_entry, "sub run")
    scopes, values = defaults(run)
    values["c__value"] = "hello"
    parsed = parse_command(run, values)
    assert parsed.errors == {}
    assert parsed.argv == [
        "--root-name=root",
        "sub",
        "--name=group",
        "run",
        "--name=run",
        "--flag",
        "--level=3",
        "--ratio=1.0",
        "--mode=a",
        "hello",
    ]


def test_scoped_names_do_not_collide(fixture_entry):
    run = node(fixture_entry, "sub run")
    _scopes, values = defaults(run)
    values["c__value"] = "hello"
    values["g1__name"] = "GROUP"
    values["c__name"] = "LEAF"
    parsed = parse_command(run, values)
    assert parsed.errors == {}
    argv = parsed.argv
    assert argv[argv.index("--name=GROUP") + 1] == "run"
    assert "--name=LEAF" in argv


def test_flag_can_be_turned_off_with_secondary_option(fixture_entry):
    run = node(fixture_entry, "sub run")
    _scopes, values = defaults(run)
    values["c__value"] = "hello"
    values["c__flag"] = False
    parsed = parse_command(run, values)
    assert parsed.errors == {}
    assert "--no-flag" in parsed.argv
    assert "--flag" not in parsed.argv


def test_count_option_repeats(fixture_entry):
    echo = node(fixture_entry, "echo")
    _scopes, values = defaults(echo)
    values["c__text"] = "x"
    values["g0__verbose"] = 2
    parsed = parse_command(echo, values)
    assert parsed.errors == {}
    assert parsed.argv.count("--verbose") == 2


def test_multiple_choice_and_multiple_values(fixture_entry):
    run = node(fixture_entry, "sub run")
    _scopes, values = defaults(run)
    values["c__value"] = "hello"
    values["c__tag"] = ["x", "y"]
    values["c__pair"] = ["alice", "3"]
    parsed = parse_command(run, values)
    assert parsed.errors == {}
    assert parsed.argv.count("--tag=x") == 1
    assert "--tag=y" in parsed.argv
    assert "--pair=alice" in parsed.argv
    assert parsed.argv[parsed.argv.index("--pair=alice") + 1] == "3"


def test_choice_and_range_validation(fixture_entry):
    run = node(fixture_entry, "sub run")
    _scopes, values = defaults(run)
    values["c__value"] = "hello"
    values["c__mode"] = "z"
    values["c__level"] = 99
    values["c__ratio"] = 3.0
    parsed = parse_command(run, values)
    assert set(parsed.errors) == {"c__mode", "c__level", "c__ratio"}
    assert "可选值" in parsed.errors["c__mode"]


def test_choice_is_case_insensitive(fixture_entry):
    run = node(fixture_entry, "sub run")
    _scopes, values = defaults(run)
    values["c__value"] = "hello"
    values["c__mode"] = "B"
    parsed = parse_command(run, values)
    assert parsed.errors == {}
    assert parsed.field_values["c__mode"] == "b"
    assert "--mode=b" in parsed.argv


def test_datetime_and_invalid_datetime(fixture_entry):
    run = node(fixture_entry, "sub run")
    _scopes, values = defaults(run)
    values["c__value"] = "hello"
    values["c__when"] = "2026-11-07 12:30:00"
    parsed = parse_command(run, values)
    assert parsed.errors == {}
    assert "--when=2026-11-07 12:30:00" in parsed.argv

    values["c__when"] = "not-a-date"
    parsed = parse_command(run, values)
    assert "c__when" in parsed.errors


def test_required_parameter(fixture_entry):
    needs = node(fixture_entry, "needs")
    _scopes, values = defaults(needs)
    parsed = parse_command(needs, values)
    assert "c__token" in parsed.errors
    values["c__token"] = "abc"
    parsed = parse_command(needs, values)
    assert parsed.errors == {}
    assert parsed.argv[-1] == "--token=abc"


def test_path_and_file_checks_use_app_cwd(fixture_entry, tmp_path):
    target = tmp_path / "sample.txt"
    target.write_text("content", encoding="utf-8")

    check = node(fixture_entry, "checkpath")
    _scopes, values = defaults(check)
    values["c__path"] = "sample.txt"
    parsed = parse_command(check, values, cwd=str(tmp_path))
    assert parsed.errors == {}
    assert parsed.argv[-1] == "sample.txt"

    values["c__path"] = "missing.txt"
    parsed = parse_command(check, values, cwd=str(tmp_path))
    assert "c__path" in parsed.errors

    read = node(fixture_entry, "readfile")
    _scopes, values = defaults(read)
    values["c__source"] = "sample.txt"
    parsed = parse_command(read, values, cwd=str(tmp_path))
    assert parsed.errors == {}
    values["c__source"] = "missing.txt"
    parsed = parse_command(read, values, cwd=str(tmp_path))
    assert "c__source" in parsed.errors


def test_negative_positional_argument_gets_terminator(fixture_entry):
    echo = node(fixture_entry, "echo")
    _scopes, values = defaults(echo)
    values["c__text"] = "-dash"
    parsed = parse_command(echo, values)
    assert parsed.errors == {}
    assert parsed.argv[-2:] == ["--", "-dash"]


def test_preview_contains_root_name(fixture_entry):
    echo = node(fixture_entry, "echo")
    _scopes, values = defaults(echo)
    values["c__text"] = "hi"
    parsed = parse_command(echo, values)
    text = argv_preview("fixture", parsed.argv)
    assert text.startswith("fixture")
    assert "--root-name=root" in text


def test_build_argv_returns_list(fixture_entry):
    echo = node(fixture_entry, "echo")
    _scopes, values = defaults(echo)
    values["c__text"] = "hi"
    parsed = parse_command(echo, values)
    assert build_argv(parsed) == parsed.argv


def test_datetime_normalisation_matches_click_formats(fixture_entry):
    run = node(fixture_entry, "sub run")
    _scopes, values = defaults(run)
    values["c__value"] = "hello"
    values["c__when"] = datetime(2026, 11, 7, 12, 30).isoformat(sep=" ")
    parsed = parse_command(run, values)
    assert parsed.errors == {}
    assert parsed.field_values["c__when"] == "2026-11-07 12:30:00"
