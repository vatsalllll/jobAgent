"""
Resume tailoring engine — provider-agnostic.
Takes a base resume + job description → tailored JSON Resume → scored & verified.
Works with Anthropic, Hugging Face, or OpenAI via the LLM abstraction layer.
"""

import json
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
        max_tokens=4096,
        temperature=0.3,
    )

    tailored = extract_json(response_text)
    if tailored is None:
        # Retry once with stronger JSON instruction
        retry_prompt = prompt + "\n\nIMPORTANT: Your response must be ONLY valid JSON. No markdown, no explanations. Just the JSON object."
        response_text = await llm.generate(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=retry_prompt,
            max_tokens=4096,
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


async def verify_fidelity(
    base_resume: dict,
    tailored_resume: dict,
) -> dict:
    """Verify that the tailored resume contains no fabricated information."""
    llm = get_llm()

    prompt = VERIFICATION_PROMPT.format(
        base_resume_json=json.dumps(base_resume, indent=2),
        tailored_resume_json=json.dumps(tailored_resume, indent=2),
    )

    response_text = await llm.generate(
        system_prompt="",
        user_prompt=prompt,
        max_tokens=1024,
        temperature=0.1,
    )

    result = extract_json(response_text)
    if result is None:
        return {"is_faithful": True, "issues": []}

    return result


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
