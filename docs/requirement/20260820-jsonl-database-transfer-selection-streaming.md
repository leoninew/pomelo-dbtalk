# JSONL 数据库传输选择与流式处理
最后修改时间: 2026-08-20 15:36:51

---
Review status: Accepted
Flow mode: standard
Stage: Requirement
---

## 迁移说明

本文档的已接受需求现归属 `dbtalk`。它描述当前 JSONL 传输契约；原实现的自动化和集成验证事实保留在同名历史 Verification 文档中。

## Background

`dbtalk database export/import` 已能以 JSONL 在既有 SQLite/MySQL schema 之间传输表数据，事务边界为单个表块，并支持 `insert` 与 `upsert`。当前导出适合受控数据量，但数据库传输需要明确表集合边界，并避免把整张表或整个 JSONL 文件一次性读入内存。

本任务以 JSONL 导出/导入为主。`dbtalk mysql dump/restore` 仍是 MySQL 原生 SQL 封装；其中 dump 仅在输出路径解析上与 JSONL export 对齐，不改变客户端、SQL 或 restore 语义。

## Goal

1. 保持一级命令结构：`dbtalk mysql dump/restore` 负责原生 SQL；`dbtalk database export/import` 负责 JSONL 表数据。
2. `database export` 与 `database import` 默认处理全部表，并支持重复指定 `--include-table` 限定表集合。
3. 保留重复指定 `--exclude-table` 的排除能力；include 与 exclude 共同决定最终表集合。
4. 对选中的多张表，根据外键依赖执行父表优先、子表后置的稳定顺序；无法安全排序的外键环在写入前失败。
5. 将大表导出改为批量循环取数并流式写入 JSONL/JSONL.GZ，避免使用 `fetchall()` 保存整表。
6. 将导入改为流式处理，保持完整预检后再写入、单表事务、`insert`/`upsert` 语义和可回放 JSONL 制品能力。
7. 统一 `database export` 与 `mysql dump` 的输出路径规则：省略 `--output` 时创建默认目录并生成带时间戳制品；已有目录路径生成同类制品；非目录路径视为文件且父目录必须存在。

## Non-goal

- 不修改 `mysql dump` 的客户端、SQL 或备份内容语义；仅使已有目录形式的 `--output` 与 JSONL export 采用相同的时间戳命名规则。
- 不修改 `mysql restore` 的行为。
- 不创建、修改或删除目标 schema，不执行应用迁移。
- 不引入行级 `WHERE` / V 条件、服务级数据闭包或自动补齐未选中的父表。
- 不改变现有 `insert`、`upsert`、表级事务和 JSONL v1 记录格式的业务语义。
- 不承诺跨表整文件原子性；前序表已提交时，后续表失败仍按现有表级事务语义处理。
- 不在本任务中实现断点续传、运行记录、checksum、签名或新的 `backup/restore` 命令。

## User scenarios

1. 管理员不指定表过滤时，导出数据库全部普通表；导入 JSONL 中全部表。
2. 管理员重复指定 `--include-table users --include-table orders` 时，只处理这组表。
3. 管理员同时使用 include 与 exclude 时，先取 include 集合（未指定 include 则取全部表），再排除 exclude 集合。
4. 管理员选择存在父子外键关系的多张表时，导出文件和导入执行均按父表到子表的顺序处理。
5. 管理员只选择子表而目标中缺少其父记录时，导入在写入前给出外键依赖预检错误，不依赖数据库写入失败来发现问题。
6. 管理员导出大表时，命令按批次从源数据库读取并持续写入 JSONL，不因整表 `fetchall()` 造成内存随表大小增长。
7. 管理员从已有 JSONL/JSONL.GZ 文件导入时，命令按流式记录读取；完整预检通过后仍按表提交事务，失败后可使用同一制品重试到其他目标连接。

## Acceptance

- [ ] CLI help 在 `database export` 与 `database import` 中暴露可重复的 `--include-table` 和 `--exclude-table`。
- [ ] 未指定 include 时默认候选集合为全部普通表；指定 include 时只允许 include 集合；exclude 从候选集合中移除。
- [ ] include/exclude 中存在空名、NUL、未知表名或最终集合为空时，在源查询或目标写入前明确失败。
- [ ] include 与 exclude 指向同一表时，命令按排除优先处理，并在日志/结果中体现最终集合。
- [ ] 导出和导入均保持当前 JSONL v1 文件格式、gzip 输入输出、`insert`/`upsert` 参数和表级事务。
- [ ] 导出每张表使用可配置或固定的批量游标/`fetchmany` 循环，不使用 `fetchall()` 读取表数据；写文件仍采用临时文件后原子替换。
- [ ] 导入不把完整 JSONL 文档和所有行长期保存在内存中；采用流式记录处理，并在任何表写入前完成文件结构、选择集合、目标 schema、类型、主键和外键依赖预检。
- [ ] 选中表之间存在外键依赖时，导出表块和导入表块使用父表优先、子表后置的稳定拓扑顺序。
- [ ] 选中表之间存在外键环时，在写入前失败，不关闭外键检查掩盖问题。
- [ ] 选中表依赖未选中的父表时，在源导出或目标导入预检阶段明确失败；本任务不自动补齐父表、不查询目标库尝试推断外部数据，也不把问题延迟到普通写入阶段。
- [ ] 单表写入失败只回滚当前表；前序成功表保持现有表级提交语义，并输出表级处理结果。
- [ ] `database export` 可省略 `--output` 并创建默认 `data/`；已有目录路径生成 `<source>-<timestamp>.jsonl`，非目录路径要求父目录已存在。
- [ ] 现有全库 export/import、SQLite/MySQL 交叉传输、gzip 文件和零日期配置相关测试继续通过，并新增过滤、外键顺序、流式批量和错误路径测试。
- [ ] 使用文档明确全部表默认行为、include/exclude 规则、外键顺序、表级事务和大数据流式处理边界。

## Open questions

- 批量读取大小采用内部默认值 1000 条；本任务暂不新增 CLI/config 覆盖项。
- 导入采用双遍读取：第一遍从 `.jsonl`/`.jsonl.gz` 流完整预检但不写目标库；第二遍重新打开同一制品，按表级事务解码和写入。两遍之间不长期保存整份文件内容。
- 选中表依赖未选中的父表时直接预检失败；不自动补齐父表，也不做跨数据库目标数据存在性推断。

## Decisions

- 命令层级保持 `mysql dump/restore` 与 `database export/import`，不新增 database backup/restore 别名。
- `--include-table` 与 `--exclude-table` 均可重复指定；选择规则为“include（未指定则全部）再减 exclude”，exclude 优先。
- 默认全表操作，不支持本任务内的行级 WHERE 条件。
- 外键排序采用现有 schema 依赖图；父表优先、子表后置，外键环拒绝。
- 批量读取默认 1000 条，作为内部实现常量，不新增用户配置。
- 外部父表依赖在预检阶段阻止传输；只处理选中表集合内部的拓扑排序。
- 导入使用双遍读取保证完整预检先于任何写入，同时避免整文件常驻内存。
- JSONL v1 仍是唯一格式；`.jsonl.gz` 继续作为压缩制品输入/输出。
- 输出路径仅以是否为已有目录判定目录模式；不存在路径一律作为文件路径，避免自动创建疑似目录。
- 事务粒度仍为表级，`insert` 与 `upsert` 参数保持显式且不改变语义。
- 导出与导入均以流式/批量处理为目标，不能通过整表或整文件 `fetchall()`/长期内存集合规避设计问题。

## Risk

- 选中子表而未选中父表时，目标已有数据与源数据之间的引用完整性难以跨数据库统一验证；错误信息必须清楚说明外部依赖和目标前置条件。
- 流式导入若需要两遍读取，会增加 I/O；若只缓存单表块，则大表仍可能占用较多内存，需在 Plan 中设定可验证的边界。
- 表级事务意味着多表传输可能部分成功；重试 `insert` 到同一目标可能遇到已提交表的约束冲突，调用方需选择新目标或 `upsert`。
- include/exclude 过滤改变默认全库行为的实际范围，命令输出和日志必须报告最终表集合，避免误传输。
- 外键拓扑排序只能表达表级顺序，不能自动解决同表自引用、跨表循环或业务层非数据库依赖。
- 双遍读取会使大型制品产生两次读取开销，但换取预检与表级事务边界的清晰性。

## User review notes

- JSONL 导出/导入与 MySQL 原生 dump/restore 分属不同一级命令职责。
- 用户确认 `database export/import` 默认全表，支持 `--include-table` 限定和 `--exclude-table` 排除。
- 用户确认事务粒度仍为表级，并保留 `insert` / `upsert` 模式参数。
- 用户确认大表导出必须循环取数，不使用 `fetchall()`。
- 用户确认批量大小默认 1000 条。
- 用户确认导入需要解释并采用“双遍读取”方案：第一遍预检、第二遍写入。
- 用户确认外部父表依赖通过预检阻止，不自动处理或推断目标数据。
- 用户确认 `database export` 与 `mysql dump` 使用一致的默认目录、已有目录和显式文件路径规则。
