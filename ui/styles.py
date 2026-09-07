"""CSS styles and HTML component templates for the Streamlit UI."""

import streamlit as st


def inject_custom_css() -> None:
    """Inject polished styling matching the Fact Knowledge Layer design system."""
    st.markdown(
        """
        <style>
        /* ── Base Fonts and Colors ───────────────────────────────────── */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

        html, body, [class*="css"] {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        }

        /* ── Top Stat Badges ────────────────────────────────────────── */
        .stat-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 16px;
            margin-bottom: 24px;
        }

        .stat-card {
            display: flex;
            align-items: center;
            padding: 16px 20px;
            border-radius: 12px;
            background: #ffffff;
            border: 1px solid #e2e8f0;
            box-shadow: 0 1px 3px rgba(0,0,0,0.04);
            transition: all 0.2s ease-in-out;
        }

        .stat-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.08);
        }

        .stat-icon-wrapper {
            width: 44px;
            height: 44px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 20px;
            margin-right: 16px;
            flex-shrink: 0;
        }

        .stat-card.corroborates {
            border-left: 4px solid #10b981;
        }
        .stat-card.corroborates .stat-icon-wrapper {
            background-color: #ecfdf5;
            color: #059669;
        }

        .stat-card.contradicts {
            border-left: 4px solid #ef4444;
        }
        .stat-card.contradicts .stat-icon-wrapper {
            background-color: #fef2f2;
            color: #dc2626;
        }

        .stat-card.reconciles {
            border-left: 4px solid #6366f1;
        }
        .stat-card.reconciles .stat-icon-wrapper {
            background-color: #eef2ff;
            color: #4f46e5;
        }

        .stat-card.uncertain {
            border-left: 4px solid #f59e0b;
        }
        .stat-card.uncertain .stat-icon-wrapper {
            background-color: #fffbeb;
            color: #d97706;
        }

        .stat-content {
            display: flex;
            flex-direction: column;
        }

        .stat-number {
            font-size: 26px;
            font-weight: 700;
            line-height: 1.1;
            color: #1e293b;
        }

        .stat-label {
            font-size: 13px;
            font-weight: 600;
            color: #475569;
            margin-top: 2px;
        }

        .stat-desc {
            font-size: 11px;
            color: #94a3b8;
        }

        /* ── Badges ─────────────────────────────────────────────────── */
        .rel-badge {
            display: inline-flex;
            align-items: center;
            padding: 4px 10px;
            border-radius: 9999px;
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.05em;
            text-transform: uppercase;
        }

        .rel-badge.reconciles {
            background-color: #e0e7ff;
            color: #3730a3;
        }

        .rel-badge.corroborates {
            background-color: #d1fae5;
            color: #065f46;
        }

        .rel-badge.contradicts {
            background-color: #fee2e2;
            color: #991b1b;
        }

        .rel-badge.uncertain {
            background-color: #fef3c7;
            color: #92400e;
        }

        .rel-badge.unrelated {
            background-color: #f1f5f9;
            color: #475569;
        }

        .confidence-pill {
            display: inline-flex;
            align-items: center;
            padding: 3px 8px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
            background: #f8fafc;
            color: #334155;
            border: 1px solid #e2e8f0;
        }

        /* ── Dimension Chips ─────────────────────────────────────────── */
        .chip {
            display: inline-flex;
            align-items: center;
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 500;
            background-color: #f1f5f9;
            color: #334155;
            margin-right: 6px;
            margin-bottom: 6px;
        }

        .chip.primary {
            background-color: #eff6ff;
            color: #1d4ed8;
            font-weight: 600;
            border: 1px solid #bfdbfe;
        }

        /* ── Comparison Cards ───────────────────────────────────────── */
        .fact-card {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.03);
            height: 100%;
        }

        .fact-card-header {
            font-size: 13px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: #2563eb;
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .fact-metric-title {
            font-size: 14px;
            color: #64748b;
            font-weight: 500;
        }

        .fact-main-val {
            font-size: 32px;
            font-weight: 800;
            color: #0f172a;
            margin: 4px 0 12px 0;
            line-height: 1.1;
        }

        .fact-meta-row {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 12px;
            color: #475569;
            margin-bottom: 6px;
        }

        .fact-evidence-quote {
            background: #f8fafc;
            border-left: 3px solid #3b82f6;
            padding: 10px 14px;
            border-radius: 0 6px 6px 0;
            font-size: 12.5px;
            line-height: 1.5;
            color: #1e293b;
            font-style: italic;
            margin-top: 8px;
        }

        /* ── Context Comparison Table ───────────────────────────────── */
        .comparison-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            margin-top: 12px;
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid #e2e8f0;
        }

        .comparison-table th {
            background: #f8fafc;
            color: #475569;
            font-weight: 600;
            padding: 10px 14px;
            text-align: left;
            border-bottom: 1px solid #e2e8f0;
        }

        .comparison-table td {
            padding: 10px 14px;
            border-bottom: 1px solid #f1f5f9;
            color: #1e293b;
        }

        .comparison-table tr:last-child td {
            border-bottom: none;
        }

        .comparison-table tr:hover {
            background-color: #f8fafc;
        }

        .match-badge-yes {
            color: #16a34a;
            font-weight: 600;
            display: inline-flex;
            align-items: center;
            gap: 4px;
        }

        .match-badge-no {
            color: #dc2626;
            font-weight: 600;
            display: inline-flex;
            align-items: center;
            gap: 4px;
        }

        /* ── Sidebar Styling ────────────────────────────────────────── */
        .sidebar-brand {
            padding: 12px 0 20px 0;
            border-bottom: 1px solid #e2e8f0;
            margin-bottom: 20px;
        }

        .sidebar-title {
            font-size: 17px;
            font-weight: 700;
            color: #0f172a;
            line-height: 1.2;
        }

        .sidebar-subtitle {
            font-size: 12px;
            color: #64748b;
            margin-top: 2px;
        }

        .sidebar-footer {
            padding-top: 20px;
            border-top: 1px solid #e2e8f0;
            margin-top: 30px;
            font-size: 11px;
            color: #64748b;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_stat_card(
    title: str,
    count: int,
    subtitle: str,
    card_type: str,
    icon: str,
) -> str:
    """Return HTML string for top stat card."""
    return f"""
    <div class="stat-card {card_type}">
        <div class="stat-icon-wrapper">
            {icon}
        </div>
        <div class="stat-content">
            <div class="stat-number">{count}</div>
            <div class="stat-label">{title}</div>
            <div class="stat-desc">{subtitle}</div>
        </div>
    </div>
    """


def render_badge(rel_type: str) -> str:
    """Return HTML string for relationship badge."""
    t = rel_type.lower()
    return f'<span class="rel-badge {t}">{rel_type}</span>'
