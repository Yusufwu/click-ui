"""Map Click parameter metadata to AMIS form components."""

from __future__ import annotations

import typing as t

from cliui.model import ParamInfo
from cliui.schema.argv import UUID_RE


def _uuid_schema() -> t.Dict[str, t.Any]:
    """Text field with the same UUID rule Click applies (also checked server-side)."""
    return {
        "type": "input-text",
        "placeholder": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        "validations": {"matchRegexp": UUID_RE.pattern},
        "validationErrors": {"matchRegexp": "需要填写合法 UUID（8-4-4-4-12 位十六进制）"},
    }


def _choice_options(param: ParamInfo) -> t.List[t.Dict[str, t.Any]]:
    return [
        {"label": str(choice), "value": choice}
        for choice in param.choices
    ]


def _number_schema(param: ParamInfo) -> t.Dict[str, t.Any]:
    schema: t.Dict[str, t.Any] = {
        "type": "input-number",
        "precision": 0 if param.type_kind in ("int", "int_range", "count") else 4,
        "step": 1 if param.type_kind in ("int", "int_range", "count") else 0.01,
    }
    manual = param.min
    manual_max = param.max
    if manual is not None:
        # AMIS has no open interval support; the server performs the precise
        # Click validation and returns a friendly error when a bound is open.
        schema["min"] = manual
    if manual_max is not None:
        schema["max"] = manual_max
    return schema


def _item_schema_for_type(param: ParamInfo) -> t.Dict[str, t.Any]:
    """Schema for one element of an array/tuple parameter."""
    kind = param.type_kind
    if kind == "choice":
        return {
            "type": "select",
            "options": _choice_options(param),
            "searchable": len(param.choices) > 8,
        }
    if kind in ("int", "int_range", "count"):
        return {"type": "input-number", "precision": 0, "step": 1}
    if kind in ("float", "float_range"):
        return {"type": "input-number", "precision": 4, "step": 0.01}
    if kind == "bool":
        return {"type": "switch"}
    if kind == "datetime":
        return {"type": "input-datetime", "format": "YYYY-MM-DD HH:mm:ss"}
    if kind == "uuid":
        return _uuid_schema()
    return {"type": "input-text"}


def build_field(param: ParamInfo, field_key: str) -> t.List[t.Dict[str, t.Any]]:
    """Return one main schema and optional helper schemas for a parameter."""
    schema: t.Dict[str, t.Any] = {
        "name": field_key,
        "label": param.label,
        "description": param.description,
    }
    if param.required:
        schema["required"] = True

    kind = param.type_kind

    if param.count:
        schema.update(_number_schema(param))
        schema.update({"min": 0, "precision": 0, "step": 1})
    elif param.is_flag:
        schema["type"] = "switch"
        schema["onText"] = "开启"
        schema["offText"] = "关闭"
        if param.description:
            schema["description"] = param.description
    elif kind == "choice":
        options = _choice_options(param)
        schema["options"] = options
        if param.multiple:
            schema["type"] = "checkboxes"
            schema["inline"] = len(options) <= 8
            # Without these AMIS submits "red,blue" or full option objects.
            schema["joinValues"] = False
            schema["extractValue"] = True
        else:
            schema["type"] = "radios"
            schema["inline"] = len(options) <= 8
    elif kind in ("int", "int_range"):
        schema.update(_number_schema(param))
    elif kind in ("float", "float_range"):
        schema.update(_number_schema(param))
    elif kind == "bool":
        schema["type"] = "switch"
    elif kind == "datetime":
        schema["type"] = "input-datetime"
        schema["format"] = "YYYY-MM-DD HH:mm:ss"
        schema["valueFormat"] = "YYYY-MM-DD HH:mm:ss"
    elif kind == "path":
        schema["type"] = "input-text"
        schema["placeholder"] = "输入或选择路径"
    elif kind == "file":
        mode = param.file_mode or "r"
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            schema["type"] = "input-text"
            schema["placeholder"] = "输出文件路径"
        else:
            schema["type"] = "input-file"
            schema["useChunk"] = False
            schema["drag"] = False
            schema["btnLabel"] = "选择文件"
            schema["receiver"] = {"method": "post", "url": "/api/upload"}
            schema["valueField"] = "value"
            if param.multiple or (param.nargs is not None and param.nargs != 1):
                schema["multiple"] = True
    elif kind == "uuid":
        schema.update(_uuid_schema())
    elif (
        param.hide_input
        and not param.multiple
        and param.nargs in (None, 1)
    ):
        schema["type"] = "input-password"
        schema["placeholder"] = "敏感信息，输入内容会被遮挡"
    else:
        schema["type"] = "input-text"

    if param.nargs and param.nargs != 1 and not param.is_flag and kind not in ("file",):
        schema = {
            "type": "input-array",
            "name": field_key,
            "label": param.label,
            "description": param.description,
            "required": param.required,
            "items": _item_schema_for_type(param),
            "addable": True,
            "removable": True,
            "draggable": False,
            "placeholder": "添加一项",
        }
        if param.nargs > 1:
            schema["minLength"] = param.nargs
            schema["maxLength"] = param.nargs

    if param.multiple and kind not in ("choice", "file"):
        schema = {
            "type": "input-array",
            "name": field_key,
            "label": param.label,
            "description": param.description,
            "required": param.required,
            "items": _item_schema_for_type(param),
            "addable": True,
            "removable": True,
            "draggable": False,
            "placeholder": "添加一项",
        }

    # ``input-array`` does not forward type-specific bounds; add them as a
    # description note so users see the same information as on the CLI.
    if schema.get("type") == "input-array" and param.description:
        schema["description"] = param.description

    result: t.List[t.Dict[str, t.Any]] = [schema]

    # A Path parameter may point at an existing file, so offer an upload
    # accessory that fills the real path after the upload finishes.
    if (
        kind == "path"
        and param.path_exists
        and param.path_file_okay
        and not param.multiple
        and (param.nargs == 1)
    ):
        result.append(
            {
                "type": "input-file",
                "name": f"{field_key}__upload",
                "label": f"{param.label} · 上传文件",
                "description": "上传后自动把真实路径填入上面的参数",
                "useChunk": False,
                "drag": False,
                "btnLabel": "选择文件",
                "receiver": {"method": "post", "url": "/api/upload"},
                "valueField": "value",
                "autoFill": {field_key: "${value}"},
            }
        )

    return result


def build_hidden_schema(param: ParamInfo, field_key: str) -> t.Dict[str, t.Any]:
    return {"type": "hidden", "name": field_key}
