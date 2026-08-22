from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from dbtalk.database.dsn import sqlite_dsn
from dbtalk.database.transfer import (
    ExportOptions,
    ImportOptions,
    TransferConnection,
    export_database,
    import_database,
)
from dbtalk.logging_config import configure_logging
from dbtalk.settings import LoggingSettings


class DatabaseTransferLoggingTests(unittest.TestCase):
    def test_configure_logging_uses_configured_standard_format_and_level(self) -> None:
        config = LoggingSettings(
            level="WARNING",
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )

        with patch("dbtalk.logging_config.logging.basicConfig") as configure:
            configure_logging(config.level, config.format, verbose=False)

        configure.assert_called_once_with(
            level="WARNING",
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            force=True,
        )

    def test_sqlite_export_logs_task_schema_table_and_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.db"
            output = root / "transfer.jsonl"
            self._create_database(source, "source")

            with self.assertLogs("dbtalk", level="INFO") as captured:
                export_database(
                    ExportOptions(
                        TransferConnection("sqlite", dsn=sqlite_dsn(source)),
                        output,
                        ZoneInfo("UTC"),
                    )
                )

            messages = "\n".join(captured.output)
            self.assertIn("database export started driver=sqlite", messages)
            self.assertIn("database export connecting sqlite", messages)
            self.assertIn(
                "database export table completed dialect=sqlite table=items rows=1", messages
            )
            self.assertIn("database export completed driver=sqlite", messages)

    def test_sqlite_import_logs_document_preflight_table_and_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.db"
            target = root / "target.db"
            output = root / "transfer.jsonl"
            self._create_database(source, "source")
            self._create_database(target, "target")
            export_database(
                ExportOptions(
                    TransferConnection("sqlite", dsn=sqlite_dsn(source)),
                    output,
                    ZoneInfo("UTC"),
                )
            )

            with self.assertLogs("dbtalk", level="INFO") as captured:
                import_database(
                    ImportOptions(
                        TransferConnection("sqlite", dsn=sqlite_dsn(target)),
                        output,
                        "upsert",
                        ZoneInfo("UTC"),
                    )
                )

            messages = "\n".join(captured.output)
            self.assertIn("database import started driver=sqlite", messages)
            self.assertIn("database import connecting sqlite", messages)
            self.assertIn(
                "database import table completed dialect=sqlite table=items rows=1 mode=upsert",
                messages,
            )
            self.assertIn("database import completed driver=sqlite", messages)

    @staticmethod
    def _create_database(path: Path, value: str) -> None:
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO items VALUES (1, ?)", (value,))
        connection.commit()
        connection.close()


if __name__ == "__main__":
    unittest.main()
