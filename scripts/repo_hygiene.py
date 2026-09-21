#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
repo_hygiene.py —— 仓库冗余／卫生扫描（存量维护用）

为什么需要这支脚本
------------------
既有的 6 支校验脚本 + kb_audit.py 查的都是「**内容对不对**」（引用通不通、
卡片齐不齐、模型可不可达）。**没有一支查「这个文件该不该存在」** ——
于是仓库会慢慢长出三类冗余：

  ① 孤儿档（orphan）：全仓零入链引用，没人知道它为什么在
  ② 派生物（derived）：`.docx`／`.pdf` 等可由源档＋脚本再生，却被当成资产入库
  ③ 本机垃圾（junk）：`.DS_Store`／`__pycache__`／`实测-*` 测试残留

三类都不影响「知识库是否连通」，所以既有的断链审计永远看不到它们。
本脚本补的正是这一格。

用法
----
    python scripts/repo_hygiene.py              # 扫描并出报告（只读，不改任何东西）
    python scripts/repo_hygiene.py --clean      # 扫描 + 把「本机垃圾」移到废纸篓
    python scripts/repo_hygiene.py --json       # 机器可读输出
    python scripts/repo_hygiene.py --strict     # 发现任何可清理项就 exit 1

设计约定（沿用本仓库的既有规范）
--------------------------------
- **覆盖类只报数，不判失败**：冗余是覆盖率性质的慢性病，不是断链那样的硬错误。
  除非加 `--strict`，否则一律 exit 0 —— 否则回归永远红灯，久了没人看。
- **只标注、不批量删**：`--clean` 动的只有「本机垃圾」（已在 .gitignore 里，
  不进仓库，删错也只影响本机）。**已入库的文件一律只出建议、不代删** ——
  它们是 git 历史的一部分，删除要由人拍板并写进 commit message。
- 判据一律「**全仓可查引用**」，不是「我记得它被用过」。
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

# 扫描期间的「不致命但要知道」的事（读不到的档／搬档改走备援路径…）。
# **不吞异常**：吞掉＝某一格从未生效却回报全绿，那比没有这支脚本更危险。
WARNINGS = []

# ── 扫描范围 ────────────────────────────────────────────────────────────────
# 这些目录不扫：.git 是版本历史；.workbuddy 是私有笔记；优化轮次是过程记录；
#   `解析产物` 是**本地工作稿**（把书／长文拆成一节节的中间产物，已进 .gitignore 不入库）。
#   ⚠️ 2026-09-19 加 `解析产物`：它一直没入库、零入链，却让本脚本**每轮都报「孤儿档 118.3 KB」**
#      —— 噪声会把真问题埋掉（看久了就没人看这一段了）。
SKIP_DIRS = {".git", ".workbuddy", "优化轮次", "__pycache__", "node_modules", "解析产物"}
TEXT_EXT = {".md", ".py", ".json", ".sh", ".txt", ".html", ".yml", ".yaml", ".csv"}

# ── 入口档：一定是「被引用」的角色，不查入链 ─────────────────────────────────
ENTRY_FILES = {"SKILL.md", "AGENTS.md", "README.md", "AGENT-BRIEF.md", "LICENSE"}

# ── 派生物：可由源档＋脚本再生 ──────────────────────────────────────────────
DERIVED_EXT = {".docx": ".md", ".pdf": ".md", ".xlsx": ".md"}
# 这些派生物有「人要看成品长什么样」的正当用途，不列为冗余（但仍会报陈旧）
DERIVED_KEEP_HINT = ()

# ── 本机垃圾：已被 .gitignore 排除，删了不影响仓库 ────────────────────────────
JUNK_NAMES = {".DS_Store", "Thumbs.db", "Desktop.ini"}
JUNK_DIR_PAT = re.compile(r"^(?:实测-|实测-|output$|\.archive$)")
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
    """全仓文本语料，用于判断「这个文件名有没有被任何地方提到」"""
    texts = {}
    for rel in files:
        if os.path.splitext(rel)[1].lower() in TEXT_EXT:
            texts[rel] = read_text(rel)
    return texts


def find_orphans(files, texts):
    """孤儿档：basename 与 stem 在全仓（扣除自身）都不出现

    刻意**排除本机垃圾**（.DS_Store／实测-*／__pycache__）：它们零引用是理所当然的，
    报在 ③ 就好 —— 同一件事报两次会让报告失真，久了没人看。
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
        # 只看「本体档」——子目录的 README/索引不算孤儿候选（它们是目录入口）
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
    """派生物：同目录存在同名源档 → 可再生；并检查时序（派生物早于源＝陈旧）

    同样排除本机垃圾：`实测-*/` 里的 .docx 本来就不入库，报在 ③ 即可。
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
            continue                      # 找不到源 → 不是「可再生」，是唯一资产，不动
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
    """回传『这是什么垃圾』，不是垃圾则回 None。find_junk 与 find_orphans 共用同一判据 ——
    两处各写一份，早晚会漂移。"""
    parts = rel.split(os.sep)
    if any(JUNK_DIR_PAT.match(p) for p in parts):
        return "本机测试产物目录"
    base = os.path.basename(rel)
    if base in JUNK_NAMES:
        return "系统／编辑器垃圾"
    if os.path.splitext(base)[1].lower() in JUNK_EXT:
        return "编译／备份残留"
    return None


def _is_junk(rel):
    return _junk_why(rel) is not None


def find_junk(files):
    """本机垃圾：.gitignore 已排除者；删了不影响公开仓库"""
    out = []
    for rel in files:
        why = _junk_why(rel)
        if why:
            out.append({"path": rel, "size": os.path.getsize(rel), "why": why})
    return sorted(out, key=lambda d: -d["size"])


def find_dupes(files):
    """内容完全相同（sha256）——同一份知识抄两遍是最贵的冗余"""
    groups = {}
    for rel in files:
        try:
            with open(rel, "rb") as f:
                h = hashlib.sha256(f.read()).hexdigest()
        except OSError as e:
            # **不吞**：读不到的档要说出来。吞掉的话，这个文件就等于「永远不参与查重」，
            # 而报告看起来完全正常 —— 那是「这关从未生效但回报全绿」的经典形态。
            WARNINGS.append(f"查重时读不到 {rel}：{e}")
            continue
        groups.setdefault(h, []).append(rel)
    return [v for v in groups.values() if len(v) > 1]


# ── 清理动作 ────────────────────────────────────────────────────────────────
def _trash_dir():
    return os.path.expanduser("~/.Trash")


def to_trash(rel):
    """移到 macOS 废纸篓。优先 `trash` CLI → osascript → 直接搬进 ~/.Trash。

    刻意不用 `rm`：这三条路径都让文件可在 Finder 废纸篓里还原。
    """
    abspath = os.path.abspath(rel)
    if not os.path.exists(abspath):
        return False, "不存在"

    # ① trash CLI
    if shutil.which("trash"):
        p = subprocess.run(["trash", abspath], capture_output=True, text=True)
        if p.returncode == 0:
            return True, "trash CLI"

    # ② Finder（有逾时，避免权限对话框卡死）
    if sys.platform == "darwin" and shutil.which("osascript"):
        script = f'tell application "Finder" to delete POSIX file "{abspath}"'
        try:
            p = subprocess.run(["osascript", "-e", script],
                               capture_output=True, text=True, timeout=15)
            if p.returncode == 0:
                return True, "Finder"
        except subprocess.TimeoutExpired:
            # 不吞：Finder 那条路走不通（多半是自动化权限对话框没人点），
            # 但要让人知道「这次是走第 ③ 条路搬的」，而不是以为 Finder 成功了。
            WARNINGS.append(f"Finder 搬档逾时，改走 ~/.Trash：{os.path.basename(abspath)}")

    # ③ 直接搬进 ~/.Trash（加时间戳避免撞名）
    td = _trash_dir()
    if os.path.isdir(td):
        name = f"{os.path.basename(abspath)}.{time.strftime('%Y%m%d-%H%M%S')}"
        try:
            shutil.move(abspath, os.path.join(td, name))
            return True, "~/.Trash"
        except OSError as e:
            return False, str(e)
    return False, "找不到废纸篓"


def clean_junk(junk):
    done, failed = [], []
    # 先文件后目录：目录空了再收
    for item in sorted(junk, key=lambda d: -len(d["path"].split(os.sep))):
        ok, how = to_trash(item["path"])
        (done if ok else failed).append((item["path"], how))
    # 收掉空目录
    for dirpath, dirnames, filenames in os.walk(".", topdown=False):
        rel = os.path.relpath(dirpath, ".")
        if rel == "." or is_skipped(rel):
            continue
        if JUNK_DIR_PAT.match(os.path.basename(rel)) and not os.listdir(dirpath):
            ok, how = to_trash(rel)
            (done if ok else failed).append((rel + "/", how))
    return done, failed


# ── 输出 ────────────────────────────────────────────────────────────────────
def human_size(n):
    if n < 1024:
        return f"{n:,.0f} B"
    if n < 1024 ** 2:
        return f"{n / 1024:,.1f} KB"
    return f"{n / 1024 ** 2:,.1f} MB"


def report(res, verbose=True):
    orphans, derived, junk, dupes = res["orphans"], res["derived"], res["junk"], res["dupes"]

    print("=" * 72)
    print("仓库冗余／卫生扫描 · repo_hygiene.py")
    print("（既有校验脚本查『内容对不对』；本脚本查『这个文件该不该存在』）")
    print("=" * 72)
    print(f"  扫描范围：{res['total']} 个文件（已排除 .git／.workbuddy／优化轮次／解析产物／__pycache__）")

    print(f"\n① 孤儿档（全仓零入链引用）：{len(orphans)} 个，"
          f"{human_size(sum(o['size'] for o in orphans))}")
    for o in orphans:
        print(f"     {human_size(o['size']):>10}  {o['path']}")
    if not orphans:
        print("     （无）")

    print(f"\n② 派生物（可由源档＋脚本再生）：{len(derived)} 个，"
          f"{human_size(sum(d['size'] for d in derived))}")
    for d in derived:
        tag = f"⚠️  陈旧：比源档晚于 {d['lag_hours']} h" if d["stale"] else "与源档同步"
        print(f"     {human_size(d['size']):>10}  {d['path']}")
        print(f"                   源：{d['source']}（{tag}）")
    if not derived:
        print("     （无）")

    print(f"\n③ 本机垃圾（.gitignore 已排除，不进仓库）：{len(junk)} 个，"
          f"{human_size(sum(j['size'] for j in junk))}")
    for j in junk:
        print(f"     {human_size(j['size']):>10}  {j['path']}   ← {j['why']}")
    if not junk:
        print("     （无）")

    print(f"\n④ 内容完全重复：{len(dupes)} 组")
    for g in dupes:
        print("     " + " ＝ ".join(g))
    if not dupes:
        print("     （无）")

    total_waste = sum(o["size"] for o in orphans) + sum(d["size"] for d in derived) \
        + sum(j["size"] for j in junk)
    print("\n" + "-" * 72)
    print(f"  可清理总量：{human_size(total_waste)}"
          f"（孤儿 {human_size(sum(o['size'] for o in orphans))} ＋ "
          f"派生 {human_size(sum(d['size'] for d in derived))} ＋ "
          f"垃圾 {human_size(sum(j['size'] for j in junk))}）")
    print("  ⚠️  ①② 已入库，本脚本**只出建议不代删** —— 删除要人拍板并写进 commit message。")
    print("     ③ 为本机文件，`--clean` 可直接移入废纸篓（不影响仓库）。")
    if WARNINGS:
        print(f"\n  ⚠️  扫描期间 {len(WARNINGS)} 条提示（不影响上面的结论，但要知道）：")
        for w in WARNINGS:
            print(f"     · {w}")


def main():
    ap = argparse.ArgumentParser(description="仓库冗余／卫生扫描")
    ap.add_argument("--clean", action="store_true", help="把『本机垃圾』移入废纸篓")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--strict", action="store_true", help="发现任何可清理项即 exit 1")
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
            print(f"✅ 已移入废纸篓（可用 Finder『放回原处』还原）：{len(done)} 项\n")
            for p, how in done:
                print(f"   → {p}   （经 {how}）")
            if failed:
                print(f"\n❌ 失败 {len(failed)} 项：")
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
    # 协议 8：脚本挂了要**降级、别卡死**。裸 traceback 会让执行 AI 停在原地，
    # 而这支脚本的所有结论都只是「建议」性质 —— 没必要为它中断整条流程。
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️  已中断（未完成）—— 扫描是只读的，仓库未受影响。", file=sys.stderr)
        sys.exit(130)
    except Exception as e:                                    # noqa: BLE001
        print(f"❌ repo_hygiene 出错：{type(e).__name__}: {e}", file=sys.stderr)
        print("   这是只读扫描，失败不影响仓库。可先手动检查："
              "\n   · 文件权限／磁盘（扫描要读全仓）"
              "\n   · 是否在仓库根目录执行（本脚本会自行切到仓库根）"
              "\n   · 若只是清理卡住，改用系统 Finder 手动删 .DS_Store / 实测-* 即可。",
              file=sys.stderr)
        sys.exit(2)
