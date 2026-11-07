from __future__ import annotations

import os

from cliui.execute.runner import execute_command


def test_success_separates_stdout_and_stderr(fixture_entry):
    before = os.getcwd()
    result = execute_command(fixture_entry, ["warn"])
    assert result.status == "success"
    assert result.exit_code == 0
    assert "to-stdout\n" in result.stdout
    assert result.stderr == "to-stderr\n"
    assert result.exception == ""
    assert os.getcwd() == before


def test_unexpected_exception_keeps_traceback(fixture_entry):
    result = execute_command(fixture_entry, ["boom"])
    assert result.status == "failed"
    assert result.exit_code == 1
    assert "RuntimeError" in result.exception
    assert "boom" in result.exception
    assert result.message.startswith("RuntimeError")


def test_click_exception_is_friendly(fixture_entry):
    result = execute_command(fixture_entry, ["needs"])
    assert result.status == "failed"
    assert result.exit_code == 2
    assert result.exception == ""
    assert "Missing option" in result.stderr
    assert "Missing option" in result.message


def test_abort_is_reported(fixture_entry):
    result = execute_command(fixture_entry, ["abort"])
    assert result.status == "failed"
    assert "Abort" in result.message
    assert "Abort" in result.stderr


def test_nonzero_system_exit(fixture_entry):
    result = execute_command(fixture_entry, ["code"])
    assert result.status == "failed"
    assert result.exit_code == 7
    assert "退出码 7" in result.message


def test_output_is_truncated(fixture_entry):
    result = execute_command(fixture_entry, ["big", "--size=500"], max_output_chars=100)
    assert result.status == "success"
    assert result.truncated
    assert "已截断" in result.stdout
    assert len(result.stdout) < 200
    fields = result.to_fields(
        command_label="big", argv_label="fixture big", record_id=12
    )
    assert fields["result_record_id"] == 12
    assert fields["result_truncated"] is True
    assert fields["result_status"] == "success"


def test_cwd_is_restored_even_after_failure(fixture_entry):
    before = os.getcwd()
    execute_command(fixture_entry, ["boom"])
    assert os.getcwd() == before
