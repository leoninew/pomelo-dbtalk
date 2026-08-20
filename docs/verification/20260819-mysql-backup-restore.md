---
Review status: Accepted
Flow mode: light
Stage: Verification
---

# MySQL 备份与导入验证

最后修改时间: 2026-08-20 15:23:00

## 迁移说明

本文是原 `housekeeper` 实现于 2026-08-19 的历史验证记录，迁入此处用于保留 MySQL dump/restore 的设计与执行证据。下文的模块路径、环境变量前缀、测试数量、真实数据库制品和结论都属于原项目；它不声明 `dbtalk` 已完成相同验证。`dbtalk` 的独立验证应在当前工作树和当前环境中重新执行，并另行记录。

## 需求对齐

- `housekeeper mysql dump` 由打印命令改为实际执行导出。
- 执行顺序为本机 `mysqldump` 优先，其次检查 Docker 和本地 `mysql` 镜像；两者不可用时输出可诊断原因并退出。
- Docker 回退在临时容器中写入 SQL 文件，通过 `docker cp` 复制到宿主机，并在 `finally` 中清理容器。
- 未传 `--output` 时会创建当前目录的 `data/` 并使用 `<database>-<timestamp>.sql` 命名；`data/` 已加入 `.gitignore`。
- `mysqldump` 配置组通过 `Settings.mysqldump` 集中加载，支持 YAML 和 `HOUSEKEEPER_MYSQLDUMP__*` 覆盖；CLI 同名参数优先级最高。
- `housekeeper mysql restore` 实际导入 SQL 文件：优先使用本机 `mysql`，缺失时使用本地 Docker `mysql` 镜像，并以 stdin 流式传入文件。
- restore 使用独立的 `mysqlrestore` 配置组；`--database` 或 `mysqlrestore.database` 会在临时导入文件中重定向 dump 的顶层数据库语句，原 dump 文件不变。

## Spec / Plan 对齐

不适用。此功能按 light / 轻量模式直接依据已接受的 Requirement 实现。

## 实际 Diff 摘要

- `src/housekeeper/mysql.py`：仅保留 Click 命令适配；dump 和 restore 分别读取独立配置组。
- `src/housekeeper/mysql_dump.py`、`src/housekeeper/mysql_restore.py`：分别实现导出和导入选项、配置合并及本机/Docker 执行路径。
- `src/housekeeper/mysql_client.py`：承载两条流程共享的进程、连接参数、Docker 镜像发现和临时容器基础设施。
- `src/housekeeper/settings.py`、`housekeeper.yaml`、`.env.example`：增加独立的 `MySQLRestoreConfig` 及 `mysqlrestore` 配置组，其中包含可选目标数据库。
- `README.md`：说明 dump/restore 配置隔离与 restore 目标库重定向语义。
- `tests/test_mysql.py`、`tests/test_settings.py`：覆盖本机和 Docker 路径、配置覆盖、目标库重定向、临时文件清理和输入文件校验。

预期变更文件与实际实现文件一致，未发现超出需求范围的代码改动。

## 验收清单

- [x] 本机存在 `mysqldump` 时直接执行，并通过环境变量传递密码。
- [x] 本机缺少 `mysqldump` 时仅使用本地已有 Docker `mysql` 镜像回退，不拉取镜像。
- [x] Docker 回退完成后复制 dump 文件并清理临时容器。
- [x] 本地 MySQL 地址在 Docker 回退中映射为 `host.docker.internal`。
- [x] 缺省输出创建 `data/` 并生成带时间戳的 SQL 文件。
- [x] `mysqldump` 配置支持连接、导出开关和默认目录，CLI 参数可逐项覆盖。
- [x] 缺少身份字段或无可执行路径时以不泄露密码的错误信息中断。
- [x] 本机存在 `mysql` 时，以输入文件 stdin 执行导入并通过环境变量传递密码。
- [x] 本机缺少 `mysql` 时，Docker 回退仅使用本地已有镜像并流式导入输入文件。
- [x] restore 使用独立的 `mysqlrestore` 配置，CLI 连接参数和目标数据库可覆盖配置。
- [x] 指定目标数据库时，临时导入文件跳过源库的 CREATE/DROP DATABASE 并重写 `USE`，原 dump 文件不变。
- [x] restore 结束后清理临时 Docker 容器和临时重定向输入文件。
- [x] 实际导入的目标库含 77 张表，与 dump 中 `CREATE TABLE` 语句数量一致。

## 命令结果

- `uv run pytest`：通过，157 项测试。
- `uv run ruff check src tests scripts/llm.py`：通过。
- `uv run ruff format --check src tests scripts/llm.py`：通过，21 个文件格式符合项目规则。
- `uv run mypy`：通过，21 个源文件无类型错误。
- `uv run housekeeper mysql restore --help`：通过，帮助信息展示独立的 `mysqlrestore` 默认值、`--database` 和必填 `--input`。
- 使用用户提供的远程 MySQL 连接信息完成真实 dump：生成 `data/mysoft_emc-20260819-110015.sql`，大小为 555,339,325 字节；临时 Docker 容器已确认清理。连接凭据仅通过临时进程环境变量提供，未写入配置、文档或命令输出。
- 使用本地 Docker `mysql` 客户端完成真实 restore：以独立目标数据库导入上述 dump，目标库含 77 张表，代表性日志表含 610,118 条记录；临时 restore 容器已确认清理。
- `git -c core.whitespace=cr-at-eol diff --check`：通过。仓库 Python 文件使用 CRLF；此选项避免 Git 将有效的行尾 CR 误报为 trailing whitespace。

## 风险与未完成项

- dump 和 restore 均没有内建超时；远端数据库较大或网络缓慢时会持续运行，直至成功、失败或被外部终止。后续可单独引入可配置超时。
- restore 会修改目标数据库中的表和数据；该操作不可作为一个整体事务回滚，调用方仍须确认目标库和 SQL 来源。
- Docker 回退在正常完成和受控失败路径中会清理临时容器；进程被外部强制终止时仍可能需要人工确认。
- 没有未完成的验收项或已知静态检查遗留项。

## 结论

dump 与 restore 均已完成并通过验证；自动化检查和真实 Docker 导出/导入均符合已接受的需求。
