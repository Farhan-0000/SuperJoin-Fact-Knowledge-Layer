"""Failures & Uncertainty audit view."""

from __future__ import annotations

import streamlit as st

from ui.data_service import get_data_service


def render_failures_view() -> None:
    """Render audit view for rejected claims, validation warnings, uncertain relationships, and low-quality pages."""
    st.title("⚠️ Failures & Uncertainty")
    st.markdown("Audit system boundaries, hallucination rejections, quote verifier warnings, and ambiguous relationships.")

    service = get_data_service()

    rejected_facts = service.get_rejected_facts()
    warning_facts = service.get_warning_facts()
    uncertain_rels = service.get_uncertain_relationships()
    failed_jobs = service.get_failed_jobs()
    low_quality_pages = service.get_low_quality_pages()

    # ── Tabs ───────────────────────────────────────────────────────────
    tab_labels = [
        f"Rejected Facts ({len(rejected_facts)})",
        f"Validation Warnings ({len(warning_facts)})",
        f"Uncertain Relationships ({len(uncertain_rels)})",
        f"Failed Jobs ({len(failed_jobs)})",
        f"Low Quality Pages ({len(low_quality_pages)})",
    ]

    tab1, tab2, tab3, tab4, tab5 = st.tabs(tab_labels)

    # ── Tab 1: Rejected Facts ──────────────────────────────────────────
    with tab1:
        st.subheader("Hallucination & Ungrounded Quote Rejections")
        st.caption(
            "Facts are strictly rejected if the claimed source quote does not verbatim or near-verbatim exist "
            "within the cited document page/block bounding box."
        )

        if not rejected_facts:
            st.success("✓ No rejected facts! All extracted claims verified against original document text.")
        else:
            for rf in rejected_facts:
                with st.container():
                    st.error(f"**Rejected Fact**: {rf.get('subject')} &bull; `{rf.get('predicate')}` &bull; {rf.get('value_text')}")
                    st.markdown(f"**Claimed Quote:** *\"{rf.get('source_quote')}\"*")
                    st.caption(
                        f"Document: {rf.get('document_name', rf.get('document_id'))} | "
                        f"Page: {rf.get('source_page_start', 1)} | "
                        f"Confidence: {int(rf.get('extraction_confidence', 0) * 100)}%"
                    )
                    notes = rf.get("extraction_notes_json") or "Quote verification failed (quote not found in source text)."
                    st.markdown(f"**Diagnosis**: `{notes}`")
                    st.markdown("---")

    # ── Tab 2: Validation Warnings ─────────────────────────────────────
    with tab2:
        st.subheader("Facts with Verification Warnings")
        st.caption("Facts flagged with warnings due to minor punctuation variance, fuzzy quote matches, or extraction confidence below standard threshold.")

        if not warning_facts:
            st.info("No validation warnings recorded.")
        else:
            for wf in warning_facts:
                with st.container():
                    st.warning(f"**Warning**: {wf.get('subject')} &bull; `{wf.get('predicate')}` &bull; {wf.get('value_text')}")
                    st.markdown(f"**Source Quote:** *\"{wf.get('source_quote')}\"*")
                    st.caption(
                        f"Document: {wf.get('document_name', wf.get('document_id'))} | "
                        f"Page: {wf.get('source_page_start', 1)} | "
                        f"Confidence: {int(wf.get('extraction_confidence', 0) * 100)}%"
                    )
                    st.markdown("---")

    # ── Tab 3: Uncertain Relationships ─────────────────────────────────
    with tab3:
        st.subheader("Unresolved & Ambiguous Relationships")
        st.caption("Candidate fact pairs where evidence or contextual scope is insufficient to definitively corroborate, contradict, or reconcile.")

        if not uncertain_rels:
            st.info("No uncertain relationships recorded.")
        else:
            for ur in uncertain_rels:
                with st.container():
                    st.markdown(
                        f"<div style='border: 1px solid #f59e0b; border-radius: 8px; padding: 14px; background: #fffbeb; margin-bottom: 12px;'>"
                        f"<div style='font-size: 14px; font-weight: 700; color: #92400e; margin-bottom: 4px;'>UNCERTAIN RELATIONSHIP ({int(ur.get('confidence', 0) * 100)}% confidence)</div>"
                        f"<div style='font-size: 13.5px; color: #78350f;'>{ur.get('explanation')}</div>"
                        f"<hr style='border: none; border-top: 1px solid #fde68a; margin: 8px 0;'>"
                        f"<div style='font-size: 12px; color: #92400e;'><strong>Fact A:</strong> {ur.get('fa_subject')} ({ur.get('fa_predicate')} = {ur.get('fa_value')}) &bull; <em>\"{ur.get('evidence_fact_a')}\"</em></div>"
                        f"<div style='font-size: 12px; color: #92400e; margin-top: 4px;'><strong>Fact B:</strong> {ur.get('fb_subject')} ({ur.get('fb_predicate')} = {ur.get('fb_value')}) &bull; <em>\"{ur.get('evidence_fact_b')}\"</em></div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

    # ── Tab 4: Failed Jobs ─────────────────────────────────────────────
    with tab4:
        st.subheader("Pipeline Job Failures")
        if not failed_jobs:
            st.success("✓ No failed processing jobs in system history.")
        else:
            from app.core.rate_limiting import format_local_timestamp

            for fj in failed_jobs:
                st.error(f"**Job ID:** `{fj.get('id')}` &bull; Stage: `{fj.get('current_stage')}`")
                st.code(fj.get("error_message") or "Unknown error", language="text")
                st.caption(f"Created: {format_local_timestamp(fj.get('created_at'))}")

    # ── Tab 5: Low Quality Pages ───────────────────────────────────────
    with tab5:
        st.subheader("Scanned Pages & Low Text Quality Flagged for OCR")
        st.caption(
            "Pages identified during parsing with text quality score < 0.30 or flagged as scanned documents. "
            "These require OCR fallback preprocessing or manual inspection to prevent extraction failures."
        )

        if not low_quality_pages:
            st.success("✓ No low-quality or scanned pages detected across indexed documents.")
        else:
            for lqp in low_quality_pages:
                with st.container():
                    quality_score = lqp.get("text_quality")
                    qual_pct = int(quality_score * 100) if quality_score is not None else 0
                    is_scanned = bool(lqp.get("is_scanned"))
                    status_badge = "SCANNED PAGE" if is_scanned else f"LOW QUALITY ({qual_pct}%)"

                    st.markdown(
                        f"<div style='border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px; background: #f8fafc; margin-bottom: 12px;'>"
                        f"<div style='display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;'>"
                        f"<span style='font-size: 14px; font-weight: 700; color: #1e293b;'>Page {lqp.get('page_number')} &bull; {lqp.get('document_name', lqp.get('document_id'))}</span>"
                        f"<span style='font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 4px; background: #fee2e2; color: #991b1b;'>{status_badge}</span>"
                        f"</div>"
                        f"<div style='font-size: 12.5px; color: #64748b;'>Extracted Characters: {lqp.get('raw_len', 0)} | Quality Metric: {qual_pct}%</div>"
                        f"<div style='font-size: 12px; color: #b45309; margin-top: 6px;'><strong>Recommendation:</strong> Flagged for optical character recognition (OCR) fallback preprocessing.</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
