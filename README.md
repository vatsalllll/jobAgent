# 🎯 Job Agent — AI-Powered Job Application Automation

An autonomous agent that discovers fresh job listings, tailors your resume using Claude, generates personalized outreach emails, and tracks everything — all orchestrated by n8n.

## How It Works

```
Every 12 hours:
  ┌─────────────────┐
  │  n8n Scheduler  │
  └────────┬────────┘
           ▼
  ┌─────────────────────────────┐
  │  1. DISCOVER JOBS           │
  │  YC Work at a Startup       │
  │  Greenhouse (60+ companies) │
  │  Filters: ≤4 days old,      │
  │  India/Remote, ≥₹50K/mo     │
  └────────┬────────────────────┘
           ▼
  ┌─────────────────────────────┐
  │  2. TAILOR RESUME           │
  │  Claude 3.5 Sonnet          │
  │  6-slot prompt + ATS match  │
  │  Fact-checking verification │
  │  Playwright → PDF export    │
  └────────┬────────────────────┘
           ▼
  ┌─────────────────────────────┐
  │  3. GENERATE OUTREACH       │
  │  Personalized email         │
  │  References company + role  │
  │  Highlights relevant exp    │
  └────────┬────────────────────┘
           ▼
  ┌─────────────────────────────┐
  │  4. LOG TO GOOGLE SHEETS    │
  │  Company, Role, Score,      │
  │  Status, Resume PDF link    │
  └─────────────────────────────┘
```

## Project Structure

```
job-agent/
├── backend/
│   ├── main.py              # FastAPI app (all endpoints)
│   ├── config.py            # Settings from .env
│   ├── requirements.txt
│   ├── .env.example         # Copy to .env and fill in
│   ├── venv/                # Python virtual environment
│   ├── data/
│   │   └── base_resume.py   # Your resume in JSON Resume format
│   ├── discover/
│   │   ├── yc_scraper.py    # YC Work at a Startup (Playwright)
│   │   ├── greenhouse.py    # Greenhouse Job Board API
│   │   └── models.py        # JobListing, etc.
│   ├── tailor/
│   │   ├── prompts.py       # Claude prompt templates
│   │   ├── claude_tailor.py # Resume tailoring + scoring
│   │   └── pdf_render.py    # HTML → PDF via Playwright
│   ├── outreach/
│   │   └── email_gen.py     # Personalized email generator
│   └── templates/outputs/   # Generated PDFs
├── n8n/
│   ├── docker-compose.yml   # n8n self-hosted
│   └── daily-sweep-workflow.json  # Import into n8n
├── docker-compose.yml
├── start.sh
└── README.md
```

## Quick Start

### Prerequisites
- Python 3.10+
- Docker Desktop (for n8n)
- Anthropic API key (Claude)
- Playwright browsers (`python -m playwright install chromium`)

### Step 1: Clone & Setup

```bash
cd ~/job-agent/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

### Step 2: Configure API Keys

```bash
cp .env.example .env
# Edit .env and add your:
#   ANTHROPIC_API_KEY=sk-ant-...      (REQUIRED)
#   HUNTER_API_KEY=                    (optional)
#   GOOGLE_CREDENTIALS_JSON=           (optional, for Sheets)
#   TRACKING_SHEET_ID=                 (optional)
```

Get your Anthropic API key at: https://console.anthropic.com/

### Step 3: Start the Backend

```bash
cd ~/job-agent/backend
source venv/bin/activate
python main.py
```

FastAPI runs at http://localhost:8000 — docs at http://localhost:8000/docs

### Step 4: Start n8n (in another terminal)

```bash
# Make sure Docker Desktop is running first
cd ~/job-agent/n8n
docker compose up -d
```

n8n runs at http://localhost:5678

### Step 5: Import n8n Workflow

1. Open http://localhost:5678
2. Create account (first-time setup)
3. Click "Import from File"
4. Select `n8n/daily-sweep-workflow.json`
5. The workflow is ready to activate

### Alternative: One-Command Start

```bash
./start.sh
```

## API Endpoints

### `POST /discover-jobs`
Find fresh job listings.
```bash
curl -X POST "http://localhost:8000/discover-jobs?sources=yc&max_age_days=4"
```

### `POST /tailor-resume`
Tailor resume for a specific job.
```bash
curl -X POST http://localhost:8000/tailor-resume \
  -H "Content-Type: application/json" \
  -d '{
    "job_id": "test-1",
    "job_title": "Software Engineer Intern",
    "company": "TestCo",
    "job_description": "Looking for a Python/TypeScript engineer..."
  }'
```

### `POST /generate-email`
Generate outreach email.
```bash
curl -X POST http://localhost:8000/generate-email \
  -H "Content-Type: application/json" \
  -d '{
    "job_title": "Software Engineer Intern",
    "company": "TestCo",
    "job_description": "...",
    "tailored_resume": {...}
  }'
```

### `POST /daily-sweep`
Full pipeline: discover → tailor → email.
```bash
curl -X POST "http://localhost:8000/daily-sweep?max_jobs=5&tailor=true&generate_emails=true"
```

### `GET /health`
Health check.

### `GET /dashboard`
View all generated resumes.

## Configuration

All settings in `backend/.env`:

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ | Claude API key |
| `CLAUDE_MODEL` | No | Default: claude-sonnet-4-5-20250514 |
| `MIN_SALARY_INR` | No | Min monthly salary (default: 50000) |
| `MAX_LISTING_AGE_DAYS` | No | Max listing age (default: 4) |
| `SENDER_EMAIL` | No | Your Gmail address |
| `HUNTER_API_KEY` | No | For contact finding |
| `GOOGLE_CREDENTIALS_JSON` | No | For Google Sheets tracking |
| `TRACKING_SHEET_ID` | No | Google Sheets spreadsheet ID |

## Job Sources

| Source | Method | Status |
|---|---|---|
| **YC Work at a Startup** | Playwright (headless) | ✅ Working |
| **Greenhouse** | Public REST API | ✅ Working |
| **Lever** | Public Postings API | 🔜 Planned |
| **LinkedIn** | Via JSearch ($25/mo) | 🔜 Planned |
| **Wellfound** | Apify actor ($5/mo) | 🔜 Planned |

## n8n Workflow (what it does)

1. **Schedule Trigger** — runs every 12 hours (or on demand)
2. **HTTP Request** → `POST /discover-jobs` — finds fresh listings
3. **Code Node** — splits jobs into individual items
4. **HTTP Request** → `POST /tailor-resume` — Claude tailors each resume
5. **Filter** — only keep jobs with match score ≥ 60
6. **HTTP Request** → `POST /generate-email` — creates outreach email
7. **Google Sheets** — logs application to tracking sheet
8. **Notification** — builds summary

## Cost Estimate

| Item | Monthly Cost |
|---|---|
| Anthropic API (Claude) | ~$20-50 |
| n8n self-hosted | Free |
| Playwright | Free |
| YC scraping | Free |
| Greenhouse API | Free |
| **Total** | **~$20-50/mo** |

(Add $25/mo for JSearch if you want LinkedIn/Indeed coverage)

## Resume Safety

The agent NEVER fabricates information:
- All claims are verified against your base resume
- Education always shows only BITS Pilani
- Numbers and metrics are preserved exactly
- A `verify_fidelity` step cross-checks every tailored resume

## Troubleshooting

**YC scraper returns 0 jobs**: Check your internet connection. The site may have changed its HTML structure — inspect the DOM and update `yc_scraper.py`.

**Claude API errors**: Verify your `ANTHROPIC_API_KEY` in `.env`.

**n8n can't reach FastAPI**: The n8n workflow uses `host.docker.internal:8000`. Make sure FastAPI is running on port 8000.

**Docker not running**: Start Docker Desktop first, then `docker compose up -d` from the `n8n/` directory.
