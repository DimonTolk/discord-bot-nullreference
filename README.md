# Nullreference Discord Bot

A reusable Python community bot for **Cloudflare Workers** and **Neon PostgreSQL**.
The current season turns a small Discord server into a city contested by five
crime families and a police department. Players participate asynchronously through
slash commands; simultaneous attendance and voice channels are not required.

Game rules live in `src/nullreference/themes/mafia/`. Infrastructure is separate
so the bot can support a different theme next year. In-game messages and help are
currently in Russian. This README describes setup and operation in English.

## Features

- Existing Discord roles determine family or police membership.
- Personal wallets, shared treasuries, spendable influence, and lifetime rankings.
- Limited weekly work, organizer-approved tasks, and asynchronous family operations.
- A random weekly task, automatically posted on Mondays at 12:00 Europe/Minsk.
- Investigations, raids, private bribes, corruption checks, and officer suspensions.
- District contests, ownership transfers, and weekly district income.
- Public game announcements and a persistent news delivery queue.
- Editable flavour text stored in Neon, with no code changes or deployment needed.
- Detailed Markdown help with command examples, sample responses, permissions,
  and limits: `/help`, then choose a `topic`.

A cosmetic shop, automatic assignment of Discord roles, and automatic assessment
of creative submissions are not implemented. Organizers publish tasks themselves
and award completed tasks with `/reward`.

## Cloudflare deployment

Connect the repository to the Worker named **`discord-bot-nullreference`**.
The name must match `wrangler.jsonc`.

| Setting | Value |
| --- | --- |
| Root directory | Repository root (`/`) |
| Build command | `npm run build` |
| Deploy command | `npm run deploy` |

Workers Builds installs npm dependencies using `package-lock.json`. The build
environment needs **Node.js 22+** and **Python 3.12+**. If required, set
`NODE_VERSION=22` and `PYTHON_VERSION=3.12` in build variables.

### Runtime settings

Add these under **Worker > Settings > Variables and Secrets**:

| Variable | Purpose |
| --- | --- |
| `DISCORD_TOKEN` | Bot token; store as a Secret |
| `DATABASE_URL` | Complete Neon PostgreSQL connection URI; store as a Secret |
| `DISCORD_PUBLIC_KEY` | Application public key from Discord General Information |
| `DISCORD_APPLICATION_ID` | Discord application ID |
| `DISCORD_GUILD_ID` | The only Discord server this Worker may serve |
| `SEASON_ID` | Optional; defaults to `mafia-2027` |

IDs and the public key can also be stored as Secrets. Their actual values do not
belong in the public repository. `keep_vars: true` preserves dashboard-configured
variables during deployment.

### Build settings

Separately add these under **Worker > Settings > Build > Variables and secrets**:

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Build Secret for database migrations; requires DDL permissions |
| `DISCORD_TOKEN` | Build Secret for slash-command registration |
| `DISCORD_APPLICATION_ID` | Application ID used during registration |
| `DISCORD_GUILD_ID` | Target server ID used during registration |

**Build and runtime variables are separate.** Runtime secrets and GitHub Secrets
are not automatically available to Workers Builds. The build phase itself is
secret-free, but the deploy command needs the four settings above.

Workers Builds normally supplies its own deployment credentials. For manual CLI
deployment, use `npx wrangler login` or a Cloudflare API token in the environment.
Do not place tokens in command arguments, source files, or `wrangler.jsonc`.

### Build and deployment sequence

`npm run build`:

1. Installs the pinned uv version and restores tools from `uv.lock`.
2. Validates the command manifest and generates the embedded default text catalog.
3. Installs the pinned, universal `workers-runtime-sdk` wheel directly into
   `python_modules/`, avoiding native/Pyodide environment path inference.
4. Checks required SDK files and creates their SHA-256 manifest.

`npm run deploy`:

1. Creates a dry-run upload bundle and checks all SDK files against that manifest.
2. Applies pending SQL migrations in a transaction with an advisory lock.
3. Publishes the verified Worker using Wrangler.
4. Registers the slash-command manifest on the configured Discord server.

A migration failure stops publication. If registration fails after publication,
retry deployment; migrations are idempotent and registration replaces the manifest.
The SDK and Wrangler versions are pinned. The deployed Worker does not include
native database drivers, `discord.py`, or a persistent Gateway connection.

Successful packaging prints:

```text
Upload bundle verified: all 22 Python SDK files are included.
```

**Production branches only:** the deploy command changes the database and Discord
command manifest. Do not give untrusted pull-request builds production secrets.
For a preview, run `npm run build`, then
`npx --no-install wrangler versions upload`, without production database/Discord
credentials. GitHub CI uses a disposable database and a dry-run bundle.

## Neon configuration

In Neon, open **Connect**, select the database and role, and copy the complete
PostgreSQL URI. For the initial setup, use the direct connection endpoint.

```text
postgresql://USER:PASSWORD@ep-example.eu-central-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require
```

Save only the URI as `DATABASE_URL`: no `psql` command, `DATABASE_URL=` prefix,
or surrounding quotes in the Cloudflare value field. Preserve the TLS parameters
provided by Neon. Runtime uses Neon's SQL-over-HTTPS API; migration scripts use
psycopg/libpq in the build environment.

Separate roles are supported: use a DDL-capable migration role for build secrets
and a runtime role with the required table and sequence permissions. A shared
role needs permissions for both migration and normal application operations.

## Discord configuration

1. Create an application in the [Discord Developer Portal](https://discord.com/developers/applications).
2. Copy **Application ID** and **Public Key** from **General Information**.
3. Obtain the **Bot Token** from **Bot**. It is different from the OAuth2 Client Secret.
4. Enable Developer Mode in Discord, then right-click the server and copy its ID.
5. Enable **Guild Install** and install the application with `bot` and
   `applications.commands` scopes.
6. Allow **View Channel**, **Send Messages**, and **Attach Files** in the relevant
   channels. Administrator, Manage Roles, and privileged intents are not required.
7. After deployment, set **General Information > Interactions Endpoint URL** to:

   ```text
   https://<your-worker>.<your-subdomain>.workers.dev/interactions
   ```

   Use the actual hostname from Cloudflare. Discord validates the signature and
   PING response; this check does not access Neon.
8. Run `/start`, configure all six sides with `/family_role`, select the news
   channel with `/news_channel`, and test `/profile` and `/work`.

For a **private bot**, set **Installation > Install Link** to **None** and keep
**Public Bot** disabled. Generate an invitation through **OAuth2 > URL Generator**
using the same scopes and permissions. Public bot status is not necessary for
installation by the application's owner.

The bot may appear **offline** in the member list because HTTP interactions do
not maintain Gateway presence. Commands and REST announcements still work.
`GET /health` checks the HTTP runtime only, not database or Discord connectivity.
The organizer-only `/setup` command checks schema access and registers commands
again; it does not apply migrations.

## Membership and permissions

Bind an existing role to a side, for example:

```text
/family_role family:cartel role:@Cartel
/family_roles
/leader_set member:@Player
```

Select the matching options in Discord; the displayed side labels are Russian.
Role names can be anything because bindings use role IDs. Omit `role` from
`/family_role` to remove a binding. A role can represent only one side per season,
and the everyone role cannot be used.

Players need exactly **one** configured family or police role. There is no `/join`.
Current membership is fetched through Discord REST for game actions, including
offline participants before an operation payout. A role change preserves the
personal wallet, work limits, and corruption record, but removes old leadership
and participation in unfinished operations for the previous side.

The first synchronized member becomes leader if the side has none. Organizers
can reassign leadership with `/leader_set`. Shared spending, operation creation,
raid responses, and district transfers require leadership. Discord administrator
permissions do not override this game rule. An operation supports up to **12
participants** to stay within the Worker's external-request budget.

## Player help

`/help` shows the introduction and a quick-start path. Its optional `topic`
parameter opens a detailed Markdown page:

| Topic | Contents |
| --- | --- |
| `overview` | Getting started, shared resources, rankings, and navigation |
| `money` | Wallets, work, donations, and personal offers |
| `operations` | Creating, joining, and resolving a family operation |
| `police` | Investigations, clues, raids, and family responses |
| `bribes` | Reserved payments, officer decisions, and corruption penalties |
| `districts` | Contest bids, ownership, transfers, and income |
| `admin` | Roles, leaders, rewards, news, and setup |
| `texts` | Editing, resetting, and exporting flavour text |
| `weekly` | Weekly presets, participation, publication, and scheduling |

For example: `/help topic:operations`. Pages explain **who may run each command**,
**what it costs**, **how often it is available**, and show **example responses**.
Examples are illustrative; live IDs, amounts, and customized messages may differ.
Each page fits Discord's message limit and uses headings, lists, bold text,
inline command examples, block quotes, and fenced sample output.

## Automatic weekly tasks

The bot posts one randomly selected task in the configured news channel every
**Monday at 12:00 in Europe/Minsk**. The existing ten-minute cron checks the
schedule, so delivery can be delayed by approximately one cron interval.

Eight presets are seeded by migration `004_weekly_tasks.sql`: a meme, an alibi,
an NPC dossier, city rumors, a business cover, a noir scene, a coded message, and
a newspaper story. Each is asynchronous and can be completed by one person for
their side. Police may participate too. Submissions are due at the end of Sunday
in the configured timezone.

The suggested reward is **3 influence and 20 treasury money per side**, after
organizer approval. The announcement includes a `/reward` example with a unique
weekly reference. Replace both the side and the reference suffix for each family;
the existing reward ledger prevents payment of the same reference twice. Posting
a task does not automatically award participation or completion.

Organizer-only commands, with private responses:

```text
/weekly_tasks
/weekly_tasks action:presets
/weekly_tasks action:publish
/weekly_tasks action:disable
/weekly_tasks action:enable
/weekly_tasks action:schedule day:1 hour:12 minute:0
```

Days use ISO numbering: Monday is 1, Sunday is 7. Schedule changes and re-enabling
take effect at the next scheduled occurrence; they do not publish an overdue task
immediately. Automatic posting is enabled by default after migration, but only
starts at the next scheduled occurrence and requires `/news_channel` to be set.
Manual `publish` can post the current week's task immediately, even when automatic
posting is disabled; it cannot create a second assignment for that week.

Selection and insertion into the news outbox are committed atomically. A unique
guild/season/week key prevents duplicate task creation under concurrent cron
runs or repeated manual publication. Consecutive repetition of a preset is
avoided when another active preset exists. Missed historical weeks are not
backfilled; an interruption after the scheduled time can catch up within the
current week. News transport retains the general at-least-once delivery caveat.

Presets live in the private Neon table `mafia_weekly_task_presets`. Edit `title`
or `body`, insert a new row, or set `enabled=false` using the Neon SQL Editor;
changes affect future selections without a deployment. Titles allow up to 80
characters, bodies up to 900. This bot's database shares the preset catalog across
its seasons. Already selected assignments keep their original text snapshot.
The publication template itself is editable through `/flavour_edit key:weekly_task`.

The [full command reference](docs/commands.md) is in Russian. The in-game guide
is also available as [Markdown](docs/player-guide.md), generated from the same
topic pages. Daily limits reset at **00:00 UTC**; ISO weeks begin on **Monday
at 00:00 UTC**.

Shared responses such as `/start`, `/help`, rankings, operation results, and
district contest results are public in the channel. Wallets, work, donations,
private offers, investigations, raid decisions, and administrative responses
remain ephemeral. See `src/nullreference/visibility.py` for the exact policy.

## Editing flavour text without deployment

`/flavour_edit key:work` displays the current template and an **Edit** button.
The button opens a private modal for its author, who must still have Manage Server.
Saving writes an override to Neon; subsequent messages use it immediately.

- `/flavour_reset` restores the default for a key.
- `/flavour_export` returns the current catalog as a private JSON attachment.
- Preserve the template's existing `$amount`, `$balance`, and other placeholders.
- Edits are recorded with the author and timestamp in `flavour_history`.
- Existing messages are not rewritten, and bot messages do not send mention pings.

Defaults live in `flavour.ru.json`; `scripts/build.py` generates `texts.py` for the
Worker bundle. Command descriptions, help pages, rule errors, and numeric balance
remain in Python and require a deployment to change.

## Runtime architecture and delivery guarantees

The Worker verifies the original request body's Ed25519 signature, a five-minute
timestamp window, Application ID, and allowed Guild ID. Administrative actions
require Manage Server or Administrator; game actions additionally enforce the
current side and leadership rules.

Commands receive an immediate deferred acknowledgement with the visibility
chosen before processing. `waitUntil` continues work: the request is persisted
in `interaction_jobs`, executed, and delivered by editing the original response.
Discord interaction IDs provide idempotency for economic actions. Persisted
response delivery can be retried up to three times within a fourteen-minute window.

If the Worker stops before the first successful job write, that request cannot
be recovered automatically. After a transient failure, check `/profile` or
`/status` before repeating a spending command: a new command has a new interaction ID.

Game state is a JSONB document per guild and season. Optimistic concurrency uses
an expected document version; the snapshot update, event, and news insertion
commit in one SQL statement. Competing writers reload and retry. Failed rule
checks do not persist partial spending.

A Cron Trigger runs every **ten minutes** to refund expired bribes, expire
district ownership, retry saved responses, and deliver news. Game actions also
check deadlines. Operations and district contests are still resolved explicitly
with their commands. Background expiry may lag by one cron interval.

News delivery is **at least once**: a crash after sending but before marking a row
as sent can produce a duplicate. Leases prevent ordinary simultaneous delivery.
Temporary interaction tokens and payloads exist only in the private Neon database;
they are cleared after delivery or by expiry maintenance. Treat database access
and backups as sensitive. Application code does not log tokens or raw payloads,
and observability is disabled by default.

## Migrations

`001` and `002` retain the original schema. `003_cloudflare.sql` adds state
versions, interaction jobs, and news leases. Existing game data is preserved.
`004_weekly_tasks.sql` adds the weekly schedule, preset catalog, and assignment history.
Do not run the old Gateway implementation concurrently: it does not update versions.

Deployment applies migrations, not HTTP handlers or cron. Applied versions are
stored in `schema_migrations`; add new files in order rather than editing applied
ones. Checksums detect later edits. Legacy rows without a checksum adopt the
current file checksum the first time the new migration runner handles them.

## Local development

Install Node.js 22+ and Python 3.12+, then run:

```text
npm ci
npm run build
```

Copy `.dev.vars.example` to `.dev.vars` and fill it in locally. Never commit it.

```text
npm run dev
```

To run migrations or register commands using local settings:

```text
python -m uv run --env-file .dev.vars python scripts/migrate.py
python -m uv run --env-file .dev.vars python scripts/register_commands.py
```

`npm run deploy` reads the real process environment. For a manual deployment using
the local file:

```text
python -m uv run --env-file .dev.vars python scripts/deploy.py
```

## Verification

```text
npm run check
npm test
python -m uv run python scripts/prepare_worker.py --check-bundle
```

The bundle check compares actual SDK files in `dist/worker/python_modules` with
the build manifest. Having the SDK only in the development environment is not
sufficient. Missing or modified files stop deployment before publication.

Integration tests require `TEST_DATABASE_URL` pointing to a **disposable** PostgreSQL
database; otherwise they are skipped. GitHub CI starts PostgreSQL 17 without
production secrets and checks migrations, idempotency, concurrent spending, failed
actions, live settings, response retries, and token cleanup.

`scripts/smoke_worker.py` exercises local workerd using public RFC 8032 test
credentials: health, signed PING, invalid signatures, expired timestamps,
Application ID validation, and administrative checks. Use it only with the
matching local test settings, never with production credentials.

## Free-plan limits

This setup uses Workers Free and Neon without Containers, paid Queues, R2, or VMs.
Workers request/CPU limits and Neon compute/storage allowances apply separately.
A successful build does not prove every production workload fits those limits;
check actual command performance after connecting the real services. The
ten-minute cron reduces database wakeups compared with a continuously running bot.
Do not enable a paid plan automatically as part of deployment.

## Adding another season

Shared HTTP adapters, configuration, signatures, and storage live in `core/` and
`security.py`. Mafia rules, command definitions, text defaults, and player help
live in `themes/mafia/`. Add another theme, select it in `Application`, and change
`SEASON_ID`; previous seasons remain in the database.

See [Python Workers](https://developers.cloudflare.com/workers/languages/python/),
[Discord interactions](https://docs.discord.com/developers/interactions/receiving-and-responding),
and [Neon serverless](https://neon.com/docs/serverless/serverless-driver) for platform documentation.

## Casino

Use `/casino_channel` (Manage Server) to select the casino text channel. `/slots amount:5` accepts 5–20 personal funds; `/blackjack amount:10` accepts 10 up to the personal balance (Discord integer ceiling: 2^53−1). Both share five game starts per player per UTC day, resetting daily at 00:00 UTC. Family funds are never used.

Slots draw three independent uniform symbols from four symbols. Any triple returns 3x the stake; exactly two cherries returns 2x; other outcomes return zero. Payout probability is 13/64 (20.3125%), expected return is 46.875%; multipliers include the stake.

Blackjack uses independent uniform 52-card draws with replacement, so counting seen cards provides no information. Dealer stands on soft 17. Natural blackjack pays 3:2 profit rounded down; ordinary wins return 2x; ties return the stake. No split, double or insurance. One active hand per player, public owner-only Hit/Stand buttons, `/blackjack_table` recovery. After 24 hours, abandoned hands stand automatically during the next action or scheduled maintenance. Stale button revisions do not draw or pay twice. State changes, stake deductions, quotas and payouts share the existing atomic optimistic transaction and interaction replay protection. Casino configuration is stored in `guild_settings.casino_channel_id` by migration 005; no server-specific IDs are committed.
