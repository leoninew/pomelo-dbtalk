"""Tests for Git-history version calculation and uv metadata updates."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "version_calc.py"
SPEC = importlib.util.spec_from_file_location("dbtalk_version_calc", SCRIPT)
assert SPEC is not None
assert SPEC.loader is not None
version_calc: Any = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = version_calc
SPEC.loader.exec_module(version_calc)


def test_calculate_version_resets_patch_for_feature_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commits = iter(
        [
            ("a" * 40, "2026-01-01T00:00:00Z", "chore: initial setup"),
            ("b" * 40, "2026-01-02T00:00:00Z", " feat: add command"),
            ("c" * 40, "2026-01-03T00:00:00Z", "fix: handle timeout"),
            ("d" * 40, "2026-01-04T00:00:00Z", "FEAT: add versioning"),
        ]
    )
    monkeypatch.setattr(version_calc, "iter_commits", lambda: commits)

    assert version_calc.calculate_version(print_history=False) == "0.2.0"


def test_prepare_project_version_update_only_changes_project_version(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_bytes(
        b'[project]\r\nname = "dbtalk"\r\nversion = "0.1.0"\r\n'
        b'\r\n[tool.example]\r\nversion = "keep"\r\n'
    )
    monkeypatch.setattr(version_calc, "PYPROJECT_FILE", pyproject)

    previous, updated = version_calc.prepare_project_version_update("0.2.0")

    assert previous == "0.1.0"
    assert updated == (
        b'[project]\r\nname = "dbtalk"\r\nversion = "0.2.0"\r\n'
        b'\r\n[tool.example]\r\nversion = "keep"\r\n'
    )


def test_apply_version_refreshes_uv_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    lock = tmp_path / "uv.lock"
    pyproject.write_text('[project]\nname = "dbtalk"\nversion = "0.1.0"\n', encoding="utf-8")
    lock.write_text('[[package]]\nname = "dbtalk"\nversion = "0.1.0"\n', encoding="utf-8")
    calls: list[tuple[str, ...]] = []

    def refresh_lock(*args: str) -> None:
        calls.append(args)
        lock.write_text('[[package]]\nname = "dbtalk"\nversion = "0.2.0"\n', encoding="utf-8")

    monkeypatch.setattr(version_calc, "PYPROJECT_FILE", pyproject)
    monkeypatch.setattr(version_calc, "UV_LOCK_FILE", lock)
    monkeypatch.setattr(version_calc, "run_uv", refresh_lock)

    version_calc.apply_version("0.2.0")

    assert 'version = "0.2.0"' in pyproject.read_text(encoding="utf-8")
    assert 'version = "0.2.0"' in lock.read_text(encoding="utf-8")
    assert calls == [("lock",)]


def test_apply_version_restores_metadata_when_uv_lock_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    lock = tmp_path / "uv.lock"
    original_pyproject = '[project]\nname = "dbtalk"\nversion = "0.1.0"\n'
    original_lock = '[[package]]\nname = "dbtalk"\nversion = "0.1.0"\n'
    pyproject.write_text(original_pyproject, encoding="utf-8")
    lock.write_text(original_lock, encoding="utf-8")

    def fail_lock(*args: str) -> None:
        raise RuntimeError(f"uv failed for {args}")

    monkeypatch.setattr(version_calc, "PYPROJECT_FILE", pyproject)
    monkeypatch.setattr(version_calc, "UV_LOCK_FILE", lock)
    monkeypatch.setattr(version_calc, "run_uv", fail_lock)

    with pytest.raises(RuntimeError, match="uv failed"):
        version_calc.apply_version("0.2.0")

    assert pyproject.read_text(encoding="utf-8") == original_pyproject
    assert lock.read_text(encoding="utf-8") == original_lock
