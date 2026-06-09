# Job Discovery AI Agent

A Python automation tool that helps find and apply to relevant internships on Internshala.

The project scrapes internship listings, compares the required skills against a resume, ranks opportunities based on skill overlap, and can automatically fill application forms using Playwright.

## Features

* Scrapes internship listings from Internshala
* Extracts skills from resumes (.txt and PDF)
* Scores internships based on skill similarity
* Filters out low-match opportunities
* Automates application submission using Playwright
* Supports dry-run mode for testing
* Generates application logs for every run

## Tech Stack

* Python
* Playwright
* Asyncio
* PDFPlumber
* JSON

## Project Structure

```text
apply.py      - Handles login and application automation
scraper.py    - Scrapes internship listings
filter.py     - Resume parsing and matching logic
main.py       - Entry point
```

## How It Works

1. Search internships using a keyword.
2. Scrape internship details.
3. Extract skills from the user's resume.
4. Compare resume skills with job requirements.
5. Rank internships by match score.
6. Automatically apply to internships above the chosen threshold.

## Running the Project

```bash
pip install -r requirements.txt
playwright install chromium
python main.py
```

## Future Improvements

* Better NLP-based skill extraction
* Support for additional job portals
* Dashboard for tracking applications
* LLM-generated cover letters

## Why I Built This

I wanted to automate the repetitive process of searching and applying for internships while learning browser automation, web scraping, and matching algorithms.
