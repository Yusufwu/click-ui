"""Defensive inspection of Click parameter types.

Only public Click objects are read here; Click itself is never modified.
"""

from __future__ import annotations

import typing as t

import click
from click import types


def type_info(param: click.Parameter) -> t.Dict[str, t.Any]:
    """Return a UI oriented description of a Click parameter type."""
    ptype = param.type
    info: t.Dict[str, t.Any] = {
        "type_kind": "text",
        "type_name": getattr(ptype, "name", type(ptype).__name__),
        "choices": [],
        "case_sensitive": True,
        "min": None,
        "max": None,
        "min_open": False,
        "max_open": False,
        "clamp": False,
        "datetime_formats": [],
        "path_exists": False,
        "path_file_okay": True,
        "path_dir_okay": True,
        "path_readable": False,
        "path_writable": False,
        "path_executable": False,
        "path_resolve": False,
        "path_allow_dash": False,
        "file_mode": "r",
        "file_lazy": False,
        "tuple_types": [],
    }

    if isinstance(ptype, click.Choice):
        info["type_kind"] = "choice"
        info["choices"] = list(ptype.choices)
        info["case_sensitive"] = bool(getattr(ptype, "case_sensitive", True))
        return info

    if isinstance(ptype, types.IntRange):
        info["type_kind"] = "int_range"
        info.update(
            {
                "min": ptype.min,
                "max": ptype.max,
                "min_open": bool(getattr(ptype, "min_open", False)),
                "max_open": bool(getattr(ptype, "max_open", False)),
                "clamp": bool(getattr(ptype, "clamp", False)),
            }
        )
        return info

    if isinstance(ptype, types.FloatRange):
        info["type_kind"] = "float_range"
        info.update(
            {
                "min": ptype.min,
                "max": ptype.max,
                "min_open": bool(getattr(ptype, "min_open", False)),
                "max_open": bool(getattr(ptype, "max_open", False)),
                "clamp": bool(getattr(ptype, "clamp", False)),
            }
        )
        return info

    if isinstance(ptype, types.DateTime):
        info["type_kind"] = "datetime"
        info["datetime_formats"] = list(getattr(ptype, "formats", ()) or ())
        return info

    if isinstance(ptype, types.Path):
        info["type_kind"] = "path"
        info.update(
            {
                "path_exists": bool(ptype.exists),
                "path_file_okay": bool(ptype.file_okay),
                "path_dir_okay": bool(ptype.dir_okay),
                "path_readable": bool(ptype.readable),
                "path_writable": bool(ptype.writable),
                "path_executable": bool(getattr(ptype, "executable", False)),
                "path_resolve": bool(ptype.resolve_path),
                "path_allow_dash": bool(ptype.allow_dash),
            }
        )
        return info

    if isinstance(ptype, types.File):
        info["type_kind"] = "file"
        info.update(
            {
                "file_mode": ptype.mode or "r",
                "file_lazy": bool(getattr(ptype, "lazy", False)),
            }
        )
        return info

    if isinstance(ptype, types.Tuple):
        info["type_kind"] = "tuple"
        info["tuple_types"] = list(getattr(ptype, "types", ()))
        return info

    if isinstance(ptype, types.UUIDParameterType):
        info["type_kind"] = "uuid"
        return info

    if isinstance(ptype, types.BoolParamType):
        info["type_kind"] = "bool"
        return info

    if isinstance(ptype, types.IntParamType):
        info["type_kind"] = "int"
        return info

    if isinstance(ptype, types.FloatParamType):
        info["type_kind"] = "float"
        return info

    if isinstance(ptype, types.UnprocessedParamType):
        info["type_kind"] = "text"
        return info

    if isinstance(ptype, types.FuncParamType):
        info["type_kind"] = "custom"
        info["type_name"] = ptype.name
        return info

    # Custom ParamType subclasses: show a text input and expose the declared name.
    info["type_kind"] = "custom"
    info["type_name"] = getattr(ptype, "name", type(ptype).__name__)
    return info
