"""Load Click applications from ``module:attr`` or ``file.py:attr`` specs."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import os
import sys
import typing as t
from dataclasses import dataclass
from pathlib import Path

import click

from cliui.introspect.tree import build_app_tree
from cliui.model import AppEntry


class AppLoadError(RuntimeError):
    """A spec could not be turned into a Click application."""


@dataclass
class AppSpec:
    target: str
    name: t.Optional[str] = None

    @property
    def raw(self) -> str:
        return f"{self.name}={self.target}" if self.name else self.target


def parse_spec(raw: str) -> AppSpec:
    text = raw.strip()
    if not text:
        raise AppLoadError("应用地址不能为空，格式为 module:attr 或 file.py:attr")
    name: t.Optional[str] = None
    if "=" in text.split(":", 1)[0]:
        name, text = text.split("=", 1)
        name = name.strip()
        text = text.strip()
        if not name:
            raise AppLoadError(f"应用名称为空: {raw}")
    if ":" not in text:
        raise AppLoadError(
            f"应用地址缺少属性名: {raw}（正确格式：module:attr 或 file.py:attr）"
        )
    module_part, attr = text.rsplit(":", 1)
    if not module_part.strip() or not attr.strip():
        raise AppLoadError(f"应用地址不完整: {raw}")
    return AppSpec(target=text, name=name)


def _resolve_attribute(obj: t.Any, attr: str) -> t.Any:
    for part in attr.split("."):
        if not part:
            raise AppLoadError(f"属性路径不合法: {attr}")
        try:
            obj = getattr(obj, part)
        except AttributeError as exc:
            raise AppLoadError(f"找不到属性 {attr}") from exc
    return obj


def _is_file_target(module_part: str) -> bool:
    return module_part.endswith(".py") or os.path.exists(
        os.path.expanduser(module_part)
    )


def _load_module(module_part: str, base_cwd: str, reload_module: bool = False) -> t.Any:
    if _is_file_target(module_part):
        path = Path(os.path.expanduser(module_part))
        if not path.is_absolute():
            path = Path(base_cwd) / path
        path = path.resolve()
        if not path.is_file():
            raise AppLoadError(f"Python 文件不存在: {path}")
        digest = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:10]
        module_name = f"_cliui_app_{path.stem}_{digest}"
        parent = str(path.parent)
        if parent not in sys.path:
            sys.path.insert(0, parent)
        spec = importlib.util.spec_from_file_location(module_name, str(path))
        if spec is None or spec.loader is None:
            raise AppLoadError(f"无法导入 Python 文件: {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            # Compile straight from the source: ``exec_module`` may reuse a
            # stale ``.pyc`` when a file changes within the same second without
            # changing its size, which is exactly what a reload must catch.
            code = compile(path.read_text(encoding="utf-8"), str(path), "exec")
            exec(code, module.__dict__)
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller
            sys.modules.pop(module_name, None)
            raise AppLoadError(f"导入 {path} 失败: {exc}") from exc
        return module

    try:
        module = importlib.import_module(module_part)
        if reload_module:
            # Module targets stay in ``sys.modules``; re-executing them is the
            # only way to pick up edits made after the server started.
            importlib.invalidate_caches()
            module = importlib.reload(module)
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller
        action = "重新加载模块" if reload_module else "导入模块"
        raise AppLoadError(f"{action} {module_part} 失败: {exc}") from exc
    return module


def _build_entry(
    raw_spec: str,
    base_cwd: str,
    name: t.Optional[str] = None,
    reload_module: bool = False,
) -> AppEntry:
    spec = parse_spec(raw_spec)
    module_part, attr = spec.target.rsplit(":", 1)
    module = _load_module(module_part, base_cwd, reload_module=reload_module)
    try:
        cli = _resolve_attribute(module, attr)
    except AppLoadError:
        raise
    if not isinstance(cli, click.Command):
        raise AppLoadError(
            f"{spec.target} 不是 click.Command（实际类型 {type(cli).__name__}）"
        )

    if _is_file_target(module_part):
        path = Path(os.path.expanduser(module_part))
        if not path.is_absolute():
            path = Path(base_cwd) / path
        cwd = str(path.resolve().parent)
        fallback_name = path.stem
    else:
        cwd = base_cwd
        fallback_name = module_part.rsplit(".", 1)[-1]

    entry = AppEntry(
        name=name or spec.name or cli.name or fallback_name,
        title=cli.name or fallback_name,
        cli=cli,
        cwd=cwd,
        import_spec=spec.target,
        base_cwd=base_cwd,
    )
    build_app_tree(entry)
    return entry


def load_app_entry(raw_spec: str, base_cwd: str) -> AppEntry:
    return _build_entry(raw_spec, base_cwd)


def reload_app_entry(entry: AppEntry) -> AppEntry:
    """Re-import the application behind ``entry`` and rebuild its command tree.

    File based apps are executed again from disk; module based apps are
    reloaded through :func:`importlib.reload`.  The registered name is kept so
    existing URLs (``?app=...``) stay valid.
    """
    if not entry.import_spec:
        raise AppLoadError(f"应用 {entry.name} 缺少原始导入地址，无法重新加载")
    return _build_entry(
        entry.import_spec,
        entry.base_cwd or os.getcwd(),
        name=entry.name,
        reload_module=True,
    )


def load_apps(specs: t.Sequence[str], base_cwd: t.Optional[str] = None) -> t.List[AppEntry]:
    cwd = base_cwd or os.getcwd()
    entries: t.List[AppEntry] = []
    used: t.Dict[str, str] = {}
    for raw in specs:
        entry = load_app_entry(raw, cwd)
        key = entry.name.casefold()
        if key in used:
            raise AppLoadError(
                f"应用名称重复: {entry.name}（来自 {used[key]} 与 {entry.import_spec}）。"
                " 请使用 name=module:attr 为其中一个指定不同名称。"
            )
        used[key] = entry.import_spec or raw
        entries.append(entry)
    return entries
