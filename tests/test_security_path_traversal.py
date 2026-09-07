"""Path-traversal and filesystem-escape regression tests.

Covers: relative traversal, nested traversal, absolute-path escapes,
encoded/literal-looking traversal strings, symlink-based escapes, and the
hard requirement that no resolvable output path may ever land inside
sdev/.
"""
from __future__ import annotations

import os

import pytest

from src.config import SDEV_DIR, safe_path_within


def test_blocks_single_level_traversal(tmp_path):
    with pytest.raises(ValueError):
        safe_path_within(tmp_path, "../escaped.json")


def test_blocks_nested_traversal(tmp_path):
    with pytest.raises(ValueError):
        safe_path_within(tmp_path, "../../../../escaped.json")


def test_blocks_traversal_hidden_inside_a_longer_relative_path(tmp_path):
    with pytest.raises(ValueError):
        safe_path_within(tmp_path, "subdir/../../escaped.json")


def test_blocks_absolute_path_escape(tmp_path):
    with pytest.raises(ValueError):
        safe_path_within(tmp_path, "/etc/passwd")


def test_does_not_treat_literal_percent_encoded_string_as_traversal(tmp_path):
    """We never URL-decode filesystem paths, so a literal string containing
    '%2e%2e' is just an unusual filename component, not a traversal - this
    confirms that non-decoding is itself the safe behaviour (the resulting
    path still resolves safely inside base_dir)."""
    result = safe_path_within(tmp_path, "%2e%2e%2fetc%2fpasswd")
    assert result.parent == tmp_path.resolve()


def test_allows_safe_nested_path(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    result = safe_path_within(tmp_path, "a/b/file.json")
    assert result == (tmp_path / "a" / "b" / "file.json").resolve()


def test_allows_absolute_path_that_is_already_inside_base(tmp_path):
    """An absolute path is only rejected if it resolves OUTSIDE base_dir -
    one that already points inside it (e.g. a path the app itself
    constructed) must be accepted, not blocked outright just for being
    absolute. (Consolidated from the former tests/test_path_safety.py,
    which this file superseded - see docs/CODE-QUALITY-AUDIT.md.)"""
    target = tmp_path / "ok.json"
    result = safe_path_within(tmp_path, str(target))
    assert result == target.resolve()


@pytest.mark.skipif(os.name == "nt", reason="symlink semantics differ on Windows")
def test_blocks_symlink_escape(tmp_path):
    """A symlink INSIDE base_dir that points OUTSIDE it must not be usable
    to escape - Path.resolve() follows symlinks, so the post-resolution
    relative_to() check in safe_path_within catches this."""
    outside = tmp_path.parent / "outside_target"
    outside.mkdir(exist_ok=True)
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    escape_link = base_dir / "escape_link"
    escape_link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError):
        safe_path_within(base_dir, "escape_link/evil.json")


def test_sdev_directory_can_never_be_an_output_destination():
    """Even a maliciously-supplied path string cannot resolve to somewhere
    inside sdev/ and be accepted as a safe output location - sdev/ is a
    sibling of the permitted output/artifacts directories, so any attempt
    to target it from within a different base_dir is a traversal that
    safe_path_within already rejects."""
    from src.config import ARTIFACTS_DIR

    relative_into_sdev = os.path.relpath(SDEV_DIR, ARTIFACTS_DIR)
    with pytest.raises(ValueError):
        safe_path_within(ARTIFACTS_DIR, f"{relative_into_sdev}/malicious.json")
