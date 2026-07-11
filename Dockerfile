FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HOME=/home/memanga

WORKDIR /app

COPY pyproject.toml README.md requirements.txt ./
COPY memanga ./memanga

RUN python -m pip install --upgrade pip \
    && python -m pip install . \
    && python -m playwright install --with-deps firefox \
    && useradd --create-home --home-dir /home/memanga --shell /usr/sbin/nologin --uid 1000 memanga \
    && mkdir -p /home/memanga/.config/memanga /home/memanga/Downloads/MeManga \
    && chown -R memanga:memanga /home/memanga

USER memanga

VOLUME ["/home/memanga/.config/memanga", "/home/memanga/Downloads/MeManga"]

ENTRYPOINT ["memanga"]
CMD ["--help"]
