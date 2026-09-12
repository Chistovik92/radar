"""Веб-панель администратора: отдельный процесс поверх aiohttp.

Панель запускается своей задачей и падает независимо от бота: исключение
здесь не должно останавливать оповещения. Поэтому весь запуск обёрнут
в защиту, а флаг `web_panel` позволяет выключить её на живой системе.

Терминала сервера в панели нет и не планируется: удалённое выполнение команд
из браузера при утечке сессии отдаёт весь сервер, а не данные бота.
Управление сервером остаётся через SSH.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import html
import logging
import re
from typing import Any
from urllib.parse import quote

from .. import config, features, roles, shortener, storage
from .. import secrets as secrets_module
from . import auth

log = logging.getLogger("radar.web")

PAGE_STYLE = """
/* Оформление панели. Две темы, один набор ролей у цвета: фон, поверхность,
   текст, приглушённый текст, рамка, ссылка и три состояния — хорошо,
   внимание, плохо. Правка цвета делается в одном месте, а не расползается
   по десятку правил.

   Насыщенность здесь не для красоты: администрация открывает панель
   в основном когда что-то пошло не так, и состояние должно читаться
   до чтения текста — цветом строки и полосой на карточке. */
:root {
  --bg: #141824; --surface: #1c2230; --surface-2: #232b3b; --surface-3: #2b3446;
  --text: #e9edf5; --muted: #93a1ba; --line: #2c3548;
  --link: #62a9ff; --link-dim: #a3b6d6;
  --accent: #4f8cff; --accent-2: #7b6bff;
  --ok: #5ed49a; --warn: #ffc861; --bad: #ff7d85;
  --ok-soft: rgba(94,212,154,.14); --warn-soft: rgba(255,200,97,.14);
  --bad-soft: rgba(255,125,133,.14); --accent-soft: rgba(79,140,255,.14);
  --shadow: 0 1px 2px rgba(0,0,0,.30), 0 8px 24px rgba(0,0,0,.22);
  --shadow-sm: 0 1px 2px rgba(0,0,0,.28);
  --radius: 14px;
  color-scheme: dark;
}
/* Светлая тема — не инверсия тёмной: на белом те же насыщенности выжигают
   глаза, поэтому акценты темнее, поверхности почти белые, а рамка заметная,
   иначе карточки сливаются с фоном. */
[data-theme="light"] {
  --bg: #eef1f7; --surface: #ffffff; --surface-2: #f4f6fb; --surface-3: #e9edf5;
  --text: #182031; --muted: #5b6880; --line: #d9dfeb;
  --link: #1a68ce; --link-dim: #44526a;
  --accent: #2f6fe0; --accent-2: #6a52e0;
  --ok: #157f47; --warn: #8a5a06; --bad: #c3302c;
  --ok-soft: rgba(21,127,71,.10); --warn-soft: rgba(138,90,6,.10);
  --bad-soft: rgba(195,48,44,.10); --accent-soft: rgba(47,111,224,.10);
  --shadow: 0 1px 2px rgba(16,24,40,.06), 0 10px 24px rgba(16,24,40,.07);
  --shadow-sm: 0 1px 2px rgba(16,24,40,.07);
  color-scheme: light;
}

* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text);
       font:15px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
       -webkit-font-smoothing:antialiased; }

/* --- шапка ------------------------------------------------------------ */
header { background:var(--surface); padding:10px 22px; display:flex;
         align-items:center; gap:14px; border-bottom:1px solid var(--line);
         position:sticky; top:0; z-index:5; flex-wrap:wrap;
         box-shadow:var(--shadow-sm); }
/* Тонкая цветная полоса сверху: единственное чисто декоративное место,
   зато панель ни с чем не спутаешь на скриншоте. */
header::before { content:""; position:absolute; inset:0 0 auto 0; height:3px;
                 background:linear-gradient(90deg,var(--accent),var(--accent-2)); }
header .brand { font-weight:700; font-size:17px; letter-spacing:.2px;
                display:flex; align-items:center; gap:8px; }
header .brand::before { content:""; width:9px; height:9px; border-radius:50%;
                        background:var(--ok);
                        box-shadow:0 0 0 4px var(--ok-soft); }
/* Версия рядом с названием: по скриншоту должно быть видно, какая версия
   установлена, иначе разбор начинается с лишнего вопроса. */
.version { color:var(--muted); font-size:12px; margin-left:-4px;
           padding:2px 8px; border-radius:999px; background:var(--surface-2);
           border:1px solid var(--line); }

nav { display:flex; gap:4px; flex-wrap:wrap; }
nav a { color:var(--link-dim); text-decoration:none; padding:7px 12px;
        border-radius:999px; white-space:nowrap; font-size:14px;
        transition:background .15s, color .15s; }
nav a:hover { color:var(--text); background:var(--surface-2); }
nav a.active { color:#fff; font-weight:600;
               background:linear-gradient(135deg,var(--accent),var(--accent-2));
               box-shadow:0 2px 10px var(--accent-soft); }
[data-theme="light"] nav a.active { color:#fff; }
.spacer { margin-left:auto; }
.who { color:var(--muted); font-size:14px; }
.who a { color:var(--link-dim); }

/* Второй ряд разделов: он часть шапки, поэтому липнет к ней, а не уезжает
   вверх при прокрутке длинного списка. */
.subnav { position:sticky; top:0; z-index:4; display:flex; gap:2px;
          padding:8px 22px; background:var(--surface-2);
          border-bottom:1px solid var(--line); flex-wrap:wrap; }
.subnav a { color:var(--muted); text-decoration:none; padding:5px 12px;
            border-radius:8px; font-size:13.5px; white-space:nowrap; }
.subnav a:hover { color:var(--text); background:var(--surface-3); }
.subnav a.active { color:var(--link); background:var(--surface);
                   box-shadow:inset 0 0 0 1px var(--line); font-weight:600; }

main { padding:24px 22px 40px; max-width:1100px; margin:0 auto; }
.back { display:inline-block; margin-bottom:10px; color:var(--muted);
        text-decoration:none; font-size:13.5px; padding:4px 10px;
        border-radius:8px; background:var(--surface-2);
        border:1px solid var(--line); }
.back:hover { color:var(--text); background:var(--surface-3); }
h1 { font-size:22px; margin:0 0 20px; letter-spacing:-.01em; }
h2 { font-size:16px; margin:0 0 12px; }
h3 { margin:0 0 12px; font-size:16px; }
a { color:var(--link); }

/* --- таблицы ---------------------------------------------------------- */
table { width:100%; border-collapse:collapse; background:var(--surface);
        border-radius:var(--radius); overflow:hidden; box-shadow:var(--shadow-sm); }
th, td { padding:11px 14px; text-align:left; border-bottom:1px solid var(--line); }
th { color:var(--muted); font-weight:600; font-size:12px; text-transform:uppercase;
     letter-spacing:.04em; background:var(--surface-2); position:sticky; top:0; }
tbody tr:nth-child(even) td, tr:nth-child(even) td { background:var(--surface-2); }
tr:hover td { background:var(--surface-3); }
tr:last-child td { border-bottom:none; }
td code { font-size:13px; }

/* --- карточки --------------------------------------------------------- */
.card { background:var(--surface); border-radius:var(--radius); padding:18px 20px;
        margin-bottom:16px; box-shadow:var(--shadow-sm);
        border:1px solid var(--line); transition:box-shadow .18s, transform .18s; }
.card:hover { box-shadow:var(--shadow); }
.card table { box-shadow:none; background:transparent; }
.card th { position:static; }
.card > :first-child { margin-top:0; }
.card > :last-child { margin-bottom:0; }
/* Состояние карточки читается полосой слева — до чтения самого текста. */
.card.warn, .card.bad, .card.busy, .card.good {
  border-left:4px solid var(--line); }
.card.warn { border-left-color:var(--warn); background:
             linear-gradient(90deg,var(--warn-soft),transparent 240px), var(--surface);
             color:var(--text); }
.card.bad  { border-left-color:var(--bad); background:
             linear-gradient(90deg,var(--bad-soft),transparent 240px), var(--surface);
             color:var(--text); }
.card.good { border-left-color:var(--ok); background:
             linear-gradient(90deg,var(--ok-soft),transparent 240px), var(--surface); }
.card.busy { border-left-color:var(--accent); position:relative; overflow:hidden; }
/* Полоса «идёт работа»: без неё страница с журналом выглядит замершей. */
.card.busy::after { content:""; position:absolute; left:0; right:0; bottom:0;
  height:3px; background:linear-gradient(90deg,transparent,var(--accent),transparent);
  animation:slide 1.6s linear infinite; }
@keyframes slide { from { transform:translateX(-100%); }
                   to   { transform:translateX(100%); } }

.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr));
        gap:14px; margin-bottom:20px; }
.metric { position:relative; }
.metric b { display:block; font-size:28px; line-height:1.15; margin-bottom:4px;
            letter-spacing:-.02em; }
.metric span { color:var(--muted); font-size:13px; }

.ok { color:var(--ok); } .warn { color:var(--warn); } .bad { color:var(--bad); }
.muted { color:var(--muted); }
.hint { color:var(--muted); font-size:13px; }
.login { max-width:430px; margin:80px auto; text-align:center; }

/* Значок состояния — для мест, где слово «включено» тонет в тексте. */
.badge { display:inline-block; padding:2px 9px; border-radius:999px;
         font-size:12px; font-weight:600; border:1px solid transparent; }
.badge.ok { background:var(--ok-soft); border-color:var(--ok); }
.badge.warn { background:var(--warn-soft); border-color:var(--warn); }
.badge.bad { background:var(--bad-soft); border-color:var(--bad); }

/* --- формы ------------------------------------------------------------ */
form.inline { display:flex; gap:10px; margin-top:12px; flex-wrap:wrap; }
input[type=text], input[type=password], input[type=url], textarea, select {
  padding:10px 12px; border-radius:10px; border:1px solid var(--line);
  background:var(--bg); color:var(--text); font:inherit;
  transition:border-color .15s, box-shadow .15s; }
input:focus-visible, textarea:focus-visible, select:focus-visible {
  outline:none; border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-soft); }
form.inline input[type=text], form.inline input[type=password],
form.inline input[type=url] { flex:1 1 240px; }
textarea { width:100%; min-height:70px; resize:vertical; }

button { padding:10px 18px; border-radius:10px; border:none; cursor:pointer;
         background:linear-gradient(135deg,var(--accent),var(--accent-2));
         color:#fff; font:inherit; font-weight:600;
         box-shadow:0 2px 10px var(--accent-soft);
         transition:transform .12s, filter .15s, box-shadow .15s; }
button:hover { filter:brightness(1.06); transform:translateY(-1px); }
button:active { transform:translateY(0); }
button:focus-visible { outline:none; box-shadow:0 0 0 3px var(--accent-soft); }
button.ghost { background:var(--surface-2); color:var(--text); box-shadow:none;
               border:1px solid var(--line); padding:6px 12px; font-size:13px;
               font-weight:500; }
button.ghost:hover { background:var(--surface-3); }
button.danger { background:linear-gradient(135deg,var(--bad),#d9534f);
                box-shadow:0 2px 10px var(--bad-soft); }
button.ghost.danger { background:var(--surface-2); color:var(--bad);
                      border-color:var(--bad); }

.note { padding:12px 15px; border-radius:10px; margin-bottom:16px;
        border:1px solid transparent; font-weight:500; }
.note.good { background:var(--ok-soft); color:var(--ok); border-color:var(--ok); }
.note.bad { background:var(--bad-soft); color:var(--bad); border-color:var(--bad); }

.keyrow { display:grid; grid-template-columns:1fr; gap:6px; padding:13px 0;
          border-bottom:1px solid var(--line); }
.keyrow:last-child { border-bottom:none; }
.keyrow .hint { color:var(--muted); font-size:13px; }

/* Журнал установки: моноширинный, со своей прокруткой — иначе длинные
   строки установщика растягивают страницу по горизонтали. */
pre.log { background:var(--bg); border:1px solid var(--line); border-radius:10px;
          padding:14px; max-height:420px; overflow:auto; font-size:12.5px;
          line-height:1.5; white-space:pre-wrap; word-break:break-word;
          margin:0; color:var(--text); }
code { background:var(--surface-2); padding:1px 6px; border-radius:6px;
       font-size:13px; }

/* Переключатель темы. Кнопка, а не хитрый ползунок: читается без
   объяснений и работает без мыши. */
#theme { background:var(--surface-2); color:var(--text); padding:7px 11px;
         font-size:14px; line-height:1; box-shadow:none;
         border:1px solid var(--line); font-weight:400; }
#theme:hover { background:var(--surface-3); transform:none; }

@media (max-width: 780px) {
  header { padding:10px 14px; gap:10px; }
  /* Разделов много, и на телефоне они не должны занимать пол-экрана:
     строка прокручивается вбок, а не переносится. Своя строка во всю
     ширину: иначе разделы зажаты между названием и кнопкой темы,
     и до дальних приходится возить пальцем через всю шапку. */
  nav { order:3; flex:1 0 100%; flex-wrap:nowrap; overflow-x:auto;
        max-width:100%; scrollbar-width:none; padding-bottom:2px; }
  nav::-webkit-scrollbar { display:none; }
  main { padding:16px 14px 32px; }
  .subnav { padding:7px 14px; flex-wrap:nowrap; overflow-x:auto;
            scrollbar-width:none; }
  .subnav::-webkit-scrollbar { display:none; }
  th, td { padding:9px 10px; }
  .who { font-size:13px; }

  /* Размер под палец. Кнопка «удалить» в строке таблицы была 28px —
     в неё попадали через раз. */
  nav a, .subnav a, button, #theme {
    min-height:40px; display:inline-flex; align-items:center; }
  button.ghost { min-height:36px; }

  /* Широкие таблицы прокручиваются вбок. Прокрутка задана ТАБЛИЦЕ,
     а не карточке: у «Реактора» карточка носит уголки-скобки
     псевдоэлементами за своей границей, и overflow на .card срезал бы
     их вместе с углами. Восстановление display:table у tbody нужно
     потому, что display:block на самой таблице отключает расчёт
     колонок, и они схлопываются в кашу. */
  table:not(.stack) { display:block; overflow-x:auto;
                      -webkit-overflow-scrolling:touch; }
  table:not(.stack) > tbody { display:table; width:100%; min-width:540px; }
  /* Липкая шапка внутри боковой прокрутки бессмысленна. */
  th { position:static; }

  /* Журнал установки занимал почти весь экран телефона. */
  pre.log { max-height:260px; }
  .login { margin:36px auto; }
}

/* Телефон, а не планшет: на 700px пять колонок ещё читаются,
   на 360px — уже нет. */
@media (max-width: 560px) {
  /* Строка таблицы разворачивается в карточку «поле: значение».
     Имя поля берётся из data-label самой разметки — иначе заголовок
     таблицы, который здесь скрыт, пришлось бы дублировать в CSS
     и чинить в двух местах при каждом изменении столбцов. */
  table.stack, table.stack > tbody, table.stack tr, table.stack td {
    display:block; width:auto; }
  table.stack { min-width:0; overflow:visible; }
  table.stack > thead { display:none; }
  table.stack tr { border:1px solid var(--line); border-radius:10px;
                   background:var(--surface-2); margin-bottom:10px;
                   padding:4px 0; }
  table.stack tr:last-child { margin-bottom:0; }
  table.stack td { border:none; padding:7px 13px; }
  table.stack td::before { content:attr(data-label); display:block;
                           color:var(--muted); font-size:11.5px;
                           text-transform:uppercase; letter-spacing:.05em; }
  table.stack td:empty { display:none; }
  .grid { grid-template-columns:1fr; }
  h1 { font-size:19px; }
}

/* Уважение к системной настройке: анимация полосы «идёт работа»
   выключается, если человек попросил меньше движения. */
@media (prefers-reduced-motion: reduce) {
  * { animation:none !important; transition:none !important; }
}
"""

THEME_STYLE = """
/* --------------------------------------------------------------------------
   Темы оформления (с 4.9.7)

   Светлая и тёмная — рабочие: их задача не мешать. «Матрица» и «Реактор» —
   для тех, кто держит панель открытой на втором экране: там важнее, чтобы
   состояние было видно от двери, чем плотность текста.

   Тема меняет ТОЛЬКО оформление: те же переменные, та же разметка, никакой
   отдельной вёрстки. Иначе каждая новая страница панели требовала бы
   правки в четырёх местах, и темы разъехались бы к третьему выпуску.
   -------------------------------------------------------------------------- */

/* ===== Матрица =========================================================== */
[data-theme="matrix"] {
  --bg: #000; --surface: #04140a; --surface-2: #062112; --surface-3: #0a3018;
  --text: #b9ffcf; --muted: #4fbf7d; --line: #0d4a24;
  --link: #46ff9c; --link-dim: #2fd47e;
  --accent: #22ff88; --accent-2: #0aff5a;
  --ok: #37ff8b; --warn: #d8ff4a; --bad: #ff5f5f;
  --ok-soft: rgba(55,255,139,.12); --warn-soft: rgba(216,255,74,.12);
  --bad-soft: rgba(255,95,95,.14); --accent-soft: rgba(34,255,136,.16);
  --shadow: 0 0 0 1px rgba(34,255,136,.12), 0 0 28px rgba(34,255,136,.10);
  --shadow-sm: 0 0 0 1px rgba(34,255,136,.10);
  --radius: 4px;
  color-scheme: dark;
}
[data-theme="matrix"] body {
  font-family: "JetBrains Mono", "Fira Code", "Cascadia Mono", Consolas,
               "Liberation Mono", monospace;
  text-shadow: 0 0 6px rgba(34,255,136,.25);
}
/* Дождь символов рисуется на canvas за содержимым: разметку он не трогает
   и снимается вместе с темой. */
#rain { position:fixed; inset:0; z-index:0; opacity:.16; pointer-events:none; }
[data-theme="matrix"] header, [data-theme="matrix"] main { position:relative; z-index:1; }
[data-theme="matrix"] header { background:rgba(4,20,10,.86);
  backdrop-filter:blur(2px); border-bottom:1px solid var(--line); }
[data-theme="matrix"] .card { border:1px solid var(--line); background:rgba(4,20,10,.82); }
[data-theme="matrix"] .card:hover { border-color:var(--accent); }
[data-theme="matrix"] h1::before { content:"> "; color:var(--accent); }
[data-theme="matrix"] h1::after {
  content:"_"; animation:blink 1.1s step-end infinite; color:var(--accent); }
@keyframes blink { 50% { opacity:0; } }
[data-theme="matrix"] nav a.active { background:var(--surface-3); color:var(--accent);
  box-shadow:inset 0 0 0 1px var(--accent); }
[data-theme="matrix"] .subnav { background:rgba(4,20,10,.9); }
[data-theme="matrix"] .subnav a.active { color:var(--accent);
  box-shadow:inset 0 0 0 1px var(--line); }
[data-theme="matrix"] th { text-transform:uppercase; letter-spacing:.12em;
  color:var(--accent); background:rgba(10,48,24,.6); }
[data-theme="matrix"] a { text-decoration:underline dotted; }
[data-theme="matrix"] .metric b { color:var(--accent);
  text-shadow:0 0 12px rgba(34,255,136,.5); }
[data-theme="matrix"] table, [data-theme="matrix"] pre.log {
  border:1px solid var(--line); }
[data-theme="matrix"] button { background:transparent; color:var(--accent);
  border:1px solid var(--accent); box-shadow:none; text-transform:uppercase;
  letter-spacing:.08em; font-size:13px; }
[data-theme="matrix"] button:hover { background:var(--accent-soft);
  box-shadow:0 0 14px var(--accent-soft); }
[data-theme="matrix"] .badge { border-radius:2px; }
/* Тонкая полоса развёртки — как на старом мониторе, но без мельтешения. */
[data-theme="matrix"] main::after {
  content:""; position:fixed; left:0; right:0; height:120px; z-index:2;
  pointer-events:none; background:linear-gradient(180deg,
    transparent, rgba(34,255,136,.05), transparent);
  animation:sweep 7s linear infinite; }
@keyframes sweep { from { top:-120px; } to { top:100%; } }

/* ===== Реактор =========================================================== */
[data-theme="ark"] {
  --bg: #060d16; --surface: rgba(12,24,38,.86); --surface-2: rgba(18,34,52,.9);
  --surface-3: rgba(24,44,66,.95);
  --text: #dff2ff; --muted: #7fa6c4; --line: rgba(94,214,255,.22);
  --link: #5ed6ff; --link-dim: #8fc6e6;
  --accent: #37c8ff; --accent-2: #ffb648;
  --ok: #4ce0b0; --warn: #ffb648; --bad: #ff6b7a;
  --ok-soft: rgba(76,224,176,.14); --warn-soft: rgba(255,182,72,.14);
  --bad-soft: rgba(255,107,122,.14); --accent-soft: rgba(55,200,255,.16);
  --shadow: 0 0 0 1px rgba(55,200,255,.16), 0 10px 40px rgba(0,0,0,.5);
  --shadow-sm: 0 0 0 1px rgba(55,200,255,.14);
  --radius: 2px;
  color-scheme: dark;
}
/* Сетка под интерфейсом: она даёт ощущение приборной панели и при этом
   ничего не весит — два повторяющихся градиента. */
[data-theme="ark"] body {
  background-image:
    linear-gradient(rgba(55,200,255,.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(55,200,255,.05) 1px, transparent 1px),
    radial-gradient(circle at 50% -10%, rgba(55,200,255,.16), transparent 60%);
  background-size: 44px 44px, 44px 44px, 100% 100%;
}
[data-theme="ark"] header { background:rgba(6,13,22,.9); backdrop-filter:blur(6px); }
[data-theme="ark"] .card { backdrop-filter:blur(4px); border:1px solid var(--line);
  position:relative; }
/* Уголки-скобки: та самая деталь, из-за которой интерфейс читается
   как приборный, а не как сайт. */
[data-theme="ark"] .card::before, [data-theme="ark"] .card::after {
  content:""; position:absolute; width:14px; height:14px; pointer-events:none;
  border:1px solid var(--accent); opacity:.7; }
[data-theme="ark"] .card::before { top:-1px; left:-1px;
  border-right:none; border-bottom:none; }
[data-theme="ark"] .card::after { bottom:-1px; right:-1px;
  border-left:none; border-top:none; }
[data-theme="ark"] .metric b { color:var(--accent);
  text-shadow:0 0 18px rgba(55,200,255,.45); font-variant-numeric:tabular-nums;
  font-family:"JetBrains Mono",Consolas,monospace; }
/* Полоска под метрикой — «шкала прибора»: заполняется при появлении. */
[data-theme="ark"] .metric::after { content:""; position:absolute; left:20px;
  right:20px; bottom:12px; height:2px; background:var(--accent); opacity:.5;
  transform-origin:left; animation:fill .8s ease-out both; }
@keyframes fill { from { transform:scaleX(0); } to { transform:scaleX(1); } }
[data-theme="ark"] h1 { text-transform:uppercase; letter-spacing:.08em;
  font-size:19px; }
[data-theme="ark"] h1::before { content:"// "; color:var(--accent); opacity:.7; }
[data-theme="ark"] .card:hover { transform:translateY(-2px);
  border-color:var(--accent); }
[data-theme="ark"] th { color:var(--accent); letter-spacing:.1em; }
[data-theme="ark"] nav a.active { background:transparent; color:var(--accent);
  box-shadow:inset 0 0 0 1px var(--accent), 0 0 16px var(--accent-soft); }
[data-theme="ark"] .subnav { background:rgba(6,13,22,.7); backdrop-filter:blur(6px); }
[data-theme="ark"] .subnav a.active { color:var(--accent); background:transparent;
  box-shadow:inset 0 0 0 1px var(--line); }
[data-theme="ark"] button { background:linear-gradient(135deg,
  rgba(55,200,255,.18), rgba(255,182,72,.14)); color:var(--text);
  border:1px solid var(--accent); text-transform:uppercase; letter-spacing:.06em;
  font-size:13px; }
[data-theme="ark"] button.danger { border-color:var(--bad);
  background:linear-gradient(135deg, rgba(255,107,122,.2), transparent); }
[data-theme="ark"] .brand::before { animation:pulse 2.4s ease-in-out infinite; }
@keyframes pulse {
  0%,100% { box-shadow:0 0 0 4px var(--accent-soft); }
  50% { box-shadow:0 0 0 9px rgba(55,200,255,.05); } }
[data-theme="ark"] header::before {
  background:linear-gradient(90deg,var(--accent),var(--accent-2),var(--accent));
  background-size:200% 100%; animation:slide-x 6s linear infinite; }
@keyframes slide-x { to { background-position:200% 0; } }

/* ===== Общее для «живых» тем ============================================ */
/* Карточки проявляются по очереди: на длинной странице это показывает
   порядок чтения, а не просто украшает. */
[data-theme="matrix"] .card, [data-theme="ark"] .card {
  animation:rise .45s ease-out both; }
[data-theme="matrix"] .card:nth-child(2), [data-theme="ark"] .card:nth-child(2) { animation-delay:.05s; }
[data-theme="matrix"] .card:nth-child(3), [data-theme="ark"] .card:nth-child(3) { animation-delay:.1s; }
[data-theme="matrix"] .card:nth-child(4), [data-theme="ark"] .card:nth-child(4) { animation-delay:.15s; }
[data-theme="matrix"] .grid .card, [data-theme="ark"] .grid .card { animation-delay:.05s; }
@keyframes rise { from { opacity:0; transform:translateY(10px); }
                  to   { opacity:1; transform:none; } }
[data-theme="matrix"] tr:hover td, [data-theme="ark"] tr:hover td {
  box-shadow:inset 2px 0 0 var(--accent); }

@media (prefers-reduced-motion: reduce) {
  #rain { display:none; }
  [data-theme="matrix"] main::after { display:none; }
}
"""

# Тема выбирается до отрисовки, иначе страница мигает тёмной и лишь потом
# становится светлой. Скрипт крошечный и стоит в head намеренно.
THEME_SCRIPT = """
(function () {
  try {
    var known = ['light', 'dark', 'matrix', 'ark'];
    var saved = localStorage.getItem('radar-theme');
    if (known.indexOf(saved) < 0) {
      saved = window.matchMedia &&
              window.matchMedia('(prefers-color-scheme: light)').matches
              ? 'light' : 'dark';
    }
    document.documentElement.setAttribute('data-theme', saved);
  } catch (e) { /* приватный режим: остаётся тема по умолчанию */ }
})();
"""

THEME_TOGGLE = """
(function () {
  var button = document.getElementById('theme');
  if (!button) { return; }
  var root = document.documentElement;
  var themes = [
    { key: 'light',  icon: '\u2600', name: 'Светлая' },
    { key: 'dark',   icon: '\u263e', name: 'Тёмная' },
    { key: 'matrix', icon: '\u2593', name: 'Матрица' },
    { key: 'ark',    icon: '\u25cf', name: 'Реактор' }
  ];
  function index() {
    var now = root.getAttribute('data-theme');
    for (var i = 0; i < themes.length; i++) {
      if (themes[i].key === now) { return i; }
    }
    return 1;
  }
  function paint() {
    var item = themes[index()];
    button.textContent = item.icon;
    button.title = 'Тема: ' + item.name + ' — нажмите, чтобы сменить';
    document.dispatchEvent(new CustomEvent('radar-theme', { detail: item.key }));
  }
  paint();
  button.addEventListener('click', function () {
    var next = themes[(index() + 1) % themes.length].key;
    root.setAttribute('data-theme', next);
    try { localStorage.setItem('radar-theme', next); } catch (e) {}
    paint();
  });
})();
"""


# Оживление интерфейса. Всё здесь необязательное: если скрипт не выполнится,
# панель останется полностью рабочей — цифры просто не будут набегать,
# а фон останется без дождя. Поэтому ни одна проверка прав, ни одна форма
# на этот код не опирается.
LIVE_SCRIPT = """
(function () {
  var root = document.documentElement;
  var calm = window.matchMedia &&
             window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* Счётчики: цифра набегает от нуля. Только там, где это действительно
     число, — иначе «4.9.7» превратилось бы в мусор. */
  function count() {
    if (calm) { return; }
    var nodes = document.querySelectorAll('.metric b');
    for (var i = 0; i < nodes.length; i++) {
      (function (node) {
        var raw = (node.textContent || '').trim();
        if (!/^[0-9\u00a0 ]+$/.test(raw)) { return; }
        var target = parseInt(raw.replace(/[^0-9]/g, ''), 10);
        if (!target || target > 1000000) { return; }
        var started = null;
        var grouped = /[\u00a0 ]/.test(raw);
        function step(now) {
          if (!started) { started = now; }
          var part = Math.min(1, (now - started) / 700);
          var value = Math.floor(target * (1 - Math.pow(1 - part, 3)));
          node.textContent = grouped ? value.toLocaleString('ru-RU') : String(value);
          if (part < 1) { requestAnimationFrame(step); }
        }
        node.textContent = '0';
        requestAnimationFrame(step);
      })(nodes[i]);
    }
  }

  /* Дождь символов — только в теме «Матрица». Рисуется на canvas позади
     содержимого: разметку не трогает и снимается вместе с темой. */
  var canvas = null, timer = null, onResize = null;
  function stopRain() {
    if (timer) { cancelAnimationFrame(timer); timer = null; }
    if (onResize) { window.removeEventListener('resize', onResize); onResize = null; }
    if (canvas) { canvas.remove(); canvas = null; }
  }
  function startRain() {
    if (calm || canvas) { return; }
    canvas = document.createElement('canvas');
    canvas.id = 'rain';
    document.body.appendChild(canvas);
    var context = canvas.getContext('2d');
    if (!context) { stopRain(); return; }
    var glyphs = '01\u0410\u0411\u0412\u0413\u0414ABCDEF<>[]{}/|=+*';
    var columns = [], step = 16, last = 0;
    onResize = function () {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
      columns = [];
      for (var x = 0; x < canvas.width / step; x++) {
        columns.push(Math.random() * canvas.height);
      }
    };
    onResize();
    window.addEventListener('resize', onResize);
    function frame(now) {
      timer = requestAnimationFrame(frame);
      if (now - last < 55) { return; }   /* ~18 кадров: дождь, а не мельтешение */
      last = now;
      context.fillStyle = 'rgba(0,0,0,.10)';
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.fillStyle = '#22ff88';
      context.font = step + 'px monospace';
      for (var i = 0; i < columns.length; i++) {
        var glyph = glyphs.charAt(Math.floor(Math.random() * glyphs.length));
        context.fillText(glyph, i * step, columns[i]);
        columns[i] = (columns[i] > canvas.height && Math.random() > 0.975)
          ? 0 : columns[i] + step;
      }
    }
    timer = requestAnimationFrame(frame);
  }

  function sync(theme) {
    if (theme === 'matrix') { startRain(); } else { stopRain(); }
  }
  document.addEventListener('radar-theme', function (event) { sync(event.detail); });
  /* Вкладку убрали из виду — гасим анимацию: панель часто висит фоном,
     и жечь батарею ради невидимого дождя незачем. */
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) { stopRain(); }
    else { sync(root.getAttribute('data-theme')); }
  });
  sync(root.getAttribute('data-theme'));
  count();
})();
"""


# --------------------------------------------------------------------------
#  Разделы панели (перестроены в 4.9.8)
# --------------------------------------------------------------------------
#
# Разделов набралось тринадцать, и они лежали одним рядом: «Ключи» стояли
# рядом с «Копиями», а «Обновление» — рядом с «Журналом». Найти нужное
# получалось только перебором. Теперь их пять, а редкое спрятано на второй
# уровень — в подменю раздела, а не в общий ряд.
#
# Правила прежние: панель повторяет права бота, а не расширяет их. Пункт,
# закрытый ролью, не показывается, и раздел без единого доступного пункта
# не показывается тоже.

def _nav_groups(role: str) -> list[tuple[str, str, str, list[tuple[str, str, str]]]]:
    """Разделы верхнего уровня и их подпункты: (адрес, имя, ключ, подпункты)."""
    moderator = roles.is_moderator(role)
    admin = roles.is_admin(role)
    owner = roles.is_superadmin(role)

    overview = [("/", "Сводка", "home")]
    if admin:
        overview.append(("/events", "События", "events"))
    if owner:
        overview.append(("/maintenance", "Обслуживание", "maintenance"))
        # Раздел виден всегда, даже когда возможность выключена: спрятанный
        # пункт человек не найдёт, а включать будет нечего — тумблер он тоже
        # не нашёл. Страница сама объясняет, что включить и какой ценой.
        overview.append(("/update", "Обновление", "update"))
        # Тот же принцип, что у «Обновления»: пункт виден всегда, даже
        # при выключенной возможности — страница сама объясняет, что
        # включить (тот же сокет Docker, та же цена).
        overview.append(("/rustdesk", "RustDesk", "rustdesk"))

    media: list[tuple[str, str, str]] = []
    if admin:
        media.append(("/links", "Ссылки", "links"))
    if owner:
        media.append(("/files", "Файлы", "files"))
        media.append(("/media", "Плейлисты", "media"))

    agent_items: list[tuple[str, str, str]] = []
    if owner:
        agent_items.append(("/agents", "Агенты", "agents"))
        agent_items.append(("/keys", "Ключи", "keys"))

    groups: list[tuple[str, str, str, list[tuple[str, str, str]]]] = [
        ("/", "Обзор", "home", overview),
    ]
    if moderator:
        groups.append(("/users", "Пользователи", "users", []))
    groups.append(("/sources", "Источники", "sources", []))
    if media:
        groups.append((media[0][0], "Медиа", "media", media))
    if agent_items:
        groups.append((agent_items[0][0], "Агенты", "agents", agent_items))
    return groups


# Страницы, до которых добираются со страницы «Обслуживание». В общем меню
# их намеренно нет — заходят туда редко, — но человек, попавший на них,
# не должен оказаться в тупике: подсветка раздела остаётся, а над заголовком
# появляется возврат. Пустое меню на такой странице и было тем самым
# «некуда вернуться».
_PARENT_PAGE: dict[str, tuple[str, str, str]] = {
    "backup": ("maintenance", "/maintenance", "Обслуживание"),
    "features": ("maintenance", "/maintenance", "Обслуживание"),
    "audit": ("maintenance", "/maintenance", "Обслуживание"),
    "partners": ("maintenance", "/maintenance", "Обслуживание"),
}


def _active_group(groups, active: str):
    """Раздел, которому принадлежит открытая страница."""
    parent = _PARENT_PAGE.get(active)
    wanted = parent[0] if parent else active
    for href, name, key, items in groups:
        if key == wanted or any(item[2] == wanted for item in items):
            return (href, name, key, items)
    return None


def _links_for(role: str) -> list[tuple[str, str, str]]:
    """Плоский список доступных страниц. Используется проверками прав."""
    flat: list[tuple[str, str, str]] = []
    for href, name, key, items in _nav_groups(role):
        if items:
            flat.extend(items)
        else:
            flat.append((href, name, key))
    return flat


def _update_body(session, running: bool, ok: str = "", err: str = "") -> str:
    """Страница обновления системы.

    Показывает не «идёт/не идёт», а сами шаги: установщик пишет журнал
    в data/logs, и человеку важно видеть, на чём он сейчас — иначе
    минуты сборки образа выглядят как зависшая кнопка.
    """
    from .. import updater

    allowed, reason = updater.ready()
    token = auth.csrf_token(session)
    parts: list[str] = [_note("ok", ok), _note("bad", err)]

    parts.append(
        '<div class="card">'
        f"<p>Установленная версия: <b>{html.escape(config.VERSION)}</b></p>"
        "<p class=\"muted\">Обновление выполняет тот же <code>install.sh</code>, "
        "что и на сервере: снимок перед заменой, сборка образа, перезапуск. "
        "Ответы на вопросы установщику не нужны — он идёт по обычному пути "
        "обновления поверх.</p></div>"
    )

    if not allowed:
        parts.append(f'<div class="card warn">{html.escape(reason)}</div>')
        if not features.enabled("panel_update"):
            parts.append(
                '<div class="card">'
                '<form method="post" action="/features/toggle">'
                f'<input type="hidden" name="csrf" value="{html.escape(token)}">'
                '<input type="hidden" name="key" value="panel_update">'
                '<input type="hidden" name="back" value="/update">'
                '<button type="submit">Включить обновление из панели</button>'
                "</form>"
                "<p class=\"muted\">Чем это оплачено: контейнеру нужен сокет "
                "Docker, а сокет Docker внутри контейнера равносилен правам "
                "root на хосте — доступ к панели станет доступом к серверу. "
                "Выключить можно там же или в разделе «Возможности».</p>"
                "</div>"
            )
        elif "не хватает прав" in reason:
            # Самый частый случай на живом сервере: сокет проброшен, но
            # контейнер не в группе docker. Даём точные две команды —
            # искать их по документации в этот момент незачем.
            parts.append(
                '<div class="card muted">Контейнеру нужно передать номер '
                "группы <code>docker</code> с этой машины. На сервере, "
                "в каталоге установки:"
                "<pre class=\"log\">echo \"DOCKER_GID=$(getent group docker | "
                "cut -d: -f3)\" >> .env\n"
                "docker compose up -d --force-recreate</pre>"
                "Обновление установщиком делает это само — команды нужны "
                "только тем, кто обновлялся до 4.9.8.</div>"
            )
        elif "Сокет Docker" in reason or "RADAR_HOST_DIR" in reason:
            parts.append(
                '<div class="card muted">Контейнер запущен по старому '
                "docker-compose.yml. На сервере, в каталоге установки:"
                "<pre class=\"log\">docker compose up -d --force-recreate</pre>"
                "Перезапуска мало: сокет и путь установки прописаны в compose "
                "и подхватываются только при пересоздании контейнера.</div>"
            )
    elif running:
        parts.append(
            '<div class="card busy"><b>Обновление идёт.</b> '
            "<p class=\"muted\">Страница обновляется сама каждые пять секунд. "
            "На шаге пересборки панель ненадолго станет недоступна — "
            "это перезапускается сам контейнер бота. После возврата "
            "откройте эту страницу снова: журнал дочитается до конца.</p></div>"
        )
    else:
        parts.append(
            '<div class="card">'
            '<form method="post" action="/update/start">'
            f'<input type="hidden" name="csrf" value="{html.escape(token)}">'
            '<button type="submit" class="danger">Обновить систему</button>'
            "</form>"
            "<p class=\"muted\">Бот будет недоступен несколько минут: "
            "на одноплатнике сборка образа занимает больше всего времени. "
            "Оповещения в это время не рассылаются.</p></div>"
        )

    name, text = updater.progress(60)
    if text:
        parts.append(
            '<div class="card"><h2>Шаги установки</h2>'
            f'<p class="muted">Журнал: <code>{html.escape(name)}</code></p>'
            f"<pre class=\"log\">{html.escape(text)}</pre></div>"
        )
    else:
        parts.append('<div class="card muted">Журналов установки пока нет.</div>')

    return "".join(parts)


async def _rustdesk_body(session, ok: str = "", err: str = "") -> str:
    """Страница RustDesk: адрес и ключ, число подключений, управление.

    Панель повторяет права бота, а не расширяет их — но раздел бота
    делит доступ на три уровня (подписка / администрация / суперадмин),
    а в панель попадают только модератор и выше. Здесь всё за одним
    `@owner_only`: страница держит тот же риск, что «Обновление» —
    и то и другое ходит через сокет Docker.
    """
    from .. import rustdesk

    allowed, reason = rustdesk.ready()
    token = auth.csrf_token(session)
    parts: list[str] = [_note("ok", ok), _note("bad", err)]

    if not allowed:
        parts.append(f'<div class="card warn">{html.escape(reason)}</div>')
        if not features.enabled("rustdesk"):
            parts.append(
                '<div class="card">'
                '<form method="post" action="/features/toggle">'
                f'<input type="hidden" name="csrf" value="{html.escape(token)}">'
                '<input type="hidden" name="key" value="rustdesk">'
                '<input type="hidden" name="back" value="/rustdesk">'
                '<button type="submit">Включить RustDesk</button>'
                "</form>"
                '<p class="muted">Тот же сокет Docker, что и «Обновление '
                "из панели»: доступ к панели станет доступом к серверу. "
                "Выключить можно там же или в «Возможностях».</p>"
                "</div>"
            )
        return "".join(parts)

    # Контейнеров может не быть вовсе — установщик про RustDesk не спросил
    # или человек ответил «нет». Тогда кнопки управления бессмысленны:
    # они ответят «No such container». Показываем то, что реально нужно, —
    # две строки в .env и один запуск профиля.
    is_deployed, deploy_reason = await rustdesk.deployed()
    if not is_deployed:
        parts.append(
            f'<div class="card warn">{html.escape(deploy_reason)}</div>'
            '<div class="card"><p>Разверните сервер на хосте, в каталоге '
            "установки:</p>"
            '<pre class="log">RUSTDESK_ENABLED=1\n'
            "RUSTDESK_PUBLIC_HOST=внешний-адрес-или-домен</pre>"
            "<p>— дописать в <code>.env</code>, затем:</p>"
            '<pre class="log">docker compose --profile rustdesk up -d</pre>'
            '<p class="muted">Это же предлагает установщик при обновлении '
            "с терминала. Наружу откроются порты 21115-21119 — их нужно "
            "пробросить на роутере.</p></div>"
        )
        return "".join(parts)

    ok_info, info = rustdesk.client_info()
    if ok_info:
        parts.append(
            '<div class="card">'
            f'<p>ID Server: <code>{html.escape(info["host"])}:{info["id_port"]}</code></p>'
            f'<p>Relay Server: <code>{html.escape(info["host"])}:{info["relay_port"]}</code></p>'
            f'<p>Key:</p><pre class="log">{html.escape(info["key"])}</pre>'
            "</div>"
        )
    else:
        parts.append(f'<div class="card muted">{html.escape(str(info))}</div>')

    ok_conn, counts = await rustdesk.connection_counts()
    if ok_conn:
        parts.append(
            '<div class="card">'
            f'<p>hbbs (устройства онлайн): <b>{counts["hbbs"]}</b></p>'
            f'<p>hbbr (активные сессии): <b>{counts["hbbr"]}</b></p>'
            '<p class="muted">Оценка по установленным TCP-соединениям — '
            "открытая версия RustDesk не публикует эти числа официально."
            "</p></div>"
        )
    else:
        parts.append(f'<div class="card muted">{html.escape(str(counts))}</div>')

    buttons = "".join(
        '<form method="post" action="/rustdesk/action" style="display:inline">'
        f'<input type="hidden" name="csrf" value="{html.escape(token)}">'
        f'<input type="hidden" name="action" value="{action}">'
        f'<button type="submit" class="danger">{title}</button></form> '
        for action, title in (
            ("restart", "🔄 Перезапустить"),
            ("stop", "⏹ Остановить"),
            ("start", "▶️ Запустить"),
        )
    )
    parts.append(
        f'<div class="card">{buttons}'
        '<p class="muted">Действует на hbbs и hbbr вместе.</p></div>'
    )
    return "".join(parts)


def _maintenance_body() -> str:
    """Обслуживание: то, к чему обращаются редко и по делу.

    Копии, партнёры, возможности и журнал действий раньше висели в общем
    ряду разделов и мешали каждый день, а нужны раз в месяц. Здесь они
    собраны вместе, и рядом с каждым — то число, ради которого туда
    обычно и заходят.
    """
    from .. import backup as backup_core

    try:
        copies = backup_core.listing()
        last = copies[0].when if copies else "копий нет"
        copies_line = f"{len(copies)} шт., последняя: {last}"
    except Exception:  # noqa: BLE001
        copies_line = "список недоступен"

    try:
        active = sum(1 for flag in features.FLAGS if features.enabled(flag.key))
        flags_line = f"включено {active} из {len(features.FLAGS)}"
    except Exception:  # noqa: BLE001
        flags_line = ""

    items = [
        ("/backup", "Копии", "Снимок базы и настроек перед изменениями.",
         copies_line),
        ("/features", "Возможности", "Что включено в боте прямо сейчас.",
         flags_line),
        ("/audit", "Журнал действий", "Кто и что менял через панель.", ""),
    ]
    if features.enabled("partners"):
        items.append(("/partners", "Партнёры", "Проекты и промокоды.", ""))

    cards = "".join(
        f'<div class="card"><h3><a href="{href}">{html.escape(name)}</a></h3>'
        f'<p class="muted">{html.escape(about)}</p>'
        + (f'<p><b>{html.escape(extra)}</b></p>' if extra else "")
        + "</div>"
        for href, name, about, extra in items
    )
    return f'<div class="grid">{cards}</div>'


def _media_body() -> str:
    """Медиатека: треки и плейлисты по людям.

    Файлы лежат у каждого свои — общей библиотеки в системе нет
    и не будет. Поэтому здесь не список песен, а расход: у кого сколько
    занято, чтобы понимать, куда уходит диск одноплатника.
    """
    from .. import music

    rows = []
    total_tracks = 0
    total_bytes = 0
    for uid, user in storage.users().items():
        tracks = music.tracks_of(user)
        if not tracks:
            continue
        size = sum(int(item.get("size") or 0) for item in tracks)
        total_tracks += len(tracks)
        total_bytes += size
        name = user.get("username") or uid
        rows.append(
            f"<tr><td>@{html.escape(str(name))}</td>"
            f"<td>{len(tracks)}</td>"
            f"<td>{len(music.playlists_of(user))}</td>"
            f"<td>{html.escape(music.format_size(size))}</td></tr>"
        )

    if not rows:
        table = ('<div class="card muted">Треков пока никто не загружал. '
                 "Раздел включается возможностью «Музыка и плейлисты».</div>")
    else:
        table = ('<div class="card"><table><tr><th>Кто</th><th>Треков</th>'
                 "<th>Плейлистов</th><th>Занято</th></tr>"
                 + "".join(rows) + "</table></div>")

    state = "включена" if features.enabled("music") else "выключена"
    return (
        f'<div class="grid">'
        f'<div class="card metric"><b>{total_tracks}</b><span>треков всего</span></div>'
        f'<div class="card metric"><b>{html.escape(music.format_size(total_bytes))}</b>'
        f"<span>занято на диске</span></div>"
        f'<div class="card metric"><b>{html.escape(state)}</b>'
        f"<span>возможность «Музыка»</span></div></div>"
        f"{table}"
        '<div class="card muted">Каждый слушает только то, что загрузил сам: '
        "общей библиотеки нет намеренно — раздача чужих фонограмм превратила бы "
        "бота в пиратский сервис.</div>"
    )


def _safe_slug(value: str) -> str:
    """Только буквы, цифры, дефис и подчёркивание — для имени файла."""
    return re.sub(r"[^A-Za-z0-9_-]", "", str(value))[:32] or "export"


def _layout(title: str, body: str, active: str = "", role: str = "",
            role_key: str = "", refresh: int = 0) -> str:
    groups = _nav_groups(role_key)
    current = _active_group(groups, active)
    # Автообновление нужно ровно одной странице — той, где идёт обновление
    # системы: шаги дописываются в журнал, и человек должен видеть их
    # без нажатий. На остальных страницах перезагрузка мешала бы формам.
    meta_refresh = (f'<meta http-equiv="refresh" content="{int(refresh)}">'
                    if refresh else "")
    nav = "".join(
        f'<a href="{href}" class="{"active" if current and key == current[2] else ""}">'
        f"{name}</a>"
        for href, name, key, _items in groups
    )
    # Второй ряд рисуется только там, где есть из чего выбирать: у «Пользователей»
    # и «Источников» подпунктов нет, и пустая полоса под шапкой сбивала бы с толку.
    parent = _PARENT_PAGE.get(active)
    marked = parent[0] if parent else active
    subnav = ""
    if current and len(current[3]) > 1:
        subnav = '<div class="subnav">' + "".join(
            f'<a href="{href}" class="{"active" if key == marked else ""}">{name}</a>'
            for href, name, key in current[3]
        ) + "</div>"
    # Возврат к разделу, из которого сюда приходят. Ссылка, а не «назад»
    # браузера: на страницу могли попасть из закладки или из бота.
    back = ""
    if parent:
        back = (f'<a class="back" href="{parent[1]}">&larr; '
                f"{html.escape(parent[2])}</a>")
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
{meta_refresh}
<title>{html.escape(title)} — Радар</title>
<script>{THEME_SCRIPT}</script>
<style>{PAGE_STYLE}</style>
<style>{THEME_STYLE}</style></head>
<body>
<header>
  <span class="brand">Радар</span><span class="version">v{html.escape(config.VERSION)}</span>
  <nav>{nav}</nav>
  <span class="spacer"></span>
  <button id="theme" type="button" aria-label="Сменить тему">☀</button>
  <span class="who">{html.escape(role)} · <a href="/logout">выйти</a></span>
</header>
{subnav}
<main>{back}<h1>{html.escape(title)}</h1>{body}</main>
<script>{THEME_TOGGLE}</script>
<script>{LIVE_SCRIPT}</script>
</body></html>"""


def _login_page(bot_username: str, message: str = "",
                public_url: str = "") -> str:
    warning = f'<p class="bad">{html.escape(message)}</p>' if message else ""
    widget = (
        f'<script async src="https://telegram.org/js/telegram-widget.js?22" '
        f'data-telegram-login="{html.escape(bot_username)}" data-size="large" '
        f'data-auth-url="/auth" data-request-access="write"></script>'
        if bot_username else
        '<p class="warn">Имя бота не определено — вход недоступен.</p>'
    )
    # Подсказка про домен. Виджет Telegram при непривязанном домене
    # показывает только «Bot domain invalid» — и по этой надписи нельзя
    # догадаться, что делать. Ошибка не наша: домен привязывается
    # у BotFather, и никакая настройка на сервере её не снимет.
    hint = (
        '<details class="muted" style="margin-top:18px;text-align:left">'
        '<summary>Кнопка не работает или пишет «Bot domain invalid»?</summary>'
        '<p>Домен нужно привязать к боту — это делается в Telegram, '
        'а не на сервере:</p>'
        '<ol>'
        '<li>Откройте <b>@BotFather</b></li>'
        '<li>Команда <code>/setdomain</code></li>'
        '<li>Выберите своего бота'
        + (f' (<b>@{html.escape(bot_username)}</b>)' if bot_username else '')
        + '</li>'
        '<li>Пришлите адрес панели: <code>' + html.escape(public_url or
          'https://ваш-домен') + '</code></li>'
        '</ol>'
        '<p>Адрес должен совпадать точно — со схемой <code>https://</code> '
        'и без пути в конце. По IP-адресу вход через Telegram '
        '<b>не работает вовсе</b>: виджет принимает только домены.</p>'
        '</details>'
    )

    # Тема выбирается и здесь: вход — первая страница, которую человек
    # видит, и встречать его чужой темой было бы странно.
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Вход — Радар</title>
<script>{THEME_SCRIPT}</script>
<style>{PAGE_STYLE}</style>
<style>{THEME_STYLE}</style></head>
<body><div class="login">
<h1>Панель системы «Радар»</h1>
<p class="muted">Версия {html.escape(config.VERSION)}</p>
<p class="muted">Вход через Telegram. Доступ — с роли администратора.</p>
{warning}{widget}{hint}
</div></body></html>"""


# --------------------------------------------------------------------------
#  Данные для страниц
# --------------------------------------------------------------------------

def _overview_body() -> str:
    users = storage.users()
    locations = sum(len(item.get("locs") or []) for item in users.values())
    by_role: dict[str, int] = {}
    for item in users.values():
        by_role[item.get("role", "user")] = by_role.get(item.get("role", "user"), 0) + 1

    metrics = [
        ("Пользователей", len(users)),
        ("Локаций", locations),
        ("Каналов", len(storage.channels())),
        ("Лент RSS", len(storage.rss_feeds())),
        ("Сообществ VK", len(storage.vk_groups())),
        ("Сессий панели", auth.active_sessions()),
    ]
    cards = "".join(
        f'<div class="card metric"><b>{value}</b><span>{html.escape(name)}</span></div>'
        for name, value in metrics
    )

    roles_rows = "".join(
        f"<tr><td>{html.escape(roles.title(key))}</td><td>{count}</td></tr>"
        for key, count in sorted(by_role.items())
    )
    return (
        f'<div class="grid">{cards}</div>'
        f"{_bot_and_server()}"
        f'<div class="card"><h3>Роли</h3><table>'
        f"<tr><th>Роль</th><th>Человек</th></tr>{roles_rows}</table></div>"
    )


def _human_time(seconds: float) -> str:
    seconds = int(max(0, seconds))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days} д {hours} ч"
    if hours:
        return f"{hours} ч {minutes} мин"
    return f"{minutes} мин"


def _bot_and_server() -> str:
    """Состояние самого бота и машины под ним.

    До 4.9.8 обзор показывал только пересчёт сущностей — сколько
    пользователей и лент. На вопрос «почему бот тормозит» он не отвечал
    вовсе, и приходилось идти по SSH. Показания снимаются с /proc
    средствами `radar/profiling.py`, без лишних зависимостей.
    """
    import shutil

    from .. import profiling

    try:
        memory = profiling.memory_mb()
        cpu = profiling.cpu_seconds()
        one, five, fifteen = profiling.load_average()
        cores = profiling.cpu_count() or 1
        alive = profiling.uptime()
    except Exception:  # noqa: BLE001
        log.warning("Показания производительности недоступны", exc_info=True)
        return '<div class="card muted">Показания сервера недоступны.</div>'

    # Нагрузка сама по себе ничего не говорит: 2.0 на четырёх ядрах — это
    # половина машины, а на одном — двойная очередь. Показываем долю.
    share = one / cores * 100
    load_class = "ok" if share < 70 else ("warn" if share < 110 else "bad")

    try:
        usage = shutil.disk_usage("data")
        free_gb = usage.free / 1024 ** 3
        used_share = (usage.used / usage.total * 100) if usage.total else 0
        disk_class = "ok" if used_share < 80 else ("warn" if used_share < 92 else "bad")
        disk = (f'<tr><td>Диск</td><td class="{disk_class}">'
                f"занято {used_share:.0f}%, свободно {free_gb:.1f} ГБ</td></tr>")
    except OSError:
        disk = '<tr><td>Диск</td><td class="muted">не определён</td></tr>'

    database = "PostgreSQL" if config.DB_BACKEND == "postgres" else "SQLite"
    api = "свой Bot API Server" if config.uses_local_api() else "общий Telegram"

    return (
        '<div class="card"><h3>Бот</h3><table>'
        f"<tr><td>Версия</td><td><b>{html.escape(config.VERSION)}</b></td></tr>"
        f"<tr><td>Работает без перезапуска</td><td>{_human_time(alive)}</td></tr>"
        f"<tr><td>Память процесса</td><td>{memory:.0f} МБ</td></tr>"
        f"<tr><td>Процессорное время</td><td>{_human_time(cpu)}</td></tr>"
        f"<tr><td>База</td><td>{database}</td></tr>"
        f"<tr><td>Отправка файлов</td><td>{api}</td></tr>"
        "</table></div>"
        '<div class="card"><h3>Сервер</h3><table>'
        f'<tr><td>Нагрузка</td><td class="{load_class}">{one:.2f} / {five:.2f} / '
        f"{fifteen:.2f} <span class=\"muted\">({share:.0f}% от {cores} "
        f"ядер)</span></td></tr>"
        f"{disk}"
        "</table>"
        '<p class="muted">Три числа — средняя очередь за 1, 5 и 15 минут. '
        "Растущее первое при спокойном третьем значит, что нагрузка "
        "только что появилась.</p></div>"
    )


def _users_body(session, message: str = "", failed: str = "") -> str:
    """Список пользователей с правкой времени.

    Модератору идентификаторы показываются частично: для его задач они
    не нужны, а утечка списка — лишний риск.

    Часовой пояс и время погоды правятся здесь же. В боте это делает сам
    человек; администрации оно нужно, когда правит не он — по просьбе или
    при разборе «почему сводка пришла ночью».
    """
    from .. import timezones

    role = session.role
    full = roles.is_admin(role)
    token = auth.csrf_token(session)
    editable = roles.is_moderator(role)

    rows = []
    for key, item in sorted(storage.users().items()):
        locations = item.get("locs") or []
        cities = ", ".join(
            sorted({str(loc.get("city") or "") for loc in locations if loc.get("city")})
        )
        lang = "en" if str(item.get("lang") or "").startswith("en") else "ru"
        zone = timezones.user_label(item, lang)
        if not timezones.chosen(item):
            zone += " (серверный)"
        moment = (str(item.get("weather_time") or "08:00")
                  if item.get("weather_mode") == "time" else "—")

        form = ""
        if editable:
            options = "".join(
                f'<option value="{timezones.render(minutes)}"'
                f'{" selected" if minutes == timezones.offset_of(item) else ""}>'
                f"{html.escape(timezones.label(minutes, lang))}</option>"
                for minutes in timezones.WHOLE_HOURS
            )
            form = (
                '<form class="inline" method="post" action="/users/time">'
                f'<input type="hidden" name="csrf" value="{token}">'
                f'<input type="hidden" name="user" value="{html.escape(key)}">'
                f'<select name="tz">{options}</select>'
                '<input type="text" name="weather_time" placeholder="08:00" '
                'pattern="[0-2][0-9]:[0-5][0-9]" style="flex:0 0 90px">'
                '<button class="ghost" type="submit">Сохранить</button></form>'
            )

        # data-label — имя столбца для узкого экрана: там таблица
        # разворачивается в карточки, заголовок скрыт, и без подписи
        # осталась бы колонка безымянных значений.
        rows.append(
            f'<tr><td data-label="Ключ">'
            f"<code>{html.escape(key if full else key[:4] + '…')}</code></td>"
            f'<td data-label="Роль">'
            f"{html.escape(roles.title(item.get('role', 'user')))}</td>"
            f'<td data-label="Локаций">{len(locations)}</td>'
            f'<td data-label="Города">{html.escape(cities or "—")}</td>'
            f'<td data-label="Время">{html.escape(zone)}<br>'
            f'<span class="muted">погода: {html.escape(moment)}</span>{form}</td></tr>'
        )

    return (
        _note("ok", message) + _note("bad", failed)
        + '<div class="card"><table class="stack"><thead>'
        '<tr><th>Ключ</th><th>Роль</th>'
        f"<th>Локаций</th><th>Города</th><th>Время</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        '<p class="muted">Пустое поле времени оставляет прежнее. По выбранному '
        "поясу считаются тихие часы, время погоды и доставка подборок.</p>"
        "</div>"
    )


def _note(kind: str, text: str) -> str:
    """Полоса с итогом действия. Пусто — ничего не показываем."""
    if not text:
        return ""
    css = "good" if kind == "ok" else "bad"
    return f'<div class="note {css}">{html.escape(text)}</div>'


def _sources_body(session, message: str = "", failed: str = "") -> str:
    """Источники: список с удалением и форма добавления.

    Правка открыта модератору — ровно как в боте. Панель повторяет права
    бота, а не расширяет их: иначе роль означала бы разное в двух местах.
    """
    from .. import sourceedit as se

    editable = roles.is_moderator(session.role)
    token = auth.csrf_token(session)

    def rows(kind: str, items: list[str]) -> str:
        if not items:
            return '<tr><td class="muted">пусто</td></tr>'
        out = []
        for item in items:
            action = ""
            if editable:
                action = (
                    '<form method="post" action="/sources/remove" '
                    'style="display:inline">'
                    f'<input type="hidden" name="csrf" value="{token}">'
                    f'<input type="hidden" name="kind" value="{html.escape(kind)}">'
                    f'<input type="hidden" name="value" value="{html.escape(item)}">'
                    '<button class="ghost" type="submit">удалить</button></form>'
                )
            out.append(
                f"<tr><td>{html.escape(item)}</td>"
                f'<td style="text-align:right;width:1%">{action}</td></tr>'
            )
        return "".join(out)

    def card(kind: str, title: str, placeholder: str) -> str:
        items = se.listing(kind)
        form = ""
        if editable:
            form = (
                '<form class="inline" method="post" action="/sources/add">'
                f'<input type="hidden" name="csrf" value="{token}">'
                f'<input type="hidden" name="kind" value="{html.escape(kind)}">'
                f'<input type="text" name="value" placeholder="{html.escape(placeholder)}" '
                'required autocomplete="off">'
                '<button type="submit">Добавить</button></form>'
            )
        return (
            f'<div class="card"><h3>{html.escape(title)} — {len(items)}</h3>'
            f"<table>{rows(kind, items)}</table>{form}</div>"
        )

    pending = list(storage.pending())
    queue_rows = "".join(
        f"<tr><td>{html.escape(item)}</td></tr>" for item in pending
    ) or '<tr><td class="muted">пусто</td></tr>'

    return (
        _note("ok", message)
        + _note("bad", failed)
        + card(se.TELEGRAM, "Telegram-каналы",
               "@channel, ссылка t.me или несколько через запятую")
        + card(se.RSS, "RSS-ленты", "https://example.ru/rss")
        + card(se.VK, "Сообщества VK", "короткое имя или ссылка vk.com/…")
        + '<div class="card"><h3>В очереди модерации — '
        + str(len(pending))
        + f"</h3><table>{queue_rows}</table>"
        + '<p class="muted">Очередь разбирается в боте: предложение '
          "пользователя принимается или отклоняется там, вместе с ответом "
          "приславшему.</p></div>"
    )


def _files_body(session, message: str = "", failed: str = "") -> str:
    """Раздача крупных файлов: кому выдана ссылка, забрали ли, сколько живёт.

    Панель — единственное место, где эту раздачу видно целиком. В боте
    человек видит свою ссылку и всё; администрации нужен обзор: чей файл,
    сколько занимает, скачали или нет, сколько осталось до сгорания.
    """
    from .. import filedrop, roles as roles_module, subscription

    token = auth.csrf_token(session)
    items = [item for item in filedrop.listing() if item.hours_left > 0]

    if not filedrop.enabled():
        return (
            '<div class="card"><b>Раздача выключена.</b> '
            '<span class="muted">Нужен внешний адрес: задайте '
            '<code>SHORT_BASE_URL</code> в разделе ключей. Без него ссылка '
            "вела бы в никуда, поэтому бот её не предлагает.</span></div>"
        )

    total_mb = sum(item.size for item in items) / 1024 / 1024
    head = (
        '<div class="grid">'
        f'<div class="card metric"><b>{len(items)}</b>'
        "<span>файлов в раздаче</span></div>"
        f'<div class="card metric"><b>{total_mb:.0f} МБ</b>'
        f"<span>занято из {filedrop.BUDGET_MB} МБ</span></div>"
        f'<div class="card metric"><b>{filedrop.MAX_FILE_MB // 1024} ГБ</b>'
        "<span>предел на один файл</span></div>"
        f'<div class="card metric"><b>{filedrop.TTL_HOURS} ч</b>'
        "<span>срок жизни ссылки</span></div>"
        "</div>"
    )

    if not items:
        return (_note("ok", message) + _note("bad", failed) + head
                + '<div class="card muted">Сейчас в раздаче пусто.</div>')

    rows = []
    for item in items:
        user = storage.get_user(item.owner) if item.owner else None
        if user is None:
            who = '<span class="muted">неизвестен</span>'
            plan = '<span class="muted">—</span>'
        else:
            name = user.get("username") or item.owner
            who = f"{html.escape(str(name))} "
            who += f'<span class="muted">{html.escape(roles_module.title(user.get("role", "")))}</span>'
            active = subscription.active(user, user.get("role"))
            plan = ('<span class="ok">подписка</span>' if active
                    else '<span class="muted">без подписки</span>')

        taken = (f'<span class="ok">забрали, раз: {item.hits}</span>'
                 if item.hits else '<span class="warn">ещё не скачан</span>')
        link = html.escape(filedrop.url_for(item))
        rows.append(
            "<tr>"
            f'<td><a href="{link}">{html.escape(item.name)}</a><br>'
            f'<span class="muted">{item.size_mb:.0f} МБ</span></td>'
            f"<td>{who}<br>{plan}</td>"
            f"<td>{taken}</td>"
            f"<td>{item.hours_left:.1f} ч</td>"
            '<td style="text-align:right;width:1%">'
            '<form method="post" action="/files/remove">'
            f'<input type="hidden" name="csrf" value="{token}">'
            f'<input type="hidden" name="token" value="{item.token}">'
            '<button class="ghost danger" type="submit">отключить</button>'
            "</form></td></tr>"
        )

    table = (
        '<div class="card"><table><tr>'
        "<th>Файл</th><th>Кому выдана</th><th>Состояние</th>"
        "<th>Осталось</th><th></th></tr>"
        + "".join(rows) + "</table>"
        '<p class="muted">Ссылка — секрет: проверить учётную запись '
        "Telegram при запросе из браузера невозможно, поэтому скачает тот, "
        "кому её переслали. «Отключить» удаляет файл сразу, не дожидаясь "
        "конца срока.</p></div>"
    )
    return _note("ok", message) + _note("bad", failed) + head + table


async def _links_body(session, message: str = "", failed: str = "") -> str:
    """Сокращённые ссылки: кто завёл, куда ведёт, живы ли переходы.

    Страница построена по образцу «Файлов»: ссылки бессрочные, и без
    обзора они копились бы в таблице бесконечно. Выборочное удаление —
    только здесь: в боте ссылки целиком не видны, и чистить по одной
    оттуда значило бы чистить вслепую.
    """
    from ..db import repo

    token = auth.csrf_token(session)
    try:
        items = await repo.short_link_list()
    except Exception:  # noqa: BLE001
        return _note("bad", "Список ссылок недоступен — смотрите журнал.")

    if not items:
        return (_note("ok", message) + _note("bad", failed)
                + '<div class="card muted">Сокращённых ссылок нет.</div>')

    rows = []
    for item in items:
        creator = item.get("created_by") or 0
        owner = storage.get_user(creator) if creator else None
        if owner is not None:
            name = owner.get("username") or creator
            who = html.escape(str(name))
        elif creator:
            who = '<span class="muted">неизвестен</span>'
        else:
            who = '<span class="muted">подборки (авто)</span>'
        hits = int(item.get("hits") or 0)
        hits_line = (f'<span class="ok">переходов: {hits}</span>' if hits
                     else '<span class="muted">переходов нет</span>')
        short = html.escape(shortener.short_url(str(item["code"])))
        rows.append(
            "<tr>"
            f'<td><a href="{short}"><code>{html.escape(str(item["code"]))}</code></a></td>'
            f'<td style="max-width:22em;overflow:hidden;text-overflow:ellipsis;'
            f'white-space:nowrap"><span title="{html.escape(str(item["url"])[:300])}">'
            f'{html.escape(str(item["url"])[:90])}</span></td>'
            f"<td>{who}</td>"
            f"<td>{hits_line}</td>"
            '<td style="text-align:right;width:1%">'
            '<form method="post" action="/links/remove">'
            f'<input type="hidden" name="csrf" value="{token}">'
            f'<input type="hidden" name="code" value="{html.escape(str(item["code"]))}">'
            '<button class="ghost danger" type="submit">удалить</button>'
            "</form></td></tr>"
        )

    table = (
        '<div class="card"><table><tr>'
        "<th>Код</th><th>Куда ведёт</th><th>Кем создана</th>"
        "<th>Переходы</th><th></th></tr>"
        + "".join(rows) + "</table></div>"
    )

    clear_all = (
        '<div class="card"><b>Удалить все ссылки.</b> '
        '<span class="muted">Разосланные в старых сообщениях перестанут '
        "открываться; автоссылки подборок появятся снова при следующем "
        "выпуске.</span>"
        '<form method="post" action="/links/clear">'
        f'<input type="hidden" name="csrf" value="{token}">'
        '<button class="ghost danger" type="submit">удалить все</button>'
        "</form></div>"
    )
    return _note("ok", message) + _note("bad", failed) + table + clear_all


async def _models_section(session) -> str:
    """Выбор модели у встроенных провайдеров, где он вообще есть.

    У OpenRouter моделей десятки, и вписывать имя руками — верный способ
    опечататься так, что выяснится это при первом разборе настоящей
    тревоги. Список спрашивается у самого провайдера; если он не ответил,
    остаётся поле для ручного ввода — отказать было бы хуже.
    """
    from .. import provider

    token = auth.csrf_token(session)
    cards = []
    for info in provider.available():
        if info.custom or info.kind != provider.KIND_OPENAI:
            continue
        current = provider.model_of(info.key)
        try:
            models = await provider.list_models(info.key)
        except Exception:  # noqa: BLE001
            log.debug("Список моделей %s недоступен", info.key, exc_info=True)
            models = []

        if models:
            options = "".join(
                f'<option value="{html.escape(name)}"'
                f'{" selected" if name == current else ""}>{html.escape(name)}'
                "</option>"
                for name in models
            )
            field = (f'<select name="model"><option value="">— по умолчанию —'
                     f"</option>{options}</select>")
            note = f"Список получен у провайдера: {len(models)} моделей."
        else:
            field = (f'<input type="text" name="model" maxlength="120" '
                     f'value="{html.escape(current)}">')
            note = ("Список моделей получить не вышло — впишите имя руками.")

        cards.append(
            f'<div class="card"><h3>{html.escape(info.title)}</h3>'
            f'<div class="hint">{html.escape(note)}</div>'
            '<form class="inline" method="post" action="/agents/model">'
            f'<input type="hidden" name="csrf" value="{token}">'
            f'<input type="hidden" name="provider" value="{html.escape(info.key)}">'
            + field
            + '<button type="submit">Сохранить</button></form></div>'
        )

    if not cards:
        return ""
    return ('<div class="card"><b>Модели встроенных провайдеров</b> '
            '<span class="muted">— список подтягивается у самого сервиса, '
            "поэтому опечатка в имени модели больше не доживёт до первой "
            "тревоги.</span></div>" + "".join(cards))


async def _agents_body(session, message: str = "", failed: str = "") -> str:
    """Свои агенты: название, адрес, ключ. Без ограничения по числу.

    Бот показывает первые пять слотов — в переписке длинный список неудобен.
    Здесь предела нет: панель для того и нужна, чтобы держать то, что
    в переписку не помещается.
    """
    from .. import agents

    token = auth.csrf_token(session)
    items = agents.load()

    def form(agent) -> str:
        new = agent is None
        slot = agents.free_slot() if new else agent.slot
        if new and not slot:
            return ""
        heading = ("➕ Новый агент" if new
                   else f"{agent.shown} — слот {agent.slot}")
        state = ""
        if not new:
            state = ('<div class="hint ok">готов к работе</div>'
                     if agent.ready else
                     '<div class="hint warn">нужны и адрес, и ключ</div>')
        legacy = ""
        if not new and agent.legacy:
            legacy = ('<div class="hint">Достался от прежней настройки '
                      "(CUSTOM_AI_URL/KEY). Сохраните — и он переедет "
                      "в обычный слот.</div>")
        return (
            f'<div class="card"><h3>{html.escape(heading)}</h3>{state}{legacy}'
            '<form method="post" action="/agents/save">'
            f'<input type="hidden" name="csrf" value="{token}">'
            f'<input type="hidden" name="slot" value="{slot}">'
            '<div class="keyrow"><div><b>Название</b></div>'
            '<div class="hint">Как агент будет показан в списке моделей.</div>'
            f'<input type="text" name="title" maxlength="32" '
            f'value="{html.escape("" if new else agent.title)}"></div>'
            '<div class="keyrow"><div><b>Базовый адрес</b></div>'
            '<div class="hint">Без /chat/completions, например '
            "http://ollama:11434/v1</div>"
            f'<input type="url" name="url" required maxlength="300" '
            f'value="{html.escape("" if new else agent.url)}"></div>'
            '<div class="keyrow"><div><b>Ключ API</b></div>'
            '<div class="hint">Сейчас: '
            f'{html.escape(secrets_module.mask("" if new else agent.key))}. '
            "Пустое поле оставит прежний ключ; сервису без ключа годится "
            "любая непустая строка.</div>"
            '<input type="password" name="key" autocomplete="off" '
            'placeholder="новое значение"></div>'
            '<div class="keyrow"><div><b>Модель</b></div>'
            '<div class="hint">Имя модели у этого сервиса, например '
            "llama3.1:8b. У своего сервиса списка моделей не спросить — "
            "вписывается руками.</div>"
            f'<input type="text" name="model" maxlength="120" '
            f'value="{html.escape("" if new else agent.model)}"></div>'
            '<div class="inline" style="margin-top:14px">'
            '<button type="submit">Сохранить</button></div></form>'
            + ("" if new else
               '<form method="post" action="/agents/remove" '
               'style="margin-top:10px">'
               f'<input type="hidden" name="csrf" value="{token}">'
               f'<input type="hidden" name="slot" value="{agent.slot}">'
               '<button class="ghost danger" type="submit">Удалить агента'
               "</button></form>")
            + "</div>"
        )

    picked = await _models_section(session)

    head = (
        '<div class="card"><b>Свои агенты</b> '
        '<span class="muted">— любой сервис с совместимым с OpenAI '
        "интерфейсом: локальная модель, корпоративный шлюз, свой прокси. "
        f"Первые {agents.BOT_SLOTS} слотов правятся и в боте, остальные — "
        "только здесь. Ключ показывается маской и не отдаётся наружу, "
        "как и остальные ключи.</span></div>"
    )
    return (_note("ok", message) + _note("bad", failed) + head
            + "".join(form(item) for item in items) + form(None) + picked)


def _keys_body(session, message: str = "", failed: str = "") -> str:
    """Ключи ИИ и токены сервисов. Только запись, без чтения.

    Значение показывается маской: перехваченная сессия панели не должна
    отдавать ключи целиком. Проверить «тот ли ключ вставлен» по маске
    можно — по первым и последним знакам, — а увести его нельзя.
    """
    token = auth.csrf_token(session)
    groups: dict[str, list] = {}
    for setting in secrets_module.SETTINGS:
        groups.setdefault(setting.group, []).append(setting)

    cards = []
    for group, items in groups.items():
        rows = []
        for setting in items:
            current = secrets_module.get(setting.key)
            shown = (secrets_module.mask(current) if setting.secret
                     else (current or "— не задано —"))
            where = (f' <span class="hint">Где взять: {html.escape(setting.where)}</span>'
                     if setting.where else "")
            restart = (' <span class="warn">применится после перезапуска</span>'
                       if setting.restart else "")
            field = "password" if setting.secret else "text"
            rows.append(
                '<div class="keyrow">'
                f"<div><b>{html.escape(setting.title)}</b> "
                f'<span class="muted">{html.escape(setting.key)}</span></div>'
                f'<div class="hint">{html.escape(setting.hint)}{where}{restart}</div>'
                f'<div class="hint">Сейчас: {html.escape(shown)}</div>'
                '<form class="inline" method="post" action="/keys/set">'
                f'<input type="hidden" name="csrf" value="{token}">'
                f'<input type="hidden" name="key" value="{html.escape(setting.key)}">'
                f'<input type="{field}" name="value" autocomplete="off" '
                'placeholder="новое значение, пусто — очистить">'
                '<button type="submit">Сохранить</button></form>'
                "</div>"
            )
        cards.append(
            f'<div class="card"><h3>{html.escape(group)}</h3>{"".join(rows)}</div>'
        )

    warning = (
        '<div class="card"><b>Значения не показываются.</b> '
        '<span class="muted">Панель принимает новый ключ, но не отдаёт '
        "существующий: доступ к чужой сессии не должен означать доступ "
        "ко всем ключам сразу. Полное значение видно только в файле "
        "<code>.env</code> на сервере.</span></div>"
    )
    return _note("ok", message) + _note("bad", failed) + warning + "".join(cards)



def _project_form(project, token: str, kinds) -> str:
    """Форма одного проекта. Пустой project — форма добавления."""
    new = project is None
    slug = "" if new else project.slug
    heading = ("➕ Новый проект" if new
               else f"{project.icon} {project.title}")

    def field(name: str, label: str, value: str, kind: str = "text",
              hint: str = "", extra: str = "") -> str:
        return (
            '<div class="keyrow">'
            f"<div><b>{html.escape(label)}</b></div>"
            + (f'<div class="hint">{html.escape(hint)}</div>' if hint else "")
            + f'<input type="{kind}" name="{name}" value="{html.escape(value)}" '
              f"{extra}></div>"
        )

    if new:
        identity = field(
            "slug", "Короткое имя", "",
            hint="Латиница, цифры и дефис. Менять потом нельзя: "
                 "по нему считаются переходы и выданные промокоды.",
            extra='required autocomplete="off" pattern="[a-z0-9-]{2,32}"',
        )
    else:
        identity = (
            f'<input type="hidden" name="slug" value="{html.escape(slug)}">'
            f'<div class="keyrow"><div><b>Короткое имя</b> '
            f'<span class="muted">{html.escape(slug)}</span></div>'
            '<div class="hint">Не меняется: по нему считаются переходы '
            "и выданные промокоды.</div></div>"
        )

    options = "".join(
        f'<option value="{html.escape(key)}"'
        f'{" selected" if (not new and project.promo_kind == key) else ""}>'
        f"{html.escape(title)}</option>"
        for key, title in kinds.items()
    )
    checked = "" if new else (" checked" if project.visible else "")
    description = "" if new else project.description
    terms = "" if new else project.promo_terms

    return (
        f'<div class="card"><h3>{html.escape(heading)}</h3>'
        '<form method="post" action="/partners/save">'
        f'<input type="hidden" name="csrf" value="{token}">'
        + identity
        + field("title", "Название", "" if new else project.title,
                hint="То, что видит человек в списке проектов.",
                extra='required maxlength="48"')
        + field("url", "Ссылка", "" if new else project.url,
                hint="http, https или tg://resolve?domain=…",
                extra='required maxlength="500"')
        + field("icon", "Значок", "🔗" if new else project.icon,
                hint="Один символ или эмодзи.", extra='maxlength="4"')
        + '<div class="keyrow"><div><b>Описание</b></div>'
          '<div class="hint">Показывается под названием. '
          "Повтор названия из первой строки убирается сам.</div>"
          f'<textarea name="description" maxlength="300">'
          f"{html.escape(description)}</textarea></div>"
        + field("order", "Порядок", "100" if new else str(project.order),
                kind="text",
                hint="Меньше — выше в списке.", extra='maxlength="5"')
        + '<div class="keyrow"><label><input type="checkbox" name="visible" '
          f'value="1"{checked}> Показывать в боте</label></div>'
        + '<div class="keyrow"><div><b>Промокод</b></div>'
          f'<select name="promo_kind">{options}</select></div>'
        + field("promo_value", "Код (один на всех)",
                "" if new else project.promo_value,
                hint="Заполняется только для режима «один на всех».",
                extra='maxlength="64"')
        + field("promo_prefix", "Приставка (для своих кодов)",
                "" if new else project.promo_prefix,
                hint="Например HYDRA. Код будет вида HYDRA-XXXX.",
                extra='maxlength="12"')
        + '<div class="keyrow"><div><b>Условия промокода</b></div>'
          f'<textarea name="promo_terms" maxlength="600">'
          f"{html.escape(terms)}</textarea></div>"
        + '<div class="inline" style="margin-top:14px">'
          '<button type="submit">Сохранить</button></div></form>'
        + ("" if new else
           '<form method="post" action="/partners/remove" '
           'style="margin-top:10px">'
           f'<input type="hidden" name="csrf" value="{token}">'
           f'<input type="hidden" name="slug" value="{html.escape(slug)}">'
           '<button class="ghost danger" type="submit">Удалить проект</button>'
           "</form>")
        + "</div>"
    )


async def _partners_body(session, message: str = "", failed: str = "") -> str:
    """Партнёрские проекты: список, правка, добавление.

    Панель повторяет то, что доступно в боте, а не расширяет права:
    раздел открыт суперадминистратору, как и правка в боте. До 4.8.7 здесь
    была одна таблица и подпись «правка — в боте»: заводить проект
    с описанием в переписке неудобно, а в панели поле описания видно
    целиком.
    """
    from .. import partners

    token = auth.csrf_token(session)
    try:
        projects = partners.order_projects(await partners.load())
    except Exception as exc:  # noqa: BLE001
        return f'<div class="card bad">Список недоступен: {html.escape(str(exc))}</div>'

    rows = []
    for project in projects:
        state = ('<span class="ok">виден</span>' if project.visible
                 else '<span class="muted">скрыт</span>')
        kind = partners.KIND_TITLES.get(project.promo_kind, "—")
        issued = ""
        if project.has_promo and features.enabled("promo_codes"):
            try:
                from ..db import repo

                count = await repo.promo_count(project.slug)
                issued = (
                    f'<a href="/partners/export?slug={html.escape(project.slug)}">'
                    f"выгрузить ({count})</a>"
                )
            except Exception:  # noqa: BLE001
                issued = '<span class="muted">недоступно</span>'
        rows.append(
            "<tr>"
            f"<td>{html.escape(project.icon)} {html.escape(project.title)}</td>"
            f'<td><a href="{html.escape(project.url)}" rel="noopener noreferrer" '
            f'target="_blank">{html.escape(project.url[:48])}</a></td>'
            f"<td>{state}</td><td>{project.clicks}</td>"
            f"<td>{html.escape(kind)}</td><td>{issued}</td>"
            "</tr>"
        )

    table = (
        '<div class="card"><h3>Проекты — ' + str(len(projects)) + "</h3><table>"
        "<tr><th>Проект</th><th>Ссылка</th><th>Показ</th><th>Переходы</th>"
        "<th>Промокод</th><th>Коды</th></tr>"
        + ("".join(rows) or '<tr><td class="muted">пусто</td></tr>')
        + "</table>"
        '<p class="muted">Выгрузка кодов содержит только код и дату выдачи, '
        "без идентификаторов пользователей.</p></div>"
    ) if projects else ""

    forms = "".join(_project_form(item, token, partners.KIND_TITLES)
                    for item in projects)
    add = ("" if len(projects) >= partners.MAX_PROJECTS
           else _project_form(None, token, partners.KIND_TITLES))
    limit = ("" if len(projects) < partners.MAX_PROJECTS else
             '<div class="card muted">Достигнут предел в '
             f"{partners.MAX_PROJECTS} проектов — удалите ненужный, "
             "чтобы добавить новый.</div>")

    return (_note("ok", message) + _note("bad", failed)
            + table + forms + add + limit)


async def _events_body() -> str:
    try:
        from ..db import repo

        stats = await repo.event_stats(days=7)
    except Exception as exc:  # noqa: BLE001
        return f'<div class="card bad">История недоступна: {html.escape(str(exc))}</div>'

    return (
        '<div class="grid">'
        f'<div class="card metric"><b>{stats["events"]}</b>'
        "<span>событий за неделю</span></div>"
        f'<div class="card metric"><b>{stats["deliveries"]}</b>'
        "<span>доставок за неделю</span></div>"
        "</div>"
        '<div class="card muted">Лента событий по адресам доступна в боте: '
        "карточка локации → «Что было по этому адресу».</div>"
    )


def _features_body(session, message: str = "", failed: str = "") -> str:
    """Возможности с переключателями.

    До 4.9.1 панель их только показывала, а подпись объясняла это тем, что
    «критичные переключатели остаются за подтверждённым каналом». Довод
    не выдержал проверки: вход в панель — тот же Telegram Login, та же
    учётная запись и та же роль, что в боте. Разница была не в надёжности,
    а в том, что форм у панели тогда не было вовсе.

    Права те же, что в боте: переключает только суперадминистратор.
    """
    token = auth.csrf_token(session)
    editable = roles.is_superadmin(session.role)

    rows = []
    for group, items in features.by_group().items():
        rows.append(f'<tr><th colspan="3">{html.escape(group)}</th></tr>')
        for flag in items:
            on = features.enabled(flag.key)
            state = (
                '<span class="muted">всегда включено</span>' if flag.locked
                else ('<span class="ok">включено</span>' if on
                      else '<span class="muted">выключено</span>')
            )
            action = ""
            if editable and not flag.locked:
                action = (
                    '<form method="post" action="/features/toggle">'
                    f'<input type="hidden" name="csrf" value="{token}">'
                    f'<input type="hidden" name="key" value="{html.escape(flag.key)}">'
                    f'<button class="ghost" type="submit">'
                    f'{"выключить" if on else "включить"}</button></form>'
                )
            since = (f' <span class="muted">с {html.escape(flag.since)}</span>'
                     if flag.since else "")
            rows.append(
                f"<tr><td>{html.escape(flag.title)}{since}<br>"
                f'<span class="muted">{html.escape(flag.description)}</span></td>'
                f"<td>{state}</td>"
                f'<td style="text-align:right;width:1%">{action}</td></tr>'
            )

    note = (
        '<div class="card muted">Переключать может суперадминистратор — '
        "здесь и в боте, командой /features. Режим обслуживания "
        "останавливает рассылку оповещений: включайте его понимая это.</div>"
        if editable else
        '<div class="card muted">Переключение доступно '
        "суперадминистратору.</div>"
    )
    return (_note("ok", message) + _note("bad", failed)
            + f'<div class="card"><table>{"".join(rows)}</table></div>' + note)


def _audit_body() -> str:
    from . import audit

    rows = "".join(
        f"<tr><td>{html.escape(item.when)}</td>"
        f"<td><code>{html.escape(item.actor)}</code></td>"
        f"<td>{html.escape(item.action)}</td>"
        f"<td>{html.escape(item.detail)}</td></tr>"
        for item in audit.recent(120)
    )
    return (
        '<div class="card"><table><tr><th>Время</th><th>Кто</th>'
        f"<th>Действие</th><th>Подробности</th></tr>"
        f"{rows or '<tr><td colspan=4 class=muted>записей нет</td></tr>'}</table></div>"
    )


# --------------------------------------------------------------------------
#  Сервер
# --------------------------------------------------------------------------

async def create_app() -> Any:
    """Собирает приложение. Импорт aiohttp внутри — панель необязательна."""
    from aiohttp import web

    from . import audit

    application = web.Application()
    bot_username = {"value": ""}

    async def resolve_username(_app) -> None:
        try:
            from ..tg import bot

            me = await bot.get_me()
            bot_username["value"] = me.username or ""
        except Exception:  # noqa: BLE001
            log.warning("Имя бота для виджета входа не определено")

    application.on_startup.append(resolve_username)

    def current_session(request):
        return auth.session_by_token(request.cookies.get(auth.SESSION_COOKIE, ""))

    def guard(handler, minimum: str = "moderator"):
        """Доступ к странице. Роль проверяется на каждом запросе, а не при входе."""
        async def wrapper(request):
            session = current_session(request)
            if session is None:
                raise web.HTTPFound("/login")
            if not roles.at_least(session.role, minimum):
                audit.record(session.user_key, "отказ в доступе", request.path)
                raise web.HTTPFound("/")
            return await handler(request, session)
        return wrapper

    def admin_only(handler):
        return guard(handler, "admin")

    def owner_only(handler):
        return guard(handler, "superadmin")

    async def login(request):
        # Адрес берём из настроек сократителя: он же и есть внешний адрес
        # панели, если сертификат выдавался установщиком. Так подсказка
        # показывает конкретный адрес, а не «ваш-домен».
        from .. import shortener

        public = shortener.base_url()
        if not public:
            host = request.headers.get("Host", "")
            if host and not host.replace(".", "").replace(":", "").isdigit():
                scheme = request.headers.get("X-Forwarded-Proto", "https")
                public = f"{scheme}://{host}"

        return web.Response(
            text=_login_page(
                bot_username["value"], request.query.get("error", ""), public
            ),
            content_type="text/html",
        )

    async def authenticate(request):
        data = dict(request.query)
        # Заголовку верим только когда панель заведомо стоит за обратным
        # прокси (WEB_HTTPS=1). Иначе его пишет кто угодно: ротацией
        # значения обходился лимит попыток, а чужим адресом можно было
        # закрыть вход конкретному человеку на десять минут.
        if config.WEB_HTTPS:
            address = request.headers.get("X-Forwarded-For",
                                          request.remote or "").split(",")[0].strip()
        else:
            address = request.remote or ""

        def role_lookup(key: str) -> str:
            user = storage.get_user(key)
            return user.get("role", "") if user else ""

        session, reason = auth.authenticate(
            data, config.BOT_TOKEN, role_lookup, address
        )
        if session is None:
            audit.record("—", "неудачный вход", reason)
            raise web.HTTPFound(f"/login?error={reason}")

        audit.record(session.user_key, "вход в панель", session.role)
        response = web.HTTPFound("/")
        response.set_cookie(
            auth.SESSION_COOKIE, session.token,
            max_age=auth.SESSION_TTL, httponly=True, samesite="Lax",
            secure=config.WEB_HTTPS,
        )
        raise response

    async def logout(request):
        token = request.cookies.get(auth.SESSION_COOKIE, "")
        session = auth.session_by_token(token)
        if session is not None:
            audit.record(session.user_key, "выход из панели", "")
        auth.drop_session(token)
        response = web.HTTPFound("/login")
        response.del_cookie(auth.SESSION_COOKIE)
        raise response

    @guard
    async def overview(_request, session):
        return web.Response(
            text=_layout("Обзор", _overview_body(), "home", roles.title(session.role), session.role),
            content_type="text/html",
        )

    @guard
    async def users_page(request, session):
        return web.Response(
            text=_layout("Пользователи",
                         _users_body(session,
                                     request.query.get("ok", ""),
                                     request.query.get("err", "")),
                         "users",
                         roles.title(session.role), session.role),
            content_type="text/html",
        )

    @guard
    async def sources_page(request, session):
        return web.Response(
            text=_layout(
                "Источники",
                _sources_body(session,
                              request.query.get("ok", ""),
                              request.query.get("err", "")),
                "sources", roles.title(session.role), session.role,
            ),
            content_type="text/html",
        )

    @owner_only
    async def keys_page(request, session):
        return web.Response(
            text=_layout(
                "Ключи",
                _keys_body(session,
                           request.query.get("ok", ""),
                           request.query.get("err", "")),
                "keys", roles.title(session.role), session.role,
            ),
            content_type="text/html",
        )

    @owner_only
    async def files_page(request, session):
        return web.Response(
            text=_layout(
                "Файлы",
                _files_body(session,
                            request.query.get("ok", ""),
                            request.query.get("err", "")),
                "files", roles.title(session.role), session.role,
            ),
            content_type="text/html",
        )

    async def files_remove(request):
        from .. import filedrop

        session, data = await _guarded_form(request, "superadmin")
        token = str(data.get("token", ""))
        if filedrop.remove(token):
            audit.record(session.user_key, "ссылка на файл отключена", token[:8])
            raise web.HTTPFound("/files?ok=" + quote("Ссылка отключена, файл удалён"))
        raise web.HTTPFound("/files?err=" + quote("Такой ссылки уже нет"))

    @admin_only
    async def links_page(request, session):
        return web.Response(
            text=_layout(
                "Ссылки",
                await _links_body(session,
                                  request.query.get("ok", ""),
                                  request.query.get("err", "")),
                "links", roles.title(session.role), session.role,
            ),
            content_type="text/html",
        )

    async def links_remove(request):
        from ..db import repo

        session, data = await _guarded_form(request, "admin")
        code = str(data.get("code", ""))
        try:
            removed = await repo.remove_short_link(code)
        except Exception:  # noqa: BLE001
            log.exception("Удаление ссылки не удалось")
            raise web.HTTPFound("/links?err=" + quote("Не удалось удалить — журнал"))
        if removed:
            audit.record(session.user_key, "короткая ссылка удалена", code)
            raise web.HTTPFound("/links?ok=" + quote(f"Ссылка {code} удалена"))
        raise web.HTTPFound("/links?err=" + quote("Такой ссылки уже нет"))

    async def links_clear(request):
        from ..db import repo

        session, data = await _guarded_form(request, "admin")
        try:
            removed = await repo.clear_short_links()
        except Exception:  # noqa: BLE001
            log.exception("Очистка ссылок не удалась")
            raise web.HTTPFound("/links?err=" + quote("Не удалось очистить — журнал"))
        audit.record(session.user_key, "короткие ссылки очищены", f"штук: {removed}")
        raise web.HTTPFound("/links?ok=" + quote(f"Удалено ссылок: {removed}"))

    @owner_only
    async def agents_page(request, session):
        return web.Response(
            text=_layout(
                "Агенты",
                await _agents_body(session,
                                   request.query.get("ok", ""),
                                   request.query.get("err", "")),
                "agents", roles.title(session.role), session.role,
            ),
            content_type="text/html",
        )

    async def agents_save(request):
        from .. import agents

        session, data = await _guarded_form(request, "superadmin")
        slot = str(data.get("slot", ""))
        if not agents.valid_slot(slot):
            raise web.HTTPFound("/agents?err=" + quote("Свободных слотов нет"))

        url = str(data.get("url", ""))
        if not agents.valid_url(url):
            raise web.HTTPFound("/agents?err=" + quote(
                "Адрес должен начинаться с http:// или https://"))

        # Пустое поле ключа означает «оставить прежний», а не «стереть»:
        # значение показано маской, и заставлять вводить его заново при
        # правке названия — верный способ потерять рабочий ключ.
        key = str(data.get("key", "")).strip()
        if not key:
            existing = next((item for item in agents.load()
                             if item.slot == int(slot)), None)
            key = existing.key if existing else ""

        if not agents.save(int(slot), str(data.get("title", "")), url, key,
                           str(data.get("model", ""))):
            raise web.HTTPFound("/agents?err=" + quote(
                "Записать не удалось — проверьте права на .env"))
        audit.record(session.user_key, "свой агент сохранён", f"слот {slot}")
        raise web.HTTPFound("/agents?ok=" + quote(f"Агент в слоте {slot} сохранён"))

    async def agents_model(request):
        from .. import provider

        session, data = await _guarded_form(request, "superadmin")
        name = str(data.get("provider", ""))
        if name not in provider.all_infos():
            raise web.HTTPFound("/agents?err=" + quote("Неизвестный провайдер"))
        if not provider.set_model(name, str(data.get("model", ""))):
            raise web.HTTPFound("/agents?err=" + quote("Записать не удалось"))
        audit.record(session.user_key, "модель провайдера изменена", name)
        raise web.HTTPFound("/agents?ok=" + quote(f"Модель {name} сохранена"))

    async def agents_remove(request):
        from .. import agents

        session, data = await _guarded_form(request, "superadmin")
        slot = str(data.get("slot", ""))
        if not agents.valid_slot(slot) or not agents.forget(int(slot)):
            raise web.HTTPFound("/agents?err=" + quote("Такого слота нет"))
        audit.record(session.user_key, "свой агент удалён", f"слот {slot}")
        raise web.HTTPFound("/agents?ok=" + quote("Агент удалён"))

    async def _guarded_form(request, minimum: str):
        """Общая часть записи: сессия, роль, токен формы.

        Возвращает (сессия, поля) либо бросает перенаправление. Проверки
        собраны в одном месте намеренно: пропустить одну из них в новом
        обработчике — самый лёгкий способ открыть панель наружу.
        """
        session = current_session(request)
        if session is None:
            raise web.HTTPFound("/login")
        if not roles.at_least(session.role, minimum):
            audit.record(session.user_key, "отказ в доступе", request.path)
            raise web.HTTPFound("/")
        data = await request.post()
        if not auth.csrf_valid(session, data.get("csrf", "")):
            audit.record(session.user_key, "форма отклонена", request.path)
            raise web.HTTPFound("/sources?err=Форма устарела, откройте страницу заново")
        return session, data

    async def sources_add(request):
        from .. import sourceedit as se

        session, data = await _guarded_form(request, "moderator")
        kind = str(data.get("kind", ""))
        if kind not in se.KINDS:
            raise web.HTTPFound("/sources?err=Неизвестный вид источника")

        added, skipped = se.add(kind, str(data.get("value", "")))
        if added:
            await storage.save()
            audit.record(session.user_key, "источники добавлены",
                         f"{kind}: {', '.join(added)}")
        parts = []
        if added:
            parts.append("Добавлено: " + ", ".join(added))
        if skipped:
            # Молчать про пропущенные нельзя: человек видит «добавлено 0»
            # и не понимает, ошибся он или источник уже был.
            parts.append("Пропущено (неверный формат или уже есть): "
                         + ", ".join(skipped))
        key = "ok" if added else "err"
        raise web.HTTPFound(f"/sources?{key}=" + quote("; ".join(parts) or "Ничего не добавлено"))

    async def sources_remove(request):
        from .. import sourceedit as se

        session, data = await _guarded_form(request, "moderator")
        kind = str(data.get("kind", ""))
        value = str(data.get("value", ""))
        if se.remove(kind, value):
            await storage.save()
            audit.record(session.user_key, "источник удалён", f"{kind}: {value}")
            raise web.HTTPFound("/sources?ok=" + quote(f"Удалён: {value}"))
        raise web.HTTPFound("/sources?err=" + quote("Такого источника нет"))

    async def download_drop(request):
        """Отдаёт крупный файл по ссылке из бота.

        Без входа в панель намеренно: ссылку человек открывает в браузере
        или качалкой, где сессии Telegram нет и быть не может. Защита —
        в непредсказуемом имени и в сроке жизни: ссылку выдаёт бот лично
        тому, кто с ним разговаривает.
        """
        from .. import filedrop

        drop = filedrop.find(request.match_info.get("token", ""))
        if drop is None:
            raise web.HTTPNotFound(
                text="Файл не найден или срок ссылки истёк.",
                content_type="text/plain",
            )
        filedrop.note_download(drop.token)
        log.info("Файл отдан по ссылке: %s (%.1f МБ)", drop.name, drop.size_mb)
        return web.FileResponse(
            drop.path,
            headers={
                # Имя из токена, а не из адреса: адрес человек может
                # обрезать, а имя файла должно остаться узнаваемым.
                "Content-Disposition":
                    f'attachment; filename="{drop.token}"; '
                    f"filename*=UTF-8''{quote(drop.name)}",
            },
        )

    async def keys_set(request):
        session, data = await _guarded_form(request, "superadmin")
        key = str(data.get("key", ""))
        if key not in secrets_module.BY_KEY:
            raise web.HTTPFound("/keys?err=" + quote("Неизвестный ключ"))

        value = str(data.get("value", "")).strip()
        if not secrets_module.write(key, value):
            raise web.HTTPFound("/keys?err=" + quote(
                "Записать не удалось — проверьте права на .env"))

        # В журнал уходит имя ключа, но НИКОГДА значение: журнал панели
        # читается в самой панели, и записанный туда ключ свёл бы на нет
        # то, ради чего значения скрыты.
        audit.record(session.user_key,
                     "ключ очищен" if not value else "ключ изменён", key)
        done = "очищен" if not value else "сохранён"
        raise web.HTTPFound("/keys?ok=" + quote(f"{key} {done}"))

    @admin_only
    async def events_page(_request, session):
        body = await _events_body()
        return web.Response(
            text=_layout("События", body, "events", roles.title(session.role), session.role),
            content_type="text/html",
        )

    @owner_only
    async def partners_page(request, session):
        body = await _partners_body(session,
                                    request.query.get("ok", ""),
                                    request.query.get("err", ""))
        return web.Response(
            text=_layout("Партнёры", body, "partners",
                         roles.title(session.role), session.role),
            content_type="text/html",
        )

    async def partners_save(request):
        from .. import partners

        session, data = await _guarded_form(request, "superadmin")
        projects = await partners.load()
        slug = str(data.get("slug", "")).strip().lower()

        existing = next((item for item in projects if item.slug == slug), None)
        if existing is None and len(projects) >= partners.MAX_PROJECTS:
            raise web.HTTPFound("/partners?err=" + quote(
                f"Больше {partners.MAX_PROJECTS} проектов не бывает"))

        # Разбор формы живёт в самом модуле партнёров: второй набор
        # правил в панели разошёлся бы с ботом.
        project = partners.from_form(data, existing)
        if project is None:
            raise web.HTTPFound("/partners?err=" + quote(
                "Проверьте короткое имя, название и ссылку"))

        rest = [item for item in projects if item.slug != project.slug]
        await partners.save(rest + [project])
        audit.record(session.user_key,
                     "партнёр изменён" if existing else "партнёр добавлен",
                     project.slug)
        raise web.HTTPFound("/partners?ok=" + quote(f"Сохранено: {project.title}"))

    async def partners_remove(request):
        from .. import partners

        session, data = await _guarded_form(request, "superadmin")
        slug = str(data.get("slug", "")).strip().lower()
        projects = await partners.load()
        rest = [item for item in projects if item.slug != slug]
        if len(rest) == len(projects):
            raise web.HTTPFound("/partners?err=" + quote("Такого проекта нет"))
        await partners.save(rest)
        audit.record(session.user_key, "партнёр удалён", slug)
        raise web.HTTPFound("/partners?ok=" + quote("Проект удалён"))

    @owner_only
    async def partners_export(request, _session):
        """Выгрузка кодов файлом. Отдаём то же, что и бот, — код и дату."""
        from .. import promo

        slug = request.query.get("slug", "")
        if not slug or len(slug) > 32:
            raise web.HTTPBadRequest(text="Не указан проект")
        rows = await promo.export_for_partner(slug)
        payload = promo.render_csv(rows)
        return web.Response(
            body=payload.encode("utf-8"),
            content_type="text/csv",
            headers={
                # slug приходит из адреса: кавычка в нём разорвала бы
                # заголовок, поэтому оставляем только безопасные знаки.
                "Content-Disposition":
                    f'attachment; filename="promo-{_safe_slug(slug)}.csv"',
            },
        )

    @owner_only
    async def features_page(request, session):
        return web.Response(
            text=_layout(
                "Возможности",
                _features_body(session,
                               request.query.get("ok", ""),
                               request.query.get("err", "")),
                "features", roles.title(session.role), session.role,
            ),
            content_type="text/html",
        )

    async def features_toggle(request):
        from ..db import repo as feature_repo

        session, data = await _guarded_form(request, "superadmin")
        key = str(data.get("key", ""))
        flag = features.resolve(key)
        if flag is None:
            raise web.HTTPFound("/features?err=" + quote("Неизвестная возможность"))
        if flag.locked:
            raise web.HTTPFound("/features?err=" + quote(
                "Это ядро системы, выключить нельзя"))

        value = not features.enabled(flag.key)
        features.set_local(flag.key, value)
        await feature_repo.set_feature(flag.key, value, session.user_key)
        audit.record(session.user_key,
                     "возможность включена" if value else "возможность выключена",
                     flag.key)
        # Возврат туда, откуда включали: тумблер доступен не только
        # со страницы возможностей, и выбрасывать человека в другой
        # раздел — значит заставлять его искать дорогу обратно.
        back = str(data.get("back", "")) or "/features"
        if not back.startswith("/") or back.startswith("//"):
            back = "/features"
        raise web.HTTPFound(back + "?ok=" + quote(
            f"{flag.title}: {'включено' if value else 'выключено'}"))

    async def user_time(request):
        """Часовой пояс и время погоды у конкретного человека.

        Города пользователей в разных поясах, и «погода в 8:00» без пояса
        означает восемь утра у сервера. В боте это правит сам человек;
        администрации оно нужно, когда правит не он — по просьбе или
        при разборе «почему пришло ночью».
        """
        from .. import timezones

        session, data = await _guarded_form(request, "moderator")
        key = str(data.get("user", ""))
        target = storage.get_user(key)
        if target is None:
            raise web.HTTPFound("/users?err=" + quote("Пользователь не найден"))

        # В боте эта же правка закрыта can_edit_user, а здесь проверки
        # не было: модератор менял пояс и время погоды суперадминистратору.
        # Панель повторяет права бота, а не расширяет их.
        if not roles.can_edit_user(session.role, target.get("role")):
            audit.record(session.user_key, "отказ в правке пользователя", key)
            raise web.HTTPFound("/users?err=" + quote("Недостаточно прав"))

        changed = []
        tz = str(data.get("tz", "")).strip()
        if tz:
            if timezones.parse(tz) is None:
                raise web.HTTPFound("/users?err=" + quote("Часовой пояс не разобран"))
            target["tz"] = tz
            changed.append("пояс")

        moment = str(data.get("weather_time", "")).strip()
        if moment:
            from ..quiet import parse_time

            if parse_time(moment) is None:
                raise web.HTTPFound("/users?err=" + quote(
                    "Время нужно в виде 08:00"))
            target["weather_time"] = moment
            target["weather_mode"] = "time"
            changed.append("время погоды")

        if not changed:
            raise web.HTTPFound("/users?err=" + quote("Нечего менять"))

        await storage.save()
        audit.record(session.user_key, "время пользователя изменено",
                     f"{key}: {', '.join(changed)}")
        raise web.HTTPFound("/users?ok=" + quote(
            f"Сохранено: {', '.join(changed)}"))


    @owner_only
    async def audit_page(_request, session):
        return web.Response(
            text=_layout("Журнал действий", _audit_body(), "audit",
                         roles.title(session.role), session.role),
            content_type="text/html",
        )

    @owner_only
    async def backup_page(_request, session):
        from . import backup as backup_module

        return web.Response(
            text=_layout("Резервные копии",
                         backup_module.body(auth.csrf_token(session)), "backup",
                         roles.title(session.role), session.role),
            content_type="text/html",
        )

    async def backup_create(request):
        # Было GET: чужая страница редиректом заставляла панель собрать
        # архив (а в нём копия .env) и занять место на диске. Теперь это
        # POST с токеном формы, как остальные изменяющие действия.
        session, _data = await _guarded_form(request, "superadmin")
        from . import backup as backup_module

        path, error = await backup_module.create(f"панель:{session.user_key}")
        if error:
            audit.record(session.user_key, "копия не создана", error)
            raise web.HTTPFound("/backup?error=1")
        audit.record(session.user_key, "создана копия", path.name)
        raise web.HTTPFound("/backup")

    @owner_only
    async def backup_download(request, session):
        from . import backup as backup_module

        name = request.query.get("name", "")
        target = backup_module.find(name)
        if target is None:
            raise web.HTTPFound("/backup")
        audit.record(session.user_key, "скачана копия", name)
        return web.FileResponse(target)

    @owner_only
    async def maintenance_page(_request, session):
        return web.Response(
            text=_layout("Обслуживание", _maintenance_body(), "maintenance",
                         roles.title(session.role), session.role),
            content_type="text/html",
        )

    @owner_only
    async def media_page(_request, session):
        return web.Response(
            text=_layout("Плейлисты", _media_body(), "media",
                         roles.title(session.role), session.role),
            content_type="text/html",
        )

    @owner_only
    async def update_page(request, session):
        from .. import updater

        busy = await updater.running()
        return web.Response(
            text=_layout(
                "Обновление",
                _update_body(session, busy,
                             request.query.get("ok", ""),
                             request.query.get("err", "")),
                "update", roles.title(session.role), session.role,
                refresh=5 if busy else 0,
            ),
            content_type="text/html",
        )

    async def update_start(request):
        from .. import updater

        session, _data = await _guarded_form(request, "superadmin")
        started, reason = await updater.start(f"панель:{session.user_key}")
        if not started:
            audit.record(session.user_key, "обновление не запущено", reason)
            raise web.HTTPFound("/update?err=" + quote(reason))
        audit.record(session.user_key, "запущено обновление системы",
                     config.VERSION)
        raise web.HTTPFound("/update?ok=" + quote(
            "Обновление запущено — шаги ниже"))

    @owner_only
    async def rustdesk_page(request, session):
        return web.Response(
            text=_layout(
                "RustDesk",
                await _rustdesk_body(session,
                                     request.query.get("ok", ""),
                                     request.query.get("err", "")),
                "rustdesk", roles.title(session.role), session.role,
            ),
            content_type="text/html",
        )

    async def rustdesk_action(request):
        from .. import rustdesk

        session, data = await _guarded_form(request, "superadmin")
        action = data.get("action", "")
        ok, reason = await rustdesk.control(action)
        if not ok:
            audit.record(session.user_key, f"rustdesk {action} не выполнен", reason)
            raise web.HTTPFound("/rustdesk?err=" + quote(reason))
        audit.record(session.user_key, f"rustdesk {action}", "")
        raise web.HTTPFound("/rustdesk?ok=" + quote(f"{action}: готово"))

    async def health(_request):
        # Версию отсюда убрали: маршрут открыт без входа, а точная версия
        # снаружи — это готовый ответ на вопрос «что здесь уязвимо».
        return web.json_response({"status": "ok"})

    async def follow(request):
        """Переход по короткой ссылке.

        Единственный маршрут панели без авторизации — иначе ссылка была бы
        бесполезна. Поэтому он ничего не показывает и ничего не принимает:
        только ищет код и перенаправляет.
        """
        from ..db import repo

        code = request.match_info.get("code", "")
        if not shortener.valid_code(code):
            raise web.HTTPNotFound(text="Ссылка не найдена")
        target = await repo.resolve_short_link(code)
        if not target:
            raise web.HTTPNotFound(text="Ссылка не найдена")
        raise web.HTTPFound(target)

    application.add_routes([
        web.get("/login", login),
        web.get("/auth", authenticate),
        web.get("/logout", logout),
        web.get("/", overview),
        web.get("/users", users_page),
        web.get("/sources", sources_page),
        web.post("/sources/add", sources_add),
        web.post("/sources/remove", sources_remove),
        web.get("/keys", keys_page),
        web.get("/agents", agents_page),
        web.post("/agents/save", agents_save),
        web.post("/agents/model", agents_model),
        web.post("/agents/remove", agents_remove),
        web.get("/files", files_page),
        web.post("/files/remove", files_remove),
        web.get("/links", links_page),
        web.post("/links/remove", links_remove),
        web.post("/links/clear", links_clear),
        web.post("/keys/set", keys_set),
        web.get("/events", events_page),
        web.get("/features", features_page),
        web.post("/features/toggle", features_toggle),
        web.post("/users/time", user_time),
        web.get("/audit", audit_page),
        web.get("/backup", backup_page),
        web.post("/backup/create", backup_create),
        web.get("/backup/download", backup_download),
        web.get("/maintenance", maintenance_page),
        web.get("/media", media_page),
        web.get("/update", update_page),
        web.post("/update/start", update_start),
        web.get("/rustdesk", rustdesk_page),
        web.post("/rustdesk/action", rustdesk_action),
        web.get("/health", health),
        web.get("/s/{code}", follow),
        web.get("/d/{token}", download_drop),
        web.get("/d/{token}/{name}", download_drop),
        web.get("/partners", partners_page),
        web.post("/partners/save", partners_save),
        web.post("/partners/remove", partners_remove),
        web.get("/partners/export", partners_export),
    ])
    return application


async def run() -> None:
    """Запускает панель. Любая ошибка здесь не должна касаться бота."""
    if not features.enabled("web_panel"):
        log.info("Веб-панель выключена флагом web_panel")
        return

    try:
        from aiohttp import web

        application = await create_app()
        runner = web.AppRunner(application)
        await runner.setup()
        site = web.TCPSite(runner, config.WEB_HOST, config.WEB_PORT)
        await site.start()
        log.info(
            "Веб-панель слушает %s:%d (HTTPS %s)",
            config.WEB_HOST, config.WEB_PORT,
            "через reverse proxy" if config.WEB_HTTPS else "выключен",
        )
        if not config.WEB_HTTPS:
            log.warning(
                "WEB_HTTPS выключен: панель отдаёт cookie без флага secure. "
                "Открывать её наружу в таком виде нельзя."
            )
    except Exception:  # noqa: BLE001
        log.exception("Веб-панель не запустилась — бот продолжает работу")
