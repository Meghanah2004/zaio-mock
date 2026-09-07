"""CLI-boundary security tests: numeric argument bounds, and proof that
internal exceptions (including ones containing secret-shaped text or
absolute paths) never reach the user as a raw stack trace or unredacted
message via the CLI's top-level error handler."""
from __future__ import annotations

import contextlib
import io

import pytest

from src.cli import build_parser


def test_paper_number_below_minimum_is_rejected():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["generate", "--paper-number", "0"])


def test_paper_number_above_maximum_is_rejected():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["generate", "--paper-number", "999999"])


def test_negative_seed_is_rejected():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["generate", "--seed", "-1"])


def test_seed_above_maximum_is_rejected():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["generate", "--seed", "99999999999"])


def test_non_integer_paper_number_is_rejected():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["generate", "--paper-number", "not-a-number"])


def test_valid_bounds_are_accepted():
    parser = build_parser()
    args = parser.parse_args(["generate", "--paper-number", "3", "--seed", "42"])
    assert args.paper_number == 3
    assert args.seed == 42


def test_main_never_leaks_secret_in_error_output(monkeypatch):
    """Force the dispatched command to fail with a message that would
    contain a secret-shaped string if it weren't redacted, and confirm
    main()'s top-level handler strips it before printing."""

    def _boom(args):
        raise ValueError("could not reach provider using key sk-ant-api03-abcdefghijklmnopqrstuvwxyz")

    import src.cli as cli_module

    parser = cli_module.build_parser()
    for action in parser._subparsers._group_actions[0].choices.values():
        action.set_defaults(func=_boom)
    monkeypatch.setattr(cli_module, "build_parser", lambda: parser)

    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        rc = cli_module.main(["analyze"])
    output = stderr.getvalue()
    assert rc == 1
    assert "sk-ant-api03" not in output
    assert "[REDACTED]" in output


def test_main_handles_unexpected_exception_type_without_traceback(monkeypatch):
    """An exception type not explicitly listed in main()'s except clause
    (e.g. a bare RuntimeError) must still be caught and printed as a clean
    one-line error, never as a raw Python traceback."""

    def _boom(args):
        raise RuntimeError("unexpected internal failure at /Users/someone/project/secret_module.py")

    import src.cli as cli_module

    parser = cli_module.build_parser()
    monkeypatch.setattr(cli_module, "build_parser", lambda: parser)
    for action in parser._subparsers._group_actions[0].choices.values():
        action.set_defaults(func=_boom)

    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        rc = cli_module.main(["analyze"])
    output = stderr.getvalue()
    assert rc == 1
    assert "Traceback" not in output
    assert "RuntimeError" in output
