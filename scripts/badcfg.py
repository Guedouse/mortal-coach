# -*- coding: utf-8 -*-
"""恶手入库门槛（权重差）：一处读取，脚本与页面共用一个来源。

优先级：
  1. 环境变量 MC_BAD_THRESH（桌面版启动子进程时会传，避免配置路径不一致）；
  2. 配置文件里的 `bad.thresh` —— 位置由 paths.config_read_paths() 决定
     （程序目录优先，其次按实例的用户目录），**不再读 %APPDATA% 的全局旧配置**；
  3. 缺省 0.10。

页面上的「门槛」是同一个数（assets/kd/badlevel.js 的 DEFAULTS.thresh）。
改门槛只影响**以后重跑**的提取：already-extracted 的 bad_moves.json 不会自己变，
所以设置里改完要跑一次「一键重建解读.bat」。
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths as P

DEFAULT_THRESH = 0.10


def app_root():
    return P.app_root()


def candidate_configs():
    """配置文件的读取顺序，和界面共用同一套（paths.config_read_paths）。"""
    for p in P.config_read_paths():
        yield p


def _clamp(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if v != v:                      # NaN
        return None
    return max(0.0, min(1.0, v))


def entry_thresh():
    """返回 0~1 的门槛。读不到就退回默认值，绝不抛异常（流水线不能因配置坏掉而停）。"""
    v = _clamp(os.environ.get("MC_BAD_THRESH"))
    if v is not None:
        return v
    for p in candidate_configs():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        bad = d.get("bad") if isinstance(d, dict) else None
        if not isinstance(bad, dict):
            continue
        v = _clamp(bad.get("thresh"))
        if v is None:               # 旧配置：三档版的 gap.medium 就是门槛
            gap = bad.get("gap")
            if isinstance(gap, dict):
                v = _clamp(gap.get("medium"))
        if v is not None:
            return v
    return DEFAULT_THRESH


if __name__ == "__main__":
    print(f"门槛 = {entry_thresh():.2f}（{entry_thresh() * 100:.0f}pt）")
