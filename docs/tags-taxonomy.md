# 标签体系说明

AnyFile Wiki 的标签体系不只是一串关键词。它继承了几个成熟工具里已经被验证过的做法：

- Paperless-ngx：文档类型、相关方、标签、全文搜索。
- Zotero：collection 做层级，tags 做细节，自动标签和人工标签分开。
- Obsidian：使用 `topic/privacy_policy` 这样的嵌套标签，方便在树状视图中展开。
- Notion：把状态、日期、人物、类型等做成结构化属性，而不是全部塞进一个标签列表。
- Google Drive Labels：标签也服务隐私、治理和敏感内容处理。
- TagSpaces：本地 sidecar 元数据，避免云服务或单一数据库锁定。
- PARA / Johnny.Decimal：保留少量稳定顶层浏览结构，避免无限嵌套。

## 当前文件

- `configs/tags.example.yaml`：默认标签体系模板。
- `configs/tags.yaml`：用户本机可复制后自定义的真实标签体系，不应提交个人化内容。
- `src/anyfile_wiki/tags.py`：标签配置读取、说明、别名归一化和格式化。

## 查看标签体系

```powershell
anyfile-wiki tags --tags-config configs/tags.example.yaml
anyfile-wiki tags --tags-config configs/tags.example.yaml --json
anyfile-wiki tags --tags-config configs/tags.example.yaml --dimension topic
anyfile-wiki tags --tags-config configs/tags.example.yaml --search privacy
```

## 设计结构

第一版保留这些维度：

- `collection/*`：给人浏览的层级，例如项目、领域、资源、归档。
- `document/*`：文件身份，例如源码、配置文件、发票、合同、身份证件、笔记。
- `topic/*`：内容主题，例如隐私策略、LLM 策略、正文提取、内容理解、人工复核。
- `workflow/*`：处理状态，例如收件箱、活跃、待复核、可归档、忽略。
- `sensitivity/*`：敏感度，例如公开、个人信息、财务、医疗、身份资料、密钥凭证。
- `source/*`：来源或相关方，后续可承接 Paperless-ngx 的 correspondent 思路。

## 自动标签与人工确认

后续分析结果应保留三层：

- `rule_tags`：规则粗标签，稳定回退和审计用。
- `model_tags`：模型建议标签，必须带置信度和证据。
- `accepted_tags`：用户确认后的最终标签，优先用于浏览和搜索。

当前 `codex-mock` 已经开始使用嵌套语义标签，例如 `topic/privacy_policy` 和 `document/source_code`。真实 LLM 接入时应继续遵守 `configs/tags.example.yaml`，不要让模型随意发明一堆不可控标签。
