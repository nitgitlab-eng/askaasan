"""Text extraction + chunking. Format is decided by magic bytes, not by name."""

import io
import re
import time

MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 400
MAX_CHARS = 600_000
MAX_UNZIPPED = 50 * 1024 * 1024  # DOCX is a zip: refuse zip bombs before parsing
MAX_RATIO = 100
MAX_PDF_CONTENT = 60 * 1024 * 1024  # decoded page content, summed over the document
MAX_PAGE_CONTENT = (
    4 * 1024 * 1024
)  # one page (content + the forms it calls): parsed inside a single extract_text()
PDF_SECONDS = 30  # wall-time budget for one PDF (checked between pages; pypdf bounds each stream)
XFORM_INVOCATIONS = (
    50  # form XObjects pypdf may enter per page (its default is 5000: one shared form re-parsed 5000x)
)
DO_OP = re.compile(rb"/([^\s/\[\]()<>{}%]+)\s*Do\b")


class ExtractError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def sniff(data: bytes, filename: str) -> str:
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"PK\x03\x04") and filename.lower().endswith(".docx"):
        return "docx"
    if filename.lower().endswith((".txt", ".md")):
        try:
            data[:4096].decode("utf-8")
        except UnicodeDecodeError as e:
            raise ExtractError("not_utf8") from e
        return "md" if filename.lower().endswith(".md") else "txt"
    raise ExtractError("unsupported_type")


def _check_zip(data: bytes) -> None:
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos = z.infolist()
    except (zipfile.BadZipFile, ValueError) as e:
        raise ExtractError("unreadable_docx") from e
    total, packed = sum(i.file_size for i in infos), sum(i.compress_size for i in infos)
    if len(infos) > 2000 or total > MAX_UNZIPPED or (packed and total / packed > MAX_RATIO):
        raise ExtractError("docx_too_large")


def _content_bytes(page, seen: dict) -> int:
    """Decoded size of a page's content stream(s). A stream shared by many pages is decoded once but counted on every
    page that uses it (pypdf re-parses it for each page)."""
    c = page.raw_get("/Contents") if "/Contents" in page else None
    total = 0
    for ref in c if isinstance(c, list) else [c] if c is not None else []:
        key = (ref.idnum, ref.generation) if hasattr(ref, "idnum") else None
        if key not in seen or key is None:
            obj = ref.get_object()
            seen[key] = len(obj.get_data()) if hasattr(obj, "get_data") else 0
        total += seen[key]
    return total


def _xform_bytes(content: bytes, resources, seen: dict, state: list) -> int:
    """Decoded bytes pypdf will parse for the form XObjects a content stream calls (`/Name Do`), nested forms included,
    following its traversal: each call re-parses the form, at most XFORM_INVOCATIONS calls per page (state[0])."""
    try:
        xobjs = resources.get_object().get("/XObject") if resources is not None else None
        xobjs = xobjs.get_object() if xobjs is not None else None
    except Exception:  # noqa: BLE001 — malformed resources: nothing pypdf could enter either
        return 0
    if not xobjs:
        return 0
    total = 0
    for m in DO_OP.finditer(content):
        if state[0] >= XFORM_INVOCATIONS:
            break
        name = "/" + m.group(1).decode("latin-1")
        if name not in xobjs:
            continue
        ref = xobjs.raw_get(name)
        key = ("xf", ref.idnum, ref.generation) if hasattr(ref, "idnum") else None
        obj = ref.get_object()
        if not hasattr(obj, "get_data") or obj.get("/Subtype") != "/Form":
            continue
        state[0] += 1
        if key is None or key not in seen:
            data = obj.get_data()
            seen[key] = (len(data), data if DO_OP.search(data) else b"")
        size, nested = seen[key]
        total += size
        if nested:
            total += _xform_bytes(nested, obj.get("/Resources"), seen, state)
    return total


def _page_xform_bytes(page, seen: dict) -> int:
    if "/Resources" not in page:
        return 0
    contents = page.get_contents()
    return _xform_bytes(contents.get_data() if contents is not None else b"", page["/Resources"], seen, [0])


def _pdf(data: bytes) -> list[tuple[int, str]]:
    from pypdf import apply_configuration

    # One shared Form XObject called thousands of times on a page would be re-parsed on every call inside a single
    # extract_text(), where the between-page checks can't see it: cap the calls and count their bytes up front.
    with apply_configuration(xform_maximum_invocations_per_extraction=XFORM_INVOCATIONS):
        return _pdf_pages(data)


def _pdf_pages(data: bytes) -> list[tuple[int, str]]:
    """Every page, under document-wide bounds checked inside the loop (pypdf only limits each stream on its own):
    pages, decoded content bytes, extracted characters and wall time."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise ExtractError("encrypted_pdf")
    if len(reader.pages) > MAX_PAGES:
        raise ExtractError("too_many_pages")
    deadline = time.monotonic() + PDF_SECONDS
    out, chars, content, seen = [], 0, 0, {}
    for i, p in enumerate(reader.pages):
        page_bytes = _content_bytes(p, seen) + _page_xform_bytes(p, seen)
        content += page_bytes
        if page_bytes > MAX_PAGE_CONTENT or content > MAX_PDF_CONTENT:
            raise ExtractError("pdf_too_complex")
        text = p.extract_text() or ""
        chars += len(text)
        if chars > MAX_CHARS:
            raise ExtractError("too_much_text")
        if time.monotonic() > deadline:
            raise ExtractError("pdf_too_complex")
        out.append((i + 1, text))
    return out


def extract(data: bytes, kind: str) -> list[tuple[int, str]]:
    """Returns [(page_number_or_0, text)]. Any parser failure is an ExtractError (a 400 for the caller), never a 500."""
    if kind == "pdf":
        try:
            return _pdf(data)
        except ExtractError:
            raise
        except Exception as e:  # malformed PDFs raise all sorts (KeyError, RecursionError, zlib.error, …)
            raise ExtractError("unreadable_pdf") from e
    if kind == "docx":
        import docx

        _check_zip(data)
        try:
            d = docx.Document(io.BytesIO(data))
            return [(0, "\n".join(p.text for p in d.paragraphs))]
        except Exception as e:
            raise ExtractError("unreadable_docx") from e
    return [(0, data.decode("utf-8", errors="replace"))]


def chunk(pages: list[tuple[int, str]], size: int = 900, overlap: int = 150) -> list[tuple[int, str]]:
    """Paragraph-aware chunks of ~size chars with overlap, tagged with their page."""
    out = []
    for page, text in pages:
        text = re.sub(r"[ \t]+", " ", text).strip()
        if not text:
            continue
        paras = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
        buf = ""
        for para in paras:
            while len(para) > size:  # very long paragraph: hard split
                head, para = para[:size], para[size - overlap :]
                if buf:
                    out.append((page, buf))
                    buf = ""
                out.append((page, head))
            if len(buf) + len(para) + 1 > size and buf:
                out.append((page, buf))
                buf = buf[-overlap:] + " " + para
            else:
                buf = f"{buf} {para}".strip()
        if buf:
            out.append((page, buf))
    return out
