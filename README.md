# db-talk

`db-talk` 是一个命令行工具，用于通用 SQL 查询/执行、基于 SQLAlchemy 风格 DSN 的数据库操作、
SQLite/MySQL/PostgreSQL 间的 JSONL 数据传输，以及 MySQL 原生 SQL 备份/还原。

## 命令手册

| 一级子命令 | 用途 | 手册 |
| --- | --- | --- |
| `db-talk mysql` | 创建和还原 MySQL 原生 SQL dump。 | [MySQL 手册](docs/mysql.md) |
| `db-talk database` | 执行 query/exec，或在既有 SQLite、MySQL、PostgreSQL schema 间通过 JSONL 传输数据。 | [数据库手册](docs/database.md) |

Codex 使用本项目时，参见 [Codex 插件与 Skills](docs/codex.md)。

当前版本不提供 MCP 能力。

## 安装与运行

项目需要 Python 3.12 和 [uv](https://docs.astral.sh/uv/)。

```powershell
uv sync --all-groups
uv run db-talk --help
```

需要时可查看子命令帮助：

```powershell
uv run db-talk mysql --help
uv run db-talk database --help
uv run db-talk database query --help
uv run db-talk database exec --help
```

## 配置

默认配置位于 [dbtalk.yaml](dbtalk.yaml)。复制 [.env.example](.env.example) 为 `.env.local`，运行前设置 `DBTALK_ENVKEY=local`，即可加载本地凭据和覆盖项。CLI 选项优先级最高。

```powershell
$env:DBTALK_ENVKEY = 'local'
uv run db-talk mysql dump
```

数据库命令通过 `--dsn DSN` 或 `--dsn-env NAME` 二选一接收明确的 SQLAlchemy 风格 DSN，例如
`sqlite:///./data/app.db`、`mysql+pymysql://user:password@host:3306/app` 或
`postgresql+psycopg://user:password@host:5432/app`。脚本中优先使用 `--dsn-env`，避免把含密码的
DSN 写入进程参数；不支持无 driver 的数据库 URL 或数据库类型专用 path 参数。

SQL 和 JSONL 制品应放在被 Git 忽略的 `data/` 或其他受控目录。

## 测试

```powershell
uv run pytest
```

依赖真实 MySQL 或 Docker 的集成测试默认跳过；运行条件和操作限制见对应命令手册。
