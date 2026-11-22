"""File and chapter naming helpers shared by the download engine."""

import re
import unicodedata

# Default output name pattern; the settings page and config use the same text.
DEFAULT_NAMING_TEMPLATE = "{title} - Chapter {chapter}"
# Longest file or folder name the downloader writes.
_MAX_NAME_LENGTH = 100
# Room kept for the chapter text when a long title must be shortened. Keys
# ("0002.000"), source labels ("0002.000 (2.00)") and parts
# ("0002_Part 10") fit, so a manga's chapters keep one title prefix.
_CHAPTER_TEXT_RESERVE = 24
_INVALID_FILENAME_CHARS = '<>:"/\\|?*'
# Windows device names: a file or folder whose name before the first dot
# is one of these (any case, trailing spaces ignored) opens the device
# instead ("CON", "nul.cbz", "COM1 .pdf"). The superscript digits count
# as well on Windows.
_WINDOWS_RESERVED_NAMES = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"{dev}{n}" for dev in ("COM", "LPT") for n in "0123456789\u00b9\u00b2\u00b3"]
)


def _get_extension(url: str) -> str:
    """Get file extension from URL path (not substring match)."""
    from posixpath import splitext
    path = url.split('?')[0].split('#')[0]
    _, ext = splitext(path)
    ext = ext.lower()
    if ext in ('.webp', '.png', '.jpg', '.jpeg', '.gif'):
        return ext
    return '.jpg'


def _sanitize_filename(name: str) -> str:
    """Make a string safe for use as a file or folder name on Windows,
    macOS and Linux."""
    name = _strip_invalid_chars(name).strip()[:_MAX_NAME_LENGTH]
    # Windows trims trailing dots/spaces from path components, so remove
    # them explicitly after truncation to keep generated paths stable.
    name = name.rstrip(". ")
    # Never yield a dot-only ('.', '..') or empty result; those are
    # directory references, not usable path components.
    if not name.strip('.'):
        return 'untitled'
    return _avoid_reserved_name(name)


def _strip_invalid_chars(name: str) -> str:
    """Remove characters that are not allowed in file names: the
    Windows-reserved punctuation and control characters."""
    for char in _INVALID_FILENAME_CHARS:
        name = name.replace(char, '')
    return ''.join(c for c in name if unicodedata.category(c) != 'Cc')


def _avoid_reserved_name(name: str) -> str:
    """Append "_" to a Windows device name ("CON" -> "CON_",
    "nul.v2" -> "nul_.v2") so the result names a real file everywhere."""
    stem, dot, rest = name.partition('.')
    if stem.rstrip(' ').upper() not in _WINDOWS_RESERVED_NAMES:
        return name
    name = f"{stem.rstrip(' ')}_{dot}{rest}"
    # The stem is at most five characters, so cutting the end keeps it.
    return name[:_MAX_NAME_LENGTH].rstrip(". ")


def _download_folder_key(title: str) -> str:
    """Key under which two titles share one download folder.

    Sanitizing can map different titles to one name ("A:B" and "AB"),
    case-insensitive file systems merge "x" and "X", and macOS stores
    composed and decomposed accents alike. Equal keys mean the titles
    would write into, and overwrite files in, the same folder.
    """
    return unicodedata.normalize("NFC", _sanitize_filename(title)).casefold()


def _chapter_base_name(template: str, title: str, chapter: str,
                       source: str = "") -> str:
    """Sanitized base name for a chapter file built from ``template``.

    Names are limited to _MAX_NAME_LENGTH characters. Instead of cutting
    the end of the whole name, which could drop the chapter text and give
    two chapters the same name, a long title is shortened so that the name
    fits with _CHAPTER_TEXT_RESERVE characters (or the chapter text's own
    length, if longer) kept for the chapter. The chapter text therefore
    stays whole, and chapters whose text fits the reserve share one title
    prefix and still sort by chapter. Names with a title short enough for
    the reserve are unchanged. Only when the name is too long even without
    any title (very long template text, source or chapter text) is it cut
    at the end like any other file name.
    """
    def render(name_title: str, name_chapter: str) -> str:
        return (template.replace("{title}", name_title)
                        .replace("{chapter}", name_chapter)
                        .replace("{source}", source))

    reserved = "x" * max(_CHAPTER_TEXT_RESERVE,
                         len(_strip_invalid_chars(chapter)))

    def fits(name_title: str) -> bool:
        cleaned = _strip_invalid_chars(render(name_title, reserved)).strip()
        return len(cleaned) <= _MAX_NAME_LENGTH

    short_title = title
    if "{title}" in template:
        while short_title and not fits(short_title):
            short_title = short_title[:-1].rstrip()
    return _sanitize_filename(render(short_title, chapter))


# Chapter numbers in output names start with a fixed-width key so that plain
# byte order and locale collation (which may skip punctuation and compare
# only letters and digits at first) both list them in chapter order,
# whatever follows the label (extension, folder end or template text):
#
# - Numeric labels get "<whole>.<fraction>": the whole number zero-padded to
#   _CHAPTER_PAD_WIDTH digits and the fraction cut or zero-filled to
#   _FRACTION_WIDTH digits ("2" -> "0002.000", "2.5" -> "0002.500",
#   "2.001" -> "0002.001"). All keys have the same shape and differ in a
#   digit, so the comparison never reaches the extension. Chapters up to
#   9999 with up to three decimal places are ordered exactly.
# - Part labels get "<whole>_Part <nn>": "_" sorts after "." in byte order
#   and "P" after digits in locales, so parts follow the chapter's numeric
#   names and precede the next chapter.
# - When the key does not read back as the source label ("2.0", "2.00",
#   "02", "2.50", more than three decimals, "2 part 1"), the exact label is
#   appended in parentheses so distinct numeric and part labels get
#   distinct names (see _format_chapter_number for the exact scope).
#   Such names sort next to the chapter with the same key; their order
#   among themselves (and against "2") is not defined, since they name the
#   same chapter number.
_CHAPTER_PAD_WIDTH = 4
_FRACTION_WIDTH = 3
_PART_PAD_WIDTH = 2
_PART_MARK = "_"

_NUMBER_RE = re.compile(r"(\d+)(?:\.(\d+))?", re.ASCII)
_PART_RE = re.compile(r"(\d+)\s*part\s*(\d+)(.*)", re.ASCII | re.IGNORECASE)


def _format_chapter_number(chapter_num: str) -> str:
    """Format a chapter number for use in output file and folder names.

    - Numeric chapters: "2" -> "0002.000", "2.5" -> "0002.500",
      "2.001" -> "0002.001", "10" -> "0010.000".
    - Part chapters keep a readable label: "2 Part 10" -> "0002_Part 10".
    - Labels whose key reads differently get the exact label appended:
      "2.0" -> "0002.000 (2.0)", "2 part 1" -> "0002_Part 01 (2 part 1)".
    - Anything else ("Extra", "Chapter 3", " 2") is returned unchanged.

    Distinct numeric labels get distinct results, and so do part labels
    unless they differ only in characters a file name drops (trailing
    "." or " ", or <>:"/\\|?* in the text after the part number).
    Pass-through labels are returned as they are, so one written exactly
    like a generated result (for example "0002.000") is not told apart
    from it. See the module comment above for the ordering contract.
    """
    number = _NUMBER_RE.fullmatch(chapter_num)
    if number:
        whole, fraction = number.groups()
        digits = ((fraction or "") + "0" * _FRACTION_WIDTH)[:_FRACTION_WIDTH]
        key = f"{_pad(whole, _CHAPTER_PAD_WIDTH)}.{digits}"
        shown = digits.rstrip("0")
        reads_as = _strip_zeros(whole) + (f".{shown}" if shown else "")
        return _with_source_label(key, chapter_num, reads_as)

    part = _PART_RE.fullmatch(chapter_num)
    if part:
        whole, part_num, rest = part.groups()
        key = (f"{_pad(whole, _CHAPTER_PAD_WIDTH)}{_PART_MARK}"
               f"Part {_pad(part_num, _PART_PAD_WIDTH)}{rest}")
        reads_as = f"{_strip_zeros(whole)} Part {_strip_zeros(part_num)}{rest}"
        return _with_source_label(key, chapter_num, reads_as)

    return chapter_num


def _strip_zeros(digits: str) -> str:
    """Digit string without leading zeros ("007" -> "7", "000" -> "0")."""
    return digits.lstrip("0") or "0"


def _pad(digits: str, width: int) -> str:
    """Zero-pad a digit string after dropping its own leading zeros."""
    return _strip_zeros(digits).zfill(width)


def _with_source_label(key: str, label: str, reads_as: str) -> str:
    """Append the source label when the key alone would not identify it."""
    return key if label == reads_as else f"{key} ({label})"


def _legacy_chapter_number(chapter_num: str) -> str:
    """Chapter label used in file names before issue #241.

    Integers and decimals were kept as-is and part chapters became
    decimal-looking strings ("2 Part 1" -> "2.01").
    """
    part = re.match(r'^(\d+)\s*[Pp]art\s*(\d+)(.*)$', chapter_num)
    if part:
        whole, part_num, rest = part.groups()
        return f"{whole}.{part_num.zfill(2)}{rest}"
    return chapter_num


def _chapter_filename_labels(chapter_num: str) -> list[str]:
    """Chapter labels a downloaded chapter may be stored under, newest first.

    The current padded form comes first, then the pre-#241 forms so
    downloads made by older versions stay reachable.
    """
    labels: list[str] = []
    for label in (_format_chapter_number(chapter_num),
                  _legacy_chapter_number(chapter_num),
                  chapter_num,
                  f"{chapter_num}.0"):
        if label not in labels:
            labels.append(label)
    return labels
