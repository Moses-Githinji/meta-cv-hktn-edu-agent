"""PDF export: document flow in, .pdf bytes out (stdlib only).

A minimal PDF writer: A4 pages (portrait, or landscape for tables),
Helvetica family (base-14, never embedded), greedy text wrapping, tables
with a repeated header row, embedded RGB figures, and a footer with page
numbers on every page. Flow blocks are ("h1"|"h2"|"p"|"bullet"|"table"|
"figure") as the Word writer. v1 limits, stated plainly: wrapping uses
estimated character widths (conservative, may break early), table rows are
never split across pages, and figures must be the 8-bit RGB PNGs our own
renderer makes.
"""

from __future__ import annotations

import struct
import zlib

PAGE_W, PAGE_H = 595.0, 842.0
MARGIN = 72.0
LAND_MARGIN = 50.0
FOOTER_Y = 40.0

_TRANSLATE = str.maketrans(
    {
        "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
        "\u2013": "-", "\u2014": "-", "\u2026": "...", "\u00a0": " ",
        "\u00b7": "-", "\u2192": "->", "\u00d7": "x",
    }
)


class PdfError(ValueError):
    pass


def sanitize(text: str) -> str:
    """Transliterate to PDF-safe WinAnsi-ish ASCII (base-14 fonts only)."""
    return str(text).translate(_TRANSLATE).encode("ascii", "replace").decode("ascii")


def _wrap(text: str, size: float, max_width: float) -> list:
    """Greedy wrap on estimated widths (avg 0.55 x size per char)."""
    words, lines, line = str(text).split(), [], ""
    limit = max(int(max_width / (0.55 * size)), 10)
    for word in words:
        trial = f"{line} {word}".strip()
        if len(trial) <= limit or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines or [""]


def _escape(text: str) -> str:
    return sanitize(text).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class _Dims:
    """Page geometry: portrait, or landscape for wide tables."""

    def __init__(self, landscape: bool) -> None:
        self.page_w = PAGE_H if landscape else PAGE_W
        self.page_h = PAGE_W if landscape else PAGE_H
        self.margin = LAND_MARGIN if landscape else MARGIN
        self.content_w = self.page_w - 2 * self.margin


class _Page:
    def __init__(self, dims: _Dims) -> None:
        self.ops: list[str] = []
        self.y = dims.page_h - dims.margin
        self.bottom = dims.margin + 12

    def need(self, height: float) -> bool:
        return self.y - height < self.bottom


def decode_png(data: bytes) -> tuple:
    """Our renderer's PNGs as (width, height, raw-deflate scanlines).

    Only 8-bit RGB, non-interlaced, filter-0 rows — exactly what diagrams/png.py
    emits. Anything else is refused with the reason.
    """
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise PdfError("figure is not a PNG")
    pos, width, height, color, idat = 8, 0, 0, 0, b""
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        if kind == b"IHDR":
            width, height, bit, color, _, _, interlace = struct.unpack(">IIBBBBB", chunk)
            if (bit, color, interlace) != (8, 2, 0):
                raise PdfError("figure PNG must be 8-bit RGB, non-interlaced")
        elif kind == b"IDAT":
            idat += chunk
        elif kind == b"IEND":
            break
        pos += 12 + length
    if not width or not idat:
        raise PdfError("figure PNG has no image data")
    try:
        raw = zlib.decompress(idat)
    except zlib.error as error:
        raise PdfError(f"figure PNG corrupt: {error}") from None
    stride = width * 3 + 1
    if len(raw) != stride * height or any(raw[i * stride] != 0 for i in range(height)):
        raise PdfError("figure PNG uses unsupported row filters")
    stream = zlib.compress(raw)[2:-4]  # raw deflate; PDF re-adds PNG prediction
    return width, height, stream


def build_pdf(title: str, flow: list, footer: str, landscape: bool = False) -> bytes:
    """(title, flow, footer) -> .pdf bytes (landscape for wide tables)."""
    dims = _Dims(landscape)
    images: list[tuple] = []
    for kind, payload in flow:
        if kind == "figure":
            width, height, stream = decode_png(payload["png"])
            images.append((payload, width, height, stream))

    pages = [_Page(dims)]
    title_lines = _wrap(title, 16, dims.content_w)
    _heading(pages, dims, title_lines, 16, bold=True, center=True)
    figure_no = 0
    for kind, payload in flow:
        if kind == "figure":
            _, width, height, _ = images[figure_no]
            _figure(pages, dims, payload["caption"], width, height, figure_no)
            figure_no += 1
        elif kind in ("h1", "h2"):
            size = 14 if kind == "h1" else 12
            _heading(pages, dims, _wrap(payload, size, dims.content_w), size, bold=True)
        elif kind == "table":
            _table(pages, dims, payload)
        else:
            prefix = "- " if kind == "bullet" else ""
            for line in _wrap(prefix + payload, 11, dims.content_w):
                _text_line(pages, dims, line, 11, bold=False)

    # Fixed numbering: 1 catalog, 2 pages, 3 helvetica, 4 helvetica-bold,
    # then per page (page, content), then images.
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
    ]
    page_ids, content_ids = [], []
    for _ in pages:
        page_ids.append(len(objects) + 1)
        content_ids.append(len(objects) + 2)
        objects.extend([b"", b""])
    image_ids = []
    for _ in images:
        image_ids.append(len(objects) + 1)
        objects.append(b"")
    kids = " ".join(f"{i} 0 R" for i in page_ids)
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode()
    image_id_by_index = {n: image_ids[n] for n in range(len(images))}

    for n, page in enumerate(pages):
        ops = "\n".join(page.ops)
        footer_text = _escape(f"{footer} - page {n + 1}")
        ops += f"\nBT /F1 9 Tf {dims.margin} {FOOTER_Y} Td ({footer_text}) Tj ET"
        stream = ops.encode("ascii")
        objects[page_ids[n] - 1] = _page_object(
            dims, page_ids[n], content_ids[n], image_id_by_index
        )
        objects[content_ids[n] - 1] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
        )
    for n, (_, width, height, stream) in enumerate(images):
        objects[image_ids[n] - 1] = (
            f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
            "/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode "
            f"/DecodeParms << /Predictor 12 /Columns {width} /Colors 3 "
            "/BitsPerComponent 8 >> /Length {len(stream)} >>\nstream\n".encode()
            + stream
            + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{n} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.extend(f"{offset:010d} 00000 n \n".encode())
    out.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)


def _table(pages: list, dims: _Dims, payload: dict) -> None:
    """A grid table: header row repeated on every page, rows kept whole."""
    head = [str(c) for c in payload.get("head", [])]
    widths = [float(w) for w in payload.get("widths", [])]
    align = list(payload.get("align", []))
    rows = [[str(c) for c in r] for r in payload.get("rows", [])]
    if not head or len(widths) != len(head):
        raise PdfError("table needs a head row and one width per column")
    total = sum(widths)
    if total <= 0:
        raise PdfError("table widths must sum above zero")
    size, leading, pad = 9.0, 11.5, 3.0
    cols = [dims.content_w * w / total for w in widths]
    xs = [dims.margin]
    for width in cols[:-1]:
        xs.append(xs[-1] + width)

    def wrapped(row: list) -> list:
        return [_wrap(cell, size, max(cols[i] - 2 * pad, 10)) for i, cell in enumerate(row)]

    def row_height(lines: list) -> float:
        return max(len(cell) for cell in lines) * leading + 2 * pad

    def draw_row(page: _Page, lines: list, height: float, header: bool) -> None:
        top = page.y
        for i, cell in enumerate(lines):
            x = xs[i]
            if header:
                page.ops.append(
                    f"0.85 0.88 0.95 rg {x:.1f} {top - height:.1f} {cols[i]:.1f} {height:.1f} re f 0 g"
                )
            font = "F2" if header else "F1"
            for n, line in enumerate(cell):
                text_w = len(line) * 0.55 * size
                extra = (cols[i] - 2 * pad - text_w) / 2 if align[i : i + 1] == ["center"] else 0
                page.ops.append(
                    f"BT /{font} {size:.0f} Tf {x + pad + max(extra, 0):.1f} "
                    f"{top - pad - (n + 1) * leading + 2:.1f} Td ({_escape(line)}) Tj ET"
                )
            page.ops.append(
                f"0.6 G 0.5 w {x:.1f} {top - height:.1f} {cols[i]:.1f} {height:.1f} re S"
            )
        page.ops.append("0 G")
        page.y = top - height

    header_lines = wrapped(head)
    header_height = row_height(header_lines)
    pages[-1].y -= 4
    page = _new_page_if_needed(pages, dims, header_height)
    draw_row(page, header_lines, header_height, True)
    for row in rows:
        lines = wrapped(row + [""] * (len(head) - len(row)))
        height = row_height(lines)
        if pages[-1].need(height + header_height):
            pages.append(_Page(dims))
            draw_row(pages[-1], header_lines, header_height, True)
        draw_row(pages[-1], lines, height, False)
    pages[-1].y -= 4


def _page_object(dims: _Dims, page_id: int, content_id: int, image_ids: dict) -> bytes:
    resources = "/Font << /F1 3 0 R /F2 4 0 R >>"
    if image_ids:
        xobjects = " ".join(f"/Im{n} {i} 0 R" for n, i in image_ids.items())
        resources += f" /XObject << {xobjects} >>"
    return (
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {dims.page_w:.0f} {dims.page_h:.0f}] "
        f"/Resources << {resources} >> /Contents {content_id} 0 R >>"
    ).encode()


def _new_page_if_needed(pages: list, dims: _Dims, height: float) -> _Page:
    if pages[-1].need(height):
        pages.append(_Page(dims))
    return pages[-1]


def _text_line(
    pages: list, dims: _Dims, text: str, size: float, bold: bool, center: bool = False
) -> None:
    page = _new_page_if_needed(pages, dims, size * 1.3)
    font = "F2" if bold else "F1"
    x = dims.margin
    if center:
        x = dims.margin + max(dims.content_w - len(text) * 0.55 * size, 0) / 2
    page.ops.append(
        f"BT /{font} {size:.0f} Tf {x:.1f} {page.y:.1f} Td ({_escape(text)}) Tj ET"
    )
    page.y -= size * 1.3


def _heading(
    pages: list, dims: _Dims, lines: list, size: float, bold: bool, center: bool = False
) -> None:
    pages[-1].y -= 6
    for line in lines:
        _text_line(pages, dims, line, size, bold, center)
    pages[-1].y -= 2


def _figure(
    pages: list, dims: _Dims, caption: str, width: int, height: int, index: int
) -> None:
    draw_w = min(dims.content_w, 360.0)
    draw_h = draw_w * height / width
    page = _new_page_if_needed(pages, dims, draw_h + 30)
    x = dims.margin + (dims.content_w - draw_w) / 2
    y = page.y - draw_h
    page.ops.append(f"q {draw_w:.1f} 0 0 {draw_h:.1f} {x:.1f} {y:.1f} cm /Im{index} Do Q")
    page.y = y - 14
    _text_line(pages, dims, caption, 10, bold=True, center=True)
