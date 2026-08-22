"""Новостные подборки: тематики, подписки, сборка сообщения.

Отличие от оповещений принципиальное. Оповещение означает «происходит
сейчас» и приходит немедленно; подборка — спокойное чтение в выбранное
время. Смешивать их нельзя: если тревожный сигнал начнёт соседствовать
с пересказом городских новостей, люди перестанут реагировать на оба.

Это единственная платная возможность в системе. Всё, что касается
безопасности — оповещения об угрозах, ЖКХ, погода, SOS, — остаётся
бесплатным навсегда.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from . import roles
from .textutils import esc, esc_attr

log = logging.getLogger("radar.digest")

FREE_TOPICS = 1          # сколько тематик доступно без подписки
MAX_ITEMS_PER_TOPIC = 6
DEFAULT_TIMES = ("08:30", "19:30")


@dataclass(frozen=True)
class Topic:
    key: str
    title: str
    icon: str
    description: str
    keywords: tuple[str, ...] = ()


TOPICS: tuple[Topic, ...] = (
    Topic("city", "Город и власть", "🏛",
          "Решения администрации, благоустройство, бюджет.",
          ("администрация", "мэр", "губернатор", "бюджет", "благоустройств",
           "депутат", "постановлен")),
    Topic("incidents", "Происшествия", "🚨",
          "ДТП, пожары, криминальная хроника, поиски людей.",
          ("дтп", "авари", "пожар", "погиб", "пострадал", "полиц", "розыск",
           "пропал")),
    Topic("utilities", "ЖКХ и инфраструктура", "🛠",
          "Плановые работы, тарифы, ремонты, капремонт.",
          ("жкх", "тариф", "капремонт", "управляющ", "водоканал", "теплосет",
           "отоплен", "отключ", "водоснабж", "электроснабж", "авари",
           "ремонт сет", "холодная вода", "горячая вода", "канализац")),
    Topic("transport", "Транспорт", "🚌",
          "Маршруты, расписания, ремонт дорог, парковки.",
          ("автобус", "троллейбус", "трамвай", "маршрут", "дорог", "парковк",
           "電", "поезд", "аэропорт")),
    Topic("health", "Здоровье", "🏥",
          "Поликлиники, эпидемиология, льготные лекарства.",
          ("больниц", "поликлиник", "врач", "грипп", "вакцин", "лекарств",
           "здравоохранен")),
    Topic("education", "Образование", "🎓",
          "Школы, детские сады, вузы, приём и экзамены.",
          ("школ", "детский сад", "вуз", "университет", "егэ", "экзамен",
           "учител", "студент")),
    Topic("social", "Социальное", "🤝",
          "Выплаты, льготы, пенсии, поддержка семей.",
          ("выплат", "льгот", "пенси", "пособи", "материнск", "многодетн",
           "соцзащит")),
    Topic("economy", "Экономика и работа", "💼",
          "Предприятия, вакансии, цены, инвестиции.",
          ("завод", "предприяти", "ваканс", "зарплат", "цены", "инвестиц",
           "бизнес", "налог")),
    Topic("culture", "Культура и досуг", "🎭",
          "Афиша, фестивали, выставки, спорт.",
          ("концерт", "выставк", "фестивал", "театр", "музе", "спорт",
           "матч", "афиш")),
    Topic("weather_nature", "Погода и природа", "🌦",
          "Прогнозы на неделю, экология, паводки.",
          ("погод", "прогноз", "паводок", "эколог", "температур", "снег",
           "жара", "заморозк", "осадк", "дожд", "ветер", "гроза", "метель",
           "ливень", "похолодан", "потеплен")),
    Topic("region", "Область", "🗺",
          "Новости региона за пределами города.",
          ("район", "област", "село", "посёлок", "муниципал")),
    Topic("federal", "Федеральное", "🇷🇺",
          "Значимые общероссийские новости кратко.",
          ("правительств", "госдум", "президент", "минист", "федеральн")),

    # Ниже — тематики, не привязанные к городу. Они кормятся отдельными
    # лентами из presets.THEMATIC: городские источники такого не публикуют,
    # и без своих лент разделы стояли бы пустыми.
    Topic("it", "IT и игры", "🎮",
          "Игры для PC, PlayStation, Xbox, техника, софт, ИИ.",
          # Слова подобраны по тому, как ленты пишут на самом деле.
          # Прежний набор требовал точных оборотов вроде «релиз игры»,
          # и заголовок «Вышло крупное обновление Cyberpunk 2077»
          # не попадал ни в одну тематику.
          # «игр» без уточнения ловит «тигр» и «пилигрим»: поиск идёт
          # по подстроке, и короткий корень собирает чужие слова.
          ("игра", "игры", "игре", "игру", "игрок", "игров",
           "гейм", "playstation", "ps5", "xbox", "nintendo", "steam",
           "консол", "видеокарт", "процессор", "смартфон", "нейросет",
           "искусственный интеллект", "приложени", "обновлени",
           "разработчик", "релиз", "патч", "киберспорт", "трейлер игры",
           "дополнени", "ноутбук", "монитор", "windows", "linux", "android",
           "ios", "чип", "гаджет", "софт", "программ", "сервер", "утечк",
           "версия", "бета", "движок", "студия", "издател")),
    Topic("science", "Наука и техника", "🔬",
          "Исследования, космос, медицина, изобретения.",
          ("учён", "исследовани", "космос", "спутник", "ракет", "нау",
           "открыти", "эксперимент", "вакцин", "телескоп", "физик")),
    Topic("sport", "Спорт", "⚽️",
          "Матчи, турниры, результаты, спортсмены.",
          ("матч", "турнир", "чемпионат", "сборн", "футбол", "хоккей",
           "баскетбол", "олимп", "гол", "спортсмен", "тренер", "лиг")),
    Topic("hobby", "Хобби и авто", "🚗",
          "Автомобили, рукоделие, сад, рыбалка, путешествия.",
          # «сад» отдельным словом брать нельзя: оно сидит внутри «осадков»,
          # и прогноз погоды уезжал в хобби. Поиск идёт по подстроке,
          # поэтому короткие корни здесь опаснее, чем кажутся.
          ("автомобил", "машин", "рыбалк", "охот", "садовод", "огород",
           "рукодел", "путешестви", "турист", "велосипед", "мотоцикл",
           "дача", "грядк", "урожай")),
    Topic("cinema", "Кино и сериалы", "🎬",
          "Премьеры, трейлеры, стриминги.",
          ("фильм", "сериал", "премьер", "трейлер", "кино", "режиссёр",
           "актёр", "сезон", "экраниз", "стриминг")),
    Topic("finance", "Деньги и рынки", "📈",
          "Курсы, вклады, налоги, крупные сделки.",
          ("курс", "рубл", "доллар", "инфляц", "ставк", "вклад", "налог",
           "биржа", "акци", "ипотек", "криптовалют")),
)

BY_KEY = {topic.key: topic for topic in TOPICS}


def topic_of(text: str) -> str | None:
    """Определяет тематику по ключевым словам.

    Грубая, но дешёвая разметка: используется, когда ИИ тематику не вернул.
    Новостей много, срочности нет — тратить на них квоту модели незачем.
    """
    haystack = (text or "").lower()
    best: tuple[int, str] | None = None
    for topic in TOPICS:
        hits = sum(1 for word in topic.keywords if word in haystack)
        if hits and (best is None or hits > best[0]):
            best = (hits, topic.key)
    return best[1] if best else None


# --------------------------------------------------------------------------
#  Подписка
# --------------------------------------------------------------------------

@dataclass
class Subscription:
    """Состояние подписки пользователя на подборки."""

    topics: list[str] = field(default_factory=list)
    times: list[str] = field(default_factory=lambda: list(DEFAULT_TIMES))
    paid_until: str = ""            # ISO-дата окончания; пусто — бесплатно
    last_sent: str = ""             # метка последней отправки

    # Служебный доступ администрации: все тематики без оплаты. В базе не
    # хранится — вычисляется по роли при каждом обращении, иначе понижение
    # роли оставило бы человеку открытую подписку навсегда.
    complimentary: bool = field(default=False, compare=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Subscription":
        data = data or {}
        return cls(
            topics=[str(item) for item in (data.get("topics") or []) if str(item) in BY_KEY],
            times=[str(item) for item in (data.get("times") or DEFAULT_TIMES)],
            paid_until=str(data.get("paid_until") or ""),
            last_sent=str(data.get("last_sent") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "topics": self.topics,
            "times": self.times,
            "paid_until": self.paid_until,
            "last_sent": self.last_sent,
        }

    @property
    def paid(self) -> bool:
        """Оплачена ли подписка на сегодня. Служебный доступ здесь не в счёт."""
        if not self.paid_until:
            return False
        try:
            until = datetime.fromisoformat(self.paid_until)
        except ValueError:
            return False
        return until.date() >= datetime.now(timezone.utc).date()

    @property
    def active(self) -> bool:
        """Открыты ли все тематики — по оплате или по служебному доступу."""
        return self.paid or self.complimentary

    @property
    def days_left(self) -> int:
        """Остаток оплаченных дней. У служебного доступа срока нет — ноль."""
        if not self.paid:
            return 0
        until = datetime.fromisoformat(self.paid_until)
        return max(0, (until.date() - datetime.now(timezone.utc).date()).days)

    @property
    def limit(self) -> int:
        """Сколько тематик доступно: без подписки — только бесплатные."""
        return len(TOPICS) if self.active else FREE_TOPICS

    def allowed_topics(self) -> list[str]:
        """Тематики, которые реально будут доставлены."""
        return self.topics[: self.limit]

    def toggle(self, key: str) -> tuple[bool, str]:
        """Переключает тематику. Возвращает (включена ли, пояснение)."""
        if key not in BY_KEY:
            return False, "Неизвестная тематика."
        if key in self.topics:
            self.topics.remove(key)
            return False, ""
        if len(self.topics) >= self.limit:
            if self.active:
                return False, "Выбраны все доступные тематики."
            return False, (
                f"Без подписки доступно тематик: {FREE_TOPICS}. "
                "Оформите подписку, чтобы выбрать больше."
            )
        self.topics.append(key)
        return True, ""

    def extend(self, days: int) -> None:
        """Продлевает подписку, не теряя остаток."""
        # Именно paid: у администратора paid_until пуст, и fromisoformat("")
        # уронил бы обработку платежа.
        base = datetime.now(timezone.utc)
        if self.paid:
            base = datetime.fromisoformat(self.paid_until)
        self.paid_until = (base + timedelta(days=days)).isoformat()


def free_for_role(role: str | None) -> bool:
    """Кому подборки положены без оплаты.

    Администрация должна видеть платную часть целиком: иначе ошибку в
    доставке двенадцати тематик обнаружит первым не разработчик, а тот,
    кто заплатил.
    """
    return roles.is_admin(role)


def subscription_of(user: dict[str, Any], role: str | None = None) -> Subscription:
    subscription = Subscription.from_dict(user.get("digest"))
    subscription.complimentary = free_for_role(role or user.get("role"))

    # Подписка единая: оплата загрузки видео открывает и подборки.
    # Для человека это одна покупка, и продавать дважды за одно и то же
    # ощущение — нечестно.
    from . import subscription as common

    shared = common.paid_until(user)
    if shared and shared > (subscription.paid_until or ""):
        subscription.paid_until = shared
    return subscription


def store_subscription(user: dict[str, Any], subscription: Subscription) -> None:
    user["digest"] = subscription.to_dict()


# --------------------------------------------------------------------------
#  Расписание
# --------------------------------------------------------------------------

def due(subscription: Subscription, now: datetime) -> str | None:
    """Пора ли отправлять подборку. Возвращает метку отправки или None."""
    if not subscription.allowed_topics():
        return None

    stamp = f"{now:%H:%M}"
    for moment in subscription.times:
        # Окно в пять минут: фоновый цикл идёт не каждую минуту.
        # Некорректное время в настройках пропускаем, а не роняем рассылку.
        try:
            hour, minute = (int(part) for part in moment.split(":"))
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        except (ValueError, TypeError):
            continue
        delta = (now - target).total_seconds()
        if 0 <= delta <= 300:
            marker = f"{now:%Y-%m-%d}-{moment}"
            if subscription.last_sent != marker:
                return marker
    return None


def period_title(now: datetime) -> str:
    if now.hour < 12:
        return "утренняя подборка"
    if now.hour < 18:
        return "дневная подборка"
    return "вечерняя подборка"


# --------------------------------------------------------------------------
#  Сборка сообщения
# --------------------------------------------------------------------------

@dataclass
class Entry:
    """Одна новость в подборке."""

    topic: str
    summary: str
    source: str = ""
    link: str = ""


def group(entries: Iterable[Entry], topics: Iterable[str]) -> dict[str, list[Entry]]:
    wanted = set(topics)
    grouped: dict[str, list[Entry]] = {}
    for entry in entries:
        if entry.topic in wanted:
            grouped.setdefault(entry.topic, []).append(entry)
    return grouped


async def build_async(entries: Iterable[Entry], subscription: Subscription,
                      now: datetime, city: str = "",
                      summaries: dict[str, str] | None = None) -> str:
    """То же, что build, но с готовыми пересказами тематик."""
    return build(entries, subscription, now, city, summaries)


async def summaries_for(entries: Iterable[Entry],
                        subscription: Subscription) -> dict[str, str]:
    """Пересказ по каждой тематике — один запрос к модели на тематику.

    Пересказывать каждую новость отдельно было бы кратно дороже по квоте,
    а выигрыш даёт именно объединение: связная сводка вместо списка
    обрывков. Если модель недоступна, словарь остаётся пустым и подборка
    выходит списком, как раньше.
    """
    from . import ai, features

    if not features.enabled("digest_summaries"):
        return {}

    grouped = group(entries, subscription.allowed_topics())
    result: dict[str, str] = {}
    for key, items in grouped.items():
        topic = BY_KEY.get(key)
        if topic is None or len(items) < 2:
            continue                     # одну новость пересказывать незачем
        text = await ai.summarize_topic(
            topic.title, [item.summary for item in items[:12]]
        )
        if text:
            result[key] = text
    return result


def build(entries: Iterable[Entry], subscription: Subscription,
          now: datetime, city: str = "",
          summaries: dict[str, str] | None = None) -> str:
    """Собирает одно сообщение из всех тематик подписки."""
    grouped = group(entries, subscription.allowed_topics())
    if not grouped:
        return ""

    header = f"📰 <b>{period_title(now).capitalize()}</b>"
    if city:
        header += f" — {esc(city)}"
    lines = [header, f"<i>{now:%d.%m.%Y, %H:%M}</i>", ""]

    for key in subscription.allowed_topics():
        items = grouped.get(key)
        if not items:
            continue
        topic = BY_KEY[key]
        lines.append(f"{topic.icon} <b>{esc(topic.title)}</b>")

        recap = (summaries or {}).get(key, "").strip()
        if recap:
            # Пересказ заменяет список, но источники всё равно перечисляем
            # ниже: сводка без возможности проверить — слухи, а не новости.
            lines.append(esc(recap))
            links = [entry.link for entry in items[:MAX_ITEMS_PER_TOPIC]
                     if entry.link]
            if links:
                shown = " · ".join(
                    f'<a href="{esc_attr(link)}">[{number}]</a>'
                    for number, link in enumerate(links, 1)
                )
                lines.append(f"<i>Источники: {shown}</i>")
            lines.append("")
            continue

        for entry in items[:MAX_ITEMS_PER_TOPIC]:
            text = entry.summary.strip()
            if entry.link:
                lines.append(f'• <a href="{esc_attr(entry.link)}">{esc(text[:220])}</a>')
            else:
                lines.append(f"• {esc(text[:220])}")
        if len(items) > MAX_ITEMS_PER_TOPIC:
            lines.append(f"  <i>…и ещё {len(items) - MAX_ITEMS_PER_TOPIC}</i>")
        lines.append("")

    if not subscription.active:
        hidden = len(subscription.topics) - len(subscription.allowed_topics())
        if hidden > 0:
            lines.append(
                f"<i>Ещё {hidden} выбранных тематик доступны по подписке.</i>"
            )

    lines.append(
        "<i>Это подборка новостей. Об опасности бот сообщает отдельно "
        "и немедленно — независимо от подписки.</i>"
    )
    return "\n".join(lines).strip()


def describe(subscription: Subscription, lang: str = "ru") -> str:
    """Состояние подписки для меню."""
    from . import i18n

    def _(key: str, russian: str) -> str:
        return i18n.t(key, lang, russian)

    lines = [f"📰 <b>{_('digest.title', 'Новостные подборки')}</b>", ""]

    if subscription.complimentary:
        lines.append(_(
            "digest.staff",
            "🛠 <b>Служебный доступ</b> — все тематики открыты без оплаты.",
        ))
        if subscription.paid:
            lines.append(
                f"{_('digest.extra_days', 'Оплачено дней сверх того')}: "
                f"<b>{subscription.days_left}</b>"
            )
    elif subscription.paid:
        lines.append(
            f"✅ {_('digest.paid', 'Подписка активна, осталось дней')}: "
            f"<b>{subscription.days_left}</b>"
        )
        lines.append("<i>" + _(
            "digest.covers_media",
            "Она же снимает дневной предел на загрузку видео.",
        ) + "</i>")
    else:
        lines.append(
            f"{_('digest.free', 'Бесплатно доступно тематик')}: "
            f"<b>{FREE_TOPICS}</b>. " + _(
                "digest.upsell",
                f"Подписка открывает все {len(TOPICS)}.",
            )
        )

    chosen = subscription.allowed_topics()
    lines.append("")
    if chosen:
        lines.append(f"<b>{_('digest.topics', 'Ваши тематики')}:</b>")
        for key in chosen:
            topic = BY_KEY[key]
            title = i18n.t(f"topic.{key}", lang, topic.title)
            lines.append(f"{topic.icon} {esc(title)}")
    else:
        lines.append(_(
            "digest.no_topics",
            "Тематики не выбраны — подборка не приходит.",
        ))

    lines.append("")
    lines.append(
        f"<b>{_('digest.times', 'Время доставки')}:</b> "
        f"{', '.join(subscription.times)}"
    )
    lines.append("")
    lines.append("<i>" + _(
        "digest.free_always",
        "Оповещения об опасности, ЖКХ, погода и SOS остаются бесплатными "
        "всегда и от подписки не зависят.",
    ) + "</i>")
    return "\n".join(lines)
