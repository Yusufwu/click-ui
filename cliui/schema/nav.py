"""Build the AMIS navigation tree."""

from __future__ import annotations

import typing as t
from urllib.parse import urlencode

from cliui.model import AppEntry, CommandInfo


def command_url(app_name: str, node_id: t.Optional[str] = None) -> str:
    params = {"app": app_name}
    if node_id:
        params["cmd"] = node_id
    return "/?" + urlencode(params)


def _selected_ids(node: t.Optional[CommandInfo]) -> t.Set[str]:
    if node is None:
        return set()
    return {item.node_id for item in node.ancestors()}


def _link(app: AppEntry, node: CommandInfo, selected: t.Optional[CommandInfo]) -> t.Dict[str, t.Any]:
    selected_ids = _selected_ids(selected)
    active = selected is not None and selected.node_id == node.node_id
    if node.is_group:
        unfolded = node.node_id in selected_ids
        custom = []
        if node.deprecated:
            custom.append("已废弃")
        if node.children:
            custom.append(str(len(node.children)))
        link: t.Dict[str, t.Any] = {
            "label": node.name,
            "to": command_url(app.name, node.node_id),
            "active": active,
            "unfolded": unfolded,
        }
        if custom:
            link["customText"] = " · ".join(custom)
        children = [_link(app, child, selected) for child in node.children]
        if children:
            link["children"] = children
        return link
    return {
        "label": node.name,
        "to": command_url(app.name, node.node_id),
        "active": active,
        "customText": "已废弃" if node.deprecated else "",
    }


def build_nav(app: AppEntry, selected: t.Optional[CommandInfo]) -> t.Dict[str, t.Any]:
    root_link: t.Dict[str, t.Any] = {
        "label": app.display_name(),
        "to": command_url(app.name),
        "active": selected is None,
        "unfolded": True,
    }
    if app.root.executable:
        root_link["to"] = command_url(app.name, app.root.node_id)
        root_link["active"] = (
            selected is None and app.root.executable
        ) or (selected is not None and selected.node_id == app.root.node_id)
    if app.root.is_group:
        children = [_link(app, child, selected) for child in app.root.children]
        if children:
            root_link["children"] = children
    elif not app.root.is_group:
        root_link["to"] = command_url(app.name, app.root.node_id)
        root_link["active"] = selected is None or selected.node_id == app.root.node_id
    return {
        "type": "nav",
        "className": "cliui-nav",
        "stacked": True,
        "searchable": True,
        "searchPlaceholder": "搜索命令…",
        "defaultOpenLevel": 2,
        "links": [root_link],
    }
