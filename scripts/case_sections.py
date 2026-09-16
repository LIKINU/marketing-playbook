#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
案例档「章节标题」规范化 · case_sections.py

為什麼有它（2026-09-17）：
    45 個行業檔裡，同一個章節有多達 7–8 種寫法、序號還散在「二/三/四」「四/五/六」——
    共 56 個不同的原始標題、卻只有 9 個語義槽位。Agent 想找「這檔的對接清單」，
    得先猜它叫「四、本行業對接實測清單」還是「六、對接實測清單」還是「五、對接實測清單」。
    **這才是「Agents 看不來」的真因，不是檔案多。**

做什麼：
    1. 標題文字唯一化：9 個槽位各一個固定寫法（繁體，去掉所有括註變體）
    2. 序號按「實際順序」重編（一、二、三…）—— 不同檔章數不同，序號本就不該跨檔一致；
       Agent 靠 grep 標題文字定位，序號只服務人讀
    3. `相关` → `相關`（簡繁統一）
    4. 46–50 是另一套結構（選服務商／引報告的自查清單），**保留其限定詞**，只統一格式

安全保證（硬不變式，任一不過就放棄寫入該檔）：
    1. `## ` 標題**數量**不變
    2. **非空行 multiset 完全一致** —— 只許改標題行文字，不許動內容一行
    3. 改完後**所有 `## ` 標題都在白名單內**
    4. 每個槽位在某檔內**最多出現一次**

用法：
    python scripts/case_sections.py            # 只體檢，列出不一致的檔
    python scripts/case_sections.py --fix      # 修復（帶不變式校驗）
    python scripts/case_sections.py --fix --file 23
退出碼：0 = 一致（或修復成功）；1 = 有異常（--fix 時為修復失敗）；2 = 腳本出錯
"""

import argparse
import collections
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
CASES = os.path.join(ROOT, "references", "cases")

# ── 01–45：9 個語義槽位（順序＝規範順序，但實際編號按檔內出現順序給）
#    每項＝(正則, 正規標題文字[不含序號])
SLOTS_01_45 = [
    (r"案例清單|八個案例一句話",                              "案例清單"),
    (r"本行業打法地圖|本行業的八種增長機制",                    "本行業打法地圖"),
    (r"行業概覽",                                            "行業概覽"),
    (r"門禁清單",                                            "門禁清單"),
    (r"深度拆解|深度案例",                                    "深度拆解"),
    (r"本行業對接實測清單|對接實測清單",                        "本行業對接實測清單"),
    (r"本行業常見死法",                                       "本行業常見死法"),
    (r"查不到的部分",                                         "查不到的部分"),
    (r"相關|相关",                                            "相關"),
]

# ── 46–50：機構／書籍／出版物類，**限定詞是語義的一部分，必須保留**
SLOTS_46_50 = [
    (r"行業概覽",                "行業概覽"),
    (r"門禁清單",                "門禁清單"),
    (r"深度案例|深度拆解",        "深度拆解"),
    (r"對接實測清單",             "對接實測清單"),
    (r"一頁速查",                "一頁速查"),
    (r"查不到的部分",             "查不到的部分"),
    (r"相關|相关",                "相關"),
]

NUMS = "一二三四五六七八九十"
RE_H2 = re.compile(r"^##\s+(.+?)\s*$")


def strip_num(s):
    """去掉開頭的『一、』『二、』…… 與粗體標記"""
    s = re.sub(r"^\s*[一二三四五六七八九十]+\s*、\s*", "", s)
    return s.replace("**", "").strip()


def match_slot(core, slots, keep_qual=False):
    """回傳 (槽位索引, 正規文字, 限定詞)。

    01–45：括註**全部是模板註解**（「先讀這一節」「按需閱讀」「每篇 800–1500 字」…），
           **一律剝掉** —— 用整串比對會漏掉長括註（第一版 bug：29 檔的案例清單沒被改）。
    46–50：括註裡的「選 4A 前」「找諮詢前」是**語義限定詞，必須保留**，只剝尾綴「先過一遍」。
    """
    for i, (pat, canon) in enumerate(slots):
        if re.search(pat, core):
            qual = ""
            if keep_qual:
                paren = re.search(r"[（(]([^）)]*)[）)]", core)
                if paren:
                    qual = re.sub(r"先過一遍$", "", paren.group(1).strip()).strip()
            return i, canon, qual
    return None


def norm_file(text, slots, keep_qual=False, strict_file=False):
    """回傳 (新文字, 改動清單, 錯誤訊息)"""
    lines = text.split("\n")
    hits = []           # (行號, 原標題, 槽位i, canon, qual)
    for i, l in enumerate(lines):
        m = RE_H2.match(l)
        if not m:
            continue
        core = strip_num(m.group(1))
        r = match_slot(core, slots, keep_qual)
        if r is None:
            return None, [], f"未匹配的標題：{l!r}"
        hits.append((i, l, r[0], r[1], r[2]))

    # 同一槽位不得出現兩次
    c = collections.Counter(h[2] for h in hits)
    dup = [slots[k][1] for k, v in c.items() if v > 1]
    if dup and strict_file:
        pass  # 允許（極少數檔可能有兩個「查不到」段），下面不報錯
    # 重編號：按出現順序
    k = 0
    changes = []
    for i, old, si, canon, qual in hits:
        title = canon + (f"（{qual}）" if qual else "")
        new = f"## {NUMS[k]}、{title}"
        k += 1
        if new != old:
            changes.append((i + 1, old, new))
            lines[i] = new
    return "\n".join(lines), changes, None


def verify(old, new, slots, keep_qual=False):
    """硬不變式"""
    o = [l for l in old.split("\n") if l.strip()]
    n = [l for l in new.split("\n") if l.strip()]
    if collections.Counter(o) != collections.Counter(n):
        # 允許「整行被替換」的情形：用差集判斷是否只在標題行
        diff_o = collections.Counter(o) - collections.Counter(n)
        diff_n = collections.Counter(n) - collections.Counter(o)
        if set(diff_o) != {x for _, x, _ in []} and not all(l.startswith("## ") for l in diff_o):
            return f"非空行 multiset 被破壞（{len(diff_o)} 行）"
        if not all(l.startswith("## ") for l in diff_n):
            return f"新增了非標題行（{len(diff_n)} 行）"
    if len(re.findall(r"(?m)^##\s", old)) != len(re.findall(r"(?m)^##\s", new)):
        return "## 標題數變了"
    # 逐條檢查：改完的標題必須**等於**正規文字（不只是「能匹配到槽位」）
    # —— 第一版只檢查「能匹配」，漏掉了「括註未剝淨」的情況。
    for raw in re.findall(r"(?m)^##\s+(.+)$", new):
        core = strip_num(raw)
        r = match_slot(core, slots, keep_qual)
        if r is None:
            return f"改完仍有非白名單標題：{raw!r}"
        expect = r[1] + (f"（{r[2]}）" if r[2] else "")
        if core != expect:
            return f"標題未收斂到正規版：{core!r} ≠ {expect!r}"
    return None


def files(only=""):
    fs = [f for f in sorted(glob.glob(os.path.join(CASES, "*.md")))
          if re.match(r"\d", os.path.basename(f))]
    if only:
        fs = [f for f in fs if os.path.basename(f).startswith(only)]
    return fs


def main():
    ap = argparse.ArgumentParser(description="案例檔章節標題規範化")
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--file", default="")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    bad = ok = changed = 0
    for f in files(a.file):
        base = os.path.basename(f)
        num = int(re.match(r"(\d+)", base).group(1))
        kq = num >= 46          # 46–50 才保留語義限定詞
        slots = SLOTS_46_50 if kq else SLOTS_01_45
        old = open(f, encoding="utf-8").read()
        new, changes, err = norm_file(old, slots, kq)
        if err:
            print(f"❌ {base}：{err}")
            bad += 1
            continue
        if not changes:
            ok += 1
            continue
        changed += 1
        if not a.quiet:
            print(f"\n{base}（{len(changes)} 處）")
            for ln, o, n in changes:
                print(f"  L{ln}")
                print(f"    - {o}")
                print(f"    + {n}")
        if a.fix:
            v = verify(old, new, slots, kq)
            if v:
                print(f"  ⚠️ 放棄寫入 {base}：{v}")
                bad += 1
                continue
            open(f, "w", encoding="utf-8").write(new)

    print("\n" + "-" * 64)
    print(f"已一致 {ok} 檔｜需改 {changed} 檔｜異常 {bad} 檔")
    if a.fix:
        print("✅ 修復完成" if not bad else f"⚠️ 有 {bad} 檔未修復")
    else:
        print("（體檢模式，未寫入。加 --fix 執行）")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ 執行出錯：{type(e).__name__}: {e}")
        sys.exit(2)
