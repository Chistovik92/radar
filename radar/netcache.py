"""Кэш ответов внешних служб.

Пункт 4 раздела 4.8: экономия обращений к сети. Замер 4.7.6.5 показал,
что цикл почти целиком уходит на ожидание сети, — а часть этих ожиданий
вообще не нужна, потому что мы спрашиваем одно и то же по нескольку раз.

Где именно повторы:

* **погода.** Она запрашивается на каждую группу локаций каждого
  пользователя. Соседи по дому, подписанные на одну улицу, дают
  одинаковые координаты с точностью до сотых — и столько же одинаковых
  запросов к Open-Meteo подряд;
* **геокодирование.** Nominatim разрешает **один запрос в секунду**, и это
  жёстче любого нашего таймаута. Повторный разбор тех же координат —
  секунда, отнятая у всего остального.

Устройство намеренно простое: словарь со временем жизни и верхней
границей размера. Вытеснитель по частоте здесь был бы дороже пользы —
записей сотни, а не миллионы, и живут они минутами.

Важно: кэш держит **сырой ответ**, а не разобранный. Разбор зависит
от языка пользователя, и кэшировать его значило бы держать по копии
на язык — при том что сетевой запрос у них общий.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import time
from typing import Any


class TTLCache:
    """Словарь, забывающий записи по времени.

    Не потокобезопасен намеренно: всё обращается к нему из одного цикла
    событий, а блокировка ради воображаемых потоков только замедлила бы.
    """

    def __init__(self, ttl: float, limit: int = 500) -> None:
        self.ttl = float(ttl)
        self.limit = max(1, int(limit))
        self._items: dict[Any, tuple[float, Any]] = {}
        self.hits = 0
        self.misses = 0

    def get(self, key: Any) -> Any | None:
        found = self._items.get(key)
        if found is None:
            self.misses += 1
            return None

        stamp, value = found
        if time.monotonic() - stamp > self.ttl:
            # Просрочку убираем сразу: иначе она занимала бы место
            # до ближайшей чистки и искажала счётчики.
            self._items.pop(key, None)
            self.misses += 1
            return None

        self.hits += 1
        return value

    def put(self, key: Any, value: Any) -> None:
        if len(self._items) >= self.limit:
            self._evict()
        self._items[key] = (time.monotonic(), value)

    def _evict(self) -> None:
        """Освобождает место: сначала просроченное, иначе самое старое."""
        now = time.monotonic()
        stale = [key for key, (stamp, _) in self._items.items()
                 if now - stamp > self.ttl]
        if stale:
            for key in stale:
                self._items.pop(key, None)
            return

        # Ничего не протухло — выкидываем самую старую запись. Одну,
        # а не половину словаря: очередной вызов вытеснит следующую.
        oldest = min(self._items, key=lambda key: self._items[key][0])
        self._items.pop(oldest, None)

    def clear(self) -> None:
        self._items.clear()
        self.hits = 0
        self.misses = 0

    def __len__(self) -> int:
        return len(self._items)

    @property
    def ratio(self) -> float:
        """Доля попаданий. Ноль обращений — ноль, а не деление на ноль."""
        total = self.hits + self.misses
        return self.hits / total if total else 0.0

    def stats(self) -> dict[str, Any]:
        return {
            "size": len(self._items),
            "hits": self.hits,
            "misses": self.misses,
            "ratio": round(self.ratio, 3),
        }


def round_point(lat: float, lon: float, digits: int = 2) -> tuple[float, float]:
    """Координаты с округлением — ключ для кэша погоды и адресов.

    Две цифры после запятой — это около 1.1 км по широте. Ровно тот
    масштаб, на котором система и так склеивает локации в одну группу
    (`CLUSTER_RADIUS_M` = 1000), поэтому огрубление не теряет ничего,
    чего система не огрубила бы сама.
    """
    try:
        return (round(float(lat), digits), round(float(lon), digits))
    except (TypeError, ValueError):
        return (0.0, 0.0)
