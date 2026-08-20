---
name: dbtalk-database
description: 使用 db-talk database 或 db-talk mysql 通过明确 DSN 执行数据库查询、写入、JSONL 传输和 MySQL 原生备份还原。
---

# db-talk Database

所有数据库命令都必须接收一个完整 DSN，或接收 `--dsn-env NAME` 从环境变量读取 DSN；二者不能同时
提供，也不能省略。不要使用 `sqlite-file`、`--sqlite-path`、`--mysql-dsn-env` 或无 driver 的 DSN。

支持的 canonical DSN：

```text
sqlite:///./data/app.db
mysql+pymysql://user:password@host:3306/database
postgresql+psycopg://user:password@host:5432/database
```

异步 Python API 使用对应的 `sqlite+aiosqlite`、`mysql+asyncmy` 和 `postgresql+psycopg` driver。CLI
使用同步执行路径。

## Query / Exec

```powershell
uv run db-talk database query `
  --dsn 'sqlite:///./data/app.db' `
  --sql 'SELECT id, name FROM users WHERE id = :id' `
  --param id=1 `
  --format json

$env:APP_DSN = 'sqlite:///./data/app.db'
uv run db-talk database exec `
  --dsn-env APP_DSN `
  --sql 'UPDATE users SET name = :name WHERE id = :id' `
  --param 'name="Ada"' `
  --param id=1
```

`query` 默认输出表格，`--format json` 输出 `columns`、`rows`、`row_count`。`exec` 可能修改或删除
数据。参数格式为可重复的 `NAME=JSON_VALUE`，只执行一条 SQL。

## JSONL Transfer

```powershell
$env:SOURCE_DSN = 'postgresql+psycopg://user:password@host:5432/source_db'
uv run db-talk database export `
  --source postgresql `
  --dsn-env SOURCE_DSN `
  --output .\data\source.jsonl

uv run db-talk database import `
  --target postgresql `
  --dsn 'postgresql+psycopg://user:password@host:5432/target_db' `
  --input .\data\source.jsonl `
  --mode upsert
```

SQLite、MySQL、PostgreSQL 的 export/import 均通过 SQLAlchemy Core adapter 执行；不要根据数据库类型
切换到另一套 transfer API。目标 schema 必须预先存在，`upsert` 需要完整主键，工具不会创建 schema。

## MySQL Backup / Restore

原生 `mysqldump`/`mysql` 仍由 `db-talk mysql` 执行，但连接同样只能通过 DSN 或 DSN 环境变量提供：

```powershell
uv run db-talk mysql dump `
  --dsn 'mysql+pymysql://user:password@host:3306/database' `
  --output .\data\backup.sql

uv run db-talk mysql restore `
  --dsn-env SOURCE_DSN `
  --input .\data\backup.sql
```

不要在命令行、skill、日志或 JSONL 制品中暴露真实密码。`dump`/`restore` 不接受 host、port、user、
password、database 分散参数，也不接受 Go 风格 DSN。
