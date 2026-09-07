# Fact Knowledge Layer — Video Demo Script

This script outlines the exact structure, visual steps, and voiceover for a 5-minute video demonstration of the **Fact Knowledge Layer**.

---

## Demo Overview

| Timestamp | Section | Visual Focus | Key Takeaway |
|---|---|---|---|
| **0:00 – 0:45** | Introduction & UI Philosophy | Streamlit UI Homepage & Sidebar | Analytical knowledge engine, **not a chatbot**; provenance-first design. |
| **0:45 – 1:30** | Document Ingestion & Deduplication | Upload Page, Pre-computed SHA-256 | Multi-PDF upload, duplicate detection, layout-aware indexing. |
| **1:30 – 2:15** | Processing Pipeline Monitor | Processing Stepper View | Real-time 6-stage async pipeline without opaque black boxes. |
| **2:15 – 3:00** | Facts Explorer & Provenance | Facts Explorer with Filter Tabs | Verbatim quotes, exact page numbers, and bounding coordinates. |
| **3:00 – 3:45** | Corroboration & Contradiction | Cross-Document Relationships | Case A ($120M vs $120,000K) & Case B (15,000 vs 11,200 headcount). |
| **3:45 – 4:15** | Contextual Reconciliation | Master-Detail & Context Matrix | Case C (Annual $500M vs Q4 $140M reconciled by TIME dimension). |
| **4:15 – 4:45** | Failure Handling & Uncertainty | Failures & Uncertainty Audit Screen | Case D (Low-text page flag, rejected hallucinated quote). |
| **4:45 – 5:00** | CLI Evaluation & Wrap-up | Terminal Scorecard (`app.cli.evaluate`)| Automated benchmark scorecard passing all test cases. |

---

## Scene-by-Scene Walkthrough

### Scene 1: Introduction & Analytical UI Philosophy (0:00 – 0:45)
- **Visual**: Open browser at `http://localhost:8501`. Display the sleek dark-mode Streamlit dashboard with its six navigation views:
  - 📤 Upload Documents
  - ⏱️ Processing Progress
  - 📊 Knowledge Summary
  - 📄 Facts Explorer
  - 🔀 Cross-Document Relationships
  - ⚠️ Failures & Uncertainty
- **Voiceover**:
  > "Welcome to the Fact Knowledge Layer demonstration. Unlike conversational chatbots that summarize documents into unverifiable prose, this system is an analytical intelligence platform. It treats documents as structured evidence, extracting verifiable claims, resolving entities, and classifying cross-document relationships across 9 contextual dimensions—with 100% provenance back to exact document pages and source quotes."

---

### Scene 2: Document Ingestion & Deduplication (0:45 – 1:30)
- **Visual**: Navigate to **Upload Documents**.
  1. Click **"Load Sample Demo Dataset"** to populate the benchmark document set.
  2. Show the **Uploaded Document Inventory** table with document IDs, page counts, block counts, table counts, and SHA-256 fingerprints.
  3. Drag and drop the same PDF again to demonstrate duplicate handling: show the system identifying the pre-computed hash and preventing duplicate ingestion.
- **Voiceover**:
  > "In the Upload Documents screen, we ingest PDF files. Low-level parsing is handled deterministically via PyMuPDF. Every file is pre-hashed with SHA-256; re-uploading an existing PDF immediately reuses the document record without duplicate processing or wasted computation."

---

### Scene 3: Processing Pipeline Monitor (1:30 – 2:15)
- **Visual**: Navigate to **Processing Progress**.
  1. Show the 6-stage async pipeline stepper:
     `Document Ingestion` $\rightarrow$ `Layout-Aware Chunking` $\rightarrow$ `Fact Extraction` $\rightarrow$ `Value Normalization` $\rightarrow$ `Candidate Generation` $\rightarrow$ `Hybrid Reasoning Engine`
  2. Point out the active job cards with elapsed times, processed fact counts, and completion status.
- **Voiceover**:
  > "Under Processing Progress, users track asynchronous pipeline execution. The system parses reading order, detects headings, builds layout-aware chunks preserving tables, extracts factual claims with strict schema enforcement, normalizes numeric and temporal values, retrieves candidate pairs via conservative embeddings, and evaluates relationships."

---

### Scene 4: Facts Explorer & Provenance Verification (2:15 – 3:00)
- **Visual**: Navigate to **Facts Explorer**.
  1. Filter by `Validation Status = VALIDATED`.
  2. Search for `revenue` in the search bar.
  3. Click to expand **"Source evidence & location"** on an extracted fact card.
  4. Highlight the verbatim source quote, page range (`Page 1`), and block ID list.
- **Voiceover**:
  > "Under Facts Explorer, every single claim is strictly separated into what the document explicitly stated versus its normalized value. Look at this fact: $120 million is normalized to 120,000,000 USD. Expanding the Source Evidence drawer reveals the verbatim quote and exact page reference. The LLM is never the final authority on its own citations—our EvidenceVerifier checks the quote against chunk text directly."

---

### Scene 5: Corroboration & Contradiction Walkthrough (3:00 – 3:45)
- **Visual**: Navigate to **Cross-Document Relationships**.
  1. Review the 4 top stat banners: **Corroborations** (Green), **Contradictions** (Red), **Reconciliations** (Blue), **Uncertain** (Amber).
  2. Click on **CASE A (Corroboration)** in the left sidebar:
     - Show **Fact A**: Acme Corporation revenue `$120 million` (Doc 1, Page 1).
     - Show **Fact B**: Acme Corporation revenue `120,000 thousand USD` (Doc 2, Page 1).
     - Point out the **Context Comparison Matrix** indicating 100% dimension alignment and normalized numeric equivalence ($120,000,000 == 120,000,000).
  3. Click on **CASE B (Contradiction)** in the left sidebar:
     - Show **Fact A**: Beta Industries headcount `15,000 personnel` (Doc 1, Page 1).
     - Show **Fact B**: Beta Industries headcount `11,200 employees` (Doc 2, Page 1).
     - Highlight the red badge: same company, same metric, same FY2024 period, but genuinely conflicting values.
- **Voiceover**:
  > "In the Relationships view, our hybrid engine compares facts across 9 structured dimensions.
  > In Case A, two different documents phrase Acme's revenue differently—'$120 million' versus '120,000 thousand USD'. Because our deterministic normalization resolves both to 120,000,000 USD under identical scopes and periods, the engine conclusively classifies them as CORROBORATES.
  > In Case B, Beta Industries' headcount is stated as 15,000 in one source and 11,200 in another. Because entity, metric, geography, and fiscal year 2024 are identical, the system flags a true CONTRADICTION."

---

### Scene 6: Contextual Reconciliation Walkthrough (3:45 – 4:15)
- **Visual**: Click on **CASE C (Reconciliation)** in the master list.
  - Fact A: Gamma Software revenue `$500 million` (FY2024 annual).
  - Fact B: Gamma Software revenue `$140 million` (Q4 FY2024 quarterly).
  - Show the **Context Comparison Table**:
    - Entity: `Gamma Software` ✅
    - Metric: `revenue` ✅
    - Period: Fact A = `FY2024`, Fact B = `Q4 FY2024` ❌ (Quarterly vs Full-year)
  - Point out the explanation: *Values differ because Fact A reports for FY2024 while Fact B reports for Q4 FY2024 (quarterly figure vs full-year figure).*
- **Voiceover**:
  > "A core tenet of our design is that differing numbers do NOT automatically mean a contradiction.
  > In Case C, Gamma Software has revenue figures of $500M and $140M. The system does not falsely declare a conflict; it identifies that Fact A reports full-year revenue while Fact B reports fourth-quarter revenue, reconciling the pair on the TIME dimension."

---

### Scene 7: Failure Handling & Uncertainty Audit (4:15 – 4:45)
- **Visual**: Navigate to **Failures & Uncertainty**.
  1. Open the **Rejected Facts** tab: Show the ungrounded hallucination quote rejected by `EvidenceVerifier` (*Delta Corp had exceptional net profit of $999 billion in 2099*).
  2. Open the **Low Quality Pages** tab: Show Page 2 of synthetic document D flagged as low-text / scanned.
  3. Show the audit notes explaining why the claims were rejected or flagged.
- **Voiceover**:
  > "Under Failures and Uncertainty, we transparently audit system limitations. If an LLM hallucinates a quote not present in the document text, our EvidenceVerifier intercepts and rejects it. Furthermore, pages with sparse text or scanned artifacts are flagged for OCR inspection rather than silently ingested."

---

### Scene 8: CLI Evaluation & Wrap-Up (4:45 – 5:00)
- **Visual**: Switch to terminal. Execute:
  ```bash
  python -m app.cli.evaluate
  ```
  Show the terminal output displaying the 4 benchmark test cases with `PASS [OK]` status and diagnostic summary.
- **Voiceover**:
  > "To verify this reproducibly, our CLI evaluation runner tests all four benchmark cases and eight failure-handling domains headlessly. With 145 automated tests passing, the Fact Knowledge Layer provides an auditable, provenance-backed foundation for enterprise document intelligence. Thank you."
