"""WebP 썸네일 400/1600 px 생성 (원본은 그대로 보관)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

from ..config import THUMB_SIZES

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp", ".gif"}


def make_thumbnails(src: Path) -> Path | None:
    """{stem}.w400.webp, {stem}.w1600.webp를 만들고 400px 경로를 반환. 이미지가 아니면 None."""
    if src.suffix.lower() not in IMAGE_EXT:
        return None
    try:
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im)
            if im.mode in ("I;16", "I;16B", "I", "F"):
                im = ImageOps.autocontrast(im.convert("I").point(lambda v: v / 256).convert("L"))
            elif im.mode not in ("RGB", "RGBA", "L"):
                im = im.convert("RGB")
            small = None
            for w in THUMB_SIZES:
                t = im.copy()
                t.thumbnail((w, w * 4))
                out = src.with_name(f"{src.stem}.w{w}.webp")
                t.save(out, "WEBP", quality=82)
                small = small or out
            return small
    except Exception:  # 손상·미지원 형식은 썸네일 없이 원본만 보관
        return None


def large_of(thumb: str | None) -> str | None:
    return thumb.replace(".w400.webp", ".w1600.webp") if thumb else None
