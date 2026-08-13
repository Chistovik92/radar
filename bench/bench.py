#!/usr/bin/env python3
"""Стенд сравнения ИИ-провайдеров для системы «Радар».

    python3 bench.py                      # прогнать всех, у кого есть ключ
    python3 bench.py --providers groq,deepseek,zai
    python3 bench.py --list-models        # какие модели реально видит каждый ключ
    python3 bench.py --probe              # только проверка доступности с этого сервера
    python3 bench.py --live saratovzhkh   # добавить свежие посты из канала (без эталона)
    python3 bench.py --selftest           # проверить логику подсчёта без сети

Ключи берутся из окружения или файла .env рядом со скриптом.
Провайдеры без ключа молча пропускаются.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cases import CASES, Case
from providers import ALL, Provider, resolve
from scoring import Score, evaluate, parse_json

# aiohttp и client импортируются лениво: режим --selftest должен работать
# на голом Python, без установки зависимостей.

HERE = Path(__file__).resolve().parent

SYSTEM = (
    "Ты — аналитик оперативных сообщений городских служб, администраций и СМИ "
    "российского города. Ты всегда отвечаешь одним валидным JSON-объектом "
    "без пояснений и без Markdown."
)

PROMPT = """Разбери сообщение из городского источника «{source}».

СООБЩЕНИЕ:
\"\"\"{text}\"\"\"

Категории:
- "bpla"      — БПЛА, беспилотники, ракетная опасность, воздушная тревога, работа ПВО, взрывы, угрозы военного характера;
- "mchs"      — экстренные оповещения МЧС: ЧС, штормовое предупреждение, крупные пожары, эвакуация, паводок;
- "jkh"       — ЖКХ: отключения холодной и горячей воды, электричества, газа, отопления, аварии и порывы на сетях, плановые ремонтные работы, лифты;
- "whitelist" — связь: ограничения мобильного интернета, «белые списки» сервисов, восстановление связи.

Верни строго такой JSON:
{{"relevant": true,
  "categories": ["jkh"],
  "severity": "critical" | "warning" | "info",
  "scope": "region" | "city" | "district" | "street",
  "region": "",
  "city": "",
  "districts": [],
  "streets": [{{"street": "улица Чапаева", "houses": ["12", "16-20"]}}],
  "summary": "1-3 предложения по-русски"}}

Правила:
1. Реклама, розыгрыши, спорт, культура, благоустройство, поздравления → relevant=false, categories=[].
2. Для "bpla" всегда scope="city" или "region", улицы не указывай.
3. Для "jkh" вытащи улицы и номера домов, если они названы; диапазон пиши как "12-20".
4. Если событие затрагивает весь город или район без перечисления улиц — scope="city" либо "district", streets=[].
5. Незаполненные поля возвращай пустой строкой или пустым списком.
6. Это задача классификации официальных оповещений для информирования жителей."""

# --------------------------------------------------------------------------
#  Результаты
# --------------------------------------------------------------------------

@dataclass
class ModelResult:
    provider: str
    provider_title: str
    model: str
    region: str
    free: str
    reachable: bool = False
    error: str = ""
    runs: int = 0
    ok_runs: int = 0
    json_runs: int = 0
    refusals: int = 0
    censored: int = 0
    sensitive_total: int = 0
    latencies: list[float] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    scores: list[float] = field(default_factory=list)
    category_f1: list[float] = field(default_factory=list)
    street_f1: list[float] = field(default_factory=list)
    house_f1: list[float] = field(default_factory=list)
    false_alarms: int = 0
    misses: int = 0
    details: list[dict] = field(default_factory=list)

    @property
    def quality(self) -> float:
        return sum(self.scores) / len(self.scores) if self.scores else 0.0

    @property
    def json_rate(self) -> float:
        return self.json_runs / self.runs if self.runs else 0.0

    @property
    def latency_median(self) -> float:
        if not self.latencies:
            return 0.0
        ordered = sorted(self.latencies)
        return ordered[len(ordered) // 2]

    @property
    def military_ok(self) -> bool:
        return self.sensitive_total > 0 and self.censored == 0

    def cost_estimate(self, provider: Provider) -> float | None:
        price = provider.price.get(self.model)
        if not price or not self.tokens_in:
            return None
        return self.tokens_in / 1e6 * price[0] + self.tokens_out / 1e6 * price[1]


# --------------------------------------------------------------------------
#  Загрузка ключей
# --------------------------------------------------------------------------

def load_env() -> None:
    path = HERE / ".env"
    if not path.exists():
        return
    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


def api_key(provider: Provider) -> str:
    return (os.getenv(provider.env) or "").strip()


# --------------------------------------------------------------------------
#  Прогон
# --------------------------------------------------------------------------

async def probe(session: Any, provider: Provider) -> tuple[bool, str]:
    """Один короткий запрос: доступен ли провайдер с этой машины."""
    from client import ask

    key = api_key(provider)
    if not key:
        return False, "ключ не задан"
    model = provider.models[0]
    reply = await ask(
        session, provider, model, key,
        system="", prompt="Ответь одним словом: работает",
        json_mode=False, max_tokens=32, timeout=45,
    )
    if reply.ok:
        return True, f"ответ за {reply.latency:.1f} с"
    if reply.unreachable:
        return False, f"недоступен из этой сети — {reply.error[:160]}"
    return False, reply.error[:200]


async def run_model(
    session: Any,
    provider: Provider,
    model: str,
    cases: list[Case],
    verbose: bool,
) -> ModelResult:
    from client import Reply, ask  # noqa: F401

    result = ModelResult(
        provider=provider.key,
        provider_title=provider.title,
        model=model,
        region=provider.region,
        free=provider.free,
    )
    key = api_key(provider)

    for index, case in enumerate(cases):
        if index:
            await asyncio.sleep(provider.min_interval)

        reply = await ask(
            session, provider, model, key,
            system=SYSTEM,
            prompt=PROMPT.format(source=case.source, text=case.text),
            json_mode=True, max_tokens=1200,
        )
        result.runs += 1
        result.latencies.append(reply.latency)
        if case.sensitive:
            result.sensitive_total += 1

        if not reply.ok:
            result.error = result.error or reply.error
            if reply.unreachable:
                result.reachable = False
                result.error = f"недоступен: {reply.error[:160]}"
                if verbose:
                    print(f"      ✗ {case.ident}: {result.error}")
                break
            if reply.refused:
                result.refusals += 1
                if case.sensitive:
                    result.censored += 1
            result.details.append(
                {"case": case.ident, "ok": False, "error": reply.error[:200]}
            )
            if verbose:
                print(f"      ✗ {case.ident}: {reply.error[:120]}")
            continue

        result.reachable = True
        result.ok_runs += 1
        result.tokens_in += reply.tokens_in
        result.tokens_out += reply.tokens_out

        if reply.refused:
            result.refusals += 1
            if case.sensitive:
                result.censored += 1

        score: Score = evaluate(case, reply.text)
        if score.parsed:
            result.json_runs += 1
        if score.censored:
            result.censored += 1
        if score.false_alarm:
            result.false_alarms += 1
        if score.missed:
            result.misses += 1

        result.scores.append(score.total)
        result.category_f1.append(score.category_f1)
        if case.streets:
            result.street_f1.append(score.street_f1)
        if case.houses:
            result.house_f1.append(score.house_f1)

        result.details.append(
            {
                "case": case.ident,
                "ok": True,
                "score": round(score.total, 3),
                "categories_f1": round(score.category_f1, 3),
                "scope_ok": score.scope_ok,
                "street_f1": round(score.street_f1, 3),
                "house_f1": round(score.house_f1, 3),
                "notes": score.notes,
                "answer": parse_json(reply.text) or reply.text[:300],
            }
        )
        if verbose:
            mark = "✓" if score.total >= 0.7 else "~" if score.total >= 0.4 else "✗"
            print(f"      {mark} {case.ident}: {score.total:.2f} ({reply.latency:.1f} с)")

    # Дедупликация: censored мог посчитаться дважды (отказ + пустая категория)
    result.censored = min(result.censored, result.sensitive_total)
    return result


# --------------------------------------------------------------------------
#  Отчёты
# --------------------------------------------------------------------------

def console_report(results: list[ModelResult], skipped: list[tuple[str, str]]) -> None:
    print("\n" + "=" * 96)
    print("ИТОГИ".center(96))
    print("=" * 96)

    header = f"{'Провайдер / модель':<44}{'Кач-во':>8}{'JSON':>7}{'БПЛА':>7}{'Задержка':>10}{'Регион':>18}"
    print(header)
    print("-" * 96)

    for item in sorted(results, key=lambda r: (-r.quality, r.latency_median)):
        name = f"{item.provider_title} / {item.model}"
        if len(name) > 43:
            name = name[:40] + "…"
        if not item.reachable:
            print(f"{name:<44}{'—':>8}{'—':>7}{'—':>7}{'—':>10}{item.region:>18}")
            print(f"    ⚠️  {item.error[:88]}")
            continue
        military = "ок" if item.military_ok else f"срез {item.censored}/{item.sensitive_total}"
        print(
            f"{name:<44}{item.quality * 100:>7.0f}%{item.json_rate * 100:>6.0f}%"
            f"{military:>7}{item.latency_median:>9.1f}с{item.region:>18}"
        )

    if skipped:
        print("\nПропущены (нет ключа):")
        for title, env in skipped:
            print(f"  • {title} — задайте {env}")

    reachable = [item for item in results if item.reachable]
    if not reachable:
        print("\n⚠️  Ни один провайдер не ответил. Проверьте ключи и доступ в сеть.")
        return

    print("\nРекомендации:")
    best = max(reachable, key=lambda r: r.quality)
    print(f"  • Лучшее качество разбора: {best.provider_title} / {best.model} "
          f"({best.quality * 100:.0f}%)")

    military = [item for item in reachable if item.military_ok]
    if military:
        pick = max(military, key=lambda r: r.quality)
        print(f"  • Без фильтрации военных тем: {pick.provider_title} / {pick.model}")
    else:
        print("  • ⚠️  Все проверенные модели срезают военную тематику — "
              "оповещения по БПЛА придётся оставить на эвристике")

    fastest = min(reachable, key=lambda r: r.latency_median)
    print(f"  • Самый быстрый: {fastest.provider_title} / {fastest.model} "
          f"({fastest.latency_median:.1f} с)")


def markdown_report(results: list[ModelResult], skipped: list[tuple[str, str]]) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Сравнение ИИ-провайдеров для системы «Радар»",
        "",
        f"Прогон: {stamp}. Кейсов на модель: {len(CASES)}.",
        "",
        "| Провайдер | Модель | Регион | Качество | JSON | Военные темы | Медиана задержки | Бесплатно |",
        "|---|---|---|---:|---:|---|---:|---|",
    ]
    for item in sorted(results, key=lambda r: -r.quality):
        if not item.reachable:
            lines.append(
                f"| {item.provider_title} | `{item.model}` | {item.region} | — | — | — | — | "
                f"недоступен: {item.error[:60]} |"
            )
            continue
        military = "✅ разбирает" if item.military_ok else f"⚠️ срезано {item.censored}/{item.sensitive_total}"
        lines.append(
            f"| {item.provider_title} | `{item.model}` | {item.region} | "
            f"{item.quality * 100:.0f}% | {item.json_rate * 100:.0f}% | {military} | "
            f"{item.latency_median:.1f} с | {item.free} |"
        )

    lines += ["", "## Подробности по метрикам", ""]
    for item in sorted(results, key=lambda r: -r.quality):
        if not item.reachable:
            continue
        streets = (
            f"{sum(item.street_f1) / len(item.street_f1) * 100:.0f}%"
            if item.street_f1 else "—"
        )
        houses = (
            f"{sum(item.house_f1) / len(item.house_f1) * 100:.0f}%"
            if item.house_f1 else "—"
        )
        lines += [
            f"### {item.provider_title} / `{item.model}`",
            "",
            f"- Валидный JSON: {item.json_runs}/{item.runs}",
            f"- Категории (F1): {sum(item.category_f1) / len(item.category_f1) * 100:.0f}%"
            if item.category_f1 else "- Категории: —",
            f"- Улицы: {streets}, дома: {houses}",
            f"- Ложные срабатывания на шуме: {item.false_alarms}",
            f"- Пропущенные значимые события: {item.misses}",
            f"- Отказы модели: {item.refusals}",
            f"- Токенов: {item.tokens_in} вход / {item.tokens_out} выход",
            "",
        ]

    if skipped:
        lines += ["## Не проверялись", ""]
        lines += [f"- {title} — не задан `{env}`" for title, env in skipped]
        lines.append("")

    return "\n".join(lines)


# --------------------------------------------------------------------------
#  Режимы
# --------------------------------------------------------------------------

async def mode_probe(providers: list[Provider]) -> None:
    import aiohttp

    print("Проверка доступности с этой машины\n")
    async with aiohttp.ClientSession() as session:
        for provider in providers:
            if not api_key(provider):
                print(f"  ⏭  {provider.title:<26} ключ не задан ({provider.env})")
                continue
            ok, detail = await probe(session, provider)
            mark = "✅" if ok else "❌"
            print(f"  {mark} {provider.title:<26} {detail}")


async def mode_list_models(providers: list[Provider]) -> None:
    import aiohttp

    from client import list_models

    print("Реальные списки моделей\n")
    async with aiohttp.ClientSession() as session:
        for provider in providers:
            key = api_key(provider)
            if not key:
                continue
            names, error = await list_models(session, provider, key)
            print(f"── {provider.title} ({provider.region})")
            if error:
                print(f"   ошибка: {error}")
                continue
            print(f"   доступно: {len(names)}")
            for candidate in provider.models:
                mark = "✅" if candidate in names else "❌ нет в каталоге"
                print(f"   {mark} {candidate}")
            others = [n for n in names if n not in provider.models][:12]
            if others:
                print(f"   прочие: {', '.join(others)}")
            print()


async def fetch_live(channel: str, limit: int) -> list[Case]:
    """Свежие посты канала как дополнительные кейсы (без эталона, для глазами)."""
    import aiohttp

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("Для --live нужен beautifulsoup4: pip install beautifulsoup4")
        return []
    url = f"https://t.me/s/{channel}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
            if response.status != 200:
                print(f"Канал @{channel}: HTTP {response.status}")
                return []
            page = await response.text()
    soup = BeautifulSoup(page, "html.parser")
    blocks = soup.find_all("div", class_="tgme_widget_message_text")
    cases = []
    for index, block in enumerate(blocks[-limit:]):
        text = block.get_text(separator="\n").strip()
        if len(text) > 40:
            cases.append(
                Case(ident=f"live-{channel}-{index}", text=text, source=channel,
                     categories=[], scope="city", note="живой пост, эталона нет")
            )
    return cases


def mode_selftest() -> int:
    """Проверка логики подсчёта без обращения к сети."""
    from cases import by_ident

    checks: list[tuple[str, bool]] = []

    case = by_ident("jkh-water-street")
    perfect = json.dumps({
        "relevant": True, "categories": ["jkh"], "scope": "street",
        "streets": [
            {"street": "ул. Чапаева", "houses": ["12", "14", "16"]},
            {"street": "улица Рахова", "houses": ["3"]},
        ],
    }, ensure_ascii=False)
    score = evaluate(case, perfect)
    checks.append(("идеальный ответ по ЖКХ ≥ 0.95", score.total >= 0.95))
    checks.append(("категории распознаны точно", score.exact_categories))

    wrong_street = json.dumps({
        "relevant": True, "categories": ["jkh"], "scope": "street",
        "streets": [{"street": "улица Ленина", "houses": ["1"]}],
    }, ensure_ascii=False)
    checks.append(("чужая улица снижает оценку", evaluate(case, wrong_street).total < 0.7))

    noise = by_ident("noise-contest")
    false_alarm = evaluate(noise, json.dumps({"relevant": True, "categories": ["jkh"]}))
    checks.append(("ложное срабатывание отмечено", false_alarm.false_alarm))
    clean = evaluate(noise, json.dumps({"relevant": False, "categories": []}))
    checks.append(("шум отсеян корректно", clean.total >= 0.9))

    military = by_ident("mil-uav-alert")
    censored = evaluate(military, json.dumps({"relevant": False, "categories": []}))
    checks.append(("цензура военной темы поймана", censored.censored))
    broken = evaluate(military, "Извините, я не могу обсуждать эту тему.")
    checks.append(("отказ без JSON пойман", broken.censored and not broken.parsed))

    ranged = by_ident("jkh-power-range")
    span = json.dumps({
        "relevant": True, "categories": ["jkh"], "scope": "street",
        "streets": [{"street": "проспект 50 лет Октября", "houses": ["12-20"]}],
    }, ensure_ascii=False)
    checks.append(("диапазон домов разворачивается", evaluate(ranged, span).house_f1 == 1.0))

    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"  {'✓' if ok else '✗'} {name}")
    print(f"\n{len(checks) - len(failed)}/{len(checks)} проверок пройдено")
    return 1 if failed else 0


# --------------------------------------------------------------------------
#  Точка входа
# --------------------------------------------------------------------------

async def main_async(args) -> int:
    import aiohttp

    providers = resolve([p for p in (args.providers or "").split(",") if p.strip()])

    if args.probe:
        await mode_probe(providers)
        return 0
    if args.list_models:
        await mode_list_models(providers)
        return 0

    cases = list(CASES)
    if args.live:
        extra = await fetch_live(args.live, args.live_limit)
        print(f"Добавлено живых постов: {len(extra)} (оцениваются только глазами)\n")
        cases += extra
    if args.quick:
        seen_kinds: set[str] = set()
        quick: list[Case] = []
        for case in cases:
            kind = case.categories[0] if case.categories else "noise"
            if kind not in seen_kinds or case.sensitive:
                quick.append(case)
                seen_kinds.add(kind)
        cases = quick

    active: list[tuple[Provider, str]] = []
    skipped: list[tuple[str, str]] = []
    for provider in providers:
        if not api_key(provider):
            skipped.append((provider.title, provider.env))
            continue
        models = provider.models[:1] if args.first_model_only else provider.models
        for model in models:
            active.append((provider, model))

    if not active:
        print("Нет ни одного провайдера с заданным ключом.")
        print("Скопируйте .env.example в .env и впишите ключи, которые есть.")
        for title, env in skipped:
            print(f"  • {title}: {env}")
        return 1

    print(f"Провайдеров с ключами: {len({p.key for p, _ in active})}, "
          f"моделей: {len(active)}, кейсов: {len(cases)}")
    print(f"Ориентировочно запросов: {len(active) * len(cases)}\n")

    results: list[ModelResult] = []
    async with aiohttp.ClientSession() as session:
        for provider, model in active:
            print(f"── {provider.title} / {model}")
            started = time.monotonic()
            result = await run_model(session, provider, model, cases, args.verbose)
            results.append(result)
            if result.reachable:
                print(f"   качество {result.quality * 100:.0f}%, "
                      f"JSON {result.json_runs}/{result.runs}, "
                      f"{time.monotonic() - started:.0f} с")
            else:
                print(f"   ⚠️  {result.error[:120]}")

    console_report(results, skipped)

    report_md = HERE / "report.md"
    report_md.write_text(markdown_report(results, skipped), encoding="utf-8")
    report_json = HERE / "report.json"
    report_json.write_text(
        json.dumps([asdict(item) for item in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nОтчёты: {report_md} и {report_json}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Сравнение ИИ-провайдеров для системы «Радар»",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"Известные провайдеры: {', '.join(p.key for p in ALL)}",
    )
    parser.add_argument("--providers", help="список через запятую; по умолчанию все")
    parser.add_argument("--probe", action="store_true", help="только проверка доступности")
    parser.add_argument("--list-models", action="store_true", help="реальные каталоги моделей")
    parser.add_argument("--selftest", action="store_true", help="проверка метрик без сети")
    parser.add_argument("--quick", action="store_true", help="сокращённый набор кейсов")
    parser.add_argument("--first-model-only", action="store_true",
                        help="по одной модели на провайдера")
    parser.add_argument("--live", metavar="CHANNEL", help="добавить свежие посты канала")
    parser.add_argument("--live-limit", type=int, default=5)
    parser.add_argument("--verbose", "-v", action="store_true", help="показывать каждый кейс")
    args = parser.parse_args()

    if args.selftest:
        return mode_selftest()

    load_env()
    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\nПрервано.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
