"""What a folder name in the inbox means: a label, a date, an album, or nothing."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from . import dates, names

# Group word, then the first dash (any kind) or colon, then the rest.
# The group word must be letters only, so "2009-06" is not a group.
_LABEL_RE = re.compile(r"^\s*([^\W\d_]+)\s*[-–—:]\s*(.+?)\s*$")


@dataclass(frozen=True)
class Label:
    group: str  # always "Event" for now
    name: str   # as typed, whitespace tidied, e.g. "Hawaii 2026"

    @property
    def key(self) -> tuple[str, str]:
        return (self.group.lower(), self.name.casefold())


def normalize_group(word: str) -> str:
    w = word.strip().lower()
    # Trips -> Trip, Events -> Event, but Christmas stays Christmas.
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "as", "is", "us", "os")):
        w = w[:-1]
    return w.capitalize()


def _tidy(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class FolderMeaning:
    kind: str  # "label", "date", "bad-date", "plain"
    label: Label | None = None
    date: dates.FuzzyDate | None = None


def parse_folder_name(name: str, now: datetime | None = None) -> FolderMeaning:
    m = _LABEL_RE.match(name)
    if not m:
        return FolderMeaning("plain")
    group = normalize_group(m.group(1))
    rest = _tidy(m.group(2))
    if group == names.DATE_GROUP:
        d = dates.parse_date_text(rest, now)
        return FolderMeaning("date", date=d) if d else FolderMeaning("bad-date")
    # Only events make views. Any other group word (or a typo of EVENT) is
    # treated as an event too, so a folder she names is never silently ignored.
    return FolderMeaning("label", label=Label(names.EVENT_GROUP, rest))


@dataclass
class FolderContext:
    """Everything the inbox folder path says about the files inside it."""

    labels: list[Label] = field(default_factory=list)
    date: dates.FuzzyDate | None = None          # from the deepest DATE folder
    bad_date_folder: str | None = None           # unreadable DATE folder name
    hint: dates.FuzzyDate | None = None          # folder-name year/month fallback


def folder_context(folder_names: list[str], now: datetime | None = None) -> FolderContext:
    """folder_names: inbox-relative folders, outermost first."""
    ctx = FolderContext()
    for name in folder_names:
        meaning = parse_folder_name(name, now)
        if meaning.kind == "label":
            if meaning.label.key not in {l.key for l in ctx.labels}:
                ctx.labels.append(meaning.label)
        elif meaning.kind == "date":
            ctx.date = meaning.date
            ctx.bad_date_folder = None  # deepest DATE folder wins
        elif meaning.kind == "bad-date":
            ctx.date = None
            ctx.bad_date_folder = name
        # Plain folders (no dash) only give context and date hints.
    hint_names = [n for n in folder_names if parse_folder_name(n, now).kind not in ("date", "bad-date")]
    ctx.hint = dates.path_hint(hint_names, now)
    return ctx
