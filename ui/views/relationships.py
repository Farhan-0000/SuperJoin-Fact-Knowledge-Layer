"""Cross-Document Relationships Explorer & Evidence View matching exact UI design mockups."""

from __future__ import annotations

import streamlit as st

from ui.data_service import get_data_service
from ui.styles import render_badge, render_stat_card


def render_relationships_view() -> None:
    """Render the master-detail Cross-Document Relationships screen."""
    service = get_data_service()
    stats = service.get_knowledge_summary()

    # ── Header ─────────────────────────────────────────────────────────
    st.title("Cross-Document Relationships")
    st.markdown("Explore how factual claims connect, corroborate, conflict, or reconcile across your documents.")

    # ── Top Stat Banner (4 Cards) ──────────────────────────────────────
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

    # ── Search & Filter Controls ───────────────────────────────────────
    search_col, sort_col = st.columns([3, 1])
    with search_col:
        search_query = st.text_input("🔍 Search facts, entities, or keywords...", "", key="rel_search")
    with sort_col:
        sort_choice = st.selectbox("Sort by", ["Confidence", "Date"], index=0)
        sort_by = "confidence" if sort_choice == "Confidence" else "date"

    # Filter tabs
    tab_counts = {
        "All": stats["relationships"],
        "Corroborates": stats["corroborations"],
        "Contradicts": stats["contradictions"],
        "Reconciles": stats["reconciliations"],
        "Uncertain": stats["uncertain"],
    }

    filter_keys = list(tab_counts.keys())
    selected_tab = st.radio(
        "Filter by Type:",
        options=filter_keys,
        horizontal=True,
        format_func=lambda k: f"{k} ({tab_counts.get(k, 0)})",
        label_visibility="collapsed",
    )

    # Fetch enriched relationships
    rel_type_param = selected_tab.lower() if selected_tab != "All" else None
    relationships = service.get_relationships_enriched(
        rel_type=rel_type_param,
        sort_by=sort_by,
        search_query=search_query if search_query else None,
        limit=100,
    )

    if not relationships:
        st.info("No relationships found matching current filters. Click 'Load Sample Demo Dataset' in Uploads to populate demo data.")
        return

    # Keep track of active selected relationship index in session state
    if "selected_rel_id" not in st.session_state or not any(r["id"] == st.session_state["selected_rel_id"] for r in relationships):
        st.session_state["selected_rel_id"] = relationships[0]["id"]

    # ── Master-Detail Two-Column Layout ────────────────────────────────
    col_list, col_detail = st.columns([4, 6], gap="large")

    # ── Left Column: Relationship List ─────────────────────────────────
    with col_list:
        st.markdown(f"#### Relationships ({len(relationships)})")

        for r in relationships:
            r_id = r["id"]
            r_type = r.get("relationship_type", "unrelated").upper()
            r_conf = int(r.get("confidence", 1.0) * 100)
            doc_a = r.get("fa_doc_name") or "Document A"
            doc_b = r.get("fb_doc_name") or "Document B"

            # Generate short title/summary
            explanation = r.get("explanation", "")
            first_sentence = explanation.split(".")[0] if explanation else f"{r.get('fa_subject')} {r.get('fa_predicate')}"
            if len(first_sentence) > 65:
                first_sentence = first_sentence[:65] + "..."

            is_selected = (r_id == st.session_state["selected_rel_id"])
            border_color = "#3b82f6" if is_selected else "#e2e8f0"
            bg_color = "#f8fafc" if is_selected else "#ffffff"

            # Preview Card Box
            st.markdown(
                f"""
                <div style="
                    border: 2px solid {border_color};
                    border-radius: 10px;
                    padding: 12px 16px;
                    background: {bg_color};
                    margin-bottom: 10px;
                    cursor: pointer;
                ">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                        {render_badge(r_type)}
                        <span style="font-size: 13px; font-weight: 700; color: #1e293b;">{r_conf}% <span style="font-size: 11px; font-weight: 500; color: #64748b;">confidence</span></span>
                    </div>
                    <div style="font-size: 14px; font-weight: 600; color: #0f172a; margin-bottom: 4px;">{first_sentence}</div>
                    <div style="font-size: 12px; color: #64748b;">📄 {doc_a} ↔ 📄 {doc_b}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # Selection button
            if st.button("Inspect Details", key=f"btn_select_{r_id}", use_container_width=True):
                st.session_state["selected_rel_id"] = r_id
                st.rerun()

    # ── Right Column: Selected Relationship Detail View ────────────────
    active_rel = next((r for r in relationships if r["id"] == st.session_state["selected_rel_id"]), relationships[0])

    with col_detail:
        rel_type = active_rel.get("relationship_type", "reconciles").upper()
        conf_pct = int(active_rel.get("confidence", 1.0) * 100)
        primary_dim = active_rel.get("primary_dimension") or "value"
        explanation_full = active_rel.get("explanation", "")

        # Top Bar: Badge & Confidence
        top_l, top_r = st.columns([1, 1])
        with top_l:
            st.markdown(render_badge(rel_type), unsafe_allow_html=True)
        with top_r:
            st.markdown(
                f"<div style='text-align: right; font-size: 15px; font-weight: 700; color: #2563eb;'>Confidence <span style='font-size: 20px; font-weight: 800;'>{conf_pct}%</span></div>",
                unsafe_allow_html=True,
            )

        # Title / Claim
        title_text = explanation_full.split(".")[0] if explanation_full else f"{active_rel.get('fa_subject')} Comparison"
        st.markdown(f"### {title_text}")

        # Explanation
        st.markdown(
            f"<div style='font-size: 13.5px; line-height: 1.6; color: #334155; margin-bottom: 14px;'>{explanation_full}</div>",
            unsafe_allow_html=True,
        )

        # Context Dimension Pills
        dim_chips = [
            f"<span class='chip primary'>📅 Dimension: {primary_dim.upper()}</span>",
            "<span class='chip'>Same entity</span>",
            "<span class='chip'>Context verified</span>",
        ]
        if rel_type == "RECONCILES":
            dim_chips.append("<span class='chip'>Compatible claims</span>")
        elif rel_type == "CONTRADICTS":
            dim_chips.append("<span class='chip'>Incompatible claims</span>")
        elif rel_type == "CORROBORATES":
            dim_chips.append("<span class='chip'>Agreed claims</span>")

        st.markdown("".join(dim_chips), unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)

        # ── Side-by-Side Comparison: Fact A vs Fact B ───────────────────
        c_fa, c_mid, c_fb = st.columns([5, 1, 5])

        # Fact A Box
        with c_fa:
            fa_subj = active_rel.get("fa_subject", "")
            fa_pred = active_rel.get("fa_predicate", "")
            fa_val = active_rel.get("fa_value", "")
            fa_time = active_rel.get("fa_time") or "N/A"
            fa_scope = active_rel.get("fa_scope") or active_rel.get("fa_geography") or "Global"
            fa_doc = active_rel.get("fa_doc_name") or "Document A"
            fa_page = active_rel.get("fa_page", 1)
            fa_quote = active_rel.get("fa_quote") or active_rel.get("evidence_fact_a") or "No quote"

            st.markdown(
                f"""
                <div class="fact-card">
                    <div class="fact-card-header">📄 Fact A</div>
                    <div class="fact-metric-title">{fa_pred.title() if fa_pred else 'Metric'}</div>
                    <div class="fact-main-val">{fa_val}</div>
                    <div class="fact-meta-row"><strong>Period:</strong> {fa_time}</div>
                    <div class="fact-meta-row"><strong>Scope:</strong> {fa_scope}</div>
                    <div class="fact-meta-row" style="margin-top: 10px; color: #2563eb; font-weight: 500;">
                        📄 {fa_doc} &bull; Page {fa_page}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            with st.expander("🔎 Source evidence", expanded=False):
                st.markdown(f'<div class="fact-evidence-quote">"{fa_quote}"</div>', unsafe_allow_html=True)
                st.caption(f"Doc: {fa_doc} (Page {fa_page})")

        # Transfer Arrow Separator
        with c_mid:
            st.markdown(
                "<div style='display: flex; height: 100%; align-items: center; justify-content: center; font-size: 28px; color: #94a3b8;'>⇄</div>",
                unsafe_allow_html=True,
            )

        # Fact B Box
        with c_fb:
            fb_subj = active_rel.get("fb_subject", "")
            fb_pred = active_rel.get("fb_predicate", "")
            fb_val = active_rel.get("fb_value", "")
            fb_time = active_rel.get("fb_time") or "N/A"
            fb_scope = active_rel.get("fb_scope") or active_rel.get("fb_geography") or "Global"
            fb_doc = active_rel.get("fb_doc_name") or "Document B"
            fb_page = active_rel.get("fb_page", 1)
            fb_quote = active_rel.get("fb_quote") or active_rel.get("evidence_fact_b") or "No quote"

            st.markdown(
                f"""
                <div class="fact-card">
                    <div class="fact-card-header">📄 Fact B</div>
                    <div class="fact-metric-title">{fb_pred.title() if fb_pred else 'Metric'}</div>
                    <div class="fact-main-val">{fb_val}</div>
                    <div class="fact-meta-row"><strong>Period:</strong> {fa_time if fb_time == 'N/A' else fb_time}</div>
                    <div class="fact-meta-row"><strong>Scope:</strong> {fb_scope}</div>
                    <div class="fact-meta-row" style="margin-top: 10px; color: #2563eb; font-weight: 500;">
                        📄 {fb_doc} &bull; Page {fb_page}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            with st.expander("🔎 Source evidence", expanded=False):
                st.markdown(f'<div class="fact-evidence-quote">"{fb_quote}"</div>', unsafe_allow_html=True)
                st.caption(f"Doc: {fb_doc} (Page {fb_page})")

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Context Comparison Table ───────────────────────────────────
        st.markdown("#### Context Comparison")

        context_comp = active_rel.get("context_comp") or []

        # Convert dictionary context_comp (from real RelationshipEngine) into standard comparison rows
        if isinstance(context_comp, dict):
            c = context_comp
            unit_val_a = c.get("unit_a") or c.get("currency_a") or active_rel.get("fa_unit") or "-"
            unit_val_b = c.get("unit_b") or c.get("currency_b") or active_rel.get("fb_unit") or "-"
            unit_match = bool(c.get("unit_match") if c.get("unit_match") is not None else c.get("currency_match", False))

            context_comp = [
                {
                    "dimension": "Entity",
                    "fact_a": c.get("entity_a") or fa_subj,
                    "fact_b": c.get("entity_b") or fb_subj,
                    "match": bool(c.get("entity_match", False)),
                },
                {
                    "dimension": "Metric",
                    "fact_a": c.get("predicate_a") or fa_pred,
                    "fact_b": c.get("predicate_b") or fb_pred,
                    "match": bool(c.get("predicate_match", False)),
                },
                {
                    "dimension": "Time Period",
                    "fact_a": c.get("period_a") or fa_time,
                    "fact_b": c.get("period_b") or fb_time,
                    "match": bool(c.get("period_match", False)),
                },
                {
                    "dimension": "Geography",
                    "fact_a": c.get("geography_a") or active_rel.get("fa_geography") or "Global",
                    "fact_b": c.get("geography_b") or active_rel.get("fb_geography") or "Global",
                    "match": bool(c.get("geography_match", True)),
                },
                {
                    "dimension": "Unit / Currency",
                    "fact_a": unit_val_a,
                    "fact_b": unit_val_b,
                    "match": unit_match,
                },
                {
                    "dimension": "Scope",
                    "fact_a": c.get("scope_a") or fa_scope,
                    "fact_b": c.get("scope_b") or fb_scope,
                    "match": bool(c.get("scope_match", False)),
                },
            ]
        elif not isinstance(context_comp, list) or not context_comp:
            same_entity = (fa_subj.lower() == fb_subj.lower())
            same_pred = (fa_pred.lower() == fb_pred.lower())
            same_time = (fa_time.lower() == fb_time.lower()) and fa_time != "N/A"
            same_scope = (fa_scope.lower() == fb_scope.lower())
            same_unit = (active_rel.get("fa_unit") == active_rel.get("fb_unit"))

            context_comp = [
                {"dimension": "Entity", "fact_a": fa_subj, "fact_b": fb_subj, "match": same_entity},
                {"dimension": "Metric", "fact_a": fa_pred, "fact_b": fb_pred, "match": same_pred},
                {"dimension": "Time Period", "fact_a": fa_time, "fact_b": fb_time, "match": same_time},
                {"dimension": "Geography", "fact_a": active_rel.get("fa_geography", "Global"), "fact_b": active_rel.get("fb_geography", "Global"), "match": True},
                {"dimension": "Unit / Currency", "fact_a": active_rel.get("fa_unit") or "$", "fact_b": active_rel.get("fb_unit") or "$", "match": same_unit},
                {"dimension": "Scope", "fact_a": fa_scope, "fact_b": fb_scope, "match": same_scope},
            ]

        # Render Table
        rows_html = ""
        for item in context_comp:
            if not isinstance(item, dict):
                continue
            dim_name = item.get("dimension", "")
            val_a = item.get("fact_a") or "-"
            val_b = item.get("fact_b") or "-"
            is_match = item.get("match", False)
            badge_html = "<span class='match-badge-yes'>✓ Yes</span>" if is_match else "<span class='match-badge-no'>✕ No</span>"

            rows_html += f"""
            <tr>
                <td><strong>{dim_name}</strong></td>
                <td>{val_a}</td>
                <td>{val_b}</td>
                <td>{badge_html}</td>
            </tr>
            """

        table_html = f"""
        <table class="comparison-table">
            <thead>
                <tr>
                    <th style="width: 25%;">Dimension</th>
                    <th style="width: 32%;">Fact A</th>
                    <th style="width: 32%;">Fact B</th>
                    <th style="width: 11%;">Match</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
        """
        st.markdown(table_html, unsafe_allow_html=True)
