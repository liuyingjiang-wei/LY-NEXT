"""将 assets/ 下的站点图标与轨道图部署到 www/（构建后或单独运行）。"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE_ICONS = ROOT / "assets" / "site-icons"
ORBIT_SRC = ROOT / "assets" / "orbit"
WWW = ROOT / "www"
ORBIT_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
ORBIT_SIZE = 512


def _deploy_site_icons() -> None:
    try:
        from PIL import Image
    except ImportError as e:
        raise SystemExit("需要 Pillow: uv run --with pillow python scripts/sync_www_assets.py") from e

    WWW.mkdir(parents=True, exist_ok=True)
    brand_dir = WWW / "brand"
    brand_dir.mkdir(parents=True, exist_ok=True)

    shoulan = SITE_ICONS / "shoulan.png"
    tubiao = SITE_ICONS / "tubiao.jpg"

    if not shoulan.is_file():
        raise SystemExit(f"缺少站点图标源文件: {shoulan}")
    if not tubiao.is_file():
        raise SystemExit(f"缺少站点图标源文件: {tubiao}")

    img = Image.open(shoulan).convert("RGBA")
    w, h = img.size
    side = min(w, h)
    left, top = (w - side) // 2, (h - side) // 2
    img = img.crop((left, top, left + side, top + side))
    for size, name in [(32, "favicon.png"), (192, "apple-touch-icon.png")]:
        img.resize((size, size), Image.Resampling.LANCZOS).save(WWW / name, optimize=True)
    print(f"www/favicon.png, www/apple-touch-icon.png <- {shoulan.name}")

    shutil.copy2(tubiao, brand_dir / "tubiao.jpg")
    print(f"www/brand/tubiao.jpg <- {tubiao.name}")


def _deploy_orbit_images() -> None:
    external = os.environ.get("LY_NEXT_AVATAR_DIR")
    src_dir = Path(external) if external else ORBIT_SRC
    if not src_dir.is_dir():
        print(f"跳过轨道图: 目录不存在 {src_dir}")
        return

    try:
        from PIL import Image
    except ImportError as e:
        raise SystemExit("需要 Pillow: uv run --with pillow python scripts/sync_www_assets.py") from e

    sources = sorted(
        (p for p in src_dir.iterdir() if p.is_file() and p.suffix.lower() in ORBIT_EXTS),
        key=lambda p: p.name.lower(),
    )
    # 排除站点图标源文件
    skip = {"shoulan.png", "tubiao.jpg"}
    sources = [p for p in sources if p.name.lower() not in skip]
    if not sources:
        print(f"跳过轨道图: {src_dir} 无可用图片")
        return

    orbit_dir = WWW / "orbit"
    orbit_dir.mkdir(parents=True, exist_ok=True)
    if len(sources) < 6:
        print(f"警告: 仅 {len(sources)} 张轨道图源，将循环使用至 6 张")

    for i in range(6):
        src = sources[i % len(sources)]
        img = Image.open(src).convert("RGB")
        w, h = img.size
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        img = img.crop((left, top, left + side, top + side))
        img = img.resize((ORBIT_SIZE, ORBIT_SIZE), Image.Resampling.LANCZOS)
        out = orbit_dir / f"orbit-{i + 1}.png"
        img.save(out, format="PNG", optimize=True)
        print(f"{out.relative_to(ROOT)} <- {src.name}")


def main() -> None:
    _deploy_site_icons()
    _deploy_orbit_images()
    print(f"已部署到 {WWW}")


if __name__ == "__main__":
    main()
