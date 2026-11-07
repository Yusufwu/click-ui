"""A demo Click application covering the parameter types the console supports.

Run it directly with Click, or expose it with::

    cliui serve examples/demo_cli.py:cli
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime

import click


@click.group(
    context_settings={"help_option_names": ["-h", "--help"], "max_content_width": 100}
)
@click.option("-v", "--verbose", count=True, help="日志详细程度，可重复传入提升级别。")
@click.option(
    "--config",
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="可选的配置文件路径（文件必须存在）。",
)
@click.pass_context
def cli(ctx: click.Context, verbose: int, config: str | None) -> None:
    """演示用 Click 应用：文本、数学、文件、系统与命令组嵌套。

    这个应用只使用 Click 的公开接口；控制台通过读取命令树来生成 AMIS 表单，
    不会修改 Click 的任何代码。
    """
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["config"] = config
    if verbose:
        click.echo(f"[verbose={verbose}] 配置文件: {config or '未提供'}", err=False)


# --------------------------------------------------------------------- text
@cli.group()
def text() -> None:
    """文本处理命令组。"""


@text.command("transform")
@click.argument("value")
@click.option(
    "--uppercase/--lowercase",
    "case",
    default=True,
    help="转换为大写或小写。",
)
def text_transform(value: str, case: bool) -> None:
    """转换一段文本的大小写。"""
    click.echo(value.upper() if case else value.lower())


@text.command("repeat")
@click.argument("value")
@click.option(
    "--times",
    type=click.IntRange(1, 20, clamp=True),
    default=3,
    show_default=True,
    help="重复次数；超出范围时按边界截断。",
)
@click.option("--separator", default=" | ", help="重复之间的分隔符。")
def text_repeat(value: str, times: int, separator: str) -> None:
    """把文本重复若干次。"""
    click.echo(separator.join([value] * times))


@text.command("mode")
@click.argument("value")
@click.option(
    "--mode",
    type=click.Choice(["upper", "lower", "title"], case_sensitive=False),
    default="upper",
    show_default=True,
    help="处理模式。",
)
def text_mode(value: str, mode: str) -> None:
    """按指定模式处理文本。"""
    if mode == "lower":
        click.echo(value.lower())
    elif mode == "title":
        click.echo(value.title())
    else:
        click.echo(value.upper())


@text.command("select")
@click.option(
    "--size",
    type=click.Choice(["S", "M", "L"], case_sensitive=False),
    default="M",
    show_default=True,
    help="单选示例；Web 中渲染为单选组。",
)
@click.option(
    "--color",
    "colors",
    type=click.Choice(["red", "green", "blue"]),
    multiple=True,
    help="多选示例；Web 中渲染为多选组，可以重复传入。",
)
def text_select(size: str, colors: tuple[str, ...]) -> None:
    """演示 Click Choice 的单选与多选。"""
    picked = ",".join(colors) if colors else "（未选择）"
    click.echo(f"size={size}; colors={picked}")


@text.command("tags")
@click.option("--tag", "tags", multiple=True, help="标签，可以重复传入多个。")
@click.option("--separator", default=",", help="输出时使用的分隔符。")
def text_tags(tags, separator: str) -> None:
    """演示 multiple=True 的多值选项。"""
    if not tags:
        click.echo("（没有标签）")
        return
    click.echo(separator.join(tags))


@text.command("pair")
@click.option("--pair", type=(str, int), help="两个值：名称和数量。")
def text_pair(pair) -> None:
    """演示 Tuple 类型（需要一次提供两个值）。"""
    if pair is None:
        click.echo("（没有提供 pair）")
        return
    name, count = pair
    click.echo(f"{name} x {count}")


@text.command("join")
@click.argument("words", nargs=-1, required=True)
@click.option("--separator", default="-", help="词之间的连接符。")
def text_join(words, separator: str) -> None:
    """演示 nargs=-1：可以一次给出任意多个位置参数。"""
    click.echo(separator.join(words))


# --------------------------------------------------------------------- math
@cli.group()
def math() -> None:
    """数学计算命令组。"""


@math.command("add")
@click.argument("left", type=int)
@click.argument("right", type=int)
def math_add(left: int, right: int) -> None:
    """两个整数相加。"""
    click.echo(f"{left + right}")


@math.command("range")
@click.argument("start", type=int)
@click.argument("stop", type=int)
@click.option(
    "--step",
    type=click.IntRange(1, 100),
    default=1,
    show_default=True,
    help="步长，必须为正数。",
)
@click.option("--limit", type=click.IntRange(1, 50), default=10, help="最多输出多少项。")
def math_range(start: int, stop: int, step: int, limit: int) -> None:
    """按步长输出区间中的数字。"""
    values = list(range(start, stop, step))[:limit]
    click.echo(" ".join(str(item) for item in values))


@math.command("scale")
@click.argument("value", type=float)
@click.option(
    "--factor",
    type=click.FloatRange(0.0, 10.0),
    default=1.0,
    show_default=True,
    help="缩放系数。",
)
@click.option("--precision", type=click.IntRange(0, 6), default=2, help="小数位数。")
def math_scale(value: float, factor: float, precision: int) -> None:
    """按系数缩放一个浮点数。"""
    click.echo(f"{value * factor:.{precision}f}")


# -------------------------------------------------------------------- files
@cli.group()
def files() -> None:
    """文件与目录命令组。"""


@files.command("read")
@click.argument("source", type=click.File("r", encoding="utf-8", lazy=False))
def files_read(source) -> None:
    """读取一个文本文件（File 类型，只读）。"""
    content = source.read()
    click.echo(content)
    click.echo(f"\n[读取完成，共 {len(content)} 个字符]")


@files.command("write")
@click.argument("target", type=click.File("w", encoding="utf-8"))
@click.option("--content", required=True, help="写入文件的内容。")
def files_write(target, content: str) -> None:
    """写入一个文本文件（File 类型，写模式）。"""
    target.write(content)
    click.echo(f"已写入 {len(content)} 个字符")


@files.command("info")
@click.argument(
    "path",
    type=click.Path(exists=True, readable=True, resolve_path=False),
)
@click.option("--recursive/--no-recursive", default=False, help="目录是否递归统计。")
def files_info(path: str, recursive: bool) -> None:
    """查看文件或目录信息（Path 类型，必须存在）。"""
    absolute = os.path.abspath(path)
    if os.path.isdir(absolute):
        total = 0
        count = 0
        if recursive:
            for root, _dirs, names in os.walk(absolute):
                for name in names:
                    count += 1
                    try:
                        total += os.path.getsize(os.path.join(root, name))
                    except OSError:
                        pass
        else:
            for name in os.listdir(absolute):
                candidate = os.path.join(absolute, name)
                if os.path.isfile(candidate):
                    count += 1
                    total += os.path.getsize(candidate)
        click.echo(f"目录: {absolute}")
        click.echo(f"文件数: {count}")
        click.echo(f"总大小: {total} 字节")
    else:
        stat = os.stat(absolute)
        click.echo(f"文件: {absolute}")
        click.echo(f"大小: {stat.st_size} 字节")
        click.echo(f"修改时间: {datetime.fromtimestamp(stat.st_mtime)}")


# ------------------------------------------------------------------- system
@cli.group()
def system() -> None:
    """系统信息与演示用命令组。"""


@system.command("echo")
@click.argument("message", nargs=-1, required=True)
@click.option("--repeat", type=click.IntRange(1, 10), default=1, help="重复次数。")
@click.option("--newline/--no-newline", "newline", default=True, help="是否换行。")
def system_echo(message, repeat: int, newline: bool) -> None:
    """输出一段文本（演示 nargs=-1 与布尔开关）。"""
    text = " ".join(message)
    for _ in range(repeat):
        click.echo(text, nl=newline)


@system.command("env")
@click.option("--name", required=True, help="环境变量名称。")
@click.option("--show-all", is_flag=True, help="列出全部环境变量。")
def system_env(name: str, show_all: bool) -> None:
    """读取环境变量。"""
    if show_all:
        for key, value in sorted(os.environ.items()):
            click.echo(f"{key}={value}")
        return
    if name not in os.environ:
        click.echo(f"环境变量不存在: {name}", err=True)
        raise click.ClickException(f"环境变量不存在: {name}")
    click.echo(os.environ[name])


@system.command("when")
@click.option(
    "--at",
    type=click.DateTime(formats=["%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]),
    help="时间点，例如 2026-11-07 12:30:00。",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["iso", "date", "readable"]),
    default="iso",
    help="输出格式。",
)
def system_when(at, output_format: str) -> None:
    """解析并格式化时间（DateTime 类型）。"""
    value = at or datetime.now()
    if output_format == "date":
        click.echo(value.strftime("%Y-%m-%d"))
    elif output_format == "readable":
        click.echo(value.strftime("%Y年%m月%d日 %H:%M:%S"))
    else:
        click.echo(value.isoformat(sep=" "))


@system.command("fail")
@click.option("--code", type=click.IntRange(1, 128), default=1, help="退出码。")
@click.option("--message", default="演示失败", help="失败信息。")
def system_fail(code: int, message: str) -> None:
    """演示失败：写入 stderr 并以非零退出码结束。"""
    click.echo(f"[stderr] {message}", err=True)
    raise click.ClickException(f"{message}（退出码 {code}）")


@system.command("sleep")
@click.argument("seconds", type=click.FloatRange(0.0, 5.0))
def system_sleep(seconds: float) -> None:
    """等待若干秒（0-5）。"""
    time.sleep(seconds)
    click.echo(f"已等待 {seconds} 秒")


@system.command("json")
@click.option("--payload", default='{"hello": "world"}', help="要输出的 JSON 文本。")
def system_json(payload: str) -> None:
    """格式化输出 JSON，便于查看长文本。"""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"JSON 解析失败: {exc}") from exc
    click.echo(json.dumps(data, ensure_ascii=False, indent=2))


@system.command("password")
@click.option(
    "--password",
    prompt=True,
    hide_input=True,
    help="密码；Web 表单中会以密码框显示，输入内容被遮挡。",
)
def system_password(password: str) -> None:
    """演示 hide_input 密码输入（Web 中自动渲染为密码框）。"""
    click.echo(f"已接收密码，长度 {len(password)}")


@system.command("uuid")
@click.argument("value", type=click.UUID)
def system_uuid(value) -> None:
    """演示 UUID 参数（Web 表单会即时校验格式）。"""
    click.echo(f"uuid={value}")


# --------------------------------------------------------------- more groups
@cli.group()
@click.option("--prefix", default="", help="所有子命令共享的前缀。")
@click.pass_context
def greet(ctx: click.Context, prefix: str) -> None:
    """带全局参数的命令组。"""
    ctx.ensure_object(dict)
    ctx.obj["prefix"] = prefix


@greet.command("hello")
@click.argument("name")
@click.pass_context
def greet_hello(ctx: click.Context, name: str) -> None:
    """向某人问好（会使用命令组的 --prefix）。"""
    click.echo(f"{ctx.obj.get('prefix', '')}hello, {name}!")


@greet.command("bye")
@click.argument("name")
@click.pass_context
def greet_bye(ctx: click.Context, name: str) -> None:
    """向某人告别（会使用命令组的 --prefix）。"""
    click.echo(f"{ctx.obj.get('prefix', '')}bye, {name}!")


@cli.group(invoke_without_command=True)
@click.option("--greeting", default="你好", help="没有子命令时使用的问候语。")
@click.pass_context
def ping(ctx: click.Context, greeting: str) -> None:
    """invoke_without_command 示例：没有子命令时也能直接执行。"""
    if ctx.invoked_subcommand is None:
        click.echo(f"{greeting}！")


@ping.command("name")
@click.argument("name")
def ping_name(name: str) -> None:
    """向指定名字打招呼。"""
    click.echo(f"你好，{name}！")


@cli.group(chain=True)
def pipeline() -> None:
    """链式命令组示例（在 Web 表单中建议逐条加入队列执行）。"""


@pipeline.command("upper")
@click.argument("value")
def pipeline_upper(value: str) -> None:
    click.echo(value.upper())


@pipeline.command("suffix")
@click.argument("value")
@click.option("--suffix", default="!")
def pipeline_suffix(value: str, suffix: str) -> None:
    click.echo(f"{value}{suffix}")


@cli.command("legacy", deprecated=True)
@click.option("--value", default="legacy")
def legacy(value: str) -> None:
    """演示已废弃命令。"""
    click.echo(f"legacy: {value}")


@cli.command("hidden-demo", hidden=True)
def hidden_demo() -> None:
    """这个命令在 Click 帮助里默认隐藏，控制台会放进“高级参数/隐藏命令”之外。"""
    click.echo("hidden-demo executed")


if __name__ == "__main__":
    cli()
