import subprocess
import shutil
import os
from pathlib import Path
from typing import Optional
from tempfile import mkdtemp

import httpx

from config import settings

CLOUD_LATEX_URL = "https://latex.ytotech.com/builds/sync"


def build_latex(resume: dict) -> str:
    basics = resume.get("basics", {})
    selected_projects = resume.get("projects", [])[:3]
    selected_achievements = resume.get("achievements", [])
    selected_skills = resume.get("skills", {})

    name = basics.get("name", "Vatsal Omar")
    phone = basics.get("phone", "+91 9696139141")
    email = basics.get("email", "vatsalomar1@gmail.com")
    linkedin_url = "https://linkedin.com/in/vatsalomar"
    linkedin_handle = "linkedin.com/in/vatsalomar"
    github_url = "https://github.com/vatsalllll"
    github_handle = "github.com/vatsalllll"
    leetcode_url = "https://leetcode.com/vatsalomar"

    for p in basics.get("profiles", []):
        net = p.get("network", "").lower()
        url = p.get("url", "")
        if "linkedin" in net:
            linkedin_url = url
            linkedin_handle = url.replace("https://", "")
        elif "github" in net:
            github_url = url
            github_handle = url.replace("https://", "")

    proj_latex = _build_projects(selected_projects)
    exp_bullets = _build_experience(resume.get("work", []))
    ach_latex = _build_achievements(selected_achievements)
    skills_latex = _build_skills(selected_skills)

    tex = r"""\documentclass[letterpaper,11pt]{article}

\usepackage{latexsym}
\usepackage[empty]{fullpage}
\usepackage{titlesec}
\usepackage{marvosym}
\usepackage[usenames,dvipsnames]{color}
\usepackage{verbatim}
\usepackage{enumitem}
\usepackage[hidelinks]{hyperref}
\usepackage{fancyhdr}
\usepackage[english]{babel}
\usepackage{tabularx}
\usepackage{xcolor}
\input{glyphtounicode}

\definecolor{linkblue}{RGB}{26, 115, 232}

\pagestyle{fancy}
\fancyhf{}
\fancyfoot{}
\renewcommand{\headrulewidth}{0pt}
\renewcommand{\footrulewidth}{0pt}

\addtolength{\oddsidemargin}{-0.65in}
\addtolength{\evensidemargin}{-0.65in}
\addtolength{\textwidth}{1.3in}
\addtolength{\topmargin}{-0.75in}
\addtolength{\textheight}{1.5in}

\urlstyle{same}
\raggedbottom
\raggedright
\setlength{\tabcolsep}{0in}

\hypersetup{colorlinks=true, urlcolor=linkblue, linkcolor=linkblue}
\titleformat{\section}{\vspace{-4pt}\scshape\raggedright\large}{}{0em}{}[\color{black}\titlerule \vspace{-5pt}]
\pdfgentounicode=1

\newcommand{\resumeItem}[1]{\item\small{#1 \vspace{-2pt}}}
\newcommand{\resumeSubItem}[1]{\resumeItem{#1}\vspace{-4pt}}
\renewcommand\labelitemii{$\vcenter{\hbox{\tiny$\bullet$}}$}

\newcommand{\resumeSubheading}[4]{
  \vspace{-2pt}\item
    \begin{tabular*}{0.97\textwidth}[t]{l@{\extracolsep{\fill}}r}
      \textbf{#1} & #2 \\
      \textit{\small#3} & \textit{\small #4} \\
    \end{tabular*}\vspace{-7pt}
}

\newcommand{\resumeProjectHeading}[2]{
    \item
    \begin{tabular*}{0.97\textwidth}{l@{\extracolsep{\fill}}r}
      \small\textbf{#1} & \small #2 \\
    \end{tabular*}\vspace{-4pt}
}

\newcommand{\resumeSubHeadingListStart}{\begin{itemize}[leftmargin=0.15in, label={}]}
\newcommand{\resumeSubHeadingListEnd}{\end{itemize}}
\newcommand{\resumeItemListStart}{\begin{itemize}[itemsep=1pt, topsep=3pt]}
\newcommand{\resumeItemListEnd}{\end{itemize}\vspace{-3pt}}
\newcommand{\clink}[2]{\href{#1}{\textcolor{linkblue}{\underline{#2}}}}

\begin{document}

\begin{center}
    \textbf{\Huge \scshape """ + _escape_latex(name) + r"""} \\ \vspace{2pt}
    \small """ + _escape_latex(phone) + r""" $|$
    \clink{mailto:""" + email + r"""}{""" + email + r"""} $|$
    \clink{""" + linkedin_url + r"""}{""" + linkedin_handle + r"""} $|$
    \clink{""" + github_url + r"""}{""" + github_handle + r"""} $|$
    \clink{""" + leetcode_url + r"""}{LeetCode}
\end{center}

\section{Education}
  \resumeSubHeadingListStart
    \resumeSubheading
      {Birla Institute of Technology and Science (BITS), Pilani}{Pilani, IN}
      {Bachelor of Science in Computer Science}{Aug 2023 -- July 2026}
  \resumeSubHeadingListEnd

\section{Experience}
  \resumeSubHeadingListStart
    \resumeSubheading
      {BLive}{Bangalore, IN}
      {Software Development Intern}{Dec 2024 -- Sept 2025}
      \resumeItemListStart
""" + exp_bullets + r"""
      \resumeItemListEnd
  \resumeSubHeadingListEnd

\section{Projects}
  \resumeSubHeadingListStart
""" + proj_latex + r"""
  \resumeSubHeadingListEnd

\section{Achievements}
  \resumeSubHeadingListStart
""" + ach_latex + r"""
  \resumeSubHeadingListEnd

\section{Technical Skills}
 \begin{itemize}[leftmargin=0.15in, label={}]
    \small{\item{
""" + skills_latex + r"""
    }}
 \end{itemize}

\end{document}
"""
    return tex


def _build_experience(work: list) -> str:
    lines = []
    for job in work[:1]:
        for h in job.get("highlights", [])[:5]:
            lines.append(f"        \\resumeItem{{{_escape_latex(h)}}}")
    return "\n".join(lines)


def _build_projects(projects: list) -> str:
    parts = []
    for i, proj in enumerate(projects):
        if i > 0:
            parts.append("    \\vspace{1pt}")
        name = _escape_latex(proj.get("name", "Project"))
        live = proj.get("url", "#")
        github = proj.get("url", "#")
        tech = proj.get("tech", [])
        tech_str = " $|$ ".join(f"\\textbf{{{t}}}" for t in tech[:6])

        parts.append("    \\resumeProjectHeading")
        parts.append(f"      {{{name}}}{{\\clink{{{live}}}{{Live}} $|$ \\clink{{{github}}}{{GitHub}}}}")
        parts.append("      \\resumeItemListStart")
        parts.append(f"        \\resumeItem{{\\textit{{Tech Stack:}} {tech_str}}}")

        for h in proj.get("highlights", [])[:3]:
            parts.append(f"        \\resumeItem{{{_escape_latex(h)}}}")

        parts.append("      \\resumeItemListEnd")

    return "\n".join(parts)


def _build_achievements(achievements: list) -> str:
    lines = []
    for a in achievements[:3]:
        title = _escape_latex(a.get("title", ""))
        desc = _escape_latex(a.get("description", ""))
        if "scaler" in title.lower() or "scaler" in desc.lower():
            continue
        lines.append(f"    \\resumeSubItem{{\\textbf{{{title}}}: {desc}}}")
    return "\n".join(lines)


def _build_skills(skills: dict) -> str:
    lines = []
    for category, skill_list in skills.items():
        if isinstance(skill_list, list) and skill_list:
            cat_label = category.replace("_", " ").title()
            items = ", ".join(skill_list)
            lines.append(f"     \\textbf{{{_escape_latex(cat_label)}}}{{: {_escape_latex(items)}}}")
    return " \\\\\n".join(lines)


def _escape_latex(text: str) -> str:
    if not text:
        return ""
    text = str(text)
    for char in ["%", "$", "#", "&", "_"]:
        text = text.replace(char, "\\" + char)
    text = text.replace("~", "\\textasciitilde{}")
    text = text.replace("^", "\\textasciicircum{}")
    text = text.replace("\u2014", "---")
    text = text.replace("\u2013", "--")
    text = text.replace("\u2018", "'")
    text = text.replace("\u2019", "'")
    text = text.replace("\u201c", "``")
    text = text.replace("\u201d", "''")
    return text


def _compile_local(tex_content: str, tmpdir: Path) -> Optional[Path]:
    tex_file = tmpdir / "resume.tex"
    tex_file.write_text(tex_content)

    pdflatex = shutil.which("pdflatex")
    if pdflatex:
        try:
            subprocess.run(
                [pdflatex, "-interaction=nonstopmode", "-output-directory", str(tmpdir), str(tex_file)],
                capture_output=True, timeout=30, cwd=str(tmpdir),
            )
            pdf = tmpdir / "resume.pdf"
            if pdf.exists() and pdf.stat().st_size > 1000:
                return pdf
        except Exception:
            pass
    return None


def _compile_docker(tex_content: str, tmpdir: Path) -> Optional[Path]:
    tex_file = tmpdir / "resume.tex"
    tex_file.write_text(tex_content)

    docker = shutil.which("docker")
    if docker:
        try:
            subprocess.run(
                [docker, "run", "--rm", "-v", f"{tmpdir}:/data",
                 "texlive/texlive:latest", "pdflatex",
                 "-interaction=nonstopmode", "-output-directory=/data", "/data/resume.tex"],
                capture_output=True, timeout=60,
            )
            pdf = tmpdir / "resume.pdf"
            if pdf.exists() and pdf.stat().st_size > 1000:
                return pdf
        except Exception:
            pass
    return None


def _compile_cloud(tex_content: str, tmpdir: Path) -> Optional[Path]:
    try:
        resp = httpx.post(
            CLOUD_LATEX_URL,
            json={
                "compiler": "pdflatex",
                "resources": [{"main": True, "content": tex_content}],
            },
            timeout=60.0,
        )
        if resp.status_code in (200, 201):
            pdf = tmpdir / "resume.pdf"
            pdf.write_bytes(resp.content)
            if pdf.stat().st_size > 1000:
                return pdf
    except Exception:
        pass
    return None


def compile_latex(tex_content: str, output_path: Optional[str] = None) -> str:
    if output_path is None:
        output_path = str(Path(settings.output_dir) / "resume.pdf")

    tmpdir = Path(mkdtemp())
    pdf = None

    pdf = _compile_local(tex_content, tmpdir)
    if pdf is None:
        pdf = _compile_docker(tex_content, tmpdir)
    if pdf is None:
        pdf = _compile_cloud(tex_content, tmpdir)

    if pdf:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(pdf, output_path)
        shutil.rmtree(tmpdir, ignore_errors=True)
        return output_path

    shutil.rmtree(tmpdir, ignore_errors=True)
    return ""


def render_latex_pdf(resume: dict, output_path: Optional[str] = None) -> str:
    tex = build_latex(resume)

    if output_path is None:
        company = resume.get("metadata", {}).get("company", "unknown")
        role = resume.get("metadata", {}).get("role", "resume")
        safe_name = f"{company}_{role}".lower().replace(" ", "_")[:60]
        output_path = str(Path(settings.output_dir) / f"{safe_name}.pdf")

    result = compile_latex(tex, output_path)

    if not result or not Path(result).exists():
        from tailor.pdf_render import _render_pdf_fpdf2
        result = _render_pdf_fpdf2(resume, output_path)

    return result
