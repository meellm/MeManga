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

# tini runs as PID 1 (issue #333) and reaps the browser processes that
# Playwright leaves behind when a driver or browser exits early; Python
# as PID 1 never reaps them, so they stayed as zombies until the
# container stopped. It forwards signals to memanga only, so the CLI's
# own SIGTERM and Ctrl-C handling is unchanged. -s keeps the reaping
# when tini is not PID 1 (docker run --init, Compose init: true).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

# Install CLI-only dependencies and the Playwright Firefox + Chromium runtimes
# first so this expensive layer stays cached when only application source
# changes. Chromium is needed by MangaPark, whose Cloudflare check blocks
# Firefox.
# requirements/cli.txt is generated from pyproject.toml (the CLI
# dependencies, without the gui extra) so the container stays lean and
# headless. It pins every package with hashes, for every platform, so the
# packages the image shares with the release builds get the same exact
# versions and pip refuses any download that does not match. Only pip
# itself is upgraded unpinned.
COPY requirements/cli.txt ./requirements/
RUN python -m pip install --upgrade pip \
    && python -m pip install --require-hashes -r requirements/cli.txt \
    && python -m playwright install --with-deps firefox chromium \
    && useradd --create-home --home-dir /home/memanga --shell /usr/sbin/nologin --uid 1000 memanga \
    && mkdir -p /home/memanga/.config/memanga /home/memanga/Downloads/MeManga \
    && chown -R memanga:memanga /home/memanga

# Install the package itself, unmodified. --no-deps keeps the pinned layer
# above the only source of dependencies; pip check then fails the build if
# pyproject.toml needs a package that layer does not provide. The image has
# no Qt runtime, so the memanga-gui launcher and --gui exit with an error
# (MEMANGA_CLI_ONLY).
# LICENSE is in the build context because pyproject.toml lists it in
# license-files, so the installed metadata carries it.
COPY pyproject.toml README.md LICENSE ./
COPY memanga ./memanga
RUN python -m pip install --no-deps . \
    && python -m pip check

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

ENTRYPOINT ["/usr/bin/tini", "-s", "--", "memanga"]
CMD ["--help"]
