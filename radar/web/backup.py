"""Раздел резервных копий в веб-панели. Логика — в radar/backup.py."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import html

from .. import backup as backup_module

create = backup_module.create
find = backup_module.find


def body() -> str:
    items = backup_module.listing()
    rows = "".join(
        f"<tr><td><code>{html.escape(item.name)}</code></td>"
        f"<td>{html.escape(item.when)}</td>"
        f"<td>{html.escape(item.size_human)}</td>"
        f'<td><a href="/backup/download?name={html.escape(item.name)}">скачать</a></td>'
        "</tr>"
        for item in items
    )
    return (
        '<div class="card">'
        '<a href="/backup/create" style="color:#5ea8ff">Создать копию сейчас</a>'
        '<p class="muted">В копию входят база целиком, файл настроек '
        "и версия проекта. Журналы не включаются — восстановление от них "
        "не зависит.</p></div>"
        '<div class="card"><table><tr><th>Файл</th><th>Создана</th>'
        f"<th>Размер</th><th></th></tr>"
        f"{rows or '<tr><td colspan=4 class=muted>копий нет</td></tr>'}</table></div>"
        '<div class="card muted">Восстановление выполняется установщиком '
        "на сервере: <code>bash install.sh --rollback</code>. Из браузера "
        "восстановление не запускается намеренно — это операция, которая "
        "должна выполняться осознанно и с доступом к машине.</div>"
    )
