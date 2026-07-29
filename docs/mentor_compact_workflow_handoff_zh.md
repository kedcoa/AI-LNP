# AI-LNP 工作流代码交接

## 代码位置

```text
GitHub: https://github.com/kedcoa/AI-LNP.git
Branch: codex/day-4-clean-start
基准 commit: b735615
```

```bash
git clone https://github.com/kedcoa/AI-LNP.git
cd AI-LNP
git checkout codex/day-4-clean-start
git checkout -b mentor/compact-extraction-experiment
git push -u origin mentor/compact-extraction-experiment
```

## 下载 gold-set 论文

GitHub 不保存原始论文。以下两个文件允许导师从官方 PMC Open Access 服务重新下载
九篇 gold-set 论文及 PMC 提供的 XML、PDF、图片、表格和补充材料：

```text
data/manifests/gold_source_manifest_v1.json
scripts/download_gold_sources.py
```

先预览，不下载：

```bash
python3 scripts/download_gold_sources.py --dry-run
```

下载全部九篇：

```bash
python3 scripts/download_gold_sources.py
```

只下载一篇，例如 GP-006：

```bash
python3 scripts/download_gold_sources.py --paper-id GP-006
```

脚本不需要 API key，也不会调用 LLM。它只使用 NCBI PMC 官方 OA package 服务，
并将文件保存到：

```text
data/raw/fulltext/oa_packages/<PMCID>/
data/raw/fulltext/gold_v1/xml/
```

下载后运行：

```bash
.venv-rag/bin/python -m src.rag.ingestion
.venv-rag/bin/python -m src.rag.run_pipeline
```

## 当前结果

```text
Gold papers: 9
Gold outcomes: 15
最终成功提取并合并: 10/15（66.7%）
本地候选检测: 15/15
仍缺少: GO-002, GO-003, GO-006, GO-017, GO-018
```

## 首先阅读

```text
README.md
docs/extraction/corrected_compact_workflow.md
reports/extraction/final_gold_dynamic_v1/evaluation.json
```

## 重要代码文件

| 阶段 | 文件 |
|---|---|
| 论文解析 | `src/rag/ingestion.py` |
| 全文 retrieval | `src/rag/run_pipeline.py` |
| Compact API packet | `src/rag/compact_api_packet.py` |
| 第一次 LLM call | `src/extraction/run_compact_one_call.py` |
| Complexity | `src/extraction/assess_outcome_complexity.py` |
| 普通 validation | `src/extraction/compact_validation.py` |
| Outcome candidates | `src/extraction/build_full_outcome_inventory.py`, `src/extraction/build_outcome_candidates.py` |
| Coverage 检查 | `src/extraction/check_outcome_coverage.py` |
| Repair routing | `src/extraction/route_compact_findings.py` |
| 缺失文本结果 | `src/extraction/run_missing_record_repair.py` |
| 表格/图片任务 | `src/extraction/build_missing_record_vision_tasks.py`, `src/extraction/run_missing_record_vision.py` |
| 合并结果 | `src/extraction/merge_missing_records.py` |
| 最终评估 | `src/extraction/evaluate_final_gold_dynamic.py` |

## 导师可以运行的测试

### 1. 先运行代码测试，不调用 API

测试 compact packet、validation、coverage、repair 和 merge：

```bash
PYTHONPATH=.venv-rag/lib/python3.14/site-packages \
  OPENAI_API_KEY= \
  SENSENOVA_API_KEY= \
  .venv/bin/python -m pytest -q \
  tests/test_compact_api_packet.py \
  tests/test_compact_one_call.py \
  tests/test_outcome_coverage.py \
  tests/test_missing_record_workflow.py \
  tests/test_day4_morning_repair.py \
  tests/test_day4_afternoon_selective_vision.py \
  tests/test_day4_merge.py \
  tests/test_final_gold_dynamic.py
```

运行全部测试：

```bash
PYTHONPATH=.venv-rag/lib/python3.14/site-packages \
  OPENAI_API_KEY= \
  SENSENOVA_API_KEY= \
  .venv/bin/python -m pytest -q
```

这两条命令不会进行 paid API call。

### 2. 从下载的论文重新建立 compact packets

论文已经下载并完成 ingestion 和 retrieval 后，运行：

```bash
.venv/bin/python -m src.rag.compact_api_packet \
  --output-dir data/staging/rag/mentor_compact_api_packets_v1
```

检查生成的文件：

```text
data/staging/rag/mentor_compact_api_packets_v1/GP-001.json
...
data/staging/rag/mentor_compact_api_packets_v1/GP-009.json
```

该步骤只在本地选择 evidence，不调用 LLM。

### 3. 先对一篇论文进行真实 extraction

建议先测试一篇复杂论文，例如 GP-006，不要一开始重新调用全部九篇。

导师先在自己的 `.env` 中设置：

```text
OPENAI_API_KEY
OPENAI_BASE_URL
COMPACT_EXTRACTION_MODEL
```

然后明确运行一次 paid call：

```bash
.venv/bin/python -m src.extraction.run_compact_one_call \
  --paper-id GP-006 \
  --packet-root data/staging/rag/mentor_compact_api_packets_v1 \
  --output-root data/staging/extraction/mentor_compact_one_call_v1 \
  --confirm-paid-call
```

这条命令最多调用一次 LLM，并将新测试与原来的 baseline 分开保存。它会自动运行：

```text
complexity assessment
-> first LLM extraction
-> compact validation
-> complex-paper outcome coverage check
```

检查：

```text
data/staging/extraction/mentor_compact_one_call_v1/GP-006/
  request.json
  response.json
  candidate.json
  result.json
  validation_report.json
  complexity.json
  outcome_candidates.json
  outcome_coverage.json
  manifest.json
```

重点比较：

- `request.json`：LLM 实际看到了哪些 evidence；
- `result.json`：模型提取了哪些 records；
- `validation_report.json`：schema、IDs 和 evidence 是否有效；
- `outcome_coverage.json`：哪些 evidence groups 没有匹配到提取结果；
- `manifest.json`：token usage、model、运行时间和 record 数量。

如果同一个 output directory 已经存在 response 或 result，脚本会拒绝重复付费调用。
测试不同方案时应使用新的 output directory，例如：

```text
data/staging/extraction/mentor_compact_one_call_v2
```

### 4. 使用已有结果测试整个本地检查路线

以下命令使用 repository 中已经保存的 extraction results，不进行 API call：

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= \
  .venv/bin/python -m src.extraction.run_enforced_compact_workflow_local
```

它会重新运行 complexity、candidate inventory、validation、coverage 和 repair routing，
并将报告写入：

```text
reports/extraction/enforced_compact_workflow_v1/
```

### 5. 重新计算当前 baseline 的最终 gold recovery

```bash
OPENAI_API_KEY= SENSENOVA_API_KEY= \
  .venv/bin/python -m src.extraction.evaluate_final_gold_dynamic
```

当前预期 baseline：

```text
10/15
66.7%
```

注意：这条命令评估 repository 中当前已经合并的 baseline records。导师的新单篇
extraction 必须经过 repair、merge 和 final validation 后，才能用于新的最终
gold-recovery 比较；不能仅凭 `candidate.json` 宣称 recovery 已提高。

## API 安全

`.env` 没有上传到 GitHub。不要提交或分享 `.env`。如需测试 paid API call，请使用
导师自己的 key，并先确认 paper、model、packet、调用次数和 cache 状态。
