"""
Contract ingestion for the Contract Clause Explainer.

Unlike a datasheet (where you cite a page), a contract is structured into
numbered clauses/sections — and "Clause 7.2 says..." is far more useful to a
user than "page 3 says...". So this module extracts the text and then splits
it into CLAUSES, keeping each clause's heading/number for citation.

It also detects the failure cases the brief asks about:
- a scanned / image-only PDF with no extractable text
- a document that doesn't look like a contract at all
"""

import re
import pdfplumber


SCANNED_DOC_CHAR_THRESHOLD = 120

# Matches common clause/section starts at the beginning of a line, e.g.:
#   "1." "1.2" "1.2.3" "Section 4" "Article 5" "12)" "(a)"
_CLAUSE_START = re.compile(
    r"""^\s*(
        (?:Section|Article|Clause|SECTION|ARTICLE|CLAUSE)\s+\d+[A-Za-z]?  # Section 4
        | \d+(?:\.\d+)*\.?\s                                              # 1.  / 1.2.3
        | \(\s*[a-zA-Z0-9]{1,3}\s*\)                                      # (a) (iv) (12)
        | \d+\)                                                          # 12)
    )""",
    re.VERBOSE,
)

# A few words we'd expect to see somewhere in a real contract. Used only as a
# soft signal to warn (not block) if the document seems not to be a contract.
_CONTRACT_HINTS = [
    "agreement", "party", "parties", "shall", "hereby", "terms",
    "obligations", "liability", "termination", "contract", "lease",
    "employment", "tenant", "landlord", "employee", "confidential",
]


class Clause:
    """One clause/section of a contract."""
    def __init__(self, ref: str, heading: str, text: str, start_page: int):
        self.ref = ref            # e.g. "7.2" or "Section 4" or "Clause 3"
        self.heading = heading    # short heading/first line, for display
        self.text = text          # full clause text
        self.start_page = start_page

    def label(self) -> str:
        """Human-readable citation label."""
        if self.ref:
            return f"Clause {self.ref}" if self.ref[0].isdigit() else self.ref
        return f"(p.{self.start_page})"

    def __repr__(self):
        return f"<Clause {self.ref!r} p{self.start_page} chars={len(self.text)}>"


class IngestResult:
    def __init__(self, clauses, full_text, warnings, is_scanned,
                 looks_like_contract, source_name, page_count):
        self.clauses = clauses
        self.full_text = full_text
        self.warnings = warnings
        self.is_scanned = is_scanned
        self.looks_like_contract = looks_like_contract
        self.source_name = source_name
        self.page_count = page_count

    @property
    def total_chars(self):
        return len(self.full_text)


def _extract_pages(path):
    """Return list of (page_number, text)."""
    pages = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            try:
                pages.append((i, page.extract_text() or ""))
            except Exception:  # noqa: BLE001
                pages.append((i, ""))
    return pages


def _split_into_clauses(pages):
    """
    Walk the document line by line; start a new clause whenever a line looks
    like a clause/section heading. Falls back to page-chunks if no structure
    is detected (some contracts are just prose).
    """
    clauses = []
    cur_ref, cur_heading, cur_lines, cur_page = "", "", [], 1
    found_structure = False

    def flush():
        if cur_lines:
            text = "\n".join(cur_lines).strip()
            if text:
                clauses.append(Clause(cur_ref, cur_heading or text[:60],
                                      text, cur_page))

    for page_no, text in pages:
        for raw in text.split("\n"):
            line = raw.rstrip()
            if not line.strip():
                cur_lines.append("")
                continue
            m = _CLAUSE_START.match(line)
            if m:
                found_structure = True
                flush()
                ref = m.group(1).strip().rstrip(".").strip()
                # normalise "Section 4" style vs "4.2" style
                cur_ref = ref
                cur_heading = line.strip()[:80]
                cur_lines = [line]
                cur_page = page_no
            else:
                cur_lines.append(line)
    flush()

    if not found_structure:
        # No clause numbering detected — fall back to page-sized chunks so the
        # rest of the pipeline still works (e.g. a prose NDA).
        clauses = []
        for page_no, text in pages:
            t = (text or "").strip()
            if t:
                clauses.append(Clause("", f"Page {page_no}", t, page_no))
        return clauses, found_structure

    clauses = _merge_heading_only(clauses)
    return clauses, found_structure


# Word count below which a clause is treated as a bare heading (e.g.
# "3. Security Deposit") rather than substantive text. Such headings get
# merged into the following clause so they don't become tiny, high-scoring
# noise during retrieval.
_HEADING_WORD_LIMIT = 5


def _merge_heading_only(clauses):
    """
    A clause whose body is just a short heading line carries no real content
    but scores very high in TF-IDF because it's tiny. Merge each such heading
    into the next clause (so 'Section 5' folds into '5.1 ...'), and drop any
    leftover heading at the very end.
    """
    out = []
    pending_heading = None  # (heading_text,) waiting to attach to next clause
    for c in clauses:
        body_words = len(c.text.split())
        is_heading_only = body_words <= _HEADING_WORD_LIMIT and "\n" not in c.text.strip()
        if is_heading_only:
            # Hold it; prefer to prepend to the next substantive clause.
            pending_heading = c.text.strip()
            continue
        if pending_heading:
            c.text = pending_heading + "\n" + c.text
            if not c.heading:
                c.heading = pending_heading[:80]
            pending_heading = None
        out.append(c)
    # If a trailing heading had nothing to attach to, keep it rather than lose data.
    if pending_heading:
        out.append(Clause("", pending_heading[:60], pending_heading, clauses[-1].start_page))
    return out


def ingest_pdf(path: str, source_name: str) -> IngestResult:
    """Read a contract PDF; return clauses + warnings. Never raises on bad input."""
    warnings = []
    try:
        pages = _extract_pages(path)
    except Exception as e:  # noqa: BLE001
        return IngestResult([], "", [f"Could not open this PDF: {e}"],
                            False, False, source_name, 0)

    full_text = "\n".join(t for _, t in pages)
    page_count = len(pages)

    is_scanned = len(full_text.strip()) < SCANNED_DOC_CHAR_THRESHOLD
    if is_scanned:
        warnings.append(
            "This PDF appears to be scanned or image-only — almost no "
            "selectable text was found. I can't read image-only documents "
            "without OCR. Please upload a text-based contract, or OCR this "
            "file first."
        )
        return IngestResult([], full_text, warnings, True, False,
                            source_name, page_count)

    clauses, structured = _split_into_clauses(pages)

    low = full_text.lower()
    hits = sum(1 for w in _CONTRACT_HINTS if w in low)
    looks_like_contract = hits >= 3
    if not looks_like_contract:
        warnings.append(
            "This doesn't look like a typical contract or agreement. I can "
            "still try to answer questions about its text, but I'm built for "
            "contracts (leases, employment, freelance, NDAs)."
        )
    if not structured:
        warnings.append(
            "I couldn't detect numbered clauses, so I'll cite by page instead "
            "of clause number."
        )

    return IngestResult(clauses, full_text, warnings, False,
                        looks_like_contract, source_name, page_count)
