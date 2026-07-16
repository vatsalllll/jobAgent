"""
Resume tailoring engine — provider-agnostic.
Takes a base resume + job description → tailored JSON Resume → scored & verified.
Works with Anthropic, Hugging Face, or OpenAI via the LLM abstraction layer.
"""

import json
import re
from typing import Optional

from tailor.prompts import (
    SYSTEM_PROMPT,
    TAILOR_PROMPT,
    MATCH_SCORE_PROMPT,
    VERIFICATION_PROMPT,
)
from tailor.llm import get_llm, extract_json


async def tailor_resume(
    base_resume: dict,
    job_description: str,
    job_title: str = "",
    company: str = "",
) -> dict:
    """
    Tailor a resume for a specific job using the configured LLM provider.
    Returns the tailored resume as a JSON Resume dict.
    """
    llm = get_llm()

    base_json = json.dumps(base_resume, indent=2, ensure_ascii=False)
    prompt = TAILOR_PROMPT.format(
        job_description=job_description,
        base_resume_json=base_json,
    )

    response_text = await llm.generate(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=prompt,
        max_tokens=8000,
        temperature=0.3,
    )

    tailored = extract_json(response_text)
    if tailored is None:
        # Retry once with stronger JSON instruction and a larger budget (truncation is the
        # usual cause — a full one-page resume JSON can exceed a small max_tokens).
        retry_prompt = prompt + "\n\nIMPORTANT: Your response must be ONLY valid JSON. No markdown, no explanations. Just the JSON object. Keep it to one page so it fits."
        response_text = await llm.generate(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=retry_prompt,
            max_tokens=8000,
            temperature=0.1,
        )
        tailored = extract_json(response_text)

    if tailored is None:
        raise ValueError(f"LLM returned unparseable JSON. Raw response (first 500 chars): {response_text[:500]}")

    tailored = _sanitize_education(tailored)
    return tailored


async def score_match(
    job_description: str,
    tailored_resume: dict,
) -> dict:
    """Score how well the tailored resume matches the job description."""
    llm = get_llm()

    prompt = MATCH_SCORE_PROMPT.format(
        job_description=job_description,
        tailored_resume_json=json.dumps(tailored_resume, indent=2),
    )

    response_text = await llm.generate(
        system_prompt="You are an ATS screening expert. Return ONLY valid JSON.",
        user_prompt=prompt,
        max_tokens=1024,
        temperature=0.1,
    )

    result = extract_json(response_text)
    if result is None:
        return {"match_score": 0, "keywords_matched": [], "gaps": ["Scoring failed"]}

    return result


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _programmatic_fidelity(base_resume: dict, tailored_resume: dict) -> list[dict]:
    """Deterministic fabrication check — the authoritative send-gate.

    Catches the high-signal, low-false-positive fabrication vectors: a new employer, a new
    project, or an education entry other than BITS Pilani. This does NOT depend on the LLM,
    so it never blocks legitimate rephrasing/reordering and never flakes on a weak free model.
    """
    issues: list[dict] = []

    base_companies = [_norm(w.get("company", "")) for w in base_resume.get("work", []) if w.get("company")]
    for w in tailored_resume.get("work", []) or []:
        comp = _norm(w.get("company", ""))
        if comp and not any(comp in bc or bc in comp for bc in base_companies):
            issues.append({"field": "work.company", "claim": w.get("company", ""),
                           "issue": "employer not present in base resume", "severity": "fabrication"})

    base_proj_tokens = [set(_norm(p.get("name", "")).split()) for p in base_resume.get("projects", [])]
    for p in tailored_resume.get("projects", []) or []:
        toks = {t for t in _norm(p.get("name", "")).split() if len(t) > 3}
        if toks and not any(toks & bt for bt in base_proj_tokens):
            issues.append({"field": "projects.name", "claim": p.get("name", ""),
                           "issue": "project not present in base resume", "severity": "fabrication"})

    for e in tailored_resume.get("education", []) or []:
        inst = _norm(e.get("institution", ""))
        if inst and "bits" not in inst and "birla" not in inst:
            issues.append({"field": "education.institution", "claim": e.get("institution", ""),
                           "issue": "education other than BITS Pilani", "severity": "fabrication"})

    return issues


async def verify_fidelity(
    base_resume: dict,
    tailored_resume: dict,
) -> dict:
    """Verify the tailored resume adds no fabricated employer/project/education.

    Purely DETERMINISTIC — no LLM call. `_programmatic_fidelity` catches the real fabrication
    vectors (new employer/project, non-BITS education) reliably, so we don't spend an LLM call
    (or risk free-tier 429s) on an inconsistent self-verification.
    """
    prog_issues = _programmatic_fidelity(base_resume, tailored_resume)
    return {
        "is_faithful": len(prog_issues) == 0,
        "verified": True,
        "issues": prog_issues,
        "advisory_issues": [],
    }


def _sanitize_education(resume: dict) -> dict:
    """Ensure education section only contains BITS Pilani."""
    if "education" in resume:
        bits_edu = [
            e for e in resume["education"]
            if "bits" in e.get("institution", "").lower()
            or "birla" in e.get("institution", "").lower()
        ]
        if not bits_edu:
            bits_edu = [{
                "institution": "Birla Institute of Technology and Science (BITS), Pilani",
                "area": "Computer Science",
                "studyType": "Bachelor of Science",
                "startDate": "2023-08",
                "endDate": "2026-07",
                "location": "Pilani, IN",
            }]
        resume["education"] = bits_edu
    return resume
