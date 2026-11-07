"""Introspection data model shared by the schema, executor and web layers."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import click


@dataclass
class ParamInfo:
    """A single Click parameter (``Option`` or ``Argument``) enriched for the UI."""

    key: str
    name: str
    kind: str  # "option" | "argument"
    level: int
    param: click.Parameter
    label: str
    help: str
    required: bool
    default: Any = None
    multiple: bool = False
    nargs: Optional[int] = 1
    hidden: bool = False
    is_flag: bool = False
    flag_value: Any = True
    count: bool = False
    hide_input: bool = False
    envvar: Optional[str] = None
    prompt: bool = False
    metavar: Optional[str] = None
    opts: List[str] = field(default_factory=list)
    secondary_opts: List[str] = field(default_factory=list)
    type_kind: str = "text"
    type_name: str = "text"
    choices: List[Any] = field(default_factory=list)
    case_sensitive: bool = True
    min: Any = None
    max: Any = None
    min_open: bool = False
    max_open: bool = False
    clamp: bool = False
    datetime_formats: List[str] = field(default_factory=list)
    path_exists: bool = False
    path_file_okay: bool = True
    path_dir_okay: bool = True
    path_readable: bool = False
    path_writable: bool = False
    path_executable: bool = False
    path_resolve: bool = False
    path_allow_dash: bool = False
    file_mode: str = "r"
    file_lazy: bool = False
    tuple_types: List[Any] = field(default_factory=list)
    description: str = ""

    @property
    def is_argument(self) -> bool:
        return self.kind == "argument"

    @property
    def is_option(self) -> bool:
        return self.kind == "option"

    @property
    def name_tokens(self) -> List[str]:
        return list(self.opts) + list(self.secondary_opts)

    def preferred_opt(self) -> str:
        """Return the most readable option string (long form first)."""
        long_opts = [opt for opt in self.opts if opt.startswith("--")]
        if long_opts:
            return long_opts[0]
        return self.opts[0] if self.opts else f"--{self.name}"

    def preferred_secondary_opt(self) -> Optional[str]:
        long_opts = [opt for opt in self.secondary_opts if opt.startswith("--")]
        if long_opts:
            return long_opts[0]
        return self.secondary_opts[0] if self.secondary_opts else None


@dataclass
class CommandInfo:
    """A command node in the Click command tree."""

    node_id: str
    name: str
    path: str
    command: click.Command
    level: int
    params: List[ParamInfo] = field(default_factory=list)
    children: List["CommandInfo"] = field(default_factory=list)
    parent: Optional["CommandInfo"] = None
    help: str = ""
    short_help: str = ""
    usage: str = ""
    hidden: bool = False
    deprecated: bool = False
    is_group: bool = False
    chain: bool = False
    invoke_without_command: bool = False
    no_args_is_help: bool = False
    allow_extra_args: bool = False
    command_collection: bool = False

    @property
    def executable(self) -> bool:
        if not self.is_group:
            return True
        return bool(self.invoke_without_command)

    def ancestors(self) -> List["CommandInfo"]:
        nodes: List[CommandInfo] = []
        node: Optional[CommandInfo] = self
        while node is not None:
            nodes.append(node)
            node = node.parent
        return list(reversed(nodes))

    def display_path(self) -> str:
        if not self.path:
            return self.name
        return self.path


@dataclass
class AppEntry:
    """A registered Click application."""

    name: str
    title: str
    cli: click.Command
    cwd: str
    root: Optional[CommandInfo] = None
    nodes: Dict[str, CommandInfo] = field(default_factory=dict)
    import_spec: Optional[str] = None
    base_cwd: str = ""
    description: str = ""

    def resolve(self, node_id: Optional[str]) -> Optional[CommandInfo]:
        if node_id in (None, ""):
            return None
        return self.nodes.get(node_id)

    def executable_nodes(self) -> List[CommandInfo]:
        return [node for node in self.nodes.values() if node.executable]

    def default_node(self) -> Optional[CommandInfo]:
        if self.root.executable and (not self.root.is_group or not self.root.children):
            return self.root
        executable = self.executable_nodes()
        return executable[0] if executable else None

    def display_name(self) -> str:
        return self.title or self.name


def default_cwd() -> str:
    return os.getcwd()
