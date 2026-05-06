# Backend Quick Start

## 1. Install dependencies

```bash
pip install -r requirements.txt
```

## 2. Configure env

Copy `.env.example` to `.env`, then update `DATABASE_URL` and `JWT_SECRET_KEY`.

## 3. Run migrations

```bash
alembic upgrade head
```

## 4. Start API server

```bash
uvicorn backend.main:app --reload
```

Open docs: `http://127.0.0.1:8000/docs`
