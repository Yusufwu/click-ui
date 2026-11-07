"""The smallest useful Click app that cli-ui-amis can serve.

Run it directly::

    python examples/minimal_cli.py deploy api --replicas 3

Or expose it as a web console::

    cliui serve examples/minimal_cli.py:cli
"""

from __future__ import annotations

import click


@click.group()
def cli() -> None:
    """A tiny deployment toolbox used by the quick start."""


@cli.command()
@click.argument("service")
@click.option(
    "--replicas",
    type=click.IntRange(1, 9),
    default=2,
    show_default=True,
    help="Number of replicas to run (1-9).",
)
@click.option("--force/--no-force", default=False, help="Skip the safety check.")
def deploy(service: str, replicas: int, force: bool) -> None:
    """Deploy a service with N replicas."""
    click.echo(f"deploying {service} x{replicas} (force={force})")


@cli.command()
@click.option("--tail/--no-tail", default=False, help="Follow the log stream.")
@click.option(
    "--level",
    type=click.Choice(["info", "warn", "error"], case_sensitive=False),
    default="info",
    show_default=True,
    help="Minimum log level.",
)
def logs(tail: bool, level: str) -> None:
    """Show logs at a given level."""
    click.echo(("following" if tail else "reading") + f" logs at {level}")


@cli.command()
@click.option("--password", prompt=True, hide_input=True, help="Operator password.")
def whoami(password: str) -> None:
    """Check credentials without printing the secret."""
    click.echo(f"credentials accepted ({len(password)} characters)")


if __name__ == "__main__":
    cli()
