"""Generate the settings reference and the example config file.

Usage: python -m memanga.config_docs [--check]

Types, choices, limits and defaults are read from the program itself
(``Config._default_config()`` and ``CONFIG_KEYS``), so they can't drift.
What a setting means and where it is changed is written here, next to the
key; generating fails when a key has no description, a description names
a key the program no longer has, or a named command or option does not
exist.
"""

import argparse
import json
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from .config import CONFIG_KEYS, Config

REFERENCE_PATH = "docs/reference/config-keys.md"
EXAMPLE_PATH = "examples/config.example.yaml"
SITE_URL = "https://meellm.github.io/MeManga/reference/config"

HEADER = (
    "<!-- Generated from the program's defaults by"
    " `python -m memanga.config_docs`. Do not edit by hand. -->"
)

# The latest published release and the keys its code reads. A published
# release does not change; update both when a new release is published,
# together with docs/.vitepress/release.ts.
RELEASE_TAG = "v0.4.4"
RELEASE_KEYS = frozenset({
    "manga",
    "delivery.mode", "delivery.download_dir", "delivery.delete_after_send",
    "delivery.output_format", "delivery.naming_template",
    "delivery.post_processing.enabled", "delivery.post_processing.command",
    "delivery.post_processing.fail_on_error",
    "email.kindle_email", "email.sender_email", "email.smtp_server",
    "email.smtp_port", "email.app_password",
    "cron.enabled", "cron.time",
    "gui.sort_by", "gui.auto_check", "gui.auto_check_interval",
    "gui.reader_prefetch_next", "gui.max_concurrent_downloads",
    "gui.view_mode", "gui.reader_view_mode", "gui.reader_dual_page",
    "reader.remove_after_read",
    "partial_chapters.enabled", "partial_chapters.threshold_percent",
    "sources.disabled", "sources.first_run_seeded",
    "sources.recurated_asura",
})


@dataclass(frozen=True)
class Section:
    title: str
    text: str


# In the order of the reference page. "" holds the top-level keys.
SECTIONS: Dict[str, Section] = {
    "delivery": Section(
        "Delivery",
        "Where downloaded chapters are saved, in which format, and what "
        "happens after a chapter is saved."),
    "email": Section(
        "Email and Kindle",
        "Sending chapters to a Kindle by email. "
        "[Send chapters to a Kindle](../guide/kindle) explains the setup."),
    "cron": Section(
        "Scheduled checks",
        "A daily check for new chapters, run by the system's scheduler."),
    "gui": Section(
        "Desktop app",
        "Settings of the desktop app."),
    "reader": Section(
        "Reader",
        "The desktop app's built-in reader."),
    "mangadex": Section(
        "MangaDex",
        "Options for chapters from MangaDex."),
    "partial_chapters": Section(
        "Partial chapters",
        "What happens when some pages of a chapter cannot be downloaded."),
    "sources": Section(
        "Sources",
        "Which sources are turned off. The desktop app writes these keys."),
    "": Section(
        "Library and file layout",
        "The keys at the top of the file."),
}


@dataclass(frozen=True)
class KeyDoc:
    # What the setting does. The first sentence is also the comment in
    # the example file.
    text: str
    # Where the desktop app changes it, for example "Settings → General".
    desktop: str = ""
    # Commands and options that change it besides `memanga config set`.
    # Values are placeholders in capitals or a {choice,list}:
    # "memanga config --partial-threshold PCT".
    commands: Tuple[str, ...] = ()
    # Set by MeManga itself; nothing to change.
    managed: bool = False
    # Only for keys that a new config file does not have: what MeManga
    # does while the key is missing.
    missing: str = ""
    # Only for keys outside CONFIG_KEYS and the defaults: the value type.
    kind: str = ""


KEYS: Dict[str, KeyDoc] = {
    # ── Top level ──────────────────────────────────────────────────────
    "schema_version": KeyDoc(
        "Layout version of this file. MeManga upgrades an older file when it "
        "saves it, and refuses a file from a newer version instead of "
        "overwriting it. Leave it as it is.",
        managed=True),
    "manga": KeyDoc(
        "Your library: one entry for each series you follow, with its title, "
        "its sources and your choices for it. Add and change series with the "
        "commands or in the desktop app; there is no need to edit the "
        "entries by hand.",
        desktop="the Library page",
        commands=("memanga add", "memanga edit", "memanga remove")),

    # ── Delivery ───────────────────────────────────────────────────────
    "delivery.mode": KeyDoc(
        "`local` keeps downloaded chapters in the download folder. `email` "
        "also sends them to a Kindle by email.",
        desktop="Settings → General",
        commands=("memanga config",)),
    "delivery.download_dir": KeyDoc(
        "Folder where downloaded chapters are saved. Each series gets a "
        "folder of its own inside it.",
        desktop="Settings → General",
        commands=("memanga config",)),
    "delivery.delete_after_send": KeyDoc(
        "With email delivery, delete a chapter's file once it has been sent. "
        "A file that cannot be deleted stays on disk.",
        desktop="Settings → Kindle / Email",
        commands=("memanga config",)),
    "delivery.output_format": KeyDoc(
        "File format of downloaded chapters: a `pdf` or `epub` document, a "
        "`cbz` or `zip` archive, or a folder of `jpg`, `png` or `webp` "
        "images. Only PDF and EPUB files are sent to a Kindle.",
        desktop="Settings → General",
        commands=("memanga config",)),
    "delivery.naming_template": KeyDoc(
        "Name of each chapter file, without the extension. `{title}`, "
        "`{chapter}` and `{source}` are replaced with the series title, the "
        "chapter number and the source. A folder of images is always named "
        "`Chapter` and the chapter number.",
        desktop="Settings → General"),
    "delivery.post_processing.enabled": KeyDoc(
        "Run `delivery.post_processing.command` after each chapter's file or "
        "folder is saved.",
        desktop="Settings → Advanced",
        commands=("memanga config",)),
    "delivery.post_processing.command": KeyDoc(
        "The command to run. Only use commands you trust. It is split into "
        "arguments and started directly, without a shell. `{output_path}`, "
        "`{title}`, `{chapter}`, `{source}`, `{format}` and `{is_dir}` in it "
        "are replaced with the saved file or folder, the series title, the "
        "chapter number, the source, the output format and `1` for a folder "
        "or `0` for a file. The same values are in the environment variables "
        "`MEMANGA_OUTPUT_PATH`, `MEMANGA_MANGA_TITLE`, `MEMANGA_CHAPTER`, "
        "`MEMANGA_SOURCE`, `MEMANGA_OUTPUT_FORMAT` and `MEMANGA_IS_DIR`.",
        desktop="Settings → Advanced",
        commands=("memanga config",)),
    "delivery.post_processing.fail_on_error": KeyDoc(
        "When the command fails: `true` marks the chapter as failed, `false` "
        "shows a warning and keeps the chapter as downloaded.",
        desktop="Settings → Advanced",
        commands=("memanga config",)),

    # ── Email ──────────────────────────────────────────────────────────
    "email.kindle_email": KeyDoc(
        "Your Kindle's Send to Kindle email address.",
        desktop="Settings → Kindle / Email",
        commands=("memanga config",)),
    "email.sender_email": KeyDoc(
        "The address the emails are sent from. It has to be on the list of "
        "approved senders in your Amazon account.",
        desktop="Settings → Kindle / Email",
        commands=("memanga config",)),
    "email.smtp_server": KeyDoc(
        "The mail server that sends the emails.",
        desktop="Settings → Kindle / Email"),
    "email.smtp_port": KeyDoc(
        "The port of the mail server.",
        desktop="Settings → Kindle / Email"),
    "email.smtp_tls": KeyDoc(
        "How the connection to the mail server is encrypted. `auto` uses "
        "implicit TLS on port 465 and STARTTLS on every other port; "
        "`starttls` and `implicit` always use that method."),
    "email.smtp_timeout": KeyDoc(
        "Seconds to wait for the mail server at each step of sending."),
    "email.max_email_mb": KeyDoc(
        "The largest email your mail provider accepts, in MB. A PDF that "
        "does not fit is split into parts that are sent one after another; "
        "an EPUB that does not fit is not sent, and a warning says why."),
    "email.app_password": KeyDoc(
        "The password for the mail server, usually an app password. Leave "
        "it empty here: MeManga keeps the password in the system keyring "
        "and only writes it into this file, as plain text, when there is no "
        "usable keyring. `MEMANGA_SMTP_PASSWORD`, or "
        "`MEMANGA_SMTP_PASSWORD_FILE` naming a file that holds the password, "
        "is used instead when set.",
        desktop="Settings → Kindle / Email",
        commands=("memanga config",)),
    "email.kindle_scope": KeyDoc(
        "Which manga are sent: `all` sends every manga, `selected` only the "
        "manga whose Kindle toggle is on. A manga that has its own Kindle "
        "choice always follows it.",
        desktop="Settings → General",
        commands=("memanga config",),
        missing=(
            "While it is missing, every manga without a choice of its own "
            "is sent. Turning email delivery on in the desktop app or with "
            "`memanga config` asks which to use; `memanga config set "
            "delivery.mode email` stores `selected`.")),

    # ── Scheduled checks ───────────────────────────────────────────────
    "cron.enabled": KeyDoc(
        "Whether MeManga has set up a daily check with the system's "
        "scheduler. It records what was set up: changing it here does not "
        "add or remove the scheduled check.",
        desktop="Settings → Advanced",
        commands=("memanga cron install", "memanga cron remove")),
    "cron.time": KeyDoc(
        "Time of day of the scheduled check, in the computer's local time.",
        desktop="Settings → Advanced",
        commands=("memanga cron install --time HH:MM",)),

    # ── Desktop app ────────────────────────────────────────────────────
    "gui.sort_by": KeyDoc(
        "Order of the library in the desktop app.",
        desktop="the sort menu of the Library page"),
    "gui.auto_check": KeyDoc(
        "When the desktop app starts or comes back online, check for new "
        "chapters if the last check is older than "
        "`gui.auto_check_interval`."),
    "gui.auto_check_interval": KeyDoc(
        "Seconds since the last check after which the desktop app checks "
        "again by itself."),
    "gui.reader_prefetch_next": KeyDoc(
        "While you read a manga in manual mode, download its next available "
        "chapter in the background.",
        desktop="Settings → Advanced"),
    "gui.network_check": KeyDoc(
        "Let the desktop app find out whether it is online by opening a "
        "connection to a well-known host. No data is sent over it.",
        desktop="Settings → Advanced"),
    "gui.network_check_hosts": KeyDoc(
        "The hosts for that test, as `host:port` entries; IPv6 addresses go "
        "in square brackets. An empty list means MeManga's built-in hosts.",
        commands=("memanga config edit",)),
    "gui.mangadex_cover_fallback": KeyDoc(
        "Look for missing or broken covers on MangaDex. This is skipped "
        "while mangadex.org is turned off on the Sources page.",
        desktop="Settings → Advanced"),
    "gui.search_chapter_counts": KeyDoc(
        "Show how many chapters each search result has. This loads the "
        "chapter list of every result.",
        desktop="Settings → Advanced"),
    "gui.cover_cache_max_mb": KeyDoc(
        "Disk space for saved cover images, in MB. Beyond it, the covers "
        "used longest ago are removed; they are loaded again when needed.",
        desktop="Settings → Advanced"),
    "gui.max_concurrent_downloads": KeyDoc(
        "How many chapters the desktop app downloads at the same time.",
        desktop="Settings → General",
        kind="whole number from 1 to 8",
        missing="While it is missing, 2 are downloaded at the same time."),
    "gui.view_mode": KeyDoc(
        "Layout of the library in the desktop app.",
        desktop="the Grid view and List view buttons of the Library page",
        kind="one of `grid`, `list`",
        missing="Missing until you switch the layout; `grid` is used."),
    "gui.reader_view_mode": KeyDoc(
        "Reader layout for a manga without a layout of its own. A layout "
        "chosen in the reader is stored with the manga; this key is only "
        "written when that manga is no longer in the library.",
        kind="one of `continuous`, `single`, `double`",
        missing=(
            "While it is missing, `continuous` is used, or `double` when "
            "`gui.reader_dual_page` is `true`.")),
    "gui.reader_dual_page": KeyDoc(
        "Setting from earlier versions: show two pages side by side. It is "
        "only read while `gui.reader_view_mode` is missing.",
        kind="`true` or `false`",
        missing="New config files do not have it."),
    "gui.browser_install_skipped": KeyDoc(
        "Records that you skipped the download of the browser components "
        "when the desktop app first asked, so it does not ask again. "
        "Installing the components clears it.",
        managed=True,
        kind="`true` or `false`",
        missing="Missing until you skip that question."),
    "gui.download_dir_confirmed": KeyDoc(
        "Records that the desktop app has asked where to save downloads, "
        "so it does not ask again.",
        managed=True,
        kind="`true` or `false`",
        missing="Missing until the desktop app has asked."),

    # ── Reader ─────────────────────────────────────────────────────────
    "reader.remove_after_read": KeyDoc(
        "Delete a chapter's downloaded file after you have read it in the "
        "built-in reader.",
        desktop="Settings → Advanced"),

    # ── MangaDex ───────────────────────────────────────────────────────
    "mangadex.data_saver": KeyDoc(
        "Download MangaDex chapters as smaller, compressed images.",
        desktop="Settings → General",
        commands=("memanga config",
                  "memanga config --mangadex-quality {original,data-saver}")),
    "mangadex.removed_group_ids": KeyDoc(
        "MangaDex scanlation groups whose chapters are skipped, by group ID. "
        "Resetting the settings to their defaults keeps this list.",
        commands=("memanga config --mangadex-remove-group GROUP_ID",)),

    # ── Partial chapters ───────────────────────────────────────────────
    "partial_chapters.enabled": KeyDoc(
        "Keep a chapter when some of its pages fail, with only the pages "
        "that worked. When off, one missing page fails the whole chapter.",
        desktop="Settings → Advanced",
        commands=("memanga config", "memanga config --partial {on,off}")),
    "partial_chapters.threshold_percent": KeyDoc(
        "The largest share of pages, in percent, that may fail for a "
        "chapter to be kept.",
        desktop="Settings → Advanced",
        commands=("memanga config", "memanga config --partial-threshold PCT")),

    # ── Sources ────────────────────────────────────────────────────────
    "sources.disabled": KeyDoc(
        "Sources that are turned off, by domain. Search and the cover "
        "look-up skip them.",
        desktop="the Sources page",
        kind="list of domains",
        missing=(
            "Missing until the desktop app first starts. It then turns off "
            "every source outside its default selection.")),
    "sources.first_run_seeded": KeyDoc(
        "Records that the desktop app has set up `sources.disabled` for the "
        "first time.",
        managed=True,
        kind="`true` or `false`",
        missing="Missing until the desktop app first starts."),
    "sources.recurated_asura": KeyDoc(
        "Records that a one-time change to `sources.disabled` has been made, "
        "so it is never made again.",
        managed=True,
        kind="`true` or `false`",
        missing="Missing until the desktop app first starts."),
}


# ─── Facts from the program ────────────────────────────────────────────

def default_config() -> dict:
    """A new config file's contents, as the program creates them."""
    # _default_config does not use the instance.
    return Config._default_config(None)


def _leaves(data: dict, prefix: str = "") -> Iterator[Tuple[str, object]]:
    """(dotted key, value) for every setting, in file order."""
    for name, value in data.items():
        key = f"{prefix}{name}"
        if isinstance(value, dict):
            yield from _leaves(value, key + ".")
        else:
            yield key, value


def default_keys() -> Dict[str, object]:
    return dict(_leaves(default_config()))


def _home_relative(value) -> Optional[str]:
    """The part after the home folder of a default that depends on it."""
    if not isinstance(value, str):
        return None
    home = Path.home()
    try:
        relative = Path(value).relative_to(home)
    except ValueError:
        return None
    return relative.as_posix() if str(home) not in ("", "/") else None


def _section(key: str) -> str:
    return key.split(".", 1)[0] if "." in key else ""


def documented_keys() -> List[str]:
    """Every documented key, grouped by section in page order, defaults
    first in file order, then the other keys in KEYS order."""
    defaults = list(default_keys())
    others = [k for k in KEYS if k not in defaults]
    order = []
    for section in SECTIONS:
        order += [k for k in defaults if _section(k) == section]
        order += [k for k in others if _section(k) == section]
    return order


# ─── Checks ────────────────────────────────────────────────────────────

def _subparsers(parser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


_PLACEHOLDER = re.compile(r"^(?:[A-Z][A-Z0-9_:]*|\{[^{}]+\})$")


def _command_problem(command: str, root) -> Optional[str]:
    """Why ``command`` (words, options and placeholders) does not exist."""
    words = command.split()
    if not words or words[0] != root.prog:
        return f"{command!r} does not start with {root.prog!r}"
    parser = root
    for word in words[1:]:
        if _PLACEHOLDER.match(word):
            continue
        if word.startswith("-"):
            options = {o for a in parser._actions for o in a.option_strings}
            if word not in options:
                return f"{command!r}: no option {word}"
            continue
        subparsers = _subparsers(parser)
        if subparsers is not None and word in subparsers.choices:
            parser = subparsers.choices[word]
            continue
        # A word an argument takes, such as the action of `memanga cron`.
        choices = {str(c) for a in parser._actions
                   if not a.option_strings and a is not subparsers
                   and a.choices for c in a.choices}
        if word not in choices:
            return f"{command!r}: no command {word!r}"
    return None


def problems() -> List[str]:
    """Why the descriptions here do not fit the program, if they don't."""
    from .cli_docs import reference_parser

    found = []
    defaults = set(default_keys())
    required = defaults | set(CONFIG_KEYS)
    for key in sorted(required - set(KEYS)):
        found.append(f"{key}: no description")
    for key, doc in KEYS.items():
        if _section(key) not in SECTIONS:
            found.append(f"{key}: no section {_section(key)!r}")
        if key in defaults:
            if doc.missing or doc.kind:
                found.append(f"{key}: has a default, so no 'missing'/'kind'")
        else:
            if not doc.missing:
                found.append(f"{key}: not in the defaults, needs 'missing'")
            if key not in CONFIG_KEYS and not doc.kind:
                found.append(f"{key}: needs 'kind'")
        if CONFIG_KEYS.get(key, {}).get("read_only") and not (
                doc.desktop or doc.commands):
            # `config set` refuses it, so the entry must name another way.
            found.append(f"{key}: read-only, needs 'desktop' or 'commands'")
    for section in SECTIONS:
        if not any(_section(k) == section for k in KEYS):
            found.append(f"section {section!r} has no keys")
    for key in sorted(RELEASE_KEYS - set(KEYS)):
        found.append(f"{key}: release key without a description")
    anchors = [anchor(k) for k in KEYS] + [slug(s.title)
                                           for s in SECTIONS.values()]
    for name in sorted({a for a in anchors if anchors.count(a) > 1}):
        found.append(f"two headings share the anchor #{name}")
    root = reference_parser()
    for key, doc in KEYS.items():
        for command in doc.commands:
            problem = _command_problem(command, root)
            if problem:
                found.append(f"{key}: {problem}")
    if _command_problem("memanga config set", root):
        found.append("memanga config set no longer exists")
    return found


# ─── Text for the page ─────────────────────────────────────────────────

# The site makes heading anchors this way: runs of punctuation and spaces
# become one "-", and the result is lower case.
_SLUG_SEPARATORS = re.compile(r"[\s~`!@#$%^&*()\-_+=\[\]{}|\\;:\"'<>,.?/]+")


def slug(text: str) -> str:
    return _SLUG_SEPARATORS.sub("-", text).strip("-").lower()


def anchor(key: str) -> str:
    """The anchor of a key's entry, whose heading is the key itself."""
    return slug(key)


def _code(value: str) -> str:
    return f"`{value}`"


def _kind_text(key: str, default) -> str:
    spec = CONFIG_KEYS.get(key)
    if spec is None:
        if KEYS[key].kind:
            return KEYS[key].kind
        if isinstance(default, bool):
            return "`true` or `false`"
        if isinstance(default, int):
            return "whole number"
        if isinstance(default, list):
            return "list"
        return "text"
    kind = spec["kind"]
    low, high = spec.get("min"), spec.get("max")
    if low is not None and high is not None:
        bounds = f" from {low:g} to {high:g}"
    elif low is not None:
        bounds = f", at least {low:g}"
    else:
        bounds = ""
    if kind == "bool":
        return "`true` or `false`"
    if kind == "int":
        return "whole number" + bounds
    if kind == "float":
        return "number" + bounds
    if kind == "choice":
        return "one of " + ", ".join(_code(c) for c in spec["choices"])
    if kind == "time":
        return "time of day as `HH:MM`"
    if kind == "list":
        if spec.get("items") == "host_port":
            return "list of `host:port` entries"
        return "list"
    return "text, not empty" if spec.get("required") else "text"


def _value_text(key: str, value) -> str:
    relative = _home_relative(value)
    if relative is not None:
        return (f"the {_code(relative)} folder in your home folder, "
                "stored as a full path")
    if isinstance(value, bool):
        return _code("true" if value else "false")
    if value == "":
        return "empty"
    if value == []:
        return "empty list"
    return _code(str(value))


def _change_text(key: str) -> str:
    doc = KEYS[key]
    spec = CONFIG_KEYS.get(key)
    ways = []
    if doc.desktop:
        ways.append(f"in the desktop app, {doc.desktop}")
    ways += [_code(c) + (" (asks questions)" if c == "memanga config" else "")
             for c in doc.commands]
    if spec is not None and not spec.get("read_only"):
        if spec.get("secret"):
            ways.append(_code(f"memanga config set {key}")
                        + " (asks for it, or reads it from standard input"
                        " with `-`)")
        else:
            ways.append(_code(f"memanga config set {key} VALUE"))
    if not ways:
        if doc.managed:
            return "MeManga sets it; leave it as it is."
        return "by editing `config.yaml`."
    if doc.managed:
        return "MeManga sets it. " + "; ".join(ways) + "."
    return "; ".join(ways) + "."


def _key_entry(key: str, defaults: Dict[str, object]) -> List[str]:
    doc = KEYS[key]
    # A plain heading: the site reads the heading's source text out as
    # the label of its permalink, so Markdown there would be read aloud.
    # reference/config.md sets the key headings in the code font.
    lines = [f"### {key}", ""]
    if key not in RELEASE_KEYS:
        lines += [f'<Badge type="info" text="Not in {RELEASE_TAG}" />', ""]
    lines += [doc.text, ""]
    lines.append(f"- **Type:** {_kind_text(key, defaults.get(key))}")
    if key in defaults:
        lines.append(f"- **Default:** {_value_text(key, defaults[key])}")
    else:
        lines.append(f"- **Default:** not in a new config file. {doc.missing}")
    if CONFIG_KEYS.get(key, {}).get("secret"):
        lines.append("- **Secret:** `memanga config show` and `memanga "
                     "config get` never print it.")
    lines.append(f"- **Change it:** {_change_text(key)}")
    return lines + [""]


def render_reference() -> str:
    defaults = default_keys()
    keys = documented_keys()
    lines = [HEADER, "", "## Settings at a glance", ""]
    for section, info in SECTIONS.items():
        members = [k for k in keys if _section(k) == section]
        links = " · ".join(f"[{_code(k)}](#{anchor(k)})" for k in members)
        lines.append(f"- **[{info.title}](#{slug(info.title)}):** {links}")
    lines.append("")
    for section, info in SECTIONS.items():
        lines += [f"## {info.title}", "",
                  info.text, ""]
        for key in keys:
            if _section(key) == section:
                lines += _key_entry(key, defaults)
    return "\n".join(lines).rstrip("\n") + "\n"


# ─── The example file ──────────────────────────────────────────────────

_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def _plain(text: str) -> str:
    """Markdown to plain comment text."""
    return _LINK.sub(r"\1", text).replace("`", "")


def _comment(text: str, indent: str) -> List[str]:
    return textwrap.wrap(_plain(text), width=76 - len(indent),
                         initial_indent=indent + "# ",
                         subsequent_indent=indent + "# ",
                         break_long_words=False, break_on_hyphens=False)


def _yaml_value(value) -> str:
    # JSON scalars and lists are valid YAML and need no quoting rules.
    return json.dumps(value, ensure_ascii=False)


def _sample(spec):
    """A valid value for a key that has no default."""
    if "choices" in spec:
        return spec["choices"][0]
    return {"bool": False, "int": spec.get("min", 0),
            "float": spec.get("min", 0), "time": "06:00",
            "list": []}.get(spec["kind"], "")


def _example_lines(data: dict, prefix: str, indent: str) -> List[str]:
    lines: List[str] = []

    def entry(comment: List[str], line: str):
        if lines:
            lines.append("")
        lines.extend(comment)
        lines.append(line)

    for name, value in data.items():
        key = f"{prefix}{name}"
        if isinstance(value, dict):
            title = _comment(SECTIONS[key].title, indent) if key in SECTIONS else []
            entry(title, f"{indent}{name}:")
            lines.extend(_example_lines(value, key + ".", indent + "  "))
            continue
        comment = _comment(KEYS[key].text, indent)
        relative = _home_relative(value)
        if relative is not None:
            comment += _comment(
                f"Without this line: the {relative} folder in your home "
                "folder.", indent)
            entry(comment, f"{indent}# {name}: {_yaml_value('/path/to/folder')}")
        else:
            entry(comment, f"{indent}{name}: {_yaml_value(value)}")
    # Settings a new file does not have, but `config set` accepts.
    defaults = default_keys()
    for key, spec in CONFIG_KEYS.items():
        if key.rsplit(".", 1)[0] + "." == prefix and key not in defaults:
            name = key.rsplit(".", 1)[1]
            comment = _comment(KEYS[key].text, indent)
            comment += _comment("Not in a new file. " + KEYS[key].missing,
                                indent)
            entry(comment, f"{indent}# {name}: {_yaml_value(_sample(spec))}")
    return lines


def render_example() -> str:
    lines = [
        "# Example config.yaml for MeManga, with every setting at its default.",
        "#",
        "# Written by python -m memanga.config_docs; do not edit it by hand.",
        "# Each setting is explained at:",
        f"# {SITE_URL}",
        "#",
    ]
    lines += _comment(
        "MeManga creates config.yaml on first use; `memanga config path` "
        "prints where it is. A setting left out of the file uses its "
        "default.", "")
    lines.append("")
    lines += _example_lines(default_config(), "", "")
    return "\n".join(lines) + "\n"


# ─── Writing ───────────────────────────────────────────────────────────

def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def generated_files(root: Path) -> Dict[Path, str]:
    found = problems()
    if found:
        raise ValueError("Settings descriptions do not match the program:\n"
                         + "\n".join(found))
    return {root / REFERENCE_PATH: render_reference(),
            root / EXAMPLE_PATH: render_example()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="Fail if the generated files differ")
    args = parser.parse_args(argv)
    root = _repo_root()
    try:
        files = generated_files(root)
    except ValueError as e:
        parser.exit(1, f"{e}\n")
    stale = []
    for path, expected in files.items():
        if not path.exists() or path.read_text(encoding="utf-8") != expected:
            stale.append(path.relative_to(root))
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(expected, encoding="utf-8")
    if stale:
        if args.check:
            parser.exit(1, "Outdated settings reference: "
                        + ", ".join(map(str, stale))
                        + "\nRun: python -m memanga.config_docs\n")
        print("Updated settings reference: " + ", ".join(map(str, stale)))


if __name__ == "__main__":
    main()
