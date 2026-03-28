"""
Configuration management for MeManga
"""

import os
import yaml
from pathlib import Path


class Config:
    """Manages configuration file."""
    
    def __init__(self, config_dir=None):
        if config_dir:
            self.config_dir = Path(config_dir)
        else:
            self.config_dir = Path.home() / ".config" / "memanga"
        
        self.config_path = self.config_dir / "config.yaml"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._data = self._load()
    
    def _load(self):
        """Load config from file."""
        if self.config_path.exists():
            with open(self.config_path, "r") as f:
                data = yaml.safe_load(f) or {}
            # Merge with defaults to ensure new fields exist
            defaults = self._default_config()
            for key, value in defaults.items():
                if key not in data:
                    data[key] = value
                elif isinstance(value, dict) and isinstance(data[key], dict):
                    for k, v in value.items():
                        if k not in data[key]:
                            data[key][k] = v
                elif isinstance(value, dict) and not isinstance(data[key], dict):
                    # User config has wrong type — replace with default
                    data[key] = value
            return data
        return self._default_config()
    
    def _default_config(self):
        """Return default configuration."""
        return {
            "manga": [],
            "delivery": {
                "mode": "local",  # "local" or "email"
                "download_dir": str(Path.home() / "Downloads" / "MeManga"),
                "delete_after_send": False,  # Delete file after sending to Kindle
                "output_format": "pdf",  # "pdf", "epub", "cbz", "zip", "jpg", "png", or "webp"
                "naming_template": "{title} - Chapter {chapter}",  # File naming pattern
            },
            "email": {
                "kindle_email": "",
                "sender_email": "",
                "smtp_server": "smtp.gmail.com",
                "smtp_port": 587,
                "app_password": "",
            },
            "cron": {
                "enabled": False,
                "time": "06:00",
            },
            "gui": {
                "sort_by": "title",
                "auto_check": True,
                "auto_check_interval": 3600,
            },
        }
    
    def get(self, key, default=None):
        """Get a config value."""
        keys = key.split(".")
        value = self._data
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
            if value is None:
                return default
        return value
    
    def set(self, key, value):
        """Set a config value."""
        keys = key.split(".")
        data = self._data
        for k in keys[:-1]:
            if k not in data or not isinstance(data[k], dict):
                data[k] = {}
            data = data[k]
        data[keys[-1]] = value
    
    def save(self):
        """Save config to file."""
        with open(self.config_path, "w") as f:
            yaml.dump(self._data, f, default_flow_style=False, allow_unicode=True)
    
    def reset(self):
        """Reset to default config."""
        self._data = self._default_config()
        self.save()
    
    # Convenience properties
    @property
    def delivery_mode(self):
        return self.get("delivery.mode", "local")
    
    @property
    def download_dir(self):
        return Path(self.get("delivery.download_dir", str(self.config_dir / "downloads"))).expanduser()
    
    @property
    def email_enabled(self):
        return self.delivery_mode == "email" and self.get("email.kindle_email")
    
    @property
    def output_format(self):
        return self.get("delivery.output_format", "pdf")


_KEYRING_SERVICE = "memanga"
_KEYRING_KEY = "app_password"


def get_app_password(cfg: Config) -> str:
    """Get app password from keyring, falling back to config file."""
    try:
        import keyring
        password = keyring.get_password(_KEYRING_SERVICE, _KEYRING_KEY)
        if password:
            return password
    except Exception:
        pass
    return cfg.get("email.app_password", "")


def set_app_password(cfg: Config, password: str):
    """Store app password in keyring, falling back to config file. Saves config."""
    try:
        import keyring
        keyring.set_password(_KEYRING_SERVICE, _KEYRING_KEY, password)
        # Clear plaintext from config if keyring succeeded
        if cfg.get("email.app_password"):
            cfg.set("email.app_password", "")
            cfg.save()
        return
    except Exception:
        pass
    # Fallback: store in config
    cfg.set("email.app_password", password)
    cfg.save()
