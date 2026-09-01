# dbtalk

`dbtalk` 是一个命令行工具，用于通用 SQL 查询/执行、基于 SQLAlchemy 风格 DSN 的数据库操作、
SQLite/MySQL/PostgreSQL 间的 JSONL 数据传输，以及 MySQL 和 PostgreSQL 原生逻辑备份/还原。

## 命令手册

| 一级子命令 | 用途 | 手册 |
| --- | --- | --- |
| `dbtalk mysql` | 管理 MySQL schema、user、权限与原生 SQL dump。 | [MySQL 手册](docs/mysql.md) |
| `dbtalk postgres` | 管理 PostgreSQL schema、role、权限与 custom archive。 | [PostgreSQL 手册](docs/postgres.md) |
| `dbtalk query/exec/export/import` | 通用 SQL 操作和 SQLite、MySQL、PostgreSQL 间 JSONL 数据传输。 | [数据库手册](docs/database.md) |

Codex 使用本项目时，参见 [Codex 插件与 Skills](docs/codex.md)。

当前版本不提供 MCP 能力。

常用命令分工：`mysql schema` / `postgres schema` 管理 schema/database；`user` / `role` 管理主体生命周期；
`grant` / `revoke` 管理 profile 或细粒度权限；`permissions list/show` 查看原生权限；`query`、`exec`、
`export`、`import` 提供通用 SQL 和 JSONL 数据传输。

## 安装与运行

项目需要 Python 3.12 和 [uv](https://docs.astral.sh/uv/)。

```powershell
uv sync --all-groups
uv run dbtalk --help
```

需要时可查看子命令帮助：

```powershell
uv run dbtalk mysql --help
uv run dbtalk mysql schema --help
uv run dbtalk mysql user --help
uv run dbtalk mysql grant --help
uv run dbtalk mysql permissions --help
uv run dbtalk postgres --help
uv run dbtalk postgres schema --help
uv run dbtalk postgres role --help
uv run dbtalk postgres grant --help
uv run dbtalk postgres permissions --help
uv run dbtalk query --help
uv run dbtalk exec --help
```

## 版本管理

项目从完整 Git 历史计算 `0.y.z` 版本：提交 subject 以 `feat` 开头时增加 `y` 并将 `z` 重置为
`0`，其他提交只增加 `z`。仅查看当前计算结果：

```powershell
make version
```

应用版本到 `pyproject.toml` 并刷新 `uv.lock`：

```powershell
make version VERSION_ARGS='--quiet --apply'
```

`--apply` 会在锁文件刷新失败时恢复两个版本文件；不会创建 Git 提交或推送标签。

## 配置

默认配置位于 [dbtalk.yaml](dbtalk.yaml)。复制 [.env.example](.env.example) 为 `.env.local`，运行前设置 `DBTALK_ENVKEY=local`，即可加载本地凭据和覆盖项。CLI 选项优先级最高。

```powershell
$env:DBTALK_ENVKEY = 'local'
uv run dbtalk mysql dump
```

数据库命令通过 `--dsn DSN` 或 `--dsn-env NAME` 二选一接收明确的 SQLAlchemy 风格 DSN，例如
`sqlite:///./data/app.db`、`mysql+pymysql://user:password@host:3306/app` 或
`postgresql+psycopg://user:password@host:5432/app`。脚本中优先使用 `--dsn-env`，避免把含密码的
DSN 写入进程参数；不支持无 driver 的数据库 URL 或数据库类型专用 path 参数。

SQL 和 JSONL 制品应放在被 Git 忽略的 `data/` 或其他受控目录。

## 本地安装

`make install` 严格依次执行 plugin 预检、`uv tool install --editable . --force` 和 plugin 应用。plugin 子命令通过已安装的 Codex、Claude、Grok CLI 各自的 plugin 安装器更新仓库
marketplace 中的 plugin。自动模式跳过缺失的部分宿主；三个宿主均不存在时会在 CLI 安装和宿主写操作前失败。预览而不写入时使用：

```powershell
uv run python scripts/install.py plugin apply --dry-run
```

使用 `--codex` 选择宿主，或使用 `--strict` 要求三个宿主都可用。`install.py` 的显式入口为 `plugin check`、
`plugin list`、`plugin apply` 和 `plugin remove`；无参数等同于 `--help`。同步器以宿主 CLI 的 JSON 状态精确识别
marketplace 和 plugin；dry-run 仍会执行只读预检和计划，不会写入用户目录。

该命令不手工复制 skill 到 `~/.codex/skills`、`~/.claude/skills` 或 `~/.grok`，由插件安装器管理其受管目录。
发布后的 plugin 需要 `dbtalk` 位于 `PATH`。同步引擎完整 vendored 在
[`scripts/install.py`](scripts/install.py)，项目只在文件顶部声明 plugin 包和 marketplace；不依赖外部同步包或
项目外的绝对路径。仓库没有 standalone skill，因此 `skill` 子命令会明确报告未配置，不会把 plugin skill
镜像到任一宿主的普通 `skills/` 目录。

同步器只通过宿主原生 CLI 管理 plugin：自动模式跳过未安装的宿主 CLI，显式 `--claude`、`--codex`、`--grok`
或 `--strict` 会在任何写入前失败。`check`、`list` 和 `--dry-run` 无写入；实际运行可能逐宿主产生部分成功，结果会逐项报告。

`make release` 仅构建 source 和 wheel 发布产物，不上传、不安装 CLI，也不修改 agent plugin。

`make binary` 使用当前系统的 Python 打包 `dist/dbtalk`（Windows 为 `.exe`）。可执行文件内置
默认 `dbtalk.yaml`；在其同目录放置 `dbtalk.yaml` 或设置 `DBTALK_ENVKEY` 后放置 `.env.<环境>`，即可
覆盖内置配置。

## 测试

```powershell
make test
make test cov=1
```

依赖真实 MySQL 或 Docker 的集成测试默认跳过；运行条件和操作限制见对应命令手册。
