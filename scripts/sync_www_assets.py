"""将 assets/ 下的站点图标与轨道图部署到 www/（构建后或单独运行）。"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE_ICONS = ROOT / "assets" / "site-icons"
FIREFLY_WEBP = ROOT / "assets" / "firefly" / "webp"
ORBIT_WEBP = ROOT / "assets" / "orbit" / "webp"
WWW = ROOT / "www"


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


def _deploy_orbit_webp() -> None:
    if not ORBIT_WEBP.is_dir():
        return
    webps = sorted(ORBIT_WEBP.glob("orbit-*.webp"))
    if not webps:
        return
    dest = WWW / "orbit"
    dest.mkdir(parents=True, exist_ok=True)
    for old in dest.glob("orbit-*.png"):
        old.unlink(missing_ok=True)
    for src in webps:
        shutil.copy2(src, dest / src.name)
    print(f"www/orbit/ <- {len(webps)} 张 WebP（assets/orbit/webp）")


def _deploy_firefly_webp() -> None:
    if not FIREFLY_WEBP.is_dir():
        return
    webps = sorted(FIREFLY_WEBP.glob("firefly-*.webp"))
    if not webps:
        return
    dest = WWW / "firefly"
    dest.mkdir(parents=True, exist_ok=True)
    for src in webps:
        shutil.copy2(src, dest / src.name)
    print(f"www/firefly/ <- {len(webps)} 张 WebP（assets/firefly/webp）")


def main() -> None:
    _deploy_site_icons()
    _deploy_orbit_webp()
    _deploy_firefly_webp()
    print(f"已部署到 {WWW}")


if __name__ == "__main__":
    main()
