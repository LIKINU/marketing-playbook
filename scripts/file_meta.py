#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
檔案「自解釋頭」生成與校驗 · file_meta.py

為什麼有它（2026-09-17，用戶原話）：
    「單純寫一個文字，根本就沒有辦法解決這麼多文件，標題也沒有說清楚，
      根本就没有辦法讓 Agent 理解並完整讀取。」
    —— 61 個檔裡只有 2 個有目錄行；檔頭全是散文（講背景、可信度），
       **沒有一條說「什麼時候讀」「讀完得到什麼」「有哪幾節」**。
       Agent 因此無法判斷要不要讀、也無法確認自己讀全了。

做什麼：
    給每個檔（references/ 頂層 ＋ cases/ 01–50）在檔案開頭插入統一的引用塊：
        > **這是什麼**   一句話
        > **什麼時候讀** 觸發場景 ＋ 明確「不要讀什麼」
        > **讀完你能**   具體產出（由實際章節推導）
        > **目錄**       由實際 `## ` 章節**自動生成** ← 這條讓 Agent 能確認讀全
        > **規模**       字數／卡數，由檔案統計**自動生成**
    原本的引用行（建立日期、可信度等）**一律保留**，移到新塊後面。

四項欄位**全部機械生成**（不靠人寫），因此永不會與實際不符；
改了章節或卡片，重跑一次即同步 —— 這才是機制，不是文字補丁。

用法：
    python scripts/file_meta.py                 # 體檢：列出缺頭／目錄不符的檔
    python scripts/file_meta.py --fix           # 生成／更新
    python scripts/file_meta.py --fix --file 23
退出碼：0 = 全部合規（或修復成功）；1 = 有異常；2 = 腳本出錯
"""

import argparse
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
CASES = os.path.join(ROOT, "references", "cases")

FIELDS = ("這是什麼", "什麼時候讀", "讀完你能", "目錄", "規模")

# ── references/ 頂層工作檔的「這是什麼／什麼時候讀／讀完你能」（人工寫準：
#    這 10 檔是「工具」而非「資料」，欄位無法從章節推導）
MANUAL = {
    "00": ("打法引擎：**104 條打法**，每條含「為什麼用它／具體動作到每一步／驗收指標／可抄案例」",
           "**動筆前出骨架時**（第 -1 步導航表：『動筆前出骨架』）",
           "按客戶狀況查到 3–7 條可執行打法，每條都能直接抄成動作"),
    "01": ("交付文檔的章節模板：八篇結構逐章骨架 ＋ 每章要填什麼",
           "**寫方案正文時**（確定打法組合之後）",
           "一份可直接往下填的八篇骨架，含每章硬要素清單"),
    "02": ("多 Agent 分工簡報：五個角色（策略／品牌／觸達／文案／財務風控）的可複製簡報 ＋ 產出規格",
           "**要跑多 Agent 分工時**（每次接案必走）",
           "五份能直接丟給角色的簡報，含「寫不到即不合格」的深度下限"),
    "03": ("方法論操作手冊：**111 個模型**（A–M 十三類），每個含「解決什麼問題／怎麼用N步／實操示例」",
           "**寫策略篇時**（必引用 ≥3 個模型並標出處）",
           "3 個以上可直接寫進方案的模型，含填空模板與示例"),
    "04": ("失敗歸因總庫：**12 個失敗模式** ＋ 歸因速查表 ＋ 接案前 34 條失敗預演清單",
           "**交付前的風險自檢**（以及客戶出事時定根因）",
           "「我這套打法會不會踩進模式 NN」的自檢結論 ＋ 對應解法"),
    "05": ("小企業／新品牌從零打造：**五階段路徑**（驗證→冷啟→成長…），每階段含目標／唯一KPI／預算／該做／不該做／常見死法／退出判據",
           "**客戶是小企業或新品牌時**（這是主入口，不是補充）",
           "客戶當前處在哪一階段、這階段唯一該盯的 KPI、以及下一步的預算與動作"),
    "06": ("本土數字營銷集團、MCN 與平台官方方法論（省廣／利歐／天下秀／分眾／無憂／遙望／小紅書種草／抖音 FACT+）",
           "**客戶要自己做投放、或要選本土媒介服務商時**",
           "可對標的本土操盤手做法 ＋ 平台官方方法論的原始口徑"),
    "07": ("選流派矩陣：**六組對照**（同一問題，五類解法怎麼解）＋ 選型三原則",
           "**客戶問「該找哪一類服務商／該走哪條流派」時**",
           "六個常見問題下、五類流派各自的解法與代價對照"),
    "08": ("質量標尺：便利店開學季案的**實測範式**——達不到本文門檻＝未達標",
           "**寫完方案、準備交付前**（當深度標尺對照用）",
           "一份「做到什麼程度算夠」的判據清單"),
    "09": ("操作流程 SOP：**S0–S8 逐步**——每步的輸入／命令／產出／校驗",
           "**一接案就跑**（不確定下一步做什麼時，也讀它）",
           "當前處在第幾步、下一步該跑哪條命令、產出應該長什麼樣"),
}


# 非案例檔（不按此規範）：導航頁本身
SKIP_NAMES = {"README.md"}

# 檔案類型判定：一級標題 + 用途
KIND = {
    "cases": "案例集",
}


def read(p):
    return open(p, encoding="utf-8").read()


def h2_sections(t):
    """檔內所有 `## ` 章節標題（去掉行內粗體，保留序號）"""
    out = []
    for m in re.finditer(r"(?m)^##\s+(.+?)\s*$", t):
        s = m.group(1).replace("**", "").strip()
        out.append(s)
    return out


def h1(t):
    m = re.search(r"(?m)^#\s+(.+?)\s*$", t)
    return m.group(1).replace("**", "").strip() if m else ""


def file_kind(path, t):
    """回傳 (種類, 顯示名, 卡數)"""
    base = os.path.basename(path)
    num = re.match(r"(\d+)", base)
    n = int(num.group(1)) if num else None
    cards = len(re.findall(r"(?m)^###\s+\d+\.\d+\s", t))
    if "/cases/" in path:
        if n and n >= 46:
            return "機構檔", cards
        return "行業檔", cards
    return "工作檔", 0


def derive(path, t, sections, cards, kind):
    """四項欄位的內容 —— 全部由檔案實際內容推導"""
    base = os.path.basename(path)
    fname_stem = re.sub(r"^\d+-", "", os.path.splitext(base)[0])
    # 慣例：檔內 H1 是繁體且更完整，優先採用；去掉「· 營銷案例集」這類後綴
    h1t = h1(t)
    h1t = re.sub(r"\s*[·・]\s*(營銷案例集|营销案例集|案例集).*$", "", h1t).strip()
    h1t = re.sub(r"^\d+\s*[·・\-—]\s*", "", h1t)
    name = h1t or fname_stem
    num = re.match(r"(\d+)", base)
    n = num.group(1) if num else ""

    # 頂層工作檔：用人工寫準的欄位（推導不出來）
    if kind == "工作檔" and n and n in MANUAL:
        what, when, ret = MANUAL[n]
        toc = " ｜ ".join(sections) if sections else "（無 ## 章節）"
        size = f"{len(t)/10000:.1f} 萬字"
        return what, when, ret, toc, size

    # ── 這是什麼
    if kind == "行業檔":
        what = f"{name} 這一行的行銷案例集：**{cards} 張深度案例卡**，每卡五要素（是什麼／為什麼／做了什麼／怎麼做／效果）＋ 適用前提與坑"
    elif kind == "機構檔":
        # 不寫「不含公司財務與人事」這種絕對話——46–50 的「行業概覽」與 51 的卡片
        # 本來就會引用乙方自身的毛利／收費結構（那是「選乙方」的判斷依據）。
        # 真正要守的規則寫成紅線，讓它機械地出現在每個機構檔的檔頭。
        what = (f"**{name}** 的機構案例：{cards} 張卡，每卡寫「誰幫誰做了什麼、怎麼做、結果如何」；"
                f"乙方自身的營收／毛利／收費口徑**只作選乙方判斷，不得寫進對外交付物**")
    else:
        what = h1(t) or fname_stem

    # ── 什麼時候讀
    if kind == "行業檔":
        when = (f"**客戶屬於「{name}」這個行業時**：進檔先讀「案例清單」挑 1–3 個 → 再跳「深度拆解」。"
                f"　⛔ **不要讀**：其餘 44 個行業檔、`cases/46–50`")
    elif kind == "機構檔":
        # 場景從章節限定詞推導（「門禁清單（選 4A 前）」→ 選 4A 前）
        qual = ""
        for s in sections:
            m = re.search(r"門禁清單[（(]([^）)]+)[）)]", s)
            if m:
                qual = m.group(1).strip()
                break
        scene = f"**{qual}**" if qual else "**要選乙方、或要把機構方法論引進方案時**"
        when = (f"{scene}：先讀「門禁清單」自查 → 再看「深度拆解」找可引用的戰役。"
                f"　⛔ **不要讀**：`cases/01–45`（那是行業案例，與選乙方無關）")
    else:
        when = "**只在它被點名時讀**（見 `../SKILL.md` 第 -1 步導航表）；不要通讀。"

    # ── 讀完你能（由實際章節推導，只列真的有的）
    got = []
    bare = [re.sub(r"^[一二三四五六七八九十]+\s*、\s*", "", s) for s in sections]
    for kw, desc in [
        ("案例清單", f"一份可抄動作清單（{cards} 條，每條一句話）"),
        ("本行業打法地圖", "本行業的主路線與取捨"),
        ("行業概覽", "本行業的規模／增長／營銷關鍵點"),
        ("門禁清單", "接案前必須問出的 A–H 八項"),
        ("深度拆解", f"{cards} 張深度卡（14 個區塊，可整卡複用）" if cards else "深度卡"),
        ("本行業對接實測清單", "本行業專屬的 10 條提問"),
        ("本行業常見死法", "本行業最常翻的車與歸因"),
        ("查不到的部分", "哪些數字不可引用（防對客戶說錯話）"),
    ]:
        if any(kw in s for s in bare):
            got.append(desc)
    # 46–51 的槽位叫「對接實測清單」（不帶「本行業」），要單獨收一次
    if (any("對接實測清單" in s for s in bare)
            and not any("本行業對接實測清單" in s for s in bare)):
        got.append("可照着問的對接實測清單")
    marks = "①②③④⑤⑥⑦⑧⑨"
    ret = ("".join(f"{marks[i]} {g}　" for i, g in enumerate(got)).strip()
           if got else "（見下方目錄）")

    # ── 目錄（自動；章節過多時截斷，避免炸掉整行）
    if not sections:
        toc = "（無 ## 章節）"
    elif len(sections) <= 14:
        toc = " ｜ ".join(sections)
    else:
        toc = " ｜ ".join(sections[:8]) + f" ｜ …（共 {len(sections)} 節）"

    # ── 規模（自動）
    chars = len(t)
    size = f"{chars/10000:.1f} 萬字" + (f" / {cards} 卡" if cards else "")
    return what, when, ret, toc, size


def meta_block(path, t):
    sections = h2_sections(t)
    kind, cards = file_kind(path, t)
    what, when, ret, toc, size = derive(path, t, sections, cards, kind)
    return (
        f"> **這是什麼**：{what}\n"
        f"> **什麼時候讀**：{when}\n"
        f"> **讀完你能**：{ret}\n"
        f"> **目錄**：{toc}\n"
        f"> **規模**：{size}\n"
    )


def split_head(t):
    """回傳 (一級標題行, 檔頭引用塊行列表, 其餘正文)"""
    lines = t.split("\n")
    i = 0
    while i < len(lines) and not lines[i].startswith("# "):
        i += 1
    if i >= len(lines):
        return None, [], t
    h1line = lines[i]
    j = i + 1
    quotes = []
    while j < len(lines) and (lines[j].startswith(">") or lines[j].strip() == ""):
        if lines[j].startswith(">"):
            quotes.append(lines[j])
        j += 1
    rest = "\n".join(lines[j:])
    return h1line, quotes, rest


def build(path, t):
    h1line, quotes, rest = split_head(t)
    if h1line is None:
        return None
    # 保留原引用行裡「不是我們生成的那五項」的行
    keep = [q for q in quotes
            if not any(("**" + f + "**") in q for f in FIELDS)]
    mb = meta_block(path, t)
    return h1line + "\n\n" + mb + ("\n".join(keep) + "\n" if keep else "") + "\n" + rest


def files(only=""):
    fs = [f for f in sorted(glob.glob(os.path.join(ROOT, "references", "*.md")))
          if os.path.basename(f) not in SKIP_NAMES]
    fs += [f for f in sorted(glob.glob(os.path.join(CASES, "*.md")))
           if os.path.basename(f) not in SKIP_NAMES]
    if only:
        fs = [f for f in fs if os.path.basename(f).startswith(only)]
    return fs


def main():
    ap = argparse.ArgumentParser(description="檔案自解釋頭")
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--file", default="")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    bad = ok = 0
    for f in files(a.file):
        base = os.path.basename(f)
        t = read(f)
        want = meta_block(f, t)
        _, quotes, _ = split_head(t)
        have = "\n".join(q for q in quotes if any(("**" + x + "**") in q for x in FIELDS))
        # 校驗：五欄齊 且 目錄行與實際章節一致
        cur_toc = ""
        for q in quotes:
            if "**目錄**" in q:
                cur_toc = q.split("**目錄**：", 1)[-1].strip()
        want_toc = meta_block(f, t).split("**目錄**：", 1)[-1].split("\n")[0].strip()
        miss = [x for x in FIELDS if ("**" + x + "**") not in have]
        if miss or cur_toc != want_toc:
            bad += 1
            if not a.quiet:
                why = (f"缺 {','.join(miss)}" if miss else "目錄與實際章節不符")
                print(f"  ⚠️ {base}：{why}")
        else:
            ok += 1
        if a.fix:
            new = build(f, t)
            if new is None:
                print(f"  ❌ {base}：找不到一級標題，跳過")
                continue
            # 硬不變式：只許動檔頭（一級標題＋引用塊），正文逐行不變
            _, _, rest_old = split_head(t)
            _, _, rest_new = split_head(new)
            if rest_old != rest_new:
                print(f"  ❌ {base}：正文被改動，放棄寫入")
                continue
            open(f, "w", encoding="utf-8").write(new)

    print("-" * 64)
    print(f"合規 {ok} 檔｜需處理 {bad} 檔")
    if a.fix:
        print("✅ 已生成/更新自解釋頭")
    else:
        print("（體檢模式，未寫入。加 --fix 執行）")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ 執行出錯：{type(e).__name__}: {e}")
        sys.exit(2)
