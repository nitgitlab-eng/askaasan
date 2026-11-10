"""A small, dependency-free QR Code encoder (ISO/IEC 18004, byte mode, versions 1-40).

Written for guest-link QR codes: encode() returns a square matrix of booleans (True = dark), svg() and png()
render it with the mandatory 4-module quiet zone. The algorithm follows the standard step by step:
bit stream → Reed-Solomon error correction + interleaving → function patterns → zig-zag placement → masking
(lowest penalty wins) → format/version information."""

from __future__ import annotations

import io

# Error-correction levels: index into the tables below, and the 2-bit format code.
ECL = {"L": (0, 1), "M": (1, 0), "Q": (2, 3), "H": (3, 2)}

# Per version (index 1..40; index 0 unused): EC codewords per block, and number of EC blocks.
ECC_PER_BLOCK = (
    (
        -1,
        7,
        10,
        15,
        20,
        26,
        18,
        20,
        24,
        30,
        18,
        20,
        24,
        26,
        30,
        22,
        24,
        28,
        30,
        28,
        28,
        28,
        28,
        30,
        30,
        26,
        28,
        30,
        30,
        30,
        30,
        30,
        30,
        30,
        30,
        30,
        30,
        30,
        30,
        30,
        30,
    ),
    (
        -1,
        10,
        16,
        26,
        18,
        24,
        16,
        18,
        22,
        22,
        26,
        30,
        22,
        22,
        24,
        24,
        28,
        28,
        26,
        26,
        26,
        26,
        28,
        28,
        28,
        28,
        28,
        28,
        28,
        28,
        28,
        28,
        28,
        28,
        28,
        28,
        28,
        28,
        28,
        28,
        28,
    ),
    (
        -1,
        13,
        22,
        18,
        26,
        18,
        24,
        18,
        22,
        20,
        24,
        28,
        26,
        24,
        20,
        30,
        24,
        28,
        28,
        26,
        30,
        28,
        30,
        30,
        30,
        30,
        28,
        30,
        30,
        30,
        30,
        30,
        30,
        30,
        30,
        30,
        30,
        30,
        30,
        30,
        30,
    ),
    (
        -1,
        17,
        28,
        22,
        16,
        22,
        28,
        26,
        26,
        24,
        28,
        24,
        28,
        22,
        24,
        24,
        30,
        28,
        28,
        26,
        28,
        30,
        24,
        30,
        30,
        30,
        30,
        30,
        30,
        30,
        30,
        30,
        30,
        30,
        30,
        30,
        30,
        30,
        30,
        30,
        30,
    ),
)
NUM_BLOCKS = (
    (
        -1,
        1,
        1,
        1,
        1,
        1,
        2,
        2,
        2,
        2,
        4,
        4,
        4,
        4,
        4,
        6,
        6,
        6,
        6,
        7,
        8,
        8,
        9,
        9,
        10,
        12,
        12,
        12,
        13,
        14,
        15,
        16,
        17,
        18,
        19,
        19,
        20,
        21,
        22,
        24,
        25,
    ),
    (
        -1,
        1,
        1,
        1,
        2,
        2,
        4,
        4,
        4,
        5,
        5,
        5,
        8,
        9,
        9,
        10,
        10,
        11,
        13,
        14,
        16,
        17,
        17,
        18,
        20,
        21,
        23,
        25,
        26,
        28,
        29,
        31,
        33,
        35,
        37,
        38,
        40,
        43,
        45,
        47,
        49,
    ),
    (
        -1,
        1,
        1,
        2,
        2,
        4,
        4,
        6,
        6,
        8,
        8,
        8,
        10,
        12,
        16,
        12,
        17,
        16,
        18,
        21,
        20,
        23,
        23,
        25,
        27,
        29,
        34,
        34,
        35,
        38,
        40,
        43,
        45,
        48,
        51,
        53,
        56,
        59,
        62,
        65,
        68,
    ),
    (
        -1,
        1,
        1,
        2,
        4,
        4,
        4,
        5,
        6,
        8,
        8,
        11,
        11,
        16,
        16,
        18,
        16,
        19,
        21,
        25,
        25,
        25,
        34,
        30,
        32,
        35,
        37,
        40,
        42,
        45,
        48,
        51,
        54,
        57,
        60,
        63,
        66,
        70,
        74,
        77,
        81,
    ),
)


class DataTooLong(ValueError):
    pass


# ── Reed-Solomon over GF(2^8), polynomial 0x11D ──────────────────────


def _gf_mul(x: int, y: int) -> int:
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def rs_divisor(degree: int) -> list[int]:
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 0x02)
    return result


def rs_remainder(data: list[int], divisor: list[int]) -> list[int]:
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return result


# ── Capacity ─────────────────────────────────────────────────────────


def raw_data_modules(ver: int) -> int:
    result = (16 * ver + 128) * ver + 64
    if ver >= 2:
        n = ver // 7 + 2
        result -= (25 * n - 10) * n - 55
        if ver >= 7:
            result -= 36
    return result


def data_codewords(ver: int, ecl: str) -> int:
    e = ECL[ecl][0]
    return raw_data_modules(ver) // 8 - ECC_PER_BLOCK[e][ver] * NUM_BLOCKS[e][ver]


def alignment_positions(ver: int) -> list[int]:
    if ver == 1:
        return []
    n = ver // 7 + 2
    step = (ver * 8 + n * 3 + 5) // (n * 4 - 4) * 2
    size = ver * 4 + 17
    result = [size - 7 - i * step for i in range(n - 1)] + [6]
    return sorted(result)


# ── Encoder ──────────────────────────────────────────────────────────


def _codewords(data: bytes, ver: int, ecl: str) -> list[int]:
    bits: list[int] = []

    def put(val: int, n: int):
        bits.extend((val >> i) & 1 for i in reversed(range(n)))

    put(0b0100, 4)  # byte mode
    put(len(data), 8 if ver < 10 else 16)
    for b in data:
        put(b, 8)
    capacity = data_codewords(ver, ecl) * 8
    put(0, min(4, capacity - len(bits)))  # terminator
    put(0, -len(bits) % 8)
    pad = 0xEC
    while len(bits) < capacity:
        put(pad, 8)
        pad ^= 0xEC ^ 0x11
    words = [int("".join(map(str, bits[i : i + 8])), 2) for i in range(0, len(bits), 8)]

    e = ECL[ecl][0]
    nblocks, ecc_len = NUM_BLOCKS[e][ver], ECC_PER_BLOCK[e][ver]
    raw = raw_data_modules(ver) // 8
    nshort = nblocks - raw % nblocks
    short_len = raw // nblocks
    div = rs_divisor(ecc_len)
    blocks, k = [], 0
    for i in range(nblocks):
        dat = words[k : k + short_len - ecc_len + (0 if i < nshort else 1)]
        k += len(dat)
        ecc = rs_remainder(dat, div)
        if i < nshort:
            dat = [*dat, 0]  # placeholder so all blocks have equal length while interleaving
        blocks.append(dat + ecc)
    out = []
    for i in range(len(blocks[0])):
        for j, blk in enumerate(blocks):
            if i != short_len - ecc_len or j >= nshort:
                out.append(blk[i])
    return out


def _format_bits(ecl: str, mask: int) -> int:
    data = ECL[ecl][1] << 3 | mask
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    return (data << 10 | rem) ^ 0x5412


def _version_bits(ver: int) -> int:
    rem = ver
    for _ in range(12):
        rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
    return ver << 12 | rem


MASKS = (
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
)


class _Grid:
    def __init__(self, ver: int):
        self.ver, self.size = ver, ver * 4 + 17
        self.m = [[False] * self.size for _ in range(self.size)]
        self.fn = [[False] * self.size for _ in range(self.size)]

    def set_fn(self, x: int, y: int, dark: bool):
        self.m[y][x] = dark
        self.fn[y][x] = True

    def function_patterns(self):
        n = self.size
        for i in range(n):
            self.set_fn(6, i, i % 2 == 0)
            self.set_fn(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < n and 0 <= y < n:
                        self.set_fn(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        pos = alignment_positions(self.ver)
        last = len(pos) - 1
        for i, ax in enumerate(pos):
            for j, ay in enumerate(pos):
                if (i, j) in ((0, 0), (0, last), (last, 0)):
                    continue  # overlaps a finder pattern
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set_fn(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)
        self.format_info("M", 0)  # reserve the areas; real bits are drawn after masking
        if self.ver >= 7:
            bits = _version_bits(self.ver)
            for i in range(18):
                bit = (bits >> i) & 1 == 1
                a, b = n - 11 + i % 3, i // 3
                self.set_fn(a, b, bit)
                self.set_fn(b, a, bit)

    def format_info(self, ecl: str, mask: int):
        n, bits = self.size, _format_bits(ecl, mask)

        def bit(i):
            return (bits >> i) & 1 == 1

        for i in range(6):
            self.set_fn(8, i, bit(i))
        self.set_fn(8, 7, bit(6))
        self.set_fn(8, 8, bit(7))
        self.set_fn(7, 8, bit(8))
        for i in range(9, 15):
            self.set_fn(14 - i, 8, bit(i))
        for i in range(8):
            self.set_fn(n - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.set_fn(8, n - 15 + i, bit(i))
        self.set_fn(8, n - 8, True)  # the "dark module"

    def place(self, words: list[int]):
        n, i, total = self.size, 0, len(words) * 8
        right = n - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(n):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = n - 1 - vert if upward else vert
                    if not self.fn[y][x] and i < total:
                        self.m[y][x] = (words[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def apply_mask(self, mask: int):
        f = MASKS[mask]
        for y in range(self.size):
            for x in range(self.size):
                if not self.fn[y][x] and f(x, y):
                    self.m[y][x] = not self.m[y][x]


def penalty(m: list[list[bool]]) -> int:
    """ISO penalty score (N1=3, N2=3, N3=40, N4=10)."""
    n, score = len(m), 0
    lines = m + [list(col) for col in zip(*m, strict=True)]
    for line in lines:
        run, prev = 0, None
        for v in line:
            if v == prev:
                run += 1
            else:
                if run >= 5:
                    score += 3 + run - 5
                run, prev = 1, v
        if run >= 5:
            score += 3 + run - 5
        s = "".join("1" if v else "0" for v in line)
        padded = "0000" + s + "0000"  # the quiet zone counts as light
        for pat in ("10111010000", "00001011101"):
            start = padded.find(pat)
            while start != -1:
                score += 40
                start = padded.find(pat, start + 1)
    for y in range(n - 1):
        for x in range(n - 1):
            if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                score += 3
    dark = sum(v for row in m for v in row)
    total = n * n
    k = (abs(dark * 20 - total * 10) + total - 1) // total - 1
    return score + k * 10


def encode(
    text: str | bytes, ecl: str = "M", mask: int | None = None, min_version: int = 1
) -> list[list[bool]]:
    data = text.encode("utf-8") if isinstance(text, str) else bytes(text)
    for ver in range(max(1, min_version), 41):
        header = 4 + (8 if ver < 10 else 16)
        if header + 8 * len(data) <= data_codewords(ver, ecl) * 8:
            break
    else:
        raise DataTooLong(len(data))
    words = _codewords(data, ver, ecl)
    best, best_score = None, None
    for msk in range(8) if mask is None else (mask,):
        g = _Grid(ver)
        g.function_patterns()
        g.place(words)
        g.apply_mask(msk)
        g.format_info(ecl, msk)
        s = penalty(g.m) if mask is None else 0
        if best_score is None or s < best_score:
            best, best_score = g.m, s
    return best


# ── Rendering ────────────────────────────────────────────────────────

QUIET = 4


def svg(matrix: list[list[bool]], scale: int = 8, dark: str = "#000000", light: str = "#ffffff") -> str:
    n = len(matrix)
    size = (n + 2 * QUIET) * scale
    parts = []
    for y, row in enumerate(matrix):
        for x, v in enumerate(row):
            if v:
                parts.append(f"M{x + QUIET},{y + QUIET}h1v1h-1z")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {n + 2 * QUIET} '
        f'{n + 2 * QUIET}" shape-rendering="crispEdges"><rect width="100%" height="100%" fill="{light}"/>'
        f'<path d="{"".join(parts)}" fill="{dark}"/></svg>'
    )


def png(matrix: list[list[bool]], scale: int = 10) -> bytes:
    from PIL import Image

    n = len(matrix) + 2 * QUIET
    img = Image.new("1", (n, n), 1)
    px = img.load()
    for y, row in enumerate(matrix):
        for x, v in enumerate(row):
            if v:
                px[x + QUIET, y + QUIET] = 0
    img = img.resize((n * scale, n * scale), Image.NEAREST)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
