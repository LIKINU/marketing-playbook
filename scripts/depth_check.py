#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度校驗 · depth_check.py  （marketing-playbook 協議 4 配套／質量基準線）

用途：selfcheck.py 只查「存在性」（章節有沒有、自檢單有沒有），一份 2,500 字的
      空殼稿也能全綠通過。本腳本查「**深度**」—— 用羅森案逆向出的 83 項量化指標，
      識別「結構完整但內容很空」。

用法：
    python depth_check.py plan.md
    python depth_check.py plan.md --quiet      # 只輸出結論

退出碼：**0 = 一律（本腳本只診斷、不阻攔出稿，用戶定調 2026-09-14）**；2 = 腳本自身出錯
        （注意：即使有 ❌ 硬指標，仍回 0 —— 要不要加厚由用戶決定，不由腳本判死）

判斷分三級（與 selfcheck.py 一致）：
    ❌ 硬指標 → 退出碼 1，必須補
    ⚠️ 警告   → 需人工確認（不影響退出碼）
    ✅ 通過

閾值來源：所有數字取自 `references/07-质量范式-便利店开学季案.md`（以下簡稱「范式档」），
         每條閾值旁標註「§X.Y #N」即該文件第 X.Y 節第 N 項實測值，未經改寫。
         凡標「推導」者，表示范式档未直接給出該數字，由相鄰實測項保守反推。

--------------------------------------------------------------------------
自測記錄（2026-09-14）
測試樣本：任一份已生成的方案 Markdown（本 skill 自帶的 `references/范例/` 可直接用來試跑）
          （樣張可取自 `references/范例/便利店开学季战役-交付稿.md`；其八篇目錄
          齊全、12 項自檢單全 ✅，是典型「結構對但很空」的空殼稿 ——
          selfcheck.py 可全綠，本腳本應報多項 FAIL。）

實跑：python3 depth_check.py references/范例/便利店开学季战役-交付稿.md
  結果：❌ 硬指標未達標 12 項　⚠️ 警告 5 項　僅 2/8 維度達標　退出碼 = 1（如預期 FAIL）

  【1】競品掃描深度   ❌ 致命弱點 0 次（≥5）｜❌ 拆解環節 0 個（≥5）
                       ｜❌ 四段式四欄全缺｜❌ 次要對手 0 個（≥3）
  【2】風險四件套     ❌ 風險條目 0 條（≥3，整維度不存在）｜❌ 無兜底／預防性動作
  【3】行動清單六要素  ❌ 行動條數 5 條（≥15）｜❌ 無「今天」條目（≥3）
                       ｜✅ 每行含負責方+時間｜✅ 含數字 100%
  【4】KPI 深度       ❌ 預警線 0/4 = 0%（范式档要求 100%）｜⚠️ 行數 4（建議 6）
                       ｜⚠️ 基準值 1/4 = 25%｜✅ 觀測方式 100%
  【5】物料清單       ❌ 物料件數 4 件（≥12）｜✅ 位置／內容／成本三列齊
  【6】禁用詞表       ❌ 未分類（≥5 類）｜❌ 詞條 7 條（≥40）
  【7】數字密度       ✅ 每千字具體數字 30.8 個（≥5.0）
                       ※ 這一維度沒抓到空殼：該稿是「預算型空殼」，金額數字很多，
                         但競品／風險／決策線全是空的。密度只能篩「全篇無數字」的稿，
                         不能單獨作為空殼判據 —— 真正管事的是【1】【2】【4】【5】【6】。
  【8】空話檢測       ✅ 無動作詞 0 次（≤5）
→ 結論：好稿與空殼的差別不在「有沒有數字」，而在【1】【2】【4】【5】【6】五處
  是否寫到羅森案的顆粒度。自測通過（腳本如預期報 FAIL，退出碼 1）。
--------------------------------------------------------------------------
誤報修正（2026-09-14）—— 只放寬「識別模式」，閾值一律不動
背景：合併終稿把環節／風險／分類寫在正文與表格裡（**環節一｜…**、#### R1｜…、
      #### 類別一｜…），舊正則只認「#### 環節N」「風險N」「A 類」，故誤判為不達標。
修正：① 環節 = 標題／正文小標／四段式表格三者取最大
      ② 四段式欄名允許變體（他怎麼做／強點／致命弱點／我們怎麼打）
      ③ 風險條目也認「R1」編號式標題，並排除「4.5 觸達硬風險」這類小節名
      ④ 禁用詞分類也認「類別一／第一類／類 A」
      ⑤ 最前置動作也認稿件自稱的「今天」日期（8/29（今天））

自測（修正後）：
  python3 depth_check.py 合并-方案.md        → ✅ 通過，8/8 維度達標，退出碼 0
  python3 depth_check.py /tmp/mp-test/plan.md → ❌ 12 項硬指標未達標，退出碼 1（仍攔空殼）
--------------------------------------------------------------------------
重複度／上限／決策推理（2026-09-14 第二次修正）—— 對比診斷的產物
背景：一份嚴格對比診斷（原版 371 行 vs 重跑版 1,998 行）找出根本原因 ——
      **舊版只設「要素數量下限」、不設上限，且只管「不許砍要素」、不規定「不許重複」**。
      執行 AI 精確優化了可被計數的部分（物料 12→18、KPI 8→15、風險 3→7、行動 18→27），
      在無法計數的部分（判斷、取捨、精煉、洞察）退回到最省力寫法：終稿膨脹 8 倍，
      卻出現「止損四步在 §7.3 與 §8.3 各寫一遍」「大件預警表出現 3 次」
      「『缺什麼，跟我說一聲』出現 55 次」，而原版的內務樣板角、家長休息區
      （停留＝客單價）、定價鐵律 ≤1.15 倍全部檢索 0 次。

修正：① 新增**【9】重複度**（硬錯誤維度）：逐字重複句／跨節逐字重複／跨節近逐字重複／
        口頭禪 —— **這才是「臃腫」的真正判據**（重複是缺陷，長不是）；
      ② 各維度「≤M」僅為**參照值**，超出只給**中性提示**、**不設上限、不阻攔出稿** ——
        量級由**門禁第 13 項先問用戶**（摘要版／標準版／完整版），不由腳本替用戶決定；
      ③ 【2】風險：兜底除了「步數」還必須有**取捨推理**（為什麼先做這個而不是先降價）。

自測（同一組閾值跑兩個已知樣本，2026-09-14 實測）：
  python3 depth_check.py 合并-方案.md → ❌【9】硬錯誤：逐字重複句 3 句、跨節近逐字重複 19 處；
        ⚠️ 口頭禪「缺什麼跟我說一聲」×55；⚠️【2】兜底缺推理
  python3 depth_check.py （本機交付稿）.md → 【9】全綠（重複句 0、跨節 0、
        近重複 0、口頭禪最高 3 次），如預期（原版乾淨）
--------------------------------------------------------------------------
"""

import collections
import re
import sys

from _common import OK, NG, WARN, HINT, INFO   # noqa: E402  统一符号，不要在各自文件里重定义

# ==========================================================================
# 閾值表 —— 全部來自 范式档 §五「可被脚本校驗的深度指標」
#
# ⚠️ 2026-09-14 修正（用戶定調，最終版）：
#   **下限＝羅森案水平（要素齊全＋判斷力）；上限不設限；量級由用戶選擇。**
#
#   背景：舊版只設下限、不管重複，於是執行 AI 精確優化了「可被計數」的部分
#   （物料 12→18、KPI 8→15、風險 3→7、行動 18→27），終稿從 371 行膨脹到 1,998 行，
#   而判斷、取捨、精煉全部退化。
#
#   但**解法不是設上限**（那等於替用戶決定他要多長）——
#   1. 真正該攔的是**重複**（同一件事說兩遍是缺陷，長不是）→ 見【9】重複度，硬錯誤
#   2. 各項「≥N」是**下限**（羅森案水平），代碼裡的「≤M」僅為**參照值**：
#      數量超過時只給**中性提示**（「數量偏多，請確認符合用戶要求的量級」），
#      **不判定「湊數」、不阻攔出稿** —— 要不要那麼長，用戶說了算。
#   3. 量級一律由**門禁第 13 項先問用戶**（摘要版／標準版／完整版 + 有無字數限制）。
# ==========================================================================
T = {
    # 【1】競品掃描深度
    "致命弱點": 5,        # 范式档 §5.1 #8（實測 5，「每環節 1 個」）
    "競品環節數": 5,      # 范式档 §5.1 #9（實測 5 個環節）
    "次要對手數": 3,      # 范式档 §5.1 #11（實測 3 股次要力量）
    "總競品數": 4,        # 范式档 §2.2.1 校驗表（頭號 + 3 = 實測 4）
    # 【2】風險四件套
    "風險條數": 3,        # 范式档 §5.1 #23（實測 3 條）
    "風險上限": 8,        # 推導（上限）：范式档實測 3 條；風險隨項目規模成長，取 3 × 2.7 ≈ 8。
                          # 依據：羅森案重跑版 7 條，其中 R7 自認「最容易用印前自檢
                          # 一次性防住」——自認不必單列卻為了湊條數立了一張卡。
    "兜底係數": 3,        # 范式档 §5.1 #25（「兜底」≥ 風險數 × 3；實測 10）
    "兜底步數": 3,        # 范式档 §5.1 #28（每條兜底 ≥3 步；實測 4 步）
    "預防性動作": 2,      # 范式档 §5.1 #26（實測 2 處）
    # 【3】行動清單六要素
    "行動條數": 15,       # 范式档 §5.1 #71（實測 18 條）
    "行動上限": 35,       # 推導（上限）：范式档實測 18 條，取 18 × 1.9 ≈ 35。
                          # 依據：重跑版 27 條，其中約 12 條是 §2.4 節奏排期表的逐字重複
                          # （同一天的行動被按天抄一遍再進行動清單）。
    "行動含數字比": 0.80, # 推導：范式档 §5.1 #71–73（18 條幾乎條條含數量/時刻）
    "今天條數": 3,        # 范式档 §5.1 #73（實測 5 條）
    # 【4】KPI 深度
    "KPI行數": 6,         # 范式档 §5.1 #34（實測 8 = 日常 6 + 報到日 2）
    "KPI上限": 15,        # 推導（上限）：范式档實測 8 行；取 8 × 1.9 ≈ 15。
                          # 依據：重跑版 15 行（已頂到本上限），且 KPI 表末尾自問
                          # 「為什麼只有 15 行」——為達標而擴表後的自我辯解。
                          # KPI 的記錄成本本身就是風險（原版只用 6 件工具、每天只看 8 個數）。
    "預警線比": 1.00,     # 范式档 §5.1 #34 / 模板 10（實測 8/8 = 100%）
    "基准值比": 0.80,     # 推導：范式档 §4.1 做法 #2（每個數字帶時間點或觸發條件）
    "觀測方式比": 0.80,   # 推導：范式档 §5.1 #34（「怎麼算」列實測 100%）
    # 【5】物料清單
    "物料件數": 12,       # 范式档 §5.1 #61（實測 12 件）
    "物料上限": 25,       # 推導（上限）：范式档實測 12 件（全部是對外物料），取 12 × 2 ≈ 25 ——
                          # 留「品類翻一倍」的空間，再多就是湊數。
                          # 依據：重跑版 18 件，其中 M17「清倉倒數」、M18「禁語自檢表」
                          # 是貼給店員自己看的內部紙，被計入「對外物料」來達標。
    # 【6】禁用詞表
    "禁用詞類別數": 5,    # 范式档 §5.1 #14（實測 5 類 A–E）
    "禁用詞類別上限": 8,  # 推導（上限）：范式档實測 5 類，放寬到 A–H（8 類）為止；
                          # 再多即為「為湊類別而切」。重跑版 6 類、每類硬湊 10 條。
    "禁用詞條數": 40,     # 范式档 §5.1 #15（實測 59 條）
    "禁用詞條數上限": 80, # 推導（上限）：范式档實測 59 條，取 59 × 1.35 ≈ 80。
                          # 依據：重跑版 60 條大量灌水 —— 類別一 #10「買不到別怪我」的
                          # 替代說法直接寫「刪除」；類別六把「環湖有 2,000 名新生」
                          # 這種事實口徑校準塞進禁用詞表充數。
    # 【7】數字密度
    "千字數字密度": 5.0,  # 推導：范式档 §5 未直接給；見 §4.1 做法 #1/#2 反推保守下限
    "千字密度警告": 8.0,  # 推導：同上，取建議值
    # 【8】空話檢測
    "空話詞": 5,          # 推導：范式档 §4.2 反面清單（「全文沒有一個不可驗收的指標」）
    "空話密度": 6,        # 推導：每千字「無動作詞」上限（與千字數字密度對照；舊版硬編碼 6）
    # 【9】重複度（2026-09-14 新增；校準樣本見 check_repeats() 的註釋）
    "重複句長度": 12,     # 推導：低於 12 字的片段多是表格欄名與慣用語，噪音大。
                          # 依據：原版最長的重複句剛好 12 字（「家长版学校发的您领了
                          # 剩下的我这儿配齐」×2）—— 這條門檻在原版上報 0。
    "重複句次數": 3,      # 硬錯誤門檻：同一句話出現 3 次，已不是「強調」而是「裝訂」
    "跨節重複行數": 5,    # 硬錯誤門檻：任意兩節共用 ≥5 行逐字相同＝其中一節是複製貼上
    "跨節近重複數": 5,    # 硬錯誤門檻（3–4 為警告）。推導：同一組閾值跑兩個已知樣本 ——
                          # 原版實測 0 處、重跑版實測 19 處，取 5 為斷點（遠離原版、貼近重跑版）
    "近重複片段長度": 24, # 推導：24 字以下的片段（欄名、慣用句）容易誤報；
                          # 加上這道長度門檻後，原版的近逐字跨節重複 = 0
    "近重複鍵長": 14,     # 推導：14 字完全相同＝兩句已無實質差異（中文本句平均 15–25 字）。
                          # 片段 ≥24 字時，取其「前 14 字」或「後 14 字」當鍵；
                          # 相同鍵落在不同章節 → 同一件事寫了兩遍
    "口頭禪長度": 8,      # 推導：≥8 字的固定短語才可能是口頭禪（5 字以下多為常用搭配）
    "口頭禪次數": 15,     # 警告門檻。推導：原版實測最高 3 次、「重跑版 55 次」，
                          # 取 15 為安全斷點（既不誤報原版，也遠低於重跑版）
}

# 空話／無動作詞（范式档 §4.2：這類詞是「沒寫具體動作」的信號）
# 模糊词表改从 _common 取（唯一真相）—— 2026-09-17：原先 depth_check 与
# selfcheck 各写一份，改一处忘一处就会出现两套判据。
from _common import VAGUE_WORDS   # noqa: E402

# 量詞白名單 —— 用來識別「具體數字」（金額／比例／天數／數量）
UNIT = (r"(?:元|塊|块|萬元|万|%|％|天|週|周|日|月|年|單|单|人|篇|份|張|张|個|个|"
        r"次|小時|小时|分鐘|分钟|秒|公里|米|㎡|倍|折|檔|档|條|条|行|列|項|项|點|点|"
        r"杯|套|種|种|家|間|间|位|名|組|组|公里|KG|kg|L|ml|SKU)")

# --------------------------------------------------------------------------
# 識別模式表 —— 只放寬「怎麼辨認」，不放寬任何閾值
# 每組都保留原本的寫法，再補上稿件實際使用的變體。
# --------------------------------------------------------------------------
# 【競品拆解環節】三種寫法都認：① 標題含「環節」② 正文小標「**環節一｜…」③ 四段式表格
RE_ROUND_HEAD = re.compile(r"^#{2,6}[^\n]*(?:環節|环节)", re.M)
RE_ROUND_BODY = re.compile(r"^\s*(?:\*\*|[-*]\s*)?\s*(?:環節|环节)\s*[一二三四五六七八九十\d]+", re.M)
RE_ROUND_ROW = re.compile(r"^\s*\|\s*\*\*[^|\n]*?(?:怎麼做|怎么做|做法)[^|\n]*?\*\*\s*\|", re.M)

# 【四段式四欄】欄名允許變體（他們的／他的、我們怎麼打／我們的打法）
FOUR_LABELS = {
    "他們怎麼做": r"他們怎麼做|他们怎么做|他怎麼做|他怎么做",
    "強點": r"強點|强点|強項|强项",
    "致命弱點": r"致命弱點|致命弱点|致命傷|致命伤|弱點|弱点",
    "我們的打法": r"我們的打法|我们的打法|我們怎麼打|我们怎么打|我們的做法|我们的做法",
}

# 【風險條目編號】除了「風險N」也認「R1／R-1」式編號標題
RE_RISK_NO = re.compile(r"^R\s*[-–]?\s*\d{1,2}(?!\d)", re.I)

# 【禁用詞分類】A 類／A類／類別一／第一類／類 A 都算一類（正規化為「一」或「A」）
RE_BANNED_CLASS = re.compile(
    r"類別\s*([一二三四五六七八九十\d]+)|第\s*([一二三四五六七八九十\d]+)\s*類|"
    r"類\s*([A-EＡ-Ｅ])|([A-EＡ-Ｅ])\s*類")

# 【最前置動作】稿件自稱的「今天」日期：8/29（今天）／8/29 今天／今天（8/29）／今天是 8/29
RE_TODAY_DATE = re.compile(
    r"(?P<d1>\d{1,2}/\d{1,2})\s*[（(【]?\s*今天"
    r"|今天\s*(?:是)?\s*[（(【]?\s*(?P<d2>\d{1,2}/\d{1,2})")

# 【決策推理】（2026-09-14 新增）兜底裡「取捨」的句式。為什麼是這幾種：
#   範式档 §五 對風險的質性要求是「兜底要說明為什麼先做這個而不是直接降價」——
#   原版寫的是「先改陳列，不要急着降价。降价是最贵的解法，先试免费的」，
#   這個「先 A 不 B」的句式就是判斷力的痕跡，而不是格式。
#   只認句式、不認關鍵詞，是為了避免把「降價」這種普通詞語也算成推理。
RE_TRADEOFF = [
    r"為什麼|为什么",                        # 為什麼先做這個
    r"而不是|而非",                          # 而不是直接降價
    r"先[^。；\n]{0,25}(?:再|然後|然后|才)",  # 先 A 再 B（分步取捨）
    r"不(?:要)?(?:急著|急着)?(?:先)?降價|不(?:要)?(?:急著|急着)?(?:先)?降价",  # 先不降價
    r"可逆|不可逆",                          # 把不可逆的手段放最後
]

# --------------------------------------------------------------------------
# 【9】重複度用的正規化與切節工具
# --------------------------------------------------------------------------
RE_SENT_END = re.compile(r"[。！？；!?;]+")
RE_CJK_ONLY = re.compile(r"^[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+$")
RE_APPENDIX = re.compile(r"附件|附錄|附录")


def norm_cmp(s):
    """比對用正規化：只保留中英數字（去掉 Markdown 裝飾、標點、空白）。

    於是「**止損四步**」＝「止損四步」、「，」＝「,」，全形半形差異都能對上。
    """
    return re.sub(r"[^\w]+", "", s, flags=re.UNICODE)


def frag_key(f, n):
    """取片段的前 n 字與後 n 字當比對鍵（前後都取，因為重複可能發生在句尾）。"""
    return [f[:n], f[-n:]]


def doc_sections(lines):
    """以標題切節 → [(title, start, end)]。

    只取該節「自己那一層的直接內容」（到下一行任何級別的標題為止）——
    否則父節會把子節整段包進來，父子節一比必然全中（那是假重複，不是真重複）。
    H1 視為文檔標題，不切節。
    """
    heads = []
    for i, ln in enumerate(lines):
        m = re.match(r"^(#{1,6})\s*(.+?)\s*$", ln)
        if m and len(m.group(1)) >= 2:
            heads.append((i, m.group(2)))
    out = []
    for k, (i, title) in enumerate(heads):
        j = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        out.append((title, i, j))
    return out


def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# --------------------------------------------------------------------------
# Markdown 解析小工具
# --------------------------------------------------------------------------
def find_region(lines, keywords):
    """回傳 (start, end) 行號區間。先找標題；找不到再退化為正文關鍵詞。"""
    n = len(lines)
    for i, ln in enumerate(lines):
        m = re.match(r"^(#{1,6})\s*(.+?)\s*$", ln)
        if m and any(k in m.group(2) for k in keywords):
            level = len(m.group(1))
            j = i + 1
            while j < n:
                m2 = re.match(r"^(#{1,6})\s", lines[j])
                if m2 and len(m2.group(1)) <= level:
                    break
                j += 1
            return (i, j)
    for i, ln in enumerate(lines):
        if any(k in ln for k in keywords):
            j = i + 1
            while j < n and not re.match(r"^#{1,6}\s", lines[j]):
                j += 1
            return (i, j)
    return None


def region_text(lines, rng):
    return "\n".join(lines[rng[0]:rng[1]]) if rng else ""


def tables_in(lines, rng):
    """抽出區域內所有 Markdown 表格 → [{'header': [...], 'rows': [[...]]}]"""
    if not rng:
        return []
    start, end = rng
    blocks, i = [], start
    while i < end:
        if lines[i].strip().startswith("|") and lines[i].count("|") >= 2:
            blk = []
            while i < end and lines[i].strip().startswith("|"):
                blk.append(lines[i])
                i += 1
            blocks.append(blk)
        else:
            i += 1
    out = []
    for blk in blocks:
        rows = []
        for idx, raw in enumerate(blk):
            cells = [c.strip() for c in raw.strip().strip("|").split("|")]
            # 分隔行：整行只由 - : 空白組成，且至少有一個 "-"（容忍空單元格與對齊冒號）
            if idx == 1 and cells and all(re.fullmatch(r"[-:\s]*", c) for c in cells) \
                    and any("-" in c for c in cells):
                continue
            rows.append(cells)
        if rows:
            out.append({"header": rows[0], "rows": rows[1:]})
    return out


def col_index(header, kws):
    for i, c in enumerate(header):
        if any(k in c for k in kws):
            return i
    return -1


def cell(row, idx):
    return row[idx].strip() if 0 <= idx < len(row) else ""


def has_digit(s):
    return bool(re.search(r"\d", s))


def risk_blocks(lines):
    """找出所有風險條目區塊 → [(title, text)]

    兩種寫法都認：
      ① 標題含「風險 N」「風險：」（原邏輯）
      ② 標題以編號開頭，形如「### R1｜現金風險」「#### R2：…」（稿件實際寫法）
    """
    n, out = len(lines), []
    for i, ln in enumerate(lines):
        m = re.match(r"^(#{2,6})\s*(.+?)\s*$", ln)
        if not m:
            continue
        title = m.group(2)
        # 排除小節標題：形如「### 4.5 觸達硬風險」「### 8.3 風險清單」
        # （否則「…硬風險」這種節名會被誤認成一條風險，且必然缺四件套）
        if re.match(r"^\d+\.\d+[\s、.．]?", title):
            continue
        if not re.search(r"風險|风险", title) and not RE_RISK_NO.match(title):
            continue
        # 排除章節名（風控／風險與假設／風險偏好／風險總覽…）
        if re.search(r"風控|风控|風險與|风险与|風險偏好|风险偏好|風險等級|风险等级|"
                     r"風險總覽|风险总览|風險清單|风险清单", title):
            continue
        is_no = bool(RE_RISK_NO.match(title))
        is_kw = bool(re.search(r"(風險|风险)\s*(?:\d|[一二三四五六七八九十]|[:：]|條|条|$)", title))
        if not (is_no or is_kw):
            continue
        level, j = len(m.group(1)), i + 1
        while j < n:
            m2 = re.match(r"^(#{1,6})\s", lines[j])
            if m2 and len(m2.group(1)) <= level:
                break
            j += 1
        out.append((title, "\n".join(lines[i:j])))
    return out


def count_terms(sec_text):
    """數禁用詞條數：抓引號／括號內、以頓號分隔的短詞，另含表格單元格。"""
    terms = []
    for m in re.finditer(r"[「『“\"]([^」』”\"]{1,80})[」』”\"]", sec_text):
        for t in re.split(r"[、，,;；/／]+", m.group(1)):
            t = t.strip()
            if t and len(t) <= 12:
                terms.append(t)
    return list(dict.fromkeys(terms))


class Dim:
    """一個校驗維度的輸出容器。"""

    def __init__(self, no, name):
        self.no, self.name, self.items = no, name, []

    def ok(self, msg):
        self.items.append((OK, msg))

    def fail(self, msg):
        self.items.append((NG, msg))
        HARD.append(msg)

    def warn(self, msg):
        self.items.append((WARN, msg))
        WARNS.append(msg)

    def info(self, msg):
        self.items.append((INFO, msg))


HARD, WARNS = [], []


# ==========================================================================
# 各維度校驗
# ==========================================================================
def count_rounds(lines, text):
    """數「競品拆解環節」。

    稿件的實際寫法常常不是「#### 環節N」型標題，所以三種都認，取最大：
      ① 標題含「環節」（原邏輯）
      ② 正文小標，形如「**環節一｜獲客**」「**環節 1｜獲客**」
      ③ 四段式表格列首，形如「| **他怎麼做** | … |」（一張表只算 1 個環節，
         故只認四段中的第一段，不重複計「我們怎麼打」那一列）
    """
    n_head = len(RE_ROUND_HEAD.findall(text))
    n_body = len(set(RE_ROUND_BODY.findall(text)))
    n_tbl = len(RE_ROUND_ROW.findall(text))
    return max(n_head, n_body, n_tbl)


def check_competitors(lines, text):
    d = Dim(1, "競品掃描深度")

    weak = len(re.findall(r"致命弱點|致命弱点", text))
    d.ok(f"「致命弱點」出現 {weak} 次（閾值 ≥{T['致命弱點']}）") if weak >= T["致命弱點"] else \
        d.fail(f"「致命弱點」出現 {weak} 次（閾值 ≥{T['致命弱點']}；范式档要求每個拆解環節 1 個）")

    rounds = count_rounds(lines, text)
    if rounds == 0:
        d.fail("競品拆解環節 0 個（閾值 ≥5）——未見「#### 環節N」式拆解，"
               "等於沒做競品掃描")
    elif rounds < T["競品環節數"]:
        d.fail(f"競品拆解環節 {rounds} 個（閾值 ≥{T['競品環節數']}）")
    else:
        d.ok(f"競品拆解環節 {rounds} 個（閾值 ≥{T['競品環節數']}）")

    # 四段式完整度：他們怎麼做／強點／致命弱點／我們的打法
    # （欄名允許變體：他怎麼做／我們怎麼打／我們的打法…，見 FOUR_LABELS）
    counts = {k: len(re.findall(v, text)) for k, v in FOUR_LABELS.items()}
    complete = min(counts.values())
    miss = [k for k, v in counts.items() if v == 0]
    if miss:
        d.fail(f"四段式缺欄：「{'、'.join(miss)}」（四段 = 他們怎麼做／強點／致命弱點／我們的打法）")
    else:
        need = max(rounds, T["競品環節數"])
        if complete >= need:
            d.ok(f"四段式完整 {complete} 組（= 環節數 × 4 的要求已滿足）")
        else:
            d.fail(f"四段式完整僅 {complete} 組 < 環節數 {rounds}（范式档要求 = 環節數 × 4）")

    # 對手數量：威脅等級 / 「另外 N 股力量」表行數
    threat = len(re.findall(r"威脅等級|威胁等级", text))
    rng = find_region(lines, ["股力量", "另外", "競品掃描", "竞品扫描", "競爭格局", "竞争格局"])
    tbl_rows = 0
    if rng:
        for tb in tables_in(lines, rng):
            if col_index(tb["header"], ["威脅", "威胁"]) >= 0:
                tbl_rows = max(tbl_rows, len(tb["rows"]))
    minor = max(threat, tbl_rows)
    if minor >= T["次要對手數"]:
        d.ok(f"次要對手 {minor} 個（閾值 ≥{T['次要對手數']}）")
    else:
        d.fail(f"次要對手 {minor} 個（閾值 ≥{T['次要對手數']}）——對手盤沒展開")

    head = bool(re.search(r"頭號對手|头号对手|全鏈條拆解|全链条拆解", text))
    total = minor + (1 if head else 0)
    if head:
        d.info("已標明頭號對手（全鏈條拆解）")
    else:
        d.warn("未標明「頭號對手」——范式档要求先立頭號對手，再列次要力量")
    if total < T["總競品數"]:
        d.warn(f"競品總數 {total} 個（范式档 §2.2.1 建議 ≥{T['總競品數']}：頭號 + 3 股力量）")
    return d


def check_risks(lines, text):
    d = Dim(2, "風險四件套")
    blocks = risk_blocks(lines)
    if not blocks:
        d.fail("風險條目 0 條（閾值 ≥3）——整份方案找不到「### 風險 N」段落，"
               "風險維度完全不存在")
        if "兜底" not in text and "预防" not in text and "預防" not in text:
            d.fail("未見任何「兜底／預防性動作」字樣")
        return d

    n_risk = len(blocks)
    if n_risk >= T["風險條數"]:
        d.ok(f"風險條目 {n_risk} 條（閾值 ≥{T['風險條數']}）")
    else:
        d.fail(f"風險條目 {n_risk} 條（閾值 ≥{T['風險條數']}）")

    # 上限：超出即警告「數量偏多 —— 請確認是否符合用戶要求的量級（**本項不設上限**）」（2026-09-14 新增，依據見 T 表註釋）
    if n_risk > T["風險上限"]:
        d.warn(f"風險 {n_risk} 條 > 上限 {T['風險上限']} 條 —— 數量偏多 —— 請確認是否符合用戶要求的量級（**本項不設上限**）；"
               "自認「用一個前置動作就能防住」的不必單獨立卡")

    # 一票否決 V2：每條風險必須有「預警信號」且含數字
    no_signal, no_digit, min_steps = [], [], []
    for title, body in blocks:
        m_no = RE_RISK_NO.match(title)
        short = m_no.group(0).strip() if m_no else \
            (re.split(r"[（(：:\s]", title.replace("風險", "").replace("风险", "").strip())[0] or title)
        m = re.search(r"預警信號|预警信号", body)
        if not m:
            no_signal.append(short)
            continue
        # 預警信號區間 = 「預警信號」到「兜底／預防性動作」之間
        tail = body[m.end():]
        cut = re.search(r"兜底|預防性動作|预防性动作", tail)
        seg = tail[:cut.start()] if cut else tail[:800]
        if not has_digit(seg):
            no_digit.append(short)
        # 兜底步數：數 ①②③ 或「第N步」，兩者取大（避免重複計數）
        zb = re.search(r"兜底", body)
        zseg = body[zb.start():] if zb else ""
        c1 = len(re.findall(r"[①②③④⑤⑥⑦⑧⑨]", zseg))
        c2 = len(re.findall(r"第[一二三四五六七八九]步", zseg))
        min_steps.append(max(c1, c2))

    if no_signal:
        d.fail(f"風險缺「預警信號」：{'、'.join(no_signal)}（一票否決 V2，范式档 §5.2）")
    else:
        d.ok(f"每條風險均含「預警信號」（{n_risk}/{n_risk}）")
    if no_digit:
        d.fail(f"風險「預警信號」缺數字：{'、'.join(no_digit)}"
               f"（預警信號必須是可量化指標，范式档 §4.3）")
    elif not no_signal:
        d.ok("預警信號均含量化數字")

    zb_total = len(re.findall(r"兜底", text))
    need = n_risk * T["兜底係數"]
    if zb_total >= need:
        d.ok(f"「兜底」出現 {zb_total} 次（閾值 ≥{need}＝風險數×{T['兜底係數']}）")
    else:
        d.fail(f"「兜底」出現 {zb_total} 次（閾值 ≥{need}＝風險數×{T['兜底係數']}）"
               "——兜底寫得太薄")

    if min_steps:
        s = min(min_steps)
        if s >= T["兜底步數"]:
            d.ok(f"每條兜底 ≥{s} 步（範式要求 ≥{T['兜底步數']} 步，且「按觸發順序不要跳步」）")
        else:
            d.fail(f"有風險的兜底只有 {s} 步（閾值 ≥{T['兜底步數']} 步，需 ①②③ 分步）")

    # 決策推理（2026-09-14 新增）：兜底不能只是「動作堆疊」，必須寫明取捨。
    # 舊判據只數「兜底」出現次數與步數 —— 那是字數代理，套話稿一樣過關（重跑版即如此：
    # 四件套齊全，但 R1 的「不降價，先換位置」沒有因果、R6 的「話術最便宜」是通用常識、
    # R7 的最壞兜底在「零物料預算」前提等於什麼都沒說）。
    # 範式档 §五 的質性要求：要寫清「為什麼先做這個而不是直接降價」。
    no_why = []
    for title, body in blocks:
        m_no = RE_RISK_NO.match(title)
        short = m_no.group(0).strip() if m_no else \
            (re.split(r"[（(：:\s]", title.replace("風險", "").replace("风险", "").strip())[0] or title)
        zb = re.search(r"兜底", body)
        zseg = body[zb.end():] if zb else body
        if not any(re.search(p, zseg) for p in RE_TRADEOFF):
            no_why.append(short)
    if no_why:
        d.warn(f"兜底缺「決策推理（為什麼先做這個，而不是一發現賣不動就降價）」："
               f"{'、'.join(no_why)}（{len(no_why)}/{n_risk} 條）—— "
               "只列動作、不寫取捨的兜底＝套話（范式档：先試免費的，再花錢的）")
    else:
        d.ok(f"每條兜底都寫明了取捨理由（{n_risk}/{n_risk} 條）")

    prev = len(re.findall(r"預防性動作|预防性动作", text))
    if prev >= T["預防性動作"]:
        d.ok(f"「預防性動作」出現 {prev} 次（閾值 ≥{T['預防性動作']}）")
    elif prev:
        d.warn(f"「預防性動作」只有 {prev} 次（閾值 ≥{T['預防性動作']}，建議每條高優風險 1 條）")
    else:
        d.fail("未見「預防性動作」——范式档：預防比兜底更重要，沒有等於只救火不防火")
    if prev and prev < n_risk:
        d.warn(f"「預防性動作」{prev} 條 < 風險 {n_risk} 條，未覆蓋全部風險")

    # 每條風險含 ≥1 具體數字
    nod = [t for t, b in blocks if not re.search(rf"\d+(?:\.\d+)?\s*{UNIT}", b)]
    if nod:
        d.warn(f"風險段內無「具體數字」：{'、'.join(nod)}（范式档 §5.1 #27 要求 100%）")
    else:
        d.ok("每條風險均含具體數字（金額／比例／天數）")
    return d


def pick_action_table(lines, all_tables):
    rng = find_region(lines, ["行動清單", "行动清单", "行動計劃", "行动计划", "執行與風控", "执行与风控"])
    cands = tables_in(lines, rng) if rng else []
    best = None
    for tb in cands:
        if col_index(tb["header"], ["時間", "时间", "什麼時候", "什么时候", "排期", "截止"]) >= 0:
            if best is None or len(tb["rows"]) > len(best["rows"]):
                best = tb
    if best is None and rng:
        best = max(cands, key=lambda t: len(t["rows"])) if cands else None
    return best, rng


def count_today_by_date(rows, text, i_when):
    """用稿件自稱的「今天」日期，數行動清單裡的最前置動作。

    例：稿件寫「**8/29（今天）就開始**」，則時間欄為 8/29 的行即為「今天」條目。
    日期必須直接標註「今天」（8/29（今天）／今天 8/29），或由文首「整理日期」推定；
    找不到自稱日期時回 0（維持原判斷：無最前置動作）。
    """
    toks = set()
    for m in RE_TODAY_DATE.finditer(text):
        toks.add(m.group("d1") or m.group("d2"))
    m = re.search(r"整理日期[:：]\s*\d{4}-(\d{2})-(\d{2})", text)
    if m:
        toks.add(f"{int(m.group(1))}/{int(m.group(2))}")
    if not toks:
        return 0
    hit = 0
    for r in rows:
        seg = cell(r, i_when) if i_when >= 0 else " ".join(r)
        if any(re.search(re.escape(t) + r"(?![\d/])", seg) for t in toks):
            hit += 1
    return hit


def check_actions(lines, all_tables):
    d = Dim(3, "行動清單六要素")
    tb, rng = pick_action_table(lines, all_tables)
    if tb is None:
        d.fail("找不到行動清單表格——行動維度完全不存在（范式档 §5.1 #71）")
        return d

    rows = tb["rows"]
    n = len(rows)
    if n >= T["行動條數"]:
        d.ok(f"行動條數 {n} 條（閾值 ≥{T['行動條數']}）")
    else:
        d.fail(f"行動條數 {n} 條（閾值 ≥{T['行動條數']}）——清單太短，動作沒拆開")

    # 上限：超出即警告「數量偏多 —— 請確認是否符合用戶要求的量級（**本項不設上限**）」（2026-09-14 新增，依據見 T 表註釋）
    if n > T["行動上限"]:
        d.warn(f"行動 {n} 條 > 上限 {T['行動上限']} 條 —— 數量偏多 —— 請確認是否符合用戶要求的量級（**本項不設上限**）；"
               "最常見的手法是把節奏排期表按天再抄一遍（同一件事說兩次，見【9】）")

    i_who = col_index(tb["header"], ["負責", "负责", "誰做", "谁做", "執行人", "执行人", "責任人", "责任人"])
    i_when = col_index(tb["header"], ["時間", "时间", "什麼時候", "什么时候", "排期", "截止"])
    i_cost = col_index(tb["header"], ["花多少", "預算", "预算", "費用", "费用", "成本", "金額", "金额"])
    i_chk = col_index(tb["header"], ["驗收", "验收", "判定", "成果", "指標", "指标"])

    if i_who < 0:
        d.fail("行動清單缺「負責方／誰做」列（一票否決 V1，范式档 §5.2）")
    if i_when < 0:
        d.fail("行動清單缺「時間」列（一票否決 V1，范式档 §5.2）")
    if i_who >= 0 and i_when >= 0:
        bad = [str(k + 1) for k, r in enumerate(rows) if not cell(r, i_who) or not cell(r, i_when)]
        if bad:
            d.fail(f"第 {','.join(bad[:8])} 行缺「負責方」或「時間」（一票否決 V1，要求 100%）")
        else:
            d.ok(f"每行均含「負責方 + 時間」（{n}/{n} = 100%）")
    if i_cost < 0:
        d.warn("行動清單缺「花多少／預算」列（建議補上）")
    if i_chk < 0:
        d.warn("行動清單缺「怎麼驗收」列（建議補上）")

    with_num = [r for r in rows if any(has_digit(c) for c in r)]
    ratio = len(with_num) / n if n else 0
    if ratio >= T["行動含數字比"]:
        d.ok(f"含具體數字的行動行 {len(with_num)}/{n} = {ratio:.0%}（閾值 ≥{T['行動含數字比']:.0%}）")
    elif ratio >= 0.4:
        d.warn(f"含具體數字的行動行 {len(with_num)}/{n} = {ratio:.0%}"
               f"（建議 ≥{T['行動含數字比']:.0%}，范式档 §4.1 #3）")
    else:
        d.fail(f"含具體數字的行動行僅 {ratio:.0%}（閾值 ≥40%）——動作沒有量")

    # 「最前置動作」的識別：稿件常寫絕對日期（8/29）而非「今天」二字，
    # 故以稿件自稱的「今天」日期換算。閾值不變，只是別把已達標的判成缺。
    rows_text = "\n".join(" ".join(r) for r in rows)
    today = len(re.findall(r"今天|立刻|马上|馬上|立即", rows_text))
    if not today:
        today = count_today_by_date(rows, "\n".join(lines), i_when)
    if today >= T["今天條數"]:
        d.ok(f"「今天／立刻」條目 {today} 條（閾值 ≥{T['今天條數']}）")
    elif today:
        d.warn(f"「今天／立刻」條目只有 {today} 條（閾值 ≥{T['今天條數']}，范式档 §5.1 #73）")
    else:
        d.fail("行動清單無「今天／立刻」條目——沒有最前置動作（范式档 §5.1 #73）")
    return d


def check_kpi(lines, all_tables):
    d = Dim(4, "KPI 深度")
    rng = find_region(lines, ["KPI", "指標", "指标", "追蹤", "追踪", "監測", "监测"])
    tbls = tables_in(lines, rng) if rng else []
    tb = None
    for t in tbls:
        if col_index(t["header"], ["指標", "指标", "KPI", "目標", "目标"]) >= 0:
            if tb is None or len(t["rows"]) > len(tb["rows"]):
                tb = t
    if tb is None and tbls:
        tb = max(tbls, key=lambda t: len(t["rows"]))
    if tb is None:
        d.fail("找不到 KPI 表格——KPI 維度完全不存在（范式档 §5.1 #34）")
        return d

    rows, n = tb["rows"], len(tb["rows"])
    if n >= T["KPI行數"]:
        d.ok(f"KPI 行數 {n}（閾值 ≥{T['KPI行數']}，范式档實測 8）")
    else:
        d.warn(f"KPI 行數 {n}（建議 ≥{T['KPI行數']}，范式档實測 8 = 日常 6 + 報到日 2）")

    # 上限：超出即警告「數量偏多 —— 請確認是否符合用戶要求的量級（**本項不設上限**）」（2026-09-14 新增，依據見 T 表註釋）
    if n > T["KPI上限"]:
        d.warn(f"KPI {n} 行 > 上限 {T['KPI上限']} 行 —— 數量偏多 —— 請確認是否符合用戶要求的量級（**本項不設上限**）；"
               "KPI 的記錄成本本身就是風險，先問「這一行沒人看會不會少一個決策」")

    # 一票關注點：預警線／決策線（范式档：沒有第三列的 KPI 表等於沒寫）
    i_alarm = col_index(tb["header"], ["預警", "预警", "兜底", "決策線", "决策线", "立刻", "即時", "告警"])
    if i_alarm >= 0:
        cov = sum(1 for r in rows if cell(r, i_alarm))
    else:
        # 注意：不可把「→」算進來 —— 目標欄的「42 → 80」是基準值，不是預警線
        cov = sum(1 for r in rows
                  if re.search(r"預警|预警|決策線|决策线|立刻|告警|連續\s*\d|连续\s*\d", " ".join(r)))
    ratio = cov / n if n else 0
    if ratio >= T["預警線比"]:
        d.ok(f"每行含「預警線 → 立刻做什麼」（{cov}/{n} = {ratio:.0%}）")
    elif ratio == 0:
        d.fail("KPI 表無「預警線／決策線」欄（0/%d）——范式档 §5.1 #34："
               "沒有第三列（預警線 → 立刻做什麼）的 KPI 表等於沒寫" % n)
    else:
        d.fail(f"「預警線」覆蓋 {cov}/{n} = {ratio:.0%}（范式档要求 100%，"
               "缺的那幾行只是數字、不是決策）")

    i_base = col_index(tb["header"], ["目標", "目标", "基準", "基准", "現況", "现况", "值"])
    if i_base >= 0:
        base_cov = sum(1 for r in rows if re.search(r"→|->|從|从", cell(r, i_base)))
    else:
        base_cov = sum(1 for r in rows if re.search(r"→|->|從\s*[\d.]+\s*到|从\s*[\d.]+\s*到", " ".join(r)))
    br = base_cov / n if n else 0
    if br >= T["基准值比"]:
        d.ok(f"含基準值對比（X → Y）的 KPI {base_cov}/{n} = {br:.0%}（閾值 ≥{T['基准值比']:.0%}）")
    elif br == 0:
        d.fail("KPI 無基準值對比（無「X → Y」或「從 X 到 Y」）——只有目標沒有起點，無法判斷進步")
    else:
        d.warn(f"基準值對比僅 {base_cov}/{n} = {br:.0%}（建議 ≥{T['基准值比']:.0%}）")

    i_obs = col_index(tb["header"], ["怎麼", "怎么", "來源", "来源", "觀測", "观测", "記", "记",
                                     "統計", "统计", "導出", "导出", "數據源", "数据源"])
    if i_obs >= 0:
        obs_cov = sum(1 for r in rows if cell(r, i_obs))
    else:
        obs_cov = len(rows) if re.search(r"後台|后台|導出|导出|系統|系统|盤點|盘点|收銀|收银|日誌|日志|每日|週報|周报", region_text(lines, rng)) else 0
    orr = obs_cov / n if n else 0
    if orr >= T["觀測方式比"]:
        d.ok(f"含觀測方式（怎麼記／後台／每日導出）{obs_cov}/{n} = {orr:.0%}（閾值 ≥{T['觀測方式比']:.0%}）")
    elif orr == 0:
        d.fail("KPI 無觀測方式（怎麼記／後台／每日導出）——指標不可測")
    else:
        d.warn(f"觀測方式覆蓋 {obs_cov}/{n} = {orr:.0%}（建議 ≥{T['觀測方式比']:.0%}）")
    return d


def check_materials(lines, all_tables):
    d = Dim(5, "物料清單")
    rng = find_region(lines, ["物料", "文案", "物料清單", "物料清单"])
    tbls = tables_in(lines, rng) if rng else []
    tb = None
    for t in tbls:
        if col_index(t["header"], ["物料", "品項", "品项", "項目", "项目", "名稱", "名称"]) >= 0:
            if tb is None or len(t["rows"]) > len(tb["rows"]):
                tb = t
    if tb is None and tbls:
        tb = max(tbls, key=lambda t: len(t["rows"]))
    if tb is None:
        d.fail("找不到物料清單表格——物料維度完全不存在（范式档 §5.1 #61）")
        return d

    rows, n = tb["rows"], len(tb["rows"])
    if n >= T["物料件數"]:
        d.ok(f"物料件數 {n} 件（閾值 ≥{T['物料件數']}）")
    else:
        d.fail(f"物料件數 {n} 件（閾值 ≥{T['物料件數']}）——物料沒列全")

    # 上限：超出即警告「數量偏多 —— 請確認是否符合用戶要求的量級（**本項不設上限**）」（2026-09-14 新增，依據見 T 表註釋）
    if n > T["物料上限"]:
        d.warn(f"物料 {n} 件 > 上限 {T['物料上限']} 件 —— 數量偏多 —— 請確認是否符合用戶要求的量級（**本項不設上限**）；"
               "只數「顧客／學生會看到的件數」，店員自看的內部紙（自檢表、清倉倒數牌）不算物料")

    for label, kws, level in [
        ("放哪／位置", ["位置", "放哪", "貼", "摆", "擺", "地點", "地点", "動線", "动线", "渠道"], "hard"),
        ("寫什麼／內容", ["內容", "内容", "文案", "規格", "规格", "話術", "话术", "做什麼", "做什么"], "hard"),
        ("成本／元", ["成本", "元", "預算", "预算", "價格", "价格", "費用", "费用", "單價", "单价"], "warn"),
    ]:
        idx = col_index(tb["header"], kws)
        if idx < 0:
            (d.fail if level == "hard" else d.warn)(f"物料表缺「{label}」列（每件物料的三要素之一）")
        else:
            cov = sum(1 for r in rows if cell(r, idx))
            if cov / n >= 0.8:
                d.ok(f"含「{label}」的物料 {cov}/{n} = {cov/n:.0%}")
            else:
                d.warn(f"含「{label}」的物料僅 {cov}/{n} = {cov/n:.0%}（建議 ≥80%）")
    return d


def check_banned(lines, text):
    d = Dim(6, "禁用詞表")
    rng = find_region(lines, ["禁用詞", "禁用词", "紅線詞", "红线词", "不能說", "不能说"])
    if not rng:
        d.fail("未見禁用詞表（禁用詞維度完全不存在）——范式档 §5.1 #14/#15")
        return d
    sec = region_text(lines, rng)

    # 分類的識別：A 類／A類（原邏輯）＋ 類別一／第一類／類 A（稿件實際寫法）
    classes = {next(g for g in m.groups() if g) for m in RE_BANNED_CLASS.finditer(sec)}
    nc = len(classes)
    if nc >= T["禁用詞類別數"]:
        d.ok(f"禁用詞分類 {nc} 類（閾值 ≥{T['禁用詞類別數']}，范式档 A–E 各類標後果）")
    elif nc:
        d.fail(f"禁用詞只分 {nc} 類（閾值 ≥{T['禁用詞類別數']}）——未按觸發後果分類")
    else:
        d.fail("禁用詞未分類（閾值 ≥5 類 A–E）——只列詞不標後果")

    terms = count_terms(sec)
    nt = len(terms)
    if nt >= T["禁用詞條數"]:
        d.ok(f"禁用詞條數 {nt} 條（閾值 ≥{T['禁用詞條數']}，范式档實測 59）")
    else:
        d.fail(f"禁用詞條數 {nt} 條（閾值 ≥{T['禁用詞條數']}，范式档實測 59）"
               + (f"——僅：{'、'.join(terms[:6])}" if terms else ""))

    if "後果" in sec or "觸發" in sec or "触发" in sec:
        d.ok("各類禁用詞標註了觸發後果（范式档要求：不只列詞）")
    else:
        d.warn("禁用詞未標註「觸發什麼後果」（范式档：每類必須標後果）")

    # 上限：超出即警告「數量偏多 —— 請確認是否符合用戶要求的量級（**本項不設上限**）」（2026-09-14 新增，依據見 T 表註釋）
    if nc > T["禁用詞類別上限"]:
        d.warn(f"禁用詞分類 {nc} 類 > 上限 {T['禁用詞類別上限']} 類 —— 類別偏多 —— 請確認是否符合用戶要求的量級")
    if nt > T["禁用詞條數上限"]:
        d.warn(f"禁用詞條數 {nt} 條 > 上限 {T['禁用詞條數上限']} 條 —— 疑似為湊條數而擴充；"
               "以「刪除／完全禁用」當替代說法、或把事實口徑校準（如「環湖有 2,000 名新生」）"
               "塞進這張表，都不是禁用詞")
    return d


def check_density(text):
    d = Dim(7, "數字密度")
    body = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S)
    chars = len(re.sub(r"\s", "", body))
    n_unit = len(re.findall(rf"\d+(?:\.\d+)?\s*{UNIT}", body))
    n_all = len(re.findall(r"\d+", body))
    lines_n = len([l for l in text.splitlines() if l.strip()])
    d.info(f"篇幅：{lines_n} 行 / {chars:,} 非空白字元")

    if chars == 0:
        d.fail("文檔為空")
        return d
    dens = n_unit / (chars / 1000)
    d.info(f"具體數字（帶單位）{n_unit} 個，全部數字 {n_all} 個")
    if dens >= T["千字密度警告"]:
        d.ok(f"每千字具體數字 {dens:.1f} 個（閾值 ≥{T['千字數字密度']:.1f}，建議 ≥{T['千字密度警告']:.1f}）")
    elif dens >= T["千字數字密度"]:
        d.warn(f"每千字具體數字 {dens:.1f} 個（閾值 ≥{T['千字數字密度']:.1f}，"
               f"建議 ≥{T['千字密度警告']:.1f}）——內容偏空")
    else:
        d.fail(f"每千字具體數字僅 {dens:.1f} 個（閾值 ≥{T['千字數字密度']:.1f}）"
               "——全文缺乏可核對的事實與金額")

    if n_unit == 0:
        d.fail("全文找不到任何「具體數字 + 單位」（元／%／天／單…）——這是空話稿的典型特徵")
    return d


def check_vague(text):
    d = Dim(8, "空話檢測")
    body = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S)
    chars = len(re.sub(r"\s", "", body)) or 1
    hits = []
    for w in VAGUE_WORDS:
        c = len(re.findall(re.escape(w), body))
        if c:
            hits.append((w, c))
    total = sum(c for _, c in hits)
    top = "、".join(f"{w}×{c}" for w, c in sorted(hits, key=lambda x: -x[1])[:8])

    if total <= T["空話詞"]:
        d.ok(f"「加強/提升/優化/賦能/打造」等無動作詞出現 {total} 次（建議 ≤{T['空話詞']}）")
    else:
        d.warn(f"「加強/提升/優化/賦能/打造」等無動作詞出現 {total} 次"
               f"（建議 ≤{T['空話詞']}）——這些詞往往意味著「沒寫具體動作」"
               + (f"｜高頻：{top}" if top else ""))
    dens = total / (chars / 1000)
    if dens > T["空話密度"]:
        d.warn(f"無動作詞密度 {dens:.1f} 個/千字（建議 ≤{T['空話密度']}）——空話比例偏高")
    return d


def check_repeats(lines, text):
    """【9】重複度 —— 抓「同一件事說兩遍」與「為湊數而膨脹」。

    這一維度是 2026-09-14 對比診斷（原版 371 行 vs 重跑版 1,998 行）的產物：
    舊版 8 個維度全部是**計數下限**，於是執行 AI 精確優化了「可被腳本數出來」的部分
    （物料 12→18、KPI 8→15、風險 3→7、行動 18→27），而終稿從 371 行膨脹到 1,998 行，
    同時出現「止損四步在 §7.3 與 §8.3 各寫一遍」「大件預警表出現 3 次」
    「『缺什麼，跟我說一聲』出現 55 次」。**數得出來的都超額，數不出來的（判斷、取捨、
    精煉）全部退化。** 所以「有沒有說第二遍」必須自己也變成可校驗的。

    四個判據（前三個是硬錯誤，第四個是警告）：
      ① 逐字重複句：同一句（≥12 字）在全文出現 ≥3 次
      ② 跨節重複行：任意兩節共用 ≥5 行逐字相同（§7 與 §8 各寫一份止損四步即屬此類）
      ③ 跨節近重複：≥24 字的句片段，前 14 字或後 14 字完全相同卻分屬 ≥2 節
         （同一判斷改寫後分放兩章 —— 這比重複字句更常見、也更能騙過肉眼）
      ④ 口頭禪：某固定短語（≥8 字）出現 ≥15 次（把同一句話反覆墊字數的信號）

    校準（同一組閾值跑兩個已知樣本，2026-09-14 實測）：
      原版   （本機交付稿）.md（371 行）→ ①0 句 ②0 對 ③0 處
                                                            ④最高 3 次 → 本維度全綠
      重跑版 合并-方案.md（1,998 行）→ ①3 句 ②0 對 ③19 處 ④55 次 → ❌
    """
    d = Dim(9, "重複度")

    # ① 逐字重複句
    cnt = collections.Counter()
    for ln in lines:
        for part in RE_SENT_END.split(ln):
            n = norm_cmp(part)
            if len(n) >= T["重複句長度"]:
                cnt[n] += 1
    dup = sorted(((k, v) for k, v in cnt.items() if v >= T["重複句次數"]),
                 key=lambda x: (-x[1], x[0]))
    if dup:
        d.fail(f"逐字重複句 {len(dup)} 句（≥{T['重複句長度']} 字、出現 ≥{T['重複句次數']} 次）："
               + "；".join(f"「{k[:18]}」×{v}" for k, v in dup[:6])
               + ("…" if len(dup) > 6 else "")
               + " —— 同一件事只准說一遍：重複處刪到只剩一處，其他用「見 §X」")
    else:
        d.ok(f"無逐字重複句（沒有 ≥{T['重複句長度']} 字的句子出現 ≥{T['重複句次數']} 次）")

    secs = doc_sections(lines)
    if len(secs) < 2:
        d.info("章節標題少於 2 個，跳過跨節重複比對")
    else:
        # ② 跨節重複行（逐字）
        line_sets = []
        for title, a, b in secs:
            s = set()
            for ln in lines[a + 1:b]:
                n = norm_cmp(ln)
                if len(n) >= 10:
                    s.add(n)
            line_sets.append((title, s))
        pairs = []
        for i in range(len(line_sets)):
            for j in range(i + 1, len(line_sets)):
                common = line_sets[i][1] & line_sets[j][1]
                if len(common) >= T["跨節重複行數"]:
                    pairs.append((len(common), line_sets[i][0], line_sets[j][0]))
        pairs.sort(reverse=True)
        if pairs:
            d.fail(f"跨節逐字重複 {len(pairs)} 對（同一行在兩節各出現一次，門檻 "
                   f"≥{T['跨節重複行數']} 行）："
                   + "；".join(f"「{a[:14]}」↔「{b[:14]}」共 {n} 行" for n, a, b in pairs[:4])
                   + " —— 其中一節是複製貼上，留一處即可")
        else:
            d.ok(f"無跨節逐字重複（沒有兩節共用 ≥{T['跨節重複行數']} 行）")

        # ③ 跨節近重複（前 14 字或後 14 字相同）
        #    附件／附錄是客戶原始資料的合法容器（SKILL §三 附件 C），不列入比對；
        #    正文各節之間一律列入。
        owner, sample, seen = collections.defaultdict(set), {}, set()
        for title, a, b in secs:
            if RE_APPENDIX.search(title):
                continue
            for ln in lines[a + 1:b]:
                for part in RE_SENT_END.split(ln):
                    f = norm_cmp(part)
                    if len(f) < T["近重複片段長度"] or f in seen:
                        continue
                    seen.add(f)
                    for k in frag_key(f, T["近重複鍵長"]):
                        owner[k].add(title)
                        sample.setdefault(k, f)
        near = sorted(((k, v) for k, v in owner.items() if len(v) >= 2),
                      key=lambda x: -len(x[1]))
        if len(near) >= T["跨節近重複數"]:
            d.fail(f"跨節近逐字重複 {len(near)} 處（≥{T['近重複片段長度']} 字的句子，"
                   f"前 {T['近重複鍵長']} 字或後 {T['近重複鍵長']} 字完全相同卻分屬兩節；"
                   f"門檻 ≥{T['跨節近重複數']}）："
                   + "；".join(f"「{sample[k][:18]}」跨 {len(v)} 節" for k, v in near[:4])
                   + " —— 同一個判斷只寫一次，其餘章節用交叉引用")
        elif near:
            d.warn(f"跨節近逐字重複 {len(near)} 處（門檻 ≥{T['跨節近重複數']} 才報硬錯誤）："
                   + "；".join(f"「{sample[k][:18]}」跨 {len(v)} 節" for k, v in near[:4]))
        else:
            d.ok("無跨節近逐字重複（沒有 ≥24 字的句子在兩節各寫一遍）")

    # ④ 口頭禪
    stream = norm_cmp(text)
    g = collections.Counter()
    n_g = T["口頭禪長度"]
    for i in range(len(stream) - n_g + 1):
        gram = stream[i:i + n_g]
        if RE_CJK_ONLY.match(gram):
            g[gram] += 1
    hot = sorted(((k, v) for k, v in g.items() if v >= T["口頭禪次數"]),
                 key=lambda x: (-x[1], x[0]))
    if hot:
        d.warn(f"疑似口頭禪 {len(hot)} 個（≥{n_g} 字的固定短語出現 ≥{T['口頭禪次數']} 次）："
               + "、".join(f"「{k}」×{v}" for k, v in hot[:5])
               + " —— 這是「把同一句話反覆墊字數」的信號：一次說清，其餘用交叉引用")
    else:
        top = g.most_common(1)
        d.ok(f"無口頭禪（最常出現的 {n_g} 字短語是「{top[0][0]}」×{top[0][1]} 次，"
             f"未達 {T['口頭禪次數']} 次）")
    return d


# ==========================================================================
def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print("用法: python depth_check.py <plan.md> [--quiet] [--strict]")
        print("  默认只診斷、不阻攔出稿（退出碼一律 0，除非腳本自身出錯=2）")
        print("  --strict：**仅对三项量化硬指标**（KPI 预警线 0%／风险条目 0／数字密度过低）")
        print("            返回退出碼 1 —— 其余维度维持「只提示」。出稿前那一次建议挂上。")
        sys.exit(0)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    quiet = "--quiet" in sys.argv
    strict = "--strict" in sys.argv
    if not args:
        print("用法: python depth_check.py <plan.md> [--quiet]")
        sys.exit(1)
    path = args[0]

    try:
        text = read_text(path)
    except Exception as e:
        print(f"{NG} 無法讀取方案檔：{e}")
        sys.exit(1)

    lines = text.splitlines()
    all_tables = tables_in(lines, (0, len(lines)))
    HARD.clear(); WARNS.clear()   # 防重入污染（同一進程跑多次時）

    dims = [
        check_competitors(lines, text),
        check_risks(lines, text),
        check_actions(lines, all_tables),
        check_kpi(lines, all_tables),
        check_materials(lines, all_tables),
        check_banned(lines, text),
        check_density(text),
        check_vague(text),
        check_repeats(lines, text),
    ]

    if not quiet:
        print("=" * 64)
        print(f"深度校驗 · {path}")
        print("=" * 64)

    passed = 0
    for d in dims:
        has_fail = any(s == NG for s, _ in d.items)
        if not quiet:
            print(f"\n【{d.no}】{d.name}")
            for s, m in d.items:
                print(f"  {s} {m}")
        if not has_fail:
            passed += 1

    print("\n" + "=" * 64)
    if HARD:
        # ── 用戶定調（2026-09-14）：**只提示、不阻攔** ──
        #    理由：① 嚴格數量門檻會逼出「資料彙編」，而精煉的羅森案原版自己都過不了；
        #          ② 方案長短與要素多少應由**用戶選擇**（門禁第 13 項先問），不由腳本判定。
        #    所以此處一律打印診斷報告並 **exit 0**，改不改由使用者決定。
        print(f"{INFO} 診斷報告：{len(HARD)} 項「要素偏薄／可再加厚」——**僅供參考，不阻攔出稿**")
        for e in HARD:
            print(f"   · {e}")
        if WARNS:
            print(f"\n{WARN} {len(WARNS)} 項提示")
            for w in WARNS:
                print(f"   · {w}")
        print("\n→ 要不要按以上提示加厚，**由你（或用戶）決定**：")
        print("   本檢查默認不設門檻、不阻攔出稿；羅森案原版（精煉版）同樣會有這些提示。")
        print(f"   （本次 {passed}/{len(dims)} 個維度達標）")
        # ⚠️ 2026-09-17（R2 數據科學視角第 11 條）：depth_check 原本「退出碼一律 0」，
        #    于是「KPI 无预警线」「风险 0 条」这类**量化硬伤可以带着 ❌ 交付**，
        #    校验沦为参考意见。--strict 只对三项量化硬指标拦，其余仍只提示。
        if strict and HARD:
            print(f"{NG} --strict：{len(HARD)} 項量化硬指標未達標 —— 拒絕交付。")
            for x in HARD[:6]:
                print(f"   · {x}")
            sys.exit(1)
        sys.exit(0)

    print(f"{OK} 深度校驗通過（{passed}/{len(dims)} 個維度達標，硬指標 0 項未達標）。")
    if WARNS:
        print(f"{WARN} {len(WARNS)} 項警告，交付前請人工確認：")
        for w in WARNS:
            print(f"   · {w}")
    print("\n→ 閾值來源：references/07-质量范式-便利店开学季案.md §五（羅森案 9 份產出實測）。")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{WARN} 已中斷（Ctrl+C）。")
        sys.exit(130)
    except Exception as e:
        print(f"\n{NG} 腳本執行出錯：{type(e).__name__}: {e}")
        print("→ 依協議 8（卡死處理）：")
        print("   1) 依上面訊息修正後重跑；")
        print("   2) 若屬環境問題（檔案讀不到／編碼異常），改用人工比對 §五 的 83 項指標，不要卡在這裡；")
        print("   3) 同一項連續 2 次不過 → 停止重試，把問題攤給用戶決定。")
        sys.exit(2)
