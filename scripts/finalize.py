# -*- coding: utf-8 -*-
"""med-term-extractor_diy 人工修正规则表
对 extract_entries.py 输出的中间文件应用逐条修正规则, 输出最终词条清单。

设计:
  - 三原语: replace(定位行, 新中文, 新英文) / remove(定位行) / add(新增词条)
  - 幂等: 规则表可反复执行; 残留检查为空才算完成
  - 每本书的规则不同, 需人工对照 OCR 版面文件(document.md)逐条判定后增补

用法:
  python finalize.py --src entries_raw.txt --out 提取_XXX词条.md

示例规则(来自《常用临床医学名词(2023年版)》临床检验章实际案例):
  1. 混行拆分: "ABO 血型鉴定（正定型） determining ABO blood group of red cell ABO 血型系统抗体致新生儿溶血病检测"
     → 两条独立词条
  2. 错序归位: "凝血因子VI coagulation factor VII" → 凝血因子VI=coagulation factor VI + 凝血因子VII=coagulation factor VII
  3. 又称残留: "称J3P试验" → remove (血浆鱼精蛋白副凝试验的又称"3P试验"被OCR拆行)
  4. 噪声去除: "关节腔积液黏蛋白 日" → 去尾部"日"
"""
import re, argparse

def find(rows, cn_exact=None, cn_contains=None):
    """按 cn/en 内容匹配定位行索引。cn_exact 为空字符串时视为未指定(防误匹配)"""
    for i, (cn, en) in enumerate(rows):
        if cn_exact and cn == cn_exact:
            return i
        if cn_contains is not None and (cn_contains in cn or cn_contains in en):
            return i
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True, help='extract_entries.py 的中间输出')
    ap.add_argument('--out', required=True, help='最终词条文件路径')
    args = ap.parse_args()

    rows = []
    with open(args.src, encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\n')
            m = re.match(r'^P\d+ \| (.*) \| (.*?)( \[.*\])?$', line)
            if m:
                rows.append([m.group(1).strip(), m.group(2).strip()])
            else:
                rows.append([line, ''])

    def replace(i, cn, en):
        rows[i][0], rows[i][1] = cn, en

    def remove(i):
        rows[i][0], rows[i][1] = '', '[REMOVE]'

    def add(cn, en):
        rows.append([cn, en])

    fixes_log = []

    # ================= 以下为示例规则, 按实际任务增补 =================
    # 混行拆分: 一行两个词条(中文1 英文1 中文2 英文2 交错)
    # i = find(rows, cn_exact='ABO 血型鉴定（正定型）')
    # replace(i, 'ABO 血型鉴定（正定型）', 'determining ABO blood group of red cell')
    # add('ABO 血型系统抗体致新生儿溶血病检测', 'detection of hemolytic disease ...')

    # 错序归位(医学知识判定对应关系):
    # i = find(rows, cn_contains='VI coagulation factor VII')
    # while i is not None:
    #     replace(i, '凝血因子VI', 'coagulation factor VI')
    #     add('凝血因子VII', 'coagulation factor VII')
    #     i = find(rows, cn_contains='VI coagulation factor VII')

    # 又称残留(被OCR拆行):
    # i = find(rows, cn_contains='称J3P试验')
    # if i is not None: remove(i)

    # 尾部噪声:
    # i = find(rows, cn_exact='关节腔积液黏蛋白 日')
    # if i is not None: replace(i, '关节腔积液黏蛋白', 'articular cavity effusion mucoprotein')
    # ================= 示例规则结束 =================

    # 通用清理: 删除 cn 为空的行(纯英文残留, 其英文应已并入完整词条)
    n_empty = sum(1 for r in rows if not r[0])
    rows = [r for r in rows if r[0]]

    # 去重 + 删除标记行
    seen, dedup = set(), []
    for cn, en in rows:
        if en == '[REMOVE]' or not cn:
            continue
        key = (cn, en)
        if key in seen:
            continue
        seen.add(key)
        dedup.append([cn, en])

    with open(args.out, 'w', encoding='utf-8') as f:
        for cn, en in dedup:
            f.write(f'{cn}, {en}\n')

    print(f'最终词条数: {len(dedup)} | 删除cn空行 {n_empty} 条')
    for x in fixes_log:
        print(' -', x)
    print('--- 残留检查 ---')
    bad = 0
    for cn, en in dedup:
        if not en:
            print('  [缺英文]', cn); bad += 1
        en_no_paren = re.sub(r'[（(][^）)]*[）)]', '', en)
        if re.search(r'[\u4e00-\u9fff]', en_no_paren):
            print('  [en含中文]', cn, '|', en[:60]); bad += 1
    if not bad:
        print('  无残留')
    print('--- 复检提示: 检查重复中文正名 ---')
    from collections import Counter
    cns = Counter(c for c, _ in dedup)
    dups = {k: v for k, v in cns.items() if v > 1}
    print('  重复:', dups if dups else '无')

if __name__ == '__main__':
    main()
