"""
WTC vs Workday Leave Deviation - Streamlit app.

Run via run_app.bat (double-click), or manually with:
    streamlit run app.py
"""
import os
import io
import base64
import pandas as pd
import streamlit as st
from PIL import Image

from leave_compare import build_report, save_report_xlsx

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
PIN_ICON_PATH = os.path.join(ASSETS_DIR, "tomtom_pin.png")
LOCKUP_DIAP_PATH = os.path.join(ASSETS_DIR, "tomtom_lockup_diap.png")


def _logo_on_black(path, width_px):
    """Renders the red-pin / white-text logo on a black background block."""
    if not os.path.exists(path):
        return
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    st.markdown(
        f"<div style='background:#000; padding:12px 18px; border-radius:8px; "
        f"display:inline-block; margin-bottom:10px;'>"
        f"<img src='data:image/png;base64,{b64}' width='{width_px}'/></div>",
        unsafe_allow_html=True,
    )


page_icon = Image.open(PIN_ICON_PATH) if os.path.exists(PIN_ICON_PATH) else "📅"
st.set_page_config(
    page_title="Leave Deviation Report",
    page_icon=page_icon,
    layout="wide",
    initial_sidebar_state="collapsed",
)

_logo_on_black(LOCKUP_DIAP_PATH, 320)

st.title("WTC vs Workday - Leave Deviation Report")
st.caption(
    "Upload the WTC dump (CSV) and the Workday General Time Off Takes Report (Excel). "
    "Birthday Leave is detected automatically (typos, abbreviations, wording and case "
    "differences are all tolerated) and excluded from the comparison. Leave is compared "
    "by number of leave entries, not day totals."
)
st.markdown(
    "<div style='color:#666; font-size:1.15em; margin-top:-8px; margin-bottom:8px;'>"
    "© ADP Team, TomTom &nbsp;|&nbsp; "
    "<a href='mailto:prabhakar.chaudhari@tomtom.com'>prabhakar.chaudhari@tomtom.com</a>"
    "</div>",
    unsafe_allow_html=True,
)
st.divider()

col1, col2 = st.columns(2)
with col1:
    wtc_upload = st.file_uploader("WTC Dump (.csv)", type=["csv"])
with col2:
    workday_upload = st.file_uploader("Workday Dump (.xlsx)", type=["xlsx"])

with st.expander("Advanced settings"):
    hours_per_day = st.number_input(
        "WTC hours-per-day conversion", min_value=1.0, max_value=24.0, value=8.0, step=0.5
    )

st.subheader("Output")
default_dir = os.path.join(os.path.expanduser("~"), "Desktop")
output_dir = st.text_input("Output folder path", value=default_dir)
output_name = st.text_input("Output file name", value="Leave_Deviation_Report.xlsx")

run_clicked = st.button("Generate Report", type="primary", disabled=not (wtc_upload and workday_upload))

if run_clicked:
    with st.spinner("Comparing WTC and Workday leave records..."):
        try:
            rows = build_report(wtc_upload, workday_upload, hours_per_day=hours_per_day)
        except Exception as e:
            st.error(f"Failed to process the files: {e}")
            st.stop()

    df = pd.DataFrame(rows)
    st.session_state["report_df"] = df
    st.session_state["report_rows"] = rows

if "report_rows" in st.session_state:
    rows = st.session_state["report_rows"]
    df = st.session_state["report_df"]

    if not rows:
        st.warning(
            "No employees could be matched between the two files - the report is empty. "
            "Double-check you uploaded the correct WTC dump and Workday export."
        )
    else:
        matched = [r for r in rows if r["Entries Deviation"] != "N/A"]
        real_dev = [r for r in matched if isinstance(r["Entries Deviation"], (int, float)) and r["Entries Deviation"] != 0]
        unmatched = [r for r in rows if r["Entries Deviation"] == "N/A"]

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Employees compared", len(matched))
        m2.metric("With a real deviation", len(real_dev))
        m3.metric("Birthday Leave records excluded", sum(1 for r in rows if r["Birthday Leave (Yes/No)"] == "Yes"))
        m4.metric("No match found", len(unmatched))

        def highlight_row(row):
            dev = row["Entries Deviation"]
            if dev == "N/A":
                return [""] * len(row)
            if isinstance(dev, (int, float)) and dev != 0:
                return ["background-color: #ff7c80"] * len(row)
            if row["Birthday Leave (Yes/No)"] == "Yes":
                return ["background-color: #c6e0b4"] * len(row)
            return [""] * len(row)

        # Row-coloring needs the pandas Styler, which requires the optional
        # "jinja2" package. If it's missing (or styling fails for any other
        # reason) on someone's machine, fall back to a plain table instead of
        # crashing the whole page - the Save/Download buttons must still work.
        try:
            st.dataframe(df.style.apply(highlight_row, axis=1), use_container_width=True, height=600)
        except Exception:
            st.info(
                "Row color-highlighting isn't available on this machine (missing the "
                "'jinja2' package) - showing the table without colors. Run "
                "install_requirements.bat again to enable highlighting."
            )
            st.dataframe(df, use_container_width=True, height=600)

        if st.button("Save to output path"):
            out_path = os.path.join(output_dir, output_name)
            try:
                os.makedirs(output_dir, exist_ok=True)
                save_report_xlsx(rows, out_path)
                st.success(f"Saved: {out_path}")
            except Exception as e:
                st.error(f"Could not save to '{out_path}': {e}")

        try:
            buf = io.BytesIO()
            tmp_path = os.path.join(os.getcwd(), "_tmp_leave_deviation_download.xlsx")
            save_report_xlsx(rows, tmp_path)
            with open(tmp_path, "rb") as f:
                buf.write(f.read())
            os.remove(tmp_path)
            st.download_button(
                "Download report (.xlsx)",
                data=buf.getvalue(),
                file_name=output_name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        except Exception as e:
            st.error(f"Could not prepare the download: {e}")
else:
    st.info("Upload both files and click 'Generate Report' to begin.")

st.markdown("---")
st.markdown(
    "<div style='text-align:center; color:gray; font-size:1.1em; line-height:1.8;'>"
    "© ADP Team, TomTom<br/>"
    "Developer: <a href='mailto:prabhakar.chaudhari@tomtom.com'>prabhakar.chaudhari@tomtom.com</a><br/>"
    "Contact person / idea: <a href='mailto:prajakta.satpute@tomtom.com'>prajakta.satpute@tomtom.com</a>"
    "</div>",
    unsafe_allow_html=True,
)
