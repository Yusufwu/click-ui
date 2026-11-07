"""Server-side builders for all AMIS pages."""

from __future__ import annotations

import html
import json
import typing as t
from urllib.parse import urlencode

from cliui.model import AppEntry, CommandInfo
from cliui.schema.form import build_command_form
from cliui.schema.nav import build_nav, command_url

STATUS_LABELS = {
    "success": "成功",
    "failed": "失败",
    "preview": "预览",
    "queued": "已排队",
    "timeout": "超时",
    "error": "异常",
    "running": "执行中",
}


def esc(value: t.Any) -> str:
    text = html.escape("" if value is None else str(value), quote=True)
    # AMIS templates interpret ``${...}``.  Escaping the dollar sign as an
    # HTML entity keeps the literal text without letting user supplied
    # command names or output be evaluated as expressions.
    return text.replace("${", "&#36;{")


def _app_link(entry: AppEntry, node_id: t.Optional[str] = None) -> str:
    return command_url(entry.name, node_id)


def _topbar(
    apps: t.List[AppEntry],
    current_app: t.Optional[AppEntry],
    user: t.Optional[t.Dict[str, t.Any]],
    queue_count: int,
    active: str,
) -> t.Dict[str, t.Any]:
    user = user or {}
    home = _app_link(current_app) if current_app else (_app_link(apps[0]) if apps else "/")
    app_switch = ""
    if len(apps) > 1:
        chips = []
        for entry in apps:
            cls = "cliui-app-chip is-active" if current_app and entry.name == current_app.name else "cliui-app-chip"
            chips.append(
                f'<a class="{cls}" href="{esc(_app_link(entry))}">{esc(entry.display_name())}</a>'
            )
        app_switch = f'<div class="cliui-app-switch">{"".join(chips)}</div>'

    active_cls = {
        "console": "is-active" if active == "console" else "",
        "records": "is-active" if active == "records" else "",
        "queue": "is-active" if active == "queue" else "",
        "batches": "is-active" if active == "batches" else "",
    }
    admin = ' <span class="cliui-admin-badge">管理员</span>' if user.get("is_admin") else ""
    queue_badge = f'<span class="cliui-pill">{queue_count}</span>' if queue_count else ""
    reload_button = ""
    if user.get("is_admin"):
        reload_button = (
            '<button type="button" class="cliui-reload-btn"'
            ' title="重新导入已注册的 Click 应用，读取最新的代码改动；完成后页面会刷新（仅管理员）">'
            "重新加载 CLI</button>"
        )

    html_text = f"""
<div class="cliui-topbar">
  <div class="cliui-brand">
    <div class="cliui-brand-mark">CLI</div>
    <div class="cliui-brand-text">
      <div class="cliui-brand-title">{esc(current_app.display_name() if current_app else "Click UI")}</div>
      <div class="cliui-brand-sub">Click → Web UI控制台</div>
    </div>
  </div>
  <div class="cliui-topbar-right">
    {app_switch}
    <a class="cliui-top-link {active_cls['console']}" href="{esc(home)}">控制台</a>
    <a class="cliui-top-link {active_cls['records']}" href="/records">执行记录</a>
    <a class="cliui-top-link {active_cls['queue']}" href="/queue">记录队列 {queue_badge}</a>
    <a class="cliui-top-link {active_cls['batches']}" href="/batches">执行批次</a>
    <span class="cliui-user">{esc(user.get("username", ""))}{admin}</span>
    {reload_button}
    <a class="cliui-top-link cliui-logout" href="/logout">退出</a>
  </div>
</div>
"""
    return {"type": "tpl", "tpl": html_text, "className": "cliui-topbar-wrap"}


def _heading(title: str, crumb: str) -> str:
    """Title and breadcrumb share one line; the crumb is shown in parentheses."""
    crumb_html = f'<span class="cliui-breadcrumb">({esc(crumb)})</span>' if crumb else ""
    return (
        '<div class="cliui-hero-row">'
        f'<h1 class="cliui-command-title">{esc(title)}</h1>'
        f"{crumb_html}"
        "</div>"
    )


def _hero(entry: AppEntry, node: t.Optional[CommandInfo]) -> t.Dict[str, t.Any]:
    if node is None:
        title = entry.display_name()
        crumb = ""
        subtitle = entry.description or "选择一个命令开始"
        meta = []
        executable_count = len(entry.executable_nodes())
        meta.append(f'<span class="cliui-meta-chip">可执行命令 {executable_count}</span>')
        meta.append(f'<span class="cliui-meta-chip">命令节点 {len(entry.nodes)}</span>')
    else:
        # Parent trail only: the current command is already the title.
        parents = node.ancestors()[:-1]
        crumb = " / ".join(part.name for part in parents)
        title = node.name
        subtitle = node.short_help or (node.help.splitlines()[0] if node.help else "")
        meta = []
        if node.is_group:
            meta.append(f'<span class="cliui-meta-chip">命令组</span>')
            meta.append(f'<span class="cliui-meta-chip">子命令 {len(node.children)}</span>')
            if node.chain:
                meta.append('<span class="cliui-meta-chip cliui-chip-warn">链式命令</span>')
            if node.invoke_without_command:
                meta.append('<span class="cliui-meta-chip">可直接执行</span>')
        else:
            meta.append('<span class="cliui-meta-chip">命令</span>')
        param_count = len(node.params)
        required_count = sum(1 for param in node.params if param.required)
        meta.append(f'<span class="cliui-meta-chip">参数 {param_count}</span>')
        if required_count:
            meta.append(f'<span class="cliui-meta-chip cliui-chip-warn">必填 {required_count}</span>')
        if node.deprecated:
            meta.append('<span class="cliui-meta-chip cliui-chip-danger">已废弃</span>')

    help_block = ""
    if node is not None and node.help:
        help_block = f'<div class="cliui-help">{esc(node.help)}</div>'
    elif node is None and entry.root.help:
        help_block = f'<div class="cliui-help">{esc(entry.root.help)}</div>'

    html_text = f"""
<div class="cliui-hero">
  {_heading(title, crumb)}
  <div class="cliui-command-subtitle">{esc(subtitle)}</div>
  <div class="cliui-meta-row">{"".join(meta)}</div>
  {help_block}
</div>
"""
    return {"type": "tpl", "tpl": html_text, "className": "cliui-hero-wrap"}


def _child_cards(children: t.List[CommandInfo], app: AppEntry) -> t.Dict[str, t.Any]:
    cards = []
    for child in children:
        desc = child.short_help or (child.help.splitlines()[0] if child.help else "无描述")
        extra = ""
        if child.is_group:
            extra = f'<span class="cliui-child-badge">组 · {len(child.children)}</span>'
        elif child.deprecated:
            extra = '<span class="cliui-child-badge cliui-chip-danger">已废弃</span>'
        cards.append(
            f"""
<a class="cliui-child-card" href="{esc(_app_link(app, child.node_id))}">
  <div class="cliui-child-head"><span class="cliui-child-name">{esc(child.name)}</span>{extra}</div>
  <div class="cliui-child-desc">{esc(desc)}</div>
  <div class="cliui-child-path">{esc(child.path or child.name)}</div>
</a>
"""
        )
    html_text = f'<div class="cliui-children">{"".join(cards)}</div>'
    return {"type": "tpl", "tpl": html_text}


def _alert(level: str, text: str) -> t.Dict[str, t.Any]:
    return {"type": "alert", "level": level, "showIcon": True, "body": text}


def build_index_page(
    entry: AppEntry,
    apps: t.List[AppEntry],
    user: t.Dict[str, t.Any],
    queue_count: int,
    selected: t.Optional[CommandInfo],
    initial_values: t.Optional[t.Dict[str, t.Any]] = None,
) -> t.Dict[str, t.Any]:
    nav = build_nav(entry, selected)
    body: t.List[t.Dict[str, t.Any]] = [
        _topbar(apps, entry, user, queue_count, "console"),
        _hero(entry, selected),
    ]

    is_group_only = selected is not None and selected.is_group and not selected.invoke_without_command
    show_children = selected is not None and selected.is_group and selected.children
    show_overview = selected is None

    if show_overview:
        root_children = entry.root.children if entry.root.is_group else []
        body.append(_alert("info", "从左侧导航树选择命令。带“组”标记的节点可以继续展开子命令。"))
        if root_children:
            body.append({"type": "panel", "title": "顶层命令", "body": [_child_cards(root_children, entry)]})
        if entry.root.executable:
            if root_children:
                body.append(
                    _alert("info", "该根命令组自身也可以直接执行（invoke_without_command）。")
                )
            body.append(build_command_form(entry, entry.root, initial_values))
        elif not root_children:
            body.append(_alert("warning", "该命令组没有可执行的子命令。"))

    if selected is not None:
        if selected.deprecated:
            body.append(_alert("warning", "该命令已被标记为废弃，请谨慎使用。"))
        if selected.chain:
            body.append(_alert("warning", "这是链式命令组：可以把多个子命令加入队列后批量执行。"))
        if selected.allow_extra_args:
            body.append(_alert("info", "该命令允许额外参数（allow_extra_args），Web 表单只能表达已声明的参数。"))
        if show_children:
            title = "子命令" if is_group_only else "子命令（也可以直接执行当前组）"
            body.append({"type": "panel", "title": title, "body": [_child_cards(selected.children, entry)]})
        if is_group_only and not selected.children:
            body.append(_alert("warning", "该命令组没有可执行的子命令，也没有开启 invoke_without_command。"))
        if not is_group_only:
            body.append(build_command_form(entry, selected, initial_values))

    page = {
        "type": "page",
        "title": "",
        "className": "cliui-page",
        "asideResizor": True,
        "asideMinWidth": 250,
        "asideMaxWidth": 420,
        "asideSticky": True,
        "aside": nav,
        "body": body,
    }
    return page


def build_records_page(
    apps: t.List[AppEntry],
    current_app: t.Optional[AppEntry],
    user: t.Dict[str, t.Any],
    queue_count: int,
) -> t.Dict[str, t.Any]:
    filters: t.List[t.Dict[str, t.Any]] = [
        {"type": "input-text", "name": "command", "label": "命令包含", "clearable": True},
        {
            "type": "select",
            "name": "status",
            "label": "状态",
            "clearable": True,
            "options": [
                {"label": "成功", "value": "success"},
                {"label": "失败", "value": "failed"},
                {"label": "预览", "value": "preview"},
            ],
        },
    ]
    if current_app and len(apps) > 1:
        filters.append(
            {
                "type": "select",
                "name": "app",
                "label": "应用",
                "clearable": True,
                "options": [{"label": app.display_name(), "value": app.name} for app in apps],
            }
        )
    if user.get("is_admin"):
        filters.append({"type": "input-text", "name": "username", "label": "执行人", "clearable": True})

    columns: t.List[t.Dict[str, t.Any]] = [
        {"name": "id", "label": "#", "width": 70},
    ]
    if len(apps) > 1:
        columns.append({"name": "app", "label": "应用", "width": 110})
    columns.extend(
        [
            {"name": "command_path", "label": "命令", "minWidth": 220},
            {"name": "status", "label": "状态", "type": "mapping", "map": STATUS_LABELS, "width": 90},
            {"name": "exit_code", "label": "退出码", "width": 90},
            {"name": "duration_ms", "label": "耗时(ms)", "width": 110},
            {"name": "created_at", "label": "执行时间", "width": 170},
        ]
    )
    if user.get("is_admin"):
        columns.append({"name": "username", "label": "执行人", "width": 120})
    columns.append(
        {
            "type": "operation",
            "label": "操作",
            "width": 110,
            "buttons": [
                {
                    "type": "button",
                    "label": "查看",
                    "level": "link",
                    "actionType": "url",
                    "blank": False,
                    "url": "/records/${id}",
                }
            ],
        }
    )

    crud = {
        "type": "crud",
        "name": "cliui-records",
        "api": {"method": "get", "url": "/api/records"},
        "syncLocation": False,
        "perPage": 20,
        "perPageAvailable": [10, 20, 50],
        "filterTogglable": True,
        "filter": {"title": "筛选条件", "body": filters, "submitOnChange": True},
        "headerToolbar": ["filter-toggler", {"type": "reload"}, "statistics", "pagination"],
        "footerToolbar": ["statistics", "pagination"],
        "columns": columns,
        "placeholder": "还没有执行记录",
    }
    return {
        "type": "page",
        "title": "",
        "className": "cliui-page cliui-wide-page",
        "body": [
            _topbar(apps, current_app, user, queue_count, "records"),
            _hero_simple("执行记录", "每次执行（含失败、预览与批量中的单项）都会单独保存，按执行人隔离；管理员可以按执行人筛选。"),
            crud,
        ],
    }


def _hero_simple(title: str, subtitle: str) -> t.Dict[str, t.Any]:
    return {
        "type": "tpl",
        "tpl": f"""
<div class="cliui-hero">
  {_heading(title, "控制台")}
  <div class="cliui-command-subtitle">{esc(subtitle)}</div>
</div>
""",
        "className": "cliui-hero-wrap",
    }


def build_queue_page(
    apps: t.List[AppEntry],
    current_app: t.Optional[AppEntry],
    user: t.Dict[str, t.Any],
    queue_count: int,
) -> t.Dict[str, t.Any]:
    columns = [
        {"name": "seq", "label": "序号", "width": 70},
        {"name": "app", "label": "应用", "width": 110},
        {"name": "command_path", "label": "命令", "minWidth": 200},
        {"name": "params_label", "label": "参数摘要", "minWidth": 260},
        {"name": "argv_label", "label": "命令预览", "minWidth": 320},
        {"name": "created_at", "label": "加入时间", "width": 170},
        {
            "type": "operation",
            "label": "操作",
            "width": 240,
            "buttons": [
                {
                    "type": "button",
                    "label": "编辑",
                    "level": "link",
                    "actionType": "url",
                    "blank": False,
                    "url": f"/?app=${{app}}&cmd=${{command_id}}&queue_item=${{id}}",
                },
                {
                    "type": "button",
                    "label": "上移",
                    "level": "link",
                    "actionType": "ajax",
                    "api": "post:/api/queue/${id}/move?direction=up",
                    "reload": "cliui-queue",
                },
                {
                    "type": "button",
                    "label": "下移",
                    "level": "link",
                    "actionType": "ajax",
                    "api": "post:/api/queue/${id}/move?direction=down",
                    "reload": "cliui-queue",
                },
                {
                    "type": "button",
                    "label": "删除",
                    "level": "link",
                    "className": "text-danger",
                    "actionType": "ajax",
                    "api": "delete:/api/queue/${id}",
                    "confirmText": "确定从队列中删除这一条？",
                    "reload": "cliui-queue",
                },
            ],
        },
    ]
    crud = {
        "type": "crud",
        "name": "cliui-queue",
        "api": {"method": "get", "url": "/api/queue"},
        "syncLocation": False,
        "perPage": 20,
        "headerToolbar": [
            {
                "type": "button",
                "label": "批量执行队列",
                "level": "primary",
                "actionType": "ajax",
                "api": {"method": "post", "url": "/api/batch/run"},
                "confirmText": "确定按顺序执行队列中的全部命令？执行完成后队列会被清空。",
                "redirect": "/batches/${batch_id}",
            },
            {
                "type": "button",
                "label": "清空队列",
                "level": "danger",
                "actionType": "ajax",
                "api": {"method": "delete", "url": "/api/queue"},
                "confirmText": "确定清空整个记录队列？此操作不可恢复。",
                "reload": "cliui-queue",
            },
            "pagination",
        ],
        "columns": columns,
        "placeholder": "队列为空。回到命令表单，点击“加入队列”即可收集多条命令。",
    }
    return {
        "type": "page",
        "title": "",
        "className": "cliui-page cliui-wide-page",
        "body": [
            _topbar(apps, current_app, user, queue_count, "queue"),
            _hero_simple(
                "记录队列",
                "加入队列的命令会保存在这里，刷新页面也不会丢失；确认顺序后可以一次性批量执行，并查看逐项结果。",
            ),
            crud,
        ],
    }


def build_batches_page(
    apps: t.List[AppEntry],
    current_app: t.Optional[AppEntry],
    user: t.Dict[str, t.Any],
    queue_count: int,
) -> t.Dict[str, t.Any]:
    columns = [
        {"name": "id", "label": "#", "width": 70},
        {"name": "status", "label": "状态", "type": "mapping", "map": STATUS_LABELS, "width": 90},
        {"name": "total", "label": "总数", "width": 80},
        {"name": "succeeded", "label": "成功", "width": 80},
        {"name": "failed", "label": "失败", "width": 80},
        {"name": "username", "label": "执行人", "width": 120},
        {"name": "created_at", "label": "开始时间", "width": 170},
        {"name": "finished_at", "label": "结束时间", "width": 170},
        {
            "type": "operation",
            "label": "操作",
            "buttons": [
                {
                    "type": "button",
                    "label": "查看",
                    "level": "link",
                    "actionType": "url",
                    "blank": False,
                    "url": "/batches/${id}",
                }
            ],
        },
    ]
    crud = {
        "type": "crud",
        "name": "cliui-batches",
        "api": {"method": "get", "url": "/api/batches"},
        "syncLocation": False,
        "perPage": 20,
        "headerToolbar": ["statistics", "pagination"],
        "footerToolbar": ["statistics", "pagination"],
        "columns": columns,
        "placeholder": "还没有批量执行记录",
    }
    return {
        "type": "page",
        "title": "",
        "className": "cliui-page cliui-wide-page",
        "body": [
            _topbar(apps, current_app, user, queue_count, "batches"),
            _hero_simple("执行批次", "批量执行会生成一个批次，批次中的每条命令都有独立的执行记录与输出。"),
            crud,
        ],
    }


def _static_text(label: str, value: t.Any, pre: bool = True) -> t.Dict[str, t.Any]:
    return {
        "type": "static",
        "label": label,
        "value": "" if value is None else str(value),
        "className": "cliui-output-text" if pre else "",
    }


def _pre_block(title: str, text: t.Optional[str]) -> t.Dict[str, t.Any]:
    if not text:
        text = "（无输出）"
    # ``static`` renders its ``value`` as plain text (React-escaped), so raw
    # output can never be interpreted as an AMIS template.
    return {
        "type": "static",
        "label": title,
        "value": text,
        "className": "cliui-output-field",
    }


def build_record_detail_page(
    record: t.Dict[str, t.Any],
    apps: t.List[AppEntry],
    current_app: t.Optional[AppEntry],
    user: t.Dict[str, t.Any],
    queue_count: int,
) -> t.Dict[str, t.Any]:
    status = str(record.get("status") or "")
    status_label = STATUS_LABELS.get(status, status)
    params_json = record.get("params_json") or "{}"
    try:
        params_pretty = json.dumps(json.loads(params_json), ensure_ascii=False, indent=2)
    except Exception:
        params_pretty = str(params_json)
    try:
        fallback_argv = " ".join(json.loads(record.get("argv_json") or "[]"))
    except Exception:
        fallback_argv = str(record.get("argv_json") or "")
    argv_label = record.get("argv_label") or fallback_argv
    rerun_url = "/?" + urlencode(
        {
            "app": record.get("app") or "",
            "cmd": record.get("command_id") or "",
            "record": record.get("id") or "",
        }
    )
    details = {
        "type": "panel",
        "title": f"执行记录 #{record.get('id')}",
        "body": [
            {
                "type": "tpl",
                "tpl": f"""
<div class="cliui-detail-head">
  <span class="cliui-result-status cliui-status-{esc(status)}"><span class="cliui-result-dot"></span>{esc(status_label)}</span>
  <span class="cliui-detail-item">退出码 <b>{esc(record.get('exit_code'))}</b></span>
  <span class="cliui-detail-item">耗时 <b>{esc(record.get('duration_ms'))} ms</b></span>
  <span class="cliui-detail-item">执行人 <b>{esc(record.get('username'))}</b></span>
  <span class="cliui-detail-item">时间 <b>{esc(record.get('created_at'))}</b></span>
</div>
<div class="cliui-detail-path">{esc(record.get('command_path'))}</div>
""",
            },
            {
                "type": "button",
                "label": "用这些参数重新打开表单",
                "level": "primary",
                "actionType": "url",
                "blank": False,
                "url": rerun_url,
            },
            _pre_block("参数 (JSON)", params_pretty),
            _pre_block("实际执行的命令", argv_label),
            _pre_block("标准输出 (stdout)", record.get("stdout")),
            _pre_block("标准错误 (stderr)", record.get("stderr")),
            _pre_block("异常", record.get("exception")),
        ],
    }
    return {
        "type": "page",
        "title": "",
        "className": "cliui-page cliui-wide-page",
        "body": [
            _topbar(apps, current_app, user, queue_count, "records"),
            _hero_simple("执行详情", "结果与错误均已按执行人单独存储。"),
            details,
        ],
    }


def build_batch_detail_page(
    batch: t.Dict[str, t.Any],
    items: t.List[t.Dict[str, t.Any]],
    apps: t.List[AppEntry],
    current_app: t.Optional[AppEntry],
    user: t.Dict[str, t.Any],
    queue_count: int,
) -> t.Dict[str, t.Any]:
    status = str(batch.get("status") or "")
    status_label = STATUS_LABELS.get(status, status)
    collapse_items = []
    active_keys = []
    for index, item in enumerate(items):
        key = f"item-{item.get('id')}"
        if index == 0:
            active_keys.append(key)
        item_status = str(item.get("status") or "")
        header = (
            f"#{item.get('batch_index')} · {item.get('command_path')} · "
            f"{STATUS_LABELS.get(item_status, item_status)} · exit {item.get('exit_code')}"
        )
        try:
            fallback_argv = " ".join(json.loads(item.get("argv_json") or "[]"))
        except Exception:
            fallback_argv = str(item.get("argv_json") or "")
        argv_label = item.get("argv_label") or fallback_argv
        collapse_items.append(
            {
                "type": "collapse",
                "key": key,
                "header": header,
                "body": [
                    {
                        "type": "button",
                        "label": f"查看执行记录 #{item.get('id')}",
                        "level": "link",
                        "actionType": "url",
                        "blank": False,
                        "url": f"/records/{item.get('id')}",
                    },
                    _pre_block("实际执行的命令", argv_label),
                    _pre_block("标准输出 (stdout)", item.get("stdout")),
                    _pre_block("标准错误 (stderr)", item.get("stderr")),
                    _pre_block("异常", item.get("exception")),
                ],
            }
        )
    summary = {
        "type": "tpl",
        "tpl": f"""
<div class="cliui-detail-head">
  <span class="cliui-result-status cliui-status-{esc(status)}"><span class="cliui-result-dot"></span>{esc(status_label)}</span>
  <span class="cliui-detail-item">总数 <b>{esc(batch.get('total'))}</b></span>
  <span class="cliui-detail-item">成功 <b>{esc(batch.get('succeeded'))}</b></span>
  <span class="cliui-detail-item">失败 <b>{esc(batch.get('failed'))}</b></span>
  <span class="cliui-detail-item">执行人 <b>{esc(batch.get('username'))}</b></span>
  <span class="cliui-detail-item">开始 <b>{esc(batch.get('created_at'))}</b></span>
  <span class="cliui-detail-item">结束 <b>{esc(batch.get('finished_at'))}</b></span>
</div>
""",
    }
    body: t.List[t.Dict[str, t.Any]] = [
        _topbar(apps, current_app, user, queue_count, "batches"),
        _hero_simple(f"执行批次 #{batch.get('id')}", "逐项展示批量执行结果，每一项都关联到独立执行记录。"),
        {"type": "panel", "title": "批次摘要", "body": [summary]},
    ]
    if collapse_items:
        body.append({"type": "collapse-group", "activeKey": active_keys, "body": collapse_items})
    else:
        body.append(_alert("info", "该批次没有执行项。"))
    return {
        "type": "page",
        "title": "",
        "className": "cliui-page cliui-wide-page",
        "body": body,
    }


def build_error_page(
    apps: t.List[AppEntry],
    current_app: t.Optional[AppEntry],
    user: t.Dict[str, t.Any],
    queue_count: int,
    message: str,
    status: int = 404,
) -> t.Dict[str, t.Any]:
    return {
        "type": "page",
        "title": "",
        "className": "cliui-page cliui-wide-page",
        "body": [
            _topbar(apps, current_app, user, queue_count, ""),
            _alert("danger", f"{status} · {message}"),
            {
                "type": "button",
                "label": "返回控制台",
                "level": "primary",
                "actionType": "url",
                "url": _app_link(current_app) if current_app else "/",
            },
        ],
    }
