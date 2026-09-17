#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
repo_hygiene.py —— 倉庫冗餘／衛生掃描（存量維護用）

為什麼需要這支腳本
------------------
既有的 6 支校驗腳本 + kb_audit.py 查的都是「**內容對不對**」（引用通不通、
卡片齊不齊、模型可不可達）。**沒有一支查「這個檔案該不該存在」** ——
於是倉庫會慢慢長出三類冗余：

  ① 孤兒檔（orphan）：全倉零入鏈引用，沒人知道它為什麼在
  ② 派生物（derived）：`.docx`／`.pdf` 等可由源檔＋腳本再生，卻被當成資產入庫
  ③ 本機垃圾（junk）：`.DS_Store`／`__pycache__`／`實測-*` 測試殘留

三類都不影響「知識庫是否連通」，所以既有的斷鏈審計永遠看不到它們。
本腳本補的正是這一格。

用法
----
    python scripts/repo_hygiene.py              # 掃描並出報告（只讀，不改任何東西）
    python scripts/repo_hygiene.py --clean      # 掃描 + 把「本機垃圾」移到廢紙簍
    python scripts/repo_hygiene.py --json       # 機器可讀輸出
    python scripts/repo_hygiene.py --strict     # 發現任何可清理項就 exit 1

設計約定（沿用本倉庫的既有規範）
--------------------------------
- **覆蓋類只報數，不判失敗**：冗余是覆蓋率性質的慢性病，不是斷鏈那樣的硬錯誤。
  除非加 `--strict`，否則一律 exit 0 —— 否則回歸永遠紅燈，久了沒人看。
- **只標注、不批量刪**：`--clean` 動的只有「本機垃圾」（已在 .gitignore 裡，
  不進倉庫，刪錯也只影響本機）。**已入庫的檔案一律只出建議、不代刪** ——
  它們是 git 歷史的一部分，刪除要由人拍板並寫進 commit message。
- 判據一律「**全倉可查引用**」，不是「我記得它被用過」。
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

# 掃描期間的「不致命但要知道」的事（讀不到的檔／搬檔改走備援路徑…）。
# **不吞異常**：吞掉＝某一格從未生效卻回報全綠，那比沒有這支腳本更危險。
WARNINGS = []

# ── 掃描範圍 ────────────────────────────────────────────────────────────────
# 這些目錄不掃：.git 是版本歷史；.workbuddy 是私有筆記；優化輪次是過程記錄
SKIP_DIRS = {".git", ".workbuddy", "优化记录", "__pycache__", "node_modules"}
TEXT_EXT = {".md", ".py", ".json", ".sh", ".txt", ".html", ".yml", ".yaml", ".csv"}

# ── 入口檔：一定是「被引用」的角色，不查入鏈 ─────────────────────────────────
ENTRY_FILES = {"SKILL.md", "AGENTS.md", "README.md", "", "LICENSE"}

# ── 派生物：可由源檔＋腳本再生 ──────────────────────────────────────────────
DERIVED_EXT = {".docx": ".md", ".pdf": ".md", ".xlsx": ".md"}
# 這些派生物有「人要看成品長什麼樣」的正當用途，不列為冗余（但仍會報陳舊）
DERIVED_KEEP_HINT = ()

# ── 本機垃圾：已被 .gitignore 排除，刪了不影響倉庫 ────────────────────────────
JUNK_NAMES = {".DS_Store", "Thumbs.db", "Desktop.ini"}
JUNK_DIR_PAT = re.compile(r"^(?:實測-|实测-|output$|\.archive$)")
JUNK_EXT = {".pyc", ".pyo", ".swp", ".bak"}


def is_skipped(rel):
    parts = rel.split(os.sep)
    return any(p in SKIP_DIRS for p in parts)


def walk_files():
    out = []
    for dirpath, dirnames, filenames in os.walk("."):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            rel = os.path.relpath(os.path.join(dirpath, fn), ".")
            if is_skipped(rel):
                continue
            out.append(rel)
    return sorted(out)


def read_text(rel):
    try:
        with open(rel, encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return ""


def build_corpus(files):
    """全倉文本語料，用於判斷「這個檔名有沒有被任何地方提到」"""
    texts = {}
    for rel in files:
        if os.path.splitext(rel)[1].lower() in TEXT_EXT:
            texts[rel] = read_text(rel)
    return texts


def find_orphans(files, texts):
    """孤兒檔：basename 與 stem 在全倉（扣除自身）都不出現

    刻意**排除本機垃圾**（.DS_Store／實測-*／__pycache__）：它們零引用是理所當然的，
    報在 ③ 就好 —— 同一件事報兩次會讓報告失真，久了沒人看。
    """
    orphans = []
    for rel in files:
        if is_skipped(rel):
            continue
        if _is_junk(rel):
            continue
        base = os.path.basename(rel)
        stem = os.path.splitext(base)[0]
        if base in ENTRY_FILES:
            continue
        # 只看「本體檔」——子目錄的 README/索引不算孤兒候選（它們是目錄入口）
        if base.lower() == "readme.md":
            continue
        hits = 0
        for other, txt in texts.items():
            if other == rel:
                continue
            hits += txt.count(base) + txt.count(stem)
        if hits <= 0:
            orphans.append({"path": rel, "size": os.path.getsize(rel)})
    return sorted(orphans, key=lambda d: -d["size"])


def find_derived(files):
    """派生物：同目錄存在同名源檔 → 可再生；並檢查時序（派生物早於源＝陳舊）

    同樣排除本機垃圾：`實測-*/` 裡的 .docx 本來就不入庫，報在 ③ 即可。
    """
    out = []
    for rel in files:
        ext = os.path.splitext(rel)[1].lower()
        if ext not in DERIVED_EXT:
            continue
        if _is_junk(rel):
            continue
        src = os.path.splitext(rel)[0] + DERIVED_EXT[ext]
        if not os.path.exists(src):
            continue                      # 找不到源 → 不是「可再生」，是唯一資產，不動
        d_mtime = os.path.getmtime(rel)
        s_mtime = os.path.getmtime(src)
        out.append({
            "path": rel,
            "source": src,
            "size": os.path.getsize(rel),
            "stale": d_mtime < s_mtime,
            "lag_hours": round((s_mtime - d_mtime) / 3600.0, 1) if d_mtime < s_mtime else 0.0,
        })
    return sorted(out, key=lambda d: -d["size"])


def _junk_why(rel):
    """回傳『這是什麼垃圾』，不是垃圾則回 None。find_junk 與 find_orphans 共用同一判據 ——
    兩處各寫一份，早晚會漂移。"""
    parts = rel.split(os.sep)
    if any(JUNK_DIR_PAT.match(p) for p in parts):
        return "本機測試產物目錄"
    base = os.path.basename(rel)
    if base in JUNK_NAMES:
        return "系統／編輯器垃圾"
    if os.path.splitext(base)[1].lower() in JUNK_EXT:
        return "編譯／備份殘留"
    return None


def _is_junk(rel):
    return _junk_why(rel) is not None


def find_junk(files):
    """本機垃圾：.gitignore 已排除者；刪了不影響公開倉庫"""
    out = []
    for rel in files:
        why = _junk_why(rel)
        if why:
            out.append({"path": rel, "size": os.path.getsize(rel), "why": why})
    return sorted(out, key=lambda d: -d["size"])


def find_dupes(files):
    """內容完全相同（sha256）——同一份知識抄兩遍是最貴的冗余"""
    groups = {}
    for rel in files:
        try:
            with open(rel, "rb") as f:
                h = hashlib.sha256(f.read()).hexdigest()
        except OSError as e:
            # **不吞**：讀不到的檔要說出來。吞掉的話，這個檔就等於「永遠不參與查重」，
            # 而報告看起來完全正常 —— 那是「這關從未生效但回報全綠」的經典形態。
            WARNINGS.append(f"查重時讀不到 {rel}：{e}")
            continue
        groups.setdefault(h, []).append(rel)
    return [v for v in groups.values() if len(v) > 1]


# ── 清理動作 ────────────────────────────────────────────────────────────────
def _trash_dir():
    return os.path.expanduser("~/.Trash")


def to_trash(rel):
    """移到 macOS 廢紙簍。優先 `trash` CLI → osascript → 直接搬進 ~/.Trash。

    刻意不用 `rm`：這三條路徑都讓檔案可在 Finder 廢紙簍裡還原。
    """
    abspath = os.path.abspath(rel)
    if not os.path.exists(abspath):
        return False, "不存在"

    # ① trash CLI
    if shutil.which("trash"):
        p = subprocess.run(["trash", abspath], capture_output=True, text=True)
        if p.returncode == 0:
            return True, "trash CLI"

    # ② Finder（有逾時，避免權限對話框卡死）
    if sys.platform == "darwin" and shutil.which("osascript"):
        script = f'tell application "Finder" to delete POSIX file "{abspath}"'
        try:
            p = subprocess.run(["osascript", "-e", script],
                               capture_output=True, text=True, timeout=15)
            if p.returncode == 0:
                return True, "Finder"
        except subprocess.TimeoutExpired:
            # 不吞：Finder 那條路走不通（多半是自動化權限對話框沒人點），
            # 但要讓人知道「這次是走第 ③ 條路搬的」，而不是以為 Finder 成功了。
            WARNINGS.append(f"Finder 搬檔逾時，改走 ~/.Trash：{os.path.basename(abspath)}")

    # ③ 直接搬進 ~/.Trash（加時間戳避免撞名）
    td = _trash_dir()
    if os.path.isdir(td):
        name = f"{os.path.basename(abspath)}.{time.strftime('%Y%m%d-%H%M%S')}"
        try:
            shutil.move(abspath, os.path.join(td, name))
            return True, "~/.Trash"
        except OSError as e:
            return False, str(e)
    return False, "找不到廢紙簍"


def clean_junk(junk):
    done, failed = [], []
    # 先檔案後目錄：目錄空了再收
    for item in sorted(junk, key=lambda d: -len(d["path"].split(os.sep))):
        ok, how = to_trash(item["path"])
        (done if ok else failed).append((item["path"], how))
    # 收掉空目錄
    for dirpath, dirnames, filenames in os.walk(".", topdown=False):
        rel = os.path.relpath(dirpath, ".")
        if rel == "." or is_skipped(rel):
            continue
        if JUNK_DIR_PAT.match(os.path.basename(rel)) and not os.listdir(dirpath):
            ok, how = to_trash(rel)
            (done if ok else failed).append((rel + "/", how))
    return done, failed


# ── 輸出 ────────────────────────────────────────────────────────────────────
def human_size(n):
    if n < 1024:
        return f"{n:,.0f} B"
    if n < 1024 ** 2:
        return f"{n / 1024:,.1f} KB"
    return f"{n / 1024 ** 2:,.1f} MB"


def report(res, verbose=True):
    orphans, derived, junk, dupes = res["orphans"], res["derived"], res["junk"], res["dupes"]

    print("=" * 72)
    print("倉庫冗余／衛生掃描 · repo_hygiene.py")
    print("（既有校驗腳本查『內容對不對』；本腳本查『這個檔案該不該存在』）")
    print("=" * 72)
    print(f"  掃描範圍：{res['total']} 個檔（已排除 .git／.workbuddy／優化輪次／__pycache__）")

    print(f"\n① 孤兒檔（全倉零入鏈引用）：{len(orphans)} 個，"
          f"{human_size(sum(o['size'] for o in orphans))}")
    for o in orphans:
        print(f"     {human_size(o['size']):>10}  {o['path']}")
    if not orphans:
        print("     （無）")

    print(f"\n② 派生物（可由源檔＋腳本再生）：{len(derived)} 個，"
          f"{human_size(sum(d['size'] for d in derived))}")
    for d in derived:
        tag = f"⚠️  陳舊：比源檔晚於 {d['lag_hours']} h" if d["stale"] else "與源檔同步"
        print(f"     {human_size(d['size']):>10}  {d['path']}")
        print(f"                   源：{d['source']}（{tag}）")
    if not derived:
        print("     （無）")

    print(f"\n③ 本機垃圾（.gitignore 已排除，不進倉庫）：{len(junk)} 個，"
          f"{human_size(sum(j['size'] for j in junk))}")
    for j in junk:
        print(f"     {human_size(j['size']):>10}  {j['path']}   ← {j['why']}")
    if not junk:
        print("     （無）")

    print(f"\n④ 內容完全重複：{len(dupes)} 組")
    for g in dupes:
        print("     " + " ＝ ".join(g))
    if not dupes:
        print("     （無）")

    total_waste = sum(o["size"] for o in orphans) + sum(d["size"] for d in derived) \
        + sum(j["size"] for j in junk)
    print("\n" + "-" * 72)
    print(f"  可清理總量：{human_size(total_waste)}"
          f"（孤兒 {human_size(sum(o['size'] for o in orphans))} ＋ "
          f"派生 {human_size(sum(d['size'] for d in derived))} ＋ "
          f"垃圾 {human_size(sum(j['size'] for j in junk))}）")
    print("  ⚠️  ①② 已入庫，本腳本**只出建議不代刪** —— 刪除要人拍板並寫進 commit message。")
    print("     ③ 為本機檔案，`--clean` 可直接移入廢紙簍（不影響倉庫）。")
    if WARNINGS:
        print(f"\n  ⚠️  掃描期間 {len(WARNINGS)} 條提示（不影響上面的結論，但要知道）：")
        for w in WARNINGS:
            print(f"     · {w}")


def main():
    ap = argparse.ArgumentParser(description="倉庫冗余／衛生掃描")
    ap.add_argument("--clean", action="store_true", help="把『本機垃圾』移入廢紙簍")
    ap.add_argument("--json", action="store_true", help="機器可讀輸出")
    ap.add_argument("--strict", action="store_true", help="發現任何可清理項即 exit 1")
    args = ap.parse_args()

    files = walk_files()
    texts = build_corpus(files)
    res = {
        "total": len(files),
        "orphans": find_orphans(files, texts),
        "derived": find_derived(files),
        "junk": find_junk(files),
        "dupes": find_dupes(files),
    }

    if args.clean:
        done, failed = clean_junk(res["junk"])
        if args.json:
            res["cleaned"] = [{"path": p, "via": h} for p, h in done]
            res["clean_failed"] = [{"path": p, "why": h} for p, h in failed]
        else:
            print(f"✅ 已移入廢紙簍（可用 Finder『放回原處』還原）：{len(done)} 項\n")
            for p, how in done:
                print(f"   → {p}   （經 {how}）")
            if failed:
                print(f"\n❌ 失敗 {len(failed)} 項：")
                for p, why in failed:
                    print(f"   ✗ {p}   {why}")

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        report(res)

    if args.strict and (res["orphans"] or res["derived"] or res["junk"] or res["dupes"]):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    # 協議 8：腳本掛了要**降級、別卡死**。裸 traceback 會讓執行 AI 停在原地，
    # 而這支腳本的所有結論都只是「建議」性質 —— 沒必要為它中斷整條流程。
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️  已中斷（未完成）—— 掃描是只讀的，倉庫未受影響。", file=sys.stderr)
        sys.exit(130)
    except Exception as e:                                    # noqa: BLE001
        print(f"❌ repo_hygiene 出錯：{type(e).__name__}: {e}", file=sys.stderr)
        print("   這是只讀掃描，失敗不影響倉庫。可先手動檢查："
              "\n   · 檔案權限／磁碟（掃描要讀全倉）"
              "\n   · 是否在倉庫根目錄執行（本腳本會自行切到倉庫根）"
              "\n   · 若只是清理卡住，改用系統 Finder 手動刪 .DS_Store / 实测-* 即可。",
              file=sys.stderr)
        sys.exit(2)
