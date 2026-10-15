#!/usr/bin/env python3
"""
MeManga - Automatic manga downloader for Kindle
A friendly CLI for tracking and downloading manga chapters.
"""

import argparse
import json
import os
import platform
import sys
import subprocess
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, Optional

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.table import Table
from rich import box

from .backup import (
    EXPORT_VERSION,
    BackupVersionError,
    validate_backup,
)
from .config import (CONFIG_DIR_ENV, Config, ConfigDirError, default_config_dir,
                     ensure_config_dir, get_app_password, resolve_config_dir,
                     set_app_password)
from .cron import (build_cron_line, build_task_command, managed_lines,
                   read_crontab,
                   remove_managed_lines, replace_managed_line,
                   source_checkout_root, unmanaged_memanga_lines)
from . import doctor
from .state import State
from .downloader import check_for_updates, download_chapter, get_supported_sources, DownloaderError, ChapterWithSource, restart_browsers, _find_chapter_on_backup, _get_sources_from_manga
from .scrapers import get_scraper
from .search import compute_search_sources, probe_chapter_counts, sweep
from .emailer import send_to_kindle, EmailError

console = Console()
# Issue #239: diagnostics (errors, refused or degraded work) go to stderr
# so stdout carries only command results.
err_console = Console(stderr=True)

# Issue #239: CLI exit codes.
EXIT_OK = 0
EXIT_ERROR = 1          # operational error: not found, invalid input, refused
EXIT_USAGE = 2          # usage error (raised by argparse itself)
EXIT_PARTIAL = 3        # check / failed --retry ran but some chapters failed
EXIT_INTERRUPTED = 130  # Ctrl-C


def _esc(value) -> str:
    """Escape data (titles, statuses, paths, errors) for interpolation
    into Rich markup so brackets render literally (issue #375)."""
    return escape(str(value))


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
    # Resolved root (the default included, issue #259), or None only
    # when a caller built the context without one.
    config_dir: Optional[Path] = None


# Context of the running command. Bound by use_context() once main()
# has parsed the arguments, never at import: building Config/State
# creates the config directory.
_context: Optional[CliContext] = None
config: Optional[Config] = None
state: Optional[State] = None


def build_context(config_dir=None) -> CliContext:
    """Build Config and State under ``config_dir`` (None = default).

    Config is tolerant so a broken config.yaml still reaches `doctor`;
    main() refuses every other command (issue #250).
    """
    return CliContext(
        config=Config(config_dir, tolerate_errors=True),
        state=State(config_dir),
        config_dir=config_dir,
    )


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


def _list_payload() -> Dict[str, Any]:
    """`list --json` payload: one entry per tracked manga, in list order."""
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
        })
    return {
        "schema_version": JSON_SCHEMA_VERSION,
        "count": len(entries),
        "manga": entries,
    }


def cmd_list(args):
    """List all tracked manga."""
    if getattr(args, "json", False):
        _print_json(_list_payload())
        return

    manga_list = config.get("manga", [])
    
    if not manga_list:
        console.print("[dim]No manga tracked yet. Use [cyan]memanga add[/cyan] to add some![/dim]")
        return
    
    table = Table(
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
    
    for i, manga in enumerate(manga_list, 1):
        title = manga["title"]
        last_ch = state.get_last_chapter(title)
        downloaded = state.get_downloaded_chapters(title)
        
        table.add_row(
            str(i),
            _esc(title),
            _get_status_display(manga),
            _esc(_get_sources_display(manga)),
            str(last_ch) if last_ch else "—",
            str(len(downloaded)) if downloaded else "0",
        )
    
    console.print(table)


def _ask_fallback_days() -> int:
    """Prompt until the fallback delay is a whole number of days >= 0."""
    while True:
        days = IntPrompt.ask("⏱️  Fallback delay (days)", default=2)
        if days >= 0:
            return days
        console.print("[prompt.invalid]Please enter 0 or more days")


def cmd_add(args):
    """Add a manga to track."""
    from urllib.parse import urlparse
    
    backup_url = None
    fallback_days = 2
    
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
        
        sources = get_supported_sources()
        console.print(f"[dim]Supported sources:[/dim] {_esc(', '.join(sources))}\n")
        
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
        if fallback_days is None:
            fallback_days = 2
        
        if not title or not url:
            return _error("[red]Error:[/red] --title and --url required (or use --interactive)")
    
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
        err_console.print(f"[dim]Supported: {_esc(', '.join(supported))}[/dim]")
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
            return

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


def cmd_remove(args):
    """Remove a manga from tracking."""
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

    if args.yes or Confirm.ask(f"Remove [cyan]{_esc(found['title'])}[/cyan]?"):
        manga_list.pop(found_idx)
        config.set("manga", manga_list)
        config.save()
        
        # Download history is only purged on request: --yes confirms the
        # removal itself, not this extra cleanup (issue #237).
        purge = getattr(args, "purge", False)
        if not purge and not args.yes:
            purge = Confirm.ask("Also remove download history?", default=False)
        if purge:
            manga_state = state.get("manga", {})
            if found["title"] in manga_state:
                del manga_state[found["title"]]
                state.set("manga", manga_state)
        
        console.print(f"[red]🗑️  Removed:[/red] {_esc(found['title'])}")


def cmd_set_status(args):
    """Set manga status (reading, on-hold, dropped, completed)."""
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


def cmd_update(args):
    """Update manga details (URL, backup, title)."""
    from urllib.parse import urlparse

    manga_list = config.get("manga", [])

    if not manga_list:
        return _error("[yellow]No manga tracked.[/yellow]")

    found, found_idx, candidates = _find_manga(args.target, manga_list)

    if not found:
        return _target_error(args.target, candidates)

    old_title = found["title"]
    changes = []

    # Update URL
    if args.url:
        new_source = urlparse(args.url).netloc.replace("www.", "")
        if "sources" in found:
            found["sources"][0] = {"url": args.url, "source": new_source}
        else:
            found["source"] = new_source
            found["url"] = args.url
        changes.append(f"URL → {new_source}")

    # Update backup
    if args.backup:
        backup_source = urlparse(args.backup).netloc.replace("www.", "")
        if "sources" in found:
            if len(found["sources"]) > 1:
                found["sources"][1] = {"url": args.backup, "source": backup_source}
            else:
                found["sources"].append({"url": args.backup, "source": backup_source})
        else:
            # Convert to multi-source format
            primary_url = found.pop("url", "")
            primary_source = found.pop("source", "")
            found["sources"] = [
                {"url": primary_url, "source": primary_source},
                {"url": args.backup, "source": backup_source},
            ]
            found.setdefault("fallback_delay_days", 2)
        changes.append(f"Backup → {backup_source}")

    # Rename title
    if args.title:
        found["title"] = args.title
        # Migrate state (download history) to new title
        manga_state = state.get("manga", {})
        if old_title in manga_state:
            manga_state[args.title] = manga_state.pop(old_title)
            state.set("manga", manga_state)
        # Move already-downloaded files so they stay reachable under the
        # new title (folder + filenames are keyed by title).
        from .downloader import rename_manga_downloads
        try:
            rename_manga_downloads(config.download_dir, old_title, args.title)
        except Exception:
            pass
        changes.append(f"Title → {args.title}")

    if not changes:
        return _error("[yellow]No changes specified. Use --url, --backup, or --title.[/yellow]")

    manga_list[found_idx] = found
    config.set("manga", manga_list)
    config.save()

    console.print(f"[green]Updated [cyan]{_esc(old_title)}[/cyan]:[/green]")
    for c in changes:
        console.print(f"  {_esc(c)}")


def cmd_check(args):
    """Check for new chapters and download."""
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

    console.print(f"[dim]=== {datetime.now().strftime('%Y-%m-%d %H:%M')} ===[/dim]")

    if dry_run:
        console.print(Panel("[bold]🔍 Dry Run — Checking for New Chapters[/bold]", border_style="yellow"))
    elif from_chapter is not None and from_chapter == 0:
        console.print(Panel("[bold]📥 Downloading All Chapters[/bold]", border_style="green"))
    elif from_chapter is not None:
        console.print(Panel(f"[bold]📥 Downloading from Chapter {from_chapter}[/bold]", border_style="green"))
    else:
        console.print(Panel("[bold]🔍 Checking for New Chapters[/bold]", border_style="blue"))
    console.print()
    
    total_new = 0
    total_downloaded = 0
    total_failed = 0
    # Manga checked, and those whose check itself errored (#239).
    total_checked = 0
    total_errored = 0
    # Chapters left undownloaded because no one could confirm them (#258).
    total_unconfirmed = 0
    interactive = _stdin_is_tty()

    delivery_mode = config.delivery_mode
    download_dir = config.download_dir
    output_format = getattr(args, 'format', None) or config.output_format
    email_cfg = config.get("email", {})
    post_processing = config.get("delivery.post_processing")

    # Partial-chapter tolerance (issue #86). Config is the source of truth;
    # `check` flags can override it for a single run.
    allow_partial = config.partial_enabled
    if getattr(args, 'allow_partial', False):
        allow_partial = True
    if getattr(args, 'no_partial', False):
        allow_partial = False
    partial_threshold = getattr(args, 'partial_threshold', None)
    if partial_threshold is None:
        partial_threshold = config.partial_threshold

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
            new_chapters = check_for_updates(
                manga, state,
                from_chapter=from_chapter,
                force_suspicious=force_suspicious,
            )

            # A batch that doesn't fit this manga's history was withheld
            # because it couldn't be confirmed by a backup source.
            suspicious = state.get_suspicious_batch(title) if from_chapter is None else None
            if suspicious:
                err_console.print(
                    f"  [yellow]└─ Warning: Suspicious chapter batch detected: "
                    f"{_esc(suspicious.get('count'))} chapter(s) up to "
                    f"{_esc(suspicious.get('highest'))} "
                    f"(last tracked: {_esc(suspicious.get('last_chapter'))})[/yellow]"
                )
                for reason in suspicious.get("reasons", []):
                    err_console.print(f"     [dim]- {_esc(reason)}[/dim]")
                err_console.print(f"     [dim]- {_esc(suspicious.get('backup_status'))}[/dim]")
                err_console.print(
                    "     [yellow]Skipped auto-delivery. Run "
                    "'memanga check --force-suspicious' to accept anyway.[/yellow]"
                )

            if not new_chapters:
                if not suspicious:
                    console.print("  [dim]└─ No new chapters[/dim]")
                continue
            
            console.print(f"  [green]└─ {len(new_chapters)} new chapter(s)![/green]")
            total_new += len(new_chapters)
            
            for ch in new_chapters:
                ch_label = f"Chapter {ch.number}"
                if ch.title:
                    ch_label += f": {ch.title}"
                # Chapter titles are scraped data; escape before markup use.
                ch_label = _esc(ch_label)

                # Dry run: just list chapters
                if dry_run:
                    source_info = ""
                    if isinstance(ch, ChapterWithSource) and ch.is_backup:
                        source_info = f" [yellow](backup: {_esc(ch.source)})[/yellow]"
                    console.print(f"     [dim][DRY RUN][/dim] {ch_label}{source_info}")
                    total_downloaded += 1
                    continue

                # Download automatically or prompt
                should_download = args.auto or args.yes
                if not should_download and not interactive:
                    # Even --quiet must not hide missing input (#258).
                    total_unconfirmed += 1
                    continue
                if not should_download and not args.quiet:
                    should_download = Confirm.ask(f"     Download {ch_label}?", default=True)

                if not should_download:
                    continue

                max_retries = getattr(args, 'retries', 3)

                # Captures partial-download details from download_chapter so
                # we can surface which pages are missing without parsing the
                # log line. Reset per attempt.
                partial_info = {}

                def _capture_partial(failed_pages, total, _info=partial_info):
                    _info["failed_pages"] = failed_pages
                    _info["total"] = total

                def _deliver_email(file_path):
                    """Send to Kindle if configured (skips image folders)."""
                    if not (delivery_mode == "email" and email_cfg.get("kindle_email")):
                        return
                    if file_path.is_dir():
                        console.print("     [dim]📧 Skipped email (image folders cannot be emailed)[/dim]")
                        return
                    console.print("     [dim]📧 Sending to Kindle...[/dim]")
                    try:
                        send_to_kindle(
                            pdf_path=file_path,
                            kindle_email=email_cfg["kindle_email"],
                            sender_email=email_cfg["sender_email"],
                            smtp_server=email_cfg.get("smtp_server", "smtp.gmail.com"),
                            smtp_port=email_cfg.get("smtp_port", 587),
                            app_password=get_app_password(config),
                        )
                        console.print("     [green]📬 Sent to Kindle![/green]")
                        if config.get("delivery.delete_after_send", False):
                            file_path.unlink()
                            console.print("     [dim]🗑️  Deleted local copy[/dim]")
                    except EmailError as email_e:
                        err_console.print(f"     [red]📧 Email failed: {_esc(email_e)}[/red]")

                def _announce_saved(file_path, from_backup, partial, source=None):
                    """Print the save line and, for partials, warn + log which
                    pages are missing so headless runs leave a trail."""
                    label = _esc(f"{file_path.parent.name}/{file_path.name}/" if file_path.is_dir() else file_path.name)
                    src = " from backup" if from_backup else ""
                    if partial:
                        miss = partial.get("failed_pages", [])
                        total = partial.get("total", 0)
                        err_console.print(
                            f"     [yellow]⚠️  Saved partial{src}: {label} — "
                            f"{len(miss)}/{total} page(s) missing (pages {_esc(miss)})[/yellow]"
                        )
                        state.add_notification(
                            "warn",
                            f"'{title}' Chapter {ch.number} saved as partial: "
                            f"{len(miss)}/{total} page(s) missing (pages {miss}).",
                        )
                        state.add_partial_chapter(
                            title,
                            ch.number,
                            source=source or "",
                            failed_pages=miss,
                            total_pages=total,
                            path=str(file_path),
                            from_backup=from_backup,
                        )
                    else:
                        state.clear_partial_chapter(title, ch.number)
                        console.print(f"     [green]✅ Saved{src}: {label}[/green]")

                try:
                    # Show source info if from backup
                    source_info = ""
                    if isinstance(ch, ChapterWithSource) and ch.is_backup:
                        source_info = f" [yellow](from backup: {_esc(ch.source)})[/yellow]"

                    console.print(f"     [dim]⬇️  Downloading {ch_label}...{source_info}[/dim]")

                    # Only accept a partial straight away when there's no
                    # backup to try first — otherwise we prefer a complete
                    # download from the backup (issue #86 direction).
                    is_from_backup = isinstance(ch, ChapterWithSource) and ch.is_backup
                    has_backup = (not is_from_backup) and len(_get_sources_from_manga(manga)) > 1
                    primary_allow_partial = allow_partial and not has_backup

                    partial_info.clear()
                    file_path = download_chapter(
                        manga, ch, download_dir, output_format,
                        max_retries=max_retries,
                        post_processing=post_processing,
                        allow_partial=primary_allow_partial,
                        partial_threshold=partial_threshold,
                        on_partial=_capture_partial,
                    )
                    _announce_saved(
                        file_path,
                        from_backup=False,
                        partial=dict(partial_info),
                        source=getattr(ch, "source", None) or "unknown",
                    )
                    _deliver_email(file_path)

                    # Update state
                    state.add_downloaded_chapter(title, ch.number)
                    state.clear_pending_backup(title, ch.number)
                    state.clear_failed_chapter(title, ch.number)
                    total_downloaded += 1

                    # Safe mode: restart browser every 3 chapters to free memory
                    safe_mode = getattr(args, 'safe', False)
                    if safe_mode and total_downloaded % 3 == 0:
                        restart_browsers()

                except DownloaderError as e:
                    ch_source = ch.source if isinstance(ch, ChapterWithSource) else "unknown"
                    is_from_backup = isinstance(ch, ChapterWithSource) and ch.is_backup

                    backup_ch = None
                    if not is_from_backup:
                        backup_ch = _find_chapter_on_backup(manga, ch.number)

                    saved = False
                    backup_e = None

                    # 1) Try a complete download from the backup source.
                    if backup_ch:
                        err_console.print(f"     [yellow]⚠️  Primary failed ({_esc(e)}), trying backup ({_esc(backup_ch.source)})...[/yellow]")
                        try:
                            file_path = download_chapter(
                                manga, backup_ch, download_dir, output_format,
                                max_retries=max_retries,
                                post_processing=post_processing,
                            )
                            _announce_saved(
                                file_path,
                                from_backup=True,
                                partial=None,
                                source=getattr(backup_ch, "source", None),
                            )
                            _deliver_email(file_path)
                            state.add_downloaded_chapter(title, ch.number)
                            state.clear_pending_backup(title, ch.number)
                            state.clear_failed_chapter(title, ch.number)
                            total_downloaded += 1
                            saved = True
                        except DownloaderError as be:
                            backup_e = be
                            err_console.print(f"     [red]❌ Backup also failed: {_esc(be)}[/red]")

                    # 2) Both sources failed to deliver a complete chapter.
                    #    If partial tolerance is on, salvage the best partial
                    #    (backup first, then primary) within the threshold.
                    if not saved and allow_partial:
                        salvage = []
                        if backup_ch:
                            salvage.append((backup_ch, True))
                        # Skip the primary here if we already tried it with
                        # partial enabled above (no backup case).
                        if not primary_allow_partial:
                            salvage.append((ch, False))
                        for cand, from_backup in salvage:
                            partial_info.clear()
                            try:
                                file_path = download_chapter(
                                    manga, cand, download_dir, output_format,
                                    max_retries=max_retries,
                                    post_processing=post_processing,
                                    allow_partial=True,
                                    partial_threshold=partial_threshold,
                                    on_partial=_capture_partial,
                                )
                            except DownloaderError:
                                continue
                            _announce_saved(
                                file_path,
                                from_backup=from_backup,
                                partial=dict(partial_info),
                                source=getattr(cand, "source", None),
                            )
                            _deliver_email(file_path)
                            state.add_downloaded_chapter(title, ch.number)
                            state.clear_pending_backup(title, ch.number)
                            state.clear_failed_chapter(title, ch.number)
                            total_downloaded += 1
                            saved = True
                            break

                    # 3) Nothing worked — record the failure.
                    if not saved:
                        if backup_ch and backup_e is not None:
                            err_console.print(f"     [red]❌ Failed: {_esc(e)}[/red]")
                            state.add_failed_chapter(
                                title, ch.number,
                                f"{ch_source}+{backup_ch.source}",
                                f"Primary: {e}; Backup: {backup_e}",
                                failed_pages=getattr(e, "failed_pages", None),
                            )
                        else:
                            err_console.print(f"     [red]❌ Failed: {_esc(e)}[/red]")
                            state.add_failed_chapter(
                                title, ch.number, ch_source, str(e),
                                failed_pages=getattr(e, "failed_pages", None),
                            )
                        total_failed += 1

        except DownloaderError as e:
            err_console.print(f"  [red]└─ Error: {_esc(e)}[/red]")
            total_errored += 1
        except Exception as e:
            err_console.print(f"  [red]└─ Unexpected error: {_esc(e)}[/red]")
            total_errored += 1
    
    # Record check history with actual counts
    state.update_last_check(new_chapters=total_new, downloaded=total_downloaded)

    # Summary
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
        err_console.print(f"[yellow]⚠️  {total_failed} chapter(s) failed — run 'memanga failed' for details.[/yellow]")
    if total_errored:
        err_console.print(f"[yellow]⚠️  {total_errored}/{total_checked} manga could not be checked.[/yellow]")
    if total_unconfirmed:
        return _non_interactive_error(
            f"skipped {total_unconfirmed} chapter(s) that need confirmation; "
            "pass --auto or --yes to download without prompting"
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

    console.print(Panel("[bold]📊 MeManga Status[/bold]", border_style="blue"))
    console.print()
    
    # Configuration
    table = Table(title="Configuration", box=box.SIMPLE, show_header=False)
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


def cmd_config(args):
    """Configure MeManga settings."""
    if args.show:
        # Show current config (mask sensitive fields)
        import copy
        import yaml
        display = copy.deepcopy(config._data)
        pw = display.get("email", {}).get("app_password", "")
        if pw:
            display["email"]["app_password"] = "****"
        console.print(Panel("[bold]Current Configuration[/bold]", border_style="cyan"))
        console.print(_esc(yaml.dump(display, default_flow_style=False)))
        return

    # Non-interactive config for partial-chapter tolerance (issue #86).
    # When any of these flags are given, persist them and return without
    # dropping into the interactive prompt flow.
    partial = getattr(args, "partial", None)
    threshold = getattr(args, "partial_threshold", None)
    if partial is not None or threshold is not None:
        if partial is not None:
            config.set("partial_chapters.enabled", partial == "on")
        if threshold is not None:
            # Already validated to [0, 100] by the argparse type.
            config.set("partial_chapters.threshold_percent", float(threshold))
        config.save()

        state_str = "enabled" if config.partial_enabled else "disabled"
        console.print(
            f"[green]✅ Partial-chapter tolerance {state_str}[/green] "
            f"[dim](threshold: {config.partial_threshold:g}%)[/dim]"
        )
        return

    if not _stdin_is_tty():
        return _non_interactive_error(
            "interactive config needs a terminal; use --show or --partial/--partial-threshold"
        )

    console.print(Panel("[bold]⚙️  Configure MeManga[/bold]", border_style="yellow"))
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
    
    console.print(Panel("[bold]🌐 Supported Sources[/bold]", border_style="cyan"))
    console.print()
    
    table = Table(box=box.SIMPLE)
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

    table = Table(box=box.SIMPLE)
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


def cmd_export(args):
    """Export manga list and download state to JSON."""
    manga_list = config.get("manga", [])
    manga_state = state.get("manga", {})

    export_data = {
        "version": EXPORT_VERSION,
        "exported_at": datetime.now().isoformat(),
        "manga": manga_list,
        "state": manga_state,
    }

    output_file = args.file or "memanga_export.json"
    output_path = Path(output_file)

    with open(output_path, "w") as f:
        json.dump(export_data, f, indent=2, default=str)

    console.print(f"[green]Exported {len(manga_list)} manga to [cyan]{_esc(output_path)}[/cyan][/green]")


def cmd_import(args):
    """Import manga list and download state from JSON."""
    import_path = Path(args.file)

    if not import_path.exists():
        return _error(f"[red]File not found:[/red] {_esc(import_path)}")

    with open(import_path, "r") as f:
        import_data = json.load(f)

    try:
        import_data = validate_backup(import_data)
    except BackupVersionError as exc:
        return _error(f"[red]Cannot import:[/red] {_esc(exc)}")

    if "manga" not in import_data:
        return _error("[red]Invalid export file (missing 'manga' key)[/red]")

    imported_manga = import_data["manga"]
    imported_state = import_data.get("state", {})

    if args.replace:
        # Full replace
        config.set("manga", imported_manga)
        config.save()
        state.set("manga", imported_state)
        console.print(f"[green]Replaced with {len(imported_manga)} manga from import[/green]")
    else:
        # Merge mode: skip duplicates, merge chapter lists
        existing_manga = config.get("manga", [])
        existing_titles = {
            m["title"].lower(): m["title"]
            for m in existing_manga
        }
        state_title_aliases = {}
        added = 0
        skipped = 0
        for m in imported_manga:
            title = m["title"]
            title_key = title.lower()
            existing_title = existing_titles.get(title_key)
            if existing_title is not None:
                if title != existing_title:
                    state_title_aliases[title] = existing_title
                skipped += 1
                continue
            existing_manga.append(m)
            existing_titles[title_key] = title
            added += 1

        config.set("manga", existing_manga)
        config.save()
        state.merge_missing_manga_state(
            imported_state,
            merge_existing_downloaded=True,
            title_aliases=state_title_aliases,
        )

        console.print(f"[green]Imported: {added} added, {skipped} skipped (duplicate)[/green]")


def _chapter_order(item):
    """Sort key for (chapter_number, info) pairs; non-numeric labels first."""
    number = item[0]
    return float(number) if number.replace('.', '', 1).isdigit() else 0


def _collect_retryable(title_filter=None):
    """Failed and accepted-partial records, optionally filtered by a
    case-insensitive title substring.

    Returns (all_failed, all_partials, retryable) where `retryable`
    merges both per manga; a failure record wins over a partial one for
    the same chapter.
    """
    all_failed = state.get_all_failed_chapters()
    all_partials = state.get_all_partial_chapters()

    # Filter by title if requested
    if title_filter:
        all_failed = {
            t: chapters for t, chapters in all_failed.items()
            if title_filter.lower() in t.lower()
        }
        all_partials = {
            t: chapters for t, chapters in all_partials.items()
            if title_filter.lower() in t.lower()
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


def cmd_failed(args):
    """List and manage chapters that failed or were accepted as partial."""
    all_failed, all_partials, retryable = _collect_retryable(args.title)

    if getattr(args, "json", False):
        # --retry/--clear are rejected with --json at parse time.
        _print_json(_failed_payload(retryable, args.title))
        return

    if not retryable:
        console.print("[dim]No failed or partial chapters recorded.[/dim]")
        return

    table = Table(
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

    if args.clear:
        for manga_title, chapters in all_failed.items():
            for chapter_num in list(chapters):
                state.clear_failed_chapter(manga_title, chapter_num)
        for manga_title, chapters in all_partials.items():
            for chapter_num in list(chapters):
                state.clear_partial_chapter(manga_title, chapter_num)
        console.print("[green]✅ Cleared all failure and partial records.[/green]")
        return

    if args.retry:
        manga_list = config.get("manga", [])
        manga_by_title = {m["title"]: m for m in manga_list}
        delivery_mode = config.delivery_mode
        download_dir = config.download_dir
        output_format = config.output_format
        email_cfg = config.get("email", {})
        post_processing = config.get("delivery.post_processing")
        retried = 0
        succeeded = 0

        for manga_title, chapters in retryable.items():
            manga = manga_by_title.get(manga_title)
            if not manga:
                err_console.print(f"  [yellow]⚠️  Manga not found in config: {_esc(manga_title)}[/yellow]")
                # Unretryable records still count as unrecovered (#239).
                retried += len(chapters)
                continue

            for chapter_num, info in sorted(chapters.items(), key=_chapter_order):
                sources = _get_sources_from_manga(manga)
                if not sources:
                    err_console.print(f"  [yellow]⚠️  No source to retry Chapter {_esc(chapter_num)} of {_esc(manga_title)}[/yellow]")
                    retried += 1
                    continue

                # Build a minimal Chapter object from primary source
                src = sources[0]
                try:
                    scraper = get_scraper(src["source"])
                    all_chapters = scraper.get_chapters(src["url"])
                    ch_obj = next((c for c in all_chapters if c.number == chapter_num), None)
                except Exception:
                    ch_obj = None

                if not ch_obj:
                    err_console.print(f"  [yellow]⚠️  Could not find Chapter {_esc(chapter_num)} of {_esc(manga_title)} on primary source[/yellow]")
                    # Try backup directly
                    ch_obj = _find_chapter_on_backup(manga, chapter_num)
                    if not ch_obj:
                        err_console.print(f"  [red]❌ Chapter {_esc(chapter_num)} not found on any source[/red]")
                        retried += 1
                        continue
                else:
                    ch_obj = ChapterWithSource(ch_obj, src["source"], src["url"], is_backup=False)

                console.print(f"  [dim]⬇️  Retrying {_esc(manga_title)} Chapter {_esc(chapter_num)}...[/dim]")
                retried += 1
                try:
                    file_path = download_chapter(manga, ch_obj, download_dir, output_format, post_processing=post_processing)
                    is_image_folder = file_path.is_dir()
                    if is_image_folder:
                        console.print(f"  [green]✅ Saved: {_esc(f'{file_path.parent.name}/{file_path.name}/')}[/green]")
                    else:
                        console.print(f"  [green]✅ Saved: {_esc(file_path.name)}[/green]")

                    if delivery_mode == "email" and email_cfg.get("kindle_email") and not is_image_folder:
                        try:
                            send_to_kindle(
                                pdf_path=file_path,
                                kindle_email=email_cfg["kindle_email"],
                                sender_email=email_cfg["sender_email"],
                                smtp_server=email_cfg.get("smtp_server", "smtp.gmail.com"),
                                smtp_port=email_cfg.get("smtp_port", 587),
                                app_password=get_app_password(config),
                            )
                            console.print(f"  [green]📬 Sent to Kindle![/green]")
                        except EmailError as email_e:
                            err_console.print(f"  [red]📧 Email failed: {_esc(email_e)}[/red]")

                    state.add_downloaded_chapter(manga_title, chapter_num)
                    state.clear_failed_chapter(manga_title, chapter_num)
                    state.clear_partial_chapter(manga_title, chapter_num)
                    succeeded += 1
                except DownloaderError as retry_e:
                    # Try backup if available
                    backup_ch = _find_chapter_on_backup(manga, chapter_num)
                    if backup_ch:
                        err_console.print(f"  [yellow]⚠️  Primary failed, trying backup ({_esc(backup_ch.source)})...[/yellow]")
                        try:
                            file_path = download_chapter(manga, backup_ch, download_dir, output_format, post_processing=post_processing)
                            state.add_downloaded_chapter(manga_title, chapter_num)
                            state.clear_failed_chapter(manga_title, chapter_num)
                            state.clear_partial_chapter(manga_title, chapter_num)
                            label = f"{file_path.parent.name}/{file_path.name}/" if file_path.is_dir() else file_path.name
                            console.print(f"  [green]✅ Saved from backup: {_esc(label)}[/green]")
                            succeeded += 1
                            continue
                        except DownloaderError:
                            pass
                    state.add_failed_chapter(manga_title, chapter_num, info.get("source", "?"), str(retry_e))
                    err_console.print(f"  [red]❌ Still failing: {_esc(retry_e)}[/red]")

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

    table = Table(title="🩺 MeManga Doctor", box=box.SIMPLE, show_header=False)
    table.add_column(width=2)
    table.add_column(style="cyan")
    table.add_column(no_wrap=False)
    for r in results:
        message = _esc(r.message)
        if r.status == doctor.SKIP:
            message = f"[dim]{message}[/dim]"
        table.add_row(_DOCTOR_ICONS[r.status], _esc(r.name), message)
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
                    retries=3,
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
            file_path = Prompt.ask("Export file", default="memanga_export.json")
            cmd_export(argparse.Namespace(file=file_path))
        elif choice == "i":
            file_path = Prompt.ask("Import file path")
            if file_path:
                replace = Confirm.ask("Replace all data? (No = merge)", default=False)
                cmd_import(argparse.Namespace(file=file_path, replace=replace))

        console.print()
        Prompt.ask("[dim]Press Enter to continue[/dim]")


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    # Issue #239: handled here, not under __main__, so `python -m memanga`
    # and the installed `memanga` script also exit 130 without a traceback.
    try:
        _main()
    except KeyboardInterrupt:
        _flush_state_on_interrupt()
        err_console.print("\n[dim]Interrupted.[/dim]")
        sys.exit(EXIT_INTERRUPTED)


def _flush_state_on_interrupt():
    """Persist state marked dirty before Ctrl-C (issue #234).

    `check` only saves at the end via update_last_check(), so chapters
    already recorded as downloaded would otherwise be lost. Best effort:
    a failed write must not replace the interrupt with a traceback.
    """
    if state is None:
        return
    try:
        state.flush()
    except Exception as e:
        err_console.print(f"[yellow]⚠️  Could not save state: {_esc(e)}[/yellow]")


def _main():
    _cli_only = bool(os.environ.get("MEMANGA_CLI_ONLY"))

    _epilog = """
Examples:
  memanga list                          # Show tracked manga
  memanga add -i                        # Add manga interactively
  memanga add -t "Solo Leveling" -u URL # Add manga directly
  memanga search "Blue Lock"            # Find a manga across sources
  memanga check                         # Check for new chapters
  memanga check --auto                  # Auto-download new chapters
  memanga doctor                        # Diagnose setup problems
  memanga cron install                  # Set up daily checks
  memanga config                        # Configure settings
  memanga --config-dir DIR status       # Use another config directory
"""
    if not _cli_only:
        _epilog += "  memanga --gui                         # Launch graphical interface\n"

    parser = argparse.ArgumentParser(
        description="📖 MeManga - Automatic manga downloader",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_epilog,
    )
    parser.add_argument(
        "--config-dir", metavar="DIR",
        help=f"Use DIR for config, state, logs and the cover cache (default: "
             f"${CONFIG_DIR_ENV}, else ~/.config/memanga). Goes before the "
             "command; created if missing.",
    )
    # In CLI-only Docker images (MEMANGA_CLI_ONLY=1) the GUI is not installed;
    # suppress the flag from help and reject it at runtime with a clear message.
    parser.add_argument(
        "--gui",
        action="store_true",
        help=argparse.SUPPRESS if _cli_only else "Launch the graphical user interface",
    )
    
    subparsers = parser.add_subparsers(dest="command", title="commands")
    
    # list
    p_list = subparsers.add_parser("list", aliases=["ls"], help="List tracked manga")
    p_list.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    p_list.set_defaults(func=cmd_list)
    
    # add
    p_add = subparsers.add_parser("add", help="Add a manga to track")
    p_add.add_argument("-t", "--title", help="Manga title")
    p_add.add_argument("-u", "--url", help="Primary source URL")
    p_add.add_argument("-b", "--backup", help="Backup source URL")
    p_add.add_argument("--fallback-days", type=_non_negative_int_arg, default=2,
                       help="Days to wait before using backup (0 or more; default: 2)")
    p_add.add_argument("-i", "--interactive", action="store_true", help="Interactive mode")
    p_add.add_argument("-f", "--force", "-y", "--yes", dest="force", action="store_true",
                       help="Add even if the source might be unsupported or a similar title is tracked")
    p_add.set_defaults(func=cmd_add)
    
    # set (change manga status)
    p_set = subparsers.add_parser("set", help="Set manga status (reading/on-hold/dropped/completed)")
    p_set.add_argument("target", help="Manga title, or #N for its number in 'memanga list'")
    p_set.add_argument("status", choices=VALID_STATUSES, help="New status")
    p_set.set_defaults(func=cmd_set_status)
    
    # remove
    p_remove = subparsers.add_parser("remove", aliases=["rm"], help="Remove a manga")
    p_remove.add_argument("target", help="Manga title, or #N for its number in 'memanga list'")
    p_remove.add_argument("-y", "--yes", action="store_true", help="Skip confirmation (keeps download history)")
    p_remove.add_argument("--purge", action="store_true", help="Also remove its download history")
    p_remove.set_defaults(func=cmd_remove)

    # update
    p_update = subparsers.add_parser("update", help="Update manga details (URL, backup, title)")
    p_update.add_argument("target", help="Manga title, or #N for its number in 'memanga list'")
    p_update.add_argument("-u", "--url", help="New primary source URL")
    p_update.add_argument("-b", "--backup", help="New backup source URL")
    p_update.add_argument("-t", "--title", help="Rename manga title")
    p_update.set_defaults(func=cmd_update)

    # check
    p_check = subparsers.add_parser("check", help="Check for new chapters")
    p_check.add_argument("-t", "--title", help="Check one manga only (title, or #N from 'memanga list')")
    p_check.add_argument("-f", "--from", dest="from_chapter", type=float, help="Start from chapter N (for fresh downloads)")
    p_check.add_argument("--all", action="store_true", help="Download all chapters from the beginning")
    p_check.add_argument("-a", "--auto", action="store_true", help="Auto-download without prompts")
    p_check.add_argument("-y", "--yes", action="store_true", help="Say yes to all prompts")
    p_check.add_argument("-q", "--quiet", action="store_true", help="Minimal output (for cron)")
    p_check.add_argument("-s", "--safe", action="store_true", help="Safe mode: restart browser every 3 chapters (for bulk downloads)")
    p_check.add_argument("-n", "--dry-run", action="store_true", help="List new chapters without downloading")
    p_check.add_argument("--force-suspicious", action="store_true", help="Accept a chapter batch even if it was flagged as suspicious")
    p_check.add_argument("--format", choices=["pdf", "epub", "cbz", "zip", "jpg", "png", "webp"], help="Output format (overrides config)")
    p_check.add_argument("--retries", type=int, default=3, metavar="N", help="Retry failed page downloads N times (default: 3, 0 to disable)")
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
    p_search.add_argument("--source", help="Search a single source only (e.g. mangadex.org)")
    p_search.add_argument("--limit", type=int, metavar="N", help="Cap results per source")
    p_search.add_argument("--add", type=int, metavar="N", help="Add result #N without prompting")
    p_search.add_argument("--status", choices=VALID_STATUSES, help="Status for the added manga (with --add or the prompt)")
    p_search.add_argument("--no-chips", action="store_true", help="Skip chapter-count probes (faster)")
    p_search.set_defaults(func=cmd_search)

    # export
    p_export = subparsers.add_parser("export", help="Export manga list and state to JSON")
    p_export.add_argument("file", nargs="?", default="memanga_export.json", help="Output file (default: memanga_export.json)")
    p_export.set_defaults(func=cmd_export)

    # import
    p_import = subparsers.add_parser("import", help="Import manga list and state from JSON")
    p_import.add_argument("file", help="JSON file to import")
    p_import.add_argument("--replace", action="store_true", help="Replace all data instead of merging")
    p_import.set_defaults(func=cmd_import)

    # failed
    p_failed = subparsers.add_parser("failed", help="List chapters with download failures")
    p_failed.add_argument("-t", "--title", help="Filter by manga title")
    p_failed.add_argument("--retry", action="store_true", help="Attempt to re-download all listed failed chapters")
    p_failed.add_argument("--clear", action="store_true", help="Clear failure records without retrying")
    p_failed.add_argument("--json", action="store_true", help="Machine-readable JSON output (listing only)")
    p_failed.set_defaults(func=cmd_failed)

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
    
    args = parser.parse_args()

    # Keep `failed --json` a pure listing contract instead of mixing
    # retry/clear progress output into machine-readable stdout.
    if args.command == "failed" and args.json and (args.retry or args.clear):
        p_failed.error("--json cannot be combined with --retry or --clear")

    # Issue #259: resolve the root once; the CLI context and the GUI
    # both use it. Usage errors exit 2, an unusable directory exits 1.
    if args.config_dir is not None and not args.config_dir.strip():
        parser.error("--config-dir needs a directory path")
    # Every command but doctor (which reports it) needs a writable root,
    # checked here so a save never fails halfway through a command.
    # The default root is kept as an explicit path too, so a scheduled
    # check pins it and a later $MEMANGA_CONFIG_DIR cannot redirect it.
    try:
        config_dir = resolve_config_dir(args.config_dir) or default_config_dir()
        if args.command != "doctor":
            ensure_config_dir(config_dir)
    except ConfigDirError as e:
        sys.stderr.write(f"error: {e}\n")
        sys.exit(EXIT_ERROR)
    try:
        use_context(build_context(config_dir))
    except OSError as e:
        sys.stderr.write(
            f"error: cannot use config directory {config_dir}: {e.strerror or e}\n"
        )
        sys.exit(EXIT_ERROR)

    # Only doctor may run on fallback defaults; anything else could act
    # on an empty manga list or overwrite the user's broken config.
    if config.load_error and args.command != "doctor":
        sys.stderr.write(
            f"error: cannot load config file {config.config_path}: {config.load_error}\n"
            "Fix or move the file, then retry. Run `memanga doctor` for details.\n"
        )
        sys.exit(1)

    if args.gui:
        if _cli_only:
            sys.stderr.write(
                "error: --gui is not available in this image (CLI-only Docker build)\n"
            )
            sys.exit(1)
        from .gui import launch_gui
        launch_gui(config_dir)
        return

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
