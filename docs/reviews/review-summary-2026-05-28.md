# 审核汇总与修复安排建议（2026-05-28）

本次按用户要求开了两个只读子代理：

- 架构审核：关注 MVP 闭环、日常运行入口、隐私边界和扩展性。
- 代码审核：关注最近未提交改动、摘要逻辑、HTML 标签树、复核文案和测试覆盖。

对应详细报告：

- [架构审核报告](architecture-review-2026-05-28.md)
- [代码审核报告](code-review-2026-05-28.md)

## 总体结论

当前 AnyFile Wiki 的单命令链路已经能完成真实目录测试，并且粗标签与模拟 LLM 两种模式均达成复核率目标。

但从“日常由 agent 空闲时持续推进”的角度看，`anyfile-wiki run` 还缺一个关键闭环：`assets` 没有成为 run-state 的正式阶段。也就是说，手动命令可以完成闭环，但自动日常入口还没有完全闭环。

代码层面发现的问题较小，主要是摘要质量和标签树展示可见性，适合快速修复。

## 需要优先修复的问题

### P0：run 自动闭环缺少 assets 阶段

来源：架构审核。

影响：`anyfile-wiki run` 可能生成复核页和 HTML，但不保证生成最终 `asset-index.jsonl`。这会影响 agent 后续读取统一资产索引。

建议安排子代理：需要。

建议修复范围：

- `src/anyfile_wiki/run_state.py`
- `src/anyfile_wiki/cli.py`
- `tests/test_run_state.py`

### P0：run review 阶段不可分页

来源：架构审核。

影响：真实目录超过 `review-limit` 后可能静默漏掉部分文件的复核判断。

建议安排子代理：需要。

建议修复范围：

- `src/anyfile_wiki/cli.py`
- `src/anyfile_wiki/inventory.py`
- `tests/test_run_state.py` 或新增 review 分页测试

### P1：摘要补全可能重复第二段

来源：代码审核。

影响：部分“标题 + 以下问题：+ 清单”的文档摘要可能重复句子。

建议安排子代理：需要，但可作为小修任务。

建议修复范围：

- `src/anyfile_wiki/analyze.py`
- `tests/test_analyze.py`

### P1：HTML 标签树可能隐藏平面 `document` 标签

来源：代码审核。

影响：普通文档标签计数存在，但标签树中可能不可点击筛选。

建议安排子代理：需要，但可作为小修任务。

建议修复范围：

- `src/anyfile_wiki/html.py`
- `tests/test_html.py`

### P2：HTML 缺少本地敏感数据提示

来源：架构审核。

影响：用户误分享 HTML 时可能泄露本地路径、文件名、摘要和复核状态。

建议安排子代理：可后置。

建议修复范围：

- `src/anyfile_wiki/html.py`
- `docs/mvp3-html-browser.md`
- `tests/test_html.py`

## 推荐的子代理安排

建议下一步开三个修复子代理，彼此写入范围基本可拆开：

1. `代码小修子代理`
   - 修复摘要重复和 `document` 标签树不可见问题。
   - 写入范围：`src/anyfile_wiki/analyze.py`、`src/anyfile_wiki/html.py`、`tests/test_analyze.py`、`tests/test_html.py`。

2. `run-assets 闭环子代理`
   - 把 `assets` 纳入 `run-state`。
   - 写入范围：`src/anyfile_wiki/run_state.py`、`src/anyfile_wiki/cli.py`、`tests/test_run_state.py`。

3. `review 分页子代理`
   - 让 run review 支持游标和分批，避免超过 `review-limit` 静默漏文件。
   - 写入范围：`src/anyfile_wiki/inventory.py`、`src/anyfile_wiki/cli.py`、`tests/test_run_state.py` 或新增测试文件。

因为第 2 和第 3 个子代理都可能修改 `cli.py` 和 `tests/test_run_state.py`，执行时最好先让 `代码小修子代理` 处理当前未提交的小范围问题；随后再按顺序处理 `run-assets` 和 `review 分页`，减少冲突。

## 当前建议

先安排 `代码小修子代理`。它能快速修复当前页面和摘要相关问题，风险最低。

之后安排 `run-assets 闭环子代理`，这是 MVP 真闭环的关键。

最后安排 `review 分页子代理`，它直接关系到真实个人目录的可扩展性。

## 执行记录

- 已安排 `代码小修子代理` 处理代码审核中的两个 P1/P2 问题：摘要 follow-up 重复和 `document` 平面标签树不可见。
- 子代理已完成修复，改动范围为 `src/anyfile_wiki/analyze.py`、`src/anyfile_wiki/html.py`、`tests/test_analyze.py`、`tests/test_html.py`。
- 已按顺序完成 `run-assets` 闭环修复：`anyfile-wiki run` 现在会在 review 后生成 `assets/asset-index.jsonl` 和 `assets/asset-index.md`，再生成 HTML 资产页。
- 已完成 `review` 分页修复：run 的 review 阶段现在使用路径游标分块生成复核清单，避免超过 `review-limit` 后静默遗漏后续文件。
- 已完成 run 阶段路径排序小修：extract/review/analyze 续跑统一使用规范化路径排序键，降低 Windows 路径大小写和写法差异带来的断点不稳定。
