---
Review status: Accepted
Flow mode: standard
Stage: Verification
---

# MySQL dump/restore 生产可用性改进计划
最后修改时间: 2026-08-28 11:34:01

## Requirement basis

本计划落实已接受的[MySQL dump/restore 生产可用性改进需求](../requirement/20260828-mysql-dump-restore-production-readiness.md)。需求已确认：

- dump 固定使用 `-B` 生成顶层 `USE`，始终传递 `--no-create-db`，不生成 `CREATE DATABASE` 或 `DROP DATABASE`。
- restore 使用 canonical MySQL DSN 连接；`--database TARGET` 是独立恢复目标，目标库必须预先存在。
- restore 只重写 `USE`，在导入客户端启动前拒绝所有数据库生命周期 DDL，不修改原始输入。
- `--skip-definer` 默认关闭，启用时只传递原生 `mysqldump --skip-definer`，不使用 `sed` 或其他文本替换。
- dump 制品先写入同目录临时文件，成功且非空后再原子发布；manifest、checksum 和 SHA-256 不在范围内。
- dump/restore 通过现有 `dbtalk` logger 输出 stderr 上的生命周期 key=value 日志。

standard 模式不单独创建 Spec；本计划固定接口、执行边界和测试策略。Plan 已被用户接受，Implementation 已完成，当前进入 Verification。

## Plan assumptions

1. 公共命令形态固定为：

   ```text
   dbtalk mysql dump    --dsn | --dsn-env [--output PATH] [--archive] [--skip-definer]
   dbtalk mysql restore --dsn | --dsn-env --input FILE [--database TARGET]
   ```

删除 `--create-database`、`--no-create-database`、`--drop-database` 和 `--no-drop-database`；数据库创建和删除继续由 `dbtalk mysql database create/drop` 负责。

2. restore 目标库优先级为 `--database`、`mysqlrestore.database`、DSN database。DSN 仍必须包含一个 database，以保持 canonical DSN 和现有连接校验；当显式目标与 DSN database 不同时，DSN 只用于连接维护库，原生 `mysql` 的导入上下文和 `USE` 都指向目标库。

3. 目标库存在性在扫描输入并拒绝数据库生命周期 DDL 后、真正导入前通过原生 MySQL client 做只读探测。探测和导入复用本机 client、mapped container、Docker fallback 的选择规则，不创建、删除或修改数据库。对 `Unknown database` 映射为明确的目标库不存在错误；其他连接或权限失败也返回非零。

4. 自动文件名冲突使用同一秒时间戳加稳定序号（例如 `-1`、`-2`）选取新路径；显式文件路径仍允许成功后原子替换已有文件。自动路径的最终发布必须避免覆盖已经存在的制品，即使冲突发生在 dump 执行期间。

5. 生命周期日志沿用现有标准库 logging 配置和 `dbtalk` logger，不引入 JSON Lines、独立日志文件或外部 logging 依赖。日志字段只使用非敏感的路径、阶段、operation id、耗时和字节数。

## Implementation steps

1. 收拢 dump 的参数和配置契约。
   - 在 `src/dbtalk/mysql/cli.py` 移除 create/drop 选项，增加 `--skip-definer`，并保持 `--archive`、`--output` 和 DSN 二选一行为。
   - 在 `src/dbtalk/mysql/dump.py` 删除 `create_database` / `drop_database` option 和 override 字段，增加 `skip_definer`；`mysqldump_command_args` 固定保留 `-B` 与 `--no-create-db`，只在显式启用时追加 `--skip-definer`。
   - 确保 `skip_definer` 贯穿本机 `mysqldump`、已映射 MySQL 容器和 Docker fallback 的每一个 native command vector；不加入文本后处理或静默兼容分支。native client 返回不支持该选项的错误时原样以受控、非敏感的非零错误结束。
   - 从 `MySQLDumpConfig`、`load_mysql_dump_config`、`dbtalk.yaml` 和 `.env.example` 删除 create/drop 配置，保留 `mysqlrestore.database` 作为可选恢复目标配置。

2. 实现 dump 制品的临时写入和安全发布。
   - 在 `dump_database` 中先解析最终路径并在其父目录创建同目录临时 `.sql`；三种客户端路径都只写该临时文件。客户端完成后检查文件存在且大小大于零。
   - gzip 路径先完成非压缩 SQL，再生成同目录临时 `.sql.gz`，检查压缩制品非空，最后统一发布；压缩、复制、校验或 native client 任一失败都清理临时文件并保持既有最终文件不变。
   - 将最终发布集中到一个 helper：显式 output 使用同目录原子替换，自动命名使用稳定序号和发布时的不覆盖保护。失败和异常路径清理所有本机临时文件以及 mapped/Docker 容器内的临时 SQL。
   - 保持现有输出目录规则和 `.sql`/`.sql.gz` 后缀规则，不添加 manifest、checksum 或保留策略。

3. 接通 restore 的独立目标库和 DDL 安全边界。
   - 在 `src/dbtalk/mysql/cli.py` 增加 `--database TARGET`，将 CLI 值与 DSN database 分开传入解析层；`resolve_restore_options` 实现 CLI、配置、DSN 的目标优先级，且向 native client 传递最终目标库。
   - 在 `src/dbtalk/mysql/restore.py` 中先读取 SQL（gzip 先解压到临时输入），使用保守的 SQL statement 扫描识别 `CREATE DATABASE` / `DROP DATABASE`（含常见 `IF EXISTS`、`IF NOT EXISTS` 形式及前导空白），一旦发现即在任何导入 client 执行前失败；不把这些语句过滤后继续执行。
   - 只对顶层 `USE` 生成临时重写输入，保留其他字节和原始换行；无 `USE` 时可直接使用解压输入。原始`.sql` 或 `.sql.gz` 永不修改，所有临时输入在成功、失败和异常路径清理。
   - DDL 扫描通过后执行只读目标库存在性探测，再进入实际 restore。local client 和 Docker fallback 的 restore command 都使用 `--database TARGET`，mapped container 的路径继续遵循既有 Unix socket 规则。

4. 增加 dump/restore 生命周期日志和可测量进度。
   - 在 dump 和 restore 的公共操作边界创建 `operation_id`，使用单调时钟计算 `elapsed_ms`，统一输出`mysql dump|restore started/progress/completed/failed`；完成事件必须包含最终 `bytes`，失败事件包含 operation id、阶段、耗时和安全错误摘要。
   - 扩展 `src/dbtalk/mysql/client.py` 的子进程执行能力：dump 对本机临时输出文件按固定间隔轮询大小；restore 以分块 feeder 统计已写入 native client 的输入字节，并在运行中发出 progress。保留当前无 shell 执行和 `MYSQL_PWD` 环境传递边界。
   - mapped container 和 Docker fallback 在 native dump 阶段无法观察容器内文件时，记录阶段性不可测量状态，并在 `docker cp` 完成后记录宿主机可测量字节；restore 的 stdin 仍可按 feeder 已发送字节统计。
   - 通过共享的错误摘要/脱敏逻辑避免日志、Click 异常和命令诊断泄露密码、完整含密码 DSN 或 SQL 内容；CLI stdout 仍只输出最终路径或结果摘要，生命周期日志只写 stderr。

5. 更新文档、skill 和自动化测试。
   - 更新 `docs/mysql.md` 与 `plugins/dbtalk/skills/dbtalk-mysql/SKILL.md`：删除 create/drop dump 参数说明，增加 `--skip-definer`、独立 `--database`、目标库预创建、DDL 拒绝、临时发布和日志语义示例。
   - 重写 `tests/test_mysql.py` 中依赖 create/drop 的命令向量、配置合并和 CLI 测试，覆盖新参数及三条 dump client 路径；补充 gzip、文件冲突、非空校验、失败清理和既有文件保护测试。
   - 在 `tests/test_mysql.py` 或新增 `tests/test_mysql_logging.py` 覆盖 restore 目标优先级、目标库探测、`USE` 重写、所有数据库 DDL 拒绝、原始输入不变、日志字段/事件顺序和敏感信息脱敏。
   - 更新 `tests/test_settings.py` 的 YAML fixture 与断言，验证 create/drop 配置不再成为 typed settings 的公开字段；必要时同步 `tests/test_unit_boundaries.py` 的配置边界断言。

## Files to change

- `src/dbtalk/mysql/cli.py`
- `src/dbtalk/mysql/dump.py`
- `src/dbtalk/mysql/restore.py`
- `src/dbtalk/mysql/client.py`
- `src/dbtalk/settings.py`
- `dbtalk.yaml`
- `.env.example`
- `docs/mysql.md`
- `plugins/dbtalk/skills/dbtalk-mysql/SKILL.md`
- `tests/test_mysql.py`
- `tests/test_mysql_logging.py`（如独立日志测试更清晰则新增）
- `tests/test_settings.py`
- `tests/test_unit_boundaries.py`（仅在配置边界测试需要同步时）

不修改 `src/dbtalk/mysql/database.py` 的数据库生命周期实现，不新增 manifest/checksum 文件，不修改 PostgreSQL 或 JSONL transfer 的行为。

## Verification plan

1. 先运行 CLI 合同检查：
   - `uv run dbtalk mysql dump --help` 必须有 `--skip-definer`，不得出现 create/drop dump 选项。
   - `uv run dbtalk mysql restore --help` 必须显示 `--database TARGET` 和必填 `--input`。
   - 用 `CliRunner` 检查 CLI stdout 只有路径/结果摘要，日志事件出现在 stderr。

2. 运行定向单元测试，覆盖：
   - dump 默认 `--no-create-db`、`-B`、`--skip-definer` 的默认/启用命令向量，以及 local、mapped container、Docker fallback 的参数传递和不支持参数失败。
   - `.sql` 与 `.sql.gz` 的临时文件、非空校验、客户端/复制/压缩失败清理、既有最终文件保护、显式输出原子替换、同秒自动命名冲突和 Docker 临时资源清理。
   - restore 的目标优先级、目标库存在性探测、`USE` 重写、gzip 输入清理、数据库 DDL 在导入 client 前拒绝、原始输入保持不变及三条执行路径。
   - `started`、`progress`、`completed`、`failed` 的 operation id、elapsed_ms、bytes、阶段和脱敏字段。

3. 运行项目既有质量入口：
   - `uv run pytest tests/test_mysql.py tests/test_mysql_logging.py tests/test_settings.py tests/test_unit_boundaries.py -q`
   - `make check`
   - `make test`
   - `git diff --check`

4. 若环境提供隔离 MySQL 实例，再执行真实集成验证：使用维护库 DSN 创建目标库，验证异库 `USE` 重写、目标库不存在时的失败、输入 DDL 拒绝、`--skip-definer` 生成结果和三类 client 路径；测试结束后只删除本次创建的临时数据库。没有授权实例时，将该项记录为未执行，不以 mock 结果替代。

## Blockers and assumptions

- 当前无已知流程阻塞；Requirement 和 Plan 已接受，Implementation 已完成，当前进入 Verification。
- `mysqldump --skip-definer` 是否存在取决于运行时客户端版本；实现不能自动降级，真实验证需要可用的 MySQL client 或对应 Docker image。
- Docker 容器内 dump 文件在复制前可能无法从宿主机观测，progress 日志在该阶段只能报告不可测量或保持最近可测量值；最终 completed bytes 仍必须可测量。
- `CREATE/DROP DATABASE` 的识别需要覆盖 mysqldump 常见注释和条件修饰语，同时避免把字符串或普通对象定义中的文本误判为数据库语句；实现和测试应采用保守扫描，无法确定时宁可拒绝恢复。
- native MySQL client 仍遵循服务器的部分失败语义；本计划不增加整体事务或自动回滚。
- `src/dbtalk/mysql/client.py` 的进程执行接口同时被 dump 和 restore 使用；实施时需保留现有测试 mock 的可替换性，并注意 Windows/Unix 的文件替换和子进程 stdin 差异。

## Risks

- 删除旧 dump create/drop CLI 和配置字段是有意的公开契约变更，旧自动化调用会在参数解析阶段失败；文档和 help 必须同步发布，数据库生命周期操作改用独立 database 命令。
- 自动输出的“无覆盖发布”与跨进程并发之间存在竞态风险；测试需覆盖已有文件和发布窗口，实施应使用平台可行的排他发布方式而非只依赖一次 `exists()` 检查。
- 原生客户端错误可能包含环境细节；错误摘要必须在日志和 CLI 结果边界统一脱敏，不能为获得诊断而回显密码、DSN 或 SQL。
- 目标库预检会增加一次连接操作；权限不足、网络抖动或客户端缺失都应在实际 restore 前明确失败，不自动创建目标库或切换到其他连接。

## Rollback

回滚只涉及源码、配置、文档和测试版本，不会撤销已完成的 dump、restore 或 database 管理操作。若新版本尚未发布，可恢复上一版本的 CLI 和 settings；若已发布，应同时恢复 CLI/help、配置字段和文档，避免只恢复实现而保留新契约。运行中产生的临时文件由 finally 清理，已发布的成功备份不由回滚流程删除或覆盖。

## User review notes

- 用户已接受本 Plan，Implementation 已完成，当前进入 Verification。
- 计划已纳入用户确认的 dump `USE`-only、restore 预存在目标库并拒绝 `CREATE/DROP DATABASE`、移除 manifest 任务，以及新增可选 `--skip-definer` 且只调用原生参数的决定。
- 当前暂无需要用户重新决策的开放项；用户审阅重点是目标库存在性预检、自动文件名冲突的排他发布，以及 Docker dump 阶段进度日志的降级语义是否符合运维使用需要。
