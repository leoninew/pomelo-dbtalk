---
Review status: Accepted
Flow mode: light
Stage: Verification
---

# 压缩数据库备份验证

最后修改时间: 2026-08-20 15:23:00

## 迁移说明

本文是原 `housekeeper` 实现于 2026-08-20 的历史验证记录，迁入此处用于保留 gzip 备份与零日期策略的执行证据。下文的模块路径、环境变量前缀、测试数量、真实数据库制品和结论都属于原项目；它不声明 `dbtalk` 已完成相同验证。`dbtalk` 的独立验证应在当前工作树和当前环境中重新执行，并另行记录。

## 需求对齐

- `housekeeper mysql dump --archive` 生成单文件 `.sql.gz`；`mysql restore` 可直接读取 `.sql.gz`。
- `housekeeper database export --archive` 生成单文件 `.jsonl.gz`；`database import` 可直接读取 gzip JSONL。
- 非本机 MySQL host 的 dump 命令添加 `-C` 压缩客户端与服务端传输；`localhost` 和 `127.0.0.1` 不添加。
- 未使用 `--archive` 时，原有 SQL/JSONL 行为保持不变。
- `database.zero_datetime_as_null` 默认开启，MySQL JSONL 导出将完整零日期写为 `null`；关闭后导出明确失败。

## Spec / Plan 对齐

不适用。此功能按 light / 轻量模式依据已接受的 Requirement 实现。

## 实际 Diff 摘要

- `src/housekeeper/mysql.py`、`mysql_dump.py`、`mysql_restore.py` 与 `mysql_client.py`：增加 gzip SQL 备份/还原和远程 dump 的 `-C`。
- `src/housekeeper/database.py` 与 `database_transfer_format.py`：增加 gzip JSONL 导出/导入。
- `src/housekeeper/settings.py`、`database.py`、`database_mysql.py` 与 `database_transfer_models.py`：增加 `database.zero_datetime_as_null` 配置，并仅在 MySQL 日期时间列的完整零日期上应用。
- `tests/test_mysql.py`、`tests/test_database_transfer.py`：覆盖 gzip 正向路径和本机 Docker 回退不添加 `-C`。
- `tests/test_settings.py`：覆盖数据库传输配置的默认值、布尔解析与环境变量覆盖。
- `docs/usage/database.md`、`docs/usage/configuration.md`、`.env.example` 与 `housekeeper.yaml`：补充 gzip 命令和零日期配置说明。

预期与实际改动文件一致；没有新增 tar 包装、`--backup` 兼容参数或独立归档模块。

## 验收清单

- [x] `--archive` 为 MySQL dump 输出 `.sql.gz`，并在远程 MySQL dump 中使用 `-C`。
- [x] `.sql.gz` 可实际还原到新建的临时 MySQL 目标库；源库与目标库均为 11 张表、6,198 行，逐表 `COUNT(*)` 无差异。
- [x] `test_component_center`（14 张表、2,578 行）可完整导出 `.jsonl.gz`，并导入本地 SQLite；逐表 `COUNT(*)` 无差异。
- [x] 本地 SQLite 的一张两行测试表可导出 `.jsonl.gz` 并导入临时 MySQL 目标库；Decimal、布尔、日期时间和 BLOB 均一致。
- [x] 所有原始 MySQL 库仅执行统计、导出和计数查询，没有执行任何写入、覆盖、删除或还原操作。
- [x] 临时 MySQL 目标库 `housekeeper_gzip_verify_20260820075958` 已删除。
- [x] `database.zero_datetime_as_null` 默认值为 `true`，可由 YAML 或 `HOUSEKEEPER_DATABASE__ZERO_DATETIME_AS_NULL=false` 关闭。
- [x] `DATE`、`DATETIME`、`TIMESTAMP` 的完整零日期在默认配置下写为 JSON `null`；文本列不受影响。
- [x] 在实际 `test_starship_cmdb` 源库上，默认配置完成 11 表、6,198 行的 `.jsonl.gz` 只读导出。
- [x] 在同一源库临时关闭配置后，导出以零日期错误明确失败。

## 命令结果

- `uv run pytest tests/test_mysql.py tests/test_database_transfer.py --tb=short -q`：43 项通过。
- `uv run ruff check`（本次涉及文件）：通过。
- `uv run mypy`（本次涉及文件）：通过。
- `git diff --check`：通过。
- 原生 MySQL gzip 验证：从小型 `test_starship_cmdb` 生成 341,877 字节 `.sql.gz`，还原到临时库后逐表精确行数一致。
- MySQL 到 SQLite gzip JSONL 验证：从 `test_component_center` 生成 1,972,240 字节 `.jsonl.gz`，导入 14 张表、2,578 行后逐表精确行数一致。
- SQLite 到 MySQL gzip JSONL 验证：两行专用测试数据导出为 410 字节 `.jsonl.gz`，导入后值与 BLOB 十六进制表示一致。
- 零日期单测与配置回归：`uv run pytest tests/test_settings.py tests/test_database_transfer.py -q`，38 项通过。
- 零日期静态检查：相关文件的 `ruff check`、`mypy` 与 `git diff --check` 均通过。
- 默认零日期实际验证：`test_starship_cmdb` 成功导出 345,513 字节 `.jsonl.gz`，11 表、6,198 行。
- 关闭零日期配置实际验证：`test_starship_cmdb` 在只读导出中以 `MySQL zero date cannot be exported while database.zero_datetime_as_null is disabled` 失败。

## 范围偏差

无产品代码范围偏差。为避免整库测试过大，先对全部 `test_*` 数据源进行 `information_schema.tables` 统计，并选择较小的数据源。

## 风险与未完成项

- 默认零日期规范化会丢失 `0000-00-00...` 与 SQL `NULL` 的语义差异。需要保留该差异时应关闭 `database.zero_datetime_as_null`，并在源数据层处理后再导出。
- 系统策略拒绝递归删除本地临时目录 `D:\ProgramFiles\Cygwin64\tmp\housekeeper-gzip-verify-20260820075958`。其中只含本次生成的 SQLite 和 gzip 测试文件；临时 MySQL 目标库已清理。
- 本次零日期验证文件位于 `D:\ProgramFiles\Cygwin64\tmp\housekeeper-zero-date-verify-202608200814`，仅含生成的 `.jsonl.gz`，没有写入源库。

## 结论

gzip 备份、还原和 SQLite/MySQL JSONL 双向传输的成功路径均已完成实际验证。默认配置下，零日期可兼容导出为 JSON `null`；关闭配置时会保留严格失败行为。所有源库保持只读。
