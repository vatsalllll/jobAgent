# Job Agent — Deep Analysis & Free-Resource Improvement Report

> **Date:** 2026-07-14
> **Scope:** Every file in `backend/` (discover, tailor, outreach, config, tests), deployment (`render.yaml`, GitHub Actions, n8n), plus live-verified research on free job/contact/email/LLM resources.
> **Method:** 4 parallel subsystem code reviews + 1 web-research stream (endpoints hit live via curl/WebFetch on 2026-07-14). Codebase is ~5,250 LOC across discover/outreach/tailor.
> **Supersedes:** `JOB_AGENT_AUDIT.md` (2026-06-23) — that audit's four headline bugs are now **fixed** (verified below); this report reflects the *current* state.

---

## 0. TL;DR — the honest headline

The old audit's P0 bugs are genuinely fixed (YC f-string, `workable.com` space, self-send, MX check added). **But the agent as deployed on Render is still largely ineffective**, for four compounding reasons:

1. **It finds very few *real* jobs.** Of the 5 default sources, `github` always returns `[]` (parses Markdown as HTML), `yc` returns synthetic "check careers page" non-jobs, `lever` mostly 404s on stale slugs, and `greenhouse`/`ashby` are over-filtered (junior-keyword-only). Real volume is thin.
2. **It emails *guessed* addresses.** With no Hunter/Google keys in prod, contact discovery collapses to domain-guessing (`{company}.com`) + generic patterns + guessed YC founder emails — and the scoring ranks those guesses **above** real verified contacts.
3. **Fabrication isn't actually prevented.** `verify_fidelity` fails *open* (parse error → "faithful"), is never enforced, and self-judges with the same weak free model.
4. **It forgets everything on restart.** The SQLite tracker lives on Render's ephemeral disk, so the 14-day dedup resets on every deploy/spin-down → the same company gets re-emailed.

None of the fixes below require a paid subscription. The good news: there is a large amount of **verified-free, no-auth job data** you're not yet using (17k+ structured listings from one GitHub file alone), and your DIY contact/LLM foundations are sound and just need re-pointing.

**Keep-it-free verdict:** 100% achievable. Everything recommended here is free-tier or no-auth. Current real cost ≈ $0 (HF/Groq free LLM, Render free, GitHub Actions free) — the goal is to raise *quality* at the same $0.

---

## 1. What actually runs in production (the reality vs. the README)

The README describes a Playwright + Claude Sonnet system. **Production is different** (`render.yaml`):

| Aspect | README says | Production actually does |
|---|---|---|
| LLM | Claude 3.5 Sonnet | **HuggingFace → Groq, `Qwen/Qwen3-32B`** (`render.yaml:11-16`) — free tier |
| YC scraping | Playwright headless | **Disabled** (`DISABLE_PLAYWRIGHT=true`) → synthetic API fallback |
| Resume PDF | Playwright HTML→PDF | **fpdf2 fallback** (Playwright not even installed) or a 3rd-party LaTeX web service |
| Persistence | — | **Ephemeral** SQLite + PDFs, wiped on every restart |
| Scheduler | n8n every 12h | **GitHub Actions** every 4h (n8n is dead/redundant) |
| Auto-apply | Greenhouse/Lever/Workday | **Dead in prod** (Playwright disabled; not wired into server) |

**Data flow (prod):** GitHub Actions cron → `POST /daily-sweep` → discover (yc,greenhouse,github,lever,ashby) → dedup/interleave → for each job: tailor (LLM) → find contact → generate email → MX-verify recipient → Gmail send w/ PDF → log to SQLite → sync to Google Sheets.

---

## 2. Critical findings, ranked

### 🔴 P0 — makes the agent ineffective or sends bad mail *right now*

| # | Finding | File / evidence | Impact |
|---|---|---|---|
| P0-1 | **`github` source always returns `[]`** — fetches a Markdown README and parses it as HTML (`soup.find_all("tr")` on pipe-tables). Runs by default, contributes zero. | `discover/github_jobs.py:33-37` | A default source silently dead. |
| P0-2 | **`yc` returns synthetic non-jobs** — every listing is title `"Software Engineer (check careers page)"`, guessed `{website}/jobs` URL, `posted_date=now`. No real roles. | `discover/yc_api_fallback.py:100,106` | Your flagship source produces junk rows. |
| P0-3 | **Contact scoring inversion** — a guessed `founders@domain` pattern (+10) or a guessed YC-founder `first.last@` (title "Founder", +15) outranks a **real GitHub-verified** personal email (+8). No bonus for verified sources except Hunter. | `outreach/contact_finder.py:48-85` | The agent preferentially emails *guesses*. |
| P0-4 | **Domain guessing still active** — falls back to `f"{clean}.com"` where `clean` strips all non-alphanumerics ("A Team"→`ateam.com`). MX check passes any valid-but-wrong domain. | `contact_finder.py:120-123` | Wrong-company deliverability; bounce/reputation risk. |
| P0-5 | **`verify_fidelity` fails open + unenforced** — JSON parse failure returns `{"is_faithful": True}`; result is never acted on; self-judged by the same weak model. | `tailor/claude_tailor.py:110`; `main.py:197-215` | Fabrication is *not* actually prevented despite the safety claim. |
| P0-6 | **Ephemeral DB breaks dedup** — `tracker.db` on Render free tier (no persistent `disk:`) is wiped on every deploy/spin-down; `was_emailed_recently()` then returns False. | `render.yaml:6` (no disk); `outreach/tracker.py:8,153-162` | Same company re-emailed after any restart. |
| P0-7 | **`Qwen3 <think>` leakage** — `_strip_thinking` targets DeepSeek tokens, has an always-true `"" in text` clause, and `text.split("")` raises `ValueError`. Qwen3's `<think>…</think>` is never stripped → pollutes JSON parsing. | `tailor/llm.py:65-72` | Tailoring/scoring parse failures on the prod model. |

### 🟠 P1 — significant reliability / security gaps

| # | Finding | File / evidence |
|---|---|---|
| P1-1 | **Mutating endpoints are unauthenticated** — `/daily-sweep`, `/discover-jobs`, `/tailor-resume`, `/generate-email`, `/sync-sheets`, `/check-emails`, `/track/{id}` have no auth. Anyone with the Render URL can trigger sweeps and send emails. (`/dashboard` & `/download-pdf` *are* protected via `Depends(verify_api_key)`.) | `main.py:91,174,223,248,519,526,541` |
| P1-2 | **`lever` slugs stale** — `figma-lever`, `postman-lever` are invalid tokens; several companies migrated off Lever → 404 → `[]`. Plus junior-only filter starves big boards. | `discover/lever_api.py:7-12,56-59` |
| P1-3 | **Over-restrictive filters** — Greenhouse/Ashby require an explicit junior/intern keyword; most boards don't tag levels → near-zero yield. | `discover/greenhouse.py:96-102`, `discover/ashby_api.py:44-63` |
| P1-4 | **Age filter is a no-op for most sources** — `lever/ashby/hackernews/yc/github` all set `posted_date=now`, so `max_age_days<=4` passes everything; the "freshness" guarantee is illusory except for Greenhouse (`updated_at`). | `main.py:162` + those sources |
| P1-5 | **Dead free team-scraper** — unterminated regex char-class `r">([a-z]+\s+[a-z]+)\s*[-—(\|<"` throws `re.error`, swallowed by bare except → never returns names. | `outreach/contact_discovery_free.py:128` |
| P1-6 | **GitHub token never sent** — docstring claims 5,000 req/hr but no auth header is set → stuck at 60/hr unauth, exhausted in a multi-company sweep. | `outreach/contact_discovery_free.py:68,81` |
| P1-7 | **Reply misclassification** — `"thank you for your interest"` is in the *rejection* list and checked first, so an interview invite opening with that phrase is marked **rejected**. Keyword-only; no thread/`In-Reply-To` validation. | `outreach/google_search.py:23,44`; `outreach/email_monitor.py:90-95` |
| P1-8 | **LaTeX resume ignores tailored content** — identity, education (BITS), and the BLive experience header are hardcoded; only bullet lines come from the resume; `_escape_latex` doesn't escape `\ { }` → invalid LaTeX on many inputs. | `tailor/latex_compiler.py:21-28,123-131,212-226` |
| P1-9 | **No LLM rate-limit/error retry** — the HF/Groq free tier 429/503s propagate to HTTP 500; only JSON-parse has a retry. Blocking sync SDK calls also stall the async event loop. | `tailor/llm.py:19,34-45` |
| P1-10 | **Google auth: no caching, no error handling** — a token refresh network round-trip runs on *every* send/sync; a revoked refresh token raises unhandled (send silently skipped). | `outreach/google_auth.py:35,62-68` |

### 🟡 P2 — quality, coverage, hygiene

- **`remoteok` always returns `[]`** — the parse loop is indented inside an `except` block after `return jobs` (dead code). `discover/remoteok.py:26-29`. (Not a default source, but broken if enabled.)
- **`indeed_rss` likely dead** — Indeed discontinued public RSS; endpoint returns HTML/404. `discover/indeed_rss.py:27-28`.
- **Turing/Upwork/Toptal** — nonexistent/blocked endpoints or Playwright-only; low ROI. `discover/turing_upwork.py`, `discover/toptal_scraper.py`.
- **Dedup by company only** (not company+role) — a second distinct role at the same company within 14 days is skipped. `main.py:309`; `tracker.py:153`.
- **ATS blocklist gaps** — missing `jobvite`, `icims`, `taleo`, `bamboohr`, `jazzhr`, `teamtailor`, `personio`, `join.com`. `contact_finder.py:88-94`.
- **SMTP verification absent** — `email_verify.py` only checks MX (domain accepts mail), not mailbox existence; catch-all providers (gmail/outlook) hardcoded valid → guessed personal Gmails pass.
- **n8n workflow is dead & broken** — superseded by GitHub Actions; its `connections` map references a mis-named trigger node so it would never fire; hardcoded `N8N_ENCRYPTION_KEY=change-me…`. Delete or mark local-only.
- **`gemini_api_key` configured but no code path** — `config.py:21` sets it; `llm.py` has no Gemini provider.
- **`requirements.txt`** lists `huggingface-hub` twice (lines 14 & 16); no lock file.
- **Tests:** 167 pass, but the entire `tailor/` package has **zero tests**, and several "tests" make live network calls (DNS/GitHub/HTTP) → will flake offline / in CI.

### ✅ Verified fixed since the 2026-06-23 audit
YC founder f-string (`contact_finder.py:236`), `workable.com` leading space (`:92`), self-send fallback removed (`main.py:377,397-400`), MX check added before send (`email_verify.py` → `main.py:407`), `/download-pdf` path-traversal guard (`main.py:501-504`), `/dashboard` auth (`main.py:515`).

---

## 3. Free resources to add (all verified live, 2026-07-14)

> Legend: ✅ hit live, 200 + real data today · ⚠️ works with caveats · ❌ dead/blocked/not-free.

### 3A. Job discovery — public ATS board APIs (no auth, highest value)

Same JSON the career pages call; no login circumvented. Use a real `User-Agent`, ~1 req/s, cache.

| Source | Endpoint (verified) | Notes |
|---|---|---|
| **Greenhouse** ✅ | `https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` (`stripe`→524) | You use this. `?content=true` = full JD. |
| **Lever** ✅ | `https://api.lever.co/v0/postings/{site}?mode=json` (`palantir`→276) | You use this. Fix stale slugs. `[]`=migrated. |
| **Ashby** ✅ | `https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true` (`openai`→720) | You use this. Adds **salary bands**. |
| **SmartRecruiters** ✅ **(add)** | `https://api.smartrecruiters.com/v1/companies/{company}/postings?limit=100` | 10 req/s. Enterprise-heavy. |
| **Workable** ✅ **(add)** | `https://apply.workable.com/api/v1/widget/accounts/{account}?details=true` | Follow job URL for full JD. |
| **Recruitee** ✅ **(add)** | `https://{company}.recruitee.com/api/offers/` | EU/SMB coverage. |
| **Teamtailor** ✅ **(add)** | `https://{company}.teamtailor.com/jobs.json` (free JSON Feed) | NOT `api.teamtailor.com` (that's paid). |
| **Workday** ⚠️ | `POST https://{tenant}.wd{N}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs` body `{"limit":20,"offset":0,"searchText":""}` (`nvidia`→2,000) | Akamai blocks bulk; great per big-enterprise. |

**Universal gotcha:** ATS slugs are **not** guessable from brand name and **decay** as companies switch vendors. Discover each slug from the live careers-page URL; re-validate periodically.

### 3B. Job discovery — the single biggest free win

| Source | Endpoint | Why |
|---|---|---|
| **SimplifyJobs/New-Grad-Positions** ✅ | `https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json` — **17,289 entries** | Clean structured JSON: `company_name, title, url, locations, date_posted, active, sponsorship, degrees`. **Best free structured data in this whole report.** |
| **SimplifyJobs/Summer2026-Internships** ✅ | same pattern, swap repo — **14,929 entries** | Your `github_jobs.py` currently fetches the README (broken). Point it at `listings.json` on the **`dev` branch** instead. |

### 3C. Job discovery — aggregator APIs/feeds

| Source | Endpoint | Verdict |
|---|---|---|
| **The Muse** ✅ | `https://www.themuse.com/api/public/jobs?page=1` | **500 req/hr no key** (3,600 w/ free key), ~410k jobs. Genuinely open. |
| **Himalayas** ✅ | `https://himalayas.app/jobs/api?limit=20&offset=0` | ~103k jobs (20/req cap). **No re-syndication** per ToS. |
| **Remotive** ✅ | `https://remotive.com/api/remote-jobs?category=software-dev&search=python` | Cleanest remote feed. Use `.com` (`.io` dead). You have it. |
| **RemoteOK** ✅ | `https://remoteok.com/api` | **Needs real UA**; **start at index `[1]`** (`[0]`=metadata); **attribution required** by ToS. Fix your dead loop. |
| **WeWorkRemotely** ✅ | `https://weworkremotely.com/remote-jobs.rss` | RSS only; all paid listings = high signal. You have it. |
| **Arbeitnow** ✅ | `https://www.arbeitnow.com/api/job-board-api?page=1` | EU/DACH + `visa_sponsorship` filter. |
| **Jobicy** ✅ | `https://jobicy.com/api/v2/remote-jobs?count=50&geo=usa&tag=python` | ≤1 poll/hr; no re-syndication. |
| **HN "Who is Hiring"** ✅ | ① `https://hn.algolia.com/api/v1/search_by_date?query=Who%20is%20Hiring&tags=story,author_whoishiring` → thread ID; ② `https://hn.algolia.com/api/v1/items/{id}` | **Unique early-stage/YC-adjacent roles.** Correct tag is `author_whoishiring`. You have this — keep it. |

### 3D. Job discovery — free-with-key (gov/commercial) & India

| Source | Endpoint | Key / limit |
|---|---|---|
| **Adzuna** ⚠️ | `https://api.adzuna.com/v1/api/jobs/{country}/search/{page}?app_id=&app_key=&what=python&where=` — supports `country=in` | Instant key, no card. ~250/day. **Salary + India coverage.** |
| **USAJobs** ✅ | `https://data.usajobs.gov/api/search?Keyword=developer` — headers `User-Agent:{email}` + `Authorization-Key:{key}` | Instant email key. US federal. |
| **Reed** ✅ | `https://www.reed.co.uk/api/1.0/search?keywords=python` — Basic auth (key as username) | UK only. ~1,000/day. |
| **Cutshort (IN)** ✅ | `https://cutshort.io/sitemap_jobs.xml` (sanctioned in `robots.txt`) | Title/company/location in slug; fetch page for JD. **Best India option.** |
| **Hirist (IN)** ✅ | `https://hirist.tech/new_sitemap-j-1.xml.gz` | Respect `Crawl-delay: 10`. |
| **foundit / ex-Monster (IN)** ✅ | `…/todays-jobs-sitemap.xml` | Closest to a real-time India feed. |

### 3E. Platforms you named — realistic free status

| Platform | Status | Free path that works |
|---|---|---|
| **YC** | ✅ metadata / ❌ live jobs | `https://yc-oss.github.io/api/companies/all.json` (6,001+ companies + `isHiring`) — richer/static vs your `api.ycombinator.com` fallback. Actual roles: via HN Algolia. WAAS `/jobs` returns 406 anon. |
| **LinkedIn** | ⚠️ | Guest endpoint `https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=&location=&start=0` works no-login **but** `robots.txt` disallows `/jobs-guest/` and IP-blocks ~100 results. **Low-volume, short bursts only.** |
| **Naukri** | ❌ | Internal API → 406 "recaptcha required"; TLS bot-filtering. Needs headless+residential proxy+CAPTCHA (paid territory). **Not free-feasible.** |
| **Wellfound** | ❌ | No public API; GraphQL needs DataDome cookies. **Manual browsing only.** |
| **Indeed** | ❌ official / ⚠️ unofficial | Publisher API dead since 2023; scraping hits Cloudflare. `github.com/speedyapply/JobSpy` (mobile-API path) is the least-blocked option (moderate ToS risk). Your `indeed_rss.py` is effectively dead. |

### 3F. Contact / email discovery (free)

**Recommended free stack:** domain → email permutation → MX check → **GitHub commit-email extraction** as ground truth → **Google CSE (100/day)** for names/roles → spend Hunter's ~25 free searches/month only on top targets.

| Method | How | Verdict |
|---|---|---|
| **GitHub commit emails** ✅ **(add)** | `GET https://api.github.com/repos/{org}/{repo}/commits` → `commit.author.email` (skip `*.noreply.github.com`). 60/hr unauth, **5,000/hr with a token**. | Strongest fully-free method for eng contacts. Complements your existing user-search. **Actually send the token.** |
| **Email permutation** ✅ | `first.last@`, `f.last@`, `first@`… | Backbone. You have it. |
| **MX check (dnspython)** ✅ | `dns.resolver.resolve(domain,"MX")` | You have it. Necessary, not sufficient. |
| **Google Custom Search API** ✅ | `https://www.googleapis.com/customsearch/v1?key=&cx=&q=` — **100/day free**. Dorks: `site:linkedin.com/in "Company" recruiter`. | Use the *official API*, not raw scraping. Free key + CSE id. |
| **Disposable-domain list** ✅ **(add)** | `github.com/disposable-email-domains/disposable-email-domains` (~3,500+) | Replace your tiny hardcoded set. |
| **SMTP RCPT-TO probe** ⚠️ | port-25 handshake | **Keep OFF.** Cloud hosts block port 25; catch-alls lie; probing risks IP blacklisting. |
| **Freemium finders** | Hunter ~25 searches+50 verify/mo (API on free) · Skrapp ~100/mo · Apollo (API now **paid**) · RocketReach ~5 · Snov trial-ish | Quality-check on guesses, not the primary engine. |

### 3G. Email sending (free tiers + deliverability)

| Option | Free limit | Verdict |
|---|---|---|
| **Gmail API (consumer)** | 500 recipients / 24h (throttled lower if bulk-looking) | ✅ Fine for low-volume personal outreach (dozens/day). You use this. |
| **Brevo** | **300/day** (~9k/mo) | ✅ Best free daily allowance if you outgrow Gmail. |
| **SMTP2GO** | 1,000/mo, 200/day (permanent) | ✅ Good permanent fallback. |
| **Mailjet / Resend** | 200/day / 100/day | ⚠️ Daily caps. |
| **SendGrid** | ❌ free plan retired Jul 2025 | ❌ |
| **Amazon SES** | no email free tier for new accts (~$0.10/1k) | ⚠️ Cheapest at scale, not free. |

**Deliverability checklist:** secondary sending domain · SPF+DKIM+DMARC (start `p=none`) · warm up 3-4 weeks (5-10/day ramping) · complaints <0.3%, bounces <2% · one-click unsubscribe (RFC 8058) · plain-text, few links first touch · personalize + real monitored Reply-To.

### 3H. LLMs (free) for tailoring — re-point away from HF serverless

| Provider | Free limits (2026) | Endpoint |
|---|---|---|
| **Groq** ✅ #1 | Llama 3.3 70B: 30 RPM / 1,000 RPD / 12k TPM; ~500-800 tok/s | `api.groq.com/openai/v1/chat/completions` |
| **Google Gemini** ✅ #2 | 2.5 Flash-Lite: 15 RPM / **1,000 RPD**; 2.5 Flash: 10 RPM / 250 RPD | `generativelanguage.googleapis.com/v1beta/models/{m}:generateContent` — ⚠️ free-tier inputs may train; strip PII |
| **OpenRouter** ✅ #3 | `:free` models 50/day (→1,000/day after one-time $10) | `openrouter.ai/api/v1/chat/completions` |
| **SambaNova** ✅ | Llama 405B/70B free; **20M tokens/day** | `api.sambanova.ai/v1/chat/completions` |
| **Cerebras** ✅ | 5 RPM, 1M TPD, 1,000-3,000 tok/s | `api.cerebras.ai/v1/chat/completions` |
| **Ollama (local)** ✅ | unlimited, private (needs ≥8GB RAM) | `http://localhost:11434/api/generate` |
| **HuggingFace serverless** ⚠️ | your current default — now the **weakest** free path | — |

All are OpenAI-compatible → slot into your existing `tailor/llm.py` abstraction with minimal code.

---

## 4. Prioritized improvement roadmap (all free)

### Phase 0 — Quick wins (hours, high impact)

1. **Fix `github_jobs.py`** → fetch `listings.json` (dev branch) from SimplifyJobs New-Grad + Summer2026. *(+30k structured listings, the single biggest coverage gain.)*
2. **Fix the contact scoring inversion** — give verified sources (`github_public`, real Hunter) a decisive bonus over guessed patterns/founders; only send when a contact is verified or `confidence≥medium`. Otherwise log `missing_contact` for manual apply.
3. **Stop domain-guessing for sends** — if the domain is guessed (not from `company_url` or `COMMON_DOMAINS`), do not auto-email; queue for manual review.
4. **Swap LLM provider to Groq** (Llama 3.3 70B) with Gemini Flash-Lite fallback; fix `_strip_thinking` to strip `<think>…</think>`. *(Fixes P0-7 + reliability.)*
5. **Enforce `verify_fidelity`** — fail *closed* (parse error ⇒ not faithful), and block send/PDF when `is_faithful=False`.
6. **Auth the mutating endpoints** — add `Depends(verify_api_key)` to `/daily-sweep`, `/sync-sheets`, `/check-emails`, etc.; set `API_KEY` in Render + pass `x-api-key` from GitHub Actions.
7. **Fix reply classifier** — move `"thank you for your interest"` out of rejection; check second-round/interview keywords first; validate replies by thread.

### Phase 1 — Coverage & persistence (days)

8. **Add ATS sources:** SmartRecruiters, Workable, Recruitee, Teamtailor (mirror `greenhouse.py` structure). Build/refresh the slug list from live careers URLs.
9. **Add aggregators:** The Muse (500/hr no key), Himalayas, Adzuna (`country=in`, salary + India). *(Real India coverage since Naukri/Wellfound are blocked.)*
10. **Add India sitemaps:** Cutshort, Hirist, foundit (sanctioned, daily).
11. **Persist state** — move dedup/tracking off ephemeral SQLite. Free options: (a) treat the **Google Sheet as source of truth** for `was_emailed_recently`; (b) free Postgres (Supabase/Neon free tier); (c) commit a small state file back to the repo via the Action.
12. **Relax level-filters** — replace junior-keyword gates with LLM/title heuristics so Greenhouse/Ashby actually yield.
13. **Send the GitHub token** in `contact_discovery_free.py` (60→5,000 req/hr) and fix the dead team-scraper regex.

### Phase 2 — Quality & hygiene (days)

14. **Real freshness** — parse actual `createdAt`/`updated_at`/`date_posted` per source instead of `posted_date=now`.
15. **Contact verification** — keep MX; add the maintained disposable-domain list; leave SMTP probing off.
16. **PDF** — either install a headless renderer path or fix `latex_compiler.py` to use tailored content + escape `\ { }`; add tests.
17. **Tests for `tailor/`** — mock the LLM; unit-test `extract_json`, `verify_fidelity` fail-closed, education sanitization.
18. **Cleanup** — delete/mark n8n as local-only; dedupe `requirements.txt`; add `*.db`/`*.log` to `.gitignore`; add a lock file; remove Turing/Upwork/Toptal or gate them clearly.
19. **Dedup by company+role**, not company alone.

### Phase 3 — Effectiveness (optional, still free)

20. **Follow-up sequences** (Day 0/5/12, auto-stop on reply) via the persisted tracker.
21. **Multi-dimensional match scoring**; only email when score ≥ threshold; rank effort toward top jobs.
22. **Cold-start mitigation** — a lightweight external ping just before the cron so the 4-hourly sweep doesn't eat a 60s Render spin-up inside the 300s budget.

---

## 5. What to explicitly NOT build on (wasted effort / bans)

LinkedIn scraping (robots-disallowed, IP-bans ~100 results) · Naukri (reCAPTCHA-gated) · Wellfound (DataDome) · Indeed official API (dead) · Instahyre & Jooble (Cloudflare challenge) · SendGrid free (retired) · SMTP RCPT-TO as core logic (port 25 blocked, blacklist risk) · `remote.io` API (gated).

---

*Full per-file evidence with line numbers is in §2. Endpoints in §3 were hit live on 2026-07-14; freemium limits drift — re-check pricing pages before relying.*
