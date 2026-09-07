"""Facts Explorer view."""

from __future__ import annotations

import streamlit as st

from ui.data_service import get_data_service


def render_facts_view() -> None:
    """Render interactive facts explorer with deep provenance."""
    st.title("📄 Facts Explorer")
    st.markdown("Inspect granular extracted claims with verified source quotes, normalized values, and document locations.")

    service = get_data_service()
    docs = service.get_documents(limit=100)

    # ── Filters & Search ───────────────────────────────────────────────
    search_q = st.text_input("🔍 Search facts by subject, predicate, value, or quote...", "")

    f_col1, f_col2, f_col3, f_col4 = st.columns(4)

    with f_col1:
        doc_choices = {"All": None}
        for d in docs:
            doc_choices[d["original_filename"]] = d["id"]
        selected_doc_label = st.selectbox("Document", list(doc_choices.keys()))
        selected_doc_id = doc_choices[selected_doc_label]

    with f_col2:
        val_status = st.selectbox(
            "Validation Status",
            ["All", "Validated", "Warning", "Rejected"],
            index=0,
        )
        val_filter = None if val_status == "All" else val_status.lower()

    with f_col3:
        val_type = st.selectbox(
            "Value Type",
            ["All", "currency", "number", "percentage", "date", "text", "quantity"],
            index=0,
        )
        type_filter = None if val_type == "All" else val_type.lower()

    with f_col4:
        min_conf = st.slider("Min Confidence", 0.0, 1.0, 0.5, 0.05)

    # ── Query Facts ───────────────────────────────────────────────────
    facts = service.get_facts(
        query_text=search_q if search_q else None,
        document_id=selected_doc_id,
        validation_status=val_filter,
        value_type=type_filter,
        min_confidence=min_conf,
        limit=100,
    )

    st.markdown(f"**Found {len(facts)} matching facts**")

    if not facts:
        st.info("No facts match the selected filter criteria.")
        return

    # ── Render Fact Cards ──────────────────────────────────────────────
    for idx, fact in enumerate(facts):
        with st.container():
            col_info, col_loc = st.columns([3, 1])

            with col_info:
                subj = fact.get("subject", "Unknown")
                pred = fact.get("predicate", "")
                val_txt = fact.get("value_text", "")
                norm_val = fact.get("normalized_numeric_value")
                unit = fact.get("unit") or ""
                time_ctx = fact.get("time_text") or ""
                scope_ctx = fact.get("scope") or ""

                st.markdown(f"### {subj} &bull; `{pred}`")

                meta_parts = [f"**Value:** {val_txt}"]
                if norm_val is not None:
                    meta_parts.append(f"*(Normalized: {norm_val:,.2f} {unit})*")
                if time_ctx:
                    meta_parts.append(f"**Period:** {time_ctx}")
                if scope_ctx:
                    meta_parts.append(f"**Scope:** {scope_ctx}")

                st.markdown(" &bull; ".join(meta_parts))

            with col_loc:
                v_status = fact.get("validation_status", "validated")
                conf = fact.get("extraction_confidence", 1.0)
                doc_name = fact.get("document_name") or "Document"
                page = fact.get("source_page_start", 1)

                if v_status == "validated":
                    st.success(f"✓ {v_status.upper()} ({int(conf * 100)}%)")
                elif v_status == "warning":
                    st.warning(f"⚠ {v_status.upper()} ({int(conf * 100)}%)")
                else:
                    st.error(f"✕ {v_status.upper()} ({int(conf * 100)}%)")

                st.caption(f"📄 {doc_name}, Page {page}")

            # Expandable Source Evidence
            with st.expander("🔎 Source evidence", expanded=False):
                quote = fact.get("source_quote", "No quote available")
                st.markdown(f'<div class="fact-evidence-quote">"{quote}"</div>', unsafe_allow_html=True)
                st.caption(
                    f"Document: {fact.get('document_name', fact.get('document_id', ''))} | "
                    f"Page: {fact.get('source_page_start', 1)} to {fact.get('source_page_end', 1)} | "
                    f"Fact ID: `{fact.get('id', '')}`"
                )

            st.markdown("<hr style='margin: 12px 0; border: none; border-top: 1px solid #f1f5f9;'>", unsafe_allow_html=True)
