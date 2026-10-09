FROM python:3.12-slim

LABEL org.opencontainers.image.title="MeManga" \
      org.opencontainers.image.description="Automatic manga downloader with Kindle support (CLI)" \
      org.opencontainers.image.source="https://github.com/meellm/MeManga" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HOME=/home/memanga \
    MEMANGA_CLI_ONLY=1

WORKDIR /app

# Install CLI-only dependencies and the Playwright Firefox + Chromium runtimes
# first so this expensive layer stays cached when only application source
# changes. Chromium is needed by MangaPark, whose Cloudflare check blocks
# Firefox.
# requirements-docker.txt mirrors requirements.txt but omits PySide6 and
# other GUI-only packages so the container stays lean and headless.
COPY requirements-docker.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements-docker.txt \
    && python -m playwright install --with-deps firefox chromium \
    && useradd --create-home --home-dir /home/memanga --shell /usr/sbin/nologin --uid 1000 memanga \
    && mkdir -p /home/memanga/.config/memanga /home/memanga/Downloads/MeManga \
    && chown -R memanga:memanga /home/memanga

# Install the package itself (deps already satisfied above).
# .dockerignore excludes memanga/gui so only the CLI source lands in the image.
# pyproject.toml declares a memanga-gui console script; remove it so the image
# exposes only the memanga CLI and does not leave a broken launcher in PATH.
# The trailing test assertion makes the build fail if the path ever changes.
# Issue #380: the image also installs MeManga's LICENSE and the third-party
# notices for the Python packages, Python runtime and Playwright browsers it
# contains under /usr/share/doc/memanga/. pip is listed explicitly: the image
# ships it (with its vendored libraries) but no requirement pulls it in.
# --require-browser fails the build unless the notices have complete
# Chromium and Firefox sections for the browsers installed above.
# Debian packages from the base image keep their own notices under
# /usr/share/doc/<package>/copyright.
COPY pyproject.toml README.md LICENSE ./
COPY packaging/third_party_notices.py ./packaging/
COPY packaging/licenses ./packaging/licenses
COPY memanga ./memanga
RUN python -m pip install --no-deps . \
    && rm -f /usr/local/bin/memanga-gui \
    && test ! -f /usr/local/bin/memanga-gui \
    && python packaging/third_party_notices.py generate \
        --requirements requirements-docker.txt \
        --package pip \
        --browsers-dir "$PLAYWRIGHT_BROWSERS_PATH" \
        --output /usr/share/doc/memanga/THIRD_PARTY_NOTICES.txt \
    && python packaging/third_party_notices.py check \
        /usr/share/doc/memanga/THIRD_PARTY_NOTICES.txt \
        --require playwright --require pip \
        --require-browser chromium --require-browser firefox \
    && install -m 0644 LICENSE /usr/share/doc/memanga/LICENSE

USER memanga

VOLUME ["/home/memanga/.config/memanga", "/home/memanga/Downloads/MeManga"]

ENTRYPOINT ["memanga"]
CMD ["--help"]
