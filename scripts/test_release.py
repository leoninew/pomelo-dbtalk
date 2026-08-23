from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("release.py")
SPEC = importlib.util.spec_from_file_location("multi_client_sync", SCRIPT)
assert SPEC is not None
assert SPEC.loader is not None
sync = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sync
SPEC.loader.exec_module(sync)


class FakeRunner:
    def __init__(self, payloads: dict[tuple[str, tuple[str, ...]], object]) -> None:
        self.payloads = payloads

    def inspect(self, target: object, arguments: tuple[str, ...]) -> object:
        return self.payloads[(target.name, tuple(arguments))]


class PluginSyncTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.config = self._create_plugin_config(self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_missing_asset_or_subcommand_displays_help(self) -> None:
        cases = (
            ((), ("--help",)),
            (("plugin",), ("plugin", "--help")),
            (("skill",), ("skill", "--help")),
        )
        for arguments, help_arguments in cases:
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), *arguments],
                capture_output=True,
                text=True,
                check=False,
            )
            help_completed = subprocess.run(
                [sys.executable, str(SCRIPT), *help_arguments],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(help_completed.returncode, 0, help_completed.stderr)
            self.assertEqual(completed.stdout, help_completed.stdout)

    def test_validates_plugin_and_marketplaces(self) -> None:
        sync.validate_plugin_sources(self.config, sync.CLIENTS)

    def test_automatic_mode_skips_missing_clients(self) -> None:
        targets, outcomes = sync.select_targets(
            self.config,
            sync.CLIENTS,
            explicit=False,
            strict=False,
            find_command=lambda name: name if name == "claude" else None,
        )

        self.assertEqual([target.name for target in targets], ["claude"])
        self.assertEqual([(outcome.client, outcome.status) for outcome in outcomes], [("codex", "skipped"), ("grok", "skipped")])

    def test_explicit_targets_fail_before_writes_when_a_client_is_missing(self) -> None:
        with self.assertRaisesRegex(sync.SyncError, "required client commands"):
            sync.select_targets(
                self.config,
                sync.CLIENTS,
                explicit=True,
                strict=False,
                find_command=lambda name: name if name == "claude" else None,
            )

    def test_plans_exact_native_operations(self) -> None:
        claude = sync.ClientTarget("claude", "claude")
        codex = sync.ClientTarget("codex", "codex")
        grok = sync.ClientTarget("grok", "grok")
        runner = FakeRunner(
            {
                ("claude", ("plugin", "marketplace", "list", "--json")): [],
                ("claude", ("plugin", "list", "--json")): [],
                ("codex", ("plugin", "marketplace", "list", "--json")): {"marketplaces": []},
                ("grok", ("plugin", "list", "--json")): [{"name": "example-plugin-extra"}],
            }
        )

        claude_plan = sync.plan_plugin(self.config, claude, runner)
        codex_plan = sync.plan_plugin(self.config, codex, runner)
        grok_plan = sync.plan_plugin(self.config, grok, runner)

        self.assertEqual(
            [command.arguments for command in claude_plan.commands],
            [
                ("plugin", "marketplace", "add", str(self.root), "--scope", "user"),
                ("plugin", "install", "example-plugin@example-plugin-local", "--scope", "user"),
            ],
        )
        self.assertEqual(
            [command.arguments for command in codex_plan.commands],
            [
                ("plugin", "marketplace", "add", str(self.root), "--json"),
                ("plugin", "add", "example-plugin@example-plugin-local", "--json"),
            ],
        )
        self.assertEqual(
            grok_plan.commands[0].arguments,
            ("plugin", "install", str(self.root / "plugins" / "example-plugin"), "--trust"),
        )

    def test_removal_uses_exact_plugin_identity(self) -> None:
        runner = FakeRunner(
            {
                ("claude", ("plugin", "list", "--json")): [{"id": "example-plugin@example-plugin-local"}],
                ("codex", ("plugin", "list", "--json")): {"installed": [{"name": "example-plugin", "marketplaceName": "example-plugin-local"}]},
                ("grok", ("plugin", "list", "--json")): [{"name": "example-plugin-extra"}],
            }
        )

        claude_plan = sync.plan_plugin_removal(self.config, sync.ClientTarget("claude", "claude"), runner)
        codex_plan = sync.plan_plugin_removal(self.config, sync.ClientTarget("codex", "codex"), runner)
        grok_plan = sync.plan_plugin_removal(self.config, sync.ClientTarget("grok", "grok"), runner)

        self.assertEqual(claude_plan.commands[0].arguments, ("plugin", "uninstall", "example-plugin@example-plugin-local", "--scope", "user"))
        self.assertEqual(codex_plan.commands[0].arguments, ("plugin", "remove", "example-plugin@example-plugin-local", "--json"))
        self.assertEqual(grok_plan.commands, ())

    def test_reinstalls_grok_plugin_when_the_source_changes(self) -> None:
        runner = FakeRunner(
            {
                ("grok", ("plugin", "list", "--json")): [
                    {"name": "example-plugin", "source": str(self.root)}
                ]
            }
        )

        plan = sync.plan_plugin(self.config, sync.ClientTarget("grok", "grok"), runner)

        self.assertEqual(
            [command.arguments for command in plan.commands],
            [
                ("plugin", "uninstall", "example-plugin", "--confirm"),
                ("plugin", "install", str(self.root / "plugins" / "example-plugin"), "--trust"),
            ],
        )

    def _create_plugin_config(self, root: Path) -> object:
        package = root / "plugins" / "example-plugin"
        (package / ".claude-plugin").mkdir(parents=True)
        (package / ".codex-plugin").mkdir()
        (package / "skills" / "example-skill").mkdir(parents=True)
        (package / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "example-plugin"}), encoding="utf-8")
        (package / ".codex-plugin" / "plugin.json").write_text(json.dumps({"name": "example-plugin", "skills": "./skills/"}), encoding="utf-8")
        (package / "skills" / "example-skill" / "SKILL.md").write_text("---\nname: example-skill\ndescription: Example.\n---\n", encoding="utf-8")
        (root / ".claude-plugin").mkdir()
        (root / ".agents" / "plugins").mkdir(parents=True)
        (root / ".claude-plugin" / "marketplace.json").write_text(json.dumps({"name": "example-plugin-local", "plugins": [{"name": "example-plugin", "source": "./plugins/example-plugin"}]}), encoding="utf-8")
        (root / ".agents" / "plugins" / "marketplace.json").write_text(json.dumps({"name": "example-plugin-local", "plugins": [{"name": "example-plugin", "source": {"source": "local", "path": "./plugins/example-plugin"}}]}), encoding="utf-8")
        marketplace = sync.Marketplace("example-plugin-local", root)
        return sync.PluginConfig(root, "example-plugin", package, {"claude": marketplace, "codex": marketplace}, {client: client for client in sync.CLIENTS})


class StandaloneSkillSyncTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.home_patch = patch.object(sync.Path, "home", return_value=self.root)
        self.home_patch.start()
        source = self.root / "source" / "example-skill"
        source.mkdir(parents=True)
        (source / "SKILL.md").write_text("---\nname: example-skill\ndescription: Example.\n---\n", encoding="utf-8")
        self.config = sync.SkillConfig("example-skill", source, {client: client for client in sync.CLIENTS})

    def tearDown(self) -> None:
        self.home_patch.stop()
        self.temp_dir.cleanup()

    def test_publishes_and_removes_only_the_skill_leaf(self) -> None:
        sync.validate_skill_source(self.config)
        target = sync.ClientTarget("codex", "codex")
        other_skill = self.root / ".codex" / "skills" / "other-skill"
        other_skill.mkdir(parents=True)
        (other_skill / "SKILL.md").write_text("other", encoding="utf-8")

        result = sync.apply_skill(self.config, target, dry_run=False)
        destination = sync.skill_target(self.config, "codex")
        self.assertEqual(result.status, "completed")
        self.assertTrue((destination / "SKILL.md").is_file())
        self.assertTrue((other_skill / "SKILL.md").is_file())

        removal = sync.remove_skill(self.config, target, dry_run=False)
        self.assertEqual(removal.status, "removed")
        self.assertFalse(destination.exists())
        self.assertTrue((other_skill / "SKILL.md").is_file())

    def test_dry_run_does_not_create_a_home(self) -> None:
        result = sync.apply_skill(self.config, sync.ClientTarget("grok", "grok"), dry_run=True)
        self.assertEqual(result.status, "planned")
        self.assertFalse((self.root / ".grok").exists())

    def test_automatic_mode_skips_missing_clients(self) -> None:
        targets, outcomes = sync.select_targets(
            self.config,
            sync.CLIENTS,
            explicit=False,
            strict=False,
            find_command=lambda name: name if name == "claude" else None,
        )
        self.assertEqual([target.name for target in targets], ["claude"])
        self.assertEqual([(outcome.client, outcome.status) for outcome in outcomes], [("codex", "skipped"), ("grok", "skipped")])


if __name__ == "__main__":
    unittest.main()
