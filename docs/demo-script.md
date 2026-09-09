# Fact Knowledge Layer — 3-Minute Video Demo Script

> **Target Duration**: Exactly 3 minutes (180 seconds) or less.  
> **Dataset Used**: Delhivery Starter Dataset (`Prospectus 2022`, `FY24 Annual Report`, `Q4 FY24 Presentation`).  
> **Spoken Word Count**: ~380 words (paced comfortably at ~130 words/minute).

---

## Timeline & Evaluation Mapping (0:00 – 3:00)

| Timestamp | Screen Focus | Architectural Focus | Key Demonstration |
|---|---|---|---|
| **0:00 – 0:30** | Knowledge Summary Dashboard | **Discovered & Grounded** | Provenance-first system (not a chatbot); 2,389 facts extracted from real PDFs. |
| **0:30 – 1:00** | Facts Explorer & Evidence Drawer | **Grounded (Zero Hallucinations)** | Verbatim quotes, exact page numbers, raw text vs normalized values. |
| **1:00 – 1:35** | Cross-Document Relationships | **Compared & Explained** | 9-dimension context comparison matrix; why differing values don't mean conflict. |
| **1:35 – 2:20** | Relationships Explorer | **Case 1, Case 2 & Case 3** | • **Case 1**: Sahil Barua Role (`CORROBORATES`)<br>• **Case 2**: Spoton CIN Conflict (`CONTRADICTS`)<br>• **Case 3**: Sort Capacity Growth (`RECONCILES` on TIME). |
| **2:20 – 2:45** | Failures & Uncertainty Audit | **Case 4 (System Boundaries)** | 81 ungrounded quotes rejected by EvidenceVerifier; scanned page flagged for OCR. |
| **2:45 – 3:00** | Terminal / CLI Evaluation | **Verification & Wrap-up** | Headless benchmark scorecard passing; 162 automated tests. |

---

## Scene-by-Scene Production Guide

### Scene 1: Introduction & Architecture (0:00 – 0:30)

- **Where to Click / What to Focus On**:
  - Open browser at `http://localhost:8501`.
  - Start on **📊 Knowledge Summary**.
  - Hover over the stat cards: **6 Documents**, **2,389 Facts**, **1,900 Validated**.
- **What to Say**:
  > *"Welcome. This is the Fact Knowledge Layer—an analytical platform that extracts, normalizes, and reconciles factual claims across documents with 100% provenance.*
  > 
  > *Instead of an opaque chatbot that generates unverifiable prose, our system operates across four rigorous pillars: facts are **Discovered** via layout-aware chunking, **Grounded** with verbatim source quotes, **Compared** across nine structured dimensions, and **Explained** with transparent contextual reasoning."*

---

### Scene 2: Facts Explorer — Provenance & Grounding (0:30 – 1:00)

- **Where to Click / What to Focus On**:
  - Click **📄 Facts Explorer** in the sidebar.
  - Type `Sahil Barua` or `revenue` into the search bar.
  - Click to expand the **"🔎 Source evidence & location"** drawer on any fact card.
  - Point your mouse at:
    1. The **Raw Stated Value** vs **Normalized Value**.
    2. The **Verbatim Quote**.
    3. The **Document Name** and **Page Number**.
- **What to Say**:
  > *"Under Facts Explorer, notice how claims are Grounded. Every fact strictly separates what the document stated from its normalized value.*
  > 
  > *Expanding the Source Evidence drawer reveals the verbatim quote and exact document page. The LLM is never the final authority on its own citations—our independent Python EvidenceVerifier checks the candidate quote directly against the source page text before any claim is accepted."*

---

### Scene 3: Compared & Explained Across 9 Dimensions (1:00 – 1:35)

- **Where to Click / What to Focus On**:
  - Click **🔀 Cross-Document Relationships** in the sidebar.
  - Point to the four top KPI cards: **Corroborations (65)**, **Contradictions (179)**, **Reconciliations (722)**.
  - Scroll down to show the **Context Comparison Matrix** (Entity, Metric, Time Period, Geography, Unit, Scope).
- **What to Say**:
  > *"Under Relationships, candidate pairs are Compared and Explained. The system doesn't rely on shallow text similarity; it evaluates facts across nine structured dimensions.*
  > 
  > *Crucially, differing numbers do not automatically imply a contradiction. If reporting periods, scopes, or units differ, the engine reconciles them with an explicit explanation."*

---

### Scene 4: The 3 Core Cases Walkthrough (1:35 – 2:20)

- **Where to Click / What to Focus On**:
  - Filter by **Corroborates**: Click the relationship for **Sahil Barua Role**.
    - Show Doc 1 (Prospectus) and Doc 2 (Annual Report) both stating Managing Director & CEO.
  - Filter by **Contradicts**: Click the relationship for **Spoton Logistics CIN**.
    - Highlight the conflicting registration numbers: `U63090GJ...` (Gujarat) vs `U63090DL...` (Delhi).
  - Filter by **Reconciles**: Click the relationship for **Rated Sort Capacity** (`3.7M` vs `7.1M`).
    - Point to the blue badge and the comparison table highlighting the **TIME** dimension mismatch (2021 vs 2024).
- **What to Say**:
  > *"Here are the core cases on real Delhivery corporate filings:*
  > 
  > *• **Case 1 (Corroboration)**: Both the 2022 Prospectus and FY24 Annual Report independently confirm Sahil Barua as Managing Director and CEO, corroborated with confidence 1.0.*
  > 
  > *• **Case 2 (Contradiction)**: For subsidiary Spoton Logistics, the Prospectus cites a Gujarat corporate registration number, while the FY24 Annual Report cites a Delhi registration number. Same entity, same attribute, conflicting values—flagged as a genuine CONTRADICTION.*
  > 
  > *• **Case 3 (Reconciliation)**: Delhivery's daily sort capacity is stated as 3.7 million in one filing and 7.1 million in another. Rather than falsely declaring a conflict, the engine recognizes that 3.7 million was FY21 capacity and 7.1 million was FY24 capacity, correctly RECONCILING the pair on the TIME dimension."*

---

### Scene 5: Case 4 — Failures, Hallucination Defense & OCR (2:20 – 2:45)

- **Where to Click / What to Focus On**:
  - Click **⚠️ Failures & Uncertainty** in the sidebar.
  - Click the **Rejected Facts** tab: Show claims rejected with audit diagnosis `"Source quote does not exist in chunk text"`.
  - Click the **Low Quality Pages** tab: Show the page flagged with text quality < 0.30 recommended for OCR.
- **What to Say**:
  > *"• **Case 4 (Failure Handling)**: Under Failures and Uncertainty, we demonstrate defensive engineering. When an LLM hallucinates an ungrounded claim or quote, our EvidenceVerifier intercepts and rejects it—as seen in these 373 rejected claims.*
  > 
  > *Additionally, pages with scanned artifacts or low text quality are flagged for OCR fallback preprocessing rather than silently failing."*

---

### Scene 6: CLI Benchmark & Wrap-Up (2:45 – 3:00)

- **Where to Click / What to Focus On**:
  - Switch window to your terminal showing the output of:
    ```bash
    python -m app.cli.evaluate
    ```
  - Point to the 4 benchmark test cases with green `PASS [OK]` indicators.
- **What to Say**:
  > *"All four cases can also be evaluated reproducibly headlessly via our CLI benchmark runner, backed by 162 automated unit and integration tests passing. The Fact Knowledge Layer delivers an auditable, provenance-first foundation for document intelligence. Thank you."*

---

## Speaker Quick-Check Tips

1. **Keep it brisk**: Don't pause between transitions; navigate to the next tab as you begin talking about it.
2. **Highlight mouse cursor**: Enable circle highlight or cursor click sounds in OBS / Loom.
3. **Pacing**: If you finish Scene 4 at 2:20, you are in perfect rhythm to wrap up at ~2:55.
