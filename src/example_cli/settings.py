"""Dynaconf configuration loading for the CLI process."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dynaconf import Dynaconf

ENV_PREFIX = "EXAMPLE_CLI"
ENV_SELECTOR = f"{ENV_PREFIX}_ENVKEY"


@dataclass(frozen=True)
class AppSettings:
    """Application settings consumed by command modules."""

    name: str
    greeting_prefix: str


@dataclass(frozen=True)
class LoggingSettings:
    """Logging settings consumed during CLI initialization."""

    level: str
    format: str


@dataclass(frozen=True)
class Settings:
    """Runtime settings consumed by the CLI process."""

    app: AppSettings
    logging: LoggingSettings


def load_settings(project_root: Path | None = None) -> Settings:
    """Load YAML and the selected dotenv file with Dynaconf precedence."""
    root = (project_root or Path.cwd()).resolve()
    environment = os.environ.get(ENV_SELECTOR)
    dotenv_path = root / f".env.{environment}" if environment else None
    config = Dynaconf(
        settings_files=[str(root / "example-cli.yaml")],
        envvar_prefix=ENV_PREFIX,
        load_dotenv=dotenv_path is not None,
        dotenv_path=str(dotenv_path) if dotenv_path else None,
        environments=False,
    )
    app = config.get("app")
    logging = config.get("logging")
    return Settings(
        app=AppSettings(
            name=app["name"],
            greeting_prefix=app["greeting_prefix"],
        ),
        logging=LoggingSettings(
            level=logging["level"],
            format=logging["format"],
        ),
    )
