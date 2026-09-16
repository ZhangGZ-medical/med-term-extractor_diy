# med-term-extractor_diy — 图片型 PDF 医学名词词条提取

从扫描版/图片型名词类 PDF（如《常用临床医学名词（2023年版）》）中提取
「中文正名, 英文名」的纯词条清单，用于术语对照、术语核对、词条入库。

实战验证：从《常用临床医学名词（2023年版）》临床检验专业名词（5 页双栏词典排版，
471-475 页）提取 **459 条词条**，无重复、无缺英文。

## 目录结构

```
med-term-extractor_diy/
├── SKILL.md                     # 技能定义（供 AI Agent 调用）
├── README.md                    # 本文件：安装与使用说明
├── scripts/
│   ├── extract_entries.py       # 主流水线：OCR坐标重建 + 中英切分
│   └── finalize.py              # 人工修正规则表框架（三原语 replace/remove/add）
└── references/
    ├── algorithm.md             # 拉丁簇状态机核心算法详解
    └── pitfalls.md              # 实战踩坑记录（8 类问题与解法）
```

## 环境要求

| 依赖 | 说明 |
|---|---|
| Python 3.10+ | 用隔离 venv 运行 |
| `pdf-ocr-pipeline` 技能（已安装） | 提供 RapidOCR 环境与 `pipeline.py`（本技能只消费其 `work/ocr/page_XXX.ocr.json` 产物） |
| PyMuPDF | PDF 探测用（`python -m pip install pymupdf`） |

无需联网、无 API 费用，全流程本地 CPU 运行。

## 快速开始（5 步）

以《常用临床医学名词（2023年版）》"临床检验专业名词.pdf" 为例：

### Step 1 探测 PDF 性质

```python
import fitz
doc = fitz.open("临床检验专业名词.pdf")
for i, page in enumerate(doc):
    print(i+1, len(page.get_text().strip()))
```

- 全部为 0 → 图片型，继续 Step 2
- 有字符但乱序错字 → 劣质 OCR 文字层，**弃用**，继续 Step 2
- 字符正常 → 不必 OCR，直接文本处理（本技能不适用）

### Step 2 OCR 识别

```bash
PY="C:/Users/G1381/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
"$PY" "C:/Users/G1381/.workbuddy/skills/pdf-ocr-pipeline/scripts/pipeline.py" \
  "临床检验专业名词.pdf" -o "_ocr_work" --engine rapid --dpi 300 --keep-images
```

词典排版用 `rapid`（每页 1-3 秒）；复杂版面升 `paddle`（每页 1-4 分钟）。
**不要依赖 pipeline 的版面结构化输出**（双栏检测常失效），只用 `_ocr_work/work/ocr/` 下的 json。

### Step 3 坐标重建 + 中英切分

```bash
"$PY" "med-term-extractor_diy/scripts/extract_entries.py" \
  --ocr-dir "_ocr_work/work/ocr" \
  --out "_ocr_work/entries_raw.txt" \
  --split-x 1050 --y-tol 40 \
  --noise-words "32.2,临床检验专业名词,免疫专业名词" \
  --page-cuts "5:1407"
```

输出 `P页码 | 中文 | 英文 [缺英文/en含中文]` 中间文件。关键参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--split-x` | 1050 | 双栏中缝 x 坐标（300DPI A4 图宽 2292） |
| `--y-tol` | 40 | 行聚类容差，**勿 <30**（会拆散英文首字母） |
| `--page-cuts` | 空 | 跨章节页切割：`页码:y坐标`（y≥该值跳过），多页用 `;` 分隔 |
| `--noise-words` | 章节标题 | 逗号分隔，剔除章节标题/编号等非词条文本 |
| `--page-range` | 空 | 页码范围，如 `1-5` |

### Step 4 人工审查 + 修正规则

```bash
grep -E "缺英文|en含中文" "_ocr_work/entries_raw.txt"
```

对照 pipeline 的 `document.md`（版面文件）逐条判定问题行，把修正写入
`finalize.py` 的规则区（示例规则已内置），然后：

```bash
"$PY" "med-term-extractor_diy/scripts/finalize.py" \
  --src "_ocr_work/entries_raw.txt" \
  --out "提取_临床检验专业名词词条.md"
```

规则三原语：

```python
replace(i, '中文正名', '英文名')   # 修正行内容
remove(i)                          # 删除又称残留/噪声行
add('中文正名', '英文名')          # 新增被拆分出的词条
```

### Step 5 校验交付

finalize.py 自带残留检查（缺英文/en 含中文/重复中文正名）。再随机抽 30 行人工抽检。
OCR 噪声词条（如"因子哑抑制物"）**原样保留并列入待人工核对清单**，交付说明中列明
提取范围、置信度、修正项。

## 常见问题

**Q1：为什么 pipeline 输出的 document.md 很乱，还要用它吗？**
不用它的正文，只用两个东西：`work/ocr/*.json`（坐标数据）和 `document.md`（人工核对问题行时查版面上下文）。

**Q2：一行出现两个词条怎么办？**
状态机能拆"中文1 英文1 中文2 英文2"交错的混行；"中文中文 英文英文"顺序错乱的混行
拆不开，靠人工规则（pitfalls.md 第 8 节）。

**Q3：词条被分页截断怎么办？**
同页续行由续行合并自动处理（纯英文行向上并入）；**跨页/跨栏续行**（英文后半孤悬在
邻栏页眉）需人工规则补全，参考示例"遗传性肌营养不良基因分析 + Becker muscular dystrophy"。

**Q4：多英文名怎么处理？**
只保留第一个（`re.split(r',\s*(?=[A-Za-zαβΑΒ])', en)[0]`），如 "α2-antiplasmin, α2-AP" → "α2-antiplasmin"。

**Q5：换一本书要改什么？**
`--split-x`/`--y-tol`（版面差异）、`--noise-words`（章节标题）、`--page-cuts`（跨章节页）、
`finalize.py` 规则表（每本书的 OCR 噪声不同）。核心算法无需改动。

## 局限性

- 只处理**双栏或单栏词典式排版**；三栏以上或图文混排需扩展分栏逻辑
- 中文内嵌拉丁的极端形态（顿号分隔如 "Th1、Th2"）状态机覆盖不全，需人工兜底
- 修正规则表是"逐书定制"的：每本新书需一轮人工审查（约占总量 3-5% 的行）
- OCR 置信度 <0.85 时建议换 `paddle` 引擎重跑，或对关键页用 DeepSeek-OCR 精读
