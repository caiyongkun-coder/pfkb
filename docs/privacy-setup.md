# 隐私配置初始化说明

隐私配置的目标不是让用户手写一堆难懂规则，而是让用户和本地 agent 先达成共识：

- 哪些内容绝对不能读取。
- 哪些内容只能登记元数据。
- 哪些内容可以本地读取和摘要，但不能进入向量索引。
- 哪些内容可以作为知识库来源。

## 当前文件

- `configs/privacy.example.yaml`：带注释和 AI 可读说明的隐私策略模板。
- `configs/privacy.yaml`：用户本机真实配置，应由模板复制后生成，不提交个人路径。
- `configs/excludes.default.yaml`：项目默认排除规则，用来过滤系统目录、安装包、缓存、开发噪声和高风险文件。

## 给用户看的方式

直接查看当前模板或本机配置：

```powershell
anyfile-wiki privacy --privacy configs/privacy.example.yaml
anyfile-wiki privacy --privacy configs/privacy.yaml
```

只看说明和规则数量，不展开全部规则：

```powershell
anyfile-wiki privacy --privacy configs/privacy.yaml --no-rules
```

## 给 agent / 初始化向导读取的方式

输出结构化 JSON：

```powershell
anyfile-wiki privacy --privacy configs/privacy.yaml --json
```

这个 JSON 会包含：

- `purpose`：隐私配置目的。
- `priority`：策略优先级。
- `setup_questions`：初始化时应该问用户的问题。
- `path_syntax`：路径、glob、扩展名等写法说明。
- `policies`：每种策略的含义、使用场景、示例、规则数量和实际规则。

后续 OpenClaw、Hermes、Codex skill 可以先读取这个 JSON，把当前配置翻译成人类能确认的问题，再修改 `configs/privacy.yaml`。

## 初始化建议

1. 复制模板：

```powershell
Copy-Item configs/privacy.example.yaml configs/privacy.yaml
```

2. 先确认 `deny`：

把密码库、密钥、钱包、浏览器登录数据、极私密 app 数据加入 `deny`。

3. 再确认 `metadata_only`：

把财务、医疗、身份、证件扫描件等目录加入 `metadata_only`，只允许登记存在和基础属性。

4. 再确认 `no_embedding`：

把合同、客户资料、法律草稿等可以本地整理但不想进入向量索引的目录加入 `no_embedding`。

5. 最后确认 `allow`：

把桌面、文档、笔记、研究资料、知识收件箱等低风险目录加入 `allow`。

6. 先 dry-run：

```powershell
anyfile-wiki scan "$env:USERPROFILE\Documents" --privacy configs/privacy.yaml --out data/first-scan --max-entries 500
anyfile-wiki status --inventory data/first-scan/inventory.sqlite --sources
```

确认 dry-run 报告后，再进入正文提取、摘要和索引阶段。
