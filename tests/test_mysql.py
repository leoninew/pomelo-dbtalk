from __future__ import annotations

import gzip
import unittest
from datetime import datetime
from pathlib import Path
from subprocess import CompletedProcess
from typing import cast
from unittest.mock import ANY, patch

import click
from click.testing import CliRunner

from dbtalk.cli import cli as main_command
from dbtalk.mysql.cli import (
    MysqlDumpOptions,
    MysqlDumpOverrides,
    MysqlRestoreOptions,
    MysqlRestoreOverrides,
    default_dump_output,
    dump_database,
    generate_dump_command,
    generate_restore_command,
    mysql_restore_args,
    mysqldump_args,
    resolve_dump_options,
    resolve_restore_options,
    restore_database,
)
from dbtalk.mysql.dump import docker_mapped_mysql_container
from dbtalk.settings import MySQLDumpConfig, MySQLRestoreConfig


class MysqlCommandTests(unittest.TestCase):
    def test_mysqldump_args_uses_defaults_without_host_or_port(self) -> None:
        options = MysqlDumpOptions(
            host="localhost",
            port=3306,
            user="root",
            password="secret",
            database="example",
            output=Path("backup.sql"),
        )

        self.assertEqual(
            mysqldump_args(options),
            [
                "env",
                "MYSQL_PWD=secret",
                "mysqldump",
                "-u",
                "root",
                "-B",
                "example",
                "--no-create-db",
                "-R",
                "-E",
                "--set-gtid-purged=OFF",
                "--skip-lock-tables",
                "-r",
                "backup.sql",
            ],
        )

    def test_generate_dump_command_quotes_sensitive_and_space_containing_values(
        self,
    ) -> None:
        options = MysqlDumpOptions(
            host="db.example.com",
            port=3307,
            user="backup user",
            password="p@ss word$",
            database="example",
            output=Path("backup file.sql"),
            create_database=True,
            drop_database=True,
        )

        self.assertEqual(
            generate_dump_command(options),
            "env 'MYSQL_PWD=p@ss word$' mysqldump -C -h db.example.com -P 3307 "
            "-u 'backup user' -B example --add-drop-database -R -E "
            "--set-gtid-purged=OFF --skip-lock-tables -r 'backup file.sql'",
        )

    def test_dump_database_runs_local_mysqldump_when_available(self) -> None:
        options = MysqlDumpOptions(
            host="db.example.com",
            port=3307,
            user="backup",
            password="secret",
            database="example",
            output=Path("backup.sql"),
            create_database=True,
            drop_database=True,
        )

        with (
            patch(
                "dbtalk.mysql.dump.shutil.which",
                return_value="/usr/bin/mysqldump",
            ),
            patch(
                "dbtalk.mysql.dump.run_command",
                return_value=CompletedProcess([], 0, "", ""),
            ) as run,
        ):
            output = dump_database(options)

        self.assertEqual(output, Path("backup.sql").resolve())
        command = run.call_args.args[0]
        self.assertEqual(
            command,
            [
                "mysqldump",
                "-C",
                "-h",
                "db.example.com",
                "-P",
                "3307",
                "-u",
                "backup",
                "-B",
                "example",
                "--add-drop-database",
                "-R",
                "-E",
                "--set-gtid-purged=OFF",
                "--skip-lock-tables",
                "-r",
                str(Path("backup.sql").resolve()),
            ],
        )
        self.assertEqual(run.call_args.args[1]["MYSQL_PWD"], "secret")

    def test_dump_database_uses_local_docker_mysql_image_as_fallback(self) -> None:
        options = MysqlDumpOptions(
            host="localhost",
            port=3306,
            user="root",
            password="secret",
            database="example",
            output=Path("backup.sql"),
        )
        success = CompletedProcess([], 0, "", "")

        with (
            patch("dbtalk.mysql.dump.shutil.which", return_value=None),
            patch("dbtalk.mysql.dump.docker_mapped_mysql_container", return_value=None),
            patch(
                "dbtalk.mysql.dump.docker_mysql_image",
                return_value=("mysql:8.4", ""),
            ),
            patch(
                "dbtalk.mysql.dump.run_command",
                side_effect=[success, success],
            ) as run,
            patch("dbtalk.mysql.dump.remove_temporary_container"),
        ):
            output = dump_database(options)

        self.assertEqual(output, Path("backup.sql").resolve())
        docker_run = run.call_args_list[0].args[0]
        self.assertEqual(docker_run[:3], ["docker", "run", "--name"])
        self.assertIn("mysql:8.4", docker_run)
        self.assertIn("host.docker.internal", docker_run)
        self.assertNotIn("-C", docker_run)
        self.assertNotIn("secret", docker_run)
        self.assertEqual(
            run.call_args_list[1].args[0],
            [
                "docker",
                "cp",
                ANY,
                str(Path("backup.sql").resolve()),
            ],
        )
        self.assertEqual(run.call_count, 2)

    def test_dump_database_writes_gzip_output_when_archive_is_enabled(self) -> None:
        runner = CliRunner()

        with runner.isolated_filesystem():
            options = MysqlDumpOptions(
                host="localhost",
                port=3306,
                user="root",
                password="secret",
                database="example",
                output=Path("backup.sql"),
                archive=True,
            )

            def write_dump(
                command: list[str], environment: dict[str, str]
            ) -> CompletedProcess[str]:
                self.assertEqual(environment["MYSQL_PWD"], "secret")
                Path(command[-1]).write_text("SELECT 1;\n", encoding="utf-8")
                return CompletedProcess(command, 0, "", "")

            with (
                patch(
                    "dbtalk.mysql.dump.docker_mapped_mysql_container",
                    return_value=None,
                ),
                patch(
                    "dbtalk.mysql.dump.shutil.which",
                    return_value="/usr/bin/mysqldump",
                ),
                patch("dbtalk.mysql.dump.run_command", side_effect=write_dump),
            ):
                output = dump_database(options)

            self.assertEqual(output, Path("backup.sql.gz").resolve())
            with gzip.open(output, "rt", encoding="utf-8") as compressed:
                self.assertEqual(compressed.read(), "SELECT 1;\n")

    def test_dump_database_uses_mapped_mysql_container_before_other_clients(self) -> None:
        options = MysqlDumpOptions(
            host="127.0.0.1",
            port=3306,
            user="root",
            password="secret",
            database="example",
            output=Path("backup.sql"),
        )
        success = CompletedProcess([], 0, "", "")

        with (
            patch(
                "dbtalk.mysql.dump.docker_mapped_mysql_container",
                return_value="mysql-server",
            ),
            patch("dbtalk.mysql.dump.shutil.which", return_value=None) as which,
            patch(
                "dbtalk.mysql.dump.run_command",
                side_effect=[success, success, success],
            ) as run,
        ):
            output = dump_database(options)

        self.assertEqual(output, Path("backup.sql").resolve())
        which.assert_called_once_with("mysqldump")
        dump_command = run.call_args_list[0].args[0]
        self.assertEqual(
            dump_command[:7],
            [
                "docker",
                "exec",
                "--env",
                "MYSQL_PWD",
                "mysql-server",
                "mysqldump",
                "-u",
            ],
        )
        self.assertNotIn("-h", dump_command)
        self.assertNotIn("-P", dump_command)
        self.assertEqual(run.call_args_list[0].args[1]["MYSQL_PWD"], "secret")
        self.assertEqual(
            run.call_args_list[1].args[0],
            ["docker", "cp", ANY, str(Path("backup.sql").resolve())],
        )
        self.assertEqual(
            run.call_args_list[2].args[0][:5],
            ["docker", "exec", "mysql-server", "rm", "-f"],
        )

    def test_docker_mapped_mysql_container_matches_the_requested_host_port(self) -> None:
        listed = CompletedProcess([], 0, "mysql-server\n", "")
        with (
            patch("dbtalk.mysql.dump.subprocess.run", return_value=listed),
        ):
            container_id = docker_mapped_mysql_container("localhost", 3306)

        self.assertEqual(container_id, "mysql-server")

    def test_docker_mapped_mysql_container_rejects_ambiguous_container_matches(self) -> None:
        listed = CompletedProcess([], 0, "mysql-one\nmysql-two\n", "")

        with (
            patch("dbtalk.mysql.dump.shutil.which", return_value="docker"),
            patch("dbtalk.mysql.dump.subprocess.run", return_value=listed) as run,
        ):
            container_id = docker_mapped_mysql_container("localhost", 3306)

        self.assertIsNone(container_id)
        self.assertEqual(run.call_count, 1)

    def test_docker_mapped_mysql_container_handles_a_docker_start_failure(self) -> None:
        with (
            patch("dbtalk.mysql.dump.subprocess.run", side_effect=OSError("unavailable")),
        ):
            container_id = docker_mapped_mysql_container("localhost", 3306)

        self.assertIsNone(container_id)

    def test_cli_dumps_to_current_directory_when_output_is_omitted(self) -> None:
        runner = CliRunner()

        with (
            runner.isolated_filesystem(),
            patch(
                "dbtalk.mysql.cli.dump_database",
                side_effect=lambda options: options.output,
            ) as dump,
        ):
            Path("backups").mkdir()
            result = runner.invoke(
                main_command,
                [
                    "mysql",
                    "dump",
                    "--dsn",
                    "mysql+pymysql://backup:secret@localhost/example",
                ],
            )
            default_output = dump.call_args.args[0].output
            self.assertTrue(default_output.parent.is_dir())

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertRegex(
            result.output,
            r"MySQL dump written to .+data[\\/]example-\d{8}-\d{6}\.sql\n",
        )
        self.assertRegex(
            default_output.name,
            r"example-\d{8}-\d{6}\.sql",
        )

    def test_cli_uses_explicit_dump_dsn(self) -> None:
        runner = CliRunner()

        with (
            runner.isolated_filesystem(),
            patch(
                "dbtalk.mysql.cli.dump_database",
                side_effect=lambda options: options.output,
            ) as dump,
        ):
            Path("backups").mkdir()
            result = runner.invoke(
                main_command,
                [
                    "mysql",
                    "dump",
                    "--dsn",
                    "mysql+pymysql://cli-user:configured-password@db.example.test:3307/configured-database",
                    "--create-database",
                    "--drop-database",
                    "--output",
                    "backups",
                ],
            )
            options = dump.call_args.args[0]

            self.assertEqual(options.host, "db.example.test")
            self.assertEqual(options.port, 3307)
            self.assertEqual(options.user, "cli-user")
            self.assertEqual(options.password, "configured-password")
            self.assertEqual(options.database, "configured-database")
            self.assertTrue(options.create_database)
            self.assertTrue(options.drop_database)
            self.assertEqual(options.output.parent, Path.cwd() / "backups")

        self.assertEqual(result.exit_code, 0, result.output)

    def test_default_dump_output_uses_database_and_timestamp(self) -> None:
        runner = CliRunner()

        with runner.isolated_filesystem():
            output = default_dump_output(
                "example",
                datetime(2026, 8, 19, 10, 37, 5),
                output_directory="data",
            )

            self.assertEqual(
                output,
                Path.cwd() / "data" / "example-20260819-103705.sql",
            )
            self.assertTrue(output.parent.is_dir())

    def test_explicit_dump_directory_uses_timestamped_default_name(self) -> None:
        config = MySQLDumpConfig(
            host="localhost",
            port=3306,
            user="root",
            password="secret",
            database="example",
            create_database=False,
            drop_database=False,
            output_directory="data",
        )
        runner = CliRunner()

        with (
            runner.isolated_filesystem(),
            patch("dbtalk.mysql.dump.datetime") as mocked_datetime,
        ):
            Path("exports").mkdir()
            mocked_datetime.now.return_value = datetime(2026, 8, 20, 15, 45, 0)
            options = resolve_dump_options(
                config,
                MysqlDumpOverrides(
                    host=None,
                    port=None,
                    user=None,
                    password=None,
                    database=None,
                    output=Path("exports"),
                    create_database=None,
                    drop_database=None,
                    archive=True,
                ),
            )

            self.assertEqual(
                options.output,
                Path.cwd() / "exports" / "example-20260820-154500.sql.gz",
            )

    def test_cli_accepts_an_existing_dump_directory(self) -> None:
        runner = CliRunner()

        with (
            runner.isolated_filesystem(),
            patch(
                "dbtalk.mysql.cli.dump_database",
                side_effect=lambda options: options.output,
            ) as dump,
        ):
            Path("exports").mkdir()
            result = runner.invoke(
                main_command,
                [
                    "mysql",
                    "dump",
                    "--dsn",
                    "mysql+pymysql://root:secret@localhost/example",
                    "--output",
                    "exports",
                ],
            )

            output = dump.call_args.args[0].output
            self.assertEqual(output.parent, Path.cwd() / "exports")
            self.assertTrue(output.name.startswith("example-"))
            self.assertEqual(output.suffix, ".sql")

        self.assertEqual(result.exit_code, 0, result.output)

    def test_dump_rejects_explicit_file_with_missing_parent_directory(self) -> None:
        options = MysqlDumpOptions(
            host="localhost",
            port=3306,
            user="root",
            password="secret",
            database="example",
            output=Path("missing") / "backup.sql",
        )

        with self.assertRaisesRegex(click.ClickException, "output directory does not exist"):
            dump_database(options)

    def test_resolve_dump_options_uses_config_defaults_and_cli_overrides(self) -> None:
        config = MySQLDumpConfig(
            host="db.example.test",
            port=3307,
            user="backup",
            password="test-password",
            database="app",
            create_database=True,
            drop_database=False,
            output_directory="backups/mysql",
        )
        runner = CliRunner()

        with runner.isolated_filesystem():
            configured = resolve_dump_options(
                config,
                MysqlDumpOverrides(
                    host=None,
                    port=None,
                    user=None,
                    password=None,
                    database=None,
                    output=None,
                    create_database=None,
                    drop_database=None,
                ),
            )
            overridden = resolve_dump_options(
                config,
                MysqlDumpOverrides(
                    host="backup.example.test",
                    port=3308,
                    user="cli-user",
                    password="cli-password",
                    database="cli-database",
                    output=Path("explicit.sql"),
                    create_database=False,
                    drop_database=True,
                ),
            )

            self.assertEqual(configured.host, "db.example.test")
            self.assertEqual(configured.port, 3307)
            self.assertEqual(configured.user, "backup")
            self.assertEqual(configured.password, "test-password")
            self.assertEqual(configured.database, "app")
            self.assertTrue(configured.create_database)
            self.assertFalse(configured.drop_database)
            self.assertTrue(configured.output.parent.is_dir())
            self.assertEqual(configured.output.parent, Path.cwd() / "backups" / "mysql")

        self.assertEqual(overridden.host, "backup.example.test")
        self.assertEqual(overridden.port, 3308)
        self.assertEqual(overridden.user, "cli-user")
        self.assertEqual(overridden.password, "cli-password")
        self.assertEqual(overridden.database, "cli-database")
        self.assertEqual(overridden.output, Path("explicit.sql"))
        self.assertFalse(overridden.create_database)
        self.assertTrue(overridden.drop_database)

    def test_resolve_dump_options_rejects_missing_credentials(self) -> None:
        config = MySQLDumpConfig(
            host="localhost",
            port=3306,
            user="",
            password="",
            database="",
            create_database=False,
            drop_database=False,
            output_directory="data",
        )

        with self.assertRaisesRegex(
            click.ClickException,
            "Missing mysqldump configuration: user, password, database",
        ):
            resolve_dump_options(
                config,
                MysqlDumpOverrides(
                    host=None,
                    port=None,
                    user=None,
                    password=None,
                    database=None,
                    output=None,
                    create_database=None,
                    drop_database=None,
                ),
            )

    def test_dump_database_explains_when_no_execution_path_is_available(self) -> None:
        options = MysqlDumpOptions(
            host="localhost",
            port=3306,
            user="root",
            password="secret",
            database="example",
            output=Path("backup.sql"),
        )

        message = "mysqldump is not available. Docker is not installed or is not on PATH."
        with (
            patch("dbtalk.mysql.dump.shutil.which", return_value=None),
            patch("dbtalk.mysql.dump.docker_mapped_mysql_container", return_value=None),
            patch(
                "dbtalk.mysql.dump.docker_mysql_image",
                return_value=(None, "Docker is not installed or is not on PATH."),
            ),
            self.assertRaisesRegex(
                click.ClickException,
                message,
            ),
        ):
            dump_database(options)

    def test_mysql_restore_args_uses_defaults_without_host_or_port(self) -> None:
        options = MysqlRestoreOptions(
            host="127.0.0.1",
            port=3306,
            user="root",
            password="secret",
            input=Path("backup.sql"),
        )

        self.assertEqual(
            mysql_restore_args(options),
            ["env", "MYSQL_PWD=secret", "mysql", "-u", "root"],
        )

    def test_restore_database_runs_local_mysql_when_available(self) -> None:
        runner = CliRunner()

        with runner.isolated_filesystem():
            input_path = Path("backup.sql")
            input_path.write_text("SELECT 1;\n", encoding="utf-8")
            options = MysqlRestoreOptions(
                host="db.example.com",
                port=3307,
                user="restore-user",
                password="secret",
                input=input_path,
            )
            with (
                patch(
                    "dbtalk.mysql.restore.shutil.which",
                    return_value="/usr/bin/mysql",
                ),
                patch(
                    "dbtalk.mysql.restore.run_command",
                    return_value=CompletedProcess([], 0, "", ""),
                ) as run,
            ):
                restored_input = restore_database(options)

            self.assertEqual(restored_input, input_path.resolve())
            command = run.call_args.args[0]
            self.assertEqual(
                command,
                [
                    "mysql",
                    "-h",
                    "db.example.com",
                    "-P",
                    "3307",
                    "-u",
                    "restore-user",
                ],
            )
            self.assertEqual(run.call_args.args[1]["MYSQL_PWD"], "secret")
            self.assertEqual(
                run.call_args.kwargs["input_path"],
                input_path.resolve(),
            )

    def test_restore_database_reads_gzip_input(self) -> None:
        runner = CliRunner()

        with runner.isolated_filesystem():
            input_path = Path("backup.sql.gz")
            with gzip.open(input_path, "wt", encoding="utf-8") as compressed:
                compressed.write("SELECT 1;\n")
            options = MysqlRestoreOptions(
                host="localhost",
                port=3306,
                user="root",
                password="secret",
                input=input_path,
            )
            captured_input: Path | None = None

            def read_dump(
                command: list[str], environment: dict[str, str], *, input_path: Path
            ) -> CompletedProcess[str]:
                nonlocal captured_input
                self.assertEqual(command, ["mysql", "-u", "root"])
                self.assertEqual(environment["MYSQL_PWD"], "secret")
                self.assertEqual(input_path.read_text(encoding="utf-8"), "SELECT 1;\n")
                captured_input = input_path
                return CompletedProcess(command, 0, "", "")

            with (
                patch(
                    "dbtalk.mysql.restore.shutil.which",
                    return_value="/usr/bin/mysql",
                ),
                patch("dbtalk.mysql.restore.run_command", side_effect=read_dump),
            ):
                restored = restore_database(options)

            self.assertEqual(restored, input_path.resolve())
            assert captured_input is not None
            self.assertFalse(captured_input.exists())

    def test_restore_database_rebases_dump_use_statement_for_target_database(
        self,
    ) -> None:
        runner = CliRunner()

        with runner.isolated_filesystem():
            input_path = Path("backup.sql")
            source = "CREATE DATABASE `source`;\nUSE `source`;\nCREATE TABLE example (id int);\n"
            input_path.write_text(source, encoding="utf-8")
            options = MysqlRestoreOptions(
                host="localhost",
                port=3306,
                user="restore-user",
                password="secret",
                input=input_path,
                database="target_database",
            )
            captured: dict[str, object] = {}

            def capture_input(
                command: list[str],
                environment: dict[str, str],
                *,
                input_path: Path,
            ) -> CompletedProcess[str]:
                captured["command"] = command
                captured["environment"] = environment
                captured["input"] = input_path.read_text(encoding="utf-8")
                captured["input_path"] = input_path
                return CompletedProcess([], 0, "", "")

            with (
                patch(
                    "dbtalk.mysql.restore.shutil.which",
                    return_value="/usr/bin/mysql",
                ),
                patch(
                    "dbtalk.mysql.restore.run_command",
                    side_effect=capture_input,
                ),
            ):
                restore_database(options)

            self.assertEqual(input_path.read_text(encoding="utf-8"), source)
            self.assertEqual(
                captured["command"],
                ["mysql", "-u", "restore-user", "--database", "target_database"],
            )
            environment = cast(dict[str, str], captured["environment"])
            self.assertEqual(environment["MYSQL_PWD"], "secret")
            self.assertEqual(
                captured["input"],
                "USE `target_database`;\nCREATE TABLE example (id int);\n",
            )
            prepared_path = cast(Path, captured["input_path"])
            self.assertFalse(prepared_path.exists())

    def test_restore_database_uses_local_docker_mysql_image_as_fallback(self) -> None:
        runner = CliRunner()

        with runner.isolated_filesystem():
            input_path = Path("backup.sql")
            input_path.write_text("SELECT 1;\n", encoding="utf-8")
            options = MysqlRestoreOptions(
                host="localhost",
                port=3306,
                user="root",
                password="secret",
                input=input_path,
                database="target_database",
            )
            success = CompletedProcess([], 0, "", "")

            with (
                patch("dbtalk.mysql.restore.shutil.which", return_value=None),
                patch(
                    "dbtalk.mysql.restore.docker_mysql_image",
                    return_value=("mysql:8.4", ""),
                ),
                patch(
                    "dbtalk.mysql.restore.run_command",
                    return_value=success,
                ) as run,
                patch("dbtalk.mysql.restore.remove_temporary_container"),
            ):
                restored_input = restore_database(options)

            self.assertEqual(restored_input, input_path.resolve())
            docker_run = run.call_args_list[0].args[0]
            self.assertEqual(docker_run[:5], ["docker", "run", "-i", "--name", ANY])
            self.assertIn("mysql:8.4", docker_run)
            self.assertIn("host.docker.internal", docker_run)
            self.assertIn("target_database", docker_run)
            self.assertNotIn("secret", docker_run)
            self.assertEqual(run.call_args.args[1]["MYSQL_PWD"], "secret")
            self.assertEqual(
                run.call_args.kwargs["input_path"],
                input_path.resolve(),
            )
            self.assertEqual(run.call_count, 1)

    def test_restore_database_reports_missing_execution_path(self) -> None:
        runner = CliRunner()

        with runner.isolated_filesystem():
            input_path = Path("backup.sql")
            input_path.write_text("SELECT 1;\n", encoding="utf-8")
            options = MysqlRestoreOptions(
                host="localhost",
                port=3306,
                user="root",
                password="secret",
                input=input_path,
            )

            message = "mysql is not available. Docker is not installed or is not on PATH."
            with (
                patch("dbtalk.mysql.restore.shutil.which", return_value=None),
                patch(
                    "dbtalk.mysql.restore.docker_mysql_image",
                    return_value=(None, "Docker is not installed or is not on PATH."),
                ),
                self.assertRaisesRegex(
                    click.ClickException,
                    message,
                ),
            ):
                restore_database(options)

    def test_generate_restore_command_quotes_input_path(self) -> None:
        options = MysqlRestoreOptions(
            host="db.example.com",
            port=3307,
            user="backup user",
            password="p@ss word$",
            input=Path("backup file.sql"),
        )

        self.assertEqual(
            generate_restore_command(options),
            "env 'MYSQL_PWD=p@ss word$' mysql -h db.example.com -P 3307 "
            "-u 'backup user' < 'backup file.sql'",
        )

    def test_resolve_restore_options_merges_config_and_overrides(self) -> None:
        config = MySQLRestoreConfig(
            host="db.example.test",
            port=3307,
            user="configured-user",
            password="configured-password",
            database="configured_database",
        )

        options = resolve_restore_options(
            config,
            MysqlRestoreOverrides(
                host=None,
                port=3308,
                user="cli-user",
                password=None,
                input=Path("backup.sql"),
                database=None,
            ),
        )

        self.assertEqual(options.host, "db.example.test")
        self.assertEqual(options.port, 3308)
        self.assertEqual(options.user, "cli-user")
        self.assertEqual(options.password, "configured-password")
        self.assertEqual(options.database, "configured_database")
        self.assertEqual(options.input, Path("backup.sql"))

    def test_cli_restores_input_with_explicit_dsn(self) -> None:
        runner = CliRunner()

        with (
            runner.isolated_filesystem(),
            patch(
                "dbtalk.mysql.cli.restore_database",
                side_effect=lambda options: options.input.resolve(),
            ) as restore,
        ):
            input_path = Path("backup.sql")
            input_path.write_text("SELECT 1;\n", encoding="utf-8")
            result = runner.invoke(
                main_command,
                [
                    "mysql",
                    "restore",
                    "--dsn",
                    "mysql+pymysql://cli-user:configured-password@db.example.test:3307/cli_database",
                    "--input",
                    "backup.sql",
                ],
            )
            options = restore.call_args.args[0]
            restored_path = input_path.resolve()

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            result.output,
            f"MySQL dump restored from {restored_path}\n",
        )
        self.assertEqual(options.host, "db.example.test")
        self.assertEqual(options.port, 3307)
        self.assertEqual(options.user, "cli-user")
        self.assertEqual(options.password, "configured-password")
        self.assertEqual(options.database, "cli_database")
        self.assertEqual(options.input, input_path)

    def test_cli_restore_requires_an_existing_input_file(self) -> None:
        runner = CliRunner()

        with runner.isolated_filesystem():
            result = runner.invoke(
                main_command,
                [
                    "mysql",
                    "restore",
                    "--dsn",
                    "mysql+pymysql://root:secret@localhost/example",
                    "--input",
                    "missing.sql",
                ],
            )

        self.assertEqual(result.exit_code, 2)
        self.assertIn("does not exist", result.output)
