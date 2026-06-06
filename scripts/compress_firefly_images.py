"""从 assets/firefly/source 生成 WebP，写入 assets/firefly/webp 与 www/firefly。"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "assets" / "firefly" / "source"
WEBP_DIR = ROOT / "assets" / "firefly" / "webp"
WWW_DIR = ROOT / "www" / "firefly"
DEV_PUBLIC_DIR = ROOT / ".workbench-src" / "public" / "firefly"
INTRO_DIR = ROOT.parent / "介绍"

SLOTS = (
    {"id": "01", "source": "天台.jpg", "variant": "wide", "max_w": 1600, "aspect": (21, 9)},
    {
        "id": "02",
        "source": "萨姆.jpg",
        "variant": "portrait",
        "max_h": 1200,
        "aspect": (3, 4),
        "focus": (0.5, 0.42),
    },
    {"id": "03", "source": "失shang.webp", "variant": "standard", "max_w": 1400, "aspect": (16, 9)},
    {"id": "04", "source": "全景.webp", "variant": "wide", "max_w": 1600, "aspect": (21, 9)},
    {
        "id": "05",
        "source": "星核.jpg",
        "variant": "portrait",
        "max_h": 1200,
        "aspect": (3, 4),
        "focus": (0.5, 0.38),
    },
    {"id": "06", "source": "羁绊.jpg", "variant": "standard", "max_w": 1400, "aspect": (16, 9)},
    {"id": "07", "source": "少女.jpg", "variant": "wide", "max_w": 1600, "aspect": (21, 9)},
)


def _crop_aspect(
    img: Image.Image, aspect: tuple[int, int], focus: tuple[float, float]
) -> Image.Image:
    aw, ah = aspect
    target_ratio = aw / ah
    w, h = img.size
    current = w / h
    if current > target_ratio:
        new_w = int(h * target_ratio)
        fx, _ = focus
        left = max(0, min(w - new_w, int((w - new_w) * fx)))
        img = img.crop((left, 0, left + new_w, h))
    else:
        new_h = int(w / target_ratio)
        _, fy = focus
        top = max(0, min(h - new_h, int((h - new_h) * fy)))
        img = img.crop((0, top, w, top + new_h))
    return img


def _resize(img: Image.Image, slot: dict) -> Image.Image:
    img = ImageOps.exif_transpose(img).convert("RGB")
    img = _crop_aspect(img, slot["aspect"], slot.get("focus", (0.5, 0.5)))

    if "max_w" in slot:
        w, h = img.size
        if w > slot["max_w"]:
            nh = int(h * slot["max_w"] / w)
            img = img.resize((slot["max_w"], nh), Image.Resampling.LANCZOS)
    if "max_h" in slot:
        w, h = img.size
        if h > slot["max_h"]:
            nw = int(w * slot["max_h"] / h)
            img = img.resize((nw, slot["max_h"]), Image.Resampling.LANCZOS)
    return img


def _save_webp(img: Image.Image, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, format="WEBP", quality=82, method=6)


def _bootstrap_source_from_intro() -> None:
    if not INTRO_DIR.is_dir() or any(SRC_DIR.glob("*")):
        return
    SRC_DIR.mkdir(parents=True, exist_ok=True)
    for slot in SLOTS:
        src = INTRO_DIR / slot["source"]
        if src.is_file():
            shutil.copy2(src, SRC_DIR / slot["source"])


def _deploy_webp_dir(webp_dir: Path, *targets: Path) -> int:
    if not webp_dir.is_dir():
        return 0
    total = 0
    for slot in SLOTS:
        name = f"firefly-{slot['id']}.webp"
        src = webp_dir / name
        if not src.is_file():
            continue
        for target in targets:
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target / name)
        total += src.stat().st_size
    return total


def main() -> None:
    _bootstrap_source_from_intro()

    missing = [s["source"] for s in SLOTS if not (SRC_DIR / s["source"]).is_file()]
    deploy_targets = [WEBP_DIR, WWW_DIR]
    if DEV_PUBLIC_DIR.parent.parent.is_dir():
        deploy_targets.append(DEV_PUBLIC_DIR)

    if missing:
        copied = _deploy_webp_dir(
            WEBP_DIR, WWW_DIR, *([DEV_PUBLIC_DIR] if DEV_PUBLIC_DIR.parent.parent.is_dir() else [])
        )
        if copied and all((WEBP_DIR / f"firefly-{s['id']}.webp").is_file() for s in SLOTS):
            print(
                f"缺少源图 {missing}，已从 assets/firefly/webp 同步到 www（约 {copied // 1024}KB）"
            )
            return
        raise SystemExit(
            f"缺少源图: {missing}\n"
            f"请将原图放入 {SRC_DIR}，或提交 assets/firefly/webp/*.webp 后拉取仓库。"
        )

    WEBP_DIR.mkdir(parents=True, exist_ok=True)
    WWW_DIR.mkdir(parents=True, exist_ok=True)

    total = 0
    for slot in SLOTS:
        img = _resize(Image.open(SRC_DIR / slot["source"]), slot)
        name = f"firefly-{slot['id']}.webp"
        _save_webp(img, WEBP_DIR / name)
        for target in deploy_targets:
            _save_webp(img, target / name)
        size = (WEBP_DIR / name).stat().st_size
        total += size
        print(f"{name} <- {slot['source']} ({img.size[0]}x{img.size[1]}, {size // 1024}KB)")

    print(
        f"firefly 插图已生成，合计约 {total // 1024}KB（请一并提交 assets/firefly/webp 与 www/firefly）"
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
