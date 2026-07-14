# Job Agent — Configuration Guide

Everything here is **free**. Times are one-time setup. After this, the agent runs itself.

---

## 1. What you MUST set (or the agent degrades)

| Key | Why | Get it (free) |
|-----|-----|---------------|
| `GROQ_API_KEY` | Primary LLM for resume tailoring + emails (fast, reliable). Without it, falls back to Gemini → HuggingFace. | https://console.groq.com/keys |
| `API_KEY` | Protects the sending endpoints. **Also add as a GitHub repo secret** (see §4) or the scheduler will 401. | `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `GITHUB_TOKEN` | Raises GitHub contact-lookup 60 → 5000 req/hr (finds real dev emails). No scopes needed. | https://github.com/settings/tokens |

## 2. Strongly recommended (free)

| Key | Why | Get it |
|-----|-----|--------|
| `GEMINI_API_KEY` | LLM fallback when Groq is rate-limited. | https://aistudio.google.com/apikey |
| `GOOGLE_CREDENTIALS_JSON` + Gmail/Sheets OAuth (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`) | Sending email + Google-Sheet tracking (which is now also the **dedup memory** that survives Render restarts). | https://console.cloud.google.com/apis/credentials |
| `TRACKING_SHEET_ID` | The Sheet used for persistent per-job dedup + your application tracker. | From the sheet URL: `.../spreadsheets/d/THIS_ID/edit` |

## 3. Optional (free)

| Key | Why |
|-----|-----|
| `HUNTER_API_KEY` | ~25 verified email lookups/month. Best-quality contacts for a few priority companies. https://hunter.io/api_keys |
| `GOOGLE_SEARCH_API_KEY` + `GOOGLE_CSE_ID` | 100 free/day — LinkedIn contact + careers-page discovery. |
| `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` | Extra India + salary-annotated jobs. Skipped silently if unset. https://developer.adzuna.com/ |
| `OPENROUTER_API_KEY` | Extra LLM fallback. https://openrouter.ai/keys |

---

## 4. Where to set them

### Local (`backend/.env`)
Copy `backend/.env.example` → `backend/.env` and fill in the keys above.

### Render (production)
Render → your service → **Environment** → add each key. All the new ones (`GROQ_API_KEY`, `GEMINI_API_KEY`, `GITHUB_TOKEN`, `ADZUNA_*`) are already declared in `render.yaml` as `sync: false`, so Render will prompt for them.

### GitHub Actions (the scheduler) — ⚠️ REQUIRED
The cron now authenticates. Add **two** repo secrets under
`GitHub repo → Settings → Secrets and variables → Actions`:
- `RENDER_URL` — your Render service URL (already used)
- `API_KEY` — **the same value** as your Render `API_KEY`

Without the `API_KEY` secret, `/daily-sweep`, `/sync-sheets`, and `/check-emails` return 401 and no jobs are processed.

---

## 5. Which endpoints need the key

| Public (no key) | Protected (need `x-api-key` header) |
|-----------------|-------------------------------------|
| `/health`, `/discover-jobs`, `/tailor-resume`, `/generate-email` | `/daily-sweep`, `/sync-sheets`, `/check-emails`, `/track/*`, `/dashboard`, `/download-pdf` |

Call protected endpoints with: `curl -H "x-api-key: YOUR_KEY" ...`

---

## 6. Verify it works

```bash
cd backend && source venv/bin/activate

# 1) LLM chain is configured
python -c "from tailor.llm import get_llm; print(get_llm().name)"
#   → fallback[groq,gemini,...]   (or the single provider you configured)

# 2) Discovery returns real jobs (public endpoint)
python main.py &   # starts on :8000
curl -s -X POST "http://localhost:8000/discover-jobs?sources=github,greenhouse,himalayas&max_age_days=14" | python -m json.tool | head

# 3) Full pipeline (needs API_KEY set). generate_emails=false = safe dry run (no emails sent)
curl -s -X POST "http://localhost:8000/daily-sweep?max_jobs=3&generate_emails=false" \
  -H "x-api-key: $API_KEY" | python -m json.tool
```

`pytest tests/ -q` should show all tests passing.

---

## 7. How the safety guarantees work (what you asked for)

- **Resume curated per job:** the tailor prompt first extracts the JD's top requirements, then selects/reorders only the most relevant projects and rewrites bullets in the JD's own terms. A fail-closed fact-check (`verify_fidelity`) blocks any resume that adds anything not in your base resume — that job is logged `needs_review` instead of emailed.
- **Never email the same job twice:** dedup is per-job (normalized URL + company|role), checked against both local SQLite and the Google Sheet, so it holds even after Render wipes local disk on restart. A *different* role at the same company is still allowed.
- **Emails only go to real, deliverable contacts:** guessed `{company}.com` domains and guessed personal addresses are never auto-emailed; verified (GitHub/Hunter) contacts rank first, then deliverable role addresses (`careers@`/`hiring@`) on a real domain, and every recipient passes an MX check before sending.
- **All beneficial free sources on:** YC, Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee, Teamtailor, The Muse, Himalayas, RemoteOK, Remotive, WeWorkRemotely, HackerNews, GitHub (SimplifyJobs 30k+ listings), and India boards Cutshort/Hirist/foundit. Adzuna turns on when you add its keys.
