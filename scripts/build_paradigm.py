# -*- coding: utf-8 -*-
"""由 composer 骨架 ＋ paradigm_data 指引，机械生成 `references/12-范式库.md`。

用户原话：「每一个都需要有一个范式，例如B端的、C端的、小客户的，都需要有他们各自的
一个范式，不仅只有大纲，也需要有里面的内容可以参考。」

为什么要有这个脚本（而不是手写一份 md）：
- 手写一份「范式」＝第三份真相。骨架在 composer、指引在 paradigm_data、范文又手写一遍，
  三者迟早不一致 —— 这正是本知识库 2026-09-17 查出来的「只查文件内性质、零件全合格
  但传动轴是断的」那类病。
- 所以：**骨架只由 composer 产出，指引只由 paradigm_data 提供，本脚本负责拼装**。
  拼装前先做一致性校验（composer 实际输出的标题 vs SKELETON_HEADS），不一致直接退出 1。

用法：
    python scripts/build_paradigm.py            # 生成并校验
    python scripts/build_paradigm.py --dry-run  # 只校验，不写文件
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import composer as C  # noqa: E402
from _common import OK, NG, WARN, HINT, INFO  # noqa: E402
import paradigm_data as P  # noqa: E402

REF = os.path.join(ROOT, "references")
OUT = os.path.join(REF, "12-范式库.md")

# 校验用的一個「中性」規則表 —— 只為產出骨架，不影響任何匹配結果
DUMMY_RULES = {
    "client": "（示例）客户",
    "gate": {
        "賣什麼": "（示例）用于校验骨架结构的占位内容，不参与任何真实匹配。",
        "賣給誰": "（示例）同上，仅为让 gate 非空以避免匹配退化。",
        "現在規模": "（示例）同上，仅为让 gate 非空以避免匹配退化。",
    },
}


def heads_of(md):
    """抽出 markdown 里的标题（# / ## / ###），归一化后返回列表（跳过文档大标题）。"""
    out = []
    for line in md.split("\n"):
        m = re.match(r"^(#{1,3})\s+(.*\S)\s*$", line)
        if not m:
            continue
        level, text = len(m.group(1)), m.group(2)
        if level == 1:
            continue          # `# 客戶 · 营销方案` 是文档大标题，不算骨架節
        out.append(P.norm(text))
    return out


def live_skeleton(tier):
    """叫 composer 真的吐一次骨架，拿它的标题清单 —— 这是唯一真相。"""
    kmap = json.loads(C.read(C.KMAP))
    C.load_model_names(os.path.join(REF, "03-方法论操作手册.md"))
    C.load_books(os.path.join(REF, "cases", "49-营销书籍与作者.md"))
    if tier == "速览":
        md = C.build_lite(DUMMY_RULES, [], kmap, ["A"], "2026-01-01")
    else:
        md = C.build_skeleton(DUMMY_RULES, [], kmap, tier, ["A"])
    return md, heads_of(md)


def check(tier):
    """回傳 (ok, 說明)。比對 composer 實際骨架與 SKELETON_HEADS。"""
    md, live = live_skeleton(tier)
    declared = [P.norm(h) for h in P.SKELETON_HEADS.get(tier, [])]
    if live == declared:
        return True, f"{tier}：{len(live)} 節，一致"
    miss = [h for h in live if h not in declared]
    extra = [h for h in declared if h not in live]
    detail = []
    if miss:
        detail.append(f"composer 有但 paradigm_data 没声明：{miss}")
    if extra:
        detail.append(f"paradigm_data 声明了但 composer 没有：{extra}")
    if not detail:   # 内容相同、顺序不同
        detail.append(f"節點相同但顺序不一致。composer={live}")
    return False, f"{tier}：不一致 —— " + "；".join(detail)


def render_tier(tier):
    meta = P.TIER_META[tier]
    n = len(P.SKELETON_HEADS[tier])
    L = []
    L.append(f"## {tier}档 · {meta['alias']}\n")
    L.append(f"| 项 | 说明 |\n|---|---|\n"
             f"| 谁用 | {meta['who']} |\n"
             f"| 篇幅 | {meta['len']} |\n"
             f"| 这一档的关键 | {meta['key']} |\n"
             f"| 章节数 | {n} 节 |\n")
    L.append("**骨架（章节顺序，一级／二级／三级混排即实际层级）：**\n")
    L.append("```")
    for h in P.SKELETON_HEADS[tier]:
        L.append(h)
    L.append("```\n")
    L.append("**逐节填写指引**（该写什么／写几句／必须含哪几个数 ＋ 可直接改写套用的句片段）\n")
    missing = 0
    for h, g in P.guides_for_tier(tier):
        L.append(f"### {h}\n")
        if not g:
            missing += 1
            L.append("> ⚠️ 本节暂无指引（范式库缺口，需补 `scripts/paradigm_data.py`）。\n")
            continue
        L.append(f"- **该写什么**：{g['what']}")
        L.append(f"- **写几句**：{g['size']}")
        L.append(f"- **必须含**：{g['must']}")
        lines = g.get("lines") or []
        if lines:
            L.append("- **关键句片段**（可直接改写套用，数值用 `【填】` 占位）：")
            for x in lines:
                L.append(f"  - {x}")
        else:
            L.append("- **关键句片段**：本节为容器章（下面各小节各自给句片段）。")
        L.append("")
    return "\n".join(L), missing


def preserved_head():
    """保留既有檔頭（一級標題 ＋ 自解釋引用塊），避免每次重生都把 file_meta 的頭洗掉。

    為什麼要這樣：本腳本會**整檔重寫**，而 `file_meta.py --fix` 會給 references/ 下的
    每個檔插一段「這是什麼／什麼時候讀／讀完你能／目錄／規模」。若重生時不保留，
    就會出現「跑一次 build_paradigm → 頭沒了 → 再跑 file_meta → 又有了」的來回漂移，
    verify_all 的 50 遍冪等壓測會直接抓到（倉庫哈希變化）。
    """
    if not os.path.exists(OUT):
        return None
    old = open(OUT, encoding="utf-8").read().split("\n")
    i = 0
    while i < len(old) and not old[i].startswith("# "):
        i += 1
    if i >= len(old):
        return None
    head = [old[i]]
    j = i + 1
    while j < len(old) and (not old[j].strip() or old[j].lstrip().startswith(">")):
        if old[j].strip():
            head.append(old[j])
        j += 1
    return "\n".join(head)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只做一致性校验，不写文件")
    a = ap.parse_args()

    print("=" * 70)
    print("范式库生成 · build_paradigm.py")
    print("=" * 70)

    bad = []
    for t in P.TIER_ORDER:
        ok, msg = check(t)
        print(("  ✅ " if ok else "  ❌ ") + msg)
        if not ok:
            bad.append(t)
    if bad:
        print("\n❌ 骨架一致性校验未通过：composer 与 paradigm_data 已漂移。")
        print("   处理：以 composer.py 为准，改 scripts/paradigm_data.py 的 SKELETON_HEADS。")
        sys.exit(1)
    print("\n  ✅ 六档骨架与 paradigm_data 声明完全一致（无漂移）\n")

    if a.dry_run:
        print("（--dry-run：未写文件）")
        return

    head = [preserved_head() or "# 范式库 · 六档骨架与填写指引", ""]
    body = []
    total_missing = 0
    for i, t in enumerate(P.TIER_ORDER, 1):
        txt, miss = render_tier(t)
        total_missing += miss
        body.append(f"# 第 {i} 档 · {t}（{P.TIER_META[t]['alias']}）\n\n{txt}\n---\n\n")

    # 用法说明只放一次：首次生成时写，之后由 file_meta 的自解释头承担
    intro = (
        "> **怎么用**：先找到你这一单的档位（不知道就看 `SKILL.md` 第二节的档位定义），\n"
        "> 照着「骨架」把章节树搭出来，再逐节读「填写指引」——该写什么、写几句、必须含哪几个数，\n"
        "> 都在那里；「关键句片段」是可直接改写套用的句式，把 `【填】` 换成本案的数字即可。\n"
        ">\n"
        "> **范式与模板的区别**：模板只给空表，填的人照样不知道写什么；范式把「这一节写什么算合格」\n"
        "> 一并写出来。所以它既是骨架，也是内容参考。\n"
        ">\n"
        "> **六档一览**：速览（小客户／快速预览）= 只留决策要素；标准 = C 端品牌；\n"
        "> 大赛 = 比赛提案；B 端 = 企业／工业品／渠道；G 端 = 政府／政企；投标 = 招投标响应。\n"
        ">\n"
        "> ⚠️ 本文件由 `scripts/build_paradigm.py` 机械生成（骨架取自 `composer.py`，\n"
        "> 指引取自 `scripts/paradigm_data.py`），**请勿手改** —— 改了下次生成会被覆盖。\n"
    )
    if not any(q for q in head if "怎么用" in q):
        head.append(intro)
    text = "\n".join(head) + "\n\n---\n\n" + "".join(body)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(text)

    nchar = len(re.sub(r"\s", "", text))
    print(f"  ✅ 已生成 {os.path.relpath(OUT, ROOT)}")
    print(f"     档位 {len(P.TIER_ORDER)} 个 ｜ 章节 "
          f"{sum(len(P.SKELETON_HEADS[t]) for t in P.TIER_ORDER)} 节 ｜ 实字 {nchar:,}")
    if total_missing:
        print(f"     ⚠️ 有 {total_missing} 节没写指引（见文中「暂无指引」标记）")
    else:
        print("     指引覆盖：全部章节均有指引 ✅")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"{WARN} 已中断。")
        sys.exit(130)
    except Exception as e:
        # 协议 8：脚本挂了要能降级继续，不能让执行 AI 卡在裸 traceback 上。
        print(f"{NG} 執行出錯：{type(e).__name__}: {e}")
        print(f"{HINT} 依協議 8：修正後重跑；環境問題就改用 Markdown 協議手工完成，不要卡在這裡。")
        sys.exit(2)
