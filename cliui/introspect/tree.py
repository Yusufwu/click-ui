"""Build a UI friendly command tree from Click objects."""

from __future__ import annotations

import logging
import typing as t

import click

from cliui.introspect.params import collect_params
from cliui.model import AppEntry, CommandInfo

logger = logging.getLogger(__name__)

MAX_DEPTH = 40


def _resolve_child(value: t.Any) -> t.Optional[click.Command]:
    if isinstance(value, click.Command):
        return value
    if callable(value):
        try:
            resolved = value()
        except Exception:
            logger.exception("lazy click command could not be loaded")
            return None
        if isinstance(resolved, click.Command):
            return resolved
    return None


def _child_commands(command: click.Command) -> t.Dict[str, click.Command]:
    if isinstance(command, click.CommandCollection):
        merged: t.Dict[str, click.Command] = {}
        for source in list(getattr(command, "sources", ())):
            for name, child in _child_commands(source).items():
                # Click itself resolves duplicate names from the first source;
                # mirror that behaviour instead of inventing a new dispatch rule.
                merged.setdefault(name, child)
        return merged

    if isinstance(command, click.MultiCommand):
        result: t.Dict[str, click.Command] = {}
        ctx: t.Optional[click.Context] = None
        try:
            ctx = click.Context(command, info_name=command.name)
            names = list(command.list_commands(ctx))
        except Exception:
            names = []
        for child_name in names:
            try:
                child = command.get_command(ctx, child_name)  # type: ignore[arg-type]
            except Exception:
                logger.exception("lazy click command could not be loaded: %s", child_name)
                child = None
            resolved = _resolve_child(child)
            if resolved is not None:
                result[child_name] = resolved
        if result:
            return result

        raw = getattr(command, "commands", {}) or {}
        if callable(raw) and not hasattr(raw, "items"):
            try:
                raw = raw()
            except Exception:
                logger.exception("callable click commands could not be resolved")
                raw = {}
        if hasattr(raw, "items"):
            for name, value in raw.items():
                resolved = _resolve_child(value)
                if resolved is not None:
                    result[name] = resolved
        return result

    return {}


def _usage_for(command: click.Command, parent_ctx: t.Optional[click.Context]) -> str:
    try:
        ctx = click.Context(command, info_name=command.name, parent=parent_ctx)
        return command.get_usage(ctx)
    except Exception:
        return command.name or ""


def build_app_tree(entry: AppEntry) -> CommandInfo:
    """Populate ``entry.root`` / ``entry.nodes`` from ``entry.cli``."""
    counter = {"value": 0}

    def walk(
        command: click.Command,
        name: str,
        path: str,
        parent: t.Optional[CommandInfo],
        level: int,
        parent_ctx: t.Optional[click.Context],
    ) -> CommandInfo:
        node_id = f"n{counter['value']}"
        counter["value"] += 1
        node = CommandInfo(node_id=node_id, name=name, path=path, command=command, level=level)
        node.parent = parent
        node.help = (getattr(command, "help", None) or "").strip()
        try:
            node.short_help = command.get_short_help_str(limit=140)
        except Exception:
            node.short_help = node.help.splitlines()[0] if node.help else ""
        node.hidden = bool(getattr(command, "hidden", False))
        node.deprecated = bool(getattr(command, "deprecated", False))
        node.is_group = isinstance(command, click.MultiCommand)
        node.chain = bool(getattr(command, "chain", False))
        node.invoke_without_command = bool(getattr(command, "invoke_without_command", False))
        node.no_args_is_help = bool(getattr(command, "no_args_is_help", False))
        node.allow_extra_args = bool(getattr(command, "allow_extra_args", False))
        node.command_collection = isinstance(command, click.CommandCollection)
        node.usage = _usage_for(command, parent_ctx)

        key_prefix = f"c__" if parent is None else f"g{level - 1}__"
        node.params = collect_params(command, level, key_prefix)

        try:
            ctx = click.Context(command, info_name=name, parent=parent_ctx)
        except Exception:
            ctx = parent_ctx

        entry.nodes[node_id] = node

        if node.is_group and level < MAX_DEPTH:
            for child_name, child in _child_commands(command).items():
                child_path = f"{path} {child_name}".strip()
                child_node = walk(child, child_name, child_path, node, level + 1, ctx)
                if not child_node.hidden:
                    node.children.append(child_node)

        return node

    entry.nodes.clear()
    root_name = entry.cli.name or entry.name
    root = walk(entry.cli, root_name, "", None, 0, None)
    entry.root = root
    entry.description = root.help.splitlines()[0] if root.help else ""
    return root


def flatten_nodes(node: CommandInfo) -> t.List[CommandInfo]:
    out: t.List[CommandInfo] = [node]
    for child in node.children:
        out.extend(flatten_nodes(child))
    return out
