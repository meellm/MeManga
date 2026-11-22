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
# Issue #366: see SMTP_TLS_MODES in emailer.py.
DEFAULT_SMTP_TLS = "auto"

# Issue #345: which manga email delivery applies to. "all": every manga
# that has not turned Kindle off; "selected": only manga turned on.
KINDLE_SCOPES = ("all", "selected")


@dataclass(frozen=True, kw_only=True)
class EmailSettings:
    """Where and how saved chapters are emailed to a Kindle.

    Values are kept as configured; the emailer checks them when it sends,
    so a bad setting fails that chapter's delivery (and is recorded as
    undelivered) rather than the whole run. ``smtp_timeout`` and
    ``max_email_mb`` None mean the emailer's default. ``app_password``
    None means it was not looked up here: the caller supplies it when
    sending.
    """

    kindle_email: str = ""
    sender_email: str = ""
    smtp_server: str = DEFAULT_SMTP_SERVER
    smtp_port: int = DEFAULT_SMTP_PORT
    smtp_tls: str = DEFAULT_SMTP_TLS
    smtp_timeout: Optional[float] = None
    max_email_mb: Optional[float] = None
    kindle_scope: str = "all"
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
            smtp_tls=cfg.get("email.smtp_tls", DEFAULT_SMTP_TLS),
            smtp_timeout=cfg.get("email.smtp_timeout"),
            max_email_mb=cfg.get("email.max_email_mb"),
            kindle_scope=kindle_scope(cfg),
            app_password=get_app_password(cfg) if resolve_password else None,
        )


def kindle_scope(cfg: Config) -> str:
    """The ``email.kindle_scope`` setting (#345). Unset means "all", how
    email delivery worked before the choice existed, so a library that
    already sends keeps sending; an invalid value means "selected"."""
    value = cfg.get("email.kindle_scope")
    if value is None:
        return "all"
    return value if value in KINDLE_SCOPES else "selected"


def proposed_kindle_scope(cfg: Config) -> str:
    """The scope to preselect when asking which manga to send (#345):
    the chosen one as delivery applies it (an invalid value is
    "selected"), else "all" when email delivery is already on (what
    happens now), else "selected", so turning email delivery on never
    sends a whole library by default."""
    if cfg.get("email.kindle_scope") is not None:
        return kindle_scope(cfg)
    return "all" if cfg.delivery_mode == "email" else "selected"


def manga_sends_to_kindle(manga: Mapping[str, Any],
                          scope: str = "all") -> bool:
    """Whether ``manga`` takes part in Kindle delivery (#341). Its own
    ``send_to_kindle`` wins; without one (older entries, or added
    without a choice) it follows ``scope`` (#345)."""
    if "send_to_kindle" not in manga:
        return scope == "all"
    return bool(manga["send_to_kindle"])


def kindle_delivery_settings(
    cfg: Config, manga: Optional[Mapping[str, Any]] = None,
) -> Optional[EmailSettings]:
    """The settings to send chapters with, or None when they are not
    sent: the delivery mode is not email, no Kindle address is set, or
    ``manga`` (when given) does not take part in it. The app password is
    looked up now, so a queued chapter is sent with the password of the
    moment it was queued."""
    if not cfg.email_enabled:
        return None
    if manga is not None and not manga_sends_to_kindle(manga,
                                                       kindle_scope(cfg)):
        return None
    return EmailSettings.from_config(cfg)
