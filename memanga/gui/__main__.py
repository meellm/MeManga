#!/usr/bin/env python3
"""
Entry point for MeManga GUI (.exe / standalone).
Sets up SSL certificates for frozen builds before anything else.
"""

import os
import sys

# Fix SSL certificates for PyInstaller frozen builds.
if getattr(sys, 'frozen', False):
    bundle_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(sys.executable)))
    ca_bundle = os.path.join(bundle_dir, 'certifi', 'cacert.pem')

    if os.path.exists(ca_bundle):
        os.environ['SSL_CERT_FILE'] = ca_bundle
        os.environ['REQUESTS_CA_BUNDLE'] = ca_bundle
        print(f"[SSL] Using CA bundle: {ca_bundle}")
    else:
        # Try the _internal subdirectory (PyInstaller onedir on newer versions)
        ca_bundle_alt = os.path.join(os.path.dirname(sys.executable), '_internal', 'certifi', 'cacert.pem')
        if os.path.exists(ca_bundle_alt):
            os.environ['SSL_CERT_FILE'] = ca_bundle_alt
            os.environ['REQUESTS_CA_BUNDLE'] = ca_bundle_alt
            print(f"[SSL] Using CA bundle (alt): {ca_bundle_alt}")
        else:
            # Last fallback: try certifi package
            try:
                import certifi
                os.environ['SSL_CERT_FILE'] = certifi.where()
                os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
                print(f"[SSL] Using certifi.where(): {certifi.where()}")
            except Exception as e:
                print(f"[SSL] WARNING: No CA bundle found! HTTPS will fail.")
                print(f"[SSL]   Tried: {ca_bundle}")
                print(f"[SSL]   Tried: {ca_bundle_alt}")
                print(f"[SSL]   certifi import error: {e}")

    # Quick test: verify SSL actually works
    try:
        import urllib.request
        urllib.request.urlopen("https://httpbin.org/get", timeout=5)
        print("[SSL] HTTPS test passed")
    except Exception as e:
        print(f"[SSL] HTTPS test FAILED: {e}")
else:
    print("[SSL] Not frozen — using system certificates")

from memanga.gui import launch_gui

if __name__ == "__main__":
    launch_gui()
