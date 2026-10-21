#!/usr/bin/env python3
"""
MeManga - Automatic manga downloader for Kindle
A friendly CLI for tracking and downloading manga chapters.
"""

import argparse
import json
import logging
import os
import platform
import re
import shutil
import signal
import sys
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, List, Optional

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.table import Table
from rich import box

from .backup import (
    EXPORT_VERSION,
    BackupVersionError,
    merge_backup_state,
    validate_backup,
    validate_backup_contents,
)
from .config import (CONFIG_DIR_ENV, CONFIG_KEYS, Config, ConfigError,
                     UnknownConfigKey,
                     config_key_spec, config_section_problems,
                     config_value_problem, default_config_dir,
                     default_root_moved, explicit_config_dir,
                     get_app_password, parse_config_value, set_app_password)
from .cron import (build_cron_line, build_task_command, managed_lines,
                   read_crontab,
                   remove_managed_lines, replace_managed_line,
                   source_checkout_root, unmanaged_memanga_lines)
from . import __version__, completion, doctor
from .persist import SaveError
from .process_lock import (LOCK_FILENAME, ConfigDirBusy, ConfigDirLock,
                           ConfigDirLockError)
from .chapters import ChapterWithSource, chapter_order_key, chapter_sort_key, chapter_value
from .state import State
from .downloader import DEFAULT_FALLBACK_DELAY_DAYS, DEFAULT_PAGE_RETRIES, check_for_updates, download_chapter, get_supported_sources, DownloaderError, restart_browsers, _find_chapter_on_backup, _get_sources_from_manga, _configure_mangadex
from .scrapers import get_scraper
from .search import compute_search_sources, probe_chapter_counts, sweep
from .emailer import send_to_kindle
from .chapter_pipeline import (ChapterPipeline, ChapterReporter, ChapterStatus,
                               PipelineOptions)
from .output import (LOG_FILE_NAME, LOG_LEVEL_ENV, RICH_MARKUP,
                     configure_logging, ensure_utf8_streams,
                     invalid_log_level_env, is_plain_console,
                     logging_configured, make_console, resolve_log_level,
                     set_console_renderer, stream_is_plain)

logger = logging.getLogger(__name__)

console = Console()
# Issue #239: diagnostics (errors, refused or degraded work) go to stderr
# so stdout carries only command results.
err_console = Console(stderr=True)

# Issue #239: CLI exit codes.
EXIT_OK = 0
EXIT_ERROR = 1          # operational error: not found, invalid input, refused
EXIT_USAGE = 2          # usage error (raised by argparse itself)
EXIT_PARTIAL = 3        # check / failed retry ran but some chapters failed
EXIT_INTERRUPTED = 130  # Ctrl-C
EXIT_TERMINATED = 143   # SIGTERM (128 + 15): cron timeout, service stop


def _esc(value) -> str:
    """Escape data (titles, statuses, paths, errors) for interpolation
    into Rich markup so brackets render literally (issue #375)."""
    return escape(str(value))


def _panel(text: str, **kwargs):
    """A Panel, or just its text when stdout is plain (issue #226)."""
    if is_plain_console(console):
        return text
    return Panel(text, **kwargs)


def _table(*args, **kwargs) -> Table:
    """A Table, borderless when stdout is plain (issue #226)."""
    if is_plain_console(console):
        kwargs.update(box=None, show_lines=False)
    return Table(*args, **kwargs)


def _log_level(args) -> int:
    """Console log level for the parsed command line.

    Only the global ``memanga -q`` quiets logging. ``check --quiet``
    keeps its own meaning (never prompt), so the scheduled
    ``check --auto --quiet`` still records degraded sources.
    """
    default = logging.INFO if getattr(args, "gui", False) else logging.WARNING
    return resolve_log_level(getattr(args, "verbose", 0),
                             getattr(args, "log_quiet", False), default)


def _render_on_err_console(markup: str) -> None:
    err_console.print(markup)


def _configure_output(args) -> None:
    """Set up consoles and logging for this run (issue #226).

    Output to a pipe, file or cron, ``--plain`` or ``TERM=dumb`` is plain
    text: no colour, emoji, borders or hard wrapping. ``NO_COLOR`` only
    turns colour off. Log records go to stderr; ``-v``/``-vv``/``-q``,
    then ``MEMANGA_LOG_LEVEL``, choose the level (default WARNING, INFO
    with ``--gui``). On an interactive stderr, command warnings and
    errors (see :func:`_diagnostic`) keep their Rich rendering.
    """
    global console, err_console
    ensure_utf8_streams()
    plain = getattr(args, "plain", False)
    if stream_is_plain(sys.stdout, plain):
        console = make_console(plain=True)
    if stream_is_plain(sys.stderr, plain):
        err_console = make_console(stderr=True, plain=True)

    configure_logging(_log_level(args))
    if not is_plain_console(err_console):
        set_console_renderer(_render_on_err_console)
    bad = invalid_log_level_env()
    if bad is not None:
        logger.warning("Ignoring %s=%r: use DEBUG, INFO, WARNING, ERROR or "
                       "CRITICAL", LOG_LEVEL_ENV, bad)


def _enable_log_file(args, root: Path) -> None:
    """Also log to the rotating ``diagnostics.log`` in ``root`` when
    ``--log-file`` was given. A file that can't be opened only warns."""
    if not getattr(args, "log_file", False):
        return
    path = root / LOG_FILE_NAME
    try:
        configure_logging(_log_level(args), log_file=path)
    except OSError as e:
        sys.stderr.write(f"warning: cannot write log file {path}: "
                         f"{e.strerror or e}\n")


def _diagnostic(level: int, markup: str, message: str, *args) -> None:
    """Report a command's warning or error (issue #226).

    It is a log record on ``memanga.cli``: ``memanga -q`` and
    ``MEMANGA_LOG_LEVEL`` decide whether it shows, redirected stderr and
    ``--log-file`` get one plain line with a timestamp and level, and an
    interactive terminal still shows ``markup``. When main() did not set
    up logging (a command function called directly), ``markup`` is
    printed as before.
    """
    if not logging_configured():
        err_console.print(markup)
        return
    logger.log(level, message, *args, extra={RICH_MARKUP: markup})


def _stdin_is_tty() -> bool:
    """True only when someone can answer a prompt (issue #258).

    Cron, pipes and CI run with stdin closed or redirected; prompting
    there either blocks or dies with EOFError, so callers must bail.
    """
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _non_interactive_error(message: str) -> int:
    """Report input a non-interactive run can't supply; return exit code 1."""
    sys.stderr.write(f"error: {message}\n")
    return EXIT_ERROR


def _error(message: str) -> int:
    """Print a Rich-markup diagnostic to stderr; return EXIT_ERROR."""
    err_console.print(message)
    return EXIT_ERROR


@dataclass
class CliContext:
    """Config and State for one CLI run, rooted in the same directory."""
    config: Config
    state: State
    # Explicitly selected root, or None for the default location.
    config_dir: Optional[Path] = None


# Context of the running command. Bound by use_context() once main()
# has parsed the arguments, never at import: building Config/State
# creates the config directory.
_context: Optional[CliContext] = None
config: Optional[Config] = None
state: Optional[State] = None


# Issue #221: `--config-dir DIR` wins over $MEMANGA_CONFIG_DIR, which
# wins over the platform default (issue #249). The selection lives in
# memanga.config so the GUI shares it.
def resolve_config_dir(cli_value=None) -> Optional[Path]:
    """Return the selected config root, or None for the default."""
    return explicit_config_dir(cli_value)


def build_context(config_dir=None, recover_state=True, root=None) -> CliContext:
    """Build Config and State under ``config_dir`` (None = default).

    ``root`` is the directory main() already resolved and locked for the
    default case, so Config and State never pick the default twice.
    Config is tolerant so a broken config.yaml still reaches `doctor`;
    main() refuses every other command (issue #250). ``recover_state``
    is False when the config directory is not locked (issue #244): a
    damaged state.json is then left as it is.
    """
    root = config_dir or root or default_config_dir()
    return CliContext(
        config=Config(root, tolerate_errors=True),
        state=State(root, recover=recover_state),
        config_dir=config_dir,
    )


# Issue #244: commands that only read config.yaml/state.json run while
# another process holds the config directory lock. Everything else,
# including any command added later, takes the lock.
READ_ONLY_COMMANDS = ("list", "ls", "status", "path", "open", "sources",
                      "export", "doctor")
READ_ONLY_CONFIG_ACTIONS = ("show", "get", "path")

# Held from before Config/State are loaded until main() has saved the
# last state; released by main().
_config_lock: Optional[ConfigDirLock] = None


def _needs_config_lock(args) -> bool:
    """True when the parsed command may change config or state."""
    if args.gui:
        return True
    if args.command in READ_ONLY_COMMANDS:
        return False
    if args.command == "config":
        action = getattr(args, "config_action", None)
        if action:
            return action not in READ_ONLY_CONFIG_ACTIONS
        return not args.show
    if args.command == "failed":
        return _failed_action(args) != "list"
    if args.command == "cron":
        return args.action != "status"
    if args.command == "search":
        # Only --add or the interactive prompt add a manga.
        return not args.json or args.add is not None
    return True


def _acquire_config_lock(config_dir: Path, required: bool = True) -> bool:
    """Lock ``config_dir`` for this process or exit 1 (issue #244).

    Nothing has been loaded or written yet when this refuses. With
    ``required=False`` a lock that cannot be taken returns False instead.
    """
    global _config_lock
    lock = ConfigDirLock(config_dir)
    try:
        lock.acquire()
    except ConfigDirBusy:
        if not required:
            return False
        sys.stderr.write(
            f"error: another MeManga process is using {config_dir} "
            "(a running check, the desktop app or another command).\n"
            "Wait for it to finish, then retry. Read-only commands such as "
            "`memanga list` and `memanga status` still work.\n"
        )
        sys.exit(EXIT_ERROR)
    except ConfigDirLockError as e:
        if not required:
            return False
        sys.stderr.write(
            f"error: cannot lock {config_dir}: {e.error.strerror or e.error}\n"
            "MeManga needs a config directory on a file system that "
            "supports file locks.\n"
        )
        sys.exit(EXIT_ERROR)
    _config_lock = lock
    return True


def _revalidate_default_root(root: Path, locked: bool) -> Path:
    """Return the default root to load, after the lock (issue #249).

    Another process may move the legacy ~/.config/memanga to the
    platform folder between default_config_dir() and taking the lock;
    this process would then lock a recreated, empty legacy folder and
    save where no normal start looks. Switch to the platform folder
    (locked when ``locked``) instead, or exit 1 if that is not possible.
    Nothing has been loaded yet.
    """
    if not default_root_moved(root):
        return root
    if locked:
        _release_config_lock()
    new_root = default_config_dir()
    if default_root_moved(new_root):
        sys.stderr.write(
            f"error: MeManga's config folder was just moved from {root}; "
            "nothing was changed. Retry the command.\n"
        )
        sys.exit(EXIT_ERROR)
    if locked:
        _acquire_config_lock(new_root)
    return new_root


def _release_config_lock():
    global _config_lock
    if _config_lock is not None:
        _config_lock.release()
        _config_lock = None


def use_context(ctx: CliContext) -> CliContext:
    """Make ``ctx`` the Config/State the command handlers operate on."""
    global _context, config, state
    _context = ctx
    config, state = ctx.config, ctx.state
    return ctx


# ============================================================================
# CLI Commands
# ============================================================================

VALID_STATUSES = ["reading", "on-hold", "dropped", "completed"]

# Issue #250: version of the `--json` payloads emitted by list, status,
# failed and doctor. Bump on incompatible changes (renamed/removed keys
# or changed types); adding keys is backwards compatible.
JSON_SCHEMA_VERSION = 1


def _print_json(payload):
    """Write a JSON payload to stdout with nothing else around it."""
    print(json.dumps(payload, indent=2))


def _non_negative_int_arg(value):
    """argparse type for whole numbers >= 0."""
    try:
        num = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(
            f"expected a non-negative integer, got {value!r}"
        )
    if num < 0:
        raise argparse.ArgumentTypeError(
            f"expected a non-negative integer, got {value!r}"
        )
    return num


def _mangadex_group_id_arg(value):
    """argparse type for --mangadex-remove-group: a MangaDex group UUID."""
    import uuid
    try:
        return str(uuid.UUID(value))
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(
            f"invalid group ID {value!r}: expected the UUID from the "
            "group's MangaDex page URL"
        )


def _partial_threshold_arg(value):
    """argparse type for --partial-threshold: a percentage in [0, 100].

    Rejects non-numeric or out-of-range input at parse time so both
    `config` and `check` give a clear error instead of silently clamping
    on the command line (issue #86).
    """
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(
            f"invalid threshold {value!r}: expected a number"
        )
    if not (0.0 <= num <= 100.0):
        raise argparse.ArgumentTypeError(
            f"threshold must be between 0 and 100, got {num:g}"
        )
    return num


def _get_status_display(manga: Dict[str, Any]) -> str:
    """Get formatted status display."""
    status = manga.get("status", "reading")
    colors = {
        "reading": "green",
        "on-hold": "yellow",
        "dropped": "red",
        "completed": "cyan",
    }
    return f"[{colors.get(status, 'white')}]{_esc(status)}[/]"


def _get_sources_display(manga: Dict[str, Any]) -> str:
    """Get display string for manga sources."""
    from urllib.parse import urlparse
    
    if "sources" in manga:
        sources = []
        for s in manga["sources"]:
            if isinstance(s, dict):
                url = s.get("url", "")
                source = s.get("source") or urlparse(url).netloc.replace("www.", "") or "?"
                sources.append(source)
            elif isinstance(s, str):
                sources.append(urlparse(s).netloc.replace("www.", ""))
        if len(sources) == 1:
            return sources[0]
        elif len(sources) > 1:
            return f"{sources[0]} (+{len(sources)-1})"
        return "?"
    return manga.get("source", "unknown")


# Issue #346: `list --sort` keys. "list" is the config order (the default).
LIST_SORT_KEYS = ["list", "title", "status", "last-chapter", "downloaded"]
DEFAULT_LIST_SORT = LIST_SORT_KEYS[0]

DEFAULT_EXPORT_FILE = "memanga_export.json"


def _list_sort_value(entry: Dict[str, Any], key: str):
    """Sort value for one `list` entry, or None to always sort it last."""
    if key == "title":
        return entry["title"].casefold()
    if key == "status":
        status = entry["status"]
        # Hand-edited unknown statuses have no rank, so they go last too.
        return VALID_STATUSES.index(status) if status in VALID_STATUSES else None
    if key == "last-chapter":
        if entry["last_chapter"] is None:
            return None
        return chapter_value(entry["last_chapter"])
    if key == "downloaded":
        return entry["downloaded_count"]
    return entry["n"]


def _list_entries(statuses=None, sort: str = DEFAULT_LIST_SORT, reverse: bool = False) -> List[Dict[str, Any]]:
    """Entries for `list` and `list --json`, filtered and sorted.

    `n` is always the position in the full list, so `#N` keeps working
    with edit/remove after filtering or sorting. Sorting is stable
    with ties kept in list order, and entries without a value (unknown
    status, no numeric last chapter) go last in either direction.
    """
    entries = []
    for i, manga in enumerate(config.get("manga", []), 1):
        title = manga["title"]
        sources = [s for s in _get_sources_from_manga(manga) if s.get("url")]
        primary = sources[0] if sources else {}
        entries.append({
            "n": i,
            "title": title,
            "status": manga.get("status", "reading"),
            "source": primary.get("source") or None,
            "source_display": _get_sources_display(manga),
            "url": primary.get("url") or None,
            "sources": sources,
            "last_chapter": state.get_last_chapter(title),
            "downloaded_count": len(state.get_downloaded_chapters(title)),
            "mode": manga.get("mode") or "auto",
            "send_to_kindle": bool(manga.get("send_to_kindle", True)),
            "backup_count": max(len(sources) - 1, 0),
        })
    if statuses:
        entries = [e for e in entries if e["status"] in statuses]
    if sort != "list" or reverse:
        valued = [(_list_sort_value(e, sort), e) for e in entries]
        ranked = sorted(
            (pair for pair in valued if pair[0] is not None),
            key=lambda pair: pair[0], reverse=reverse,
        )
        entries = [e for _, e in ranked] + [e for v, e in valued if v is None]
    return entries


def _list_payload(statuses=None, sort: str = DEFAULT_LIST_SORT, reverse: bool = False) -> Dict[str, Any]:
    """`list --json` payload: one entry per listed manga, in output order."""
    entries = _list_entries(statuses, sort, reverse)
    return {
        "schema_version": JSON_SCHEMA_VERSION,
        "count": len(entries),
        "manga": entries,
    }


def cmd_list(args):
    """List all tracked manga."""
    statuses = getattr(args, "status", None)
    sort = getattr(args, "sort", None) or DEFAULT_LIST_SORT
    reverse = getattr(args, "reverse", False)
    if getattr(args, "json", False):
        _print_json(_list_payload(statuses, sort, reverse))
        return

    if not config.get("manga", []):
        console.print("[dim]No manga tracked yet. Use [cyan]memanga add[/cyan] to add some![/dim]")
        return

    entries = _list_entries(statuses, sort, reverse)
    if not entries:
        console.print(f"[dim]No manga with status {_esc(', '.join(statuses))}.[/dim]")
        return
    
    table = _table(
        title="📚 Tracked Manga",
        box=box.ROUNDED,
        show_lines=True,
    )
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Title", style="cyan bold")
    table.add_column("Status", justify="center")
    table.add_column("Source", style="green")
    table.add_column("Last Ch.", style="yellow", justify="center")
    table.add_column("Downloaded", style="magenta", justify="center")
    # Issue #346: mode and the Kindle toggle share one stacked column so
    # the table still fits 80 columns. Source's "(+N)" is the backup count.
    table.add_column("Mode\nKindle", justify="center", no_wrap=True)

    for entry in entries:
        last_ch = entry["last_chapter"]

        table.add_row(
            str(entry["n"]),
            _esc(entry["title"]),
            _get_status_display(entry),
            _esc(entry["source_display"]),
            str(last_ch) if last_ch else "—",
            str(entry["downloaded_count"]),
            _esc(entry["mode"]) + "\n" + ("on" if entry["send_to_kindle"] else "off"),
        )
    
    console.print(table)


def _ask_fallback_days() -> int:
    """Prompt until the fallback delay is a whole number of days >= 0."""
    while True:
        days = IntPrompt.ask("⏱️  Fallback delay (days)", default=DEFAULT_FALLBACK_DELAY_DAYS)
        if days >= 0:
            return days
        console.print("[prompt.invalid]Please enter 0 or more days")


def cmd_add(args):
    """Add a manga to track."""
    from urllib.parse import urlparse
    
    backup_url = None
    fallback_days = DEFAULT_FALLBACK_DELAY_DAYS
    
    # Issue #238: flag-driven `add` never prompts; --force (alias --yes)
    # accepts an unsupported source or a similar title deliberately.
    force = getattr(args, 'force', False) or getattr(args, 'yes', False)
    can_prompt = bool(args.interactive)

    if args.interactive:
        if not _stdin_is_tty():
            return _non_interactive_error(
                "add --interactive needs a terminal; pass --title and --url instead"
            )
        # Interactive mode
        console.print("\n[bold green]➕ Add New Manga[/bold green]\n")
        
        # Issue #347: hundreds of domains are unreadable here; point at
        # `sources` instead of dumping them all.
        console.print(
            f"[dim]{len(get_supported_sources())} supported sources; "
            f"run `memanga sources` to see them.[/dim]\n"
        )
        
        title = Prompt.ask("📖 Manga title")
        if not title:
            return
        
        url = Prompt.ask("🔗 Primary source URL")
        if not url:
            return
        
        # Ask for backup source
        if Confirm.ask("Add a backup source?", default=False):
            backup_url = Prompt.ask("🔗 Backup source URL (e.g., MangaDex)")
            if backup_url:
                fallback_days = _ask_fallback_days()
    else:
        title = args.title
        url = args.url
        backup_url = getattr(args, 'backup', None)
        fallback_days = getattr(args, 'fallback_days', None)
        
        if not title or not url:
            return _error("[red]Error:[/red] --title and --url required (or use --interactive)")
        if fallback_days is not None and not backup_url:
            return _error(
                "[red]Error:[/red] --fallback-days needs a backup source "
                "(add one with --backup URL)"
            )
        if fallback_days is None:
            fallback_days = DEFAULT_FALLBACK_DELAY_DAYS
    
    # Extract source from URL
    parsed = urlparse(url)
    source = parsed.netloc.lower()
    if source.startswith("www."):
        source = source[4:]

    # Check if source is supported (exact or subdomain match)
    supported = get_supported_sources()
    source_ok = any(source == s or source.endswith("." + s) for s in supported)
    if not source_ok:
        err_console.print(f"[yellow]⚠️  Warning:[/yellow] '{_esc(source)}' might not be supported.")
        err_console.print("[dim]Run `memanga sources` to see supported sources.[/dim]")
        if not force:
            if not can_prompt:
                return _non_interactive_error(
                    f"'{source}' might not be supported; pass --force to add it anyway"
                )
            if not Confirm.ask("Add anyway?"):
                return
    
    # Build manga entry
    if backup_url:
        # New multi-source format
        manga_entry = {
            "title": title,
            "fallback_delay_days": fallback_days,
            "sources": [
                {"url": url},
                {"url": backup_url},
            ],
        }
    else:
        # Simple single-source format
        manga_entry = {
            "title": title,
            "source": source,
            "url": url,
        }

    # Issue #347: policy fields are written only when given, so a plain
    # `add` keeps the legacy defaults (reading / auto / Kindle on).
    status = getattr(args, 'status', None)
    mode = getattr(args, 'mode', None)
    kindle = getattr(args, 'send_to_kindle', None)
    if status is not None:
        manga_entry["status"] = status
    if mode is not None:
        manga_entry["mode"] = mode
    if kindle is not None:
        manga_entry["send_to_kindle"] = kindle
    
    # Try to fetch cover URL from the manga page
    if source_ok:
        try:
            scraper = get_scraper(source)
            cover_url = scraper.get_cover_url(url)
            if cover_url:
                manga_entry["cover_url"] = cover_url
        except Exception:
            pass

    manga_list = config.get("manga", [])

    # Check for exact duplicate
    for m in manga_list:
        if m["title"].lower() == title.lower():
            err_console.print(f"[yellow]⚠️  '{_esc(title)}' already exists![/yellow]")
            return EXIT_ERROR

    # Issue #246: titles that differ only in characters a file name drops
    # ("A:B" and "AB") would share one download folder and overwrite each
    # other's chapter files, so --force does not override this.
    owner = _download_folder_owner(title, manga_list)
    if owner is not None:
        return _error(
            f"[red]Error:[/red] '{_esc(title)}' would use the same download "
            f"folder as '{_esc(owner['title'])}'; pick another title"
        )

    # Check for similar titles (substring match)
    new_lower = title.lower()
    for m in manga_list:
        existing_lower = m["title"].lower()
        if (new_lower in existing_lower or existing_lower in new_lower) and new_lower != existing_lower:
            err_console.print(f"[yellow]⚠️  Similar manga already tracked: [cyan]{_esc(m['title'])}[/cyan][/yellow]")
            if not force:
                if not can_prompt:
                    return _non_interactive_error(
                        f"similar manga already tracked: '{m['title']}'; pass --force to add anyway"
                    )
                if not Confirm.ask("Add anyway?", default=False):
                    return
            break
    
    manga_list.append(manga_entry)
    config.set("manga", manga_list)
    config.save()
    
    if backup_url:
        backup_source = urlparse(backup_url).netloc.replace("www.", "")
        console.print(f"\n[green]✅ Added:[/green] {_esc(title)}")
        console.print(f"   [dim]Primary:[/dim] {_esc(source)}")
        console.print(f"   [dim]Backup:[/dim] {_esc(backup_source)} (after {fallback_days} days)")
    else:
        console.print(f"\n[green]✅ Added:[/green] {_esc(title)} ({_esc(source)})")


def _is_ascii_number(text: str) -> bool:
    """True for a non-empty run of 0-9 only (str.isdigit also accepts '²')."""
    return text.isascii() and text.isdigit()


def _find_manga(target: str, manga_list: list):
    """Resolve a target to one tracked manga (issue #237).

    `#N` picks the Nth entry in `memanga list`. Anything else is a title:
    an exact case-insensitive match wins, then a unique substring match.
    A bare number is a title too, so a manga called "86" stays reachable,
    but only as an exact match: "1" must never substring-hit "Mob Psycho 100".

    Returns (manga, index, candidates); manga is None when nothing or more
    than one entry matched, and candidates lists the ambiguous matches.
    """
    target = target.strip()
    if target.startswith("#") and _is_ascii_number(target[1:]):
        idx = int(target[1:]) - 1
        if 0 <= idx < len(manga_list):
            return manga_list[idx], idx, []
        return None, None, []

    needle = target.lower()
    exact = [i for i, m in enumerate(manga_list) if m["title"].lower() == needle]
    if len(exact) == 1:
        return manga_list[exact[0]], exact[0], []
    if exact or _is_ascii_number(target):
        matches = exact
    else:
        matches = [
            i for i, m in enumerate(manga_list) if needle and needle in m["title"].lower()
        ]
    if len(matches) == 1:
        return manga_list[matches[0]], matches[0], []
    return None, None, [manga_list[i] for i in matches]


def _target_error(target: str, candidates: list) -> int:
    """Report a target that matched no manga, or several (issue #237)."""
    if not candidates:
        err_console.print(f"[red]Not found:[/red] {_esc(target)}")
        if _is_ascii_number(target.strip()):
            err_console.print(
                f"[dim]A bare number must match a title exactly; "
                f"use '#{target.strip()}' for the list index.[/dim]"
            )
        err_console.print("[dim]Use 'memanga list' to see tracked manga.[/dim]")
        return EXIT_ERROR
    err_console.print(
        f"[red]Ambiguous:[/red] {_esc(target)} matches {len(candidates)} manga:"
    )
    for m in candidates:
        err_console.print(f"  [cyan]{_esc(m['title'])}[/cyan]")
    err_console.print("[dim]Use the full title, or '#N' from 'memanga list'.[/dim]")
    return EXIT_ERROR


def _shares_download_dir(title: str, others) -> bool:
    """True if another tracked manga writes to the same download folder."""
    return _download_folder_owner(title, others) is not None


def _download_folder_owner(title: str, others):
    """The tracked manga in ``others`` that writes to the same download
    folder as ``title``, or None.

    Sanitizing can map different titles to one folder ("A:B" and "AB"),
    and case-insensitive filesystems merge "x" and "X" too.
    """
    from .downloader import _download_folder_key
    key = _download_folder_key(title)
    return next((m for m in others
                 if _download_folder_key(m.get("title", "")) == key), None)


def cmd_remove(args):
    """Remove a manga from tracking.

    Issue #349: download history and downloaded files are kept unless
    explicitly requested. ``--yes`` only answers the removal confirmation;
    it never implies --purge-history or --delete-files.
    """
    from .downloader import (UnsafeDownloadPathError, delete_manga_downloads,
                             find_manga_downloads)

    # getattr: the TUI builds its own Namespace without these flags.
    purge_history = (getattr(args, "purge_history", False)
                     or getattr(args, "purge", False))
    keep_files = getattr(args, "keep_files", False)
    delete_files = getattr(args, "delete_files", False)
    if keep_files and delete_files:
        return _error("[red]--keep-files and --delete-files are mutually exclusive.[/red]")

    manga_list = config.get("manga", [])

    if not manga_list:
        return _error("[yellow]No manga to remove.[/yellow]")

    found, found_idx, candidates = _find_manga(args.target, manga_list)

    if not found:
        return _target_error(args.target, candidates)

    if not args.yes and not _stdin_is_tty():
        return _non_interactive_error(
            f"refusing to remove '{found['title']}' without confirmation; pass --yes"
        )

    title = found["title"]
    others = manga_list[:found_idx] + manga_list[found_idx + 1:]

    # Resolve the file target before anything is written, so an unsafe
    # --delete-files request leaves config, state and files untouched.
    files_dir = None
    if delete_files:
        if _shares_download_dir(title, others):
            return _error(
                f"[red]Refusing to delete files:[/red] another tracked manga "
                f"uses the same download folder as {_esc(title)}."
            )
        try:
            files_dir = find_manga_downloads(config.download_dir, title)
        except (UnsafeDownloadPathError, OSError) as e:
            return _error(f"[red]Refusing to delete files:[/red] {_esc(e)}")

    if not args.yes:
        prompt = f"Remove [cyan]{_esc(title)}[/cyan]"
        if files_dir is not None:
            prompt += f" and delete [yellow]{_esc(files_dir)}[/yellow]"
        if not Confirm.ask(prompt + "?"):
            return None
        # Interactive runs may opt in to extra cleanup; both default to
        # no and are asked before anything is written (issues #237/#349).
        if not purge_history:
            purge_history = Confirm.ask("Also remove download history?", default=False)
        if not keep_files and not delete_files and not _shares_download_dir(title, others):
            try:
                candidate = find_manga_downloads(config.download_dir, title)
            except (UnsafeDownloadPathError, OSError):
                candidate = None
            if candidate is not None and Confirm.ask(
                    f"Also delete downloaded files in [yellow]{_esc(candidate)}[/yellow]?",
                    default=False):
                delete_files, files_dir = True, candidate

    manga_list.pop(found_idx)
    config.set("manga", manga_list)
    config.save()

    if purge_history:
        manga_state = state.get("manga", {})
        if title in manga_state:
            del manga_state[title]
            state.set("manga", manga_state)

    console.print(f"[red]🗑️  Removed:[/red] {_esc(title)}")
    if purge_history:
        console.print("[dim]Download history removed.[/dim]")

    if delete_files:
        try:
            deleted = delete_manga_downloads(config.download_dir, title)
        except (UnsafeDownloadPathError, OSError) as e:
            return _error(
                f"[red]Removed from tracking, but could not delete its files:[/red] {_esc(e)}"
            )
        if deleted is None:
            console.print("[dim]No downloaded files to delete.[/dim]")
        else:
            console.print(f"[dim]Deleted downloaded files: {_esc(deleted)}[/dim]")


def cmd_set_status(args):
    """Set manga status (reading, on-hold, dropped, completed).

    Deprecated by issue #348: `edit TARGET --status STATUS` replaces it.
    Kept for one release, hidden from help and completion; stdout and
    exit codes are unchanged so existing scripts keep working.
    """
    import shlex

    sys.stderr.write(
        "warning: 'memanga set' is deprecated and will be removed in the next "
        "release; use: memanga edit "
        f"{shlex.quote(args.target)} --status {shlex.quote(args.status)}\n"
    )
    manga_list = config.get("manga", [])
    
    if not manga_list:
        return _error("[yellow]No manga tracked.[/yellow]")
    
    new_status = args.status.lower()

    if new_status not in VALID_STATUSES:
        err_console.print(f"[red]Invalid status:[/red] {_esc(new_status)}")
        err_console.print(f"[dim]Valid: {', '.join(VALID_STATUSES)}[/dim]")
        return EXIT_ERROR

    found, found_idx, candidates = _find_manga(args.target, manga_list)

    if not found:
        return _target_error(args.target, candidates)

    old_status = found.get("status", "reading")
    manga_list[found_idx]["status"] = new_status
    config.set("manga", manga_list)
    config.save()
    
    # Status colors
    colors = {"reading": "green", "on-hold": "yellow", "dropped": "red", "completed": "cyan"}
    old_color = colors.get(old_status, "white")
    new_color = colors.get(new_status, "white")
    
    console.print(
        f"[cyan]{_esc(found['title'])}[/cyan]: "
        f"[{old_color}]{_esc(old_status)}[/] → [{new_color}]{_esc(new_status)}[/]"
    )


_PLAIN_CHAPTER = re.compile(r"[0-9]+(?:\.[0-9]+)?")


def _chapter_lookup(tokens, known):
    """Resolve CHAPTER arguments to the labels stored for a manga (#356).

    The GUI matches read chapters by their exact label, so each argument
    must name a stored label: an exact match wins, then a plain number
    ("5", "05", "5.0") matches the one plain-number label of equal value.
    Labels such as "Chapter 5" or "5 Part 1" only match exactly.

    Returns (resolved, unknown, ambiguous): resolved labels in argument
    order without duplicates, arguments matching nothing, and arguments
    matching several labels (mapped to those labels).
    """
    known = list(dict.fromkeys(str(k) for k in known))
    plain = [k for k in known if _PLAIN_CHAPTER.fullmatch(k)]
    resolved, unknown, ambiguous = [], [], {}
    for token in tokens:
        token = token.strip()
        if token in known:
            matches = [token]
        elif _PLAIN_CHAPTER.fullmatch(token):
            matches = [k for k in plain if float(k) == float(token)]
        else:
            matches = []
        if not matches:
            unknown.append(token)
        elif len(matches) > 1:
            ambiguous[token] = matches
        elif matches[0] not in resolved:
            resolved.append(matches[0])
    return resolved, unknown, ambiguous


def _chapter_list_text(chapters) -> str:
    return ", ".join(_esc(ch) for ch in chapters)


def cmd_read(args):
    """Mark chapters of a tracked manga read or unread (issue #356).

    Writes the same per-chapter read set the desktop reader and the
    Library/Detail pages use. Marking read also clears the chapter's
    saved in-chapter position, as finishing it in the reader does;
    unread only drops it from the read set. Files, download history
    and the "continue reading" chapter are never changed.

    Every CHAPTER is checked before anything is written, so one bad
    argument leaves the state untouched.
    """
    mark_read = args.mark_read
    manga_list = config.get("manga", [])

    if not manga_list:
        return _error("[yellow]No manga tracked.[/yellow]")

    found, _, candidates = _find_manga(args.target, manga_list)

    if not found:
        return _target_error(args.target, candidates)

    title = found["title"]
    read_set = state.get_read_chapters(title)
    downloaded = state.get_downloaded_chapters(title)

    if args.all:
        if mark_read:
            chapters = sorted(dict.fromkeys(str(ch) for ch in downloaded),
                              key=chapter_sort_key)
            if not chapters:
                console.print(f"[dim]No downloaded chapters of {_esc(title)} to mark read.[/dim]")
                return None
        else:
            chapters = sorted(read_set, key=chapter_sort_key)
            if not chapters:
                console.print(f"[dim]No chapters of {_esc(title)} are marked read.[/dim]")
                return None
    else:
        # The chapters the desktop app lists for this manga (its Detail
        # page), plus, for unread, anything already in the read set.
        known = [entry.get("number", "") for entry in state.get_available_chapters(title)]
        known += downloaded + state.get_external_chapters(title)
        if not mark_read:
            known += read_set
        known = [str(k) for k in known if str(k)]
        chapters, unknown, ambiguous = _chapter_lookup(args.chapters, known)
        if unknown or ambiguous:
            for token in unknown:
                err_console.print(
                    f"[red]Unknown chapter:[/red] {_esc(token)} is not in the "
                    f"chapter list of {_esc(title)}"
                )
            for token, matches in ambiguous.items():
                err_console.print(
                    f"[red]Ambiguous chapter:[/red] {_esc(token)} matches "
                    f"{_chapter_list_text(matches)}; give the exact label"
                )
            err_console.print("[dim]Nothing was changed.[/dim]")
            return EXIT_ERROR

    if mark_read:
        changed = [ch for ch in chapters if ch not in read_set]
        # Only chapters becoming read: an already-read chapter may have
        # been reopened, and its new saved page must survive.
        for ch in changed:
            state.mark_chapter_read(title, ch)
            # A finished chapter reopens at its start, as in the reader.
            state.clear_reader_position(title, ch)
    else:
        changed = [ch for ch in chapters if ch in read_set]
        for ch in changed:
            state.unmark_chapter_read(title, ch)
    state.flush()

    verb = "read" if mark_read else "unread"
    unchanged = [ch for ch in chapters if ch not in changed]
    if changed:
        noun = "chapter" if len(changed) == 1 else "chapters"
        console.print(
            f"[green]✅ Marked {len(changed)} {noun} of {_esc(title)} {verb}:[/green] "
            f"{_chapter_list_text(changed)}"
        )
    if unchanged:
        console.print(f"[dim]Already {verb}: {_chapter_list_text(unchanged)}[/dim]")


# Issue #357: how long `open` waits for the opener to report an error.
# An opener still running after that has launched the file manager.
_OPENER_WAIT_SECONDS = 5


def _has_downloaded_files(folder: Path) -> bool:
    """True if ``folder`` holds a file at any depth (issue #357).

    Image formats save each chapter as a sub-folder of pages, so files
    are searched recursively. Hidden files such as .DS_Store don't
    count. Read-only: symlinked sub-folders are not followed.
    """
    for _, _, files in os.walk(folder):
        if any(not name.startswith(".") for name in files):
            return True
    return False


def _manga_download_folder(target):
    """Resolve TARGET to its download folder for `path` and `open` (#357).

    The folder is ``<download dir>/<sanitized title>``, where downloads
    are written. Returns (folder, None) when it exists, else (None, exit
    code) after reporting the problem on stderr. Nothing is created.
    """
    from .downloader import _sanitize_filename

    manga_list = config.get("manga", [])
    if not manga_list:
        return None, _error("[yellow]No manga tracked.[/yellow]")

    found, _, candidates = _find_manga(target, manga_list)
    if not found:
        return None, _target_error(target, candidates)

    title = found["title"]
    # absolute(), not resolve(): keep a symlinked folder at the path the
    # user configured. The leading separator also keeps a title such as
    # "-x" from being read as an option by the opener.
    folder = (Path(config.download_dir) / _sanitize_filename(title)).absolute()
    if folder.is_dir():
        if _has_downloaded_files(folder):
            return folder, None
    elif os.path.lexists(folder):
        err_console.print(
            f"[red]Not a folder:[/red] {_esc(folder)} (downloads of {_esc(title)})",
            soft_wrap=True,
        )
        return None, EXIT_ERROR
    if sys.platform == "win32":
        quoted = subprocess.list2cmdline([title])
    else:
        import shlex
        quoted = shlex.quote(title)
    err_console.print(f"[yellow]No downloads for {_esc(title)} yet.[/yellow]")
    err_console.print(f"[dim]Expected folder: {_esc(folder)}[/dim]", soft_wrap=True)
    err_console.print(
        f"[dim]Download chapters with: memanga check {_esc(quoted)} --download[/dim]",
        soft_wrap=True,
    )
    return None, EXIT_ERROR


def _open_folder(folder: Path) -> Optional[str]:
    """Open ``folder`` in the OS file manager; return an error or None.

    Same platform split as the GUI's folder buttons, but the folder must
    already exist and failures are reported instead of swallowed.
    """
    if sys.platform == "win32":
        try:
            os.startfile(str(folder))  # type: ignore[attr-defined]
        except OSError as e:
            return str(e)
        return None

    if sys.platform == "darwin":
        opener = "open"
    else:
        opener = shutil.which("xdg-open")
        if not opener:
            return "xdg-open was not found (is a desktop environment installed?)"
    try:
        # An argv list, never a shell. stdout stays clean for the caller;
        # the opener's own stderr explains failures such as no display.
        proc = subprocess.Popen(
            [opener, str(folder)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as e:
        return f"could not run {os.path.basename(opener)}: {e}"
    try:
        code = proc.wait(timeout=_OPENER_WAIT_SECONDS)
    except subprocess.TimeoutExpired:
        # Still running: it launched the file manager in the foreground.
        # Leave it open.
        return None
    if code != 0:
        return f"{os.path.basename(opener)} exited with status {code}"
    return None


def cmd_path(args):
    """Print the download folder of a tracked manga (issue #357).

    stdout carries only the absolute path, for scripts; a manga with no
    downloaded files yet is an error, reported on stderr.
    """
    folder, code = _manga_download_folder(args.target)
    if folder is None:
        return code
    sys.stdout.write(f"{folder}\n")
    return None


def cmd_open(args):
    """Open the download folder of a tracked manga (issue #357)."""
    folder, code = _manga_download_folder(args.target)
    if folder is None:
        return code
    problem = _open_folder(folder)
    if problem:
        err_console.print(f"[red]Could not open the folder:[/red] {_esc(problem)}")
        err_console.print(f"[dim]Folder: {_esc(folder)}[/dim]", soft_wrap=True)
        return EXIT_ERROR
    console.print(f"[green]📂 Opened:[/green] {_esc(folder)}", soft_wrap=True)
    return None


_HOST_LABEL = re.compile(r"^[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?$")


def _is_http_url(value: str) -> bool:
    """True for an http(s) URL with a valid hostname (and port, if any).

    Malformed input such as ``http://[`` makes urlparse raise ValueError;
    that is reported as "not a URL" rather than a traceback.
    """
    import ipaddress
    from urllib.parse import urlparse
    try:
        parsed = urlparse(value)
        host = parsed.hostname
        parsed.port  # raises ValueError for a non-numeric/out-of-range port
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not host:
        return False
    if parsed.netloc.rpartition("@")[2].startswith("["):
        try:
            ipaddress.IPv6Address(host)
        except ValueError:
            return False
        return True
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return False
    labels = ascii_host[:-1].split(".") if ascii_host.endswith(".") else ascii_host.split(".")
    return len(ascii_host) <= 253 and all(_HOST_LABEL.match(label) for label in labels)


def _source_from_url(url: str) -> str:
    """Scraper source key for a validated URL: its canonical hostname.

    Unlike netloc this drops userinfo and port (so credentials never end up
    in the stored source), strips a trailing dot and a leading ``www.``, and
    IDNA-encodes the host so get_scraper() can match it.
    """
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").rstrip(".")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        pass
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


def cmd_update(args):
    """Edit a tracked manga's sources, title and per-manga settings (issue #350)."""
    import copy

    manga_list = config.get("manga", [])

    if not manga_list:
        return _error("[yellow]No manga tracked.[/yellow]")

    found, found_idx, candidates = _find_manga(args.target, manga_list)

    if not found:
        return _target_error(args.target, candidates)

    old_title = found["title"]
    url = args.url
    backup = args.backup
    no_backup = getattr(args, "no_backup", False)
    title = args.title
    fallback_days = getattr(args, "fallback_days", None)
    status = getattr(args, "status", None)
    mode = getattr(args, "mode", None)
    kindle = getattr(args, "send_to_kindle", None)

    requested = (url, backup, title, fallback_days, status, mode, kindle)
    if all(value is None for value in requested) and not no_backup:
        return _error(
            "[yellow]No changes specified. Use --url, --backup, --no-backup, "
            "--fallback-days, --title, --status, --mode or --kindle/--no-kindle.[/yellow]"
        )

    # Issue #350: validate every requested value before touching config, so
    # a bad combination never leaves a half-applied edit behind.
    if url is not None:
        url = url.strip()
        if not _is_http_url(url):
            return _error(f"[red]Error:[/red] --url needs an http(s) URL, got {_esc(repr(url))}")
    if backup is not None:
        backup = backup.strip()
        if not backup:
            return _error("[red]Error:[/red] --backup needs a URL; use --no-backup to remove the backup")
        if not _is_http_url(backup):
            return _error(f"[red]Error:[/red] --backup needs an http(s) URL, got {_esc(repr(backup))}")
    if title is not None:
        title = title.strip()
        if not title:
            return _error("[red]Error:[/red] --title cannot be empty")
        others = [m for i, m in enumerate(manga_list) if i != found_idx]
        for m in others:
            if m["title"].lower() == title.lower():
                return _error(f"[red]Error:[/red] '{_esc(m['title'])}' already exists; pick another title")
        # Same folder as another manga: see cmd_add (issue #246).
        owner = _download_folder_owner(title, others)
        if owner is not None:
            return _error(
                f"[red]Error:[/red] '{_esc(title)}' would use the same download "
                f"folder as '{_esc(owner['title'])}'; pick another title"
            )

    # Legacy entries keep `source`/`url`; multi-source entries keep a
    # `sources` list whose items are dicts or bare URL strings.
    sources = found.get("sources") if "sources" in found else None
    entry_urls = [s.get("url", "") if isinstance(s, dict) else (s or "") for s in sources or []]
    current_url = entry_urls[0] if sources is not None and entry_urls else found.get("url", "")
    backup_count = max(len(entry_urls) - 1, 0)
    current_backup = entry_urls[1] if backup_count else ""

    if no_backup and fallback_days is not None:
        return _error(
            "[red]Error:[/red] --fallback-days cannot be combined with --no-backup "
            "(removing the backup also removes its fallback delay)"
        )
    if fallback_days is not None and backup is None and not backup_count:
        return _error(
            f"[red]Error:[/red] '{_esc(old_title)}' has no backup source; "
            "--fallback-days needs one (add it with --backup URL)"
        )
    if backup is not None and url is None and not current_url:
        return _error(
            f"[red]Error:[/red] '{_esc(old_title)}' has no primary source; "
            "set one with --url before adding a backup"
        )

    edited = copy.deepcopy(found)
    changes = []

    # Update URL
    if url is not None and url != current_url:
        new_source = _source_from_url(url)
        if "sources" in edited and edited["sources"]:
            edited["sources"][0] = {"url": url, "source": new_source}
        elif "sources" in edited:
            edited["sources"] = [{"url": url, "source": new_source}]
        else:
            edited["source"] = new_source
            edited["url"] = url
        changes.append(f"URL → {new_source}")

    # Update backup (replaces the first backup; further backups are kept)
    if backup is not None and backup != current_backup:
        backup_source = _source_from_url(backup)
        if "sources" in edited:
            if len(edited["sources"]) > 1:
                edited["sources"][1] = {"url": backup, "source": backup_source}
            else:
                edited["sources"].append({"url": backup, "source": backup_source})
        else:
            # Convert to multi-source format
            primary_url = edited.pop("url", "")
            primary_source = edited.pop("source", "")
            edited["sources"] = [
                {"url": primary_url, "source": primary_source},
                {"url": backup, "source": backup_source},
            ]
            edited.setdefault("fallback_delay_days", 2)
        changes.append(f"Backup → {backup_source}")

    # Remove every backup, and the fallback delay that only applies to
    # them (same as clearing the backup in the desktop app).
    if no_backup and backup_count:
        edited["sources"] = edited["sources"][:1]
        edited.pop("fallback_delay_days", None)
        changes.append("Backup removed" if backup_count == 1 else f"Backups removed ({backup_count})")
    elif no_backup and "fallback_delay_days" in edited:
        # Primary-only (legacy/imported) entry with a leftover delay: there
        # is no backup to remove, but the stale delay goes too.
        edited.pop("fallback_delay_days")
        changes.append("Stale fallback delay removed")

    if fallback_days is not None and fallback_days != edited.get(
            "fallback_delay_days", DEFAULT_FALLBACK_DELAY_DAYS):
        edited["fallback_delay_days"] = fallback_days
        changes.append(f"Fallback delay → {fallback_days} day{'' if fallback_days == 1 else 's'}")

    if status is not None and status != found.get("status", "reading"):
        edited["status"] = status
        changes.append(f"Status → {status}")
    if mode is not None and mode != (found.get("mode") or "auto"):
        edited["mode"] = mode
        changes.append(f"Mode → {mode}")
    if kindle is not None and kindle != bool(found.get("send_to_kindle", True)):
        edited["send_to_kindle"] = kindle
        changes.append(f"Kindle → {'on' if kindle else 'off'}")

    # Rename title
    if title is not None and title != old_title:
        edited["title"] = title
        # Migrate state (download history) to new title
        state.rename_manga(old_title, title)
        # Move already-downloaded files so they stay reachable under the
        # new title (folder + filenames are keyed by title).
        from .downloader import rename_manga_downloads
        try:
            rename_manga_downloads(config.download_dir, old_title, title)
        except Exception:
            pass
        changes.append(f"Title → {title}")

    if not changes:
        console.print(f"[dim]No changes: [cyan]{_esc(old_title)}[/cyan] already has those settings.[/dim]")
        return

    manga_list[found_idx] = edited
    config.set("manga", manga_list)
    config.save()

    console.print(f"[green]Updated [cyan]{_esc(old_title)}[/cyan]:[/green]")
    for c in changes:
        console.print(f"  {_esc(c)}")


def _chapter_label(ch) -> str:
    """`Chapter N` or `Chapter N: title`, escaped for Rich markup
    (chapter titles are scraped data)."""
    label = f"Chapter {ch.number}"
    if ch.title:
        label += f": {ch.title}"
    return _esc(label)


class _ConsoleChapterReporter(ChapterReporter):
    """Prints chapter-pipeline progress the way `check` always has:
    progress and saves on stdout; warnings and failures are log records
    on stderr (see :func:`_diagnostic`)."""

    def downloading(self, chapter):
        source_info = ""
        if isinstance(chapter, ChapterWithSource) and chapter.is_backup:
            source_info = f" [yellow](from backup: {_esc(chapter.source)})[/yellow]"
        console.print(f"     [dim]⬇️  Downloading {_chapter_label(chapter)}...{source_info}[/dim]")

    def trying_backup(self, error, backup_chapter):
        _diagnostic(
            logging.WARNING,
            f"     [yellow]⚠️  Primary failed ({_esc(error)}), trying backup ({_esc(backup_chapter.source)})...[/yellow]",
            "Chapter %s: primary failed (%s), trying backup (%s)",
            backup_chapter.number, error, backup_chapter.source,
        )

    def backup_failed(self, error):
        _diagnostic(logging.ERROR,
                    f"     [red]❌ Backup also failed: {_esc(error)}[/red]",
                    "Backup also failed: %s", error)

    def saved(self, outcome):
        path = outcome.path
        name = f"{path.parent.name}/{path.name}/" if path.is_dir() else path.name
        label = _esc(name)
        src = " from backup" if outcome.from_backup else ""
        if outcome.status is ChapterStatus.PARTIAL:
            miss = outcome.missing_pages
            _diagnostic(
                logging.WARNING,
                f"     [yellow]⚠️  Saved partial{src}: {label} — "
                f"{len(miss)}/{outcome.total_pages} page(s) missing (pages {_esc(miss)})[/yellow]",
                "Saved partial%s: %s — %d/%d page(s) missing (pages %s)",
                src, name, len(miss), outcome.total_pages, miss,
            )
        else:
            console.print(f"     [green]✅ Saved{src}: {label}[/green]")

    def email_skipped_folder(self, path):
        console.print("     [dim]📧 Skipped email (image folders cannot be emailed)[/dim]")

    def email_sending(self, path):
        console.print("     [dim]📧 Sending to Kindle...[/dim]")

    def email_sent(self, path):
        console.print("     [green]📬 Sent to Kindle![/green]")

    def deleted_after_send(self, path):
        console.print("     [dim]🗑️  Deleted local copy[/dim]")

    def delete_failed(self, path, error):
        _diagnostic(
            logging.WARNING,
            f"     [yellow]⚠️  Could not delete local copy: {_esc(error)}[/yellow]",
            "Could not delete local copy %s: %s", path, error,
        )

    def email_failed(self, error):
        _diagnostic(logging.ERROR,
                    f"     [red]📧 Email failed: {_esc(error)}[/red]",
                    "Email failed: %s", error)

    def failed(self, outcome):
        _diagnostic(logging.ERROR,
                    f"     [red]❌ Failed: {_esc(outcome.error)}[/red]",
                    "Chapter %s: Failed: %s", outcome.chapter, outcome.error)


def _chapter_pipeline(output_format=None, max_retries=DEFAULT_PAGE_RETRIES,
                      allow_partial=None, partial_threshold=None) -> ChapterPipeline:
    """The chapter pipeline shared by `check` and `failed retry` (#352,
    #222), configured from config and printing to the console.

    Partial-chapter tolerance (issue #86) comes from config unless the
    caller overrides it for a single run.
    """
    if allow_partial is None:
        allow_partial = config.partial_enabled
    if partial_threshold is None:
        partial_threshold = config.partial_threshold
    options = PipelineOptions(
        download_dir=config.download_dir,
        output_format=output_format or config.output_format,
        max_retries=max_retries,
        post_processing=config.get("delivery.post_processing"),
        allow_partial=allow_partial,
        partial_threshold=partial_threshold,
        delivery_mode=config.delivery_mode,
        email=config.get("email", {}),
        delete_after_send=config.get("delivery.delete_after_send", False),
    )
    # Bind the collaborators imported here rather than the pipeline's
    # defaults, so this module stays the one place to replace them.
    return ChapterPipeline(
        options=options,
        state=state,
        reporter=_ConsoleChapterReporter(),
        download=download_chapter,
        find_backup=_find_chapter_on_backup,
        send=send_to_kindle,
        app_password=lambda: get_app_password(config),
    )


class StateCheckpointError(Exception):
    """state.json could not be written after a chapter (issue #230)."""


def _checkpoint_state():
    """Write state now; raise StateCheckpointError on failure.

    save(), not flush(): some mutators save() without marking state
    dirty, so after one of them failed flush() would see nothing to
    write. The write is atomic; a failure leaves the previous file.
    """
    try:
        state.save()
    except Exception as e:
        raise StateCheckpointError(str(e)) from e


def _process_chapter(pipeline: ChapterPipeline, manga, chapter):
    """Run one chapter through ``pipeline`` and persist the result before
    the caller moves on (issue #230).

    The pipeline only marks state dirty (the GUI batches its writes), so
    without this a CLI process killed later in a long run lost chapters
    it had already saved and sent, and the next run sent them again.
    The checkpoint also runs when the chapter raised, so whatever was
    recorded before the error is kept. If it fails, StateCheckpointError
    propagates past the per-manga error handling and ends the command:
    continuing would download and deliver chapters that cannot be
    recorded.
    """
    try:
        outcome = pipeline.process(manga, chapter)
    except Exception:
        _checkpoint_state()
        raise
    _checkpoint_state()
    return outcome


def _check_summary_line(dry_run, checked, new, downloaded, failed,
                        errored, unconfirmed) -> str:
    """The single plain-text summary of a `check` run (issue #226)."""
    if dry_run:
        line = f"Dry run: {new} chapter(s) available for download"
    elif new == 0:
        line = "Summary: no new chapters found"
    else:
        line = (f"Summary: {downloaded}/{new} chapters downloaded, "
                f"{failed} failed")
    line += f"; checked {checked} manga, {errored} could not be checked"
    if unconfirmed:
        line += f", {unconfirmed} chapter(s) need confirmation"
    return line


def cmd_check(args):
    """Check for new chapters and download them.

    Modes (#351):
      - ``--dry-run``: check only. Lists what a download run would fetch;
        never downloads, delivers or changes state. Wins over every
        download flag.
      - ``--download`` (aliases ``--auto``/``--yes``): download without
        prompting.
      - otherwise: ask per chapter on a terminal. Without a terminal, or
        with ``--quiet``, nothing is downloaded and the run exits 1.
    """
    manga_list = config.get("manga", [])
    
    if not manga_list and not args.title:
        console.print("[yellow]No manga tracked. Use 'memanga add' first![/yellow]")
        return
    
    # Filter to specific manga if provided
    if args.title:
        found, _, candidates = _find_manga(args.title, manga_list)
        if not found:
            return _target_error(args.title, candidates)
        manga_list = [found]
    
    from_chapter = getattr(args, 'from_chapter', None)
    if getattr(args, 'all', False):
        from_chapter = 0
    dry_run = getattr(args, 'dry_run', False)
    # `--auto`/`--yes` are aliases of `--download`; programmatic callers
    # (the TUI) may still pass the old attribute names.
    download = (
        getattr(args, 'download', False)
        or getattr(args, 'auto', False)
        or getattr(args, 'yes', False)
    )
    # --quiet never prompts; it is not permission to download.
    can_prompt = _stdin_is_tty() and not getattr(args, 'quiet', False)

    console.print(f"[dim]=== {datetime.now().strftime('%Y-%m-%d %H:%M')} ===[/dim]")

    if dry_run:
        console.print(_panel("[bold]🔍 Dry Run — Check Only (nothing is downloaded or recorded)[/bold]", border_style="yellow"))
    elif from_chapter is not None and from_chapter == 0:
        console.print(_panel("[bold]📥 Downloading All Chapters[/bold]", border_style="green"))
    elif from_chapter is not None:
        console.print(_panel(f"[bold]📥 Downloading from Chapter {from_chapter}[/bold]", border_style="green"))
    else:
        console.print(_panel("[bold]🔍 Checking for New Chapters[/bold]", border_style="blue"))
    console.print()
    
    total_new = 0
    total_downloaded = 0
    total_failed = 0
    # Manga checked, and those whose check itself errored (#239).
    total_checked = 0
    total_errored = 0
    # Chapters left undownloaded because no one could confirm them (#258).
    total_unconfirmed = 0

    # Partial-chapter tolerance (issue #86). Config is the source of truth;
    # `check` flags can override it for a single run.
    allow_partial = None
    if getattr(args, 'allow_partial', False):
        allow_partial = True
    if getattr(args, 'no_partial', False):
        allow_partial = False
    pipeline = _chapter_pipeline(
        output_format=getattr(args, 'format', None),
        max_retries=getattr(args, 'retries', DEFAULT_PAGE_RETRIES),
        allow_partial=allow_partial,
        partial_threshold=getattr(args, 'partial_threshold', None),
    )
    delivery_mode = pipeline.options.delivery_mode
    download_dir = pipeline.options.download_dir

    for manga in manga_list:
        title = manga["title"]
        status = manga.get("status", "reading")
        
        # Skip non-reading manga unless explicitly specified by title
        if status != "reading" and not args.title:
            console.print(f"[dim]Skipping:[/dim] [cyan]{_esc(title)}[/cyan] {_esc(f'[{status}]')}")
            continue
        
        console.print(f"[dim]Checking:[/dim] [cyan]{_esc(title)}[/cyan]...")
        total_checked += 1
        
        try:
            force_suspicious = getattr(args, 'force_suspicious', False)
            check_kwargs = dict(
                from_chapter=from_chapter,
                force_suspicious=force_suspicious,
            )
            report = {}
            if dry_run:
                check_kwargs.update(dry_run=True, report=report)
            new_chapters = check_for_updates(manga, state, **check_kwargs)

            # A batch that doesn't fit this manga's history was withheld
            # because it couldn't be confirmed by a backup source. A dry run
            # records nothing, so report what this preview decided rather
            # than a persisted record it would have cleared or replaced.
            if dry_run:
                suspicious = report.get("withheld")
            else:
                suspicious = state.get_suspicious_batch(title) if from_chapter is None else None
            if suspicious:
                reasons = list(suspicious.get("reasons", []))
                reasons.append(suspicious.get("backup_status"))
                if dry_run:
                    advice = ("A download run would skip these chapters. Run "
                              "'memanga check --download --force-suspicious' "
                              "to accept anyway.")
                else:
                    advice = ("Skipped auto-delivery. Run "
                              "'memanga check --force-suspicious' to accept anyway.")
                markup = "\n".join(
                    [f"  [yellow]└─ Warning: Suspicious chapter batch detected: "
                     f"{_esc(suspicious.get('count'))} chapter(s) up to "
                     f"{_esc(suspicious.get('highest'))} "
                     f"(last tracked: {_esc(suspicious.get('last_chapter'))})[/yellow]"]
                    + [f"     [dim]- {_esc(reason)}[/dim]" for reason in reasons]
                    + [f"     [yellow]{_esc(advice)}[/yellow]"]
                )
                _diagnostic(
                    logging.WARNING, markup,
                    "%s: Suspicious chapter batch detected: %s chapter(s) up to "
                    "%s (last tracked: %s); %s; %s",
                    title, suspicious.get("count"), suspicious.get("highest"),
                    suspicious.get("last_chapter"),
                    "; ".join(str(r) for r in reasons), advice,
                )
            elif dry_run and report.get("forced"):
                _diagnostic(
                    logging.WARNING,
                    f"  [yellow]└─ --force-suspicious: includes {_esc(report['forced'])} "
                    "chapter(s) from a suspicious batch; a download run with "
                    "this flag would accept it.[/yellow]",
                    "%s: --force-suspicious: includes %s chapter(s) from a "
                    "suspicious batch; a download run with this flag would "
                    "accept it.", title, report["forced"],
                )

            if not new_chapters:
                if not suspicious:
                    console.print("  [dim]└─ No new chapters[/dim]")
                continue
            
            console.print(f"  [green]└─ {len(new_chapters)} new chapter(s)![/green]")
            total_new += len(new_chapters)
            
            for ch in new_chapters:
                ch_label = _chapter_label(ch)

                # Dry run: just list chapters
                if dry_run:
                    source_info = ""
                    if isinstance(ch, ChapterWithSource) and ch.is_backup:
                        source_info = f" [yellow](backup: {_esc(ch.source)})[/yellow]"
                    console.print(f"     [dim][DRY RUN][/dim] {ch_label}{source_info}")
                    continue

                # Download automatically or prompt
                should_download = download
                if not should_download and not can_prompt:
                    # No one can confirm: no terminal, or --quiet. Never
                    # download implicitly and never hide it (#258, #351).
                    total_unconfirmed += 1
                    continue
                if not should_download:
                    should_download = Confirm.ask(f"     Download {ch_label}?", default=True)

                if not should_download:
                    continue

                if _process_chapter(pipeline, manga, ch).saved:
                    total_downloaded += 1
                    # Safe mode: restart browser every 3 chapters to free memory
                    if getattr(args, 'safe', False) and total_downloaded % 3 == 0:
                        restart_browsers()
                else:
                    total_failed += 1

        except StateCheckpointError:
            # Ends the run (#230): no further chapter may be downloaded or
            # delivered once results can't be recorded.
            raise
        except DownloaderError as e:
            _diagnostic(logging.ERROR, f"  [red]└─ Error: {_esc(e)}[/red]",
                        "%s: Error: %s", title, e)
            total_errored += 1
        except Exception as e:
            _diagnostic(logging.ERROR,
                        f"  [red]└─ Unexpected error: {_esc(e)}[/red]",
                        "%s: Unexpected error: %s", title, e)
            total_errored += 1
    
    # Record check history with actual counts. A dry run is a preview:
    # it must not count as a check (the GUI auto-check throttles on it).
    if not dry_run:
        state.update_last_check(new_chapters=total_new, downloaded=total_downloaded)

    # Summary
    if is_plain_console(console):
        # Issue #226: one greppable line for cron and pipes.
        console.print(_check_summary_line(
            dry_run, total_checked, total_new, total_downloaded,
            total_failed, total_errored, total_unconfirmed,
        ), markup=False)
    else:
        console.print()
        if total_new == 0:
            console.print("[dim]No new chapters found.[/dim]")
        elif dry_run:
            console.print(f"[yellow]📊 Dry run: {total_new} chapter(s) available for download[/yellow]")
        else:
            console.print(f"[green]📊 Summary: {total_downloaded}/{total_new} chapters downloaded[/green]")
            if delivery_mode == "local":
                console.print(f"[dim]📁 Downloads: {_esc(download_dir)}[/dim]")
    if total_failed > 0:
        _diagnostic(
            logging.WARNING,
            f"[yellow]⚠️  {total_failed} chapter(s) failed — run 'memanga failed' for details.[/yellow]",
            "%d chapter(s) failed — run 'memanga failed' for details.",
            total_failed,
        )
    if total_errored:
        _diagnostic(
            logging.WARNING,
            f"[yellow]⚠️  {total_errored}/{total_checked} manga could not be checked.[/yellow]",
            "%d/%d manga could not be checked.", total_errored, total_checked,
        )
    if total_unconfirmed:
        return _non_interactive_error(
            f"skipped {total_unconfirmed} chapter(s) that need confirmation; "
            "pass --download (or its aliases --auto/--yes) to download without "
            "prompting, or --dry-run to only list them"
        )
    # Issue #239: nothing could be checked is an error; some chapters or
    # manga failing while the rest ran is a partial failure.
    if total_checked and total_errored == total_checked:
        return EXIT_ERROR
    if total_failed or total_errored:
        return EXIT_PARTIAL


def _status_payload() -> Dict[str, Any]:
    """`status --json` payload. Never includes the SMTP password."""
    return {
        "schema_version": JSON_SCHEMA_VERSION,
        "paths": {
            "config_dir": str(config.config_dir),
            "config": str(config.config_path),
            "state": str(state.state_path),
        },
        "manga_count": len(config.get("manga", [])),
        "output_format": config.output_format,
        "delivery": {
            "mode": config.delivery_mode,
            "download_dir": str(config.download_dir),
            "delete_after_send": bool(config.get("delivery.delete_after_send", False)),
        },
        "email": {
            "kindle_email": config.get("email.kindle_email") or None,
            "sender_email": config.get("email.sender_email") or None,
            "smtp_server": config.get("email.smtp_server", "smtp.gmail.com"),
            "smtp_port": config.get("email.smtp_port", 587),
        },
        "post_processing": {
            "enabled": bool(config.get("delivery.post_processing.enabled")),
            "fail_on_error": bool(config.get("delivery.post_processing.fail_on_error", False)),
        },
        "partial_chapters": {
            "enabled": config.partial_enabled,
            "threshold_percent": config.partial_threshold,
        },
        "cron": {
            "enabled": bool(config.get("cron.enabled")),
            "time": config.get("cron.time", "06:00"),
        },
        "last_check": state.get("last_check"),
    }


def cmd_status(args):
    """Show current status and configuration."""
    if getattr(args, "json", False):
        _print_json(_status_payload())
        return

    console.print(_panel("[bold]📊 MeManga Status[/bold]", border_style="blue"))
    console.print()
    
    # Configuration
    table = _table(title="Configuration", box=box.SIMPLE, show_header=False)
    table.add_column(style="dim", width=18)
    table.add_column(style="white")
    
    manga_list = config.get("manga", [])
    delivery_mode = config.delivery_mode
    
    table.add_row("Manga tracked", f"[cyan]{len(manga_list)}[/cyan]")
    table.add_row("Output format", f"[cyan]{_esc(config.output_format)}[/cyan]")
    table.add_row("Delivery mode", f"[yellow]{_esc(delivery_mode)}[/yellow]")
    
    if delivery_mode == "local":
        table.add_row("Download dir", _esc(config.download_dir))
    else:
        kindle_email = config.get("email.kindle_email")
        sender_email = config.get("email.sender_email")
        table.add_row("Kindle email", _esc(kindle_email) if kindle_email else "[red]not set[/red]")
        table.add_row("Sender email", _esc(sender_email) if sender_email else "[red]not set[/red]")
    
    pp_enabled = bool(config.get("delivery.post_processing.enabled"))
    pp_status = "enabled" if pp_enabled else "disabled"
    table.add_row(
        "Post-processing",
        f"[{'green' if pp_enabled else 'dim'}]{pp_status}[/]",
    )

    cron_status = "enabled" if config.get("cron.enabled") else "disabled"
    cron_time = config.get("cron.time", "06:00")
    table.add_row("Cron", f"[{'green' if cron_status == 'enabled' else 'dim'}]{cron_status}[/] ({_esc(cron_time)})")
    
    console.print(table)
    
    # Paths
    console.print()
    console.print(f"[dim]Config:[/dim] {_esc(config.config_path)}")
    console.print(f"[dim]State:[/dim]  {_esc(state.state_path)}")
    
    # Last check
    last_check = state.get("last_check")
    if last_check:
        console.print(f"[dim]Last check:[/dim] {_esc(last_check)}")


def _masked_config_data():
    """A copy of the loaded config with the app password masked."""
    import copy
    display = copy.deepcopy(config._data)
    pw = display.get("email", {}).get("app_password", "")
    if pw:
        display["email"]["app_password"] = "****"
    return display


def _config_error(message: str) -> int:
    """Plain-text diagnostic on stderr for the scriptable config actions."""
    sys.stderr.write(f"error: {message}\n")
    return EXIT_ERROR


def _config_value_text(value) -> str:
    """Render a config value for `config get`: one script-friendly line."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return str(value)


def _config_show(args):
    if getattr(args, "json", False):
        _print_json(_masked_config_data())
        return
    import yaml
    console.print(_panel("[bold]Current Configuration[/bold]", border_style="cyan"))
    console.print(_esc(yaml.dump(_masked_config_data(), default_flow_style=False)))


def _config_get(args):
    try:
        spec = config_key_spec(args.key)
    except UnknownConfigKey:
        return _config_error(f"unknown config key '{args.key}'; "
                             "see `memanga config get --help` for the keys")
    if spec.get("secret"):
        print("****" if get_app_password(config) else "")
        return
    print(_config_value_text(config.get(args.key)))


def _read_secret(args):
    """The secret for `config set`, or None after reporting why not.

    The value never comes from argv, where shell history and the
    process list would keep it.
    """
    if args.value == "-":
        return sys.stdin.readline().rstrip("\r\n")
    if args.value is not None:
        _config_error(f"{args.key} is not read from the command line; pass '-' "
                      "and send the value on stdin")
        return None
    if not _stdin_is_tty():
        _config_error(f"{args.key} needs a value; pass '-' and send it on stdin")
        return None
    return Prompt.ask("App password", password=True)


def _config_set(args):
    try:
        spec = config_key_spec(args.key)
    except UnknownConfigKey:
        return _config_error(f"unknown config key '{args.key}'; "
                             "see `memanga config set --help` for the keys")
    if spec.get("read_only"):
        return _config_error(f"{args.key} is managed by `{spec['read_only']}`")

    if spec.get("secret"):
        secret = _read_secret(args)
        if secret is None:
            return EXIT_ERROR
        set_app_password(config, secret)
        console.print(f"[green]✅ {_esc(args.key)} updated[/green]")
        return

    if args.value is None:
        return _config_error(f"config set {args.key} needs a VALUE")
    try:
        value = parse_config_value(args.key, args.value)
    except ValueError as e:
        return _config_error(f"invalid value for {args.key}: {e}")
    config.set(args.key, value)
    config.save()
    console.print(f"[green]✅ {_esc(args.key)} = {_esc(_config_value_text(value))}[/green]")


def _config_edit(args):
    import shlex
    import yaml
    if not _stdin_is_tty():
        return _non_interactive_error(
            "config edit needs a terminal; use `config set KEY VALUE` instead"
        )
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not editor:
        return _config_error("set $VISUAL or $EDITOR to choose an editor")
    path = config.config_path
    if not path.exists():
        config.save()  # start from the defaults
    try:
        command = shlex.split(editor, posix=os.name != "nt")
        result = subprocess.run(command + [str(path)])
    except (OSError, ValueError) as e:
        return _config_error(f"could not start editor '{editor}': {e}")
    if result.returncode != 0:
        return _config_error(
            f"editor exited with status {result.returncode}; {path} was not checked"
        )

    try:
        edited = Config(config.config_dir)
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError, ConfigError) as e:
        return _config_error(
            f"{path} is not valid: {e}\nRun `memanga config edit` again to fix it."
        )
    # Loading merges defaults over sections that are not mappings, so
    # check the file's own structure before the merged values.
    problems = config_section_problems(raw)
    for key in CONFIG_KEYS:
        value = edited.get(key)
        if value is None:
            continue  # unset: the default applies
        problem = config_value_problem(key, value)
        if problem:
            problems.append(f"{key}: {problem}")
    if problems:
        for problem in problems:
            sys.stderr.write(f"error: {problem}\n")
        sys.stderr.write("Run `memanga config edit` again to fix it.\n")
        return EXIT_ERROR
    console.print(f"[green]✅ {_esc(path)} is valid[/green]")


def _config_email(args):
    password_set = bool(get_app_password(config))
    table = _table(title="Email delivery", box=box.SIMPLE, show_header=False)
    table.add_column(style="dim", width=18)
    table.add_column(style="white")
    table.add_row("Delivery mode", _esc(config.delivery_mode))
    for label, key in (("Kindle email", "email.kindle_email"),
                       ("Sender email", "email.sender_email")):
        value = config.get(key)
        table.add_row(label, _esc(value) if value else "[red]not set[/red]")
    table.add_row("SMTP server", _esc(config.get("email.smtp_server", "smtp.gmail.com")))
    table.add_row("SMTP port", _esc(config.get("email.smtp_port", 587)))
    table.add_row("App password", "set" if password_set else "[red]not set[/red]")
    console.print(table)
    if not args.test:
        console.print("[dim]Pass --test to try logging in to the SMTP server.[/dim]")
        return

    with console.status("[dim]Logging in to the SMTP server...[/dim]"):
        result = doctor.check_smtp(config, state, live=True)
    if result.status == doctor.OK:
        console.print(f"[green]✅ {_esc(result.message)}[/green]")
        return
    return _error(f"[red]❌ {_esc(result.message)}[/red]")


_CONFIG_ACTIONS = {
    "show": _config_show,
    "get": _config_get,
    "set": _config_set,
    "path": lambda args: print(config.config_path),
    "edit": _config_edit,
    "email": _config_email,
}

# Actions that must work on a config.yaml that cannot be loaded, so the
# user can find and fix it.
CONFIG_ACTIONS_ON_BROKEN_CONFIG = ("path", "edit")


def cmd_config(args):
    """Configure MeManga settings."""
    action = getattr(args, "config_action", None)
    if action:
        return _CONFIG_ACTIONS[action](args)

    if args.show:
        _config_show(args)
        return

    # Non-interactive config for partial-chapter tolerance (issue #86).
    # When any of these flags are given, persist them and return without
    # dropping into the interactive prompt flow.
    partial = getattr(args, "partial", None)
    threshold = getattr(args, "partial_threshold", None)
    mangadex_quality = getattr(args, "mangadex_quality", None)
    remove_group = getattr(args, "mangadex_remove_group", None)
    if (partial is not None or threshold is not None or
            mangadex_quality is not None or remove_group is not None):
        if partial is not None:
            config.set("partial_chapters.enabled", partial == "on")
        if threshold is not None:
            # Already validated to [0, 100] by the argparse type.
            config.set("partial_chapters.threshold_percent", float(threshold))
        if mangadex_quality is not None:
            config.set("mangadex.data_saver", mangadex_quality == "data-saver")
        if remove_group is not None:
            groups = list(config.get("mangadex.removed_group_ids", []) or [])
            if remove_group not in groups:
                groups.append(remove_group)
            config.set("mangadex.removed_group_ids", groups)
        config.save()

        if partial is not None or threshold is not None:
            state_str = "enabled" if config.partial_enabled else "disabled"
            console.print(
                f"[green]✅ Partial-chapter tolerance {state_str}[/green] "
                f"[dim](threshold: {config.partial_threshold:g}%)[/dim]"
            )
        if mangadex_quality is not None:
            console.print(f"[green]✅ MangaDex image quality: {mangadex_quality}[/green]")
        if remove_group is not None:
            console.print(
                f"[green]✅ MangaDex group {remove_group} removed[/green] "
                "[dim](delete its downloaded chapters too)[/dim]"
            )
        return

    if not _stdin_is_tty():
        return _non_interactive_error(
            "interactive config needs a terminal; use `config show` (or --show), "
            "`config set KEY VALUE` or a config flag"
        )

    console.print(_panel("[bold]⚙️  Configure MeManga[/bold]", border_style="yellow"))
    console.print()
    
    # Delivery mode
    current_mode = config.delivery_mode
    console.print(f"[bold]Delivery Mode[/bold] (current: [cyan]{_esc(current_mode)}[/cyan])")
    console.print("  [1] local  - Download PDFs to a directory")
    console.print("  [2] email  - Send PDFs to Kindle via email")
    mode_choice = Prompt.ask("Select mode", choices=["1", "2", ""], default="")
    
    if mode_choice == "1":
        config.set("delivery.mode", "local")
        download_dir = Prompt.ask(
            "Download directory",
            default=str(config.download_dir)
        )
        config.set("delivery.download_dir", download_dir)

    elif mode_choice == "2":
        config.set("delivery.mode", "email")

        console.print("\n[bold]Email Configuration[/bold]")
        console.print("[dim]You need a Gmail account with an App Password.[/dim]")
        console.print("[dim]Kindle email must be whitelisted in Amazon settings.[/dim]\n")

        kindle_email = Prompt.ask(
            "Kindle email (@kindle.com)",
            default=config.get("email.kindle_email", "")
        )
        sender_email = Prompt.ask(
            "Sender Gmail",
            default=config.get("email.sender_email", "")
        )

        config.set("email.kindle_email", kindle_email)
        config.set("email.sender_email", sender_email)

        if Confirm.ask("Update app password?"):
            app_password = Prompt.ask("App password", password=True)
            set_app_password(config, app_password)

        delete_after = Confirm.ask(
            "Delete files after sending to Kindle?",
            default=config.get("delivery.delete_after_send", False)
        )
        config.set("delivery.delete_after_send", delete_after)

    # Output format
    current_format = config.output_format
    console.print(f"\n[bold]Output Format[/bold] (current: [cyan]{_esc(current_format)}[/cyan])")
    console.print("  [1] pdf   - Portable Document Format")
    console.print("  [2] epub  - E-reader format (Kindle optimized)")
    console.print("  [3] cbz   - Comic Book ZIP archive")
    console.print("  [4] zip   - ZIP archive of images")
    console.print("  [5] jpg   - JPEG images (folder per chapter)")
    console.print("  [6] png   - PNG images (folder per chapter)")
    console.print("  [7] webp  - WebP images (folder per chapter)")
    fmt_choice = Prompt.ask("Select format", choices=["1", "2", "3", "4", "5", "6", "7", ""], default="")

    if fmt_choice == "1":
        config.set("delivery.output_format", "pdf")
    elif fmt_choice == "2":
        config.set("delivery.output_format", "epub")
    elif fmt_choice == "3":
        config.set("delivery.output_format", "cbz")
    elif fmt_choice == "4":
        config.set("delivery.output_format", "zip")
    elif fmt_choice == "5":
        config.set("delivery.output_format", "jpg")
    elif fmt_choice == "6":
        config.set("delivery.output_format", "png")
    elif fmt_choice == "7":
        config.set("delivery.output_format", "webp")

    current_quality = "data-saver" if config.get("mangadex.data_saver", False) else "original"
    quality = Prompt.ask(
        "MangaDex image quality", choices=["original", "data-saver"],
        default=current_quality,
    )
    config.set("mangadex.data_saver", quality == "data-saver")

    # Post-processing hook (optional, disabled by default)
    pp_enabled = bool(config.get("delivery.post_processing.enabled"))
    console.print(
        f"\n[bold]Post-processing[/bold] (current: "
        f"[cyan]{'enabled' if pp_enabled else 'disabled'}[/cyan])"
    )
    console.print(
        "[dim]Run a command after each chapter is saved. "
        "Only enable commands you trust.[/dim]"
    )
    if Confirm.ask("Enable post-processing command?", default=pp_enabled):
        console.print(
            "[dim]Placeholders: {output_path} {title} {chapter} {source} "
            "{format} {is_dir} (also as MEMANGA_* env vars).[/dim]"
        )
        console.print(
            "[dim]Commands run directly, without a shell. Invoke a shell "
            "explicitly for pipes, redirects, or globbing. Scripts should "
            "prefer MEMANGA_* env vars.[/dim]"
        )
        pp_command = Prompt.ask(
            "Command",
            default=config.get("delivery.post_processing.command", "")
        )
        pp_fail = Confirm.ask(
            "Mark chapter as failed if the command fails?",
            default=config.get("delivery.post_processing.fail_on_error", False)
        )
        config.set("delivery.post_processing.enabled", True)
        config.set("delivery.post_processing.command", pp_command)
        config.set("delivery.post_processing.fail_on_error", pp_fail)
    else:
        config.set("delivery.post_processing.enabled", False)

    # Partial-chapter tolerance (issue #86)
    current_partial = config.partial_enabled
    state_str = "enabled" if current_partial else "disabled"
    console.print(
        f"\n[bold]Partial-Chapter Tolerance[/bold] (current: [cyan]{state_str}[/cyan])"
    )
    console.print(
        "[dim]Keep a chapter that is missing a few pages instead of discarding it.[/dim]"
    )
    if Confirm.ask("Enable partial-chapter tolerance?", default=current_partial):
        config.set("partial_chapters.enabled", True)
        threshold = Prompt.ask(
            "Max % of pages allowed to fail",
            default=str(config.partial_threshold),
        )
        try:
            value = float(threshold)
        except (TypeError, ValueError):
            console.print("[yellow]⚠️  Invalid number, keeping previous threshold.[/yellow]")
        else:
            clamped = max(0.0, min(100.0, value))
            if clamped != value:
                console.print(
                    f"[yellow]⚠️  Threshold must be 0-100; clamped to {clamped:g}%.[/yellow]"
                )
            config.set("partial_chapters.threshold_percent", clamped)
    else:
        config.set("partial_chapters.enabled", False)

    config.save()
    console.print("\n[green]✅ Configuration saved![/green]")


def cmd_cron(args):
    """Manage scheduled task for automatic checking."""
    if platform.system() == "Windows":
        return _cmd_cron_windows(args)
    return _cmd_cron_unix(args)


def _print_unmanaged_cron_lines(crontab):
    """Point out MeManga lines that cron install/remove leave alone."""
    lines = unmanaged_memanga_lines(crontab)
    if not lines:
        return
    console.print("[yellow]These crontab lines mention MeManga but are not "
                  "managed by 'memanga cron'; edit them with 'crontab -e':[/yellow]")
    for line in lines:
        console.print(f"[dim]{_esc(line)}[/dim]")


def _cmd_cron_unix(args):
    """Manage cron job (macOS/Linux)."""

    if args.action == "status":
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
        )

        # Issue #231: only the marked line counts as the installed job.
        existing = result.stdout if result.returncode == 0 else ""
        owned = managed_lines(existing)
        if owned:
            console.print("[green]✅ Cron job is installed[/green]")
            for line in owned:
                console.print(f"[dim]{_esc(line)}[/dim]")
        else:
            console.print("[yellow]⚠️  No cron job found[/yellow]")
            console.print("[dim]Use 'memanga cron install' to set up automatic checking.[/dim]")
        _print_unmanaged_cron_lines(existing)
        return

    elif args.action == "install":
        time_str = args.time or config.get("cron.time", "06:00")

        if not args.time:
            if not _stdin_is_tty():
                return _non_interactive_error(
                    "cron install needs a terminal to ask for the time; pass --time HH:MM"
                )
            time_str = Prompt.ask("Check time (HH:MM)", default=time_str)

        try:
            hour, minute = time_str.split(":")
            hour, minute = int(hour), int(minute)
        except ValueError:
            return _error("[red]Invalid time format. Use HH:MM[/red]")

        # Issue #232: run the current interpreter and log to the config
        # root, never into the package install directory.
        cron_line = build_cron_line(
            minute, hour, config.config_dir, sys.executable,
            config_dir=_context.config_dir,
            source_root=source_checkout_root(Path(__file__).resolve().parent))

        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        existing = read_crontab(result)
        if existing is None:
            # Never overwrite a crontab we could not read (issue #231).
            return _error("[red]Could not read the current crontab; nothing "
                          f"was changed: {_esc((result.stderr or '').strip())}[/red]")

        # Issue #231: replace only the line a previous install marked as
        # managed; every other entry, comment and blank line is kept.
        new_crontab = replace_managed_line(existing, cron_line)
        process = subprocess.Popen(
            ["crontab", "-"],
            stdin=subprocess.PIPE,
            text=True,
        )
        process.communicate(input=new_crontab)

        if process.returncode == 0:
            config.set("cron.enabled", True)
            config.set("cron.time", time_str)
            config.save()

            console.print(f"[green]✅ Cron job installed! Will check daily at {time_str}[/green]")
            console.print(f"[dim]{_esc(cron_line)}[/dim]")
            _print_unmanaged_cron_lines(existing)
        else:
            return _error("[red]Failed to install cron job[/red]")

    elif args.action == "remove":
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        if result.returncode != 0:
            console.print("[yellow]No crontab found[/yellow]")
            return

        new_crontab, removed = remove_managed_lines(result.stdout)

        if not removed:
            console.print("[yellow]No MeManga cron job found[/yellow]")
            _print_unmanaged_cron_lines(result.stdout)
            return

        if not new_crontab.strip():
            write = subprocess.run(["crontab", "-r"], capture_output=True)
        else:
            write = subprocess.Popen(["crontab", "-"], stdin=subprocess.PIPE, text=True)
            write.communicate(input=new_crontab)
        if write.returncode != 0:
            return _error("[red]Failed to remove cron job[/red]")

        config.set("cron.enabled", False)
        config.save()

        console.print("[green]✅ Cron job removed[/green]")


def _cmd_cron_windows(args):
    """Manage Windows Task Scheduler task."""
    task_name = "MeManga_AutoCheck"

    if args.action == "status":
        result = subprocess.run(
            ["schtasks", "/query", "/tn", task_name],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            console.print("[green]✅ Scheduled task is installed[/green]")
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    console.print(f"[dim]{_esc(line.strip())}[/dim]")
        else:
            console.print("[yellow]⚠️  No scheduled task found[/yellow]")
            console.print("[dim]Use 'memanga cron install' to set up automatic checking.[/dim]")

    elif args.action == "install":
        time_str = args.time or config.get("cron.time", "06:00")

        if not args.time:
            if not _stdin_is_tty():
                return _non_interactive_error(
                    "cron install needs a terminal to ask for the time; pass --time HH:MM"
                )
            time_str = Prompt.ask("Check time (HH:MM)", default=time_str)

        try:
            hour, minute = time_str.split(":")
            int(hour), int(minute)
        except ValueError:
            return _error("[red]Invalid time format. Use HH:MM[/red]")

        # Delete existing task if present
        subprocess.run(
            ["schtasks", "/delete", "/tn", task_name, "/f"],
            capture_output=True, text=True,
        )

        # Issue #232: the running interpreter, not a checkout-local venv.
        cmd = build_task_command(
            sys.executable, _context.config_dir,
            source_root=source_checkout_root(Path(__file__).resolve().parent))
        result = subprocess.run(
            [
                "schtasks", "/create",
                "/tn", task_name,
                "/tr", cmd,
                "/sc", "daily",
                "/st", time_str,
                "/f",
            ],
            capture_output=True, text=True,
        )

        if result.returncode == 0:
            config.set("cron.enabled", True)
            config.set("cron.time", time_str)
            config.save()
            console.print(f"[green]✅ Scheduled task installed! Will check daily at {time_str}[/green]")
        else:
            return _error(f"[red]Failed to create scheduled task: {_esc(result.stderr.strip())}[/red]")

    elif args.action == "remove":
        result = subprocess.run(
            ["schtasks", "/delete", "/tn", task_name, "/f"],
            capture_output=True, text=True,
        )

        if result.returncode == 0:
            config.set("cron.enabled", False)
            config.save()
            console.print("[green]✅ Scheduled task removed[/green]")
        else:
            console.print("[yellow]No MeManga scheduled task found[/yellow]")


def cmd_sources(args):
    """List supported manga sources."""
    sources = get_supported_sources()
    
    console.print(_panel("[bold]🌐 Supported Sources[/bold]", border_style="cyan"))
    console.print()
    
    table = _table(box=box.SIMPLE)
    table.add_column("Source", style="cyan")
    table.add_column("Type", style="dim")
    table.add_column("Best For")
    
    table.add_row("[bold]tcbonepiecechapters.com[/bold]", "Requests", "Jump manga (One Piece, JJK, MHA)")
    table.add_row("[bold]weebcentral.com[/bold]", "Hybrid", "Large library (1000+ series)")
    table.add_row("[bold]asurascans.com[/bold]", "API", "Manhwa / Webtoons")
    table.add_row("[bold]mangakatana.com[/bold]", "Playwright", "General manga library")
    table.add_row("[bold]mangadex.org[/bold]", "API", "Fan translations (skip Shueisha)")
    
    console.print(table)
    console.print()
    console.print(f"[dim]Total: {len(sources)} sources • All tested and working![/dim]")


def _add_search_result(result, status=None):
    """Add one search result to the tracked manga list.

    Returns (ok, message). Printing is left to the caller so the JSON
    output path can stay machine-readable.
    """
    manga_list = config.get("manga", [])
    for m in manga_list:
        if m["title"].lower() == result.title.lower():
            return False, f"'{result.title}' already exists"
    # Same folder as another manga: see cmd_add (issue #246).
    owner = _download_folder_owner(result.title, manga_list)
    if owner is not None:
        return False, (f"'{result.title}' would use the same download folder "
                       f"as '{owner['title']}'")

    entry = {
        "title": result.title,
        "source": result.source,
        "url": result.url,
    }
    if result.cover_url:
        entry["cover_url"] = result.cover_url
    if status:
        entry["status"] = status

    manga_list.append(entry)
    config.set("manga", manga_list)
    config.save()
    return True, f"Added: {result.title} ({result.source})"


def cmd_search(args):
    """Search enabled sources for a manga by title."""
    query = args.query.strip()
    if not query:
        return _error("[red]Error:[/red] empty search query")
    if args.limit is not None and args.limit < 1:
        return _error("[red]Error:[/red] --limit must be at least 1")

    # Resolve the source list: one source with --source, otherwise the
    # same enabled-aggregators + library sweep the GUI Search page runs.
    if args.source:
        source = args.source.lower()
        if source.startswith("www."):
            source = source[4:]
        try:
            get_scraper(source)
        except ValueError:
            err_console.print(f"[red]Unknown source:[/red] {_esc(source)}")
            err_console.print("[dim]Use 'memanga sources' to see supported sources.[/dim]")
            return EXIT_ERROR
        sources = [source]
    else:
        sources = compute_search_sources(config)

    if not sources:
        return _error("[yellow]No searchable sources enabled.[/yellow]")

    quiet = args.json  # keep stdout machine-readable for --json

    if not quiet:
        console.print(f'Searching {len(sources)} sources for [cyan]"{_esc(query)}"[/cyan]...')

    if quiet:
        results, failures = sweep(query, sources, limit=args.limit)
        if results and not args.no_chips:
            probe_chapter_counts(results)
    else:
        progress = {"done": 0, "found": 0}

        with console.status(f"[dim]0/{len(sources)} sources[/dim]") as status:
            def _tick(extra_found=0):
                progress["done"] += 1
                progress["found"] += extra_found
                status.update(
                    f"[dim]{progress['done']}/{len(sources)} sources · "
                    f"{progress['found']} results[/dim]"
                )

            results, failures = sweep(
                query, sources, limit=args.limit,
                on_source_done=lambda src, count: _tick(count),
                on_source_failed=lambda src, err: _tick(),
            )
            if results and not args.no_chips:
                status.update(f"[dim]Fetching chapter counts for {len(results)} results...[/dim]")
                probe_chapter_counts(results)

    # ── Output ──
    if args.json:
        add_ok = None
        payload = {
            "query": query,
            "sources_searched": len(sources),
            "results": [
                {
                    "n": i,
                    "title": r.title,
                    "source": r.source,
                    "url": r.url,
                    "cover_url": r.cover_url,
                    "chapters": r.chapter_count,
                }
                for i, r in enumerate(results, 1)
            ],
            "failed": [{"source": f.source, "error": f.error} for f in failures],
        }
        if args.add is not None:
            if 1 <= args.add <= len(results):
                add_ok, message = _add_search_result(
                    results[args.add - 1], args.status
                )
            else:
                add_ok, message = False, f"invalid result number: {args.add}"
            payload["added"] = {"ok": add_ok, "message": message}
        print(json.dumps(payload, indent=2))
        if args.add is not None:
            return 0 if add_ok else 1
        return 0 if results else 1

    summary = f"{len(sources) - len(failures)} / {len(sources)} sources done"
    if failures:
        first = failures[0]
        summary += f" · {len(failures)} failed ({first.source}: {first.error})"

    if not results:
        err_console.print(f"[yellow]No results for \"{_esc(query)}\".[/yellow]")
        err_console.print(f"[dim]{_esc(summary)}[/dim]")
        return EXIT_ERROR

    table = _table(box=box.SIMPLE)
    table.add_column("#", style="dim", justify="right")
    table.add_column("Source", style="green")
    table.add_column("Title", style="cyan bold")
    table.add_column("Chapters", style="yellow", justify="right")
    for i, r in enumerate(results, 1):
        table.add_row(
            str(i),
            _esc(r.source),
            _esc(r.title),
            str(r.chapter_count) if r.chapter_count is not None else "—",
        )
    console.print(table)
    console.print(f"[dim]{_esc(summary)}[/dim]")

    # ── Selection ──
    if args.add is not None:
        if not (1 <= args.add <= len(results)):
            return _error(f"[red]Invalid result number:[/red] {args.add} (valid: 1-{len(results)})")
        ok, message = _add_search_result(results[args.add - 1], args.status)
        if ok:
            console.print(f"[green]✅ {_esc(message)}[/green]")
            return 0
        return _error(f"[yellow]⚠️  {_esc(message)}[/yellow]")

    # Interactive prompt — only when someone is actually at the
    # terminal. Piped/cron invocations just get the table.
    if not _stdin_is_tty():
        return 0

    console.print()
    choice = Prompt.ask("Add which? ([cyan]number[/cyan] to add, [cyan]q[/cyan] to quit)", default="q")
    choice = choice.strip().lower()
    if choice in ("q", ""):
        return 0
    # Accept both "3" and "a 3".
    if choice.startswith("a ") or choice.startswith("a\t"):
        choice = choice[1:].strip()
    try:
        n = int(choice)
    except ValueError:
        return _error(f"[red]Not a result number:[/red] {_esc(choice)}")
    if not (1 <= n <= len(results)):
        return _error(f"[red]Invalid result number:[/red] {n} (valid: 1-{len(results)})")
    ok, message = _add_search_result(results[n - 1], args.status)
    if ok:
        console.print(f"[green]✅ {_esc(message)}[/green]")
        return 0
    return _error(f"[yellow]⚠️  {_esc(message)}[/yellow]")


# Issue #244: export runs without the config directory lock, so it must
# never write over the files MeManga itself keeps there (also their
# backups and recovery copies).
_OWN_FILES = ("config.yaml", "state.json", LOCK_FILENAME)


def _is_own_file_name(name: str) -> bool:
    """config.yaml, state.json, memanga.lock, or one of their backups,
    recovery copies or temps (``<own name>.<anything>``)."""
    name = name.casefold()
    return name in _OWN_FILES or name.startswith(
        tuple(f"{own}." for own in _OWN_FILES))


class _UnverifiedTarget(Exception):
    """An existing export destination could not be told apart from
    MeManga's own files."""


def _own_file_target(path: Path) -> bool:
    """True when writing ``path`` would write one of MeManga's own files,
    also through a symlink, a hard link or another spelling of the
    config directory.

    Raises _UnverifiedTarget when ``path`` exists but its identity, or
    that of the files in the config directory, cannot be established:
    a hard link has a name of its own, so only the identity tells.
    """
    root = config.config_dir
    target = Path(os.path.realpath(path))
    try:
        in_root = os.path.samefile(target.parent, root)
    except OSError:
        in_root = False
    if in_root and _is_own_file_name(target.name):
        return True
    try:
        target_stat = os.stat(target)
    except FileNotFoundError:
        return False  # a new file is no alias
    except OSError as e:
        raise _UnverifiedTarget(e.strerror or e) from e
    # Identity is st_dev + st_ino (os.path.samestat); a zero st_ino means
    # the file system gives no file ID to compare.
    if not target_stat.st_ino:
        raise _UnverifiedTarget("the file system reports no file ID")
    # Compare with every own file in the config directory, backups and
    # recovery copies included. os.stat(), not DirEntry.stat(): on
    # Windows the latter leaves st_ino at zero.
    try:
        with os.scandir(root) as entries:
            own = [entry.path for entry in entries
                   if _is_own_file_name(entry.name)]
    except OSError as e:
        raise _UnverifiedTarget(e.strerror or e) from e
    for own_path in own:
        try:
            own_stat = os.stat(own_path)
        except FileNotFoundError:
            continue  # replaced or removed since the listing
        except OSError as e:
            raise _UnverifiedTarget(e.strerror or e) from e
        if not own_stat.st_ino:
            raise _UnverifiedTarget("the file system reports no file ID")
        if os.path.samestat(target_stat, own_stat):
            return True
    return False


def cmd_export(args):
    """Export manga list and download state to JSON.

    Issue #354: ``-`` writes the JSON to stdout (and nothing else, so it
    can be piped); the summary goes to stderr.
    """
    manga_list = config.get("manga", [])
    manga_state = state.get("manga", {})

    export_data = {
        "version": EXPORT_VERSION,
        "exported_at": datetime.now().isoformat(),
        "manga": manga_list,
        "state": manga_state,
    }

    output_file = args.file or DEFAULT_EXPORT_FILE

    if output_file == "-":
        json.dump(export_data, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        sys.stdout.flush()
        err_console.print(f"[green]Exported {len(manga_list)} manga to stdout[/green]")
        return None

    output_path = Path(output_file)
    try:
        own_target = _own_file_target(output_path)
    except _UnverifiedTarget as e:
        return _error(
            f"[red]Cannot export to {_esc(output_path)}:[/red] MeManga "
            "could not make sure it is not one of its own files in "
            f"{_esc(config.config_dir)} ({_esc(e)}). "
            "Nothing was written. Export to a new file name instead."
        )
    if own_target:
        return _error(
            f"[red]Cannot export to {_esc(output_path)}:[/red] it is one of "
            f"MeManga's own files in {_esc(config.config_dir)}. Choose "
            "another file name."
        )
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2, default=str)
    except OSError as exc:
        return _error(f"[red]Cannot export:[/red] {_esc(exc)}")

    console.print(f"[green]Exported {len(manga_list)} manga to [cyan]{_esc(output_path)}[/cyan][/green]")


def _plan_import_merge(existing_manga, imported_manga):
    """Work out a merge import without touching config or state.

    Returns (merged_list, added_titles, skipped_titles, state_title_aliases).
    ``merged_list`` is a new list; ``existing_manga`` is left as-is so a
    dry run can't leak into the live config (Config.get returns its own
    object). It holds the existing entries first, in their order, followed
    by the added ones, so ``merged_list[len(merged_list) - len(added_titles):]``
    are exactly the added entries; cmd_import's download-folder check
    (_import_folder_clash) relies on this order.
    """
    merged = list(existing_manga)
    existing_titles = {
        m["title"].lower(): m["title"]
        for m in merged
    }
    state_title_aliases = {}
    added = []
    skipped = []
    for m in imported_manga:
        title = m["title"]
        title_key = title.lower()
        existing_title = existing_titles.get(title_key)
        if existing_title is not None:
            if title != existing_title:
                state_title_aliases[title] = existing_title
            skipped.append(title)
            continue
        merged.append(m)
        existing_titles[title_key] = title
        added.append(title)
    return merged, added, skipped, state_title_aliases


def _import_folder_clash(manga_list, first_new=0):
    """Error text when an entry the import adds would share a download
    folder with another entry of the resulting ``manga_list``, else None
    (issue #246).

    Entries from index ``first_new`` on are the imported ones; clashes
    only among the entries before it were already tracked and are left
    alone. Titles like "A:B" and "AB", or "x" and "X" in a replaced list,
    would write their chapter files into one folder and overwrite each
    other.
    """
    from .downloader import _download_folder_key
    seen = {}
    for index, entry in enumerate(manga_list):
        title = entry.get("title", "")
        key = _download_folder_key(title)
        if key in seen and index >= first_new:
            return (
                f"[red]Cannot import:[/red] '{_esc(seen[key])}' and "
                f"'{_esc(title)}' would use the same download folder; rename "
                "one first. Nothing was changed."
            )
        seen.setdefault(key, title)
    return None


def cmd_import(args):
    """Import manga list and download state from JSON.

    Issue #354: ``-`` reads the JSON from stdin, ``--dry-run`` reports
    what would change without writing, and ``--replace`` needs ``--yes``
    or an interactive confirmation. The whole payload is validated
    before config or state is touched.
    """
    # getattr: the TUI builds its own Namespace without these flags.
    dry_run = getattr(args, "dry_run", False)
    yes = getattr(args, "yes", False)
    from_stdin = args.file == "-"

    if from_stdin:
        source_label = "stdin"
        try:
            # Decode the bytes as UTF-8 like a file import, not with the
            # console's code page (Windows).
            buffer = getattr(sys.stdin, "buffer", None)
            raw = (buffer.read().decode("utf-8-sig") if buffer is not None
                   else sys.stdin.read())
        except (OSError, UnicodeDecodeError) as exc:
            return _error(f"[red]Cannot import:[/red] {_esc(exc)}")
    else:
        import_path = Path(args.file)
        source_label = str(import_path)
        if not import_path.exists():
            return _error(f"[red]File not found:[/red] {_esc(import_path)}")
        try:
            # utf-8-sig: also accept a backup re-saved with a BOM by an
            # editor such as Windows Notepad.
            with open(import_path, "r", encoding="utf-8-sig") as f:
                raw = f.read()
        except (OSError, UnicodeDecodeError) as exc:
            return _error(f"[red]Cannot import:[/red] {_esc(exc)}")

    try:
        import_data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return _error(f"[red]Cannot import:[/red] invalid JSON in {_esc(source_label)} ({_esc(exc)})")

    try:
        import_data = validate_backup(import_data)
        imported_manga, imported_state = validate_backup_contents(import_data)
    except BackupVersionError as exc:
        return _error(f"[red]Cannot import:[/red] {_esc(exc)}")

    if args.replace:
        current_count = len(config.get("manga", []))
        clash = _import_folder_clash(imported_manga)
        if clash:
            return _error(clash)
        if dry_run:
            console.print(
                f"[cyan]Dry run:[/cyan] would replace {current_count} manga with "
                f"{len(imported_manga)} from {_esc(source_label)} "
                f"(state for {len(imported_state)} titles); nothing was changed"
            )
            return None
        if not yes:
            # stdin already carried the backup, so it can't answer a prompt.
            if from_stdin or not _stdin_is_tty():
                return _non_interactive_error(
                    f"refusing to replace {current_count} manga and all download "
                    "state without confirmation; pass --yes (or --dry-run to preview)"
                )
            if not Confirm.ask(
                    f"Replace all {current_count} manga and download state with "
                    f"{len(imported_manga)} manga from [cyan]{_esc(source_label)}[/cyan]?",
                    default=False):
                console.print("[yellow]Import cancelled; nothing was changed.[/yellow]")
                return None
        # Full replace
        config.set("manga", imported_manga)
        config.save()
        state.set("manga", imported_state)
        console.print(f"[green]Replaced with {len(imported_manga)} manga from import[/green]")
        return None

    # Merge mode: skip duplicates, merge chapter lists
    merged_manga, added, skipped, state_title_aliases = _plan_import_merge(
        config.get("manga", []), imported_manga,
    )
    # _plan_import_merge appends the added entries after the existing ones.
    clash = _import_folder_clash(merged_manga,
                                 first_new=len(merged_manga) - len(added))
    if clash:
        return _error(clash)

    # Rehearse the state merge before anything is saved (and before a dry
    # run reports success), so a backup that still can't merge with local
    # state fails with nothing written instead of leaving config imported
    # and state not (issue #354).
    try:
        merge_backup_state(
            state.get("manga", {}),
            imported_state,
            title_aliases=state_title_aliases,
        )
    except (TypeError, ValueError, AttributeError) as exc:
        return _error(f"[red]Cannot import:[/red] backup state does not merge with local state ({_esc(exc)})")

    if dry_run:
        console.print(
            f"[cyan]Dry run:[/cyan] {len(added)} added, {len(skipped)} skipped "
            f"(duplicate) from {_esc(source_label)}; nothing was changed"
        )
        for title in added:
            console.print(f"  [green]+[/green] {_esc(title)}")
        for title in skipped:
            console.print(f"  [dim]= {_esc(title)} (already tracked; state merged)[/dim]")
        return None

    config.set("manga", merged_manga)
    config.save()
    state.merge_missing_manga_state(
        imported_state,
        merge_existing_downloaded=True,
        title_aliases=state_title_aliases,
    )

    console.print(f"[green]Imported: {len(added)} added, {len(skipped)} skipped (duplicate)[/green]")


def _chapter_order(item):
    """Sort key for (chapter_number, info) pairs; non-numeric labels first,
    labelled chapters such as "10 Part 1" by their chapter number."""
    return chapter_order_key(item[0])


def _resolve_failed_target(target):
    """Resolve a `failed` TARGET with the same rules as `check -t` (#352).

    `#N` picks the Nth entry in `memanga list`. A title also matches manga
    that are no longer tracked but still have failure or partial records,
    so those records stay reachable.

    Returns (title, None), or (None, exit code) after reporting the error.
    """
    manga_list = config.get("manga", [])
    stripped = target.strip()
    if stripped.startswith("#") and _is_ascii_number(stripped[1:]):
        candidates = manga_list
    else:
        tracked = {m["title"].casefold() for m in manga_list}
        recorded = sorted(
            set(state.get_all_failed_chapters()) | set(state.get_all_partial_chapters())
        )
        candidates = list(manga_list) + [
            {"title": t} for t in recorded if t.casefold() not in tracked
        ]
    found, _, matches = _find_manga(target, candidates)
    if not found:
        return None, _target_error(target, matches)
    return found["title"], None


def _collect_retryable(title=None):
    """Failed and accepted-partial records, optionally only those of one
    manga (a title resolved by `_resolve_failed_target`, compared
    case-insensitively).

    Returns (all_failed, all_partials, retryable) where `retryable`
    merges both per manga; a failure record wins over a partial one for
    the same chapter.
    """
    all_failed = state.get_all_failed_chapters()
    all_partials = state.get_all_partial_chapters()

    if title:
        key = title.casefold()
        all_failed = {
            t: chapters for t, chapters in all_failed.items()
            if t.casefold() == key
        }
        all_partials = {
            t: chapters for t, chapters in all_partials.items()
            if t.casefold() == key
        }

    retryable = {}
    for manga_title, chapters in all_failed.items():
        retryable.setdefault(manga_title, {}).update(chapters)
    for manga_title, chapters in all_partials.items():
        bucket = retryable.setdefault(manga_title, {})
        for chapter_num, info in chapters.items():
            if chapter_num in bucket:
                continue
            bucket[chapter_num] = {
                **info,
                "partial": True,
                "error": "Accepted partial download",
            }
    return all_failed, all_partials, retryable


def _failed_payload(retryable, title_filter=None) -> Dict[str, Any]:
    """`failed --json` payload: one flat entry per retryable chapter,
    sorted by manga title then chapter number."""
    chapters = []
    for manga_title, records in sorted(retryable.items()):
        for chapter_num, info in sorted(records.items(), key=_chapter_order):
            is_partial = bool(info.get("partial")) or "accepted_at" in info
            chapters.append({
                "title": manga_title,
                "chapter": chapter_num,
                "status": "partial" if is_partial else "failed",
                "recorded_at": (info.get("accepted_at") if is_partial else info.get("failed_at")) or None,
                "source": info.get("source") or None,
                "failed_pages": list(info.get("failed_pages") or []),
                "total_pages": (info.get("total_pages") or None) if is_partial else None,
                "attempts": None if is_partial else info.get("attempts", 1),
                "error": None if is_partial else (info.get("error") or None),
            })
    return {
        "schema_version": JSON_SCHEMA_VERSION,
        "title_filter": title_filter or None,
        "count": len(chapters),
        "chapters": chapters,
    }


def _primary_chapters(src):
    """Chapters listed on a manga's primary source ``src``, by number.
    Empty when the listing fails, so `failed retry` falls back to the
    backup sources."""
    chapters = {}
    try:
        scraper = get_scraper(src["source"])
        _configure_mangadex(scraper, state)
        # Reading the entries stays inside the guard: a listing whose
        # entries are not Chapter objects (some scrapers return dicts)
        # counts as failed, so retry still reaches the backup sources.
        for ch in scraper.get_chapters(src["url"]):
            # The first listing of a number wins, as before.
            chapters.setdefault(ch.number, ch)
    except Exception:
        return {}
    return chapters


def _failed_action(args) -> str:
    """`list`, `retry` or `clear`: the subcommand, else the legacy
    `--clear`/`--retry` alias (`--clear` wins, as it always did)."""
    action = getattr(args, "failed_action", None)
    if action:
        return action
    if getattr(args, "clear", False):
        return "clear"
    if getattr(args, "retry", False):
        return "retry"
    return "list"


def cmd_failed(args):
    """List, retry or clear chapters that failed or were accepted as partial.

    Actions (#352): `failed [list]`, `failed retry` and `failed clear`, each
    with an optional TARGET resolved like `check -t`. `--retry` and
    `--clear` remain aliases of the subcommands.
    """
    action = _failed_action(args)
    target = getattr(args, "target", None) or getattr(args, "title", None)
    title = None
    if target:
        title, error = _resolve_failed_target(target)
        if error:
            return error
    all_failed, all_partials, retryable = _collect_retryable(title)

    if getattr(args, "json", False):
        # retry/clear are rejected with --json at parse time.
        _print_json(_failed_payload(retryable, target))
        return

    if not retryable:
        console.print("[dim]No failed or partial chapters recorded.[/dim]")
        return

    table = _table(
        title="⚠️  Retryable Chapter Downloads",
        box=box.ROUNDED,
        show_lines=True,
    )
    table.add_column("Manga", style="cyan bold")
    table.add_column("Chapter", style="yellow", justify="center")
    table.add_column("Status", justify="center")
    table.add_column("Recorded At", style="dim")
    table.add_column("Source", style="green")
    table.add_column("Pages Missing", justify="center")
    table.add_column("Attempts", justify="center")
    table.add_column("Reason", style="red", no_wrap=False, max_width=40)

    for manga_title, chapters in sorted(retryable.items()):
        for chapter_num, info in sorted(chapters.items(), key=_chapter_order):
            is_partial = bool(info.get("partial")) or "accepted_at" in info
            recorded_at = (
                info.get("accepted_at") if is_partial else info.get("failed_at", "")
            )[:16].replace("T", " ")
            pages = info.get("failed_pages", [])
            pages_str = str(pages) if pages else "—"
            table.add_row(
                _esc(manga_title),
                _esc(chapter_num),
                "partial" if is_partial else "failed",
                _esc(recorded_at),
                _esc(info.get("source", "?")),
                _esc(pages_str),
                "—" if is_partial else _esc(info.get("attempts", 1)),
                _esc(info.get("error", "")),
            )

    console.print(table)
    console.print()

    if action == "clear":
        for manga_title, chapters in all_failed.items():
            for chapter_num in list(chapters):
                state.clear_failed_chapter(manga_title, chapter_num)
        for manga_title, chapters in all_partials.items():
            for chapter_num in list(chapters):
                state.clear_partial_chapter(manga_title, chapter_num)
        if title:
            console.print(f"[green]✅ Cleared failure and partial records for {_esc(title)}.[/green]")
        else:
            console.print("[green]✅ Cleared all failure and partial records.[/green]")
        return

    if action == "retry":
        manga_list = config.get("manga", [])
        manga_by_title = {m["title"]: m for m in manga_list}
        # Retries go through the same chapter pipeline as `check` (#352, #222).
        pipeline = _chapter_pipeline()
        retried = 0
        succeeded = 0

        for manga_title, chapters in retryable.items():
            manga = manga_by_title.get(manga_title)
            if not manga:
                _diagnostic(
                    logging.WARNING,
                    f"  [yellow]⚠️  Manga not found in config: {_esc(manga_title)}[/yellow]",
                    "Manga not found in config: %s", manga_title,
                )
                # Unretryable records still count as unrecovered (#239).
                retried += len(chapters)
                continue

            sources = _get_sources_from_manga(manga)
            # One primary listing per manga, not per failed chapter (#222).
            src = sources[0] if sources else None
            primary = _primary_chapters(src) if src and chapters else {}

            for chapter_num, info in sorted(chapters.items(), key=_chapter_order):
                if not sources:
                    _diagnostic(
                        logging.WARNING,
                        f"  [yellow]⚠️  No source to retry Chapter {_esc(chapter_num)} of {_esc(manga_title)}[/yellow]",
                        "No source to retry Chapter %s of %s",
                        chapter_num, manga_title,
                    )
                    retried += 1
                    continue

                ch_obj = primary.get(chapter_num)
                if not ch_obj:
                    _diagnostic(
                        logging.WARNING,
                        f"  [yellow]⚠️  Could not find Chapter {_esc(chapter_num)} of {_esc(manga_title)} on primary source[/yellow]",
                        "Could not find Chapter %s of %s on primary source",
                        chapter_num, manga_title,
                    )
                    # Try backup directly
                    ch_obj = _find_chapter_on_backup(manga, chapter_num, state)
                    if not ch_obj:
                        _diagnostic(
                            logging.ERROR,
                            f"  [red]❌ Chapter {_esc(chapter_num)} not found on any source[/red]",
                            "Chapter %s of %s not found on any source",
                            chapter_num, manga_title,
                        )
                        retried += 1
                        continue
                else:
                    ch_obj = ChapterWithSource(ch_obj, src["source"], src["url"], is_backup=False)

                console.print(f"  [dim]⬇️  Retrying {_esc(manga_title)} Chapter {_esc(chapter_num)}...[/dim]")
                retried += 1
                outcome = _process_chapter(pipeline, manga, ch_obj)
                # Saved again as a partial is not a recovery: the record stays.
                if outcome.status is ChapterStatus.COMPLETE:
                    succeeded += 1

        console.print()
        console.print(f"[green]📊 Retry summary: {succeeded}/{retried} chapters recovered[/green]")
        if succeeded < retried:
            return EXIT_PARTIAL


_DOCTOR_ICONS = {
    doctor.OK: "[green]✅[/green]",
    doctor.WARNING: "[yellow]⚠️[/yellow]",
    doctor.FAIL: "[red]❌[/red]",
    doctor.SKIP: "[dim]➖[/dim]",
}

# Plain output drops the icons (issue #226), so it names the status.
_DOCTOR_LABELS = {
    doctor.OK: "OK",
    doctor.WARNING: "WARN",
    doctor.FAIL: "FAIL",
    doctor.SKIP: "SKIP",
}


def cmd_doctor(args):
    """Diagnose common setup and runtime problems (issue #250).

    Exit code: 0 when no selected check failed, 1 when one did (or,
    with --strict, when one warned). Usage errors exit 2 via argparse.
    """
    only = set(args.check) if args.check else None

    def run():
        return doctor.run_checks(
            config, state, only=only,
            smtp=args.smtp, launch_browsers=args.launch_browsers,
        )

    if args.json:
        results = run()
        _print_json(doctor.build_report(results))
        return doctor.exit_code(results, strict=args.strict)

    with console.status("[dim]Running checks...[/dim]"):
        results = run()

    plain = is_plain_console(console)
    table = _table(title="🩺 MeManga Doctor", box=box.SIMPLE, show_header=False)
    table.add_column(width=None if plain else 2)
    table.add_column(style="cyan")
    table.add_column(no_wrap=False)
    status_cells = _DOCTOR_LABELS if plain else _DOCTOR_ICONS
    for r in results:
        message = _esc(r.message)
        if r.status == doctor.SKIP:
            message = f"[dim]{message}[/dim]"
        table.add_row(status_cells[r.status], _esc(r.name), message)
    console.print(table)

    report = doctor.build_report(results)
    counts = report["summary"]
    summary = (f"{counts['ok']} ok · {counts['warning']} warning · "
               f"{counts['fail']} failed · {counts['skip']} skipped")
    if report["status"] == doctor.FAIL:
        console.print(f"[red]❌ Problems found[/red] [dim]({summary})[/dim]")
    elif report["status"] == doctor.WARNING:
        console.print(f"[yellow]⚠️  Healthy with warnings[/yellow] [dim]({summary})[/dim]")
    else:
        console.print(f"[green]✅ All checks passed[/green] [dim]({summary})[/dim]")
    return doctor.exit_code(results, strict=args.strict)


def cmd_tui(args):
    """Run interactive TUI."""
    if not _stdin_is_tty():
        return _non_interactive_error(
            "the interactive menu needs a terminal; run a subcommand instead (see `memanga --help`)"
        )
    while True:
        console.clear()
        console.print(Panel.fit(
            "[bold magenta]MeManga[/bold magenta] 📖\n"
            "[dim]Manga to Kindle automation[/dim]",
            border_style="magenta"
        ))
        console.print()
        
        menu_items = [
            ("1", "📚 List Manga", "Show tracked manga"),
            ("2", "➕ Add Manga", "Track a new manga"),
            ("3", "🗑️  Remove Manga", "Stop tracking a manga"),
            ("4", "🔍 Check Now", "Check for new chapters"),
            ("5", "⚠️  Failed Chapters", "View/retry failed downloads"),
            ("6", "⚙️  Configure", "Change settings"),
            ("7", "⏰ Cron", "Manage auto-check schedule"),
            ("8", "📊 Status", "View status & config"),
            ("9", "✏️  Update Manga", "Change URL, backup, or title"),
            ("e", "📤 Export", "Export manga list to JSON"),
            ("i", "📥 Import", "Import manga list from JSON"),
            ("q", "🚪 Quit", "Exit"),
        ]

        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(style="bold cyan", width=3)
        table.add_column(style="bold white", width=18)
        table.add_column(style="dim")

        for key, title, desc in menu_items:
            table.add_row(_esc(f"[{key}]"), title, desc)

        console.print(table)
        console.print()

        choice = Prompt.ask("Select", choices=["1", "2", "3", "4", "5", "6", "7", "8", "9", "e", "i", "q"], default="4")
        
        if choice == "q":
            console.print("[dim]Goodbye! 📖[/dim]")
            break
        
        console.print()
        
        if choice == "1":
            cmd_list(argparse.Namespace())
        elif choice == "2":
            cmd_add(argparse.Namespace(interactive=True, title=None, url=None))
        elif choice == "3":
            cmd_list(argparse.Namespace())
            target = Prompt.ask("\nEnter #N or title to remove (or 'b' to go back)")
            if target != 'b':
                cmd_remove(argparse.Namespace(target=target, yes=False, purge=False))
        elif choice == "4":
            cmd_list(argparse.Namespace())
            console.print()
            # Which manga?
            target = Prompt.ask("Check which manga? ([cyan]a[/cyan]=all, or enter #N / title)", default="a")
            title = None
            if target.lower() != "a":
                manga_list_ref = config.get("manga", [])
                found, _, candidates = _find_manga(target, manga_list_ref)
                if not found:
                    _target_error(target, candidates)
                else:
                    title = found["title"]

            if target.lower() == "a" or title:
                # Auto-download?
                auto = Confirm.ask("Auto-download new chapters?", default=True)

                # Start from chapter?
                from_input = Prompt.ask(
                    "Start from chapter? (Enter for latest, 0 or 'all' for all chapters, or type a number)",
                    default="",
                )
                from_chapter = None
                if from_input.strip().lower() == "all":
                    from_chapter = 0
                elif from_input.strip():
                    try:
                        from_chapter = float(from_input)
                    except ValueError:
                        console.print("[red]Invalid chapter number, using latest.[/red]")

                # Safe mode auto-enabled for bulk downloads
                safe = from_chapter is not None

                # Format override?
                fmt_input = Prompt.ask(
                    "Output format? (Enter for default, or type pdf/epub/cbz/zip/jpg/png/webp)",
                    default="",
                )
                fmt = fmt_input.strip().lower() if fmt_input.strip().lower() in ("pdf", "epub", "cbz", "zip", "jpg", "png", "webp") else None

                cmd_check(argparse.Namespace(
                    title=title,
                    auto=auto,
                    yes=False,
                    quiet=False,
                    from_chapter=from_chapter,
                    safe=safe,
                    dry_run=False,
                    format=fmt,
                    retries=DEFAULT_PAGE_RETRIES,
                ))
        elif choice == "5":
            retry = Confirm.ask("Retry all failed downloads?", default=False)
            cmd_failed(argparse.Namespace(title=None, retry=retry, clear=False))
        elif choice == "6":
            cmd_config(argparse.Namespace(show=False))
        elif choice == "7":
            console.print("[1] Status  [2] Install  [3] Remove")
            cron_choice = Prompt.ask("Select", choices=["1", "2", "3"], default="1")
            action = {"1": "status", "2": "install", "3": "remove"}[cron_choice]
            cmd_cron(argparse.Namespace(action=action, time=None))
        elif choice == "8":
            cmd_status(argparse.Namespace())
        elif choice == "9":
            cmd_list(argparse.Namespace())
            target = Prompt.ask("\nEnter #N or title to update (or 'b' to go back)")
            if target != 'b':
                url = Prompt.ask("New primary URL (leave blank to skip)", default="") or None
                backup = Prompt.ask("New backup URL (leave blank to skip)", default="") or None
                new_title = Prompt.ask("New title (leave blank to skip)", default="") or None
                cmd_update(argparse.Namespace(target=target, url=url, backup=backup, title=new_title))
        elif choice == "e":
            file_path = Prompt.ask("Export file", default=DEFAULT_EXPORT_FILE)
            cmd_export(argparse.Namespace(file=file_path))
        elif choice == "i":
            file_path = Prompt.ask("Import file path")
            if file_path:
                replace = Confirm.ask("Replace all data? (No = merge)", default=False)
                # Answering yes above is the explicit --replace confirmation.
                cmd_import(argparse.Namespace(file=file_path, replace=replace,
                                              yes=replace, dry_run=False))

        console.print()
        Prompt.ask("[dim]Press Enter to continue[/dim]")


def cmd_completion(args):
    """Print a shell completion script built from the parser (#248).

    Written with sys.stdout, not Rich, so the script is never wrapped
    or styled.
    """
    sys.stdout.write(completion.script(args.shell, build_parser()))
    return EXIT_OK


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    # Issue #244: the config directory lock outlives _main() so the
    # interrupt handlers below still save state while holding it.
    try:
        _run_main()
    finally:
        _release_config_lock()


def _run_main():
    # Issue #239: handled here, not under __main__, so `python -m memanga`
    # and the installed `memanga` script also exit 130 without a traceback.
    try:
        _main()
    except KeyboardInterrupt:
        _flush_state_on_interrupt()
        err_console.print("\n[dim]Interrupted.[/dim]")
        sys.exit(EXIT_INTERRUPTED)
    except TerminationRequested:
        _flush_state_on_interrupt()
        err_console.print("\n[dim]Terminated.[/dim]")
        sys.exit(EXIT_TERMINATED)
    except StateCheckpointError as e:
        stopped = ("Stopped: nothing more is downloaded or sent while "
                   "results can't be recorded.")
        _diagnostic(
            logging.ERROR,
            f"[red]❌ Could not save state: {_esc(e)}[/red]\n[red]{stopped}[/red]",
            "Could not save state: %s. %s", e, stopped,
        )
        sys.exit(EXIT_ERROR)
    except SaveError as e:
        # Issue #243: a failed config/state save (full disk, permissions)
        # ends the command with a message instead of a traceback.
        reason = e.error.strerror or e.error
        advice = ("and its backup were not changed by this save. Free up "
                  "disk space or check the folder's permissions, then retry.")
        _diagnostic(
            logging.ERROR,
            f"[red]❌ Could not save {_esc(e.path.name)}: {_esc(reason)}[/red]\n"
            f"[red]{_esc(e.path)} {advice}[/red]",
            "Could not save %s: %s. %s %s", e.path.name, reason, e.path, advice,
        )
        sys.exit(EXIT_ERROR)


class TerminationRequested(BaseException):
    """Raised by the CLI's SIGTERM handler (issue #230).

    A BaseException, like KeyboardInterrupt, so the commands' ``except
    Exception`` handlers let it through to main(), which saves state.
    """


def _raise_termination(signum, frame):
    raise TerminationRequested(signum)


@contextmanager
def _sigterm_as_shutdown():
    """Turn SIGTERM into TerminationRequested while a CLI command runs.

    Python's default SIGTERM action exits without cleanup, so a cron
    `timeout` or a service stop lost state not yet written (issue #230).
    Only the main thread may install handlers, and the GUI never runs
    under this, so Qt keeps its own shutdown. The previous handler is
    restored afterwards.
    """
    if (not hasattr(signal, "SIGTERM")
            or threading.current_thread() is not threading.main_thread()):
        yield
        return
    previous = signal.signal(signal.SIGTERM, _raise_termination)
    try:
        yield
    finally:
        # None: the handler wasn't installed from Python.
        signal.signal(signal.SIGTERM,
                      signal.SIG_DFL if previous is None else previous)


def _flush_state_on_interrupt():
    """Persist state marked dirty before Ctrl-C (issue #234) or SIGTERM
    (issue #230).

    Each finished chapter is already checkpointed; this keeps whatever
    else was marked dirty before the signal (e.g. notifications). Best effort:
    a failed write must not replace the interrupt with a traceback.
    """
    if state is None:
        return
    try:
        state.flush()
    except Exception as e:
        _diagnostic(logging.WARNING,
                    f"[yellow]⚠️  Could not save state: {_esc(e)}[/yellow]",
                    "Could not save state: %s", e)


def _subparser(parser, name):
    """Return the subcommand parser registered under ``name``."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices[name]
    raise KeyError(name)


def build_parser() -> argparse.ArgumentParser:
    """Build the `memanga` argument parser (also used for completion)."""
    _cli_only = bool(os.environ.get("MEMANGA_CLI_ONLY"))

    _epilog = """
Examples:
  memanga list                          # Show tracked manga
  memanga add -i                        # Add manga interactively
  memanga add -t "Solo Leveling" -u URL # Add manga directly
  memanga search "Blue Lock"            # Find a manga across sources
  memanga check                         # Check for new chapters
  memanga check "Solo Leveling"         # Check one manga (same as -t)
  memanga check --download              # Download new chapters, no prompts
  memanga check --dry-run               # Only list new chapters
  memanga edit "#1" --status on-hold    # Change a manga's status
  memanga read "Solo Leveling" 1 2      # Mark chapters read (unread undoes)
  memanga path "Solo Leveling"          # Print its download folder
  memanga open "Solo Leveling"          # Open its download folder
  memanga doctor                        # Diagnose setup problems
  memanga cron install                  # Set up daily checks
  memanga config                        # Configure settings
  memanga config set KEY VALUE          # Change one setting
  memanga --config-dir DIR status       # Use another config directory
  memanga completion bash               # Print a shell completion script
"""
    if not _cli_only:
        _epilog += "  memanga --gui                         # Launch graphical interface\n"

    # A fixed prog keeps usage and error lines stable under both the
    # `memanga` script and `python -m memanga` (issue #248).
    parser = argparse.ArgumentParser(
        prog="memanga",
        description="📖 MeManga - Automatic manga downloader",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_epilog,
    )
    parser.add_argument(
        "-V", "--version", action="version", version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--config-dir", metavar="DIR",
        help=f"Use DIR for config.yaml and state.json"
             f"{'' if _cli_only else ', also with --gui'} "
             f"(default: ${CONFIG_DIR_ENV} or the platform config folder). "
             "Goes before the command.",
    )
    # In CLI-only Docker images (MEMANGA_CLI_ONLY=1) the GUI is not installed;
    # suppress the flag from help and reject it at runtime with a clear message.
    parser.add_argument(
        "--gui",
        action="store_true",
        help=argparse.SUPPRESS if _cli_only else "Launch the graphical user interface",
    )
    # Issue #226: output and logging. Like --config-dir these go before
    # the command; `check -q` keeps its own meaning (never prompt).
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "-v", "--verbose", action="count", default=0,
        help="Show more diagnostics on stderr (-v progress, -vv debug). "
             f"Overrides ${LOG_LEVEL_ENV}. Goes before the command.",
    )
    verbosity.add_argument(
        "-q", "--quiet", dest="log_quiet", action="store_true",
        help="Hide warning, progress and debug diagnostics; errors still "
             f"show. Overrides ${LOG_LEVEL_ENV}. Goes before the command.",
    )
    parser.add_argument(
        "--plain", action="store_true",
        help="Plain text output: no colour, emoji, borders or line wrapping "
             "(automatic when output is not a terminal). Goes before the "
             "command.",
    )
    parser.add_argument(
        "--log-file", action="store_true",
        help=f"Also write diagnostics to {LOG_FILE_NAME} in the config "
             "directory (rotated, with timestamps). Goes before the command.",
    )
    
    subparsers = parser.add_subparsers(dest="command", title="commands")
    
    # list
    p_list = subparsers.add_parser("list", aliases=["ls"], help="List tracked manga")
    p_list.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    p_list.add_argument("--status", action="append", choices=VALID_STATUSES,
                        help="Only show manga with this status (repeat for several)")
    p_list.add_argument("--sort", choices=LIST_SORT_KEYS, default=DEFAULT_LIST_SORT,
                        help=f"Sort order (default: {DEFAULT_LIST_SORT}, the order manga were added). "
                             "Ties keep list order; # stays the list number for #N")
    p_list.add_argument("--reverse", action="store_true",
                        help="Reverse the sort; manga with no numeric last chapter "
                             "or an unknown status stay last")
    p_list.set_defaults(func=cmd_list)
    
    # add
    p_add = subparsers.add_parser("add", help="Add a manga to track")
    p_add.add_argument("-t", "--title", help="Manga title")
    p_add.add_argument("-u", "--url", help="Primary source URL")
    p_add.add_argument("-b", "--backup", help="Backup source URL")
    p_add.add_argument("--fallback-days", type=_non_negative_int_arg,
                       help="Days to wait before using the backup (0 or more; "
                            f"default: {DEFAULT_FALLBACK_DELAY_DAYS}); needs --backup")
    p_add.add_argument("--status", choices=VALID_STATUSES,
                       help="Initial status (default: reading)")
    p_add.add_argument("--mode", choices=["auto", "manual"],
                       help="Desktop-app download mode (default: auto)")
    p_add_kindle = p_add.add_mutually_exclusive_group()
    p_add_kindle.add_argument("--kindle", dest="send_to_kindle", action="store_const", const=True,
                              help="Turn the desktop app's per-manga Kindle toggle on (default)")
    p_add_kindle.add_argument("--no-kindle", dest="send_to_kindle", action="store_const", const=False,
                              help="Turn the desktop app's per-manga Kindle toggle off")
    p_add.add_argument("-i", "--interactive", action="store_true",
                       help="Interactive mode (--status, --mode and --kindle/--no-kindle still apply)")
    p_add.add_argument("-f", "--force", "-y", "--yes", dest="force", action="store_true",
                       help="Add even if the source might be unsupported or a similar title is tracked")
    p_add.set_defaults(func=cmd_add)
    
    # remove
    p_remove = subparsers.add_parser("remove", aliases=["rm"], help="Remove a manga")
    p_remove.add_argument("target", help="Manga title, or #N for its number in 'memanga list'")
    p_remove.add_argument("-y", "--yes", action="store_true",
                          help="Skip the removal confirmation only (never purges history or deletes files)")
    # --purge is the pre-#349 spelling, kept as an alias.
    p_remove.add_argument("--purge-history", "--purge", dest="purge_history", action="store_true",
                          help="Also remove its download history")
    files_group = p_remove.add_mutually_exclusive_group()
    files_group.add_argument("--keep-files", action="store_true",
                             help="Keep its downloaded files (default; skips the interactive prompt)")
    files_group.add_argument("--delete-files", action="store_true",
                             help="Also delete its download folder (<download dir>/<title>)")
    p_remove.set_defaults(func=cmd_remove)

    # edit
    # Issue #350: only the fields given are changed. Issue #348: `edit` is
    # the command name, `update` stays an alias.
    p_update = subparsers.add_parser(
        "edit", aliases=["update"],
        help="Edit a manga's sources, title, status, mode, Kindle toggle or fallback delay",
        description="Change only the fields given; everything else is kept. Output format "
                    "is global (memanga config, or check --format); there is no per-manga format.",
    )
    p_update.add_argument("target", help="Manga title, or #N for its number in 'memanga list'")
    p_update.add_argument("-u", "--url", help="New primary source URL")
    p_update_backup = p_update.add_mutually_exclusive_group()
    p_update_backup.add_argument("-b", "--backup",
                                 help="Add a backup source URL, or replace the first backup")
    p_update_backup.add_argument("--no-backup", action="store_true",
                                 help="Remove every backup source and its fallback delay")
    p_update.add_argument("--fallback-days", type=_non_negative_int_arg,
                          help="Days to wait before using the backup (0 or more); "
                               "needs a backup source")
    p_update.add_argument("-t", "--title", help="Rename manga title (moves its history and downloads)")
    p_update.add_argument("--status", choices=VALID_STATUSES, help="New status")
    p_update.add_argument("--mode", choices=["auto", "manual"], help="Desktop-app download mode")
    p_update_kindle = p_update.add_mutually_exclusive_group()
    p_update_kindle.add_argument("--kindle", dest="send_to_kindle", action="store_const", const=True,
                                 help="Turn the desktop app's per-manga Kindle toggle on")
    p_update_kindle.add_argument("--no-kindle", dest="send_to_kindle", action="store_const", const=False,
                                 help="Turn the desktop app's per-manga Kindle toggle off")
    p_update.set_defaults(func=cmd_update)

    # set: deprecated by issue #348 in favour of `edit TARGET --status`.
    # Registered without help= so it stays out of the command list and the
    # completion script; it still runs for one release.
    p_set = subparsers.add_parser(
        "set",
        description="Deprecated: use 'memanga edit TARGET --status STATUS'. "
                    "'set' will be removed in the next release.",
    )
    p_set.add_argument("target", help="Manga title, or #N for its number in 'memanga list'")
    p_set.add_argument("status", choices=VALID_STATUSES, help="New status")
    p_set.set_defaults(func=cmd_set_status)

    # read / unread (issue #356): the read state the desktop reader keeps.
    for name, mark_read, help_text, all_help in (
        ("read", True, "Mark chapters of a manga as read",
         "Mark every downloaded chapter read"),
        ("unread", False, "Mark chapters of a manga as unread",
         "Mark every read chapter unread"),
    ):
        p_mark = subparsers.add_parser(
            name, help=help_text,
            description=(
                f"{help_text}, as the desktop app's reader and chapter list show it.\n\n"
                "CHAPTER is a chapter number or label from the manga's chapter list\n"
                "(downloaded, found by 'check', or marked read elsewhere); give one\n"
                "or more, or --all. Every CHAPTER is checked before anything changes.\n"
                "Marking read also resets the chapter's saved page, as finishing it\n"
                "in the reader does. Files and download history are never touched.\n\n"
                "Exit codes: 0 success (also when nothing needed changing); 1 the\n"
                "manga or a chapter was not found or is ambiguous; 2 usage error."
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        p_mark.add_argument("target", metavar="TARGET",
                            help="Manga title, or #N for its number in 'memanga list'")
        p_mark.add_argument("chapters", nargs="*", metavar="CHAPTER",
                            help="Chapter number or label, e.g. 12 or 10.5")
        p_mark.add_argument("--all", action="store_true", help=all_help)
        p_mark.set_defaults(func=cmd_read, mark_read=mark_read)

    # path / open (issue #357): the manga's download folder.
    for name, func, help_text, detail in (
        ("path", cmd_path, "Print the download folder of a manga",
         "Only the absolute path is printed to stdout, so scripts can use\n"
         "it: cd \"$(memanga path TARGET)\"."),
        ("open", cmd_open, "Open the download folder of a manga in the file manager",
         "Uses the system file manager (xdg-open on Linux)."),
    ):
        p_folder = subparsers.add_parser(
            name, help=help_text,
            description=(
                f"{help_text}: <download dir>/<title>, where its chapters are saved.\n"
                f"{detail}\n"
                "Nothing is created; a manga with nothing downloaded yet is an error.\n\n"
                "Exit codes: 0 success; 1 the manga was not found or is ambiguous,\n"
                "it has no download folder yet, or the folder could not be opened;\n"
                "2 usage error."
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        p_folder.add_argument("target", metavar="TARGET",
                              help="Manga title, or #N for its number in 'memanga list'")
        p_folder.set_defaults(func=func)

    # check
    p_check = subparsers.add_parser(
        "check",
        help="Check for new chapters",
        description=(
            "Check tracked manga for new chapters.\n\n"
            "Modes:\n"
            "  check --dry-run    check only: list what a download run would fetch;\n"
            "                     never downloads, delivers or changes state\n"
            "  check --download   download without prompting (--auto and --yes are\n"
            "                     aliases; scheduled runs use 'check --auto --quiet')\n"
            "  check              ask per chapter on a terminal; without a terminal,\n"
            "                     or with --quiet, download nothing and exit 1\n\n"
            "--dry-run wins over --download. --all and --from choose where to start;\n"
            "they don't download by themselves.\n\n"
            "Exit codes: 0 no new chapters, chapters listed or all downloaded, or a\n"
            "suspicious batch withheld (warning on stderr); 1 every checked manga\n"
            "failed, the target was not found, chapters needed confirmation, or\n"
            "state.json could not be written; 2 usage error; 3 some chapters or\n"
            "manga failed; 130 interrupted; 143 terminated (SIGTERM)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Issue #248: positional TARGET like edit/remove; -t stays.
    p_check.add_argument("target", nargs="?", metavar="TARGET",
                         help="Check one manga only (title, or #N from 'memanga list')")
    p_check.add_argument("-t", "--title", help="Same as TARGET")
    p_check.add_argument("-f", "--from", dest="from_chapter", type=float, help="Start from chapter N (for fresh downloads)")
    p_check.add_argument("--all", action="store_true", help="Start from the first chapter (backfill; skips the suspicious-batch check)")
    p_check.add_argument("--download", "-a", "--auto", "-y", "--yes", dest="download", action="store_true",
                         help="Download new chapters without prompting (--auto and --yes are aliases)")
    p_check.add_argument("-q", "--quiet", action="store_true",
                         help="Never prompt; without --download, new chapters are skipped and the run exits 1 "
                              "(to hide warnings, use `memanga -q check`)")
    p_check.add_argument("-s", "--safe", action="store_true", help="Safe mode: restart browser every 3 chapters (for bulk downloads)")
    p_check.add_argument("-n", "--dry-run", action="store_true",
                         help="Check only: list what would be downloaded; no downloads or state changes (wins over --download)")
    p_check.add_argument("--force-suspicious", action="store_true", help="Accept a chapter batch even if it was flagged as suspicious")
    p_check.add_argument("--format", choices=["pdf", "epub", "cbz", "zip", "jpg", "png", "webp"], help="Output format (overrides config)")
    p_check.add_argument("--retries", type=int, default=DEFAULT_PAGE_RETRIES, metavar="N",
                         help=f"Retry failed page downloads N times (default: {DEFAULT_PAGE_RETRIES}, 0 to disable)")
    # Partial-chapter tolerance (issue #86) — config is the source of truth;
    # these override it for a single run.
    partial_grp = p_check.add_mutually_exclusive_group()
    partial_grp.add_argument("--allow-partial", action="store_true", help="Keep a chapter with a few missing pages instead of discarding it (issue #86)")
    partial_grp.add_argument("--no-partial", action="store_true", help="Force-discard any chapter with missing pages, even if partial tolerance is enabled in config")
    p_check.add_argument("--partial-threshold", type=_partial_threshold_arg, metavar="PCT", help="Max %% of pages allowed to fail before a partial is refused, 0-100 (default: config value)")
    p_check.set_defaults(func=cmd_check)
    
    # status
    p_status = subparsers.add_parser("status", help="Show status and configuration")
    p_status.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    p_status.set_defaults(func=cmd_status)
    
    # config
    p_config = subparsers.add_parser("config", help="Configure settings")
    p_config.add_argument("--show", action="store_true", help="Show current config")
    p_config.add_argument(
        "--mangadex-quality", choices=["original", "data-saver"],
        help="Select MangaDex chapter image quality",
    )
    p_config.add_argument(
        "--mangadex-remove-group", type=_mangadex_group_id_arg, metavar="GROUP_ID",
        help="Block a scanlation group's MangaDex chapters by group ID",
    )
    # Non-interactive partial-chapter tolerance controls (issue #86). When
    # omitted, `config` stays interactive.
    p_config.add_argument(
        "--partial", choices=["on", "off"],
        help="Enable/disable partial-chapter tolerance without prompting",
    )
    p_config.add_argument(
        "--partial-threshold", type=_partial_threshold_arg, metavar="PCT",
        help="Persist the max %% of pages allowed to fail (0-100)",
    )
    p_config.set_defaults(func=cmd_config)
    # Scriptable actions (issue #353). Without one, `config` keeps the
    # flags above and the interactive wizard.
    config_keys_help = "KEY is one of: " + ", ".join(CONFIG_KEYS)
    config_actions = p_config.add_subparsers(dest="config_action", title="actions", metavar="ACTION")
    p_cfg_show = config_actions.add_parser(
        "show", help="Show the current config (app password masked)")
    p_cfg_show.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    p_cfg_get = config_actions.add_parser(
        "get", help="Print one setting's value", description=config_keys_help)
    p_cfg_get.add_argument("key", metavar="KEY")
    p_cfg_set = config_actions.add_parser(
        "set", help="Change one setting",
        description=config_keys_help + ". For email.app_password pass '-' "
                    "and send the value on stdin, or omit VALUE on a terminal "
                    "to be prompted.")
    p_cfg_set.add_argument("key", metavar="KEY")
    p_cfg_set.add_argument("value", nargs="?", metavar="VALUE")
    config_actions.add_parser("path", help="Print the config file path")
    config_actions.add_parser(
        "edit", help="Open config.yaml in $VISUAL or $EDITOR, then check it")
    p_cfg_email = config_actions.add_parser(
        "email", help="Show email delivery settings (app password masked)")
    p_cfg_email.add_argument("--test", action="store_true",
                             help="Log in to the configured SMTP server (network)")
    
    # cron
    p_cron = subparsers.add_parser("cron", help="Manage cron job")
    p_cron.add_argument("action", choices=["status", "install", "remove"], help="Action")
    p_cron.add_argument("--time", help="Check time (HH:MM) for install")
    p_cron.set_defaults(func=cmd_cron)
    
    # sources
    p_sources = subparsers.add_parser("sources", help="List supported sources")
    p_sources.set_defaults(func=cmd_sources)

    # search
    p_search = subparsers.add_parser("search", help="Search sources for a manga by title")
    p_search.add_argument("query", help="Manga title to search for")
    p_search.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    # Completion offers every supported source (`memanga sources`); the
    # value stays free-form, e.g. www. or a subdomain (issue #260).
    completion.suggest(
        p_search.add_argument("--source", help="Search a single source only (e.g. mangadex.org)"),
        get_supported_sources,
    )
    p_search.add_argument("--limit", type=int, metavar="N", help="Cap results per source")
    p_search.add_argument("--add", type=int, metavar="N", help="Add result #N without prompting")
    p_search.add_argument("--status", choices=VALID_STATUSES, help="Status for the added manga (with --add or the prompt)")
    p_search.add_argument("--no-chips", action="store_true", help="Skip chapter-count probes (faster)")
    p_search.set_defaults(func=cmd_search)

    # export
    p_export = subparsers.add_parser("export", help="Export manga list and state to JSON")
    p_export.add_argument("file", nargs="?", default=DEFAULT_EXPORT_FILE,
                          help=f"Output file, or - for stdout (default: {DEFAULT_EXPORT_FILE})")
    p_export.set_defaults(func=cmd_export)

    # import
    p_import = subparsers.add_parser("import", help="Import manga list and state from JSON")
    p_import.add_argument("file", help="JSON file to import, or - for stdin")
    p_import.add_argument("--replace", action="store_true", help="Replace all data instead of merging (asks first; see --yes)")
    p_import.add_argument("--dry-run", action="store_true", help="Validate the backup and show what would change, without writing")
    p_import.add_argument("-y", "--yes", action="store_true", help="Confirm --replace without prompting (required when not interactive or reading stdin)")
    p_import.set_defaults(func=cmd_import)

    # failed
    p_failed = subparsers.add_parser(
        "failed",
        help="List, retry or clear failed and partial chapter downloads",
        description=(
            "List, retry or clear chapters that failed or were saved as partial.\n\n"
            "Actions:\n"
            "  failed [list [TARGET]]   list the records (the default)\n"
            "  failed retry [TARGET]    download the chapters again the way 'check'\n"
            "                           does: backup source, partial rules, delivery\n"
            "  failed clear [TARGET]    forget the records without downloading\n\n"
            "TARGET is a title or '#N' from 'memanga list', matched like 'check -t';\n"
            "without it every manga is included. '--retry' and '--clear' are kept as\n"
            "aliases of 'failed retry' and 'failed clear'. '--json' only lists.\n\n"
            "Exit codes: 0 success; 1 the target was not found or is ambiguous;\n"
            "2 usage error; 3 retry left some chapters failed or partial."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_failed.add_argument("-t", "--title", help="Only this manga (title, or #N from 'memanga list'); same as TARGET")
    p_failed.add_argument("--retry", action="store_true", help="Alias of 'failed retry'")
    p_failed.add_argument("--clear", action="store_true", help="Alias of 'failed clear'")
    p_failed.add_argument("--json", action="store_true", help="Machine-readable JSON output (listing only)")
    p_failed.set_defaults(func=cmd_failed)
    failed_actions = p_failed.add_subparsers(dest="failed_action", title="actions", metavar="ACTION")
    for name, help_text in (
        ("list", "List failed and partial chapters (default)"),
        ("retry", "Download the listed chapters again"),
        ("clear", "Forget the listed records without downloading"),
    ):
        p_action = failed_actions.add_parser(name, help=help_text, description=help_text + ".")
        # SUPPRESS keeps these from overwriting the same options given
        # before the action (`failed -t X retry`).
        p_action.add_argument("target", nargs="?", default=argparse.SUPPRESS, metavar="TARGET",
                              help="Title or #N from 'memanga list' (default: every manga)")
        p_action.add_argument("-t", "--title", default=argparse.SUPPRESS,
                              help="Same as TARGET")
        if name == "list":
            p_action.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                                  help="Machine-readable JSON output")

    # doctor (issue #250)
    p_doctor = subparsers.add_parser(
        "doctor",
        help="Diagnose setup problems (runtime/install, paths, browsers, email, scheduler)",
        description="Run local health checks. Exits 0 when no check fails, "
                    "1 when any selected check fails.",
    )
    p_doctor.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    p_doctor.add_argument(
        "--check", action="append", choices=doctor.CHECK_NAMES, metavar="NAME",
        help="Run only this check; repeatable. One of: " + ", ".join(doctor.CHECK_NAMES),
    )
    p_doctor.add_argument("--smtp", action="store_true",
                          help="Log in to the configured SMTP server (network; skipped by default)")
    p_doctor.add_argument("--launch-browsers", action="store_true",
                          help="Launch Firefox and Chromium headless instead of only checking they are installed")
    p_doctor.add_argument("--strict", action="store_true", help="Also exit non-zero on warnings")
    p_doctor.set_defaults(func=cmd_doctor)

    # tui (default if no command)
    p_tui = subparsers.add_parser("tui", help="Interactive terminal UI")
    p_tui.set_defaults(func=cmd_tui)

    # completion (issue #248)
    p_completion = subparsers.add_parser(
        "completion",
        help="Print a shell completion script (bash)",
        description=(
            "Print a completion script for SHELL to stdout. Only bash is\n"
            "supported for now.\n\n"
            "Load it for the current session, or add the line to ~/.bashrc:\n"
            "  source <(memanga completion bash)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_completion.add_argument("shell", choices=completion.SHELLS, help="Target shell")
    p_completion.set_defaults(func=cmd_completion)

    # Keep the deprecated `set` out of the usage line too; argparse would
    # otherwise list every registered name there.
    subparsers.metavar = "{" + ",".join(
        name for name, sub in subparsers.choices.items() if sub is not p_set
    ) + "}"

    return parser


def _main():
    _cli_only = bool(os.environ.get("MEMANGA_CLI_ONLY"))
    parser = build_parser()
    p_check = _subparser(parser, "check")
    p_config = _subparser(parser, "config")
    p_failed = _subparser(parser, "failed")

    args = parser.parse_args()
    _configure_output(args)

    if args.command == "check":
        if args.target and args.title and args.target != args.title:
            p_check.error("give the target once: TARGET or -t/--title")
        args.title = args.title or args.target

    if args.command == "failed":
        action = getattr(args, "failed_action", None)
        if action and (args.retry or args.clear):
            p_failed.error(f"--retry/--clear cannot be combined with the '{action}' action")
        # Keep `failed --json` a pure listing contract instead of mixing
        # retry/clear progress output into machine-readable stdout.
        if args.json and _failed_action(args) != "list":
            p_failed.error("--json cannot be combined with retry or clear (--retry/--clear)")
        target = getattr(args, "target", None)
        if target and args.title and target != args.title:
            p_failed.error("give the target once: TARGET or -t/--title")

    if args.command in ("read", "unread"):
        if args.all and args.chapters:
            _subparser(parser, args.command).error("give CHAPTER arguments or --all, not both")
        if not args.all and not args.chapters:
            _subparser(parser, args.command).error("give at least one CHAPTER, or --all")

    if args.command == "config" and args.config_action:
        legacy = [flag for flag, value in (
            ("--show", args.show),
            ("--mangadex-quality", args.mangadex_quality),
            ("--mangadex-remove-group", args.mangadex_remove_group),
            ("--partial", args.partial),
            ("--partial-threshold", args.partial_threshold),
        ) if value is not None and value is not False]
        if legacy:
            p_config.error(f"{legacy[0]} cannot be combined with the "
                           f"'{args.config_action}' action")

    # Needs no config or state, so it works before setup and never
    # writes to the config directory.
    if args.command == "completion" and not args.gui:
        sys.exit(args.func(args))
    # The GUI selects the same way (issue #249): main() loads Config/State
    # in the selected root and hands them, and an explicit choice, to
    # launch_gui().
    config_dir = resolve_config_dir(args.config_dir)
    # Issue #244: lock before loading, so no other process can write
    # between this load and our last save.
    lock_dir = config_dir or default_config_dir()
    locked = _needs_config_lock(args)
    if locked:
        _acquire_config_lock(lock_dir)
    if config_dir is None:
        lock_dir = _revalidate_default_root(lock_dir, locked)
    ctx = build_context(config_dir, recover_state=locked, root=lock_dir)
    # A read-only command found a damaged state.json: repair it only
    # while holding the lock (kept until main() ends), else leave it
    # untouched and report it through state.load_error.
    if ctx.state.needs_recovery and _acquire_config_lock(lock_dir, required=False):
        ctx = build_context(config_dir, root=lock_dir)
    use_context(ctx)
    _enable_log_file(args, lock_dir)

    # Only doctor and `config path/edit` may run on fallback defaults;
    # anything else could act on an empty manga list or overwrite the
    # user's broken config.
    broken_config_ok = args.command == "doctor" or (
        args.command == "config"
        and getattr(args, "config_action", None) in CONFIG_ACTIONS_ON_BROKEN_CONFIG
    )
    if config.load_error and not broken_config_ok:
        sys.stderr.write(
            f"error: cannot load config file {config.config_path}: {config.load_error}\n"
            "Fix or move the file, then retry. Run `memanga doctor` for details.\n"
        )
        sys.exit(1)
    # Issue #243: same rule for a state file that could not be loaded,
    # copied aside or restored; a damaged file that was copied aside and
    # replaced only warns.
    if state.load_error and not broken_config_ok:
        sys.stderr.write(
            f"error: cannot load state file: {state.load_error}\n"
            "Fix or move the file, then retry. Run `memanga doctor` for details.\n"
        )
        sys.exit(1)
    if state.recovery_notice:
        sys.stderr.write(f"warning: {state.recovery_notice}\n")

    if args.gui:
        if _cli_only:
            sys.stderr.write(
                "error: --gui is not available in this image (CLI-only Docker build)\n"
            )
            sys.exit(1)
        from .gui import launch_gui
        # Hand over the loaded state so the GUI can show its recovery
        # notice; a second State() would find the repaired file.
        launch_gui(config=config, state=state, explicit_config_dir=config_dir)
        return

    with _sigterm_as_shutdown():
        if args.command is None:
            # Default to TUI, but never drop automation into the menu (#258).
            if not _stdin_is_tty():
                parser.print_help(sys.stderr)
                sys.exit(cmd_tui(args))
            cmd_tui(args)
        elif hasattr(args, 'func'):
            result = args.func(args)
            if result:
                sys.exit(result)
        else:
            parser.print_help()


if __name__ == "__main__":
    main()
