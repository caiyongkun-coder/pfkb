# 代码审核报告（2026-05-28）

本报告来自代码审核子代理的只读审查。审查重点是最近未提交改动，以及 `src/anyfile_wiki/analyze.py`、`src/anyfile_wiki/html.py`、`src/anyfile_wiki/review.py` 和对应测试。

## 发现

### P2：摘要补全会在跳过标题后重复第二段

位置：[src/anyfile_wiki/analyze.py](../../src/anyfile_wiki/analyze.py)

问题：`summarize_text()` 如果先因 `title == paragraphs[0]` 把 `summary` 切到 `paragraphs[1]`，随后 `_needs_summary_followup(summary)` 为真时，循环仍从 `paragraphs[1:]` 开始，导致第二段被拼接两次。

典型输入：

```markdown
# 数据问题

以下问题：

第一条问题...
```

影响：`analyze` CLI 生成的 `knowledge-index.jsonl/.md`、后续 HTML/资产摘要展示都可能出现重复句子，属于用户可见的摘要质量回归。

建议：

- 在 `summarize_text()` 中记录当前摘要使用的段落下标。
- follow-up 拼接时从下一个段落开始，而不是固定从 `paragraphs[1:]` 开始。
- 补回归测试覆盖“第一段是标题、第二段是冒号引导句”的场景。

### P2：HTML 标签树会隐藏平面 `document` 标签

位置：[src/anyfile_wiki/html.py](../../src/anyfile_wiki/html.py)

问题：新增 `fallbackTags.document.dimension = "document"` 后，`buildTagTree()` 遇到 tag 本身等于 dimension 的情况会得到空 `localParts`，不会创建任何子节点。

规则分析里 `content_type == "document"` 会直接产生：

```json
["document", "..."]
```

因此普通文档标签会计入数量，但不出现在筛选树中，用户无法通过该标签筛选普通文档。此前该平面标签会落到 `other` 分组，至少可见。

建议：

- 在 `buildTagTree()` 中处理 `tag === dimension` 的特殊情况。
- 可以把它作为该维度下的一个叶子节点，节点 key 使用原始 tag，显示 `tagInfo(tag).zh`。
- 补测试覆盖 `tags: ["document"]` 时页面数据或渲染逻辑仍能展示该筛选项。

## 测试缺口

- `tests/test_analyze.py` 只覆盖了无标题的冒号引导摘要，没有覆盖“第一段是标题、第二段需要 follow-up”的重复拼接场景。
- `tests/test_html.py` 当前主要断言 HTML 字符串包含 fallback 配置，没有执行 JS 标签树逻辑，也没有覆盖 `tags: ["document"]` 这类平面标签等于 dimension 的筛选可见性。
- 代码审核子代理按只读要求未运行测试，避免产生 `.pytest_cache` 等工作区写入。

## 是否需要修复子代理

需要，但范围很小。建议安排一个 `代码质量修复子代理`，负责：

- 修正 `summarize_text()` 的 follow-up 起始下标。
- 修正 HTML 标签树对平面标签等于 dimension 的渲染。
- 补两个回归测试。

这组修复可与架构层 P0/P1 修复并行，因为写入范围主要集中在 `analyze.py`、`html.py` 和相关测试。
