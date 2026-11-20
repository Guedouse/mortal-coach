# -*- coding: utf-8 -*-
"""生成应用图标：麻将「發」牌（绿字象牙底）。

输出 app/icon.png（512，窗口/关于页用）与 app/icon.ico（多尺寸，PyInstaller 用）。
只用系统字体，缺字体时退化成几何图形，不会抛异常。
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
S = 1024

IVORY_TOP = (250, 247, 236, 255)
IVORY_BOT = (233, 227, 207, 255)
GREEN = (12, 112, 66, 255)
GREEN_DARK = (8, 82, 49, 255)
EDGE = (206, 197, 172, 255)

FONT_CANDIDATES = [
    r"C:/Windows/Fonts/msjhbd.ttc",
    r"C:/Windows/Fonts/msjh.ttc",
    r"C:/Windows/Fonts/msyhbd.ttc",
    r"C:/Windows/Fonts/simhei.ttf",
    r"C:/Windows/Fonts/simsun.ttc",
]


def pick_font(size):
    for f in FONT_CANDIDATES:
        if Path(f).exists():
            try:
                return ImageFont.truetype(f, size)
            except Exception:
                continue
    return None


def vertical_gradient(w, h, top, bot):
    img = Image.new("RGB", (1, h))
    px = img.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3))
    return img.resize((w, h))


def main():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 牌体（留一点外边距，小尺寸下也不会糊在一起）
    pad = int(S * 0.055)
    r = int(S * 0.16)
    box = [pad, pad, S - pad, S - pad]

    # 投影
    sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle(
        [box[0], box[1] + int(S * 0.018), box[2], box[3] + int(S * 0.018)],
        radius=r, fill=(0, 0, 0, 70))
    img.alpha_composite(sh.filter(__import__("PIL.ImageFilter", fromlist=["GaussianBlur"]).GaussianBlur(18)))

    # 象牙底 + 竖向渐变
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=r, fill=255)
    grad = vertical_gradient(S, S, IVORY_TOP, IVORY_BOT).convert("RGBA")
    img.paste(grad, (0, 0), mask)

    # 牌边
    d.rounded_rectangle(box, radius=r, outline=EDGE, width=max(4, int(S * 0.012)))

    # 「發」字：略偏上，给下方留白
    font = pick_font(int(S * 0.54))
    if font:
        ch = "發"
        bb = d.textbbox((0, 0), ch, font=font)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        x = (S - tw) / 2 - bb[0]
        y = int(S * 0.47) - th / 2 - bb[1]
        # 极轻的立体感：先画一层深绿偏移
        d.text((x, y + max(2, int(S * 0.004))), ch, font=font, fill=GREEN_DARK)
        d.text((x, y), ch, font=font, fill=GREEN)
    else:
        cx, cy, h = S // 2, int(S * 0.46), int(S * 0.30)
        d.line([(cx, cy - h), (cx, cy + h)], fill=GREEN, width=int(S * 0.05))
        d.line([(cx - h * 0.6, cy), (cx + h * 0.6, cy)], fill=GREEN, width=int(S * 0.05))

    # 四个角的绿色小方块（麻将牌的角标感）
    cs = int(S * 0.030)
    off = int(S * 0.080)
    for cx in (box[0] + off, box[2] - off):
        for cy in (box[1] + off, box[3] - off):
            d.rounded_rectangle([cx - cs, cy - cs, cx + cs, cy + cs],
                                radius=int(cs * 0.3), fill=GREEN)

    img.save(OUT / "icon.png")
    img.resize((512, 512), Image.LANCZOS).save(OUT / "icon-512.png")
    img.save(OUT / "icon.ico", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print("icon ok")


if __name__ == "__main__":
    main()
