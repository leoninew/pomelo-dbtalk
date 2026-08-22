---
name: dbtalk-database
description: 使用 dbtalk database 或 dbtalk mysql 通过明确 DSN 执行数据库查询、写入、JSONL 传输和 MySQL 原生备份还原。
---

# dbtalk Database

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
uv run dbtalk database query `
  --dsn 'sqlite:///./data/app.db' `
  --timeout 30 `
  --sql 'SELECT id, name FROM users WHERE id = :id' `
  --param id=1 `
  --format json

$env:APP_DSN = 'sqlite:///./data/app.db'
uv run dbtalk database exec `
  --write `
  --dsn-env APP_DSN `
  --timeout 30 `
  --sql 'UPDATE users SET name = :name WHERE id = :id' `
  --param 'name="Ada"' `
  --param id=1
```

`query` 默认输出表格，`--format json` 输出 `columns`、`rows`、`row_count`。它使用数据库只读会话，
不分析 SQL 文本；写入或 DDL 会由数据库拒绝。`exec` 默认使用只读会话，传入 `--write` 或 `-w` 后才
切换为写会话；实际是否为写入由数据库判断。参数格式为可重复的 `NAME=JSON_VALUE`，两条命令都只执行
一条 SQL。

`--timeout` / `-t` 以秒限制单条 query/exec，只接受正整数。省略时使用
`database.operation_timeout_seconds` 配置（默认 30），可用
`DBTALK_DATABASE__OPERATION_TIMEOUT_SECONDS` 覆盖。不要为超时而改写 SQL；SQLite、PostgreSQL 和
MySQL 分别使用其原生会话或驱动机制。MySQL 写入超时后不保证非事务性语句或隐式提交 DDL 的完整回滚。

## JSONL Transfer

```powershell
$env:SOURCE_DSN = 'postgresql+psycopg://user:password@host:5432/source_db'
uv run dbtalk database export `
  --source postgresql `
  --dsn-env SOURCE_DSN `
  --output .\data\source.jsonl

uv run dbtalk database import `
  --target postgresql `
  --dsn 'postgresql+psycopg://user:password@host:5432/target_db' `
  --input .\data\source.jsonl `
  --mode upsert
```

SQLite、MySQL、PostgreSQL 的 export/import 均通过 SQLAlchemy Core adapter 执行；不要根据数据库类型
切换到另一套 transfer API。目标 schema 必须预先存在，`upsert` 需要完整主键，工具不会创建 schema。

## MySQL Backup / Restore

原生 `mysqldump`/`mysql` 仍由 `dbtalk mysql` 执行，但连接同样只能通过 DSN 或 DSN 环境变量提供：

```powershell
uv run dbtalk mysql dump `
  --dsn 'mysql+pymysql://user:password@host:3306/database' `
  --output .\data\backup.sql

uv run dbtalk mysql restore `
  --dsn-env SOURCE_DSN `
  --input .\data\backup.sql
```

不要在命令行、skill、日志或 JSONL 制品中暴露真实密码。`dump`/`restore` 不接受 host、port、user、
password、database 分散参数，也不接受 Go 风格 DSN。
