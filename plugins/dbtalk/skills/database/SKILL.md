---
name: dbtalk-database
description: 使用 dbtalk database 以 JSONL 在 SQLite 与 MySQL 之间导出或导入既有表数据。用户要求跨数据库搬运数据、JSONL 传输、严格插入或按主键更新时使用；不用于 mysqldump SQL 备份恢复。
---

# dbtalk Database

使用 `dbtalk database` 在 SQLite 与 MySQL 之间传输既有 schema 中的表数据。JSONL 不创建数据库、表、索引、视图、触发器、权限或迁移；原生 MySQL SQL 备份和恢复使用 `dbtalk mysql`。

先确认可用参数：

```powershell
uv run dbtalk database export --help
uv run dbtalk database import --help
```

## 连接与制品

SQLite 连接由 `--sqlite-path` 指定。MySQL 使用 `--mysql-dsn-env` 指向保存 DSN 的环境变量，避免把密码写入命令行、skill、日志或 JSONL 示例。支持：

```text
mysql://user:password@host:3306/database
user:password@tcp(host:3306)/database
```

例如：

```powershell
$env:SOURCE_MYSQL_DSN = 'mysql://user:password@host:3306/source_db'
uv run dbtalk database export --source mysql --mysql-dsn-env SOURCE_MYSQL_DSN --output .\data\source.jsonl.gz --archive
```

`dbtalk.yaml` 中的 `mysqldump` 与 `mysqlrestore` 配置组不用于本命令。JSONL 制品承载业务数据，应保存到 Git 忽略的 `data/` 或其他受控目录。

## Export

省略 `--output` 时，命令会创建当前目录的 `data/`，并写入 `<source>-<timestamp>.jsonl`；`--archive` 时为 `.jsonl.gz`。`--output` 指向已有目录时，在该目录生成相同的时间戳文件。其他路径按文件处理，父目录必须已经存在；不存在的路径不会被推断为目录或自动创建。

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
```

- 默认导出全部表。`--include-table` 可重复指定集合，随后应用可重复的 `--exclude-table`，且 exclude 优先。
- 未知、空或含 NUL 的表名，以及最终为空的表集合，会在查询前失败。
- 表按外键父表优先顺序导出；未选中的父表依赖或外键环会在预检失败，不自动补齐表，也不关闭外键检查。
- `--archive` 将输出写为 `.jsonl.gz`，没有 `.gz` 后缀时自动追加。
- BLOB 以 base64 type tag、DECIMAL 以 decimal type tag 保存。无偏移日期时间按 `--tz` 解释并规范化为 UTC 的 ISO 8601 `Z`。
- MySQL `TIME` 为负值或不在一天内时无法表示为跨库 time-of-day；这类数据需要保留原生行为时，改用 `dbtalk mysql dump`。

## Import

```powershell
$env:TARGET_MYSQL_DSN = 'mysql://user:password@host:3306/target_db'
uv run dbtalk database import `
  --target mysql `
  --mysql-dsn-env TARGET_MYSQL_DSN `
  --input .\data\transfer.jsonl.gz `
  --mode upsert `
  --exclude-table audit_log `
  --tz UTC
```

在目标连接、既有 schema、导入模式和输入制品来源明确，且用户已授权写入后执行 import。

- 导入前流式预检目标表、列、类型、完整主键、表筛选和外键依赖；任一项不兼容时不写入任何表块。
- `--mode insert` 只执行插入；约束冲突会导致当前表块失败并回滚。
- `--mode upsert` 要求完整主键或联合主键；已存在的行按主键更新，未命中时插入，不清空表，不使用 `REPLACE` 或 `DELETE`。
- 制品会读取两遍：第一遍预检，第二遍重开相同制品并按父表优先顺序写入。两遍之间不要替换或截断输入文件。
- 每个表块是一个事务；失败块会回滚，已提交的前序块不会自动回滚。
- SQLite 导入后执行完整性和外键检查；MySQL 不通过关闭外键检查绕过依赖。

完成后检查 CLI 汇总的表数、行数，并按需要抽查目标表。
