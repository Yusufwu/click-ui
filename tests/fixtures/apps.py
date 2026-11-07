"""Small Click applications used by the automated tests."""

from __future__ import annotations

import json

import click


@click.group()
@click.option("--root-name", default="root", help="根级名称。")
@click.option("-v", "--verbose", count=True, help="详细程度，可重复。")
def fixture(root_name: str, verbose: int) -> None:
    """测试用根命令组。"""
    click.echo(f"[root={root_name} verbose={verbose}]")


@fixture.command("echo")
@click.argument("text")
@click.option("--name", default="leaf", help="叶子名称。")
def echo(text: str, name: str) -> None:
    """回显文本。"""
    click.echo(f"{name}:{text}")


@fixture.group()
@click.option("--name", default="group", help="组级名称。")
def sub(name: str) -> None:
    """子命令组。"""
    click.echo(f"[sub={name}]")


@sub.command("run")
@click.argument("value")
@click.option("--name", default="run", help="命令名称。")
@click.option("--flag/--no-flag", "flag", default=True, help="布尔开关。")
@click.option("--level", type=click.IntRange(1, 10), default=3, help="等级。")
@click.option("--ratio", type=click.FloatRange(0.0, 2.0), default=1.0, help="比例。")
@click.option(
    "--mode", type=click.Choice(["a", "b"], case_sensitive=False), default="a"
)
@click.option("--tag", multiple=True, help="可重复标签。")
@click.option(
    "--color",
    type=click.Choice(["red", "green", "blue"]),
    multiple=True,
    help="可多选的颜色。",
)
@click.option("--pair", type=(str, int), help="两个值。")
@click.option(
    "--when",
    type=click.DateTime(formats=["%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]),
    help="时间。",
)
def sub_run(value, name, flag, level, ratio, mode, tag, color, pair, when) -> None:
    """组合多种参数类型。"""
    payload = {
        "value": value,
        "name": name,
        "flag": flag,
        "level": level,
        "ratio": ratio,
        "mode": mode,
        "tag": list(tag),
        "color": list(color),
        "pair": list(pair) if pair else None,
        "when": when.isoformat(sep=" ") if when else None,
    }
    click.echo(json.dumps(payload, ensure_ascii=False))


@fixture.command("needs")
@click.option("--token", required=True, help="必填令牌。")
def needs(token: str) -> None:
    """必须提供 --token。"""
    click.echo(f"token={token}")


@fixture.command("readfile")
@click.argument("source", type=click.File("r", encoding="utf-8"))
def readfile(source) -> None:
    """读取文件。"""
    click.echo(source.read())


@fixture.command("checkpath")
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
def checkpath(path: str) -> None:
    """检查路径存在。"""
    click.echo(f"exists: {path}")


@fixture.command("writepath")
@click.argument("path", type=click.Path(dir_okay=False))
@click.option("--content", default="hello")
def writepath(path: str, content: str) -> None:
    """写入文件（Path 类型，不要求存在）。"""
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    click.echo(f"written: {path}")


@fixture.command("boom")
def boom() -> None:
    """抛出未捕获异常。"""
    raise RuntimeError("boom")


@fixture.command("abort")
def abort() -> None:
    """触发 Click Abort。"""
    raise click.Abort()


@fixture.command("warn")
def warn() -> None:
    """同时写 stdout 和 stderr。"""
    click.echo("to-stdout")
    click.echo("to-stderr", err=True)


@fixture.command("code")
def code() -> None:
    """以退出码 7 结束。"""
    raise SystemExit(7)


@fixture.command("big")
@click.option("--size", type=int, default=1000, help="输出字符数。")
def big(size: int) -> None:
    """输出大量文本。"""
    click.echo("x" * size)


@fixture.command("password")
@click.option("--value", prompt=True, hide_input=True, help="密码值。")
def password(value: str) -> None:
    """隐藏输入的密码选项。"""
    click.echo(f"len={len(value)}")


@fixture.command("uuid")
@click.argument("value", type=click.UUID)
def uuid_param(value) -> None:
    """UUID 参数。"""
    click.echo(f"uuid:{value}")


@fixture.command("secret", hidden=True)
def secret() -> None:
    """隐藏命令。"""
    click.echo("secret")


@click.command()
@click.argument("value")
def single(value: str) -> None:
    """单体命令（没有子命令）。"""
    click.echo(f"single:{value}")


@click.command()
def dynamic() -> None:
    """动态加载的命令。"""
    click.echo("dynamic")


class LazyGroup(click.Group):
    """A group that resolves commands lazily, like large real applications."""

    def list_commands(self, ctx):
        return ["dynamic"]

    def get_command(self, ctx, name):
        if name == "dynamic":
            return dynamic
        return None


lazy = LazyGroup(name="lazy")


@click.group()
def first() -> None:
    """第一个来源。"""


@first.command("one")
def one() -> None:
    click.echo("one")


@click.group()
def second() -> None:
    """第二个来源。"""


@second.command("two")
def two() -> None:
    click.echo("two")


collection = click.CommandCollection(name="collection", sources=[first, second])
