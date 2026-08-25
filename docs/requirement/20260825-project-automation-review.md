# pomelo-dbtalk Makefile 审查结果

最后修改时间: 2026-08-25 22:14:54

Review status: Accepted
Flow mode: light
Stage: Requirement

## 结论

`FAIL（当前 uv 样本中最接近）`。`check fix=1` 已采用直接命令和只读默认值，但 `sync` 仍未收敛为 `deps`，`release` 错误地混合 plugin 同步与 editable 安装。

## 证据

- `Makefile:31-36` 的 check 已直接执行 ruff format/lint 和 mypy，并支持 `fix=1`。
- `Makefile:39-40` 的 test 没有统一 `cov=1` 参数。
- `Makefile:46-49` 的 release 执行 plugin check、`pip install -e .`、plugin apply。
- `Makefile:43-44` 的 `package` 才执行 `uv build`。

## 目标规范

保留 check 的直接命令结构，将 `sync` 改为 `deps`；新增 `install: uv tool install --editable . --force`，plugin 同步移入 install；test 增加 `cov=1`；release 只负责 `uv build`。
