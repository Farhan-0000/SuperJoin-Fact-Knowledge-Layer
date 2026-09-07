"""Synthetic Evaluation Fixtures explicitly labeled for Phase 11 testing and evaluation.

All fixtures in this module are generated programmatically and clearly marked as
SYNTHETIC TEST FIXTURES to evaluate corroboration, contradiction, reconciliation,
and extraction failure handling.
"""

from __future__ import annotations

from pathlib import Path
import fitz  # PyMuPDF


# ── CASE A: Corroboration Fixtures ─────────────────────────────────────


def create_case_a_doc1(output_path: Path | None = None) -> bytes:
    """CASE A (Doc 1) — Synthetic fixture stating revenue in standard notation."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text(fitz.Point(50, 40), "[SYNTHETIC TEST FIXTURE — CASE A DOC 1]", fontsize=9)
    page.insert_text(fitz.Point(50, 100), "Acme Corporation FY2025 Annual Financial Report", fontsize=16)
    page.insert_text(
        fitz.Point(50, 150),
        "Acme Corporation achieved consolidated revenue of $120 million in FY2025 across all global operations.",
        fontsize=11,
    )
    page.insert_text(
        fitz.Point(50, 190),
        "Operating performance remained strong across North America and European divisions.",
        fontsize=11,
    )
    page.insert_text(fitz.Point(50, 760), "[SYNTHETIC EVALUATION DATASET — NOT REAL PRODUCTION DATA]", fontsize=8)

    pdf_bytes = doc.tobytes()
    if output_path:
        Path(output_path).write_bytes(pdf_bytes)
    doc.close()
    return pdf_bytes


def create_case_a_doc2(output_path: Path | None = None) -> bytes:
    """CASE A (Doc 2) — Synthetic fixture stating equivalent revenue with different wording and units."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text(fitz.Point(50, 40), "[SYNTHETIC TEST FIXTURE — CASE A DOC 2]", fontsize=9)
    page.insert_text(fitz.Point(50, 100), "Acme Corporation Q4 Investor Review & FY Summary", fontsize=16)
    page.insert_text(
        fitz.Point(50, 150),
        "In fiscal year 2025, Acme Corporation generated 120,000 thousand USD in total global sales.",
        fontsize=11,
    )
    page.insert_text(
        fitz.Point(50, 190),
        "International expansion contributed to double-digit growth year over year.",
        fontsize=11,
    )
    page.insert_text(fitz.Point(50, 760), "[SYNTHETIC EVALUATION DATASET — NOT REAL PRODUCTION DATA]", fontsize=8)

    pdf_bytes = doc.tobytes()
    if output_path:
        Path(output_path).write_bytes(pdf_bytes)
    doc.close()
    return pdf_bytes


# ── CASE B: Contradiction Fixtures ─────────────────────────────────────


def create_case_b_doc1(output_path: Path | None = None) -> bytes:
    """CASE B (Doc 1) — Synthetic fixture stating 15,000 employees for FY2024."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text(fitz.Point(50, 40), "[SYNTHETIC TEST FIXTURE — CASE B DOC 1]", fontsize=9)
    page.insert_text(fitz.Point(50, 100), "Beta Industries Workforce & Operations Report", fontsize=16)
    page.insert_text(
        fitz.Point(50, 150),
        "Beta Industries employed 15,000 full-time personnel globally as of FY2024 year end.",
        fontsize=11,
    )
    page.insert_text(
        fitz.Point(50, 190),
        "The corporate talent base expanded across software and manufacturing centers.",
        fontsize=11,
    )
    page.insert_text(fitz.Point(50, 760), "[SYNTHETIC EVALUATION DATASET — NOT REAL PRODUCTION DATA]", fontsize=8)

    pdf_bytes = doc.tobytes()
    if output_path:
        Path(output_path).write_bytes(pdf_bytes)
    doc.close()
    return pdf_bytes


def create_case_b_doc2(output_path: Path | None = None) -> bytes:
    """CASE B (Doc 2) — Synthetic fixture stating conflicting 11,200 employees for exact same period."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text(fitz.Point(50, 40), "[SYNTHETIC TEST FIXTURE — CASE B DOC 2]", fontsize=9)
    page.insert_text(fitz.Point(50, 100), "Beta Industries Annual Sustainability & Governance Report", fontsize=16)
    page.insert_text(
        fitz.Point(50, 150),
        "At the close of FY2024, Beta Industries had 11,200 total employees worldwide.",
        fontsize=11,
    )
    page.insert_text(
        fitz.Point(50, 190),
        "Diversity and inclusion benchmarks progressed across all regional facilities.",
        fontsize=11,
    )
    page.insert_text(fitz.Point(50, 760), "[SYNTHETIC EVALUATION DATASET — NOT REAL PRODUCTION DATA]", fontsize=8)

    pdf_bytes = doc.tobytes()
    if output_path:
        Path(output_path).write_bytes(pdf_bytes)
    doc.close()
    return pdf_bytes


# ── CASE C: Reconciliation Fixtures ───────────────────────────────────


def create_case_c_doc1(output_path: Path | None = None) -> bytes:
    """CASE C (Doc 1) — Synthetic fixture stating full year revenue ($500M in FY2024)."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text(fitz.Point(50, 40), "[SYNTHETIC TEST FIXTURE — CASE C DOC 1]", fontsize=9)
    page.insert_text(fitz.Point(50, 100), "Gamma Software FY2024 Annual Shareholder Letter", fontsize=16)
    page.insert_text(
        fitz.Point(50, 150),
        "Gamma Software achieved total consolidated annual revenue of $500 million for FY2024.",
        fontsize=11,
    )
    page.insert_text(
        fitz.Point(50, 190),
        "Enterprise subscription renewals drove recurring revenue to new all-time highs.",
        fontsize=11,
    )
    page.insert_text(fitz.Point(50, 760), "[SYNTHETIC EVALUATION DATASET — NOT REAL PRODUCTION DATA]", fontsize=8)

    pdf_bytes = doc.tobytes()
    if output_path:
        Path(output_path).write_bytes(pdf_bytes)
    doc.close()
    return pdf_bytes


def create_case_c_doc2(output_path: Path | None = None) -> bytes:
    """CASE C (Doc 2) — Synthetic fixture stating Q4 quarterly revenue ($140M in Q4 FY2024)."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text(fitz.Point(50, 40), "[SYNTHETIC TEST FIXTURE — CASE C DOC 2]", fontsize=9)
    page.insert_text(fitz.Point(50, 100), "Gamma Software Q4 Earnings Summary", fontsize=16)
    page.insert_text(
        fitz.Point(50, 150),
        "Gamma Software recorded fourth-quarter revenue of $140 million in Q4 FY2024.",
        fontsize=11,
    )
    page.insert_text(
        fitz.Point(50, 190),
        "Quarterly momentum accelerated due to cloud platform adoption.",
        fontsize=11,
    )
    page.insert_text(fitz.Point(50, 760), "[SYNTHETIC EVALUATION DATASET — NOT REAL PRODUCTION DATA]", fontsize=8)

    pdf_bytes = doc.tobytes()
    if output_path:
        Path(output_path).write_bytes(pdf_bytes)
    doc.close()
    return pdf_bytes


# ── CASE D: Extraction Failure & Uncertainty Fixture ───────────────────


def create_case_d_failure_doc(output_path: Path | None = None) -> bytes:
    """CASE D — Synthetic fixture with ambiguous wording, malformed table, and low-text page."""
    doc = fitz.open()

    # Page 1: Ambiguous wording and unparseable metric claims
    page1 = doc.new_page(width=600, height=800)
    page1.insert_text(fitz.Point(50, 40), "[SYNTHETIC TEST FIXTURE — CASE D FAILURE MODES]", fontsize=9)
    page1.insert_text(fitz.Point(50, 100), "Delta Corp Incomplete Draft Notes", fontsize=16)
    page1.insert_text(
        fitz.Point(50, 150),
        "Preliminary unverified notes: Delta Corp expenses were maybe 35% or $35M? Missing audit sign-off.",
        fontsize=11,
    )
    page1.insert_text(
        fitz.Point(50, 190),
        "Notice: Tables below contain corrupted rows and missing column titles.",
        fontsize=11,
    )

    # Malformed table without proper grid boundaries or column labels
    page1.insert_text(fitz.Point(60, 240), "???   ---   ???", fontsize=10)
    page1.insert_text(fitz.Point(60, 260), "12.4  45.1  unclear", fontsize=10)

    # Page 2: Low-text / scanned-like page (< 15 characters)
    page2 = doc.new_page(width=600, height=800)
    page2.insert_text(fitz.Point(50, 50), "[Scan Blank]", fontsize=8)

    pdf_bytes = doc.tobytes()
    if output_path:
        Path(output_path).write_bytes(pdf_bytes)
    doc.close()
    return pdf_bytes
