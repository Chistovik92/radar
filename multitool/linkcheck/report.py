"""Формирование отчёта для Telegram в виде HTML-сообщения.

Отчёт содержит перечень найденных признаков и сетевые проверки,
но никогда не утверждает, что ссылка «безопасна».
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import html
from typing import Any

from .analyze import Verdict


def _verdict_icon(level: str) -> str:
    return {"ok": "✅", "attention": "⚠️", "suspect": "🔶", "danger": "🚨"}.get(level, "❓")


def build_report(v: Verdict) -> str:
    if not v.signals and not v.net:
        return "Ничего не удалось проанализировать."

    lines: list[str] = ["<b>Результат проверки ссылки</b>\n"]
    url = html.escape(v.url)
    lines.append(f"<b>Ссылка:</b> <code>{url}</code>\n")

    if v.signals:
        lines.append("<b>Признаки из адреса:</b>")
        for sig in sorted(v.signals, key=lambda s: s.weight, reverse=True):
            title = html.escape(sig.title)
            detail = html.escape(sig.detail) if sig.detail else ""
            lines.append(f"  • <i>{title}</i> ({sig.weight})")
            if detail:
                lines.append(f"      <code>{detail}</code>")
        lines.append("")

    if v.net:
        lines.append("<b>Сетевые проверки:</b>")
        if not v.net.success:
            lines.append("  <i>Не удалось завершить сетевую проверку</i>")
            if v.net.notes:
                for note in v.net.notes:
                    lines.append(f"      <code>{html.escape(note)}</code>")
        else:
            if v.net.chain and len(v.net.chain) > 1:
                lines.append("  <b>Перенаправления:</b>")
                for hop in v.net.chain:
                    lines.append(f"      <code>{html.escape(hop)}</code>")
                lines.append("")
            if v.net.domain_age_days is not None:
                age = v.net.domain_age_days
                lines.append(f"  <i>Возраст домена:</i> {age} дн.")
                if age < 30:
                    lines.append("      <i>(домен зарегистрирован недавно)</i>")
                lines.append("")
            if v.net.cert_valid_days is not None:
                days = v.net.cert_valid_days
                lines.append(f"  <i>Сертификат валиден:</i> {days} дн.")
                if days < 0:
                    lines.append("      <i>(сертификат просрочен)</i>")
                elif days < 7:
                    lines.append("      <i>(сертификат скоро истекает)</i>")
                lines.append("")
            if v.net.threats:
                lines.append("  <b>⚠️ Обнаружены угрозы по Safe Browsing:</b>")
                for t in v.net.threats:
                    lines.append(f"      <code>{html.escape(t)}</code>")
                lines.append("")
            if v.net.notes:
                lines.append("  <b>Примечания сети:</b>")
                for note in v.net.notes:
                    lines.append(f"      <code>{html.escape(note)}</code>")
                lines.append("")
    score = v.score
    level = v.level
    icon = _verdict_icon(level)
    lines.append(f"<b>Итоговый счёт:</b> {score}/100 {icon}")
    lines.append(f"<b>Уровень риска:</b> {level.title()}")
    lines.append("")
    lines.append(
        "⚠️ <i>Это не гарантия безопасности. "
        "Отсутствие признаков не означает, что ссылка полностью безопасна. "
        "Всегда проверяйте источник через официальные каналы.</i>"
    )
    return "\n".join(lines)


def build_report_plain(v: Verdict) -> str:
    if not v.signals and not v.net:
        return "Ничего не удалось проанализировать."

    lines: list[str] = ["Результат проверки ссылки"]
    lines.append("")
    lines.append(f"Ссылка: {v.url}")
    lines.append("")

    if v.signals:
        lines.append("Признаки из адреса:")
        for sig in sorted(v.signals, key=lambda s: s.weight, reverse=True):
            lines.append(f"  • {sig.title} ({sig.weight})")
            if sig.detail:
                lines.append(f"      {sig.detail}")
        lines.append("")

    if v.net:
        lines.append("Сетевые проверки:")
        if not v.net.success:
            lines.append("  Не удалось завершить сетевую проверку")
            if v.net.notes:
                for note in v.net.notes:
                    lines.append(f"      {note}")
        else:
            if v.net.chain and len(v.net.chain) > 1:
                lines.append("  Перенаправления:")
                for hop in v.net.chain:
                    lines.append(f"      {hop}")
                lines.append("")
            if v.net.domain_age_days is not None:
                age = v.net.domain_age_days
                lines.append(f"  Возраст домена: {age} дн.")
                if age < 30:
                    lines.append("      (домен зарегистрирован недавно)")
                lines.append("")
            if v.net.cert_valid_days is not None:
                days = v.net.cert_valid_days
                lines.append(f"  Сертификат валиден: {days} дн.")
                if days < 0:
                    lines.append("      (сертификат просрочен)")
                elif days < 7:
                    lines.append("      (сертификат скоро истекает)")
                lines.append("")
            if v.net.threats:
                lines.append("  ⚠️ Обнаружены угрозы по Safe Browsing:")
                for t in v.net.threats:
                    lines.append(f"      {t}")
                lines.append("")
            if v.net.notes:
                lines.append("  Примечания сети:")
                for note in v.net.notes:
                    lines.append(f"      {note}")
                lines.append("")
    score = v.score
    level = v.level
    icon = _verdict_icon(level)
    lines.append(f"Итоговый счёт: {score}/100 {icon}")
    lines.append(f"Уровень риска: {level.title()}")
    lines.append("")
    lines.append(
        "⚠️ Это не гарантия безопасности. "
        "Отсутствие признаков не означает, что ссылка полностью безопасна. "
        "Всегда проверяйте источник через официальные каналы."
    )
    return "\n".join(lines)