"""Upload Documents view."""

from __future__ import annotations

import streamlit as st

from ui.data_service import get_data_service


def render_upload_view() -> None:
    """Render document upload and inventory screen."""
    st.title("📤 Upload Documents")
    st.markdown("Upload one or more PDF documents to extract facts, normalize entities, and identify cross-document relationships.")

    service = get_data_service()

    # ── Upload Section ─────────────────────────────────────────────────
    with st.container():
        uploaded_files = st.file_uploader(
            "Select or drop PDF documents here",
            type=["pdf"],
            accept_multiple_files=True,
            help="Only PDF files are accepted. SHA-256 hashes will be computed prior to processing.",
        )

        col_btn, col_demo = st.columns([1, 1])

        with col_btn:
            if st.button("📥 Process Uploads", type="primary", disabled=not uploaded_files):
                new_count = 0
                reused_count = 0
                for file in uploaded_files:
                    file_bytes = file.read()
                    doc, is_new = service.upload_pdf_bytes(file_bytes, file.name)
                    if is_new:
                        new_count += 1
                        st.success(f"Ingested **{file.name}** ({doc.get('page_count', 0)} pages)")
                    else:
                        reused_count += 1
                        st.info(f"Reused existing record for **{file.name}** (SHA-256 matched: `{doc.get('sha256', '')[:12]}...`)")

                st.rerun()

        with col_demo:
            if st.button("✨ Load Sample Demo Dataset", help="Seed sample documents (Annual Report, Investor Report, Sustainability Report) with rich relationships"):
                service.seed_demo_dataset()
                st.success("Sample demo dataset successfully loaded!")
                st.rerun()

    st.markdown("---")

    # ── Ingested Documents Inventory ───────────────────────────────────
    st.subheader("Document Inventory")
    docs = service.get_documents(limit=100)

    if not docs:
        st.info("No documents uploaded yet. Upload PDFs above or click 'Load Sample Demo Dataset' to explore.")
        return

    # Let user select which documents to run pipeline on
    doc_options = {d["id"]: f"{d['original_filename']} ({d['page_count']} pages, {d['status']})" for d in docs}
    selected_doc_ids = st.multiselect(
        "Select documents to run pipeline on:",
        options=list(doc_options.keys()),
        default=list(doc_options.keys())[:3],
        format_func=lambda x: doc_options.get(x, x),
    )

    col_run, _ = st.columns([1, 2])
    with col_run:
        if st.button("🚀 Start Processing Pipeline", type="primary", disabled=not selected_doc_ids):
            job_id = service.start_pipeline_job(selected_doc_ids, mode="full")
            st.session_state["active_job_id"] = job_id
            st.session_state["active_nav"] = "Processing"
            st.rerun()

    # Render Document Table
    table_data = []
    for d in docs:
        table_data.append({
            "Document ID": d["id"][:8] + "...",
            "Filename": d["original_filename"],
            "Pages": d["page_count"],
            "Status": d["status"].upper(),
            "SHA-256": d["sha256"][:12] + "...",
            "Uploaded": d.get("created_at", "")[:19].replace("T", " "),
        })

    st.dataframe(table_data, use_container_width=True)
