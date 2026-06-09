"""
main.py
-------
CLI entry point for the Auto Apply Bot.

Quick start
-----------
  python main.py                         # fully interactive
  python main.py --keyword "frontend intern" --resume resume.pdf --dry-run

All flags
---------
  --keyword        Search term (e.g. "frontend intern")
  --resume         Path to resume PDF or TXT
  --email          Internshala account email
  --password       Internshala account password (prompted securely if omitted)
  --name           Your full name (used in cover letter)
  --threshold      Min match score 0-100  [default: 60]
  --max-listings   Max internships to scrape  [default: 20]
  --dry-run        Fill forms but do NOT click Submit
  --no-headless    Show the browser window (great for debugging)
  --output         JSON log path  [default: logs/applications.json]
  --scrape-only    Scrape + filter only; skip the apply step
"""

import argparse
import asyncio
import getpass
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Logging must be configured before project imports ─────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("main")

# ── Project modules ────────────────────────────────────────────────────────
from scraper import scrape_internships
from filter  import filter_internships
from apply   import run_applications, ApplicationResult


# ---------------------------------------------------------------------------
# Resume loading
# ---------------------------------------------------------------------------

def load_resume(path: Path) -> str:
    """Return plain text from a .txt or .pdf resume file."""
    if path.suffix.lower() == ".pdf":
        try:
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                return "\n".join(p.extract_text() or "" for p in pdf.pages)
        except ImportError:
            logger.warning(
                "pdfplumber not installed — PDF text extraction skipped.\n"
                "  Install with: pip install pdfplumber\n"
                "  Or provide a .txt version of your resume."
            )
            return ""
    # .txt or any other text format
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:
        logger.error(f"Cannot read resume: {exc}")
        return ""


# ---------------------------------------------------------------------------
# Output / summary
# ---------------------------------------------------------------------------

def save_results(results: list, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_at":  datetime.now().isoformat(),
        "total":   len(results),
        "applied": sum(1 for r in results if r.status == "applied"),
        "skipped": sum(1 for r in results if r.status == "skipped"),
        "failed":  sum(1 for r in results if r.status == "failed"),
        "results": [r.to_dict() for r in results],
    }
    with open(output, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    logger.info(f"Log saved → {output}")


def print_summary(results: list) -> None:
    applied = [r for r in results if r.status == "applied"]
    skipped = [r for r in results if r.status == "skipped"]
    failed  = [r for r in results if r.status == "failed"]

    sep = "─" * 62
    print(f"\n{sep}")
    print("  AUTO APPLY BOT — RUN SUMMARY")
    print(sep)
    print(f"  Total processed : {len(results)}")
    print(f"  ✅ Applied       : {len(applied)}")
    print(f"  ⏭️  Skipped       : {len(skipped)}")
    print(f"  ❌ Failed        : {len(failed)}")
    print(sep)

    if applied:
        print("\n  ✅ APPLIED TO:")
        for r in applied:
            print(f"     • {r.title} @ {r.company}  [{r.score:.1f}%]")

    if failed:
        print("\n  ❌ FAILED:")
        for r in failed:
            print(f"     • {r.title} @ {r.company}")
            print(f"       Reason: {r.reason}")

    print(f"\n{sep}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="auto_apply_bot",
        description="Auto Apply Bot — scrapes, filters, and applies to Internshala internships",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--keyword",      type=str,   help="Internship search keyword")
    p.add_argument("--resume",       type=Path,  help="Path to resume (PDF or TXT)")
    p.add_argument("--email",        type=str,   help="Internshala account email")
    p.add_argument("--password",     type=str,   help="Internshala account password")
    p.add_argument("--name",         type=str,   help="Your full name (for cover letter)")
    p.add_argument("--threshold",    type=float, default=60.0,
                                     help="Min match score 0-100 (default: 60)")
    p.add_argument("--max-listings", type=int,   default=20,
                                     help="Max internships to scrape (default: 20)")
    p.add_argument("--dry-run",      action="store_true",
                                     help="Fill forms but do NOT submit")
    p.add_argument("--no-headless",  action="store_true",
                                     help="Show the browser window")
    p.add_argument("--output",       type=Path,  default=Path("logs/applications.json"),
                                     help="JSON log output path")
    p.add_argument("--scrape-only",  action="store_true",
                                     help="Scrape and filter only; skip applying")
    return p


def prompt_missing(args: argparse.Namespace) -> argparse.Namespace:
    """Interactively fill any argument not supplied on the command line."""
    if not args.keyword:
        args.keyword = input("🔍  Search keyword (e.g. 'frontend intern'): ").strip()
    if not args.resume:
        raw = input("📄  Path to your resume (PDF or TXT): ").strip()
        args.resume = Path(raw)
    if not args.scrape_only:
        if not args.name:
            args.name = input("👤  Your full name: ").strip()
        if not args.email:
            args.email = input("📧  Internshala email: ").strip()
        if not args.password:
            args.password = getpass.getpass("🔒  Internshala password: ")
    return args


# ---------------------------------------------------------------------------
# Async core
# ---------------------------------------------------------------------------

async def async_main(args: argparse.Namespace) -> None:
    headless = not args.no_headless

    # Validate resume
    if not args.resume.exists():
        logger.error(f"Resume not found: {args.resume}")
        sys.exit(1)

    resume_text = load_resume(args.resume)
    if not resume_text.strip():
        logger.warning(
            "Resume text appears empty — skill matching will be minimal.\n"
            "Tip: provide a plain .txt version for best results."
        )

    # ── 1. Scrape ──────────────────────────────────────────────────────────
    print(f"\n🌐  Searching Internshala for '{args.keyword}'…\n")
    internships = await scrape_internships(
        keyword=args.keyword,
        max_listings=args.max_listings,
        fetch_details=True,
        headless=headless,
    )

    if not internships:
        print("⚠️   No internships found. Try a different keyword.")
        sys.exit(0)

    print(f"📋  Scraped {len(internships)} listing(s).\n")

    # ── 2. Filter ──────────────────────────────────────────────────────────
    print(f"🔬  Filtering by resume match (threshold: {args.threshold}%)…\n")
    passed, skipped = filter_internships(
        internships=internships,
        resume_text=resume_text,
        threshold=args.threshold,
    )
    print(f"✅  {len(passed)} passed  |  ⏭️   {len(skipped)} skipped\n")

    # ── 3a. Scrape-only mode ───────────────────────────────────────────────
    if args.scrape_only:
        all_results = []
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        for si in passed + skipped:
            all_results.append(ApplicationResult(
                title=si.internship.title,
                company=si.internship.company,
                link=si.internship.link,
                status="skipped",
                reason="--scrape-only mode; not applied.",
                score=si.score,
                matched_skills=si.matched_skills,
                timestamp=ts,
            ))
        save_results(all_results, args.output)
        print_summary(all_results)
        return

    # ── 3b. Apply ──────────────────────────────────────────────────────────
    mode = "DRY RUN (not submitting)" if args.dry_run else "LIVE"
    print(f"🤖  Starting applications [{mode}]…\n")

    results = await run_applications(
        passed_jobs=passed,
        skipped_jobs=skipped,
        applicant={"name": args.name, "email": args.email, "password": args.password},
        resume_path=args.resume,
        dry_run=args.dry_run,
        headless=headless,
    )

    # ── 4. Save & report ───────────────────────────────────────────────────
    save_results(results, args.output)
    print_summary(results)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()
    args   = prompt_missing(args)

    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user.")
        sys.exit(0)


if __name__ == "__main__":
    main()
