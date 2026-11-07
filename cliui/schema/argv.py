"""Turn AMIS form values back into a Click argv list, with friendly validation."""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shlex
import subprocess
import sys
import typing as t
from dataclasses import dataclass, field

from cliui.model import CommandInfo, ParamInfo

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


@dataclass
class Scope:
    prefix: str
    command: CommandInfo
    selected: bool
    params: t.List[ParamInfo]


@dataclass
class ScopedValue:
    scope: Scope
    param: ParamInfo
    key: str
    value: t.Any


@dataclass
class ParsedCommand:
    node: CommandInfo
    scopes: t.List[Scope]
    values: t.List[ScopedValue] = field(default_factory=list)
    errors: t.Dict[str, str] = field(default_factory=dict)
    argv: t.List[str] = field(default_factory=list)
    field_values: t.Dict[str, t.Any] = field(default_factory=dict)


def collect_scopes(node: CommandInfo) -> t.List[Scope]:
    chain = node.ancestors()
    scopes: t.List[Scope] = []
    for index, ancestor in enumerate(chain[:-1]):
        scopes.append(Scope(prefix=f"g{index}__", command=ancestor, selected=False, params=ancestor.params))
    scopes.append(Scope(prefix="c__", command=node, selected=True, params=node.params))
    return scopes


def field_key(scope: Scope, param: ParamInfo) -> str:
    return f"{scope.prefix}{param.key}"


def _json_safe(value: t.Any) -> t.Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def default_value(param: ParamInfo) -> t.Any:
    if param.count:
        try:
            return int(param.default or 0)
        except (TypeError, ValueError):
            return 0
    if param.is_flag:
        return bool(param.default) if param.default is not None else False
    if param.multiple:
        if param.default is None:
            return []
        try:
            values = list(param.default)
        except TypeError:
            values = [param.default]
        if param.nargs and param.nargs > 1:
            flat: t.List[t.Any] = []
            for item in values:
                if isinstance(item, (list, tuple)):
                    flat.extend(item)
                else:
                    flat.append(item)
            return flat
        return values
    if param.nargs and param.nargs != 1:
        if param.default is None:
            return []
        try:
            return list(param.default)
        except TypeError:
            return [param.default]
    if param.type_kind == "bool":
        return bool(param.default) if param.default is not None else False
    return _json_safe(param.default) if param.default is not None else None


def build_form_defaults(
    node: CommandInfo, scopes: t.List[Scope], initial_values: t.Optional[t.Dict[str, t.Any]] = None
) -> t.Dict[str, t.Any]:
    data: t.Dict[str, t.Any] = {}
    for scope in scopes:
        for param in scope.params:
            key = field_key(scope, param)
            if initial_values and key in initial_values:
                data[key] = initial_values[key]
            else:
                data[key] = default_value(param)
    return data


def _as_bool(value: t.Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "y", "t")
    return bool(value)


def _empty(value: t.Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value == ""
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    return False


def _to_int(value: t.Any, key: str, errors: t.Dict[str, str], label: str) -> t.Optional[int]:
    try:
        if isinstance(value, bool):
            return int(value)
        return int(str(value).strip())
    except (TypeError, ValueError):
        errors[key] = f"{label} 需要是整数"
        return None


def _to_float(value: t.Any, key: str, errors: t.Dict[str, str], label: str) -> t.Optional[float]:
    try:
        if isinstance(value, bool):
            raise ValueError
        return float(str(value).strip())
    except (TypeError, ValueError):
        errors[key] = f"{label} 需要是数字"
        return None


def _match_choice(value: t.Any, param: ParamInfo) -> t.Optional[t.Any]:
    if param.case_sensitive:
        for choice in param.choices:
            if value == choice:
                return choice
        for choice in param.choices:
            if str(choice) == str(value):
                return choice
    else:
        folded = str(value).casefold()
        for choice in param.choices:
            if str(choice).casefold() == folded:
                return choice
    return None


def _convert_datetime(
    value: t.Any, param: ParamInfo, key: str, errors: t.Dict[str, str]
) -> t.Optional[str]:
    if isinstance(value, _dt.datetime):
        parsed = value
    else:
        text = str(value).strip()
        parsed = None
        formats = list(param.datetime_formats or [])
        for fmt in formats:
            try:
                parsed = _dt.datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            for fmt in (
                "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%Y-%m-%d",
                "%Y/%m/%d %H:%M:%S",
                "%Y/%m/%d",
            ):
                try:
                    parsed = _dt.datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
        if parsed is None:
            accepted = ", ".join(formats) if formats else "%Y-%m-%d %H:%M:%S"
            errors[key] = f"时间格式不正确，可接受格式: {accepted}"
            return None
    target_formats = list(param.datetime_formats or [])
    if target_formats:
        try:
            return parsed.strftime(target_formats[0])
        except Exception:
            return parsed.isoformat(sep=" ")
    return parsed.isoformat(sep=" ")


def _resolve_for_check(value: str, cwd: t.Optional[str]) -> str:
    expanded = os.path.expanduser(value)
    if cwd and not os.path.isabs(expanded):
        expanded = os.path.join(cwd, expanded)
    return expanded


def _validate_path(
    value: str,
    param: ParamInfo,
    key: str,
    errors: t.Dict[str, str],
    cwd: t.Optional[str] = None,
) -> t.Optional[str]:
    if value == "-" and param.path_allow_dash:
        return value
    expanded = os.path.expanduser(value)
    if value == "":
        return value
    checked = _resolve_for_check(value, cwd)
    exists = os.path.exists(checked)
    if param.path_exists and not exists:
        errors[key] = f"路径不存在: {value}"
        return expanded
    if exists:
        if not param.path_file_okay and os.path.isfile(checked):
            errors[key] = f"这里需要目录，但给的是文件: {value}"
        if not param.path_dir_okay and os.path.isdir(checked):
            errors[key] = f"这里需要文件，但给的是目录: {value}"
        if param.path_readable and not os.access(checked, os.R_OK):
            errors[key] = f"路径不可读: {value}"
        if param.path_writable and not os.access(checked, os.W_OK):
            errors[key] = f"路径不可写: {value}"
        if param.path_executable and not os.access(checked, os.X_OK):
            errors[key] = f"路径不可执行: {value}"
    return expanded


def _normalize_one(
    param: ParamInfo,
    value: t.Any,
    key: str,
    errors: t.Dict[str, str],
    cwd: t.Optional[str] = None,
) -> t.Any:
    if param.is_flag:
        return _as_bool(value)
    if param.count:
        number = _to_int(value, key, errors, param.label)
        if number is not None and number < 0:
            errors[key] = f"{param.label} 不能为负数"
            return 0
        return number
    if value is None:
        return None
    if param.type_kind == "choice":
        match = _match_choice(value, param)
        if match is None:
            errors[key] = f"{param.label} 的可选值: {', '.join(str(c) for c in param.choices)}"
            return value
        return match
    if param.type_kind in ("int", "int_range"):
        number = _to_int(value, key, errors, param.label)
        if number is None:
            return None
        if param.type_kind == "int_range":
            if param.min is not None:
                too_low = number < param.min if not param.min_open else number <= param.min
                if too_low:
                    if param.clamp:
                        number = param.min + 1 if param.min_open else param.min
                    else:
                        errors[key] = f"{param.label} 必须 {'>' if param.min_open else '>='} {param.min}"
            if param.max is not None:
                too_high = number > param.max if not param.max_open else number >= param.max
                if too_high:
                    if param.clamp:
                        number = param.max - 1 if param.max_open else param.max
                    else:
                        errors[key] = f"{param.label} 必须 {'<' if param.max_open else '<='} {param.max}"
        return number
    if param.type_kind in ("float", "float_range"):
        number = _to_float(value, key, errors, param.label)
        if number is None:
            return None
        if param.type_kind == "float_range":
            if param.min is not None:
                too_low = number < param.min if not param.min_open else number <= param.min
                if too_low:
                    if param.clamp:
                        number = param.min
                    else:
                        errors[key] = f"{param.label} 必须 {'>' if param.min_open else '>='} {param.min}"
            if param.max is not None:
                too_high = number > param.max if not param.max_open else number >= param.max
                if too_high:
                    if param.clamp:
                        number = param.max
                    else:
                        errors[key] = f"{param.label} 必须 {'<' if param.max_open else '<='} {param.max}"
        return number
    if param.type_kind == "bool":
        return _as_bool(value)
    if param.type_kind == "datetime":
        return _convert_datetime(value, param, key, errors)
    if param.type_kind == "uuid":
        text = str(value).strip()
        if not UUID_RE.match(text):
            errors[key] = f"{param.label} 需要是合法 UUID"
        return text
    if param.type_kind == "path":
        return _validate_path(str(value), param, key, errors, cwd)
    if param.type_kind == "file":
        text = str(value).strip()
        mode = param.file_mode or "r"
        if (
            not any(flag in mode for flag in ("w", "a", "x", "+"))
            and text != "-"
            and not os.path.exists(_resolve_for_check(text, cwd))
        ):
            errors[key] = f"文件不存在: {text}"
        return os.path.expanduser(text)
    if param.type_kind == "tuple":
        return value
    return str(value) if not isinstance(value, (int, float, bool)) else value


def parse_command(
    node: CommandInfo, data: t.Dict[str, t.Any], cwd: t.Optional[str] = None
) -> ParsedCommand:
    scopes = collect_scopes(node)
    parsed = ParsedCommand(node=node, scopes=scopes)

    for scope in scopes:
        for param in scope.params:
            key = field_key(scope, param)
            raw = data.get(key, default_value(param))

            if param.multiple:
                if raw is None:
                    values = []
                elif isinstance(raw, list):
                    values = raw
                elif isinstance(raw, tuple):
                    values = list(raw)
                elif isinstance(raw, str):
                    values = [raw] if raw != "" else []
                else:
                    values = [raw]
                if param.nargs and param.nargs > 1 and values and not isinstance(values[0], (list, tuple)):
                    grouped: t.List[t.List[t.Any]] = []
                    if len(values) % param.nargs != 0:
                        parsed.errors[key] = f"{param.label} 需要成组提供，每组 {param.nargs} 项"
                    else:
                        for start in range(0, len(values), param.nargs):
                            grouped.append(values[start : start + param.nargs])
                    values = grouped
                normalized: t.List[t.Any] = []
                for item in values:
                    if isinstance(item, (list, tuple)):
                        group: t.List[t.Any] = []
                        for sub in item:
                            group.append(_normalize_one(param, sub, key, parsed.errors, cwd))
                        normalized.append(group)
                    else:
                        normalized.append(_normalize_one(param, item, key, parsed.errors, cwd))
                value: t.Any = normalized
            elif param.nargs and param.nargs != 1:
                if raw is None:
                    value = None
                else:
                    values = list(raw) if isinstance(raw, (list, tuple)) else [raw]
                    if (
                        param.nargs > 1
                        and not _empty(raw)
                        and len(values) != param.nargs
                    ):
                        parsed.errors[key] = f"{param.label} 需要 {param.nargs} 项，当前 {len(values)} 项"
                    value = [
                        _normalize_one(param, item, key, parsed.errors, cwd) for item in values
                    ]
            else:
                value = _normalize_one(param, raw, key, parsed.errors, cwd)

            if _empty(value):
                value = None if not (param.type_kind == "bool" and not param.is_flag) else value
                if param.multiple or (param.nargs and param.nargs != 1):
                    value = []
                if param.count:
                    value = 0

            if param.required and _empty(value):
                if param.is_argument:
                    parsed.errors.setdefault(key, f"{param.label} 是必填参数")
                else:
                    parsed.errors.setdefault(key, f"{param.label} 是必填项")
            if param.prompt and _empty(value):
                parsed.errors.setdefault(key, f"{param.label} 需要在表单中填写（命令行会交互提示）")

            parsed.field_values[key] = _json_safe(value)
            parsed.values.append(ScopedValue(scope=scope, param=param, key=key, value=value))

    parsed.argv = build_argv(parsed)
    return parsed


def _stringify(value: t.Any) -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (_dt.datetime,)):
        return value.isoformat(sep=" ")
    return str(value)


def _append_option(argv: t.List[str], param: ParamInfo, value: t.Any) -> None:
    opt = param.preferred_opt()
    if param.is_flag:
        if _as_bool(value):
            argv.append(opt)
        elif param.default is True and not param.count:
            secondary = param.preferred_secondary_opt()
            if secondary:
                argv.append(secondary)
        return

    if param.count:
        try:
            count = int(value or 0)
        except (TypeError, ValueError):
            count = 0
        argv.extend([opt] * max(0, count))
        return

    def add_one(item: t.Any) -> None:
        if isinstance(item, (list, tuple)):
            if not item:
                return
            first = _stringify(item[0])
            if opt.startswith("--"):
                argv.append(f"{opt}={first}")
            else:
                argv.extend([opt, first])
            argv.extend(_stringify(sub) for sub in item[1:])
            return
        text = _stringify(item)
        if opt.startswith("--"):
            argv.append(f"{opt}={text}")
        else:
            argv.append(opt)
            argv.append(text)

    if param.multiple:
        for item in value or []:
            add_one(item)
        return
    if param.nargs and param.nargs != 1:
        if isinstance(value, (list, tuple)):
            add_one(value)
        elif value is not None:
            add_one([value])
        return
    if value is None:
        return
    if param.type_kind == "bool" and not _as_bool(value):
        # A non-flag bool option still needs an explicit value; False is
        # meaningful and must not be silently omitted.
        add_one("False")
        return
    if isinstance(value, str) and value == "":
        return
    add_one(value)


def build_argv(parsed: ParsedCommand) -> t.List[str]:
    argv: t.List[str] = []
    scopes = parsed.scopes
    values_by_scope: t.Dict[int, t.List[ScopedValue]] = {}
    for item in parsed.values:
        values_by_scope.setdefault(id(item.scope), []).append(item)

    for index, scope in enumerate(scopes):
        items = values_by_scope.get(id(scope), [])
        options = [item for item in items if item.param.is_option]
        arguments = [item for item in items if item.param.is_argument]
        for item in options:
            _append_option(argv, item.param, item.value)
        tokens: t.List[str] = []
        for item in arguments:
            value = item.value
            if value is None:
                continue
            if isinstance(value, (list, tuple)):
                tokens.extend(_stringify(sub) for sub in value)
            else:
                tokens.append(_stringify(value))
        if index == len(scopes) - 1 and any(
            token.startswith("-") and token != "-" for token in tokens
        ):
            # Click's parser would treat ``-something`` as an option.  A
            # terminator makes positional values unambiguous; all options of
            # the selected command have already been emitted above.
            argv.append("--")
        argv.extend(tokens)
        if index < len(scopes) - 1:
            argv.append(scopes[index + 1].command.name)
    return argv


def argv_preview(root_name: str, argv: t.List[str]) -> str:
    tokens = [root_name] + list(argv)
    if sys.platform == "win32":
        return subprocess.list2cmdline(tokens)
    return shlex.join(tokens)


def scopes_to_schema_params(scopes: t.List[Scope]) -> t.List[t.Tuple[str, Scope]]:
    return [(field_key(scope, param), scope) for scope in scopes for param in scope.params]
