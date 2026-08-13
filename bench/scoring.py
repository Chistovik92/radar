"""Оценка ответа модели против эталонной разметки.

Метрики подобраны под то, что реально влияет на работу «Радара»:
корректность категорий, точность извлечения улиц и домов, отсутствие
ложных срабатываний на шуме и — отдельно — способность разбирать
военные сообщения без фильтрации.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from cases import Case

CATEGORIES = ("jkh", "bpla", "mchs", "whitelist")

STREET_TYPES = {
    "улица", "ул", "проспект", "пр", "прт", "переулок", "пер", "бульвар", "бр",
    "шоссе", "ш", "площадь", "пл", "проезд", "тупик", "набережная", "наб", "мкр",
    "микрорайон", "им", "имени",
}

_WORD = re.compile(r"[а-яёa-z0-9]+")

def _words(text: str) -> list[str]:
    return _WORD.findall((text or "").lower().replace("ё", "е"))


def norm_street(name: str) -> str:
    return " ".join(word for word in _words(name) if word not in STREET_TYPES).strip()


def norm_house(house: str) -> str:
    raw = (house or "").lower().replace("ё", "е").replace(" ", "")
    match = re.search(r"\d+\s*[а-я]?(?:-\d+)?(?:/\d+)?", raw)
    return match.group(0) if match else ""


def expand_houses(items) -> set[str]:
    """«12-20» → {12, 13, …, 20}; одиночные номера остаются как есть."""
    result: set[str] = set()
    for item in items or []:
        value = norm_house(str(item))
        if not value:
            continue
        span = re.fullmatch(r"(\d+)-(\d+)", value)
        if span:
            low, high = sorted((int(span.group(1)), int(span.group(2))))
            if high - low <= 200:
                result.update(str(number) for number in range(low, high + 1))
                continue
        result.add(value)
    return result


def parse_json(raw: str) -> dict | None:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", (raw or "").strip(), flags=re.S)
    match = re.search(r"\{.*\}", cleaned, re.S)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def f1(predicted: set[str], expected: set[str]) -> float:
    if not predicted and not expected:
        return 1.0
    if not predicted or not expected:
        return 0.0
    hits = len(predicted & expected)
    if not hits:
        return 0.0
    precision = hits / len(predicted)
    recall = hits / len(expected)
    return 2 * precision * recall / (precision + recall)


@dataclass
class Score:
    ident: str
    parsed: bool = False
    has_address: bool = False   # у эталона есть улицы или дома
    is_noise: bool = False      # эталон: сообщение не должно оповещать
    category_f1: float = 0.0
    exact_categories: bool = False
    scope_ok: bool = False
    street_f1: float = 0.0
    house_f1: float = 0.0
    false_alarm: bool = False    # шум признан значимым
    missed: bool = False         # значимое признано шумом
    censored: bool = False       # военный кейс срезан
    notes: list[str] = field(default_factory=list)

    @property
    def total(self) -> float:
        """Итог 0..1: категории важнее всего, затем адреса и масштаб.

        Веса распределяются по эталону, а не по ответу модели: иначе
        промах по адресу вознаграждался бы переносом веса на категории.
        """
        if not self.parsed:
            return 0.0

        # Шум: единственное, что важно — не поднять ложную тревогу.
        if self.is_noise:
            return 0.0 if self.false_alarm else 1.0

        score = 0.5 * self.category_f1 + 0.15 * self.scope_ok
        if self.has_address:
            score += 0.2 * self.street_f1 + 0.15 * self.house_f1
        else:
            # адресов в эталоне нет — вес уходит на категории
            score += 0.35 * self.category_f1
        if self.missed:
            score -= 0.35
        return max(0.0, min(1.0, score))


def evaluate(case: Case, raw_text: str) -> Score:
    score = Score(
        ident=case.ident,
        has_address=bool(case.streets or case.houses),
        is_noise=not case.categories,
    )
    payload = parse_json(raw_text)
    if payload is None:
        score.notes.append("не удалось разобрать JSON")
        if case.sensitive:
            score.censored = True
        return score

    score.parsed = True

    relevant = bool(payload.get("relevant"))
    predicted = {
        str(item) for item in (payload.get("categories") or []) if str(item) in CATEGORIES
    }
    if not relevant:
        predicted = set()
    expected = set(case.categories)

    score.category_f1 = f1(predicted, expected)
    score.exact_categories = predicted == expected

    if expected and not predicted:
        score.missed = True
        if case.sensitive:
            score.censored = True
            score.notes.append("военная тема отброшена как незначимая")
    if not expected and predicted:
        score.false_alarm = True
        score.notes.append(f"ложное срабатывание: {', '.join(sorted(predicted))}")

    score.scope_ok = str(payload.get("scope", "")).lower() == case.scope

    streets_raw = payload.get("streets") or []
    predicted_streets: set[str] = set()
    predicted_houses: set[str] = set()
    for item in streets_raw:
        if isinstance(item, str):
            predicted_streets.add(norm_street(item))
        elif isinstance(item, dict):
            if item.get("street"):
                predicted_streets.add(norm_street(str(item["street"])))
            predicted_houses |= expand_houses(item.get("houses"))
    predicted_streets.discard("")

    expected_streets = {norm_street(name) for name in case.streets} - {""}
    expected_houses = expand_houses(case.houses)

    if expected_streets or predicted_streets:
        score.street_f1 = f1(predicted_streets, expected_streets)
    if expected_houses or predicted_houses:
        score.house_f1 = f1(predicted_houses, expected_houses)

    return score
