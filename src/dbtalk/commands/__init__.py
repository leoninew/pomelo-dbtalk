"""Database command groups registered by the root CLI."""

from dbtalk.commands.database import database
from dbtalk.commands.mysql import mysql

__all__ = ["database", "mysql"]
