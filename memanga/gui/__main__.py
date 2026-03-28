#!/usr/bin/env python3
"""
Entry point for MeManga GUI (.exe / standalone).
Sets up SSL certificates and Playwright browser path for frozen builds.
"""

import os
import sys
from pathlib import Path

if getattr(sys, 'frozen', False):
    bundle_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(sys.executable)))

    # --- SSL certificates ---
    ca_bundle = os.path.join(bundle_dir, 'certifi', 'cacert.pem')
    if os.path.exists(ca_bundle):
        os.environ['SSL_CERT_FILE'] = ca_bundle
        os.environ['REQUESTS_CA_BUNDLE'] = ca_bundle
        print(f"[SSL] CA bundle: {ca_bundle}", flush=True)
    else:
        ca_bundle_alt = os.path.join(os.path.dirname(sys.executable), '_internal', 'certifi', 'cacert.pem')
        if os.path.exists(ca_bundle_alt):
            os.environ['SSL_CERT_FILE'] = ca_bundle_alt
            os.environ['REQUESTS_CA_BUNDLE'] = ca_bundle_alt
        else:
            try:
                import certifi
                os.environ['SSL_CERT_FILE'] = certifi.where()
                os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
            except Exception:
                print("[SSL] WARNING: No CA bundle found!", flush=True)

    # --- Playwright browsers ---
    # Playwright installs browsers to ~\AppData\Local\ms-playwright (Windows)
    # or ~/.cache/ms-playwright (Linux/Mac). Inside a PyInstaller bundle,
    # Playwright's bundled driver looks for browsers relative to itself
    # (.local-browsers/) which is wrong. Point it to the real install location.
    if os.name == 'nt':
        pw_browsers = Path.home() / "AppData" / "Local" / "ms-playwright"
    else:
        pw_browsers = Path.home() / ".cache" / "ms-playwright"

    if pw_browsers.exists():
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(pw_browsers)
        print(f"[Playwright] Browsers: {pw_browsers}", flush=True)
    else:
        print(f"[Playwright] WARNING: Browser dir not found at {pw_browsers}", flush=True)

    # Quick SSL test
    try:
        import urllib.request
        urllib.request.urlopen("https://httpbin.org/get", timeout=5)
        print("[SSL] HTTPS test passed", flush=True)
    except Exception as e:
        print(f"[SSL] HTTPS test FAILED: {e}", flush=True)
else:
    print("[Init] Running from source", flush=True)

from memanga.gui import launch_gui

if __name__ == "__main__":
    launch_gui()
