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

大目录建议分批重试，避免一个大文件拖住整批任务：

```powershell
# 先跑新增支持的轻量格式
anyfile-wiki extract --inventory data/first-scan/inventory.sqlite --out data/retry-images-xls --extensions .xls,.jpg,.png,.sh --timeout-seconds 120

# 再跑小 Excel；默认使用 spreadsheet 轻量摘要，结果会逐条写入 manifest 和 inventory，即使中断也能保留已完成项
anyfile-wiki extract --inventory data/first-scan/inventory.sqlite --out data/retry-xlsx-small --extensions .xlsx --max-source-mb 2 --retry-failed --timeout-seconds 60
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

- `direct_text`：`.txt`、`.md`、`.json`、`.yaml`、`.xml`、`.sql`、`.sh`、`.ps1`、代码文件等文本类文件。

预留可选支持：

- `spreadsheet`：`.xls`、`.xlsx`。默认生成轻量表格摘要、工作表清单和前几行预览，避免大 Excel 被完整转换拖慢。
- `markitdown`：`.pdf`、`.docx`、`.pptx`。如果未安装 MarkItDown，会记录为 `skipped`，不会影响基础流程。
- `ocr`：`.jpg`、`.jpeg`、`.png`、`.bmp`、`.tif`、`.tiff`、`.webp`。OCR 使用 RapidOCR，可识别图片中的中英文文字；如果未安装 OCR 依赖，会记录为 `skipped`。

安装建议：

```powershell
python -m pip install -e .[parse]
python -m pip install -e .[ocr]
python -m pip install -e .[all]
```

说明：

- `.docx` 是 OOXML 格式，本质上是 zip + XML，Python 解析器通常可以直接读取。
- `.doc` 是旧版 Word 二进制 OLE 格式，当前不直接支持。后续建议接入 LibreOffice/WPS 这类本地转换器，把 `.doc` 转为 `.docx` 或文本后再解析。
- 图片文件不会交给通用文档转换器处理，而是走 `ocr` parser，避免出现“转换成功但正文为空”的误判。
