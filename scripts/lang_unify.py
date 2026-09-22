#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lang_unify.py —— 全仓语言统一（繁体 → 简体）

背景（2026-09-18，用户指令「**全部都改成简体吧**」）
--------------------------------------------------
本 skill 原本采**双轨语言**：交付物简体 ／ 内部文档繁体。
代价是一个永久的转换步骤（`composer` 注入知识库内容时要逐字 t2s），
而且「哪一份该是哪一种」只能靠人记 —— 记错就是交付稿混繁体。

用户裁定：**全仓统一简体**。这反而让规则变简单：
  - 知识库简体 → `composer` 的 t2s 变成 no-op（少一个会出错的环节）
  - 交付物本来就必须简体 → 一条规则管到底

⚠️ **「交付物必须简体」这条没有放松**：`selfcheck`【9】照旧把繁体交付稿判硬错误
   —— 它现在的意义变成「挡外部贴进来的繁体」，比以前更需要。

两处**不准转**（转了就坏）
--------------------------
① `scripts/t2s_data.py` —— 它的 `T2S_PAIRS` 是「**偶位繁体／奇位简体**」的**资料**。
   整档转下去等于把两半压成一半，`selfcheck` 的繁体侦测立刻失效。
   （该档的散文本来就是简体，所以整档略过最干净。）
② 任何含 **`lang-keep-trad`** 标记的那一行 —— 最典型的例子是 `smoke_test.py` 的
   **繁体负向夹具**：它必须保持繁体，否则「繁体稿应被拦」这个测试就变成
   在测一份简体稿（永远该通过）→ 测试静默失效。

用法
----
    python scripts/lang_unify.py                   # 只扫描报告（只读）
    python scripts/lang_unify.py --fix             # 就地转换
    python scripts/lang_unify.py --fix --dry-run   # 只列出会动哪些档
    python scripts/lang_unify.py --strict          # 还有繁体就 exit 1（当门槛用）

转换引擎
--------
优先 `opencc`（词组级，较准）；没装则退回**本仓库自带**的 `t2s_data.T2S_PAIRS`
（零依赖、覆盖本知识库实际用到的字）。实际用了哪个会明示 —— 不静默降级。
"""

import argparse
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

TEXT_EXT = {".md", ".py", ".json", ".sh", ".txt"}
SKIP_DIRS = {".git", ".workbuddy", "__pycache__", "node_modules",
             # 本地工作稿（把书／长文拆成一节节的中间产物，已进 .gitignore 不入库）——
             # 它与 `repo_hygiene.SKIP_DIRS` 同步排除：不入库的东西不必进语言统一的报告，
             # 否则「需转换：1 个文件｜0 处」这种空报告会一直挂在最后一关。
             "解析产物",
             # ⚠️ 2026-09-22 补 `优化轮次`：它早就该在这 —— `repo_hygiene.SKIP_DIRS` 里一直有它，
             #   这里漏了（注释明明写着「同步排除」，**两处其实没同步**）。
             #   更要紧的是性质：该目录放的是**过程记录与外部来的原件**（如豆包的评审档），
             #   那些繁体是**原件的原貌** —— 转成简体就等于**篡改证据**。
             "优化轮次"}

# 整档略过（见档头 ① ）
# ⛔ 这两支**整档都不许动**（见下方 VOCAB 注释的同一道理）：
#    · `t2s_data.py` —— `T2S_PAIRS` 是「偶位繁体／奇位简体」的**判据数据**
#    · `lang_unify.py` 自己 —— 本档的 `VOCAB` 表与「否决理由」清单里**必然**写满港台用词，
#      它就是尺子本身；跑一遍自己的词汇层会把表改掉（实测：119 处）
EXCLUDE_FILES = {"scripts/t2s_data.py", "scripts/lang_unify.py"}
# 行级护栏（见档头 ② ）。
# ⚠️ 判据必须是「**行尾注释里的**标记」，不能只找字串：本档的说明文字与
#    `KEEP_MARK = "…"` 这一行都含这个字串，宽松判据会把它们一起保护起来
#    —— 于是「保护繁体」的机制反过来保护了自己的说明，变成自我豁免。
# 支持两种注释形态：Python/shell 的 `#` 与 Markdown/HTML 的 `<!-- -->`
#   —— 规约条款、变更记录是 .md，也需要「这一行是判据／举例，别动」的能力。
KEEP_RE = re.compile(r"(?:#|<!--)\s*lang-keep-trad")


# ── 已知「替换撞车」产生的坏词：出现即硬错误（**判据靠攒**）────────────────
#
# 为什么单列这一关：下面这些**不是错别字，是替换撞车**。幂等复查**抓不到它们**——
# 撞车的结果本身是稳定的（跑第二遍不再变），所以「跑两遍一样」证明不了没问题。
# 每发现一个新的就加一条，下次它再出现会立刻红灯。
#
#   产质量量 ← 「产品品质」里的「品质」被换（品质→质量）
#   X文件案  ← 「X档案」里的「X档」被先换（个档→个文件 抢在 档案→文件 前面）
#   …尔／…斯坦 ← 国名替换自我触发（厄瓜多→厄瓜多尔 的结果里仍含「厄瓜多」）
BAD_ARTIFACTS = [
    r"产质量量", r"[个单跨多逐份]文件案",
    r"文件[次期位级]",          # 「一个档次／五个档期／六个档位」被 个档→个文件 撞坏
    r"厄瓜多尔尔", r"尼日尔尔", r"哈萨克斯坦坦", r"乌兹别克斯坦坦",
]

# ═══ 词汇层：港台用词 → 内地用词（**人工审定**，不是引擎产物）═══════════════
#
# 为什么不用 opencc 的 `tw2sp`：它的词表是为「台湾正体」设计的，拿它跑**已经是简体**的
# 文本会误触发。2026-09-18 实测（本仓库真实语料）：
#     什么 → 什幺 ／ 小程序 → 小进程 ／ 核心结论 → 内核结论 ／ 文件 → 文档
# 用不了。**词汇替换只能是人工审定的表。**
#
# 候选怎么来的：`opencc/dictionary/TWPhrasesRev.txt`（518 对）
#   ∩ 本仓库实际出现（137 对），再逐条人工筛。**筛掉约 60 条**，
#   最常见的否决理由有三类，写在这里免得下次有人「照表全转」：
#
#   ① **它本来就是内地标准词**（最大的一类，也是最大的一类误伤）
#      核心→内核／执行→运行／线上→在线／指标→指针／建立→创建／复制→拷贝／新增→添加／
#      文件→文档／互动→交互／整合→集成／程序→进程／简报→演示文稿／预设→缺省／
#      通道→信道／智慧→智能／序列→串行／类比→模拟／模拟→仿真／遮蔽→屏蔽／向量→矢量／
#      通讯→通信／查询→查找／列举→枚举／高阶→高端／进阶→高端／区域性→局部／
#      社群→社区／截图→截屏／存档→存盘／启用→激活／过载→重载／堆叠→堆栈／离线→脱机
#      —— 这些在内地书面语里全是正常词；照表换会把「执行摘要」「线上线下一体」「KPI 指标」
#         「智慧城市」「小程序」改成错的。
#   ② **词表本身是错的**：正规化→范式（正规化＝规范化，范式＝paradigm，语义不同；
#      而「范式」恰是本仓库的自有术语，换了会把整套文档改名）
#   ③ **同形不同义、要看上下文**（人工核过上下文后否决，逐条给理由）：
#      装置→设备：本仓库 32 处里绝大多数是「艺术装置／场景装置」（内地也说「装置」），
#                 换了会把「沉浸式山石艺术装置」变成「艺术设备」
#      物件→对象：13 处全是**实体物件**（「日常物件」「能被拍照的物件」），内地也说「物件」
#      呼叫→调用：9 处里混着「紧急呼叫按钮」（换了变成「紧急调用按钮」）
#      图示→图标：2 处是「用图示说明」（＝插画），图标＝icon，两回事
#      讯息→消息：内地本来就用「讯息」，且「媒介即讯息」是这句的通用译法
#      宣告→声明：内地本来就用「宣告」；本仓库把它当技术术语（「宣告清单」），换不划算
#      plus 堆叠（内地营销说「叠加」，数据结构才说「堆栈」）／乳酪／桌布（2 处，可能是桌布本义）
#
# 本表只收「一眼是港台用词、且在内地有唯一对应」的。
VOCAB = [
    # ── 商业／营销（本仓库高频，最要紧的一组）──
    ("渠道通路", "渠道"),          # 必须先于「通路」→「渠道」，否则变成「渠道渠道」
    ("行销", "营销"),              # 本仓库「营销」远多于「行销」，统一
    ("品质感", "质感"),            # 必须先于「品质」→「质量」
    # ⚠️ `(?!量)`：原文里**本来就对**的「产品质量／商品质量」含 `品质` 子串，
    #    无断言会把它们换成「产品质量」（2026-09-18 实测 14 处）
    ("品质(?!量)", "质量"),
    # ⚠️ 2026-09-22 加前置断言：`通路` 会撞进**「普·通路·径」**（实测被改成「普渠道径」）——
    #   这是本库第 6 次「子串替换撞车」。规矩：**短键必须枚举它会撞进去的词**：
    #     · 后置撞车 → `键(?!后缀)`（见上一条「渠道通路」的处理）
    #     · 前置撞车 → `(?<!前缀)键`（本条）
    #   新增短键时**两向都要想一遍**，别只防一边。
    # ⚠️ **已识别的潜伏撞车**（2026-09-22 全表扫过一遍，9 个键有前置撞车外形，逐个看上下文后）：
    #     · 真撞车 3 个：`客制`（创客制度）／`内建`（层内建立）／`机率`（开机率）
    #     · 但它们**目前只出现在 `解析产物/`**，而该目录在 SKIP_DIRS → **实际不会触发**。
    #     · → **现在不加断言**（防一个到不了的情况＝无谓复杂度，本库规矩：不能复现的需求不加）。
    #       但若哪天把 `解析产物/` 纳入扫描，**先给这 3 个加前置断言**，否则会改出
    #       「创定制度」「层内置立」「开几率」这类**通顺但错**的中文。
    (r"(?<!普)通路", "渠道"),
    ("客制", "定制"),
    # ── 文件／资料 ──
    # ⚠️ 每个 `X档` 都带 `(?!案)`：不然「个档」会先命中「**个档案**」里的两个字，
    #    把「N 个档案」拆成「N 个文件**案**」（2026-09-18 实测）。带上断言后，
    #    「个档案」整段交给下面的「档案→文件」处理，结果是「个文件」✓
    # ⚠️ 断言必须写全 `案|次|期|位|级` —— `个档` 会撞进「一个档**次**」「五个档**期**」
    #    「六个档**位**」这几个词里，换成「文件＋次／期／位」那种**不成词**的东西
    #    （2026-09-19 实测 9 处）。这类**结果是合法中文、只是意思错了**的撞车，
    #    坏词嗅探抓不到 —— 只能靠把断言一次写全。
    ("档头(?!案|次|期|位|级)", "文件头"), ("档名(?!案|次|期|位|级)", "文件名"),
    ("单档(?!案|次|期|位|级)", "单文件"), ("跨档(?!案|次|期|位|级)", "跨文件"),
    ("多档(?!案|次|期|位|级)", "多文件"), ("逐档(?!案|次|期|位|级)", "逐文件"),
    ("个档(?!案|次|期|位|级)", "个文件"), ("份档(?!案|次|期|位|级)", "份文件"),
    ("档案", "文件"),
    ("资料夹", "文件夹"), ("资料库", "数据库"),
    ("栏位", "字段"), ("字串", "字符串"), ("字元", "字符"), ("字型", "字体"), ("型别", "类型"),
    # ⛔ 不换「档」本身：「标准档／速览档／档位／档期／高档」在内地也是对的（那是「档位」不是「文件」）
    # ── 技术概念 ──
    ("使用者", "用户"), ("伺服器", "服务器"), ("软体", "软件"), ("硬体", "硬件"),
    ("模组", "模块"), ("介面", "接口"), ("函式", "函数"),
    ("程式码", "代码"), ("程式", "程序"),          # 「码」必须在「程式」之前
    ("演算法", "算法"), ("布林", "布尔"), ("阵列", "数组"), ("变数", "变量"), ("引数", "参数"),
    ("元件", "组件"), ("回圈", "循环"), ("内建", "内置"), ("外挂", "插件"),
    # ⚠️ `(?!择)`：`点选` 会撞进「试｜点选｜择标准」（试＋点选＋择标准），
    #    把「试点选择标准」弄成不成词的「试点＋击＋择标准」（2026-09-19 实测 3 处）。
    #    本档已被 EXCLUDE_FILES 排除，所以这里能把坏形态写出来当例子。
    ("点选(?!择)", "点击"), ("选单", "菜单"), ("载入", "加载"), ("开启", "打开"),
    ("视觉化", "可视化"),     ("点选(?!择)", "点击"), ("重新命名", "重命名"), ("相容", "兼容"),
    # ⚠️ 2026-09-19 删掉两对「过度适用」的规则（第二、三次栽在同一类）：
    #   · `批次 → 批量`：本仓库用「批次」表示 **batch（第 N 批）**，与「批量（batch size）」不同义。
    #     实测把它改成了「每批的条目数」才能表达原意 —— 说明**被改的那句本来是对的**。
    #   · `扫描器 → 扫描仪`：`扫描仪` 是**硬件**；本仓库指的是**代码扫描器／审计器**
    #     （改完会得到「审计仪」这种不通的说法）。
    #   → 判准：港台词表里那些**在内地同样合法、且本领域有专门含义**的词，不要进表。
    #     **宁可漏转一个词，也不要把对的话改错**（错词的嗅探难度远高于漏转）。
    ("支援", "支持"), ("讯号", "信号"), ("连结", "链接"),
    ("贴上", "粘贴"), ("简讯", "短信"), ("部落格", "博客"), ("列印", "打印"),
    ("远端", "远程"), ("缩排", "缩进"), ("页首", "页眉"), ("页尾", "页脚"),
    ("连线", "连接"), ("检视", "查看"), ("解析度", "分辨率"), ("萤幕", "屏幕"), ("触控", "触摸"),
    ("磁碟", "磁盘"), ("汇入", "导入"), ("释出", "发布"), ("高画质", "高清"),
    ("除错", "调试"), ("登入", "登录"), ("联络", "联系"), ("作业系统", "操作系统"),
    ("区域网", "局域网"), ("多工", "多任务"), ("重新整理", "刷新"),
    ("半形", "半角"), ("全形", "全角"), ("取样", "采样"), ("机率", "几率"),
    ("镭射", "激光"), ("矽", "硅"),
    # ── 国名／外来词 ──
    # 国名要「不重复加后缀」：`厄瓜多`→`厄瓜多尔` 的结果里**仍含** `厄瓜多`，
    # 不写断言的话每跑一遍就多一个「尔」—— 2026-09-18 实测把
    # `厄瓜多尔` 变成了 `厄瓜多` + `尔尔`（该错误形态见本档 VOCAB 的断言注释；
    # 本档已被 EXCLUDE_FILES 排除，所以这里的举例不会被自己改掉）
    ("厄瓜多(?!尔)", "厄瓜多尔"), ("卡达", "卡塔尔"), ("查德", "乍得"),
    ("尼日(?!尔)", "尼日尔"), ("哈萨克(?!斯坦)", "哈萨克斯坦"), ("乌兹别克(?!斯坦)", "乌兹别克斯坦"),
    ("泡面", "方便面"), ("速食面", "方便面"), ("计程车", "出租车"),
]

# ── 词汇层例外：这些短语里的词是**另一个义项**，内地也用原词，不能换 ────────────
# 机制：先把例外短语换成哨兵（不可能出现在正文里的字符），跑完替换再还原。
# 为什么需要它：`档案` → `文件` 在「文件」义上（135 处里的约 129 处）是对的，
#   但「公司档案／机构档案」是**档案袋·卷宗**义 —— 内地同样说「档案」，
#   换成「公司文件」就把「不记公司档案（创办人、成立年份…）」这句的意思弄歪了。
VOCAB_KEEP = [
    "公司档案", "机构档案", "人事档案", "客户档案", "档案袋",
    "档案管理", "档案室", "档案馆",          # 内地同样说「档案」，不是「文件」
]


# ── 字体层例外：这些词里的字**不是繁体**，是规范字／专名用字 ──────────────────
# 与 `VOCAB_KEEP` 是同一类问题（「公司档案」的「档案」不是「文件」），
# 只是发生在**字体层**：引擎退到 `t2s_data` 字级表时（opencc 不可用），
# 下面这些字会被**逐字**换掉，而它们本来就是对的中文 —— 换了就是错字。
#
# 2026-09-21 实测（本仓库真实语料：报告 71 处「繁体」里 **38 处是这一类**）：
#   `吒→咤`：《哪吒之魔童闹海》《哪吒汽车》《哪吒 2》→「哪咤」
#            —— 「吒」本身就是规范字（「哪吒」用「吒」，「叱咤风云」才用「咤」）
#   `乾→干`：「乾坤圈」造型书签 →「干坤圈」 —— 「乾」读 qián 时简体仍写「乾」
#   `尅→克`：「尅街」（街区专名）→「克街」
#
# ⚠️ 护栏放在**本档**，不放 `t2s_data.py`：那张表是「扫描语料 → 逐字转换」机械生成的
#    （见其档头），它根本不知道「哪咤」是错的 —— 下次重新生成，错映射还会回来。
#    「这个词不能换」是**使用方的纪律**，所以留在这一层。
FONT_KEEP = [
    "哪吒", "乾坤", "尅街",
]



def engine():
    """回传 (convert_fn, 引擎名)。不静默降级 —— 用了哪个、为什么，都要说出来。"""
    try:
        import opencc
        cc = opencc.OpenCC("t2s")
        return cc.convert, "opencc（词组级）"
    except ImportError as e:
        # 这不是「吞掉异常」，是**有意的降级**：opencc 是可选依赖，
        # 本仓库刻意让 t2s_data.py 兜底（跨机器、没网也要能跑）。
        # 但降级**必须说出来** —— 静默降级会让人以为用的是词组级引擎，
        # 实际拿到的是字级结果而不自知。所以把原因一起带进引擎名。
        _why = f"opencc 不可用：{type(e).__name__}"
    sys.path.insert(0, HERE)
    try:
        from t2s_data import T2S_PAIRS
    except ImportError:
        print("❌ 既没有 opencc，也载不到内置表 t2s_data.py —— 无法转换。", file=sys.stderr)
        print("   解：pip install opencc-python-reimplemented", file=sys.stderr)
        sys.exit(2)
    m = dict(zip(T2S_PAIRS[::2], T2S_PAIRS[1::2]))
    return (lambda s: "".join(m.get(c, c) for c in s)), f"t2s_data（内置表，字级；{_why}）"


# `--only` 限定范围（**供生成器复用本脚本的词表**，不另抄一份）：
#   例：`lang_unify.py --fix --only references/14-商业模式模式库.md`
ONLY = []


def targets():
    if ONLY:
        return [os.path.relpath(x, ROOT) if os.path.isabs(x) else x for x in ONLY]
    out = []
    for dp, dn, fn in os.walk(ROOT):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for f in fn:
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, ROOT)
            if rel.replace(os.sep, "/") in EXCLUDE_FILES:
                continue
            if os.path.splitext(f)[1].lower() in TEXT_EXT:
                out.append(rel)
    return sorted(out)


# 词汇层按「**最长键优先**」排序 —— 与 `impact.py` 的 `specificity()` 是同一条规矩：
# 判据是「谁更具体」，不是「谁先写」。表里已手动排过序，这里再排一次兜底，
# 免得后来人往里插了短键（如「通路」插到「渠道通路」前面）就静默出错。
VOCAB_SORTED = sorted(VOCAB, key=lambda kv: -len(kv[0]))


def apply_vocab(t):
    """先给例外短语上哨兵 → 跑替换 → 还原。

    顺序不能反：先把「公司档案」保护起来，才不会在跑「档案→文件」时被顺手改掉。
    """
    safe = {}
    for i, ph in enumerate(VOCAB_KEEP):
        if ph in t:
            tok = f"\x00{i}\x00"
            safe[tok] = ph
            t = t.replace(ph, tok)
    for a, b in VOCAB_SORTED:
        t = re.sub(a, b, t)      # re.sub：键可以带 (?!…) 之类的断言
    for tok, ph in safe.items():
        t = t.replace(tok, ph)
    return t


def apply_font_keep(t, fn):
    """字体层专名护栏：先给专名上哨兵 → 跑引擎 → 还原。

    为什么必须有：`engine()` 在 opencc 缺席时退回**字级**表，字级表逐字查表，
    不知道「哪吒」是一个词 —— 它只会看见「吒」这个字，然后换成「咤」。
    结果是**通顺的中文里出现一个错字**，比繁体本身更坏（繁体一眼看得出，
    错字要看很久），而且它会随转换器一起流进交付稿。

    哨兵用 `\\x01` 与控制字符区间，与 `apply_vocab` 用的 `\\x00` 区分开 ——
    两层护栏在同一份文本上先后生效，不共用编号免得还原时互相顶掉。
    """
    safe = {}
    for i, ph in enumerate(FONT_KEEP):
        if ph in t:
            tok = f"\x01{i}\x01"
            safe[tok] = ph
            t = t.replace(ph, tok)
    t = fn(t)
    for tok, ph in safe.items():
        t = t.replace(tok, ph)
    return t


def non_idempotent_keys():
    """合成探针：找出「替换结果仍能被自己再匹配」的键。

    2026-09-18 实测踩到的第一类非幂等：`厄瓜多` → `厄瓜多尔`，结果里**还含** `厄瓜多`，
    于是每跑一遍就多一个「尔」（`厄瓜多尔粉钻`）。**只跑一遍看不出来。**
    第二类（撞上更大的词，如「产品品质」→「产品质量」）合成探针抓不到 ——
    那一类由 `main()` 里对真实文本的 `apply_vocab(s) == s` 复查兜底。
    """
    bad = []
    for a, b in VOCAB:
        probe = apply_vocab(a)
        if apply_vocab(probe) != probe:
            bad.append((a, b))
    return bad


def convert_text(t, fn, use_vocab=True):
    """逐行转，但**保持词组级精度**：先整段转，再把带护栏标记的行原样还原。

    为什么不逐行喂给 opencc：它是词组级的，拆成一行一行会丢掉跨行的词组上下文。
    护栏（`# lang-keep-trad`）对**两层都生效** —— 字体层与词汇层都不许碰那几行。
    """
    lines = t.split("\n")
    keep = {i for i, ln in enumerate(lines) if KEEP_RE.search(ln)}
    conv = apply_font_keep(t, fn).split("\n")
    if len(conv) != len(lines):
        # 换行数变了（不该发生）→ 退回逐行，安全优先
        conv = [apply_font_keep(ln, fn) for ln in lines]
    for i in range(len(conv)):
        if i in keep:
            conv[i] = lines[i]
        elif use_vocab:
            conv[i] = apply_vocab(conv[i])
    return "\n".join(conv)


def main():
    ap = argparse.ArgumentParser(description="全仓语言统一（繁→简；含港台用词→内地说法）")
    ap.add_argument("--fix", action="store_true", help="就地转换")
    ap.add_argument("--dry-run", action="store_true", help="与 --fix 并用：只列出不动手")
    ap.add_argument("--strict", action="store_true", help="还有残留就 exit 1")
    ap.add_argument("--json", action="store_true",
                    help="机器可读摘要（给 verify_all 用 —— 解析输出文案太脆，文案一改就断）")
    ap.add_argument("--only", action="append", default=[], metavar="相對路徑",
                    help="只处理指定档（可重复）—— 给生成器/单档维护用")
    ap.add_argument("--no-vocab", action="store_true",
                    help="只做字体层，不动词汇层（词汇表是人工审定的，见 VOCAB 注释）")
    a = ap.parse_args()

    ONLY[:] = a.only

    fn, eng = engine()
    use_vocab = not a.no_vocab

    changed, skipped_keep = [], 0
    vocab_hits = collections.Counter()
    f_total = v_total = 0
    for rel in targets():
        p = os.path.join(ROOT, rel)
        try:
            t = open(p, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError) as e:
            print(f"  ⚠️  读不到 {rel}：{e}")
            continue
        skipped_keep += sum(1 for ln in t.split("\n") if KEEP_RE.search(ln))
        font = convert_text(t, fn, use_vocab=False)
        s = convert_text(t, fn, use_vocab=use_vocab)
        # ── 计数必须**分层**，不能用「逐位比较整份文件」──
        # 2026-09-18 踩过：替换会改变**长度**（4 字的「渠道通路」→ 2 字），
        # 一旦长度变了，后面所有位置全部错位 → 逐位比较会把整份文件都算成「改了」，
        # 实测报出「108 档 / 133 万字」这种荒谬数字（真实改动只有两千处）。
        # 字体层：t2s 基本 1:1，位数相同才逐位比；不同就退回「按字符集差」估。
        f_n = (sum(1 for x, y in zip(t, font) if x != y)
               if len(t) == len(font) else abs(len(t) - len(font)))
        v_n = 0
        if use_vocab and s != font:
            for k, _v in VOCAB_SORTED:
                d = font.count(k) - s.count(k)
                if d > 0:
                    vocab_hits[k] += d
                    v_n += d
        f_total += f_n
        v_total += v_n
        if s != t:
            changed.append((f_n, v_n, rel, p, s))

    print("=" * 72)
    print("全仓语言统一 · lang_unify.py")
    print(f"引擎：{eng}")
    print(f"略过整档：{'、'.join(sorted(EXCLUDE_FILES))}（T2S_PAIRS 是资料，见档头）")
    # ⚠️ 这行**不能**把标记完整拼出来（井号 + 空格 + lang-keep-trad），
    #    否则 KEEP_RE 会命中它自己 → 这行永远不会被转换（自我豁免，实测踩过）。
    print(f"护栏标记：行尾注释 lang-keep-trad（{skipped_keep} 行受保护）")
    print(f"词汇层：{'开（%d 对，人工审定）' % len(VOCAB) if use_vocab else '关（--no-vocab）'}")
    print("=" * 72)

    if not changed:
        if a.json:
            print(json.dumps({"changed": 0, "font": 0, "vocab": 0, "files": []}, ensure_ascii=False))
        else:
            print("\n✅ 全仓已是「简体内地用词」—— 没有需要转换的档。")
        sys.exit(0)

    print(f"\n需转换：{len(changed)} 个文件 ｜ 字体层 {f_total:,} 处 ＋ 词汇层 {v_total:,} 处\n")
    print(f"{'字体':>7} {'词汇':>6}  档")
    for f_n, v_n, rel, _p, _s in sorted(changed, key=lambda c: -(c[0] + c[1])):
        print(f"{f_n:>7} {v_n:>6}  {rel}")

    if vocab_hits:
        print(f"\n词汇层明细（共 {sum(vocab_hits.values()):,} 处）：")
        vmap = dict(VOCAB)
        for k, n in vocab_hits.most_common():
            print(f"  {n:>6}×  {k} → {vmap[k]}")

    if a.json:
        print(json.dumps({"changed": len(changed), "font": f_total, "vocab": v_total,
                          "files": [rel for _f, _v, rel, _p, _s in changed]}, ensure_ascii=False))

    # ── 坏词嗅探（**拦在写入之前**）──────────────────────────────────────
    # 扫「改完之后的样子」，而不是现场文件 —— 这样 --dry-run 也能提前抓到。
    art = []
    for _f, _v, rel, _p, s in changed:
        # 逐行扫，**跳过护栏行** —— 护栏行是「判据／举例」，里面本来就写着坏词
        # （如变更记录举例「产品品质 → 产质量量」）。不跳的话，
        # 谁的举例谁就被自己的坏词关拦下。
        for ln in s.split("\n"):
            if KEEP_RE.search(ln):
                continue
            for pat in BAD_ARTIFACTS:
                for m in re.finditer(pat, ln):
                    art.append((rel, m.group(0)))
    if art:
        print("\n❌ 替换撞车：改完之后会出现这些**坏词** —— 拒绝写入。")
        for rel, w in art[:12]:
            print(f"   · {rel}：`{w}`")
        print("   处置：给相关键加断言（如 `个档(?!案)`），修好后把坏词加进 BAD_ARTIFACTS。")
        sys.exit(2)

    # ── 幂等复查（**拦在写入之前**）────────────────────────────────────
    # 非幂等的替换会把正文改烂，而且**只跑一遍时看着全对** —— 必须在这里拦住。
    nidem = non_idempotent_keys()
    bad_files = [rel for _f, _v, rel, p, s in changed if use_vocab and apply_vocab(s) != s]
    if nidem or bad_files:
        print("\n❌ 词汇表**不是幂等的** —— 拒绝写入（跑了会把正文改烂）。")
        for a, b in nidem:
            print(f"   · 自我触发：`{a}` → `{b}`，而结果里仍能匹配到 `{a}` → 每跑一遍多改一次")
        if bad_files:
            print(f"   · 撞上更大的词：{len(bad_files)} 个文件再跑一遍还会变，如 {bad_files[0]}")
        print("   处置：给键加断言（如 `品质(?!量)`），或把例外短语加进 VOCAB_KEEP。")
        sys.exit(2)

    if a.fix:
        if a.dry_run:
            print(f"\n（--dry-run）以上 {len(changed)} 个档**未改动**。")
        else:
            for _f, _v, rel, p, s in changed:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(s)
            print(f"\n✅ 已转换 {len(changed)} 个档。")
            print("   下一步（**顺序重要**）：① 重生成生成物：build_paradigm --doc-map／"
                  "case_play_index --fix"
                  "\n                      ② 回归：smoke_test ＋ kb_audit ＋ verify_all（按需 -n）")
    else:
        print("\n（以上为报告；要真的转换请加 --fix）")

    sys.exit(1 if a.strict else 0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️  已中断。", file=sys.stderr)
        sys.exit(130)
    except Exception as e:                                    # noqa: BLE001
        print(f"❌ lang_unify 出错：{type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(2)
