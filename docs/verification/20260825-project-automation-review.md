# 项目自动化 Makefile 验证
最后修改时间: 2026-08-25 22:14:54

Review status: Draft
Flow mode: light
Stage: Verification

## Requirement alignment

实现符合 `docs/requirement/20260825-project-automation-review.md` 所定义的 Makefile 收敛目标：

- `sync` 已替换为只同步锁定开发依赖的 `deps`。
- `install` 按 plugin 预检、用户级 editable CLI 安装、CLI PATH 验证、plugin 同步的顺序执行。
- `check` 默认只读，只有 `fix=1` 才请求 Ruff 修改源码。
- `test` 默认不产生覆盖率报告；`cov=1` 仅追加覆盖率参数，不改变 pytest 的收集范围。
- `release` 仅构建 source 和 wheel 分发产物，不安装 CLI、不写入 agent plugin，也不上传。

light 模式不创建独立 Spec 或 Plan，以下内容直接按 Requirement 核对。

## Actual diff summary

- `Makefile` 收敛公共入口为 `deps`、`install`、`check`、`test`、`release`，保留容器构建与烟测作为必要项目工作流；所有命令型 target 均在 `.PHONY` 中。
- 测试配置移除 pytest 默认覆盖率参数，改由 `make test cov=1` 明确启用；CI 保留显式覆盖率门禁。
- plugin 打包测试改为校验 `install` 的预检、`uv tool install`、plugin apply 顺序，并新增 `release` 只构建产物的约束。
- README 与 Codex 说明同步改为 `make install` 管理用户级 CLI 和 plugin，`make release` 仅构建发布制品。

## Expected vs actual files

| Requirement 范围 | 实际文件 |
| --- | --- |
| 公共 Makefile 入口、`fix`/`cov` 参数与 release 边界 | `Makefile` |
| 默认测试与覆盖率开关边界 | `pyproject.toml` |
| CI 覆盖率门禁 | `.github/workflows/ci.yml` |
| plugin 安装与 release 边界的防漂移测试 | `tests/test_plugin_packaging.py` |
| 用户和 agent 使用说明 | `README.md`、`docs/codex.md` |
| 过程文档 | `docs/requirement/20260825-project-automation-review.md`、本文件 |

实际代码和说明文件均在 Requirement 的预期范围内。容器 target 未改变，且没有把 Docker 验证混入 Python 质量入口。

## Acceptance checklist

- [x] 裸 `make` 只显示公共工作流帮助，不安装、构建、发布或修改源码。
- [x] 所有命令型 target 都声明在 `.PHONY`，且没有 catch-all 规则。
- [x] `deps` 使用 `uv sync --all-groups --locked --no-install-project`；没有引入 `pip`、Poetry 或第二套锁文件工作流。
- [x] `install` 使用 `uv tool install --editable . --force`，在 plugin apply 前进行只读预检和 PATH 可见性验证。
- [x] 默认 `check` 使用 `ruff format --check`、无 `--fix` 的 `ruff check` 与 mypy；`fix=1` 展开为格式化与 `ruff check --fix`。
- [x] 默认 `test` 不启用覆盖率；`cov=1` 追加 terminal-missing 与 HTML 覆盖率报告参数，并保留相同 pytest 收集范围。
- [x] `release` 仅调用 `uv build`；已构建 source distribution 和 wheel，未隐含上传、CLI 安装或 plugin 同步。
- [x] CI 显式执行覆盖率测试，继续满足 90% 分支覆盖率门禁。

## Test results

| Command | Result |
| --- | --- |
| `make` | Passed。仅显示帮助和公开入口。 |
| `make -n install` | Passed。顺序为 plugin check、`uv tool install --editable . --force`、`dbtalk --version`、plugin apply；未实际执行，避免写入用户级 CLI 和 agent plugin。 |
| `make -n check fix=1` | Passed。Ruff format 不再带 `--check`，Ruff lint 带 `--fix`；mypy 仍只读。 |
| `make -n test cov=1` | Passed。仅追加 `--cov=dbtalk`、terminal-missing 和 HTML 报告参数。 |
| `make check` | Passed。Ruff format、Ruff lint 和 mypy 均通过；58 个 source files 无类型错误。 |
| `make test` | Passed。pytest 为 178 passed、1 skipped；`scripts/test_release.py` 为 10 passed。 |
| `make test cov=1` | Passed。178 passed、1 skipped；总覆盖率 90.04%，达到 90% 门槛，并生成 `htmlcov/`。 |
| `make release` | Passed。构建 `dist/dbtalk-0.1.0.tar.gz` 和 `dist/dbtalk-0.1.0-py3-none-any.whl`。 |
| `make deps` | Passed。锁定的全部开发依赖完成同步，且未安装项目本身。 |
| `uv lock --check` | Passed。`uv.lock` 与项目配置一致。 |
| `uv run python scripts/release.py plugin check` | Passed。Claude、Codex、Grok 的只读预检均为 READY。 |
| `uv tool dir --bin` 与 `dbtalk --version` | Passed。`C:\\Users\\leon\\.local\\bin` 位于当前终端 PATH，已安装 CLI 输出 `dbtalk, version 0.1.0`。 |
| `git diff --check` | Passed。无空白错误。 |

`uv build` 输出一条 `uv_build` 版本范围与当前 uv 版本不一致的 warning，但构建成功；该 warning 既有于本次 Makefile 改动之外，且未影响构建结果。

## Scope deviation

无实现范围偏差。实际 `make install` 未执行，因为它会覆盖用户级 editable CLI 并调用三个宿主的 plugin 安装器；已通过配方展开、PATH 检查和真实的只读 plugin preflight 验证其前置条件。

未执行 `make docker-build` 或 `make docker-smoke`。这两个 target 未在本次 diff 中修改，也不属于 Python Makefile 收敛需求的验收范围。

## Risks and incomplete items

- `make test` 使用项目的完整 `tests/` 收集范围。通常 `tests/test_manual_integration.py` 会因缺少 `DBTALK_RUN_INTEGRATION=1` 而跳过；若调用者显式设置该环境变量，手工集成测试会被纳入 `make test`。这与“test 只运行单元测试”的严格边界存在环境相关风险，后续可通过显式 pytest marker 排除或拆分测试目录消除。
- 尚未在全新用户环境实际执行 `make install`，因此没有验证真实 plugin 写入、更新和新 agent 会话加载。执行该操作需要明确授权，因为它会修改用户级 CLI 和 agent plugin 状态。

## Conclusion

在当前开发环境中，Makefile 公共入口、uv 锁定依赖、check/fix、test/cov、release 构建边界和 CI 覆盖率门禁均已按 Requirement 验证通过。验证记录保留为 `Draft`，待审阅上述 `make test` 集成测试选择风险和未执行的外部安装副作用后接受。
