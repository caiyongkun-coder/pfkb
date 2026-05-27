# MVP1 提取说明

MVP1 在 MVP0 的隐私策略和 inventory 之上，加入受策略门控的正文提取流程。

## 基本流程

```powershell
anyfile-wiki scan "$env:USERPROFILE\Documents" --privacy configs/privacy.yaml --out data/first-scan --max-entries 500
anyfile-wiki extract --inventory data/first-scan/inventory.sqlite --out data/first-extract
anyfile-wiki extracts --inventory data/first-scan/inventory.sqlite --stats
```

`anyfile-wiki extract` 只会处理 inventory 中同时满足以下条件的文件：

- 不是目录。
- `is_read_allowed = true`。
- `is_extract_allowed = true`。
- 文件扩展名有已知 parser。

命中 `deny` 或 `metadata_only` 的文件不会被读取正文。

## 输出

提取流程会产生两类结果：

- artifact 文件：提取后的 Markdown / 文本内容。
- `extract-manifest.jsonl`：逐条记录 `path`、`parser`、`status`、`output_path`、`error`、源文件大小和 mtime。

同时，提取结果也会写入 `inventory.sqlite` 的 `extractions` 表，方便后续查询、重跑、摘要和标签。

## 增量重跑

默认情况下，如果某个文件最近一次成功提取，且源文件大小和 mtime 没有变化，`anyfile-wiki extract` 会跳过该文件并记录 `up_to_date`。

强制重跑：

```powershell
anyfile-wiki extract --inventory data/first-scan/inventory.sqlite --out data/first-extract --force
```

只重试最近一次失败或跳过的记录：

```powershell
anyfile-wiki extract --inventory data/first-scan/inventory.sqlite --out data/first-extract --retry-failed
```

## 查看提取结果

```powershell
anyfile-wiki extracts --inventory data/first-scan/inventory.sqlite --stats
anyfile-wiki extracts --inventory data/first-scan/inventory.sqlite --status error
anyfile-wiki extracts --inventory data/first-scan/inventory.sqlite --parser direct_text
anyfile-wiki extracts --inventory data/first-scan/inventory.sqlite --json
```

## Parser 状态

当前已支持：

- `direct_text`：`.txt`、`.md`、`.json`、`.yaml`、代码文件等文本类文件。

预留可选支持：

- `markitdown`：`.pdf`、`.docx`、`.pptx`、`.xlsx`。如果未安装 MarkItDown，会记录为 `skipped`，不会影响基础流程。
