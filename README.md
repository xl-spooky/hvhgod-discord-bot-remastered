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

2) Start the database **and Redis** services:

```
docker compose up -d db redis
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
docker compose logs -f redis # follow redis logs
docker compose down          # stop services
```

### Run locally (Poetry)

```
# Optional: run Redis locally (or start the docker service: `docker compose up -d redis`)
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
2. Start the stack: `docker compose up -d db redis`.
3. Apply migrations inside the helper container: `docker compose run --rm migrate upgrade head`.
4. Launch the bot: `docker compose up --build bot`.

### 2. Dockerised bot → local / remote Postgres

1. Install or reference your own PostgreSQL outside Docker (for example the host `psql` package).
2. Provide Redis credentials the bot can reach (e.g. run `docker compose up -d redis` or point to a managed instance with `REDIS_URL`).
3. Update `.env` with the host connection info, e.g. `DB_HOST=host.docker.internal` (macOS/Windows) or the machine IP / `172.17.0.1` (Linux). Adjust `DB_PORT`, `DB_USER`, `DB_PASS`, `DB_NAME`, or supply a full `DATABASE_URL`. Override `REDIS_HOST` / `REDIS_PORT` (or `REDIS_URL`) if Redis is not containerised.
4. Run migrations from Docker using those credentials: `docker compose run --rm migrate upgrade head`.
5. Start the bot container: `docker compose up --build bot`.

### 3. Local bot → Docker Postgres

1. Bring up the backing services: `docker compose up -d db redis` (or install both locally).
2. Point the bot to those services by setting `DB_HOST=localhost` and `REDIS_HOST=localhost` (plus any custom credentials) in `.env`.
3. Apply migrations locally: `./scripts/migrate.sh upgrade head` (or `poetry run alembic upgrade head`).
4. Start the bot with Poetry: `poetry run python -m spooky.bot`.

### 4. Bot and Postgres outside Docker (same machine or separate hosts)

1. Ensure PostgreSQL and Redis are reachable from the bot host.
2. Provide connection strings through `DATABASE_URL` / `REDIS_URL` (e.g. `postgresql+asyncpg://...` / `rediss://user:pass@cache.example.com:6380/0`) or fill out the granular `DB_*` and `REDIS_*` values.
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

## Redis Configuration & Connection Modes

Redis backs the project's TTL caches so multiple bot instances stay in sync. The compose stack ships with a `redis` service, and `.env.example` points to it by default (`REDIS_HOST=redis`, `REDIS_PORT=6379`, `REDIS_DB=0`).

### Dockerised Redis (default)

- Start it alongside Postgres: `docker compose up -d db redis`.
- Leave the defaults in `.env` untouched.

### Local or managed Redis

- Install Redis on your host (e.g. `brew install redis`, `choco install redis`, package manager) **or** provision a managed instance (Upstash, Elasticache, etc.).
- Update `.env` with either a full `REDIS_URL` (`redis://user:pass@hostname:6379/0`, `rediss://` for TLS) or granular overrides (`REDIS_HOST=localhost`, `REDIS_PORT=6379`, optional `REDIS_USER`, `REDIS_PASS`, `REDIS_DB`).
- Set `REDIS_SSL=1` when you need TLS but are not using a `rediss://` URL.

### Mixed deployments

It is common to run the bot locally while pointing to Redis in Docker (or vice-versa). Adjust the `REDIS_*` values so the bot can reach the cache host (e.g. `REDIS_HOST=host.docker.internal` from inside containers, or the container's mapped port when running locally).

Redis environment variables:

| Variable | Purpose |
| --- | --- |
| `REDIS_URL` | Connection URL (`redis://...`, `rediss://...`). Overrides other Redis vars. |
| `REDIS_HOST` / `REDIS_PORT` | Host/port when composing the URL manually (defaults: `redis`, `6379`). |
| `REDIS_DB` | Logical database index (defaults to `0`). |
| `REDIS_USER` / `REDIS_PASS` | Optional auth credentials when not embedding them in `REDIS_URL`. |
| `REDIS_SSL` | Set to `1` to force TLS when using granular values. |

The entrypoint initialises the Redis client at startup and shuts it down on exit. If Redis is unreachable, the bot falls back to in-process TTLs but you lose cross-instance cache invalidation.


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
