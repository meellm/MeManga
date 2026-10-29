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
COPY pyproject.toml README.md ./
COPY memanga ./memanga
RUN python -m pip install --no-deps . \
    && rm -f /usr/local/bin/memanga-gui \
    && test ! -f /usr/local/bin/memanga-gui

# Third-party notices (issue #380): MeManga's license plus the license
# texts of every installed Python distribution, the Python runtime and the
# Playwright browser builds, in /usr/share/doc/memanga. The generator and
# its license texts are bind-mounted for this step only, so they do not
# stay in the image. The check fails the build if any entry lacks a
# license text or a browser build is missing.
COPY LICENSE /usr/share/doc/memanga/LICENSE
RUN --mount=type=bind,source=packaging,target=/tmp/memanga-packaging \
    python /tmp/memanga-packaging/third_party_notices.py generate \
        --label "Docker image" \
        --browsers-dir "$PLAYWRIGHT_BROWSERS_PATH" \
        --project-license /usr/share/doc/memanga/LICENSE \
        --output /usr/share/doc/memanga/THIRD_PARTY_NOTICES.txt \
    && python /tmp/memanga-packaging/third_party_notices.py check \
        /usr/share/doc/memanga/THIRD_PARTY_NOTICES.txt \
        --require playwright --require certifi --require pikepdf \
        --require-browser chromium --require-browser firefox

USER memanga

VOLUME ["/home/memanga/.config/memanga", "/home/memanga/Downloads/MeManga"]

ENTRYPOINT ["memanga"]
CMD ["--help"]
