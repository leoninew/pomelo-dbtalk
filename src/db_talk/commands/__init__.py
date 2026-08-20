"""Database command groups registered by the root CLI."""

from db_talk.commands.database import database
from db_talk.commands.mysql import mysql

__all__ = ["database", "mysql"]
