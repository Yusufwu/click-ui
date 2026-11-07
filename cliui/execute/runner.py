"""Execute a Click command in-process through ``click.testing.CliRunner``.

Click itself is never modified: the command tree is only read, and execution is
handed to the normal Click entry point with an argv list.
"""

from __future__ import annotations

import os
import threading
import time
import traceback
import typing as t
from dataclasses import dataclass

import click
from click.testing import CliRunner

from cliui.model import AppEntry


# Click commands may use process-global state (cwd, stdout, signals).  Running
# one at a time keeps those interactions predictable and avoids chdir races.
_EXEC_LOCK = threading.Lock()

STATUS_LABELS = {
    "success": "执行成功",
    "failed": "执行失败",
    "preview": "命令预览（未执行）",
    "queued": "已加入记录队列",
    "skipped": "已跳过（执行锁被占用）",
}


@dataclass
class ExecutionResult:
    status: str
    exit_code: t.Optional[int]
    stdout: str
    stderr: str
    exception: str
    duration_ms: int
    argv: t.List[str]
    message: str = ""
    exception_type: str = ""
    truncated: bool = False

    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)

    def duration_label(self) -> str:
        if self.duration_ms < 1000:
            return f"{self.duration_ms} ms"
        return f"{self.duration_ms / 1000:.2f} s"

    def to_fields(
        self,
        *,
        command_label: str,
        argv_label: str,
        record_id: t.Optional[int] = None,
    ) -> t.Dict[str, t.Any]:
        """Fields understood by the AMIS result panel."""
        return {
            "result_status": self.status,
            "result_status_label": self.status_label(),
            "result_exit_code": "-" if self.exit_code is None else self.exit_code,
            "result_duration_label": self.duration_label(),
            "result_command_label": command_label,
            "result_message": self.message,
            "result_record_id": record_id,
            "result_truncated": self.truncated,
            "result_truncated_note": (
                "输出内容过长，已截断保存。请缩小输出范围后重新执行以查看完整内容。"
                if self.truncated
                else ""
            ),
            "result_argv": argv_label,
            "result_stdout": self.stdout,
            "result_stderr": self.stderr,
            "result_exception": self.exception,
        }


def _truncate(text: str, limit: int) -> t.Tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    marker = f"\n... [输出超过 {limit} 个字符，已截断]"
    return text[:limit] + marker, True


def _stderr_summary(stderr: str) -> str:
    """Pick the most useful line from Click's stderr output."""
    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]
    for line in reversed(lines):
        if line.startswith("Error:"):
            return line[len("Error:") :].strip()
    return lines[-1] if lines else ""


def _exception_message(
    exc: t.Optional[BaseException], exit_code: int, stderr: str = ""
) -> str:
    """Human readable description of how the command ended.

    Under ``standalone_mode`` Click turns ``ClickException`` / ``Abort`` into
    ``SystemExit`` and writes the real message to stderr, so stderr is
    consulted before falling back to a plain exit code.
    """
    code = exit_code
    if isinstance(exc, SystemExit):
        code = exc.code if exc.code is not None else exit_code
    if code == 0:
        return "命令执行成功"
    if isinstance(exc, click.exceptions.Abort) or "Aborted!" in (stderr or ""):
        return "命令被中止（Aborted）"
    if isinstance(exc, click.exceptions.ClickException):
        try:
            return _truncate(exc.format_message(), 200)[0]
        except Exception:
            return str(exc)
    if exc is not None and not isinstance(exc, SystemExit):
        return _truncate(f"{type(exc).__name__}: {exc}", 200)[0]
    summary = _stderr_summary(stderr)
    if summary:
        return _truncate(summary, 200)[0]
    return f"命令以退出码 {code} 结束"


def _exception_traceback(exc: t.Optional[BaseException]) -> str:
    if exc is None:
        return ""
    if isinstance(exc, (click.exceptions.ClickException, click.exceptions.Abort, SystemExit)):
        return ""
    return "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    ).strip()


def execute_command(
    entry: AppEntry,
    argv: t.Sequence[str],
    *,
    max_output_chars: int = 200_000,
    wait_seconds: t.Optional[float] = None,
) -> ExecutionResult:
    """Run ``entry.cli`` with ``argv`` inside the application directory.

    ``wait_seconds`` is only used by the scheduler: web requests wait for the
    execution lock, while a scheduled fire can give up and be recorded as
    ``skipped`` instead of blocking the next job.
    """
    args = [str(item) for item in argv]
    started = time.perf_counter()

    if wait_seconds is None:
        acquired = _EXEC_LOCK.acquire()
    else:
        acquired = _EXEC_LOCK.acquire(timeout=max(0.0, float(wait_seconds)))
    if not acquired:
        return ExecutionResult(
            status="skipped",
            exit_code=None,
            stdout="",
            stderr="",
            exception="",
            duration_ms=0,
            argv=args,
            message="另一个命令正在执行，本次定时执行已跳过。",
            exception_type="ExecutionLockBusy",
        )

    try:
        previous = os.getcwd()
        try:
            try:
                os.chdir(entry.cwd)
            except OSError as exc:
                return ExecutionResult(
                    status="failed",
                    exit_code=None,
                    stdout="",
                    stderr="",
                    exception="",
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    argv=args,
                    message=f"无法切换到应用目录 {entry.cwd}: {exc}",
                    exception_type=type(exc).__name__,
                )

            runner = CliRunner(mix_stderr=False)
            try:
                result = runner.invoke(
                    entry.cli,
                    args,
                    catch_exceptions=True,
                    standalone_mode=True,
                    color=False,
                )
            except Exception as exc:  # CliRunner should already catch this
                duration = int((time.perf_counter() - started) * 1000)
                return ExecutionResult(
                    status="failed",
                    exit_code=None,
                    stdout="",
                    stderr="",
                    exception="".join(
                        traceback.format_exception(type(exc), exc, exc.__traceback__)
                    ).strip(),
                    duration_ms=duration,
                    argv=args,
                    message=f"{type(exc).__name__}: {exc}",
                    exception_type=type(exc).__name__,
                )
        finally:
            try:
                os.chdir(previous)
            except OSError:
                pass
    finally:
        _EXEC_LOCK.release()

    duration = int((time.perf_counter() - started) * 1000)
    stdout, out_cut = _truncate(result.stdout or "", max_output_chars)
    stderr, err_cut = _truncate(result.stderr or "", max_output_chars)
    exception_text, exc_cut = _truncate(
        _exception_traceback(result.exception), max_output_chars
    )

    exit_code = result.exit_code
    exc = result.exception
    # ``SystemExit(0)`` is a normal way for Click commands to finish.
    failed = exit_code != 0 or (
        exc is not None and not isinstance(exc, SystemExit)
    )
    if isinstance(exc, SystemExit) and exc.code == 0:
        failed = False
    if exit_code == 0 and exc is None:
        failed = False

    return ExecutionResult(
        status="failed" if failed else "success",
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        exception=exception_text,
        duration_ms=duration,
        argv=args,
        message=_exception_message(exc, exit_code, stderr),
        exception_type=type(exc).__name__ if exc is not None else "",
        truncated=out_cut or err_cut or exc_cut,
    )
