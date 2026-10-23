"""Kindle email delivery settings, read from config in one place (issue #296).

The desktop app's Downloads, Detail and Reader pages, its download worker
and the CLI's ``check``, ``failed retry``, ``send --pending`` and
``config email`` all build an :class:`EmailSettings` here, so defaults,
the app password lookup and when delivery applies cannot drift between
them.
"""

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from .config import Config, get_app_password

DEFAULT_SMTP_SERVER = "smtp.gmail.com"
DEFAULT_SMTP_PORT = 587


@dataclass(frozen=True, kw_only=True)
class EmailSettings:
    """Where and how saved chapters are emailed to a Kindle.

    Values are kept as configured; the emailer checks them when it sends,
    so a bad setting fails that chapter's delivery (and is recorded as
    undelivered) rather than the whole run. ``smtp_timeout`` None means
    the emailer's default. ``app_password`` None means it was not looked
    up here: the caller supplies it when sending.
    """

    kindle_email: str = ""
    sender_email: str = ""
    smtp_server: str = DEFAULT_SMTP_SERVER
    smtp_port: int = DEFAULT_SMTP_PORT
    smtp_timeout: Optional[float] = None
    # Never part of the repr, so it cannot reach a log line that way.
    app_password: Optional[str] = field(default=None, repr=False)

    @classmethod
    def from_config(cls, cfg: Config, *,
                    resolve_password: bool = True) -> "EmailSettings":
        """The ``email.*`` settings of ``cfg``. With ``resolve_password``,
        the app password is looked up now (environment, keyring, then
        config; see :func:`memanga.config.get_app_password`)."""
        return cls(
            kindle_email=cfg.get("email.kindle_email", ""),
            sender_email=cfg.get("email.sender_email", ""),
            smtp_server=cfg.get("email.smtp_server", DEFAULT_SMTP_SERVER),
            smtp_port=cfg.get("email.smtp_port", DEFAULT_SMTP_PORT),
            smtp_timeout=cfg.get("email.smtp_timeout"),
            app_password=get_app_password(cfg) if resolve_password else None,
        )


def manga_sends_to_kindle(manga: Mapping[str, Any]) -> bool:
    """Whether ``manga`` takes part in Kindle delivery (#341). A missing
    ``send_to_kindle`` (older entries) means it does."""
    return bool(manga.get("send_to_kindle", True))


def kindle_delivery_settings(
    cfg: Config, manga: Optional[Mapping[str, Any]] = None,
) -> Optional[EmailSettings]:
    """The settings to send chapters with, or None when they are not
    sent: the delivery mode is not email, no Kindle address is set, or
    ``manga`` (when given) opted out. The app password is looked up now,
    so a queued chapter is sent with the password of the moment it was
    queued."""
    if not cfg.email_enabled:
        return None
    if manga is not None and not manga_sends_to_kindle(manga):
        return None
    return EmailSettings.from_config(cfg)
