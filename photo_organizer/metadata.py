"""Read dates, GPS and camera info from photos and videos.

Images use Pillow (+ pillow-heif for HEIC). Videos use a tiny MP4/QuickTime
atom reader below, so no extra dependency is needed. Every reader returns an
empty Meta on any problem instead of raising.
"""

from __future__ import annotations

import logging
import os
import re
import struct
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import dates

log = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".gif", ".tif", ".tiff", ".webp", ".dng"}
VIDEO_EXTS = {".mov", ".mp4", ".m4v"}
SIDECAR_EXTS = {".aae"}

_heif_registered = False


def _register_heif() -> None:
    global _heif_registered
    if _heif_registered:
        return
    _heif_registered = True
    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
    except Exception:  # pragma: no cover - only if the package is missing
        log.warning("pillow-heif not available; HEIC metadata will not be read")


def kind_for(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext in IMAGE_EXTS:
        return "photo"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in SIDECAR_EXTS:
        return "sidecar"
    return "other"


@dataclass
class DateCandidate:
    date: dates.FuzzyDate
    source: str          # e.g. "exif-original", "quicktime-creationdate", "filename"
    tz_offset: str | None = None


@dataclass
class Meta:
    candidates: list[DateCandidate] = field(default_factory=list)  # best first
    make: str | None = None
    model: str | None = None
    software: str | None = None
    gps_lat: float | None = None
    gps_lon: float | None = None


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------

_T_DATETIME = 306
_T_MAKE = 271
_T_MODEL = 272
_T_SOFTWARE = 305
_T_DTO = 36867
_T_DTD = 36868
_T_OFFSET = 36880
_T_OFFSET_ORIG = 36881
_T_OFFSET_DIG = 36882
_IFD_EXIF = 0x8769
_IFD_GPS = 0x8825


def _text(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, bytes):
        v = v.decode("utf-8", "ignore")
    v = str(v).replace("\x00", "").strip()
    return v or None


def _gps_coord(value, ref) -> float | None:
    try:
        d, m, s = (float(x) for x in value)
    except Exception:
        return None
    coord = d + m / 60 + s / 3600
    ref = _text(ref) or ""
    if ref.upper() in ("S", "W"):
        coord = -coord
    return round(coord, 7)


def read_image_meta(path: str) -> Meta:
    _register_heif()
    meta = Meta()
    try:
        from PIL import Image

        with Image.open(path) as img:
            exif = img.getexif()
            exif_ifd = exif.get_ifd(_IFD_EXIF)
            gps = exif.get_ifd(_IFD_GPS)
    except Exception as e:
        log.info("No readable metadata in %s: %s", path, e)
        return meta

    meta.make = _text(exif.get(_T_MAKE))
    meta.model = _text(exif.get(_T_MODEL))
    meta.software = _text(exif.get(_T_SOFTWARE))

    def offset(tag):
        o = _text(exif_ifd.get(tag)) or _text(exif.get(tag))
        return o if o and re.fullmatch(r"[+-]\d{2}:\d{2}", o) else None

    for tag, src, off_tag in (
        (_T_DTO, "exif-original", _T_OFFSET_ORIG),
        (_T_DTD, "exif-digitized", _T_OFFSET_DIG),
    ):
        d = dates.parse_exif_datetime(_text(exif_ifd.get(tag)))
        if d:
            meta.candidates.append(DateCandidate(d, src, offset(off_tag)))
    d = dates.parse_exif_datetime(_text(exif.get(_T_DATETIME)))
    if d:
        meta.candidates.append(DateCandidate(d, "exif-datetime", offset(_T_OFFSET)))

    if gps:
        meta.gps_lat = _gps_coord(gps.get(2), gps.get(1))
        meta.gps_lon = _gps_coord(gps.get(4), gps.get(3))
    return meta


# ---------------------------------------------------------------------------
# Videos (MP4 / QuickTime atoms)
# ---------------------------------------------------------------------------

_QT_EPOCH = datetime(1904, 1, 1, tzinfo=timezone.utc)
_CONTAINERS = {b"moov", b"udta", b"trak", b"mdia"}


def _atoms(f, start: int, end: int):
    """Yield (type, payload_start, payload_end) for atoms in [start, end)."""
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        header = f.read(8)
        if len(header) < 8:
            return
        size, kind = struct.unpack(">I4s", header)
        hdr = 8
        if size == 1:
            big = f.read(8)
            if len(big) < 8:
                return
            size = struct.unpack(">Q", big)[0]
            hdr = 16
        elif size == 0:
            size = end - pos
        if size < hdr or pos + size > end:
            return
        yield kind, pos + hdr, pos + size
        pos += size


def _read(f, start: int, end: int, limit: int = 1 << 20) -> bytes:
    f.seek(start)
    return f.read(min(end - start, limit))


def _parse_meta_atom(f, start: int, end: int) -> dict[str, object]:
    """QuickTime 'mdta' metadata: keys + ilst -> {key: value}."""
    # In QuickTime files 'meta' has no version/flags; in ISO MP4 it does.
    f.seek(start + 4)
    if f.read(4) not in (b"hdlr", b"keys", b"ilst"):
        start += 4
    keys: list[str] = []
    values: dict[str, object] = {}
    for kind, s, e in _atoms(f, start, end):
        if kind == b"keys":
            data = _read(f, s, e)
            count = struct.unpack(">I", data[4:8])[0]
            p = 8
            for _ in range(count):
                if p + 8 > len(data):
                    break
                ksize = struct.unpack(">I", data[p:p + 4])[0]
                keys.append(data[p + 8:p + ksize].decode("utf-8", "ignore"))
                p += max(ksize, 8)
        elif kind == b"ilst":
            for item, is_, ie in _atoms(f, s, e):
                index = struct.unpack(">I", item)[0]
                for dkind, ds, de in _atoms(f, is_, ie):
                    if dkind == b"data" and 1 <= index <= len(keys):
                        raw = _read(f, ds, de)
                        values[keys[index - 1]] = raw[8:].decode("utf-8", "ignore").strip("\x00")
    return values


def _parse_iso6709(s: str) -> tuple[float, float] | None:
    m = re.match(r"([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)", s)
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))


def read_video_meta(path: str, local_tz=None) -> Meta:
    meta = Meta()
    apple: dict[str, object] = {}
    mvhd_time: datetime | None = None
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            end = f.tell()

            def walk(s: int, e: int, depth: int = 0):
                nonlocal mvhd_time
                for kind, ps, pe in _atoms(f, s, e):
                    if kind == b"mvhd":
                        data = _read(f, ps, pe, 32)
                        version = data[0]
                        secs = struct.unpack(">Q", data[4:12])[0] if version == 1 else struct.unpack(">I", data[4:8])[0]
                        if secs:
                            mvhd_time = _QT_EPOCH + timedelta(seconds=secs)
                    elif kind == b"meta":
                        apple.update(_parse_meta_atom(f, ps, pe))
                    elif kind in _CONTAINERS and depth < 4:
                        walk(ps, pe, depth + 1)

            walk(0, end)
    except Exception as e:
        log.info("Couldn't read video metadata in %s: %s", path, e)
        return meta

    created = apple.get("com.apple.quicktime.creationdate")
    if isinstance(created, str) and (parsed := dates.parse_iso_with_offset(created)):
        meta.candidates.append(DateCandidate(parsed[0], "quicktime-creationdate", parsed[1]))
    if mvhd_time is not None:
        # Generic creation_time is UTC; convert to the Mac's local time.
        local = mvhd_time.astimezone(local_tz) if local_tz else mvhd_time.astimezone()
        off = local.utcoffset()
        tz = None
        if off is not None:
            mins = int(off.total_seconds() // 60)
            tz = f"{'+' if mins >= 0 else '-'}{abs(mins) // 60:02d}:{abs(mins) % 60:02d}"
        meta.candidates.append(
            DateCandidate(dates.FuzzyDate.from_datetime(local.replace(tzinfo=None)), "video-creation-time", tz)
        )
    meta.make = _text(apple.get("com.apple.quicktime.make"))
    meta.model = _text(apple.get("com.apple.quicktime.model"))
    meta.software = _text(apple.get("com.apple.quicktime.software"))
    loc = apple.get("com.apple.quicktime.location.ISO6709")
    if isinstance(loc, str) and (ll := _parse_iso6709(loc)):
        meta.gps_lat, meta.gps_lon = ll
    return meta


def read_meta(path: str, local_tz=None) -> Meta:
    """local_tz: zone for converting UTC video times (None = this computer's zone)."""
    kind = kind_for(path)
    if kind == "photo":
        return read_image_meta(path)
    if kind == "video":
        return read_video_meta(path, local_tz)
    return Meta()
