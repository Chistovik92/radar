"""Общая подмена Docker Engine API для офлайн-тестов.

Вынесено из `tests/test_updater.py` в 4.9.8.4, когда `tests/test_rustdesk.py`
понадобился ровно тот же приём — без него пришлось бы держать две копии
одного и того же класса и чинить обе при любой правке.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import json


class FakeResponse:
    """Одна из немногих строк реального ответа Docker Engine API —
    статус, JSON, текст или сырые байты (для мультиплексированного
    потока `docker exec`)."""

    def __init__(self, status: int, body="") -> None:
        self.status = status
        self._body = body

    async def json(self):
        return self._body if isinstance(self._body, (dict, list)) else {}

    async def text(self) -> str:
        if isinstance(self._body, bytes):
            return self._body.decode("utf-8", errors="replace")
        if isinstance(self._body, str):
            return self._body
        return json.dumps(self._body, ensure_ascii=False)

    async def read(self) -> bytes:
        if isinstance(self._body, bytes):
            return self._body
        if isinstance(self._body, str):
            return self._body.encode("utf-8")
        return b""

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False


class FakeSession:
    """Подменяет aiohttp.ClientSession: без сокета Docker и без сети.

    `routes` — {(метод, кусок пути в конце URL): FakeResponse}, сверяется
    по суффиксу, потому что реальный код всегда обращается к одному хосту
    (`API`), различаются только пути.
    """

    def __init__(self, routes: dict[tuple[str, str], FakeResponse]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, str]] = []

    def _resolve(self, method: str, url: str) -> FakeResponse:
        for (want_method, suffix), response in self.routes.items():
            if want_method == method and url.endswith(suffix):
                return response
        raise AssertionError(f"неожиданный запрос: {method} {url}")

    def get(self, url: str, **kwargs) -> FakeResponse:
        self.calls.append(("GET", url))
        return self._resolve("GET", url)

    def post(self, url: str, **kwargs) -> FakeResponse:
        self.calls.append(("POST", url))
        return self._resolve("POST", url)

    def delete(self, url: str, **kwargs) -> FakeResponse:
        self.calls.append(("DELETE", url))
        return self._resolve("DELETE", url)

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False
