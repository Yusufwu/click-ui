"""Flask application factory: pages, APIs, authentication and execution."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import typing as t
import uuid
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote

from flask import (
    Flask,
    Response,
    abort,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from cliui.config import ServeConfig
from cliui.execute.runner import ExecutionResult, execute_command
from cliui.model import AppEntry, CommandInfo
from cliui.registry import AppLoadError, reload_app_entry
from cliui.scheduling import (
    SchedulerService,
    describe_cron,
    next_fire_for_schedule,
    next_fire_preview_message,
    next_fire_time,
    next_fire_times,
    run_schedule_once,
    validate_schedule,
)
from cliui.schema.argv import argv_preview, parse_command
from cliui.storage.repo import Store, schedule_items, summarize_params
from cliui.web.auth import api_login_required, load_user, login_required
from cliui.web.pages import (
    STATUS_LABELS,
    build_batch_detail_page,
    build_batches_page,
    build_error_page,
    build_index_page,
    build_queue_page,
    build_record_detail_page,
    build_records_page,
    build_overview_page,
    build_schedule_detail_page,
    build_schedules_page,
)


MAX_PAGE_SIZE = 200


def _json_script(payload: t.Any) -> str:
    text = json.dumps(payload, ensure_ascii=False)
    # ``<\/`` is a valid JSON escape and cannot break out of the script tag.
    return text.replace("</", "<\\/")


def _int_arg(name: str, default: int, maximum: int = MAX_PAGE_SIZE) -> int:
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(1, min(maximum, value))


def _payload() -> t.Dict[str, t.Any]:
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    if request.form:
        return {key: value for key, value in request.form.items()}
    return {}


def _restore_mirrors(data: t.Dict[str, t.Any]) -> t.Dict[str, t.Any]:
    """Copy ``mirror__<name>`` values (sent by the schedule dialog) back."""
    for key in list(data.keys()):
        if not key.startswith("mirror__"):
            continue
        target = key[len("mirror__"):]
        data.setdefault(target, data[key])
    return data


def _safe_filename(name: str) -> str:
    base = os.path.basename((name or "upload.bin").replace("\\", "/"))
    base = re.sub(r"[^\w.\- ()\[\]]+", "_", base, flags=re.UNICODE)
    base = base.strip(" .")
    return base or "upload.bin"


def _truthy(value: t.Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in ("1", "true", "yes", "on", "y")


def _command_label(node: CommandInfo) -> str:
    return node.display_path()


def _exception_for_storage(result: ExecutionResult) -> str:
    if result.exception:
        return result.exception
    if result.status == "failed":
        return result.message
    return ""


def _status_payload(
    *,
    ok: bool,
    msg: str = "",
    data: t.Optional[t.Dict[str, t.Any]] = None,
    errors: t.Optional[t.Dict[str, str]] = None,
    http_status: int = 200,
) -> Response:
    body: t.Dict[str, t.Any] = {"status": 0 if ok else 1, "msg": msg}
    if data is not None:
        body["data"] = data
    if errors:
        body["status"] = 422
        body["errors"] = errors
    return jsonify(body), http_status


def create_app(
    *,
    entries: t.List[AppEntry],
    store: Store,
    config: ServeConfig,
    secret_key: t.Optional[str] = None,
    scheduler: t.Optional[SchedulerService] = None,
) -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static",
    )
    app.secret_key = secret_key or config.secret_key
    app.config.update(
        MAX_CONTENT_LENGTH=config.max_upload_bytes,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_NAME="cliui_session",
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    )

    apps_by_name: t.Dict[str, AppEntry] = {entry.name: entry for entry in entries}
    if scheduler is not None:
        # The reload endpoint replaces the dict contents in place, so the
        # scheduler shares the same mapping and always sees fresh entries.
        scheduler.apps_by_name = apps_by_name

    app.before_request(load_user(store))

    # ------------------------------------------------------------------ helpers
    def current_user() -> t.Dict[str, t.Any]:
        return g.user

    def queue_count() -> int:
        user = g.user
        return store.queue_count(user["id"]) if user else 0

    def pick_app(name: t.Optional[str]) -> t.Optional[AppEntry]:
        if name:
            return apps_by_name.get(name)
        return entries[0] if entries else None

    def render_page(page: t.Dict[str, t.Any], title: str = "Click UI") -> str:
        return render_template(
            "index.html", page_json=_json_script(page), title=title
        )

    def page_error(
        message: str,
        *,
        status: int = 404,
        entry: t.Optional[AppEntry] = None,
        http_status: t.Optional[int] = None,
    ) -> t.Tuple[str, int]:
        page = build_error_page(
            entries,
            entry,
            current_user(),
            queue_count(),
            message,
            status,
        )
        return render_page(page, f"{status} · {message}"), http_status or status

    def api_error(message: str, http_status: int = 400) -> Response:
        return _status_payload(ok=False, msg=message, http_status=http_status)

    def entry_for(data: t.Dict[str, t.Any]) -> t.Optional[AppEntry]:
        return pick_app(str(data.get("_cliui_app") or ""))

    def node_for(
        entry: AppEntry, data: t.Dict[str, t.Any]
    ) -> t.Optional[CommandInfo]:
        node_id = str(data.get("_cliui_command") or "")
        if not node_id:
            return None
        return entry.resolve(node_id)

    def parsed_for(
        entry: AppEntry, node: CommandInfo, data: t.Dict[str, t.Any]
    ) -> t.Any:
        return parse_command(node, data, cwd=entry.cwd)

    def result_fields_for_app(
        entry: AppEntry,
        result: ExecutionResult,
        node: CommandInfo,
        record_id: t.Optional[int] = None,
    ) -> t.Dict[str, t.Any]:
        root_name = entry.root.name if entry.root else entry.name
        return result.to_fields(
            command_label=_command_label(node),
            argv_label=argv_preview(root_name, result.argv),
            record_id=record_id,
        )

    def save_execution(
        entry: AppEntry,
        node: CommandInfo,
        field_values: t.Dict[str, t.Any],
        result: ExecutionResult,
        *,
        batch_id: t.Optional[int] = None,
        batch_index: t.Optional[int] = None,
    ) -> int:
        root_name = entry.root.name if entry.root else entry.name
        return store.record_execution(
            user_id=g.user["id"],
            username=g.user["username"],
            app=entry.name,
            command_id=node.node_id,
            command_path=_command_label(node),
            params=field_values,
            argv=result.argv,
            argv_label=argv_preview(root_name, result.argv),
            status=result.status,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            exception=_exception_for_storage(result),
            duration_ms=result.duration_ms,
            batch_id=batch_id,
            batch_index=batch_index,
        )

    def run_in_background(
        entry: AppEntry,
        argv: t.List[str],
        record_id: int,
    ) -> None:
        """Execute after the HTTP response; the record starts as ``running``."""

        def worker() -> None:
            try:
                result = execute_command(
                    entry, argv, max_output_chars=config.max_output_chars
                )
                exception_text = _exception_for_storage(result)
            except Exception as exc:  # noqa: BLE001 - never lose the record
                result = ExecutionResult(
                    status="failed",
                    exit_code=None,
                    stdout="",
                    stderr="",
                    exception=f"{type(exc).__name__}: {exc}",
                    duration_ms=0,
                    argv=list(argv),
                    message=f"{type(exc).__name__}: {exc}",
                )
                exception_text = result.exception
            try:
                store.update_execution_result(
                    record_id,
                    status=result.status,
                    exit_code=result.exit_code,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    exception=exception_text,
                    duration_ms=result.duration_ms,
                )
            except Exception:  # noqa: BLE001 - log and keep serving
                app.logger.exception("后台执行结果写入失败 #%s", record_id)

        threading.Thread(
            target=worker, name=f"cliui-exec-{record_id}", daemon=True
        ).start()

    def require_owned(row: t.Dict[str, t.Any]) -> None:
        if not g.user.get("is_admin") and row["user_id"] != g.user["id"]:
            abort(403)

    def require_schedule_owned(row: t.Dict[str, t.Any]) -> None:
        if not g.user.get("is_admin") and int(row["created_by"]) != int(g.user["id"]):
            abort(403)

    def sync_scheduler() -> None:
        if scheduler is None:
            return
        try:
            scheduler.sync()
        except Exception:  # noqa: BLE001 - a page action must not fail on resync
            app.logger.exception("scheduler resync failed")

    # -------------------------------------------------------------------- auth
    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = ""
        next_url = request.values.get("next", "/")
        next_url = next_url if next_url.startswith("/") and not next_url.startswith("//") else "/"
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            user = store.authenticate(username, password) if username else None
            if user is None:
                error = "用户名或密码不正确"
            else:
                session.clear()
                session["user_id"] = int(user["id"])
                session.permanent = True
                return redirect(next_url)
        if g.user is not None and request.method == "GET":
            return redirect("/")
        return render_template(
            "login.html",
            error=error,
            next_url=next_url,
            has_users=store.count_users() > 0,
        )

    @app.get("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ------------------------------------------------------------------- pages
    @app.get("/")
    @login_required
    def index():
        entry = pick_app(request.args.get("app"))
        if entry is None:
            return page_error("还没有注册任何 Click 应用。", status=500, http_status=500)

        selected = entry.resolve(request.args.get("cmd"))
        initial_values: t.Optional[t.Dict[str, t.Any]] = None

        record_id = request.args.get("record")
        if record_id:
            try:
                record = store.get_execution(int(record_id))
            except ValueError:
                record = None
            if record is None:
                return page_error("执行记录不存在", status=404, entry=entry)
            require_owned(record)
            try:
                initial_values = json.loads(record["params_json"] or "{}")
            except json.JSONDecodeError:
                initial_values = {}
            entry = pick_app(record["app"]) or entry
            selected = entry.resolve(record["command_id"])

        queue_item = request.args.get("queue_item")
        if queue_item:
            try:
                item = store.get_queue_item(int(queue_item), g.user["id"])
            except ValueError:
                item = None
            if item is None:
                return page_error("队列项不存在", status=404, entry=entry)
            try:
                initial_values = json.loads(item["params_json"] or "{}")
            except json.JSONDecodeError:
                initial_values = {}
            entry = pick_app(item["app"]) or entry
            selected = entry.resolve(item["command_id"])

        if request.args.get("cmd") and selected is None:
            return page_error("命令不存在或尚未注册", status=404, entry=entry)

        page = build_index_page(
            entry,
            entries,
            g.user,
            queue_count(),
            selected,
            initial_values,
        )
        return render_page(page, f"{entry.display_name()} · 控制台")

    @app.get("/overview")
    @login_required
    def overview_page():
        entry = pick_app(request.args.get("app"))
        page = build_overview_page(
            entries,
            entry,
            g.user,
            queue_count(),
            query=request.args.get("q") or "",
            favorites=store.favorite_commands(g.user["id"]),
            recent=store.recent_commands(user_id=g.user["id"]),
        )
        return render_page(page, "命令总览")

    @app.post("/overview/favorite")
    @login_required
    def overview_favorite():
        app_name = (request.form.get("app") or "").strip()
        command_path = (request.form.get("path") or "").strip()
        if app_name and command_path:
            store.toggle_favorite(g.user["id"], app_name, command_path)
        query = (request.form.get("q") or "").strip()
        target = "/overview" + (f"?q={quote(query)}" if query else "")
        return redirect(target)

    @app.get("/records")
    @login_required
    def records_page():
        entry = pick_app(request.args.get("app"))
        page = build_records_page(entries, entry, g.user, queue_count())
        return render_page(page, "执行记录")

    @app.get("/records/<int:record_id>")
    @login_required
    def record_detail(record_id: int):
        record = store.get_execution(record_id)
        if record is None:
            return page_error("执行记录不存在", status=404)
        require_owned(record)
        entry = pick_app(record["app"])
        page = build_record_detail_page(record, entries, entry, g.user, queue_count())
        return render_page(page, f"执行记录 #{record_id}")

    @app.get("/queue")
    @login_required
    def queue_page():
        entry = pick_app(request.args.get("app"))
        page = build_queue_page(entries, entry, g.user, queue_count())
        return render_page(page, "记录队列")

    @app.get("/batches")
    @login_required
    def batches_page():
        entry = pick_app(request.args.get("app"))
        page = build_batches_page(entries, entry, g.user, queue_count())
        return render_page(page, "执行批次")

    @app.get("/schedules")
    @login_required
    def schedules_page():
        entry = pick_app(request.args.get("app"))
        page = build_schedules_page(entries, entry, g.user, queue_count())
        return render_page(page, "定时任务")

    @app.get("/schedules/<int:schedule_id>")
    @login_required
    def schedule_detail(schedule_id: int):
        row = store.get_schedule(schedule_id)
        if row is None:
            return page_error("定时任务不存在", status=404)
        require_schedule_owned(row)
        items = schedule_items(row)
        executions = store.schedule_executions(schedule_id)
        entry = pick_app(row.get("app_name"))
        page = build_schedule_detail_page(
            row, items, executions, entries, entry, g.user, queue_count()
        )
        return render_page(page, f"定时任务 #{schedule_id}")

    @app.post("/schedules/<int:schedule_id>/run")
    @login_required
    def schedule_run_form(schedule_id: int):
        row = store.get_schedule(schedule_id)
        if row is None:
            return page_error("定时任务不存在", status=404)
        require_schedule_owned(row)
        status, execution_id = run_schedule_once(
            store,
            apps_by_name,
            row,
            max_output_chars=config.max_output_chars,
            wait_seconds=None,
        )
        store.mark_schedule_result(
            schedule_id, status=status, execution_id=execution_id
        )
        return redirect(f"/schedules/{schedule_id}")

    @app.post("/schedules/<int:schedule_id>/toggle")
    @login_required
    def schedule_toggle_form(schedule_id: int):
        row = store.get_schedule(schedule_id)
        if row is None:
            return page_error("定时任务不存在", status=404)
        require_schedule_owned(row)
        enabled = _truthy(request.values.get("enabled"))
        next_value: t.Optional[str] = None
        if enabled:
            next_value = next_fire_for_schedule(row)
            if next_value is None:
                return page_error(
                    "该单次任务的时间已过，无法启用", status=400, entry=pick_app(row.get("app_name"))
                )
        store.set_schedule_enabled(schedule_id, enabled, next_value)
        sync_scheduler()
        return redirect(f"/schedules/{schedule_id}")

    @app.post("/schedules/<int:schedule_id>/duplicate")
    @login_required
    def schedule_duplicate_form(schedule_id: int):
        row = store.get_schedule(schedule_id)
        if row is None:
            return page_error("定时任务不存在", status=404)
        require_schedule_owned(row)
        next_value = next_fire_for_schedule(row)
        if next_value is None:
            return page_error(
                "该单次任务的时间已过，请先编辑计划时间再复制",
                status=400,
                entry=pick_app(row.get("app_name")),
            )
        new_id = store.duplicate_schedule(
            schedule_id,
            created_by=g.user["id"],
            created_by_name=g.user["username"],
            next_run_at=next_value,
        )
        sync_scheduler()
        if new_id is None:
            return page_error("定时任务不存在", status=404)
        return redirect(f"/schedules/{new_id}")

    @app.post("/schedules/<int:schedule_id>/items/<int:index>/remove")
    @login_required
    def schedule_item_remove_form(schedule_id: int, index: int):
        row = store.get_schedule(schedule_id)
        if row is None:
            return page_error("定时任务不存在", status=404)
        require_schedule_owned(row)
        if store.remove_schedule_item(schedule_id, index) is None:
            return page_error(
                "无法移除：索引越界，或计划至少需要保留一条命令",
                status=400,
                entry=pick_app(row.get("app_name")),
            )
        return redirect(f"/schedules/{schedule_id}")

    @app.get("/batches/")
    @login_required
    def latest_batch():
        rows, _total = store.list_batches(
            user_id=None if g.user.get("is_admin") else g.user["id"],
            page=1,
            per_page=1,
        )
        if rows:
            return redirect(f"/batches/{rows[0]['id']}")
        return redirect("/batches")

    @app.get("/batches/<int:batch_id>")
    @login_required
    def batch_detail(batch_id: int):
        batch = store.get_batch(batch_id)
        if batch is None:
            return page_error("执行批次不存在", status=404)
        require_owned(batch)
        items = store.batch_executions(batch_id)
        entry = pick_app(batch["app"])
        page = build_batch_detail_page(
            batch, items, entries, entry, g.user, queue_count()
        )
        return render_page(page, f"执行批次 #{batch_id}")

    # --------------------------------------------------------------------- APIs
    @app.post("/api/preview")
    @api_login_required
    def api_preview():
        data = _payload()
        entry = entry_for(data)
        if entry is None:
            return api_error("应用不存在", 404)
        node = node_for(entry, data)
        if node is None:
            return api_error("命令不存在", 404)
        parsed = parsed_for(entry, node, data)
        if parsed.errors:
            return _status_payload(
                ok=False,
                msg="表单校验未通过",
                errors=parsed.errors,
                http_status=200,
            )
        root_name = entry.root.name if entry.root else entry.name
        preview = ExecutionResult(
            status="preview",
            exit_code=None,
            stdout="",
            stderr="",
            exception="",
            duration_ms=0,
            argv=parsed.argv,
            message="参数已通过校验，命令尚未执行。",
        )
        return _status_payload(
            ok=True,
            msg="命令预览",
            data=result_fields_for_app(entry, preview, node),
        )

    @app.post("/api/execute")
    @api_login_required
    def api_execute():
        data = _payload()
        entry = entry_for(data)
        if entry is None:
            return api_error("应用不存在", 404)
        node = node_for(entry, data)
        if node is None:
            return api_error("命令不存在", 404)
        parsed = parsed_for(entry, node, data)
        if parsed.errors:
            return _status_payload(
                ok=False,
                msg="表单校验未通过",
                errors=parsed.errors,
                http_status=200,
            )

        if _truthy(data.get("background")):
            root_name = entry.root.name if entry.root else entry.name
            record_id = store.record_execution(
                user_id=g.user["id"],
                username=g.user["username"],
                app=entry.name,
                command_id=node.node_id,
                command_path=_command_label(node),
                params=parsed.field_values,
                argv=parsed.argv,
                argv_label=argv_preview(root_name, parsed.argv),
                status="running",
                exit_code=None,
                stdout="",
                stderr="",
                exception="",
                duration_ms=0,
            )
            run_in_background(entry, parsed.argv, record_id)
            running = ExecutionResult(
                status="running",
                exit_code=None,
                stdout="",
                stderr="",
                exception="",
                duration_ms=0,
                argv=parsed.argv,
                message="已在后台执行。长任务可以离开本页，稍后刷新执行记录查看结果。",
            )
            fields = result_fields_for_app(entry, running, node, record_id)
            fields["result_status_label"] = "执行中（后台）"
            fields["result_duration_label"] = "后台运行"
            return _status_payload(
                ok=True,
                msg=f"已提交后台执行（记录 #{record_id}）",
                data=fields,
            )

        result = execute_command(
            entry, parsed.argv, max_output_chars=config.max_output_chars
        )
        record_id = save_execution(entry, node, parsed.field_values, result)
        msg = "执行完成" if result.status == "success" else "执行结束（失败）"
        return _status_payload(
            ok=True,
            msg=msg,
            data=result_fields_for_app(entry, result, node, record_id),
        )

    @app.get("/api/records")
    @api_login_required
    def api_records():
        page = _int_arg("page", 1)
        per_page = _int_arg("perPage", 20)
        status = request.args.get("status") or None
        command = request.args.get("command") or None
        app_name = request.args.get("app") or None
        username = request.args.get("username") or None
        trigger = request.args.get("trigger") or None
        admin = bool(g.user.get("is_admin"))
        if not admin:
            username = None
        items, total = store.list_executions(
            user_id=None if admin else g.user["id"],
            page=page,
            per_page=per_page,
            app=app_name,
            command=command,
            status=status,
            username=username,
            trigger=trigger,
        )
        for item in items:
            item.pop("stdout", None)
            item.pop("stderr", None)
            item.pop("exception", None)
            item.pop("params_json", None)
        return jsonify({"status": 0, "msg": "", "data": {"items": items, "total": total}})

    @app.get("/api/executions/<int:execution_id>")
    @api_login_required
    def api_execution_status(execution_id: int):
        row = store.get_execution(execution_id)
        if row is None:
            return api_error("执行记录不存在", 404)
        require_owned(row)
        status = str(row.get("status") or "")
        return _status_payload(
            ok=True,
            msg="后台执行中" if status == "running" else "执行已结束",
            data={
                "id": row["id"],
                "status": status,
                "status_label": STATUS_LABELS.get(status, status),
                "exit_code": row.get("exit_code"),
                "duration_ms": row.get("duration_ms"),
                "stdout": row.get("stdout") or "",
                "stderr": row.get("stderr") or "",
                "exception": row.get("exception") or "",
                "created_at": row.get("created_at"),
            },
        )

    @app.get("/api/batches")
    @api_login_required
    def api_batches():
        page = _int_arg("page", 1)
        per_page = _int_arg("perPage", 20)
        admin = bool(g.user.get("is_admin"))
        items, total = store.list_batches(
            user_id=None if admin else g.user["id"],
            page=page,
            per_page=per_page,
        )
        return jsonify({"status": 0, "msg": "", "data": {"items": items, "total": total}})

    @app.get("/api/queue")
    @api_login_required
    def api_queue_list():
        page = _int_arg("page", 1)
        per_page = _int_arg("perPage", 20)
        items, total = store.list_queue(
            user_id=g.user["id"], page=page, per_page=per_page
        )
        return jsonify({"status": 0, "msg": "", "data": {"items": items, "total": total}})

    @app.post("/api/queue")
    @api_login_required
    def api_queue_add():
        data = _payload()
        entry = entry_for(data)
        if entry is None:
            return api_error("应用不存在", 404)
        node = node_for(entry, data)
        if node is None:
            return api_error("命令不存在", 404)
        parsed = parsed_for(entry, node, data)
        if parsed.errors:
            return _status_payload(
                ok=False, msg="表单校验未通过", errors=parsed.errors
            )
        root_name = entry.root.name if entry.root else entry.name
        params_label = summarize_params(parsed.field_values)
        argv_label = argv_preview(root_name, parsed.argv)
        item_id = store.add_queue_item(
            user_id=g.user["id"],
            username=g.user["username"],
            app=entry.name,
            command_id=node.node_id,
            command_path=_command_label(node),
            params=parsed.field_values,
            argv=parsed.argv,
            params_label=params_label,
            argv_label=argv_label,
        )
        count = store.queue_count(g.user["id"])
        queued = ExecutionResult(
            status="queued",
            exit_code=None,
            stdout="",
            stderr="",
            exception="",
            duration_ms=0,
            argv=parsed.argv,
            message=f"已加入记录队列（第 {count} 项），可以继续添加或前往“记录队列”批量执行。",
        )
        fields = result_fields_for_app(entry, queued, node)
        fields["queue_count"] = count
        fields["queue_item_id"] = item_id
        return _status_payload(ok=True, msg="已加入队列", data=fields)

    @app.delete("/api/queue")
    @api_login_required
    def api_queue_clear():
        removed = store.clear_queue(g.user["id"])
        return _status_payload(ok=True, msg=f"已清空 {removed} 项", data={"queue_count": 0})

    @app.delete("/api/queue/<int:item_id>")
    @api_login_required
    def api_queue_delete(item_id: int):
        if not store.delete_queue_item(item_id, g.user["id"]):
            return api_error("队列项不存在", 404)
        return _status_payload(
            ok=True,
            msg="已删除",
            data={"queue_count": store.queue_count(g.user["id"])},
        )

    @app.post("/api/queue/<int:item_id>/move")
    @api_login_required
    def api_queue_move(item_id: int):
        direction = request.args.get("direction", "up")
        if direction not in ("up", "down"):
            return api_error("direction 只能是 up 或 down")
        if not store.move_queue_item(item_id, g.user["id"], direction):
            return api_error("无法移动（已到边界或队列项不存在）", 400)
        return _status_payload(ok=True, msg="已调整顺序")

    @app.post("/api/batch/run")
    @api_login_required
    def api_batch_run():
        items = store.queue_items(g.user["id"])
        if not items:
            return api_error("记录队列为空，无法批量执行")
        batch_id = store.create_batch(
            user_id=g.user["id"],
            username=g.user["username"],
            app=items[0]["app"],
            status="running",
            title=f"队列批量执行（{len(items)} 项）",
        )
        succeeded = 0
        failed = 0
        for index, item in enumerate(items, start=1):
            try:
                argv = json.loads(item["argv_json"] or "[]")
                if not isinstance(argv, list):
                    argv = []
            except json.JSONDecodeError:
                argv = []
            try:
                params = json.loads(item["params_json"] or "{}")
                if not isinstance(params, dict):
                    params = {}
            except json.JSONDecodeError:
                params = {}

            entry = apps_by_name.get(item["app"])
            node = entry.resolve(item["command_id"]) if entry else None

            if entry is None:
                failed += 1
                store.record_execution(
                    user_id=g.user["id"],
                    username=g.user["username"],
                    app=item["app"],
                    command_id=item["command_id"],
                    command_path=item["command_path"],
                    params=params,
                    argv=argv,
                    argv_label=item["argv_label"],
                    status="failed",
                    exit_code=None,
                    stdout="",
                    stderr="",
                    exception=f"应用未注册或已被移除: {item['app']}",
                    duration_ms=0,
                    batch_id=batch_id,
                    batch_index=index,
                )
                continue

            try:
                result = execute_command(
                    entry, argv, max_output_chars=config.max_output_chars
                )
                if result.status == "success":
                    succeeded += 1
                else:
                    failed += 1
                if node is None:
                    # The stored argv still runs; only rerun links lose their
                    # command identity.
                    store.record_execution(
                        user_id=g.user["id"],
                        username=g.user["username"],
                        app=entry.name,
                        command_id=item["command_id"],
                        command_path=item["command_path"],
                        params=params,
                        argv=result.argv,
                        argv_label=item["argv_label"],
                        status=result.status,
                        exit_code=result.exit_code,
                        stdout=result.stdout,
                        stderr=result.stderr,
                        exception=_exception_for_storage(result),
                        duration_ms=result.duration_ms,
                        batch_id=batch_id,
                        batch_index=index,
                    )
                else:
                    save_execution(
                        entry,
                        node,
                        params,
                        result,
                        batch_id=batch_id,
                        batch_index=index,
                    )
            except Exception as exc:  # noqa: BLE001 - a batch item must not stop the batch
                failed += 1
                store.record_execution(
                    user_id=g.user["id"],
                    username=g.user["username"],
                    app=item["app"],
                    command_id=item["command_id"],
                    command_path=item["command_path"],
                    params=params,
                    argv=argv,
                    argv_label=item["argv_label"],
                    status="failed",
                    exit_code=None,
                    stdout="",
                    stderr="",
                    exception=f"{type(exc).__name__}: {exc}",
                    duration_ms=0,
                    batch_id=batch_id,
                    batch_index=index,
                )

        total = len(items)
        store.update_batch(
            batch_id,
            status="success" if failed == 0 else "failed",
            total=total,
            succeeded=succeeded,
            failed=failed,
        )
        store.clear_queue(g.user["id"])
        return _status_payload(
            ok=True,
            msg=f"批量执行完成：成功 {succeeded}，失败 {failed}",
            data={
                "batch_id": batch_id,
                "total": total,
                "succeeded": succeeded,
                "failed": failed,
                "queue_count": 0,
            },
        )

    @app.post("/api/reload")
    @api_login_required
    def api_reload():
        if not g.user.get("is_admin"):
            return _status_payload(
                ok=False, msg="只有管理员可以重新加载应用", http_status=403
            )
        try:
            fresh = [reload_app_entry(entry) for entry in entries]
        except AppLoadError as exc:
            return _status_payload(
                ok=False, msg=f"重新加载失败：{exc}", http_status=400
            )
        # Mutate the shared list/dict in place so every closure keeps seeing
        # the newest entries without rebuilding the Flask app.
        entries[:] = fresh
        apps_by_name.clear()
        apps_by_name.update({entry.name: entry for entry in entries})
        return _status_payload(
            ok=True,
            msg=f"已重新加载 {len(entries)} 个 Click 应用",
            data={
                "apps": [
                    {
                        "name": entry.name,
                        "display_name": entry.display_name(),
                        "nodes": len(entry.nodes),
                        "commands": len(entry.executable_nodes()),
                    }
                    for entry in entries
                ]
            },
        )

    # ------------------------------------------------------------- schedules
    def _schedule_plan(data: t.Dict[str, t.Any]) -> t.Tuple[
        t.Optional[str], t.Optional[str], str
    ]:
        cron = str(data.get("cron") or "").strip() or str(
            data.get("cron_preset") or ""
        ).strip()
        return validate_schedule(
            trigger_type=str(data.get("trigger_type") or "cron"),
            cron=cron,
            run_at=str(data.get("run_at") or ""),
            timezone=str(data.get("timezone") or ""),
        )

    @app.post("/api/schedules/shell")
    @api_login_required
    def api_schedule_shell_create():
        data = _payload()
        raw = data.get("shell_commands")
        if isinstance(raw, list):
            values = [str(value).strip() for value in raw]
        else:
            values = [line.strip() for line in str(raw or "").splitlines()]
        commands = [value for value in values if value]
        if not commands:
            return api_error("请至少填写一条 Shell 命令")
        if len(commands) > 20:
            return api_error("一个计划最多 20 条 Shell 命令")
        if any(len(command) > 2000 for command in commands):
            return api_error("单条 Shell 命令最多 2000 个字符")
        try:
            cron, run_at, tz = _schedule_plan(data)
        except ValueError as exc:
            return api_error(str(exc))
        next_value = next_fire_time(cron=cron, run_at=run_at, timezone=tz)
        if next_value is None:
            return api_error("该计划没有未来的触发时间，请修改运行时间")
        items = [
            {
                "kind": "shell",
                "shell": command,
                "app_name": "shell",
                "command_path": command,
                "argv": [command],
                "params": {},
                "argv_label": command,
            }
            for command in commands
        ]
        schedule_id = store.create_schedule(
            app_name="shell",
            command_path=commands[0],
            argv=[commands[0]],
            params={},
            argv_label=commands[0],
            cron=cron,
            run_at=run_at,
            timezone=tz,
            catch_up=_truthy(data.get("catch_up")),
            enabled=True,
            created_by=g.user["id"],
            created_by_name=g.user["username"],
            next_run_at=next_value,
            items=items,
        )
        sync_scheduler()
        return _status_payload(
            ok=True,
            msg=f"已创建定时任务 #{schedule_id}（{len(commands)} 条 Shell 命令），"
            f"下次运行 {next_value}",
            data={"schedule_id": schedule_id, "next_run_at": next_value},
        )

    @app.post("/api/schedules/preview")
    @api_login_required
    def api_schedule_preview():
        data = _payload()
        try:
            cron, run_at, tz = _schedule_plan(data)
            times = next_fire_times(
                cron=cron, run_at=run_at, timezone=tz, count=3
            )
        except ValueError as exc:
            return _status_payload(ok=False, msg=str(exc), http_status=400)
        return _status_payload(
            ok=True,
            msg=next_fire_preview_message(times),
            data={"times": times},
        )

    @app.get("/api/schedules/describe")
    @api_login_required
    def api_schedule_describe():
        expression = request.args.get("cron", "")
        try:
            description = describe_cron(expression)
        except ValueError as exc:
            return _status_payload(ok=False, msg=str(exc), http_status=400)
        return _status_payload(ok=True, data={"description": description})

    @app.post("/api/schedules")
    @api_login_required
    def api_schedule_create():
        data = _restore_mirrors(_payload())
        entry = entry_for(data)
        if entry is None:
            return api_error("应用不存在", 404)
        node = node_for(entry, data)
        if node is None:
            return api_error("命令不存在", 404)
        parsed = parsed_for(entry, node, data)
        if parsed.errors:
            return _status_payload(
                ok=False, msg="表单校验未通过", errors=parsed.errors
            )
        try:
            cron, run_at, tz = _schedule_plan(data)
        except ValueError as exc:
            return api_error(str(exc))
        next_value = next_fire_time(cron=cron, run_at=run_at, timezone=tz)
        if next_value is None:
            return api_error("该计划没有未来的触发时间，请修改运行时间")
        root_name = entry.root.name if entry.root else entry.name
        try:
            schedule_id = store.create_schedule(
                app_name=entry.name,
                command_path=_command_label(node),
                argv=parsed.argv,
                params=parsed.field_values,
                argv_label=argv_preview(root_name, parsed.argv),
                cron=cron,
                run_at=run_at,
                timezone=tz,
                catch_up=_truthy(data.get("catch_up")),
                enabled=True,
                created_by=g.user["id"],
                created_by_name=g.user["username"],
                next_run_at=next_value,
            )
        except sqlite3.Error as exc:
            return api_error(f"创建定时任务失败: {exc}")
        sync_scheduler()
        return _status_payload(
            ok=True,
            msg=f"已创建定时任务 #{schedule_id}，下次运行 {next_value}",
            data={"schedule_id": schedule_id, "next_run_at": next_value},
        )

    @app.get("/api/schedules")
    @api_login_required
    def api_schedule_list():
        page = _int_arg("page", 1)
        per_page = _int_arg("perPage", 20)
        app_name = request.args.get("app") or None
        admin = bool(g.user.get("is_admin"))
        items, total = store.list_schedules(
            user_id=None if admin else g.user["id"],
            page=page,
            per_page=per_page,
            app=app_name,
        )
        for item in items:
            plan_items = schedule_items(item)
            first = plan_items[0] if plan_items else {}
            shell = str(first.get("shell") or "").strip()
            summary = f"Shell: {shell}" if shell else str(item.get("command_path") or "")
            if len(summary) > 90:
                summary = summary[:87] + "..."
            if len(plan_items) > 1:
                summary = f"{summary} · 共 {len(plan_items)} 条"
            item["items_count"] = len(plan_items)
            item["command_summary"] = summary
            item["title"] = (
                f"#{item['id']} {summary} · "
                f"{item.get('cron') or item.get('run_at') or ''}".rstrip()
            )
            item.pop("params_json", None)
            item.pop("argv_json", None)
            item.pop("items_json", None)
        return jsonify({"status": 0, "msg": "", "data": {"items": items, "total": total}})

    @app.post("/api/schedules/<int:schedule_id>/run")
    @api_login_required
    def api_schedule_run(schedule_id: int):
        row = store.get_schedule(schedule_id)
        if row is None:
            return api_error("定时任务不存在", 404)
        require_schedule_owned(row)
        status, execution_id = run_schedule_once(
            store,
            apps_by_name,
            row,
            max_output_chars=config.max_output_chars,
            wait_seconds=None,
        )
        store.mark_schedule_result(
            schedule_id, status=status, execution_id=execution_id
        )
        return _status_payload(
            ok=True,
            msg=f"已执行定时任务 #{schedule_id}：{status}",
            data={"execution_id": execution_id, "status": status},
        )

    @app.post("/api/schedules/<int:schedule_id>/toggle")
    @api_login_required
    def api_schedule_toggle(schedule_id: int):
        row = store.get_schedule(schedule_id)
        if row is None:
            return api_error("定时任务不存在", 404)
        require_schedule_owned(row)
        enabled = request.args.get("enabled", "1").lower() not in (
            "0",
            "false",
            "no",
            "off",
        )
        next_value: t.Optional[str] = None
        if enabled:
            next_value = next_fire_for_schedule(row)
            if next_value is None:
                return api_error("该单次任务的时间已过，无法启用")
        store.set_schedule_enabled(schedule_id, enabled, next_value)
        sync_scheduler()
        return _status_payload(
            ok=True,
            msg="已启用" if enabled else "已暂停",
            data={"enabled": enabled, "next_run_at": next_value},
        )

    @app.post("/api/schedules/<int:schedule_id>/edit")
    @api_login_required
    def api_schedule_edit(schedule_id: int):
        row = store.get_schedule(schedule_id)
        if row is None:
            return api_error("定时任务不存在", 404)
        require_schedule_owned(row)
        data = _payload()
        try:
            cron, run_at, tz = _schedule_plan(data)
        except ValueError as exc:
            return api_error(str(exc))
        next_value = next_fire_time(cron=cron, run_at=run_at, timezone=tz)
        if next_value is None:
            return api_error("该计划没有未来的触发时间，请修改运行时间")
        if not store.update_schedule_plan(
            schedule_id,
            cron=cron,
            run_at=run_at,
            timezone=tz,
            catch_up=_truthy(data.get("catch_up")),
            next_run_at=next_value,
        ):
            return api_error("定时任务不存在", 404)
        sync_scheduler()
        return _status_payload(
            ok=True,
            msg=f"计划已更新，下次运行 {next_value}",
            data={"schedule_id": schedule_id, "next_run_at": next_value},
        )

    @app.post("/api/schedules/<int:schedule_id>/duplicate")
    @api_login_required
    def api_schedule_duplicate(schedule_id: int):
        row = store.get_schedule(schedule_id)
        if row is None:
            return api_error("定时任务不存在", 404)
        require_schedule_owned(row)
        next_value = next_fire_for_schedule(row)
        if next_value is None:
            return api_error("该单次任务的时间已过，请先编辑计划时间再复制")
        new_id = store.duplicate_schedule(
            schedule_id,
            created_by=g.user["id"],
            created_by_name=g.user["username"],
            next_run_at=next_value,
        )
        if new_id is None:
            return api_error("定时任务不存在", 404)
        sync_scheduler()
        return _status_payload(
            ok=True,
            msg=f"已复制为定时任务 #{new_id}",
            data={"schedule_id": new_id, "next_run_at": next_value},
        )

    @app.post("/api/schedules/<int:schedule_id>/items")
    @api_login_required
    def api_schedule_item_add(schedule_id: int):
        row = store.get_schedule(schedule_id)
        if row is None:
            return api_error("定时任务不存在", 404)
        require_schedule_owned(row)
        data = _restore_mirrors(_payload())
        entry = entry_for(data)
        if entry is None:
            return api_error("应用不存在", 404)
        node = node_for(entry, data)
        if node is None:
            return api_error("命令不存在", 404)
        parsed = parsed_for(entry, node, data)
        if parsed.errors:
            return _status_payload(
                ok=False, msg="表单校验未通过", errors=parsed.errors
            )
        root_name = entry.root.name if entry.root else entry.name
        item = {
            "app_name": entry.name,
            "command_path": _command_label(node),
            "argv": parsed.argv,
            "params": parsed.field_values,
            "argv_label": argv_preview(root_name, parsed.argv),
        }
        items = store.add_schedule_item(schedule_id, item)
        if items is None:
            return api_error("定时任务不存在", 404)
        sync_scheduler()
        return _status_payload(
            ok=True,
            msg=f"已向定时任务 #{schedule_id} 追加第 {len(items)} 条命令",
            data={"schedule_id": schedule_id, "items_count": len(items)},
        )

    @app.delete("/api/schedules/<int:schedule_id>/items/<int:index>")
    @api_login_required
    def api_schedule_item_delete(schedule_id: int, index: int):
        row = store.get_schedule(schedule_id)
        if row is None:
            return api_error("定时任务不存在", 404)
        require_schedule_owned(row)
        items = store.remove_schedule_item(schedule_id, index)
        if items is None:
            return api_error("无法移除：索引越界，或计划至少需要保留一条命令")
        sync_scheduler()
        return _status_payload(
            ok=True,
            msg=f"已移除，计划剩余 {len(items)} 条命令",
            data={"schedule_id": schedule_id, "items_count": len(items)},
        )

    @app.delete("/api/schedules/<int:schedule_id>")
    @api_login_required
    def api_schedule_delete(schedule_id: int):
        row = store.get_schedule(schedule_id)
        if row is None:
            return api_error("定时任务不存在", 404)
        require_schedule_owned(row)
        store.delete_schedule(schedule_id)
        sync_scheduler()
        return _status_payload(ok=True, msg="已删除定时任务")

    @app.post("/api/upload")
    @api_login_required
    def api_upload():
        upload = request.files.get("file")
        if upload is None and request.files:
            upload = next(iter(request.files.values()))
        if upload is None or not upload.filename:
            return api_error("没有收到文件")
        original = upload.filename
        filename = _safe_filename(original)
        stored = f"{uuid.uuid4().hex}_{filename}"
        target = Path(config.upload_dir) / stored
        upload.save(str(target))
        return _status_payload(
            ok=True,
            msg="上传成功",
            data={
                "value": str(target.resolve()),
                "filename": original,
                "url": f"/uploads/{stored}",
            },
        )

    # ------------------------------------------------------------ error pages
    @app.errorhandler(403)
    def handle_403(_error):
        if request.path.startswith("/api/"):
            return _status_payload(ok=False, msg="没有权限访问该资源", http_status=403)
        return page_error("没有权限访问该资源", status=403)

    @app.errorhandler(404)
    def handle_404(_error):
        if request.path.startswith("/api/"):
            return _status_payload(ok=False, msg="接口不存在", http_status=404)
        return page_error("页面不存在", status=404)

    @app.errorhandler(413)
    def handle_413(_error):
        if request.path.startswith("/api/"):
            return _status_payload(ok=False, msg="上传文件超过大小限制", http_status=413)
        return page_error("上传文件超过大小限制", status=413, http_status=413)

    @app.errorhandler(500)
    def handle_500(error):
        app.logger.exception("unhandled error", exc_info=error)
        if request.path.startswith("/api/"):
            return _status_payload(ok=False, msg="服务器内部错误", http_status=500)
        try:
            return page_error("服务器内部错误", status=500, http_status=500)
        except Exception:
            return "服务器内部错误", 500

    return app
