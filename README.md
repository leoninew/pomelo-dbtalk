# dbtalk

[![CI](https://github.com/leoninew/pomelo-dbtalk/actions/workflows/ci.yml/badge.svg)](https://github.com/leoninew/pomelo-dbtalk/actions/workflows/ci.yml)

`dbtalk` 是一个面向自动化和运维场景的数据库命令行工具，统一处理 SQL 操作、数据迁移、权限管理和逻辑备份。

支持 SQLite、MySQL 和 PostgreSQL，并使用明确的 SQLAlchemy 风格 DSN 作为连接入口。

## 功能

- 使用 `query` 和 `exec` 执行 SQL，支持参数绑定和超时控制
- 在 SQLite、MySQL、PostgreSQL 之间导出和导入 JSONL 数据
- 管理 MySQL schema、user 和 PostgreSQL schema、role
- 使用 `grant`、`revoke` 管理权限 profile，使用 `permissions list/show` 查看原生权限
- 创建和恢复 MySQL SQL dump、PostgreSQL custom archive

## 安装

需要 Python 3.12 或更高版本，以及 [uv](https://docs.astral.sh/uv/)。从源码安装并运行：

```bash
uv sync --all-groups
uv run dbtalk --help
```

## 快速开始

连接信息建议通过环境变量传入，避免密码出现在命令历史中：

```bash
mkdir -p data
export APP_DSN='sqlite:///./data/app.db'

uv run dbtalk query \
  --dsn-env APP_DSN \
  --sql 'SELECT 1 AS ok'

uv run dbtalk exec \
  --write \
  --dsn-env APP_DSN \
  --sql 'CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, body TEXT NOT NULL)'
```

Windows PowerShell 使用 `$env:APP_DSN = '...'` 设置环境变量。

## 命令

| 命令 | 用途 |
| --- | --- |
| `dbtalk mysql schema` | 管理 MySQL schema/database |
| `dbtalk mysql user` | 管理 MySQL 用户 |
| `dbtalk mysql grant` / `dbtalk mysql revoke` | 授予或撤销 MySQL 权限 |
| `dbtalk postgres schema` | 管理 PostgreSQL schema/database |
| `dbtalk postgres role` | 管理 PostgreSQL role |
| `dbtalk postgres grant` / `dbtalk postgres revoke` | 授予或撤销 PostgreSQL 权限 |
| `dbtalk mysql permissions list/show` | 查看 MySQL 原生权限 |
| `dbtalk postgres permissions list/show` | 查看 PostgreSQL 原生权限 |
| `dbtalk mysql dump/restore` | 处理 MySQL SQL dump |
| `dbtalk postgres dump/restore` | 处理 PostgreSQL custom archive |
| `dbtalk query/exec` | 查询或执行单条 SQL |
| `dbtalk export/import` | 传输 JSONL 数据 |

## DSN 和配置

支持的 DSN 示例：

```text
sqlite:///./data/app.db
mysql+pymysql://user:password@host:3306/app
postgresql+psycopg://user:password@host:5432/app
```

命令必须在 `--dsn DSN` 和 `--dsn-env NAME` 中选择一个。默认配置位于 [dbtalk.yaml](dbtalk.yaml)，可使用 `DBTALK_` 前缀的环境变量覆盖。

## 文档

- [数据库操作](docs/database.md)：SQL、JSONL 导入导出和 DSN 约定
- [MySQL 手册](docs/mysql.md)：schema、用户、权限、dump 和 restore
- [PostgreSQL 手册](docs/postgres.md)：schema、role、权限、dump 和 restore
- [Codex 插件](docs/codex.md)：在 Codex 中使用仓库内插件

## 开发

```bash
make deps
make check
make test
make release
```

`make check` 执行 Ruff 和 Mypy；`make test` 运行测试套件。依赖真实数据库的集成测试默认跳过。

## Docker

```bash
docker build -t dbtalk .
docker run --rm dbtalk --help
```
