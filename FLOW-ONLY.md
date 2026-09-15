# FERIXDI FLOW ONLY — 15.09.2026

Отдельный split-routing профиль для Google Flow.

Через Ferixdi направляются:
- flow.google
- labs.google
- labs.google.com
- accounts.google.com
- googleapis.com
- gstatic.com
- googleusercontent.com
- storage.googleapis.com

Всё остальное:
- DIRECT

Пользователь получает персональную ссылку:

https://YOUR_DOMAIN/flow/PERSONAL_ID?token=SIGNED_TOKEN

Endpoint генерирует Mihomo/Clash-compatible YAML с группой
`FERIXDI FLOW AUTO`, которая выбирает живой US RAW/gRPC профиль.

Если US-узел недоступен, генератор использует другой здоровый узел,
чтобы профиль не становился пустым.

Почему не добавлен `google.com` целиком:
это отправило бы через VPN слишком много посторонних Google-сервисов.

Почему список включает общие Google CDN/API домены:
Flow использует общую инфраструктуру Google для авторизации, статических
ресурсов, API и медиа. Поэтому часть другого Google-трафика на этих общих
доменах тоже может идти через выбранный узел.
