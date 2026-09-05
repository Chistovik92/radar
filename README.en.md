# Radar v4.9.3.2

[Русская версия](README.md)

A Telegram bot that watches for city threats and utility outages, matches
them against your saved addresses and warns you — with a focus on air
threats and infrastructure failures.

The system does not replace official warning channels. It is a helper,
not a substitute.

## Install

One command on a clean Debian or Ubuntu machine:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Chistovik92/radar/main/install.sh) --lang=en
```

Without `--lang=en` the installer asks for a language first. Either way it
then walks through every step with timings and reports what it did at the
end.

Downloading the script first is more reliable. If the connection drops,
`<(curl ...)` hands over an incomplete script — the installer survives that
(its body is wrapped in a function, so a truncated file simply does not
run), but a downloaded file can be re-run without fetching it again:

```bash
curl -fsSLo radar-install.sh https://raw.githubusercontent.com/Chistovik92/radar/main/install.sh
bash radar-install.sh --lang=en
```

### Choosing a version

By default the code from `main` is installed — the latest one, whether or
not it has been tagged as a release.

```bash
sudo bash install.sh --versions            # list what is available
sudo bash install.sh --version=v4.6.1      # install a specific release
```

Installing an older release **is** the rollback procedure. It is not
blocked and needs no confirmation: if a new version breaks something, you
need to go back immediately, not argue with the installer. A snapshot is
taken before anything is overwritten.

### Installer flags

| Flag | What it does |
|---|---|
| `--lang=ru\|en` | installer language (Russian by default) |
| `--version=TAG` | install a specific release, including an older one |
| `--versions` | list available releases |
| `--backup` | take a backup and exit |
| `--rollback` | restore the previous version from the last snapshot |
| `--migrate` | prepare a move to another machine |
| `--restore=FILE` | deploy from a backup file |
| `--restore-url=URL` | deploy from a link produced by `--migrate` |
| `--reset` | full reset: back up, wipe, install from scratch |
| `--uninstall` | stop and remove containers and image, keep the data |
| `--skip-updates` | do not update system packages |

## What it does

Watches public Telegram channels of utility services, emergency services
and city administrations, plus RSS feeds of local media. Messages are
analysed by an AI model, then matched against your locations.

* **Air threats** — one message per city, listing every matched location.
* **Utilities** — address level, by street and building.
* **Allow-list warning** — when an air threat is announced, operators
  restrict mobile internet; the bot says so explicitly.
* **Weather** — per group of locations, as text or as a rendered image.
* **News digests** — eighteen topics, delivered at a time you choose.
* **SOS** — an alert to your trusted contacts with your location.
* **Video download** — 20 clips a day for free, up to 50 MB each.

Sources are polled **in parallel**, with at most `SOURCE_CONCURRENCY` of
them at a time (6 by default). Until 4.7.7 the walk was sequential: a
measurement on the production server showed 51 seconds per cycle against a
180-second interval — the bot spent over a quarter of its time waiting on
the network while using two percent of the CPU. The cap matters as much as
the parallelism: dozens of simultaneous requests to `t.me` from one address
look like scraping, and it is the alerting system that would pay for it.

## Time zone

Users live in different time zones, so each has their own local time.
The zone is picked in the alert settings and gives meaning to three things
at once: quiet hours, the weather time and digest delivery. Until a zone
is chosen, the server's zone is used, exactly as before 4.8.4.4.

Labels follow the interface language: offsets are counted from UTC in
English (`UTC+5`) and from Moscow in Russian (`MSK+2`) — a Russian speaker
thinks in Moscow time, and `UTC+5` tells them nothing.

An offset is stored rather than a zone name. The price of that simplicity
is daylight saving time, which an offset does not track. Russia has not
changed clocks since 2014, so this costs nothing there; a user in Europe
or the US adjusts the choice twice a year.

## Subscription

One subscription for the whole bot. It opens two things at once: news
digests across all topics, and video downloads without the daily cap.

**The parts are not sold separately.** The model underneath was already
one — paying for either opened both — but people saw two offers and
reasonably concluded they had to buy both. Charging twice for one feeling
is not on, so there is a single entry point now.

**A 7-day trial**, once per person, offered up front rather than after
a refusal to buy — otherwise only those who reach the refusal ever see it.

**Danger alerts are free always** and do not depend on the subscription.
That is a project rule, not a current setting.

## Large files by link

Telegram accepts no more than 50 MB from bots. When `SHORT_BASE_URL` is
set — the external address the panel is served on — a file over that limit
is handed over as a link instead: it never goes through the messenger at
all, the person downloads it themselves.

Only a bot user gets a link, because the bot hands it out in the chat.
The link itself is the secret: a browser request carries no Telegram
identity, so anyone holding the link can fetch the file. The name is
therefore unguessable, the link lives for a day, and the whole drop is
capped by a disk budget — a full disk would stop alerts, and alerts
outrank downloads.

## The web panel

The panel mirrors the bot's permissions rather than extending them.
A **moderator** edits the source list — Telegram channels, RSS feeds and
VKontakte communities — using the same parsing rules as the bot, so
`@name`, `t.me/name` and a bare name all give the same result in both
places. A **superadmin** sets AI keys and service tokens, and the Files tab shows
the whole drop: who a link was issued to, whether they hold a subscription,
whether the file was picked up, and how long it has left. A link can be
switched off early.

The panel comes in light and dark themes — the toggle sits in the header,
the choice is remembered in the browser, and the system preference is the
default.

**Keys go in but never come out.** An existing value is shown only as a
mask such as `AIza…9kQw`: enough to check which key is in place, not
enough to take it. Access to a hijacked panel session must not mean access
to every key at once. The full value stays in `.env` on the server, and
the panel's own log records the key's name, never its value.

## Language

The bot asks which language to use on first contact — both for new users
and for those who used it before the language choice existed. It can be
changed later from the menu ("🌍 Language").

The dictionary lives in `radar/i18n.py`, and an untranslated string falls
back to Russian rather than showing a raw key — a Russian line among
English ones is unpleasant but readable, unlike `menu.title.short`.

Since 4.7.6 **everything an ordinary user can reach is translated:** the
main menu, alerts, weather as text and as an image (including the wind
rose and moon phases), news digests, SOS, the history log, video
download, the whole "Notifications" screen, "Suggest a source", `/help`
and role names.

Superadministrator screens deliberately stay in Russian — keys, AI
management, network, backups, logs, the partner project editor. Only the
system's owner reads them, and translating them would double the
maintenance burden without a single reader.

## Moving to another server

On the **old** machine — one command, no full installation:

```bash
curl -fsSLo radar-install.sh https://raw.githubusercontent.com/Chistovik92/radar/main/install.sh
sudo bash radar-install.sh --migrate
```

It takes a backup (database, `.env`, data files) and asks how to transfer
it to the new machine. **Two options:**

**1. By hand — the reliable way.** The backup file travels by any means
(scp, a USB stick), and the installer on the new machine deploys it:

```bash
# on the old machine:
scp /root/radar_bot/backups/radar-backup-YYYYMMDD-HHMMSS.tar.gz user@new-server:~/

# on the new machine (Docker required: curl -fsSL https://get.docker.com | sh):
curl -fsSLo radar-install.sh https://raw.githubusercontent.com/Chistovik92/radar/main/install.sh
sudo bash radar-install.sh --restore
```

A bare `--restore` picks the archive from the current directory: put the
file next to the installer and run it.

**2. By a one-time link — ⚠️ not verified on a live move yet.** The
installer welds the backup onto itself into one self-contained file,
brings up a one-time serving and prints two commands for the new machine:

```bash
curl -fsSLo radar-restore.sh http://OLD-SERVER-ADDRESS:8899/TOKEN
sudo bash radar-restore.sh
```

The downloaded file carries both the bot's code and the data — the new
server needs neither GitHub nor the full installer. While the link is
alive the installer waits with a countdown; Ctrl+C cancels, closing the
terminal does not. The link works **once** and expires after 30 minutes,
and it carries the bot token and passwords — do not share it;
**port 8899 must be forwarded on the old server's router to the machine
itself** — without forwarding the new server cannot connect, and the
manual option is then the simpler path.

Either way, a normal installation follows on this data: the dump is
loaded **before** the bot starts, and after the start the system recounts
users, locations and sources and reports whether it adds up.

The old bot is **not** stopped automatically. Two instances sharing one
token steal updates from each other, but deciding when to switch is your
call: an automatic shutdown would leave both systems silent if the move
failed.

## Full removal

The installer's `--uninstall` flag stops and removes the containers and
the image while **keeping** the database and settings. To remove the
whole system — database, `.env`, backups, logs, the install directory:

```bash
curl -fsSLo uninstall.sh https://raw.githubusercontent.com/Chistovik92/radar/main/tools/uninstall.sh
bash uninstall.sh
```

The script is self-contained: it works on a broken installation too,
neither network nor repository required. It asks for an explicit "yes"
and can take one last backup before deleting (without the video cache
and logs). Use `--yes` for automation; `RADAR_HOME=/path` for a
non-standard directory.

## Requirements

* Debian 11+ or Ubuntu 20.04+, root access
* 2 GB RAM (4 GB comfortable), 10 GB disk
* Docker (installed automatically if missing)
* A bot token from [@BotFather](https://t.me/BotFather)
* A Gemini API key — optional; without it the system falls back to
  heuristics: alerts still arrive, analysis quality is lower

## Documentation

* [ROADMAP.en.md](docs/ROADMAP.en.md) — what is planned and what is done
* [STATUS.md](docs/STATUS.md) — current state, version history
* [API_SETUP.md](docs/API_SETUP.md) — where to get every key
* [MONETIZATION.en.md](docs/MONETIZATION.en.md) — paid features
* [NEWS_DIGEST.md](docs/NEWS_DIGEST.md) — how digests work

STATUS, API_SETUP and NEWS_DIGEST are Russian only for now — they are the
author's working documents, read mainly during development itself.

## Licence

GPL-3.0. Author: SecretHero.
