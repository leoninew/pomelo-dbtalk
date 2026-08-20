# dbtalk

`dbtalk` 是一个命令行工具，用于 MySQL 原生 SQL 备份/还原，以及 SQLite 与 MySQL 间的 JSONL 数据传输。

## 命令手册

| 一级子命令 | 用途 | 手册 |
| --- | --- | --- |
| `dbtalk mysql` | 创建和还原 MySQL 原生 SQL dump。 | [MySQL 手册](docs/mysql.md) |
| `dbtalk database` | 在既有 SQLite 与 MySQL schema 间通过 JSONL 传输数据。 | [数据库传输手册](docs/database.md) |

Codex 使用本项目时，参见 [Codex 插件与 Skills](docs/codex.md)。

当前版本不提供查询和 MCP 能力。

## 安装与运行

项目需要 Python 3.12 和 [uv](https://docs.astral.sh/uv/)。

```powershell
uv sync --all-groups
uv run dbtalk --help
```

需要时可查看子命令帮助：

```powershell
uv run dbtalk mysql --help
uv run dbtalk database --help
```

## 配置

默认配置位于 [dbtalk.yaml](dbtalk.yaml)。复制 [.env.example](.env.example) 为 `.env.local`，运行前设置 `DBTALK_ENVKEY=local`，即可加载本地凭据和覆盖项。CLI 选项优先级最高。

```powershell
$env:DBTALK_ENVKEY = 'local'
uv run dbtalk mysql dump
```

SQL 和 JSONL 制品应放在被 Git 忽略的 `data/` 或其他受控目录。

## 测试

```powershell
uv run pytest
```

依赖真实 MySQL 或 Docker 的集成测试默认跳过；运行条件和操作限制见对应命令手册。
