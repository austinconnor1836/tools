"""CLI entry points for lecture_slides."""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def video_main(argv: list[str] | None = None):
    """Single-video slide extraction (backwards-compatible entry point)."""
    from .pipeline import process_video

    ap = argparse.ArgumentParser(
        description="Extract lecture slide contents from a video into one Obsidian markdown file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("video", type=Path, help="Lecture video file")
    ap.add_argument("-o", "--output", type=Path, required=True, help="Output .md path")
    ap.add_argument("--title", type=str, default=None,
                    help="Document title (rendered as `#`). Defaults to a cleaned-up "
                         "version of the video filename.")
    ap.add_argument("-i", "--interval", type=float, default=2.0,
                    help="Seconds between sampled frames (default 2.0)")
    ap.add_argument("--hash-threshold", type=int, default=20,
                    help="Bits of 256-bit hash difference to count as a new slide (default 20)")
    ap.add_argument("-w", "--workers", type=int, default=4,
                    help="Concurrent Claude API workers (default 4)")
    args = ap.parse_args(argv)

    try:
        process_video(
            video=args.video,
            output_md=args.output,
            title=args.title,
            interval=args.interval,
            hash_threshold=args.hash_threshold,
            workers=args.workers,
        )
    except (FileNotFoundError, RuntimeError) as e:
        sys.exit(f"error: {e}")


def course_main(argv: list[str] | None = None):
    """Download and process all lecture videos from a Coursera course."""
    from .coursera import scrape_course

    ap = argparse.ArgumentParser(
        description="Download lecture videos from a Coursera course and extract slides into per-module Notes.md files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("url", type=str, help="Coursera course URL (e.g. https://www.coursera.org/learn/course-name)")
    ap.add_argument("-o", "--output", type=Path, required=True, help="Output directory for module folders")
    ap.add_argument("--modules", type=str, default=None,
                    help="Comma-separated module numbers to process (1-indexed, e.g. 1,3,5)")
    ap.add_argument("--headed", action="store_true",
                    help="Run browser in headed mode for debugging")
    ap.add_argument("--keep-videos", action="store_true",
                    help="Keep downloaded video files after processing")
    ap.add_argument("--skip-download", action="store_true",
                    help="Skip download, use existing videos in output dir")
    ap.add_argument("--save-videos", type=Path, default=None,
                    help="Also download 720p lecture videos to this directory")
    ap.add_argument("-i", "--interval", type=float, default=2.0,
                    help="Seconds between sampled frames (default 2.0)")
    ap.add_argument("--hash-threshold", type=int, default=20,
                    help="Bits of 256-bit hash difference to count as a new slide (default 20)")
    ap.add_argument("-w", "--workers", type=int, default=4,
                    help="Concurrent Claude API workers (default 4)")
    args = ap.parse_args(argv)

    module_filter = None
    if args.modules:
        module_filter = [int(x.strip()) for x in args.modules.split(",")]

    try:
        scrape_course(
            course_url=args.url,
            output_dir=args.output,
            module_filter=module_filter,
            headed=args.headed,
            keep_videos=args.keep_videos,
            skip_download=args.skip_download,
            save_videos_dir=args.save_videos,
            interval=args.interval,
            hash_threshold=args.hash_threshold,
            workers=args.workers,
        )
    except (FileNotFoundError, RuntimeError) as e:
        sys.exit(f"error: {e}")


def pdf_main(argv: list[str] | None = None):
    """Single-PDF slide extraction."""
    from .pipeline import process_pdf

    ap = argparse.ArgumentParser(
        description="Extract lecture slide contents from a PDF into one Obsidian markdown file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("pdf", type=Path, help="Lecture slides PDF file")
    ap.add_argument("-o", "--output", type=Path, required=True, help="Output .md path")
    ap.add_argument("--title", type=str, default=None,
                    help="Document title (rendered as `#`). Defaults to a cleaned-up "
                         "version of the PDF filename.")
    ap.add_argument("--hash-threshold", type=int, default=20,
                    help="Bits of 256-bit hash difference to count as a new slide (default 20)")
    ap.add_argument("-w", "--workers", type=int, default=4,
                    help="Concurrent Claude API workers (default 4)")
    args = ap.parse_args(argv)

    try:
        process_pdf(
            pdf=args.pdf,
            output_md=args.output,
            title=args.title,
            hash_threshold=args.hash_threshold,
            workers=args.workers,
        )
    except (FileNotFoundError, RuntimeError) as e:
        sys.exit(f"error: {e}")


def login_main(argv: list[str] | None = None):
    """Interactive login to Coursera — saves session for future headless runs."""
    from .coursera import _login, _save_session, SESSION_FILE

    import os
    from playwright.sync_api import sync_playwright

    email = os.environ.get("COURSERA_EMAIL", "")
    password = os.environ.get("COURSERA_PASSWORD", "")
    if not email or not password:
        sys.exit("error: set COURSERA_EMAIL and COURSERA_PASSWORD in .env")

    print("Opening browser for Coursera login...", file=sys.stderr)
    print("Solve the CAPTCHA if prompted, then the session will be saved.", file=sys.stderr)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        try:
            _login(page, context, email, password)
            print(f"Session saved to {SESSION_FILE}", file=sys.stderr)
        finally:
            context.close()
            browser.close()


def main(argv: list[str] | None = None):
    """Top-level CLI with subcommands: video, course, login."""
    ap = argparse.ArgumentParser(
        prog="lecture_slides",
        description="Extract lecture slides from videos or Coursera courses.",
    )
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("video", help="Process a single video file", add_help=False)
    sub.add_parser("pdf", help="Process a single PDF slides file", add_help=False)
    sub.add_parser("course", help="Download and process a Coursera course", add_help=False)
    sub.add_parser("login", help="Log in to Coursera interactively (saves session)")
    args, remaining = ap.parse_known_args(argv)

    if args.command == "video":
        video_main(remaining)
    elif args.command == "pdf":
        pdf_main(remaining)
    elif args.command == "course":
        course_main(remaining)
    elif args.command == "login":
        login_main(remaining)
