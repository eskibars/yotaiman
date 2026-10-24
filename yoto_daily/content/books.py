"""Turning books into text.

Supports ``.mobi``, ``.epub``, ``.pdf``, ``.html`` and a URL.  Each reader
returns a :class:`Book`, which carries the title and the text split into
chapters -- a long book becomes several audio tracks rather than one enormous
one, because the player handles chaptered content far better.

Nothing here needs a network except the URL reader, and every parser degrades
with a clear error rather than a stack trace when its optional dependency is
missing.
"""

from __future__ import annotations

import html
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Rough target length for one spoken chapter, in words.
DEFAULT_CHAPTER_WORDS = 1800


@dataclass
class Book:
    """The extracted contents of a book."""

    title: str = ""
    text: str = ""
    chapters: list[str] = field(default_factory=list)
    source: str = ""
    fmt: str = ""

    @property
    def word_count(self) -> int:
        return len(self.text.split())


class BookError(RuntimeError):
    """Raised when a book cannot be read."""


# ----------------------------------------------------------------------
# text helpers
# ----------------------------------------------------------------------
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_NL_RE = re.compile(r"\n{3,}")


def normalise(text: str) -> str:
    """Collapse whitespace while keeping paragraph breaks."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WS_RE.sub(" ", text)
    text = _NL_RE.sub("\n\n", text)
    return text.strip()


def split_chapters(text: str, max_words: int = DEFAULT_CHAPTER_WORDS) -> list[str]:
    """Split text into chunks of at most ``max_words`` words.

    Paragraph boundaries are preferred, and a chunk is never cut mid-sentence.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return []

    chapters: list[str] = []
    current: list[str] = []
    count = 0

    for para in paragraphs:
        words = len(para.split())
        if count and count + words > max_words:
            chapters.append("\n\n".join(current))
            current, count = [], 0
        # A single enormous paragraph still has to be split.
        if words > max_words:
            sentences = re.split(r"(?<=[.!?])\s+", para)
            for sentence in sentences:
                sw = len(sentence.split())
                if sw > max_words:
                    # One sentence longer than the budget: cut on words.
                    chunk: list[str] = []
                    count = 0
                    for word in sentence.split():
                        if count and count + 1 > max_words:
                            chapters.append(" ".join(chunk))
                            chunk, count = [], 0
                        chunk.append(word)
                        count += 1
                    if chunk:
                        current.append(" ".join(chunk))
                        count = len(chunk)
                    continue
                if count and count + sw > max_words:
                    chapters.append("\n\n".join(current))
                    current, count = [], 0
                current.append(sentence)
                count += sw
            continue
        current.append(para)
        count += words

    if current:
        chapters.append("\n\n".join(current))
    return [c for c in (c.strip() for c in chapters) if c]


def _html_to_text(html_source: str) -> str:
    """Strip tags from HTML, keeping paragraph structure."""
    try:
        from lxml import html as lxml_html

        doc = lxml_html.fromstring(html_source)
        for bad in doc.xpath("//script|//style|//nav|//footer|//header"):
            bad.getparent().remove(bad)
        blocks = []
        for el in doc.xpath("//p|//h1|//h2|//h3|//h4|//h5|//h6|//li|//blockquote|//td"):
            text = " ".join(el.text_content().split())
            if text:
                blocks.append(text)
        if blocks:
            return "\n\n".join(blocks)
        return " ".join(doc.text_content().split())
    except ImportError:
        # No lxml: fall back to a crude tag strip.
        stripped = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html_source)
        stripped = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n\n", stripped)
        stripped = re.sub(r"(?s)<[^>]+>", " ", stripped)
        stripped = html.unescape(stripped)
        return normalise(stripped)


# ----------------------------------------------------------------------
# readers
# ----------------------------------------------------------------------
def read_epub(path: Path) -> Book:
    """Read an EPUB: follow the OPF spine and extract each document."""
    try:
        from xml.etree import ElementTree
    except ImportError:  # pragma: no cover
        raise BookError("epub support requires the stdlib")

    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()

        opf_name = next(
            (n for n in names if n.lower().endswith(".opf")),
            None,
        )
        if opf_name is None:
            raise BookError(f"{path.name} contains no OPF package document")

        opf_dir = str(Path(opf_name).parent)
        root = ElementTree.fromstring(archive.read(opf_name))

        def tag(el: str) -> str:
            return el.rsplit("}", 1)[-1]

        manifest: dict[str, str] = {}
        for item in root.iter():
            if tag(item.tag) == "item":
                item_id = item.get("id")
                href = item.get("href")
                if item_id and href:
                    manifest[item_id] = href

        spine: list[str] = []
        for element in root.iter():
            if tag(element.tag) == "itemref":
                idref = element.get("idref")
                if idref and idref in manifest:
                    spine.append(manifest[idref])

        title = ""
        for element in root.iter():
            if tag(element.tag) == "title" and element.text:
                title = element.text.strip()
                break
        if not title:
            title = path.stem

        documents = spine or [
            n for n in names if n.lower().endswith((".xhtml", ".html", ".htm"))
        ]

        blocks: list[str] = []
        for href in documents:
            member = f"{opf_dir}/{href}" if opf_dir and opf_dir != "." else href
            member = member.replace("//", "/")
            if member not in names:
                candidate = next((n for n in names if n.endswith(href)), None)
                if not candidate:
                    continue
                member = candidate
            try:
                raw = archive.read(member).decode("utf-8", errors="replace")
            except KeyError:
                continue
            text = _html_to_text(raw)
            if text:
                blocks.append(text)

    full = normalise("\n\n".join(blocks))
    if not full:
        raise BookError(f"no readable text found in {path.name}")
    return Book(
        title=title,
        text=full,
        chapters=split_chapters(full),
        source=str(path),
        fmt="epub",
    )


def read_mobi(path: Path) -> Book:
    """Read a Kindle MOBI/AZW file by converting it to EPUB first."""
    try:
        import mobi
    except ImportError as exc:
        raise BookError(
            "mobi support needs the 'mobi' package: pip install mobi"
        ) from exc

    try:
        with path.open("rb") as handle:
            epub_path = mobi.extract(handle)
    except Exception as exc:
        raise BookError(f"could not read {path.name}: {exc}") from exc

    if not epub_path or not Path(epub_path).exists():
        raise BookError(f"mobi extraction produced no output for {path.name}")

    book = read_epub(Path(epub_path))
    book.source = str(path)
    book.fmt = "mobi"
    if not book.title or book.title == path.stem:
        book.title = path.stem.replace("_", " ").replace("-", " ").title()
    return book


def read_pdf(path: Path) -> Book:
    """Read a PDF."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise BookError(
            "pdf support needs the 'pypdf' package: pip install pypdf"
        ) from exc

    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        raise BookError(f"could not read {path.name}: {exc}") from exc

    blocks: list[str] = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if text.strip():
            blocks.append(text.strip())

    full = normalise("\n\n".join(blocks))
    if not full:
        raise BookError(f"no extractable text in {path.name} (it may be scanned images)")

    title = ""
    try:
        meta = reader.metadata or {}
        title = str(meta.get("/Title") or "").strip()
    except Exception:
        title = ""
    if not title:
        title = path.stem.replace("_", " ").replace("-", " ").title()

    return Book(
        title=title,
        text=full,
        chapters=split_chapters(full),
        source=str(path),
        fmt="pdf",
    )


def read_html(path: Path) -> Book:
    """Read an HTML file."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    text = normalise(_html_to_text(raw))
    if not text:
        raise BookError(f"no readable text in {path.name}")

    title = ""
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
    if match:
        title = html.unescape(match.group(1)).strip()
    if not title:
        title = path.stem.replace("_", " ").replace("-", " ").title()

    return Book(
        title=title,
        text=text,
        chapters=split_chapters(text),
        source=str(path),
        fmt="html",
    )


def read_url(url: str, *, timeout: float = 60.0) -> Book:
    """Fetch a URL and read it as HTML, PDF or plain text."""
    import requests

    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "yotaiman/0.1 (book reader)"},
        )
    except Exception as exc:
        raise BookError(f"could not fetch {url}: {exc}") from exc

    if resp.status_code >= 400:
        raise BookError(f"fetching {url} returned HTTP {resp.status_code}")

    content_type = resp.headers.get("Content-Type", "").lower()
    title = url.rsplit("/", 1)[-1] or url

    if "pdf" in content_type or url.lower().endswith(".pdf"):
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            handle.write(resp.content)
            tmp_path = Path(handle.name)
        try:
            book = read_pdf(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)
        book.source = url
        book.fmt = "pdf"
        return book

    if "html" in content_type or "<html" in resp.text[:2000].lower():
        text = normalise(_html_to_text(resp.text))
        match = re.search(r"(?is)<title[^>]*>(.*?)</title>", resp.text)
        if match:
            title = html.unescape(match.group(1)).strip()
    else:
        text = normalise(resp.text)

    if not text:
        raise BookError(f"no readable text at {url}")

    return Book(
        title=title,
        text=text,
        chapters=split_chapters(text),
        source=url,
        fmt="html" if "html" in content_type else "text",
    )


# ----------------------------------------------------------------------
# dispatch
# ----------------------------------------------------------------------
def read_book(source: str | Path, *, max_words: int = DEFAULT_CHAPTER_WORDS) -> Book:
    """Read a book from a path or a URL.

    The format is chosen from the file extension, falling back to sniffing
    the file's magic bytes for formats that lie about their suffix.
    """
    raw = str(source)

    if raw.startswith(("http://", "https://")):
        return read_url(raw)

    path = Path(raw).expanduser()
    if not path.exists():
        raise BookError(f"no such file: {path}")

    suffix = path.suffix.lower()

    if suffix == ".epub":
        return read_epub(path)
    if suffix in (".mobi", ".azw", ".azw3", ".prc"):
        return read_mobi(path)
    if suffix == ".pdf":
        return read_pdf(path)
    if suffix in (".html", ".htm", ".xhtml"):
        return read_html(path)
    if suffix == ".txt":
        text = normalise(path.read_text(encoding="utf-8", errors="replace"))
        return Book(
            title=path.stem.replace("_", " ").title(),
            text=text,
            chapters=split_chapters(text, max_words),
            source=str(path),
            fmt="txt",
        )

    # Unknown suffix: sniff.
    head = path.read_bytes()[:8]
    if head.startswith(b"PK"):
        return read_epub(path)
    if head.startswith(b"%PDF"):
        return read_pdf(path)
    if head[:4] in (b"BOOK", b"TEXt"):
        return read_mobi(path)

    return read_html(path)


def describe_formats() -> list[dict[str, Any]]:
    """Which book formats this installation can actually read."""
    formats = []

    def has(module: str) -> bool:
        try:
            __import__(module)
            return True
        except ImportError:
            return False

    formats.append(
        {
            "format": "epub",
            "available": True,
            "requires": None,
            "note": "built in (zip + OPF spine)",
        }
    )
    formats.append(
        {
            "format": "mobi",
            "available": has("mobi"),
            "requires": "mobi",
            "note": "converted to EPUB first",
        }
    )
    formats.append(
        {
            "format": "pdf",
            "available": has("pypdf"),
            "requires": "pypdf",
            "note": "text-layer PDFs only; scanned images have no text",
        }
    )
    formats.append(
        {
            "format": "html",
            "available": True,
            "requires": None,
            "note": "built in",
        }
    )
    formats.append(
        {
            "format": "url",
            "available": True,
            "requires": None,
            "note": "fetches a URL and reads HTML, PDF or plain text",
        }
    )
    return formats
