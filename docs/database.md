# 数据库操作手册

`dbtalk database` 提供通用 SQL `query`/`exec`，并用 JSONL 在既有 SQLite、MySQL 与 PostgreSQL schema
之间传输表数据。所有连接入口都使用一个明确的 SQLAlchemy 2.x DSN：命令接受二选一的 `--dsn DSN`
或 `--dsn-env NAME`，Python API 接受 DSN 字符串或环境变量名。不会根据数据库类型猜测 driver。

```powershell
uv run dbtalk database --help
uv run dbtalk database export --help
uv run dbtalk database import --help
uv run dbtalk database query --help
uv run dbtalk database exec --help
```

## DSN 约定

支持的 DSN 必须使用以下明确形式：

```text
sqlite:///./data/app.db
sqlite:////absolute/path/app.db
mysql+pymysql://user:password@host:3306/app
mysql+asyncmy://user:password@host:3306/app
postgresql+psycopg://user:password@host:5432/app
```

`mysql://`、`postgres://`、`postgresql://`、Go 风格 `user:password@tcp(...)` 和数据库类型专用文件
参数都不属于 canonical DSN，命令会拒绝。密码可放在环境变量中，避免出现在进程参数中。

## Query / Exec

SQL 使用 SQLAlchemy named bind 参数。参数格式为可重复的 `NAME=JSON_VALUE`，字符串需要使用 JSON
字符串表示：

```powershell
uv run dbtalk database query `
  --dsn 'sqlite:///./data/app.db' `
  --sql 'SELECT id, name FROM users WHERE id = :id' `
  --param id=1 `
  --format table

$env:APP_DSN = 'sqlite:///./data/app.db'
uv run dbtalk database query `
  --dsn-env APP_DSN `
  --sql 'SELECT id, name FROM users WHERE id = :id' `
  --param id=1 `
  --format json

uv run dbtalk database exec `
  --dsn-env APP_DSN `
  --sql 'UPDATE users SET name = :name WHERE id = :id' `
  --param 'name="Ada"' `
  --param id=1
```

`query` 默认输出 `table`，也可使用 `--format json`。JSON 输出包含 `columns`、`rows` 和 `row_count`；
日期时间、Decimal 和 BLOB 会转换为 JSON-safe 值。`exec` 输出影响行数。两条命令只执行一条 SQL，
`exec` 可能修改或删除数据。

同步 Python API 为 `DatabaseClient`，异步 API 为 `AsyncDatabaseClient`；异步 API 会按 async driver
建立 SQLAlchemy async engine，不向调用方暴露原生 DBAPI 连接。

## Export

export 读取选定源 schema，将表元数据和行数据写入一个 JSONL 文件：

```powershell
uv run dbtalk database export `
  --source sqlite `
  --dsn 'sqlite:///./source.db' `
  --output .\data\transfer.jsonl `
  --include-table users `
  --exclude-table audit_log

$env:SOURCE_PG_DSN = 'postgresql+psycopg://user:password@host:5432/source_db'
uv run dbtalk database export `
  --source postgresql `
  --dsn-env SOURCE_PG_DSN `
  --output .\data\transfer.jsonl
```

| 选项 | 说明 |
| --- | --- |
| `--source sqlite|mysql|postgresql` | 必填，必须与 DSN dialect 一致。 |
| `--dsn DSN` / `--dsn-env NAME` | 必须二选一。 |
| `--output FILE_OR_DIRECTORY` | 可选的 JSONL 输出文件，或已有的输出目录。 |
| `--tz IANA_NAME` | 无时区日期时间的解释时区，默认 `UTC`。 |
| `--include-table NAME` | 限定导出的表，可重复指定。 |
| `--exclude-table NAME` | 排除表，可重复指定。 |
| `--archive` | 写入 gzip 压缩 JSONL。 |

表按外键父表到子表顺序写入。只选择子表而未选择所需父表，或遇到外键环时会预检失败；工具不会
自动创建 schema、补充表或关闭外键检查。大表固定按每批 1000 行循环读取，不使用 `fetchall()`。

省略 `--output` 时创建当前目录的 `data/` 并生成 `<source>-<timestamp>.jsonl`。传入 `--archive` 时
生成 `.jsonl.gz`。显式 `--output` 指向已有目录时，在该目录生成时间戳文件；其他路径视为文件路径，
父目录必须已经存在。

## Import

import 将 JSONL 制品写入既有目标 schema：

```powershell
uv run dbtalk database import `
  --target sqlite `
  --dsn 'sqlite:///./target.db' `
  --input .\data\transfer.jsonl `
  --mode upsert

$env:TARGET_MYSQL_DSN = 'mysql+pymysql://user:password@host:3306/target_db'
uv run dbtalk database import `
  --target mysql `
  --dsn-env TARGET_MYSQL_DSN `
  --input .\data\transfer.jsonl.gz `
  --mode insert
```

| 选项 | 说明 |
| --- | --- |
| `--target sqlite|mysql|postgresql` | 必填，必须与 DSN dialect 一致。 |
| `--dsn DSN` / `--dsn-env NAME` | 必须二选一。 |
| `--input FILE` | 必填的 JSONL 或 gzip JSONL 输入文件。 |
| `--mode insert|upsert` | 必填的写入模式。 |
| `--tz IANA_NAME` | 写入无时区日期时间时的时区，默认 `UTC`。 |
| `--include-table NAME` | 限定导入表，可重复指定。 |
| `--exclude-table NAME` | 排除表，可重复指定。 |

写入前会扫描整个制品，校验结构、目标表、列类型、完整主键和外键顺序。`upsert` 命中主键时更新，
未命中时插入；不会清空表，也不使用 `REPLACE` 或 `DELETE`。每个表块是一个事务，失败表块回滚，
已提交的前序表块不会自动回滚。SQLite 导入后还会执行完整性和外键检查。

## JSONL 类型

BLOB 使用 base64 type tag，DECIMAL 使用 decimal type tag。无时区日期时间按 `--tz` 解释并规范化为
UTC ISO 8601 字符串。MySQL 零日期可由 `database.zero_datetime_as_null` 默认转换为 JSON `null`；
设为 `false` 时遇到零日期会失败。PostgreSQL 普通表、主键、外键、常见类型和 JSONL transfer 由
SQLAlchemy Inspector 和对应 dialect 处理。
