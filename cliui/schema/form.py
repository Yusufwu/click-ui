"""Build AMIS form schemas for a selected Click command."""

from __future__ import annotations

import typing as t

from cliui.model import AppEntry, CommandInfo
from cliui.scheduling import CRON_PRESETS, DEFAULT_TIMEZONE
from cliui.schema.argv import build_form_defaults, collect_scopes, field_key
from cliui.schema.fields import build_field

RESULT_FIELDS: t.List[t.Dict[str, t.Any]] = [
    {
        "type": "tpl",
        "tpl": '<div class="cliui-result-status cliui-status-${result_status}">'
        '<span class="cliui-result-dot"></span>${result_status_label}</div>',
    },
    {
        "type": "flex",
        "className": "cliui-result-meta",
        "items": [
            {"type": "static", "name": "result_exit_code", "label": "退出码"},
            {"type": "static", "name": "result_duration_label", "label": "耗时"},
            {"type": "static", "name": "result_command_label", "label": "命令"},
        ],
    },
    {"type": "static", "name": "result_message", "label": "说明", "visibleOn": "this.result_message"},
    {
        "type": "tpl",
        "tpl": '<div class="cliui-record-link"><a href="/records/${result_record_id}" target="_blank">'
        "查看完整执行记录 #${result_record_id}</a></div>",
        "visibleOn": "this.result_record_id",
    },
    {
        "type": "static",
        "name": "result_truncated_note",
        "label": "提示",
        "visibleOn": "this.result_truncated",
    },
    {
        "type": "static",
        "name": "result_argv",
        "label": "命令预览",
        "className": "cliui-output-field",
        "copyable": True,
    },
    {
        "type": "static",
        "name": "result_stdout",
        "label": "标准输出 (stdout)",
        "className": "cliui-output-field",
        "copyable": True,
    },
    {
        "type": "static",
        "name": "result_stderr",
        "label": "标准错误 (stderr)",
        "className": "cliui-output-field",
        "copyable": True,
        "visibleOn": "this.result_stderr",
    },
    {
        "type": "static",
        "name": "result_exception",
        "label": "异常堆栈",
        "className": "cliui-output-field",
        "copyable": True,
        "visibleOn": "this.result_exception",
    },
]


def build_command_form(
    app: AppEntry,
    node: CommandInfo,
    initial_values: t.Optional[t.Dict[str, t.Any]] = None,
) -> t.Dict[str, t.Any]:
    scopes = collect_scopes(node)
    data = build_form_defaults(node, scopes, initial_values)
    data["_cliui_app"] = app.name
    data["_cliui_command"] = node.node_id
    data["trigger_type"] = "cron"
    data["cron"] = ""
    data["cron_preset"] = ""
    data["run_at"] = ""
    data["timezone"] = DEFAULT_TIMEZONE
    data["catch_up"] = False
    data["background"] = False
    data["append_schedule_id"] = ""

    body: t.List[t.Dict[str, t.Any]] = [
        {
            "type": "hidden",
            "name": "_cliui_app",
        },
        {
            "type": "hidden",
            "name": "_cliui_command",
        },
    ]

    # Global options that must be placed before the sub-command token.
    ancestors = scopes[:-1]
    for index, scope in enumerate(ancestors):
        if not scope.params:
            continue
        fields: t.List[t.Dict[str, t.Any]] = []
        for param in scope.params:
            fields.extend(build_field(param, field_key(scope, param)))
        body.append(
            {
                "type": "collapse-group",
                "activeKey": [],
                "body": [
                    {
                        "type": "collapse",
                        "key": f"globals-{index}",
                        "header": f"全局参数 · {scope.command.path or scope.command.name}",
                        "body": fields,
                    }
                ],
            }
        )

    normal_fields: t.List[t.Dict[str, t.Any]] = []
    hidden_fields: t.List[t.Dict[str, t.Any]] = []
    for param in node.params:
        target = hidden_fields if param.hidden else normal_fields
        target.extend(build_field(param, field_key(scopes[-1], param)))

    if normal_fields:
        body.append(
            {
                "type": "panel",
                "title": "命令参数",
                "className": "cliui-fields-panel",
                "body": normal_fields,
            }
        )
    else:
        body.append(
            {
                "type": "alert",
                "level": "info",
                "showIcon": True,
                "body": "该命令没有可填写的参数，直接点击“执行”即可。",
            }
        )
    if hidden_fields:
        body.append(
            {
                "type": "collapse-group",
                "activeKey": [],
                "body": [
                    {
                        "type": "collapse",
                        "key": "hidden-params",
                        "header": "高级参数（Click 帮助中默认隐藏）",
                        "body": hidden_fields,
                    }
                ],
            }
        )

    body.append(
        {
            "type": "panel",
            "title": "定时设置（可选）",
            "className": "cliui-schedule-panel",
            "body": [
                {
                    "type": "alert",
                    "level": "info",
                    "showIcon": True,
                    "body": "填写下面的计划后点击“加入定时”，命令会按 Cron 或单次时间自动执行。"
                    "不填也可以正常“执行”或“加入队列”。",
                },
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
                    "description": "5 段：分 时 日 月 周；与下方“常用预设”二选一（都填时以这里为准）。",
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
                    "description": "默认 Asia/Shanghai。",
                },
                {
                    "type": "switch",
                    "name": "catch_up",
                    "label": "停机补跑",
                    "description": "调度器停机期间错过的触发默认记为 missed；开启后最多补跑一次。",
                },
                {
                    "type": "action",
                    "label": "预览未来 3 次触发",
                    "level": "link",
                    "actionType": "ajax",
                    "api": {"method": "post", "url": "/api/schedules/preview"},
                },
                {"type": "divider"},
                {
                    "type": "select",
                    "name": "append_schedule_id",
                    "label": "追加到已有计划",
                    "clearable": True,
                    "source": {"method": "get", "url": "/api/schedules?perPage=100"},
                    "labelField": "title",
                    "valueField": "id",
                    "description": "把当前命令（含已填参数）追加到一条已有计划；"
                    "一个计划可以包含多条命令，按顺序执行。",
                },
                {
                    "type": "submit",
                    "label": "追加到已有计划",
                    "level": "info",
                    "visibleOn": "this.append_schedule_id != null && this.append_schedule_id != ''",
                    "api": {
                        "method": "post",
                        "url": "/api/schedules/${append_schedule_id}/items",
                    },
                },
            ],
        }
    )

    body.append(
        {
            "type": "panel",
            "title": "执行选项（可选）",
            "className": "cliui-exec-options",
            "body": [
                {
                    "type": "switch",
                    "name": "background",
                    "label": "后台执行",
                    "description": "适合长时间运行的任务：点击“执行”后立即返回，"
                    "命令在后台继续运行；可在执行记录中查看最终结果。",
                }
            ],
        }
    )

    body.append(
        {
            "type": "panel",
            "title": "执行结果",
            "className": "cliui-result-panel",
            "visibleOn": "this.result_status != null",
            "body": RESULT_FIELDS,
        }
    )

    form: t.Dict[str, t.Any] = {
        "type": "form",
        "name": "cliui-command-form",
        "id": "cliui-command-form",
        "mode": "horizontal",
        "labelWidth": 170,
        "submitOnChange": False,
        "persistData": False,
        "resetAfterSubmit": False,
        "data": data,
        "body": body,
        "actions": [
            {
                "type": "submit",
                "label": "执行",
                "level": "primary",
                "tooltip": "立即执行命令，显示结果",
                "api": {"method": "post", "url": "/api/execute"},
            },
            {
                "type": "submit",
                "label": "加入队列",
                "level": "info",
                "tooltip": "点击“加入队列”不会立即执行；可以在“记录队列”页中把多条命令批量执行。",
                "api": {"method": "post", "url": "/api/queue"},
            },
            {
                "type": "submit",
                "label": "加入定时",
                "level": "success",
                "tooltip": "按上方“定时设置”创建定时任务；不会立即执行。可在“定时任务”页查看与启停。",
                "api": {"method": "post", "url": "/api/schedules"},
            },
            {
                "type": "submit",
                "label": "预览命令",
                "level": "default",
                "api": {"method": "post", "url": "/api/preview"},
            },
            {
                "type": "reset",
                "label": "重置表单",
            },
        ],
    }
    return form
