# -*- coding: utf-8 -*-
"""统计 assets/kd 下各个前端文件对上游 killer_mortal_gui(9f85c6b) 的继承比例。

用行内容比对（去空行、去首尾空白、忽略顺序），只作声明文案的依据。
"""
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
# /tmp 在 Windows 的 Git Bash 里是 %TEMP%，Python 要的是真实盘符路径
UP = Path(os.environ.get("TEMP") or "/tmp")
PAIRS = [
    (UP / "up_index.js", "assets/kd/index.js"),
    (UP / "up_index.html", "assets/kd/index.html"),
    (UP / "up_style.css", "assets/kd/style.css"),
    (UP / "up_translations.js", "assets/kd/translations.js"),
]


def norm(p):
    t = Path(p).read_bytes().decode("utf-8", "replace").replace("\r\n", "\n")
    return [l.strip() for l in t.split("\n") if l.strip()]


for up, ours in PAIRS:
    if not up.exists():
        print(f"跳过 {ours}：没找到上游文件 {up}（先按 THIRD_PARTY_NOTICES 第 3.1 节把它放到 %TEMP%）")
        continue
    u, o = norm(up), norm(BASE / ours)
    keep = sum(1 for l in u if l in set(o))
    name = ours.split("/")[-1]
    print("%-16s 上游非空 %5d  原样保留 %5d  本项目非空 %5d  新增约 %5d"
          % (name, len(u), keep, len(o), len(o) - keep))
