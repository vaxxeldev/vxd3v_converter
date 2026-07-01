# DEVLOG

## 2026-07-02 — Clean foundation

- Initialized a new quality-first Python project without reusing the deleted implementation.
- Added Bothost-oriented configuration, pinned dependencies and media domain models.
- Preserved the supplied AI instructions and converter reference assets unchanged.

## 2026-07-02 — Native TGS renderer

- Added an `rlottie` C++ renderer with explicit premultiplied-to-straight alpha conversion.
- Added native adaptive tinting and streaming BGRA frames into lossless FFV1.
- Added bounded TGS validation, render planning and sanitized process diagnostics.

## 2026-07-02 — Lossless conversion pipeline

- Added strict WEBP, TGS and WEBM validation plus FFprobe metadata inspection.
- Added a bounded per-user render queue and deterministic lossless TGS cache.
- Added 60 FPS alpha-aware composition, premium effects, adaptive recoloring,
  custom backgrounds and watermark positioning.
- Added H.264 High/BT.709 export profiles matching the supplied reference contract.

## 2026-07-02 — Persistent Telegram workflow

- Added durable SQLite user settings and pending input state.
- Added Aiogram menus for canvas, output, background, emoji color, size and watermark.
- Added direct extraction of premium custom emoji, stickers and public sticker-set links.
- Added output delivery as Telegram animation, video, high-quality file or real GIF.

## 2026-07-02 — Bothost PRO packaging

- Added a multi-stage Debian image that keeps compilers out of production.
- Installed the application and native renderer outside Bothost's `/app` source mount.
- Added a privilege-dropping entrypoint while retaining writable `/app/data` volumes.
- Added a Telegram-independent CLI for deterministic renderer checks.

## 2026-07-02 — Quality gate

- Added 26 tests for validation, layout, persistence, queueing, keyboards and export commands.
- Added a production-container integration render from a moving 60 FPS TGS fixture.
- Verified 1920×530, H.264 High, yuv420p, 180 frames and complete BT.709 VUI metadata.
- Verified at least 170 unique decoded frames, preventing static-frame false positives.
