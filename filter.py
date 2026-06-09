"""
filter.py
---------
Resume skill extraction and internship-to-resume matching engine.

Algorithm
---------
1. Extract canonical skill keys from the resume text.
2. For each internship, extract skill keys from its tags + description.
3. Compute a blended score (Jaccard overlap + recall) scaled to 0-100.
4. Return (passed, skipped) split at the configured threshold.
"""

import re
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Skill taxonomy — add more entries freely
# ---------------------------------------------------------------------------

TECH_SKILLS: dict = {
    # Frontend
    "html":         ["html", "html5"],
    "css":          ["css", "css3", "tailwind", "bootstrap", "sass", "scss"],
    "javascript":   ["javascript", "js", "es6", "es2015"],
    "typescript":   ["typescript", "ts"],
    "react":        ["react", "reactjs", "react.js", "react js"],
    "vue":          ["vue", "vuejs", "vue.js"],
    "angular":      ["angular", "angularjs"],
    "nextjs":       ["next.js", "nextjs"],
    # Backend
    "python":       ["python", "py"],
    "django":       ["django"],
    "flask":        ["flask"],
    "fastapi":      ["fastapi"],
    "node":         ["node", "node.js", "nodejs", "express", "expressjs"],
    "java":         ["java", "spring", "springboot", "spring boot"],
    "cpp":          ["c++", "cpp"],
    "csharp":       ["c#", "csharp", ".net", "dotnet"],
    "go":           ["golang", "go lang"],
    "rust":         ["rust"],
    "php":          ["php", "laravel"],
    # Data / ML
    "sql":          ["sql", "mysql", "postgresql", "postgres", "sqlite"],
    "nosql":        ["mongodb", "nosql", "dynamodb", "firebase"],
    "ml":           ["machine learning", "ml", "scikit", "sklearn"],
    "dl":           ["deep learning", "neural network", "tensorflow", "keras", "pytorch"],
    "nlp":          ["nlp", "natural language processing", "spacy", "nltk"],
    "data_analysis":["data analysis", "pandas", "numpy", "matplotlib", "seaborn"],
    "tableau":      ["tableau"],
    "powerbi":      ["power bi", "powerbi"],
    # Design
    "figma":        ["figma"],
    "photoshop":    ["photoshop"],
    "ui_ux":        ["ui/ux", "ui ux", "ux design", "user experience"],
    # DevOps / Cloud
    "git":          ["git", "github", "gitlab"],
    "docker":       ["docker"],
    "kubernetes":   ["kubernetes", "k8s"],
    "aws":          ["aws", "amazon web services", "ec2", "s3"],
    "gcp":          ["gcp", "google cloud"],
    "azure":        ["azure", "microsoft azure"],
    "linux":        ["linux", "unix", "bash", "shell"],
    # General
    "excel":        ["excel", "spreadsheet", "vba"],
    "agile":        ["agile", "scrum", "kanban"],
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ScoredInternship:
    internship: object        # Internship from scraper.py
    score: float              # 0–100
    matched_skills: list
    resume_skills: list
    reason: str
    _threshold: float = 60.0

    @property
    def passes(self) -> bool:
        return self.score >= self._threshold

    def to_dict(self) -> dict:
        return {
            **self.internship.to_dict(),
            "score": round(self.score, 2),
            "matched_skills": self.matched_skills,
            "resume_skills": self.resume_skills,
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_skills(text: str) -> set:
    """Return canonical skill keys found in *text* via word-boundary regex."""
    text_lower = text.lower().strip()
    found = set()
    for key, aliases in TECH_SKILLS.items():
        for alias in sorted(aliases, key=len, reverse=True):
            if re.search(r"\b" + re.escape(alias) + r"\b", text_lower):
                found.add(key)
                break
    return found


def _compute_score(resume_skills: set, job_skills: set, job_text: str):
    """Return (score_0_to_100, list_of_matched_skill_keys)."""
    if not resume_skills:
        return 0.0, []

    effective = job_skills if job_skills else _extract_skills(job_text)
    if not effective:
        # No discernible job skills — neutral score so we don't auto-block
        return 50.0, []

    intersection = resume_skills & effective
    union = resume_skills | effective
    jaccard = len(intersection) / len(union) if union else 0.0
    recall  = len(intersection) / len(effective)
    blended = 0.5 * jaccard + 0.5 * recall
    return round(blended * 100, 2), sorted(intersection)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_resume(resume_text: str) -> set:
    """Extract canonical skill keys from raw resume text."""
    skills = _extract_skills(resume_text)
    logger.info(f"Resume skills detected ({len(skills)}): {sorted(skills)}")
    return skills


def score_internship(internship, resume_skills: set, threshold: float = 60.0) -> ScoredInternship:
    """Score a single internship against the parsed resume skills."""
    # Canonicalise skill tags from the job listing
    canonical_job_skills = set()
    for raw in (s.lower().strip() for s in internship.skills_required):
        for key, aliases in TECH_SKILLS.items():
            if any(raw == a or a in raw for a in aliases):
                canonical_job_skills.add(key)
                break
        else:
            canonical_job_skills.add(raw)   # keep unknown skill raw

    combined_text = f"{internship.title} {internship.description}"
    score, matched = _compute_score(resume_skills, canonical_job_skills, combined_text)

    if score >= threshold:
        reason = (
            f"Score {score:.1f}% >= threshold {threshold:.0f}%. "
            f"Matched: {', '.join(matched) or 'general overlap'}."
        )
    else:
        reason = (
            f"Score {score:.1f}% < threshold {threshold:.0f}%. "
            "Not enough skill overlap."
        )

    return ScoredInternship(
        internship=internship,
        score=score,
        matched_skills=matched,
        resume_skills=sorted(resume_skills),
        reason=reason,
        _threshold=threshold,
    )


def filter_internships(internships: list, resume_text: str, threshold: float = 60.0):
    """
    Score every internship and split into (passed, skipped).

    Parameters
    ----------
    internships : list[Internship]  from scraper.py
    resume_text : full text of the user's resume
    threshold   : minimum score (0-100) to qualify for application

    Returns
    -------
    (passed: list[ScoredInternship], skipped: list[ScoredInternship])
    """
    resume_skills = parse_resume(resume_text)
    passed, skipped = [], []

    for job in internships:
        si = score_internship(job, resume_skills, threshold)
        if si.passes:
            passed.append(si)
            logger.info(f"  PASS  [{si.score:5.1f}%] {job.title} @ {job.company}")
        else:
            skipped.append(si)
            logger.info(f"  SKIP  [{si.score:5.1f}%] {job.title} @ {job.company}")

    logger.info(
        f"Filter complete — {len(passed)} passed, {len(skipped)} skipped "
        f"(threshold={threshold}%)"
    )
    return passed, skipped
