#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""start_here.py — 開新會話的第一條命令（**用「查」代替「讀」**）

為什麼要有它（用戶 2026-09-17 指出）：
    「**下一次不是還要重新讀**」
    這是真問題：倉庫已經長到 references/ 8.2M、14 份編號參考 ＋ 52 份行業案例 ＋
    293 節範式庫 ＋ 116 條打法。**每次開新會話，執行 AI 都得從頭讀一遍** ——
    整理目錄只解決「人找得到」，沒解決「AI 讀得少」。

它怎麼解決：
    把「讀什麼」從**通讀**變成**查詢**。三條子命令：
      --client "客戶情況…"  → 只輸出「**該讀哪幾份、讀哪一節、多少字**」＋「**明確不要讀什麼**」
      --grep  "關鍵詞"      → 跨庫檢索，只回傳命中的行（**替代通讀整份檔**）
      --files               → 全庫清單＋字數（讓你知道預算，再決定讀不讀）

    ⛔ 它的輸出**不是文件**，是**給執行 AI 的閱讀清單**。
       讀完這份清單（約 20 行），就知道這單案子該碰哪 2000 字、不該碰哪 40 萬字。

用法：
    python scripts/start_here.py --client "武漢光谷川菜館，一家店，人均 60，客流掉三成"
    python scripts/start_here.py --grep "場景化"
    python scripts/start_here.py --files
"""
import argparse
import glob
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REF = os.path.join(ROOT, "references")
CASES = os.path.join(REF, "cases")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import OK, NG, WARN, HINT   # noqa: E402  统一符号（不要在各自文件里重定义）

# 「明確不要讀」清單：這些檔**只能按需查單節**，通讀是浪費
NEVER_READ_THROUGH = {
    "03-方法论操作手册.md": "13 萬字、111 個模型 —— 只按需查單個模型碼，不通讀",
    "00-打法库.md": "116 條打法 —— 只讀 §0 一頁速查表，其餘按 §編號查",
    "04-失败归因总库.md": "12 模式 ＋ 34 條預演 —— 由 `composer --internal` 自動注入相關條目",
}
# 推薦給「不確定」時的第一份（最小可用組合）
STARTER = ["SKILL.md", "references/12-范式库.md"]


def read(p):
    try:
        return io.open(p, encoding="utf-8").read()
    except Exception:
        return ""


def n_chars(p):
    return len(re.sub(r"\s", "", read(p)))


def human(n):
    return f"{n/10000:.1f} 萬字" if n >= 10000 else f"{n} 字"


def load_map():
    try:
        return json.loads(read(os.path.join(HERE, "knowledge_map.json")))
    except Exception:
        return {}


def infer_case_file(client, kmap):
    """**複用 composer 已驗過的 `infer_industry`**，不自己寫一份。

    ⚠️ 教訓（本腳本第一次寫時踩的）：我原本用 bigram 相似度猜行業檔，結果
    「武漢光谷川菜館」被判成 `25-潮玩文创IP.md` —— **噪聲當信號**。
    `knowledge_map.industry_to_cases` 是**最長關鍵詞優先**的確定性映射（已被 kb_audit 驗過），
    直接用它才對。**同一個判斷不要有兩份實現。**
    """
    if not client:
        return "", 0
    sys.path.insert(0, HERE)
    try:
        import composer as C
        f = C.infer_industry({"賣什麼": client, "賣給誰": client, "品类": client}, kmap)
        if f:
            # ⚠️ 映射表裡的值**不帶 .md 後綴**（如 "03-美妆个护"）—— 第一次沒補後綴，
            #    於是每個客戶都判成「匹配度不足」。補上再驗存在性。
            base = os.path.basename(f)
            for cand in (os.path.join(CASES, base + ".md"),
                         os.path.join(CASES, base),
                         os.path.join(REF, base + ".md"),
                         os.path.join(REF, base)):
                if os.path.exists(cand):
                    return cand, 99
    except Exception as e:
        # 不许静默：行业判定失败会被读成「这个客户没有对应行业档」，
        # 而实际是判定本身出错 —— 两者对下游的含义完全不同。
        print(f"  {WARN} 行业判定失败（{type(e).__name__}）—— 请手工指定案例档", file=sys.stderr)
    return "", 0


def matched_routes(client, kmap):
    hits = []
    for r in kmap.get("路由规则", []):
        got = [k for k in r["kw"] if k in client]
        if got:
            hits.append((len(got), got, r["方向"]))
    hits.sort(key=lambda x: -x[0])
    return hits


def cmd_client(client, _):
    kmap = load_map()
    print("=" * 68)
    print("開新會話第一步 · 這單案子該讀什麼（**別通讀**）")
    print("=" * 68)

    total = sum(n_chars(f) for f in glob.glob(os.path.join(REF, "**", "*.md"), recursive=True)
                if os.path.isfile(f))
    print(f"\n全庫體量：references/ 約 {human(total)}（通讀一遍＝燒掉大量上下文）")
    print(f"本清單把「要讀的」壓到 3 份以內。\n")

    print("【① 必讀（按這個順序）】")
    n = 0
    for rel in STARTER:
        p = os.path.join(ROOT, rel)
        if os.path.exists(p):
            n += 1
            print(f"  {n}. {rel}　（{human(n_chars(p))}）")
    note = ("· SKILL.md：只讀 §0 門禁 13 項 ＋ §二路由表 ＋ §六自檢清單，**不用通讀**\n"
            "· 12-范式库.md：**只讀你這單對應的那一檔**（速覽／标准／大赛／B端／G端／投标），約 1 萬字")
    print(f"     {note}")

    hits = matched_routes(client, kmap)
    if hits:
        print("\n【② 客户狀況命中的打法方向（去 00-打法库.md 按 §編號查，不要通讀）】")
        for cnt, kws, dirs in hits[:4]:
            print(f"  · 命中 {cnt} 個關鍵詞（{'、'.join(kws[:4])}）→ {'、'.join(dirs[:6])}")

    cf, score = infer_case_file(client, kmap)
    if cf and score >= 4:
        print(f"\n【③ 最相關的行業案例檔】{os.path.relpath(cf, ROOT)}（{human(n_chars(cf))}）")
        print("     → **只讀「案例清單」那一段**（30 秒掃完），挑中 1–3 條再看「深度拆解」")
    else:
        print(f"\n【③ 行業案例】匹配度不足，**先別讀案例庫**；等門禁問完行業再來查（--grep 更快）")

    print("\n【④ 明確不要通讀】")
    for f, why in NEVER_READ_THROUGH.items():
        print(f"  ⛔ {f} —— {why}")
    print("  ⛔ 另外 51 個**非本行業**案例檔")

    print("\n【⑤ 想查某個詞，用檢索代替通讀】")
    print('  python scripts/start_here.py --grep "場景化"')

    print("\n【⑥ 下一步】")
    print("  python scripts/flow.py --dir 案子目錄     # 看目前卡在哪一步")
    print("  python scripts/composer.py --rules rules.json --out skeleton.md --tier 标准 --internal skeleton.internal.md")
    print("=" * 68)


def cmd_grep(kw, _):
    print("=" * 68)
    print(f'跨庫檢索：「{kw}」（**用查代替讀**）')
    print("=" * 68)
    hits, files = 0, {}
    for f in sorted(glob.glob(os.path.join(REF, "**", "*.md"), recursive=True)):
        if not os.path.isfile(f):
            continue
        for i, ln in enumerate(read(f).split("\n"), 1):
            if kw in ln:
                hits += 1
                rel = os.path.relpath(f, ROOT)
                files.setdefault(rel, []).append((i, ln.strip()[:96]))
    if not hits:
        print(f"{WARN} 沒命中。換個詞，或先跑 --files 看有哪些檔。")
        return
    for rel, ls in list(files.items())[:14]:
        print(f"\n{rel}（{len(ls)} 處）")
        for i, s in ls[:3]:
            print(f"   {i}: {s}")
        if len(ls) > 3:
            print(f"   …另有 {len(ls)-3} 處")
    print(f"\n{HINT} 共 {hits} 處、{len(files)} 個檔。**只讀命中的那幾行，不要通讀整份檔。**")


def cmd_files(_, __):
    print("=" * 68)
    print("全庫清單（**先看字數，再決定讀不讀**）")
    print("=" * 68)
    rows = []
    for f in sorted(glob.glob(os.path.join(REF, "*.md"))):
        rows.append((os.path.relpath(f, ROOT), n_chars(f)))
    cn = sum(n_chars(f) for f in glob.glob(os.path.join(CASES, "*.md")))
    rows.append((f"references/cases/（{len(glob.glob(os.path.join(CASES, '*.md')))} 檔）", cn))
    for f in sorted(glob.glob(os.path.join(REF, "范例", "*.md"))):
        rows.append((os.path.relpath(f, ROOT), n_chars(f)))
    for rel, n in sorted(rows, key=lambda x: -x[1]):
        flag = "  ⛔ 別通讀" if os.path.basename(rel) in NEVER_READ_THROUGH else ""
        print(f"  {human(n):>10}  {rel}{flag}")
    print(f"\n  {'合計':>10}  {human(sum(n for _, n in rows))}")


def main():
    ap = argparse.ArgumentParser(description="開新會話第一步：告訴你該讀什麼、明確不要讀什麼")
    ap.add_argument("--client", default="", help="客戶情況一段話（門禁答案或 brief）")
    ap.add_argument("--grep", default="", help="跨庫檢索（替代通讀）")
    ap.add_argument("--files", action="store_true", help="全庫清單＋字數")
    a = ap.parse_args()
    if a.grep:
        cmd_grep(a.grep, None)
    elif a.files:
        cmd_files(None, None)
    elif a.client:
        cmd_client(a.client, None)
    else:
        cmd_client("", None)
        print(f"\n{WARN} 沒給 --client，上面是通用清單。給了客戶情況會更準。")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{WARN} 已中斷。")
        sys.exit(130)
    except Exception as e:
        print(f"\n{NG} start_here 執行出錯：{type(e).__name__}: {e}")
        print(f"{HINT} 依協議 8：直接用 SKILL.md 的「第 -1 步」手工判斷要讀哪幾份，不要卡在這裡。")
        sys.exit(2)
