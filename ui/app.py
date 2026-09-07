"""Main Streamlit Application for Fact Knowledge Layer."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is in sys.path so ui package and app package can be imported cleanly
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from ui.data_service import get_data_service
from ui.styles import inject_custom_css
from ui.views.failures import render_failures_view
from ui.views.facts import render_facts_view
from ui.views.knowledge import render_knowledge_view
from ui.views.processing import render_processing_view
from ui.views.relationships import render_relationships_view
from ui.views.upload import render_upload_view

# ── 1. Page Configuration ──────────────────────────────────────────────
st.set_page_config(
    page_title="Fact Knowledge Layer",
    page_icon="📑",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Inject custom design tokens
inject_custom_css()

# Initialize data service
service = get_data_service()

# ── 2. Sidebar Navigation ──────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        """
        <div class="sidebar-brand">
            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 6px;">
                <span style="font-size: 26px;">📑</span>
                <span class="sidebar-title">Fact Knowledge Layer</span>
            </div>
            <div class="sidebar-subtitle">Turn documents into connected facts</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    nav_options = [
        "Upload Documents",
        "Processing",
        "Knowledge Summary",
        "Facts Explorer",
        "Relationships",
        "Failures & Uncertainty",
    ]

    # Sync navigation state
    if "active_nav" not in st.session_state:
        st.session_state["active_nav"] = "Relationships" if service.get_knowledge_summary()["relationships"] > 0 else "Upload Documents"

    active_index = 0
    if st.session_state["active_nav"] in nav_options:
        active_index = nav_options.index(st.session_state["active_nav"])

    nav_icons = {
        "Upload Documents": "📤 Upload Documents",
        "Processing": "⏱️ Processing",
        "Knowledge Summary": "📊 Knowledge Summary",
        "Facts Explorer": "📄 Facts Explorer",
        "Relationships": "🔀 Relationships",
        "Failures & Uncertainty": "⚠️ Failures & Uncertainty",
    }

    selected_nav = st.radio(
        "Navigation",
        options=nav_options,
        index=active_index,
        format_func=lambda x: nav_icons.get(x, x),
        label_visibility="collapsed",
    )

    if selected_nav != st.session_state["active_nav"]:
        st.session_state["active_nav"] = selected_nav
        st.rerun()

    # ── Sidebar Document Inventory Mini-List ───────────────────────────
    docs = service.get_documents(limit=5)
    st.markdown("<br>", unsafe_allow_html=True)
    if docs:
        st.markdown(f"🟢 **{len(docs)} documents processed**")
        for d in docs:
            st.caption(f"📄 {d['original_filename']}")
    else:
        st.caption("⚪ No documents in storage yet")

    # ── Attribution & Version Footer ───────────────────────────────────
    st.markdown(
        """
        <div class="sidebar-footer">
            <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; margin-bottom: 12px;">
                <div style="display: flex; align-items: center; gap: 6px; font-weight: 600; color: #4338ca; margin-bottom: 4px;">
                    <span>✨</span> Superjoin VIT 2026
                </div>
                <div style="font-size: 11px; color: #64748b;">
                    Engineering Intern Assignment Prototype
                </div>
            </div>
            <div style="color: #94a3b8; font-size: 11px;">v0.1.0</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ── 3. Main Route Dispatcher ───────────────────────────────────────────
current_view = st.session_state.get("active_nav", "Relationships")

if current_view == "Upload Documents":
    render_upload_view()
elif current_view == "Processing":
    render_processing_view()
elif current_view == "Knowledge Summary":
    render_knowledge_view()
elif current_view == "Facts Explorer":
    render_facts_view()
elif current_view == "Relationships":
    render_relationships_view()
elif current_view == "Failures & Uncertainty":
    render_failures_view()
