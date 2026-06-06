"""从 assets/orbit 源图生成 WebP，写入 assets/orbit/webp 与 www/orbit。"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
ORBIT_SRC = ROOT / "assets" / "orbit"
ORBIT_WEBP_DIR = ROOT / "assets" / "orbit" / "webp"
WWW_ORBIT_DIR = ROOT / "www" / "orbit"
DEV_PUBLIC_DIR = ROOT / ".workbench-src" / "public" / "orbit"

ORBIT_COUNT = 6
ORBIT_SIZE = 384
ORBIT_WEBP_QUALITY = 80
ORBIT_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
SKIP_NAMES = {"shoulan.png", "tubiao.jpg"}


def _list_sources(src_dir: Path) -> list[Path]:
    if not src_dir.is_dir():
        return []
    sources = sorted(
        (p for p in src_dir.iterdir() if p.is_file() and p.suffix.lower() in ORBIT_EXTS),
        key=lambda p: p.name.lower(),
    )
    return [p for p in sources if p.name.lower() not in SKIP_NAMES]


def _process_one(src: Path) -> Image.Image:
    img = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side))
    if img.size[0] != ORBIT_SIZE:
        img = img.resize((ORBIT_SIZE, ORBIT_SIZE), Image.Resampling.LANCZOS)
    return img


def _save_webp(img: Image.Image, dest: Path) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, format="WEBP", quality=ORBIT_WEBP_QUALITY, method=6)
    return dest.stat().st_size


def _remove_legacy_png(dir_path: Path) -> None:
    if not dir_path.is_dir():
        return
    for old in dir_path.glob("orbit-*.png"):
        old.unlink(missing_ok=True)


def _deploy_webp_only(*targets: Path) -> int:
    if not ORBIT_WEBP_DIR.is_dir():
        return 0
    total = 0
    for i in range(1, ORBIT_COUNT + 1):
        src = ORBIT_WEBP_DIR / f"orbit-{i}.webp"
        if not src.is_file():
            return 0
        for target in targets:
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target / src.name)
        total += src.stat().st_size
    return total


def compress_orbit_images() -> int:
    external = os.environ.get("LY_NEXT_AVATAR_DIR")
    src_dir = Path(external) if external else ORBIT_SRC

    sources = _list_sources(src_dir)
    deploy_targets = [ORBIT_WEBP_DIR, WWW_ORBIT_DIR]
    if DEV_PUBLIC_DIR.parent.parent.is_dir():
        deploy_targets.append(DEV_PUBLIC_DIR)

    if not sources:
        copied = _deploy_webp_only(
            WWW_ORBIT_DIR, *([DEV_PUBLIC_DIR] if DEV_PUBLIC_DIR.parent.parent.is_dir() else [])
        )
        if copied and all(
            (ORBIT_WEBP_DIR / f"orbit-{i}.webp").is_file() for i in range(1, ORBIT_COUNT + 1)
        ):
            print(f"缺少轨道图源，已从 assets/orbit/webp 同步到 www（约 {copied // 1024}KB）")
            return copied
        if not ORBIT_SRC.is_dir():
            print(f"跳过轨道图: 目录不存在 {src_dir}")
            return 0
        raise SystemExit(
            f"轨道图源目录无可用图片: {src_dir}\n"
            f"请放入 {ORBIT_SRC} 或提交 assets/orbit/webp/orbit-*.webp"
        )

    if len(sources) < ORBIT_COUNT:
        print(f"警告: 仅 {len(sources)} 张轨道图源，将循环使用至 {ORBIT_COUNT} 张")

    total = 0
    for i in range(ORBIT_COUNT):
        src = sources[i % len(sources)]
        img = _process_one(src)
        name = f"orbit-{i + 1}.webp"
        for target in deploy_targets:
            total += _save_webp(img, target / name)
        size = (ORBIT_WEBP_DIR / name).stat().st_size
        print(f"{name} <- {src.name} ({ORBIT_SIZE}x{ORBIT_SIZE}, {size // 1024}KB)")

    for target in deploy_targets:
        _remove_legacy_png(target)

    print(
        f"轨道图已生成 WebP，单套约 {total // ORBIT_COUNT // 1024}KB x {ORBIT_COUNT}（请提交 assets/orbit/webp）"
    )
    return total


def main() -> None:
    try:
        compress_orbit_images()
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
