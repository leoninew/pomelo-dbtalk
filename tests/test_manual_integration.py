"""Opt-in integration coverage for a manually prepared MySQL source."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from dbtalk.cli import cli


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("DBTALK_RUN_INTEGRATION") != "1",
    reason="set DBTALK_RUN_INTEGRATION=1 to run manually",
)
def test_manual_mysql_dump(tmp_path: Path) -> None:
    required = (
        "DBTALK_MYSQLDUMP__HOST",
        "DBTALK_MYSQLDUMP__USER",
        "DBTALK_MYSQLDUMP__PASSWORD",
        "DBTALK_MYSQLDUMP__DATABASE",
    )
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        pytest.skip(f"set manual MySQL configuration: {', '.join(missing)}")

    output = tmp_path / "manual.sql"
    result = CliRunner().invoke(cli, ["mysql", "dump", "--output", str(output)])

    assert result.exit_code == 0, result.output
    assert output.is_file()
    assert output.stat().st_size > 0
