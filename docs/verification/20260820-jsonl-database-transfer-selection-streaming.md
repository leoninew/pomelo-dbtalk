# JSONL 数据库传输选择与流式处理验证
最后修改时间: 2026-08-20 15:23:00

---
Review status: Accepted
Flow mode: standard
Stage: Verification
---

## 迁移说明

本文是原 `housekeeper` 实现于 2026-08-20 的历史验证记录，迁入此处用于保留表选择与流式 JSONL 处理的执行证据。下文的模块路径、环境变量前缀、测试数量、真实数据库制品和结论都属于原项目；它不声明 `dbtalk` 已完成相同验证。`dbtalk` 的独立验证应在当前工作树和当前环境中重新执行，并另行记录。

## Requirement alignment

已按已接受的 Requirement 验证 `housekeeper database export/import`。本次验证不涉及 `housekeeper mysql dump/restore`，也没有修改原始数据库 schema 或数据。

## Plan alignment

- 使用固定 1000 行批量读取、JSONL/JSONL.GZ 流式导出和双遍导入。
- 使用 `--include-table project` 将测试范围限制为一张小表，避免整库测试。
- 原始 SQLite 与原始 MySQL 仅作为读取源；导入目标均为新建 SQLite 文件或新建 MySQL schema。

## Actual diff summary

- 一级命令按包目录拆分为 `housekeeper/database/` 与 `housekeeper/mysql/`，不保留旧模块兼容层。
- `database export/import` 增加 include/exclude 选择、外键依赖预检、拓扑顺序、1000 行批量读取、JSONL.GZ 双遍导入。
- 测试、使用文档和 `database-transfer` skill 已同步更新。

## Acceptance checklist

- [x] `database export` 与 `database import` help 暴露可重复的 `--include-table` 和 `--exclude-table`。
- [x] 默认全表、include 限定、exclude 优先、未知表和空集合均有测试覆盖。
- [x] JSONL v1、gzip、`insert`/`upsert` 和表级事务保持可用。
- [x] SQLite/MySQL 导出业务数据使用 `fetchmany(1000)`；MySQL 元数据查询仍使用小规模 metadata fetch。
- [x] 导入第一遍完成格式、选择、schema、类型、主键和外键预检后，第二遍重新打开制品写入。
- [x] 外部父表依赖和外键错误路径在写入前阻止；SQLite 完整性检查保持开启。
- [x] 使用文档说明默认全表、过滤、外键顺序、双遍读取和表级事务。

## Automated checks

```text
uv run pytest -q                                      196 passed
ruff check src/housekeeper tests/...                  passed
uv run mypy src/housekeeper                           passed
python -m compileall -q src/housekeeper tests        passed
git diff --check                                      passed
```

## Integration test

源连接：

- SQLite：`D:\SourceCodes\mywork\pomelo-orbit\data\db\pomelo-orbit.db`
- MySQL：`127.0.0.1:3306/pomelo_orbit`，使用用户提供的 DSN；密码不记录在文档中。

选取 `project` 表：两边均为 1 行、无外键，符合受控数据量要求。两份源制品均使用 `--archive --include-table project` 导出为 `.jsonl.gz`，导出日志均报告 `1 tables, 1 rows`。

验证结果：

| 方向 | 目标 | 结果 |
| --- | --- | --- |
| SQLite -> SQLite | 新建 `target-sqlite-from-sqlite.db` | 成功，1 表 1 行 |
| MySQL -> SQLite | 新建 `target-sqlite-from-mysql.db` | 成功，1 表 1 行 |
| SQLite -> MySQL | 新建 `housekeeper_transfer_test_20260820_01` schema | 成功，1 表 1 行 |

三个目标中的 `project` 行均为：`id=01KRRKK0K3T519ZQZES3M4QA9Z`、`code=default`、`is_active=1`，名称和时间值与源数据一致。MySQL 目标查询显示时间为 `2026-08-17T03:29:19.767Z`；SQLite 目标保存为对应的目标时区无偏移值。

## Source safety

- 原始 SQLite 文件导出使用只读 URI；验证结束时文件大小仍为 `925696`，修改时间仍为 `2026-08-19 12:51:32`。
- 原始 MySQL 只执行 schema、统计和导出读取；没有使用 `--allow-write` 连接原库，也没有执行写 SQL。
- 新建 MySQL schema 仅用于本次导入验证；临时 `pomelo-db` datasource 配置已移除。

## Scope and risks

- 本次真实连接验证只覆盖 `project` 小表，未对 44 张表整库执行导出，也未在真实 MySQL 目标上验证多表外键拓扑导入。
- 原始 SQLite 文件被运行中的 pomelo-orbit 进程占用，额外 SHA256 文件读取被系统拒绝；未进行任何绕过锁的操作。大小和修改时间检查正常。
- 双遍读取依赖两遍之间输入制品不被替换或截断；本次制品在两遍之间保持不变。

## Conclusion

在受控 `project` 表范围内，SQLite/MySQL JSONL.GZ 导出、SQLite 导入和 SQLite/MySQL 交叉传输均通过。实现满足当前 Requirement/Plan 的功能验收；多表大数据和真实 MySQL 外键目标仍属于后续扩展验证范围。
