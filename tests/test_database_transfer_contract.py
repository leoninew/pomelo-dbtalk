from __future__ import annotations

import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

from click.testing import CliRunner

from dbtalk.cli import cli as main
from dbtalk.database.transfer import (
    ExportOptions,
    TransferConnection,
    validate_connection,
)


class DatabaseTransferContractTests(unittest.TestCase):
    def test_database_help_exposes_jsonl_commands(self) -> None:
        result = CliRunner().invoke(main, ["database", "--help"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("export", result.output)
        self.assertIn("import", result.output)

    def test_export_help_exposes_connection_and_timezone_options(self) -> None:
        result = CliRunner().invoke(main, ["database", "export", "--help"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("--sqlite-path", result.output)
        self.assertIn("--mysql-dsn-env", result.output)
        self.assertIn("--tz", result.output)
        self.assertIn("--include-table", result.output)
        self.assertIn("--exclude-table", result.output)

    def test_import_help_exposes_strict_insert_and_upsert_modes(self) -> None:
        result = CliRunner().invoke(main, ["database", "import", "--help"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("insert", result.output)
        self.assertIn("upsert", result.output)
        self.assertNotIn("append", result.output)
        self.assertIn("--include-table", result.output)
        self.assertIn("--exclude-table", result.output)

    def test_connection_contract_requires_driver_specific_input(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "--sqlite-path"):
            validate_connection(TransferConnection(driver="sqlite"))
        with self.assertRaisesRegex(RuntimeError, "--mysql-dsn-env"):
            validate_connection(TransferConnection(driver="mysql"))

    def test_export_options_preserve_public_shape(self) -> None:
        options = ExportOptions(
            connection=TransferConnection(driver="sqlite", sqlite_path=Path("source.db")),
            output=Path("transfer.jsonl"),
            timezone=ZoneInfo("UTC"),
        )

        self.assertEqual(options.connection.driver, "sqlite")
        self.assertEqual(options.output, Path("transfer.jsonl"))


if __name__ == "__main__":
    unittest.main()
