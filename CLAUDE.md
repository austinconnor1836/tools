# Repo notes

Scripts in this repo assume a `.env` file in the repo root with keys like
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc. `.env` is gitignored.

## `lecture_slides/` package

The `lecture_slides.py` shim at the repo root is a backwards-compat entry point;
all logic lives in the `lecture_slides/` package:

- `models.py` — Pydantic models (`Diagram`, `SlideContent`) and `VLM_PROMPT`
- `pipeline.py` — frame sampling, dedup, Claude vision, cropping, `process_video()`
- `coursera.py` — Playwright login, course discovery, video download, `scrape_course()`
- `cli.py` — argparse entry points (`video` and `course` subcommands)
- `__main__.py` — enables `python -m lecture_slides`

Pipeline: ffmpeg samples frames from a lecture video → perceptual-hash dedup →
Claude vision transcribes each unique frame → markdown + cropped diagram assets.

When modifying this package, preserve these invariants:

**Boilerplate filter (VLM prompt).** Must return empty text AND no diagrams for
non-content slides: course title cards ("Introduction to ___ with <instructor>"),
university branding / logo slides ("University of X", "Be Boulder."), copyright
lines ("© Regents of..."), sources / references / bibliography pages, and
"Thank you" / "Questions?" closers. Persistent branding footers (school name,
copyright line, slide number on every slide) must also be stripped. The
presenter's webcam / video feed inset is never lecture content — exclude it
from both text and the diagrams list. Handle this all in the VLM prompt, not
via hardcoded regex in Python, so the tool generalizes to other institutions.

**Build-on completeness.** Lecture slides often build bullets progressively.
`dedupe_frames` must keep the LAST frame of each stable segment (detect
boundaries via consecutive-frame hash-diff, then emit the frame immediately
before each boundary) so the most-complete state of the slide gets transcribed.
The VLM prompt must also emphasize counting every visible bullet — Sonnet will
otherwise silently drop trailing bullets.

**Formatting.** The output document starts with `# {title}` (cleaned from the
filename via `clean_title()`, or overridden with `--title`). The VLM is
prompted to use `#` for slide titles; output is then demoted one level by
`demote_headers()` so slide titles become `##` and the video title is the
only `#`.

**Cross-platform.** No OS-specific logic (paths, shell commands, string
filters). Dependencies: `ffmpeg` on PATH, `python-dotenv`, `anthropic`,
`pillow`, `pydantic`, `playwright`, `httpx`.
