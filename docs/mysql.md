# MySQL 手册

`dbtalk mysql` 用于管理 MySQL 数据库，以及创建和还原原生 SQL dump。每个子命令都必须接受且只接受一个
`--dsn DSN` 或 `--dsn-env NAME`。

```powershell
uv run dbtalk mysql --help
uv run dbtalk mysql database --help
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

## Database management

`database` 子命令只管理 MySQL 数据库本身，不执行任意 SQL、不管理账号，也不替代 dump/restore。DSN 必须
指向实例中一个已存在且可连接的管理库，所用账号需要相应的 MySQL 数据库管理权限。

```powershell
$env:MYSQL_MANAGEMENT_DSN = 'mysql+pymysql://operator:password@db.example.com:3306/mysql'

uv run dbtalk mysql database list --dsn-env MYSQL_MANAGEMENT_DSN
uv run dbtalk mysql database create --dsn-env MYSQL_MANAGEMENT_DSN --name app_db
uv run dbtalk mysql database drop --dsn-env MYSQL_MANAGEMENT_DSN --name app_db --yes
```

`list` 输出可见数据库名。`create` 使用服务端默认创建属性。`drop` 是不可逆操作，必须显式提供 `--yes`；
失败时命令只报告动作失败，不会输出 DSN 密码。MySQL 的名称、权限和 DDL 行为由服务器决定，执行前确认
目标名称和连接账号。

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
