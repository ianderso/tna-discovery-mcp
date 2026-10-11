"""Turning Discovery's answers into compact, citable tool results.

Discovery's text fields carry fragments of EAD markup (``<scopecontent>``,
``<p>``, ``<unittitle type=&#34Title">``, ``<extref href=...>``), sometimes
with entities missing their semicolons; :func:`clean` makes them plain
text. Every result names the record's public page (``url``) and carries what a
citation needs: the holding archive, the reference, the covering dates.

WO 97, the Royal Hospital Chelsea's soldiers' service documents, describes
each man from 1760 to 1854 in one standard sentence, ``NAME Born PLACE, County
Served in REGIMENT(S) Discharged aged N``; :func:`parse_wo97` takes it apart.
"""

from __future__ import annotations

import html
import re
from typing import Any

#: The public page of a record, which is what a person opens and cites.
RECORD_PAGE = "https://discovery.nationalarchives.gov.uk/details/r/{id}"

#: The catalogue levels of TNA's own records (ISAD(G), as TNA numbers them).
#: Other archives' catalogues number their levels differently.
TNA_LEVELS = {
    1: "department",
    2: "division",
    3: "series",
    4: "sub-series",
    5: "sub-sub-series",
    6: "piece",
    7: "item",
}

#: Discovery's source codes, as its search facets report them.
SOURCES = {
    "100": "TNA catalogue",
    "200": "TNA digitised records",
    "300": "National Register of Archives",
    "600": "another archive's catalogue",
}

#: Closure status codes whose meaning is plain.
CLOSURE = {"O": "open", "C": "closed", "R": "retained by the department"}

#: Characters of a search hit's description kept.
HIT_CHARS = 400

#: Characters of a search hit's context (its place in the hierarchy) kept.
CONTEXT_CHARS = 240

#: Characters of one long text field (a series' scope and content, a
#: department's history) kept in get_record.
TEXT_CHARS = 4_000

_HEAD = re.compile(r"<head\b[^>]*>.*?</head>", re.I | re.S)
_BLOCK = re.compile(r"</?(p|list|item|lb|br|chronlist|chronitem|table|row)\b[^>]*>", re.I)
_TAG = re.compile(r"<[^>]*>")
_SPACE_BEFORE_PUNCT = re.compile(r"[ \t]+([,.;:)\]])")


def clean(text: object, *, one_line: bool = False) -> str:
    """Plain text from a Discovery field: markup stripped, entities decoded.

    Paragraphs and list items become lines; ``one_line`` joins them, for a
    search hit or for parsing. A ``<head>`` only repeats the field's name
    ("Scope and Content", "Arrangement") and is dropped. Entities are decoded
    after the tags are stripped, so an encoded ``&lt;`` in the text does not
    become a tag.
    """
    if not isinstance(text, str) or not text:
        return ""
    out = _HEAD.sub("\n", text)
    out = _BLOCK.sub("\n", out)
    out = _TAG.sub(" ", out)
    out = html.unescape(out)
    lines = [" ".join(line.split()) for line in out.splitlines()]
    lines = [_SPACE_BEFORE_PUNCT.sub(r"\1", line) for line in lines if line]
    return " ".join(lines) if one_line else "\n".join(lines)


def clip(text: str, limit: int) -> str:
    """Text cut to ``limit`` characters at a word boundary, marked when cut."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0] if " " in text[:limit] else text[:limit]
    return cut.rstrip() + " ..."


def record_url(record_id: str) -> str:
    """The public Discovery page of a record."""
    return RECORD_PAGE.format(id=record_id)


def level_of(number: object, tna: bool) -> dict[str, Any]:
    """``level`` (Discovery's number) and, for TNA's records, ``level_name``."""
    if not isinstance(number, int) or isinstance(number, bool):
        return {}
    out: dict[str, Any] = {"level": number}
    if tna and number in TNA_LEVELS:
        out["level_name"] = TNA_LEVELS[number]
    return out


def is_tna(held_by: list[str]) -> bool:
    """Whether a record is The National Archives' own."""
    return any("national archives" in h.lower() for h in held_by)


def held_by_names(value: object) -> list[str]:
    """Holding archives' names, from a search hit (strings) or a record (objects)."""
    names: list[str] = []
    for entry in value if isinstance(value, list) else []:
        if isinstance(entry, str):
            name = entry
        elif isinstance(entry, dict):
            name = entry.get("xReferenceName") or ""
        else:
            continue
        name = clean(name, one_line=True)
        if name and name not in names:
            names.append(name)
    return names


def covering_years(start: object, end: object) -> tuple[int | None, int | None]:
    """Years from Discovery's numeric dates (``18110101``), 0 or absent as None."""

    def year(value: object) -> int | None:
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value // 10_000 or None
        return None

    return year(start), year(end)


# --------------------------------------------------------------------------- #
# References and ids
# --------------------------------------------------------------------------- #
#: A Discovery record id: TNA's (``C8853102``, ``D651997``), Archon's
#: (``A13530124``), the NRA's (``N13554877``), or another archive's GUID,
#: with or without hyphens.
_ID = re.compile(
    r"^(?:[A-Za-z]\d{1,12}"
    r"|[0-9A-Fa-f]{32}"
    r"|[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})$"
)

#: A TNA reference: a department code, a space, and a series number with any
#: piece and item after it (``WO 97/1211/256``).
_TNA_REFERENCE = re.compile(r"^([A-Za-z]{1,6})\s*(\d[\w/ .\-]*)$")

#: A series code alone (``WO 97``, ``PROB 11``).
_SERIES = re.compile(r"^([A-Za-z]{1,6})\s*(\d{1,5}[A-Za-z]?)$")

#: A department code alone (``WO``).
_DEPARTMENT = re.compile(r"^[A-Za-z]{1,6}$")


def as_id(value: str) -> str | None:
    """The value as a record id in Discovery's case, or None if it is not one.

    Ids are case-sensitive: the letter of a TNA id is upper case, and a GUID
    lower case. A value with a space or a slash is a reference, never an id.
    """
    text = value.strip()
    if not _ID.match(text):
        return None
    if text[0].isalpha() and text[1:].isdigit():
        return text[0].upper() + text[1:]
    return text.lower()


def as_reference(value: str) -> str | None:
    """A catalogue reference tidied to Discovery's form, or None if unusable.

    References are case-sensitive in the API: a TNA department code is upper
    case and separated from the series number by one space, so ``wo97/1211``
    becomes ``WO 97/1211``. Other archives' references (``Add MS 2741``) are
    kept as written, with runs of spaces collapsed.
    """
    text = " ".join(value.split())
    if not text or len(text) > 120 or not text.isprintable():
        return None
    if m := _TNA_REFERENCE.match(text):
        rest = re.sub(r"\s*/\s*", "/", m.group(2))
        return f"{m.group(1).upper()} {rest}"
    return text


def as_series(value: str) -> str | None:
    """A series code in Discovery's form (``WO 97``), or None if it is not one."""
    m = _SERIES.match(value.strip())
    return f"{m.group(1).upper()} {m.group(2).upper()}" if m else None


def as_department(value: str) -> str | None:
    """A department code in Discovery's form (``WO``), or None if it is not one."""
    text = value.strip()
    return text.upper() if _DEPARTMENT.match(text) else None


# --------------------------------------------------------------------------- #
# WO 97
# --------------------------------------------------------------------------- #
#: An item in the item-level part of WO 97 (1760-1854): ``WO 97/<piece>/<item>``.
_WO97_ITEM = re.compile(r"^WO 97/\d+/\d+[A-Za-z]?$")

_BORN = re.compile(r"(?:^|\s)Born\s+")
_SERVED = re.compile(r"(?:^|\s)Served in\s+")
_DISCHARGED = re.compile(r"(?:^|\s)Discharged aged\s+")
_AGE = re.compile(r"^(\d{1,3}|\[[^\]]*\])\.?\s*")
_UNSPECIFIED = re.compile(r"^other regiments?(\(s\))? unspecified$", re.I)


def is_wo97_item(reference: str) -> bool:
    """Whether a reference is an item in WO 97's item-level part."""
    return bool(_WO97_ITEM.match(reference or ""))


def parse_wo97(description: str, start: object = None, end: object = None) -> dict | None:
    """Take apart WO 97's standard description, keeping the original.

    ``NAME [alias NAME] Born PLACE[, County] Served in REGT[; REGT...]
    Discharged aged N [Covering date gives year of discharge|enlistment.]``.
    The markers are matched with their capitals (names and places are
    written in upper case, so ``BORNHOLM`` is not ``Born``). ``start`` and
    ``end`` are Discovery's numeric covering dates: the papers' first and
    last years, usually enlistment and discharge, unless the description
    says the one date gives the year of discharge or of enlistment.

    Returns None if the description is not in the standard form.
    """
    flat = clean(description, one_line=True)
    served_at = _SERVED.search(flat)
    if not served_at:
        return None
    head, tail = flat[: served_at.start()], flat[served_at.end() :]
    born_at = _BORN.search(head)
    name_text = (head[: born_at.start()] if born_at else head).strip()
    born_text = head[born_at.end() :].strip() if born_at else ""
    if not name_text:
        return None
    age: int | None = None
    age_text = ""
    note = ""
    discharged_at = _DISCHARGED.search(tail)
    if discharged_at:
        served_text = tail[: discharged_at.start()]
        after = tail[discharged_at.end() :]
        if m := _AGE.match(after):
            age_text = m.group(1)
            age = int(age_text) if age_text.isdigit() else None
            note = after[m.end() :].strip()
        else:
            note = after.strip()
    else:
        served_text = tail.rstrip(". ")

    names = [n.strip() for n in re.split(r"\s+alias\s+", name_text) if n.strip()]
    words = names[0].split()
    out: dict[str, Any] = {
        "name": names[0],
        "surname": words[-1],
        "forenames": " ".join(words[:-1]),
    }
    if len(names) > 1:
        out["aliases"] = names[1:]
    if born_text:
        place, _, county = born_text.rpartition(",")
        if place:
            out["birthplace"], out["county"] = place.strip(), county.strip()
        else:
            out["birthplace"] = born_text
    regiments, unspecified = [], False
    for part in served_text.split(";"):
        part = part.strip().rstrip(".")
        if not part:
            continue
        if _UNSPECIFIED.match(part):
            unspecified = True
        else:
            regiments.append(part)
    out["regiments"] = regiments
    if unspecified:
        out["other_regiments_unspecified"] = True
    if age is not None:
        out["discharge_age"] = age
    elif age_text:
        out["discharge_age"] = None
        out["discharge_age_text"] = age_text

    first, last = covering_years(start, end)
    lowered = note.lower()
    if "year of enlistment" in lowered:
        out["enlistment_year"] = first
        out["discharge_year"] = None
    elif "year of discharge" in lowered:
        out["discharge_year"] = last
    elif first and last:
        out["service_years"] = f"{first}-{last}" if first != last else str(first)
        out["discharge_year"] = last
    else:
        out["discharge_year"] = last
    if out.get("discharge_year") and age is not None:
        born = out["discharge_year"] - age
        out["estimated_birth_year"] = born
        out["birth_year_range"] = [born - 1, born]
    if note:
        out["covering_note"] = note.rstrip()
    out["original"] = flat
    return out


_ORDINAL = re.compile(r"^(\d+)(st|nd|rd|th|d)?$")
_DROP = frozenset({"regiment", "regt", "of", "the", "and", "s"})
_ALIAS = {"ft": "foot", "regts": "regiment", "drgns": "dragoon", "gds": "guard"}


def _tokens(text: str) -> set[str]:
    """Words folded for loose matching: ordinals to numbers, plurals to singular."""
    out: set[str] = set()
    for word in re.findall(r"[a-z0-9]+", (text or "").lower()):
        word = _ALIAS.get(word, word)
        if m := _ORDINAL.match(word):
            out.add(m.group(1))
            continue
        if word in _DROP:
            continue
        if len(word) > 3 and word.endswith("s"):
            word = word[:-1]
        out.add(word)
    return out


def regiment_matches(wanted: str, regiments: list[str]) -> bool:
    """Whether every word of ``wanted`` is in one of the regiments, loosely.

    "33rd Foot", "33 Foot" and "33rd Regiment of Foot" all match "33rd Foot
    Regiment"; "Dragoons" matches "7th Dragoons" and "6th Dragoon Guards".
    Loose on purpose: a filter that drops the right man is worse than one
    that keeps a stranger.
    """
    want = _tokens(wanted)
    if not want:
        return True
    return any(want <= _tokens(r) for r in regiments)


def place_matches(wanted: str, *places: str) -> bool:
    """Whether every word of ``wanted`` is in the birthplace or county."""
    want = _tokens(wanted)
    if not want:
        return True
    return want <= set().union(*(_tokens(p) for p in places if p))


def name_matches(wanted: str, candidate: str) -> bool:
    """One name word against another, case-folded; a trailing * matches a prefix."""
    want = wanted.strip().casefold().replace("'", "")
    have = candidate.strip().casefold().replace("'", "")
    if want.endswith("*"):
        return have.startswith(want[:-1])
    return have == want


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #
def entity_lines(value: object) -> list[dict[str, str]]:
    """Discovery's lists of people, bodies and related material, as plain rows.

    Each row keeps whatever text the entry has, and the record id it points
    at, so a related series can be read with get_record.
    """
    rows: list[dict[str, str]] = []
    for entry in value if isinstance(value, list) else []:
        if isinstance(entry, str):
            text = clean(entry, one_line=True)
            if text:
                rows.append({"text": text})
            continue
        if not isinstance(entry, dict):
            continue
        person = " ".join(
            clean(entry.get(k), one_line=True)
            for k in ("preTitle", "title", "firstName", "surname")
            if entry.get(k)
        )
        parts = [
            clean(entry.get("description"), one_line=True),
            person,
            clean(entry.get("xReferenceName"), one_line=True),
            clean(entry.get("xReferenceDescription"), one_line=True),
        ]
        text = " ".join(p for p in parts if p)
        if not text:
            continue
        row = {"text": text}
        if entry.get("xReferenceId"):
            row["id"] = str(entry["xReferenceId"])
        if entry.get("xReferenceURL"):
            row["url"] = str(entry["xReferenceURL"])
        rows.append(row)
    return rows


def place_lines(value: object) -> list[str]:
    """Discovery's place entries, as display names."""
    out: list[str] = []
    for entry in value if isinstance(value, list) else []:
        if isinstance(entry, str):
            text = clean(entry, one_line=True)
        elif isinstance(entry, dict):
            text = clean(entry.get("displayName"), one_line=True) or ", ".join(
                clean(entry.get(k), one_line=True)
                for k in ("placeName", "parish", "town", "county", "region", "country")
                if entry.get(k)
            )
        else:
            continue
        if text and text not in out:
            out.append(text)
    return out


def label_of(record: dict) -> str:
    """A short name for a record: its title, else (for a piece) its scope and content."""
    title = clean(record.get("title"), one_line=True)
    if title:
        return title
    scope = record.get("scopeContent")
    return clean(scope.get("description"), one_line=True) if isinstance(scope, dict) else ""
