#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""promise_check.py — 「文档承诺 ↔ 实际执行」对账关

為什麼要有它（2026-09-17，三個 agent 審出來的元規律）：
    三個 agent（BCG／貝恩／4A）各獨立審一遍，31 條候選裡有 **9 條是同一個病**：
    **能力寫在文檔裡，但沒有一條鏈路真的執行它。**
    · `09` 說「不許形容詞堆砌」→ 腳本一直沒有 AI 腔詞表
    · `SKILL` 說「風險要掛失敗歸因」→ 腳本反而攔這個編號
    · `SKILL` 承諾了「核心結論卡片／2.3／7.3／附件 A–E」→ composer 根本不生成
    · `paradigm_data` 的 must 說「要寫主動放棄了什麼」→ 零腳本消費
    · `04-失败归因总库` 有 34 條失敗預演 → 零消費
    · 打法庫的「難度」字段 → 解析進內存又丟掉
    跟之前那批 bug 同族：**文檔承諾 ≠ 機械執行**。

本腳本做三件**可機械化**的對賬（承諾本身是散文，無法全自動，所以只做能機械化的部分）：
    ① **字段消費**：composer 解析了打法庫的哪些字段？每個是否**真的被印進輸出**？
       （專抓「解析進內存又丟掉」這一類——「難度」「不適用」就是實測踩到的）
    ② **參考文件消費**：references/ 下每個檔，是否**有被某支腳本真的讀到**？
       （專抓「46,010 字的庫零消費」這一類）
    ③ **骨架承諾消費**：`paradigm_data.GUIDE` 裡每節的 `must` 約定，在 selfcheck 裡
       有沒有對應的**可判定關卡**？（must 裡用了粗體**必須**的點，最好都有腳本管）

用法：
    python scripts/promise_check.py                 # 全量對賬
    python scripts/promise_check.py --report 對賬.md

退出碼：0 無未消費；1 有（默認只報、不阻，畢竟有些「零消費」是故意的）
"""
import argparse
import glob
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REF = os.path.join(ROOT, "references")

OK, NG, WARN, HINT = "✅", "❌", "⚠️", "→"


def read(p):
    return io.open(p, encoding="utf-8").read()


def py_files():
    return sorted(glob.glob(os.path.join(HERE, "*.py")))


# 解析端用的「內部欄位」：這些是解析/路由用的原始材料，本來就不用印進輸出
_INTERNAL_FIELDS = {"raw", "cases_raw", "cases", "case_line", "id", "major", "name"}


def field_consumption():
    """① composer 解析了哪些字段、每個是否被印進輸出。

    ⚠️ 2026-09-17 实测误报并修正：① 输出端写的是 `p.get('difficulty')`（**单引号**），
       初版只查双引号 → 把明明已输出的字段全判成「未输出」；② `raw/cases_raw` 这类
       是解析用的中间材料，本来就不该进输出 —— 列入 `_INTERNAL_FIELDS` 豁免。
    """
    src = read(os.path.join(HERE, "composer.py"))
    keys = sorted(set(re.findall(r'p\["(\w+)"\]\s*=', src)))
    m = re.search(r"def play_block\(.*?(?=\ndef )", src, re.S)
    lite = re.search(r"def build_lite\(.*?(?=\ndef )", src, re.S)
    skel = re.search(r"def build_skeleton\(.*?(?=\ndef )", src, re.S)
    out_src = (m.group(0) if m else "") + (lite.group(0) if lite else "") \
        + (skel.group(0) if skel else "")
    missing = []
    for k in keys:
        if k in _INTERNAL_FIELDS:
            continue
        # 同时认 p["k"] / p['k'] / p.get("k") / p.get('k') 四种写法
        pat = (r'p\s*\[\s*[\"\']' + re.escape(k) + r'[\"\']\s*\]'
               r'|p\.get\(\s*[\"\']' + re.escape(k) + r'[\"\']')
        if not re.search(pat, out_src):
            missing.append(k)
    return keys, missing


# 這些檔**本來就是給人（或給執行 AI）讀的參考冊**，不該被腳本消費 —— 屬「僅供人工」豁免
_HUMAN_FACING = {
    "01-接案输出模板.md": "寫方案時給人看的逐章指南",
    "02-多Agent分工简报.md": "五份給人複製的角色簡報",
    "10-文案与物料样本库.md": "給人抄的文案母版",
    "13-顶级机构对标标准.md": "對標量表，給人打分定位用",
    "11-防返工交付协议.md": "交付鐵律，給人與執行 AI 讀",
    "07-质量范式-便利店开学季案.md": "質量標尺範例",
}
# 這些檔**是知識資產，本來就該被腳本消費** —— 零消費＝真問題（元規律的實證）
_MUST_CONSUME = {
    "04-失败归因总库.md": "46,010 字、34 條失敗預演；R1 的貝恩 agent 已指出它零消費，待接入 composer --premortem",
}


def reference_consumption():
    """② references/*.md 頂層檔，是否有腳本讀到（用檔名在腳本源碼裡出現判定）。

    ⚠️ 2026-09-17 实测误报并修正：01/02/10/13 這類是**人讀的參考冊**，被腳本讀到
       才奇怪 —— 不能一律當「零消費」。所以分三類：
         · _HUMAN_FACING（僅供人工，豁免）  · _MUST_CONSUME（該消費，零消費＝真問題）
         · 其餘（有腳本讀最好，沒讀只提醒）
    """
    refs = sorted(glob.glob(os.path.join(REF, "*.md")))
    # ⚠️ 「提到檔名」≠「讀了內容」。這三支腳本只是在**註釋/描述串**裡提到檔名，並沒有真的讀：
    #    file_meta（檔名索引器）、promise_check（就是本腳本自己）、relocate_06（一次性遷移，
    #    只在一行註釋裡點名）。不排除它們，「零消費」就會被誤判成「已消費」（引用 ≠ 消費）。
    _NON_CONSUMER = {"file_meta.py", "promise_check.py", "relocate_06.py"}
    scripts_src = "\n".join(read(f) for f in py_files()
                              if os.path.basename(f) not in _NON_CONSUMER)
    unreads, should_miss, exempt = [], [], []
    for f in refs:
        base = os.path.basename(f)
        if base in scripts_src:
            continue
        if base in _HUMAN_FACING:
            exempt.append(base)
        elif base in _MUST_CONSUME:
            should_miss.append(base)
        else:
            unreads.append(base)
    cases_globbed = bool(re.search(r"references.*cases|CASES\s*=", scripts_src))
    return unreads, should_miss, exempt, cases_globbed


# 判据對賬表（curated，防誤報）：R1 期間逐項補上、並被「selfcheck 腳本」承載的判據。
# 一旦有人把對應的關卡刪掉，這張表就會把「承諾又變回零執行」抓出來 —— 它是回歸守衛。
_CONTRACTS = {
    "为什么这么做须含实质": "至少含一條實質",
    "执行摘要门槛": "執行摘要不達標",
    "AI 腔拦截": "AI 腔",
    "场景章深度": "場景章內容不達標",
    "Big Idea 判据": "Big Idea",
    "利益相关者章": "利益相关者",
    "Red Team 定长三条": "Red Team",
    "洞察萃取": "洞察萃取",
    "主动放弃 ≥2": "「主动放弃了什么」不足",
    "议题树 H 被引用": "议题树",
    "交叉引用有效性": "指向不存在的章節",
    "施工语气拦截": "給 AI 的施工說明",
    "自检单防伪": "自檢單防偽",
}


def must_consumption():
    """③ 判據對賬：`_CONTRACTS` 裡每個承諾，selfcheck 裡必須有對應的可判定關。

    為什麼不用「掃 GUIDE.must 的關鍵詞」：那會把 38 節都誤報成「沒有關卡」——
    must 是散文，散文的可判定約定和 selfcheck 的檢查詞不會字面重合。
    所以改用 **curated 對賬表**：承諾 → 判據關鍵詞，顯式、可回歸、零誤報。"""
    sc = read(os.path.join(HERE, "selfcheck.py"))
    uncovered = [name for name, kw in _CONTRACTS.items() if kw not in sc]
    return len(_CONTRACTS), uncovered


def main():
    ap = argparse.ArgumentParser(description="「文档承诺 ↔ 实际执行」对账关")
    ap.add_argument("--report", default="")
    a = ap.parse_args()

    print("=" * 68)
    print("文檔承諾 ↔ 實際執行 · 對賬")
    print("=" * 68)
    findings = []
    R = ["# 文檔承諾 ↔ 實際執行 · 對賬\n"]

    # ① 字段消費
    keys, missing = field_consumption()
    print(f"\n【1】字段消費（composer 解析了 {len(keys)} 個字段）")
    R.append(f"\n## ① 字段消費（{len(keys)} 個字段）\n")
    if missing:
        print(f"  {NG} 解析進內存卻**沒被印進輸出**的字段：{'、'.join(missing)}")
        findings.append(f"字段被解析卻未輸出：{'、'.join(missing)}")
        R.append(f"- ❌ 解析進內存卻沒被印進輸出：{'、'.join(missing)}"
                 f"（這正是「難度」當年踩過的那類坑）\n")
    else:
        print(f"  {OK} 每個被解析的字段都進了輸出")
        R.append(f"- ✅ 每個被解析的字段都進了輸出\n")

    # ② 參考文件消費
    unreads, should_miss, exempt, cases_globbed = reference_consumption()
    print(f"\n【2】參考文件消費（references/ 頂層 {len(glob.glob(os.path.join(REF, '*.md')))} 檔）")
    R.append(f"\n## ② 參考文件消費\n")
    if should_miss:
        for b in should_miss:
            print(f"  {NG} **該消費卻零消費**：{b} —— {_MUST_CONSUME[b]}")
            R.append(f"- ❌ 該消費卻零消費：`{b}` —— {_MUST_CONSUME[b]}\n")
        findings.append(f"該消費卻零消費：{'、'.join(should_miss)}")
    if unreads:
        print(f"  {WARN} 沒有腳本讀到（未列入豁免，需人確認）：{'、'.join(unreads)}")
        R.append(f"- ⚠️ 沒有腳本讀到（未列入豁免）：{'、'.join(unreads)}\n")
    if exempt:
        print(f"  {OK} 僅供人工（豁免，正確）：{len(exempt)} 檔")
        R.append(f"- ✅ 僅供人工（豁免）：{'、'.join(exempt)}\n")
    if not should_miss and not unreads:
        print(f"  {OK} 除豁免外，每個檔都至少被一支腳本讀到")
        R.append(f"- ✅ 除豁免外，每個檔都至少被一支腳本讀到\n")
    print(f"  {OK if cases_globbed else WARN} cases/ 由 glob 載入：{cases_globbed}")
    R.append(f"- cases/ 由 glob 載入：{cases_globbed}（kb_audit 的 L2 另驗其可達性）\n")

    # ③ 判據對賬
    total_must, uncovered = must_consumption()
    print(f"\n【3】判據對賬（{_CONTRACTS.__len__()} 項承諾）")
    R.append(f"\n## ③ 判據對賬\n")
    if uncovered:
        for name in uncovered:
            print(f"  {NG} 承諾有、關卡沒有：{name}")
            R.append(f"- ❌ 承諾有、關卡沒有：{name}\n")
        findings.append(f"{len(uncovered)} 項承諾沒有可判定關：{'、'.join(uncovered[:4])}")
    else:
        print(f"  {OK} {total_must} 項承諾全部有對應關卡")
        R.append(f"- ✅ {total_must} 項承諾全部有對應關卡\n")

    print("\n" + "=" * 68)
    if findings:
        print(f"{WARN} 對賬差異 {len(findings)} 項（見上）。建議：能機械化的補關卡，"
              f"屬「僅供人工」的標明豁免 —— **不要讓它靜默掛著**。")
        for x in findings:
            print(f"   · {x}")
        print("=" * 68)
        sys.exit(1)
    print(f"{OK} 對賬一致：承諾的都有執行。")
    if a.report:
        io.open(a.report, "w", encoding="utf-8").write("".join(R))
        print(f"已寫出：{a.report}")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{WARN} 已中斷。")
        sys.exit(130)
    except Exception as e:
        print(f"\n{NG} promise_check 執行出錯：{type(e).__name__}: {e}")
        print(f"{HINT} 依協議 8：修正後重跑。")
        sys.exit(2)
