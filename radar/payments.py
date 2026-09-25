"""Платёжный слой со сменным провайдером (с 5.0.2).

Пункт 5 блока 5.0: продажи не должны знать, кто принимает деньги.
Интерфейс один — выставить счёт и узнать его состояние, — а провайдер
выбирается настройкой `PAY_PROVIDER` и меняется, не трогая продажи.

Провайдеры:

* **manual** — денег бот не принимает вовсе. Человек платит так, как
  договорился с суперадминистратором, а тот подтверждает оплату кнопкой.
  Работает без регистрации где-либо и остаётся запасным путём всегда;
* **cryptopay** — Crypto Pay API (@CryptoBot): счёт создаётся запросом,
  человек платит внутри Telegram, бот узнаёт об оплате, спросив состояние
  счёта. Регистрации продавца не требует — ровно поэтому он первый
  в дорожной карте. Формат сверен с исходниками клиента `aiocryptopay`
  (официальная документация help.crypt.bot из среды разработки
  недоступна): `GET /api/createInvoice` и `/api/getInvoices` с заголовком
  `Crypto-Pay-API-Token`, ответ `{"ok": true, "result": …}`, ссылка
  на оплату — `bot_invoice_url`, состояния счёта — active, paid, expired.

⚠️ **Чего код не проверяет и проверить не может**: комиссию Crypto Pay,
лимиты и условия вывода. Они менялись, и вписывать их по памяти карта
запрещает; смотреть — в самом @CryptoBot до включения продаж.

Webhook Crypto Pay (`verify_signature`) подготовлен, но не подключён:
бот работает опросом Telegram, а своего входящего адреса у него нет.
Оплата подтверждается кнопкой «Я оплатил» — бот спрашивает состояние
счёта у провайдера сам. Токен провайдера в журнал не пишется.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets as pysecrets
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("radar.payments")

TIMEOUT = 20

ACTIVE = "active"
PAID = "paid"
EXPIRED = "expired"

MAINNET = "https://pay.crypt.bot"
TESTNET = "https://testnet-pay.crypt.bot"


class PaymentError(Exception):
    """Отказ провайдера, понятный человеку. Токенов в тексте нет."""


@dataclass(frozen=True)
class Invoice:
    """Счёт у провайдера."""

    id: str
    url: str            # куда идти платить; пусто у ручного провайдера
    amount: float
    currency: str
    status: str = ACTIVE


class Provider:
    """Общий интерфейс провайдера."""

    kind = ""
    title = ""
    # Подтверждает ли оплату человек (суперадминистратор), а не провайдер.
    manual = False

    def problems(self) -> list[str]:
        return []

    async def create_invoice(self, amount: float, currency: str, description: str,
                             payload: str, expires_in: int = 3600) -> Invoice:
        raise NotImplementedError

    async def status(self, invoice_id: str) -> str:
        raise NotImplementedError

    async def cancel(self, invoice_id: str) -> bool:
        """Погасить счёт у провайдера, чтобы по нему нельзя было заплатить.
        False — не вышло (счёт уже оплачен, провайдер недоступен)."""
        return True


class ManualProvider(Provider):
    """Оплату подтверждает суперадминистратор. Счёт — только номер заказа."""

    kind = "manual"
    title = "подтверждение суперадминистратором"
    manual = True

    async def create_invoice(self, amount: float, currency: str, description: str,
                             payload: str, expires_in: int = 3600) -> Invoice:
        return Invoice(pysecrets.token_hex(6), "", amount, currency)

    async def status(self, invoice_id: str) -> str:
        # Состояние ручного счёта знает только заказ: его меняет кнопка
        # суперадминистратора, а не провайдер.
        return ACTIVE


class CryptoPayProvider(Provider):
    """Crypto Pay API (@CryptoBot, он же @send)."""

    kind = "cryptopay"
    title = "Crypto Pay (@CryptoBot)"

    def __init__(self, token: str, *, testnet: bool = False,
                 assets: str = "") -> None:
        self.token = (token or "").strip()
        self.base = TESTNET if testnet else MAINNET
        self.assets = ",".join(item.strip().upper() for item in (assets or "").split(",")
                               if item.strip())

    def problems(self) -> list[str]:
        return [] if self.token else ["токен Crypto Pay (PAY_CRYPTOPAY_TOKEN)"]

    async def _call(self, method: str, params: dict[str, Any]) -> Any:
        import aiohttp

        if self.problems():
            raise PaymentError("Crypto Pay не настроен: " + ", ".join(self.problems()) + ".")
        clean = {key: value for key, value in params.items() if value not in (None, "")}
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=TIMEOUT),
            ) as session:
                async with session.get(f"{self.base}/api/{method}", params=clean,
                                       headers={"Crypto-Pay-API-Token": self.token}) as response:
                    text = await response.text()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            # Общий предел времени aiohttp бросает asyncio.TimeoutError, а не
            # ClientError: до 5.6.2 зависший Crypto Pay ронял обработчик
            # вместо понятного «попробуйте позже».
            log.warning("Crypto Pay недоступен: %s", type(exc).__name__)
            raise PaymentError("Crypto Pay не отвечает — попробуйте позже.")
        return parse_response(text)

    async def create_invoice(self, amount: float, currency: str, description: str,
                             payload: str, expires_in: int = 3600) -> Invoice:
        result = await self._call("createInvoice", {
            "currency_type": "fiat",
            "fiat": currency.upper(),
            "amount": f"{float(amount):.2f}",
            "accepted_assets": self.assets,
            "description": description[:1024],
            "payload": payload[:4096],
            "expires_in": int(expires_in),
        })
        return invoice_from(result, currency)

    async def status(self, invoice_id: str) -> str:
        result = await self._call("getInvoices", {"invoice_ids": str(invoice_id)})
        items = result.get("items") if isinstance(result, dict) else result
        for item in items or []:
            if str(item.get("invoice_id")) == str(invoice_id):
                return str(item.get("status") or ACTIVE)
        raise PaymentError("Crypto Pay не нашёл счёт.")

    async def cancel(self, invoice_id: str) -> bool:
        # `deleteInvoice` — как в aiocryptopay (`delete_invoice`).
        try:
            return bool(await self._call("deleteInvoice", {"invoice_id": str(invoice_id)}))
        except PaymentError as exc:
            log.warning("Crypto Pay: счёт не удалён: %s", exc)
            return False


def parse_response(text: str) -> Any:
    """Ответ Crypto Pay: {"ok": true, "result": …} или {"ok": false, "error": …}."""
    try:
        payload = json.loads(text)
    except ValueError:
        raise PaymentError("Crypto Pay ответил не JSON.")
    if not isinstance(payload, dict):
        raise PaymentError("Crypto Pay ответил непонятно.")
    if not payload.get("ok"):
        error = payload.get("error") or {}
        name = error.get("name") if isinstance(error, dict) else str(error)
        raise PaymentError(f"Crypto Pay отказал: {name or 'без пояснения'}.")
    return payload.get("result")


def invoice_from(result: Any, currency: str) -> Invoice:
    if not isinstance(result, dict) or not result.get("invoice_id"):
        raise PaymentError("Crypto Pay не вернул счёт.")
    url = (result.get("bot_invoice_url") or result.get("mini_app_invoice_url")
           or result.get("pay_url") or "")
    return Invoice(str(result["invoice_id"]), str(url),
                   float(result.get("amount") or 0), currency,
                   str(result.get("status") or ACTIVE))


def verify_signature(token: str, body: bytes, signature: str) -> bool:
    """Подпись webhook Crypto Pay: HMAC-SHA256 тела, ключ — SHA-256 токена."""
    key = hashlib.sha256((token or "").encode()).digest()
    expected = hmac.new(key, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, (signature or "").strip())


def _setting(key: str) -> str:
    from . import secrets

    return str(secrets.get(key) or "").strip()


def provider() -> Provider:
    """Провайдер из настроек. Незнакомое или пустое имя — ручной."""
    kind = _setting("PAY_PROVIDER").lower()
    if kind == "cryptopay":
        return CryptoPayProvider(_setting("PAY_CRYPTOPAY_TOKEN"),
                                 testnet=_setting("PAY_CRYPTOPAY_TESTNET") in ("1", "true", "yes"),
                                 assets=_setting("PAY_CRYPTOPAY_ASSETS"))
    return ManualProvider()
