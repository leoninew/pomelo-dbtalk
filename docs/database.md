# 数据库传输手册

`dbtalk database` 用 JSONL 在既有 SQLite 与 MySQL schema 之间传输表数据。它不会创建数据库、表、索引、视图、触发器、用户、权限或迁移。MySQL 原生 SQL 备份与还原请使用 [`dbtalk mysql`](mysql.md)。

```powershell
uv run dbtalk database --help
uv run dbtalk database export --help
uv run dbtalk database import --help
```

## 连接与制品

使用 `--source` 或 `--target` 选择源端或目标端：

| 驱动 | 必需连接选项 |
| --- | --- |
| SQLite | `--sqlite-path PATH` |
| MySQL | `--mysql-dsn-env NAME` |

对 MySQL，`--mysql-dsn-env` 指向保存 DSN 的环境变量，从而避免将凭据写入命令行和传输制品。支持以下格式：

```text
mysql://user:password@host:3306/database
user:password@tcp(host:3306)/database
```

```powershell
$env:SOURCE_MYSQL_DSN = 'mysql://user:password@host:3306/source_db'
uv run dbtalk database export --source mysql --mysql-dsn-env SOURCE_MYSQL_DSN --output .\data\source.jsonl
```

`mysqldump` 与 `mysqlrestore` 配置组不影响本命令。JSONL 制品包含业务数据，应保存至被 Git 忽略的 `data/` 或其他受控目录。

## Export

export 读取选定源 schema，将表元数据和行数据写入一个 JSONL 文件。

```powershell
uv run dbtalk database export --source sqlite --sqlite-path .\source.db

uv run dbtalk database export `
  --source sqlite `
  --sqlite-path .\source.db `
  --output .\data\transfer.jsonl `
  --include-table users `
  --include-table orders `
  --exclude-table audit_log `
  --tz Asia/Shanghai

uv run dbtalk database export `
  --source mysql `
  --mysql-dsn-env SOURCE_MYSQL_DSN `
  --output .\data\transfer.jsonl.gz `
  --archive
```

| 选项 | 说明 |
| --- | --- |
| `--source sqlite|mysql` | 必填的源驱动。 |
| `--output FILE_OR_DIRECTORY` | 可选的 JSONL 输出文件，或已有的输出目录。 |
| `--sqlite-path FILE` | 源端为 SQLite 时必填。 |
| `--mysql-dsn-env NAME` | 源端为 MySQL 时必填。 |
| `--tz IANA_NAME` | 解释无时区日期时间的时区，默认 `UTC`。 |
| `--include-table NAME` | 限定导出的表；可重复指定。 |
| `--exclude-table NAME` | 排除表；可重复指定，且优先于 include。 |
| `--archive` | 写入 gzip 压缩 JSONL；路径没有 `.gz` 后缀时自动追加。 |

默认导出全部源表。未知、为空、包含 NUL 的表名，以及最终为空的表集合都会在传输前失败。表按外键父表到子表顺序写入。只选择子表而未选择所需父表，或遇到外键环时会预检失败；工具不会自动补充表或关闭外键检查。

省略 `--output` 时，dbtalk 创建当前目录的 `data/`，并生成 `<source>-<timestamp>.jsonl`，例如 `sqlite-20260820-153651.jsonl`。传入 `--archive` 时生成 `.jsonl.gz`。显式 `--output` 指向已有目录时，在该目录生成相同的时间戳文件；其他路径一律视为文件路径，父目录必须已经存在。不存在的路径不会被推断为目录或自动创建。

大表导出固定按每批 1000 行循环读取并写入 JSONL 或 JSONL.GZ，不会使用 `fetchall()` 将整表载入内存。

## JSONL 表示

制品包含一个 header 和多个表块。每个表块记录表名、列、声明类型、完整主键、行与行数。BLOB 使用 base64 类型标签，DECIMAL 使用 decimal 类型标签，以便保留 JSON 无法原生表达的类型。

无时区日期时间按 `--tz` 解释，保存到 JSONL 时规范化为 UTC，导入时转换为目标时区。`database.zero_datetime_as_null` 默认 `true`，可在 `dbtalk.yaml` 中配置，也可通过环境变量覆盖：

```env
DBTALK_DATABASE__ZERO_DATETIME_AS_NULL=false
```

MySQL JSONL 导出默认将 `DATE`、`DATETIME`、`TIMESTAMP` 列的完整零日期（`0000-00-00` 或 `0000-00-00 00:00:00[.fraction]`）写为 JSON `null`。这是为兼容 MySQL 历史空白日期的有损规范化；不会处理 `VARCHAR` 等文本列或 `TIME` 列。将 `database.zero_datetime_as_null` 设为 `false`，或设置 `DBTALK_DATABASE__ZERO_DATETIME_AS_NULL=false` 后，遇到这类值会使导出失败。

MySQL 的负 `TIME` 值或超过一天的 `TIME` 值无法表示为可移植的 time-of-day 数据；需要保留这些值时请使用 [`dbtalk mysql`](mysql.md)。

为兼容既有数据库，日期时间解析也接受 Go 风格的 `YYYY-MM-DD HH:MM:SS[.fraction] ±HHMM TZ` 存储格式，并将其规范化为 JSONL 的 UTC ISO 8601 字符串。导入 MySQL 时，目标 `DATETIME`/`TIMESTAMP` 声明的小数秒精度决定写入精度；未声明精度时按 MySQL 默认的 0 位小数秒写入。

## Import

import 将 JSONL 制品写入既有目标 schema。执行前必须确认目标、制品来源及写入授权。

```powershell
uv run dbtalk database import `
  --target sqlite `
  --sqlite-path .\target.db `
  --input .\data\transfer.jsonl `
  --mode upsert

$env:TARGET_MYSQL_DSN = 'mysql://user:password@host:3306/target_db'
uv run dbtalk database import `
  --target mysql `
  --mysql-dsn-env TARGET_MYSQL_DSN `
  --input .\data\transfer.jsonl.gz `
  --mode insert
```

| 选项 | 说明 |
| --- | --- |
| `--target sqlite|mysql` | 必填的目标驱动。 |
| `--input FILE` | 必填的 JSONL 或 gzip 压缩 JSONL 输入文件。 |
| `--mode insert|upsert` | 必填的写入模式。 |
| `--sqlite-path FILE` | 目标端为 SQLite 时必填。 |
| `--mysql-dsn-env NAME` | 目标端为 MySQL 时必填。 |
| `--tz IANA_NAME` | 写入无时区日期时间时使用的时区，默认 `UTC`。 |
| `--include-table NAME` | 限定导入制品中的表；可重复指定。 |
| `--exclude-table NAME` | 排除制品中的表；可重复指定，且优先于 include。 |

写入前，dbtalk 会扫描整个制品，校验结构、表筛选、既有目标表、源列、兼容列类型、完整主键和外键顺序。`upsert` 要求非空的完整主键：命中行按主键更新，不存在的行插入；不会清空表，也不使用 `REPLACE` 或 `DELETE`。

制品会先用于预检，再被重新读取以写入数据；两次读取之间不要替换或截断该文件。每个表块是一个事务：失败表块会回滚，已经提交的先前表块不会自动回滚。SQLite 导入后还会执行完整性和外键检查；两种驱动均不会通过关闭外键检查绕过依赖。

导入完成后，确认 CLI 报告的表数和行数，并按需要抽查目标数据。
