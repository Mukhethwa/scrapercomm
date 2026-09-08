"""Get the timetable picture out of a PRASA PDF page.

Each page carries two images: a small JPEG of the branding, and one large bitmap that is
the entire timetable. The bitmap is stored raw and Flate-compressed rather than as a
JPEG, so PIL cannot open the stream directly - it has to be rebuilt from the pixel bytes
using the width, height and colour space the PDF declares.

No external renderer is needed, which matters: poppler and ghostscript are one more thing
to install on every machine that runs this, and the pages are already images.
"""
from __future__ import annotations

from dataclasses import dataclass

import pdfplumber
from PIL import Image

# Anything smaller than this is branding, not a timetable.
MIN_PIXELS = 800

MODES = {1: "L", 3: "RGB", 4: "CMYK"}


@dataclass
class PageImage:
    """One page's timetable bitmap, with whatever the text layer said about it."""
    page_number: int
    heading: str
    image: Image.Image

    @property
    def size(self) -> tuple[int, int]:
        return self.image.size


def _decode(stream) -> Image.Image | None:
    """Rebuild a PIL image from a PDF image XObject, whatever it is compressed with."""
    attrs = stream.attrs
    try:
        width, height = int(attrs["Width"]), int(attrs["Height"])
    except (KeyError, TypeError, ValueError):
        return None
    if max(width, height) < MIN_PIXELS:
        return None

    try:
        raw = stream.get_data()
    except Exception:      # noqa: BLE001 - an image we cannot decompress is one we skip
        return None

    # A JPEG-compressed page (DCTDecode) is already a file PIL understands.
    import io
    try:
        return Image.open(io.BytesIO(raw))
    except Exception:      # noqa: BLE001 - not a container format; treat it as raw samples
        pass

    per_pixel = len(raw) / (width * height) if width and height else 0
    mode = MODES.get(round(per_pixel))
    if not mode:
        return None
    try:
        return Image.frombytes(mode, (width, height), raw)
    except ValueError:
        return None


def page_images(pdf_path: str) -> list[PageImage]:
    """The timetable bitmap from every page that has one, in page order."""
    out: list[PageImage] = []
    with pdfplumber.open(pdf_path) as pdf:
        for number, page in enumerate(pdf.pages, 1):
            heading = " ".join((page.extract_text() or "").split())
            best: Image.Image | None = None
            for im in page.images:
                stream = im.get("stream")
                if stream is None:
                    continue
                decoded = _decode(stream)
                if decoded is None:
                    continue
                # The timetable is the biggest thing on the page.
                if best is None or decoded.size[0] * decoded.size[1] > best.size[0] * best.size[1]:
                    best = decoded
            if best is not None:
                out.append(PageImage(number, heading, best))
    return out
