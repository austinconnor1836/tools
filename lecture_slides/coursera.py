"""Coursera course scraping: login, discover modules/videos, download lectures."""

import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright, Page, BrowserContext

from .pipeline import process_pdf, process_video, demote_headers, clean_title

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
class Module:
    title: str
    order: int
    lectures: list[Lecture] = field(default_factory=list)


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

        # Get the module title — it's the first h2 with the module-specific
        # heading class, not the course title or chat panel headings.
        # Coursera renders: course title (h2) → module title (h2) → section headings (h2)
        # The module title is the second h2 on the page.
        module_title = f"Module {mod_num}"
        headings = page.query_selector_all("h2")
        if len(headings) >= 2:
            candidate = headings[1].inner_text().strip().split("\n")[0].strip()
            # Skip if it's the course title (same as first h2) or a chat heading
            first_h2 = headings[0].inner_text().strip().split("\n")[0].strip()
            if candidate and candidate != first_h2 and "Chat" not in candidate:
                module_title = candidate

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

        if lectures:
            modules.append(Module(title=module_title, order=mod_num, lectures=lectures))

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


def download_lecture(page: Page, lecture: Lecture, dest_dir: Path) -> tuple[Path, str]:
    """Navigate to a lecture page, check for PDF slides, fall back to video.

    Returns (file_path, kind) where kind is 'pdf' or 'video'.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe_title = _sanitize_filename(lecture.title)

    # Check if we already have either format
    pdf_path = dest_dir / f"{lecture.order:02d}_{safe_title}.pdf"
    mp4_path = dest_dir / f"{lecture.order:02d}_{safe_title}.mp4"
    if pdf_path.exists() and pdf_path.stat().st_size > 0:
        print(f"    already downloaded: {pdf_path.name}", file=sys.stderr)
        return pdf_path, "pdf"
    if mp4_path.exists() and mp4_path.stat().st_size > 0:
        print(f"    already downloaded: {mp4_path.name}", file=sys.stderr)
        return mp4_path, "video"

    print(f"    checking downloads: {lecture.title}...", file=sys.stderr)

    # Navigate to the lecture page
    page.goto(lecture.url, wait_until="domcontentloaded", timeout=60000)
    time.sleep(5)

    # Get available downloads
    downloads = get_lecture_downloads(page)

    # Prefer PDF slides over video
    pdf_dl = next((d for d in downloads if d.kind == "pdf"), None)
    if pdf_dl:
        print(f"    downloading PDF slides: {pdf_dl.label}...", file=sys.stderr)
        _download_file(pdf_dl.url, pdf_path, page)
        return pdf_path, "pdf"

    # Fall back to video — prefer 1080p
    video_dl = next(
        (d for d in downloads if d.kind == "mp4" and "1080" in d.label),
        next((d for d in downloads if d.kind == "mp4"), None),
    )
    if video_dl:
        print(f"    downloading video: {video_dl.label}...", file=sys.stderr)
        _download_file(video_dl.url, mp4_path, page)
        return mp4_path, "video"

    # Last resort: try to extract video URL from the player
    video_url = _try_video_source(page)
    if video_url:
        print(f"    downloading video (from player)...", file=sys.stderr)
        _download_file(video_url, mp4_path, page)
        return mp4_path, "video"

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


def combine_module_notes(
    module_title: str,
    lectures: list[tuple[str, Path]],
    output_dir: Path,
) -> Path:
    """Merge per-lecture markdown files into a single Notes.md for the module.

    Each lecture's content (with slide titles at ##) is demoted one level so that:
      # Module Title
      ## Lecture Title
      ### Slide titles
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    notes_path = output_dir / "Notes.md"
    asset_dir_name = "Notes_assets"

    lines = [f"# {module_title}", ""]

    for lecture_title, md_path in lectures:
        if not md_path.exists():
            lines.append(f"## {lecture_title}")
            lines.append("")
            lines.append("*Processing failed for this lecture.*")
            lines.append("")
            continue

        content = md_path.read_text(encoding="utf-8")

        # Strip the per-lecture `# title` line
        content_lines = content.split("\n")
        body_lines = []
        skipped_title = False
        for line in content_lines:
            if not skipped_title and line.startswith("# ") and not line.startswith("## "):
                skipped_title = True
                continue
            body_lines.append(line)

        body = "\n".join(body_lines).strip()

        # Demote headers one more level (## -> ###, etc.) so slide titles become ###
        body = demote_headers(body)

        # Rewrite asset paths to point to the shared Notes_assets directory
        # Per-lecture assets are named like lecture_01_s001_fig1.png in lecture_01_assets/
        # We need to update paths in markdown image references
        old_asset_dir = f"{md_path.stem}_assets"
        body = body.replace(f"{old_asset_dir}/", f"{asset_dir_name}/")

        lines.append(f"## {lecture_title}")
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
            print(f"    {mod.order}. {mod.title} ({len(mod.lectures)} lectures)", file=sys.stderr)

        # Download lecture files (PDF slides preferred, video as fallback)
        print("[3/4] downloading lecture materials...", file=sys.stderr)
        dl_dir = output_dir / ".downloads"
        dl_dir.mkdir(exist_ok=True)

        # (title, path, kind) where kind is "pdf" or "video"
        module_files: dict[int, list[tuple[str, Path, str]]] = {}
        failures: list[str] = []

        for mod in modules:
            mod_dl_dir = dl_dir / f"module_{mod.order:02d}"
            mod_files: list[tuple[str, Path, str]] = []

            for lecture in mod.lectures:
                if skip_download:
                    safe_title = _sanitize_filename(lecture.title)
                    # Check for either format
                    for ext, kind in [(".pdf", "pdf"), (".mp4", "video")]:
                        expected = mod_dl_dir / f"{lecture.order:02d}_{safe_title}{ext}"
                        if expected.exists():
                            mod_files.append((lecture.title, expected, kind))
                            break
                    else:
                        print(f"    skipped (not found): {safe_title}", file=sys.stderr)
                    continue

                try:
                    file_path, kind = download_lecture(page, lecture, mod_dl_dir)
                    mod_files.append((lecture.title, file_path, kind))
                except Exception as e:
                    print(f"    FAILED: {lecture.title}: {e}", file=sys.stderr)
                    failures.append(f"Module {mod.order}, {lecture.title}: {e}")

            module_files[mod.order] = mod_files

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

        lecture_mds: list[tuple[str, Path]] = []

        for idx, (lecture_title, file_path, kind) in enumerate(files, 1):
            lecture_stem = f"lecture_{idx:02d}"
            lecture_md = mod_output_dir / f"{lecture_stem}.md"

            if lecture_md.exists():
                print(f"    already processed: {lecture_stem}", file=sys.stderr)
                lecture_mds.append((lecture_title, lecture_md))
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
                lecture_mds.append((lecture_title, lecture_md))
            except Exception as e:
                print(f"    FAILED: {lecture_title}: {e}", file=sys.stderr)
                failures.append(f"Module {mod.order}, {lecture_title} (processing): {e}")
                lecture_mds.append((lecture_title, lecture_md))

        # Combine into Notes.md
        notes_path = combine_module_notes(mod.title, lecture_mds, mod_output_dir)

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
        for lecture_title, md_path in lecture_mds:
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
