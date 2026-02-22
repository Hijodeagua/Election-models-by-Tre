"""Streamlit dashboard for Election Oracle.

Run with: streamlit run src/dashboard/app.py
"""

from __future__ import annotations

try:
    import streamlit as st
    import plotly.graph_objects as go
except ImportError:
    raise SystemExit(
        "Dashboard requires streamlit and plotly. "
        "Install with: pip install election-oracle[dev]"
    )


def main() -> None:
    st.set_page_config(page_title="Election Oracle", page_icon="🗳️", layout="wide")
    st.title("Election Oracle")
    st.markdown("*Polling aggregation and election forecasting*")

    tab_approval, tab_ballot, tab_senate = st.tabs([
        "Presidential Approval",
        "Generic Ballot",
        "Senate Races",
    ])

    with tab_approval:
        st.header("Presidential Approval")
        st.info("Connect data sources to populate this view. Run `refresh-data` first.")

    with tab_ballot:
        st.header("Generic Ballot")
        st.info("Generic ballot tracking coming soon.")

    with tab_senate:
        st.header("2026 Senate Races")
        st.info("Senate race polling coming soon.")


if __name__ == "__main__":
    main()
