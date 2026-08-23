# PostgreSQL 手册

`dbtalk postgres` 使用原生 `pg_dump` 和 `pg_restore` 创建、校验和恢复单个 PostgreSQL 数据库的
custom archive。它不提供物理备份、WAL/PITR、`pg_dumpall` 或 cluster 全局 role/tablespace 恢复。

```powershell
uv run dbtalk postgres --help
uv run dbtalk postgres dump --help
uv run dbtalk postgres restore --help
```

## DSN 与客户端

所有命令必须且只能提供一个 `--dsn DSN` 或 `--dsn-env NAME`。PostgreSQL DSN 必须使用明确的
`postgresql+psycopg://` 格式：

```powershell
$env:APP_DSN = 'postgresql+psycopg://backup:password@db.example.com:5432/app?sslmode=require'
```

脚本中优先使用 `--dsn-env`，避免密码出现在进程参数中。`dbtalk` 向 native client 传递无密码的
libpq URI；本机客户端读取临时 `.pgpass`，Docker client 通过子进程环境读取密码。正常输出、日志和
错误摘要不会回显密码。

命令优先使用本机 `pg_dump` / `pg_restore`。缺失时，才使用本机 Docker 中已有的配置 image：

```yaml
postgres:
  output_directory: data
  client_image: postgres:18
```

可用 `DBTALK_POSTGRES__CLIENT_IMAGE` 覆盖 image。不会安装客户端、拉取 image 或根据源库版本自动选择
tag。PostgreSQL 18+ 是当前支持基线；`pg_dump` client 必须不低于源服务端 major，恢复目标通常不应低于
备份来源。

## Dump

```powershell
uv run dbtalk postgres dump `
  --dsn-env APP_DSN `
  --output .\data\app.dump `
  --compression-level 6
```

dump 始终生成 `pg_dump --format=custom` 的 `.dump` archive。省略 `--output` 时创建
`postgres.output_directory`，并生成 `<database>-<timestamp>.dump`；已有目录同样生成时间戳文件。
显式文件路径的父目录必须已经存在。

custom archive 具有 PostgreSQL 原生内部压缩，不能等同于 `.sql.gz`。不要给 `.dump` 再套 gzip；
`pg_restore` 可以直接读取它。`--compression-level` 仅接受 `0` 到 `9`；省略时保留 native client 的
默认 archive 压缩行为。

## Restore

```powershell
uv run dbtalk postgres restore `
  --dsn-env APP_DSN `
  --input .\data\app.dump `
  --clean `
  --if-exists `
  --jobs 4
```

目标数据库必须已经存在，并由 DSN 明确指定。restore 会先运行 `pg_restore --list` 校验 archive；无效
archive 在连接和写入目标库前失败。

默认恢复跳过 owner 与 ACL，以支持不同账号管理的环境。需要原样恢复时，显式传入
`--preserve-owner` 和/或 `--preserve-privileges`。`--jobs` 只接受正整数，适用于 custom archive。

`--clean` 会删除 archive 将恢复的目标对象，默认关闭；`--if-exists` 只能与 `--clean` 同时使用。
restore 并非整体原子操作，发生错误时目标数据库可能保留部分恢复状态。执行前必须确认目标 DSN、
archive 来源和写入授权。

## Scope

常规 logical dump 包含单库中的 schema、表数据、索引、约束、序列、视图、函数和 extension 声明。
它不备份 cluster 全局 role、role password、tablespace 或实例配置；跨环境恢复还要求目标实例具备兼容的
extension 与客户端版本。需要全量 cluster 灾备或时间点恢复时，应使用独立的 PostgreSQL 物理备份方案。
