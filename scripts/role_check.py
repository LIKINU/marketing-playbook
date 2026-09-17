#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分工校验 · role_check.py  （把「多 Agent 分工每次必走」变成机械检查）

为什么有它（2026-09-16）：
    SKILL 要求「多 Agent 分工每次必走、不省略」，但**没有任何脚本检查** → 一个人一把写完也能过。
    规则只写在文字里＝模型不会看＝等于没有。本脚本把它变成可跑的一关。

用法：
    python scripts/role_check.py roles.json
    cat roles.json | python scripts/role_check.py -

roles.json 格式（主理人在分工后填；每角色只填「产出摘要」，不搬全文）：
{
  "client": "客户名",
  "roles": {
    "策略":   { "产出": "三次收窄 + 打法组合 + 选品定价 + 节奏排期（摘要一句话）" },
    "品牌":   { "产出": "竞品 5 环节四段式 + 定位支点 + 禁用词 5 类" },
    "触达":   { "产出": "4 渠道 + 用户路径 + 触达硬风险" },
    "文案":   { "产出": "物料 12 件逐件原文 + 一线话术" },
    "财务风控": { "产出": "预算 ≥6 项 + KPI ≥8 含预警线 + 风险 ≥3 四件套" }
  },
  "裁决记录": "策略 vs 触达 对渠道数量的冲突：裁决保留 2 个核心渠道（理由：人力 2 人）"
}

退出码：0 = 通过；1 = 不通过；2 = 脚本出错
"""

import json
import sys

from _common import OK, NG, WARN, HINT, INFO   # noqa: E402  统一符号，不要在各自文件里重定义
ROLES = ["策略", "品牌", "触达", "文案", "财务风控"]


def load(path):
    if path == "-":
        return json.load(sys.stdin)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print("用法: python role_check.py <roles.json|->")
        print("  校验 5 个执行角色是否都留下产出，且有其裁决记录（SKILL：多 Agent 分工每次必走）")
        sys.exit(0)
    if len(sys.argv) < 2:
        print("用法: python role_check.py <roles.json|->")
        sys.exit(1)

    try:
        data = load(sys.argv[1])
    except Exception as e:
        print(f"{NG} 无法读取分工记录：{e}")
        sys.exit(1)

    roles = data.get("roles") or {}
    client = data.get("client", "(未填客户名)")
    print("=" * 64)
    print(f"分工校验 · {client}")
    print("=" * 64)

    missing, empty = [], []
    for r in ROLES:
        info = roles.get(r)
        out = (info or {}).get("产出", "") if isinstance(info, dict) else str(info or "")
        if info is None:
            missing.append(r)
            print(f"{NG} {r}：未见产出")
        elif not str(out).strip():
            empty.append(r)
            print(f"{NG} {r}：产出为空")
        else:
            s = str(out).strip().replace("\n", " ")
            print(f"{OK} {r}：{s[:52]}{'…' if len(s) > 52 else ''}")

    extra = [k for k in roles if k not in ROLES]
    if extra:
        print(f"ℹ️  另有未识别角色：{'、'.join(extra)}（可忽略）")

    verdict = data.get("裁决记录") or data.get("裁决记录")
    if verdict and str(verdict).strip():
        print(f"{OK} 裁决记录：{str(verdict).strip()[:60]}…")
    else:
        print(f"{NG} 缺「裁决记录」—— 主理人必须记录至少一处冲突的裁决理由")

    print("-" * 64)
    if missing or empty or not (verdict and str(verdict).strip()):
        print(f"{NG} 分工不完整：缺 {len(missing)} 个角色、{len(empty)} 个空产出"
              f"{'、缺裁决记录' if not (verdict and str(verdict).strip()) else ''}")
        print("→ 依 SKILL「多 Agent 分工每次必走」：补齐 5 个角色产出 ＋ 裁决记录后重跑。")
        sys.exit(1)
    print(f"{OK} 分工通过：5 个角色产出齐全 ＋ 有裁决记录。")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"{NG} 执行出错：{type(e).__name__}: {e}")
        sys.exit(2)
