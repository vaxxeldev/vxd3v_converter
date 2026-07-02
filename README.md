# VXD3V Converter

Telegram-бот для создания плавных MP4-анимаций из премиум-эмодзи и стикеров.
Рендер выполняется в 60 FPS через нативный rlottie и FFmpeg.

## Развёртывание на Bothost PRO

Проект использует собственный многоэтапный `Dockerfile`. В панели Bothost укажите:

- Git URL: `https://github.com/vaxxeldev/vxd3v_converter.git`;
- ветка: `main`;
- сборка: кастомный Dockerfile из корня репозитория;
- публичный порт и домен не нужны — бот работает через long polling.

Добавьте в разделе «Переменные окружения»:

| Переменная | Обязательность | Назначение |
|---|---:|---|
| `BOT_TOKEN` | обязательно | токен Telegram-бота |
| `ADMIN_ID` | обязательно | Telegram ID администратора платежей |
| `DIRECT_PAYMENT_BANK` | обязательно | банк для прямого перевода |
| `DIRECT_PAYMENT_REQUISITES` | обязательно | реквизиты получателя |
| `DIRECT_PAYMENT_RECIPIENT` | обязательно | имя получателя |
| `CRYPTO_PAY_TOKEN` | обязательно для Crypto Bot | API-токен приложения Crypto Pay |
| `NEW_USER_BONUS_KOPECKS` | рекомендуется | стартовый баланс нового пользователя, по умолчанию `1000` |
| `DATABASE_PATH` | рекомендуется | `/app/data/bot.sqlite3` |
| `CACHE_ROOT` | рекомендуется | `/app/data/cache` |

Остальные настройки и безопасные значения по умолчанию перечислены в
`.env.example`. Секреты нельзя добавлять в Git.

SQLite, кэш рендера и Telegram `file_id` сохраняются в `/app/data`. Bothost
монтирует эту папку как постоянное хранилище, поэтому баланс и настройки не
пропадают после обновления контейнера.

После первого деплоя проверьте в логах строки `Start polling` и
`Run polling for bot`. Если изменились переменные окружения, выполните повторный
деплой контейнера.

## Формат результата

Основной результат: MP4/H.264 High, yuv420p, 60 FPS и BT.709. Пользователю файл
отправляется как Telegram GIF-анимация.

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
