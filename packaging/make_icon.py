"""Generate the Focus Forge app icon (assets/icon.ico + icon.png).

Drawn programmatically in the app's own visual language — the corner-bracket
focus frame with a mini prerequisite tree inside, in the theme palette — so
the icon is reproducible and stays in sync with a palette change. Rerun after
editing:  python packaging/make_icon.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ui import theme as T  # noqa: E402 — palette single source of truth

SIZES = [16, 24, 32, 48, 64, 128, 256]
S = 256  # master canvas, downscaled per size


def _draw(canvas_px: int) -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    bg = T.BG_ELEVATED
    accent = T.ACCENT
    bracket = T.FOCUS_BRACKET

    # Rounded dark plate
    d.rounded_rectangle([8, 8, S - 8, S - 8], radius=44, fill=bg)

    # Corner brackets — the focus-node signature. Inset from the plate edge.
    bw = 14          # stroke width
    arm = 52         # arm length
    m = 30           # inset
    for cx, cy, sx, sy in ((m, m, 1, 1), (S - m, m, -1, 1),
                           (m, S - m, 1, -1), (S - m, S - m, -1, -1)):
        d.line([(cx, cy + sy * bw // 2), (cx + sx * arm, cy + sy * bw // 2)],
               fill=bracket, width=bw)
        d.line([(cx + sx * bw // 2, cy), (cx + sx * bw // 2, cy + sy * arm)],
               fill=bracket, width=bw)

    # Mini focus tree: one parent node, orthogonal split to two children.
    lw = 12
    r = 21
    top = (S // 2, 92)
    kids = ((92, 178), (S - 92, 178))
    mid_y = (top[1] + kids[0][1]) // 2
    line = accent
    d.line([top, (top[0], mid_y)], fill=line, width=lw)
    d.line([(kids[0][0], mid_y), (kids[1][0], mid_y)], fill=line, width=lw)
    for kx, ky in kids:
        d.line([(kx, mid_y), (kx, ky)], fill=line, width=lw)

    def node(x, y, filled):
        box = [x - r, y - r, x + r, y + r]
        if filled:
            d.rectangle(box, fill=accent)
        else:
            d.rectangle(box, fill=bg, outline=accent, width=10)

    node(*top, True)
    for kx, ky in kids:
        node(kx, ky, False)

    return img.resize((canvas_px, canvas_px), Image.LANCZOS) if canvas_px != S else img


def main() -> None:
    out_dir = ROOT / "assets"
    out_dir.mkdir(exist_ok=True)
    master = _draw(S)
    master.save(out_dir / "icon.png")
    master.save(out_dir / "icon.ico",
                sizes=[(s, s) for s in SIZES])
    print(f"wrote {out_dir / 'icon.png'} and {out_dir / 'icon.ico'} ({SIZES})")


if __name__ == "__main__":
    main()
