# vxd3v converter

Quality-first Telegram converter for premium emoji and stickers.

The renderer targets the supplied reference contract: 1920×530, 60 FPS, 180 frames,
three seconds, H.264 High, yuv420p and BT.709 limited range.

Implementation and deployment details are added incrementally and recorded in
`DEVLOG.md`.

## Bothost PRO

The project uses a custom multi-stage `Dockerfile`. Add `BOT_TOKEN` in the
Bothost environment and deploy the `main` branch. Runtime sources are installed
under `/usr/local`, while persistent SQLite data and render cache live in
`/app/data` as required by Bothost volumes.

The default process uses long polling and does not require a public port.

Required Bothost environment variable: `BOT_TOKEN`. Optional tuning variables
are documented in `.env.example`; persistent state requires no external database.

## Local renderer

Inside the Linux container, a sticker can be rendered without Telegram:

```text
vxd3v-render sticker.tgs result.mp4 --format file --background #F74539
```

## Verification

```text
python -m pytest -ra
```

The integration test uses the local `vxd3v-converter:local` image when it is
available and verifies both the reference video metadata and actual frame motion.
