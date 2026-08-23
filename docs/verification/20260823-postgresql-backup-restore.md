# PostgreSQL 单库逻辑备份与还原验证
最后修改时间: 2026-08-23 14:10:52

---
Review status: Accepted
Flow mode: standard
Stage: Verification
---

## Requirement alignment

已实现 `dbtalk postgres dump` 和 `dbtalk postgres restore`，以原生 `pg_dump` / `pg_restore`
处理单个 PostgreSQL 数据库的 custom archive：

- dump 只生成 `.dump` custom archive，支持 `--compression-level 0..9`，不复用 MySQL 的 gzip
  `--archive` 语义。
- restore 在写入前执行 `pg_restore --list`，支持显式 `--clean --if-exists`、`--jobs`，默认传递
  `--no-owner --no-privileges`，并可显式保留 owner 或 ACL。
- 连接只接受 `postgresql+psycopg://` 的 `--dsn` / `--dsn-env`；子进程 argv 不含密码。本机客户端使用
  临时 `.pgpass`，Docker fallback 通过受控的 `PGPASSWORD` 环境变量传递凭据。
- 本机 `pg_dump` / `pg_restore` 缺失时，使用配置的本地 Docker image；默认 `postgres:18`，不拉取 image。
- 已增加 PostgreSQL CLI、配置、文档和 Codex skill；既有 MySQL 和 JSONL 命令未改变。

## Plan alignment

- 计划中的 `postgres` 配置和 root command 注册已完成，包含 `output_directory` 与可覆盖的
  `client_image`。
- native/Docker 客户端边界、临时凭据文件、Docker host mapping、bind mount、archive 原子输出和恢复预检
  已完成。
- 实现中发现 Windows 使用 `Path("/backup")` 会产生反斜杠容器路径，使 Docker `pg_dump` 写入容器临时
  文件系统而非 bind mount。已改用 `PurePosixPath`，并增加回归断言；属于计划中 Docker bind mount
  风险的修复，没有扩大功能范围。
- standard 流程未创建独立 Spec，按已接受 Requirement 和 Plan 验证。

## Actual diff summary

- 新增 `src/dbtalk/postgres/`，实现 native client、Docker fallback、custom dump、restore 与 Click
  适配。
- 注册 `dbtalk postgres`，并扩展 typed settings、YAML 和环境变量示例，以默认 `postgres:18` 支持
  可配置 Docker client image。
- 新增 PostgreSQL 单测，扩展 root CLI 与 settings 覆盖。
- 新增 PostgreSQL 手册和 Codex skill，更新 README、Codex 文档、插件 metadata 与包描述。
- 新增本功能的 Requirement、Plan 和 Verification 过程文档。

## Expected vs actual files

计划列出的 CLI、PostgreSQL package、配置、测试、README、手册、Codex skill 和 plugin metadata 均已
修改或新增。实现额外修改了 `pyproject.toml` 的项目描述，使发布元数据覆盖 PostgreSQL backup/restore；
该改动与功能范围一致。

工作区另有 `docs/requirement/20260823-database-management.md` 和
`docs/requirement/20260823-user-management.md` 两份无关未跟踪文档；它们不属于本功能，未纳入验证或暂存。

## Acceptance checklist

- [x] `dump` / `restore` 仅接受 canonical PostgreSQL DSN 的 `--dsn` / `--dsn-env` 二选一。
- [x] dump 生成 custom `.dump`，支持默认输出路径、显式输出路径及 archive compression level。
- [x] custom archive 可直接由 `pg_restore` 消费，未实现外层 gzip。
- [x] restore 在写入前验证 archive，支持 clean/if-exists 约束、parallel jobs 与 owner/ACL 策略。
- [x] 默认优先本机客户端；缺失时仅使用配置且已存在的 Docker image，不安装或拉取依赖。
- [x] 密码不进入 client argv、正常输出或日志；本机临时 `.pgpass` 在命令结束时清理。
- [x] 单元测试覆盖本机路径、Docker fallback、凭据处理、archive 预检和危险选项约束。
- [x] 文档、Codex skill 和 plugin metadata 与 CLI 行为一致。

## Test results

### Automated checks

以下检查均通过：

```text
uv run pytest                         120 passed, 1 skipped, coverage 91.06%
uv run ruff check .                   passed
uv run ruff format --check .          passed
uv run mypy src tests                 passed
uv lock --check                       passed
uv build                              passed
git diff --check                      passed
plugin validation                     passed
```

当前 Windows 环境没有 `make`，因此按 Makefile 定义直接执行了等价的 pytest、Ruff 和 Mypy 命令。
`uv build` 仅报告现有 `uv-build` 版本约束与当前 uv 版本不匹配的 warning，source distribution 和 wheel
均成功生成。

### PostgreSQL integration

首次使用用户提供的本机 PostgreSQL 连接完成真实集成验证。认证成功，服务端实际版本为 PostgreSQL
16.15；本机没有 native client 或 `postgres:18` image，因此仅在首次命令中覆盖为本地已有的 `postgres:16`
image，不修改项目默认配置。

验证过程创建随机临时源库和目标库，在源库中创建外键关联表、两行数据与视图，然后执行：

1. Docker fallback `dump --compression-level 6`，成功生成 3283-byte custom archive。
2. Docker fallback restore 的 archive `--list` 预检及 `--jobs 2` 恢复，目标库查询验证两行数据和视图结果。
3. 针对临时目标库执行 `--clean --if-exists --jobs 2 --preserve-owner --preserve-privileges`，再次验证表行数。
4. 删除两个随机临时数据库，并查询确认它们不再存在。

后续在升级后的 PostgreSQL 18.6 服务端，使用默认 `postgres:18` Docker client image 完成同一真实集成验证：

1. Docker fallback `dump --compression-level 6` 成功生成 3554-byte custom archive。
2. restore 内置 archive `--list` 预检及 `--jobs 2` 恢复均成功；表行数、库存数量总和和视图结果均为
   `2|14|2`。
3. 向目标库写入额外测试数据后，执行
   `--clean --if-exists --jobs 2 --preserve-owner --preserve-privileges`；二次校验仍为 `2|14|2`，证明清理
   恢复生效。
4. 删除两个随机临时数据库，并查询确认它们不再存在。

## Missed or expanded scope

- 无物理备份、`pg_dumpall`、role/tablespace、plain SQL、directory format 或参数透传实现，符合 Non-goal。
- 运行策略阻止删除两次集成测试生成的 `.dump` 制品；所有临时数据库均已删除，archive 位于忽略的
  `data/` 目录且不属于 Git 变更。

## Risks and incomplete items

- `--clean` 恢复不能整体回滚，生产使用前仍需确认目标数据库和 archive 来源。
- 恢复跨环境时，extension、role 和权限兼容性仍由 PostgreSQL 原生语义决定。

## Conclusion

Requirement、Plan 与实际 diff 一致；自动检查以及 PostgreSQL 16.15 与 18.6 的真实 Docker fallback
dump/restore 均通过。除受策略限制而保留的忽略 archive 外，没有阻止交付的问题。用户已确认验证通过，
本功能可作为一个独立提交暂存。
