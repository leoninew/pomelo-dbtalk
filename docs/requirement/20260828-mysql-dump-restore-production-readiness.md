---
Review status: Accepted
Flow mode: standard
Stage: Requirement
---

# MySQL dump/restore 生产可用性改进需求
最后修改时间: 2026-08-28 10:26:12

## Background

当前 `dbtalk mysql dump/restore` 已能调用本机或 Docker 中的原生 MySQL 客户端，完成整库 SQL dump、gzip 压缩和恢复。 dump 统一将数据库内容与数据库生命周期分离：只保留顶层 `USE` 以固定导入上下文，永不生成 `CREATE DATABASE` 或 `DROP DATABASE`；目标库由恢复前的独立数据库管理操作准备。存储对象默认保留原始 `DEFINER`，跨环境导出时可通过显式 `--skip-definer` 请求原生客户端去除该子句。但现有实现存在三类影响日志数据库运维的问题：

- restore 没有公开 `--database`，目标库实际被 DSN 绑定；恢复目标选择和数据库生命周期边界不够明确。
- 普通 `.sql` dump 直接写入最终路径，失败时可能留下残缺制品，默认秒级文件名还可能发生覆盖。
- dump/restore 只在 CLI 结束时输出路径，没有结构化的开始、进度、完成、耗时和字节数日志，难以监控长时间运行的日志备份任务。

本需求只处理上述三类生产可用性问题，不改变原生 `mysqldump`/`mysql` 作为执行边界。

## Goal

1. 为 `dbtalk mysql restore` 提供独立的 `--database TARGET`，明确区分连接 DSN 与恢复目标库；目标库必须在恢复前存在。
2. 在默认 dump 模式下，将顶层 `USE` 重定向到显式目标库；restore 不负责创建或删除数据库。
3. 让 dump 制品以临时文件完成写入、校验后再发布，失败不得污染既有最终制品。
4. 为 `dbtalk mysql dump` 增加可选 `--skip-definer`；默认不启用，启用时只使用 `mysqldump` 原生能力处理对象定义。
5. 为 dump/restore 增加统一的结构化生命周期日志：`started`、周期性 `progress`、`completed` 和 `failed`，至少包含 operation id、阶段、耗时和可测量字节数。
6. 同步 CLI help、MySQL 手册、plugin skill 和自动化测试，消除公开契约与实现漂移。

## Non-goal

- 不实现增量备份、binlog 备份、PITR 或按时间范围导出。
- 不实现 dump 制品加密、签名、远端对象存储或备份保留策略。
- 不默认删除或重写对象定义中的 `DEFINER`；`--skip-definer` 仅作为用户显式选择的原生客户端参数。
- 不把 dump/restore 改造成 SQLAlchemy 数据传输，也不改变原生客户端的 SQL 语义。
- 不提供全量 restore 的整体事务回滚；MySQL DDL/DML 的部分失败仍遵循客户端和服务器语义。
- 不在本需求中自动创建或删除目标数据库；restore 拒绝输入中的 `CREATE DATABASE` 和 `DROP DATABASE`，数据库生命周期必须由独立管理命令完成。

## User scenarios

### 异库恢复

运维人员使用指向已有维护库的连接 DSN，并通过 `--database` 指定已准备好的日志目标库。默认 dump 只包含顶层 `USE`，restore 将其重定向到目标库；目标库必须已存在，restore 不执行数据库创建或删除，原始 dump 不得被修改。

### 跨环境对象恢复

当目标环境没有源环境的 definer 账号时，运维人员可以显式传入 `--skip-definer` 生成适合目标环境的 dump。该选择只影响 view、trigger、procedure、function 和 event 等对象定义；恢复用户仍必须拥有目标对象的创建权限，且恢复后的对象安全上下文由 MySQL 当前用户决定。

### 失败任务保护制品

定时任务执行 dump 时，网络中断、权限失败或客户端异常退出，最终 `.sql`/`.sql.gz` 必须保持原样，不得把部分输出标记为可用备份。成功后才发布最终制品。

### 备份审计

运维平台通过 stderr 日志区分任务开始、运行中、完成和失败，并能获得 operation id、输出路径、耗时和字节数。

## Acceptance

- `dbtalk mysql restore --help` 展示 `--database TARGET`；该参数优先于 DSN/config 中的目标库，未指定时保持现有 DSN 目标库行为。
- restore 的连接 DSN 仍必须是项目支持的完整 MySQL DSN；当 `--database` 与 DSN database 不同时，连接使用 DSN 指向的维护库，导入 SQL 使用显式目标库。
- dump 的命令参数只保留 `USE` 语义，永不生成 `CREATE DATABASE` 或 `DROP DATABASE`；数据库生命周期不属于 dump 制品。
- dump 默认保留对象定义中的 `DEFINER`；传入 `--skip-definer` 时，local client、mapped container 和 Docker fallback 都必须向原生 `mysqldump` 传递该参数。
- `--skip-definer` 不得通过 `sed` 或其他文本替换实现；客户端不支持该参数时，命令应返回清晰的非零错误，不得静默降级或修改 dump 内容。
- 显式目标库模式不得执行输入中的 `CREATE DATABASE` 或 `DROP DATABASE`；对于外部或旧 dump 中的此类语句，restore 必须在执行客户端前拒绝并给出清晰错误，不得静默过滤或声称已完成数据库生命周期操作。
- restore 目标库不存在时，命令返回非零并给出清晰错误，不输出成功消息；目标库创建由独立的 `dbtalk mysql database create` 或其他明确管理流程完成。
- 普通 `.sql` 和 gzip dump 都先写入同目录临时文件；客户端失败、复制失败、压缩失败或校验失败时，临时文件被清理，既有最终文件不被替换。
- 自动生成的默认文件名发生同秒冲突时不得覆盖已有制品；显式 `--output` 仍允许用户明确更新固定路径，但更新必须在成功后原子替换。
- 成功 dump 的最终文件非空。
- dump/restore 至少输出以下结构化事件，字段使用项目现有 key=value 日志风格：`mysql dump started`、`mysql dump progress`、`mysql dump completed`、`mysql dump failed`，以及对应的 restore 事件。成功事件包含 `operation_id`、`elapsed_ms`、`bytes`；restore 进度包含已处理字节数，dump 在可测量时包含当前制品字节数。
- 生命周期日志、标准输出和异常摘要不得包含密码、完整含密码 DSN 或 SQL 制品内容；CLI 标准输出继续只输出最终路径/结果摘要。
- 单元测试覆盖目标库参数和 `USE` 重写、数据库 DDL 拒绝、`--skip-definer` 默认/启用及各客户端路径、失败时最终文件保护、文件冲突、生命周期日志和敏感信息脱敏；既有测试保持通过。
- CLI、`docs/mysql.md`、`plugins/dbtalk/skills/dbtalk-mysql/SKILL.md` 与本需求中的参数和语义一致。

## Open questions

暂无需要用户确认的未决事项。

## Decisions

- 保留 canonical DSN 要求；`--database` 是恢复目标参数，不替代连接 DSN。连接 DSN 可以指向已有维护库，目标库必须先由独立数据库管理操作创建。
- dump 只保留 `USE`，不生成 `CREATE DATABASE` 或 `DROP DATABASE`；不提供可选模式或兼容模式。
- dump 默认保留 `DEFINER`；`--skip-definer` 是显式可选参数，直接交给原生 `mysqldump`，不做文本后处理。
- restore 在执行客户端前拒绝输入中的 `CREATE DATABASE` 或 `DROP DATABASE`；目标库创建和删除必须走独立数据库管理命令。
- 默认生成文件只通过追加稳定序号解决冲突，不改变既有数据库名和秒级时间戳命名的前缀。
- 运行日志使用现有 Python logging 配置和 `dbtalk` logger，输出到 stderr；不新增独立日志文件或外部日志依赖。

## Risk

- 临时文件与最终制品的发布需要跨平台原子替换语义；实现必须在失败路径清理临时文件，验证阶段需检查异常窗口的行为。
- 原生 `mysql` 客户端在表级 DDL/DML 和部分失败方面遵循服务器语义，工具不能承诺整体回滚。
- Docker 回退路径的实时字节数可能不可见，只能保证生命周期日志和最终字节数；需要真实 Docker 环境验证客户端、复制和清理路径。
- `--skip-definer` 是否可用取决于实际 `mysqldump` 客户端版本和发行版；不同客户端需要在运行环境中通过 `mysqldump --help` 或实际命令结果确认。
- 全量测试不等同于真实 MySQL 恢复验证；至少需要一个隔离 MySQL 实例验证目标库 `USE` 重写、数据库 DDL 拒绝和日志字段。

## User review notes

用户已确认 dump 只保留 `USE`，不生成 `CREATE DATABASE` 或 `DROP DATABASE`；restore 目标库必须预先存在，并拒绝输入中的数据库生命周期 DDL。新增可选 `--skip-definer` 任务，默认保留 `DEFINER`，不使用 `sed`。
