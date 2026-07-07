# Job Agent — Comprehensive Audit & Improvement Plan

> **Agent:** AI-Powered Job Application Automation  
> **Location:** `/Users/vatsal/job-agent`  
> **Stack:** Python (FastAPI), n8n, GitHub Actions, Render, Gmail API, Google Sheets  
> **Status:** Active — deployed on Render, scheduled via GitHub Actions  
> **Audit Date:** 2026-06-23

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Component Breakdown](#2-component-breakdown)
3. [Critical Bugs](#3-critical-bugs)
4. [Security Vulnerabilities](#4-security-vulnerabilities)
5. [What's Missing](#5-whats-missing)
6. [Complete Improvement Plan](#6-complete-improvement-plan)
7. [Roadmap: Best Job Application Agent](#7-roadmap-best-job-application-agent)

---

## 1. Architecture Overview

```
GitHub Actions (Scheduler)
        │
        │ POST /daily-sweep
        ▼
┌─────────────────────────────────────────────┐
│               FastAPI Backend                │
│              (Render / Local)                │
│                                              │
│  ┌──────────┐  ┌─────────┐  ┌────────────┐  │
│  │ Discover  │→ │  Tailor │→ │  Outreach   │  │
│  │  (jobs)   │  │ (resume)│  │  (email)    │  │
│  └──────────┘  └─────────┘  └────────────┘  │
│        │            │              │         │
│        ▼            ▼              ▼         │
│  ┌────────────────────────────┐              │
│  │      LLM Layer             │              │
│  │  (Anthropic / HF / OpenAI) │              │
│  └────────────────────────────┘              │
│        │                                     │
│        ▼                                     │
│  ┌────────────────────────────┐              │
│  │      Gmail API Layer       │              │
│  └────────────────────────────┘              │
└─────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────┐
│           Google Sheets (Tracking)           │
└─────────────────────────────────────────────┘
```

### Data Flow

1. **Scheduler** (GitHub Actions cron) → `POST /daily-sweep`
2. **Discover** → Scrapes 10+ job sources (YC, Greenhouse, Lever, Ashby, RemoteOK, etc.)
3. **Tailor** → LLM rewrites resume for each job, scores match, verifies fidelity
4. **Contact Finder** → Finds company domain → discovers contacts (Hunter.io / patterns / YC API)
5. **Best Contact** → Scores & picks the best contact, filters ATS domains
6. **Email Gen** → LLM writes personalized outreach email
7. **Send** → Gmail API sends with tailored PDF attachment
8. **Track** → Logs to SQLite + Google Sheets

---

## 2. Component Breakdown

### 2.1 Discover Module (`backend/discover/`)

| Source | Method | Works? | Notes |
|--------|--------|--------|-------|
| YC Work at a Startup | Playwright | ✅ | Falls back to YC API if Playwright disabled |
| Greenhouse | REST API | ✅ | 35+ company boards (OpenAI, Stripe, Vercel, etc.) |
| Lever | REST API | ✅ | 15 boards (Spotify, Canva, Plaid, etc.) |
| Ashby | REST API | ✅ | 8 boards (Linear, Ramp, Mercury, Cursor) |
| RemoteOK | Web scrape | ✅ | |
| WeWorkRemotely | Web scrape | ✅ | |
| Remotive | RSS feed | ✅ | |
| GitHub Jobs | Web scrape | ✅ | |
| Upwork | RSS feed | ✅ | |
| Turing | Web scrape | ✅ | |
| Toptal | Web scrape | ✅ | |

### 2.2 Tailor Module (`backend/tailor/`)

- **LLM Abstraction** → Supports Anthropic, HuggingFace, OpenAI
- **Tailor Resume** → 6-slot prompt, JSON Resume output, education sanitization
- **Score Match** → ATS-style scoring 0-100
- **Verify Fidelity** → Cross-checks against base resume
- **PDF Render** → LaTeX compiler + Jinja2 HTML → Playwright PDF

### 2.3 Outreach Module (`backend/outreach/`)

- **Contact Finder** → Domain resolution, pattern emails, Hunter.io, YC founder API
- **Google Search** → LinkedIn profile search, careers page discovery
- **Email Gen** → LLM-generated personalized cold emails (120-180 words)
- **Gmail Send** → OAuth2 Gmail API with PDF attachments
- **Email Monitor** → Checks inbox for replies, auto-classifies as rejection / interview
- **Auto Apply** → Playwright form filler for Greenhouse, Lever, Workday

### 2.4 Tracking (`backend/outreach/tracker.py`)

- SQLite database with applications & sweeps tables
- Status lifecycle: discovered → tailored → ongoing → applied → rejected/interview
- Dedup: skips companies emailed within 14 days

### 2.5 Scheduler (GitHub Actions)

```yaml
schedule:
  - cron: "0 */4 * * *"    # Sweep every 4 hours
  - cron: "0 2,8,14,20 * * *"  # Email check
```

---

## 3. Critical Bugs

### BUG 1 — Email Delivery to ATS System Addresses (P0 - PRODUCTION BLOCKER)

**🟢 CONFIRMED** — You are actively experiencing this.

**Root Cause Analysis:**

The email system is designed to detect and block ATS domains (like `ashbyhq.com`, `greenhouse.io`, `lever.co`) via `_is_ats_domain()` in `contact_finder.py`. However, **emails are still being sent to ATS addresses** like `careers@jobs.ashbyhq.com` through this chain of issues:

**Primary Cause: Invalid domain → fallback generates bad contacts**

When a company uses an Ashby/GH/Lever job board URL (e.g., `https://jobs.ashbyhq.com/company-name`):
1. `find_company_domain()` correctly identifies it as ATS and returns `""` (empty)
2. `safe_domain` becomes `""`
3. No pattern contacts are generated
4. YC founder API may or may not find contacts with valid emails

BUT — `find_company_domain()` falls through to guessing the domain:
```python
guessed = f"{clean}.com"
if _is_ats_domain(guessed):
    return ""
return guessed  # ← Returns guessed domain even if wrong
```

This means for companies with non-obvious domains, the guess can land on a valid domain that happens to point to the ATS system or generate contact patterns like `careers@{wrongdomain}.com`.

**Secondary Cause: YC founder email construction bug (line 235)**

```python
f["email"] = f"{f['email']}@{safe_domain}" if safe_domain else f["{f['email']}@unknown.com"]
#                                                                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# This is a DICTIONARY KEY LOOKUP, not an f-string!
# Should be: f"{f['email']}@unknown.com"
```

When `safe_domain` is empty AND YC founders are found without email domains, this line raises a `KeyError: "{f['email']}@unknown.com"`. This exception is caught by the broad `except` block in `daily_sweep()`, and the job is skipped silently with no email sent (but also no contact logged).

**Tertiary Cause: No-API-key scenario**

On Render, `HUNTER_API_KEY` is not set (see `render.yaml` — `sync: false`). Without Hunter.io or Google Search API keys:
- No real contacts are found for most companies
- Only pattern-based emails are generated (if domain resolves)
- YC founder API has the KeyError bug above
- The best available contact is often `careers@{guessed-domain}.com`

**What happens in practice:**
1. Job from Ashby board (e.g., "Modal" at `jobs.ashbyhq.com/modal`)
2. Domain guess → `modal.com` (correct for Modal!)
3. Pattern → `careers@modal.com`, `jobs@modal.com`
4. These are NOT ATS domains → email sent to `careers@modal.com` ✅

But if domain guess is wrong (e.g., "A Team" → `ateam.com`), patterns are generated for a wrong domain that may either bounce or hit an ATS system alias.

**🛠️ Fix Plan:**
1. Fix the YC founder f-string bug (line 235)
2. Add `google_token.json` to `.gitignore` (it's already in `.gitignore` as `google_token.json`)
3. Implement recipient validation: skip email if no valid, verified contact found
4. Add explicit domain verification: check MX records for contact domain before sending
5. In `daily_sweep()`, if `best_contact` has empty email, DO NOT send — instead log the job as `pending_contact` for manual review

### BUG 2 — YC Founder Email Construction (P1)

**File:** `backend/outreach/contact_finder.py:235`

```python
f["email"] = f"{f['email']}@{safe_domain}" if safe_domain else f["{f['email']}@unknown.com"]
```

The `else` branch is syntactically wrong — it performs a dictionary lookup on `f` (the founder dict) with the literal key `"{f['email']}@unknown.com"`. This always raises `KeyError` when `safe_domain` is empty AND YC founders are returned (which is most YC companies).

**🛠️ Fix:**
```python
f["email"] = f"{f['email']}@{safe_domain}" if safe_domain else f"{f['email']}@unknown.com"
```

### BUG 3 — `" workable.com"` Leading Space in ATS_DOMAINS (P1)

**File:** `backend/outreach/contact_finder.py:91`

```python
ATS_DOMAINS = [
    ...
    " workable.com",  # ← Leading space! Won't match "workable.com"
    ...
]
```

The leading space in `" workable.com"` means `_is_ats_domain("workable.com")` returns `False`. Workable-hosted careers pages won't be filtered.

**🛠️ Fix:** Remove the leading space.

### BUG 4 — Email Fallback Sends to Self Instead of Skipping (P2)

**File:** `backend/main.py:357`

```python
recipient = best_contact.get("email", "") if best_contact.get("email") else settings.sender_email
```

When no valid contact is found, the system sends the email to `vatsalomar1@gmail.com` (your own email). This means you get useless emails in your inbox instead of nothing happening. Worse, the application is logged as `status=ongoing` when no email was actually sent to an employer.

**🛠️ Fix:** When no valid contact email is available, skip sending entirely and log the job as `status=missing_contact` for manual review.

### BUG 5 — `_score_contact` Ranks Generic Patterns Over Real Contacts (P2)

**File:** `backend/outreach/contact_finder.py:47-83`

The scoring system gives generic pattern emails (`careers@`, `jobs@`) a base score of 4, and `hello@` / `team@` a score of 2. In environments without Hunter.io (like Render), these pattern emails compete with Hunter.io results. Since `HUNTER_API_KEY` is not set on Render, the only contacts available are pattern-generic ones and YC API founders. The pattern-generated ones may not reach the actual hiring person.

### BUG 6 — `daily_sweep` Re-renders LLM Provider on Every Job (P2)

**File:** `backend/main.py:344`

```python
tailored_result = await tailor_resume_endpoint(TailorRequest(...))
```

Every call to `tailor_resume_endpoint` calls `reset_provider()` and `get_llm()` which re-authenticates with the LLM provider. When processing 10 jobs, this means 10 re-authentications. Inefficient and increases API latency.

---

## 4. Security Vulnerabilities

### VULN 1 — API Keys Exposed in Render Configuration (P1)

`render.yaml` contains hardcoded secrets references:
- `HF_API_KEY: sync: false` — Listed as an env var name
- All secrets are `sync: false` meaning they must be manually entered in Render dashboard

While the keys themselves aren't in the file, the configuration structure leaks the service architecture (which APIs are used, provider names). This is low severity but unnecessary information disclosure.

### VULN 2 — Google OAuth Token in Repository (P1)

**File:** `.gitignore` excludes `google_token.json` but `config.py` has:
```python
google_token_path: str = "data/google_token.json"
```

The `.gitignore` entry `google_token.json` (no `data/` prefix) won't match `data/google_token.json`. If this file is created, it WILL be committed.

**Check:** Run `git ls-files | grep token` to verify no token has been committed.

### VULN 3 — SQLite Database Exposed via API (P2)

**File:** `backend/main.py:469-471`
```python
@app.get("/dashboard")
async def dashboard():
    return tracker_dashboard()
```

The dashboard endpoint returns all application data including contact emails, notes, and statuses with NO authentication. If deployed on Render with a public URL, anyone can access `/dashboard` and see all your job applications.

### VULN 4 — No Input Validation on /discover-jobs (P2)

**File:** `backend/main.py:81-151`

The `sources` parameter is directly split and used to import/call modules:
```python
source_list = [s.strip() for s in sources.split(",")]
if "yc" in source_list:
    tasks.append(("yc", scrape_yc_jobs(...)))
```

An attacker could pass unexpected values. While this is constrained to pre-defined source names, there's no try/except around the URL/string parsing beyond the individual scrapers.

### VULN 5 — Open Redirect via /download-pdf (P2)

**File:** `backend/main.py:457-465`
```python
@app.get("/download-pdf")
async def download_pdf(path: str):
    full_path = Path(path)
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="PDF not found")
    return FileResponse(path=str(full_path), ...)
```

The `path` parameter is user-controlled with no directory traversal protection. An attacker could use `../../etc/passwd` to read arbitrary files. While `FileResponse` may restrict media types, the `download-pdf` path traversal is a real concern.

### VULN 6 — Dependency Vulnerabilities (P3)

`requirements.txt` has pinned minimum versions but no upper bounds or lock file:
- `httpx>=0.28.0` — no lock
- No `pip freeze > requirements-lock.txt`
- `huggingface-hub` is listed twice (lines 14 and 16)

### VULN 7 — Bare Except Blocks Throughout (P2)

Many functions use bare `except Exception:` or `except:` which silently swallows all errors:
- `contact_finder.py:161` — `except Exception: return []`
- `contact_finder.py:187` — `except Exception: return []`
- `email_gen.py` — multiple bare excepts
- `yc_scraper.py` — bare excepts in loops

This makes debugging impossible — errors disappear silently into empty returns.

---

## 5. What's Missing

### 5.1 Core Features

| Feature | Status | Priority |
|---------|--------|----------|
| LinkedIn/Indeed job discovery | ❌ Missing | P0 |
| Auto-apply to job portals | ⚠️ Partial (Playwright but needs manual review) | P1 |
| Response tracking & follow-ups | ❌ Missing | P1 |
| Duplicate detection across sources | ⚠️ Basic (by company+title) | P2 |
| Interview scheduling | ❌ Missing | P2 |
| Salary/benefit comparison | ❌ Missing | P3 |
| Multi-profile support | ❌ Missing | P2 |
| Company research enrichment | ⚠️ Basic (one-liner only) | P2 |

### 5.2 Infrastructure

| Feature | Status | Priority |
|---------|--------|----------|
| Proper logging & monitoring | ❌ Missing | P0 |
| CI/CD with proper secrets | ❌ Missing | P1 |
| Database migrations | ❌ Missing | P1 |
| Rate limiting / throttling | ❌ Missing | P2 |
| API auth / security | ❌ Missing | P1 |
| Health monitoring & alerts | ❌ Missing | P1 |
| Lock file (requirements-lock.txt) | ❌ Missing | P2 |
| Unit / integration tests | ❌ Missing | P0 |
| Error tracking (Sentry) | ❌ Missing | P1 |
| Docker Compose for full stack | ⚠️ Partial | P2 |

### 5.3 Contact Discovery

| Feature | Status | Priority |
|---------|--------|----------|
| Hunter.io integration | ⚠️ Built but config missing in production | P0 |
| LinkedIn contact finding | ⚠️ Script exists but not integrated | P1 |
| Apollo.io / Lusha integration | ❌ Missing | P1 |
| Email verification (MX check) | ❌ Missing | P0 |
| Contact scoring improvements | ⚠️ Basic heuristic scoring | P2 |
| Bulk email validation | ❌ Missing | P1 |

### 5.4 Email System

| Feature | Status | Priority |
|---------|--------|----------|
| Attachment fallback | ⚠️ Partial | P2 |
| Email templates | ❌ Missing | P2 |
| A/B subject line testing | ❌ Missing | P3 |
| Send scheduling | ❌ Missing | P2 |
| Reply classification | ⚠️ Basic keyword matching | P2 |
| Follow-up sequence | ❌ Missing | P1 |
| Unsubscribe / bounce handling | ❌ Missing | P0 |
| Email analytics | ❌ Missing | P2 |

### 5.5 Quality & Reliability

| Feature | Status | Priority |
|---------|--------|----------|
| Unit tests | ❌ Missing | P0 |
| Integration tests | ❌ Missing | P0 |
| End-to-end tests | ❌ Missing | P1 |
| Type hints (complete) | ⚠️ Partial | P2 |
| Error recovery | ❌ Missing | P1 |
| Retry logic | ❌ Missing | P1 |
| Telemetry / observability | ❌ Missing | P1 |

---

## 6. Complete Improvement Plan

### Phase 0: Critical Fixes (SHIP THIS WEEK)

```
Priority: P0 | Effort: 2-3 hours | Impact: Production stability
```

- [ ] **Fix YC founder f-string bug** (`contact_finder.py:235`)
- [ ] **Fix `" workable.com"` leading space** (`contact_finder.py:91`)
- [ ] **Don't send email when no valid contact** (`main.py:357`) — skip instead of self-sending
- [ ] **Stop sending to ATS domains entirely** — validate recipient domain before each send
- [ ] **Add `.env` variables for Hunter.io** on Render and configure the API key
- [ ] **Add `/dashboard` auth check** — basic API key header at minimum
- [ ] **Fix `/download-pdf` path traversal** — validate path is within output directory
- [ ] **Disable all auto-sending** until contact resolution is confirmed working
- [ ] **Add MX record check** for recipient email domain before sending

### Phase 1: Foundation (NEXT 2 WEEKS)

```
Priority: P0-P1 | Effort: 3-5 days
```

- [ ] **Unit test suite** — pytest for every module:
  - Contact finder (test ATS filtering, domain resolution, scoring)
  - Email gen (test prompt output parsing)
  - Discover scrapers (test with mock data)
  - Tracker (test DB operations)
- [ ] **Integration tests** — test `/daily-sweep` flow end-to-end with mocks
- [ ] **Lock file** — `pip freeze > requirements-lock.txt`
- [ ] **Structured logging** — JSON logs with request IDs, log levels per module
- [ ] **Error tracking** — Sentry integration
- [ ] **Add `data/` prefix** to `google_token.json` in `.gitignore`
- [ ] **Fix bare except blocks** — log errors with context, don't silently swallow

### Phase 2: Contact Discovery Overhaul (WEEKS 3-4)

```
Priority: P0 | Effort: 3-5 days
```

- [ ] **Hunter.io API key** — get one and configure on Render
- [ ] **Email verification service** (ZeroBounce / NeverBounce) — verify email deliverability BEFORE sending
- [ ] **Domain MX record check** — `dnspython` to verify domain accepts mail
- [ ] **Improved company domain resolution**:
  - Use Crunchbase / Clearbit API for company domain lookup
  - Fallback: Wikipedia API
  - Caching layer (Redis or simple TTL cache)
- [ ] **Multiple contact sources**:
  - Apollo.io (free tier: 50 credits/month)
  - Lusha (free tier: 50 credits/month)
  - Proxycurl (for LinkedIn emails)
  - SignalHire
- [ ] **Contact scoring overhaul**:
  - Score actual verified emails >> pattern-generated >> generic
  - Only send if confidence ≥ "medium"
  - Flag low-confidence contacts for manual review

### Phase 3: Email Intelligence (WEEKS 5-6)

```
Priority: P1 | Effort: 3-5 days
```

- [ ] **Follow-up sequences**:
  - Email 1: Initial outreach (Day 0)
  - Email 2: Follow-up (Day 5)
  - Email 3: Final follow-up (Day 12)
  - Auto-stop on reply
- [ ] **Smart email timing**:
  - Send Tue-Thu 8-10am recipient timezone
  - Avoid Monday mornings / Friday afternoons
- [ ] **Reply classification (ML)**:
  - Replace keyword matching with an LLM-based classifier
  - Categories: interview_request, rejection, not_interested, question, out_of_office
  - Auto-schedule interviews when detected
- [ ] **A/B subject line testing**:
  - Track open rates per subject line pattern
  - Learn which styles perform best
- [ ] **Bounce handling**:
  - Parse Gmail bounce notifications
  - Auto-remove invalid contacts
  - Retry with alternative contact

### Phase 4: LinkedIn & Auto-Apply (WEEKS 7-8)

```
Priority: P1 | Effort: 4-6 days
```

- [ ] **LinkedIn job search**:
  - LinkedIn Jobs API (via rapidapi or similar)
  - Filter: SWE intern/junior, India/Remote, <7 days old
- [ ] **Indeed job search**:
  - Indeed Publisher API or scraping
  - Same filters
- [ ] **Auto-apply improvements**:
  - Full Greenhouse form fill (resume + cover letter + questions)
  - Lever + Ashby form support
  - LinkedIn Easy Apply automation
- [ ] **YC manual apply assistant**:
  - Open YC company in browser
  - Pre-fill form with resume data
  - Just need user to click submit

### Phase 5: Intelligence Layer (WEEKS 9-10)

```
Priority: P2 | Effort: 5-7 days
```

- [ ] **Company research enrichment**:
  - Auto-fetch company Crunchbase profile
  - Recent funding news
  - Tech stack (BuiltWith API)
  - Culture signals (Glassdoor ratings, team size)
- [ ] **Match scoring overhaul**:
  - Multi-dimensional scoring: skills (40%), experience (30%), culture (15%), growth (15%)
  - Only email for jobs with score ≥ 70
- [ ] **Salary analysis**:
  - Parse salary from descriptions
  - Compare with market rates
  - Flag below-market opportunities
- [ ] **Priority ranking**:
  - Rank jobs by: match score × company quality × response probability
  - Focus effort on top-N jobs per week

### Phase 6: Operations & Scale (WEEKS 11-12)

```
Priority: P2-P3 | Effort: 3-4 days
```

- [ ] **Dashboard web UI** (simple HTML or Streamlit):
  - See all applications
  - Filter by status, source, company
  - Daily/Weekly summary
  - Response rate analytics
- [ ] **Weekly report**:
  - Auto-generated email summary
  - Jobs found, applied, responses, interviews
  - Cost tracking (API usage)
- [ ] **Multi-user support**:
  - Upload resume → get tailored + auto-apply
  - Separate tracking per user
- [ ] **Rate limiting**:
  - Max 10 emails/day (Gmail limit is 500/day for free tier)
  - Respect sender reputation
- [ ] **Cost optimization**:
  - Cheaper LLM for matching, expensive LLM for email generation
  - Cache frequent prompts
  - Batch API calls

---

## 7. Roadmap: Best Job Application Agent

### What "Best" Means

A world-class job application agent:
1. **Finds every relevant job** across ALL platforms within hours of posting
2. **Finds the RIGHT person** to contact — not `careers@`, not ATS systems
3. **Sends personalized, high-quality emails** that get responses (30%+ reply rate)
4. **Automates the entire application process** — from discovery to interview scheduling
5. **Learns from outcomes** — which emails work, which jobs convert, which sources deliver
6. **Is reliable & observable** — never silently fails, always logs, alerts on issues

### The Ultimate Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Orchestrator (n8n / Temporal)             │
│  Schedule → Discover → Research → Contact → Tailor → Email   │
└─────────────────────────────────────────────────────────────┘
         │                │                │
         ▼                ▼                ▼
  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
  │ Job Discovery │ │ Contact       │ │ Email Engine │
  │               │ │ Intelligence  │ │              │
  │ 10+ sources   │ │ 5+ providers  │ │ LLM-written  │
  │ Real-time     │ │ MX-verified   │ │ A/B tested   │
  │ Dedup & rank  │ │ Score ≥ 0.8   │ │ Follow-up    │
  └──────────────┘ └──────────────┘ └──────────────┘
         │                │                │
         ▼                ▼                ▼
  ┌─────────────────────────────────────────────────────────────┐
  │                    Observability Stack                       │
  │  Logs (JSON) → Monitoring → Alerts → Weekly Report           │
  └─────────────────────────────────────────────────────────────┘
```

### Key Differentiators

1. **Contact-first approach**: Never send to `careers@` or `jobs@`. Always find a person.
2. **Verified delivery**: Check MX records + email verification BEFORE sending.
3. **Follow-up engine**: 3-email sequences with smart timing and auto-stop on reply.
4. **Response analytics**: Track which emails get replies, which subject lines work.
5. **Multi-model LLM**: Cheap model for scoring/ranking, premium model for email writing.
6. **Full auto-apply**: Submit forms on Greenhouse, Lever, LinkedIn, Workday via Playwright.
7. **Interview scheduling**: Auto-detect interview invites, suggest calendar slots.

---

## Summary: Immediate Action Items

| # | What | Why | Effort |
|---|------|-----|--------|
| 1 | Fix YC founder f-string bug (`contact_finder.py:235`) | Crashes when safe_domain is empty | 1 min |
| 2 | Fix ` workable.com` leading space | ATS blocking bug | 1 min |
| 3 | Skip email if no valid contact (`main.py:357`) | Stops self-sending | 5 min |
| 4 | Configure Hunter.io API key on Render | Actually find real contacts | 10 min |
| 5 | Add MX record check before sending | Verify deliverability | 30 min |
| 6| Add auth to `/dashboard` | Security | 15 min |
| 7 | Fix `/download-pdf` path traversal | Security | 15 min |
| 8 | Disable auto-send until contacts work | Stop embarrassing bounces | 1 min |
| 9 | Fix `data/google_token.json` in `.gitignore` | Prevent secret leak | 1 min |
| 10 | Write tests for contact_finder.py | Catch ATS bugs before deploy | 2 hours |
