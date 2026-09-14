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

退出碼：0 = 深度達標；1 = 有硬指標不達標；2 = 腳本自身出錯

判斷分三級（與 selfcheck.py 一致）：
    ❌ 硬指標 → 退出碼 1，必須補
    ⚠️ 警告   → 需人工確認（不影響退出碼）
    ✅ 通過

閾值來源：所有數字取自 `references/范本-罗森案范式.md`（以下簡稱「范式档」），
         每條閾值旁標註「§X.Y #N」即該文件第 X.Y 節第 N 項實測值，未經改寫。
         凡標「推導」者，表示范式档未直接給出該數字，由相鄰實測項保守反推。

--------------------------------------------------------------------------
自測記錄（2026-09-14）
測試樣本：$HOME/Desktop/Marketing-skill/example-山霧茶飲開業季方案.md
          （166 行，由 示例交付稿-山霧茶飲開業季方案.docx 還原；該 docx 八篇目錄
          齊全、12 項自檢單全 ✅，是典型「結構對但很空」的空殼稿 ——
          selfcheck.py 可全綠，本腳本應報多項 FAIL。）

實跑：python3 depth_check.py example-山霧茶飲開業季方案.md
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
"""

import re
import sys

OK, NG, WARN, INFO = "✅", "❌", "⚠️", "ℹ️"

# ==========================================================================
# 閾值表 —— 全部來自 范式档 §五「可被脚本校驗的深度指標」
# ==========================================================================
T = {
    # 【1】競品掃描深度
    "致命弱點": 5,        # 范式档 §5.1 #8（實測 5，「每環節 1 個」）
    "競品環節數": 5,      # 范式档 §5.1 #9（實測 5 個環節）
    "次要對手數": 3,      # 范式档 §5.1 #11（實測 3 股次要力量）
    "總競品數": 4,        # 范式档 §2.2.1 校驗表（頭號 + 3 = 實測 4）
    # 【2】風險四件套
    "風險條數": 3,        # 范式档 §5.1 #23（實測 3 條）
    "兜底係數": 3,        # 范式档 §5.1 #25（「兜底」≥ 風險數 × 3；實測 10）
    "兜底步數": 3,        # 范式档 §5.1 #28（每條兜底 ≥3 步；實測 4 步）
    "預防性動作": 2,      # 范式档 §5.1 #26（實測 2 處）
    # 【3】行動清單六要素
    "行動條數": 15,       # 范式档 §5.1 #71（實測 18 條）
    "行動含數字比": 0.80, # 推導：范式档 §5.1 #71–73（18 條幾乎條條含數量/時刻）
    "今天條數": 3,        # 范式档 §5.1 #73（實測 5 條）
    # 【4】KPI 深度
    "KPI行數": 6,         # 范式档 §5.1 #34（實測 8 = 日常 6 + 報到日 2）
    "預警線比": 1.00,     # 范式档 §5.1 #34 / 模板 10（實測 8/8 = 100%）
    "基准值比": 0.80,     # 推導：范式档 §4.1 做法 #2（每個數字帶時間點或觸發條件）
    "觀測方式比": 0.80,   # 推導：范式档 §5.1 #34（「怎麼算」列實測 100%）
    # 【5】物料清單
    "物料件數": 12,       # 范式档 §5.1 #61（實測 12 件）
    # 【6】禁用詞表
    "禁用詞類別數": 5,    # 范式档 §5.1 #14（實測 5 類 A–E）
    "禁用詞條數": 40,     # 范式档 §5.1 #15（實測 59 條）
    # 【7】數字密度
    "千字數字密度": 5.0,  # 推導：范式档 §5 未直接給；見 §4.1 做法 #1/#2 反推保守下限
    "千字密度警告": 8.0,  # 推導：同上，取建議值
    # 【8】空話檢測
    "空話詞": 5,          # 推導：范式档 §4.2 反面清單（「全文沒有一個不可驗收的指標」）
}

# 空話／無動作詞（范式档 §4.2：這類詞是「沒寫具體動作」的信號）
VAGUE_WORDS = [
    "加強", "加强", "提升", "優化", "优化", "賦能", "赋能", "打造", "做好",
    "重視", "重视", "注重", "夯實", "夯实", "助力", "深化", "增強", "增强",
    "全方位", "全面提升", "進一步", "进一步", "持續發力", "持续发力", "大力",
]

# 量詞白名單 —— 用來識別「具體數字」（金額／比例／天數／數量）
UNIT = (r"(?:元|塊|块|萬元|万|%|％|天|週|周|日|月|年|單|单|人|篇|份|張|张|個|个|"
        r"次|小時|小时|分鐘|分钟|秒|公里|米|㎡|倍|折|檔|档|條|条|行|列|項|项|點|点|"
        r"杯|套|種|种|家|間|间|位|名|組|组|公里|KG|kg|L|ml|SKU)")


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
            if idx == 1 and cells and all(re.fullmatch(r":?-{2,}:?", c or "-") for c in cells):
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
    """找出所有「風險 N」型標題區塊 → [(title, text)]"""
    n, out = len(lines), []
    for i, ln in enumerate(lines):
        m = re.match(r"^(#{2,6})\s*(.+?)\s*$", ln)
        if not m:
            continue
        title = m.group(2)
        if not re.search(r"風險|风险", title):
            continue
        # 排除章節名（風控／風險與假設／風險偏好…）
        if re.search(r"風控|风控|風險與|风险与|風險偏好|风险偏好|風險等級|风险等级", title):
            continue
        if not re.search(r"(風險|风险)\s*(?:\d|[一二三四五六七八九十]|[:：]|條|条|$)", title):
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
def check_competitors(lines, text):
    d = Dim(1, "競品掃描深度")

    weak = len(re.findall(r"致命弱點|致命弱点", text))
    d.ok(f"「致命弱點」出現 {weak} 次（閾值 ≥{T['致命弱點']}）") if weak >= T["致命弱點"] else \
        d.fail(f"「致命弱點」出現 {weak} 次（閾值 ≥{T['致命弱點']}；范式档要求每個拆解環節 1 個）")

    rounds = len(re.findall(r"^#{2,6}[^\n]*(?:環節|环节)", text, re.M))
    if rounds == 0:
        d.fail("競品拆解環節 0 個（閾值 ≥5）——未見「#### 環節N」式拆解，"
               "等於沒做競品掃描")
    elif rounds < T["競品環節數"]:
        d.fail(f"競品拆解環節 {rounds} 個（閾值 ≥{T['競品環節數']}）")
    else:
        d.ok(f"競品拆解環節 {rounds} 個（閾值 ≥{T['競品環節數']}）")

    # 四段式完整度：他們怎麼做／強點／致命弱點／我們的打法
    labels = {
        "他們怎麼做": r"他們怎麼做|他们怎么做",
        "強點": r"強點|强点",
        "致命弱點": r"致命弱點|致命弱点",
        "我們的打法": r"我們的打法|我们的打法",
    }
    counts = {k: len(re.findall(v, text)) for k, v in labels.items()}
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

    # 一票否決 V2：每條風險必須有「預警信號」且含數字
    no_signal, no_digit, min_steps = [], [], []
    for title, body in blocks:
        short = re.split(r"[（(：:\s]", title.replace("風險", "").replace("风险", "").strip())[0] or title
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

    today = len(re.findall(r"今天|立刻|马上|馬上|立即", "\n".join(" ".join(r) for r in rows)))
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

    classes = set(re.findall(r"^\s*(?:\*\*)?\s*([A-EＡ-Ｅ])\s*類", sec, re.M))
    classes |= set(re.findall(r"[」（(]\s*([A-EＡ-Ｅ])\s*類", sec))
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
    if dens > 6:
        d.warn(f"無動作詞密度 {dens:.1f} 個/千字（建議 ≤3）——空話比例偏高")
    return d


# ==========================================================================
def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    quiet = "--quiet" in sys.argv
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

    dims = [
        check_competitors(lines, text),
        check_risks(lines, text),
        check_actions(lines, all_tables),
        check_kpi(lines, all_tables),
        check_materials(lines, all_tables),
        check_banned(lines, text),
        check_density(text),
        check_vague(text),
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
        print(f"{NG} 深度校驗不通過：{len(HARD)} 項硬指標未達標")
        for e in HARD:
            print(f"   · {e}")
        if WARNS:
            print(f"\n{WARN} {len(WARNS)} 項警告")
            for w in WARNS:
                print(f"   · {w}")
        print("\n→ 這些是「結構完整但內容空」的典型信號。補完後重跑。")
        print(f"   （本次 {passed}/{len(dims)} 個維度無硬指標不達標）")
        sys.exit(1)

    print(f"{OK} 深度校驗通過（{passed}/{len(dims)} 個維度達標，硬指標 0 項未達標）。")
    if WARNS:
        print(f"{WARN} {len(WARNS)} 項警告，交付前請人工確認：")
        for w in WARNS:
            print(f"   · {w}")
    print("\n→ 閾值來源：references/范本-罗森案范式.md §五（羅森案 9 份產出實測）。")
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
