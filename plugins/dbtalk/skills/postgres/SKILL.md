---
name: dbtalk-postgres
description: 使用 dbtalk postgres 管理 PostgreSQL database，或创建和恢复单库 custom archive。用户要求 PostgreSQL database create/drop/list、backup、dump、restore 时使用。
---

# dbtalk PostgreSQL

使用 `dbtalk postgres` 管理 PostgreSQL database，或处理单个 PostgreSQL 数据库的 native logical
dump 和 restore。它创建并消费 `pg_dump --format=custom` archive，不用于 JSONL 数据传输、物理备份、WAL/PITR、role 或 tablespace。

先确认可用参数：

```powershell
uv run dbtalk postgres dump --help
uv run dbtalk postgres restore --help
uv run dbtalk postgres database --help
```

## 连接与客户端

连接必须通过完整的 `--dsn DSN` 或 `--dsn-env NAME` 二选一提供，并使用
`postgresql+psycopg://user:password@host:5432/database`。脚本中把 DSN 保存到环境变量，不能在命令行、
日志、skill 或 archive 文件名中暴露真实密码：

```powershell
$env:APP_DSN = 'postgresql+psycopg://backup:password@db.example.com:5432/app'
```

优先使用本机 `pg_dump` / `pg_restore`。缺失时，只能使用 `postgres.client_image` 配置的本地 Docker image，
默认 `postgres:18`；不会安装客户端、拉取 image 或自动重试。必要时通过
`DBTALK_POSTGRES__CLIENT_IMAGE` 配置与源服务端兼容的更高 major image。

## Database management

数据库生命周期操作使用 `dbtalk postgres database`，与 query/exec、role 管理和 dump/restore 分离。管理
DSN 必须连接到目标以外的维护库，通常为 `postgres`，并使用具有建库或删库权限的账号。

```powershell
uv run dbtalk postgres database list --dsn-env POSTGRES_MANAGEMENT_DSN
uv run dbtalk postgres database create --dsn-env POSTGRES_MANAGEMENT_DSN --name app_db
uv run dbtalk postgres database drop --dsn-env POSTGRES_MANAGEMENT_DSN --name app_db --yes
```

先执行 `list` 核对目标。删除不可逆，只有用户明确授权删除指定目标时才传入 `--yes`；不能删除管理 DSN
正在连接的数据库。存在其他连接时应如实报告失败，不主动终止其他会话；不猜测目标、不执行任意 SQL、
不创建或管理 role。

## Dump

```powershell
uv run dbtalk postgres dump --dsn-env APP_DSN --output .\data\app.dump
uv run dbtalk postgres dump --dsn-env APP_DSN --compression-level 6
```

dump 只输出 custom `.dump` archive，默认在 `postgres.output_directory` 中生成带时间戳的文件。archive
已使用 PostgreSQL 原生内部压缩；不要使用 MySQL 的 `.sql.gz` 语义或另行 gzip。

## Restore

restore 会修改目标数据库。只有目标 DSN、输入 archive 来源和写入授权均已明确时才能执行：

```powershell
uv run dbtalk postgres restore --dsn-env APP_DSN --input .\data\app.dump
```

目标数据库必须已经存在。默认跳过 archive 中的 owner 和 ACL；需要保留时传入
`--preserve-owner`、`--preserve-privileges`。`--clean` 会删除目标对象，必须显式指定；`--if-exists`
只能与 `--clean` 一起使用。custom archive 可使用 `--jobs N` 并行恢复，`N` 必须为正整数。

restore 在写入前用 `pg_restore --list` 校验 archive。即使启用 fail-fast，restore 也不能整体回滚；完成后
确认命令成功退出，并按需检查代表性对象和数据。
