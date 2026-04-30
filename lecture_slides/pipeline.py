"""Core pipeline: video/PDF → frames → dedup → vision LLM → markdown."""

import base64
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

from .models import SlideContent, VLM_PROMPT


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
    pixels = img.tobytes()
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


def _analyze_slide_gemini(client, frame_path: Path) -> SlideContent:
    """Analyze a slide image using Google Gemini."""
    from google.genai import types

    img_bytes = frame_path.read_bytes()
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            types.Content(
                role="user",
                parts=[
                    types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                    types.Part.from_text(text=VLM_PROMPT + "\n\nRespond with JSON matching this schema:\n"
                        + json.dumps(SlideContent.model_json_schema(), indent=2)),
                ],
            ),
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SlideContent,
        ),
    )
    return SlideContent.model_validate_json(response.text)


def _analyze_slide_claude(client, frame_path: Path) -> SlideContent:
    """Analyze a slide image using Claude."""
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


def _make_vision_client() -> tuple:
    """Create a vision client, preferring Gemini (free) over Claude.

    Returns (client, analyze_fn) where analyze_fn(client, path) -> SlideContent.
    """
    if os.environ.get("GEMINI_API_KEY"):
        from google import genai
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        return client, _analyze_slide_gemini, "gemini-2.5-flash"

    if os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic
        client = anthropic.Anthropic()
        return client, _analyze_slide_claude, "claude-sonnet-4-6"

    raise RuntimeError("set GEMINI_API_KEY or ANTHROPIC_API_KEY in your environment or .env")


def crop_diagram(frame_path: Path, bbox: list[float], out_path: Path, pad: float = 0.05) -> bool:
    """Crop a diagram region from an image. `pad` adds margin as a fraction of image size."""
    img = Image.open(frame_path)
    w, h = img.size
    x1, y1, x2, y2 = bbox
    box = (
        max(0, int((x1 - pad) * w)),
        max(0, int((y1 - pad) * h)),
        min(w, int((x2 + pad) * w)),
        min(h, int((y2 + pad) * h)),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        return False
    img.crop(box).save(out_path)
    return True


ENRICH_PROMPT = """You are given lecture slide notes (markdown) and the instructor's spoken transcript for the same lecture.

Your task: enrich the slide notes by interleaving relevant transcript content where it adds insight.

RULES:
- Keep ALL existing slide content EXACTLY as-is. Do not modify, rephrase, or remove any existing text, math, headings, or image references.
- Add transcript insights as blockquotes (> ) placed AFTER the relevant slide section they explain.
- Only add transcript content that provides additional explanation, examples, intuition, or context beyond what's already on the slide.
- Skip transcript segments that merely read the slide text verbatim — those add no value.
- Preserve the exact heading hierarchy (# ## ### etc.).
- Preserve all image references (![...](...)) exactly as they appear.
- Do not add any commentary of your own — only use the instructor's words from the transcript.

Return the complete enriched markdown document. Do NOT wrap the output in a code fence (```markdown)."""


def _strip_code_fence(text: str) -> str:
    """Remove wrapping ```markdown ... ``` code fences from LLM output."""
    stripped = text.strip()
    if stripped.startswith("```markdown"):
        stripped = stripped[len("```markdown"):].strip()
    elif stripped.startswith("```md"):
        stripped = stripped[len("```md"):].strip()
    elif stripped.startswith("```"):
        stripped = stripped[3:].strip()
    if stripped.endswith("```"):
        stripped = stripped[:-3].strip()
    return stripped


def enrich_with_transcript(slide_md: str, transcript: str) -> str:
    """Enrich slide notes with relevant transcript excerpts using an LLM."""
    client, _, model_name = _make_vision_client()
    print(f"      using {model_name} for transcript enrichment", file=sys.stderr)

    if os.environ.get("GEMINI_API_KEY"):
        from google.genai import types
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(
                        text=f"{ENRICH_PROMPT}\n\n---\n\n## SLIDE NOTES:\n\n{slide_md}\n\n---\n\n## TRANSCRIPT:\n\n{transcript}"
                    )],
                ),
            ],
            config=types.GenerateContentConfig(
                max_output_tokens=65536,
            ),
        )
        return _strip_code_fence(response.text)
    else:
        import anthropic
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=16384,
            messages=[{
                "role": "user",
                "content": f"{ENRICH_PROMPT}\n\n---\n\n## SLIDE NOTES:\n\n{slide_md}\n\n---\n\n## TRANSCRIPT:\n\n{transcript}",
            }],
        )
        return _strip_code_fence(response.content[0].text)


def demote_headers(md: str) -> str:
    """Shift every ATX heading down one level (# -> ##, ## -> ###, ...)."""
    return re.sub(r"^(#{1,5})(?= +\S)", r"#\1", md, flags=re.MULTILINE)


def clean_title(stem: str) -> str:
    """Heuristically turn a messy filename stem into a human-readable title."""
    s = stem
    s = re.sub(r"^_?[a-f0-9]{12,}_+", "", s)
    s = re.sub(r"^M\d+_+V\d+_+", "", s)
    s = re.sub(r"_+(MP4|MOV|MKV|WEBM|AVI)(_+\d+p?)?$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"_+\d+p?$", "", s)
    s = re.sub(r"\s*\(\d+\)$", "", s)
    s = s.strip(" _-")
    s = re.sub(r"[_\-]+", " ", s)
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def fmt_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def process_video(
    video: Path,
    output_md: Path,
    title: str | None = None,
    interval: float = 2.0,
    hash_threshold: int = 20,
    workers: int = 4,
) -> Path:
    """Run the full pipeline on a single video file. Returns the path to the written .md file."""
    if not video.exists():
        raise FileNotFoundError(f"video not found: {video}")

    client, analyze_fn, model_name = _make_vision_client()

    out_md = output_md.resolve()
    out_dir = out_md.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    asset_dir = out_dir / f"{out_md.stem}_assets"
    asset_dir.mkdir(exist_ok=True)

    with tempfile.TemporaryDirectory() as td:
        frame_dir = Path(td)
        print(f"[1/3] sampling frames every {interval}s...", file=sys.stderr)
        raw = sample_frames(video, frame_dir, interval)
        print(f"      sampled {len(raw)} frames", file=sys.stderr)

        print(f"[2/3] deduping via perceptual hash (threshold={hash_threshold})...", file=sys.stderr)
        unique = dedupe_frames(raw, hash_threshold)
        print(f"      kept {len(unique)} unique slides", file=sys.stderr)

        print(f"[3/3] analyzing {len(unique)} slides with {model_name}...", file=sys.stderr)

        def work(idx_item):
            i, (ts, fp) = idx_item
            try:
                return i, ts, fp, analyze_fn(client, fp), None
            except Exception as e:
                return i, ts, fp, None, e

        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(work, it): it for it in enumerate(unique)}
            for done, fut in enumerate(concurrent.futures.as_completed(futures), 1):
                results.append(fut.result())
                print(f"      {done}/{len(unique)} done", file=sys.stderr)

        results.sort(key=lambda r: r[0])

        title = title or clean_title(video.stem)
        lines = [f"# {title}", ""]
        for i, ts, fp, content, err in results:
            if err:
                lines.append(f"*extraction failed at {fmt_ts(ts)}: {err}*")
                lines.append("")
                continue
            if content.text.strip():
                lines.append(demote_headers(content.text.strip()))
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

    return out_md


def pdf_to_images(pdf_path: Path, out_dir: Path, dpi: int = 200) -> list[tuple[int, Path]]:
    """Render each PDF page to a JPEG image. Returns [(page_num, image_path)]."""
    doc = fitz.open(pdf_path)
    pages = []
    zoom = dpi / 72
    mat = fitz.Matrix(zoom, zoom)
    for i, page in enumerate(doc):
        pix = page.get_pixmap(matrix=mat)
        img_path = out_dir / f"page_{i + 1:04d}.jpg"
        pix.save(str(img_path))
        pages.append((i + 1, img_path))
    doc.close()
    return pages


def process_pdf(
    pdf: Path,
    output_md: Path,
    title: str | None = None,
    hash_threshold: int = 20,
    workers: int = 4,
) -> Path:
    """Run the slide extraction pipeline on a PDF file. Returns the path to the written .md file."""
    if not pdf.exists():
        raise FileNotFoundError(f"PDF not found: {pdf}")

    client, analyze_fn, model_name = _make_vision_client()

    out_md = output_md.resolve()
    out_dir = out_md.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    asset_dir = out_dir / f"{out_md.stem}_assets"
    asset_dir.mkdir(exist_ok=True)

    with tempfile.TemporaryDirectory() as td:
        img_dir = Path(td)
        print(f"[1/3] converting PDF pages to images...", file=sys.stderr)
        raw = pdf_to_images(pdf, img_dir)
        print(f"      rendered {len(raw)} pages", file=sys.stderr)

        print(f"[2/3] deduping via perceptual hash (threshold={hash_threshold})...", file=sys.stderr)
        unique = dedupe_frames(raw, hash_threshold)
        print(f"      kept {len(unique)} unique slides", file=sys.stderr)

        print(f"[3/3] analyzing {len(unique)} slides with {model_name}...", file=sys.stderr)

        def work(idx_item):
            i, (page_num, fp) = idx_item
            try:
                return i, page_num, fp, analyze_fn(client, fp), None
            except Exception as e:
                return i, page_num, fp, None, e

        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(work, it): it for it in enumerate(unique)}
            for done, fut in enumerate(concurrent.futures.as_completed(futures), 1):
                results.append(fut.result())
                print(f"      {done}/{len(unique)} done", file=sys.stderr)

        results.sort(key=lambda r: r[0])

        title = title or clean_title(pdf.stem)
        lines = [f"# {title}", ""]
        for i, page_num, fp, content, err in results:
            if err:
                lines.append(f"*extraction failed for page {page_num}: {err}*")
                lines.append("")
                continue
            if content.text.strip():
                lines.append(demote_headers(content.text.strip()))
                lines.append("")
            for j, d in enumerate(content.diagrams):
                crop_name = f"{out_md.stem}_p{page_num:03d}_fig{j + 1}.png"
                crop_path = asset_dir / crop_name
                if crop_diagram(fp, d.bbox, crop_path):
                    rel = crop_path.relative_to(out_dir).as_posix()
                    lines.append(f"![{d.caption}]({rel})")
                    lines.append(f"*{d.caption}*")
                    lines.append("")

        out_md.write_text("\n".join(lines), encoding="utf-8")
        print(f"\nwrote {out_md}", file=sys.stderr)
        print(f"assets in {asset_dir}", file=sys.stderr)

    return out_md
