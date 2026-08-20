---
Review status: Accepted
Flow mode: light
Stage: Requirement
---

# 压缩数据库备份需求

最后修改时间: 2026-08-20 15:23:00

## 迁移说明

本文档的已接受需求现归属 `dbtalk`。原实现的测试数量、真实数据库和临时制品仅记录在同名历史 Verification 文档中，不能作为本项目的验证结论。

## Background

`dbtalk mysql dump` 输出原生 SQL，`dbtalk database export` 输出 JSONL。两种文件在跨主机保存或传输时都可能较大，但现有命令没有统一的 gzip 备份入口，导入侧也不能直接消费压缩文件。

## Goal

- 为 `dbtalk mysql dump` 和 `dbtalk database export` 增加可选的 `--archive` 参数；提供时将导出结果写为 gzip 文件。
- `dbtalk mysql restore` 直接接受 `.sql.gz` 文件。
- `dbtalk database import` 直接接受 `.jsonl.gz` 文件。
- MySQL JSONL 导出默认将完整零日期规范化为 `null`，并可在配置中关闭；关闭时必须明确失败。
- 保持未使用备份参数时既有 `.sql` 与 `.jsonl` 输出、导入行为不变。

## Non-goal

- 不改变 MySQL 连接、JSONL 格式、导入模式或原生 SQL dump 的语义。
- 不支持 tar、多文件归档、嵌套压缩、其他压缩格式或将解压内容写入用户指定目录。
- 不在 CLI 输出中展示归档内容、密码或数据库数据。

## User scenarios

1. 管理员在 MySQL dump 时传入 `--archive`，得到可传输的 `.sql.gz` 文件；未传该参数仍得到 SQL 文件。
2. 管理员在 SQLite/MySQL JSONL 导出时传入 `--archive`，得到 `.jsonl.gz` 文件，并可直接作为 JSONL import 的输入。
3. 管理员把 `.sql.gz` 传给 `mysql restore`，命令在受控临时位置读取其中的 SQL，再按已有本机或 Docker 路径导入。

## Acceptance

- `--archive` 可用于 MySQL dump 与 JSONL export；输出路径没有 `.gz` 后缀时自动追加该后缀。
- MySQL dump 在连接非本机地址时添加 `-C` 压缩客户端与服务端传输；`localhost` 与 `127.0.0.1` 不添加该参数。
- MySQL restore 与 JSONL import 识别相应的 `.gz` 输入，并拒绝损坏或内容类型不匹配的 gzip 文件。
- SQL gzip 内容只写入自动清理的临时文件；JSONL gzip 内容在读取流中直接解析。
- 单元测试覆盖 SQL gzip 备份/还原、JSONL gzip 导出/导入以及无效 gzip 拒绝；既有未压缩测试继续通过。
- 使用说明和 MySQL skill 说明压缩命令与 gzip 格式。

## Open questions

暂无需要用户确认的未决事项。

## Decisions

- `--archive` 明确表示它会生成 gzip 文件，而非改变数据库导出内容。
- 压缩输入按 `.gz` 文件名识别；MySQL 要求解压后的逻辑文件名为 `.sql`，JSONL 要求为 `.jsonl`。
- `mysqldump --compress/-C` 只压缩客户端与服务端的传输协议，不生成 gzip 文件，因此不用于控制备份文件格式。
- `database.zero_datetime_as_null` 默认 `true`；只对 MySQL `DATE`、`DATETIME`、`TIMESTAMP` 的完整 `0000-00-00` 零日期生效，关闭后拒绝导出。文本列、`TIME` 和部分零日期不作转换。

## Risk

- SQL 解压后的内容会占用临时磁盘空间，超大备份需要预留足够空间。
- restore/import 仍会按既有语义修改目标数据库；归档压缩不提供事务级回滚。
- 将零日期转为 `null` 会丢失两者之间的语义差异；需要保留该差异的用户应关闭该配置并处理源数据。
