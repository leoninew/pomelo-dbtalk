from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPOSITORY_ROOT / "plugins" / "dbtalk"


def load_release_module() -> Any:
    script = REPOSITORY_ROOT / "scripts" / "release.py"
    spec = importlib.util.spec_from_file_location("dbtalk_release", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return cast(dict[str, Any], data)


def plugin_source(entry: dict[str, Any]) -> str:
    source = entry["source"]
    if isinstance(source, str):
        return source
    path = source["path"]
    assert isinstance(path, str)
    return path


def test_host_manifests_reference_the_shared_skills() -> None:
    codex_manifest = load_json(PLUGIN_ROOT / ".codex-plugin" / "plugin.json")
    claude_manifest = load_json(PLUGIN_ROOT / ".claude-plugin" / "plugin.json")

    assert codex_manifest["name"] == "dbtalk"
    assert codex_manifest["version"].startswith("0.1.0+codex.")
    assert codex_manifest["skills"] == "./skills/"
    assert claude_manifest["name"] == "dbtalk"
    assert claude_manifest["version"] == "0.1.0"


def test_host_marketplaces_reference_the_plugin_root() -> None:
    codex_marketplace = load_json(REPOSITORY_ROOT / ".agents" / "plugins" / "marketplace.json")
    claude_marketplace = load_json(REPOSITORY_ROOT / ".claude-plugin" / "marketplace.json")

    assert codex_marketplace["name"] == "dbtalk-local"
    assert claude_marketplace["name"] == "dbtalk-local"
    assert any(
        entry["name"] == "dbtalk" and plugin_source(entry) == "./plugins/dbtalk"
        for entry in codex_marketplace["plugins"]
    )
    assert any(
        entry["name"] == "dbtalk" and plugin_source(entry) == "./plugins/dbtalk"
        for entry in claude_marketplace["plugins"]
    )


def test_shared_skills_use_the_released_cli() -> None:
    skill_paths = tuple(sorted((PLUGIN_ROOT / "skills").glob("*/SKILL.md")))

    assert len(skill_paths) == 3
    assert not (REPOSITORY_ROOT / "skills").exists()
    for skill_path in skill_paths:
        contents = skill_path.read_text(encoding="utf-8")
        assert "uv run dbtalk" not in contents
        assert "dbtalk" in contents
        frontmatter = contents.split("---", 2)[1]
        name_line = next(line for line in frontmatter.splitlines() if line.startswith("name:"))
        assert name_line.split(":", 1)[1].strip() == skill_path.parent.name


def test_release_configuration_is_local_and_native_plugin_only() -> None:
    release = load_release_module()
    config = release.configured_release()

    assert config.skill is None
    assert config.plugin is not None
    assert config.plugin.plugin_name == "dbtalk"
    assert config.plugin.package == PLUGIN_ROOT
    assert config.plugin.marketplaces["claude"].name == "dbtalk-local"
    assert config.plugin.marketplaces["codex"].name == "dbtalk-local"

    source = (REPOSITORY_ROOT / "scripts" / "release.py").read_text(encoding="utf-8")
    assert "plugin_release" not in source
    assert "release_config" not in source
    assert not (REPOSITORY_ROOT / "scripts" / "release_config.py").exists()


def test_install_installs_editably_between_preflight_and_apply() -> None:
    makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")
    install_target = makefile[makefile.index("install: ##") : makefile.index("check: ##")]

    assert "pip install" not in install_target
    assert install_target.index(
        "$(UV) run python scripts/release.py plugin check"
    ) < install_target.index("$(UV) tool install --editable . --force")
    assert install_target.index("$(UV) tool install --editable . --force") < install_target.index(
        "$(UV) run python scripts/release.py plugin apply"
    )


def test_release_only_builds_distribution_artifacts() -> None:
    makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")
    release_target = makefile[makefile.index("release: ##") : makefile.index("docker-build:")]

    assert "$(UV) build" in release_target
    assert "plugin" not in release_target
    assert "tool install" not in release_target
