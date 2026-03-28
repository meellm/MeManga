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
from datetime import datetime
from typing import Dict, Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich import box

from .config import Config, get_app_password, set_app_password
from .state import State
from .downloader import check_for_updates, download_chapter, get_supported_sources, DownloaderError, ChapterWithSource, restart_browsers
from .scrapers import get_scraper
from .emailer import send_to_kindle, EmailError

console = Console()
config = Config()
state = State()

# ============================================================================
# CLI Commands
# ============================================================================

VALID_STATUSES = ["reading", "on-hold", "dropped", "completed"]


def _get_status_display(manga: Dict[str, Any]) -> str:
    """Get formatted status display."""
    status = manga.get("status", "reading")
    colors = {
        "reading": "green",
        "on-hold": "yellow",
        "dropped": "red",
        "completed": "cyan",
    }
    return f"[{colors.get(status, 'white')}]{status}[/]"


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


def cmd_list(args):
    """List all tracked manga."""
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
            title,
            _get_status_display(manga),
            _get_sources_display(manga),
            str(last_ch) if last_ch else "—",
            str(len(downloaded)) if downloaded else "0",
        )
    
    console.print(table)


def cmd_add(args):
    """Add a manga to track."""
    from urllib.parse import urlparse
    
    backup_url = None
    fallback_days = 2
    
    if args.interactive:
        # Interactive mode
        console.print("\n[bold green]➕ Add New Manga[/bold green]\n")
        
        sources = get_supported_sources()
        console.print(f"[dim]Supported sources:[/dim] {', '.join(sources)}\n")
        
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
                fallback_days = int(Prompt.ask("⏱️  Fallback delay (days)", default="2"))
    else:
        title = args.title
        url = args.url
        backup_url = getattr(args, 'backup', None)
        fallback_days = getattr(args, 'fallback_days', None)
        if fallback_days is None:
            fallback_days = 2
        
        if not title or not url:
            console.print("[red]Error:[/red] --title and --url required (or use --interactive)")
            return 1
    
    # Extract source from URL
    parsed = urlparse(url)
    source = parsed.netloc.lower()
    if source.startswith("www."):
        source = source[4:]

    # Check if source is supported (exact or subdomain match)
    supported = get_supported_sources()
    source_ok = any(source == s or source.endswith("." + s) for s in supported)
    if not source_ok:
        console.print(f"[yellow]⚠️  Warning:[/yellow] '{source}' might not be supported.")
        console.print(f"[dim]Supported: {', '.join(supported)}[/dim]")
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
            console.print(f"[yellow]⚠️  '{title}' already exists![/yellow]")
            return

    # Check for similar titles (substring match)
    new_lower = title.lower()
    for m in manga_list:
        existing_lower = m["title"].lower()
        if (new_lower in existing_lower or existing_lower in new_lower) and new_lower != existing_lower:
            console.print(f"[yellow]⚠️  Similar manga already tracked: [cyan]{m['title']}[/cyan][/yellow]")
            if not Confirm.ask("Add anyway?", default=False):
                return
            break
    
    manga_list.append(manga_entry)
    config.set("manga", manga_list)
    config.save()
    
    if backup_url:
        backup_source = urlparse(backup_url).netloc.replace("www.", "")
        console.print(f"\n[green]✅ Added:[/green] {title}")
        console.print(f"   [dim]Primary:[/dim] {source}")
        console.print(f"   [dim]Backup:[/dim] {backup_source} (after {fallback_days} days)")
    else:
        console.print(f"\n[green]✅ Added:[/green] {title} ({source})")


def _find_manga(target: str, manga_list: list):
    """Find manga by number or partial title match. Returns (manga, index) or (None, None)."""
    try:
        idx = int(target) - 1
        if 0 <= idx < len(manga_list):
            return manga_list[idx], idx
    except ValueError:
        for i, m in enumerate(manga_list):
            if target.lower() in m["title"].lower():
                return m, i
    return None, None


def cmd_remove(args):
    """Remove a manga from tracking."""
    manga_list = config.get("manga", [])

    if not manga_list:
        console.print("[yellow]No manga to remove.[/yellow]")
        return

    found, found_idx = _find_manga(args.target, manga_list)

    if not found:
        console.print(f"[red]Not found:[/red] {args.target}")
        console.print("[dim]Use 'memanga list' to see tracked manga.[/dim]")
        return

    if args.yes or Confirm.ask(f"Remove [cyan]{found['title']}[/cyan]?"):
        manga_list.pop(found_idx)
        config.set("manga", manga_list)
        config.save()
        
        # Also remove from state?
        if args.yes or Confirm.ask("Also remove download history?", default=False):
            manga_state = state.get("manga", {})
            if found["title"] in manga_state:
                del manga_state[found["title"]]
                state.set("manga", manga_state)
        
        console.print(f"[red]🗑️  Removed:[/red] {found['title']}")


def cmd_set_status(args):
    """Set manga status (reading, on-hold, dropped, completed)."""
    manga_list = config.get("manga", [])
    
    if not manga_list:
        console.print("[yellow]No manga tracked.[/yellow]")
        return
    
    new_status = args.status.lower()

    if new_status not in VALID_STATUSES:
        console.print(f"[red]Invalid status:[/red] {new_status}")
        console.print(f"[dim]Valid: {', '.join(VALID_STATUSES)}[/dim]")
        return

    found, found_idx = _find_manga(args.target, manga_list)

    if not found:
        console.print(f"[red]Not found:[/red] {args.target}")
        return

    old_status = found.get("status", "reading")
    manga_list[found_idx]["status"] = new_status
    config.set("manga", manga_list)
    config.save()
    
    # Status colors
    colors = {"reading": "green", "on-hold": "yellow", "dropped": "red", "completed": "cyan"}
    old_color = colors.get(old_status, "white")
    new_color = colors.get(new_status, "white")
    
    console.print(f"[cyan]{found['title']}[/cyan]: [{old_color}]{old_status}[/] → [{new_color}]{new_status}[/]")


def cmd_update(args):
    """Update manga details (URL, backup, title)."""
    from urllib.parse import urlparse

    manga_list = config.get("manga", [])

    if not manga_list:
        console.print("[yellow]No manga tracked.[/yellow]")
        return

    found, found_idx = _find_manga(args.target, manga_list)

    if not found:
        console.print(f"[red]Not found:[/red] {args.target}")
        console.print("[dim]Use 'memanga list' to see tracked manga.[/dim]")
        return

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
        changes.append(f"Title → {args.title}")

    if not changes:
        console.print("[yellow]No changes specified. Use --url, --backup, or --title.[/yellow]")
        return

    manga_list[found_idx] = found
    config.set("manga", manga_list)
    config.save()

    console.print(f"[green]Updated [cyan]{old_title}[/cyan]:[/green]")
    for c in changes:
        console.print(f"  {c}")


def cmd_check(args):
    """Check for new chapters and download."""
    manga_list = config.get("manga", [])
    
    if not manga_list:
        console.print("[yellow]No manga tracked. Use 'memanga add' first![/yellow]")
        return
    
    # Filter to specific manga if provided
    if args.title:
        manga_list = [m for m in manga_list if args.title.lower() in m["title"].lower()]
        if not manga_list:
            console.print(f"[red]Not found:[/red] {args.title}")
            return
    
    from_chapter = getattr(args, 'from_chapter', None)
    if getattr(args, 'all', False):
        from_chapter = 0
    dry_run = getattr(args, 'dry_run', False)

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
    
    delivery_mode = config.delivery_mode
    download_dir = config.download_dir
    output_format = getattr(args, 'format', None) or config.output_format
    email_cfg = config.get("email", {})
    
    for manga in manga_list:
        title = manga["title"]
        status = manga.get("status", "reading")
        
        # Skip non-reading manga unless explicitly specified by title
        if status != "reading" and not args.title:
            console.print(f"[dim]Skipping:[/dim] [cyan]{title}[/cyan] [{status}]")
            continue
        
        console.print(f"[dim]Checking:[/dim] [cyan]{title}[/cyan]...")
        
        try:
            new_chapters = check_for_updates(manga, state, from_chapter=from_chapter)
            
            if not new_chapters:
                console.print("  [dim]└─ No new chapters[/dim]")
                continue
            
            console.print(f"  [green]└─ {len(new_chapters)} new chapter(s)![/green]")
            total_new += len(new_chapters)
            
            for ch in new_chapters:
                ch_label = f"Chapter {ch.number}"
                if ch.title:
                    ch_label += f": {ch.title}"

                # Dry run: just list chapters
                if dry_run:
                    source_info = ""
                    if isinstance(ch, ChapterWithSource) and ch.is_backup:
                        source_info = f" [yellow](backup: {ch.source})[/yellow]"
                    console.print(f"     [dim][DRY RUN][/dim] {ch_label}{source_info}")
                    total_downloaded += 1
                    continue

                # Download automatically or prompt
                should_download = args.auto or args.yes
                if not should_download and not args.quiet:
                    should_download = Confirm.ask(f"     Download {ch_label}?", default=True)

                if not should_download:
                    continue

                try:
                    # Show source info if from backup
                    source_info = ""
                    if isinstance(ch, ChapterWithSource) and ch.is_backup:
                        source_info = f" [yellow](from backup: {ch.source})[/yellow]"
                    
                    console.print(f"     [dim]⬇️  Downloading {ch_label}...{source_info}[/dim]")
                    file_path = download_chapter(manga, ch, download_dir, output_format)
                    is_image_folder = file_path.is_dir()

                    if is_image_folder:
                        console.print(f"     [green]✅ Saved: {file_path.parent.name}/{file_path.name}/[/green]")
                    else:
                        console.print(f"     [green]✅ Saved: {file_path.name}[/green]")

                    # Email if configured (skip for image folders)
                    if delivery_mode == "email" and email_cfg.get("kindle_email"):
                        if is_image_folder:
                            console.print(f"     [dim]📧 Skipped email (image folders cannot be emailed)[/dim]")
                        else:
                            console.print(f"     [dim]📧 Sending to Kindle...[/dim]")
                            try:
                                send_to_kindle(
                                    pdf_path=file_path,
                                    kindle_email=email_cfg["kindle_email"],
                                    sender_email=email_cfg["sender_email"],
                                    smtp_server=email_cfg.get("smtp_server", "smtp.gmail.com"),
                                    smtp_port=email_cfg.get("smtp_port", 587),
                                    app_password=get_app_password(config),
                                )
                                console.print(f"     [green]📬 Sent to Kindle![/green]")

                                # Delete after send if configured
                                if config.get("delivery.delete_after_send", False):
                                    file_path.unlink()
                                    console.print(f"     [dim]🗑️  Deleted local copy[/dim]")

                            except EmailError as e:
                                console.print(f"     [red]📧 Email failed: {e}[/red]")
                    
                    # Update state
                    state.add_downloaded_chapter(title, ch.number)
                    # Clear pending backup if this was from backup (or if primary caught up)
                    state.clear_pending_backup(title, ch.number)
                    total_downloaded += 1
                    
                    # Safe mode: restart browser every 3 chapters to free memory
                    safe_mode = getattr(args, 'safe', False)
                    if safe_mode and total_downloaded % 3 == 0:
                        restart_browsers()
                    
                except DownloaderError as e:
                    console.print(f"     [red]❌ Failed: {e}[/red]")
                    
        except DownloaderError as e:
            console.print(f"  [red]└─ Error: {e}[/red]")
        except Exception as e:
            console.print(f"  [red]└─ Unexpected error: {e}[/red]")
    
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
            console.print(f"[dim]📁 Downloads: {download_dir}[/dim]")


def cmd_status(args):
    """Show current status and configuration."""
    console.print(Panel("[bold]📊 MeManga Status[/bold]", border_style="blue"))
    console.print()
    
    # Configuration
    table = Table(title="Configuration", box=box.SIMPLE, show_header=False)
    table.add_column(style="dim", width=18)
    table.add_column(style="white")
    
    manga_list = config.get("manga", [])
    delivery_mode = config.delivery_mode
    
    table.add_row("Manga tracked", f"[cyan]{len(manga_list)}[/cyan]")
    table.add_row("Output format", f"[cyan]{config.output_format}[/cyan]")
    table.add_row("Delivery mode", f"[yellow]{delivery_mode}[/yellow]")
    
    if delivery_mode == "local":
        table.add_row("Download dir", str(config.download_dir))
    else:
        table.add_row("Kindle email", config.get("email.kindle_email") or "[red]not set[/red]")
        table.add_row("Sender email", config.get("email.sender_email") or "[red]not set[/red]")
    
    cron_status = "enabled" if config.get("cron.enabled") else "disabled"
    cron_time = config.get("cron.time", "06:00")
    table.add_row("Cron", f"[{'green' if cron_status == 'enabled' else 'dim'}]{cron_status}[/] ({cron_time})")
    
    console.print(table)
    
    # Paths
    console.print()
    console.print(f"[dim]Config:[/dim] {config.config_path}")
    console.print(f"[dim]State:[/dim]  {state.state_path}")
    
    # Last check
    last_check = state.get("last_check")
    if last_check:
        console.print(f"[dim]Last check:[/dim] {last_check}")


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
        console.print(yaml.dump(display, default_flow_style=False))
        return
    
    console.print(Panel("[bold]⚙️  Configure MeManga[/bold]", border_style="yellow"))
    console.print()
    
    # Delivery mode
    current_mode = config.delivery_mode
    console.print(f"[bold]Delivery Mode[/bold] (current: [cyan]{current_mode}[/cyan])")
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
    console.print(f"\n[bold]Output Format[/bold] (current: [cyan]{current_format}[/cyan])")
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

    config.save()
    console.print("\n[green]✅ Configuration saved![/green]")


def cmd_cron(args):
    """Manage scheduled task for automatic checking."""
    if platform.system() == "Windows":
        _cmd_cron_windows(args)
    else:
        _cmd_cron_unix(args)


def _cmd_cron_unix(args):
    """Manage cron job (macOS/Linux)."""
    import sys
    project_dir = Path(__file__).resolve().parent.parent
    python_path = project_dir / "venv" / "bin" / "python3"
    if not python_path.exists():
        python_path = Path(sys.executable)

    if args.action == "status":
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
        )

        if "memanga" in result.stdout.lower():
            console.print("[green]✅ Cron job is installed[/green]")
            for line in result.stdout.split("\n"):
                if "memanga" in line.lower():
                    console.print(f"[dim]{line}[/dim]")
        else:
            console.print("[yellow]⚠️  No cron job found[/yellow]")
            console.print("[dim]Use 'memanga cron install' to set up automatic checking.[/dim]")
        return

    elif args.action == "install":
        time_str = args.time or config.get("cron.time", "06:00")

        if not args.time:
            time_str = Prompt.ask("Check time (HH:MM)", default=time_str)

        try:
            hour, minute = time_str.split(":")
            hour, minute = int(hour), int(minute)
        except ValueError:
            console.print("[red]Invalid time format. Use HH:MM[/red]")
            return 1

        cron_cmd = f"cd {project_dir} && {python_path} -m memanga check --auto --quiet"
        cron_line = f"{minute} {hour} * * * {cron_cmd} >> {project_dir}/memanga.log 2>&1"

        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        existing = result.stdout if result.returncode == 0 else ""

        lines = [l for l in existing.split("\n") if l and "memanga" not in l.lower()]
        lines.append(cron_line)

        new_crontab = "\n".join(lines) + "\n"
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
            console.print(f"[dim]{cron_line}[/dim]")
        else:
            console.print("[red]Failed to install cron job[/red]")
            return 1

    elif args.action == "remove":
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        if result.returncode != 0:
            console.print("[yellow]No crontab found[/yellow]")
            return

        lines = [l for l in result.stdout.split("\n") if l and "memanga" not in l.lower()]

        if len(lines) == len(result.stdout.strip().split("\n")):
            console.print("[yellow]No MeManga cron job found[/yellow]")
            return

        new_crontab = "\n".join(lines) + "\n" if lines else ""

        if not lines:
            subprocess.run(["crontab", "-r"], capture_output=True)
        else:
            process = subprocess.Popen(["crontab", "-"], stdin=subprocess.PIPE, text=True)
            process.communicate(input=new_crontab)

        config.set("cron.enabled", False)
        config.save()

        console.print("[green]✅ Cron job removed[/green]")


def _cmd_cron_windows(args):
    """Manage Windows Task Scheduler task."""
    task_name = "MeManga_AutoCheck"
    project_dir = Path(__file__).resolve().parent.parent
    python_path = project_dir / "venv" / "Scripts" / "python.exe"
    if not python_path.exists():
        python_path = sys.executable

    if args.action == "status":
        result = subprocess.run(
            ["schtasks", "/query", "/tn", task_name],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            console.print("[green]✅ Scheduled task is installed[/green]")
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    console.print(f"[dim]{line.strip()}[/dim]")
        else:
            console.print("[yellow]⚠️  No scheduled task found[/yellow]")
            console.print("[dim]Use 'memanga cron install' to set up automatic checking.[/dim]")

    elif args.action == "install":
        time_str = args.time or config.get("cron.time", "06:00")

        if not args.time:
            time_str = Prompt.ask("Check time (HH:MM)", default=time_str)

        try:
            hour, minute = time_str.split(":")
            int(hour), int(minute)
        except ValueError:
            console.print("[red]Invalid time format. Use HH:MM[/red]")
            return 1

        # Delete existing task if present
        subprocess.run(
            ["schtasks", "/delete", "/tn", task_name, "/f"],
            capture_output=True, text=True,
        )

        cmd = f'"{python_path}" -m memanga check --auto --quiet'
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
            console.print(f"[red]Failed to create scheduled task: {result.stderr.strip()}[/red]")
            return 1

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
    table.add_row("[bold]asuracomic.net[/bold]", "Playwright", "Manhwa / Webtoons")
    table.add_row("[bold]mangakatana.com[/bold]", "Playwright", "General manga library")
    table.add_row("[bold]mangadex.org[/bold]", "API", "Fan translations (skip Shueisha)")
    
    console.print(table)
    console.print()
    console.print(f"[dim]Total: {len(sources)} sources • All tested and working![/dim]")


def cmd_export(args):
    """Export manga list and download state to JSON."""
    manga_list = config.get("manga", [])
    manga_state = state.get("manga", {})

    export_data = {
        "version": 1,
        "exported_at": datetime.now().isoformat(),
        "manga": manga_list,
        "state": manga_state,
    }

    output_file = args.file or "memanga_export.json"
    output_path = Path(output_file)

    with open(output_path, "w") as f:
        json.dump(export_data, f, indent=2, default=str)

    console.print(f"[green]Exported {len(manga_list)} manga to [cyan]{output_path}[/cyan][/green]")


def cmd_import(args):
    """Import manga list and download state from JSON."""
    import_path = Path(args.file)

    if not import_path.exists():
        console.print(f"[red]File not found:[/red] {import_path}")
        return 1

    with open(import_path, "r") as f:
        import_data = json.load(f)

    if "manga" not in import_data:
        console.print("[red]Invalid export file (missing 'manga' key)[/red]")
        return 1

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
        existing_titles = {m["title"].lower() for m in existing_manga}
        existing_state = state.get("manga", {})

        added = 0
        skipped = 0
        for m in imported_manga:
            if m["title"].lower() in existing_titles:
                skipped += 1
                continue
            existing_manga.append(m)
            existing_titles.add(m["title"].lower())
            added += 1

        # Merge state (downloaded chapter lists)
        for title, s in imported_state.items():
            if title in existing_state:
                # Merge downloaded lists
                existing_downloaded = set(existing_state[title].get("downloaded", []))
                imported_downloaded = set(s.get("downloaded", []))
                def _sort_key(x):
                    try:
                        return float(x)
                    except (ValueError, TypeError):
                        return 0.0
                merged = sorted(
                    existing_downloaded | imported_downloaded,
                    key=_sort_key,
                )
                existing_state[title]["downloaded"] = merged
            else:
                existing_state[title] = s

        config.set("manga", existing_manga)
        config.save()
        state.set("manga", existing_state)

        console.print(f"[green]Imported: {added} added, {skipped} skipped (duplicate)[/green]")


def cmd_tui(args):
    """Run interactive TUI."""
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
            ("5", "⚙️  Configure", "Change settings"),
            ("6", "⏰ Cron", "Manage auto-check schedule"),
            ("7", "📊 Status", "View status & config"),
            ("8", "✏️  Update Manga", "Change URL, backup, or title"),
            ("9", "📤 Export", "Export manga list to JSON"),
            ("0", "📥 Import", "Import manga list from JSON"),
            ("q", "🚪 Quit", "Exit"),
        ]
        
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(style="bold cyan", width=3)
        table.add_column(style="bold white", width=18)
        table.add_column(style="dim")
        
        for key, title, desc in menu_items:
            table.add_row(f"[{key}]", title, desc)
        
        console.print(table)
        console.print()
        
        choice = Prompt.ask("Select", choices=["1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "q"], default="4")
        
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
            target = Prompt.ask("\nEnter # or title to remove (or 'b' to go back)")
            if target != 'b':
                cmd_remove(argparse.Namespace(target=target, yes=False))
        elif choice == "4":
            cmd_list(argparse.Namespace())
            console.print()
            # Which manga?
            target = Prompt.ask("Check which manga? ([cyan]a[/cyan]=all, or enter # / title)", default="a")
            title = None
            if target.lower() != "a":
                manga_list_ref = config.get("manga", [])
                found, _ = _find_manga(target, manga_list_ref)
                if not found:
                    console.print(f"[red]Not found:[/red] {target}")
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
                ))
        elif choice == "5":
            cmd_config(argparse.Namespace(show=False))
        elif choice == "6":
            console.print("[1] Status  [2] Install  [3] Remove")
            cron_choice = Prompt.ask("Select", choices=["1", "2", "3"], default="1")
            action = {"1": "status", "2": "install", "3": "remove"}[cron_choice]
            cmd_cron(argparse.Namespace(action=action, time=None))
        elif choice == "7":
            cmd_status(argparse.Namespace())
        elif choice == "8":
            cmd_list(argparse.Namespace())
            target = Prompt.ask("\nEnter # or title to update (or 'b' to go back)")
            if target != 'b':
                url = Prompt.ask("New primary URL (leave blank to skip)", default="") or None
                backup = Prompt.ask("New backup URL (leave blank to skip)", default="") or None
                new_title = Prompt.ask("New title (leave blank to skip)", default="") or None
                cmd_update(argparse.Namespace(target=target, url=url, backup=backup, title=new_title))
        elif choice == "9":
            file_path = Prompt.ask("Export file", default="memanga_export.json")
            cmd_export(argparse.Namespace(file=file_path))
        elif choice == "0":
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
    parser = argparse.ArgumentParser(
        description="📖 MeManga - Automatic manga downloader",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  memanga list                          # Show tracked manga
  memanga add -i                        # Add manga interactively
  memanga add -t "Solo Leveling" -u URL # Add manga directly
  memanga check                         # Check for new chapters
  memanga check --auto                  # Auto-download new chapters
  memanga cron install                  # Set up daily checks
  memanga config                        # Configure settings
        """,
    )
    
    subparsers = parser.add_subparsers(dest="command", title="commands")
    
    # list
    p_list = subparsers.add_parser("list", aliases=["ls"], help="List tracked manga")
    p_list.set_defaults(func=cmd_list)
    
    # add
    p_add = subparsers.add_parser("add", help="Add a manga to track")
    p_add.add_argument("-t", "--title", help="Manga title")
    p_add.add_argument("-u", "--url", help="Primary source URL")
    p_add.add_argument("-b", "--backup", help="Backup source URL")
    p_add.add_argument("--fallback-days", type=int, default=2, help="Days to wait before using backup (default: 2)")
    p_add.add_argument("-i", "--interactive", action="store_true", help="Interactive mode")
    p_add.set_defaults(func=cmd_add)
    
    # set (change manga status)
    p_set = subparsers.add_parser("set", help="Set manga status (reading/on-hold/dropped/completed)")
    p_set.add_argument("target", help="Manga # or title")
    p_set.add_argument("status", choices=VALID_STATUSES, help="New status")
    p_set.set_defaults(func=cmd_set_status)
    
    # remove
    p_remove = subparsers.add_parser("remove", aliases=["rm"], help="Remove a manga")
    p_remove.add_argument("target", help="Manga # or title")
    p_remove.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")
    p_remove.set_defaults(func=cmd_remove)

    # update
    p_update = subparsers.add_parser("update", help="Update manga details (URL, backup, title)")
    p_update.add_argument("target", help="Manga # or title")
    p_update.add_argument("-u", "--url", help="New primary source URL")
    p_update.add_argument("-b", "--backup", help="New backup source URL")
    p_update.add_argument("-t", "--title", help="Rename manga title")
    p_update.set_defaults(func=cmd_update)

    # check
    p_check = subparsers.add_parser("check", help="Check for new chapters")
    p_check.add_argument("-t", "--title", help="Check specific manga only")
    p_check.add_argument("-f", "--from", dest="from_chapter", type=float, help="Start from chapter N (for fresh downloads)")
    p_check.add_argument("--all", action="store_true", help="Download all chapters from the beginning")
    p_check.add_argument("-a", "--auto", action="store_true", help="Auto-download without prompts")
    p_check.add_argument("-y", "--yes", action="store_true", help="Say yes to all prompts")
    p_check.add_argument("-q", "--quiet", action="store_true", help="Minimal output (for cron)")
    p_check.add_argument("-s", "--safe", action="store_true", help="Safe mode: restart browser every 3 chapters (for bulk downloads)")
    p_check.add_argument("-n", "--dry-run", action="store_true", help="List new chapters without downloading")
    p_check.add_argument("--format", choices=["pdf", "epub", "cbz", "zip", "jpg", "png", "webp"], help="Output format (overrides config)")
    p_check.set_defaults(func=cmd_check)
    
    # status
    p_status = subparsers.add_parser("status", help="Show status and configuration")
    p_status.set_defaults(func=cmd_status)
    
    # config
    p_config = subparsers.add_parser("config", help="Configure settings")
    p_config.add_argument("--show", action="store_true", help="Show current config")
    p_config.set_defaults(func=cmd_config)
    
    # cron
    p_cron = subparsers.add_parser("cron", help="Manage cron job")
    p_cron.add_argument("action", choices=["status", "install", "remove"], help="Action")
    p_cron.add_argument("--time", help="Check time (HH:MM) for install")
    p_cron.set_defaults(func=cmd_cron)
    
    # sources
    p_sources = subparsers.add_parser("sources", help="List supported sources")
    p_sources.set_defaults(func=cmd_sources)

    # export
    p_export = subparsers.add_parser("export", help="Export manga list and state to JSON")
    p_export.add_argument("file", nargs="?", default="memanga_export.json", help="Output file (default: memanga_export.json)")
    p_export.set_defaults(func=cmd_export)

    # import
    p_import = subparsers.add_parser("import", help="Import manga list and state from JSON")
    p_import.add_argument("file", help="JSON file to import")
    p_import.add_argument("--replace", action="store_true", help="Replace all data instead of merging")
    p_import.set_defaults(func=cmd_import)

    # tui (default if no command)
    p_tui = subparsers.add_parser("tui", help="Interactive terminal UI")
    p_tui.set_defaults(func=cmd_tui)
    
    args = parser.parse_args()
    
    if args.command is None:
        # Default to TUI
        cmd_tui(args)
    elif hasattr(args, 'func'):
        result = args.func(args)
        if result:
            sys.exit(result)
    else:
        parser.print_help()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[dim]Interrupted.[/dim]")
        sys.exit(1)
