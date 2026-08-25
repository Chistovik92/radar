# Roadmap

What is being built in which version, in what order, and why. The document
is updated with every release; current state is in
[STATUS.md](STATUS.md) (Russian only), the earnings plan is in
[MONETIZATION.en.md](MONETIZATION.en.md).

Every notable capability is declared as a flag in `radar/features.py` and
turned on by the superadministrator right inside the bot, without a version
update. So "version" means "the code has arrived," not "the feature is on":
new things arrive switched off, get turned on on the live system, and can be
killed with one button if something goes wrong.

**Support for old versions.** Since 4.6.1 the `db.json` importer has been
removed entirely: migration code from a version nearly two years old had
never been verified by anyone, and keeping it meant carrying an unverified
path through every build. So 4.6.0 is the last version that reads the 3.x
format, and upgrading from it goes in steps: **2.x → 3.3.5 → 4.6.0 →
current**. The 4.6.0 step cannot be skipped: newer code will not read the
JSON and will silently start with an empty database. The full upgrade table
is in [README.en.md](../README.en.md).

---

## Versioning rules

The number lives in `radar/__init__.py`; the installer, the bot and the
documentation all take it from there. The format is two to four numbers:
`X.Y`, `X.Y.Z` or `X.Y.Z.W`. The smaller the change, the deeper the
component:

| Component | Grows when | Example |
|---|---|---|
| `X` — major | platform change or data incompatibility | 3.x → 4.0 |
| `Y` — minor | a large block of work: web panel, digests, server move | 4.6 → 4.7 |
| `Z` — patch | a finished feature within that block | 4.7.4 → 4.7.5 |
| `W` — fourth | a small fix, a bug fix, a documentation pass | 4.7.5.3 → 4.7.5.4 |

Three rules that are not worked around:

1. **The number only grows and is never reused.** Going back to a lower
   number, or publishing the same one twice, is not allowed: the
   installer builds its list from releases, and nobody could tell which
   of the two they installed. Gaps in the fourth component are fine and
   are the author's call — the history has 4.7.3.5 right after 4.7.3.3
   and 4.7.4.3 right after 4.7.4.
2. **Every change is a complete release:** bump the number, commit, push,
   tag and publish a GitHub release. A half-release — code in `main` with
   no tag — has already happened (4.6.5 and 4.7.3.2 shipped without one)
   and it breaks `install.sh --versions`: the installer builds its list
   from releases, and a version that is not there does not exist as far as
   it is concerned.
3. **The number is updated everywhere at once:** `radar/__init__.py`,
   `README.md`, `README.en.md`, `docs/STATUS.md` (the version history row)
   and, if the plan changes, `docs/ROADMAP.md` together with
   `docs/ROADMAP.en.md`. The Russian and English versions of a document are
   updated together — a divergence is noticed only by a reader, and they
   have no way to tell which one is correct.

The sections below run in strictly ascending version order — that broke
once and went unnoticed for a while. Items in the 4.7 block share one
continuous sequence (1–26), because the work there ran interleaved and
referring to a number is easier. Sections 4.8 and later are plans, each
numbered from one.

---

## 4.0 — foundation ✅ done

1. **A real database instead of JSON.** SQLAlchemy 2.x async. **SQLite** by
   default — a file next to the bot, no separate container or password;
   PostgreSQL is enabled via a profile on a more capable machine. Same
   schema either way: `users`, `locations`, `sources`, `events`,
   `deliveries`, `features`, `meta`.
2. **A multi-platform schema from day one.** A user has a surrogate key
   plus a `(platform, external_id)` pair. Done up front so that 4.2 would
   not need to migrate production data: the same numeric identifier on
   Telegram and on MAX belongs to different people.
3. **Automatic migration** of the 3.x format; the source is kept as
   `db.json.migrated`.
4. **Event history** — the `events` and `deliveries` tables.
5. **Feature toggles** — `/features` for the superadministrator.
6. **A messenger abstraction** — `radar/platforms/base.py`.
7. **Author signature** in every source file, checked in CI.
8. **Renaming**: HydraVPN → HydraSite, `/vpn` → `/partner`.

**Verification:** 165 offline tests, 31 modules, the installer checked
byte-for-byte.

---

## 4.1 — emergency help and submission ✅ implemented

1. **SOS button** — trusted contacts, geolocation, repeats until stood
   down. The contact is chosen with Telegram's built-in button: forwarding
   a message no longer reveals the sender since Bot API 7.0.
2. **Weather for users, sent by the administration** — mode and frequency
   are set on the user's behalf.
3. **Resilience**: 37 checks for corrupted data, empty responses, missing
   fields.

Moved to 4.3: VK and OK sources — they need keys that were not available
yet.

---

## 4.2 — media, MAX, alert accuracy ✅ implemented

1. **Video download by link** with a choice of quality, a custom Bot API
   Server for files up to 2 GB.
2. **MAX adapter** — written, not verified on a live server.
3. **Alert geography** — an alert is not sent without a confirmed match on
   city or region.
4. **Past events** go into the morning and evening digest instead of an
   alert.
5. **Access keys and AI provider comparison** — from the bot, no SSH
   needed.
6. **Gemini model selection** — `/models`, `/setmodel`.

---

## 4.3 — network, providers, VKontakte ✅ implemented

1. **VKontakte as a source** — `wall.get` with a service key. VK's quirks
   are handled: errors arrive with HTTP 200 and an `error` body, codes 6
   and 9 mean rate limiting (the source is not excluded for that), an empty
   array without an error does not mean "no news."
   Flag: `source_vk`.
2. **Switching the AI provider on the fly** — Gemini or DeepSeek. Access
   and balance are checked before switching: DeepSeek bills as you go, and
   a key with a zero balance looks the same as a working one until the
   first request — and the first request would be a real alert being
   parsed.
   Flag: `provider_switch`.
3. **Its own network egress** via sing-box: subscriptions, VLESS,
   Shadowsocks, Trojan, SOCKS5. Managed from the bot, configuration is
   generated automatically. **Adding a key turns nothing on** — the
   superadministrator picks the server and protocol by hand.
   Flag: `egress_proxy`.

Moved to 4.4: Odnoklassniki (needs an application key from apiok.ru), news
digests, weather as an image, quiet hours, anti-spam.

---

## 4.4 — digests and delivery ✅ implemented

1. **News digests** — 12 topics, one message at a chosen time, subscription
   via Telegram Stars. Prices are set by the superadministrator with
   `/digestprice`. Design is in [NEWS_DIGEST.md](NEWS_DIGEST.md) (Russian
   only).
2. **Weather as an image** — PNG rendering via Pillow. The library is
   optional: without it, text is used automatically, which matters under
   mobile-internet restrictions.
3. **Quiet hours** — non-urgent items wait until morning and are delivered
   as one batch. Military threats and emergency-service alerts always go
   through — that is the whole point of the system.
4. **Anti-spam** — comparison by the stems of significant words, not exact
   text: city channels retell the same event with different phrasing.

---

## 4.5 — web panel ✅ implemented

1. **A separate process** under the `web_panel` flag: the panel can crash
   independently of the bot, alerts keep going out.
2. **Sign-in only via the Telegram Login Widget.** Three things are
   checked: the `hash` signature by HMAC of the bot token, the freshness of
   `auth_date`, and the role in the database (administrator or above). No
   passwords — there is no reason to add one when the account is already
   verified.
3. **Sections:** overview, users and locations, sources, events and
   delivery statistics, feature-toggle state, an action log.
4. **Security:** `httponly` and `secure` cookies, a 4-hour session, a limit
   on login attempts, constant-time signature comparison, a log of every
   sign-in and every rejection.

**There is no server terminal in the panel, and there never will be.**
Running commands remotely from a browser, if a session leaks, hands over
the whole server, not just the bot's data. Server management stays over
SSH.

---

## 4.6 — sources, digests and weather as an image ✅ implemented

The partner section and promo codes were planned for here but shipped
later: the section in **4.6.4**, promo codes in **4.7.0**. Sources and
digests went ahead of them.

1. **A "Partner projects" section** instead of a single button: a list of
   projects with a description, a link and an icon. The first is
   HydraSite, others are added as data, with no code changes. Order,
   visibility and text are edited by the superadministrator.
   Flag: `partners`. ✅ implemented in 4.6.4; in 4.6.5 section management
   was collected into the "Management" menu.
2. **Personal promo codes.** Generation and issuing — **superadministrator
   only**: create a series, set an expiry and an activation limit, issue it
   to a specific user or segment. A partner project verifies it via a
   signed link with a shared secret — no shared database and no mutual
   availability dependency. The same promo codes also work for a news
   digest subscription.
   Flag: `promo_codes`. ✅ implemented in 4.7.0 together with the partner
   export and the web-panel section.
3. **News sources and rewrites.** ✅ implemented in 4.6.1.
   - Six topics not tied to a city: IT and gaming, science and tech,
     sports, hobbies and cars, films and series, money and markets. Each
     has its own feeds in `presets.THEMATIC` — city channels do not
     publish this kind of content.
   - Thematic feeds are polled **only for topics people actually want**:
     reading a feed nobody subscribes to just burns requests for nothing.
   - The AI condenses a topic's news into one coherent summary: one
     request per topic, not per news item. Flag: `digest_summaries`.
   - Numbered links to sources sit under the summary. A summary you cannot
     verify is a rumor, not news.
4. **Link shortening.** ✅ implemented in 4.6.1, an internal utility.
   Built into the web panel (`/s/<code>`), no separate certificate needed.
   Only the superadministrator can add links: a public shortener attracts
   phishing, and the domain pays for it — along with the links inside
   danger alerts. Settings: `SHORT_BASE_URL`, `SHORT_SALT`.
5. **Weather as an image — reworked.** ✅ implemented in 4.6.0.
   - A global switch for everyone: the `weather_image_all` flag overrides
     personal choice without erasing it. Turn the flag off and the previous
     choice comes back.
   - The background changes with time of day **at the location's point**,
     not by the server's clock: night, dawn, day, sunset. Computed from
     local time and the local sunrise and sunset.
   - Wind: a direction arrow, speed, where it is blowing from, a
     descriptive strength rating, gusts. The arrow shows **where** it is
     blowing to — that reads more naturally.
   - The moon, with phase and illumination, drawn when it is visible.
   - A separate palette for a light daytime sky: white captions on a blue
     background were unreadable.

---

## 4.7 — verifying backup and restore

Data has to survive any failure — its own or mine. The mechanisms are
written; this section is about making sure they actually work, before a
backup is ever needed for real.

1. **A backup with one command.** `install.sh --backup`: a `pg_dump`
   database dump, `.env`, files from `data/` — into one archive with a
   manifest. Implemented in 4.0.5. Scheduling and rotation in 4.7.3.5: the
   `backup_schedule` flag, a nightly backup, the last seven kept.
   Rotation is not there for tidiness: without it, backups would fill the
   single-board computer's disk within weeks, and the first thing to break
   would not be backups — it would be the bot itself, with no room left for
   the database. The backup is taken inside the monitoring cycle, not as a
   separate job, so it never fires mid-deployment.
2. **A restore with one command.** ✅ implemented in 4.7.4.3:
   `tools/restore.sh` — a separate script that the installer places next to
   the install (`restore.sh` in the bot's directory). Separate on purpose:
   restore is needed exactly when the install is broken, and at that
   moment the installer itself may not run at all. No image builds and no
   network calls: unpack, put files back, bring it up. `--list` shows the
   available backups, no arguments takes the latest one.
   The role used to be played by
   `install.sh --rollback`: a snapshot of the install and the database is
   taken before every deployment, the last five are kept. ✅ implemented in
   4.5.6.
3. **Rollback on a failed install.** Any interruption after files have been
   overwritten offers a restore instead of leaving the system half
   upgraded. ✅ implemented in 4.5.7.
4. **Full reset** — `install.sh --reset`: back up, remove the database and
   files, install from scratch. Implemented in 4.0.5.
5. **A fire drill — the main point of this section.** Restore that has
   never once been tested should be considered broken. On a clean machine:
   deploy from scratch, fill it with data, take a backup, tear the install
   down completely, restore from the backup. Separately — restore on
   different hardware, since a backup has to survive not only an error but
   the death of the single-board computer itself.
6. **Integrity check** — implemented in 4.7.3.5: a "Check integrity" button
   in the backups section, recounting users, locations and sources, with a
   warning if there is no data. The same recount runs automatically during
   a move to another server (4.7.1).
7. **The PostgreSQL dump loads itself.** ✅ fully closed: for server moves
   in 4.7.1, for rollback in 4.7.6.5. Previously `--rollback` printed a
   `docker exec … psql …` command and suggested running it by hand — that
   is, at exactly the moment the installation is already broken and psql
   is the last thing on anyone's mind. Loading moved into a shared
   `load_pg_dump` function: two separate implementations would inevitably
   drift apart — one gets fixed, the other is forgotten. The dump is
   loaded **before** the bot starts, otherwise the bot creates an empty
   schema and the dump lands on top of it half-way. It also turned out
   that rollback on a PostgreSQL installation brought the bot up without
   the `postgres` profile — that is, without the database itself — fixed
   in the same place.
8. **Maintenance mode.** The bot answers "work in progress," the background
   cycle is stopped — so alerts are not lost and not double-sent during
   operations. Flag: `maintenance`. ✅ implemented ahead of schedule in
   4.5.6.

   **Extended in 4.7.8.** The mode turned out to have a hole exactly where
   it is needed most: it only works while the bot is **running**. During an
   update the container is down for about three minutes (build,
   diagnostics, start), and there is nobody to answer for all of it. Worse,
   startup runs `delete_webhook(drop_pending_updates=True)` — messages that
   had piled up were erased without a trace, and anyone who wrote during
   the update never got a reply. For an alerting system that is doubly bad:
   silence is indistinguishable from a breakdown.

   Now, before clearing the queue, the bot fetches the pending updates once,
   extracts **only the chat identifiers** from them, and writes to those
   people: "there was maintenance, please send it again."
   Flag: `restart_notice`.

   The key decision: the updates themselves are **not processed**. Replaying
   a ten-minute-old SOS press, or re-parsing a location that was sent then,
   is not acceptable — it would look like an event happening right now,
   which is exactly what this system must never do. There is a dedicated
   test asserting the module never touches the dispatcher.

   An instant reply *during* the downtime was **deliberately not built.**
   It would need a separate stub process holding the same token, and a stub
   left behind would keep stealing updates from the real bot — which would
   then look dead. Three minutes of delay is cheaper than that failure.

### 4.7 — installer: languages and version choice

9. **Two installer languages: Russian and English.** Finished in 4.7.3:
    the installer asks for a language at the start (when the terminal is
    interactive), every step heading is translated, along with the move
    procedure, the timing report and the summary. Started in 4.7.2. The
    language comes from `--lang=ru|en`, the `RADAR_LANG` variable, or the
    system `LANG`, and is remembered in `.env`. Russian by default.
    The scope of translation is deliberately limited to what a person
    reads: step headings, the move procedure, summaries, prompts.
    Technical log lines stayed in Russian — only the author reads them, and
    translating them would double the maintenance burden for no benefit.
    **Closed in 4.7.6.5:** the remaining screens are translated — the
    database choice with all its explanations, database maintenance, the
    "what to do with the existing installation" menu, the `.env` question
    and the diagnostics line. That is also when a trap surfaced:
    `info`/`ok`/`warn` already go through the `tr_msg` mechanism, where
    the Russian string itself is the key, and the log always receives the
    Russian original. Putting `$(t …)` inside them would have broken that
    — the log would have become bilingual. So menus and prompts go
    through the dictionary, while `info`/`ok`/`warn` messages go through
    `tr_msg`. Dictionary completeness is now checked by
    `tools/lint_installer.py`: a key defined in only one language used to
    silently return an empty string.
10. **Documentation in two languages.** `README.en.md` — 4.7.3.1,
    `MONETIZATION.en.md` — 4.7.5, `ROADMAP.en.md` — 4.7.5.3.
    **Still left:** STATUS, API_SETUP and NEWS_DIGEST — the author's
    working documents, read mostly during development itself, so
    translating them is the least urgent.
    Since 4.7.5.4 README and ROADMAP are updated **in both languages at
    once**, together with the change itself: a divergence between the
    Russian and English text is found only by a reader, and by then they
    cannot tell which version is the correct one.
11. **Choosing which version to install.** Implemented in 4.7.3.1, an
    interactive list picker added in 4.7.3.3, and in 4.7.3.5 a question
    about skipping the system package update:
    `--versions` shows the list of GitHub releases, `--version=TAG`
    installs the one requested. Installing an older release **is** the
    rollback — it is not blocked and needs no confirmation: if the new
    version broke something, you need to go back immediately. When an
    install fails, "install the previous release from GitHub" appears
    among the offered actions — for when the code itself is broken and the
    snapshot cannot help.
    **By default the code from `main` is installed**, regardless of
    whether it has been tagged as a release: the author's server should
    always run the latest version, not the latest one that happens to have
    a tag.
    A caveat that had to be accounted for during implementation: unreleased
    code has not had manual review, so a snapshot is taken before
    installing it (it already is, either way) and a warning is shown.
12. **TLS for the web panel and short links.** ✅ implemented in 4.7.5, and
    in 4.7.5.1 wired into the installer: it asks about the domain, checks
    whether a certificate already exists, and **carries the setup through
    to the end** — writes the address into the link shortener and sets up
    the salt. Getting a certificate alone is not enough: without an address
    and a salt, short links stay off, and there is no way to tell why. An
    existing salt is never overwritten — changing it would break links
    already sent out.
    Implementation details:
    `tools/tls.sh domain [email]` brings up Caddy in front of the panel.
    Caddy was chosen over certbot: it renews the certificate on its own, no
    cron and no hooks needed — for a machine nobody watches daily, that
    matters more than flexibility, because a forgotten renewal breaks the
    panel exactly three months later.
    The script checks the A record and whether port 80 is free **before**
    talking to Let's Encrypt: they allow five failures per hour per domain,
    and it is not worth spending attempts on a check that is bound to fail.
    Earlier wording of this item: A known complication: the check reaches
    port 80 **from the outside**, and if the router does not forward it or
    the ISP blocks it, issuance silently fails. Before 4.7, link shortening
    works over plain HTTP on whatever address is already up: it does not
    need a certificate.

---

## 4.7 — other work

Collected here is what does not deserve its own version but keeps piling
up.

13. **Measurements instead of guesses.** ✅ closed: the tool — `/perf` —
    was built in 4.5.7, readings were taken on the production server in
    4.7.6.5, and the optimization shipped in 4.7.7.

    What the measurement showed (RK3318, 35 sources, 21 minutes observed):

    | Stage | Share | Average |
    |---|---|---|
    | Source collection | 100% | 51.2 s |
    | AI analysis | 0% | 10 ms |
    | Alert delivery | 0% | 1 ms |
    | Digest delivery | 0% | 1 ms |

    Meanwhile: 2 min 50 s of CPU time over 21 minutes, load average 0.07
    across four cores, 247 MiB of memory. The machine was idle: 51 seconds
    of a 180-second cycle went into waiting on the network, one source at
    a time.

    The `/perf` report itself concluded that "collection is bound by the
    network, not by code speed." True to the letter and misleading in
    substance — and that turned out to be the main finding: **sequential
    waiting is not cured by faster code but by overlapping the waits**.
    `collect()` walked the sources strictly in turn, each waiting for the
    previous one.

    Done in 4.7.7: a parallel walk capped by `SOURCE_CONCURRENCY`
    (6 by default) — 51 seconds becomes roughly 10–14. The cap is
    mandatory: thirty-five simultaneous requests to `t.me` from one
    address look like scraping, and it is the alerting system that pays
    for it. Two properties that are easy to lose unnoticed were preserved:
    result order (deduplication through `seen` depends on it) and
    resilience — one broken feed does not bring the cycle down.

    **The second measurement mattered more than the first.** Right after a
    server reboot came a complaint that the bot "takes a long time to
    answer, or does not answer commands at all", and `/perf` showed 1 min
    41 s of CPU time over one minute of observation at a load average of
    0.54. The core was busy, not waiting on the network — the opposite of
    the first reading.

    The cause: `BeautifulSoup(page, "html.parser")` and `ET.fromstring`
    were computed **directly in the event loop**, and that loop is shared
    with Telegram polling. `html.parser` is pure Python, and parsing a
    channel page on ARM takes hundreds of milliseconds; while the bot
    parsed thirty-five pages, there was nobody left to answer commands.
    It shows up worst at startup, where the warm-up walks every source at
    once.

    Fixed in 4.7.7: parsing moved into `parse_channel` and `parse_rss`
    and runs through `asyncio.to_thread`. This mattered more than the
    parallelism itself — and without it the parallel walk would have made
    things worse: six simultaneous parses would occupy the loop more
    tightly than one.

    **The VK walk is deliberately left sequential:** it has a `sleep(0.4)`
    between requests because VK returns codes 6 and 9 on frequent calls.
    Speeding it up would mean collecting rate-limit errors and treating
    live communities as dead.

    A caveat: observation ran for 21 minutes, so the measurement says
    nothing about memory growth or the `save` stage (which never fired).
    Those need a full-day run.
14. **Flags with no implementation.** Partly closed in 4.7.2: `weather`,
    `ai_analysis` (turning it off now switches to the heuristic, as its
    description promised), `source_telegram`, `source_rss`, `all_clear`,
    `history` now actually toggle behavior.
    In 4.7.4.3, five more were closed: `ai_assistant` (checked together
    with the role), `whitelist_notice` (the check moved inside message
    assembly — the "check it yourself" agreement already failed once
    before), `source_export`, `provider_switch`, `egress_proxy` (their
    buttons hide along with the sections).
    In 4.7.5, the last three were closed: `digest_suggestions` (closes off
    accepting suggestions), `platform_max` (the MAX adapter now runs as a
    separate task behind a flag — the implementation was never verified on
    a live server and must not interfere with Telegram), and `source_ok`
    **was removed from the list**: there is no Odnoklassniki code in the
    project, only keys in the settings existed. A toggle that switches
    nothing on is worse than no toggle at all — it will come back together
    with the implementation, not before.
    **Item closed: every remaining flag toggles something.** A toggle that
    lies is worse than one that is missing: people rely on it.
15. **Event log.** The entry point was added in 4.7.2, **it started
    filling up in 4.7.4.8**: before that, `store_event` and
    `record_delivery` were never called from anywhere, and the section
    always showed empty, even when alerts had gone out. A delivery is only
    logged after it is actually sent: the log has to reflect what was
    received, not what was planned. Open to everyone — these are records of
    a person's own alerts. It shows only what a person was actually sent —
    the log is built from deliveries, not from every event in the system.
16. ~~**The `radar/platforms/` package** (MAX) is not imported by any
    module.~~ ✅ closed in 4.7.5 together with the `platform_max` flag:
    `main.py` starts `MaxTransport` as a separate task when the flag is
    on and `MAX_BOT_TOKEN` is set. The entry sat here already-fixed until
    4.7.6.5 — a small thing in itself, but a roadmap that lies about what
    is done devalues its other entries too.
17. **Video download.** Closed in 4.7.2: a "Download video" button in the
    main menu when the flag is on.
18. ~~The GitHub repository fell behind.~~ ✅ closed in August 2026: `main`
    holds the current version, and tags are in place starting from
    `v3.3.5` and `v4.6.0`, one for every release since.

---

## 4.7.1 — moving to another server

19. **A full move with one command.** ✅ implemented in 4.7.1.
    `install.sh --migrate` on the old machine builds a backup and prints
    the next steps; `install.sh --restore=FILE` on the new one deploys the
    system, loads the dump before the bot starts, and recounts users,
    locations and sources.
    Decisions baked in: the bot on the old machine is **not** shut down
    automatically — two instances sharing one token get in each other's
    way, but deciding when to switch over is a human call; a PostgreSQL
    dump is not loaded into SQLite, and this is stated out loud rather than
    silently skipped.
    4.7.2 added transfer by link: `--migrate` brings up a one-time serving
    of the backup and prints a ready-made command for the new machine —
    copying files by hand is no longer necessary. Protection for the
    transfer: a random 32-character path, served exactly once, a hard
    expiry. Built this way because the backup contains the bot token and
    database passwords: an open link would mean putting them on the public
    internet.
    **The main thing still left is a fire drill:** go through a full move
    on a clean machine. Until then the mechanism is considered unverified.

---

## 4.7.5 — bot interface language

20. **Russian and English in the bot itself.** In 4.7.5 the news digests
    were translated, along with the names of all eighteen topics; in
    4.7.5.2, the SOS section. That is also when a quiet bug turned up:
    duplicate keys in the dictionary silently overrode one another, and the
    section showed the wrong text. A test for duplicates was added — Python
    does not treat a repeated key as an error.
    In 4.7.5.3 the **text** weather summary was translated (WMO condition
    descriptions, "today"/"tomorrow", weekday names, "feels like," forecast
    error messages) — the weather image (`weather_image.py`, the wind rose
    and moon phases from `astro.py`) still stays in Russian, to be
    translated separately. `/help` and the top level of the "Management"
    section were also translated — the heading, the first screen's buttons
    (`keyboards.manage_menu`), the "insufficient permissions" messages. The
    subordinate management screens (sources, users, AI, network, keys,
    backups) were left untouched — that is the next step of the same item.
    The groundwork was laid in 4.7.3:
    the `i18n` module, a `lang` field on the user, a language question on
    first contact — for both new users and those who used the bot before
    the choice existed (the marker for "not asked yet" is an empty field,
    so nobody is left silently on Russian). Menus, key alert strings and
    the video section were translated.
    In 4.7.3.1 the main menu was translated: it used to be assembled
    without regard to language, and with an English interface the buttons
    stayed Russian.
    In 4.7.6 everything an ordinary user can reach was closed out:
    - **role names** (`roles.title`) — visible in `/start`, `/id` and
      "Management";
    - **alert categories** (`matching.category_title`) — the settings
      screen and digest headings;
    - **the whole "Notifications" screen:** weather mode, summary format,
      quiet hours, every prompt and input-error message;
    - **the weather image** — captions, wind rose, wind-force scale and
      moon phases (`weather_image.py`, `astro.py`);
    - **"Suggest a source"** — the only sources screen an ordinary person
      ever reaches.
    **The item is closed for the user-facing part.** What deliberately
    stays untranslated is what only the superadministrator can reach:
    keys, AI management, network, backups, logs, the partner project
    editor. The superadministrator is the author himself, and translating
    those screens would double the maintenance burden without a single
    reader — for exactly the same reason the installer's technical log
    lines stayed in Russian (item 9). Moderator screens — the source queue
    and user cards — remain candidates: a reader is theoretically possible
    there, but there is none yet.
    A caveat that proved its worth: the text used to be scattered across
    modules as inline strings in the code, so the first step was moving it
    into a shared dictionary. Without that, translation would have had to
    be assembled piece by piece, and half the strings would have stayed
    Russian without anyone noticing.

---

## 4.7.9 — the 50 MB sending limit

Telegram does not let bots send files larger than 50 MB through
`api.telegram.org`. There are only two honest ways around it: fit the clip
under the limit, or run your own Bot API Server. This section covers both,
in order of cost.

The prompt for it was a review of [Cliply](https://github.com/Cliply/Cliply),
a cross-platform downloader built on Electron. **Not a single line was taken
from it, and that was deliberate:** Cliply is written in JavaScript and
TypeScript and is a desktop shell around the same `yt-dlp` and `ffmpeg` that
already run here. There is nothing to port. Its licence is GPL-3.0 — the same
as ours, so borrowing would have been lawful; no licence change was needed.

What proved valuable was not a solution but an observation from
`ytdlp-mappers.js`: the codec matters as much as the frame height. That idea
became item 21.

21. **Codec, and the smaller file at the same height.** ✅ implemented in
    4.7.9. A plain bug surfaced: among several variants of the same height
    the **largest** was picked. For a system with a sending ceiling that is
    exactly backwards. The order of preference is now: a known size beats an
    unknown one ("~48 MB" lets you decide whether it fits, blank space lets
    you decide nothing), then the smaller file, then the more efficient
    codec (`av1 > vp9 > h265 > h264`).
    The same frame in av1 weighs roughly half what it does in h264 — under a
    50 MB ceiling that is the difference between 1080p and 480p.
    **The caveat that stops an efficient codec being chosen silently:**
    Telegram's built-in player reliably handles only h264, while av1 and vp9
    arrive as a file rather than a video on some devices. So a risky codec is
    shown in the button caption, and at equal height the default goes to
    whatever is certain to play. Handing over an unplayable file is worse
    than handing over lower quality.
    The `MIN_SANE_MB` floor: some sites carry stubs of a few dozen kilobytes
    at the same frame height, and without it "prefer smaller" would slide
    straight to those.
22. **A size filter in the yt-dlp selector itself.** ✅ implemented in
    4.7.10. Before that the size was checked only after the download had
    finished: a two-gigabyte clip was fetched in full only to be rejected.
    On a single-board computer's link that is tens of minutes and all the
    traffic, wasted.

    Two distinct mechanisms went in, and they should not be conflated:

    - **format selection.** Size conditions were added to the selector,
      using the `<?` comparison — which lets a format through when the size
      field is absent. Some sites do not report a size at all, and a strict
      condition would have left the person with no options. The chain ends
      with the previous unconstrained variants: if nothing fits the limit,
      it is better to download something plainly large and say so honestly
      than to answer "no formats found";
    - **`max_filesize` — a safety catch.** It aborts the download once the
      size becomes apparent mid-flight. This is **not** a guarantee of an
      exact fit: yt-dlp checks the limit against each file separately, while
      Telegram looks at the merged one. So the video stream is picked with
      room reserved for audio (`audio_reserve_mb`), and the exact check
      stays after the merge.

    The quota is not spent on an aborted download — it was already only
    charged once a finished file existed.
23. **A free-space check before downloading.** ✅ implemented in 4.7.11.
    A clear refusal instead of a filled disk.
    **Three times** the clip's size plus headroom is required, and that is
    not over-caution: yt-dlp downloads video and audio as separate files and
    then merges them into a third — at peak all three sit on disk at once.
    Refusing matters more than convenience here. On a single-board computer,
    running out of space breaks not the video download but the whole bot:
    the database has nowhere to write, and alerts stop. The clip can wait,
    an alert cannot.
    The opposite case is handled separately: if free space cannot be
    determined, the download is **allowed**. Forbidding work on a guess is
    worse than skipping the check.
24. ~~**Splitting into 50 MB parts.**~~ ❌ rejected in 4.7.12 by the
    author's decision: a person should not have to reassemble the video
    themselves. Recording it beats quietly not doing it: a rejected option
    with a stated reason does not come back around for discussion.
25. **Re-encoding to a target size.** ✅ implemented in 4.7.12, flag
    `media_transcode`, off by default.

    A variant larger than the limit is no longer simply refused: the bot
    offers to compress it, naming the resolution and the time. If the person
    agrees, the source is downloaded in full (the download limit is **not**
    applied then — otherwise there would be nothing to compress) and handed
    to ffmpeg.

    How the plan is computed: the bitrate follows from duration and target
    size, the resolution is picked from a ladder (1500 kbps — 720p, 800 —
    480p, 400 — 360p, 200 — 240p), and the remainder goes to audio. No
    upscaling: raising the resolution during compression spends bitrate on
    invented pixels.

    **Refusing matters more than delivering.** The bitrate is dictated by
    duration and no arithmetic gets around it: 50 MB for an hour of video is
    110 kbps, which is not enough for any resolution. The boundary sits near
    24 minutes; past it the bot explains the arithmetic and points at a local
    Bot API Server instead of producing unwatchable mush. Handing over mush
    instead of video betrays the expectation rather than fulfilling the
    request.

    To keep this from harming the main job: `nice -n 19`, two threads out of
    four cores, a hard `TRANSCODE_TIMEOUT` (half an hour by default). When
    the CPU is short, the clip should suffer, not the alerts. The time is
    stated up front — "please wait" without a number is not a warning. In
    practice it comes out at 3–8 minutes: a longer clip gets a smaller
    resolution, and that encodes faster.

    The RK3318 does have a hardware encoder (rkmpp), but it needs a specially
    built ffmpeg and a device passed into the container — the
    `python:3.11-slim` image has neither.
26. **Its own Bot API Server.** ✅ brought into working order in
    4.7.12.5. Raises the limit to 2 GB and makes item 25 almost
    unnecessary.

    It turned out the path was **dead**: the container has been described
    in `docker-compose` since 4.2 and the bot knows how to talk to a local
    server, but the `TELEGRAM_API_SERVER` variable was never set anywhere
    — not by the installer, not otherwise. So the profile would come up
    and the bot would still call the public Telegram. The only visible
    symptom was that the limit did not change.

    The installer now **asks** about a local server and, given consent,
    writes everything at once: `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`,
    `TELEGRAM_API_SERVER` and `MEDIA_ENABLED`. The keys are validated on
    the spot: `api_id` digits only, `api_hash` exactly 32 hexadecimal
    characters. A typo would otherwise surface at the first large upload.

    **Declining writes nothing**, and the question returns on the next
    run: the keys come from a third-party site, and a person may not have
    them at hand right now. Installation must not stall on something that
    requires going to a browser.

    The caveat stands: a local server caches files on disk and needs
    noticeably more space. Compose clears cache older than six hours and
    when the disk fills past 85 percent, but how much that is on an RK3318
    has to be measured, not assumed.

---

## 4.7.12.5 — images and captions

27. **Downloading images by link.** Deliberately separate from video: the
    mechanics differ. Video goes through yt-dlp with quality selection,
    merging and compression; an image is one request and one file, and
    routing it the same way would burden a simple task with the lot.
    A large image is not refused — it goes as a **document**: Telegram
    accepts photos only up to 10 MB, while documents get the same 50 MB as
    video. The file opens fine, just without an inline preview. Refusing
    would be worse: the person asked for a file, not a preview.
    Disk protection sits in two places and both are needed: the declared
    `Content-Length` rejects the plainly oversized **before** downloading,
    and the actual volume is counted as it arrives and aborted on excess.
    A server can declare one size and send another, and a link can lead to
    an endless stream; a filled disk on a single-board computer stops not
    the images but the alerts.
28. **Caption and description text.** The "📝 Description" button appears
    only when a description actually exists — an empty button would
    promise for nothing. Long text is trimmed at 3500 characters with an
    explicit note: Telegram would have cut it silently mid-word.

---

## 4.8 — optimizing for the single-board computer

The system stays on the current server. A move is not planned — instead,
the work is making the existing resources comfortably enough.

1. **Profiling.** The measurement tool — the `/perf` command — was built in
   4.5.7; what remains is PostgreSQL under real load and conclusions from
   the readings.
2. **Tuning PostgreSQL for the actual amount of memory.** In 4.0.5 the
   settings were already raised for 4 GB (`shared_buffers=256MB`, a 1 GB
   cache, parallel workers enabled). In 4.6, automatic tuning based on
   available memory at install time.
3. **Container limits** — memory caps so that one process cannot drag down
   the whole system. Set in 4.0.5, refined based on measurement results.
4. **Cutting network calls:** batching geocoding requests, caching
   Open-Meteo responses, sensible polling intervals for sources.
5. **A compact database:** automatic history cleanup by
   `EVENT_RETENTION_DAYS`, regular `VACUUM`, monitoring size and warning in
   the bot as it grows.
6. **A fast start.** The schema is created directly from the models,
   without running Alembic inside the bot process — mixing synchronous
   Alembic with an already-running event loop was what hung the startup on
   ARM.

---

## 4.9 — operations

1. **Zero-downtime updates:** the schema is applied before the restart,
   rollback to the previous version with one command.
2. **Metrics:** number of alerts, delivery latency, AI quota spend, share
   of dead sources — in the panel and in the bot.
3. **Automatic source checks** on a schedule, with a report.
4. **Automatic cleanup** of history and logs.
5. **A system health panel** for the superadministrator right inside the
   bot: memory, disk, database size, container state.

---

## 4.9.5 — music and playlists

An idea from August 2026: uploading tracks to the bot, personal playlists,
similar-track suggestions. A subsystem separate from monitoring — placed
here for exactly that reason: it must never delay danger alerts.

1. **Upload and storage.** A track is sent as a file or a link, sorted
   into playlists, and plays through Telegram's built-in player. The
   upload mechanics already exist in `media.py` — reuse them instead of
   writing them again.
2. **Sources for suggestions.** Options, from simple to complex:
   - **your own files** — matching by ID3 tags (artist, genre, year), no
     external requests at all. Start here: it always works and asks nobody
     for anything;
   - **MusicBrainz + ListenBrainz** — open databases, a free license, a
     public API with no key. They give "similar artists" and genres
     honestly and legally;
   - **Last.fm API** — a free key, rich "similar to" links, but the terms
     of use restrict resale;
   - **YouTube Music** — tempting, but only reachable through unofficial
     scrapers: breaks with every layout change and directly violates the
     service's terms. Not viable as a foundation, at most a manual,
     one-off import on an explicit command.
3. **Mixing.** Shuffle what was uploaded, build a selection by genre or
   artist, continue a playlist with something similar.
4. **A constraint that cannot be worked around.** Distributing other
   people's recordings is distribution, not personal listening, and paid
   access to tracks would turn the bot into a piracy service with all the
   consequences for the domain and hosting. The safe frame: **everyone
   listens to what they uploaded themselves**, there is no shared library,
   and what becomes paid is capacity and convenience (storage volume,
   number of playlists, similar-track suggestions), not the music itself.

---

## 5.5 — Discord

The "other messengers" section is split per platform: they differ not in the
amount of work but in what someone else's API allows at all. Putting them in
one version would promise the same thing where the capabilities are not the
same.

The `Transport` protocol from 4.0 is built for exactly this: the core does
not know where a message came from, so a new platform is one adapter, not a
rewrite.

1. **Discord.** The simplest of the remaining platforms: a bot is created in
   the Developer Portal in a minute, the token is issued immediately,
   verification is only needed past 100 servers. An adapter over the Gateway
   (WebSocket) or via discord.py.
   Telegram's buttons map onto Discord's components almost one to one, but
   there are differences: a limit of 5 buttons per row and 5 rows, a
   mandatory response to an interaction within 3 seconds, and a separate
   permission to read message content (Message Content Intent).
   The sensible use case is not address-based alerts but a community
   channel: summaries and system status.

---

## 5.6 — Viber

1. **Viber.** A public account is registered without a legal entity, and the
   Bot API works over a webhook — HTTPS arrived here in 4.7.5, so there is no
   external obstacle. Buttons and keyboards map onto `Button` closely to how
   it works in Telegram.
   The constraint to account for: Viber counts as a subscriber only someone
   who subscribed to the account themselves, and writing first to anyone who
   has not is not allowed. For alerts that means the same order as SOS in
   Telegram: subscription first, alerts after.

---

## 6.0 — MAX

1. **MAX — bringing it to production.** The adapter was written in 4.2, but
   not a single request has run against a live server. Needed: owner
   verification (a legal entity, sole proprietor, or self-employed person
   registered in Russia), a webhook instead of long polling, linking Telegram
   and MAX accounts, its own FSM on the shared database. The blockers here
   are not in the code — the code can be finished in a day, the verification
   cannot.
   Plus a platform limit: **reading other people's public channels on MAX is
   not possible** — the API is bot-centric. MAX is a delivery channel, not a
   source.

---

## 6.5 — WhatsApp, deliberately reduced

1. **WhatsApp.** To be implemented, but in a knowingly limited form, and the
   limitation is stated out loud — that is the main point of this item.

   **Alerts will not work over WhatsApp.** The Cloud API forbids proactive
   messages outside a 24-hour window from the person's last contact.
   Everything outside that window must be a pre-approved Meta template with
   fixed text and a couple of substitutions. Our alerts are by definition
   sudden, arbitrary in wording, and arrive when the person has written
   nothing. That is not "hard" — it is incompatible by the platform's design.

   What is genuinely available: **news digests and scheduled summaries**
   through approved templates, replies to enquiries inside the 24-hour
   window, help and system status.

   So inside the WhatsApp version the bot **openly offers a move to
   Telegram**, explaining that danger alerts arrive there instantly and
   without templates. Staying silent about this is not an option: someone who
   signed up for alerts and never receives them ends up worse off than if
   they had never signed up. The line "this system does not replace official
   warning channels" gains a second one here: **WhatsApp does not replace the
   Telegram version of this bot.**

   Needed: business verification with Meta, a phone number, approval of each
   template. None of those conditions is closed by writing code.

---

## 7.0 — VKontakte and Odnoklassniki as messengers

1. **VKontakte as a messenger.** A proven path: the bot is attached to a
   community, the access key is issued in the "Working with API" section,
   events arrive via the Callback API (a webhook, and we do have a static IP)
   or via Long Poll with no external address. Buttons map onto `Button`
   almost one to one. Placed this far out deliberately: VK already works here
   **as a source** (4.3) and pays off daily, whereas VK as a messenger is a
   convenience for people who are not on Telegram.
2. **Odnoklassniki.** Harder: the application is registered on apiok.ru, and
   confirmation plus a signature on every request are required. Both as a
   source (the `source_ok` flag was removed in 4.7.5 — there must be no
   toggle without an implementation) and as a messenger. Worth taking on
   after the VK adapter has run for a season.

---

## Further out — under discussion

- Mini Apps: a map of locations and event history inside the messenger.
- Expansion to new cities as users show up there.
- Replacing or duplicating the AI provider based on the `bench/` stand's
  results.
- Exporting summaries for management companies — a first step toward B2B.

---

## Monetization by version

Details are in [MONETIZATION.en.md](MONETIZATION.en.md). In short:

Versions run in ascending order — as does everything else in this document.

| Version | What appears | State |
|---|---|:--:|
| 3.3 | a partner-project button in the menu | ✅ |
| 4.4 | news digest subscription via Telegram Stars | ✅ |
| 4.6.4 | the partner projects section | ✅ |
| 4.7.0 | personal promo codes, conversion statistics | ✅ |
| 4.7.3 | unlimited video download — 10 Stars a month | ✅ |
| 4.9 | channel-effectiveness metrics | planned |
| 4.9.5 | music storage capacity and similar-track suggestions | planned |
| later | B2B export for management companies | idea |

### Video download — monetization (since 4.7.3)

Downloads are open to every role. The limit moved from role-based to
quota-based:

* **20 clips a day for free**, the counter resets daily;
* **10 Stars — a month with no daily cap.**

Counting by pieces, not megabytes: "17 of 20 left" is clear to a person,
while "380 MB left" requires guessing a clip's size in advance beforehand.
What is expensive here is not traffic but the single-board computer's CPU
time.

**The 50 MB size limit is not lifted by the subscription** — and the
purchase description says so plainly. This is a limit of the Telegram Bot
API: a bot physically cannot send a larger file through
`api.telegram.org`. You cannot sell what you cannot deliver.

How the limit will be lifted in later versions — **a custom Bot API
Server.** Telegram gives out its source code, and running through your own
server raises the limit from 50 MB to 2 GB. Support is already in place:
the `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_API_SERVER`
variables, and `media.size_limit_mb()` already returns a different limit
depending on whether it is a custom server or the shared one. What is
left: deploying it as a container next to the bot, automating that in the
installer, and accounting for the fact that a custom server needs
noticeably more disk (files are cached locally) — on the RK3318 that is a
separate question that has to be measured, not assumed.

---

### Link shortening — why it is not in that table

The idea of selling shortening limits was discussed in August 2026 and
rejected. The reasons, so as not to circle back to it:

* **There is nobody to pay for it.** Bitly and a dozen alternatives offer
  shortening for free with no limits. Selling where a competitor offers
  unlimited for free is not a business. Digests are the opposite in this
  sense: there is no ready-made alternative.
* **A public shortener is bait for abuse.** Within a week of opening it up,
  it would start being used for phishing, and the domain would land in
  Safe Browsing. Along with it, the links inside danger alerts would stop
  opening, and HydraSite on the same domain would suffer too.

So the service stays internal: it shortens links inside digests and
operates on the superadministrator's command.

Earnings are built on the **author's own projects**, not third-party
advertising: the partner section leads to HydraSite and other projects,
promo codes track conversion. There are no direct sales inside "Radar"
itself.

---

## Principles that do not change

1. **Danger alerts are always free.** No subscription for an alert, ever.
2. **Ads never appear inside danger messages.** Trust is worth more than
   any conversion.
3. **New things arrive switched off** and get turned on deliberately.
4. **The phrase "this system does not replace official warning channels"**
   stays everywhere: sources are public, classification is probabilistic,
   delivery depends on the messenger.
