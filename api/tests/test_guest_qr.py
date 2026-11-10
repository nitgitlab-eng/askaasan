"""QR encoder correctness: exact matrices from a reference encoder (libqrencode 4, byte mode, level M) for a short URL
(version 2) and a long one (version 12: version info, several RS blocks), plus structural decoding checks."""

import pytest

from apps.guests import qr

SHORT = "https://aasan.in/g/demo-1"
SHORT_MASK = 1
SHORT_REF = (
    "1fddc7f",
    "1046d41",
    "175a85d",
    "1748a5d",
    "174355d",
    "1057c41",
    "1fd557f",
    "e700",
    "146a125",
    "1aa936b",
    "1fd8add",
    "19f088",
    "cc1161",
    "b993e3",
    "1dfdbcd",
    "73b7f8",
    "19691f2",
    "18911",
    "1fda951",
    "1048512",
    "174e3f2",
    "1742996",
    "17560bb",
    "1049530",
    "1fd5549",
)
LONG = "https://example.com/" + "y" * 250
LONG_MASK = 1
LONG_REF = (
    "1fd645715ddd5527f",
    "104c031ed881dd141",
    "175cf3bab88008d5d",
    "1746ea2fbaae2265d",
    "1746457dfd555515d",
    "1054c396c5d555441",
    "1fd5555555555557f",
    "700c9c77777500",
    "14699d547d5555425",
    "b9d328e5aaaaaaa7",
    "15cbb069422222125",
    "b8b8409b777775ba",
    "15d55d141555554d2",
    "a91b20e6aaaaaaa7",
    "5777469622222125",
    "30b84c9b7777757a",
    "4626a44155555452",
    "2bb613e6aaaaaaaf",
    "14ffd7a9622222129",
    "130a4199b7777757a",
    "14607fd415555545a",
    "abe2b1e6aaaaaaa7",
    "4fdc4b9622222125",
    "130a72b9b7777757a",
    "10635fc4155555452",
    "bd1b2e6aaaaaaa7",
    "16fcc499622222125",
    "1b097299b7755757a",
    "1a625ec5155555452",
    "1abf091c2aab8aaa4",
    "11ffc6a9fe23311f7",
    "191a5388c4cf7751a",
    "1d525ec4d48955753",
    "1d1f091e45deaab17",
    "15ffc6adfcce221f5",
    "1b0a5389df7fb3fda",
    "18f25eccc95555282",
    "199f091a6aa22a0a7",
    "15438229162aaa855",
    "1b0a5389df77776da",
    "18da1684c15555682",
    "1983c15e66aaaaaa7",
    "15efcae1122222275",
    "1a321305d377777ea",
    "195a56c0d95555682",
    "199345524aaaaa8a7",
    "1457c2ed162222055",
    "12a29701cf77777da",
    "19def278c955556c2",
    "931767a6aaaaa827",
    "5e06df516222205d",
    "1208f0b1df77777da",
    "9727700c95555682",
    "18b2c3326aaaaa8a7",
    "6d35ed5162222055",
    "1239e391df77777da",
    "d715700fd55557f2",
    "11e30246aaaab17",
    "1fd06fd5562222355",
    "104af39147757551a",
    "174077337d55555f2",
    "1742e333f6b9abb74",
    "17507df6960000157",
    "104ac0a3aa23776a8",
    "1fd07730637555621",
)


def _rows(ref, n):
    return [[c == "1" for c in format(int(h, 16), f"0{n}b")] for h in ref]


@pytest.mark.parametrize(
    ("text", "mask", "ref", "size"), [(SHORT, SHORT_MASK, SHORT_REF, 25), (LONG, LONG_MASK, LONG_REF, 65)]
)
def test_matches_reference_encoder(text, mask, ref, size):
    m = qr.encode(text, "M", mask=mask)
    assert len(m) == size
    assert m == _rows(ref, size)


def _format_from(m):
    coords = [(8, i) for i in range(6)] + [(8, 7), (8, 8), (7, 8)] + [(14 - i, 8) for i in range(9, 15)]
    return sum(int(m[y][x]) << i for i, (x, y) in enumerate(coords))


def test_structure_finders_timing_format():
    m = qr.encode(SHORT)  # automatic mask choice
    n = len(m)
    for ox, oy in ((0, 0), (n - 7, 0), (0, n - 7)):
        for dy in range(7):
            for dx in range(7):
                ring = max(abs(dx - 3), abs(dy - 3))
                assert m[oy + dy][ox + dx] == (ring != 2), (ox, oy, dx, dy)
    assert [m[6][i] for i in range(8, n - 8)] == [i % 2 == 0 for i in range(8, n - 8)]
    fmt = _format_from(m)
    # a valid format word is one of the 32 BCH codewords; the level bits say M (00)
    valid = {qr._format_bits(ecl, k): (ecl, k) for ecl in "LMQH" for k in range(8)}
    assert fmt in valid and valid[fmt][0] == "M"
    assert m[n - 8][8] is True  # dark module


def test_reed_solomon_known_vector():
    # ISO/IEC 18004 Annex I example: "01234567" in version 1-M → data codewords and their 10 EC codewords.
    data = [0x10, 0x20, 0x0C, 0x56, 0x61, 0x80, 0xEC, 0x11, 0xEC, 0x11, 0xEC, 0x11, 0xEC, 0x11, 0xEC, 0x11]
    assert qr.rs_remainder(data, qr.rs_divisor(10)) == [
        0xA5,
        0x24,
        0xD4,
        0xC1,
        0xED,
        0x36,
        0xC7,
        0x87,
        0x2C,
        0x55,
    ]


def test_capacity_and_versions():
    assert (
        qr.data_codewords(1, "M") == 16
        and qr.data_codewords(10, "M") == 216
        and qr.data_codewords(40, "L") == 2956
    )
    assert len(qr.encode("a" * 14, "M")) == 21  # 14 bytes fit version 1-M
    assert len(qr.encode("a" * 15, "M")) == 25
    assert qr.alignment_positions(7) == [6, 22, 38] and qr.alignment_positions(32) == [
        6,
        34,
        60,
        86,
        112,
        138,
    ]
    with pytest.raises(qr.DataTooLong):
        qr.encode("x" * 3000, "H")


def test_svg_and_png_render():
    m = qr.encode(SHORT)
    s = qr.svg(m)
    assert s.startswith("<svg") and 'viewBox="0 0 33 33"' in s  # 25 modules + 4-module quiet zone each side
    assert qr.png(m)[:8] == b"\x89PNG\r\n\x1a\n"
