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
