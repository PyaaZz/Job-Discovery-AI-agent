# 🤖 Auto Apply Bot — Internshala Internship Automator

A production-ready Python + Playwright bot that **scrapes**, **filters**, and
**auto-applies** to internships on Internshala by matching listings to your
resume via skill-overlap analysis.

---

## 📁 Project Structure

```
auto_apply_bot/
├── scraper.py          ← Async Playwright scraper (listings + detail pages)
├── filter.py           ← Resume skill parser + match-score engine
├── apply.py            ← Playwright login + form-fill + submit engine
├── main.py             ← CLI entry point
├── sample_resume.txt   ← Example resume for testing
├── requirements.txt    ← Python dependencies
└── logs/
    └── applications.json   ← Auto-generated per run
```

---

## ⚙️ Setup (5 minutes)

### 1 · Prerequisites
- **Python 3.11+** — https://python.org/downloads
- A free **Internshala account** — https://internshala.com

### 2 · Create a virtual environment
```bash
python -m venv venv
source venv/bin/activate      # macOS / Linux
venv\Scripts\activate         # Windows
```

### 3 · Install dependencies
```bash
pip install -r requirements.txt
```

### 4 · Install Playwright's Chromium browser
```bash
playwright install chromium
```
> One-time download (~150 MB). Takes ~60 seconds.

---

## 🚀 Running the Bot

### Interactive mode (recommended first time)
```bash
python main.py
```
The bot will prompt you for everything it needs.

### Full CLI mode
```bash
python main.py \
  --keyword    "frontend intern" \
  --resume     sample_resume.txt \
  --name       "John Doe" \
  --email      john@example.com \
  --password   yourpassword \
  --threshold  60 \
  --max-listings 20
```

### Safe dry-run (fill forms, don't submit)
```bash
python main.py \
  --keyword "python intern" \
  --resume  sample_resume.txt \
  --name    "John Doe" \
  --email   you@example.com \
  --password yourpass \
  --dry-run \
  --no-headless        # ← watch the browser in real time
```

### Scrape & filter only (no login needed)
```bash
python main.py \
  --keyword "data science intern" \
  --resume  sample_resume.txt \
  --scrape-only
```

---

## 🎛️ All CLI Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--keyword` | prompted | Search term, e.g. `"frontend intern"` |
| `--resume` | prompted | Path to resume (.pdf or .txt) |
| `--email` | prompted | Internshala account email |
| `--password` | prompted (hidden) | Internshala password |
| `--name` | prompted | Your name for the cover letter |
| `--threshold` | `60` | Min skill-match score (0–100) |
| `--max-listings` | `20` | Cap on listings scraped |
| `--dry-run` | off | Fill forms but don't submit |
| `--no-headless` | off | Show the browser window |
| `--output` | `logs/applications.json` | Where to write the JSON log |
| `--scrape-only` | off | Scrape + filter; skip applying |

---

## 📊 Output — logs/applications.json

```json
{
  "run_at": "2024-06-15T10:32:01",
  "total": 15,
  "applied": 8,
  "skipped": 5,
  "failed": 2,
  "results": [
    {
      "title": "Frontend Developer Intern",
      "company": "Tech Corp",
      "link": "https://internshala.com/internship/...",
      "status": "applied",
      "reason": "Score 78.5% >= threshold 60%. Matched: react, javascript, css.",
      "score": 78.5,
      "matched_skills": ["react", "javascript", "css"],
      "resume_skills": ["react", "python", "javascript", "css", "node"],
      "timestamp": "2024-06-15T10:35:42"
    },
    {
      "title": "Java Backend Intern",
      "company": "Enterprise Ltd",
      "link": "https://internshala.com/internship/...",
      "status": "skipped",
      "reason": "Score 22.0% < threshold 60%. Not enough skill overlap.",
      "score": 22.0,
      "matched_skills": [],
      "timestamp": "2024-06-15T10:33:11"
    }
  ]
}
```

---

## 🔬 How the Skill Matcher Works

```
Resume text  ──► extract_skills()  ──► {python, react, sql, …}
                                              │
Job listing  ──► extract_skills()  ──► {react, html, css, …}
                                              │
                          score = 0.5 × Jaccard(A∩B / A∪B)
                                + 0.5 × Recall(A∩B / B)
                                × 100

score >= threshold  →  PASS  →  auto-apply
score <  threshold  →  SKIP  →  logged only
```

40+ canonical skills are detected via word-boundary regex, so
`"React.js"`, `"ReactJS"`, and `"react"` all map to the same key.

---

## 🛠️ Customisation

### Raise / lower the match bar
```bash
--threshold 75    # stricter — only very strong matches
--threshold 40    # looser  — apply to more jobs
```

### Add new skills to the taxonomy
Edit `TECH_SKILLS` in `filter.py`:
```python
"solidity": ["solidity", "web3", "ethereum", "smart contract"],
"rust":     ["rust", "cargo"],
```

### Change the cover letter
Edit `_COVER_LETTER` in `apply.py`.

### Handle CAPTCHAs
Run with `--no-headless`, solve the CAPTCHA manually once,
then let the bot continue.

---

## ⚠️ Troubleshooting

| Symptom | Fix |
|---------|-----|
| `No internship cards found` | Internshala updated their HTML — adjust selectors in `scraper.py` |
| Login fails | Double-check credentials; run `--no-headless` to watch |
| PDF skills empty | Install `pdfplumber` or pass a `.txt` resume |
| CAPTCHA blocks login | Use `--no-headless`, solve it once manually |
| Apply button not found | Internshala form changed — check apply.py selectors |

---

## 📦 Dependencies

| Package | Purpose |
|---------|---------|
| `playwright` | Browser automation (Chromium) |
| `pdfplumber` | Extract text from PDF resumes |
