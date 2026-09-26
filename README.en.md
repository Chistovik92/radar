# Radar v5.8.1

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

### Updating from 4.9.x to 5.x

One step, with a **fresh** installer:

```bash
curl -fsSLo install.sh https://raw.githubusercontent.com/Chistovik92/radar/main/install.sh
sudo bash install.sh
# or the old file with an explicit version:
sudo bash install.sh --version=v5.8.1
```

The move from 4.9.x to 5.8 was checked on **all 43 releases of 4.9**
(v4.9 … v4.9.9.4), on SQLite and on PostgreSQL 16: a database created and
filled by each release's own code is brought up by 5.8 the same way the
bot does at start — missing tables and columns are added, the schema is
not recreated, and users, addresses, sources, flags, service data,
delivery history, short links and promo codes stay in place. Environment
variables between 4.9 and 5.8 were only added, all with defaults.
**There is one trap:** an old `install.sh` saved on the server installs
its own old version under "latest code" — the code lives inside the file.
Since 5.8.1 the installer checks the newest release at that point and
offers to download its installer; for 4.9.x use a fresh file or
`--version=v5.8.1`. The panel's "Update" button leads to 5.x only from
4.9.8.9 on (see "Updating from the panel").

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

The database is SQLite by default; PostgreSQL is available for a stronger
machine (`DB_BACKEND=postgres` in `.env` and the `postgres` compose
profile). Since 4.9.9.3 the installer tunes PostgreSQL for the machine's
memory (`PG_SHARED_BUFFERS` and friends in `.env`): `shared_buffers` is an
eighth of the memory but no more than 128 MB, so the database does not hit
its own container limit. Values set by hand are left alone; without these
lines the database starts with the old defaults.

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

Two rules added in 4.9.9.2:

* **A retold past danger is a summary, not an alert.** A news item saying
  "a missile danger was declared in the evening and lasted from 21:10 to
  22:40" goes into the morning or evening summary as something that
  happened. What decides is when the event itself took place, by the sense
  of the text, not the words "missile danger" in the headline. If there is
  a call to take cover or "until the all-clear" nearby, it is still an
  alert: staying silent about a live danger is worse than sending one too
  many.
* **A memo is not an incident.** Instructions on what to do when a pipe
  bursts or gas smells, or a list of emergency numbers, arrive in full with
  a link to the original and a calm "ℹ️ Памятка" (memo) heading — without
  "utility failures" and without danger. Like the alerts themselves, the
  memo is sent in Russian: it retells Russian-language sources. The bot cannot forward the post by
  Telegram means: it reads channels through the web preview, not as a
  member. Posts from Telegram channels now carry a link to the original,
  like RSS news always did.
* **VPN ads are cut out** (since 4.9.9.3, the "Hide VPN ads" feature).
  Channels and media put VPN-service ads into their posts; the bot does
  not pass them on. In alerts, memos and summaries the ad paragraph is
  replaced with a "[реклама VPN-сервиса скрыта]" (VPN ad hidden) mark —
  with no partner: advertising inside alerts is not allowed, our own
  included. In news digests the ad posts are replaced by a single
  partner-project line. News about VPNs (say, about blocking) is not
  treated as an ad: it takes both a VPN mention and an ad sign — a promo
  code, a price, the legal "Реклама" label, an erid.

Sources are polled **in parallel**, with at most `SOURCE_CONCURRENCY` of
them at a time (6 by default). Until 4.7.7 the walk was sequential: a
measurement on the production server showed 51 seconds per cycle against a
180-second interval — the bot spent over a quarter of its time waiting on
the network while using two percent of the CPU. The cap matters as much as
the parallelism: dozens of simultaneous requests to `t.me` from one address
look like scraping, and it is the alerting system that would pay for it.

### What happens when something breaks (since 4.9.8.14)

Alerts matter more than anything else here, so their path is guarded separately.

* **The background loop is supervised.** If the monitoring task dies, the bot
  will not keep answering commands as if nothing happened: a watchdog revives
  the loop and notifies the administrators. After three failed revivals the bot
  stops itself, and a container with `restart: unless-stopped` comes back up.
  It will not keep running silently without alerts.
* **Visible from outside.** Every turn of the loop is stamped into
  `data/heartbeat`. The container `HEALTHCHECK` reads that stamp (`docker ps`
  shows `unhealthy`), and `/stats` has a "last pass" line.
* **Retries on network failure.** A dropped connection or a "retry after" reply
  from Telegram no longer means a lost alert: sending is retried, and the
  "delivered" mark is set only after success — otherwise the alert goes out on
  the next cycle.
* **Held alerts are not lost.** Messages postponed by quiet hours are stored in
  the database and survive a restart; the queue limit is per recipient.
* **Section failures are explained.** A handler that crashes tells the person
  what went wrong instead of leaving a dead button.
* **Metrics and health on one screen** (since 4.9.9.3). `/metrics` or
  "Management → 🩺 Metrics and health": delivered alerts and the latency
  from the source post to the message (median and 90%), AI quota spend,
  the share of unavailable sources, memory, disks, database size and
  container state.

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

## Music and external storage

Tracks live in `data/music` next to the bot. On a single-board
computer space runs out quickly — the directory can be moved to
external media:

```bash
# on the server, once: a stick/disk is mounted into ~/radar_bot/data/music
sudo mount /dev/sdX1 /root/radar_bot/data/music

# permanently — a line in /etc/fstab (substitute your filesystem)
echo '/dev/sdX1 /root/radar_bot/data/music ext4 defaults,nofail 0 2' | sudo tee -a /etc/fstab
```

No bot settings needed: the directory is the same. Alternatively set
the path with `MUSIC_DIR` in `.env` (the container needs access to it —
add it to `volumes` in `docker-compose.yml`).

Two warnings:

- **`nofail` is mandatory**: without it the server will not boot when
  the drive falls off. A bot without music lives; a server without
  its disk does not.
- the media must survive frequent writes: a cheap stick dies within
  months; an SSD or HDD is fine.

How full the disks are (the external one included) is visible in the
nightly report — the "Disk watching" toggle in `/features`; the letter
arrives when space is running out. The "🗜 Compress" button on a track
re-encodes it to opus at the source bitrate — the size drops several
times with no audible difference.

### Selections and similar tracks (since 4.9.9.3)

The "🎛 Build a selection" button in the music section lists the genres
and artists of your storage that have at least two tracks and builds a
playlist from them; pressing it again rebuilds the playlist instead of
creating a second one.

The "Music: data from open databases" feature (`music_meta`, off by
default) asks MusicBrainz for a genre after a track is uploaded, if the
tags have none, and ListenBrainz for related artists — similar-track
matching gets more accurate. Everything stays within your own storage:
there is no shared library. It is off by default because these are
requests to third-party services carrying the track's name.

### Music in the cloud (since 4.9.9)

External media still runs into the same server. The **"Music in the
cloud"** capability (`music_cloud`, off by default) moves tracks into a
cloud: `rclone serve webdav` runs next to the bot, the bot puts and takes
files over HTTP, and a cache of recent tracks stays on the device.

The cloud is configured on the server once:

```bash
# pick a provider and sign in (Yandex.Disk, Mail.ru, S3, WebDAV — 70+ options)
docker run --rm -it -v ~/radar_bot/data/rclone:/config/rclone rclone/rclone config
```

Then a profile in `docker-compose.yml` and three lines in `.env`:

```bash
MUSIC_CLOUD_REMOTE=name_from_rclone_config:music
MUSIC_CLOUD_URL=http://radar_rclone:8080
# user and password are only needed if rclone is started with --user/--pass
```

```bash
docker compose --profile cloud up -d
```

Then turn on "Music in the cloud" in `/features`. To check that the
storage answers and how much space it has, run `/doctor`.

What matters here:

- **the WebDAV port is not published** and must not be: there is no
  encryption there, and it must listen only on the internal Compose
  network;
- **a cloud failure does not lose the track** — it stays on the device,
  and the bot says so plainly. Local space is spent in that case;
- **the cache takes up to 256 MB** and evicts whatever has gone
  untouched longest; losing it has no consequences, the originals are in
  the cloud;
- **delivering a track goes through someone else's network**, so it is
  slower than from disk. Alerts never travel this path: music and
  monitoring share neither the queue nor the channel;
- **compression ("🗜 Compress") replaces the file in the cloud too**,
  otherwise space would be freed only on the disk.

Why WebDAV rather than mounting the cloud as a directory: `rclone mount`
would have worked without a single change in the bot, but it requires
FUSE inside the container (`--cap-add SYS_ADMIN`) — noticeably wider
rights for a process that goes to the internet for news. A hundred lines
of our own client is cheaper.


#### Connecting a cloud from the panel (since 4.9.9.1)

The **"Cloud"** section in the panel (under "Media") adds and removes
storages itself — `rclone config` on the server is no longer required.
rclone is started with its remote-control API, and the panel talks to it
over the network:

```bash
# in .env
RCLONE_RC_URL=http://radar_rclone:5572
RCLONE_RC_USER=radar
RCLONE_RC_PASS=pick_your_own
```

The `cloud` profile starts rclone with the right flags already. The
control port is not published outside either — access is only from the
internal Compose network.

**WebDAV, S3, SFTP and FTP** can be set up straight from the panel —
everything that needs no more than an address, a login and a password.
The same page shows whether the storage answers the bot, how much space it
has, and how big the on-device cache is.

**What the panel cannot and will not do.** Yandex.Disk, Google Drive and
Dropbox sign in through a browser: a person clicks "allow" on the
provider's page, and there is no token without that. The panel has no
browser, and it has no terminal — that is a separate project rule. For
Yandex the simplest way around it is WebDAV: the address
`https://webdav.yandex.ru` and an **app password** instead of the main
one. For the rest, `rclone authorize` on any machine with a browser stays
the way.

The panel runs no commands on the server: it calls another service with a
closed list of actions — add an access record, remove one, ask about size.

## Link checking

The `/check` command and the "🔍 Check a link" button in the main menu
(the `linkcheck` feature flag, off by default). It analyses an address
for phishing signs: homoglyphs imitating a brand, a brand in someone
else's domain, credentials before `@`, executable schemes and files,
bait words, shorteners. Network checks: the redirect chain, domain age
and registrar (RDAP), certificate lifetime, Google Safe Browsing lists (the key lives
in the keys section; without it the network part works partially;
disable with `LINKCHECK_NET=0`).

Free tier: **200 checks per day** for everyone; subscribers get no
daily limit. The rate is `LINKCHECK_RATE_LIMIT` checks per minute
(5 by default, not applied to subscribers).

The output lists the signs with weights and **never says "the link is
safe"** — the absence of signs is not a guarantee. Verify sources through
official channels.

## Subscription

One subscription for the whole bot. It opens several things at once: news
digests across all topics, video downloads without the daily cap, and
the address and key for your own RustDesk server, if that section is
enabled (see below).

**The parts are not sold separately.** The model underneath was already
one — paying for either opened both — but people saw two offers and
reasonably concluded they had to buy both. Charging twice for one feeling
is not on, so there is a single entry point now.

**A 7-day trial**, once per person, offered up front rather than after
a refusal to buy — otherwise only those who reach the refusal ever see it.

**Danger alerts are free always** and do not depend on the subscription.
That is a project rule, not a current setting.

## RustDesk

Your own remote-access relay (hbbs/hbbr) next to the bot — feature flag
`rustdesk`, off by default. The installer deploys the containers itself
(the `rustdesk` profile in `docker-compose.yml`) and, on a re-run,
checks that the expected container name really is `rustdesk-server`
and not something else. The external address is asked only once: when the
panel's certificate has already been issued via `tls.sh`, the installer
offers that same domain — Enter accepts it.

The bot's menu section: connection address and key — subscribers and
admins; connections right now — admins; start, stop and restart —
the superadmin. The address-and-key screen also shows client setup
steps and a download link. The same three things (address and key,
connections, control) are in the web panel too — the "RustDesk" page
under Overview, superadmin only. Deployment details and `.env`
variables are in [docs/API_SETUP.md](docs/API_SETUP.md).

## VPN (since 5.0) ⚠️ not verified against live panels

Issuing VPN access from the bot — feature flag `vpn`, off by default.
Since 5.0.1 there can be **several panels at once, including different
kinds**: up to six slots (`VPN1_*` … `VPN6_*`), each with its own kind,
address and credentials. Ten panels are supported through one internal
layer (`radar/vpnpanels.py`):

| Panel | Login | What the person gets |
|---|---|---|
| **3x-ui** 2.x and 3.x | API token or username/password (with CSRF in 3.x) | a subscription |
| **x-ui** (alireza0) | username/password | a subscription |
| **s-ui** | API token | a subscription |
| **Marzban** | token or username/password | a subscription |
| **PasarGuard** | API key or username/password | a subscription |
| **Marzneshin** | token or username/password | a subscription |
| **Remnawave** | API token | a subscription |
| **Hiddify** | API key (the admin's uuid) | a connection page |
| **Outline** | apiUrl + certificate fingerprint | an `ss://` key, no expiry |
| **wg-easy** | username/password | a one-time link to a WireGuard file, no traffic limit |

Deliberately unsupported: AmneziaVPN (managed over SSH only, no HTTP API
for keys) and bare Xray or sing-box without a panel (they keep no users).

**Issuing is fully controlled by the superadmin.** Nobody gets access
without their decision, admins included:

- a person opens "🔐 VPN" and sends a request — only the superadmin is
  notified;
- the superadmin ticks the panels to issue on and taps "Grant" — the
  links arrive in the person's private chat, one per panel;
- the section shows requests, granted access per panel, extending by
  `VPN_DAYS` days, disabling, revoking and checking all panels at once.

The role check is not only on the buttons but in the issuing logic itself:
a call made on behalf of anyone but the superadmin is refused.

Requests to different panels run **in parallel**, and one panel failing
neither delays nor breaks the others: issuing on three panels with one
of them down grants on two and says plainly what happened to the third.

Extending and re-issuing return **the same key**: the account name in
the panel is derived from the user's id. Expiry is enforced by the panel
itself — the bot polls nothing on a schedule, and the alert loop never
touches the panels.

Links are not stored in the database; neither they, nor UUIDs, nor tokens
ever reach the logs. No payments. Setup is in the "VPN" section of
[docs/API_SETUP.md](docs/API_SETUP.md).

**Clients created outside the bot (since 5.8).** "🔗 Panel clients"
searches every panel for records holding the Telegram id of a person known
to the bot — in the panel's own field (`tgId`, `telegramId`,
`telegram_id`), the name, email or comment — and offers to bind them to
the account. Binding changes nothing in the panel: the key, expiry and
traffic stay the same, and extending and paid plans then work with that
record instead of creating a second one. The superadmin binds other
clients by hand from the person's card; "↩️" removes the binding without
touching the panel.

### Selling by plan (since 5.0.2) ⚠️ not verified with real payments

Feature flag `vpn_sales`, off by default — only the superadmin turns
sales on. Plans are a `VPN_PLANS` line in the keys section:
`days:trafficGB:devices:price` separated by semicolons, e.g.
`30:0:3:199; 90:0:3:499` (0 means no limit). Currency is `VPN_CURRENCY`,
RUB by default; the panels sold on are `VPN_PLAN_SLOTS`.

Payment goes through a swappable provider (`PAY_PROVIDER`):

- **manual** — the bot takes no money: the person pays as described in
  `PAY_MANUAL_NOTE`, and the superadmin confirms the payment with a
  button. Works without registering anywhere;
- **cryptopay** — Crypto Pay (@CryptoBot): an invoice inside Telegram,
  paid in crypto; the bot checks the invoice state when the person taps
  "I've paid". No merchant registration needed.

A payment extends **the same** key and adds the days to what is left.
Tapping "I've paid" twice never grants access twice. If a panel does not
respond, the order stays paid and the superadmin gets a "Retry" button.
The device limit is enforced on 3x-ui, x-ui (`limitIp`) and Remnawave
(`hwidDeviceLimit`); the other panels have none.

The code does not check Crypto Pay's fees, limits or withdrawal terms —
look them up in @CryptoBot itself before turning sales on. Telegram Stars
are not used for selling VPN: they are meant for digital goods inside
Telegram. Income is taxable whatever the channel — that is the author's
decision, not the code's. Threat alerts are unaffected: they are always
free.

**How to verify on your server:**

```bash
python -m radar vpn check            # every panel: reachable, login accepted
python -m radar vpn selftest --yes   # full cycle on a radar_selftest account
```

`selftest` creates a `radar_selftest` account in each panel, verifies
expiry, disabling, enabling and the link against the panel's replies, and
leaves the account disabled. The clients were checked against the panels'
source code and run over HTTP against emulators of them
(`tools/vpn_http_check.py`, a CI step), but they have never talked to a
real panel — `selftest` is that first check.

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

## Group moderation

The `moderation` flag, off by default. The bot is added to a group and
given administrator rights — **deleting messages** and **banning
members**; without them it says so once in the chat and does nothing.
There is no need to change privacy mode at @BotFather: an administrator
receives every message anyway.

What it does: removes spam and suspicious links (the same check `/check`
uses), forbids links from newcomers for the first day, runs the
warning → mute → ban ladder, greets newcomers with an "I am not a bot"
button (silence until it is pressed), keeps anti-flood and a stopword
list, and clears join/leave service messages.

For chat administrators, inside the group: `/warn`, `/mute`, `/ban`,
`/unban` as a reply to a message, and `/modstatus` for current settings.
Rights are checked with Telegram rather than against Radar's own roles —
a group admin and a bot admin are different lists. Chat administrators
themselves are never moderated.

The chat list and toggles live in the panel under "Chats", and in the
command line:

```bash
bash tools/radarctl.sh chats list
bash tools/radarctl.sh chats off -1001234567890
```

**Sections meant for private chat stay silent in groups.** That is a
separate fix in the same release: before it, a bot added to a group
answered every member with "access denied", registered them as its own
users, and replied with AI to any text.

### Adding the bot to a group

1. Group → Members → Add → find the bot by name.
2. In the same place make it an **administrator** with **Delete
   messages** and **Ban users**. "Invite links" helps the jump-to-group
   button, but only when the group has neither a public name nor an
   existing invite link.
3. Type `/modon` in the group — the chat shows up under "Chats".

No need to change privacy mode at @BotFather: an administrator receives
every message anyway.

### The bot is already in the group

Nothing to add — check the administrator rights and type `/modon` in the
group. The separate command exists because Telegram only tells a bot
about **changes**: groups it was added to earlier never announce
themselves. `/modoff` turns moderation off for that chat, `/modstatus`
shows the current settings.

**People already in the group are never written to.** The greeting and
the "I am not a bot" check only reach those who join afterwards.

### Jumping into a group from the bot

The "Chats" section (a button under Manage) lists every group; tapping
one opens it. The link is chosen in this order: the public `@name`, then
the **existing** owner's invite link, and only if neither exists does the
bot create its own. It never revokes the previous link — that would break
it for everyone it was handed to.

### Posting to a group as the bot (since 4.9.8.14)

Flag `chat_post`, off by default. In the "Chats" section every group gets
a ✍️ button — **for the superadmin only**: the message goes out as the bot,
and to the members that is the voice of the system, not private mail.

The order is: button → text (bold, italics and links are kept as typed) →
a preview of exactly what the group will see → confirmation → sending.
The preview step cannot be skipped: what is published in someone else's
group cannot be taken back.

Length (3500 characters) and markup are checked beforehand: a tag Telegram
does not know would mean not "an announcement without italics" but an
announcement that never arrives. A draft lives ten minutes, so a forgotten
one does not surface in the group the next day. If sending fails, the bot
names the reason — usually the bot was removed, lost its rights, or the
group forbids messages from bots.

### An invite link for a chat (since 4.9.9.1)

The bot can find a link itself: the group's public name, the owner's link,
or one it creates. But there are cases where that does not work — a closed
chat that admits by request, a link limited by time or by number of uses,
an invitation the owner issued separately.

Then the **superadmin** sets it, and it becomes the primary link rather
than a fallback. Two ways, whichever suits:

* **in the bot** — the "Chats" section, the ➕ button next to the group
  (🔗 if a link is already set). Send the link as a message; `-` removes
  it again;
* **in the panel** — the "Chats" section, the "Invite" column: the field
  is edited where it is shown. An empty field removes your own link.

Since 4.9.9.2 such chats are visible to **all users**: a "💬 Our chats"
button appears in the main menu with a button for each one. Only chats
with a manually set link are shown: a closed group the bot was merely added
to for moderation does not become open to everyone because of it.

Once saved, the jump button in the chat list follows it. Any address of
the form `https://t.me/…` will do.

### Posting to a group from the panel (since 4.9.9.1)

The same as the ✍️ button in the bot, and in the same two steps: pick the
group, write the text, see how the members will read it, and only then
send. The preview cannot be skipped: what is published in someone else's
group cannot be taken back.

Markup is written with tags — `<b>`, `<i>`, `<a href=…>`. A tag Telegram
does not know is rejected before sending: it would mean not "an
announcement without italics" but an announcement that never arrives.

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

**On a phone the panel works as it is.** Sections move to their own
full-width row, buttons and links are sized for a finger, wide tables
scroll sideways, and the user list unfolds into "field: value" cards on
a narrow screen. The styling is not stripped down: the "Matrix" rain and
the "Reactor" bracket corners stay on the phone too.

### Panel themes

The header button cycles the styling: **light → dark → "Matrix" →
"Reactor"**. The choice is remembered in the browser, per administrator.

"Matrix" is a green terminal with a rain of glyphs and a command prompt in
the heading. "Reactor" is an instrument panel: a grid, bracket corners on
cards, glowing figures.

The styling requests nothing from the server and loads no external fonts:
a panel on a machine without internet access opens exactly the same.
Animations are disabled by the "reduce motion" system setting and stop in
a background tab.

### Updating from the panel

The "Update" section, available to the superadmin, downloads the latest
release's installer from GitHub, checks it and runs it: a snapshot before
replacing anything, building the image, restarting. The downloaded
installer replaces `install.sh` in the installation directory. If GitHub
is unreachable, the reason shows up in the log on the same page.

**Before 4.9.8.9 the button reinstalled the version already in place:**
it ran the `install.sh` sitting on the server, and that file carries the
code inside itself. The fix lives in the bot's code, so a server on
4.9.8.8 or older has to be updated by hand once, with a fresh installer:

```bash
cd ~/radar_bot
curl -fsSLo install.sh https://raw.githubusercontent.com/Chistovik92/radar/main/install.sh
bash install.sh
```

After that the panel button works on its own.

### Command line

Everything the panel can do also works from a console — the wrapper sits
next to the installation:

```bash
bash tools/radarctl.sh --help
bash tools/radarctl.sh sources list
bash tools/radarctl.sh features on digest
bash tools/radarctl.sh backup create
bash tools/radarctl.sh rustdesk connections --json
bash tools/radarctl.sh doctor --quick
```

Bot commands run inside the container (that is where the database and
`.env` live); installation commands run on the host: `update`, `restore`,
`wipe`. Reading commands accept `--json`; destructive ones do nothing
without `--yes` and return code `2`, distinct from the error code — so
that `cron` never confuses "not confirmed" with "broken".

### Removing the installation

For a server left behind after a migration: it removes the containers,
the image and the whole directory, along with the database, keys, backups
and logs:

```bash
bash tools/radarctl.sh wipe          # asks for confirmation
bash tools/radarctl.sh wipe --yes    # no questions
```

The same is available in the panel — Maintenance → Removal, behind the
`panel_wipe` feature (off by default) and confirmed by typing a word
rather than clicking a button. The panel stops answering while it runs:
it lives in the very container being removed.

**What removal does not do:** it does not revoke issued tokens. If the
server leaves your hands, change the bot token at @BotFather and the AI
keys — they were in `.env`. And note that deleting a file on a flash card
does not erase the data physically: a board is safer reflashed. The steps are
visible in the panel itself — the installer writes a step-by-step log into
`data/logs`, and the page reads the latest one, refreshing itself while the
work is in progress. During the image rebuild the panel is briefly
unavailable: that is the bot's own container restarting; once it is back,
the page finishes reading the log.

**The `panel_update` feature is off by default, and not out of token
caution.** For the container to update the system it needs the Docker
socket, and a Docker socket inside a container is equivalent to root on the
host: whoever reaches the panel reaches the server. Enable it knowing that
price. The panel still runs no arbitrary commands — only one fixed
scenario; there is no server terminal in it and there never will be.

**Keys go in but never come out.** An existing value is shown only as a
mask such as `AIza…9kQw`: enough to check which key is in place, not
enough to take it. Access to a hijacked panel session must not mean access
to every key at once. The full value stays in `.env` on the server, and
the panel's own log records the key's name, never its value.

### The MAX messenger (since 4.9.9.4) ⚠️ not verified in operation

The "MAX messenger" feature (`platform_max`, off by default). The adapter
is written from the [dev.max.ru](https://dev.max.ru/docs-api/)
documentation: polling for events, sending messages, answering button
presses, the platform's limits and a 30-requests-per-second limiter. The
token is set with `MAX_BOT_TOKEN`, the address with `MAX_API_URL`.

**Not a single request has run against a live server.** MAX issues tokens
only to verified Russian legal entities, and without a token neither the
address, nor the field names, nor the response shapes can be checked.

Since 5.7 MAX is a full sign-in to the shared account: an address is set
with `/address` or a geolocation (saved after confirmation), alerts for it
arrive here, and `/link` links MAX with Telegram, VK and Discord — see
"One account in every network" below. Categories, quiet hours, weather and
subscriptions are configured in the Telegram bot.

### Discord (since 5.5) ⚠️ not verified in operation

Feature flag `platform_discord`, off by default. Discord here is a
**community channel**, not address-based alerts: no alert goes out
without confirmed geography, and addresses live in Telegram.

- slash commands `/about`, `/status`, `/summary`, `/help`;
- a daily summary in the `DISCORD_CHANNEL_ID` channel at
  `DISCORD_SUMMARY_TIME` (20:00 by default): how many events there were
  per category and how many all-clears — no addresses, cities or text;
- a channel message when monitoring goes silent and when it recovers.

The adapter is written on `aiohttp` without `discord.py`: REST and the
Gateway (WebSocket) with heartbeats, session resume and the platform's
limits respected. The protocol was checked against the `discord.py`
source; the transport is exercised over a real WebSocket against an
emulator (`tools/discord_http_check.py`, a CI step). It has never talked
to real Discord. Setup is in section 15 of
[docs/API_SETUP.md](docs/API_SETUP.md).

### One account in every network (since 5.7) ⚠️ not verified in operation

A person has one profile — addresses, settings, role, subscription — and
Telegram, VK (flag `platform_vk`), MAX (`platform_max`) and Discord
(`platform_discord`) are equal ways to sign in to it. The platform flags
are off by default. You can start in any network:

- **VK and MAX**: `/address street, house, city` or a geolocation — the
  bot shows the address it found and saves it **only after "yes"** (no
  alert without confirmed geography). `/addresses` lists them, `/remove N`
  deletes one, plus `/status` and `/lang en`;
- **Discord**: the same `/address`, `/addresses`, `/remove` as slash
  commands, replies are visible only to the author, alerts arrive in DMs;
- **Telegram** — the full interface, as before.

**Linking networks.** In one network — `/link` (in Telegram also
"⚙️ Alerts" → "🔗 Linked networks"): the bot gives a six-digit code valid
for 10 minutes. In another network the code is sent to the bot (in
Telegram as `/link CODE`) and confirmed with "yes". After that addresses
and settings are shared, **alerts arrive in every linked network**, and
all networks of the account are told about the new link.

- if the account has Telegram, the profile is stored under the Telegram
  key; when Telegram is linked to a VK account, the addresses move there;
- two profiles' addresses are merged (points closer than 40 m are the
  same), the role stays with the main profile: merging never raises it;
- an account has one entry per network — two Telegram accounts never merge;
- confirmation is mandatory: a code links addresses too, and a planted
  code would give someone else's account access to them; brute force is
  limited to five wrong codes per 10 minutes;
- `/unlink` in any network or the button in Telegram detaches a network.

**Web panel sign-in by code.** `/panel` in any network of the account
(moderators and above) gives a one-time code valid for 5 minutes; it is
entered on the panel's sign-in page instead of the Telegram widget — so the
panel also opens by IP address, where the widget does not work. The other
networks of the account are told about every code request.

Copies and delivery to VK, MAX and Discord run as background tasks:
Telegram does not wait for them, and a platform failure does not delay
the alert loop.

Viber and WhatsApp are not connected: since 2024 Viber bots require a
contract and €115 a month plus a fee per message, and since July 2025
WhatsApp charges for every template message and requires Meta business
verification — details in the [roadmap](docs/ROADMAP.en.md). VK setup is
in section 16 of [docs/API_SETUP.md](docs/API_SETUP.md).

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
