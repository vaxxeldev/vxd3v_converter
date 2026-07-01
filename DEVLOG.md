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
