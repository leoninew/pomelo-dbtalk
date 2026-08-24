---
Review status: Accepted
Flow mode: light
Stage: Verification
---

# MySQL 备份与导入验证

最后修改时间: 2026-08-24

## 迁移说明

本文保留原 `housekeeper` 实现于 2026-08-19 的历史验证记录，用于保存 MySQL dump/restore 的初始设计与执行证据。原记录中的模块路径、环境变量前缀、测试数量、真实数据库制品和结论均属于原项目；它们不声明 `dbtalk` 已完成相同验证。本次 `dbtalk` 的独立验证结果追加在下文“2026-08-24 dbtalk 验证更新”中。

## 2026-08-24 dbtalk 验证更新

### 需求对齐

- `dbtalk mysql dump` 仍优先调用本机 `mysqldump`。
- 本机客户端缺失且 DSN 为 `localhost` 或 `127.0.0.1` 时，Docker 对请求端口仅筛选出一个运行中容器才会进入该容器执行 `mysqldump`；该调用使用默认 Unix socket，不传 `-h`、`-P` 或 `-C`。
- 容器 dump 成功后以 `docker cp` 写入请求的宿主机路径，并在 `finally` 中删除容器内临时 SQL 文件。
- 容器无法唯一识别、Docker 命令失败或 DSN 为非本机地址时，保留既有本地 Docker `mysql` 镜像临时客户端回退；不会安装客户端、拉取镜像或猜测容器。

### 实际 Diff 摘要

- `src/dbtalk/mysql/dump.py` 增加本机端口的运行中容器发现，以及容器内 `mysqldump`、复制制品和清理临时 SQL 文件的执行路径。
- `tests/test_mysql.py` 覆盖优先级、socket 参数、省略密码参数、复制与清理、唯一与歧义匹配、Docker 启动失败。
- `docs/mysql.md` 与 MySQL plugin skill 说明容器内 socket 路径、临时客户端回退和不猜测容器的边界。

### 验收清单

- [x] 本机 `mysqldump` 优先于全部 Docker 路径。
- [x] 本机客户端缺失且唯一运行中容器匹配时，容器内 dump 不传 `-h`、`-P` 或 `-C`，密码通过 `MYSQL_PWD` 传递。
- [x] 成功路径复制 dump 到宿主机，并尝试清理容器内临时文件。
- [x] 歧义容器匹配和 Docker 启动失败不会选择容器。
- [x] 无容器路径时保留本地 Docker `mysql` 镜像回退；远端 DSN 不进行本机容器发现。
- [x] 面向用户的手册和 MySQL skill 已说明执行顺序与故障处理边界。

### 命令结果

- `git diff --cached --check`：通过。
- `uv run pytest tests/test_mysql.py --no-cov -q`：`28 passed`。
- `uv run pytest -q`：`177 passed, 1 skipped`，分支覆盖率 `90.04%`。
- `uv run ruff check .`：通过。
- `uv run ruff format --check .`：`95 files already formatted`。
- `uv run mypy src tests`：通过，`58 source files` 无类型错误。
- `uv run python scripts/test_release.py`：`10 tests`，`OK`。

### 风险与未完成项

- 本次未提供真实 Docker MySQL 容器和隔离数据库，容器发现、socket dump、`docker cp` 与清理由 subprocess mock 测试覆盖；既有手工集成测试仍因未设置 `DBTALK_RUN_INTEGRATION=1` 跳过。
- Docker 筛选到多个容器或 Docker daemon 不可用时会保守回退，不会为发现容器而启动、停止或修改任何容器。

### 当前结论

当前 `dbtalk` 工作树的专项测试、全量测试、静态检查和发布脚本测试均通过。自动化验证支持交付本次执行路径；真实 Docker MySQL 端口映射的端到端验证保留为后续在用户授权环境中的集成检查。

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
