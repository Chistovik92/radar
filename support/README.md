# Отдельный бот поддержки

Базовая установка не включает Gemini и не выполняет AI-запросы:

```sh
pip install -r support/requirements.txt
```

Gemini — опциональная функция. Для `/draft` и AI-классификации установите дополнительную зависимость и явно включите её:

```sh
pip install -r support/requirements-ai.txt
export SUPPORT_AI=1
export GEMINI_API_KEY=...
```

При `SUPPORT_AI=0` SDK не импортируется, сетевые AI-запросы не выполняются, FAQ и классификация работают детерминированно. При ошибке Gemini также используется безопасный детерминированный fallback.

Docker по умолчанию собирается без Gemini. Чтобы включить зависимость в образ:

```sh
docker build --build-arg SUPPORT_AI=1 -f support/Dockerfile .
```

Это build arg только для установки пакета; в runtime всё равно нужны `SUPPORT_AI=1` и `GEMINI_API_KEY`.
