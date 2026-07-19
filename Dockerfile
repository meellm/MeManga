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

# Install CLI-only dependencies and the Playwright Firefox runtime first so
# this expensive layer stays cached when only application source changes.
# requirements-docker.txt mirrors requirements.txt but omits PySide6 and
# other GUI-only packages so the container stays lean and headless.
COPY requirements-docker.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements-docker.txt \
    && python -m playwright install --with-deps firefox \
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

USER memanga

VOLUME ["/home/memanga/.config/memanga", "/home/memanga/Downloads/MeManga"]

ENTRYPOINT ["memanga"]
CMD ["--help"]
