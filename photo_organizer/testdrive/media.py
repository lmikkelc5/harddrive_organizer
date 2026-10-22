"""Write test media: images with chosen EXIF (Pillow) and tiny QuickTime/MP4 files.

Shared by the test-drive generator and the pytest suite.
"""

from __future__ import annotations

import struct
from datetime import datetime, timezone

from PIL import Image, ImageDraw, ImageFont


def heif_available() -> bool:
    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
        return True
    except Exception:
        return False


def build_exif(dto: str | None = None, *, offset: str | None = None, dtd: str | None = None,
               dt: str | None = None, make: str | None = None, model: str | None = None,
               software: str | None = None, gps: tuple[float, float] | None = None,
               description: str | None = None) -> Image.Exif:
    """Dates like '2026:07:14 15:30:22'; gps as (lat, lon) in degrees."""
    exif = Image.Exif()
    if description:
        exif[270] = description
    if make:
        exif[271] = make
    if model:
        exif[272] = model
    if software:
        exif[305] = software
    if dt:
        exif[306] = dt
    sub = exif.get_ifd(0x8769)
    if dto:
        sub[36867] = dto
    if dtd:
        sub[36868] = dtd
    if offset:
        sub[36881] = offset
    if gps:
        lat, lon = gps

        def dms(v: float):
            v = abs(v)
            d = int(v)
            m = int((v - d) * 60)
            s = round(((v - d) * 60 - m) * 60, 4)
            return (float(d), float(m), float(s))

        g = exif.get_ifd(0x8825)
        g[1] = "N" if lat >= 0 else "S"
        g[2] = dms(lat)
        g[3] = "E" if lon >= 0 else "W"
        g[4] = dms(lon)
    return exif


FORMATS = {".png": "PNG", ".heic": "HEIF", ".heif": "HEIF", ".tif": "TIFF", ".tiff": "TIFF",
           ".webp": "WEBP", ".gif": "GIF"}


def save_image(path: str, img: Image.Image, exif: Image.Exif) -> None:
    ext = "." + path.rsplit(".", 1)[-1].lower()
    fmt = FORMATS.get(ext, "JPEG")
    if fmt == "HEIF":
        heif_available()
    img.save(path, format=fmt, exif=exif.tobytes())


def story_image(lines: list[str], background: tuple[int, int, int], size=(640, 480)) -> Image.Image:
    """A picture that says what it is and where it should end up."""
    img = Image.new("RGB", size, background)
    draw = ImageDraw.Draw(img)
    try:
        big = ImageFont.load_default(size=34)
        small = ImageFont.load_default(size=22)
    except TypeError:  # very old Pillow without FreeType sizes
        big = small = ImageFont.load_default()
    y = 30
    for i, line in enumerate(lines):
        font = big if i == 0 else small
        draw.text((30, y), line, fill=(255, 255, 255), font=font, stroke_width=2, stroke_fill=(0, 0, 0))
        y += 50 if i == 0 else 34
    return img


# ---------------------------------------------------------------------------
# Video
# ---------------------------------------------------------------------------

_QT_EPOCH = datetime(1904, 1, 1, tzinfo=timezone.utc)


def _atom(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


def video_bytes(apple_date: str | None = None, utc: datetime | None = None,
                model: str | None = None, unique: bytes = b"", brand: bytes = b"qt  ") -> bytes:
    """A minimal (not playable) QuickTime/MP4 file with:
    - mvhd creation_time (UTC, what ffmpeg writes as creation_time), and/or
    - Apple's com.apple.quicktime.creationdate (local time with offset).
    """
    secs = int((utc - _QT_EPOCH).total_seconds()) if utc else 0
    moov = _atom(b"mvhd", bytes(4) + struct.pack(">II", secs, secs) + bytes(88))
    entries = []
    if apple_date:
        entries.append(("com.apple.quicktime.creationdate", apple_date))
    if model:
        entries.append(("com.apple.quicktime.model", model))
    if entries:
        keys = bytes(4) + struct.pack(">I", len(entries))
        ilst = b""
        for i, (k, v) in enumerate(entries, start=1):
            kb = k.encode()
            keys += struct.pack(">I4s", 8 + len(kb), b"mdta") + kb
            data = _atom(b"data", struct.pack(">II", 1, 0) + v.encode())
            ilst += struct.pack(">I", 8 + len(data)) + struct.pack(">I", i) + data
        hdlr = _atom(b"hdlr", bytes(8) + b"mdta" + bytes(12) + b"\x00")
        moov += _atom(b"meta", hdlr + _atom(b"keys", keys) + _atom(b"ilst", ilst))
    return (_atom(b"ftyp", brand + bytes(4) + brand) + _atom(b"moov", moov)
            + _atom(b"mdat", unique or b"\x00"))
