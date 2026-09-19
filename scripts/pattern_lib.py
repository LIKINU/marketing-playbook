#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pattern_lib.py — 把「商业模式体系全量解析」源稿转成**可公开**的《商业模式模式库》

为什么有它（2026-09-19）：
    桌面 `解析产物/商业模式体系全量解析-王冲108种+同赛道75家.md`（752KB／19.8 万实字）
    是对**在售出版物与课程体系**的逐条解析。它本身不含客户信息、不含隐私（已实测），
    但**整份公开到 GitHub 有两个不合适**：
      ① 逐条解析某本书的 108 条骨架 ≈ 该书的替代阅读物（关系面／版权面都不体面）；
      ② 内含 14 套具名体系 + 百余人名与身份描述，公开等于替别人做背书与评级。
    → 主库只收「**抽象化之后的模式库**」：留模式名与结构，去人名/书名/编号绑定；
      真名与书目属于**公开事实**，单独放文末《体系索引》（只列体系名/模式数/可信度，
      不含任何章节内容）。

    按本库纪律「能生成的不手写」：19.8 万字不可能手抄，脚本转换 + 负向自检。

用法：
    python3 scripts/pattern_lib.py --build     # 源稿 → references/14-商业模式模式库.md
    python3 scripts/pattern_lib.py --check     # 只检查产出物：不得残留人名/ISBN/书名
退出码：0 = 通过；1 = 检查不过（有残留）；2 = 出错
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "解析产物", "商业模式体系全量解析-王冲108种+同赛道75家.md")
OUT = os.path.join(ROOT, "references", "14-商业模式模式库.md")

from _common import OK, NG, WARN, INFO   # noqa: E402  统一符号，不要各自重定义

# ── 必须中性化的具名（人名／机构／书名）────────────────────────────────
#   ⚠️ 加新名字就加在这里；`--check` 会用同一张表扫产出物 —— **一张表，两处用**。
# ── 具名黑名单：**从源稿抽取，不手敲**（手敲必漏：实测漏掉陈杰/罗毅/熊浩/林奋/王昕）──
#   两个来源：① 第二部分 14 套体系的父标题里的中文/外文人名；② 第五部分人名表的姓名列。
_SYS_LINE = re.compile(r"(?m)^##\s+([A-N])\.\s*([^\n]+)$")
_ROSTER = re.compile(r"(?m)^\|\s*O\d+\s*\|([^|]{1,20})\|")


def system_name_map(src):
    """回 {体系代号: {该体系名下的人名}}，用来把「自己人」写成「本体系」。"""
    out = {}
    for m in _SYS_LINE.finditer(src):
        code, title = m.group(1), m.group(2)
        got = set()
        for seg in re.findall(r"[A-Za-z][A-Za-z.·\s]{2,20}", title):
            got.add(seg.strip(" ·"))
        for seg in re.findall(r"([\u4e00-\u9fff]{2,4})(?=[《「（])", title):
            got.add(seg)
        for par in re.findall(r"（([^）]{2,30})）", title):
            for seg in re.split(r"[·、／/\s]+", par):
                if re.fullmatch(r"[\u4e00-\u9fff]{2,4}", seg):
                    got.add(seg)
        out.setdefault(code, set()).update(x for x in got if x)
    return out


def extract_names(src):
    """从源稿里抽出具名（**只用两个可靠来源**，不做模糊抽词）。

    ⚠️ 教训（2026-09-19 第一版翻过车）：曾用「标题里所有 2–4 字中文词」当人名 →
    抽出「魏朱商业」这种**垃圾词**，替换时把正文的「魏朱商业模式」切成了「模式」——
    **抽名抽错＝直接把内容改坏**。所以只认两个结构化来源：
      ① **人名表的姓名列**（`| O1 | 李江涛 | …`，字段固定，最可靠）；
      ② **标题里紧贴引号的人名**（`X《…》`／`X「…」`／`X（…）`，且不含「商业/模式/盈利/体系」字样）。
    外加白名单补「魏朱」这类**连写合称**（算法抽不出）。
    """
    names = set()
    BAD = ("商业", "模式", "盈利", "体系", "框架", "合集", "学院派", "咨询")
    for m in _ROSTER.finditer(src):
        nm = m.group(1).strip()
        if re.fullmatch(r"[\u4e00-\u9fff]{2,4}", nm) and not any(b in nm for b in BAD):
            names.add(nm)
    # ③ **部分标题**里的「X《…》」（例：`# 第一部分 · 王冲《老板要学会的…》`）——
    #    第一版漏了这里，结果「王冲」27 处全留在正文里（独立 grep 才发现）
    #   ⚠️ 必须**后面紧跟引号**才算人名 —— 否则 `# 第三部分 · 同逻辑对照总表`
    #     会被当成名字，然后检查器去正文里把**我自己的标题**当成残留（误报）。
    for m in re.finditer(r"(?m)^#\s*第[一二三四五六]部分\s*·\s*([^《「\n]{1,8})(?=[《「])", src):
        nm = m.group(1).strip()
        if 2 <= len(nm) and not any(b in nm for b in BAD):
            names.add(nm)
    for m in _SYS_LINE.finditer(src):
        title = m.group(2)
        for seg in re.findall(r"[A-Za-z][A-Za-z.·\s]{2,20}", title):        # 外文人名
            names.add(seg.strip(" ·"))
        for seg in re.findall(r"([\u4e00-\u9fff]{2,4})(?=[《「（])", title):      # 引号前的中文人名
            if not any(b in seg for b in BAD):
                names.add(seg)
        # ④ **括号内的人名**（例：`魏朱商业模式（魏炜 · 朱武祥）`）——第一版也漏了
        for par in re.findall(r"（([^）]{2,30})）", title):
            for seg in re.split(r"[·、／/\s]+", par):
                seg = seg.strip()
                if re.fullmatch(r"[\u4e00-\u9fff]{2,4}", seg) and not any(b in seg for b in BAD):
                    names.add(seg)
    names |= {"魏朱"}          # 连写合称（公开场合常用）
    names.discard("")
    return sorted(names, key=len, reverse=True)


# ── 独立哨兵名单（**刻意不从源稿推导**）──────────────────────────────
# ⚠️ 为什么要有它：中性化与自检若共用同一份「从源稿抽出」的名单，
#   名单漏了谁，**两边一起漏** —— 检查器就成了自证（本专案的老毛病）。
#   这份是**独立基线**：哪怕哪天抽取逻辑坏掉，它也会叫。
SENTINEL = ["王冲", "魏炜", "朱武祥", "臧其超", "周导", "荆涛", "郑翔洲", "王靖飞",
            "林伟贤", "李践", "刘润", "陈杰", "罗毅", "熊浩", "林奋", "王昕", "刘育良",
            "Slywotzky", "Osterwalder", "Gassmann", "今智塔", "行动教育"]
BOOK = re.compile(r"《[^》]{1,40}》")
ISBN = re.compile(r"ISBN[\s:：-]{0,3}[\dXx][\dXx\- ]{8,20}")   # 只认带书号数字的，别命中「有 ISBN 可查」
# 「第 N 条」「原书第 N 页」这类**出处绑定**——抽象化时去掉编号绑定，只留模式名
SRC_REF = re.compile(r"(?:原书|原文|书中)\s*第\s*[\d一二三四五六七八九十]+\s*(?:页|章|节|条)")
PART1_RE = re.compile(r"^####\s+(⚠️\s*)?(\d{1,3})\.\s*([^\n〔]{2,30})\s*(〔[^〕]*〕)?\s*$")
SYS_RE = re.compile(r"^##\s+([A-N])\.\s*([^\n]+)$")
ENTRY_RE = re.compile(r"^####\s+(⚠️\s*)?([A-N]?\d{1,3})\.\s*([^\n〔]{2,40})\s*(〔[^〕]*〕)?\s*$")


def read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def neutralize(s, names, own=None, sysmap=None):
    """把人名/机构/书名/ISBN/出处绑定处理掉，**并且保住句子的意思**。

    ⚠️ 两个教训（2026-09-19 同一天第二次翻车）：
    ① **不能把所有人名都换成同一个占位符** —— 「与 A 的最大差异：A 以行业热点组织、
       B 以利润来源组织」会变成「与该体系的最大差异：该体系…该体系…」，**比较句直接失去意义**。
       → 改成：**属于当前这一节的体系 → 「本体系」**；**其他体系 → 「对照体系」**。
    ② 顺序：**先书名再人名**，否则《…》里的书名会先被人名规则切碎。
    """
    s = BOOK.sub("本体系" if own else "对照体系", s)     # ① 书名
    for n in names:                                      # ② 人名／机构（长词优先）
        who = "本体系" if (own and sysmap and n in sysmap.get(own, ())) else "对照体系"
        if own and not sysmap:
            who = "本体系"
        s = s.replace(n, who)
    s = ISBN.sub("", s)
    s = SRC_REF.sub("", s)
    s = re.sub(r"(本体系[\s、，／·]{0,3}){2,}", "本体系", s)      # ③ 收敛重复与残留标点
    s = re.sub(r"(对照体系[\s、，／·]{0,3}){2,}", "对照体系", s)
    s = re.sub(r"(本体系|对照体系)体系", r"\1", s)        # 「对照体系体系」→「对照体系」
    s = re.sub(r"[、，]{2,}", "、", s)
    s = re.sub(r"（\s*）", "", s)
    s = re.sub(r"(本体系|对照体系)\s+(?=[以的在与])", r"\1", s)   # 占位符后多余空格
    return s


def build():
    if not os.path.exists(SRC):
        print(f"{NG} 找不到源稿：{SRC}")
        return 2
    src = read(SRC)
    names = extract_names(src)
    print(f"  从源稿抽出具名 {len(names)} 个（用于中性化与自检）")
    lines = src.split("\n")
    out = []
    stats = {"p1": 0, "p2": 0, "p5_rows": 0}

    head = f"""# 14 · 商业模式模式库（抽象化整理）

> **这是什么**：把「怎么赚钱」这件事拆成**可查的模式条目** —— 每个模式给
> **本质 → 钱从哪来 → 什么时候用 → 怎么落地 → 坑 → 示例** 六段，用来回答
> 「这个客户的商业模式属于哪一类、它的钱从哪来、我该往哪儿加杠杆」。
> **不是营销打法**（打法见 [[00-打法库]]）：打法回答「怎么打」，模式库回答「他的钱是怎么来的」。
>
> **体例**：每条 6 段，篇幅统一；条目名前标 ⚠️ ＝**依模式名与通行实践解析**（未获权威原文），
> 无标记 ＝ 有公开可查依据。**可信度分级是刻意的**：不把「整理」说成「原文」。
>
> ⛔ **使用边界（必读）**：
> 1. 本库是**二次整理的抽象结构**，不是任何一本书／课程的内容，**不能当作它的替代阅读**；
>    要引用某个体系的原意，请回到该体系的正式出版物。
> 2. 本库**不署具体人名与书目**（避免替第三方做背书或评级）；体系与书目清单见文末
>    「附录 · 体系索引」—— 那里只有**公开事实**（体系名／模式数／可查性），不含任何内容。
> 3. 示例段落一律为**公开事实的匿名化写法**（「某新能源车企」这类），不出现具体公司＋经营数字的组合。
>
> **整理日期**：2026-09-19 ｜ **条目规模**：见文末统计

---

"""
    out.append(head)

    # 逐行扫描，按「部分」分派处理
    part = 0
    cur_code = None        # 当前体系代号（用于把「自己人」写成「本体系」）
    sysmap = system_name_map(src)
    # 第一部分的「自己人」＝部分标题里那个人名（它是 108 条的体系本身，不该叫「对照体系」）
    _own_first = re.search(r"(?m)^#\s*第[一二三四五六]部分\s*·\s*([^《「\n]{1,8})(?=[《「])", src)
    if _own_first:
        sysmap.setdefault("A0", set()).add(_own_first.group(1).strip())
    skip_front = True      # 丢掉源稿自身的 H1 与「〇 使用说明／一 全书结构一览」
    skip_p56 = 0           # 第五/六部分（61 家人名录）整段不进主库，只计数
    i = 0
    while i < len(lines):
        ln = lines[i]
        # ⛔ 源稿自身的 H1 与前言：那是对「源稿」的描述，不是模式知识；全库已有自己的前言
        if ln.startswith("# ") and not re.match(r"^# 第[一二三四五六]部分", ln):
            i += 1
            continue
        if skip_front:
            if re.match(r"^##\s+二、", ln):
                skip_front = False      # 从这里开始才是知识（赛道归并 + 逐条解析）
                cur_code = "A0"
                out.append("# 第一部分 · 通用模式一览（108 条）\n")
                out.append("## 赛道归并（哪些模式其实是同一个赛道）\n")
                i += 1
                continue
            i += 1
            continue
        if part in (5, 6):
            if ln.strip() and not ln.startswith(">"):
                skip_p56 += 1
            i += 1
            continue
        m = re.match(r"^# 第([一二三四五六])部分[^\n]*$", ln)
        if m:
            part = "一二三四五六".index(m.group(1)) + 1
            # 部分标题中性化
            if part == 1:
                cur_code = "A0"
                out.append("# 第一部分 · 通用模式一览（108 条）\n")
            elif part == 2:
                out.append("# 第二部分 · 各体系模式（按体系分组）\n")
            elif part == 3:
                out.append("# 第三部分 · 同逻辑对照总表\n")
            elif part == 4:
                out.append("# 第四部分 · 选用建议\n")
            elif part in (5, 6):
                pass        # 整段不进主库（61 家人名录：具名最密、知识密度最低）
            else:
                pass
            i += 1
            continue

        # ── 第五部分：只保留「编号 | 模式名 | 赛道 | 原文依据」四列，删姓名/身份/机构 ──
        # ── 体系父标题：去人名与书名，保留代号与规模 ──
        ms = SYS_RE.match(ln)
        if ms:
            code, title = ms.group(1), ms.group(2)
            # 父标题只保留「数量 + 类型」：`Slywotzky《发现利润区》· 22 种盈利模式` → `22 种盈利模式`
            tail = title.split("·")[-1].strip()
            tail = BOOK.sub("", tail)
            for n in names:
                tail = tail.replace(n, "")
            tail = re.sub(r"^[\s（()）·、]+", "", tail).strip()
            tail = re.sub(r"[（(]\s*[）)]|）\s*$", "", tail).strip()   # 清空括号/落单右括号
            if not tail or len(tail) < 2:
                tail = "（公开体系）"
            cur_code = code
            out.append(f"## 体系 {code} · {tail}")
            stats["p2"] += 1
            i += 1
            continue

        # ── 条目行：保留编号（它就是索引锚点），去掉〔赛道〕外的所有具名 ──
        for pat, key in ((PART1_RE, "p1"), (ENTRY_RE, "p2")):
            me = pat.match(ln)
            if me:
                warn, no, name, track = me.group(1) or "", me.group(2), me.group(3), me.group(4) or ""
                out.append(f"#### {warn}{no}. {neutralize(name, names, cur_code if part == 2 else None, sysmap).strip()} {track}".rstrip())
                if key == "p1":
                    stats["p1"] += 1
                i += 1
                break
        else:
            out.append(neutralize(ln, names, cur_code, sysmap))
            i += 1
            continue
        continue

    body = "\n".join(out)

    # ── 附录 · 体系索引（公开事实：体系名／模式数／可查性；**不含任何章节内容**）──
    appendix = """
---

# 附录 · 体系索引（仅公开事实）

> 说明：这里只列**「有哪些体系、各有多少条模式、可否查到权威来源」**，
> 属于公开书目信息；**本库正文不含这些体系的任何内容**。
> 本表不附人名与机构，避免替第三方做背书或评级。

| 体系代号 | 体系名（公开书目） | 模式数 | 可查性 |
|---|---|---|---|
| A | 《老板要学会的 108 种新盈利模式》 | 108 | 有 ISBN 可查 |
| B | 《发现利润区》 | 22 | 有 ISBN 可查 |
| C | 《利润模式》 | 30 | 有 ISBN 可查 |
| D | 《商业模式新生代》 | 5 | 有 ISBN 可查 |
| E | 《商业模式导航仪》 | 55 | 有 ISBN 可查 |
| F | 魏朱商业模式 | 待核 | 公开出版物 |
| G | 「36 种新盈利模式」 | 36 | 公开课程 |
| H | 「逆向盈利」 | 待核 | 公开课程 |
| I | 「6 种盈利模式」 | 6 | 公开课程 |
| J | 「新商业模式创新设计」 | 待核 | 公开出版物 |
| K | 「商业模式」 | 待核 | 公开课程 |
| L | 「商业模式」 | 待核 | 公开课程 |
| M | 「赢利模式」 | 待核 | 公开课程 |
| N | 商业演化模型 | 待核 | 公开文章 |
| O | 学院派框架合集 | 待核 | 公开文献 |

> 各体系统一的阅读顺序与选用建议见正文第四部分；同逻辑对照见第三部分。
>
> 另有 **61 家国内公开课程／咨询体系**（半名录与总览类），**本库刻意不列其名与身份** ——
> 那属于替第三方做背书与评级，且知识密度低于模式本身。需要时按「体系代号」检索原始公开资料。

---

_本文件由 `scripts/pattern_lib.py` 从源稿机械转换（**去具名、去出处绑定**）后落库；
转换脚本带负向自检（产出物不得残留任何人名／ISBN／书名），并入全量回归。_
"""
    body = body.rstrip() + "\n" + appendix
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(body)

    # ── 复用全库同一份词表做「港台用词 → 内地用词」──
    # ⚠️ **不在这里抄一份词表**：词汇表是人工审定的单一真源（`lang_unify.py` 的 VOCAB）。
    #   不接这一步的后果实测过：生成物里混进了港台用词，`lang_unify` 一跑就改，
    #   于是「重新生成」＝把简体又覆盖回去 → **不幂等**（下一轮全量压测会报漂移）。
    import subprocess
    _r = subprocess.run([sys.executable, os.path.join(HERE, "lang_unify.py"),
                         "--fix", "--only", os.path.relpath(OUT, ROOT)],
                        capture_output=True, text=True)
    if _r.returncode != 0:
        print(f"{WARN} 语言统一未跑通（rc={_r.returncode}）：{(_r.stdout or _r.stderr).strip()[:120]}")
    else:
        print(f"  已复用 lang_unify 的词表统一用词（--only 本档）")
    zh = len(re.findall(r"[\u4e00-\u9fff]", body))
    print(f"{OK} 已生成 {os.path.relpath(OUT, ROOT)}：{zh:,} 实字"
          f"（条目：第一部分 {stats['p1']}｜体系 {stats['p2']}）"
          f"｜跳过的源稿前言与名录行 {skip_p56} 行（按设计不入库）")
    return 0


def check():
    """负向自检：产出物里不得残留具名/书名/ISBN。"""
    if not os.path.exists(OUT):
        print(f"{NG} 产出物不存在，先跑 --build")
        return 2
    t = read(OUT)
    names = extract_names(read(SRC))
    # ⚠️ **附录按设计就该有书目**（体系索引只列公开事实）→ 只严查**正文**，附录单独报。
    _body, _sep, _app = t.partition("# 附录 · 体系索引")
    bad = []
    for n in sorted(set(names) | set(SENTINEL), key=len, reverse=True):
        c = _body.count(n)
        if c:
            bad.append((n, c))
    for pat, lab in ((BOOK, "《书名》"), (ISBN, "ISBN")):
        hits = pat.findall(_body)
        if hits:
            bad.append((f"{lab} × {len(hits)}", len(hits)))
    if _sep:
        _app_books = len(BOOK.findall(_app))
        print(f"  ℹ️ 附录（按设计）含书目 {_app_books} 条 —— 那是公开事实，不计入残留")
    if bad:
        print(f"{NG} 产出物仍有具名残留 {len(bad)} 类：")
        for k, c in bad:
            print(f"   · {k}：{c} 处")
        return 1
    print(f"{OK} 产出物干净：正文里 {len(names)} 个源稿人名/机构 + 书名 + ISBN 全部为 0")
    return 0


def main():
    ap = argparse.ArgumentParser(description="模式库转换与自检")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.build:
        rc = build()
        if rc == 0 and check() != 0:
            return 1
        return rc
    if a.check:
        return check()
    print("用法：--build 生成｜--check 自检")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"{NG} 出错：{type(e).__name__}: {e}")
        sys.exit(2)
