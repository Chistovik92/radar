"""Модель разобранной новости, правила сопоставления с локациями и сборка сообщений.

Только стандартная библиотека — модуль полностью покрывается тестами офлайн.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .textutils import (
    cluster_locations,
    district_matches,
    esc,
    esc_attr,
    house_in_range,
    normalize_city,
    same_city,
    street_matches,
)

# Ключи категорий совпадают с настройками пользователя из версий 2.x —
# это сохраняет совместимость с продакшен-базой.
CATEGORY_TITLES = {
    "bpla": "БПЛА / ракетная опасность",
    "mchs": "Экстренные оповещения МЧС",
    "jkh": "ЖКХ и аварии на сетях",
    "whitelist": "Предупреждать о «белых списках»",
}

CATEGORY_ICONS = {"bpla": "🛸", "mchs": "🆘", "jkh": "🛠", "whitelist": "📶"}

# Военные угрозы объявляются на весь город, независимо от указанных улиц.
CITY_WIDE_ALWAYS = {"bpla"}
# Связь и «белые списки» обычно вводятся на город/регион целиком.
CITY_WIDE_DEFAULT = {"whitelist"}

SEVERITY_ICONS = {"critical": "🔴", "warning": "🟠", "info": "🔵"}

# О «белых списках» в городских пабликах почти не пишут — операторы вводят их
# молча. Поэтому предупреждение выдаётся не по новости, а автоматически:
# объявлена угроза БПЛА или ракетная опасность → значит связь, скорее всего,
# уже ограничена.
ALL_CLEAR_NOTICE = (
    "📶 <b>Мобильный интернет</b>\n"
    "«Белые списки» могут быть отключены в ближайшее время — связь обычно "
    "восстанавливают не сразу после отбоя, а в течение нескольких часов."
)

WHITELIST_NOTICE = (
    "📵 <b>Мобильный интернет</b>\n"
    "При угрозе с воздуха операторы включают «белые списки»: работают только "
    "госуслуги, банки, карты и такси. Мессенджеры и соцсети могут не открываться.\n"
    "Домашний проводной интернет и Wi-Fi обычно продолжают работать. "
    "Для срочной связи — звонки и SMS."
)


@dataclass
class Analysis:
    """Результат разбора одного сообщения источника."""

    relevant: bool = False
    categories: list[str] = field(default_factory=list)
    severity: str = "info"
    scope: str = "city"  # region | city | district | street
    region: str = ""
    city: str = ""
    districts: list[str] = field(default_factory=list)
    streets: list[dict[str, Any]] = field(default_factory=list)  # {"street": str, "houses": [str]}
    summary: str = ""
    source: str = ""
    raw: str = ""
    link: str = ""            # ссылка на новость (для RSS)
    all_clear: bool = False   # отбой ранее объявленной опасности
    engine: str = "ai"  # ai | heuristic

    @classmethod
    def from_payload(
        cls, payload: dict[str, Any], *, source: str, raw: str, link: str = ""
    ) -> "Analysis":
        streets: list[dict[str, Any]] = []
        for item in payload.get("streets") or []:
            if isinstance(item, str):
                streets.append({"street": item, "houses": []})
            elif isinstance(item, dict) and item.get("street"):
                houses = item.get("houses") or []
                streets.append(
                    {
                        "street": str(item["street"]),
                        "houses": [str(h) for h in houses if str(h).strip()],
                    }
                )
        categories = [c for c in (payload.get("categories") or []) if c in CATEGORY_TITLES]
        severity = str(payload.get("severity") or "info").lower()
        scope = str(payload.get("scope") or "city").lower()
        return cls(
            relevant=bool(payload.get("relevant")) and bool(categories),
            categories=categories,
            severity=severity if severity in SEVERITY_ICONS else "info",
            scope=scope if scope in {"region", "city", "district", "street"} else "city",
            region=str(payload.get("region") or "").strip(),
            city=str(payload.get("city") or "").strip(),
            districts=[str(d) for d in (payload.get("districts") or []) if str(d).strip()],
            streets=streets,
            summary=str(payload.get("summary") or "").strip(),
            source=source,
            raw=raw,
            link=link,
            all_clear=bool(payload.get("all_clear")),
        )

    @property
    def is_city_wide(self) -> bool:
        """Оповещение действует на весь город (военная угроза, связь, общегородская ЧС)."""
        cats = set(self.categories)
        if cats & CITY_WIDE_ALWAYS:
            return True
        if cats & CITY_WIDE_DEFAULT and not self.streets:
            return True
        if "jkh" in cats:
            return False
        # МЧС и прочее: адресное, только если названы конкретные улицы
        return not self.streets

    @property
    def icon(self) -> str:
        for key in ("bpla", "mchs", "jkh", "whitelist"):
            if key in self.categories:
                return CATEGORY_ICONS[key]
        return "ℹ️"

    def title(self) -> str:
        names = [CATEGORY_TITLES[c] for c in self.categories if c in CATEGORY_TITLES]
        return " / ".join(names) or "Событие"

    def text(self) -> str:
        return self.summary or self.raw[:300]


# --------------------------------------------------------------------------
#  Эвристический разбор (работает без Gemini)
# --------------------------------------------------------------------------

_HEURISTICS: list[tuple[str, re.Pattern]] = [
    ("bpla", re.compile(
        r"бпла|беспилотн|дрон|воздушн\w* тревог|ракетн\w* опасн|работа\w* пво|"
        r"противовоздушн|обломк\w* бпла|угроз\w* атаки", re.I)),
    ("mchs", re.compile(
        r"мчс|штормов\w* предупрежд|чрезвычайн\w* ситуац|эвакуац|крупн\w* пожар|"
        r"экстренн\w* оповещ|режим повышенной готовности|паводок|подтоплен", re.I)),
    ("jkh", re.compile(
        r"отключ\w*\s+(?:воды|холодн|горяч|электро|света|газ|отоплен)|"
        r"без воды|без света|без газа|без отоплен|прекращ\w* подач|"
        r"аварий\w*\s+(?:работ|отключ|ситуац)|порыв|утечк\w* газа|"
        r"ремонтн\w* работ|коммунальн\w* авар|обесточ", re.I)),
    ("whitelist", re.compile(
        r"бел\w* список|ограничен\w* мобильн\w* интернет|мобильн\w* интернет"
        r"|перебо\w* (?:со )?связ|ограничен\w* связи", re.I)),
]

ALL_CLEAR_RE = re.compile(
    r"отбо[йя]\b|снят\w*\s+(?:режим\w*\s+)?(?:беспилотн\w*|ракетн\w*|воздушн\w*|опасн\w*)|"
    r"опасност\w*\s+снят|угроза\s+снят|тревога\s+отмен|"
    r"режим\w*\s+беспилотн\w*\s+опасност\w*\s+отмен|"
    r"отмен\w*\s+(?:режим\w*\s+)?(?:беспилотн\w*|ракетн\w*|воздушн\w*)|"
    r"обстановка\s+спокойн|угроз\w*\s+миновал",
    re.I,
)

_STREET_TYPE_RE = (
    r"(?:ул(?:ица|\.)?|пр(?:оспект|-т|\.)?|пер(?:еулок|\.)?|б(?:ульвар|-р)|"
    r"ш(?:оссе|\.)?|пл(?:ощадь|\.)?|проезд|наб(?:ережная|\.)?|тракт|мкр(?:орайон)?)"
)
_STREET_AFTER = re.compile(
    _STREET_TYPE_RE + r"\s+([А-ЯЁ][\w\-]+(?:\s+[А-ЯЁ]?[\w\-]+){0,2})", re.U
)
_STREET_BEFORE = re.compile(
    r"([А-ЯЁ][\w\-]+(?:\s+[А-ЯЁ]?[\w\-]+){0,1})\s+" + _STREET_TYPE_RE + r"(?![\w])", re.U
)
_HOUSES = re.compile(r"(?:д(?:ом|\.)|№)\s*([\d]+[А-Яа-яA-Za-z]?(?:\s*/\s*\d+)?)", re.U)
_DISTRICT = re.compile(r"([А-ЯЁ][а-яё\-]+)\s+район", re.U)
_CITY = re.compile(r"(?:в|город[еа]?|г\.)\s+([А-ЯЁ][а-яё\-]+)", re.U)


def heuristic_analysis(
    text: str, *, source: str = "", default_city: str = "", link: str = ""
) -> Analysis:
    """Резервный разбор без ИИ: ключевые слова + извлечение улиц и домов."""
    categories = [key for key, pattern in _HEURISTICS if pattern.search(text)]
    if not categories:
        return Analysis(
            relevant=False, source=source, raw=text, link=link, engine="heuristic"
        )

    streets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in list(_STREET_AFTER.finditer(text)) + list(_STREET_BEFORE.finditer(text)):
        name = match.group(1).strip(" ,.;:")
        key = name.lower()
        if len(name) < 3 or key in seen:
            continue
        seen.add(key)
        tail = text[match.end(): match.end() + 60]
        houses = [h.replace(" ", "") for h in _HOUSES.findall(tail)]
        streets.append({"street": name, "houses": houses})

    districts = [f"{d} район" for d in dict.fromkeys(_DISTRICT.findall(text))]
    city_match = _CITY.search(text)
    city = city_match.group(1) if city_match else default_city

    if "bpla" in categories:
        scope = "city"
    elif streets:
        scope = "street"
    elif districts:
        scope = "district"
    else:
        scope = "city"

    all_clear = bool(ALL_CLEAR_RE.search(text))
    if all_clear:
        severity = "info"
    else:
        severity = "critical" if {"bpla", "mchs"} & set(categories) else "warning"
    summary = re.sub(r"\s+", " ", text).strip()
    return Analysis(
        relevant=True,
        all_clear=all_clear,
        categories=categories,
        severity=severity,
        scope=scope,
        city=city,
        districts=districts,
        streets=streets[:8],
        summary=summary[:400],
        source=source,
        raw=text,
        link=link,
        engine="heuristic",
    )


# --------------------------------------------------------------------------
#  Сопоставление новости с локацией
# --------------------------------------------------------------------------

def location_city(loc: dict[str, Any]) -> str:
    return str(loc.get("city") or "")


def matches_location(analysis: Analysis, loc: dict[str, Any]) -> bool:
    """Затрагивает ли событие конкретную локацию пользователя."""
    if not analysis.relevant:
        return False

    loc_city = location_city(loc)
    if analysis.city and loc_city and not same_city(analysis.city, loc_city):
        # Регион совпал, город — нет: пропускаем, кроме региональных оповещений
        if not (analysis.scope == "region" and analysis.region and loc.get("region")
                and same_city(analysis.region, str(loc["region"]))):
            return False

    if analysis.is_city_wide:
        return True

    # Адресный уровень: улица (и дом), затем район, затем общегородская авария.
    loc_street = str(loc.get("street") or "")
    loc_house = str(loc.get("house") or "")
    if analysis.streets:
        if not loc_street:
            return _raw_mentions_location(analysis, loc)
        for item in analysis.streets:
            if street_matches(loc_street, item.get("street", "")):
                if house_in_range(loc_house, item.get("houses") or []):
                    return True
        return False

    if analysis.districts:
        loc_district = str(loc.get("district") or "")
        if loc_district:
            return any(district_matches(loc_district, d) for d in analysis.districts)
        return False

    if analysis.scope in ("city", "region"):
        return True

    return False


def _raw_mentions_location(analysis: Analysis, loc: dict[str, Any]) -> bool:
    """Запасной путь для старых локаций без разобранного адреса."""
    name = str(loc.get("name") or "")
    tokens = {w for w in re.findall(r"[а-яёa-z0-9]{4,}", name.lower())}
    if not tokens:
        return False
    haystack = (analysis.raw + " " + " ".join(s.get("street", "") for s in analysis.streets)).lower()
    return any(token in haystack for token in tokens)


def match_locations(analysis: Analysis, locations: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [loc for loc in locations if matches_location(analysis, loc)]


# --------------------------------------------------------------------------
#  Сборка сообщений
# --------------------------------------------------------------------------

def _loc_label(loc: dict[str, Any]) -> str:
    return esc(loc.get("name") or "локация")


def format_locations_header(locations: Sequence[dict[str, Any]], note: str = "") -> str:
    names = ", ".join(_loc_label(loc) for loc in locations)
    suffix = f" <i>({note})</i>" if note else ""
    return f"📍 <b>Совпавшие локации:</b> {names}{suffix}"


def _source_label(analysis: Analysis) -> str:
    label = analysis.source or "источник"
    name = esc(label) if ("." in label or "/" in label) else f"@{esc(label)}"
    # У новости из RSS есть прямая ссылка — делаем заголовок кликабельным.
    if analysis.link:
        return f'<a href="{esc_attr(analysis.link)}">{name}</a>'
    return name


def _event_line(analysis: Analysis) -> str:
    icon = "✅" if analysis.all_clear else SEVERITY_ICONS.get(analysis.severity, "🔵")
    mark = "" if analysis.engine == "ai" else " <i>(без ИИ)</i>"
    line = f"{icon} <b>{_source_label(analysis)}</b>{mark}\n{esc(analysis.text())}"
    if analysis.link:
        line += f'\n🔗 <a href="{esc_attr(analysis.link)}">Читать источник</a>'
    return line


def build_city_alert(
    city: str,
    locations: Sequence[dict[str, Any]],
    events: Sequence[Analysis],
    whitelist_notice: bool = False,
) -> str:
    """Одно сообщение на город: военные и другие общегородские угрозы."""
    titles = {analysis.title() for analysis in events}
    head = f"🚨 <b>ОПАСНОСТЬ — {esc(city or 'город')}</b>"
    lines = [
        head,
        f"<b>{esc(' / '.join(sorted(titles)))}</b>",
        format_locations_header(locations, "весь город"),
        "",
    ]
    lines.extend(_event_line(analysis) for analysis in events)
    if whitelist_notice:
        lines.append("")
        lines.append(WHITELIST_NOTICE)
    return "\n".join(lines)


def build_all_clear(
    city: str,
    locations: Sequence[dict[str, Any]],
    events: Sequence[Analysis],
    whitelist_notice: bool = False,
) -> str:
    """Отбой опасности: спокойный тон, другой сигнал, без слова «ОПАСНОСТЬ»."""
    titles = {analysis.title() for analysis in events}
    lines = [
        f"✅ <b>ОТБОЙ — {esc(city or 'город')}</b>",
        f"<b>{esc(' / '.join(sorted(titles)))}</b> — опасность снята",
        format_locations_header(locations, "весь город"),
        "",
    ]
    lines.extend(_event_line(analysis) for analysis in events)
    if whitelist_notice:
        lines.append("")
        lines.append(ALL_CLEAR_NOTICE)
    return "\n".join(lines)


def build_utility_alert(locations: Sequence[dict[str, Any]], events: Sequence[Analysis], grouped: bool) -> str:
    """Сообщение по ЖКХ/адресным событиям для одной группы локаций."""
    note = "в пределах 1 км" if grouped else ""
    lines = [
        "🛠 <b>ЖКХ и аварии на сетях</b>",
        format_locations_header(locations, note),
        "",
    ]
    lines.extend(_event_line(analysis) for analysis in events)
    return "\n".join(lines)


def cluster_title(cluster: Sequence[dict[str, Any]]) -> str:
    """Заголовок сводки погоды: одна локация или список объединённых."""
    names = ", ".join(_loc_label(loc) for loc in cluster)
    if len(cluster) > 1:
        return f"📍 <b>{names}</b> <i>(в пределах 1 км)</i>"
    return f"📍 <b>{names}</b>"


# --------------------------------------------------------------------------
#  Группировка оповещений для одного пользователя
# --------------------------------------------------------------------------

def _city_of(analysis: Analysis, locations: Sequence[dict[str, Any]], fallback: str) -> tuple[str, str]:
    """Ключ группировки по городу и его отображаемое имя."""
    for loc in locations:
        city = str(loc.get("city") or "")
        if city:
            return normalize_city(city), city
    city = analysis.city or fallback
    return normalize_city(city), city or "город"


def plan_alerts(
    locations: Sequence[dict[str, Any]],
    settings: dict[str, Any],
    analyses: Sequence[Analysis],
    radius_m: float = 1000.0,
    default_city: str = "",
) -> list[tuple[str, str]]:
    """Собирает готовые сообщения для пользователя.

    Правила:
      * военные и другие общегородские угрозы — одно сообщение на город
        со списком всех совпавших локаций в нём;
      * ЖКХ и адресные события — отдельное сообщение на группу локаций;
      * локации ближе radius_m объединяются в одну группу.

    Возвращает список пар («city» | «utility», текст сообщения).
    """
    if not locations:
        return []

    enabled = {key for key, value in (settings or {}).items() if value}
    warn_about_whitelist = "whitelist" in enabled
    clusters = cluster_locations(locations, radius_m)

    city_buckets: dict[str, dict[str, Any]] = {}
    cluster_buckets: dict[int, dict[str, Any]] = {}

    for analysis in analyses:
        if not analysis.relevant or not (set(analysis.categories) & enabled):
            continue
        matched = match_locations(analysis, locations)
        if not matched:
            continue

        if analysis.is_city_wide:
            key, label = _city_of(analysis, matched, default_city)
            # Отбой не должен смешиваться с действующей тревогой в одном сообщении.
            bucket_key = f"{key}:clear" if analysis.all_clear else key
            bucket = city_buckets.setdefault(
                bucket_key,
                {"city": label, "locs": {}, "events": [], "all_clear": analysis.all_clear},
            )
            bucket["events"].append(analysis)
            for loc in matched:
                bucket["locs"][loc.get("id") or loc.get("name")] = loc
            continue

        matched_ids = {id(loc) for loc in matched}
        for index, cluster in enumerate(clusters):
            inside = [loc for loc in cluster if id(loc) in matched_ids]
            if not inside:
                continue
            bucket = cluster_buckets.setdefault(
                index, {"size": len(cluster), "locs": {}, "events": []}
            )
            bucket["events"].append(analysis)
            for loc in inside:
                bucket["locs"][loc.get("id") or loc.get("name")] = loc

    messages: list[tuple[str, str]] = []
    for bucket in city_buckets.values():
        military = any("bpla" in analysis.categories for analysis in bucket["events"])
        notice = military and warn_about_whitelist
        locs = list(bucket["locs"].values())
        if bucket["all_clear"]:
            messages.append(
                ("clear", build_all_clear(bucket["city"], locs, bucket["events"], notice))
            )
        else:
            messages.append(
                ("city", build_city_alert(bucket["city"], locs, bucket["events"], notice))
            )
    for bucket in cluster_buckets.values():
        messages.append(
            (
                "utility",
                build_utility_alert(
                    list(bucket["locs"].values()), bucket["events"], grouped=bucket["size"] > 1
                ),
            )
        )
    return messages
