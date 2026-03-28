#!/usr/bin/env python3
"""
Entry point for MeManga GUI (.exe / standalone).
Sets up SSL certificates for frozen builds before anything else.
"""

import os
import sys

# Fix SSL certificates for PyInstaller frozen builds.
# Without this, every HTTPS request fails with SSLCertVerificationError
# because PyInstaller doesn't bundle certifi's CA bundle by default.
if getattr(sys, 'frozen', False):
    import certifi
    ca_bundle = certifi.where()
    os.environ['SSL_CERT_FILE'] = ca_bundle
    os.environ['REQUESTS_CA_BUNDLE'] = ca_bundle

from memanga.gui import launch_gui

if __name__ == "__main__":
    launch_gui()
