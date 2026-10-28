---
title: Quickstart Guide
badge: Setup
---

# Quickstart Guide

Get Kwuo running locally inside **WSL** using `ruv` (the Python UV environment manager).

---

## 1. Prerequisites

Ensure you have the following installed in your environment:
* **WSL** (Windows Subsystem for Linux)
* **Python 3.12+**
* **ruv** (UV wrapper for WSL virtual environment isolation)
* **PostgreSQL** and **Redis**

---

## 2. Environment Configuration

Copy the example environment template into `.env`:

```bash
cp .env.example .env
```

Ensure your PostgreSQL and Redis connection strings in `.env` are configured:

```ini
SECRET_KEY=your-secure-32-byte-secret-key-here-replace-for-security
DATABASE_URL=postgresql+asyncpg://<username>:<password>@localhost:5432/ps_tab
REDIS_URL=redis://localhost:6379/0
```

> [!TIP]
> Ensure local PostgreSQL is running in WSL before starting the server:
> `sudo service postgresql start`

---

## 3. Running Development Tasks

Kwuo uses `taskipy` managed via `ruv`:

### Start the FastAPI Dev Server
```bash
ruv run task dev
```
The server will boot with hot-reloading enabled at `http://localhost:8000`.

### Start the ARQ Background Worker
```bash
ruv run task worker
```

### Run the Automated Test Suite
```bash
ruv run task test
```
