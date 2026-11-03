"""PNG renderer: drawings in, PNG bytes out (stdlib only).

A tiny rasterizer (lines, rects, circles, 5x7 label text) plus a minimal PNG
encoder, so figures embed in Word and PDF exports without new dependencies.
v1 limits, stated plainly: labels render in capitals (the SVG keeps exact
case), one stroke width, no anti-aliasing.
"""

from __future__ import annotations

import struct
import zlib

# 5x7 glyphs ("#" ink, "." paper) for A-Z 0-9 space and .,;:-+()/=%!?'" .
# Lowercase maps to uppercase; anything else renders as "?".
FONT = {
    "A": (".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "B": ("####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."),
    "C": (".###.", "#...#", "#....", "#....", "#....", "#...#", ".###."),
    "D": ("####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."),
    "E": ("#####", "#....", "#....", "####.", "#....", "#....", "#####"),
    "F": ("#####", "#....", "#....", "####.", "#....", "#....", "#...."),
    "G": (".###.", "#...#", "#....", "#.###", "#...#", "#...#", ".###."),
    "H": ("#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "I": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "#####"),
    "J": ("..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."),
    "K": ("#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"),
    "L": ("#....", "#....", "#....", "#....", "#....", "#....", "#####"),
    "M": ("#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"),
    "N": ("#...#", "##..#", "##..#", "#.#.#", "#..##", "#..##", "#...#"),
    "O": (".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "P": ("####.", "#...#", "#...#", "####.", "#....", "#....", "#...."),
    "Q": (".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"),
    "R": ("####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"),
    "S": (".####", "#....", "#....", ".###.", "....#", "....#", "####."),
    "T": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
    "U": ("#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "V": ("#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."),
    "W": ("#...#", "#...#", "#...#", "#.#.#", "#.#.#", "##.##", "#...#"),
    "X": ("#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"),
    "Y": ("#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."),
    "Z": ("#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"),
    "0": (".###.", "#..##", "#.#.#", "#.#.#", "##..#", "#...#", ".###."),
    "1": ("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", "#####"),
    "2": (".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"),
    "3": ("####.", "....#", "....#", ".###.", "....#", "....#", "####."),
    "4": ("...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."),
    "5": ("#####", "#....", "####.", "....#", "....#", "#...#", ".###."),
    "6": (".###.", "#....", "#....", "####.", "#...#", "#...#", ".###."),
    "7": ("#####", "....#", "...#.", "..#..", "..#..", "..#..", "..#.."),
    "8": (".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."),
    "9": (".###.", "#...#", "#...#", ".####", "....#", "....#", ".###."),
    " ": (".....", ".....", ".....", ".....", ".....", ".....", "....."),
    ".": (".....", ".....", ".....", ".....", ".....", ".##..", ".##.."),
    ",": (".....", ".....", ".....", ".....", ".##..", ".##..", ".#..."),
    ":": (".....", ".##..", ".##..", ".....", ".##..", ".##..", "....."),
    ";": (".....", ".##..", ".##..", ".....", ".##..", ".##..", ".#..."),
    "-": (".....", ".....", ".....", "#####", ".....", ".....", "....."),
    "+": (".....", "..#..", "..#..", "#####", "..#..", "..#..", "....."),
    "(": ("...#.", "..#..", ".#...", ".#...", ".#...", "..#..", "...#."),
    ")": (".#...", "..#..", "...#.", "...#.", "...#.", "..#..", ".#..."),
    "/": ("....#", "....#", "...#.", "..#..", ".#...", "#....", "#...."),
    "%": ("##..#", "##..#", "...#.", "..#..", ".#...", "#..##", "#..##"),
    "=": (".....", ".....", "#####", ".....", "#####", ".....", "....."),
    "!": ("..#..", "..#..", "..#..", "..#..", "..#..", ".....", "..#.."),
    "?": (".###.", "#...#", "....#", "...#.", "..#..", ".....", "..#.."),
    "'": ("..#..", "..#..", ".....", ".....", ".....", ".....", "....."),
    '"': (".#.#.", ".#.#.", ".....", ".....", ".....", ".....", "....."),
}

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GRID = (204, 204, 204)


class Canvas:
    """An RGB canvas with clipped drawing primitives."""

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.pixels = bytearray(WHITE * width * height)

    def set(self, x: int, y: int, color: tuple) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            i = (y * self.width + x) * 3
            self.pixels[i : i + 3] = bytes(color)

    def line(self, x1: int, y1: int, x2: int, y2: int, color: tuple) -> None:
        dx, dy = abs(x2 - x1), abs(y2 - y1)
        sx, sy = (1 if x2 >= x1 else -1), (1 if y2 >= y1 else -1)
        x, y, err = x1, y1, dx - dy
        while True:
            for ox in (0, 1):
                for oy in (0, 1):
                    self.set(x + ox, y + oy, color)
            if x == x2 and y == y2:
                return
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy

    def rect(self, x: int, y: int, w: int, h: int, color: tuple) -> None:
        self.line(x, y, x + w, y, color)
        self.line(x + w, y, x + w, y + h, color)
        self.line(x + w, y + h, x, y + h, color)
        self.line(x, y + h, x, y, color)

    def circle(self, cx: int, cy: int, r: int, color: tuple, fill: bool) -> None:
        x, y, err = r, 0, 1 - r
        plotted: set[tuple[int, int]] = set()
        while x >= y:
            for sx, sy in ((x, y), (y, x), (-x, y), (-y, x), (x, -y), (y, -x), (-x, -y), (-y, -x)):
                plotted.add((cx + sx, cy + sy))
            y += 1
            if err < 0:
                err += 2 * y + 1
            else:
                x -= 1
                err += 2 * (y - x) + 1
        if fill:
            rows: dict[int, list[int]] = {}
            for px, py in plotted:
                rows.setdefault(py, []).append(px)
            for py, cols in rows.items():
                for px in range(min(cols), max(cols) + 1):
                    self.set(px, py, color)
        for px, py in plotted:
            for ox in (0, 1):
                for oy in (0, 1):
                    self.set(px + ox, py + oy, color)

    def text(self, x: int, y: int, text: str, size: int, color: tuple) -> None:
        for n, char in enumerate(str(text).upper()):
            glyph = FONT.get(char, FONT["?"])
            for row, bits in enumerate(glyph):
                for col, bit in enumerate(bits):
                    if bit == "#":
                        for ox in range(size):
                            for oy in range(size):
                                self.set(
                                    x + n * 6 * size + col * size + ox,
                                    y + row * size + oy,
                                    color,
                                )


def rasterize(drawing: dict) -> Canvas:
    """Draw every primitive onto a canvas."""
    canvas = Canvas(drawing["width"], drawing["height"])
    for primitive in drawing["primitives"]:
        shape = primitive["shape"]
        if shape == "line":
            canvas.line(
                primitive["x1"], primitive["y1"], primitive["x2"], primitive["y2"],
                GRID if primitive.get("tone") == "grid" else BLACK,
            )
        elif shape == "rect":
            canvas.rect(primitive["x"], primitive["y"], primitive["w"], primitive["h"], BLACK)
        elif shape == "circle":
            canvas.circle(
                primitive["cx"], primitive["cy"], primitive["r"], BLACK,
                bool(primitive.get("fill")),
            )
        else:
            # Same rule as the SVG renderer: the title is centred.
            size = primitive.get("size", 1)
            x = primitive["x"]
            if primitive.get("el") == "frame" and size > 1:
                x -= len(str(primitive["text"])) * 6 * size // 2
            canvas.text(x, primitive["y"], primitive["text"], size, BLACK)
    return canvas


def encode_png(canvas: Canvas) -> bytes:
    """A canvas as PNG bytes (8-bit RGB, filter 0, no interlace)."""
    rows = b"".join(
        b"\x00" + bytes(canvas.pixels[y * canvas.width * 3 : (y + 1) * canvas.width * 3])
        for y in range(canvas.height)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", canvas.width, canvas.height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(bytes(rows)))
        + _chunk(b"IEND", b"")
    )


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def render(drawing: dict) -> bytes:
    """A drawing (see layout.py) as PNG bytes."""
    return encode_png(rasterize(drawing))
