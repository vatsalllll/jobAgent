"""
Outreach email generator — provider-agnostic.
Generates personalized cold outreach emails using the configured LLM.
"""

import json

from config import settings
from tailor.llm import get_llm, extract_json


OUTREACH_SYSTEM_PROMPT = """You are an expert at writing personalized, professional cold outreach emails
that actually get responses from startup founders and hiring managers.

Your emails succeed because they are:
1. Specific — you reference the recipient's company, product, or mission (not generic praise)
2. Substantive — you explain WHY you are interested in this specific company
3. Value-forward — you tell them what you can contribute, not just ask for a job
4. Concise — 4 short paragraphs max. Nobody reads long cold emails.
5. Confident but not arrogant — professional, warm, direct
6. Action-oriented — clear next step with low friction (15-min call, reply, etc.)

Rules:
- Subject line: include the role title, keep it under 60 chars
- Never use templates like "I hope this email finds you well"
- Never use buzzwords: "passionate", "rockstar", "ninja", "synergy", "eager"
- Never beg or sound desperate
- Always mention that the resume is attached
- Always include 1-2 specific projects/achievements that directly match the role
- Close with a clear, low-friction ask (e.g., "Would you be open to a 15-minute chat next week?")
- Write at a 9th-grade reading level — short sentences, active verbs"""


OUTREACH_PROMPT = """[CANDIDATE]
Name: {candidate_name}
Background: Computer Science student at BITS Pilani, graduating July 2026
Key strengths: Multi-agent AI systems, LLM orchestration, full-stack product engineering

Notable projects:
{portfolio_summary}

[RECIPIENT]
Name: {recipient_name}
Role at company: {recipient_role}
Company: {company}

[THE ROLE]
Title: {job_title}
Company: {company}
Why the candidate fits: {fit_rationale}

[GOAL]
Write a 4-paragraph personalized cold outreach email that:
1. Opens with a specific, genuine observation about {company} — what they do, what mission they serve, or why they caught your attention
2. Explains WHY you are specifically interested in this role (not just any job)
3. Describes what you can BRING to the team — 1-2 concrete projects or skills directly relevant to {company}'s work
4. Closes with a low-friction ask and explicitly mentions the attached resume

[FORMAT]
Return valid JSON:
{{
  "subject": "<subject line, under 60 chars, includes role title>",
  "body": "<email body, 4 paragraphs, plain text, ~150-200 words>"
}}

Return ONLY the JSON, no preamble."""


async def generate_outreach_email(
    job_title: str,
    company: str,
    job_description: str,
    tailored_resume: dict,
    recipient_name: str = "",
    recipient_role: str = "Hiring Manager",
) -> dict:
    """Generate a personalized outreach email for a job application."""
    llm = get_llm()

    # Build portfolio summary
    portfolio_parts = []
    for proj in tailored_resume.get("projects", [])[:2]:
        portfolio_parts.append(f"- {proj.get('name', '')}: {proj.get('description', '')[:100]}")
    portfolio_summary = "\n".join(portfolio_parts) or "Multi-agent AI systems, full-stack development, real-time IoT data pipelines"

    # Build fit rationale
    resume_text = json.dumps(tailored_resume).lower()
    jd_lower = job_description.lower()
    matching_keywords = []
    tech_keywords = [
        "python", "typescript", "go", "react", "fastapi", "postgresql", "docker",
        "ai", "machine learning", "llm", "agent", "rag", "nlp", "backend",
        "full-stack", "api", "cloud", "gcp", "aws", "iot", "websockets",
        "redis", "nestjs", "next.js", "flutter", "reinforcement learning"
    ]
    for kw in tech_keywords:
        if kw in jd_lower and kw in resume_text:
            matching_keywords.append(kw)

    fit_rationale = (
        f"Strong alignment on: {', '.join(matching_keywords[:5])}"
        if matching_keywords
        else "Strong technical alignment with the role requirements"
    )

    prompt = OUTREACH_PROMPT.format(
        candidate_name=settings.sender_name,
        portfolio_summary=portfolio_summary,
        recipient_name=recipient_name or "Hiring Team",
        recipient_role=recipient_role,
        company=company,
        job_title=job_title,
        fit_rationale=fit_rationale,
    )

    response_text = await llm.generate(
        system_prompt=OUTREACH_SYSTEM_PROMPT,
        user_prompt=prompt,
        max_tokens=1500,
        temperature=0.5,
    )

    result = extract_json(response_text)
    if result is None:
        result = {
            "subject": f"Application: {job_title} at {company}",
            "body": response_text.strip()[:1000],
        }

    if result.get("body") and "resume" not in result["body"].lower() and "attached" not in result["body"].lower():
        result["body"] = result["body"].rstrip() + "\n\nMy tailored resume is attached for your review."

    return result
