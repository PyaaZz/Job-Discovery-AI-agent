"""
scraper.py
----------
Async Playwright scraper for Internshala internship listings.
Extracts: title, company, location, stipend, duration, link, description, skills.
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field, asdict
from typing import Optional
from urllib.parse import quote_plus

from playwright.async_api import async_playwright, Page, Browser, TimeoutError as PWTimeoutError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Internship:
    title: str
    company: str
    location: str
    stipend: str
    duration: str
    link: str
    description: str = ""
    skills_required: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_search_url(keyword: str, page: int = 1) -> str:
    slug = keyword.strip().lower().replace(" ", "-")
    base = f"https://internshala.com/internships/keywords-{quote_plus(slug)}"
    if page > 1:
        base += f"/page-{page}"
    return base


async def _random_delay(min_s: float = 0.8, max_s: float = 2.2) -> None:
    import random
    await asyncio.sleep(min_s + random.random() * (max_s - min_s))


# ---------------------------------------------------------------------------
# Detail page scraper
# ---------------------------------------------------------------------------

async def _extract_description(page: Page, link: str):
    """Visit a job detail page and return (description, skills_list)."""
    try:
        await page.goto(link, wait_until="domcontentloaded", timeout=20_000)
        await _random_delay(0.5, 1.2)

        description = ""
        for sel in [".internship_details", "#about_company", ".about-internship", "[class*='detail']"]:
            try:
                el = await page.query_selector(sel)
                if el:
                    description = (await el.inner_text()).strip()
                    if description:
                        break
            except Exception:
                pass

        skills = []
        for sel in [".skill_tags .individual_skill", ".skills_section span", "[class*='skill'] span"]:
            try:
                els = await page.query_selector_all(sel)
                skills = [s.strip() for el in els if (s := (await el.inner_text()).strip())]
                if skills:
                    break
            except Exception:
                pass

        # Fallback: mine skills from description
        if not skills and description:
            common_tech = {
                "python", "javascript", "react", "node", "html", "css", "java",
                "c++", "sql", "mongodb", "django", "flask", "angular", "vue",
                "typescript", "figma", "machine learning", "deep learning",
                "data analysis", "tableau", "git", "docker", "aws", "linux",
            }
            desc_lower = description.lower()
            skills = [t for t in common_tech if t in desc_lower]

        return description, skills

    except PWTimeoutError:
        logger.warning(f"Timeout fetching detail page: {link}")
        return "", []
    except Exception as exc:
        logger.warning(f"Failed to fetch detail page {link}: {exc}")
        return "", []


# ---------------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------------

async def scrape_internships(
    keyword: str,
    max_listings: int = 20,
    fetch_details: bool = True,
    headless: bool = True,
) -> list:
    """
    Scrape internship listings from Internshala for the given keyword.

    Parameters
    ----------
    keyword       : Search term, e.g. "frontend intern"
    max_listings  : Cap on how many listings to collect
    fetch_details : Visit each job page for full description + skills
    headless      : Run browser without a visible window

    Returns
    -------
    list[Internship]
    """
    internships = []

    async with async_playwright() as pw:
        browser: Browser = await pw.chromium.launch(
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

        list_page = await context.new_page()
        page_num = 1

        while len(internships) < max_listings:
            url = _build_search_url(keyword, page_num)
            logger.info(f"Fetching listing page {page_num}: {url}")

            try:
                await list_page.goto(url, wait_until="networkidle", timeout=30_000)
            except PWTimeoutError:
                logger.warning("networkidle timed out — trying domcontentloaded")
                try:
                    await list_page.goto(url, wait_until="domcontentloaded", timeout=20_000)
                except Exception as exc:
                    logger.error(f"Could not load listing page: {exc}")
                    break

            await _random_delay(1.0, 2.0)

            # Try multiple card selectors — Internshala occasionally tweaks class names
            card_selectors = [
                ".individual_internship",
                ".internship-item",
                "[class*='internship_meta']",
                ".internship_list_container .internship",
            ]
            cards = []
            for sel in card_selectors:
                try:
                    cards = await list_page.query_selector_all(sel)
                    if cards:
                        logger.info(f"Found {len(cards)} cards with selector '{sel}'")
                        break
                except Exception as exc:
                    logger.warning(f"Browser closed unexpectedly: {exc}")
                    cards = []
                    break

            if not cards:
                logger.info("Stopping pagination — browser or page closed.")
                break

            if not cards:
                logger.warning(f"No internship cards on page {page_num}. Stopping.")
                break

            for card in cards:
                if len(internships) >= max_listings:
                    break
                try:
                    title = ""
                    for t_sel in [".profile", "h3", ".title", "[class*='profile']"]:
                        el = await card.query_selector(t_sel)
                        if el:
                            title = (await el.inner_text()).strip()
                            if title:
                                break

                    company = ""
                    for c_sel in [".company_name", ".company", "h4", "[class*='company']"]:
                        el = await card.query_selector(c_sel)
                        if el:
                            company = (await el.inner_text()).strip()
                            if company:
                                break

                    location = "Remote"
                    for l_sel in [".location_link", ".locations", "[class*='location']"]:
                        el = await card.query_selector(l_sel)
                        if el:
                            location = (await el.inner_text()).strip() or "Remote"
                            break

                    stipend = "Unpaid"
                    for s_sel in [".stipend", "[class*='stipend']", ".salary"]:
                        el = await card.query_selector(s_sel)
                        if el:
                            stipend = (await el.inner_text()).strip() or "Unpaid"
                            break

                    duration = ""
                    for d_sel in [".duration", "[class*='duration']"]:
                        el = await card.query_selector(d_sel)
                        if el:
                            duration = (await el.inner_text()).strip()
                            break

                    link = ""
                    for a_sel in ["a.view_detail_button", "a[href*='/internship/']", "a"]:
                        el = await card.query_selector(a_sel)
                        if el:
                            href = await el.get_attribute("href")
                            if href:
                                link = href if href.startswith("http") else f"https://internshala.com{href}"
                                break

                    if not title or not link:
                        logger.debug("Skipping card — missing title or link.")
                        continue

                    internships.append(Internship(
                        title=title, company=company, location=location,
                        stipend=stipend, duration=duration, link=link,
                    ))
                    logger.info(f"  [{len(internships)}] {title} @ {company}")

                except Exception as exc:
                    logger.warning(f"Error parsing card: {exc}")
                    continue

            next_btn = await list_page.query_selector(
                "a[rel='next'], .next_pages_link, [class*='next']"
            )
            if next_btn:
                page_num += 1
                await _random_delay(1.5, 3.0)
            else:
                logger.info("No next page. Done scraping listings.")
                break

        # Fetch descriptions from detail pages
        if fetch_details and internships:
            detail_page = await context.new_page()
            logger.info(f"Fetching details for {len(internships)} internships...")

            for i, job in enumerate(internships):
                logger.info(f"  Detail {i+1}/{len(internships)}: {job.link}")
                desc, skills = await _extract_description(detail_page, job.link)
                job.description = desc
                job.skills_required = skills
                await _random_delay(1.0, 2.5)

            await detail_page.close()

        await browser.close()

    logger.info(f"Scraping complete. Collected {len(internships)} internships.")
    return internships
