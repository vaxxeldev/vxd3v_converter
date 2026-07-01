# DEVLOG

## 2026-07-02 — Clean foundation

- Initialized a new quality-first Python project without reusing the deleted implementation.
- Added Bothost-oriented configuration, pinned dependencies and media domain models.
- Preserved the supplied AI instructions and converter reference assets unchanged.

## 2026-07-02 — Native TGS renderer

- Added an `rlottie` C++ renderer with explicit premultiplied-to-straight alpha conversion.
- Added native adaptive tinting and streaming BGRA frames into lossless FFV1.
- Added bounded TGS validation, render planning and sanitized process diagnostics.
