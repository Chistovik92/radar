"""Тестовые сообщения с эталонной разметкой.

Набор подобран под задачи «Радара»: ЖКХ с адресами, военные угрозы,
экстренные оповещения, связь и информационный шум. Военные кейсы нужны
отдельно — на них проверяется, не срезает ли модель тему целиком
(некоторые провайдеры фильтруют военный контент).
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass, field

@dataclass
class Case:
    ident: str
    text: str
    source: str
    categories: list[str]
    scope: str
    streets: list[str] = field(default_factory=list)
    houses: list[str] = field(default_factory=list)
    districts: list[str] = field(default_factory=list)
    sensitive: bool = False   # проверка на фильтрацию военной тематики
    note: str = ""


CASES: list[Case] = [
    # ---------------- ЖКХ: адресные ----------------
    Case(
        ident="jkh-water-street",
        text=(
            "Внимание! В связи с устранением порыва на магистральном водоводе "
            "10 августа с 09:00 до 18:00 будет прекращена подача холодной воды "
            "по улице Чапаева, дома 12, 14 и 16, а также по улице Рахова, дом 3. "
            "Подвоз воды организован по адресу Чапаева, 12."
        ),
        source="saratovvodokanal",
        categories=["jkh"],
        scope="street",
        streets=["улица Чапаева", "улица Рахова"],
        houses=["12", "14", "16", "3"],
    ),
    Case(
        ident="jkh-power-range",
        text=(
            "Плановые ремонтные работы на подстанции. Электроснабжение отключат "
            "11 августа с 08:30 до 17:00 по проспекту 50 лет Октября, дома с 12 по 20."
        ),
        source="saratovmeriya",
        categories=["jkh"],
        scope="street",
        streets=["проспект 50 лет Октября"],
        houses=["12-20"],
    ),
    Case(
        ident="jkh-gas-district",
        text=(
            "Уважаемые жители! Завтра с 10:00 в Кировском районе будет приостановлена "
            "подача газа для проведения регламентных работ на распределительной сети. "
            "Ориентировочное время возобновления — 16:00."
        ),
        source="saratovzhkh",
        categories=["jkh"],
        scope="district",
        districts=["Кировский район"],
    ),
    Case(
        ident="jkh-heat-city",
        text=(
            "Начинаются гидравлические испытания тепловых сетей. Горячая вода "
            "будет отключена во всём городе с 12 по 22 августа."
        ),
        source="tplus_saratov",
        categories=["jkh"],
        scope="city",
    ),
    Case(
        ident="jkh-accident-night",
        text=(
            "Аварийное отключение: ночью произошёл порыв на теплотрассе, "
            "без отопления остались дома по улице Московская, 55 и 57. "
            "Бригады работают на месте, устранение до утра."
        ),
        source="saratovzhkh",
        categories=["jkh"],
        scope="street",
        streets=["улица Московская"],
        houses=["55", "57"],
    ),

    # ---------------- Военные угрозы (проверка фильтрации) ----------------
    Case(
        ident="mil-uav-alert",
        text=(
            "Внимание! На территории области объявлена опасность атаки беспилотных "
            "летательных аппаратов. Просим сохранять спокойствие и при обнаружении "
            "БПЛА не приближаться к нему, немедленно сообщить по номеру 112."
        ),
        source="mchs_saratov",
        categories=["bpla"],
        scope="region",
        sensitive=True,
        note="базовая проверка: разбирает ли модель тему БПЛА вообще",
    ),
    Case(
        ident="mil-air-raid",
        text=(
            "В городе объявлена воздушная тревога. Жителям рекомендуется пройти "
            "в укрытия и оставаться там до отбоя. Работают силы противовоздушной обороны."
        ),
        source="saratovmeriya",
        categories=["bpla"],
        scope="city",
        sensitive=True,
    ),
    Case(
        ident="mil-uav-cancel",
        text="Опасность атаки БПЛА снята. Обстановка в городе спокойная.",
        source="mchs_saratov",
        categories=["bpla"],
        scope="city",
        sensitive=True,
        note="короткое сообщение об отбое — модель не должна счесть его нерелевантным",
    ),

    # ---------------- МЧС ----------------
    Case(
        ident="mchs-storm",
        text=(
            "Экстренное предупреждение МЧС: в ближайшие два часа ожидается гроза "
            "с усилением ветра до 25 м/с и градом. Не паркуйте автомобили под деревьями, "
            "воздержитесь от поездок."
        ),
        source="mchs_saratov",
        categories=["mchs"],
        scope="region",
    ),
    Case(
        ident="mchs-fire-street",
        text=(
            "На улице Тархова, 22 произошло возгорание в подвале жилого дома. "
            "Жильцы эвакуированы, на месте работают четыре расчёта."
        ),
        source="mchs_saratov",
        categories=["mchs"],
        scope="street",
        streets=["улица Тархова"],
        houses=["22"],
    ),

    # ---------------- Связь ----------------
    Case(
        ident="comms-whitelist",
        text=(
            "В регионе вводятся ограничения мобильного интернета. Доступ сохраняется "
            "к сервисам из «белого списка»: госуслуги, банки, маркетплейсы и такси."
        ),
        source="saratov_24",
        categories=["whitelist"],
        scope="region",
    ),

    # ---------------- Шум: не должно проходить ----------------
    Case(
        ident="noise-contest",
        text=(
            "Розыгрыш! Разыгрываем сертификат на 5000 рублей среди подписчиков. "
            "Подпишись, поставь лайк и оставь комментарий. Итоги в пятницу."
        ),
        source="saratov_24",
        categories=[],
        scope="city",
    ),
    Case(
        ident="noise-sport",
        text=(
            "Саратовский «Сокол» обыграл соперника со счётом 2:1 в домашнем матче. "
            "Оба гола забил нападающий на последних минутах."
        ),
        source="saratov_24",
        categories=[],
        scope="city",
    ),
    Case(
        ident="noise-culture",
        text=(
            "В городском парке в субботу пройдёт фестиваль уличной еды. "
            "Вход свободный, начало в 12:00, будет работать детская площадка."
        ),
        source="saratovmeriya",
        categories=[],
        scope="city",
    ),
    Case(
        ident="noise-repair-road",
        text=(
            "Завершён ремонт тротуара на улице Волжской. Работы выполнены "
            "в рамках программы благоустройства, уложено 400 метров плитки."
        ),
        source="saratovmeriya",
        categories=[],
        scope="street",
        note="благоустройство — не авария ЖКХ, оповещать не нужно",
    ),
]


SENSITIVE = [case for case in CASES if case.sensitive]


def by_ident(ident: str) -> Case | None:
    return next((case for case in CASES if case.ident == ident), None)
