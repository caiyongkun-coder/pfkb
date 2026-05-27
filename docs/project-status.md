# AnyFile Wiki 当前状态

更新日期：2026-05-28

## 仓库状态

- GitHub 仓库：`https://github.com/caiyongkun-coder/anyfile-wiki`
- 主分支：`main`
- 当前已推送提交：
  - `0e122cd Animate review export completion state`
  - `91a0e15 Fix review page decision feedback on file URLs`
  - `a309f97 Add human review decisions flow`
  - `322af00 Rename project to AnyFile Wiki`

## 已完成能力

- 项目已正式改名为 AnyFile Wiki。
- CLI 已统一为 `anyfile-wiki`。
- 已有隐私策略、推荐扫描目录、标签体系和 LLM 策略配置。
- 已能扫描配置路径，生成 `inventory.sqlite`、`scan-plan.md` 和 `access-log.jsonl`。
- 已能对允许读取的文件做内容提取。
- 已能生成规则版、模拟语义版和真实 LLM API 版分析结果。
- 已能生成给 agent 使用的 `knowledge-index.jsonl`、`analysis-manifest.jsonl`。
- 已能生成给人看的 `knowledge-index.md`、`tag-index.md`。
- 已能生成 `knowledge-index.html` 资产浏览页，支持中英双语、标签树、搜索、筛选、分页和详情面板。
- 已能生成 `human-review.html` 人工复核批复页。
- 人工复核页支持确认当前结果、允许本地 LLM、允许云端 LLM、已人工整理、忽略、稍后处理、保持隐私。
- 人工复核页可导出 `review-decisions.jsonl`。
- 新增 `anyfile-wiki decisions`，可读取 `review-decisions.jsonl` 并生成批复摘要。
- `file://` 静态打开时，批复按钮已能即时响应。
- 导出批复后，按钮会动画变成 `✓ 导出完成 / Exported`；后续再修改批复会恢复为待导出状态。

## 最新验证

- `python -m pytest -q`：`71 passed`
- `anyfile-wiki --help` 已包含 `decisions` 命令。
- 演示页已生成：
  - `data/review-html-demo/human-review.html`
  - `data/review-html-demo/human-review.jsonl`
  - `data/review-html-demo/human-review.md`

## 当前设计结论

- `knowledge-index.html` 和 `human-review.html` 都是静态页面，不需要后端服务。
- 静态页面只负责人类浏览和批复，不直接启动本地命令。
- 人类批复导出为 `review-decisions.jsonl` 后，由 agent 或 CLI 继续读取并执行下一步。
- 云端 LLM 必须显式授权目录和确认风险；默认不允许云端读取本地文件。

## 下一步建议

优先做“决策应用层”：

1. 读取 `review-decisions.jsonl`。
2. 把 `allow_local_llm` 转成待本地 LLM 复核队列。
3. 把 `ignore` 转成忽略清单。
4. 把 `mark_manual` 和 `manual_tags` 转成人工标签覆盖记录。
5. 把 `allow_cloud_llm` 转成云端授权候选建议，但不直接修改隐私配置。
6. 生成一份 agent 可执行的后续计划，例如 `next-actions.jsonl` 或 `decision-plan.md`。

之后再做日常运行的 `run-state.json`，让长时间扫描、提取和分析可以暂停、恢复和增量推进。
