# syntax=docker/dockerfile:1.7

FROM python:3.13-slim-trixie AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN apt-get update \
    && apt-get install --yes --no-install-recommends g++ librlottie-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
COPY native ./native

RUN g++ -O3 -DNDEBUG -std=c++17 -Wall -Wextra -Wpedantic \
        native/tgs_renderer.cpp -lrlottie -o /usr/local/bin/tgs-renderer \
    && strip /usr/local/bin/tgs-renderer \
    && python -m pip wheel --wheel-dir /wheels .


FROM python:3.13-slim-trixie AS runtime

LABEL org.opencontainers.image.source="https://github.com/vaxxeldev/vxd3v_shop" \
      org.opencontainers.image.description="Quality-first Telegram sticker converter"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    DATABASE_PATH=/app/data/bot.sqlite3 \
    CACHE_ROOT=/app/data/cache \
    BANNER_ROOT=/usr/src/app/banners \
    TEMP_ROOT=/tmp/vxd3v-converter \
    RLOTTIE_RENDERER_BIN=/usr/local/bin/tgs-renderer

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ffmpeg fonts-dejavu-core gosu librlottie0-1 tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 bot \
    && useradd --system --uid 10001 --gid bot --no-create-home bot

COPY --from=builder /wheels /wheels
RUN python -m pip install /wheels/*.whl \
    && rm -rf /wheels

COPY --from=builder /usr/local/bin/tgs-renderer /usr/local/bin/tgs-renderer
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint
COPY banners /usr/src/app/banners
COPY assets/fonts /usr/share/fonts/truetype/vxd3v
RUN chmod 0755 /usr/local/bin/tgs-renderer /usr/local/bin/docker-entrypoint

WORKDIR /usr/src/app
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/docker-entrypoint"]
CMD ["python", "-m", "app.main"]
