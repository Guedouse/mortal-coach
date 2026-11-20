# -*- coding: utf-8 -*-
"""在桌面生成 mortal-coach 快捷方式（带图标）。不依赖 COM。"""
import os
from pathlib import Path

import pylnk3

EXE = Path(__file__).resolve().parent.parent / "mortal-coach.exe"


def desktop_dir():
    for c in (Path.home() / "Desktop", Path.home() / "OneDrive" / "Desktop"):
        if c.exists():
            return c
    return Path(os.path.expanduser("~"))


def main():
    d = desktop_dir()
    lnk = d / "mortal-coach.lnk"
    pylnk3.for_file(
        str(EXE),
        lnk_name=str(lnk),
        description="mortal-coach · 日麻对局复盘",
        icon_file=str(EXE),
        icon_index=0,
        work_dir=str(EXE.parent),
    )
    print("已创建", lnk, lnk.exists())


if __name__ == "__main__":
    main()
