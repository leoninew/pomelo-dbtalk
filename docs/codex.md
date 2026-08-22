# Codex 插件与 Skills

本项目提供本地 Codex 插件 `dbtalk`，将数据库操作指引作为可按任务自动选择的 skills 发布。插件定义在 [`plugins/dbtalk/.codex-plugin/plugin.json`](../plugins/dbtalk/.codex-plugin/plugin.json)，个人 marketplace 条目位于 [`.agents/plugins/marketplace.json`](../.agents/plugins/marketplace.json)。

插件本身不包含独立的数据库实现；它在本项目中通过 `uv run dbtalk` 调用同一套 CLI。因此，使用插件前仍需在项目根目录完成依赖安装：

```powershell
uv sync --all-groups
```

## 已发布 Skills

| Skill | 适用任务 | 调用命令 | 参考手册 |
| --- | --- | --- | --- |
| [`dbtalk-mysql`](../plugins/dbtalk/skills/mysql/SKILL.md) | MySQL backup、dump、restore、导入 `.sql`，或配置 `mysqldump` / `mysqlrestore`。 | `dbtalk mysql` | [MySQL 手册](mysql.md) |
| [`dbtalk-database`](../plugins/dbtalk/skills/database/SKILL.md) | 通用 query/exec，以及 SQLite、MySQL、PostgreSQL 间 JSONL 导出/导入。 | `dbtalk database` | [数据库手册](database.md) |

两个 skill 只在其职责范围内选择命令：原生 MySQL SQL 备份与还原使用 `dbtalk-mysql`；通用 SQL 操作和
跨库数据传输使用 `dbtalk-database`。它们不会替代 CLI 的参数校验或配置加载。

## 操作边界

skills 会先通过相应的 `--help` 确认可用参数，并复用 CLI 的安全约束：凭据应保存在 `.env.local` 或环境变量中，不能出现在命令行示例、日志或 JSONL 制品中。

`dbtalk-mysql` 仅使用本机客户端，或回退到本机已有 Docker `mysql` 镜像；不会安装客户端或拉取镜像。`dbtalk-database` 仅传输既有 schema 的数据；导入前必须明确目标库、制品来源和写入授权。

命令行为、配置字段和参数以 [CLI 手册](../README.md#命令手册) 与运行时 `--help` 为准；skill 文件用于让 Codex 在合适的任务中选择并安全地运行这些命令。
