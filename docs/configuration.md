# 配置说明

MVP0 的配置目标是隐私优先：先决定“能不能碰这个文件”，再决定是否解析、摘要或索引。任何读取正文的动作都必须发生在策略命中之后。

## 配置文件

- `configs/privacy.example.yaml`：用户隐私策略示例。建议复制为 `configs/privacy.yaml` 后再修改。
- `configs/roots.example.yaml`：推荐扫描目录示例，用来初始化“从哪里开始盘点”。
- `configs/tags.example.yaml`：标签体系示例，用来定义 collection、document、topic、workflow、sensitivity 等维度。
- `configs/llm.example.yaml`：LLM 和云端读取边界示例。
- `configs/excludes.default.yaml`：项目默认排除规则，用于过滤系统目录、开发噪声、危险扩展名、安装包、临时文件和缓存。

路径建议统一使用 `/` 分隔符。Windows 路径可以写成 `C:/Users/<user>/Documents`，跨平台路径可以写成 `${USERPROFILE}/Documents`、`${HOME}/Documents` 或 `~/Documents`。glob 规则中 `**` 表示任意层级。

## 策略优先级

策略按固定优先级合并：

1. `deny`
2. `metadata_only`
3. `no_embedding`
4. `allow`

`deny` 永远优先。只要路径、glob、文件名或扩展名命中 `deny`，系统就不能读取正文、不能解析、不能摘要、不能写入索引。`allow` 只表示“这个范围可以考虑扫描”，不能覆盖 `deny`，也不能覆盖默认排除规则中的高风险项。

当一个文件同时命中多个策略时，使用最高优先级的动作。例如同时命中 `metadata_only` 和 `no_embedding` 时，只记录元数据，不读取正文；同时命中 `deny` 和 `allow` 时，必须拒绝访问。

## 策略语义

`deny` 用于永久禁止读取的内容，例如私密目录、密钥、密码库、钱包、浏览器 Cookie、应用内部数据库、证件资料等。命中后应在审计日志或 dry-run 报告中记录原因，但不读取文件内容。

`metadata_only` 用于“知道它存在即可”的内容，例如财务、医疗、身份材料。系统只能记录路径、文件名、大小、修改时间、扩展名、MIME 类型等不需要读取正文的信息。不要为了摘要、全文 hash、OCR 或预览而打开文件正文。

`no_embedding` 用于允许读取和提取文本、但禁止进入向量索引的内容。它可以用于合同、客户资料、法律草稿等：系统可以生成普通摘要或结构化元信息，但不能把正文或摘要写入 embedding/向量库。

`allow` 用于明确扫描范围，例如桌面、文档目录、知识库收件箱。MVP0 建议只扫描 `allow` 命中的用户目录；即使命中 `allow`，仍然要先经过 `deny` 和 `excludes.default.yaml`。

## Dry-run

第一次真实扫描前应先执行 dry-run。dry-run 只生成访问计划，不读取文件正文，不做解析，不写入全文索引或向量索引。

dry-run 报告至少应展示：

- 将被完全跳过的文件和原因：`deny`、默认排除、权限不足、文件锁定等。
- 只记录元数据的文件和原因：命中 `metadata_only`。
- 可读取但不做 embedding 的文件：命中 `no_embedding`。
- 可正常读取、解析和索引的文件：命中 `allow` 且未命中更高优先级规则。

用户确认 dry-run 结果后，真实扫描也必须重新应用同一套策略。不能因为 dry-run 已经通过，就在真实扫描时绕过规则。

## 默认排除规则

`configs/excludes.default.yaml` 是保守的默认规则，重点避免个人电脑扫描被噪声和敏感数据污染：

- 系统目录：Windows、macOS、Linux 的系统路径、回收站、临时目录、日志和缓存。
- 开发噪声：`node_modules`、虚拟环境、构建产物、测试缓存、锁文件、编译产物。
- 危险扩展名和文件名：密钥、证书、密码库、环境变量文件、浏览器凭据、钱包、SQLite/应用数据库。
- 安装包、临时文件和缓存：安装器、磁盘镜像、临时后缀、Office 临时文件、系统缩略图、浏览器缓存。

这些默认规则的行为等价于拒绝读取。后续如果需要放宽某个目录，应优先增加更精确的用户配置或专用 adapter，而不是用宽泛的 `allow` 覆盖默认风险项。

## 推荐工作流

1. 复制 `configs/privacy.example.yaml` 为本地 `configs/privacy.yaml`。
2. 先把密钥、密码库、财务、医疗、证件、浏览器数据目录加入 `deny` 或 `metadata_only`。
3. 再把桌面、文档、知识库收件箱等低风险目录加入 `allow`。
4. 执行 dry-run，检查每个目录的处理动作和命中原因。
5. 确认 dry-run 结果后再执行真实扫描。

## LLM 配置

`configs/llm.example.yaml` 控制内容理解阶段是否调用模型。默认是 `rules`，不会调用任何模型。

本地 LLM 配置示例：

```yaml
llm:
  mode: local
local:
  enabled: true
  provider: ollama
  model: qwen2.5:7b
  endpoint: http://localhost:11434
  allow_network_loopback_only: true
```

云端 LLM 配置示例：

```yaml
llm:
  mode: cloud
cloud:
  enabled: true
  provider: openai
  model: ""
  api_key_env: OPENAI_API_KEY
  risk_acknowledged: true
  allowed_paths:
    - C:/Users/<user>/Documents/PublicNotes
```

云端模式只会处理同时满足这些条件的文件：已经通过隐私策略、已经本地提取正文、`access_policy` 在 `allowed_policies` 内、路径位于 `allowed_paths` 下，并且用户已确认风险。未通过检查的文件不会上传，会被标记为需要人工处理。
