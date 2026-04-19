#!/usr/bin/env python
"""Extract lecture slide contents from a video into one Obsidian markdown file.

Usage:
  python lecture_slides.py LECTURE.mp4 -o slides.md
  python lecture_slides.py LECTURE.mp4 -o slides.md --interval 1.5 --workers 6

Pipeline:
  1. ffmpeg samples one frame every `--interval` seconds
  2. Perceptual-hash dedup removes near-duplicate frames
  3. Claude vision per unique frame: verbatim text + diagram bounding boxes
  4. Crop diagram regions via Pillow, write .md + sibling assets folder
"""

import argparse
import base64
import concurrent.futures
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from PIL import Image
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).parent / ".env")


class Diagram(BaseModel):
    bbox: list[float] = Field(
        description="[x1, y1, x2, y2] in normalized 0-1 coords; (0,0)=top-left, (1,1)=bottom-right"
    )
    caption: str = Field(description="Short caption describing the diagram")


class SlideContent(BaseModel):
    text: str = Field(
        description="Verbatim text on the slide as markdown (headers, bullets, $math$). "
                    "Do NOT summarize. Preserve exact wording."
    )
    diagrams: list[Diagram] = Field(default_factory=list)


VLM_PROMPT = """Transcribe this lecture slide.

- `text`: verbatim content exactly as shown, preserved with markdown. Use `#` \
for the slide title and `##`+ for any sub-headings. Preserve bullets, \
`$inline$` and `$$display$$` math, and code blocks. Do NOT paraphrase or \
summarize.

  COMPLETENESS IS CRITICAL. Before finalizing, count every bullet / line / \
item visible in the image and confirm each one appears in your output. Do \
NOT skip trailing bullets just because they seem like less-important asides \
— transcribe EVERY visible line, even short ones. If a bullet is partially \
cut off but legible, include as much as you can read.

  Return "" (empty) AND no diagrams for boilerplate / non-content slides:
  - blank slides or slides showing only the presenter's webcam
  - course title / intro cards (e.g. "Introduction to ___ with <instructor name>")
  - university or institution branding / logo slides (e.g. "University of X",
    "Be Boulder.", school crests, department logos)
  - copyright / legal notices (e.g. "© Regents of...")
  - sources / references / bibliography slides
  - "Thank you" / "Questions?" / end-of-lecture closers
  Also ignore persistent branding FOOTERS that appear on every slide (school
  name, copyright line, slide number) — transcribe only the lecture content
  itself. If after stripping boilerplate nothing remains, return "".

- `diagrams`: for each non-text visual element that conveys lecture content \
(figure, chart, plot, graph, flowchart, schematic, architecture diagram), \
return a bounding box in normalized [x1, y1, x2, y2] coords where (0,0) is \
top-left and (1,1) is bottom-right, plus a brief caption. IGNORE: the \
presenter's webcam / video feed (usually a small rectangular inset showing \
the speaker), logos, institutional crests, page numbers, decorative \
background patterns. Return [] if the slide is text-only or boilerplate."""


def sample_frames(video: Path, out_dir: Path, interval: float) -> list[tuple[float, Path]]:
    """Sample one frame every `interval` seconds using ffmpeg."""
    pattern = str(out_dir / "raw_%05d.jpg")
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-i", str(video),
         "-vf", f"fps=1/{interval}",
         "-q:v", "2", pattern],
        check=True,
    )
    files = sorted(out_dir.glob("raw_*.jpg"))
    return [(i * interval, fp) for i, fp in enumerate(files)]


def phash(img_path: Path, size: int = 16) -> int:
    """Simple average-hash on a grayscale downsample. Returns a `size*size`-bit int."""
    img = Image.open(img_path).convert("L").resize((size, size), Image.LANCZOS)
    pixels = img.tobytes()  # one byte per pixel in mode "L"
    avg = sum(pixels) / len(pixels)
    bits = 0
    for i, p in enumerate(pixels):
        if p >= avg:
            bits |= 1 << i
    return bits


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def dedupe_frames(frames: list[tuple[float, Path]], threshold: int) -> list[tuple[float, Path]]:
    """Split into segments on big consecutive-frame hash jumps; keep the LAST frame of each
    segment so build-on slides are captured in their final, most-complete state."""
    if not frames:
        return []
    hashes = [phash(fp) for _, fp in frames]
    boundaries = [0]
    for i in range(1, len(frames)):
        if hamming(hashes[i], hashes[i - 1]) > threshold:
            boundaries.append(i)
    boundaries.append(len(frames))
    kept: list[tuple[float, Path]] = []
    for start, end in zip(boundaries, boundaries[1:]):
        kept.append(frames[end - 1])
    return kept


def analyze_slide(client: anthropic.Anthropic, frame_path: Path) -> SlideContent:
    data = base64.standard_b64encode(frame_path.read_bytes()).decode("utf-8")
    response = client.messages.parse(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/jpeg", "data": data,
                }},
                {"type": "text", "text": VLM_PROMPT},
            ],
        }],
        output_format=SlideContent,
    )
    return response.parsed_output


def crop_diagram(frame_path: Path, bbox: list[float], out_path: Path):
    img = Image.open(frame_path)
    w, h = img.size
    x1, y1, x2, y2 = bbox
    box = (
        max(0, int(x1 * w)),
        max(0, int(y1 * h)),
        min(w, int(x2 * w)),
        min(h, int(y2 * h)),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        return False
    img.crop(box).save(out_path)
    return True


def fmt_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", type=Path, help="Lecture video file")
    ap.add_argument("-o", "--output", type=Path, required=True, help="Output .md path")
    ap.add_argument("-i", "--interval", type=float, default=2.0,
                    help="Seconds between sampled frames (default 2.0; lower=more coverage)")
    ap.add_argument("--hash-threshold", type=int, default=20,
                    help="Bits of 256-bit hash difference to count as a new slide (default 20; "
                         "lower=more sensitive to changes, higher=skips subtle builds)")
    ap.add_argument("-w", "--workers", type=int, default=4,
                    help="Concurrent Claude API workers (default 4)")
    args = ap.parse_args()

    if not args.video.exists():
        sys.exit(f"error: video not found: {args.video}")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("error: set ANTHROPIC_API_KEY in your environment or .env")

    out_md = args.output.resolve()
    out_dir = out_md.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    asset_dir = out_dir / f"{out_md.stem}_assets"
    asset_dir.mkdir(exist_ok=True)

    with tempfile.TemporaryDirectory() as td:
        frame_dir = Path(td)
        print(f"[1/3] sampling frames every {args.interval}s...", file=sys.stderr)
        raw = sample_frames(args.video, frame_dir, args.interval)
        print(f"      sampled {len(raw)} frames", file=sys.stderr)

        print(f"[2/3] deduping via perceptual hash (threshold={args.hash_threshold})...", file=sys.stderr)
        unique = dedupe_frames(raw, args.hash_threshold)
        print(f"      kept {len(unique)} unique slides", file=sys.stderr)

        print(f"[3/3] analyzing {len(unique)} slides with claude-sonnet-4-6...", file=sys.stderr)
        client = anthropic.Anthropic()

        def work(idx_item):
            i, (ts, fp) = idx_item
            try:
                return i, ts, fp, analyze_slide(client, fp), None
            except Exception as e:
                return i, ts, fp, None, e

        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(work, it): it for it in enumerate(unique)}
            for done, fut in enumerate(concurrent.futures.as_completed(futures), 1):
                results.append(fut.result())
                print(f"      {done}/{len(unique)} done", file=sys.stderr)

        results.sort(key=lambda r: r[0])

        lines = []
        for i, ts, fp, content, err in results:
            if err:
                lines.append(f"*extraction failed at {fmt_ts(ts)}: {err}*")
                lines.append("")
                continue
            if content.text.strip():
                lines.append(content.text.strip())
                lines.append("")
            for j, d in enumerate(content.diagrams):
                crop_name = f"{out_md.stem}_s{i + 1:03d}_fig{j + 1}.png"
                crop_path = asset_dir / crop_name
                if crop_diagram(fp, d.bbox, crop_path):
                    rel = crop_path.relative_to(out_dir).as_posix()
                    lines.append(f"![{d.caption}]({rel})")
                    lines.append(f"*{d.caption}*")
                    lines.append("")

        out_md.write_text("\n".join(lines), encoding="utf-8")
        print(f"\nwrote {out_md}", file=sys.stderr)
        print(f"assets in {asset_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
