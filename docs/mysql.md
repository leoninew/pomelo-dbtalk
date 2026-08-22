# MySQL 手册

`dbtalk mysql` 用于创建 MySQL 原生 SQL dump，以及还原 `.sql` 或 `.sql.gz` 文件。连接入口与其他
数据库命令一致：`dump` 和 `restore` 都必须接受且只接受一个 `--dsn DSN` 或 `--dsn-env NAME`。

```powershell
uv run dbtalk mysql --help
uv run dbtalk mysql dump --help
uv run dbtalk mysql restore --help
```

## DSN

MySQL backup/restore 只接受明确的 `mysql+pymysql://` DSN：

```powershell
uv run dbtalk mysql dump `
  --dsn 'mysql+pymysql://user:password@host:3306/app' `
  --output .\data\app.sql

$env:APP_DSN = 'mysql+pymysql://user:password@host:3306/app'
uv run dbtalk mysql restore `
  --dsn-env APP_DSN `
  --input .\data\app.sql.gz
```

`mysql://`、`postgresql://`、`postgres://`、Go 风格 DSN 和 host/user/password/database 分散参数都
不是 canonical DSN。完整 DSN 可能包含密码；脚本中优先使用 `--dsn-env`。密码只通过 `MYSQL_PWD`
传递给原生客户端，正常输出不会回显密码。

## Dump

```powershell
uv run dbtalk mysql dump `
  --dsn 'mysql+pymysql://user:password@host:3306/app' `
  --output .\data\app.sql `
  --create-database `
  --drop-database `
  --archive
```

| 选项 | 说明 |
| --- | --- |
| `--dsn DSN` / `--dsn-env NAME` | 必须二选一的 MySQL DSN。 |
| `--output FILE_OR_DIRECTORY` | SQL 制品输出文件或已有输出目录。 |
| `--create-database` / `--no-create-database` | 包含或省略 `CREATE DATABASE`。 |
| `--drop-database` / `--no-drop-database` | 包含或省略 `DROP DATABASE`。 |
| `--archive` | 写入 gzip 压缩 dump。 |

省略 `--output` 时使用配置中的 `mysqldump.output_directory`（默认 `data/`），生成
`<database>-<timestamp>.sql`。显式输出目录必须已经存在。

## Restore

```powershell
uv run dbtalk mysql restore `
  --dsn 'mysql+pymysql://user:password@host:3306/app' `
  --input .\data\app.sql.gz
```

| 选项 | 说明 |
| --- | --- |
| `--dsn DSN` / `--dsn-env NAME` | 必须二选一的 MySQL DSN；数据库名来自 DSN。 |
| `--input FILE` | 必填的 SQL 或 gzip 压缩 SQL 输入文件。 |

目标数据库必须已经存在，除非 SQL 文件本身创建它。还原可能覆盖或删除现有数据，执行前确认目标
连接、输入来源和写入授权。

## 客户端与故障处理

`dbtalk` 优先使用本机 `mysqldump` 或 `mysql` 可执行文件。缺失时才使用本机已有的 Docker `mysql` 镜像；
不会安装客户端、拉取镜像、创建数据库或自动重试。
