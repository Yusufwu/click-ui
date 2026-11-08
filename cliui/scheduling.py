"""Cron / one-off scheduling for registered Click applications.

This module deliberately does not import Flask: the same service powers
``cliui serve --scheduler`` (a background thread inside the web process) and
``cliui scheduler`` (a standalone process for production deployments).
"""

from __future__ import annotations

import typing as t
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from cliui.execute.runner import execute_command
from cliui.model import AppEntry, CommandInfo
from cliui.storage.repo import Store, schedule_items


DEFAULT_TIMEZONE = "Asia/Shanghai"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
MANUAL_TRIGGER = "manual"
SCHEDULE_TRIGGER = "schedule"

CRON_PRESETS: t.List[t.Tuple[str, str]] = [
    ("每小时整点", "0 * * * *"),
    ("每天 02:00", "0 2 * * *"),
    ("每周一 09:00", "0 9 * * 1"),
    ("每月 1 日 03:00", "0 3 1 * *"),
]


def get_timezone(name: t.Optional[str]) -> ZoneInfo:
    text = (name or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"未知时区: {text}（请使用 IANA 名称，例如 Asia/Shanghai）") from exc


def format_time(value: datetime) -> str:
    return value.strftime(TIME_FORMAT)


def parse_time(text: str, tz: ZoneInfo) -> datetime:
    value = (text or "").strip().replace("T", " ")
    for fmt in (TIME_FORMAT, "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=tz)
        except ValueError:
            continue
    raise ValueError(f"时间格式不正确: {text}（示例：2026-11-08 09:00:00）")


def normalize_cron(expression: str) -> str:
    text = (expression or "").strip()
    if not text:
        raise ValueError("Cron 表达式不能为空")
    try:
        # Validates the five fields (minute hour day month day_of_week).
        CronTrigger.from_crontab(text)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"Cron 表达式不合法: {text}（需要 5 段：分 时 日 月 周，例如 0 2 * * *）"
        ) from exc
    return " ".join(text.split())


def validate_schedule(
    *,
    trigger_type: str,
    cron: t.Optional[str],
    run_at: t.Optional[str],
    timezone: t.Optional[str],
) -> t.Tuple[t.Optional[str], t.Optional[str], str]:
    """Validate user input and return ``(cron, run_at, timezone)``."""
    tz_name = (timezone or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
    get_timezone(tz_name)
    kind = (trigger_type or "cron").strip().lower()
    if kind in ("once", "date", "single", "run_at"):
        text = (run_at or "").strip()
        if not text:
            raise ValueError("单次执行需要填写运行时间")
        tz = get_timezone(tz_name)
        return None, format_time(parse_time(text, tz)), tz_name
    if kind != "cron":
        raise ValueError("触发方式只能是 cron 或 once")
    text = (cron or "").strip()
    if not text:
        raise ValueError("周期执行需要填写 Cron 表达式")
    return normalize_cron(text), None, tz_name


def build_trigger(
    *,
    cron: t.Optional[str],
    run_at: t.Optional[str],
    timezone: t.Optional[str],
) -> BaseTrigger:
    tz = get_timezone(timezone)
    if cron:
        return CronTrigger.from_crontab(cron, timezone=tz)
    if run_at:
        return DateTrigger(run_date=parse_time(run_at, tz), timezone=tz)
    raise ValueError("定时任务缺少 Cron 表达式或运行时间")


def next_fire_times(
    *,
    cron: t.Optional[str],
    run_at: t.Optional[str],
    timezone: t.Optional[str],
    count: int = 3,
    after: t.Optional[datetime] = None,
) -> t.List[str]:
    """Return the next ``count`` fire times without sleeping or scheduling."""
    trigger = build_trigger(cron=cron, run_at=run_at, timezone=timezone)
    tz = get_timezone(timezone)
    if after is None:
        after = datetime.now(tz)
    else:
        after = after.astimezone(tz)
    results: t.List[str] = []
    previous: t.Optional[datetime] = None
    cursor = after
    while len(results) < count:
        fire = trigger.get_next_fire_time(previous, cursor)
        if fire is None:
            break
        if fire < after:
            # ``DateTrigger`` reports a past run_date instead of ``None``.
            break
        results.append(format_time(fire))
        previous = fire
        cursor = fire
    return results


def next_fire_time(
    *,
    cron: t.Optional[str],
    run_at: t.Optional[str],
    timezone: t.Optional[str],
    after: t.Optional[datetime] = None,
) -> t.Optional[str]:
    times = next_fire_times(
        cron=cron, run_at=run_at, timezone=timezone, count=1, after=after
    )
    return times[0] if times else None


def next_fire_for_schedule(
    schedule: t.Dict[str, t.Any], *, after: t.Optional[datetime] = None
) -> t.Optional[str]:
    return next_fire_time(
        cron=schedule.get("cron"),
        run_at=schedule.get("run_at"),
        timezone=schedule.get("timezone"),
        after=after,
    )


def schedule_trigger(schedule: t.Dict[str, t.Any]) -> BaseTrigger:
    return build_trigger(
        cron=schedule.get("cron"),
        run_at=schedule.get("run_at"),
        timezone=schedule.get("timezone"),
    )


def resolve_node(entry: AppEntry, command_path: str) -> t.Optional[CommandInfo]:
    """Resolve a stored command path against a freshly loaded command tree."""
    for node in entry.nodes.values():
        if node.display_path() == command_path and node.executable:
            return node
    return None


def run_schedule_once(
    store: Store,
    apps_by_name: t.Dict[str, AppEntry],
    schedule: t.Dict[str, t.Any],
    *,
    max_output_chars: int = 200_000,
    wait_seconds: t.Optional[float] = 0.0,
) -> t.Tuple[str, t.Optional[int]]:
    """Execute every command in a schedule and persist one record per item."""
    user_id = int(schedule.get("created_by") or 0)
    username = str(schedule.get("created_by_name") or "")
    schedule_id = int(schedule.get("id") or 0)
    items = schedule_items(schedule)

    def record(
        item: t.Dict[str, t.Any],
        status: str,
        exit_code: t.Optional[int],
        stdout: str,
        stderr: str,
        exception: str,
        duration_ms: int,
        resolved_argv: t.List[str],
    ) -> int:
        return store.record_execution(
            user_id=user_id,
            username=username,
            app=str(item.get("app_name") or ""),
            command_id="",
            command_path=str(item.get("command_path") or ""),
            params=item.get("params") or {},
            argv=resolved_argv,
            argv_label=str(item.get("argv_label") or ""),
            status=status,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            exception=exception,
            duration_ms=duration_ms,
            trigger=SCHEDULE_TRIGGER,
            schedule_id=schedule_id,
        )

    statuses: t.List[str] = []
    last_execution_id: t.Optional[int] = None
    for item in items:
        app_name = str(item.get("app_name") or "")
        command_path = str(item.get("command_path") or "")
        argv = [str(arg) for arg in (item.get("argv") or [])]
        entry = apps_by_name.get(app_name)
        if entry is None:
            last_execution_id = record(
                item,
                "failed",
                None,
                "",
                "",
                f"应用未注册或已被移除: {app_name}",
                0,
                argv,
            )
            statuses.append("failed")
            continue
        if resolve_node(entry, command_path) is None:
            last_execution_id = record(
                item,
                "failed",
                None,
                "",
                "",
                f"命令不存在或已不可执行: {command_path}",
                0,
                argv,
            )
            statuses.append("failed")
            continue

        result = execute_command(
            entry, argv, max_output_chars=max_output_chars, wait_seconds=wait_seconds
        )
        exception = result.exception
        if not exception and result.status in ("failed", "skipped"):
            exception = result.message
        last_execution_id = record(
            item,
            result.status,
            result.exit_code,
            result.stdout,
            result.stderr,
            exception,
            result.duration_ms,
            result.argv,
        )
        statuses.append(result.status)

    if "failed" in statuses:
        overall = "failed"
    elif "skipped" in statuses:
        overall = "skipped"
    elif statuses:
        overall = "success"
    else:
        overall = "failed"
    return overall, last_execution_id


class SchedulerService:
    """APScheduler wrapper that loads its jobs from the SQLite schedule table."""

    JOB_PREFIX = "cliui-schedule-"

    def __init__(
        self,
        *,
        store: Store,
        apps_by_name: t.Dict[str, AppEntry],
        max_output_chars: int = 200_000,
        wait_seconds: float = 0.0,
        blocking: bool = False,
        log: t.Optional[t.Callable[[str], None]] = None,
    ) -> None:
        self.store = store
        self.apps_by_name = apps_by_name
        self.max_output_chars = max_output_chars
        self.wait_seconds = wait_seconds
        self._log = log or (lambda _message: None)
        scheduler_class = BlockingScheduler if blocking else BackgroundScheduler
        self.scheduler = scheduler_class(
            timezone=get_timezone(DEFAULT_TIMEZONE),
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 60},
        )

    # ---------------------------------------------------------------- public
    def start(self) -> None:
        self.recover_missed()
        self.sync()
        self.scheduler.start()

    def shutdown(self, wait: bool = False) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=wait)

    def sync(self) -> None:
        """Rebuild every job from the database (called after UI changes)."""
        for job in self.scheduler.get_jobs():
            if job.id.startswith(self.JOB_PREFIX):
                try:
                    self.scheduler.remove_job(job.id)
                except Exception:  # noqa: BLE001 - already fired or removed
                    pass
        now = datetime.now(get_timezone(DEFAULT_TIMEZONE))
        for row in self.store.enabled_schedules():
            next_value = row.get("next_run_at")
            if not next_value or next_value < format_time(now):
                next_value = next_fire_for_schedule(row, after=now)
                if not next_value:
                    # A one-off schedule whose time has already passed.
                    self.store.set_schedule_enabled(int(row["id"]), False, None)
                    continue
                self.store.update_schedule_next_run(int(row["id"]), next_value)
            try:
                trigger = schedule_trigger(row)
            except ValueError as exc:
                self._log(f"定时任务 #{row['id']} 配置无效，已跳过：{exc}")
                continue
            self.scheduler.add_job(
                self._fire,
                trigger=trigger,
                args=[int(row["id"])],
                id=f"{self.JOB_PREFIX}{row['id']}",
                name=f"{row.get('app_name')} · {row.get('command_path')}",
                replace_existing=True,
            )

    def recover_missed(self) -> None:
        """Handle fires that passed while no scheduler process was running."""
        now = datetime.now(get_timezone(DEFAULT_TIMEZONE))
        for row in self.store.enabled_schedules():
            stored = row.get("next_run_at")
            if not stored:
                continue
            try:
                due = parse_time(stored, get_timezone(row.get("timezone")))
            except ValueError:
                due = None
            if due is None or due > now:
                continue
            schedule_id = int(row["id"])
            next_value = next_fire_for_schedule(row, after=now)
            if row.get("catch_up"):
                claimed = self.store.claim_schedule_run(
                    schedule_id,
                    expected_next_run_at=stored,
                    next_run_at=next_value,
                    now=format_time(now),
                )
                if not claimed:
                    continue
                status, execution_id = run_schedule_once(
                    self.store,
                    self.apps_by_name,
                    row,
                    max_output_chars=self.max_output_chars,
                    wait_seconds=self.wait_seconds,
                )
                self.store.finish_schedule_run(
                    schedule_id,
                    status=status,
                    execution_id=execution_id,
                    next_run_at=next_value,
                    enabled=next_value is not None,
                )
                self._log(
                    f"定时任务 #{schedule_id} 停机期间错过，已补跑一次（{status}）"
                )
            else:
                self.store.mark_schedule_missed(schedule_id, next_value)
                if next_value is None:
                    self.store.set_schedule_enabled(schedule_id, False, None)
                self._log(f"定时任务 #{schedule_id} 停机期间错过，已标记 missed")

    # --------------------------------------------------------------- internal
    def _fire(self, schedule_id: int) -> None:
        row = self.store.get_schedule(schedule_id)
        if not row or not row.get("enabled"):
            return
        tz = get_timezone(row.get("timezone"))
        now = datetime.now(tz)
        try:
            trigger = schedule_trigger(row)
            fire = trigger.get_next_fire_time(None, now)
        except ValueError as exc:
            self._log(f"定时任务 #{schedule_id} 配置无效：{exc}")
            return
        # DateTrigger reports the run date even after it has passed.
        next_value = format_time(fire) if fire is not None and fire >= now else None
        claimed = self.store.claim_schedule_run(
            schedule_id,
            expected_next_run_at=row.get("next_run_at"),
            next_run_at=next_value,
            now=format_time(now),
        )
        if not claimed:
            # Another process (or an earlier fire) already handled this slot.
            return
        status, execution_id = run_schedule_once(
            self.store,
            self.apps_by_name,
            row,
            max_output_chars=self.max_output_chars,
            wait_seconds=self.wait_seconds,
        )
        self.store.finish_schedule_run(
            schedule_id,
            status=status,
            execution_id=execution_id,
            next_run_at=next_value,
            enabled=next_value is not None,
        )
        self._log(f"定时任务 #{schedule_id} 执行完成：{status}")


def next_fire_preview_message(times: t.List[str]) -> str:
    if not times:
        return "该设置没有未来的触发时间（单次任务时间已过？）"
    return "未来触发时间：" + "，".join(times)
