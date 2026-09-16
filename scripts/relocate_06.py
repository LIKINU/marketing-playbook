#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 `references/06-本土数字营销与MCN.md` 併入 cases 庫 · relocate_06.py

為什麼（2026-09-17，用戶指令）：
    「050607 為甚麼沒放在 cases 庫裏 而且要跟 cases 庫的格式一樣」
    用戶裁定：**06 進 cases；05/07 只統一標題**（後者由 top_titles.py 處理）。

06 為什麼原本不在 cases：
    它是「機構＋操盤手＋平台模型」的調研報告，用 `# A. / ## A1.` 分塊，
    與 cases 庫的 `行業概覽／門禁清單／深度拆解／對接實測清單／查不到的部分／相關`
    六槽結構不同。但內容本身是好的（每卡六段：定位／商業模式／操盤手法／失敗歸因／
    可複用套路／反面教訓），**不為了搬家把內容砍掉**——只重排結構。

做什麼：
    1. 29 個 `## X#.` 區塊 → cases 卡片 `### 3.N 標題`（3.1–3.29，按檔內實際順序重編）
    2. 四組用粗體組標示：甲 本土營銷集團／乙 MCN／丙 新消費操盤／丁 平台模型
       （用粗體而非 `## `，因為 cases 的 `## ` 是六個固定槽位）
    3. 卡內原本的 `### ` 小節降一級為 `#### `
    4. 補上原本缺的槽位：一、行業概覽／二、門禁清單／四、對接實測清單／六、相關
    5. 原本五節「查不到的部分」降為 `### `，收進 `## 五、查不到的部分`
    6. 加一條 `> ⚠️ 用法紅線`（本檔含機構財務足迹，不得寫進交付物）
    7. 刪原檔、全庫更新引用

硬不變式（任一不過就不寫入）：
    1. 原文的**非標題行逐行全數出現在新文**（卡片正文零損失）
    2. 新檔恰好 6 個 `## `，且全落在 46–51 的槽位白名單內
    3. 卡片數 = 30

用法：
    python scripts/relocate_06.py            # 體檢（不寫入）
    python scripts/relocate_06.py --fix
退出碼：0 = 成功；1 = 不變式失敗；2 = 腳本出錯
"""

import argparse
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
REF = os.path.join(ROOT, "references")
CASES = os.path.join(REF, "cases")

SRC = os.path.join(REF, "06-本土数字营销与MCN.md")
DST = os.path.join(CASES, "51-本土数字营销与MCN.md")

# ── 卡片標題對照（原 `## X#. …` → 新標題；股票代碼不進標題，正文裡有）
TITLES = {
    "A1": "省廣集團", "A2": "利歐數字", "A3": "引力傳媒", "A4": "天下秀 IMS",
    "A5": "微播易 / 火星文化", "A6": "分眾傳媒",
    "B1": "無憂傳媒", "B2": "遙望科技", "B3": "蜂群文化", "B4": "Papitube",
    "C1": "元氣森林", "C2": "花西子（重點復盤）", "C3": "鐘薛高（從「雪糕刺客」到破產）",
    "C4": "Ubras", "C5": "王小滷", "C6": "王飽飽",
    "C7": "完美日記 / 逸仙電商（簡略版）", "C8": "三頓半（簡略版）",
    "C9": "新消費品牌的集體退潮（2021–2024）合輯",
    "A7": "平台官方方法論：小紅書種草 / 抖音 FACT+",
    "D1": "阿里：AIPL → DEEPLINK", "D2": "天貓：FAST 與 GROW",
    "D3": "京東：4A → JD GOAL", "D4": "抖音／巨量引擎：O-5A 與巨量雲圖",
    "D5": "騰訊廣告：5R", "D6": "其他平台的模型（B 站 MATES / 知乎 DEEP / 快手）",
    "D7": "所有模型的橫向對比與共同局限", "D8": "可直接複用的套路", "D9": "反面教訓",
}

# ── 卡片順序（= 輸出順序，也就是 3.1–3.29 的編號順序）
#    原檔的物理順序是 A1…A6,A7,B1…B4,C1…C9,D1…D9 —— A7（平台官方方法論）
#    夾在 A6 和 B1 之間。為了讓「甲/乙/丙/丁」四組連續、序號不跳，
#    這裡按區塊重排：A7 移到丁組開頭（詳見 transform）。
ORDER = ["A1", "A2", "A3", "A4", "A5", "A6",
         "B1", "B2", "B3", "B4",
         "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9",
         "A7", "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9"]
IDX = {k: i + 1 for i, k in enumerate(ORDER)}

GROUPS = [
    ("A1", "**甲、本土數字營銷與媒介集團**（要買量、要媒介代理時讀）"),
    ("B1", "**乙、MCN 機構**（要投達人、要建內容矩陣時讀）"),
    ("C1", "**丙、新消費品牌操盤複盤**（看別人怎麼翻車，比看成功案例有用）"),
    ("A7", "**丁、各平台消費者資產模型**（平台官方方法論：只能照做，不能改）"),
]

CHABU = ["公司財務與業務數據缺失", "關鍵數字存在矛盾", "模型細節未能核實",
         "MCN 分成比例的具體數字", "其他未展開的部分"]

H1 = "# 本土數字營銷與 MCN · 機構案例集"

REDLINE = ("> ⚠️ **用法紅線**：本檔比其他機構檔多一層「機構財務足迹」（營收結構／毛利／應收帳款）。"
           "**那是給你判斷「這家乙方能不能接你的單」用的，不是案例內容**——"
           "嚴禁把機構自身的營收、利潤、員工數寫進對客戶的交付物（見 `cases/README.md` §六）。")

OVERVIEW = """## 一、行業概覽

- **收費模式三種，對應三種完全不同的公司**：① 媒介代理賺**返點差價**（媒體給代理的返點通常 3%–15%，代理讓渡一部分給廣告主，自留 1%–5%）【行業認知】；② 內容與創意按項目收費；③ 達人／MCN 端抽成（行業訪談常見 10%–30%，**無單一權威口徑，只能當談判參考，不能寫進合同模板**）。**接案第一件事是問清「這筆錢是服務費還是過帳」。**
- **上市與非上市是兩個資料世界**：媒介代理集團多為上市公司（財報可查）；MCN 與創意熱店幾乎全部未上市，**規模、營收、達人數全靠自報**，引用前必須先降級。
- **毛利極薄是結構事實，不是經營不善**：省廣 2025 年集團整體毛利率 **5.85%**、數字營銷板塊僅 **4.14%**、出海業務 **1.62%**（大陸 7.90%）——**總額法把媒體流水全額入帳，收入奇大、毛利奇薄**，任何風吹草動都吃掉利潤。
- **MCN 的本質是流量批發，收入高度集中**：頭部達人貢獻大部分營收，**達人一走或塌房，乙方收入與甲方投放一起歸零**。
- **規則由平台制定，代理只能執行**：AIPL／DEEPLINK、FAST／GROW、JD GOAL、O-5A、5R **全部是平台自建的人群資產模型**，目的是把投放與數據留在平台內。代理能做的是把模型翻譯成可執行動作，**不能改模型**。
- **新消費操盤手（元氣森林、花西子、鐘薛高、完美日記…）的集體退潮說明一件事**：**流量操盤能力 ≠ 品牌資產**。投放驅動的增長在紅利期看起來像品牌力，紅利一停就現形。
"""

GATE = """## 二、門禁清單（選本土數字營銷服務商前）

- **A. 需求類型**：要媒介代理（買量）／內容與創意／達人與 MCN／平台方法論落地／全域代運營？**這是五種不同的公司，報價與考核方式都不同。**
- **B. 預算與結算方式**：年度框架還是項目制？服務費比例？**代理商的墊資能力與帳期是這個行業的死穴**（省廣 2025 年應收帳款單項計提壞帳 3.28 億元、其他應收款計提 3.19 億元，就是這個機制的代價）。
- **C. 費用結構**：服務費／返點／達人坑位費與佣金／素材製作費各佔多少？**返點是分給你還是被吃掉？能不能看到媒體原始對帳單？**
- **D. 數據與資產歸屬（最容易被忽略、離場時最貴）**：投放帳戶、素材版權、人群包、達人合約簽在誰名下？**結束合作時帶得走什麼？**
- **E. 過去做過什麼**：近 12 個月同品類戰役？有無翻車（虛假宣傳、刷量、達人塌房）？**有無行政處罰記錄？**
- **F. 團隊與交付**：提案團隊與執行團隊是不是同一批人？達人資源是自有簽約還是二手轉包？駐場人數與彙報頻率？
- **G. 合規紅線**：廣告法禁用語清單、功效宣稱、平台違規記錄；**MCN 合約的違約金與競業條款**——這一塊接案雙方都最容易吃虧。
- **H. 驗收指標與口徑**：以曝光／CPM／CPA／ROI／GMV 中的哪一個結算？**口徑由誰定義、數據由誰提供？** 平台模型給的是可執行清單，還是 PPT？
"""

DOCKET = """## 四、對接實測清單（選本土數字營銷服務商時問）

- **案例核實**：最近 3 個同品類案例，能不能給甲方對接人？**只給 PPT 不給聯絡人的，一律降級使用。**
- **資產歸屬**：投放帳戶、素材、人群包、達人合約結束後歸誰？**寫進合同了嗎？**
- **返點與對帳**：返點怎麼算？我能不能看到媒體原始對帳單？
- **達人來源**：名單是自有簽約還是平台抓取轉包？坑位費與佣金怎麼報？**達人出事誰擔？**
- **方法論兌現**：平台模型（AIPL／5A／FAST）你能出可執行動作清單，還是只有方案 PPT？
- **責任分擔**：出現虛假宣傳處罰或達人塌房，責任與賠償怎麼分？
- **離場條款**：中途換人，達人合約、帳戶與素材怎麼處理？
- **成功標準**：這次以什麼結算（曝光／CPA／ROI／GMV）？口徑誰定義？
"""

RELATED = """## 六、相關

- `48-本土创意与营销服务商` —— 創意熱店與全案服務商（華與華、藍色光標等）。**本檔是媒介代理集團與 MCN；要選乙方，兩檔一起看才夠。**
- `46-国际4A与传播集团` —— 國際 4A 的對照組（方法論、收費結構與客戶結構都不同）。
- `47-战略咨询` —— 策略層的外部大腦。**先分清你要買的是「策略」還是「執行」，再在這三檔之間選。**
- `49-营销书籍与作者`、`50-机构出版物与观点库` —— 本檔方法論的原始出處與延伸閱讀。
- `references/03-方法论操作手册` —— 平台模型只是 111 個模型中的一類。**別把平台自建模型當通行方法論**（見本檔「丁」）。
- `references/06-选流派矩阵与对照表` —— 「該找哪一類服務商」的選型入口。
- `references/04-失败归因总库` —— 流量結構依賴單一 IP、達人連坐、監管處罰等模式的歸因（模式 04／05／06）。
"""


def transform(t):
    """回傳（新檔文字, 錯誤）"""
    lines = t.split("\n")
    starts = [i for i, l in enumerate(lines) if re.match(r"^##\s+[A-D]\d+\.", l)]
    if not starts:
        return None, "找不到任何 `## X#.` 卡片"
    first = starts[0]
    quotes = [l for l in lines[:first] if l.startswith(">")]   # 原檔頭的「可信度標註規則」

    # ── 先按區塊切（丟掉 `# A.` 這類組 H1；組前言暫存到 pending，掛在其後第一張卡前）
    blocks, pre, cur, pending = {}, {}, None, []
    for l in lines[first:]:
        if l.startswith("# "):
            cur = None
            continue
        m = re.match(r"^##\s+([A-D])(\d+)\.\s*(.*)$", l)
        if m:
            cur = m.group(1) + m.group(2)
            if cur not in TITLES:
                return None, f"未知卡片代號：{cur}"
            blocks[cur] = []
            if any(x.strip() for x in pending):
                pre[cur] = pending
            pending = []
            continue
        mc = re.match(r"^##\s+([一二三四五])\s*、\s*(.+?)\s*$", l)
        if mc and mc.group(2) in CHABU:
            cur = "CHABU"
            blocks.setdefault(cur, [])
            if any(x.strip() for x in pending):     # 「結尾」段的引言
                blocks[cur] += [x for x in pending if x.strip()] + [""]
                pending = []
            blocks[cur].append(f"### {mc.group(1)}、{mc.group(2)}")
            continue
        if cur is None:
            pending.append(l)          # 組前言（「# B. MCN 機構」後、B1 前那段）
            continue
        blocks[cur].append("#### " + l[4:] if l.startswith("### ") else l)

    missing = [k for k in ORDER if k not in blocks]
    if missing:
        return None, f"缺卡片區塊：{missing}"
    if "CHABU" not in blocks:
        return None, "找不到「查不到的部分」五個小節"

    # ── 按 ORDER 重排輸出（A7 因此移到丁組開頭，序號連續不跳）
    out = []
    for blk in ORDER:
        body = re.sub(r"\n{3,}", "\n\n", "\n".join(blocks[blk])).strip()
        body = re.sub(r"\n-{3,}\s*$", "", body).strip()      # 去掉區塊尾部的 ---
        for gk, glabel in GROUPS:
            if gk == blk:
                out += ["", glabel, ""]
        if pre.get(blk):
            out += [x for x in pre[blk] if x.strip()]
            out += [""]
        out += ["", f"### 3.{IDX[blk]} {TITLES[blk]}", "", body, "", "---"]
    head = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()

    chabu_text = re.sub(r"\n{3,}", "\n\n", "\n".join(blocks["CHABU"])).strip()
    parts = re.split(r"(?m)^### ([一二三四五]、)", chabu_text)
    if len(parts) < 3:
        return None, "「查不到的部分」小節切分失敗"
    chunks = [parts[1 + i] + parts[2 + i] for i in range(0, len(parts) - 1, 2)]
    lead = parts[0].strip()          # 五小節之前的引言（不能丟）
    chabu = "\n\n".join("### " + c.strip() for c in chunks)
    if lead:
        chabu = lead + "\n\n" + chabu

    new = (H1 + "\n\n" + REDLINE + "\n" + "\n".join(quotes) + "\n\n"
           + OVERVIEW + "\n"
           + GATE + "\n"
           + "## 三、深度拆解\n\n" + head + "\n\n"
           + DOCKET + "\n"
           + "## 五、查不到的部分\n\n" + chabu + "\n\n"
           + RELATED)
    return re.sub(r"\n{3,}", "\n\n", new), None


def verify(old, new):
    def nonhead(s):
        return [l for l in s.split("\n") if l.strip() and not l.lstrip().startswith("#")]
    n = set(nonhead(new))
    miss = [l for l in nonhead(old) if l not in n]
    if miss:
        return f"{len(miss)} 行正文丟失，例：{miss[0][:70]!r}"
    h2 = re.findall(r"(?m)^##\s+(.+)$", new)
    if len(h2) != 6:
        return f"`## ` 應為 6 個，實為 {len(h2)}：{h2}"
    allow = ("行業概覽", "門禁清單", "深度拆解", "對接實測清單", "查不到的部分", "相關")
    if not all(any(a in h for a in allow) for h in h2):
        return f"有不在槽位白名單內的標題：{h2}"
    cards = re.findall(r"(?m)^### 3\.\d+ ", new)
    if len(cards) != len(ORDER):
        return f"卡片數應為 {len(ORDER)}，實為 {len(cards)}"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true")
    a = ap.parse_args()

    if not os.path.exists(SRC):
        print(f"❌ 找不到來源檔：{SRC}（可能已搬過）")
        sys.exit(1)
    t = open(SRC, encoding="utf-8").read()
    new, err = transform(t)
    if err:
        print(f"❌ 轉換失敗：{err}")
        sys.exit(1)
    v = verify(t, new)
    if v:
        print(f"❌ 不變式失敗：{v}")
        sys.exit(1)

    print(f"✅ 轉換通過：{len(ORDER)} 張卡｜{len(t)} 字 → {len(new)} 字")
    if not a.fix:
        print("（體檢模式，未寫入。加 --fix 執行）")
        sys.exit(0)

    open(DST, "w", encoding="utf-8").write(new)
    os.remove(SRC)
    print(f"✅ 寫入 {os.path.relpath(DST, ROOT)}，刪除 {os.path.relpath(SRC, ROOT)}")

    hits = 0
    for f in glob.glob(os.path.join(ROOT, "**", "*.md"), recursive=True):
        if "/.git/" in f or "/.workbuddy/" in f:
            continue
        s0 = open(f, encoding="utf-8").read()
        s = s0.replace("references/06-本土数字营销与MCN.md",
                       "references/cases/51-本土数字营销与MCN.md")
        s = s.replace("06-本土数字营销与MCN", "cases/51-本土数字营销与MCN")
        if s != s0:
            open(f, "w", encoding="utf-8").write(s)
            n = sum(1 for x, y in zip(s0.split("\n"), s.split("\n")) if x != y)
            hits += 1
            print(f"   引用更新：{os.path.relpath(f, ROOT)}（{n} 行）")
    print(f"✅ 引用更新：{hits} 個檔")
    print("接著跑：case_sections.py --fix && file_meta.py --fix")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ 執行出錯：{type(e).__name__}: {e}")
        sys.exit(2)
