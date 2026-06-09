"""
apply.py
--------
Playwright-based auto-apply engine for Internshala.

Flow per job
------------
1. Navigate to the job detail page.
2. Click "Apply Now".
3. Fill the cover letter / application textarea.
4. Upload the resume PDF.
5. Submit (or stop before submit if --dry-run).

Human-like behaviour
--------------------
- Random per-character typing delay (40–130 ms)
- Random pauses between page actions (0.8–6 s)
- Realistic Chrome user-agent
"""

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from pathlib import Path

from playwright.async_api import (
    async_playwright,
    BrowserContext,
    Page,
    TimeoutError as PWTimeoutError,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class ApplicationResult:
    title: str
    company: str
    link: str
    status: str           # "applied" | "skipped" | "failed"
    reason: str
    score: float
    matched_skills: list = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "company": self.company,
            "link": self.link,
            "status": self.status,
            "reason": self.reason,
            "score": round(self.score, 2),
            "matched_skills": self.matched_skills,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Human-like interaction helpers
# ---------------------------------------------------------------------------

async def _delay(min_s: float = 0.6, max_s: float = 2.0) -> None:
    await asyncio.sleep(min_s + random.random() * (max_s - min_s))


async def _human_type(page: Page, selector: str, text: str) -> None:
    """Mimick human typing with per-character random delays."""
    await page.click(selector)
    await page.fill(selector, "")
    for char in text:
        await page.type(selector, char, delay=random.randint(40, 130))
    await _delay(0.2, 0.5)


async def _safe_click(page: Page, *selectors: str, timeout: int = 5_000) -> bool:
    """Try selectors in order; return True if any click succeeded."""
    for sel in selectors:
        try:
            el = await page.wait_for_selector(sel, timeout=timeout, state="visible")
            if el:
                await el.scroll_into_view_if_needed()
                await _delay(0.3, 0.8)
                await el.click()
                return True
        except Exception:
            continue
    return False


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

async def login(context: BrowserContext, email: str, password: str) -> bool:
    """Log in to Internshala; return True on success."""
    page = await context.new_page()
    try:
        await page.goto(
            "https://internshala.com/login/user",
            wait_until="domcontentloaded",
            timeout=20_000,
        )
        await _delay(1.0, 2.0)
        await _human_type(page, "#email", email)
        await _human_type(page, "#password", password)

        clicked = await _safe_click(page, "#login_submit", "button[type='submit']")
        if not clicked:
            logger.error("Login button not found.")
            return False

        # Wait for redirect signal
        try:
            await page.wait_for_url("**/dashboard**", timeout=10_000)
            logger.info("Login successful — dashboard loaded.")
            return True
        except PWTimeoutError:
            logout = await page.query_selector("a[href*='logout'], .logout")
            if logout:
                logger.info("Login successful — logout link detected.")
                return True
            logger.error("Login may have failed — no dashboard or logout link found.")
            return False

    except Exception as exc:
        logger.error(f"Login exception: {exc}")
        return False
    finally:
        await page.close()


# ---------------------------------------------------------------------------
# Cover letter template
# ---------------------------------------------------------------------------

_COVER_LETTER = """Dear Hiring Team,

I am writing to express my strong interest in the {title} position at {company}. \
With hands-on experience in {skills}, I am excited by the opportunity to contribute \
to your team while continuing to grow professionally.

I am a motivated, detail-oriented individual who thrives in collaborative environments. \
I have attached my resume and would welcome the chance to discuss how my background \
aligns with your needs.

Thank you for considering my application.

Warm regards,
{name}""".strip()


# ---------------------------------------------------------------------------
# Single-job application
# ---------------------------------------------------------------------------

async def _apply_single(
    context: BrowserContext,
    si,                          # ScoredInternship
    applicant: dict,
    resume_path: Path,
    dry_run: bool = False,
) -> ApplicationResult:

    job = si.internship
    ts  = time.strftime("%Y-%m-%dT%H:%M:%S")
    base = dict(
        title=job.title,
        company=job.company,
        link=job.link,
        score=si.score,
        matched_skills=si.matched_skills,
        timestamp=ts,
    )

    page = await context.new_page()
    try:
        # 1 ── Open job page ─────────────────────────────────────────────────
        await page.goto(job.link, wait_until="domcontentloaded", timeout=20_000)
        await _delay(1.5, 3.0)

        # 2 ── Click Apply Now ───────────────────────────────────────────────
        clicked = await _safe_click(
            page,
            "#apply_now_btn",
            "button.apply_now",
            "a.apply_now",
            "button:has-text('Apply Now')",
            "button:has-text('Apply')",
            "[class*='apply']",
        )
        if not clicked:
            return ApplicationResult(**base, status="failed", reason="Apply button not found.")

        await _delay(1.5, 2.5)

        # 3 ── Guard: unexpected login wall ─────────────────────────────────
        if await page.query_selector("#email, input[name='email']"):
            return ApplicationResult(
                **base, status="failed",
                reason="Unexpected login wall — ensure you are logged in."
            )

        # 4 ── Cover letter ──────────────────────────────────────────────────
        cover = _COVER_LETTER.format(
            title=job.title,
            company=job.company,
            skills=", ".join(si.matched_skills[:4]) or "relevant technical areas",
            name=applicant["name"],
        )
        for sel in [
            "textarea[name='cover_letter']",
            "textarea[placeholder*='cover']",
            "textarea[placeholder*='Cover']",
            "textarea",
        ]:
            try:
                if await page.query_selector(sel):
                    await _human_type(page, sel, cover)
                    logger.debug("Cover letter filled.")
                    break
            except Exception:
                continue

        await _delay(0.5, 1.0)

        # 5 ── Upload resume ─────────────────────────────────────────────────
        if resume_path and resume_path.exists():
            for sel in [
                "input[type='file'][name*='resume']",
                "input[type='file'][accept*='pdf']",
                "input[type='file']",
            ]:
                try:
                    fi = await page.query_selector(sel)
                    if fi:
                        await fi.set_input_files(str(resume_path))
                        logger.debug(f"Resume uploaded: {resume_path.name}")
                        await _delay(1.0, 2.0)
                        break
                except Exception:
                    continue
        else:
            logger.warning(f"Resume not found: {resume_path}")

        # 6 ── Submit ────────────────────────────────────────────────────────
        if dry_run:
            logger.info(f"[DRY RUN] {job.title} @ {job.company} — not submitted")
            return ApplicationResult(
                **base, status="applied",
                reason="Dry run — form filled, not submitted."
            )

        submitted = await _safe_click(
            page,
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('Submit')",
            "button:has-text('Apply')",
        )
        if not submitted:
            return ApplicationResult(**base, status="failed", reason="Submit button not found.")

        # 7 ── Confirm ───────────────────────────────────────────────────────
        await _delay(2.0, 3.5)
        confirmed = False
        for indicator in [
            "text=Successfully applied",
            "text=Application submitted",
            ".success_message",
            "[class*='success']",
        ]:
            try:
                await page.wait_for_selector(indicator, timeout=5_000)
                confirmed = True
                break
            except PWTimeoutError:
                continue

        reason = (
            "Application submitted successfully." if confirmed
            else "Submitted — success confirmation not detected."
        )
        logger.info(f"  APPLIED: {job.title} @ {job.company}  [{si.score:.1f}%]")
        return ApplicationResult(**base, status="applied", reason=reason)

    except PWTimeoutError:
        return ApplicationResult(**base, status="failed", reason="Page timed out.")
    except Exception as exc:
        logger.error(f"Error applying to {job.title}: {exc}")
        return ApplicationResult(**base, status="failed", reason=f"Unexpected error: {exc}")
    finally:
        await page.close()


# ---------------------------------------------------------------------------
# Public runner
# ---------------------------------------------------------------------------

async def run_applications(
    passed_jobs: list,
    skipped_jobs: list,
    applicant: dict,
    resume_path: Path,
    dry_run: bool = False,
    headless: bool = True,
) -> list:
    """
    Log in to Internshala and apply to every job that passed the filter.

    Returns list[ApplicationResult] covering both passed and skipped jobs.
    """
    results = []

    # Record skipped jobs immediately (no browser needed)
    for si in skipped_jobs:
        results.append(ApplicationResult(
            title=si.internship.title,
            company=si.internship.company,
            link=si.internship.link,
            status="skipped",
            reason=si.reason,
            score=si.score,
            matched_skills=si.matched_skills,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
        ))

    if not passed_jobs:
        logger.info("No jobs passed the filter — nothing to apply to.")
        return results

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
        )

        # Single login — session cookies persist for all subsequent pages
        logged_in = await login(context, applicant["email"], applicant["password"])
        if not logged_in:
            logger.error("Login failed — aborting all applications.")
            for si in passed_jobs:
                results.append(ApplicationResult(
                    title=si.internship.title,
                    company=si.internship.company,
                    link=si.internship.link,
                    status="failed",
                    reason="Internshala login failed.",
                    score=si.score,
                    matched_skills=si.matched_skills,
                    timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
                ))
            await browser.close()
            return results

        # Apply sequentially with human-like pacing
        for idx, si in enumerate(passed_jobs, 1):
            logger.info(
                f"Applying [{idx}/{len(passed_jobs)}]: "
                f"{si.internship.title} @ {si.internship.company}"
            )
            result = await _apply_single(context, si, applicant, resume_path, dry_run)
            results.append(result)

            if idx < len(passed_jobs):
                await _delay(3.0, 6.0)   # breathe between applications

        await browser.close()

    return results
