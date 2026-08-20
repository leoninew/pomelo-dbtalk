---
Review status: Accepted
Flow mode: light
Stage: Requirement
---

# MySQL 备份与导入需求

最后修改时间: 2026-08-20 15:31:55

## 迁移说明

本文档的已接受需求现归属 `dbtalk`。命令、配置前缀和质量门禁均以本项目为准；原实现的验证事实保留在同名历史 Verification 文档中，不能代替本项目的独立验证。

## Goal

- `dbtalk mysql dump` 接收已提供的 MySQL 连接信息后实际执行导出，而非仅打印命令。
- 优先使用本机可执行的 `mysqldump`。
- 本机没有 `mysqldump` 时，检查 Docker CLI 和本地可用的 `mysql` 镜像；满足条件时在临时容器中执行 `mysqldump`，再将 SQL 文件复制到宿主机。
- 未传递 `--output` 时，将导出文件写入当前目录的 `data/`，默认文件名为 `<database>-<timestamp>.sql`；目录不存在时自动创建。
- 传递 `--output` 且路径是已有目录时，在该目录生成同样命名规则的 dump；路径不存在或是已有文件时，将其视为文件路径，且其父目录必须已经存在。
- 将 MySQL 连接参数和默认导出选项集中到 `mysqldump` 配置组；CLI 参数可覆盖配置值。
- 验证阶段发现的静态检查失败需一并修复，使 `dbtalk` 的 ruff、format 和 mypy 检查恢复通过。
- `dbtalk mysql restore` 接收 mysqldump SQL 文件后实际导入：优先使用本机 `mysql`，缺失时使用本地已有的 Docker `mysql` 镜像；不再仅打印命令。
- restore 支持独立指定目标数据库；目标与 dump 内顶层 `USE` 不同时，导入流重定向至目标库，原 dump 文件保持不变。

## Non-goal

- 不自动拉取 Docker 镜像或安装 MySQL/Docker。
- 不在日志、标准输出或异常信息中输出密码。
- 不自动创建数据库、删除数据库或修改原 SQL dump 文件内容；显式指定 restore 目标库时，会在临时导入流中重定向顶层 `USE` 语句。

## Acceptance

- 本机存在 `mysqldump` 时直接调用，并使用环境变量传递密码。
- 本机无 `mysqldump` 时，Docker 回退仅使用本地已有的 `mysql` 镜像。
- Docker 回退完成后将 dump 文件写入用户指定路径，并清理临时容器。
- Docker 回退能将默认本机地址映射到容器可访问的宿主机地址。
- 未给 `--output` 时创建当前目录下的 `data/`，并在其中生成 `<database>-<timestamp>.sql`。
- `--output` 指向已有目录时，在其中生成 `<database>-<timestamp>.sql`；非目录路径视为文件路径，父目录不存在时明确失败。
- `mysqldump` 配置组支持 host、port、user、password、database、CREATE/DROP DATABASE 开关和默认输出目录；未配置的身份字段可由 CLI 补充。
- 全仓 `ruff check`、`ruff format --check` 与 `mypy` 通过。
- CLI 成功时输出最终 dump 文件路径；失败时返回清晰错误。
- 单元测试覆盖本机路径、Docker 回退路径和默认输出路径，无需真实 MySQL 或 Docker。
- 本机存在 `mysql` 时直接以输入文件作为 stdin 执行导入，并使用环境变量传递密码。
- 本机无 `mysql` 时，Docker 回退仅使用本地已有的 `mysql` 镜像，并将输入文件流式传入容器。
- restore 使用独立的 `mysqlrestore` 配置组的连接默认值，CLI 参数可覆盖；输入文件必须存在。
- restore 的目标数据库可通过独立的 `mysqlrestore.database` 或 `--database` 指定；指定后不会误用 dump 内的源数据库。
- restore 成功时输出导入文件路径；无本机/Docker 执行路径或导入失败时返回清晰错误。

## Risk

- Docker 回退依赖 Docker daemon 可用、MySQL 镜像已在本地且容器网络能到达目标数据库。
- Docker 不可用的具体原因由 Docker CLI 的退出状态决定；CLI 仅报告本机可识别的原因，不会自动修复 Docker 环境。
- 数据库连接或权限错误应直接报错，不应掩盖为 Docker 回退问题。
- 导入 SQL 会直接修改目标数据库；调用方必须确认目标连接信息、SQL 来源和其中的 DDL/DML 内容。
- 目录是否存在是 `--output` 的唯一目录判定条件；不存在的路径不推断为目录，以避免静默创建拼写错误的目录。
