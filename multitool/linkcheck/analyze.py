"""Разбор ссылки на признаки мошенничества без обращения к сети.

Результат — список признаков с весом и кратким пояснением.
Сумма весов даёт вердикт: 0–14 = «признаков не найдено»,
15–34 = «следует обратить внимание», 35–59 = «подозрительно»,
60+ = «опасно». Ни один признак не даёт гарантии: сайт может
быть подозрительным в одном аспекте и полностью честным в другом.

Модуль нарочно не знает ни о Telegram, ни о «Радаре»: чистая функция
от строки, тестируемая без сети и без бота.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

SCORE_MAX = 100

SIGNALS = [
    ("scheme_http", 20, "незащищённое HTTP"),
    ("scheme_suspicious", 35, "опасная схема"),
    ("executable_scheme", 60, "исполняемая схема"),
    ("userinfo", 45, "учётные данные перед @"),
    ("ip_literal", 10, "IP вместо домена"),
    ("punycode", 15, "пуньякод (идн-домен)"),
    ("mixed_script", 25, "смешанные алфавиты"),
    ("homograph_brand", 70, "подмена букв с имитацией бренда"),
    ("brand_wrong_domain", 40, "бренд в домене, но не в реестре"),
    ("brand_path", 12, "бренд в пути"),
    ("typosquat", 30, "подобный бренду домен"),
    ("suspicious_tld", 5, "подозрительная зона"),
    ("subdomain_depth", 6, "глубокая вложенность"),
    ("hyphen_label", 3, "дефис в метке домена"),
    ("shortener", 5, "сокращатель ссылки"),
    ("nonstandard_port", 2, "нестандартный порт"),
    ("bait_word", 8, "слова-призыв в пути"),
    ("executable_ext", 15, "исполняемый файл"),
    ("double_ext", 30, "двойное расширение"),
    ("many_escapes", 4, "много кодов экранирования"),
    ("trailing_dot", 3, "точка в конце домена"),
    ("zero_width", 20, "невидимые символы"),
    ("digits_in_brand", 6, "цифры в имени домена"),
    ("free_hosting", 4, "свободный хостинг"),
]

VERDICT = {
    0: "ok",
    15: "attention",
    35: "suspect",
    60: "danger",
}

MULTI_SUFFIXES = frozenset({
    "co.uk", "ac.uk", "gov.uk", "org.uk", "edu.uk", "ne.uk", "lc.uk",
    "com.au", "net.au", "org.au", "gov.au", "edu.au", "id.au",
    "com.br", "net.br", "org.br", "gov.br", "edu.br",
    "com.ru", "net.ru", "org.ru", "pp.ru", "info.ru", "srv.ru",
    "su", "tj", "ws", "cc", "tv", "co", "mobi", "name",
})

SUSPICIOUS_TLD = frozenset({
    "tk", "ml", "ga", "cf", "gq", "zip", "top", "xyz", "click", "work",
    "loan", "link", "ru.name",
})

URL_SHORTENERS = frozenset({
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "buff.ly",
    "rebrandly.com", "lnkd.in", "wp.me", "cutt.ly", "shrt.co",
    "soo.gd", "adf.ly", "y2u.be", "b2n.me", "clck.ru",
})

BAIT_WORDS = frozenset({
    "login", "signin", "sign-in", "sign_in",
    "verify", "verification", "verify-account",
    "secure", "security", "secure-account",
    "account", "update", "reset", "reset-password",
    "password", "recovery", "wallet", "cryptocurrency",
    "bitcoin", "ethereum", "gift", "prize", "bonus", "cashback",
    "free", "scan", "phishing", "virus", "trojan",
    "captcha", "auth", "token",
    "вход", "авторизация", "подтверждение", "пароль",
    "деньги", "зарплата", "подарок", "бонус", "кешбэк",
    "кошелёк", "криптовалюта", "биткоин", "эфириум",
    "скан", "фишинг", "вирус", "троянский",
    "капча", "аутентификация", "токен",
})

EXECUTABLE_EXT = frozenset({
    "exe", "scr", "bat", "cmd", "msi", "vbs", "vbe", "jar", "com",
    "pif", "vb", "js", "jse", "ps1", "hta", "cpl", "run",
})

CONFUSER = {
    "а": "a", "б": "b", "в": "b", "г": "r", "д": "g", "е": "e", "ё": "e",
    "ж": "zh", "з": "3", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
    "н": "h", "о": "o", "п": "n", "р": "p", "с": "c", "т": "t", "у": "y",
    "ф": "f", "х": "x", "ц": "u", "ч": "4", "ш": "w", "щ": "w", "ъ": "",
    "ы": "bi", "ь": "", "э": "e", "ю": "io", "я": "ya",
    "ѕ": "s", "і": "i", "ї": "i", "ј": "j", "љ": "lj", "њ": "nj",
    "ћ": "c", "џ": "dz", "ґ": "g",
    "α": "a", "ε": "e", "κ": "k", "ν": "n",
    "ο": "o", "ρ": "p", "σ": "s", "τ": "t", "υ": "u", "ω": "o",
}

DIGIT_LETTER = {"0": "o", "4": "a", "3": "e", "5": "s", "6": "g", "8": "b", "9": "g"}

BRANDS: dict[str, list[str]] = {}
for block in [
    {"sberbank": ["sberbank.ru", "sber.ru", "sb.ru", "sberbank.com"]},
    {"tinkoff": ["tinkoff.ru"]},
    {"alfa-bank": ["alfabank.ru", "alfa-bank.ru"]},
    {"vtb": ["vtb.ru"]},
    {"gosuslugi": ["gosuslugi.ru"]},
    {"vk": ["vk.com", "vkontakte.ru"]},
    {"telegram": ["telegram.org", "telegram.com"]},
    {"youtube": ["youtube.com"]},
    {"facebook": ["facebook.com"]},
    {"instagram": ["instagram.com"]},
    {"twitter": ["twitter.com", "x.com"]},
    {"linkedin": ["linkedin.com"]},
    {"paypal": ["paypal.com"]},
    {"apple": ["apple.com"]},
    {"microsoft": ["microsoft.com"]},
    {"google": ["google.com"]},
    {"yandex": ["yandex.ru", "ya.ru"]},
    {"ozon": ["ozon.ru"]},
    {"wildberries": ["wildberries.ru"]},
    {"aliexpress": ["aliexpress.com"]},
    {"amazon": ["amazon.com"]},
    {"ebay": ["ebay.com"]},
    {"visa": ["visa.com"]},
    {"mastercard": ["mastercard.com"]},
]:
    BRANDS.update(block)

ALL_LEGIT = frozenset(d for v in BRANDS.values() for d in v)


@dataclass(slots=True)
class Signal:
    code: str
    weight: int
    title: str
    detail: str | None = None

    @property
    def verdict(self) -> str:
        if self.weight <= 14:
            return "ok"
        if self.weight <= 34:
            return "attention"
        if self.weight <= 59:
            return "suspect"
        return "danger"


@dataclass(slots=True)
class NetResult:
    success: bool = False
    final_url: str = ""
    chain: list[str] = field(default_factory=list)
    domain_age_days: int | None = None
    cert_valid_days: int | None = None
    threats: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Verdict:
    url: str
    signals: list[Signal] = field(default_factory=list)
    net: NetResult | None = None

    @property
    def score(self) -> int:
        return min(sum(s.weight for s in self.signals), SCORE_MAX)

    @property
    def level(self) -> str:
        for threshold, label in reversed(VERDICT.items()):
            if self.score >= threshold:
                return label
        return "ok"


def _deconfuse(text: str) -> str:
    """Сводит похожие символы к латинице: цифры и чужие алфавиты."""
    out = []
    for ch in text:
        out.append(CONFUSER.get(ch, DIGIT_LETTER.get(ch, ch)))
    return "".join(out)


def _norm(text: str) -> str:
    """Нормализованный вид домена: только a-z0-9 после деоцифровки."""
    return re.sub(r"[^a-z0-9]", "", _deconfuse(text))


def _is_ip(host: str) -> bool:
    try:
        import ipaddress
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _is_puny(host: str) -> bool:
    return any(label.lower().startswith("xn--") for label in host.split("."))


def _mixed_script(host: str) -> bool:
    scripts = set()
    for ch in host.lower():
        name = unicodedata.name(ch, "")
        if "LATIN" in name:
            scripts.add("latin")
        elif "CYRILLIC" in name:
            scripts.add("cyrillic")
        elif "GREEK" in name:
            scripts.add("greek")
    return len(scripts) > 1


def _extract_registrable(host: str) -> tuple[str, str]:
    host = host.lower().rstrip(".")
    labels = host.split(".")
    if len(labels) == 2:
        return (labels[0], labels[1])
    if len(labels) <= 1:
        return (host, "")
    s2 = ".".join(labels[-2:])
    s3 = ".".join(labels[-3:])
    if s3 in MULTI_SUFFIXES:
        return (".".join(labels[:-3]) or "", s3)
    if s2 in MULTI_SUFFIXES:
        return (".".join(labels[:-2]), s2)
    if host.endswith(".ru") or host.endswith(".ua"):
        return (".".join(labels[:-1]), labels[-1])
    return (".".join(labels[:-2]), s2)


def _is_executable(path: str) -> bool:
    segments = path.split("/")
    for seg in segments:
        ext = seg.rsplit(".", 1)[-1].lower() if "." in seg else ""
        if ext in EXECUTABLE_EXT:
            return True
    return False


def _is_double_ext(path: str) -> bool:
    segments = path.split("/")
    for seg in segments:
        parts = seg.rsplit(".", 1)
        if len(parts) == 2 and parts[-1].lower() in EXECUTABLE_EXT and "." in parts[0]:
            return True
    return False


def analyze(url: str) -> Verdict:
    v = Verdict(url=url)
    raw = url.strip()

    if re.search(r"[\u200b\u200c\u200d\u200e\u200f\ufeff]", raw):
        v.signals.append(Signal("zero_width", 20, "невидимый символ в ссылке"))
    if raw.rstrip().endswith(".") or raw.endswith("\u2026"):
        v.signals.append(Signal("trailing_dot", 3, "точка в конце домена"))

    if raw.startswith("javascript:") or raw.startswith("data:") or raw.startswith("file:"):
        v.signals.append(Signal("executable_scheme", 60, "исполняемая схема"))
        return v

    if "://" not in raw and re.match(r'^[a-z0-9.-]+\.[a-z]{2,}', raw, re.I):
        raw = "http://" + raw
        v.signals.append(Signal("scheme_http", 20, "незащищённое HTTP"))

    match = re.match(r'^([a-z][a-z0-9+.-]*):(?:/{2,3})?([^/]*)(/.*)?$', raw, re.I | re.S)
    if not match:
        return v

    scheme, host_part, path_part = match.group(1), match.group(2), match.group(3) or ""
    scheme = scheme.lower() + ":"

    if scheme not in ("http:", "https:", "ftp:", "mailto:", "tel:", "whatsapp:", "tg:"):
        v.signals.append(Signal("scheme_suspicious", 35, f"неизвестная схема: {scheme}"))
    if scheme == "http:":
        v.signals.append(Signal("scheme_http", 20, "незащищённое HTTP"))

    if "@" in host_part:
        cred = host_part.split("@")[0]
        host_part = host_part.split("@")[1]
        v.signals.append(Signal("userinfo", 45, f"учётные данные: {cred}"))

    if not host_part:
        return v

    host_clean = host_part.split(":")[0].rstrip(".")

    if _is_ip(host_clean):
        v.signals.append(Signal("ip_literal", 10, f"IP: {host_clean}"))
    elif _is_puny(host_clean):
        v.signals.append(Signal("punycode", 15, "пуньякод"))

    if _mixed_script(host_clean):
        v.signals.append(Signal("mixed_script", 25, "смешанные алфавиты"))
        confusable = _deconfuse(host_clean)
        for brand in BRANDS:
            if brand in confusable and brand not in host_clean:
                v.signals.append(Signal("homograph_brand", 70, f"подмена букв с имитацией {brand}"))
                break

    reg_label, tld = _extract_registrable(host_clean)
    reg_lower = reg_label.lower()

    for brand, legit in BRANDS.items():
        if brand in reg_lower:
            is_legit = any(host_clean == d or host_clean.endswith("." + d) for d in legit)
            if not is_legit:
                v.signals.append(Signal("brand_wrong_domain", 40, f"бренд {brand}, домен не из списка"))

    if tld.lstrip(".") in SUSPICIOUS_TLD:
        v.signals.append(Signal("suspicious_tld", 5, f"подозрительная зона: {tld}"))

    labels = reg_label.split("-")
    if len(labels) > 1 and any(len(l) > 4 for l in labels):
        v.signals.append(Signal("hyphen_label", 3, "дефис в метке домена"))

    host_count = len(host_clean.split("."))
    if host_count > 4:
        v.signals.append(Signal("subdomain_depth", 6, "глубокая вложенность домена"))

    full = host_clean
    for short in URL_SHORTENERS:
        if short in full:
            v.signals.append(Signal("shortener", 5, f"сокращатель: {short}"))
            break

    if path_part:
        path_lower = path_part.lower()
        for brand in BRANDS:
            if brand in path_lower and brand not in ALL_LEGIT:
                v.signals.append(Signal("brand_path", 12, f"бренд {brand} в пути"))
                break

        for keyword in BAIT_WORDS:
            if keyword in path_lower or keyword in full:
                v.signals.append(Signal("bait_word", 8, f"слово-призыв: {keyword}"))
                break

        if _is_double_ext(path_lower):
            v.signals.append(Signal("double_ext", 30, "двойное расширение файла"))
        if _is_executable(path_lower):
            v.signals.append(Signal("executable_ext", 15, "исполняемый файл"))

    percent = len(re.findall(r"%[0-9a-fA-F]{2}", url))
    if percent > 3:
        v.signals.append(Signal("many_escapes", 4, f"{percent} закодированных октетов"))

    domain_norm = _norm(reg_lower)
    for brand, legit in BRANDS.items():
        brand_norm = _norm(brand)
        if levenshtein(domain_norm, brand_norm) <= 2 and domain_norm != brand_norm:
            if f"{reg_label}.{tld}" not in legit:
                v.signals.append(Signal("typosquat", 30, f"подобно бренду: {brand}"))
                break

    for ch in reg_label:
        if ch.isdigit():
            v.signals.append(Signal("digits_in_brand", 6, "цифры в имени домена"))
            break

    return v


def levenshtein(a: str, b: str, limit: int = 2) -> int:
    la, lb = len(a), len(b)
    if la < lb:
        a, b, la, lb = b, a, lb, la
    prev = list(range(lb + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (ca != cb)))
        prev = curr
        if min(prev) > limit:
            return limit + 1
    return prev[-1]
