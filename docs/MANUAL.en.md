# Radar — user manual

The bot, the web panel and the command line are three ways to manage one system.
This document follows the code of version 5.9.10.1. Installation, settings and the
details of every feature are in [README.en.md](../README.en.md); here are the
workflow and a reference. The Russian manual, [MANUAL.md](MANUAL.md), is the original.

> The system does not replace official warning channels.

What was **not** verified on a live system is marked ⚠️. If an item disagrees with
what you see on the server, trust the server and tell the author.

---

## 1. Three ways to manage

| Way | Where it runs | When it fits |
|---|---|---|
| The Telegram bot (also MAX, VK, Discord - more limited) | in the messenger | everyday: menu, users, replies to people |
| The web panel | in a browser, on a domain, Telegram sign-in | wide forms: keys, partners, VPN, settings, logs |
| The command line | the server terminal | ssh, cron, scripts, when there is no panel or browser |

Rights are the same everywhere: the panel and the CLI give no more than the role in
the bot. **There is no server terminal in the web panel and there never will be.**

### Roles

| Action | User | Moderator | Administrator | Superadmin |
|---|:--:|:--:|:--:|:--:|
| Own locations and settings | ✅ | ✅ | ✅ | ✅ |
| AI assistant in chat | - | ✅ | ✅ | ✅ |
| Source moderation | - | ✅ | ✅ | ✅ |
| Editing others' locations and alerts | - | ✅ | ✅ | ✅ |
| Deleting users, appointing moderators | - | - | ✅ | ✅ |
| Appointing administrators | - | - | - | ✅ |

You can act only on those **one level below**. The superadmin cannot be changed.
Access to the bot is by an invite link from the "Users" menu.

---

## 2. The bot

### A user's first steps

1. `/start` or `/menu` - the main menu.
2. Add an address (a location): street, house, city. **Without a confirmed geography
   no alert is sent** - that is a rule of the project, not a flaw.
3. Choose what to be alerted about; optionally set quiet hours and a time zone.
4. Danger alerts are always free. Only the news digests can be paid.
5. An event in the past arrives as a summary, not as an alert.

### Commands

Common: `/start`, `/menu` - menu · `/id` - your ID and role · `/cancel` - reset input ·
`/help` · `/language` - interface language · `/link` - a shared account with another
network · `/panel` - the web panel link · `/partner` - partner projects · `/digest` -
news digests · `/sub`, `/subscription` - subscription · `/check <link>` - a link check
for scam signs (when enabled).

Moderator and above: `/ai`, `/aireset` - the AI assistant · `/quota` - quota usage.

Administrator and above: `/stats`, `/models` - statistics and models.

Superadmin: `/features` · `/logs`, `/logtail`, `/logclear` · `/keys` · `/backup` ·
`/network` · `/perf` · `/metrics` · `/provider` · `/setmodel` · `/ai_admin` · `/bench` ·
`/cookies` · `/media` · `/music` · `/short`, `/shorts`, `/shortclear` · `/digestprice` ·
`/history` · `/sos`.

In groups (moderation): `/chats`, `/modon`, `/modstatus`, `/warn`. A newcomer is
restricted until pressing "I am not a bot".

⚠️ Which exact role each of the last commands needs was not verified here; take the role
table above and the README "Commands" section as a guide. The bot refuses by itself when
rights are missing.

### Features (flags)

Everything notable is switched on and off by the superadmin on a live system. New things
arrive **off**. The core (for example, alerts) cannot be switched off. To switch: the bot
`/features`, the panel "Features", the CLI `features on <key>`.

---

## 3. The web panel

The address is `https://your-domain` (port `WEB_PORT`, 8080 by default, behind a reverse
proxy). Sign-in is the Telegram widget, so:

1. In @BotFather: `/setdomain` → pick the bot → send `https://your-domain` exactly,
   without a trailing path.
2. By IP address the sign-in does not work at all - that is a Telegram limit.

The panel is switched on by the `web_panel` flag.

### Sections

| Section | What is inside |
|---|---|
| Overview | a status summary |
| Users | the list; a person's zone and weather time (moderator) |
| Sources | add/remove Telegram channels, RSS, VK communities (moderator+) |
| Features | switches (superadmin) |
| Keys | AI keys and tokens; entered, but shown masked |
| Agents | AI agents and models |
| Files | file sharing: who got a link, expiry, early disabling |
| Links | short links |
| Chats | moderated groups: switch on, invite link, announcement, sending |
| Backups | create and download a backup |
| Maintenance, Media | disk, cache, database, video download |
| Cloud | music in the cloud (rclone) |
| VPN | panels, access, disconnecting app devices |
| Subscriptions | granting and cancelling subscriptions |
| RustDesk | the remote-access server |
| Partners | partner projects and promo codes, export |
| Settings | all `.env` settings by section, restart |
| Journal, Events | the audit and the event stream |
| Update | update to the latest release (`panel_update` flag) |
| Removal | removing the installation (`panel_wipe` flag) |

Security: forms are protected by a session token; the panel log records the name of a
changed key but not its value. Themes - the button in the header: light → dark →
"Matrix" → "Reactor".

---

## 4. The command line

### How to run

From the host (recommended):

```bash
bash ~/radar_bot/tools/radarctl.sh --help
bash ~/radar_bot/tools/radarctl.sh <command> [arguments] [--json]
```

Inside the container: `python -m radar.cli <command>`. A non-standard directory -
`RADAR_HOME=/path`, a non-standard container name - `RADAR_CONTAINER`.

Data commands run **inside the container** (the database and `.env` are there).
Installation commands run **on the host**: `update`, `restore`, `wipe`, `restart`.

### Reference

| Command | Actions | Notes |
|---|---|---|
| `sources` | `list`, `add <kind> <value>`, `remove <kind> <value>`, `prune` | kind: `telegram`(`tg`) / `rss` / `vk`; `prune`: `--days N` (30), `--dead`, `--yes`, `--force`, `--pause SEC` (0.8) |
| `users` | `list [--role]`, `show`, `role`, `delete`, `time`, `stale [--prune]` | the superadmin cannot be changed; `stale` - those who blocked the bot |
| `features` | `list`, `on <key>`, `off <key>` | takes effect at once if the bot runs |
| `keys` | `list`, `get`, `set`, `unset`, `pending` | values are validated as in the panel; secrets are masked |
| `backup` | `list`, `create` | |
| `db` | `size`, `vacuum`, `copy` | `copy`: `--from sqlite\|postgres`, `--to …`, `--replace`, `--yes` |
| `links` | `list`, `add <url>`, `remove <code>`, `clear` | `--yes` for destructive ones |
| `chats` | `list`, `on`, `off`, `forget`, `clean`, `invite`, `announce`, `warns` | `clean` and `announce --yes` work only from a running bot |
| `files` | `list`, `remove <token>` | `--yes` |
| `rustdesk` | `info`, `connections`, `start`, `stop`, `restart` | `--yes` |
| `vpn` | `check`, `selftest`; `panels`, `panel-save\|remove\|check`; `access`, `issue`, `extend`, `on`, `off`, `revoke`, `deny`; `orders`, `order-confirm\|retry\|cancel`; `app-revoke` | see the README |
| `subs` | `list`, `codes`, `grant`, `revoke`, `code-add`, `code-drop` | the bot subscription |
| `partners` | `list`, `show`, `save`, `remove`, `export` | `save --set field=value` |
| `ai` | `status`, `models`, `set-model`, `provider`, `health`, `ask`, `reset`, `bench`, `agents`, `agent-save\|remove\|model` | some only with a running bot |
| `metrics`, `perf`, `net` | - | `perf --reset` |
| `check`, `cookies`, `history`, `events` | `check URL [--no-net]`, `cookies status\|set FILE`, `history UID`, `events` | |
| `music`, `cloud` | `music usage\|list`; `cloud list\|check\|add\|forget` | |
| `stats`, `logs`, `audit` | `stats`; `logs list\|tail\|clear`; `audit tail\|clear` | |
| `restart` | - | `--yes`; on the host - `radarctl.sh restart` |
| `doctor`, `version` | `doctor --quick` | |
| Host | `update`, `restore FILE`, `wipe --yes`, `restart` | not from the container |

The output language is `--lang ru|en` or `RADAR_LANG`; otherwise the system language
(`C.UTF-8` means Russian).

Commands accept `--json`. Destructive actions without `--yes` do nothing and return
code **2**; an error is code **1**; success is **0**. That is how cron tells "not
confirmed" from "broken".

### How a command reaches the bot (since 5.9.3)

Data commands do not run in a separate process: the console hands the command line to the
running bot through the socket `data/admin.sock` (mode 600), and the bot executes it in its
own memory. So `features on digest` takes effect at once, without a restart, and a source
edit is not overwritten by the bot's next save.

- The bot is not running - there is no socket; the command goes straight to the database
  and the console says so on stderr.
- `--local` or `RADAR_CLI_LOCAL=1` - always directly.
- `doctor`, `version`, `db copy` do not involve the bot.
- If the link breaks after the command was sent, it is not repeated automatically: check
  the result with `list`.

⚠️ Not verified in a real container through `docker exec`.

### Examples for cron

```bash
# a backup every night; code 1 is an error, cron will send mail
15 3 * * *  bash /home/USER/radar_bot/tools/radarctl.sh backup create

# once a week show silent sources, deleting nothing
0 9 * * 1   bash /home/USER/radar_bot/tools/radarctl.sh sources prune --days 30 --json

# a quick diagnosis
*/30 * * * * bash /home/USER/radar_bot/tools/radarctl.sh doctor --quick
```

### What the CLI deliberately lacks

Parity with the bot and the panel is closed (5.9.10). Outside the console stay the panel
sign-in, file downloads, the digest menu, a person's own video download and SOS: these are
the person's own actions, and an SOS must not be sent for someone else. The full list with
reasons is in `tools/lint_cli_parity.py`.

---

## 5. Groups and platforms

### Telegram: groups

An administrator adds the bot (rights "Delete messages" and "Ban users"), then `/modon`
in the group. Moderation (`moderation`) removes spam and foreign links, runs the
warning → mute → ban ladder, greets newcomers with the "I am not a bot" button. Separate
flags, all off (since 5.9.4):

- `captcha_kick` - one who has not pressed it in 5 minutes is removed (a ban lifted at once);
- `deleted_cleanup` - `/cleandeleted` for a group administrator (or
  `radarctl.sh chats clean -100…`): a check of the members **known to the bot** and removal
  of deleted accounts. The Bot API does not return a member list, so the report's coverage
  reads "known X / Y";
- `cas_check` - joiners are checked against the external CAS spammer database (only the
  numeric identifier is sent).

Alerts are no longer sent to those who blocked the bot; the list is
`radarctl.sh users stale`.

### Discord

The `platform_discord` flag and a bot token - summaries and status; address alerts go to
private messages of a linked account (`/link`). On top (all off by default):

- **Member verification** (`discord_verify`, since 5.9.5): the "I am human" button → a
  question in a window → the "verified" role; an account linked via `/link` passes without
  a question; on joining - account age and names with ads; a timeout. The Discord-side setup
  (role, bot rights, closed channels, `/verifysetup`) is in the README. A human cannot be
  proven reliably - this raises the cost of automated joining.
- **Music by link** (`discord_music`, since 5.9.7): `/play` (a link or words), `/skip`,
  `/pause`, `/resume`, `/stop`, `/queue`. It needs `requirements-voice.txt`
  (`discord.py[voice]`, DAVE encryption), ffmpeg and the rights "Connect" and "Speak".
  Spotify, Apple Music and Deezer do not open; playing from YouTube violates its terms.

### Languages

Russian, English, Ukrainian, Persian and Simplified Chinese - `/language` in Telegram,
`/lang ru|en|uk|fa|zh` in VK, MAX and Discord. The translations were made without native
speakers: send corrections to the author.

---

## 6. Installation, update, rollback

Installation is one script, `install.sh` (Debian/Ubuntu, Docker; the bot runs in the
container `radar_container`). The full procedure and the table of version transitions are
in the README. Rules that must not be skipped:

- **Before any update** - a backup: `radarctl.sh backup create`.
- Update: `radarctl.sh update` or the panel's "Update". A move from old versions goes in
  steps; the 4.6.0 step must not be skipped.
- Restore: `radarctl.sh restore FILE`.
- Removal: `radarctl.sh wipe --yes` or the panel's "Removal" (the `panel_wipe` flag needed).
- **Do not run the bot on Windows**: the image is built for ARM, the installer for
  Debian/Ubuntu.

## 7. If something is wrong

| Symptom | What to check |
|---|---|
| `bad interpreter` on `install.sh` | the file became CRLF; it must be LF |
| "Bot domain invalid" in the panel | `/setdomain` at BotFather was not done or the address does not match |
| A flag switched by command does not work (before 5.9.3) | update to 5.9.3 or restart the bot |
| The bot does not start after an update | `radarctl.sh doctor`, then `docker logs radar_container` |
| An alert did not arrive | is there a confirmed address; is the flag on; are they quiet hours; is it maintenance mode |
| A key "vanished" in the panel | the panel shows a mask; the value is in `.env` on the server |

## 8. What is not negotiable

1. Danger alerts are free always.
2. No advertising inside alert messages.
3. Without a confirmed geography no alert is sent.
4. An event in the past is a summary, not an alert.
5. There is no server terminal in the web panel.
6. The wording "does not replace official warning channels" stays everywhere.
