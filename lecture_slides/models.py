"""Pydantic models and prompts for slide content extraction."""

from pydantic import BaseModel, Field


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


VLM_PROMPT = """Transcribe this lecture slide into well-formatted markdown.

- `text`: verbatim content exactly as shown, formatted as clean markdown.

  FORMATTING RULES (critical):
  - Use `#` for the slide title and `##`+ for any sub-headings.
  - Each bullet point MUST be on its own line, prefixed with `- ` or `* `.
  - Separate paragraphs and distinct blocks of text with a blank line.
  - Display math (centered equations) MUST use `$$...$$` on its own line,
    with blank lines before and after.
  - Inline math uses `$...$`.
  - Preserve code blocks with triple backticks.
  - Do NOT run separate sentences or ideas together on one line. If text
    appears on separate lines in the slide, keep them on separate lines.

  COMPLETENESS IS CRITICAL. Before finalizing, count every bullet / line /
  item visible in the image and confirm each one appears in your output. Do
  NOT skip trailing bullets just because they seem like less-important asides
  — transcribe EVERY visible line, even short ones. If a bullet is partially
  cut off but legible, include as much as you can read.

  Do NOT paraphrase or summarize. Preserve exact wording.

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

- `diagrams`: ONLY for actual visual figures that cannot be represented as
  text: plots, graphs, charts, flowcharts, schematics, architecture diagrams,
  photographs, hand-drawn illustrations. Return a bounding box in normalized
  [x1, y1, x2, y2] coords where (0,0) is top-left and (1,1) is bottom-right,
  plus a brief caption.

  DO NOT include as diagrams:
  - Matrices, tables, or grids of numbers (transcribe these as text/math)
  - Equations or mathematical expressions (transcribe as LaTeX)
  - Transition probability matrices (transcribe as text)
  - Simple state labels or numbered lists
  - The presenter's webcam / video feed
  - Logos, institutional crests, page numbers, decorative backgrounds

  Return [] for most slides — only include entries for genuine visual figures
  that lose meaning if not shown as an image."""
