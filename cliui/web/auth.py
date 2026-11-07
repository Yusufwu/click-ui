"""Session based authentication helpers."""

from __future__ import annotations

import functools
import typing as t
from urllib.parse import urlparse

from flask import g, jsonify, redirect, request, url_for, session

from cliui.model import AppEntry
from cliui.storage.repo import Store


def safe_next_url(value: t.Optional[str]) -> str:
    """Only allow local absolute paths to avoid open redirects."""
    if not value:
        return "/"
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        return "/"
    if not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


def load_user(store: Store):
    """Create a ``before_request`` hook that puts the user in ``g``."""

    def hook() -> None:
        g.user = None
        if request.endpoint == "static":
            return
        user_id = session.get("user_id")
        if not user_id:
            return
        user = store.get_user(int(user_id))
        if user is None:
            session.clear()
            return
        g.user = user

    return hook


def login_required(view: t.Callable[..., t.Any]) -> t.Callable[..., t.Any]:
    @functools.wraps(view)
    def wrapped(*args: t.Any, **kwargs: t.Any):
        if getattr(g, "user", None) is None:
            target = request.full_path if request.query_string else request.path
            return redirect(url_for("login", next=safe_next_url(target)))
        return view(*args, **kwargs)

    return wrapped


def api_login_required(view: t.Callable[..., t.Any]) -> t.Callable[..., t.Any]:
    @functools.wraps(view)
    def wrapped(*args: t.Any, **kwargs: t.Any):
        if getattr(g, "user", None) is None:
            return jsonify({"status": 1, "msg": "登录已失效，请刷新页面重新登录"}), 401
        return view(*args, **kwargs)

    return wrapped


def admin_required(view: t.Callable[..., t.Any]) -> t.Callable[..., t.Any]:
    @functools.wraps(view)
    @login_required
    def wrapped(*args: t.Any, **kwargs: t.Any):
        if not g.user.get("is_admin"):
            return jsonify({"status": 1, "msg": "需要管理员权限"}), 403
        return view(*args, **kwargs)

    return wrapped


def apps_for_user(apps: t.List[AppEntry], user: t.Dict[str, t.Any] | None) -> t.List[AppEntry]:
    return list(apps)
