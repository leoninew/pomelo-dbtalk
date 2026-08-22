---
name: dbtalk-mysql
description: 使用 dbtalk mysql 实际导出 MySQL 数据库或恢复 mysqldump SQL 文件。用户要求 MySQL backup、dump、restore、导入 .sql，或配置 mysqldump/mysqlrestore 时使用。
---

# dbtalk MySQL

使用 `dbtalk mysql` 处理 MySQL 原生 SQL dump 和 restore。优先使用本机的 `mysqldump` 或 `mysql`；本机客户端缺失时，只能回退到本机已有的 Docker `mysql` 镜像。不要安装客户端、拉取镜像或替换为其他备份工具。

先确认可用参数：

```powershell
uv run dbtalk mysql dump --help
uv run dbtalk mysql restore --help
```

## 配置与凭据

从项目根目录的 `dbtalk.yaml` 读取默认配置。设置 `DBTALK_ENVKEY=local` 时，`.env.local` 中的 `DBTALK_*` 值覆盖 YAML。
数据库连接必须通过完整的 `--dsn DSN` 或 `--dsn-env NAME` 二选一提供，不再使用 host、port、user、password、
database 分散参数。支持的 MySQL DSN 是 `mysql+pymysql://user:password@host:3306/database`。
将含凭据的 DSN 保存到环境变量，不要写入命令行、日志、文档或提交记录：

```env
APP_DSN=mysql+pymysql://user:password@host:3306/database
```

## Dump

dump 需要完整的 MySQL DSN。未传 `--output` 时，输出默认为当前目录的 `data/<database>-<timestamp>.sql`，并会自动创建配置的输出目录。显式传入 `--output` 且路径是已有目录时，也会在其中生成同样的时间戳文件。其他路径视为文件，父目录必须已存在；不存在的路径不会被推断为目录或自动创建。

```powershell
uv run dbtalk mysql dump --dsn-env APP_DSN --output .\data\app.sql
uv run dbtalk mysql dump --dsn-env APP_DSN --output .\data\app.sql --archive
```

`--archive` 写入 `.sql.gz`；输出路径没有 `.gz` 后缀时会自动追加。`--create-database` 和 `--drop-database` 分别包含 `CREATE DATABASE` 和 `DROP DATABASE`。非本机 MySQL host 使用连接压缩；`localhost` 与 `127.0.0.1` 不使用该参数。

完成后确认 CLI 输出的最终文件存在且大小合理。备份文件属于业务数据，放在被 Git 忽略的 `data/` 或其他受控目录中。

## Restore

restore 需要已有的 `.sql` 或 `.sql.gz` 文件，以及完整的 MySQL DSN。目标库必须已存在，除非 SQL 文件本身会创建它。

```powershell
uv run dbtalk mysql restore --dsn-env APP_DSN --input .\data\app-20260820-120000.sql.gz
```

只有在目标连接、目标库、输入文件来源和写入授权已明确时才能执行 restore。若 dump 含有源数据库的 `CREATE DATABASE`、`DROP DATABASE` 或 `USE`，通过 `--database <target>` 显式指定目标库；命令会在临时输入中跳过源库数据库 DDL 并重写 `USE`，不会修改原始 dump 文件。

restore 会覆盖或删除 dump 中同名表及数据，不能整体回滚。完成后确认命令成功退出，并按需检查目标表数或代表性数据。

## 运行路径与故障处理

- 密码只通过子进程环境变量 `MYSQL_PWD` 传递，输出中不得回显。
- Docker 回退连接本机数据库时使用 `host.docker.internal`；不要改成容器内的 `localhost`。
- Docker daemon 不可用或本地没有 `mysql` 镜像时，如实报告并停止；不要自动重试、拉取镜像、创建目标库或停止其他容器。
- dump 和 restore 没有内建超时。大文件操作仅按用户指定频率检查状态，不要中断仍在执行的 restore。
