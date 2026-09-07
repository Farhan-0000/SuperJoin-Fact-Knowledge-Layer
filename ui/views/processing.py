"""Processing Progress view."""

from __future__ import annotations

import streamlit as st

from ui.data_service import get_data_service


def render_processing_view() -> None:
    """Render pipeline execution progress and job status monitor."""
    st.title("⏱️ Processing Progress")
    st.markdown("Monitor real-time asynchronous pipeline execution stages across documents.")

    service = get_data_service()
    jobs = service.get_jobs(limit=10)

    if not jobs:
        st.info("No processing jobs found. Go to 'Upload Documents' to start a new job.")
        return

    # Select active job: either from session state or the latest one
    active_job_id = st.session_state.get("active_job_id")
    job_ids = [j["id"] for j in jobs]

    default_idx = 0
    if active_job_id in job_ids:
        default_idx = job_ids.index(active_job_id)

    selected_job_id = st.selectbox(
        "Select Job:",
        options=job_ids,
        index=default_idx,
        format_func=lambda x: f"{x} ({next((j['status'] for j in jobs if j['id'] == x), '')})",
    )

    current_job = service.get_job(selected_job_id)
    if not current_job:
        st.warning("Job not found.")
        return

    # ── Active Job Progress Card ───────────────────────────────────────
    st.markdown("### Job Execution Monitor")

    col_stat, col_stage, col_items = st.columns(3)
    status_val = current_job.get("status", "queued")
    stage_val = current_job.get("current_stage", "queued")
    progress_val = float(current_job.get("progress", 0.0))
    completed_items = current_job.get("completed_items", 0)
    total_items = current_job.get("total_items", 0)

    with col_stat:
        if status_val == "completed":
            st.success(f"**Status**: {status_val.upper()}")
        elif status_val == "running":
            st.info(f"**Status**: {status_val.upper()}")
        elif status_val == "failed":
            st.error(f"**Status**: {status_val.upper()}")
        else:
            st.warning(f"**Status**: {status_val.upper()}")

    with col_stage:
        st.markdown(f"**Current Stage**: `{stage_val}`")

    with col_items:
        st.markdown(f"**Items Completed**: `{completed_items} / {total_items}`")

    # Progress Bar
    clamped_progress = max(0.0, min(1.0, progress_val))
    st.progress(clamped_progress)
    st.caption(f"Progress: {int(clamped_progress * 100)}%")

    # Stage Pipeline Stepper
    pipeline_stages = [
        ("chunking", "1. Chunking"),
        ("fact_extraction", "2. Fact Extraction"),
        ("normalization", "3. Normalization"),
        ("candidate_generation", "4. Candidate Generation"),
        ("relationship_reasoning", "5. Relationship Reasoning"),
        ("completed", "6. Completed"),
    ]

    cols = st.columns(len(pipeline_stages))
    for idx, (s_key, s_label) in enumerate(pipeline_stages):
        with cols[idx]:
            if status_val == "completed":
                st.markdown(f"🟢 **{s_label}**")
            elif s_key == stage_val:
                st.markdown(f"🔵 **{s_label}** *(active)*")
            elif current_job.get("completed_items", 0) > idx:
                st.markdown(f"✅ **{s_label}**")
            else:
                st.markdown(f"⚪ {s_label}")

    if status_val == "completed":
        st.success("🎉 Pipeline execution completed successfully!")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("📊 View Knowledge Summary", use_container_width=True):
                st.session_state["active_nav"] = "Knowledge Summary"
                st.rerun()
        with c2:
            if st.button("🔀 Explore Relationships", type="primary", use_container_width=True):
                st.session_state["active_nav"] = "Relationships"
                st.rerun()

    elif status_val == "failed":
        st.error(f"Job failed: {current_job.get('error_message', 'Unknown error')}")

    elif status_val in ("running", "queued"):
        st.button("🔄 Refresh Status", on_click=lambda: None)

    st.markdown("---")

    # ── Job History ────────────────────────────────────────────────────
    st.subheader("Job History")
    hist_table = []
    for j in jobs:
        hist_table.append({
            "Job ID": j["id"],
            "Type": j["job_type"].upper(),
            "Documents": len(j.get("doc_ids", [])),
            "Status": j["status"].upper(),
            "Stage": j.get("current_stage", ""),
            "Progress": f"{int(j.get('progress', 0.0) * 100)}%",
            "Started": (j.get("started_at") or "")[:19].replace("T", " "),
            "Completed": (j.get("completed_at") or "")[:19].replace("T", " "),
        })

    st.dataframe(hist_table, use_container_width=True)
