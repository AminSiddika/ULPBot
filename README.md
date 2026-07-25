# ULP Bot v2

Professional Telegram bot for searching, extracting, and generating combos from ULP (URL:Login:Password) databases. Built with aiogram, MongoDB, Redis, FastAPI, and full production infrastructure.

## Features

- **ULP Search** — Fast keyword search across large databases via ripgrep
- **Redis Caching** — Search results cached for 5 minutes, drastically reducing response time
- **Combo Extraction** — Extract mail:pass, user:pass, number:pass formats
- **Combo Generation** — Generate and download combo files in any format
- **Admin Panel** — Upload databases, browse files, manage downloads
- **Usage Stats** — Track queries, users, and command popularity (MongoDB)
- **Background Scheduler** — Auto-clean downloads, daily stats aggregation, cache flush
- **Rate Limiting** — Redis-backed per-user rate limiting (configurable per command)
- **Webhook Mode** — Production deployment via webhook with FastAPI health endpoint
- **Sentry** — Error tracking with Sentry (optional, set `SENTRY_DSN`)
- **Async** — Fully asynchronous for high throughput

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Bot Framework | aiogram 3.x |
| Database | MongoDB 7 + motor (async) |
| Cache | Redis 7 |
| Search Engine | ripgrep |
| Health/Webhook | FastAPI + uvicorn |
| Scheduler | APScheduler |
| Error Tracking | Sentry |
| Logging | loguru |
| Linting | ruff |
| Type Check | mypy |
| Testing | pytest + mongomock |
| Containerization | Docker (multi-stage) + docker-compose |
| CI/CD | GitHub Actions |

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.12+ (for local dev)
- Telegram Bot Token from [@BotFather](https://t.me/BotFather)

### Production (Docker)

```bash
cp .env.example .env
# Edit .env with your bot token, owner ID, and optionally SENTRY_DSN
make build
make up
```

### Webhook Mode (Production)

Set these in `.env`:

```env
WEBHOOK_HOST=https://your-domain.com
WEBHOOK_PATH=/webhook
WEBHOOK_PORT=8080
```

Put nginx/Caddy in front forwarding `https://your-domain.com/webhook` to `http://bot:8080/webhook`.

### Local Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# Edit .env — set MONGO_URI=mongodb://localhost:27017

# Start MongoDB and Redis
docker compose up -d mongo redis

# Run bot
python -m src.main
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BOT_TOKEN` | Yes | — | Telegram bot token |
| `OWNER_ID` | Yes | — | Owner Telegram user ID |
| `ADMIN_IDS` | No | — | Comma-separated admin IDs |
| `MONGO_URI` | No | `mongodb://mongo:27017` | MongoDB connection URI |
| `MONGO_DB` | No | `ulpbot` | MongoDB database name |
| `REDIS_URL` | No | `redis://redis:6379/0` | Redis connection URL |
| `WEBHOOK_HOST` | No | — | Webhook host URL (enables webhook mode) |
| `WEBHOOK_PATH` | No | `/webhook` | Webhook endpoint path |
| `WEBHOOK_PORT` | No | `8080` | Webhook server port |
| `SENTRY_DSN` | No | — | Sentry DSN for error tracking |
| `DATA_DIR` | No | `./data` | ULP database files directory |
| `LOG_LEVEL` | No | `INFO` | Logging level |

## Commands

### Public

| Command | Description |
|---------|------------|
| `/start` | Welcome message |
| `/help` | Help and command list |
| `/cmds` | List all commands |
| `/ulp <keyword>` | Search ULP database |
| `/extract <format> <keyword>` | Extract specific format |
| `/cmb <keyword>` | Generate combo file |

### Admin

| Command | Description |
|---------|------------|
| `/add` | Upload .txt database (reply to file) |
| `/files` | Browse all database files |
| `/clean` | DB stats and cleanup tools |
| `/stats` | Usage statistics |

### Formats

- `mail:pass` — Email:Password
- `user:pass` — Username:Password
- `number:pass` — Phone:Password
- `raw` — Full URL:Login:Password

## Rate Limits

| Command | Limit | Window |
|---------|-------|--------|
| `/ulp` | 15 req | 60s |
| `/extract` | 15 req | 60s |
| `/cmb` | 10 req | 5 min |

## Database Setup

Place `.txt` ULP database files in the `data/` directory:

```
ulp-bot/
├── data/
│   ├── combo1.txt
│   ├── combo2.txt
│   └── ...
```

Each file: one record per line in `url:login:password` format.

## Project Structure

```
ulp-bot/
├── src/
│   ├── main.py              # Entry point (polling or webhook)
│   ├── config.py            # pydantic-settings configuration
│   ├── webhook.py           # FastAPI webhook + health endpoint
│   ├── bot/
│   │   ├── dispatcher.py    # Router + middleware setup
│   │   ├── middlewares/     # Auth, throttling
│   │   └── handlers/        # Command handlers
│   ├── database/
│   │   ├── engine.py        # Motor async MongoDB client
│   │   └── repos/           # User & log repositories
│   ├── services/
│   │   ├── search.py        # ripgrep search + combo generation
│   │   ├── cache.py         # Redis caching + rate limiting
│   │   └── scheduler.py     # APScheduler background jobs
│   └── utils/
│       └── logger.py        # loguru configuration
├── tests/                   # pytest with mongomock
├── data/                    # ULP database files
├── downloads/               # Temporary combo output
├── Dockerfile               # Multi-stage build
├── docker-compose.yml       # bot + mongo + redis
├── Makefile
├── pyproject.toml
└── .github/workflows/ci.yml
```

## License

MIT
