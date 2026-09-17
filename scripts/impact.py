#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""impact.py — 改一处，自动算出「影响面」（**替代靠人记住跑哪几条**）

為什麼要有它（用戶 2026-09-18 質問）：
    「**那不應該是修了一個就自己把所有東西都預測好，預計好會影響什麼東西嗎？
      為什麼要多次質檢？**」

    這個直覺是對的，而且它就是編譯器／型別系統在做的事：
    **改一個函式簽名 → 編譯器把所有呼叫點列給你**。它之所以能做到，是因為
    **依賴邊是明確寫在資料裡的**（誰 import 誰、型別是什麼）。

    而這個倉庫原先的依賴邊是**散在文字裡的**：
      · 「改骨架要同步 paradigm_data」→ 寫在 SKILL 的一句話裡
      · 「改卡片要跑 case_sections」→ 寫在維護紀律表裡
      · 「SKILL 裡寫的腳本數要跟著改」→ 沒人寫，全靠 optimize_scan 事後抓
    → 於是「影響面」只能靠**人記得**，而人一定會漏。漏了就只能靠**再跑一輪質檢**兜。

    本工具就是把那些邊**從文字搬進資料**，並提供兩條命令：
      `--git`     改完直接跑：讀 `git status`，算出「你現在必須重跑什麼」
      `--changed` 指定改了哪個檔／哪一類，輸出影響面
      `--verify`  不只列清單，**直接把該跑的跑一遍**（可驗證，不靠自覺）

用法：
    python scripts/impact.py                 # 自動看 git 改了什麼
    python scripts/impact.py --changed scripts/composer.py
    python scripts/impact.py --list          # 列出所有受管對象
    python scripts/impact.py --verify        # 列出後直接執行
"""
import argparse
import fnmatch
import io
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from _common import OK, NG, WARN, HINT   # noqa: E402

PY = sys.executable

# ═══ 變更 → 影響面 映射（**這就是把「散在文字裡的依賴邊」搬進資料**）═══
#   must_run  ：必須重跑的校驗（不跑＝不知道有沒有壞）
#   must_sync ：必須同步改的地方（不改＝下次校驗會紅燈）
#   why       ：為什麼，一句話（給後來人看，避免被當成迷信）
RULES = [
    {
        "match": ["scripts/composer.py"],
        "what": "骨架組裝器（章節／打法／注入邏輯）",
        "must_run": [["build_paradigm.py", "--doc-map", "README.md"],
                     [""],
                     ["smoke_test.py"]],
        "must_sync": ["scripts/paradigm_data.py 的 SKELETON_HEADS 與 GUIDE"
                      "（新增/刪除章節必須同步，否則 build_paradigm 直接退出 1）",
                      "章節編號必須**與實際出現順序同向**（插了新節要重編號）"],
        "why": "骨架是唯一真相：範式庫、README 結構表、 都由它派生",
        "heavy": True,
    },
    {
        "match": ["scripts/paradigm_data.py"],
        "what": "逐節填寫指引（資料層）",
        "must_run": [["build_paradigm.py", "--doc-map", "README.md"],
                     [""]],
        "must_sync": ["若新增章節 → 同步 composer 的骨架（兩者必須一致）"],
        "why": "它與 composer 是**兩份宣告同一件事**的資料，必須對賬",
    },
    {
        "match": ["scripts/selfcheck.py"],
        "what": "交付前自檢（18 關）",
        "must_run": [["smoke_test.py"], ["kb_audit.py"]],
        "must_sync": ["新增/刪除關卡 → 同步 （關數）與 README §0.3（關清單）",
                      "新加的硬關**先問「這條要求對最輕的那檔也成立嗎」**——"
                      "已連續五次誤傷速覽類標杆稿，完整版才強制的走 _hard_if_full()"],
        "why": "自檢是唯一攔截層，改它等於改交付門檻",
        "heavy": True,
    },
    {
        "match": ["scripts/_common.py"],
        "what": "跨腳本共用常量",
        "must_run": [["kb_audit.py"]],
        "must_sync": [],
        "why": "所有腳本都 import 它 —— 改壞＝全部崩",
        "heavy": True,
    },
    {
        "match": ["references/00-打法库.md"],
        "what": "116 條打法（打法／案例行／五要素）",
        "must_run": [["kb_audit.py"], ["case_play_index.py", "--fix"], ["smoke_test.py"]],
        "must_sync": ["案例行只接受「品牌關鍵詞@檔號」，由腳本解析生成，**不手寫檔名**"],
        "why": "打法↔案例是 L2 鏈路；composer 直接解析這份檔",
    },
    {
        "match": ["references/cases/*.md", "references/cases/"],
        "what": "52 份行業案例卡",
        "must_run": [["case_sections.py", "--fix"], ["case_order.py"],
                     ["case_lint.py"], ["case_upgrade.py"],
                     ["case_play_index.py", "--fix"], ["kb_audit.py"]],
        "must_sync": ["卡片格式見 cases/README.md §四（**14 塊**）",
                      "歸因提醒（第 9 塊）會被 composer 帶進交付稿，不是可選項"],
        "why": "案例卡是**給模型看的教材**：教材教錯，下游寫出來一定錯",
    },
    {
        "match": ["references/12-范式库.md"],
        "what": "六檔範式庫",
        "must_run": [],
        "must_sync": ["⛔ **不要手改這個檔** —— 它由 build_paradigm 生成；"
                      "要改就改 paradigm_data.py，再重跑 build_paradigm"],
        "why": "它是產物不是源頭；手改會在下次生成時被覆蓋，且造成兩份真相",
    },
    {
        "match": ["README.md"],
        "what": "給人看的說明 + 倉庫地圖",
        "must_run": [["build_paradigm.py", "--doc-map", "README.md"]],
        "must_sync": ["DOCMAP 標記區塊內的內容**不要手改**（會被重生成覆蓋）；"
                      "要改結構就改 paradigm_data"],
        "why": "結構表是生成物，手寫必然過時",
    },
    {
        "match": [""],
        "what": "給 agent 的單檔快照",
        "must_run": [[""]],
        "must_sync": ["⛔ 不要手改 —— 它是生成物"],
        "why": "同上；掛在 verify_all 裡自動重生成",
    },
    {
        "match": ["SKILL.md"],
        "what": "唯一入口（門禁／八篇／路由表／自檢清單）",
        "must_run": [["optimize_scan.py"], ["kb_audit.py"]],
        "must_sync": ["腳本數／CLI 數寫在裡面 —— 加腳本後要同步（optimize_scan 會抓）",
                      "⚠️ 檔頭是 YAML frontmatter，**改開頭前先看 `head -3`**，別盲插"],
        "why": "它是入口，數字錯了會誤導所有讀者",
    },
    {
        "match": ["scripts/*.py"],
        "what": "新增／刪除腳本",
        "must_run": [["optimize_scan.py"], [""]],
        "must_sync": ["SKILL 腳本表補索引 + 更新腳本數/CLI 數",
                      "OK/NG/WARN 常量一律 `from _common import`，**不要在各自檔裡重定義**",
                      "有 CLI 入口就必須有退出碼語義（純報告類加 `# exit-code: n/a`）"],
        "why": "腳本數與常量重複都是 optimize_scan 的檢查項",
    },
    {
        "match": ["scripts/verify_all.py"],
        "what": "全鏈路驗證器（A–F 關）",
        "must_run": [["smoke_test.py"]],
        "must_sync": ["FIXERS 裡每一支都必須**冪等**（第 2 輪起哈希零漂移）"],
        "why": "改驗證器本身＝改變門檻，且它自己也在被測",
    },
    {
        "match": ["references/*.md"],
        "what": "知識庫編號文檔（00–13）",
        "must_run": [["kb_audit.py"], ["file_meta.py"]],
        "must_sync": ["09–13 用**簡體**維護（內容原樣進交付物）；其餘用繁體",
                      "改檔名/編號要跑 rename_tidy.py（舊檔名不得殘留）"],
        "why": "L1 檔案引用可解析 ＋ L7 私有痕跡都靠這條鏈",
    },
]

# 這些檔「改了必須跑全量」—— 因為它們是別人的依賴，影響面無法枚舉
FULL_REGRESSION = ["verify_all.py"]


def read(p):
    return io.open(p, encoding="utf-8").read()


def git_changed():
    try:
        out = subprocess.run(["git", "status", "--short", "--untracked-files=all"],
                             cwd=ROOT, capture_output=True, text=True).stdout
    except Exception:
        return []
    fs = []
    for ln in out.split("\n"):
        m = re.match(r"^\s*\S+\s+(.+)$", ln)
        if m:
            p = m.group(1).strip().strip('"')
            if p and not p.startswith(".workbuddy"):
                fs.append(p)
    return fs


def hit(rule, path):
    for pat in rule["match"]:
        if fnmatch.fnmatch(path, pat) or path.startswith(pat.rstrip("*")) or path == pat:
            return True
    return False


def main():
    ap = argparse.ArgumentParser(description="改一處 → 自動算出影響面")
    ap.add_argument("--changed", default="", help="你改了哪個檔（可多次指定，逗號分隔）")
    ap.add_argument("--list", action="store_true", help="列出所有受管對象")
    ap.add_argument("--verify", action="store_true", help="列出影響面後直接跑一遍")
    a = ap.parse_args()

    if a.list:
        print("=" * 70)
        print("受管對象（改了它 → 影響面可枚舉）")
        print("=" * 70)
        for r in RULES:
            print(f"\n· {r['what']}")
            print(f"    檔案：{' / '.join(r['match'])}")
            print(f"    為什麼：{r['why']}")
        print(f"\n{HINT} 不在表裡的檔（如新增的臨時檔）→ 保守起見直接跑 "
              f"`python {' '.join(FULL_REGRESSION)} -n 50`。")
        sys.exit(0)

    if a.changed:
        files = [x.strip() for x in a.changed.split(",") if x.strip()]
    else:
        files = git_changed()
        if not files:
            print(f"{OK} git 工作區是乾淨的 —— 沒有變更，也就沒有影響面要算。")
            sys.exit(0)
        print("=" * 70)
        print(f"從 git 看到 {len(files)} 個變更，正在算影響面…")
        print("=" * 70)

    matched, runs, syncs, heavy = [], [], [], False
    for f in files:
        for r in RULES:
            if hit(r, f):
                if r["what"] not in [x["what"] for x in matched]:
                    matched.append(r)
                for cmd in r["must_run"]:
                    if cmd not in runs:
                        runs.append(cmd)
                for s in r["must_sync"]:
                    if s not in syncs:
                        syncs.append(s)
                if r.get("heavy"):
                    heavy = True
                break

    print(f"\n【你改了什麼】")
    for f in files[:20]:
        print(f"  · {f}")
    if len(files) > 20:
        print(f"  …共 {len(files)} 個")

    print(f"\n【影響面 · 必須重跑】")
    if runs:
        for cmd in runs:
            print(f"  {HINT} python scripts/{' '.join(cmd)}")
    else:
        print(f"  （表裡沒有專屬項 → 保守起見跑全量）")
    print(f"  {HINT} python scripts/verify_all.py -n 50   ← **最後一關，永遠要跑**"
          + ("（本次有重檔變更，務必）" if heavy else ""))

    if syncs:
        print(f"\n【影響面 · 必須同步改（不改＝下次校驗紅燈）】")
        for s in syncs:
            print(f"  ⚠️ {s}")

    if not matched:
        print(f"\n{WARN} 沒有命中映射表 —— 說明這是個**還沒建模的依賴邊**。"
              f"\n{HINT} 處理完後，請把它加進 `scripts/impact.py` 的 RULES —— "
              f"**每補一條邊，下次就少一次盲目重跑。**")

    if a.verify:
        print("\n" + "=" * 70)
        print("直接執行（--verify）")
        print("=" * 70)
        bad = 0
        for cmd in runs:
            print(f"\n→ python scripts/{' '.join(cmd)}")
            rc = subprocess.call([PY, os.path.join(HERE, cmd[0])] + list(cmd[1:]), cwd=ROOT)
            if rc != 0:
                bad += 1
                print(f"   {NG} rc={rc}")
        print("\n" + "-" * 70)
        print(f"{OK if not bad else NG} 輕量校驗：{len(runs)-bad}/{len(runs)} 通過")
        print(f"{HINT} 記得最後跑 **verify_all -n 50**（含 50 遍冪等 + 端到端出稿）。")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        print(f"{NG} impact 執行出錯：{type(e).__name__}: {e}")
        sys.exit(2)
