"""
Email generator — rewritten to follow user's exact prompt structure:
1. Structured context block (match score, skills, angles)
2. Personalized cold email (120-180 words, Opening→Fit→Evidence→Interest→CTA)
3. 5 subject line options
4. Optional referral version for engineers
"""

import json

from config import settings
from tailor.llm import get_llm, extract_json


CONTEXT_BLOCK_PROMPT = """You are an experienced technical recruiter.

Analyze this candidate against the job and produce a structured summary.

[CANDIDATE PROFILE]
{candidate_profile}

[RESUME]
{resume_json}

[TARGET ROLE]
{job_title} at {company}

[JOB DESCRIPTION]
{job_description}

Return valid JSON with these exact keys:
{{
  "role_match_score": <0-100>,
  "matching_skills": ["<5-8 skills from resume that match the role>"],
  "missing_skills": ["<0-3 skills from role not in resume, be honest>"],
  "strongest_resume_points": ["<3 strongest achievements or projects relevant to this role>"],
  "company_signal": "<what the company appears to be building or hiring for, 1 sentence>",
  "best_angle": "<the single strongest pitch angle for this candidate, 1 sentence>"
}}

Return ONLY the JSON. No preamble."""


EMAIL_PROMPT = """You are an experienced technical recruiter and career coach.

Write a personalized cold email to a recruiter for a job opportunity.
The goal is to start a conversation and get a response — NOT to beg for a job.

INPUTS:
Candidate: {candidate_name} — CS student at BITS Pilani, graduating July 2026.
Context summary: {context_summary}
Recruiter: {recruiter_name}
Company: {company}
Role: {job_title}

RULES:
- Keep the email between 120-180 words.
- Be concise and professional. Never sound desperate.
- Never use "I am writing to express my interest".
- Never repeat the entire resume. Focus only on 2-3 most relevant experiences.
- Mention specific technologies that overlap with the role.
- Demonstrate understanding of what the company is building.
- Show why the candidate is a strong fit.
- End with a low-friction CTA.
- Avoid: passionate, hardworking, team player, fast learner, eager, excited, thrilled.
- Use evidence instead of claims.
- Personalize the opening based on the context summary's company_signal.
- If no recruiter info, use a role-focused opening.

EMAIL STRUCTURE:
Paragraph 1 — Opening: Personalized observation about company, team, product, or hiring need.
Paragraph 2 — Fit: Connect 1-2 specific candidate experiences directly to role requirements.
Paragraph 3 — Evidence + Interest: Mention a concrete achievement and explain why this company is interesting.
Paragraph 4 — CTA: Low-friction ask (brief call, consideration, reply).

TONE: Confident. Technical. Direct. Human. No corporate fluff.

OUTPUT: Return valid JSON with these keys:
{{
  "subject": "<best subject line, 4-8 words, includes role title, no clickbait>",
  "body": "<the email body, 120-180 words, plain text, 4 paragraphs separated by blank lines>"
}}

Return ONLY the JSON."""


SUBJECT_LINE_PROMPT = """Generate 5 subject line options for a cold outreach email.

Role: {job_title}
Company: {company}
Candidate angle: {best_angle}

Rules:
- 4-8 words each
- No clickbait
- Include role name when possible
- Prioritize credibility over cleverness

Return valid JSON:
{{
  "subjects": ["<option 1>", "<option 2>", "<option 3>", "<option 4>", "<option 5>"]
}}"""


REFERRAL_PROMPT = """You are an experienced engineer helping a junior reach out to another engineer.

Write a short email to an engineer (NOT a recruiter) at {company}.
The goal is to ask for advice or a technical perspective — NOT a job referral.

INPUTS:
Candidate: {candidate_name} — CS at BITS Pilani, graduating July 2026.
Candidate context: {context_summary}
Engineer: {recipient_name}
Company: {company}
Role interested in: {job_title}

RULES:
- Keep under 120 words.
- Mention 1-2 common technical interests based on the context.
- Ask ONE specific question about the team/tech/product.
- Never directly ask "Can you refer me?".
- Never ask for a job.
- Be genuine — engineers respect directness.

OUTPUT: Return valid JSON:
{{
  "subject": "<short subject, under 6 words>",
  "body": "<the referral email, under 120 words, plain text>"
}}"""


async def build_context_block(
    job_title: str,
    company: str,
    job_description: str,
    base_resume: dict,
) -> dict:
    """Step 1: Generate structured context analysis before writing the email."""
    llm = get_llm()

    profile = (
        f"CS student at BITS Pilani, graduating July 2026. "
        f"Key projects: ChaosOps AI (multi-agent RL systems), StrategyVault (AI trading platform), "
        f"AcordLayer (self-hosted collaboration platform). "
        f"Internship: BLive — built production Flutter apps, real-time IoT telematics, "
        f"RBAC with NestJS+PostgreSQL across Zomato/TVS/Ather/Bounce fleet."
    )

    prompt = CONTEXT_BLOCK_PROMPT.format(
        candidate_profile=profile,
        resume_json=json.dumps(base_resume, indent=2),
        job_title=job_title,
        company=company,
        job_description=job_description[:3000],
    )

    response = await llm.generate(
        system_prompt="You are a technical recruiter. Return ONLY valid JSON.",
        user_prompt=prompt,
        max_tokens=800,
        temperature=0.3,
    )

    result = extract_json(response)
    if result is None:
        return {
            "role_match_score": 70,
            "matching_skills": ["Python", "TypeScript", "FastAPI"],
            "missing_skills": [],
            "strongest_resume_points": ["Production multi-agent systems", "Full-stack development at scale"],
            "company_signal": f"{company} is hiring for a technical role",
            "best_angle": "Production engineering experience with modern AI/agentic systems",
        }
    return result


async def generate_outreach_email(
    job_title: str,
    company: str,
    job_description: str,
    tailored_resume: dict,
    recipient_name: str = "",
    recipient_role: str = "Hiring Team",
    is_engineer: bool = False,
) -> dict:
    """Generate a personalized outreach email following the user's prompt structure."""
    llm = get_llm()

    context = await build_context_block(job_title, company, job_description, tailored_resume)
    context_summary = json.dumps(context, indent=2)

    if is_engineer and recipient_name:
        prompt = REFERRAL_PROMPT.format(
            candidate_name=settings.sender_name,
            context_summary=context_summary,
            recipient_name=recipient_name,
            company=company,
            job_title=job_title,
        )
    else:
        prompt = EMAIL_PROMPT.format(
            candidate_name=settings.sender_name,
            context_summary=context_summary,
            recipient_name=recipient_name or "Hiring Team",
            company=company,
            job_title=job_title,
        )

    response = await llm.generate(
        system_prompt="You are an experienced technical recruiter writing a cold outreach email. Return ONLY valid JSON.",
        user_prompt=prompt,
        max_tokens=600 if is_engineer else 800,
        temperature=0.5,
    )

    result = extract_json(response)
    if result is None:
        text = response.strip()
        result = {
            "subject": f"{job_title} — Vatsal Omar",
            "body": text,
        }

    body = result.get("body", "")
    if len(body.split()) < 60:
        body += "\n\nMy tailored resume is attached with further details."
    result["body"] = body

    return result


async def generate_subject_lines(
    job_title: str,
    company: str,
    context: dict,
) -> list[str]:
    """Generate 5 subject line options."""
    llm = get_llm()

    prompt = SUBJECT_LINE_PROMPT.format(
        job_title=job_title,
        company=company,
        best_angle=context.get("best_angle", ""),
    )

    response = await llm.generate(
        system_prompt="You are an email copywriter. Return ONLY valid JSON.",
        user_prompt=prompt,
        max_tokens=200,
        temperature=0.7,
    )

    result = extract_json(response)
    if result and "subjects" in result:
        return result["subjects"]
    return [f"{job_title} Application", f"Interested in {job_title}", f"Regarding {job_title} at {company}"]
