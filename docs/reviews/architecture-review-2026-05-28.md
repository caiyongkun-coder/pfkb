# 架构审核报告（2026-05-28）

本报告来自架构审核子代理的只读审查。审查范围包括 `src/anyfile_wiki`、`tests`、`docs`、`configs`，重点关注 AnyFile Wiki 当前 MVP 闭环、日常运行入口、隐私边界和后续扩展性。

## 架构现状

当前项目已经形成本地优先的数据资产流水线：

```text
scan -> extract -> analyze -> review -> decisions/assets/html
```

核心模块分工如下：

- 隐私策略：`src/anyfile_wiki/policy.py`
- dry-run 扫描：`src/anyfile_wiki/scan.py`
- SQLite 清单：`src/anyfile_wiki/inventory.py`
- 正文提取、OCR、Excel、超时隔离：`src/anyfile_wiki/parse.py`、`src/anyfile_wiki/extract_worker.py`
- 规则与 LLM 分析：`src/anyfile_wiki/analyze.py`、`src/anyfile_wiki/llm_client.py`、`src/anyfile_wiki/llm_config.py`
- 人工复核与批复：`src/anyfile_wiki/review.py`、`src/anyfile_wiki/review_ui.py`、`src/anyfile_wiki/review_server.py`、`src/anyfile_wiki/decisions.py`
- 最终资产索引与 HTML 浏览页：`src/anyfile_wiki/assets.py`、`src/anyfile_wiki/html.py`
- 日常断点运行：`src/anyfile_wiki/run_state.py` 和 `src/anyfile_wiki/cli.py` 中的 `_run_*_stage`

当前实现更像“多个可组合 CLI 阶段 + 一个轻量 run-state 调度器”。单命令能力较完整，但 `run` 自动闭环还没有完全覆盖 `assets` 阶段。

## 关键风险

### P0：`anyfile-wiki run` 没有真正执行 assets 阶段

证据：

- `src/anyfile_wiki/run_state.py:11` 定义 `STAGE_ORDER = ("scan", "extract", "analyze", "review", "html")`，没有 `assets`。
- `src/anyfile_wiki/run_state.py:55` 到 `src/anyfile_wiki/run_state.py:56` 已预留 `asset_dir` 和 `asset_index`，但没有对应 stage。
- `src/anyfile_wiki/cli.py:653` 到 `src/anyfile_wiki/cli.py:675` 有独立 `cmd_assets`。
- `src/anyfile_wiki/cli.py:991` 到 `src/anyfile_wiki/cli.py:999` 的 `_run_html_stage` 只是优先读取已存在的 `asset-index.jsonl`，没有确保它由本次 run 生成。
- `README.md:32` 描述 `run` 会推进复核页和 HTML 资产页，但实际不会生成 `assets/asset-index.jsonl`，除非用户手动跑 `assets` 或通过 `review-server` 提交。

影响：日常自动链路完成后，HTML 可能仍是分析索引视图，不包含人工批复后的 `asset_status`、`review_action`、`manual_tags`。这与项目目标中的完整闭环不一致。

### P0：run 的 review 阶段不可分页，超过 `review-limit` 会静默漏复核

证据：

- `src/anyfile_wiki/cli.py:222` 默认 `--review-limit` 为 1000。
- `src/anyfile_wiki/cli.py:967` 到 `src/anyfile_wiki/cli.py:977` 的 `_run_review_stage` 只取一次 `inventory.list_files(limit=...)`。
- `src/anyfile_wiki/cli.py:980` 到 `src/anyfile_wiki/cli.py:988` 随后直接把 review 标为 `complete`。
- `src/anyfile_wiki/inventory.py:152` 到 `src/anyfile_wiki/inventory.py:174` 的 `list_files` 使用 `ORDER BY last_seen_at DESC, path ASC LIMIT :limit`，没有游标续跑。

影响：真实个人目录很容易超过 1000 个文件。超出部分既不会进入 `human-review.jsonl`，也不会进入 review 统计，最终资产索引会偏向最近扫描的一小段文件。

### P1：run 各阶段游标排序标准不统一

证据：

- 扫描排序用 `Path.resolve()` 和 `casefold()`：`src/anyfile_wiki/scan.py:202` 到 `src/anyfile_wiki/scan.py:203`。
- extract 阶段游标用 SQLite 原始 `path > :after_path`：`src/anyfile_wiki/inventory.py:176` 到 `src/anyfile_wiki/inventory.py:199`。
- analyze 阶段用 Python 字符串路径比较：`src/anyfile_wiki/cli.py:919` 到 `src/anyfile_wiki/cli.py:924`。

影响：在 Windows 大小写、符号链接、相对路径/绝对路径混用、盘符大小写变化时，断点续跑顺序不完全稳定。短期可接受，但真实目录回归需要覆盖。

### P1：HTML 单文件缺少“仅本地/分享前脱敏”的边界提示

证据：

- `src/anyfile_wiki/html.py:43` 到 `src/anyfile_wiki/html.py:53` 会把 `source_path`、`records`、`tags`、`stats` 直接内嵌到 HTML。
- `docs/mvp3-html-browser.md:51` 提到方便复制、分享和离线打开。

影响：HTML 很适合本地浏览，但如果用户误分享，可能泄露本地路径、文件名、摘要、复核状态。建议在 HTML 内和文档中明确提醒“包含本地数据，分享前请脱敏”。

### P2：可选解析依赖的就绪状态还不是一等能力

证据：

- `pyproject.toml:17` 到 `pyproject.toml:33` 默认依赖只有 `PyYAML`，`markitdown/openpyxl/xlrd/rapidocr` 都在 extras。
- `src/anyfile_wiki/parse.py:163` 到 `src/anyfile_wiki/parse.py:174` 已选择 spreadsheet/OCR parser。
- `src/anyfile_wiki/review.py:257` 到 `src/anyfile_wiki/review.py:275` 会把缺依赖归类成复核原因。

影响：当前行为是安全的，会跳过并记录，但真实目录回归前最好有 `anyfile-wiki doctor` 或环境检查，提前告诉用户 OCR、Excel、PDF 能力是否可用。

## 修复建议

P0：

- 在 `src/anyfile_wiki/run_state.py` 将 `STAGE_ORDER` 扩展为 `scan, extract, analyze, review, assets, html`。
- 在 `src/anyfile_wiki/cli.py` 增加 `_run_assets_stage`，复用 `build_asset_index()` 和 `write_asset_outputs()`。
- 调整 `_run_html_stage`，优先读取本次 run 生成的 `asset-index.jsonl`，并在缺失时明确记录 fallback 原因。
- 补 `tests/test_run_state.py`：断言完整 run 后存在 `assets/asset-index.jsonl`，且 HTML 内含 `asset_status`。

P1：

- 改造 `_run_review_stage` 为可分页，使用稳定 path 游标，类似 extract/analyze。
- 给 `Inventory` 增加适合 review 的分页查询，例如 `list_files_after(..., include_dirs=False)` 或 `list_review_candidates_after`。
- 补超过 `review-limit` 的测试：第一轮 `paused`，第二轮继续，最终 review 统计覆盖全部文件。

P2：

- 统一 run 游标排序，优先使用 `normalized_path` 或新增统一 sort key。
- 增加真实目录回归命令入口文档。

P3：

- 增加环境检查入口，例如 `anyfile-wiki doctor`。
- 在 HTML 或生成日志中加入“此文件包含本地路径和摘要，分享前请脱敏”的提示。

## 是否需要修复子代理

需要。建议至少安排两个修复子代理：

- `run-assets 闭环修复子代理`：负责把 `assets` 纳入 `run-state`，确保 `run` 能产出 `assets/asset-index.jsonl` 和最终 HTML。
- `review 分页与真实目录修复子代理`：负责让 `_run_review_stage` 支持游标/分块统计，避免超过 `review-limit` 后静默漏文件。

可选第三个后续子代理：

- `doctor 与真实目录回归子代理`：负责可选依赖探测、真实目录回归命令脚本、HTML 脱敏提示验证。
