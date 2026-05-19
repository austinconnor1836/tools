---
name: coursera
description: Scrape a Coursera course — downloads lecture slides, transcripts, quizzes, readings, programming assignments, and optionally videos. Generates per-module Notes.md files.
allowed-tools: Bash(.venv/bin/python *) Bash(find *) Bash(ls *) Bash(du *) Read
argument-hint: <course-url> -o <output-dir> [--modules 1,2,3] [--only quizzes] [--save-videos <dir>]
---

# Coursera Course Scraper

Scrape a Coursera course and generate comprehensive lecture notes.

## Running the command

```bash
.venv/bin/python -m lecture_slides course $ARGUMENTS
```

## Examples

Full course scrape:
```bash
.venv/bin/python -m lecture_slides course https://www.coursera.org/learn/course-name -o /path/to/output --keep-videos
```

Specific modules with video downloads:
```bash
.venv/bin/python -m lecture_slides course https://www.coursera.org/learn/course-name -o /path/to/output --modules 2,3,4 --keep-videos --save-videos /path/to/videos
```

Re-scrape only quizzes:
```bash
.venv/bin/python -m lecture_slides course https://www.coursera.org/learn/course-name -o /path/to/output --modules 1,2,3 --only quizzes
```

## What it does

1. Logs into Coursera (session cached at `~/.cache/lecture_slides/`)
2. Discovers all modules, lectures, quizzes, assignments, and readings
3. Downloads PDF slides (preferred) or videos as fallback
4. Downloads lecture transcripts
5. Uses Gemini Flash (free) to extract slide content as markdown
6. Enriches notes with transcript insights
7. Scrapes quiz submissions with answers
8. Downloads R programming assignment notebooks via Jupyter API
9. Scrapes reading/supplement pages
10. Combines everything into per-module Notes.md with Obsidian [[]] links

## Options

- `--modules 1,2,3` — only process specific modules
- `--only quizzes` — re-run specific content types (lectures, quizzes, assignments, readings)
- `--save-videos /path` — also download 720p/1080p lecture videos
- `--keep-videos` — keep downloaded processing files after completion
- `--headed` — show browser for debugging
- `-w 4` — concurrent API workers (default 4)

## Prerequisites

- `.env` with `GEMINI_API_KEY` (free) and `COURSERA_EMAIL`/`COURSERA_PASSWORD`
- First run requires `--headed` or `.venv/bin/python -m lecture_slides login` to solve CAPTCHA
- `.venv` activated with dependencies installed

## Environment check

```!
cd /Users/austin/Developer/tools && .venv/bin/python -c "from lecture_slides.coursera import scrape_course; print('lecture_slides OK')" 2>&1 && grep -c GEMINI_API_KEY .env && grep -c COURSERA_EMAIL .env
```
