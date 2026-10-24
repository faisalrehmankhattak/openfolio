"""Document and image parsers. They run only inside the sandbox subprocess (sandbox.py).

Each parser reads a file the member uploaded (untrusted), and either returns a small dict or raises
ParseError with a short code that the Studio turns into a friendly message. Heavy libraries are
imported inside the function, so the subprocess loads only what one file needs.
"""

from __future__ import annotations

import re
import unicodedata
import warnings
import zipfile
from pathlib import Path
from typing import Any

MAX_TEXT_CHARS = 40_000  # what the drafting model sees from one file
PDF_MAX_PAGES = 30
DOCX_MAX_ENTRIES = 300
DOCX_MAX_UNCOMPRESSED = 25 * 1024 * 1024
IMAGE_MAX_PIXELS = 40_000_000
PHOTO_SIZE = 512
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class ParseError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def tidy(text: str) -> str:
    """NFC, no control or invisible format characters, at most one blank line in a row, capped."""
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch) not in ("Cc", "Cf", "Co", "Cs"))
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:MAX_TEXT_CHARS]


def parse_pdf(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    # A PDF ends with %%EOF; anything after it (a ZIP or script appended to make a polyglot) is refused.
    if not data.startswith(b"%PDF-") or not data[-1024:].rstrip(b"\r\n\t \x00").endswith(b"%%EOF"):
        raise ParseError("pdf_malformed")
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(path, strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ParseError("pdf_encrypted")
        pages = len(reader.pages)
        if pages > PDF_MAX_PAGES:
            raise ParseError("pdf_pages")
        parts: list[str] = []
        total = 0
        for page in reader.pages:
            chunk = page.extract_text() or ""
            parts.append(chunk)
            total += len(chunk)
            if total > MAX_TEXT_CHARS:
                break
    except ParseError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, AttributeError, IndexError, OSError) as e:
        raise ParseError("pdf_malformed") from e
    return {"text": tidy("\n\n".join(parts)), "pages": pages}


def parse_docx(path: Path) -> dict[str, Any]:
    from defusedxml import ElementTree
    from defusedxml.common import DefusedXmlException

    try:
        with zipfile.ZipFile(path) as zf:
            entries = zf.infolist()
            if len(entries) > DOCX_MAX_ENTRIES:
                raise ParseError("docx_entries")
            # Declared sizes can lie, so the read below is capped as well.
            if sum(e.file_size for e in entries) > DOCX_MAX_UNCOMPRESSED:
                raise ParseError("zip_bomb")
            names = {e.filename for e in entries}
            if "word/document.xml" not in names or "[Content_Types].xml" not in names:
                raise ParseError("docx_not_word")
            info = zf.getinfo("word/document.xml")
            if info.flag_bits & 0x1:
                raise ParseError("docx_encrypted")
            with zf.open(info) as f:
                xml = f.read(DOCX_MAX_UNCOMPRESSED + 1)
            if len(xml) > DOCX_MAX_UNCOMPRESSED:
                raise ParseError("zip_bomb")
    except ParseError:
        raise
    except (zipfile.BadZipFile, zipfile.LargeZipFile, KeyError, OSError, ValueError, NotImplementedError) as e:
        raise ParseError("docx_malformed") from e
    try:
        root = ElementTree.fromstring(xml, forbid_dtd=True)
    except (DefusedXmlException, ElementTree.ParseError, ValueError) as e:
        raise ParseError("docx_malformed") from e
    paragraphs: list[str] = []
    for para in root.iter(f"{_W}p"):
        pieces = []
        for node in para.iter():
            if node.tag == f"{_W}t" and node.text:
                pieces.append(node.text)
            elif node.tag in (f"{_W}tab", f"{_W}br"):
                pieces.append(" ")
        paragraphs.append("".join(pieces))
    return {"text": tidy("\n".join(paragraphs))}


def parse_text(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ParseError("text_encoding") from e
    if _CONTROL.search(text):
        raise ParseError("text_binary")
    return {"text": tidy(text)}


def process_photo(path: Path, out: Path) -> dict[str, Any]:
    """Decode, upright, strip every piece of metadata, square-crop and save a fresh 512 px JPEG."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    Image.MAX_IMAGE_PIXELS = IMAGE_MAX_PIXELS
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    try:
        with Image.open(path) as img:
            if img.format not in ("JPEG", "PNG", "WEBP"):
                raise ParseError("image_type")
            width, height = img.size
            if width * height > IMAGE_MAX_PIXELS:
                raise ParseError("image_pixels")
            if width < 64 or height < 64:
                raise ParseError("image_small")
            if img.format == "JPEG":
                img.draft("RGB", (PHOTO_SIZE * 2, PHOTO_SIZE * 2))  # decode at a reduced scale: faster, less memory
            img.seek(0)  # the first frame of an animation
            upright = ImageOps.exif_transpose(img)
            if upright.mode in ("RGBA", "LA", "P"):
                rgba = upright.convert("RGBA")
                flat = Image.new("RGB", rgba.size, (255, 255, 255))
                flat.paste(rgba, mask=rgba.getchannel("A"))
                upright = flat
            square = ImageOps.fit(upright.convert("RGB"), (PHOTO_SIZE, PHOTO_SIZE), Image.Resampling.LANCZOS)
    except ParseError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as e:
        raise ParseError("image_pixels") from e
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, EOFError) as e:
        raise ParseError("image_malformed") from e
    # A brand-new image carries no EXIF, GPS, ICC or comments from the upload.
    clean = Image.new("RGB", square.size)
    clean.paste(square)
    clean.save(out, "JPEG", quality=86, optimize=True, progressive=True)
    return {"width": PHOTO_SIZE, "height": PHOTO_SIZE}
