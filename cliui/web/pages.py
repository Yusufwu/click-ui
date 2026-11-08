"""Server-side builders for all AMIS pages."""

from __future__ import annotations

import html
import json
import typing as t
from urllib.parse import urlencode

from cliui.model import AppEntry, CommandInfo
from cliui.scheduling import CRON_PRESETS, DEFAULT_TIMEZONE
from cliui.schema.form import build_command_form
from cliui.schema.nav import build_nav, command_url
from cliui.storage.repo import schedule_items

STATUS_LABELS = {
    "success": "成功",
    "failed": "失败",
    "preview": "预览",
    "queued": "已排队",
    "timeout": "超时",
    "error": "异常",
    "running": "执行中",
    "skipped": "已跳过",
}

SCHEDULE_STATUS_LABELS = {
    "success": "成功",
    "failed": "失败",
    "skipped": "已跳过",
    "missed": "错过（停机）",
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
        "schedules": "is-active" if active == "schedules" else "",
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
    <a class="cliui-brand-mark" href="/overview" title="命令总览：查看所有 Click 命令及一句话说明">CLI</a>
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
    <a class="cliui-top-link {active_cls['schedules']}" href="/schedules">定时任务</a>
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
                {"label": "已跳过", "value": "skipped"},
                {"label": "执行中", "value": "running"},
            ],
        },
        {
            "type": "select",
            "name": "trigger",
            "label": "来源",
            "clearable": True,
            "options": [
                {"label": "手动", "value": "manual"},
                {"label": "定时", "value": "schedule"},
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
            {
                "name": "trigger",
                "label": "来源",
                "type": "mapping",
                "map": {"manual": "手动", "schedule": "定时"},
                "width": 80,
            },
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


def _one_line_help(node: CommandInfo) -> str:
    text = (node.short_help or node.help or "").strip()
    return text.splitlines()[0].strip() if text else ""


def build_overview_page(
    apps: t.List[AppEntry],
    current_app: t.Optional[AppEntry],
    user: t.Dict[str, t.Any],
    queue_count: int,
    *,
    query: str = "",
    favorites: t.Optional[t.Set[t.Tuple[str, str]]] = None,
    recent: t.Optional[t.List[t.Dict[str, t.Any]]] = None,
) -> t.Dict[str, t.Any]:
    """Overview of every registered command with search, favorites and recents."""
    favorites = favorites or set()
    recent = recent or []
    keyword = query.strip().lower()

    lookup: t.Dict[t.Tuple[str, str], t.Tuple[AppEntry, CommandInfo]] = {}
    for entry in apps:
        for node in entry.nodes.values():
            if node is not entry.root and not node.hidden:
                lookup[(entry.name, node.display_path())] = (entry, node)

    def item_html(
        entry: AppEntry,
        node: CommandInfo,
    ) -> str:
        if node.is_group:
            kind, kind_cls = "命令组", "is-group"
        else:
            kind, kind_cls = "可执行", "is-run"
        desc = _one_line_help(node) or "（暂无说明）"
        indent = max(0, node.level - 1) * 16
        is_fav = (entry.name, node.display_path()) in favorites
        label = "★" if is_fav else "☆"
        title = "取消收藏" if is_fav else "收藏该命令"
        fav_html = (
            '<form method="post" action="/overview/favorite" class="cliui-overview-fav">'
            f'<input type="hidden" name="app" value="{esc(entry.name)}">'
            f'<input type="hidden" name="q" value="{esc(query)}">'
            f'<input type="hidden" name="path" value="{esc(node.display_path())}">'
            f'<button type="submit" title="{title}" class="cliui-overview-star'
            f'{"" if is_fav else " is-empty"}">{label}</button></form>'
        )
        return f"""
<div class="cliui-overview-item">
  <a class="cliui-overview-path" href="{esc(command_url(entry.name, node.node_id))}"
     style="padding-left:{indent}px">{esc(node.display_path())}</a>
  <span class="cliui-overview-kind {kind_cls}">{kind}</span>
  <span class="cliui-overview-desc">{esc(desc)}</span>
  {fav_html}
</div>"""

    def chips(entries: t.List[t.Tuple[AppEntry, CommandInfo]]) -> str:
        if not entries:
            return ""
        links = "".join(
            f'<a class="cliui-overview-chip" href="{esc(command_url(entry.name, node.node_id))}">'
            f"{esc(node.display_path())}</a>"
            for entry, node in entries
        )
        return links

    fav_links = [lookup[key] for key in sorted(favorites) if key in lookup]
    recent_links = [
        lookup[(row["app"], row["command_path"])]
        for row in recent
        if (row.get("app"), row.get("command_path")) in lookup
    ]

    sections: t.List[str] = []
    total_commands = 0
    total_executable = 0
    for entry in apps:
        nodes = [
            node
            for node in entry.nodes.values()
            if node is not entry.root and not node.hidden
        ]
        if keyword:
            nodes = [
                node
                for node in nodes
                if keyword in node.display_path().lower()
                or keyword in _one_line_help(node).lower()
            ]
        nodes.sort(key=lambda node: node.display_path())
        total_commands += len(nodes)
        total_executable += sum(1 for node in nodes if node.executable)
        if keyword and not nodes:
            continue
        rows = [item_html(entry, node) for node in nodes]
        body_html = "".join(rows) or (
            '<div class="cliui-overview-empty">该应用还没有可展示的命令。</div>'
        )
        sections.append(
            f"""
<section class="cliui-overview-app">
  <div class="cliui-overview-app-head">
    <div>
      <div class="cliui-overview-app-title">{esc(entry.display_name())}</div>
      <div class="cliui-overview-app-sub">{esc(entry.description or "（暂无应用说明）")}</div>
    </div>
    <div class="cliui-overview-app-actions">
      <span class="cliui-meta-chip">命令 {len(nodes)}</span>
      <a class="cliui-overview-open" href="{esc(_app_link(entry))}">打开控制台</a>
    </div>
  </div>
  <div class="cliui-overview-list-head">
    <span>命令路径（点击进入）</span><span>类型</span><span>一句话说明</span><span></span>
  </div>
  <div class="cliui-overview-list">{body_html}</div>
</section>"""
        )

    if keyword and not sections:
        sections.append(
            f'<div class="cliui-overview-empty">没有匹配 “{esc(query)}” 的命令。'
            '<a class="cliui-overview-open" href="/overview">清除搜索</a></div>'
        )
    elif not sections:
        sections.append(
            '<div class="cliui-overview-empty">还没有注册任何 Click 应用。</div>'
        )

    extras: t.List[str] = []
    if fav_links:
        extras.append(
            f"""
<section class="cliui-overview-extras">
  <div class="cliui-overview-extra-title">我的收藏</div>
  <div class="cliui-overview-chips">{chips(fav_links)}</div>
</section>"""
        )
    if recent_links:
        extras.append(
            f"""
<section class="cliui-overview-extras">
  <div class="cliui-overview-extra-title">最近使用</div>
  <div class="cliui-overview-chips">{chips(recent_links)}</div>
</section>"""
        )

    content = f"""
<div class="cliui-overview-toolbar">
  <form method="get" action="/overview" class="cliui-overview-search">
    <input type="text" name="q" value="{esc(query)}" placeholder="搜索命令路径或说明">
    <button type="submit">搜索</button>
    {f'<a class="cliui-overview-open" href="/overview">清除</a>' if query else ''}
  </form>
  <div class="cliui-overview-summary">
    <span class="cliui-meta-chip">应用 {len(apps)}</span>
    <span class="cliui-meta-chip">命令 {total_commands}</span>
    <span class="cliui-meta-chip">可执行 {total_executable}</span>
  </div>
</div>
{"".join(extras)}
{"".join(sections)}
"""
    return {
        "type": "page",
        "title": "",
        "className": "cliui-page",
        "body": [
            _topbar(apps, current_app, user, queue_count, "overview"),
            _hero_simple(
                "命令总览",
                "所有已注册 Click 应用的命令树。支持搜索、收藏和最近使用；"
                "点击任意命令直接进入控制台并预选该命令。点击左上角 CLI 标记可随时回到这里。",
            ),
            {"type": "tpl", "tpl": content},
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


def _schedule_plan_fields() -> t.List[t.Dict[str, t.Any]]:
    return [
        {
            "type": "radios",
            "name": "trigger_type",
            "label": "触发方式",
            "options": [
                {"label": "周期（Cron）", "value": "cron"},
                {"label": "单次", "value": "once"},
            ],
        },
        {
            "type": "input-text",
            "name": "cron",
            "label": "Cron 表达式",
            "placeholder": "0 2 * * *",
            "description": "5 段：分 时 日 月 周。",
        },
        {
            "type": "select",
            "name": "cron_preset",
            "label": "常用预设",
            "clearable": True,
            "options": [
                {"label": label, "value": expression}
                for label, expression in CRON_PRESETS
            ],
        },
        {
            "type": "input-text",
            "name": "run_at",
            "label": "单次时间",
            "placeholder": "2026-11-08 09:00:00",
            "description": "仅“单次”方式使用，格式 YYYY-MM-DD HH:MM:SS。",
        },
        {
            "type": "input-text",
            "name": "timezone",
            "label": "时区（IANA）",
            "placeholder": DEFAULT_TIMEZONE,
        },
        {
            "type": "switch",
            "name": "catch_up",
            "label": "停机补跑",
            "description": "调度器停机期间错过的触发默认记为 missed；开启后最多补跑一次。",
        },
    ]


def _shell_schedule_dialog() -> t.Dict[str, t.Any]:
    form = {
        "type": "form",
        "mode": "horizontal",
        "labelWidth": 150,
        "submitOnChange": False,
        "wrapWithPanel": False,
        "data": {
            "trigger_type": "cron",
            "cron": "",
            "cron_preset": "",
            "run_at": "",
            "timezone": DEFAULT_TIMEZONE,
            "catch_up": False,
            "shell_commands": [""],
        },
        "body": [
            {
                "type": "alert",
                "level": "warning",
                "showIcon": True,
                "body": "Shell 命令会以运行 cliui 的系统用户身份执行，请只填写可信内容。"
                "每次触发按顺序执行，每条命令单独写入执行记录。",
            },
            *_schedule_plan_fields(),
            {
                "type": "input-array",
                "name": "shell_commands",
                "label": "Shell 命令",
                "scaffold": "",
                "addable": True,
                "removable": True,
                "minLength": 1,
                "maxLength": 20,
                "items": {
                    "type": "input-text",
                    "placeholder": "echo hello",
                },
                "description": "点击“新增”可以添加多条命令；按顺序执行（最多 20 条）。",
            },
            {
                "type": "button",
                "label": "预览未来 3 次触发",
                "level": "link",
                "actionType": "ajax",
                "api": {"method": "post", "url": "/api/schedules/preview"},
            },
        ],
    }
    actions = [
        {
            "type": "button",
            "label": "取消",
            "actionType": "cancel",
        },
        {
            "type": "submit",
            "label": "创建定时",
            "level": "primary",
            "api": {"method": "post", "url": "/api/schedules/shell"},
            "reload": "cliui-schedules",
        },
    ]
    return {
        "type": "button",
        "label": "新建定时",
        "level": "primary",
        "actionType": "dialog",
        "dialog": {
            "title": "新建定时（Shell）",
            "size": "md",
            "closeOnEsc": True,
            "showCloseButton": True,
            "body": form,
            "actions": actions,
        },
    }


def build_schedules_page(
    apps: t.List[AppEntry],
    current_app: t.Optional[AppEntry],
    user: t.Dict[str, t.Any],
    queue_count: int,
) -> t.Dict[str, t.Any]:
    columns: t.List[t.Dict[str, t.Any]] = [
        {"name": "id", "label": "#", "width": 70},
        {"name": "app_name", "label": "应用", "width": 110},
        {"name": "command_summary", "label": "命令", "minWidth": 320},
        {
            "type": "tpl",
            "name": "plan",
            "label": "计划",
            "tpl": "${cron || run_at}",
            "minWidth": 200,
        },
        {"name": "timezone", "label": "时区", "width": 140},
        {
            "name": "enabled",
            "label": "状态",
            "type": "mapping",
            "map": {"1": "已启用", "0": "已暂停"},
            "width": 90,
        },
        {"name": "next_run_at", "label": "下次运行", "width": 170},
        {"name": "last_run_at", "label": "上次运行", "width": 170},
        {
            "name": "last_status",
            "label": "上次结果",
            "type": "mapping",
            "map": SCHEDULE_STATUS_LABELS,
            "width": 110,
        },
    ]
    if user.get("is_admin"):
        columns.append({"name": "created_by_name", "label": "创建人", "width": 110})
    columns.append(
        {
            "type": "operation",
            "label": "操作",
            "width": 300,
            "buttons": [
                {
                    "type": "button",
                    "label": "详情",
                    "level": "link",
                    "actionType": "url",
                    "blank": False,
                    "url": "/schedules/${id}",
                },
                {
                    "type": "button",
                    "label": "立即运行",
                    "level": "link",
                    "actionType": "ajax",
                    "api": {"method": "post", "url": "/api/schedules/${id}/run"},
                    "confirmText": "立即执行一次该定时任务？执行记录会标记为“定时”。",
                    "reload": "cliui-schedules",
                },
                {
                    "type": "button",
                    "label": "暂停",
                    "level": "link",
                    "actionType": "ajax",
                    "api": {"method": "post", "url": "/api/schedules/${id}/toggle?enabled=0"},
                    "reload": "cliui-schedules",
                    "visibleOn": "this.enabled",
                },
                {
                    "type": "button",
                    "label": "启用",
                    "level": "link",
                    "actionType": "ajax",
                    "api": {"method": "post", "url": "/api/schedules/${id}/toggle?enabled=1"},
                    "reload": "cliui-schedules",
                    "visibleOn": "!this.enabled",
                },
                {
                    "type": "button",
                    "label": "复制",
                    "level": "link",
                    "actionType": "ajax",
                    "api": {"method": "post", "url": "/api/schedules/${id}/duplicate"},
                    "reload": "cliui-schedules",
                },
                {
                    "type": "button",
                    "label": "记录",
                    "level": "link",
                    "actionType": "url",
                    "blank": False,
                    "url": "/records/${last_execution_id}",
                    "visibleOn": "this.last_execution_id",
                },
                {
                    "type": "button",
                    "label": "删除",
                    "level": "link",
                    "className": "text-danger",
                    "actionType": "ajax",
                    "api": {"method": "delete", "url": "/api/schedules/${id}"},
                    "confirmText": "确定删除该定时任务？已有的执行记录会保留。",
                    "reload": "cliui-schedules",
                },
            ],
        }
    )
    crud = {
        "type": "crud",
        "name": "cliui-schedules",
        "api": {"method": "get", "url": "/api/schedules"},
        "syncLocation": False,
        "perPage": 20,
        "filterTogglable": False,
        "filter": {
            "title": "筛选条件",
            "body": [
                {
                    "type": "select",
                    "name": "app",
                    "label": "应用",
                    "clearable": True,
                    "options": [
                        {"label": app.display_name(), "value": app.name} for app in apps
                    ],
                }
            ],
            "submitOnChange": True,
        },
        "headerToolbar": [
            _shell_schedule_dialog(),
            "filter-toggler",
            {"type": "reload"},
            "statistics",
            "pagination",
        ],
        "footerToolbar": ["statistics", "pagination"],
        "columns": columns,
        "placeholder": "还没有定时任务。点击“新建定时”可创建 Shell 计划，或在命令表单中点击“加入定时”创建 Click 命令计划。",
    }
    return {
        "type": "page",
        "title": "",
        "className": "cliui-page cliui-wide-page",
        "body": [
            _topbar(apps, current_app, user, queue_count, "schedules"),
            _hero_simple(
                "定时任务",
                "定时任务按 Cron 表达式或单次时间自动执行命令；执行结果会写入执行记录并标记为“定时”。"
                "普通用户只能管理自己创建的定时任务，管理员可以查看全部。",
            ),
            crud,
        ],
    }


def _find_command_node(entry: AppEntry, command_path: str) -> t.Optional[CommandInfo]:
    for node in entry.nodes.values():
        if node.executable and node.display_path() == command_path:
            return node
    return None


def build_schedule_detail_page(
    schedule: t.Dict[str, t.Any],
    items: t.List[t.Dict[str, t.Any]],
    executions: t.List[t.Dict[str, t.Any]],
    apps: t.List[AppEntry],
    current_app: t.Optional[AppEntry],
    user: t.Dict[str, t.Any],
    queue_count: int,
) -> t.Dict[str, t.Any]:
    schedule_id = int(schedule.get("id") or 0)
    enabled = bool(schedule.get("enabled"))
    plan_text = schedule.get("cron") or schedule.get("run_at") or "（未设置）"
    last_status = str(schedule.get("last_status") or "")
    status_text = SCHEDULE_STATUS_LABELS.get(last_status, "从未运行")

    item_rows: t.List[str] = []
    for index, item in enumerate(items):
        app_name = str(item.get("app_name") or "")
        command_path = str(item.get("command_path") or "")
        shell_command = str(item.get("shell") or "").strip()
        argv_label = str(item.get("argv_label") or "") or " ".join(
            str(arg) for arg in (item.get("argv") or [])
        )
        if shell_command:
            path_text = (
                f'<span class="cliui-kind-badge">Shell</span> {esc(shell_command)}'
            )
            argv_text = ""
            link = ""
        else:
            entry = next(
                (candidate for candidate in apps if candidate.name == app_name), None
            )
            node = _find_command_node(entry, command_path) if entry else None
            path_text = f"{esc(app_name)} · {esc(command_path)}"
            argv_text = (
                f'<div class="cliui-schedule-item-argv">{esc(argv_label)}</div>'
                if argv_label
                else ""
            )
            link = (
                f'<a class="cliui-schedule-item-link" href="{esc(command_url(entry.name, node.node_id))}">打开命令</a>'
                if entry and node
                else '<span class="cliui-schedule-item-tip">命令已不可用</span>'
            )
        remove = (
            f'<form method="post" action="/schedules/{schedule_id}/items/{index}/remove"'
            ' class="cliui-schedule-item-remove">'
            f'<button type="submit" title="从该计划移除这条命令">移除</button></form>'
            if len(items) > 1
            else '<span class="cliui-schedule-item-tip">至少保留一条</span>'
        )
        item_rows.append(
            f"""
<div class="cliui-schedule-item">
  <span class="cliui-schedule-item-index">{index + 1}</span>
  <div class="cliui-schedule-item-body">
    <div class="cliui-schedule-item-path">{path_text}</div>
    {argv_text}
  </div>
  {link}
  {remove}
</div>"""
        )

    items_html = (
        "".join(item_rows)
        or '<div class="cliui-overview-empty">该计划还没有命令。</div>'
    )

    exec_rows: t.List[str] = []
    for record in executions:
        record_status = str(record.get("status") or "")
        exec_rows.append(
            f"""<tr>
  <td><a href="/records/{record.get('id')}">#{record.get('id')}</a></td>
  <td><span class="cliui-result-status cliui-status-{esc(record_status)}">"""
            f'<span class="cliui-result-dot"></span>{esc(STATUS_LABELS.get(record_status, record_status))}'
            f"</span></td>"
            f"<td>{esc(record.get('exit_code'))}</td>"
            f"<td>{esc(record.get('duration_ms'))} ms</td>"
            f"<td>{esc(record.get('created_at'))}</td>"
            "</tr>"
        )
    exec_html = (
        '<table class="cliui-schedule-runs"><thead><tr><th>#</th><th>状态</th>'
        "<th>退出码</th><th>耗时</th><th>时间</th></tr></thead><tbody>"
        + "".join(exec_rows)
        + "</tbody></table>"
        if exec_rows
        else '<div class="cliui-overview-empty">还没有执行记录。可以点击“立即运行”查看效果。</div>'
    )

    summary_html = f"""
<div class="cliui-schedule-summary">
  <div class="cliui-schedule-summary-row">
    <span class="cliui-result-status cliui-status-{esc('success' if enabled else 'running')}">
      <span class="cliui-result-dot"></span>{'已启用' if enabled else '已暂停'}
    </span>
    <span class="cliui-detail-item">计划 <b>{esc(plan_text)}</b></span>
    <span class="cliui-detail-item">时区 <b>{esc(schedule.get('timezone'))}</b></span>
    <span class="cliui-detail-item">停机补跑 <b>{'开启' if schedule.get('catch_up') else '关闭'}</b></span>
  </div>
  <div class="cliui-schedule-summary-row">
    <span class="cliui-detail-item">下次运行 <b>{esc(schedule.get('next_run_at') or '-')}</b></span>
    <span class="cliui-detail-item">上次运行 <b>{esc(schedule.get('last_run_at') or '-')}</b></span>
    <span class="cliui-detail-item">上次结果 <b>{esc(status_text)}</b></span>
    <span class="cliui-detail-item">创建人 <b>{esc(schedule.get('created_by_name'))}</b></span>
  </div>
</div>
"""

    actions_html = f"""
<div class="cliui-schedule-actions">
  <form method="post" action="/schedules/{schedule_id}/run">
    <button type="submit" class="cliui-action-btn is-primary">立即运行</button>
  </form>
  <form method="post" action="/schedules/{schedule_id}/toggle">
    <input type="hidden" name="enabled" value="{'0' if enabled else '1'}">
    <button type="submit" class="cliui-action-btn">{'暂停' if enabled else '启用'}</button>
  </form>
  <form method="post" action="/schedules/{schedule_id}/duplicate">
    <button type="submit" class="cliui-action-btn">复制为新计划</button>
  </form>
  <a class="cliui-action-link" href="/schedules">返回列表</a>
</div>
"""

    append_hint = ""
    if items:
        first = items[0]
        entry = next(
            (candidate for candidate in apps if candidate.name == first.get("app_name")),
            None,
        )
        node = (
            _find_command_node(entry, str(first.get("command_path") or ""))
            if entry and not str(first.get("shell") or "").strip()
            else None
        )
        if node:
            console_url = "/?" + urlencode(
                {"app": first.get("app_name") or "", "cmd": node.node_id}
            )
            append_hint = (
                '<div class="cliui-schedule-hint">在控制台填好命令参数后，点击“加入定时”弹窗里的'
                '“追加到已有计划”即可增加一条命令；也可以'
                f'<a class="cliui-overview-open" href="{esc(console_url)}">从当前命令继续</a>。</div>'
            )
        else:
            append_hint = (
                '<div class="cliui-schedule-hint">Shell 计划本身不接受追加参数；如需增加命令，'
                "可在控制台打开任意 Click 命令，在“加入定时”弹窗里追加到本计划。</div>"
            )

    edit_form = {
        "type": "form",
        "mode": "horizontal",
        "labelWidth": 170,
        "submitOnChange": False,
        "data": {
            "trigger_type": "once" if schedule.get("run_at") else "cron",
            "cron": schedule.get("cron") or "",
            "cron_preset": "",
            "run_at": schedule.get("run_at") or "",
            "timezone": schedule.get("timezone") or DEFAULT_TIMEZONE,
            "catch_up": bool(schedule.get("catch_up")),
        },
        "body": [
            {
                "type": "radios",
                "name": "trigger_type",
                "label": "触发方式",
                "options": [
                    {"label": "周期（Cron）", "value": "cron"},
                    {"label": "单次", "value": "once"},
                ],
            },
            {
                "type": "input-text",
                "name": "cron",
                "label": "Cron 表达式",
                "placeholder": "0 2 * * *",
            },
            {
                "type": "select",
                "name": "cron_preset",
                "label": "常用预设",
                "clearable": True,
                "options": [
                    {"label": label, "value": expression}
                    for label, expression in CRON_PRESETS
                ],
            },
            {
                "type": "input-text",
                "name": "run_at",
                "label": "单次时间",
                "placeholder": "2026-11-08 09:00:00",
            },
            {
                "type": "input-text",
                "name": "timezone",
                "label": "时区（IANA）",
                "placeholder": DEFAULT_TIMEZONE,
            },
            {
                "type": "switch",
                "name": "catch_up",
                "label": "停机补跑",
                "description": "调度器停机期间错过的触发会记为 missed；开启后最多补跑一次。",
            },
        ],
        "actions": [
            {
                "type": "submit",
                "label": "保存计划",
                "level": "primary",
                "api": {"method": "post", "url": f"/api/schedules/{schedule_id}/edit"},
                "redirect": f"/schedules/{schedule_id}",
            },
        ],
    }

    return {
        "type": "page",
        "title": "",
        "className": "cliui-page cliui-wide-page",
        "body": [
            _topbar(apps, current_app, user, queue_count, "schedules"),
            _hero_simple(
                f"定时任务 #{schedule_id}",
                "一个计划可以包含多条命令，每次触发会按顺序执行并分别写入执行记录；"
                "修改计划时间后立即生效，复制计划可以复用同一组命令。",
            ),
            {"type": "tpl", "tpl": summary_html + actions_html},
            {"type": "panel", "title": "计划设置", "body": [edit_form]},
            {
                "type": "panel",
                "title": f"命令列表（{len(items)} 条）",
                "body": [
                    {"type": "tpl", "tpl": f'<div class="cliui-schedule-items">{items_html}</div>'},
                    {"type": "tpl", "tpl": append_hint} if append_hint else _alert(
                        "info", "该计划还没有命令，请到控制台创建命令后追加。"
                    ),
                ],
            },
            {"type": "panel", "title": "最近执行", "body": [{"type": "tpl", "tpl": exec_html}]},
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
            *(
                [
                    _alert(
                        "info",
                        "该命令正在后台执行，结果尚未写入。可稍后刷新本页查看最终状态。",
                    ),
                    {
                        "type": "button",
                        "label": "刷新状态",
                        "level": "primary",
                        "actionType": "url",
                        "blank": False,
                        "url": f"/records/{record.get('id')}",
                    },
                ]
                if status == "running"
                else []
            ),
            {
                "type": "tpl",
                "tpl": f"""
<div class="cliui-detail-head">
  <span class="cliui-result-status cliui-status-{esc(status)}"><span class="cliui-result-dot"></span>{esc(status_label)}</span>
  <span class="cliui-detail-item">退出码 <b>{esc(record.get('exit_code'))}</b></span>
  <span class="cliui-detail-item">耗时 <b>{esc(record.get('duration_ms'))} ms</b></span>
  <span class="cliui-detail-item">执行人 <b>{esc(record.get('username'))}</b></span>
  <span class="cliui-detail-item">来源 <b>{esc('定时' if record.get('trigger') == 'schedule' else '手动')}</b></span>
  <span class="cliui-detail-item">时间 <b>{esc(record.get('created_at'))}</b></span>
</div>
<div class="cliui-detail-path">{esc(record.get('command_path'))}{(' · 定时任务 #' + str(record.get('schedule_id'))) if record.get('schedule_id') else ''}</div>
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
