"""Coursera course scraping: login, discover modules/videos, download lectures."""

import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright, Page, BrowserContext

from .pipeline import process_pdf, process_video, enrich_with_transcript, demote_headers, clean_title

SESSION_DIR = Path.home() / ".cache" / "lecture_slides"
SESSION_FILE = SESSION_DIR / "coursera_session.json"


@dataclass
class Lecture:
    title: str
    url: str
    order: int


@dataclass
class LectureDownload:
    kind: str   # "mp4", "pdf", "webvtt", "txt", ...
    label: str  # "Lecture Video (1080p)", "Video Slides", etc.
    url: str


@dataclass
class Quiz:
    title: str
    url: str
    order: int  # position among all items in the module


@dataclass
class ProgrammingAssignment:
    title: str
    url: str
    order: int


@dataclass
class Reading:
    title: str
    url: str
    order: int


@dataclass
class ModuleItem:
    """A single item in a module, preserving page order."""
    kind: str  # "lecture", "quiz", "assignment", "reading"
    title: str
    url: str
    order: int  # position in the module page (1-indexed)


@dataclass
class Module:
    title: str
    order: int
    lectures: list[Lecture] = field(default_factory=list)
    quizzes: list[Quiz] = field(default_factory=list)
    assignments: list[ProgrammingAssignment] = field(default_factory=list)
    readings: list[Reading] = field(default_factory=list)
    items: list[ModuleItem] = field(default_factory=list)  # all items in page order


def _sanitize_filename(name: str) -> str:
    """Remove characters that are invalid in file/directory names."""
    s = re.sub(r'[<>:"/\\|?*]', "", name)
    return s.strip(". ")


def _save_session(context: BrowserContext) -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(SESSION_FILE))


def _login(page: Page, context: BrowserContext, email: str, password: str) -> None:
    """Log into Coursera via email/password.

    Coursera uses Arkose Labs CAPTCHA on login. In headed mode the user can
    solve it manually; in headless mode login will fail if a CAPTCHA appears
    (use a saved session instead).
    """
    print("  logging in to Coursera...", file=sys.stderr)
    page.goto("https://www.coursera.org/?authMode=login", wait_until="networkidle")

    # Step 1: Enter email and click Continue (Coursera uses a two-step login)
    page.wait_for_selector('input[name="email"]', timeout=15000)
    page.fill('input[name="email"]', email)

    # Click the "Continue" button in the auth section
    continue_btn = page.query_selector(
        'button[type="submit"]:has-text("Continue"), '
        'button:has-text("Continue"):not(:has-text("Google")):not(:has-text("Facebook")):not(:has-text("Apple"))'
    )
    if continue_btn and continue_btn.is_visible():
        continue_btn.click()
    else:
        page.press('input[name="email"]', "Enter")

    # Step 2: Wait for password field and fill it
    page.wait_for_selector('input[name="password"]', state="visible", timeout=15000)
    page.fill('input[name="password"]', password)

    # Click login/submit button
    login_btn = page.query_selector('button[type="submit"]:has-text("Login"), button[type="submit"]:has-text("Log in")')
    if login_btn and login_btn.is_visible():
        login_btn.click()
    else:
        page.press('input[name="password"]', "Enter")

    # A CAPTCHA may appear — wait for it to be solved (long timeout for manual solving)
    print("  waiting for login (solve CAPTCHA if prompted)...", file=sys.stderr)

    # Wait until we navigate away from the login page — 3 minute timeout for CAPTCHA
    try:
        page.wait_for_function(
            """() => {
                return !window.location.href.includes('authMode=login')
                    && !window.location.href.includes('/login');
            }""",
            timeout=180000,
        )
    except Exception:
        raise RuntimeError(
            "Login timed out. If a CAPTCHA appeared, run with --headed so you can solve it. "
            "Once logged in, the session is saved for future headless runs."
        )

    page.wait_for_load_state("networkidle")

    _save_session(context)
    print("  logged in successfully", file=sys.stderr)


def _ensure_logged_in(page: Page, context: BrowserContext, headed: bool = False) -> None:
    """Restore session or log in fresh."""
    email = os.environ.get("COURSERA_EMAIL", "")
    password = os.environ.get("COURSERA_PASSWORD", "")
    if not email or not password:
        raise RuntimeError("set COURSERA_EMAIL and COURSERA_PASSWORD in .env")

    # Try existing session
    if SESSION_FILE.exists():
        print("  restoring saved session...", file=sys.stderr)
        page.goto("https://www.coursera.org/", wait_until="networkidle")
        time.sleep(2)
        # Check if session is still valid — if we're not redirected to login
        # and the page has typical logged-in content (no login prompt)
        if "authMode=login" not in page.url and "/login" not in page.url:
            # Try navigating to a course page to confirm session works
            print("  session restored", file=sys.stderr)
            return
        print("  session expired, re-authenticating...", file=sys.stderr)

    if not headed:
        raise RuntimeError(
            "No valid session found. Run with --headed first so you can solve the "
            "CAPTCHA during login. The session will be saved for future headless runs."
        )

    _login(page, context, email, password)


def _clean_lecture_title(raw_text: str) -> str:
    """Extract just the lecture title from Coursera's link text.

    innerText form:  'Intro to X\\n\\nVideo•\\n. Duration: 6 minutes\\n6 min'
    textContent form: 'Intro to XVideo•. Duration: 6 minutes6 min'
    We only want the actual title.
    """
    # First try splitting on newline (works for innerText)
    first_line = raw_text.split("\n")[0].strip()
    # Strip textContent metadata that runs together with the title
    first_line = re.sub(r"Video•.*$", "", first_line).strip()
    first_line = re.sub(r"Reading•.*$", "", first_line).strip()
    return first_line


def discover_course(page: Page, course_url: str) -> list[Module]:
    """Navigate each module page and extract lecture videos in order."""
    base = re.sub(r"/(home|module).*$", "", course_url.rstrip("/"))

    print(f"  navigating to course: {base}", file=sys.stderr)

    # First, discover how many modules exist by visiting module 1 and checking sidebar
    page.goto(f"{base}/home/module/1", wait_until="networkidle")
    time.sleep(3)

    # Find module links in the sidebar navigation
    module_links = page.query_selector_all(f'a[href*="{base.split("/learn/")[1]}/home/module/"]')
    module_numbers = set()
    for link in module_links:
        href = link.get_attribute("href") or ""
        match = re.search(r"/home/module/(\d+)", href)
        if match:
            module_numbers.add(int(match.group(1)))

    if not module_numbers:
        # Fallback: try incrementing module numbers
        module_numbers = set(range(1, 20))

    max_module = max(module_numbers)
    modules: list[Module] = []

    for mod_num in sorted(module_numbers):
        mod_url = f"{base}/home/module/{mod_num}"

        # Only navigate if not already on this page
        if f"/module/{mod_num}" not in page.url:
            page.goto(mod_url, wait_until="networkidle")
            time.sleep(3)

        # Check if page loaded (Coursera redirects on invalid modules)
        if f"/module/{mod_num}" not in page.url:
            if mod_num <= max_module:
                continue
            break

        # Get the module title. Skip banners ("Congratulations", "Rate this
        # course", "Chat with us", etc.) by finding the first h2 whose text
        # doesn't match known non-module patterns, excluding the course title.
        module_title = f"Module {mod_num}"
        course_title_el = page.query_selector("h2")
        course_title = course_title_el.inner_text().strip().split("\n")[0] if course_title_el else ""
        skip_patterns = ["congratulations", "rate this", "chat with", "next course",
                         "you increased", "skill score"]
        for h2 in page.query_selector_all("h2"):
            text = h2.inner_text().strip().split("\n")[0].strip()
            if not text or text == course_title:
                continue
            if any(p in text.lower() for p in skip_patterns):
                continue
            module_title = text
            break

        # Find lecture links (videos only, not readings/quizzes)
        links = page.query_selector_all('a[href*="/lecture/"]')
        lectures = []
        seen_urls = set()
        for link in links:
            href = link.get_attribute("href") or ""
            # Some completed lectures have empty innerText (SVG checkmark blocks it)
            # but textContent still has the title prefixed with "Completed".
            text = link.inner_text().strip()
            if not text:
                text = link.evaluate("el => el.textContent.trim()") or ""
                text = re.sub(r"^Completed", "", text).strip()
            if not href or not text or href in seen_urls:
                continue
            seen_urls.add(href)
            title = _clean_lecture_title(text)
            full_url = href if href.startswith("http") else f"https://www.coursera.org{href}"
            lectures.append(Lecture(title=title, url=full_url, order=len(lectures) + 1))

        # Find quiz/assignment links
        quiz_links = page.query_selector_all('a[href*="/assignment-submission/"]')
        quizzes = []
        for link in quiz_links:
            href = link.get_attribute("href") or ""
            text = link.inner_text().strip()
            if not text:
                text = link.evaluate("el => el.textContent.trim()") or ""
                text = re.sub(r"^Completed", "", text).strip()
            if not href or not text or href in seen_urls:
                continue
            seen_urls.add(href)
            title = _clean_lecture_title(text)
            # Skip practice quizzes (Quick Check-In) and policy quizzes
            if "quick check" in title.lower() or "policy quiz" in title.lower():
                continue
            full_url = href if href.startswith("http") else f"https://www.coursera.org{href}"
            quizzes.append(Quiz(title=title, url=full_url, order=len(quizzes) + 1))

        # Find programming assignment links (R only)
        prog_links = page.query_selector_all('a[href*="/programming/"]')
        assignments = []
        for link in prog_links:
            href = link.get_attribute("href") or ""
            text = link.inner_text().strip()
            if not text:
                text = link.evaluate("el => el.textContent.trim()") or ""
                text = re.sub(r"^Completed", "", text).strip()
            if not href or not text or href in seen_urls:
                continue
            seen_urls.add(href)
            title = _clean_lecture_title(text)
            # Only include R assignments — titles use "(R)" or "in R"
            title_lower = title.lower()
            if "(r)" not in title_lower and not title_lower.endswith(" in r") and " in r " not in title_lower:
                continue
            full_url = href if href.startswith("http") else f"https://www.coursera.org{href}"
            assignments.append(ProgrammingAssignment(title=title, url=full_url, order=len(assignments) + 1))

        # Find reading/supplement links
        reading_links = page.query_selector_all('a[href*="/supplement/"]')
        readings = []
        # Skip generic course-level readings
        skip_reading_patterns = ["earn academic", "course syllabus", "assessment expectations",
                                 "ai citation", "course facilitation", "course support",
                                 "course resources", "coding in python", "calculator notebook",
                                 "proctoru", "exam tools", "about the final", "create your",
                                 "log in to", "do not open", "joining the"]
        for link in reading_links:
            href = link.get_attribute("href") or ""
            text = link.inner_text().strip()
            if not text:
                text = link.evaluate("el => el.textContent.trim()") or ""
                text = re.sub(r"^Completed", "", text).strip()
            if not href or not text or href in seen_urls:
                continue
            seen_urls.add(href)
            title = _clean_lecture_title(text)
            if any(p in title.lower() for p in skip_reading_patterns):
                continue
            full_url = href if href.startswith("http") else f"https://www.coursera.org{href}"
            readings.append(Reading(title=title, url=full_url, order=len(readings) + 1))

        # Build ordered items list from all content links in DOM order
        all_content_links = page.query_selector_all(
            'a[href*="/lecture/"], a[href*="/supplement/"], '
            'a[href*="/assignment-submission/"], a[href*="/programming/"]'
        )
        items: list[ModuleItem] = []
        seen_item_urls: set[str] = set()
        for link in all_content_links:
            href = link.get_attribute("href") or ""
            if not href or href in seen_item_urls:
                continue
            text = link.inner_text().strip()
            if not text:
                text = link.evaluate("el => el.textContent.trim()") or ""
                text = re.sub(r"^Completed", "", text).strip()
            if not text:
                continue
            title = _clean_lecture_title(text)
            # Determine kind and apply filters
            if "/lecture/" in href:
                kind = "lecture"
            elif "/supplement/" in href:
                if any(p in title.lower() for p in skip_reading_patterns):
                    continue
                kind = "reading"
            elif "/assignment-submission/" in href:
                if "quick check" in title.lower() or "policy quiz" in title.lower():
                    continue
                kind = "quiz"
            elif "/programming/" in href:
                title_lower = title.lower()
                if "(r)" not in title_lower and not title_lower.endswith(" in r") and " in r " not in title_lower:
                    continue
                kind = "assignment"
            else:
                continue
            seen_item_urls.add(href)
            full_url = href if href.startswith("http") else f"https://www.coursera.org{href}"
            items.append(ModuleItem(kind=kind, title=title, url=full_url, order=len(items) + 1))

        if lectures:
            modules.append(Module(title=module_title, order=mod_num, lectures=lectures,
                                  quizzes=quizzes, assignments=assignments, readings=readings,
                                  items=items))

    if not modules:
        raise RuntimeError(
            "Could not discover course structure. The page layout may have changed. "
            "Try running with --headed to inspect the page."
        )

    return modules


def get_lecture_downloads(page: Page) -> list[LectureDownload]:
    """Open the Downloads tab on a lecture page and extract all available resources."""
    downloads: list[LectureDownload] = []

    # Click the Downloads tab
    dl_tab = page.query_selector('button:has-text("Downloads")')
    if not dl_tab:
        return downloads
    dl_tab.click()
    time.sleep(2)

    # The downloads panel is a visible [role="tabpanel"] containing <li> items.
    # Each item has a file-type label and a link, e.g. "pdf\nVideo Slides".
    # Scope to the tabpanel to avoid picking up sidebar navigation items.
    panel = page.query_selector('[role="tabpanel"]:visible')
    if not panel:
        return downloads

    lis = panel.query_selector_all("li")
    items = []
    for li in lis:
        link = li.query_selector("a")
        if not link:
            continue
        href = link.get_attribute("href") or ""
        text = li.inner_text().strip()
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        if len(lines) >= 2:
            items.append({"kind": lines[0].lower(), "label": " ".join(lines[1:]), "href": href})

    for item in items:
        kind = item.get("kind", "")
        label = item.get("label", "")
        href = item.get("href", "")
        if kind and href:
            url = href if href.startswith("http") else f"https://www.coursera.org{href}"
            downloads.append(LectureDownload(kind=kind, label=label, url=url))

    return downloads


def download_lecture(page: Page, lecture: Lecture, dest_dir: Path) -> tuple[Path, str, Path | None]:
    """Navigate to a lecture page, check for PDF slides, fall back to video.

    Returns (file_path, kind, transcript_path) where kind is 'pdf' or 'video'.
    transcript_path is None if no transcript was available.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe_title = _sanitize_filename(lecture.title)
    transcript_path = dest_dir / f"{lecture.order:02d}_{safe_title}.txt"

    # Check if we already have either format
    pdf_path = dest_dir / f"{lecture.order:02d}_{safe_title}.pdf"
    mp4_path = dest_dir / f"{lecture.order:02d}_{safe_title}.mp4"
    tx_path = transcript_path if transcript_path.exists() and transcript_path.stat().st_size > 0 else None
    if pdf_path.exists() and pdf_path.stat().st_size > 0:
        print(f"    already downloaded: {pdf_path.name}", file=sys.stderr)
        return pdf_path, "pdf", tx_path
    if mp4_path.exists() and mp4_path.stat().st_size > 0:
        print(f"    already downloaded: {mp4_path.name}", file=sys.stderr)
        return mp4_path, "video", tx_path

    print(f"    checking downloads: {lecture.title}...", file=sys.stderr)

    # Navigate to the lecture page
    page.goto(lecture.url, wait_until="domcontentloaded", timeout=60000)
    time.sleep(5)

    # Get available downloads
    downloads = get_lecture_downloads(page)

    # Download transcript if available
    txt_dl = next((d for d in downloads if d.kind == "txt" and "transcript" in d.label.lower()), None)
    if txt_dl:
        print(f"    downloading transcript...", file=sys.stderr)
        _download_file(txt_dl.url, transcript_path, page)

    # Prefer PDF slides over video
    pdf_dl = next((d for d in downloads if d.kind == "pdf"), None)
    if pdf_dl:
        print(f"    downloading PDF slides: {pdf_dl.label}...", file=sys.stderr)
        _download_file(pdf_dl.url, pdf_path, page)
        tx = transcript_path if transcript_path.exists() and transcript_path.stat().st_size > 0 else None
        return pdf_path, "pdf", tx

    # Fall back to video — prefer 1080p
    video_dl = next(
        (d for d in downloads if d.kind == "mp4" and "1080" in d.label),
        next((d for d in downloads if d.kind == "mp4"), None),
    )
    tx = transcript_path if transcript_path.exists() and transcript_path.stat().st_size > 0 else None

    if video_dl:
        print(f"    downloading video: {video_dl.label}...", file=sys.stderr)
        _download_file(video_dl.url, mp4_path, page)
        return mp4_path, "video", tx

    # Last resort: try to extract video URL from the player
    video_url = _try_video_source(page)
    if video_url:
        print(f"    downloading video (from player)...", file=sys.stderr)
        _download_file(video_url, mp4_path, page)
        return mp4_path, "video", tx

    raise RuntimeError(f"Could not find slides or video for: {lecture.title}")


def _try_video_source(page: Page) -> str | None:
    """Extract the video URL from the HTML5 video player."""
    try:
        video_src = page.evaluate("""() => {
            const video = document.querySelector('video');
            if (video) {
                if (video.src && video.src.includes('.mp4')) return video.src;
                const source = video.querySelector('source[type*="mp4"], source[src*=".mp4"]');
                if (source) return source.src;
                if (video.currentSrc) return video.currentSrc;
            }
            return null;
        }""")
        if video_src:
            return video_src
    except Exception:
        pass
    return None


def _download_file(url: str, dest: Path, page: Page) -> None:
    """Download a file via httpx with cookies from the browser session."""
    # Extract cookies from the browser context
    cookies = page.context.cookies()
    cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)

    with httpx.Client(follow_redirects=True, timeout=300) as client:
        headers = {"Cookie": cookie_header}
        with client.stream("GET", url, headers=headers) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            downloaded = 0
            with open(dest, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded * 100 // total
                        print(f"\r    {pct}% ({downloaded // (1024*1024)}MB / {total // (1024*1024)}MB)", end="", file=sys.stderr)
            if total:
                print(file=sys.stderr)

    print(f"    saved: {dest.name} ({dest.stat().st_size // (1024*1024)}MB)", file=sys.stderr)


QUIZ_PROMPT = """Extract the quiz questions and answers from this screenshot of a Coursera assignment submission page.

For each question, output:
- The question number and text (preserve all math as LaTeX: $inline$ and $$display$$)
- All answer choices (if multiple choice)
- The student's selected/submitted answer, marked with ✅
- Whether the answer was correct or incorrect

Format as clean markdown. Use `### Question N` for each question.
Skip any "honor code" or "AI assistant" boilerplate text embedded in the page.
If a question has a text/numeric input answer, show the submitted value."""


def scrape_quiz(page: Page, quiz: Quiz, output_dir: Path) -> Path | None:
    """Navigate to a quiz submission page, screenshot it, and extract Q&A via Gemini."""
    safe_title = _sanitize_filename(quiz.title)
    md_path = output_dir / f"{safe_title}.md"

    if md_path.exists() and md_path.stat().st_size > 0:
        print(f"    already scraped quiz: {safe_title}", file=sys.stderr)
        return md_path

    print(f"    scraping quiz: {quiz.title}...", file=sys.stderr)

    # Navigate to submission view
    submission_url = quiz.url if quiz.url.startswith("http") else f"https://www.coursera.org{quiz.url}"
    if not submission_url.endswith("/view-submission"):
        submission_url = submission_url.rstrip("/") + "/view-submission"

    page.goto(submission_url, wait_until="domcontentloaded", timeout=60000)
    time.sleep(5)

    # Dismiss Honor Code modal if present
    try:
        continue_btn = page.query_selector('button:has-text("Continue")')
        if continue_btn and continue_btn.is_visible():
            continue_btn.click()
            time.sleep(2)
    except Exception:
        pass

    # Scroll to load all content
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    time.sleep(2)

    # Take full-page screenshots (quiz pages can be very long)
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        # Get page height and take segmented screenshots
        viewport_height = page.viewport_size["height"]
        total_height = page.evaluate("() => document.documentElement.scrollHeight")
        screenshots = []
        y = 0
        idx = 0
        while y < total_height:
            page.evaluate(f"window.scrollTo(0, {y})")
            time.sleep(0.5)
            ss_path = td_path / f"quiz_{idx:02d}.png"
            page.screenshot(path=str(ss_path), full_page=False)
            screenshots.append(ss_path)
            idx += 1
            y += viewport_height

        # Use Gemini to extract Q&A from screenshots
        from .pipeline import _make_vision_client
        client, _, model_name = _make_vision_client()
        print(f"    extracting Q&A with {model_name}...", file=sys.stderr)

        if os.environ.get("GEMINI_API_KEY"):
            from google.genai import types
            parts = []
            for ss in screenshots:
                parts.append(types.Part.from_bytes(data=ss.read_bytes(), mime_type="image/png"))
            parts.append(types.Part.from_text(text=QUIZ_PROMPT))

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[types.Content(role="user", parts=parts)],
                config=types.GenerateContentConfig(max_output_tokens=16384),
            )
            quiz_md = response.text
        else:
            import anthropic
            import base64
            content = []
            for ss in screenshots:
                data = base64.standard_b64encode(ss.read_bytes()).decode("utf-8")
                content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}})
            content.append({"type": "text", "text": QUIZ_PROMPT})
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=16384,
                messages=[{"role": "user", "content": content}],
            )
            quiz_md = response.content[0].text

    # Write quiz markdown
    output_dir.mkdir(parents=True, exist_ok=True)
    full_md = f"# {quiz.title}\n\n{quiz_md}"
    md_path.write_text(full_md, encoding="utf-8")
    print(f"    wrote {md_path.name}", file=sys.stderr)
    return md_path


def download_notebook(page: Page, context, assignment: ProgrammingAssignment, output_dir: Path) -> Path | None:
    """Launch a Coursera lab, download the Jupyter notebook via API."""
    safe_title = _sanitize_filename(assignment.title)
    ipynb_path = output_dir / f"{safe_title}.ipynb"

    if ipynb_path.exists() and ipynb_path.stat().st_size > 0:
        print(f"    already downloaded notebook: {ipynb_path.name}", file=sys.stderr)
        return ipynb_path

    print(f"    downloading notebook: {assignment.title}...", file=sys.stderr)

    # Navigate to the assignment page
    url = assignment.url if assignment.url.startswith("http") else f"https://www.coursera.org{assignment.url}"
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    time.sleep(5)

    # Dismiss Honor Code modal
    try:
        btn = page.query_selector('button:has-text("Continue")')
        if btn and btn.is_visible():
            btn.click()
            time.sleep(2)
    except Exception:
        pass

    # Click "Launch lab" and capture the new tab
    launch_btn = page.query_selector('button:has-text("Launch lab"), button:has-text("Open lab")')
    if not launch_btn:
        print(f"    no Launch lab button found", file=sys.stderr)
        return None

    try:
        with context.expect_page(timeout=60000) as new_page_info:
            launch_btn.click()
        lab_page = new_page_info.value
        lab_page.wait_for_load_state("domcontentloaded", timeout=60000)
        time.sleep(5)
    except Exception as e:
        print(f"    failed to open lab: {e}", file=sys.stderr)
        return None

    try:
        # Wait for the iframe to appear — labs can take a while to spin up
        print(f"    waiting for lab to load...", file=sys.stderr)
        try:
            lab_page.wait_for_selector("iframe", timeout=60000)
        except Exception:
            pass
        time.sleep(5)

        iframe_el = lab_page.query_selector("iframe")
        if not iframe_el:
            print(f"    no iframe found in lab page", file=sys.stderr)
            return None

        iframe_src = iframe_el.get_attribute("src") or ""
        if "/notebooks/" not in iframe_src:
            print(f"    unexpected iframe src: {iframe_src[:80]}", file=sys.stderr)
            return None

        # Use Jupyter's REST API to download the notebook JSON
        api_url = iframe_src.replace("/notebooks/", "/api/contents/")
        print(f"    fetching notebook via API...", file=sys.stderr)

        api_page = context.new_page()
        api_page.goto(api_url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        body = api_page.inner_text("body")
        api_page.close()

        if not body.startswith("{"):
            print(f"    API response not JSON: {body[:100]}", file=sys.stderr)
            return None

        import json
        data = json.loads(body)
        notebook_content = data.get("content")
        if not notebook_content:
            print(f"    no content in API response", file=sys.stderr)
            return None

        # Save the notebook
        output_dir.mkdir(parents=True, exist_ok=True)
        with open(ipynb_path, "w", encoding="utf-8") as f:
            json.dump(notebook_content, f, indent=1)

        print(f"    saved: {ipynb_path.name}", file=sys.stderr)
        return ipynb_path

    finally:
        lab_page.close()


def scrape_reading(page: Page, reading: Reading, output_dir: Path) -> Path | None:
    """Navigate to a reading/supplement page and save its content as markdown."""
    safe_title = _sanitize_filename(reading.title)
    md_path = output_dir / f"{safe_title}.md"

    if md_path.exists() and md_path.stat().st_size > 0:
        print(f"    already scraped reading: {safe_title}", file=sys.stderr)
        return md_path

    print(f"    scraping reading: {reading.title}...", file=sys.stderr)

    url = reading.url if reading.url.startswith("http") else f"https://www.coursera.org{reading.url}"
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    time.sleep(5)

    # Click Resume if needed to navigate to the actual content
    try:
        resume_btn = page.query_selector('button:has-text("Resume"), a:has-text("Resume")')
        if resume_btn and resume_btn.is_visible():
            resume_btn.click()
            time.sleep(5)
    except Exception:
        pass

    # Take full-page screenshots and use Gemini to extract content
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        viewport_height = page.viewport_size["height"]
        total_height = page.evaluate("() => document.documentElement.scrollHeight")
        screenshots = []
        y = 0
        idx = 0
        while y < total_height:
            page.evaluate(f"window.scrollTo(0, {y})")
            time.sleep(0.5)
            ss_path = td_path / f"reading_{idx:02d}.png"
            page.screenshot(path=str(ss_path), full_page=False)
            screenshots.append(ss_path)
            idx += 1
            y += viewport_height

        from .pipeline import _make_vision_client
        client, _, model_name = _make_vision_client()
        print(f"    extracting content with {model_name}...", file=sys.stderr)

        reading_prompt = (
            "Extract the reading/article content from this Coursera supplement page as clean markdown. "
            "Include the title as a # heading. Preserve all text, formatting, links, and any embedded content. "
            "Skip navigation elements, sidebar, and Coursera UI chrome. "
            "If there are references to downloadable PDFs, note the title of the PDF."
        )

        if os.environ.get("GEMINI_API_KEY"):
            from google.genai import types
            parts = [types.Part.from_bytes(data=ss.read_bytes(), mime_type="image/png") for ss in screenshots]
            parts.append(types.Part.from_text(text=reading_prompt))
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[types.Content(role="user", parts=parts)],
                config=types.GenerateContentConfig(max_output_tokens=16384),
            )
            reading_md = response.text
        else:
            import base64
            content = []
            for ss in screenshots:
                data = base64.standard_b64encode(ss.read_bytes()).decode("utf-8")
                content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}})
            content.append({"type": "text", "text": reading_prompt})
            response = client.messages.create(
                model="claude-sonnet-4-6", max_tokens=16384,
                messages=[{"role": "user", "content": content}],
            )
            reading_md = response.content[0].text

    output_dir.mkdir(parents=True, exist_ok=True)
    md_path.write_text(reading_md, encoding="utf-8")
    print(f"    wrote {md_path.name}", file=sys.stderr)
    return md_path


def combine_module_notes(
    module_title: str,
    lecture_mds: dict[str, Path],
    output_dir: Path,
    quiz_mds: dict[str, Path] | None = None,
    notebook_paths: dict[str, Path] | None = None,
    reading_mds: dict[str, Path] | None = None,
    ordered_items: list[ModuleItem] | None = None,
) -> Path:
    """Merge per-lecture markdown files into a single Notes.md for the module.

    All items are interleaved in the order they appear on the Coursera page.
    Lectures get their content inlined; quizzes, assignments, and readings
    are linked with Obsidian's [[]] syntax, all at the ## heading level.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    notes_path = output_dir / "Notes.md"
    asset_dir_name = "Notes_assets"
    quiz_mds = quiz_mds or {}
    notebook_paths = notebook_paths or {}
    reading_mds = reading_mds or {}

    lines = [f"# {module_title}", ""]

    if ordered_items:
        for item in ordered_items:
            if item.kind == "lecture":
                md_path = lecture_mds.get(item.title)
                if not md_path or not md_path.exists():
                    lines.append(f"## {item.title}")
                    lines.append("")
                    lines.append("*Processing failed for this lecture.*")
                    lines.append("")
                    continue

                content = md_path.read_text(encoding="utf-8")
                content_lines = content.split("\n")
                body_lines = []
                skipped_title = False
                for line in content_lines:
                    if not skipped_title and line.startswith("# ") and not line.startswith("## "):
                        skipped_title = True
                        continue
                    body_lines.append(line)

                body = "\n".join(body_lines).strip()
                body = demote_headers(body)
                old_asset_dir = f"{md_path.stem}_assets"
                body = body.replace(f"{old_asset_dir}/", f"{asset_dir_name}/")

                lines.append(f"## {item.title}")
                lines.append("")
                if body:
                    lines.append(body)
                    lines.append("")

            elif item.kind == "quiz":
                key = _sanitize_filename(item.title)
                qmd = quiz_mds.get(key)
                if qmd:
                    lines.append(f"## [[{qmd.name}]]")
                    lines.append("")

            elif item.kind == "assignment":
                key = _sanitize_filename(item.title)
                nb = notebook_paths.get(key)
                if nb:
                    lines.append(f"## [[{nb.name}]]")
                    lines.append("")

            elif item.kind == "reading":
                key = _sanitize_filename(item.title)
                rmd = reading_mds.get(key)
                if rmd:
                    lines.append(f"## [[{rmd.name}]]")
                    lines.append("")
    else:
        # Fallback: lectures only (no ordered items available)
        for title, md_path in lecture_mds.items():
            if not md_path.exists():
                lines.append(f"## {title}")
                lines.append("")
                lines.append("*Processing failed for this lecture.*")
                lines.append("")
                continue
            content = md_path.read_text(encoding="utf-8")
            content_lines = content.split("\n")
            body_lines = []
            skipped_title = False
            for line in content_lines:
                if not skipped_title and line.startswith("# ") and not line.startswith("## "):
                    skipped_title = True
                    continue
                body_lines.append(line)
            body = "\n".join(body_lines).strip()
            body = demote_headers(body)
            old_asset_dir = f"{md_path.stem}_assets"
            body = body.replace(f"{old_asset_dir}/", f"Notes_assets/")
            lines.append(f"## {title}")
            lines.append("")
            if body:
                lines.append(body)
                lines.append("")

    notes_path.write_text("\n".join(lines), encoding="utf-8")
    return notes_path


def scrape_course(
    course_url: str,
    output_dir: Path,
    module_filter: list[int] | None = None,
    headed: bool = False,
    keep_videos: bool = False,
    skip_download: bool = False,
    interval: float = 2.0,
    hash_threshold: int = 20,
    workers: int = 4,
) -> None:
    """Full pipeline: login → discover → download (PDF or video) → process → combine."""
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print("[1/4] connecting to Coursera...", file=sys.stderr)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)

        context_args = {}
        if SESSION_FILE.exists():
            context_args["storage_state"] = str(SESSION_FILE)

        context = browser.new_context(**context_args)
        page = context.new_page()

        _ensure_logged_in(page, context, headed=headed)

        print("[2/4] discovering course structure...", file=sys.stderr)
        modules = discover_course(page, course_url)

        if module_filter:
            modules = [m for m in modules if m.order in module_filter]

        print(f"  found {len(modules)} modules:", file=sys.stderr)
        for mod in modules:
            extras = []
            if mod.quizzes:
                extras.append(f"{len(mod.quizzes)} quizzes")
            if mod.assignments:
                extras.append(f"{len(mod.assignments)} assignments")
            if mod.readings:
                extras.append(f"{len(mod.readings)} readings")
            extra_str = f", {', '.join(extras)}" if extras else ""
            print(f"    {mod.order}. {mod.title} ({len(mod.lectures)} lectures{extra_str})", file=sys.stderr)

        # Download lecture files (PDF slides preferred, video as fallback)
        print("[3/4] downloading lecture materials...", file=sys.stderr)
        dl_dir = output_dir / ".downloads"
        dl_dir.mkdir(exist_ok=True)

        # (title, path, kind, transcript_path)
        module_files: dict[int, list[tuple[str, Path, str, Path | None]]] = {}
        failures: list[str] = []

        for mod in modules:
            mod_dl_dir = dl_dir / f"module_{mod.order:02d}"
            mod_files: list[tuple[str, Path, str, Path | None]] = []

            for lecture in mod.lectures:
                if skip_download:
                    safe_title = _sanitize_filename(lecture.title)
                    tx_path = mod_dl_dir / f"{lecture.order:02d}_{safe_title}.txt"
                    tx = tx_path if tx_path.exists() and tx_path.stat().st_size > 0 else None
                    for ext, kind in [(".pdf", "pdf"), (".mp4", "video")]:
                        expected = mod_dl_dir / f"{lecture.order:02d}_{safe_title}{ext}"
                        if expected.exists():
                            mod_files.append((lecture.title, expected, kind, tx))
                            break
                    else:
                        print(f"    skipped (not found): {safe_title}", file=sys.stderr)
                    continue

                try:
                    file_path, kind, transcript = download_lecture(page, lecture, mod_dl_dir)
                    mod_files.append((lecture.title, file_path, kind, transcript))
                except Exception as e:
                    print(f"    FAILED: {lecture.title}: {e}", file=sys.stderr)
                    failures.append(f"Module {mod.order}, {lecture.title}: {e}")

            module_files[mod.order] = mod_files

        # Scrape quizzes while browser is still open
        module_quizzes: dict[int, list[Path]] = {}
        for mod in modules:
            if not mod.quizzes:
                continue
            mod_dir_name = _sanitize_filename(f"Module {mod.order} - {mod.title}")
            mod_output_dir = output_dir / mod_dir_name
            quiz_paths = []
            for quiz in mod.quizzes:
                try:
                    qmd = scrape_quiz(page, quiz, mod_output_dir)
                    if qmd:
                        quiz_paths.append(qmd)
                except Exception as e:
                    print(f"    FAILED quiz: {quiz.title}: {e}", file=sys.stderr)
                    failures.append(f"Module {mod.order}, quiz {quiz.title}: {e}")
            module_quizzes[mod.order] = quiz_paths

        # Download programming assignment notebooks
        module_notebooks: dict[int, list[Path]] = {}
        for mod in modules:
            if not mod.assignments:
                continue
            mod_dir_name = _sanitize_filename(f"Module {mod.order} - {mod.title}")
            mod_output_dir = output_dir / mod_dir_name
            nb_paths = []
            for assignment in mod.assignments:
                try:
                    nb = download_notebook(page, context, assignment, mod_output_dir)
                    if nb:
                        nb_paths.append(nb)
                except Exception as e:
                    print(f"    FAILED notebook: {assignment.title}: {e}", file=sys.stderr)
                    failures.append(f"Module {mod.order}, notebook {assignment.title}: {e}")
            module_notebooks[mod.order] = nb_paths

        # Scrape readings
        module_readings: dict[int, list[Path]] = {}
        for mod in modules:
            if not mod.readings:
                continue
            mod_dir_name = _sanitize_filename(f"Module {mod.order} - {mod.title}")
            mod_output_dir = output_dir / mod_dir_name
            reading_paths = []
            for reading in mod.readings:
                try:
                    rmd = scrape_reading(page, reading, mod_output_dir)
                    if rmd:
                        reading_paths.append(rmd)
                except Exception as e:
                    print(f"    FAILED reading: {reading.title}: {e}", file=sys.stderr)
                    failures.append(f"Module {mod.order}, reading {reading.title}: {e}")
            module_readings[mod.order] = reading_paths

        context.close()
        browser.close()

    # Process files and combine into Notes.md per module
    print("[4/4] processing lectures and generating notes...", file=sys.stderr)

    for mod in modules:
        mod_dir_name = _sanitize_filename(f"Module {mod.order} - {mod.title}")
        mod_output_dir = output_dir / mod_dir_name
        mod_output_dir.mkdir(parents=True, exist_ok=True)
        asset_dir = mod_output_dir / "Notes_assets"
        asset_dir.mkdir(exist_ok=True)

        files = module_files.get(mod.order, [])
        if not files:
            print(f"  skipping {mod.title} (no files)", file=sys.stderr)
            continue

        print(f"  processing module: {mod.title}", file=sys.stderr)

        lecture_mds: dict[str, Path] = {}

        for idx, (lecture_title, file_path, kind, transcript_path) in enumerate(files, 1):
            lecture_stem = f"lecture_{idx:02d}"
            lecture_md = mod_output_dir / f"{lecture_stem}.md"

            if lecture_md.exists():
                print(f"    already processed: {lecture_stem}", file=sys.stderr)
                lecture_mds[lecture_title] = lecture_md
                continue

            print(f"    processing ({kind}): {lecture_title}...", file=sys.stderr)
            try:
                if kind == "pdf":
                    process_pdf(
                        pdf=file_path,
                        output_md=lecture_md,
                        title=lecture_title,
                        hash_threshold=hash_threshold,
                        workers=workers,
                    )
                else:
                    process_video(
                        video=file_path,
                        output_md=lecture_md,
                        title=lecture_title,
                        interval=interval,
                        hash_threshold=hash_threshold,
                        workers=workers,
                    )

                # Enrich with transcript if available
                if transcript_path and lecture_md.exists():
                    print(f"    enriching with transcript...", file=sys.stderr)
                    try:
                        slide_md = lecture_md.read_text(encoding="utf-8")
                        transcript = transcript_path.read_text(encoding="utf-8")
                        enriched = enrich_with_transcript(slide_md, transcript)
                        lecture_md.write_text(enriched, encoding="utf-8")
                    except Exception as e:
                        print(f"    transcript enrichment failed: {e}", file=sys.stderr)

                lecture_mds[lecture_title] = lecture_md
            except Exception as e:
                print(f"    FAILED: {lecture_title}: {e}", file=sys.stderr)
                failures.append(f"Module {mod.order}, {lecture_title} (processing): {e}")
                lecture_mds[lecture_title] = lecture_md

        # Build dicts keyed by sanitized title for quizzes, notebooks, readings
        quiz_dict = {_sanitize_filename(p.stem): p for p in module_quizzes.get(mod.order, [])}
        nb_dict = {_sanitize_filename(p.stem): p for p in module_notebooks.get(mod.order, [])}
        reading_dict = {_sanitize_filename(p.stem): p for p in module_readings.get(mod.order, [])}
        notes_path = combine_module_notes(
            mod.title, lecture_mds, mod_output_dir,
            quiz_mds=quiz_dict, notebook_paths=nb_dict, reading_mds=reading_dict,
            ordered_items=mod.items,
        )

        # Move per-lecture asset directories into the shared Notes_assets
        for idx in range(1, len(files) + 1):
            lecture_stem = f"lecture_{idx:02d}"
            per_lecture_assets = mod_output_dir / f"{lecture_stem}_assets"
            if per_lecture_assets.exists():
                for asset_file in per_lecture_assets.iterdir():
                    target = asset_dir / asset_file.name
                    asset_file.rename(target)
                per_lecture_assets.rmdir()

        # Clean up per-lecture markdown files
        for lecture_title, md_path in lecture_mds.items():
            if md_path.exists() and md_path.name != "Notes.md":
                md_path.unlink()

        print(f"  wrote {notes_path}", file=sys.stderr)

    # Clean up downloads unless --keep-videos
    if not keep_videos and not skip_download:
        import shutil
        shutil.rmtree(dl_dir, ignore_errors=True)
        print("  cleaned up downloaded files", file=sys.stderr)

    # Summary
    print(file=sys.stderr)
    if failures:
        print(f"completed with {len(failures)} failure(s):", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
    else:
        print("all modules processed successfully", file=sys.stderr)

    print(f"output: {output_dir}", file=sys.stderr)
