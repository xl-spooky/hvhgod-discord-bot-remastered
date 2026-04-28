<p align="center">
  <img src="assets/README_images/top_banner.png" alt="Spooky Bot Banner" width="100%" />
</p>

<h1 align="center">Spooky Bot v2</h1>
<p align="center">
  <b>The playful ghost with serious security.</b><br/>
  A modern multipurpose Discord bot built on Python 3.11, Disnake, and PostgreSQL.
</p>

---

## Features

* Advanced security features to keep your server safe
* Powerful moderation tools to manage communities
* Economy system with coins and rewards
* Fun commands and entertainment features (games, memes, etc.)
* Configuration options with flexible settings
* Reposter / social media integration (TikTok, etc.)
* Information commands for quick server insights

---

## Quick Start

Clone the repository:

```
git clone https://github.com/spooky-bot/spooky-bot-v2
cd spooky-bot-v2
```

### Run with Docker (recommended)

1) Copy env and set your bot token:

```
# Windows PowerShell
Copy-Item .env.example .env

# macOS/Linux
cp .env.example .env
```

Edit `.env` and set `SPOOKY_BOT__TOKEN` (required).

2) Start the database service:

```
docker compose up -d db
```

3) Apply migrations (first run only):

```
docker compose run --rm migrate upgrade head
```

4) Start the bot:

```
# foreground logs
docker compose up --build bot

# or background
docker compose up -d --build bot
```

Useful:

```
docker compose logs -f bot   # follow bot logs
docker compose down          # stop services
```

### Run locally (Poetry)

```
poetry install
# Install the project in editable mode so tools like Pyright resolve third-party imports
poetry run pip install -e .
Copy-Item .env.example .env   # or: cp .env.example .env
# set SPOOKY_BOT__TOKEN in .env

# First time DB init
poetry run alembic upgrade head

# Start bot
poetry run python -m spooky.bot
```

After changing models:

```
# generate + tweak revision
./scripts/migrate.sh revision "describe change"
# apply it
./scripts/migrate.sh upgrade head
```

---

## Database Configuration & Connection Modes

Spooky's SQLAlchemy setup is entirely environment-driven, so the bot and PostgreSQL can live wherever you need. Copy `.env.example` to `.env` and adjust the variables that match your deployment.

### 1. Bot **and** Postgres in Docker

1. Keep the defaults in `.env` (`DB_HOST=db`, `DB_USER=spooky`, etc.).
2. Start the stack: `docker compose up -d db`.
3. Apply migrations inside the helper container: `docker compose run --rm migrate upgrade head`.
4. Launch the bot: `docker compose up --build bot`.

### 2. Dockerised bot → local / remote Postgres

1. Install or reference your own PostgreSQL outside Docker (for example the host `psql` package).
2. Update `.env` with the host connection info, e.g. `DB_HOST=host.docker.internal` (macOS/Windows) or the machine IP / `172.17.0.1` (Linux). Adjust `DB_PORT`, `DB_USER`, `DB_PASS`, `DB_NAME`, or supply a full `DATABASE_URL`.
3. Run migrations from Docker using those credentials: `docker compose run --rm migrate upgrade head`.
4. Start the bot container: `docker compose up --build bot`.

### 3. Local bot → Docker Postgres

1. Bring up the backing service: `docker compose up -d db` (or install Postgres locally).
2. Point the bot to that service by setting `DB_HOST=localhost` (plus any custom credentials) in `.env`.
3. Apply migrations locally: `./scripts/migrate.sh upgrade head` (or `poetry run alembic upgrade head`).
4. Start the bot with Poetry: `poetry run python -m spooky.bot`.

### 4. Bot and Postgres outside Docker (same machine or separate hosts)

1. Ensure PostgreSQL is reachable from the bot host.
2. Provide the database connection string through `DATABASE_URL` (e.g. `postgresql+asyncpg://...`) or fill out the granular `DB_*` values.
3. Run migrations with `./scripts/migrate.sh upgrade head`.
4. Launch the bot using Poetry or your preferred process manager (systemd, PM2, etc.).

The migration helper works everywhere:

```
./scripts/migrate.sh upgrade head
./scripts/migrate.sh downgrade base
./scripts/migrate.sh revision "describe change"
```

Docker users can run the same commands through the migrate service: `docker compose run --rm migrate <alembic args>`.

Environment variables (optional; defaults live in `.env.example`):

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Full SQLAlchemy URL (`postgresql+asyncpg://user:pass@host:port/db`). Overrides everything else. |
| `DB_DRIVER` | Override driver scheme (defaults to `postgresql+asyncpg`). |
| `DB_HOST` / `DB_PORT` | Host/port when assembling the URL manually. |
| `DB_USER` / `DB_PASS` / `DB_NAME` | Credentials when not using `DATABASE_URL`. |
| `DB_ECHO` | Set to `1` to echo SQL statements for debugging. |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, `DB_POOL_RECYCLE` | Optional async engine tuning knobs. |


---

## Tech Stack

* Language: Python 3.11+
* Discord API: Disnake
* Database: PostgreSQL 13+
* ORM: SQLAlchemy 2.0 (asyncpg)
* Config: Dynaconf
* Logging: Loguru
* Formatting & Linting: Ruff + Pre-commit
* CI/CD: GitHub Actions
* Migrations: Alembic

---

## Project Layout

```
spooky/
 +- bot/          # Core bot code (entry point, extensions)
 +- models/       # SQLAlchemy models and typing helpers
 +- core/         # Settings, logging, environment utilities
 +- db/           # Async engine + session lifecycle helpers
 +- ext/          # Shared components, utilities, helpers
 +- migrations/   # Alembic configuration and revision scripts
```

---

## License

AGPL v3 (see `pyproject.toml`)

---

## Acknowledgements

Thanks to: Disnake · SQLAlchemy · Alembic · Loguru · Dynaconf · Ruff · The wider OSS community
