"""Smoke tests to confirm the package imports and the CLI runs."""

from equity_analyst import __version__
from equity_analyst.__main__ import main


def test_version() -> None:
    assert isinstance(__version__, str)
    assert __version__


def test_cli_runs() -> None:
    assert main([]) == 0
