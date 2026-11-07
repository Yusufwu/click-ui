"""Convert Click parameters into UI metadata."""

from __future__ import annotations

import typing as t

import click

from cliui.introspect.typeinfo import type_info
from cliui.model import ParamInfo


HELP_PARAM_NAMES = {"help", "version"}


def _safe_default(param: click.Parameter) -> t.Any:
    value = getattr(param, "default", None)
    if callable(value):
        try:
            value = value()
        except Exception:
            return None
    if value is None:
        return None
    if getattr(param, "multiple", False):
        try:
            return list(value)
        except TypeError:
            return [value]
    if isinstance(value, tuple):
        return list(value)
    return value


def _humanize(name: str) -> str:
    """Turn ``root_name`` into a readable ``Root Name`` label."""
    text = str(name).replace("_", " ").replace("-", " ").strip()
    return text.title() if text else str(name)


def _label_for(param: click.Parameter) -> str:
    metavar = getattr(param, "metavar", None)
    if metavar:
        return str(metavar)
    return _humanize(param.name)


def _envvar_text(param: click.Parameter) -> t.Optional[str]:
    envvar = getattr(param, "envvar", None)
    if not envvar:
        return None
    if isinstance(envvar, (list, tuple)):
        return ", ".join(str(item) for item in envvar)
    return str(envvar)


def _describe_default(value: t.Any) -> t.Optional[str]:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        if not value:
            return None
        return ", ".join(str(item) for item in value)
    if isinstance(value, bool):
        return "开启" if value else "关闭"
    return str(value)


def _build_description(
    param: click.Parameter, info: t.Dict[str, t.Any], default: t.Any
) -> str:
    help_text = (getattr(param, "help", None) or "").strip()
    parts: t.List[str] = []
    if help_text:
        parts.append(help_text)

    if isinstance(param, click.Option):
        parts.append("选项 " + " / ".join(param.opts + list(getattr(param, "secondary_opts", []))))
    else:
        parts.append("位置参数")

    type_kind = info["type_kind"]
    if type_kind == "choice":
        choices = ", ".join(str(choice) for choice in info["choices"])
        parts.append(f"可选值: {choices}")
    elif type_kind not in ("text", "custom"):
        parts.append(f"类型: {info['type_name']}")

    if type_kind in ("int_range", "float_range"):
        range_bits = []
        if info.get("min") is not None:
            range_bits.append((">" if info.get("min_open") else ">=") + str(info["min"]))
        if info.get("max") is not None:
            range_bits.append(("<" if info.get("max_open") else "<=") + str(info["max"]))
        if range_bits:
            parts.append("范围: " + " 且 ".join(range_bits))
        if info.get("clamp"):
            parts.append("超出范围会被截断")

    if type_kind == "datetime" and info.get("datetime_formats"):
        parts.append("可接受格式: " + ", ".join(info["datetime_formats"]))

    if type_kind == "path":
        constraints = []
        if info.get("path_exists"):
            constraints.append("必须存在")
        if info.get("path_file_okay") and not info.get("path_dir_okay"):
            constraints.append("必须是文件")
        if info.get("path_dir_okay") and not info.get("path_file_okay"):
            constraints.append("必须是目录")
        if info.get("path_readable"):
            constraints.append("可读")
        if info.get("path_writable"):
            constraints.append("可写")
        if info.get("path_executable"):
            constraints.append("可执行")
        if info.get("path_allow_dash"):
            constraints.append("允许 - 表示标准输入输出")
        if constraints:
            parts.append("路径要求: " + ", ".join(constraints))

    if type_kind == "file":
        mode = info.get("file_mode") or "r"
        parts.append(f"文件访问模式: {mode}")
        if "w" in mode or "a" in mode or "x" in mode:
            parts.append("输出文件请直接填写路径")
        else:
            parts.append("可直接上传文件，上传后自动填入临时路径")

    if getattr(param, "multiple", False):
        parts.append("可多值，在表单中可添加多项")
    nargs = getattr(param, "nargs", 1)
    if nargs is not None and nargs != 1:
        if nargs < 0:
            parts.append("可接受任意多个值")
        else:
            parts.append(f"需要 {nargs} 个值")

    default_text = _describe_default(default)
    if default_text:
        parts.append(f"默认值: {default_text}")

    envvar = _envvar_text(param)
    if envvar:
        parts.append(f"环境变量: {envvar}（留空则由 Click 读取）")

    if getattr(param, "prompt", False):
        parts.append("命令行中会交互提示，请在此填写")

    if getattr(param, "hide_input", False):
        parts.append("敏感信息，输入内容会以掩码显示")

    if getattr(param, "hidden", False):
        parts.append("该参数在 Click 帮助中隐藏")

    return " · ".join(part for part in parts if part)


def describe_param(param: click.Parameter, level: int, key_prefix: str, index: int) -> ParamInfo:
    """Build a :class:`ParamInfo` for one Click parameter."""
    info = type_info(param)
    default = _safe_default(param)
    multiple = bool(getattr(param, "multiple", False))
    nargs = getattr(param, "nargs", 1)
    if nargs is None:
        nargs = 1
    opts = list(getattr(param, "opts", []) or [])
    secondary_opts = list(getattr(param, "secondary_opts", []) or [])
    is_flag = bool(getattr(param, "is_flag", False))
    is_count = bool(getattr(param, "count", False))
    flag_value = getattr(param, "flag_value", True)

    if is_count:
        info["type_kind"] = "count"
    elif is_flag:
        info["type_kind"] = "bool"

    label = _label_for(param)
    envvar = _envvar_text(param)
    required = bool(getattr(param, "required", False))
    if getattr(param, "multiple", False) and default is None:
        default = []

    # ``key`` is unique within one command.  The form builder later adds a
    # scope prefix (``c__`` for the selected command, ``g0__`` and so on for
    # ancestor groups) so identical names at different levels never collide.
    key = str(param.name)

    return ParamInfo(
        key=key,
        name=param.name,
        kind="argument" if isinstance(param, click.Argument) else "option",
        level=level,
        param=param,
        label=label,
        help=(getattr(param, "help", None) or "").strip(),
        required=required,
        default=default,
        multiple=multiple,
        nargs=nargs,
        hidden=bool(getattr(param, "hidden", False)),
        is_flag=is_flag,
        flag_value=flag_value,
        count=is_count,
        hide_input=bool(getattr(param, "hide_input", False)),
        envvar=envvar,
        prompt=bool(getattr(param, "prompt", False)),
        metavar=getattr(param, "metavar", None),
        opts=opts,
        secondary_opts=secondary_opts,
        type_kind=info["type_kind"],
        type_name=info["type_name"],
        choices=list(info["choices"]),
        case_sensitive=bool(info["case_sensitive"]),
        min=info["min"],
        max=info["max"],
        min_open=bool(info["min_open"]),
        max_open=bool(info["max_open"]),
        clamp=bool(info["clamp"]),
        datetime_formats=list(info["datetime_formats"]),
        path_exists=bool(info["path_exists"]),
        path_file_okay=bool(info["path_file_okay"]),
        path_dir_okay=bool(info["path_dir_okay"]),
        path_readable=bool(info["path_readable"]),
        path_writable=bool(info["path_writable"]),
        path_executable=bool(info["path_executable"]),
        path_resolve=bool(info["path_resolve"]),
        path_allow_dash=bool(info["path_allow_dash"]),
        file_mode=info["file_mode"],
        file_lazy=bool(info["file_lazy"]),
        tuple_types=list(info["tuple_types"]),
        description=_build_description(param, info, default),
    )


def is_help_parameter(param: click.Parameter) -> bool:
    """Return True for Click's built-in help/version options."""
    if not isinstance(param, click.Option):
        return False
    if param.name not in HELP_PARAM_NAMES:
        return False
    if not getattr(param, "is_eager", False):
        return False
    if getattr(param, "expose_value", True):
        return False
    return any(opt in ("--help", "-h", "--version") for opt in param.opts)


def collect_params(command: click.Command, level: int, key_prefix: str) -> t.List[ParamInfo]:
    params: t.List[ParamInfo] = []
    used_keys = set()
    index = 0
    for param in list(command.params):
        if is_help_parameter(param):
            continue
        described = describe_param(param, level, key_prefix, 0)
        key = described.key
        if key in used_keys:
            suffix = 1
            while f"{key}__{suffix}" in used_keys:
                suffix += 1
            described.key = f"{key}__{suffix}"
        used_keys.add(described.key)
        params.append(described)
        index += 1
    return params
