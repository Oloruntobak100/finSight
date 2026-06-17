# FinSight AI

**Chat with your finances.** AI-powered financial intelligence platform.

Connect bank accounts (Plaid, Mono) and accounting software (QuickBooks, Xero), then ask questions about your money in plain English.

## Monorepo Structure

```
finsight-ai/
├── frontend/          # Next.js 15 (Vercel)
├── backend/           # FastAPI (Railway)
├── shared/types/      # Shared TypeScript types
├── docker-compose.yml
└── .env.example
```

> Note: The legacy Vite ERP UI in `app/` is unrelated to FinSight AI and can be removed.

## Quick Start

### 1. Supabase

1. Create a project at [supabase.com](https://supabase.com)
2. Run `backend/supabase/migrations/001_initial.sql` in the SQL editor
3. Copy URL, anon key, service role key, and JWT secret

### 2. Environment

```bash
cp .env.example .env
# Fill in all values
```

Generate encryption key:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 3. Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 4. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

### 5. Docker (optional)

```bash
docker-compose up
```

## API Endpoints

| Area | Endpoints |
|------|-----------|
| Banking | `POST /banking/plaid/link-token`, `/plaid/exchange`, `/sync` |
| OAuth | `GET /oauth/quickbooks/authorize`, `/xero/authorize` |
| Transactions | `GET /transactions`, `PATCH /transactions/{id}/category` |
| Analytics | `GET /analytics/metrics`, `/forecast`, `/subscriptions` |
| Chat | `POST /chat/sessions`, `POST /chat/sessions/{id}/messages` (streaming) |

## Tech Stack

- **Frontend:** Next.js 15, TypeScript, Tailwind, Shadcn-style UI, Recharts
- **Backend:** Python FastAPI, APScheduler
- **Database:** Supabase (PostgreSQL + Auth)
- **AI:** Anthropic Claude API
- **Banking:** Plaid (global), Mono (Africa)
- **Accounting:** QuickBooks Online, Xero (OAuth 2.0)

## Deployment

- Frontend → Vercel (`frontend/`)
- Backend → Railway (`backend/`)
- Database → Supabase (managed)
