"""Command line entry point for the console itself."""

from __future__ import annotations

import json
import os
import secrets
import webbrowser

import click

from cliui import __version__
from cliui.config import ServeConfig, build_config
from cliui.registry import AppLoadError, load_app_entry, load_apps
from cliui.scheduling import SchedulerService
from cliui.storage.repo import Store


def _purge_old_executions(store: Store, config: ServeConfig) -> None:
    if config.retention_days <= 0:
        return
    removed = store.purge_executions(retention_days=config.retention_days)
    click.echo(
        f"已清理 {removed} 条超过 {config.retention_days} 天的执行记录"
    )


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="cliui")
def main() -> None:
    """Run existing Click applications inside an AMIS web console."""


@main.command("serve")
@click.argument("specs", nargs=-1, required=False)
@click.option("--host", default="127.0.0.1", show_default=True, help="监听地址")
@click.option("--port", default=5000, type=int, show_default=True, help="监听端口")
@click.option("--data-dir", default=None, help="数据目录（默认 ./data）")
@click.option("--db-path", default=None, help="SQLite 文件路径")
@click.option("--secret-key", default=None, help="Flask session 密钥")
@click.option("--admin-password", default=None, help="首次启动时管理员密码")
@click.option(
    "--max-output-chars",
    default=200_000,
    type=int,
    show_default=True,
    help="单条输出最多保存的字符数",
)
@click.option(
    "--max-upload-mb",
    default=64,
    type=int,
    show_default=True,
    help="上传文件大小上限（MB）",
)
@click.option("--debug/--no-debug", default=False, help="启用 Flask 调试模式")
@click.option("--open/--no-open", "open_browser", default=False, help="启动后打开浏览器")
@click.option(
    "--retention-days",
    default=0,
    type=int,
    show_default=True,
    help="执行记录保留天数；0 表示永久保留。启动时清理更早的记录（输出已压缩存储）",
)
@click.option(
    "--scheduler/--no-scheduler",
    "run_scheduler",
    default=False,
    help="在同一进程内启动定时调度线程（开发环境推荐；生产可独立运行 cliui scheduler）",
)
@click.option(
    "--scheduler-wait-seconds",
    default=0,
    type=float,
    show_default=True,
    help="定时触发等待执行锁的秒数，超时记为 skipped",
)
def serve_command(
    specs: tuple,
    host: str,
    port: int,
    data_dir: str | None,
    db_path: str | None,
    secret_key: str | None,
    admin_password: str | None,
    max_output_chars: int,
    max_upload_mb: int,
    debug: bool,
    open_browser: bool,
    retention_days: int,
    run_scheduler: bool,
    scheduler_wait_seconds: float,
) -> None:
    """启动 Web 控制台。

    每个 SPEC 的格式为 module:attr 或 path/to/file.py:attr；可以重复传入多个
    应用，也可以使用 name=module:attr 自定义显示名称。
    """
    if not specs:
        raise click.UsageError(
            "至少需要一个 Click 应用，例如：\n"
            "  cliui serve examples/demo_cli.py:cli\n"
            "  cliui serve mypkg.cli:cli name=other=otherpkg.cli:cli"
        )

    try:
        entries = load_apps(list(specs))
    except AppLoadError as exc:
        raise click.UsageError(str(exc)) from exc

    config = build_config(
        host=host,
        port=port,
        data_dir=data_dir,
        db_path=db_path,
        secret_key=secret_key,
        max_output_chars=max_output_chars,
        max_upload_bytes=max_upload_mb * 1024 * 1024,
        retention_days=retention_days,
        admin_password=admin_password,
        debug=debug,
        open_browser=open_browser,
    )
    store = Store(config.db_path)
    created, password = store.ensure_admin(
        config.admin_password or secrets.token_urlsafe(12)
    )
    _purge_old_executions(store, config)
    if created:
        click.echo("")
        click.echo("已创建管理员账号：")
        click.echo("  用户名: admin")
        click.echo(f"  密码:   {password}")
        click.echo("  请妥善保存，之后可在命令行用 `cliui user add` 创建更多账号。")
        click.echo("")

    from cliui.web.server import create_app

    store.save_app_specs(
        [
            (entry.name, entry.import_spec or "", entry.base_cwd or "")
            for entry in entries
            if entry.import_spec
        ]
    )
    scheduler_service = None
    if run_scheduler:
        scheduler_service = SchedulerService(
            store=store,
            apps_by_name={entry.name: entry for entry in entries},
            max_output_chars=config.max_output_chars,
            wait_seconds=scheduler_wait_seconds,
            log=lambda message: click.echo(f"[scheduler] {message}"),
        )
        scheduler_service.start()

    app = create_app(
        entries=entries, store=store, config=config, scheduler=scheduler_service
    )
    url = f"http://{host}:{port}/"
    click.echo("已注册应用：")
    for entry in entries:
        click.echo(
            f"  - {entry.display_name()} ({entry.name}) · {len(entry.nodes)} 个命令节点"
        )
    click.echo(f"控制台地址: {url}")
    click.echo(f"数据目录:   {config.data_dir}")

    if open_browser:
        webbrowser.open(url)

    app.run(
        host=host,
        port=port,
        debug=debug,
        use_reloader=False,
        threaded=True,
    )


@main.command("scheduler")
@click.argument("specs", nargs=-1, required=False)
@click.option("--data-dir", default=None, help="数据目录（默认 ./data）")
@click.option("--db-path", default=None, help="SQLite 文件路径")
@click.option(
    "--max-output-chars",
    default=200_000,
    type=int,
    show_default=True,
    help="单条输出最多保存的字符数",
)
@click.option(
    "--scheduler-wait-seconds",
    default=0,
    type=float,
    show_default=True,
    help="等待执行锁的秒数，超时记为 skipped",
)
@click.option(
    "--retention-days",
    default=0,
    type=int,
    show_default=True,
    help="执行记录保留天数；0 表示永久保留。启动时清理更早的记录",
)
def scheduler_command(
    specs: tuple,
    data_dir: str | None,
    db_path: str | None,
    max_output_chars: int,
    scheduler_wait_seconds: float,
    retention_days: int,
) -> None:
    """启动独立的定时调度进程（生产环境推荐）。

    不传 SPEC 时，会使用 `cliui serve` 上次注册并保存在数据库里的应用；
    也可以像 serve 一样用 module:attr 或 path/to/file.py:attr 显式指定。
    """
    config = build_config(
        data_dir=data_dir,
        db_path=db_path,
        max_output_chars=max_output_chars,
        retention_days=retention_days,
    )
    store = Store(config.db_path)
    _purge_old_executions(store, config)

    if specs:
        try:
            entries = load_apps(list(specs))
        except AppLoadError as exc:
            raise click.UsageError(str(exc)) from exc
        store.save_app_specs(
            [
                (entry.name, entry.import_spec or "", entry.base_cwd or "")
                for entry in entries
                if entry.import_spec
            ]
        )
    else:
        saved = store.load_app_specs()
        if not saved:
            raise click.UsageError(
                "数据库里还没有注册应用。请先运行 `cliui serve ...`，"
                "或者直接给 scheduler 传入应用地址。"
            )
        entries = []
        for row in saved:
            try:
                entry = load_app_entry(
                    row["import_spec"], row.get("base_cwd") or os.getcwd()
                )
            except AppLoadError as exc:
                click.echo(f"警告：应用 {row['name']} 加载失败，已跳过：{exc}")
                continue
            entry.name = row["name"]
            entries.append(entry)

    if not entries:
        raise click.UsageError("没有可用的应用，调度器无法运行。")

    service = SchedulerService(
        store=store,
        apps_by_name={entry.name: entry for entry in entries},
        max_output_chars=config.max_output_chars,
        wait_seconds=scheduler_wait_seconds,
        blocking=True,
        log=lambda message: click.echo(f"[scheduler] {message}"),
    )
    click.echo(f"定时调度器已启动 · 数据目录 {config.data_dir}")
    for entry in entries:
        click.echo(f"  - {entry.display_name()} ({entry.name})")
    click.echo(f"当前启用的定时任务：{len(store.enabled_schedules())} 个")
    try:
        service.start()
    except (KeyboardInterrupt, SystemExit):
        service.shutdown()


@main.group("user")
def user_group() -> None:
    """管理控制台账号。"""


@user_group.command("add")
@click.argument("username")
@click.argument("password", required=False)
@click.option("--admin", is_flag=True, help="创建管理员账号")
@click.option("--data-dir", default=None, help="数据目录（默认 ./data）")
def user_add(
    username: str, password: str | None, admin: bool, data_dir: str | None
) -> None:
    """创建账号；省略密码时会安全地交互输入。"""
    if not password:
        password = click.prompt("密码", hide_input=True, confirmation_prompt=True)
    config = build_config(data_dir=data_dir)
    store = Store(config.db_path)
    try:
        created = store.create_user(username, password, is_admin=admin)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if not created:
        raise click.ClickException(f"用户名已存在: {username}")
    click.echo(f"已创建{'管理员' if admin else ''}账号: {username}")


@user_group.command("list")
@click.option("--data-dir", default=None, help="数据目录（默认 ./data）")
def user_list(data_dir: str | None) -> None:
    """列出所有账号。"""
    config = build_config(data_dir=data_dir)
    store = Store(config.db_path)
    users = store.list_users()
    if not users:
        click.echo("还没有账号。使用 `cliui user add <用户名> <密码> --admin` 创建。")
        return
    for item in users:
        role = "管理员" if item.get("is_admin") else "普通用户"
        click.echo(
            f"#{item['id']:<4} {item['username']:<20} {role}\t"
            f"创建于 {item.get('created_at') or '-'}"
        )


@main.command("tree")
@click.argument("spec")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON")
def tree_command(spec: str, as_json: bool) -> None:
    """打印一个 Click 应用的命令树（含 AMIS node_id）。"""
    try:
        entry = load_app_entry(spec, base_cwd=".")
    except AppLoadError as exc:
        raise click.UsageError(str(exc)) from exc

    if as_json:
        payload = {
            "app": entry.name,
            "title": entry.title,
            "cwd": entry.cwd,
            "nodes": [
                {
                    "node_id": node.node_id,
                    "name": node.name,
                    "path": node.path,
                    "level": node.level,
                    "group": node.is_group,
                    "executable": node.executable,
                    "help": node.short_help,
                    "params": [
                        {
                            "key": param.key,
                            "kind": param.kind,
                            "label": param.label,
                            "type": param.type_kind,
                            "required": param.required,
                            "default": param.default,
                            "description": param.description,
                        }
                        for param in node.params
                    ],
                }
                for node in entry.nodes.values()
            ],
        }
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    click.echo(f"{entry.display_name()} [{entry.name}]  ({entry.cwd})")

    def render(node, indent: int) -> None:
        marker = "组" if node.is_group else "命令"
        extra = " · 可直接执行" if node.is_group and node.executable else ""
        click.echo(
            f"{'  ' * indent}- [{node.node_id}] {node.name}  ({marker}{extra})"
        )
        for param in node.params:
            required = " 必填" if param.required else ""
            click.echo(
                f"{'  ' * (indent + 1)}· {param.key} <{param.type_kind}>{required} "
                f"{param.help}".rstrip()
            )
        for child in node.children:
            render(child, indent + 1)

    if entry.root is not None:
        render(entry.root, 0)


if __name__ == "__main__":  # pragma: no cover
    main()
