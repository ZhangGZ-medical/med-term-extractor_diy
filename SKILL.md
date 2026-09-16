---
name: med-term-extractor_diy
description: 从图片型（扫描版）PDF 中提取医学名词词条的完整管线。适用于用户要求从《常用临床医学名词》等名词类书籍 PDF 中提取"中文正名, 英文名"词条清单、构建术语对照表、词条级术语核对等任务。核心能力：OCR 坐标级版面重建（双栏分栏、y 聚类成行、英文续行合并）、拉丁簇状态机中英切分（正确处理 ABO/HLA/677C/T/蛋白C 等中文内嵌拉丁）、又称/曾称剔除、混行拆分与人工修正规则表。触发词：提取医学名词词条、图片型PDF提取词条、名词表提取、glossary extraction、术语词条提取、常用临床医学名词提取。
agent_created: true
---

# med-term-extractor_diy — 图片型 PDF 医学名词词条提取管线

把扫描版/图片型名词类 PDF（如《常用临床医学名词（2023年版）》）转换为
"中文正名, 英文名" 的纯词条清单（每行一条，无标题）。

## 适用场景

- 输入为图片型 PDF（无文字层，或文字层为劣质 OCR 不可用）
- 版面为双栏/多栏词典式排版，词条结构为「中文正名 + 英文名」
- 输出需求：仅词条行、逗号分隔、多英文名取第一个、排除又称/曾称、跨行截断合并

**不适用**：有高质量文字层的数字版 PDF（直接用 `pdf` / `pdfkit-py` 技能提取即可）。

## 工作流程（5 步）

### Step 1 探测 PDF 性质

用 PyMuPDF 检查每页 `get_text()` 长度：

- 全 0 字符 → 图片型，走本管线
- 有字符但**乱序/错字严重**（如 "血管景张家转换响(猫入/欲失)angiotesinconvertingcnzym"）→ 是劣质 OCR 文字层，**弃用**，仍走本管线
- 字符正常 → 不必 OCR，直接文本处理

### Step 2 OCR 识别（依赖 pdf-ocr-pipeline 技能）

```bash
PY="C:/Users/G1381/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
"$PY" "C:/Users/G1381/.workbuddy/skills/pdf-ocr-pipeline/scripts/pipeline.py" \
  "输入.pdf" -o "输出目录" --engine rapid --dpi 300 --keep-images
```

- 词典排版（大字、规整）用 `rapid` 引擎即可（每页 1-3 秒）；复杂版面再升 `paddle`
- 产物：`work/ocr/page_XXX.ocr.json`（含 items: box+text+score）——本技能只消费这个结构
- **注意**：pipeline 的双栏检测常失效（`two_column=false`），不要依赖其版面结构化输出，坐标重建由本技能脚本完成

### Step 3 坐标重建 + 中英切分（scripts/extract_entries.py）

```bash
"$PY" scripts/extract_entries.py \
  --ocr-dir "输出目录/work/ocr" \
  --out "entries_raw.txt" \
  --split-x 1050 --y-tol 40 \
  --noise-words "32.2,临床检验专业名词,免疫专业名词" \
  --page-cuts "5:1407"
```

脚本内部逻辑（按顺序）：

1. **分栏**：按 item box 中心 x 与 `--split-x` 分左右栏（`--img-w` 默认 2292，即 300DPI A4）
2. **聚类成行**：栏内按 y 排序聚类，容差 `--y-tol`（默认 40px；**不要调太小**，会把 OCR 拆开的英文首字母 "a"+"ngiotensin" 拆成两行）
3. **续行合并**：纯拉丁行（无中文）向上并入前一行（处理跨行英文名）
4. **行级又称截断**：先于切分执行（否则 "Addis count［又称］Addis计数" 的又称部分会污染英文起点检测）
5. **拉丁簇状态机切分中英**（本技能核心算法，见 references/algorithm.md）
6. 输出 `P页码 | 中文 | 英文 [缺英文/en含中文]` 中间文件供人工审查

### Step 4 人工修正规则表（scripts/finalize.py）

自动切分无法解决：OCR 字符噪声（Ⅸ→"区"、1→l）、一行两个词条错序混排（如
"凝血因子VI coagulation factor VII"）、又称被拆两行等。这些需要**对照 document.md
版面文件逐条判定**，写入 `finalize.py` 的修正规则（replace/add/remove 三原语），
医学知识在此介入（如判定凝血因子 VI/VII 的正确对应）。

**流程**：先跑 Step 3 输出 → 人工核对问题行 → 增补规则 → 重跑（幂等）→ 直到残留检查为空。

### Step 5 校验交付

```python
# 程序化校验：无重复中文正名、无空英文、无逗号缺失
# 随机抽 30 行人工抽检；OCR 噪声词条如实标注"待人工核对"，不擅自改写
```

输出 `提取_XXX词条.md` 到原 PDF 所在目录，**仅词条行**（用户要求不加标题/说明）。

## 关键参数与坑（详见 references/pitfalls.md）

| 参数/决策 | 值/结论 | 原因 |
|---|---|---|
| `--y-tol` | 40px（勿 <30） | 太小拆散英文词；太大合并相邻词条行（合并后的错序混行靠人工修正兜底） |
| x 间隙拆分 | **禁用** | 会误伤"中文+英文"同行结构（白细胞管型丢英文的教训） |
| 又称截断时机 | 行级预处理最先 | 又称部分含中文会干扰英文起点检测 |
| 章节边界 | `--page-cuts pg:y` | 跨章节页需按 y 切割（如第5页 y≥1407 起是下一章节） |
| 编码/标点 | 全半角统一、断词合并 `(\w+)-\s+(\w+)` | OCR 常见 "qualita- tive" 断词 |

## 与用户规则的对齐（重要）

- 多英文名只保留第一个（逗号+缩写分隔截断）
- 严格排除"又称""曾称"及其后内容
- 缺英文名/含特殊符号的词条：**按原样提取中文正名并标注缺失，不擅自改写**
- 输出仅词条，无标题、无说明文字

## 交付说明模板（对话中给出，不写入词条文件）

提取范围、OCR 引擎与置信度、词条数、待人工核对清单（OCR 噪声词条）、修正了哪些 OCR 明显误识（如 Thl→Th1）。
