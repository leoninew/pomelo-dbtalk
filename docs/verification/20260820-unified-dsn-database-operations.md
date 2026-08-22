# 统一 DSN 与通用数据库操作
最后修改时间: 2026-08-22 21:22:40

---
Review status: Accepted
Flow mode: standard
Stage: Verification
---

## Requirement alignment

已实现并验证以下已接受需求：

- 使用 SQLAlchemy 2.x Core 统一 SQLite、MySQL 和 PostgreSQL 的 DSN、连接、查询、执行和 JSONL transfer 边界。
- 只接受明确的 canonical DSN；不接受 DSN 别名、Go 风格 DSN、无 driver 的 MySQL/PostgreSQL URL 或数据库类型专用连接参数。
- `dbtalk database query` 和 `dbtalk database exec` 接受 `--dsn` 或 `--dsn-env`，严格二选一；query 默认输出 `table`，同时支持 `json`。
- `export/import/dump/restore/query/exec` 均使用统一的 `--dsn` / `--dsn-env` 连接入口。
- 同步 `DatabaseClient`、异步 `AsyncDatabaseClient`、参数化 SQL、事务和非敏感错误输出已覆盖。
- MySQL dump/restore 仍在原生客户端边界执行，不把 SQL backup/restore 迁移为 SQLAlchemy transfer。
- 发行包和命令入口统一为 `dbtalk`，Python 模块包迁移为 `dbtalk`。

## Plan alignment

- 依赖、锁文件、SQLAlchemy engine 工厂和 canonical DSN parser 已完成。
- JSONL transfer 已切换到 SQLAlchemy adapter，保留表选择、外键顺序、批量读取、事务和类型编码逻辑。
- PostgreSQL dialect、Psycopg 3 和 async driver 依赖已加入；本次没有真实 PostgreSQL 服务可供集成验证。
- CLI help、文档和 Codex skills 已同步到 `dbtalk` 和统一 DSN 契约。
- 未创建兼容旧入口或旧参数的别名。

## Spec alignment

不适用。standard 流程未单独创建 Spec 文档，按已接受 Requirement 和 Plan 验证。

## Actual diff summary

- `pyproject.toml`、`uv.lock`：发行包名改为 `dbtalk`，console script 改为 `dbtalk`，加入 SQLAlchemy、PostgreSQL、async driver 和输出依赖。
- `src/dbtalk/`：完成 Python 包目录迁移；新增 DSN parser、sync/async connection client、通用 query/exec、SQLAlchemy transfer adapter 和 PostgreSQL 支持。
- `src/dbtalk/database/cli.py`、`src/dbtalk/mysql/cli.py`：所有数据库命令统一使用 `--dsn` / `--dsn-env`。
- `src/dbtalk/database/sqlite.py` 删除，旧 SQLite/PyMySQL transfer 分流删除，transfer 统一走 SQLAlchemy adapter。
- `README.md`、数据库/MySQL 手册、Codex 文档和 skills：同步命令入口、DSN 格式、凭据和安全边界。
- 测试：新增通用操作、DSN、sync/async、CLI 和 SQLAlchemy transfer 覆盖，并迁移 Python import 路径到 `dbtalk`。

## Expected vs actual files

计划中的核心代码、测试、文档和依赖文件均已实际修改或新增；由于发行包名 `dbtalk` 由 `uv_build` 映射到 Python 模块名，实际源码目录为 `src/dbtalk/`，相应 import、覆盖率配置和测试路径已同步迁移。

未创建独立 `tests/test_database_dsn.py` 或 `tests/test_database_cli.py`；相关覆盖已合并到现有 `tests/test_database_operations.py`、transfer contract 和 CLI 测试中。未修改原始 SQLite 数据库、MySQL 源库 schema 或源库数据。

## Acceptance checklist

- [x] canonical DSN 解析、driver 校验、别名/Go DSN/旧专用参数拒绝。
- [x] SQLAlchemy 2.x、同步/异步 SQLite/MySQL/PostgreSQL driver 和 tabulate 依赖锁定。
- [x] sync/async client、参数化 query/exec、事务和错误映射。
- [x] query 的 `table` / `json` 输出，默认 `table`，NULL 和 JSON-safe 值处理。
- [x] 六类数据库命令的 `--dsn` / `--dsn-env` 二选一契约和帮助文案。
- [x] SQLite/MySQL JSONL export/import 单元与真实服务回归。
- [x] MySQL 原生 dump 使用 canonical DSN 转换为客户端参数，密码通过子进程环境传递。
- [x] `dbtalk` 发行包、console script、Python 模块和 Docker entrypoint。
- [x] 文档、skills、日志和错误输出不回显 DSN 密码。
- [ ] 真实 PostgreSQL 服务集成：当前环境未提供 PostgreSQL 服务，未执行。

## Test results

### Static and project checks

以下检查全部通过：

```text
uv lock --check
uv sync --all-groups --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
uv build
git diff --check
```

结果：`96 passed, 1 skipped`，覆盖率 `92.12%`；唯一跳过项是未启用的 manual integration marker。`uv build` 生成 source distribution 和 wheel；当前本机 uv 版本高于项目声明的 uv-build 约束，仅产生 warning，不影响构建结果。

`uv run dbtalk --version` 和 `uv run python -m dbtalk --version` 均输出 `dbtalk, version 0.1.0`。六个命令的 help 均显示 `dbtalk`，且未发现 `sqlite-file`、`--sqlite-path` 或 `--mysql-dsn-env`。

### Real SQLite/MySQL integration

使用用户提供的 Orbit SQLite 文件和 MySQL 服务进行了只读源验证。原始 SQLite 文件验证前后大小均为 `937984` bytes，修改时间保持为 `2026-08-19 21:47:36`；MySQL 源库只执行了 query、SQLAlchemy read-only export 和原生 dump。

- 两个源库均成功查询到 44 张表、524 行。
- SQLite JSONL export 成功：44 tables、524 rows。
- MySQL JSONL export 成功：44 tables、524 rows。
- MySQL 原生 SQL dump 成功，使用本地 Docker MySQL image。
- 建立临时 MySQL 库和临时 SQLite 库后，由测试夹具预创建 44 张表；`dbtalk import` 本身没有创建 schema。
- SQLite -> MySQL、MySQL -> SQLite 在排除 schema 差异表后均成功导入 43 张表、523 行。
- 两个临时目标库上的 query/exec、参数绑定和结果读取均成功。
- 临时 SQLite 目标上的 `AsyncDatabaseClient` 查询成功，`application_rows=5`。
- 临时 MySQL 库、临时 SQLite/JSONL/SQL 制品已清理；临时 MySQL 库已确认不存在。

### Observed schema difference

两套既有 Orbit schema 的 `schema_migrations` 定义不一致：SQLite 的 `version` 列不是主键，MySQL 的 `version` 列是主键。统一 transfer adapter 在 import 预检阶段正确拒绝了直接导入，且拒绝发生在写入前；显式使用 `--exclude-table schema_migrations` 后其余 43 张表成功双向导入。

这不是对源库的修改，也不是被静默绕过的兼容性问题；调用方需要在 schema 对齐或显式排除该表后再执行 transfer。

## Missed or expanded scope

- 未执行真实 PostgreSQL 集成，原因是当前环境没有 PostgreSQL 服务或用户提供的 PostgreSQL DSN。
- 用户提供的 MySQL 环境变量值是 Go 风格 DSN；测试夹具在进程内显式构造 canonical `mysql+pymysql://` DSN，未放宽公共 parser 对 Go 风格 DSN 的拒绝规则。
- 未对现有 MySQL 库执行 import、exec、restore 或任何 schema/data 写操作。
- 未为本次手工集成创建持久化测试制品或修改源项目配置。

## Risks and incomplete items

- PostgreSQL 的真实 schema/type/FK/import/upsert 行为仍需服务级验证。
- 两个已有 Orbit schema 的迁移元数据表不一致；完整跨库 transfer 不能默认包含 `schema_migrations`。
- `uv_build` 的项目约束为 `<0.11.0`，当前环境使用 `uv 0.11.16`；构建已成功，但依赖约束应在后续工具链升级时明确调整。

## Conclusion

Requirement 和 Plan 的 SQLite/MySQL、统一 DSN、query/exec、sync/async、JSONL transfer、MySQL backup 以及 `dbtalk` 包/入口范围均通过验证。交付仍保留 PostgreSQL 真实服务验证和 Orbit `schema_migrations` schema 对齐两个明确事项；除此之外没有发现阻止交付的失败项。
