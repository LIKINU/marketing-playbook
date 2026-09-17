#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分工校驗 · role_check.py  （把「多 Agent 分工每次必走」變成機械檢查）

為什麼有它（2026-09-16）：
    SKILL 要求「多 Agent 分工每次必走、不省略」，但**沒有任何腳本檢查** → 一個人一把寫完也能過。
    規則只寫在文字裡＝模型不會看＝等於沒有。本腳本把它變成可跑的一關。

用法：
    python scripts/role_check.py roles.json
    cat roles.json | python scripts/role_check.py -

roles.json 格式（主理人在分工後填；每角色只填「產出摘要」，不搬全文）：
{
  "client": "客戶名",
  "roles": {
    "策略":   { "產出": "三次收窄 + 打法組合 + 選品定價 + 節奏排期（摘要一句話）" },
    "品牌":   { "產出": "競品 5 環節四段式 + 定位支點 + 禁用詞 5 類" },
    "觸達":   { "產出": "4 渠道 + 用戶路徑 + 觸達硬風險" },
    "文案":   { "產出": "物料 12 件逐件原文 + 一線話術" },
    "財務風控": { "產出": "預算 ≥6 項 + KPI ≥8 含預警線 + 風險 ≥3 四件套" }
  },
  "裁決記錄": "策略 vs 觸達 對渠道數量的衝突：裁決保留 2 個核心渠道（理由：人力 2 人）"
}

退出碼：0 = 通過；1 = 不通過；2 = 腳本出錯
"""

import json
import sys

from _common import OK, NG, WARN, HINT, INFO   # noqa: E402  统一符号，不要在各自文件里重定义
ROLES = ["策略", "品牌", "觸達", "文案", "財務風控"]


def load(path):
    if path == "-":
        return json.load(sys.stdin)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print("用法: python role_check.py <roles.json|->")
        print("  校驗 5 個執行角色是否都留下產出，且有其裁決記錄（SKILL：多 Agent 分工每次必走）")
        sys.exit(0)
    if len(sys.argv) < 2:
        print("用法: python role_check.py <roles.json|->")
        sys.exit(1)

    try:
        data = load(sys.argv[1])
    except Exception as e:
        print(f"{NG} 無法讀取分工記錄：{e}")
        sys.exit(1)

    roles = data.get("roles") or {}
    client = data.get("client", "(未填客戶名)")
    print("=" * 64)
    print(f"分工校驗 · {client}")
    print("=" * 64)

    missing, empty = [], []
    for r in ROLES:
        info = roles.get(r)
        out = (info or {}).get("產出", "") if isinstance(info, dict) else str(info or "")
        if info is None:
            missing.append(r)
            print(f"{NG} {r}：未見產出")
        elif not str(out).strip():
            empty.append(r)
            print(f"{NG} {r}：產出為空")
        else:
            s = str(out).strip().replace("\n", " ")
            print(f"{OK} {r}：{s[:52]}{'…' if len(s) > 52 else ''}")

    extra = [k for k in roles if k not in ROLES]
    if extra:
        print(f"ℹ️  另有未識別角色：{'、'.join(extra)}（可忽略）")

    verdict = data.get("裁決記錄") or data.get("裁决记录")
    if verdict and str(verdict).strip():
        print(f"{OK} 裁決記錄：{str(verdict).strip()[:60]}…")
    else:
        print(f"{NG} 缺「裁決記錄」—— 主理人必須記錄至少一處衝突的裁決理由")

    print("-" * 64)
    if missing or empty or not (verdict and str(verdict).strip()):
        print(f"{NG} 分工不完整：缺 {len(missing)} 個角色、{len(empty)} 個空產出"
              f"{'、缺裁決記錄' if not (verdict and str(verdict).strip()) else ''}")
        print("→ 依 SKILL「多 Agent 分工每次必走」：補齊 5 個角色產出 ＋ 裁決記錄後重跑。")
        sys.exit(1)
    print(f"{OK} 分工通過：5 個角色產出齊全 ＋ 有裁決記錄。")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"{NG} 執行出錯：{type(e).__name__}: {e}")
        sys.exit(2)
