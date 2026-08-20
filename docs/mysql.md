# MySQL 手册

`dbtalk mysql` 用于创建 MySQL 原生 SQL dump，以及还原 `.sql` 或 `.sql.gz` 文件。需要在 SQLite 与 MySQL 间做数据级 JSONL 传输时，请使用 [`dbtalk database`](database.md)。

```powershell
uv run dbtalk mysql --help
uv run dbtalk mysql dump --help
uv run dbtalk mysql restore --help
```

## 配置

命令从项目根目录的 [`dbtalk.yaml`](../dbtalk.yaml) 读取默认值。设置 `DBTALK_ENVKEY=local` 后，会加载项目根目录的 `.env.local`；其中 `DBTALK_*` 值覆盖 YAML。CLI 选项优先级最高。

`dump` 和 `restore` 使用独立配置组。应将凭据放入 `.env.local` 或进程环境变量，不要写入命令行或提交到仓库。

```env
DBTALK_MYSQLDUMP__HOST=localhost
DBTALK_MYSQLDUMP__PORT=3306
DBTALK_MYSQLDUMP__USER=
DBTALK_MYSQLDUMP__PASSWORD=
DBTALK_MYSQLDUMP__DATABASE=
DBTALK_MYSQLDUMP__CREATE_DATABASE=false
DBTALK_MYSQLDUMP__DROP_DATABASE=false
DBTALK_MYSQLDUMP__OUTPUT_DIRECTORY=data

DBTALK_MYSQLRESTORE__HOST=localhost
DBTALK_MYSQLRESTORE__PORT=3306
DBTALK_MYSQLRESTORE__USER=
DBTALK_MYSQLRESTORE__PASSWORD=
DBTALK_MYSQLRESTORE__DATABASE=
```

密码通过 `MYSQL_PWD` 传递给 MySQL 客户端，dbtalk 的正常输出不会回显密码。

## Dump

`dump` 需要 `user`、`password` 和 `database`，可通过配置或同名 CLI 选项提供。

```powershell
uv run dbtalk mysql dump --database app --output .\data\app.sql
uv run dbtalk mysql dump --database app --output .\data\app.sql --archive
uv run dbtalk mysql dump --database app --create-database --drop-database
```

未指定 `--output` 时，dbtalk 会创建配置中的 `mysqldump.output_directory`（默认 `data/`），并输出 `<database>-<timestamp>.sql`。使用 `--archive` 时输出会 gzip 压缩；路径没有 `.gz` 后缀会自动追加。

显式指定 `--output` 时，只有路径已经是目录才会被当作目录，并在其中生成 `<database>-<timestamp>.sql`。其他路径都被视为文件路径，且父目录必须已经存在；不存在的路径不会被推断为目录或自动创建。

| 选项 | 说明 |
| --- | --- |
| `--host`、`--port`、`--user`、`--password`、`--database` | 覆盖对应的 `mysqldump` 配置值。 |
| `--output FILE_OR_DIRECTORY` | SQL 制品输出文件，或已有的输出目录。 |
| `--create-database` / `--no-create-database` | 包含或省略 `CREATE DATABASE` 语句。 |
| `--drop-database` / `--no-drop-database` | 包含或省略 `DROP DATABASE` 语句。 |
| `--archive` | 写入 gzip 压缩的 dump。 |

生成的 dump 包含存储过程、事件和数据库选择语句。连接非本机 MySQL host 时使用客户端压缩；`localhost` 与 `127.0.0.1` 不使用该参数。

## Restore

`restore` 需要已有的 `.sql` 或 `.sql.gz` 输入文件，以及 `user` 和 `password`。目标数据库可选：不传 `--database` 时，由 SQL 文件控制数据库选择。目标库必须已经存在，除非 SQL 文件本身创建它。

```powershell
uv run dbtalk mysql restore --input .\data\app.sql
uv run dbtalk mysql restore --database app_local --input .\data\app.sql.gz
```

| 选项 | 说明 |
| --- | --- |
| `--host`、`--port`、`--user`、`--password`、`--database` | 覆盖对应的 `mysqlrestore` 配置值。 |
| `--input FILE` | 必填的 SQL 或 gzip 压缩 SQL 输入文件。 |

传入 `--database` 后，dbtalk 会准备临时输入：跳过顶层 `CREATE DATABASE`、`DROP DATABASE`，并将顶层 `USE` 语句改写为指定目标库。原始 dump 文件不会被修改。

还原可能覆盖或删除现有表及数据。执行前请确认目标连接、目标库、输入来源和写入授权。

## 客户端与故障处理

dbtalk 优先使用本机 `mysqldump` 或 `mysql` 可执行文件。缺失时，才使用本机已有的 Docker `mysql` 镜像；不会安装客户端、拉取镜像、创建数据库或自动重试。

Docker 回退连接 `localhost` 或 `127.0.0.1` 时使用 `host.docker.internal`，其他 host 原样传递。Docker 不可用或本机没有 MySQL 镜像时，命令会失败退出。

dump 成功后检查 CLI 报告的输出路径与文件大小；restore 成功后检查退出状态，并按需要抽查目标表。
