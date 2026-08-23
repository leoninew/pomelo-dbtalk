"""Database command groups registered by the root CLI."""

from dbtalk.commands.database import database
from dbtalk.commands.mysql import mysql
from dbtalk.commands.postgres import postgres

__all__ = ["database", "mysql", "postgres"]
