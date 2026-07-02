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

## 2026-07-02 — Single Telegram output

- Removed user-facing format selection and kept Telegram GIF as silent H.264 MP4.
- Added startup migration from legacy video, file and true-GIF preferences.

## 2026-07-02 — Editable premium interface

- Replaced menu message spam with one persistent SQLite-backed control panel.
- Added premium custom emoji to interface text and button icons with a plain fallback.
- Added compact settings screens with Back and red Cancel navigation.
- User configuration messages are deleted after validation and errors stay inside the panel.
- Persisted the last sticker selection for a separate preview workflow.

## 2026-07-02 — Main panel copy

- Reworked the main panel into compact Send and Configuration blockquotes.
- Kept premium emoji while making the supplied Russian copy and hierarchy exact.

## 2026-07-02 — Panel recovery after chat clear

- Explicit `/start` now recreates the control panel instead of trusting a stale message ID.
- Added regression coverage for clearing Telegram chat history and starting again.

## 2026-07-02 — Cached animated banners

- Converted the persistent control panel to a Telegram animation with editable captions.
- Added start, wallet, top-up, size and resolution banners at 1920×530 and 60 FPS.
- Added memory plus SQLite `file_id` caching with SHA-256 invalidation and stale-ID recovery.
- Added the requested custom hourglass emoji to render status screens.

## 2026-07-02 — Manual balance payments

- Added direct-transfer top-ups with validated amounts, receipt uploads and admin review.
- Added atomic, one-time balance credits and explicit user notifications after approval.
- Added paid render reservations with automatic refunds after failed or interrupted renders.
- Added free full-quality previews with a forced semi-transparent centered `vxd3v` watermark.
- Added a YooKassa placeholder for the future provider integration.

## 2026-07-02 — Payment hotfix and admin credits

- Fixed direct-transfer callbacks by exposing the settings repository under the expected DI key.
- Added admin-only `.пополнить @username сумма` balance credits with an auditable ledger entry.
- Added normalized username tracking for users who interact with the bot.
- Increased the free preview's centered `vxd3v` watermark from 4% to 10% of canvas height.

## 2026-07-02 — Watermark fonts and Crypto Bot

- Added per-user Montserrat and Space Mono watermark selection with bundled OFL fonts.
- Increased regular watermark size to 8% and preview watermark size to 13% of canvas height.
- Replaced the YooKassa placeholder with RUB-denominated Crypto Bot invoices.
- Added persistent invoice polling, automatic one-time balance credits and payment notifications.
- Added strict API URL, response and payment-link validation while keeping the API token in env only.

## 2026-07-02 — Larger preview label

- Replaced the free preview watermark with a centered `предпросмотр` label.
- Increased its font size to 20% of canvas height without changing paid render watermarks.
