#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""structure_fix.py — 交付稿「结构体检 ＋ 重编号」

为什么要有它（2026-09-17，瞳话案原地踩出来的）：
    那份 4 万字项目书把「团队十章」映射进「官方四部分」之后，编号变成
        一 → 三 → 三 → 二 → 四 → 五 → 八 →（无号）→ 六 → 七 → 九 → 十（消失）
    还带 4 处「见第三部分 1.1」这类**指向不存在章节**的交叉引用。
    这些全是**机械问题**，但我当时是临时写了个一次性脚本改的 —— 下次还得重写。
    → 固化成工具：体检（只报）+ 重编号（--renumber）+ 引用重写（--refmap）。

三条铁律（对应 references/11-防返工交付协议.md）：
    · 铁律 1：**不改任何标题文字**，只动编号。
    · 铁律 4：改结构必改引用与编号 —— 本脚本的核心职责。
    · 不可解则**不猜**：悬空引用无法自动唯一确定目标时，报出来要人给 `--refmap`。

用法：
    python scripts/structure_fix.py plan.md                    # 只体检（不写文件）
    python scripts/structure_fix.py plan.md -o fixed.md --renumber
    python scripts/structure_fix.py plan.md -o fixed.md --renumber --refmap refs.json
    python scripts/structure_fix.py plan.md --report 体检报告.md

refs.json 形如：{"第三部分 1.1": "第三部分 4.1", "第三部分 2.4": "第三部分 5.4"}

退出码：0 无硬问题（或有 --renumber 且引用全可解）；1 有悬空引用未解决；2 执行错误
"""
import argparse
import json
import os
import re
import sys

CN = "一二三四五六七八九十"
CN2I = {c: i for i, c in enumerate(CN, 1)}


def cn(n):
    """1–99 → 中文数字（交付稿里只用得到一~十四）"""
    if n <= 10:
        return CN[n - 1]
    if n < 20:
        return "十" + (CN[n - 11] if n > 10 else "")
    return CN[n // 10 - 1] + "十" + (CN[n % 10 - 1] if n % 10 else "")


RE_PART = re.compile(r"^(#)\s*第([一二三四五六七八九十]+)部分")
RE_H2 = re.compile(r"^(##)\s+(.+?)\s*$")
RE_CHAP = re.compile(r"^(###)\s*([一二三四五六七八九十]+)、(.+?)\s*$")
RE_SUB = re.compile(r"^(#{3,4})\s*([0-9]+)\.([0-9]+)(\s.*)$")


class Doc:
    def __init__(self, text):
        self.lines = text.split("\n")
        self.parts = []          # [(part, chap_cn, title, (i,j))]
        self.subs = []           # [(line_idx, part, chap_cn or None, sec, i, j)]
        self.scan()

    def scan(self):
        part, chap, sec = None, None, ""
        for li, ln in enumerate(self.lines):
            m = RE_PART.match(ln)
            if m:
                part, chap, sec = m.group(2), None, ""
                continue
            m = RE_H2.match(ln)
            if m and not ln.startswith("###"):
                chap, sec = None, m.group(2)
                continue
            m = RE_CHAP.match(ln)
            if m:
                chap = m.group(2)
                self.parts.append((part, chap, m.group(3), li))
                continue
            m = RE_SUB.match(ln)
            if m:
                self.subs.append((li, part, chap, sec, int(m.group(2)), int(m.group(3))))

    # ── 体检 ────────────────────────────────────────────────
    def audit(self):
        hard, warn = [], []
        # ① 章号重复
        seen = {}
        for part, c, t, _ in self.parts:
            k = (part, c)
            if k in seen:
                hard.append(f"章号重复：第{part}部分「{c}、{t}」与「{c}、{seen[k]}」")
            seen[k] = t
        # ② 章号递增
        lastp, lastv = None, 0
        for part, c, t, _ in self.parts:
            if part != lastp:
                lastp, lastv = part, 0
            v = CN2I.get(c, 0)
            if v and v < lastv:
                warn.append(f"章号倒序：第{part}部分「{c}、{t}」排在更大的编号之后")
            lastv = max(lastv, v)
        # ③ 子编号重复（同部分）
        bucket = {}
        for li, part, chap, sec, i, j in self.subs:
            bucket.setdefault((part, f"{i}.{j}"), []).append(li)
        for (part, num), ls in bucket.items():
            if len(ls) > 1:
                hard.append(f"子编号重复：第{part}部分 {num} 出现 {len(ls)} 次（行 {ls}）")
        # ④ 章内子编号递增
        grp = {}
        for li, part, chap, sec, i, j in self.subs:
            grp.setdefault((part, chap or f"§{sec}"), []).append((i, j, li))
        for k, ls in grp.items():
            ls.sort(key=lambda x: x[2])
            seq = [x[1] for x in ls]
            if seq != sorted(seq):
                at = next(n for n in range(1, len(seq)) if seq[n] < seq[n - 1])
                warn.append(f"章内子编号非递增：第{k[0]}部分「{k[1]}」"
                            f"{ls[at-1][0]}.{ls[at-1][1]} → {ls[at][0]}.{ls[at][1]}")
        # ⑤ 带部分号的引用
        idx = {(p, f"{i}.{j}") for _, p, _, _, i, j in self.subs}
        refs, dangling = [], []
        for li, ln in enumerate(self.lines):
            for m in re.finditer(r"第([一二三四五六七八九十]+)部分\s*([0-9]+\.[0-9]+)", ln):
                refs.append((li, m.group(0), m.group(1), m.group(2)))
                if (m.group(1), m.group(2)) not in idx:
                    dangling.append((li, m.group(0),
                                     f"第{m.group(1)}部分 {m.group(2)}"))
        for li, s, why in dangling:
            hard.append(f"悬空引用（行 {li + 1}）：「{s}」→ {why} 不存在")
        # ⑥ 不带部分号的「裸引用」（如「（4.3 节）」）—— 目标落在哪个部分靠上下文推断，
        #    脚本**不猜**：只列出来，要求人用 --refmap 指认。
        #    实测教训：瞳话案第四部分的「诊断结论是信任问题（4.3 节）」其实指的是**第二部分**，
        #    若按「就近原则」自动改，必然改错。
        bare = []
        for li, ln in enumerate(self.lines):
            for m in re.finditer(r"(?<!部分)(?<!第)([0-9]+\.[0-9]+)\s*节", ln):
                bare.append((li, m.group(1)))
        return hard, warn, refs, bare

    # ── 重编号 ──────────────────────────────────────────────
    def renumber(self):
        """按**正文出现顺序**重编章号为 一、二、三…；子编号同步重排。

        基数（base）的判定规则 —— 这是实测踩出来的，不是拍脑袋：
          · 进入「## N. xxx」节 → base = N（官方四部分的自有编号：第四部分的 1.1–7.3 就靠它）
          · 出现「### 中文数字、xxx」章 → base = 该章的新章号（团队十章的 1.1–9.3 靠它）
          · 两者都没有 → base 沿用本部分已用到的最大章号
          子序号在 **(部分, ##节, base)** 内累加；base 一变就重新从 1 开始。
        ⚠️ 两个曾经踩过的坑：
          ① 一度让同一部分所有「无编号 ## 节」共用一个 base → 第四部分的
             ## 1./## 2./… 全被编成 9.1、9.1… **互相撞号**。
          ② 附录的自有编号（附录九的 9.1–9.6）**不属于**章节体系，必须原样保留，
             否则会变成 10.1–10.6，「附录九 ↔ 10.x」直接对不上。
        回传 (新行, 子编号映射 {(部分,旧) -> (部分,新)}, 章号映射)。"""
        new_lines = list(self.lines)
        chap_map, sub_map = {}, {}
        seq = 0
        part, sec, base = None, None, None
        idx = {}
        for li, ln in enumerate(self.lines):
            m = RE_PART.match(ln)
            if m:
                part, sec, base = m.group(2), None, None
                continue
            m = RE_H2.match(ln)
            if m and not ln.startswith("###"):
                sec = m.group(2)
                mn = re.match(r"^([0-9]+)[.、]", sec)
                # 附录／附件自成编号体系 → 不参与重编号
                base = int(mn.group(1)) if mn else None
                if re.match(r"^附[录录件]", sec):
                    base = "SKIP"
                continue
            m = RE_CHAP.match(ln)
            if m:
                seq += 1
                chap_map[(part, m.group(2))] = cn(seq)
                base = seq
                new_lines[li] = f"{m.group(1)} {cn(seq)}、{m.group(3)}"
                continue
            m = RE_SUB.match(ln)
            if m:
                if base == "SKIP":
                    continue                      # 附录自有编号：原样不动
                b = base if isinstance(base, int) else (seq or 1)
                k = (part, sec, b)
                idx[k] = idx.get(k, 0) + 1
                newnum = f"{b}.{idx[k]}"
                sub_map[(part, f"{m.group(2)}.{m.group(3)}")] = (part, newnum)
                new_lines[li] = f"{m.group(1)} {newnum}{m.group(4)}"
        return new_lines, sub_map, chap_map

    def rewrite_refs(self, lines, sub_map, refmap):
        """改写引用。顺序很要紧：
        ① 先**字面**套人工 refmap（最长键优先）—— 这是唯一能处理「不带部分号的裸引用」
           与「原本就指错的引用」的手段；
        ② 再自动解析剩下的「第X部分 A.B」—— 这类目标唯一，可靠机械映射；
        ③ 仍解不出的**不猜**，原样保留并回报。
        """
        out = list(lines)
        changed, unresolved = [], []

        # ① 人工映射先落，但**用占位符保护**其结果 —— 否则它写出来的新编号会被第 ② 步
        #   当成「旧编号」再映射一次（实测：第三部分 5.4 → 6.4 → 又被映射成别的东西）。
        guard = {}
        for n, k in enumerate(sorted(refmap.keys(), key=len, reverse=True)):
            v = refmap[k]
            tok = f"\x00RT{n}\x00"
            hit = 0
            for li in range(len(out)):
                if k in out[li]:
                    out[li] = out[li].replace(k, tok)
                    hit += 1
            if hit:
                guard[tok] = v
                changed.append(f"{k} → {v}（人工指定，{hit} 处）")

        # ② 自动映射剩下的「第X部分 A.B」
        for li, ln in enumerate(out):
            new = ln
            for m in re.finditer(r"第([一二三四五六七八九十]+)部分\s*([0-9]+\.[0-9]+)", ln):
                key = m.group(0)
                if key not in new:
                    continue
                tgt = sub_map.get((m.group(1), m.group(2)))
                if tgt:
                    repl = f"第{tgt[0]}部分 {tgt[1]}"
                    new = new.replace(key, repl)
                    changed.append(f"{key} → {repl}")
                else:
                    unresolved.append(key)
            out[li] = new

        # ③ 还原人工映射的结果
        for li in range(len(out)):
            for tok, v in guard.items():
                if tok in out[li]:
                    out[li] = out[li].replace(tok, v)
        return out, changed, sorted(set(unresolved))


def main():
    ap = argparse.ArgumentParser(description="交付稿结构体检 ＋ 重编号（不改标题文字，只动编号与引用）")
    ap.add_argument("md")
    ap.add_argument("-o", "--out", default="", help="输出修复后的 md（不给＝只体检不写档）")
    ap.add_argument("--renumber", action="store_true", help="按正文出现顺序重编章号与子编号")
    ap.add_argument("--refmap", default="", help="人工引用映射 JSON：{\"第三部分 1.1\": \"第三部分 4.1\"}")
    ap.add_argument("--report", default="", help="把体检／修复报告写到这个路径")
    a = ap.parse_args()

    if not os.path.exists(a.md):
        print(f"❌ 找不到文件：{a.md}")
        sys.exit(2)
    text = open(a.md, encoding="utf-8").read()
    doc = Doc(text)

    R = []
    R.append("# 结构体检报告\n")
    R.append(f"> 对象：`{os.path.basename(a.md)}`　｜　由 `scripts/structure_fix.py` 生成\n")
    R.append(f"> 章节（### 中文数字、）{len(doc.parts)} 个　｜　子章节 {len(doc.subs)} 个\n")

    print("=" * 66)
    print("交付稿结构体检 · structure_fix.py")
    print("=" * 66)
    print(f"  章节 {len(doc.parts)} 个　｜　子章节 {len(doc.subs)} 个")

    hard, warn, refs, bare = doc.audit()
    rmap = {}
    if a.refmap:
        if not os.path.exists(a.refmap):
            print(f"❌ 找不到 --refmap：{a.refmap}")
            sys.exit(2)
        rmap = json.loads(open(a.refmap, encoding="utf-8").read())

    R.append("\n## 一、体检结果\n")
    R.append(f"- 带部分号的引用：**{len(refs)} 处**\n")
    R.append(f"- 硬问题：**{len(hard)}**　｜　警告：**{len(warn)}**\n")
    if hard:
        R.append("\n### 硬问题（必修）\n")
        for x in hard:
            R.append(f"- ❌ {x}\n")
    if warn:
        R.append("\n### 警告（建议修）\n")
        for x in warn:
            R.append(f"- ⚠️ {x}\n")
    print(f"  硬问题 {len(hard)}　｜　警告 {len(warn)}")
    for x in hard[:8]:
        print(f"    ❌ {x}")
    for x in warn[:6]:
        print(f"    ⚠️  {x}")
    if bare:
        print(f"  ⚠️  不带部分号的裸引用 {len(bare)} 处（目标靠上下文，脚本不猜）："
              + "、".join(f"行 {li+1}「{n} 节」" for li, n in bare[:6]))
        R.append(f"\n### 不带部分号的裸引用（{len(bare)} 处，需人工指认）\n")
        for li, n in bare:
            R.append(f"- 行 {li+1}：「{n} 节」 —— 目标落在哪个部分要靠上下文，"
                     f"自动改必错。请用 `--refmap` 指定，例如 `{{\"（{n} 节）\": \"（X.Y 节）\"}}`\n")

    lines, changed = list(doc.lines), []
    unresolved = []
    if a.renumber:
        lines, sub_map, chap_map = doc.renumber()
        lines, changed, unresolved = doc.rewrite_refs(lines, sub_map, rmap)
        print(f"\n  重编号：章号 {len(chap_map)} 个；标题文字一律未动")
        print(f"  引用改写：{len(changed)} 处；仍未解 {len(unresolved)} 处")
        for x in changed:
            print(f"    ✅ {x}")
        for x in unresolved:
            print(f"    ⚠️  无法自动判定：{x}　→ 用 --refmap 指到正确章节（不要猜）")
        R.append("\n## 二、重编号\n")
        R.append(f"- 章号重编：{len(chap_map)} 个（**标题文字一律未改**）\n")
        R.append(f"- 引用改写：{len(changed)} 处\n")
        for x in changed:
            R.append(f"  - {x}\n")
        if unresolved:
            R.append(f"\n### 仍未解（需人给 `--refmap`）\n")
            for x in unresolved:
                R.append(f"- ⚠️ {x}\n")
        R.append("\n## 三、重编号后的章节顺序\n")
        cur_part = None
        for ln in lines:
            m = RE_PART.match(ln)
            if m:
                cur_part = m.group(2)
                R.append(f"\n**第{cur_part}部分**\n")
                continue
            m = RE_CHAP.match(ln)
            if m:
                R.append(f"- {m.group(2)}、{m.group(3)}\n")

    if a.out:
        open(a.out, "w", encoding="utf-8").write("\n".join(lines))
        print(f"\n  已写出：{a.out}")
        R.append(f"\n---\n\n> 修复后文件：`{os.path.basename(a.out)}`\n")
    if a.report:
        open(a.report, "w", encoding="utf-8").write("".join(R))
        print(f"  已写出报告：{a.report}")

    if unresolved and not rmap:
        print("\n⚠️ 有引用无法自动判定目标 —— 依「不可解则不猜」原则，**没有硬套**。")
        print("   请人工确认后用 --refmap 指定，或手工改。")
        sys.exit(1)
    print("\n✅ 体检完成。" + ("　硬问题已随重编号一并处理。" if a.renumber and not hard else ""))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ structure_fix 执行出错：{type(e).__name__}: {e}")
        sys.exit(2)
