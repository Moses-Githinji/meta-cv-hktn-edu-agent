"""Word export: document flow in, .docx bytes out (stdlib only).

A minimal Office Open XML package built with zipfile: headings, paragraphs,
bullets, tables with a repeated header row, embedded PNG figures with
numbered captions, and a footer with page numbers. Flow blocks (see
build.py): ("h1"|"h2"|"p"|"bullet", text), ("table", {"head", "widths",
"align", "rows"}), and ("figure", {"png", "width", "height", "caption"}).
"""

from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape

EMU_PER_INCH = 914400
MAX_WIDTH_IN = 6.0
_PX_PER_INCH = 96.0


class DocxError(ValueError):
    pass


def build_docx(title: str, flow: list, footer: str, landscape: bool = False) -> bytes:
    """(title, flow, footer) -> .docx bytes (landscape for wide tables)."""
    images = [b[1] for b in flow if b[0] == "figure"]
    document, rels = _document(title, flow, landscape)
    package = io.BytesIO()
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _content_types(len(images)))
        archive.writestr("_rels/.rels", _root_rels())
        archive.writestr("word/document.xml", document)
        archive.writestr("word/_rels/document.xml.rels", rels)
        archive.writestr("word/styles.xml", _styles())
        archive.writestr("word/footer1.xml", _footer(footer))
        for n, image in enumerate(images, start=1):
            archive.writestr(f"word/media/figure{n}.png", image["png"])
    return package.getvalue()


def _para(
    text: str,
    style: str | None = None,
    center: bool = False,
    bold: bool = False,
    size: int | None = None,
) -> str:
    props = ""
    if style:
        props += f'<w:pStyle w:val="{style}"/>'
    if center:
        props += "<w:jc w:val=\"center\"/>"
    run = ("<w:b/>" if bold else "") + (f"<w:sz w:val=\"{size}\"/>" if size else "")
    run_props = f"<w:rPr>{run}</w:rPr>" if run else ""
    return (
        f"<w:p>{f'<w:pPr>{props}</w:pPr>' if props else ''}"
        f"<w:r>{run_props}<w:t xml:space=\"preserve\">{escape(text)}</w:t></w:r></w:p>"
    )


def _figure_para(image: dict, rel_id: str) -> str:
    width_in = min(image["width"] / _PX_PER_INCH, MAX_WIDTH_IN)
    scale = width_in / (image["width"] / _PX_PER_INCH)
    cx, cy = int(width_in * EMU_PER_INCH), int(image["height"] / _PX_PER_INCH * scale * EMU_PER_INCH)
    return (
        "<w:p><w:pPr><w:jc w:val=\"center\"/></w:pPr><w:r><w:drawing><wp:inline "
        f'distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
        '<wp:docPr id="1" name="figure"/>'
        '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        "<pic:nvPicPr><pic:cNvPr id=\"1\" name=\"\"/><pic:cNvPicPr/></pic:nvPicPr>"
        f'<pic:blipFill><a:blip r:embed="{rel_id}"/></pic:blipFill>'
        f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/>'
        "</a:xfrm><a:prstGeom prst=\"rect\"/></pic:spPr>"
        "</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>"
    )


def _table(payload: dict, landscape: bool) -> str:
    """A grid table: fixed column widths, bold shaded header repeated by Word."""
    head = [str(c) for c in payload.get("head", [])]
    widths = [float(w) for w in payload.get("widths", [])]
    align = list(payload.get("align", []))
    rows = [[str(c) for c in r] for r in payload.get("rows", [])]
    if not head or len(widths) != len(head):
        raise DocxError("table needs a head row and one width per column")
    total = sum(widths)
    if total <= 0:
        raise DocxError("table widths must sum above zero")
    usable = (16838 - 2 * 720) if landscape else (11906 - 2 * 1440)
    cols = [max(int(usable * w / total), 100) for w in widths]
    grid = "".join(f'<w:gridCol w:w="{c}"/>' for c in cols)
    borders = "".join(
        f'<w:{edge} w:val="single" w:sz="4" w:space="0" w:color="999999"/>'
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV")
    )

    def row(cells: list, header: bool) -> str:
        parts = []
        for i, cell in enumerate(cells):
            shade = '<w:shd w:val="clear" w:fill="D9E2F3"/>' if header else ""
            parts.append(
                f"<w:tc><w:tcPr><w:tcW w:w=\"{cols[i]}\" w:type=\"dxa\"/>{shade}</w:tcPr>"
                f"{_para(cell, center=align[i : i + 1] == ['center'], bold=header, size=18)}</w:tc>"
            )
        repeat = "<w:trPr><w:tblHeader/></w:trPr>" if header else ""
        return f"<w:tr>{repeat}{''.join(parts)}</w:tr>"

    body = row(head, True)
    for cells in rows:
        body += row((cells + [""] * len(head))[: len(head)], False)
    return (
        "<w:tbl><w:tblPr><w:tblStyle w:val=\"TableGrid\"/>"
        f"<w:tblW w:w=\"{sum(cols)}\" w:type=\"dxa\"/><w:tblBorders>{borders}</w:tblBorders>"
        f"</w:tblPr><w:tblGrid>{grid}</w:tblGrid>{body}</w:tbl>"
    )


def _document(title: str, flow: list, landscape: bool = False) -> tuple:
    parts = [_para(title, style="Title", center=True)]
    rels = [
        '<Relationship Id="rIdFooter" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" '
        'Target="footer1.xml"/>'
    ]
    figure_n = 0
    for kind, payload in flow:
        if kind == "h1":
            parts.append(_para(payload, style="Heading1"))
        elif kind == "h2":
            parts.append(_para(payload, style="Heading2"))
        elif kind == "bullet":
            parts.append(_para(payload, style="ListBullet"))
        elif kind == "table":
            parts.append(_table(payload, landscape))
        elif kind == "figure":
            figure_n += 1
            rel_id = f"rIdFigure{figure_n}"
            rels.append(
                f'<Relationship Id="{rel_id}" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
                f'Target="media/figure{figure_n}.png"/>'
            )
            parts.append(_figure_para(payload, rel_id))
            parts.append(_para(payload["caption"], center=True, bold=True))
        else:
            parts.append(_para(payload))
    if landscape:
        sect = (
            "<w:sectPr>"
            '<w:pgSz w:w="16838" w:h="11906" w:orient="landscape"/>'
            '<w:pgMar w:top="720" w:right="720" w:bottom="720" w:left="720"/>'
            '<w:footerReference w:type="default" r:id="rIdFooter"/>'
            "<w:pgNumType/></w:sectPr>"
        )
    else:
        sect = (
            "<w:sectPr><w:pgSz w:w=\"11906\" w:h=\"16838\"/>"
            '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/>'
            '<w:footerReference w:type="default" r:id="rIdFooter"/>'
            "<w:pgNumType/></w:sectPr>"
        )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
        f"<w:body>{''.join(parts)}{sect}</w:body></w:document>"
    )
    rels_doc = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{''.join(rels)}</Relationships>"
    )
    return document, rels_doc


def _content_types(figures: int) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="png" ContentType="image/png"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        '<Override PartName="/word/footer1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
        "</Types>"
    )


def _root_rels() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/></Relationships>'
    )


def _styles() -> str:
    def style(name: str, size: int, bold: bool = False) -> str:
        return (
            f'<w:style w:type="paragraph" w:styleId="{name}"><w:name w:val="{name}"/>'
            f"<w:rPr><w:sz w:val=\"{size}\"/>{'<w:b/>' if bold else ''}</w:rPr></w:style>"
        )

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        + style("Normal", 22)
        + style("Title", 44, True)
        + style("Heading1", 32, True)
        + style("Heading2", 26, True)
        + style("ListBullet", 22)
        + "</w:styles>"
    )


def _footer(text: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:p><w:pPr><w:jc w:val=\"center\"/></w:pPr>"
        f"<w:r><w:t xml:space=\"preserve\">{escape(text)} — page </w:t></w:r>"
        '<w:r><w:fldSimple w:instr="PAGE"/></w:r>'
        "</w:p></w:ftr>"
    )
