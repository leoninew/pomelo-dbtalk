"""Synchronous and asynchronous SQLAlchemy database clients."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager

from sqlalchemy import text
from sqlalchemy.engine import URL, Connection, Engine, create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from .dsn import ParsedDsn, parse_dsn
from .models import DatabaseOperationError, ExecutionResult, QueryResult


class DatabaseSession:
    """A transaction-aware wrapper around one synchronous SQLAlchemy connection."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def query(self, statement: str, parameters: Mapping[str, object] | None = None) -> QueryResult:
        try:
            result = self._connection.execute(text(statement), dict(parameters or {}))
            columns = tuple(str(key) for key in result.keys())  # noqa: SIM118
            rows = tuple(tuple(row) for row in result.fetchall())
        except SQLAlchemyError as error:
            raise DatabaseOperationError("database query failed") from error
        return QueryResult(columns=columns, rows=rows)

    def execute(
        self, statement: str, parameters: Mapping[str, object] | None = None
    ) -> ExecutionResult:
        try:
            result = self._connection.execute(text(statement), dict(parameters or {}))
        except SQLAlchemyError as error:
            raise DatabaseOperationError("database execution failed") from error
        return ExecutionResult(row_count=max(result.rowcount, 0))


class DatabaseClient:
    """Public synchronous database API backed by a SQLAlchemy engine."""

    def __init__(self, dsn: str | URL | ParsedDsn) -> None:
        parsed = dsn if isinstance(dsn, ParsedDsn) else parse_dsn(_dsn_string(dsn))
        if parsed.async_mode:
            raise DatabaseOperationError("an async DSN cannot create a sync client")
        self.dsn = parsed
        try:
            self._engine: Engine = create_engine(parsed.url)
        except SQLAlchemyError as error:
            raise DatabaseOperationError("database engine could not be created") from error

    @property
    def dialect(self) -> str:
        return self.dsn.dialect

    @contextmanager
    def connect(self) -> Iterator[DatabaseSession]:
        try:
            with self._engine.connect() as connection:
                yield DatabaseSession(connection)
        except DatabaseOperationError:
            raise
        except SQLAlchemyError as error:
            raise DatabaseOperationError("database connection failed") from error

    @contextmanager
    def transaction(self) -> Iterator[DatabaseSession]:
        try:
            with self._engine.begin() as connection:
                yield DatabaseSession(connection)
        except DatabaseOperationError:
            raise
        except SQLAlchemyError as error:
            raise DatabaseOperationError("database transaction failed") from error

    def query(self, statement: str, parameters: Mapping[str, object] | None = None) -> QueryResult:
        with self.connect() as session:
            return session.query(statement, parameters)

    def execute(
        self, statement: str, parameters: Mapping[str, object] | None = None
    ) -> ExecutionResult:
        with self.transaction() as session:
            return session.execute(statement, parameters)

    def close(self) -> None:
        self._engine.dispose()

    def __enter__(self) -> DatabaseClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class AsyncDatabaseSession:
    """A transaction-aware wrapper around one asynchronous SQLAlchemy connection."""

    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    async def query(
        self, statement: str, parameters: Mapping[str, object] | None = None
    ) -> QueryResult:
        try:
            result = await self._connection.execute(text(statement), dict(parameters or {}))
            columns = tuple(str(key) for key in result.keys())  # noqa: SIM118
            rows = tuple(tuple(row) for row in result.fetchall())
        except SQLAlchemyError as error:
            raise DatabaseOperationError("database query failed") from error
        return QueryResult(columns=columns, rows=rows)

    async def execute(
        self, statement: str, parameters: Mapping[str, object] | None = None
    ) -> ExecutionResult:
        try:
            result = await self._connection.execute(text(statement), dict(parameters or {}))
        except SQLAlchemyError as error:
            raise DatabaseOperationError("database execution failed") from error
        return ExecutionResult(row_count=max(result.rowcount, 0))


class AsyncDatabaseClient:
    """Public asynchronous database API backed by a SQLAlchemy async engine."""

    def __init__(self, dsn: str | URL | ParsedDsn) -> None:
        parsed = dsn if isinstance(dsn, ParsedDsn) else parse_dsn(_dsn_string(dsn), async_mode=True)
        if not parsed.async_mode:
            raise DatabaseOperationError("an async client requires an async DSN")
        self.dsn = parsed
        try:
            self._engine: AsyncEngine = create_async_engine(parsed.url)
        except SQLAlchemyError as error:
            raise DatabaseOperationError("async database engine could not be created") from error

    @property
    def dialect(self) -> str:
        return self.dsn.dialect

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[AsyncDatabaseSession]:
        try:
            async with self._engine.connect() as connection:
                yield AsyncDatabaseSession(connection)
        except DatabaseOperationError:
            raise
        except SQLAlchemyError as error:
            raise DatabaseOperationError("database connection failed") from error

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncDatabaseSession]:
        try:
            async with self._engine.begin() as connection:
                yield AsyncDatabaseSession(connection)
        except DatabaseOperationError:
            raise
        except SQLAlchemyError as error:
            raise DatabaseOperationError("database transaction failed") from error

    async def query(
        self, statement: str, parameters: Mapping[str, object] | None = None
    ) -> QueryResult:
        async with self.connect() as session:
            return await session.query(statement, parameters)

    async def execute(
        self, statement: str, parameters: Mapping[str, object] | None = None
    ) -> ExecutionResult:
        async with self.transaction() as session:
            return await session.execute(statement, parameters)

    async def close(self) -> None:
        await self._engine.dispose()

    async def __aenter__(self) -> AsyncDatabaseClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()


def create_client(dsn: str | URL) -> DatabaseClient:
    """Create the public sync client from a DSN."""

    return DatabaseClient(dsn)


def create_async_client(dsn: str | URL) -> AsyncDatabaseClient:
    """Create the public async client from a DSN."""

    return AsyncDatabaseClient(dsn)


def _dsn_string(dsn: str | URL) -> str:
    if isinstance(dsn, URL):
        return dsn.render_as_string(hide_password=False)
    return dsn


__all__ = [
    "AsyncDatabaseClient",
    "AsyncDatabaseSession",
    "DatabaseClient",
    "DatabaseSession",
    "create_async_client",
    "create_client",
]
