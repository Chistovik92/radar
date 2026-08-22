#!/usr/bin/env bash

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

#
# Получает сертификат и поднимает перед панелью Caddy, который сам держит
# его в актуальном состоянии.
#
# Почему Caddy, а не certbot с nginx: Caddy получает и продлевает
# сертификат сам, без cron и хуков. Для машины, за которой никто
# не следит ежедневно, это важнее гибкости — забытое продление ломает
# панель ровно через три месяца, когда о нём уже никто не помнит.
#
# ГЛАВНОЕ ОГРАНИЧЕНИЕ, о котором нужно знать заранее: проверка владения
# доменом идёт ИЗВНЕ на порты 80 и 443. Если роутер их не пробрасывает
# или провайдер режет — выдача не пройдёт, и никакие настройки здесь
# не помогут. Скрипт проверяет это до обращения к Let's Encrypt,
# чтобы не тратить попытки: у них лимит пять неудач в час на домен.
#
set -Eeuo pipefail

APP_DIR="${RADAR_HOME:-$HOME/radar_bot}"
DOMAIN="${1:-}"
EMAIL="${2:-}"

C_RESET=""; C_BOLD=""; C_DIM=""; C_GREEN=""; C_RED=""; C_YELLOW=""
if [ -t 1 ]; then
    C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
    C_GREEN=$'\033[1;32m'; C_RED=$'\033[1;31m'; C_YELLOW=$'\033[1;33m'
fi
ok()   { printf "  %s✓%s %s\n" "$C_GREEN" "$C_RESET" "$*"; }
info() { printf "  %s→%s %s\n" "$C_DIM" "$C_RESET" "$*"; }
warn() { printf "  %s!%s %s\n" "$C_YELLOW" "$C_RESET" "$*"; }
die()  { printf "\n  %s✗ %s%s\n\n" "$C_RED" "$*" "$C_RESET" >&2; exit 1; }

if [ -z "$DOMAIN" ]; then
    cat <<'USAGE'

  Сертификат для веб-панели «Радара»

  Использование:
    bash tls.sh домен [почта]

  Например:
    bash tls.sh radar.example.ru admin@example.ru

  Что нужно заранее:
    1. Домен указывает A-записью на внешний адрес этого сервера.
    2. Порты 80 и 443 проброшены на сервер снаружи.
       Проверка владения доменом идёт именно снаружи — без проброса
       сертификат не выдадут, сколько ни пробуй.

USAGE
    exit 0
fi

printf "\n  %sСертификат для %s%s\n\n" "$C_BOLD" "$DOMAIN" "$C_RESET"

command -v docker >/dev/null 2>&1 || die "Docker не установлен"
[ -d "$APP_DIR" ] || die "Установка не найдена в $APP_DIR"

# --- проверки до обращения к Let's Encrypt --------------------------------
#
# У них лимит: пять неудачных попыток на домен в час. Поэтому всё, что
# можно проверить самим, проверяем заранее.

info "Проверяю, куда указывает домен"
resolved="$(getent hosts "$DOMAIN" 2>/dev/null | awk '{print $1}' | head -1 || true)"
external="$(curl -fsS --max-time 8 https://api.ipify.org 2>/dev/null || true)"

if [ -z "$resolved" ]; then
    die "Домен $DOMAIN не разрешается в адрес — проверьте A-запись"
fi
ok "Домен указывает на $resolved"

if [ -n "$external" ] && [ "$resolved" != "$external" ]; then
    warn "Внешний адрес сервера — $external, а домен указывает на $resolved"
    warn "Если между ними нет проброса, проверка владения не пройдёт"
fi

info "Проверяю, свободен ли порт 80"
if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ':80 '; then
    die "Порт 80 занят. Освободите его: проверка Let's Encrypt идёт на него"
fi
ok "Порт 80 свободен"

WEB_PORT="$(grep -E '^WEB_PORT=' "$APP_DIR/.env" 2>/dev/null | cut -d= -f2- || true)"
: "${WEB_PORT:=8080}"

# --- Caddy ----------------------------------------------------------------

mkdir -p "$APP_DIR/tls"
cat > "$APP_DIR/tls/Caddyfile" <<CADDY
$DOMAIN {
    reverse_proxy radar:$WEB_PORT
    encode gzip
}
CADDY
ok "Настройки Caddy записаны"

cat > "$APP_DIR/tls/docker-compose.tls.yml" <<COMPOSE
services:
  caddy:
    image: caddy:2-alpine
    container_name: radar_tls
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./tls/Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    networks:
      - default

volumes:
  caddy_data:
  caddy_config:
COMPOSE
ok "Описание контейнера готово"

info "Поднимаю Caddy — сертификат запросится автоматически"
cd "$APP_DIR"
if ! docker compose -f docker-compose.yml -f tls/docker-compose.tls.yml up -d caddy; then
    die "Caddy не запустился — смотрите docker logs radar_tls"
fi

printf "\n"
info "Жду выдачу сертификата (обычно до минуты)"
issued=false
for _ in $(seq 1 30); do
    if docker logs radar_tls 2>&1 | grep -q "certificate obtained successfully"; then
        issued=true
        break
    fi
    sleep 4
done

if [ "$issued" = true ]; then
    ok "Сертификат получен"
    printf "\n  Панель доступна: %shttps://%s%s\n" "$C_BOLD" "$DOMAIN" "$C_RESET"
    printf "  Короткие ссылки: %shttps://%s/s/КОД%s\n\n" "$C_BOLD" "$DOMAIN" "$C_RESET"
    printf "  Не забудьте задать в боте:\n"
    printf "    SHORT_BASE_URL = https://%s\n\n" "$DOMAIN"
else
    warn "Сертификат пока не выдан. Обычная причина — порты 80 и 443"
    warn "не проброшены снаружи. Посмотрите: docker logs radar_tls"
    printf "\n"
fi
