"""Owner-only редактор текстов лендинга без изменения его разметки."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import html
from typing import Any, Mapping

from .landing_content import PAGES, Field, changed_pages, default_content


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _note(kind: str, text: str) -> str:
    if not text:
        return ""
    return f'<div class="card {"good" if kind == "ok" else "bad"}">{esc(text)}</div>'


def overview_body(stored: Any, message: str = "", failed: str = "") -> str:
    changed = changed_pages(stored)
    cards = []
    for key, schema in PAGES.items():
        state = ('<span class="badge warn">изменено</span>' if key in changed
                 else '<span class="badge ok">по умолчанию</span>')
        cards.append(
            f'<div class="card"><h3><a href="/site/{esc(key)}">{esc(schema.title)}</a></h3>'
            f'<p class="muted">{esc(schema.description)}</p><p>{state}</p></div>'
        )
    return (_note("ok", message) + _note("bad", failed)
            + '<p class="muted">Здесь меняются только тексты и содержимое простых списков. '
              'Структура, стили и вёрстка остаются в коде. Изменения видны на сайте сразу, '
              'без пересборки лендинга. Политика и соглашение редактируются только в коде '
              'и остаются серверными страницами для Platega.</p>'
            + '<div class="grid">' + "".join(cards) + "</div>")


def _input_name(prefix: str, key: str) -> str:
    return f"{prefix}.{key}" if prefix else key


def _render_scalar(item: Field, name: str, value: Any,
                   textlist_rows: int | None = None) -> str:
    text = value if isinstance(value, str) else ""
    label = esc(item.label)
    limit = int(item.limit)
    hint = f'<div class="hint">{esc(item.hint)} Максимум {limit} символов.</div>'
    if item.kind == "textlist":
        rows = textlist_rows if textlist_rows is not None else len(text.split("\n"))
        limit = rows * limit + max(0, rows - 1)
        hint = f'<div class="hint">{esc(item.hint)} Максимум {item.limit} символов в строке.</div>'
    if item.kind in ("longtext", "textlist"):
        control = (f'<textarea name="{esc(name)}" maxlength="{limit}" rows="'
                   f'{max(3, len(text.splitlines()) + 1)}">{esc(text)}</textarea>')
    else:
        input_type = "url" if item.kind == "url" else "text"
        control = (f'<input type="{input_type}" name="{esc(name)}" maxlength="{limit}" '
                   f'value="{esc(text)}" style="width:100%">')
    return f'<div class="keyrow"><label for="{esc(name)}"><b>{label}</b></label>{control}{hint}</div>'


def _render_fields(fields: tuple[Field, ...], values: Mapping[str, Any], prefix: str = "") -> str:
    rendered = []
    for item in fields:
        name = _input_name(prefix, item.key)
        value = values.get(item.key, item.default)
        if item.kind == "list":
            rows = value if isinstance(value, list) else []
            blocks = []
            for index, row in enumerate(rows):
                row_values = row if isinstance(row, Mapping) else {}
                blocks.append(
                    f'<fieldset class="card"><legend><b>{esc(item.label)} · {index + 1}</b></legend>'
                    + _render_fields(item.fields, row_values, f"{name}.{index}") + "</fieldset>"
                )
            rendered.append(f'<h2>{esc(item.label)}</h2>' + "".join(blocks))
        else:
            textlist_rows = None
            if item.kind == "textlist" and isinstance(value, list):
                textlist_rows = len(value)
                value = "\n".join(str(line) for line in value)
            rendered.append(_render_scalar(item, name, value, textlist_rows))
    return "".join(rendered)


def edit_body(page_key: str, token: str, values: Mapping[str, Any],
              message: str = "", failed: str = "") -> str:
    schema = PAGES[page_key]
    hidden = f'<input type="hidden" name="csrf" value="{esc(token)}">'
    form = (f'<form method="post" action="/site/{esc(page_key)}">{hidden}'
            + _render_fields(schema.fields, values)
            + '<p><button type="submit">Сохранить</button> '
              '<button type="submit" class="ghost danger" name="reset" value="1" '
              'formaction="?reset=1" onclick="return confirm(\'Сбросить все тексты страницы?\')">'
              'Сбросить страницу</button></p></form>')
    return (_note("ok", message) + _note("bad", failed)
            + f'<p class="muted">{esc(schema.description)}</p>'
              '<p class="hint">HTML и Markdown не исполняются: содержимое выводится как обычный текст. '
              'Пустые поля допустимы. Число повторяющихся блоков задаёт разметка.</p>' + form)


def _valid_url(value: str) -> bool:
    if not value:
        return True
    if value.startswith("/"):
        return not value.startswith("//") and "\\" not in value
    return value.startswith(("https://", "http://", "mailto:")) and " " not in value


def _read_fields(fields: tuple[Field, ...], form: Mapping[str, Any],
                 defaults: Mapping[str, Any], prefix: str = "") -> tuple[dict[str, Any], str]:
    result: dict[str, Any] = {}
    for item in fields:
        name = _input_name(prefix, item.key)
        default = defaults.get(item.key, item.default)
        if item.kind == "list":
            rows = default if isinstance(default, list) else []
            values = []
            for index, row in enumerate(rows):
                row_default = row if isinstance(row, Mapping) else {}
                value, error = _read_fields(item.fields, form, row_default, f"{name}.{index}")
                if error:
                    return {}, error
                values.append(value)
            result[item.key] = values
            continue
        raw = str(form.get(name, ""))
        if item.kind == "textlist":
            expected = len(default) if isinstance(default, list) else 0
            value = raw.split("\n") if raw else []
            value = [line.rstrip("\r") for line in value]
            if len(value) != expected:
                return {}, f"{item.label}: нужно ровно {expected} строк — структура страницы не меняется"
            for line in value:
                if len(line) > item.limit:
                    return {}, f"{item.label}: строка длиннее {item.limit} символов"
            result[item.key] = value
            continue
        value = raw.strip() if item.kind in ("text", "url") else raw.strip("\r\n")
        if len(value) > item.limit:
            return {}, f"{item.label}: максимум {item.limit} символов"
        if item.kind in ("text", "url") and ("\n" in value or "\r" in value):
            return {}, f"{item.label}: поле должно быть одной строкой"
        if item.kind == "url" and not _valid_url(value):
            return {}, f"{item.label}: разрешены https://, http://, mailto: или относительный адрес /…"
        result[item.key] = value
    return result, ""


def apply_form(page_key: str, form: Mapping[str, Any],
               current: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], str]:
    """Разбирает только поля схемы; лишние POST-ключи игнорируются."""
    if page_key not in PAGES:
        return {}, "Неизвестная страница"
    values = current or default_content()[page_key]
    return _read_fields(PAGES[page_key].fields, form, values)
