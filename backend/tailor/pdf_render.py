"""
HTML Resume Renderer + PDF Export using Playwright.
Renders a JSON Resume to clean, ATS-friendly HTML, then exports to PDF.
"""

import json
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from config import settings

# Set up Jinja2 environment
_templates_dir = Path(__file__).parent / "templates"
_templates_dir.mkdir(exist_ok=True)
_jinja_env = Environment(
    loader=FileSystemLoader(str(_templates_dir)),
    autoescape=select_autoescape(["html", "xml"]),
)


def render_html(resume: dict) -> str:
    """Render a JSON Resume to ATS-friendly HTML."""
    template = _jinja_env.get_template("resume.html.j2")
    return template.render(resume=resume)


async def render_pdf(resume: dict, output_path: Optional[str] = None) -> str:
    """
    Render resume to PDF using Playwright (headless Chromium).

    Returns the path to the generated PDF.
    """
    from playwright.async_api import async_playwright

    html = render_html(resume)

    if output_path is None:
        company = resume.get("metadata", {}).get("company", "unknown")
        role = resume.get("metadata", {}).get("role", "resume")
        safe_name = f"{company}_{role}".lower().replace(" ", "_")[:60]
        output_path = str(Path(settings.output_dir) / f"{safe_name}.pdf")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html, wait_until="networkidle")
        await page.pdf(
            path=output_path,
            format="A4",
            margin={"top": "0.4in", "bottom": "0.4in", "left": "0.5in", "right": "0.5in"},
            print_background=True,
        )
        await browser.close()

    return output_path


# ── Inline HTML Template (embedded — no file dependency) ──

RESUME_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ resume.basics.name }} — Resume</title>
<style>
  @page {
    size: A4;
    margin: 0.4in 0.5in;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    font-size: 10pt;
    line-height: 1.4;
    color: #1a1a1a;
    max-width: 210mm;
    margin: 0 auto;
    padding: 0.4in 0.5in;
  }
  h1 { font-size: 18pt; font-weight: 700; margin-bottom: 2px; }
  h2 { font-size: 12pt; font-weight: 600; color: #333; border-bottom: 1.5px solid #2563eb; padding-bottom: 2px; margin-top: 14px; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px; }
  h3 { font-size: 10.5pt; font-weight: 600; margin-bottom: 1px; }
  a { color: #2563eb; text-decoration: none; }
  p { margin-bottom: 3px; }
  .header { text-align: center; margin-bottom: 10px; }
  .header .subtitle { font-size: 9.5pt; color: #555; }
  .contact { font-size: 9pt; color: #666; margin-top: 2px; }
  .contact span { margin: 0 6px; }
  .summary { font-size: 9.5pt; font-style: italic; color: #444; margin-bottom: 8px; line-height: 1.35; }
  .section { margin-bottom: 8px; }
  .entry { margin-bottom: 7px; }
  .entry-header { display: flex; justify-content: space-between; align-items: baseline; }
  .entry-title { font-weight: 600; }
  .entry-subtitle { font-size: 9pt; color: #555; }
  .entry-date { font-size: 8.5pt; color: #888; white-space: nowrap; }
  ul { padding-left: 16px; margin-top: 2px; }
  li { font-size: 9.5pt; margin-bottom: 2px; line-height: 1.35; }
  .skills-grid { display: flex; flex-wrap: wrap; gap: 3px 8px; }
  .skill-tag { font-size: 9pt; color: #333; }
  .skill-tag::after { content: " ·"; color: #ccc; }
  .skill-tag:last-child::after { content: ""; }
  .tech-stack { font-size: 8.5pt; color: #666; font-style: italic; }
  .achievement { margin-bottom: 3px; font-size: 9pt; }
  .achievement strong { font-weight: 600; }
</style>
</head>
<body>

<!-- HEADER -->
<div class="header">
  <h1>{{ resume.basics.name }}</h1>
  <div class="subtitle">{{ resume.basics.label }}</div>
  <div class="contact">
    <span>{{ resume.basics.email }}</span> |
    <span>{{ resume.basics.phone }}</span> |
    {% for p in resume.basics.profiles %}
    <span><a href="{{ p.url }}">{{ p.network }}</a></span>{% if not loop.last %} | {% endif %}
    {% endfor %}
  </div>
</div>

<!-- SUMMARY -->
{% if resume.basics.summary %}
<div class="summary">{{ resume.basics.summary }}</div>
{% endif %}

<!-- EDUCATION -->
<h2>Education</h2>
<div class="section">
{% for edu in resume.education %}
<div class="entry">
  <div class="entry-header">
    <span class="entry-title">{{ edu.institution }}</span>
    <span class="entry-date">{{ edu.startDate }} – {{ edu.endDate }}</span>
  </div>
  <div class="entry-subtitle">{{ edu.studyType }} in {{ edu.area }}{% if edu.location %} — {{ edu.location }}{% endif %}</div>
</div>
{% endfor %}
</div>

<!-- EXPERIENCE -->
{% if resume.work %}
<h2>Experience</h2>
<div class="section">
{% for job in resume.work %}
<div class="entry">
  <div class="entry-header">
    <span class="entry-title">{{ job.position }}</span>
    <span class="entry-date">{{ job.startDate }} – {{ job.endDate }}</span>
  </div>
  <div class="entry-subtitle">{{ job.company }}{% if job.location %} — {{ job.location }}{% endif %}</div>
  <ul>
  {% for highlight in job.highlights %}
    <li>{{ highlight }}</li>
  {% endfor %}
  </ul>
</div>
{% endfor %}
</div>
{% endif %}

<!-- PROJECTS -->
{% if resume.projects %}
<h2>Projects</h2>
<div class="section">
{% for proj in resume.projects %}
<div class="entry">
  <div class="entry-header">
    <span class="entry-title">
      {% if proj.url %}<a href="{{ proj.url }}">{{ proj.name }}</a>{% else %}{{ proj.name }}{% endif %}
    </span>
  </div>
  {% if proj.tech %}<div class="tech-stack">{{ proj.tech | join(" · ") }}</div>{% endif %}
  {% if proj.description %}<p style="font-size:9pt; margin-top:1px;">{{ proj.description }}</p>{% endif %}
  {% if proj.highlights %}
  <ul>
  {% for h in proj.highlights %}
    <li>{{ h }}</li>
  {% endfor %}
  </ul>
  {% endif %}
</div>
{% endfor %}
</div>
{% endif %}

<!-- ACHIEVEMENTS -->
{% if resume.achievements %}
<h2>Achievements</h2>
<div class="section">
{% for ach in resume.achievements %}
<div class="achievement">
  <strong>{{ ach.title }}</strong> — {{ ach.description }}
</div>
{% endfor %}
</div>
{% endif %}

<!-- SKILLS -->
{% if resume.skills %}
<h2>Technical Skills</h2>
<div class="section">
{% for category, skills in resume.skills.items() %}
  {% if skills is iterable and skills is not string %}
  <div style="margin-bottom: 2px;">
    <strong style="font-size:9pt;">{{ category | replace('_', ' ') | title }}:</strong>
    <span class="skills-grid" style="display:inline;">
    {% for skill in skills %}
      <span class="skill-tag">{{ skill }}</span>
    {% endfor %}
    </span>
  </div>
  {% endif %}
{% endfor %}
</div>
{% endif %}

</body>
</html>"""


def render_html_inline(resume: dict) -> str:
    """Render resume using inline template (no file dependency)."""
    env = Environment(autoescape=True)
    template = env.from_string(RESUME_HTML_TEMPLATE)
    return template.render(resume=resume)


async def render_pdf_inline(resume: dict, output_path: Optional[str] = None) -> str:
    company = resume.get("metadata", {}).get("company", "unknown")
    role = resume.get("metadata", {}).get("role", "resume")
    if output_path is None:
        safe_name = f"{company}_{role}".lower().replace(" ", "_")[:60]
        output_path = str(Path(settings.output_dir) / f"{safe_name}.pdf")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.async_api import async_playwright
        html = render_html_inline(resume)
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.set_content(html, wait_until="networkidle")
            await page.pdf(
                path=output_path,
                format="A4",
                margin={"top": "0.4in", "bottom": "0.4in", "left": "0.5in", "right": "0.5in"},
                print_background=True,
            )
            await browser.close()
        return output_path
    except ImportError:
        return _render_pdf_fpdf2(resume, output_path)
    except Exception:
        return _render_pdf_fpdf2(resume, output_path)


def _render_pdf_fpdf2(resume: dict, output_path: str) -> str:
    """Generate a clean PDF using fpdf2 — no browser required. Works on Render."""
    try:
        from fpdf import FPDF
    except ImportError:
        return ""

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    accent = (37, 99, 235)
    text_dark = (26, 26, 26)
    text_muted = (102, 102, 102)

    basics = resume.get("basics", {})
    name = basics.get("name", "Resume")
    label = basics.get("label", "")
    email = basics.get("email", "")
    phone = basics.get("phone", "")
    url = basics.get("url", "")
    summary = basics.get("summary", "")
    location = basics.get("location", {})
    loc_str = ", ".join(filter(None, [location.get("city", ""), location.get("region", ""), location.get("countryCode", "")]))
    profiles = basics.get("profiles", [])

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*text_dark)
    pdf.cell(0, 10, name, ln=True)

    if label:
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*text_muted)
        pdf.cell(0, 5, label, ln=True)

    contact_parts = [p for p in [email, phone, loc_str] if p]
    if contact_parts:
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*text_muted)
        pdf.cell(0, 5, "  |  ".join(contact_parts), ln=True)

    profile_strs = [f"{p.get('network', '')}: {p.get('url', '')}" for p in profiles if p.get("url")]
    if profile_strs:
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(accent[0], accent[1], accent[2])
        for ps in profile_strs[:3]:
            pdf.cell(0, 4, ps, ln=True)

    if summary:
        pdf.ln(2)
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(*text_muted)
        pdf.multi_cell(0, 4, summary)

    def section_header(title: str) -> None:
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(*accent)
        pdf.cell(0, 6, title.upper(), ln=True)
        pdf.set_draw_color(*accent)
        pdf.set_line_width(0.5)
        y = pdf.get_y()
        pdf.line(10, y, 200, y)
        pdf.ln(2)
        pdf.set_text_color(*text_dark)

    education = resume.get("education", [])
    if education:
        section_header("Education")
        for edu in education:
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 5, edu.get("institution", ""), ln=True)
            dates = " - ".join(filter(None, [edu.get("startDate", ""), edu.get("endDate", "")]))
            study = f"{edu.get('studyType', '')} in {edu.get('area', '')}".strip()
            line = study + (f"  ({dates})" if dates else "")
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(*text_muted)
            pdf.cell(0, 4, line, ln=True)
            pdf.set_text_color(*text_dark)

    work = resume.get("work", [])
    if work:
        section_header("Experience")
        for job in work:
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 5, job.get("position", ""), ln=True)
            dates = " - ".join(filter(None, [job.get("startDate", ""), job.get("endDate", "")]))
            sub = f"{job.get('company', '')}" + (f"  ({dates})" if dates else "")
            pdf.set_font("Helvetica", "I", 9)
            pdf.set_text_color(*text_muted)
            pdf.cell(0, 4, sub, ln=True)
            pdf.set_text_color(*text_dark)
            for h in job.get("highlights", [])[:5]:
                pdf.set_font("Helvetica", "", 9)
                txt = h.replace("\u2014", "-").replace("\u2013", "-").encode("latin-1", "replace").decode("latin-1")
                pdf.multi_cell(0, 4, f"- {txt}")

    projects = resume.get("projects", [])
    if projects:
        section_header("Projects")
        for proj in projects[:3]:
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 5, proj.get("name", ""), ln=True)
            tech = proj.get("tech", [])
            if tech:
                pdf.set_font("Helvetica", "I", 8)
                pdf.set_text_color(*text_muted)
                pdf.cell(0, 4, "  |  ".join(tech[:6]), ln=True)
                pdf.set_text_color(*text_dark)
            for h in proj.get("highlights", [])[:3]:
                pdf.set_font("Helvetica", "", 9)
                txt = h.replace("\u2014", "-").replace("\u2013", "-").encode("latin-1", "replace").decode("latin-1")
                pdf.multi_cell(0, 4, f"- {txt}")

    achievements = resume.get("achievements", [])
    if achievements:
        section_header("Achievements")
        for a in achievements[:3]:
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(0, 5, a.get("title", ""), ln=True)
            pdf.set_font("Helvetica", "", 9)
            desc = a.get("description", "").replace("\u2014", "-").replace("\u2013", "-").encode("latin-1", "replace").decode("latin-1")
            pdf.multi_cell(0, 4, desc)

    skills = resume.get("skills", {})
    if skills:
        section_header("Technical Skills")
        pdf.set_font("Helvetica", "", 9)
        for category, skill_list in skills.items():
            if isinstance(skill_list, list) and skill_list:
                cat_label = category.replace("_", " ").title()
                pdf.set_font("Helvetica", "B", 9)
                pdf.cell(35, 4, f"{cat_label}:", ln=False)
                pdf.set_font("Helvetica", "", 9)
                pdf.multi_cell(0, 4, ", ".join(skill_list))

    try:
        pdf.output(output_path)
        return output_path
    except Exception:
        return ""
