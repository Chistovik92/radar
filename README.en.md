# Radar v4.8.3

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

It takes a backup (database, `.env`, data files), welds it onto itself
into **one self-contained file** and brings up a one-time serving. While
the link is alive the installer waits with a countdown; Ctrl+C cancels,
closing the terminal does not — the serving finishes its lifetime in
the background.

It then prints two commands for the **new** machine:

```bash
curl -fsSLo radar-restore.sh http://OLD-SERVER-ADDRESS:8899/TOKEN
sudo bash radar-restore.sh
```

The downloaded file carries both the bot's code and the data — the new
server needs neither GitHub nor the full installer, only Docker
(`curl -fsSL https://get.docker.com | sh`). A normal installation follows
on this data: the dump is loaded **before** the bot starts, and after the
start the system recounts users, locations and sources and reports
whether it adds up.

The link works **once** and expires after 30 minutes. **Port 8899 must be
forwarded on the old server's router to the machine itself** — without
forwarding the new server cannot connect. If forwarding is not an option,
copy the backup by hand:

```bash
# on the old machine:
scp /root/radar_bot/backups/radar-backup-YYYYMMDD-HHMMSS.tar.gz user@new-server:~/
# on the new one:
curl -fsSLo radar-install.sh https://raw.githubusercontent.com/Chistovik92/radar/main/install.sh
sudo bash radar-install.sh --restore=radar-backup-YYYYMMDD-HHMMSS.tar.gz
```

The link carries the bot token, database password and API keys — do not
share it.

The old bot is **not** stopped automatically. Two instances sharing one
token steal updates from each other, but deciding when to switch is your
call: an automatic shutdown would leave both systems silent if the move
failed.

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
