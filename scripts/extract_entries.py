# -*- coding: utf-8 -*-
"""med-term-extractor_diy 主流水线
从 pdf-ocr-pipeline 的 OCR 产物(work/ocr/page_XXX.ocr.json)提取医学名词词条。

核心算法:
  1. 按 box x 坐标分栏(split_x), 解决 pipeline 双栏检测失效
  2. 栏内按 y 聚类成行(y_tol), 纯拉丁行向上并入(续行合并)
  3. 行级又称/曾称截断(先于切分)
  4. 拉丁簇状态机中英切分(中文内嵌拉丁 ABO/HLA/677C/T/蛋白C 处理)
  5. 输出 P页码 | 中文 | 英文 [缺英文/en含中文] 供人工审查

用法:
  python extract_entries.py --ocr-dir <OCR目录> --out <输出文件> \
      [--split-x 1050] [--img-w 2292] [--y-tol 40] \
      [--noise-words "32.2,临床检验专业名词"] \
      [--page-cuts "5:1407"] [--page-range 1-5]
"""
import json, re, os, argparse, sys

def has_cjk(s):
    return bool(re.search(r'[\u4e00-\u9fff]', s))

def is_pure_latin(s):
    t = s.strip()
    return bool(t) and not has_cjk(t)

def center(box):
    return sum(p[0] for p in box) / 4, sum(p[1] for p in box) / 4

def truncate_alias(s):
    """截断又称/曾称及其后"""
    for kw in ['又称', '曾称']:
        idx = s.find(kw)
        if idx != -1:
            s = s[:idx]
    s = re.sub(r'[［\[]\s*$', '', s)
    s = s.replace('_', '')
    return s

def outside_cn(s):
    """s 中是否有括号外中文"""
    in_p = 0
    for c in s:
        if c in '（(':
            in_p += 1
        elif c in '）)':
            in_p = max(0, in_p - 1)
        elif has_cjk(c) and in_p == 0:
            return True
    return False

def cluster_lines(items, y_tol=40):
    """按 y 聚类成行, 返回 [[(cx, text), ...], ...] 行内按 x 排序"""
    items = sorted(items, key=lambda t: (t[0], t[1]))
    lines, cur, cur_y = [], [], None
    for cy, cx, text in items:
        if cur_y is None or abs(cy - cur_y) <= y_tol:
            cur.append((cx, text))
            cur_y = cy if cur_y is None else (cur_y + cy) / 2
        else:
            lines.append(cur)
            cur = [(cx, text)]
            cur_y = cy
    if cur:
        lines.append(cur)
    for ln in lines:
        ln.sort(key=lambda t: t[0])
    return lines

def en_starts(line):
    """拉丁簇状态机: 找英文起点位置列表
    规则:
      - 簇后(穿透符号/空格/数字)跟中文 → 中文内嵌拉丁, 跳过
      - 单大写簇 + 空格 + 小写 → 跳过 (蛋白C protein 型)
      - 英文段内遇中文 → 回到中文段
    """
    res = []
    state = 'cn'
    for m in re.finditer(r'[A-Za-zαβΑΒ][A-Za-zαβΑΒ0-9\-/]*', line):
        pos, clus = m.start(), m.group()
        if state == 'en':
            prev = line[max(0, pos - 3):pos]
            if has_cjk(prev):
                state = 'cn'
            else:
                continue
        after = line[m.end():]
        nxt = re.search(r'[^\s\-–/（）()、，,·:：;；。0-9]', after)
        nxt_ch = nxt.group() if nxt else ''
        if nxt_ch and has_cjk(nxt_ch):
            continue
        if re.match(r'^[A-Z]$', clus) and re.match(r'\s+[a-z]', after):
            continue
        res.append(pos)
        state = 'en'
    return res

def split_cn_en(line):
    starts = en_starts(line)
    if not starts:
        return line.strip(), ''
    pos = starts[0]
    cn = line[:pos].strip()
    en = line[pos:].strip()
    m = re.match(r'[αβΑΒ]?\s*\d*\s*[-–]?\s*$', cn)
    if m and m.group().strip():
        en_head = re.match(r'^([αβΑΒ]?\s*\d*\s*[-–]?\s*)', en)
        if en_head and en_head.group().strip():
            cn = cn[:m.start()].strip()
    cn = re.sub(r'[（(]$', '', cn).strip()
    return cn, en

def split_multi(line):
    """混行拆分: 仅当第1、2英文起点之间含中文才拆"""
    starts = en_starts(line)
    if len(starts) >= 2 and has_cjk(line[starts[0]:starts[1]]):
        p2 = starts[1]
        return split_multi(line[:p2].strip()) + split_multi(line[p2:].strip())
    return [line]

def clean_cn(cn, noise_words=()):
    cn = truncate_alias(cn)
    cn = cn.strip(' ［[]：:。，,、·')
    for w in noise_words:
        cn = re.sub(r'\s*' + re.escape(w) + r'\s*$', '', cn)
    return cn.strip(' ［[]：:。，,、·')

def clean_en(en):
    en = truncate_alias(en)
    en = re.split(r',\s*(?=[A-Za-zαβΑΒ])', en)[0]
    en = re.sub(r'^[Il1]+(?=[αβΑΒ])', '', en)
    en = re.sub(r'^([a-zA-Z])\s+(?=[a-z])', r'\1', en)  # 合并拆开的英文首字母
    en = re.sub(r'(\w+)-\s+(\w+)', r'\1\2', en)  # 断词合并 qualita- tive
    return en.strip(' ,，:：;；·.()（）-–')

def fix_cn_en_tail(cn, en):
    """cn 尾部'空格+单大写'且 en 以小写开头 → 大写移回 en 前(如 'B淋巴细胞计数 B')"""
    m = re.search(r'\s([A-Z])$', cn)
    if m and re.match(r'[a-z]', en):
        cn = cn[:m.start()].strip()
        en = m.group(1) + ' ' + en
    return cn, en

def is_noise_line(text, noise_words=()):
    t = text.strip()
    if not t:
        return True
    if t in noise_words or re.fullmatch(r'\d{2,4}', t):
        return True
    # 页眉检索字母串: 大量汉字密集且无英文
    if len(t) > 15 and not has_cjk(t) and not re.search(r'[A-Za-z]', t):
        return True
    if len(t) > 12 and re.search(r'[\u4e00-\u9fff]{12,}', t) and not re.search(r'[A-Za-z]', t):
        return True
    return False

def main():
    ap = argparse.ArgumentParser(description='OCR词条提取主流水线')
    ap.add_argument('--ocr-dir', required=True, help='pdf-ocr-pipeline输出的work/ocr目录')
    ap.add_argument('--out', required=True, help='输出中间文件路径(供人工审查)')
    ap.add_argument('--split-x', type=float, default=1050.0, help='双栏中缝x坐标(默认1050)')
    ap.add_argument('--img-w', type=float, default=2292.0, help='页面渲染宽度px(300DPI A4≈2292)')
    ap.add_argument('--y-tol', type=float, default=40.0, help='行聚类y容差px(默认40,勿<30)')
    ap.add_argument('--noise-words', default='32.2,临床检验专业名词,免疫专业名词',
                    help='逗号分隔的章节标题等噪声词')
    ap.add_argument('--page-cuts', default='', help='跨章节页切割, 如 5:1407 表示第5页y>=1407跳过; 多页用;分隔')
    ap.add_argument('--page-range', default='', help='页码范围, 如 1-5(留空=全部)')
    args = ap.parse_args()

    noise_words = tuple(w.strip() for w in args.noise_words.split(',') if w.strip())
    page_cuts = {}
    for item in args.page_cuts.split(';'):
        if ':' in item:
            pg, y = item.split(':')
            page_cuts[int(pg)] = float(y)
    pg_min, pg_max = None, None
    if args.page_range:
        m = re.match(r'(\d+)-(\d+)', args.page_range)
        if m:
            pg_min, pg_max = int(m.group(1)), int(m.group(2))

    files = sorted(f for f in os.listdir(args.ocr_dir) if re.match(r'page_\d+\.ocr\.json$', f))
    raw_lines = []
    for fn in files:
        pg = int(re.search(r'(\d+)', fn).group(1))
        if pg_min is not None and not (pg_min <= pg <= (pg_max or pg_min)):
            continue
        d = json.load(open(os.path.join(args.ocr_dir, fn), encoding='utf-8'))
        cut_y = page_cuts.get(pg)
        items = []
        for it in d['items']:
            cx, cy = center(it['box'])
            if cut_y is not None and cy >= cut_y:
                continue
            items.append((cy, cx, it['text']))
        left = [t for t in items if t[1] < args.split_x]
        right = [t for t in items if t[1] >= args.split_x]
        for col in [left, right]:
            for line_items in cluster_lines(col, y_tol=args.y_tol):
                text = ' '.join(t for _, t in line_items)
                if is_noise_line(text, noise_words):
                    continue
                raw_lines.append((pg, text))

    # 续行合并: 纯拉丁行向上并入(仅同页)
    merged = []
    for pg, text in raw_lines:
        if is_pure_latin(text) and merged and merged[-1][0] == pg:
            merged[-1] = (pg, merged[-1][1] + ' ' + text)
        else:
            merged.append((pg, text))

    entries = []
    for pg, line in merged:
        line = truncate_alias(line)
        for sub in split_multi(line):
            cn, en = split_cn_en(sub)
            cn, en = clean_cn(cn, noise_words), clean_en(en)
            cn, en = fix_cn_en_tail(cn, en)
            if not cn and not en:
                continue
            entries.append((pg, cn, en, sub))

    with open(args.out, 'w', encoding='utf-8') as f:
        for pg, cn, en, raw in entries:
            flag = ''
            if not en:
                flag = ' [缺英文]'
            elif outside_cn(en):
                flag = ' [en含中文]'
            f.write(f'P{pg} | {cn} | {en}{flag}\n')
    n_missing = sum(1 for _, c, e, _ in entries if not e)
    print(f'输出 {len(entries)} 词条 | 缺英文 {n_missing} | -> {args.out}')
    print('下一步: 人工审查问题行(grep 缺英文/en含中文), 修正后写入 finalize.py 规则表')

if __name__ == '__main__':
    main()
