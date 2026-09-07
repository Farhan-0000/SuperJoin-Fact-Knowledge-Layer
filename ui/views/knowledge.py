"""Knowledge Summary view."""

from __future__ import annotations

import streamlit as st

from ui.data_service import get_data_service
from ui.styles import render_stat_card


def render_knowledge_view() -> None:
    """Render high-level aggregated statistics and analytics."""
    st.title("📊 Knowledge Summary")
    st.markdown("Aggregated metrics across ingested documents, extracted claims, validations, and cross-document relationships.")

    service = get_data_service()
    stats = service.get_knowledge_summary()

    # ── Top Level Stat Cards ───────────────────────────────────────────
    st.markdown("### Cross-Document Highlights")
    stat_cols = st.columns(4)
    with stat_cols[0]:
        st.markdown(
            render_stat_card("Corroborations", stats["corroborations"], "Facts that agree", "corroborates", "✓"),
            unsafe_allow_html=True,
        )
    with stat_cols[1]:
        st.markdown(
            render_stat_card("Contradictions", stats["contradictions"], "Conflicting facts", "contradicts", "✕"),
            unsafe_allow_html=True,
        )
    with stat_cols[2]:
        st.markdown(
            render_stat_card("Reconciliations", stats["reconciliations"], "Different but compatible", "reconciles", "🔗"),
            unsafe_allow_html=True,
        )
    with stat_cols[3]:
        st.markdown(
            render_stat_card("Uncertain", stats["uncertain"], "Needs more context", "uncertain", "?"),
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Secondary Metrics ──────────────────────────────────────────────
    st.markdown("### Inventory & Quality Metrics")
    m_col1, m_col2, m_col3, m_col4, m_col5 = st.columns(5)
    with m_col1:
        st.metric("Documents Ingested", stats["documents"])
    with m_col2:
        st.metric("Total Extracted Facts", stats["facts"])
    with m_col3:
        st.metric("Validated Facts", stats["validated_facts"])
    with m_col4:
        st.metric("Warnings", stats["warnings"])
    with m_col5:
        st.metric("Rejected (Hallucinated)", stats["rejected"])

    st.markdown("---")

    # ── Distribution Visuals ───────────────────────────────────────────
    c_left, c_right = st.columns(2)

    with c_left:
        st.subheader("Relationship Distribution")
        rel_data = {
            "CORROBORATES": stats["corroborations"],
            "CONTRADICTS": stats["contradictions"],
            "RECONCILES": stats["reconciliations"],
            "UNCERTAIN": stats["uncertain"],
            "UNRELATED": stats["unrelated"],
        }
        st.bar_chart(rel_data)

    with c_right:
        st.subheader("Fact Validation Breakdown")
        val_data = {
            "Validated": stats["validated_facts"],
            "Warning": stats["warnings"],
            "Rejected": stats["rejected"],
        }
        st.bar_chart(val_data)

    st.markdown("---")

    # ── Canonical Entities ─────────────────────────────────────────────
    st.subheader(f"Resolved Entities ({stats['entities']})")
    entities = service.get_entity_breakdown(limit=50)

    if entities:
        ent_table = []
        for e in entities:
            ent_table.append({
                "Canonical Name": e["canonical_name"],
                "Entity Type": (e.get("entity_type") or "other").upper(),
                "Associated Facts": e.get("fact_count", 0),
                "Aliases": ", ".join(e.get("aliases", [])) or "None",
            })
        st.dataframe(ent_table, use_container_width=True)
    else:
        st.caption("No resolved entities registered yet.")
