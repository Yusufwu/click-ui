from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from cliui.cli import main


FIXTURE_APPS = Path(__file__).parent / "fixtures" / "apps.py"


def test_tree_outputs_json():
    runner = CliRunner()
    result = runner.invoke(main, ["tree", f"{FIXTURE_APPS}:fixture", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["app"] == "fixture"
    assert payload["nodes"][0]["node_id"] == "n0"
    assert any(item["name"] == "echo" for item in payload["nodes"])


def test_tree_text_output():
    runner = CliRunner()
    result = runner.invoke(main, ["tree", f"{FIXTURE_APPS}:fixture"])
    assert result.exit_code == 0
    assert "fixture" in result.output
    assert "verbose" in result.output


def test_serve_requires_an_app():
    runner = CliRunner()
    result = runner.invoke(main, ["serve"])
    assert result.exit_code == 2
    assert "至少需要一个 Click 应用" in result.output


def test_bad_spec_is_reported():
    runner = CliRunner()
    result = runner.invoke(main, ["tree", "not-a-spec"])
    assert result.exit_code == 2
    assert "缺少属性名" in result.output


def test_user_add_and_list(tmp_path):
    data_dir = str(tmp_path / "data")
    runner = CliRunner()
    result = runner.invoke(
        main, ["user", "add", "alice", "secret1", "--data-dir", data_dir]
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(main, ["user", "list", "--data-dir", data_dir])
    assert result.exit_code == 0
    assert "alice" in result.output
    assert "普通用户" in result.output
