# =============================================================================
# Copyright (c) 2025 ADP Team, TomTom. All rights reserved.
# This file is proprietary and confidential. Developed exclusively by the
# ADP Team at TomTom. Unauthorised copying, distribution or modification
# of this file, via any medium, is strictly prohibited.
# Contact: prabhakar.chaudhari@tomtom.com | sachin.shete@tomtom.com
# =============================================================================
"""
AA1 Name Checker -- Streamlit UI
Run:  streamlit run app.py
"""

import os
import datetime
import pandas as pd
import streamlit as st
from analyzer import DBConfig, run_analysis, to_excel_bytes

# Both MNR servers -- same credentials, different hosts
_DB_HOST_1 = "caprod-cpp-pgmnr-001.flatns.net"   # EUR / CIS
_DB_HOST_2 = "caprod-cpp-pgmnr-002.flatns.net"   # Americas / APAC / Africa / ME
_DB_PORT   = 5432
_DB_NAME   = "mnr"
_DB_USER   = "mnr_ro"

_SLACK_WEBHOOK = (
    "https://hooks.slack.com/services/"
    "T0LFAG45S/B0B93M0DUR5/3kVvksiZRH1AiNU22wiKyjUj"
)


def _post_slack(schema_old, schema_new, country, matched, errors, missing):
    import json as _json
    import urllib.request as _req
    try:
        user    = os.environ.get("USERNAME") or os.environ.get("USER") or "Unknown"
        machine = os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "-"
        now     = datetime.datetime.now().strftime("%d %b %Y  %H:%M")
        payload = {
            "blocks": [
                {"type": "header",
                 "text": {"type": "plain_text",
                          "text": "AA1 Name Checker - Usage Log", "emoji": True}},
                {"type": "section",
                 "fields": [
                     {"type": "mrkdwn", "text": f"*User:*\n{user}"},
                     {"type": "mrkdwn", "text": f"*Machine:*\n{machine}"},
                     {"type": "mrkdwn", "text": f"*Old Schema:*\n{schema_old}"},
                     {"type": "mrkdwn", "text": f"*New Schema:*\n{schema_new}"},
                 ]},
                {"type": "section",
                 "fields": [
                     {"type": "mrkdwn", "text": f"*Country:*\n{country or 'ALL (Globe)'}"},
                     {"type": "mrkdwn",
                      "text": f"*Results:*\nMatched: {matched} | Name Error: {errors} | Missing: {missing}"},
                 ]},
                {"type": "context",
                 "elements": [{"type": "mrkdwn", "text": f"Time: {now}"}]},
            ]
        }
        data = _json.dumps(payload).encode("utf-8")
        req = _req.Request(_SLACK_WEBHOOK, data=data,
                           headers={"Content-Type": "application/json"}, method="POST")
        with _req.urlopen(req, timeout=10) as resp:
            if resp.read().decode() == "ok":
                st.toast("Usage logged to Slack", icon="✅")
    except Exception as _e:
        st.warning(f"Slack logging failed: {_e}")


st.set_page_config(page_title="AA1 Name Checker", page_icon="search",
                   layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
    <style>
    div[data-testid="metric-container"] {
        background:#f0f4ff; border-radius:8px; padding:8px 16px;
    }
    .block-container { padding-top:2rem; }
    .db-info-box {
        background:#f8faff; border:1px solid #dbeafe; border-radius:8px;
        padding:10px 16px; font-size:13px; color:#374151; margin-bottom:8px;
    }
    .db-info-box b { color:#1a56db; }
    .adp-footer {
        text-align:center; padding:16px 0 6px 0;
        color:#6b7280; font-size:13px; letter-spacing:0.3px;
        border-top: 1px solid #e5e7eb; margin-top: 8px;
    }
    .adp-footer strong { color:#1a56db; }
    .adp-footer a { color:#1a56db; text-decoration:none; }
    .adp-footer a:hover { text-decoration:underline; }
    </style>
""", unsafe_allow_html=True)

st.title("AA1 Name Checker")
st.divider()

tab_checker, = st.tabs(["AA1 Name Comparison  (Old MNR vs New MNR)"])

_defaults = {"result": None, "excel_bytes": None, "ran": False}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


with tab_checker:

    # Fixed DB info banner -- both servers
    st.markdown(
        f'<div class="db-info-box">'
        f'<b>Database (Globe / MNR)</b> &nbsp;|&nbsp; '
        f'<b>Server 1</b> (EUR/CIS): <b>{_DB_HOST_1}</b> &nbsp;|&nbsp; '
        f'<b>Server 2</b> (APAC/Americas/Africa): <b>{_DB_HOST_2}</b> &nbsp;|&nbsp; '
        f'DB: <b>{_DB_NAME}</b> &nbsp;|&nbsp; User: <b>{_DB_USER}</b> &nbsp;|&nbsp; Port: <b>{_DB_PORT}</b>'
        f'</div>',
        unsafe_allow_html=True,
    )

    db_pass = st.text_input("Database Password", type="password",
                            placeholder="Enter mnr_ro password",
                            help="Password for the mnr_ro read-only user (same for both servers)")

    st.divider()

    # Step 1
    st.subheader("Step 1 - Select MNR Versions")
    st.caption(
        "Enter the version prefix only (e.g. _2026_06_004). "
        "The tool auto-discovers all country schemas on both servers "
        "and compares each pair."
    )

    c_old, c_new, c_country = st.columns([2, 2, 1])
    with c_old:
        schema_old = st.text_input("Old MNR Version", placeholder="_2026_06_004",
                                   help="Version prefix of the OLD MNR")
    with c_new:
        schema_new = st.text_input("New MNR Version", placeholder="_2026_06_005",
                                   help="Version prefix of the NEW MNR")
    with c_country:
        country_raw = st.text_input("Country Code (optional)", placeholder="e.g. ITA",
                                    help="Leave blank to run on ALL countries (Globe).")
        country_code = country_raw.strip().upper() or None

    st.divider()

    # Step 2
    st.subheader("Step 2 - Output Path")
    out_dir = st.text_input(
        "Output folder",
        value=os.path.join(os.path.dirname(os.path.abspath(__file__)), "Output"),
        help="Excel file saved as Matched_Data_YYYYMMDD.xlsx",
    )

    st.divider()

    # Step 3
    st.subheader("Step 3 - Run Analysis")

    missing_fields = []
    if not db_pass:    missing_fields.append("Database Password")
    if not schema_old: missing_fields.append("Old MNR Version")
    if not schema_new: missing_fields.append("New MNR Version")

    scope_label = f"Country: {country_code}" if country_code else "Scope: ALL countries (Globe) -- both servers"
    st.caption(scope_label)

    run_clicked = st.button(
        "Run Analysis", type="primary", disabled=bool(missing_fields),
        help=("Fill in: " + ", ".join(missing_fields)) if missing_fields else "",
    )

    if run_clicked:
        cfg1 = DBConfig(host=_DB_HOST_1, port=_DB_PORT, dbname=_DB_NAME,
                        user=_DB_USER, password=db_pass)
        cfg2 = DBConfig(host=_DB_HOST_2, port=_DB_PORT, dbname=_DB_NAME,
                        user=_DB_USER, password=db_pass)

        progress_bar = st.progress(0, text="Connecting to Globe databases...")
        status_box   = st.empty()

        def _progress(current, total, s_old, s_new):
            pct = int((current / max(total, 1)) * 90)
            progress_bar.progress(pct,
                text=f"Processing {current + 1}/{total}: {s_old} vs {s_new}")
            status_box.info(f"Comparing: {s_old}  vs  {s_new}")

        try:
            result = run_analysis(
                db_cfg=cfg1,
                schema_old=schema_old.strip(),
                schema_new=schema_new.strip(),
                country_code=country_code,
                progress_callback=_progress,
                db_cfg2=cfg2,
            )

            progress_bar.progress(95, text="Building Excel report...")
            status_box.info("Building Excel report...")
            excel_bytes = to_excel_bytes(result)

            try:
                os.makedirs(out_dir, exist_ok=True)
                fname = f"Matched_Data_{result.timestamp}.xlsx"
                fpath = os.path.join(out_dir, fname)
                with open(fpath, "wb") as fh:
                    fh.write(excel_bytes)
            except Exception:
                fpath = None

            progress_bar.progress(100, text="Done!")
            status_box.empty()

            st.session_state["result"]      = result
            st.session_state["excel_bytes"] = excel_bytes
            st.session_state["ran"]         = True

            total_features    = len(result.matched) + len(result.name_error) + len(result.missing_feature)
            n_schemas         = len(result.schemas_processed)
            n_missing_schemas = len(result.schemas_new_missing)
            st.success(
                f"Analysis complete!  "
                f"**{n_schemas} schema pairs processed**"
                + (f"  |  **{n_missing_schemas} schemas with no new version**" if n_missing_schemas else "")
                + f"  |  **{total_features:,} total AA1 features**  |  "
                f"Matched: {len(result.matched):,}  |  "
                f"Name errors: {len(result.name_error):,}  |  "
                f"Missing: {len(result.missing_feature):,}"
                + (f"  |  Saved: {fpath}" if fpath else "")
            )

            # Debug expander
            with st.expander("Schema discovery details", expanded=False):
                st.write(f"**Schemas with both old & new version ({n_schemas}):**")
                if result.schemas_processed:
                    st.dataframe(
                        pd.DataFrame(result.schemas_processed, columns=["Old Schema", "New Schema"]),
                        use_container_width=True, height=200,
                    )
                if n_missing_schemas:
                    st.write(f"**Old schemas where new version does NOT exist ({n_missing_schemas}) -- all features go to Missing_feature:**")
                    st.dataframe(
                        pd.DataFrame(result.schemas_new_missing, columns=["Old Schema (no new version)"]),
                        use_container_width=True, height=200,
                    )

            _post_slack(schema_old=schema_old, schema_new=schema_new,
                        country=country_code or "",
                        matched=len(result.matched),
                        errors=len(result.name_error),
                        missing=len(result.missing_feature))

        except Exception as exc:
            progress_bar.empty()
            status_box.empty()
            st.error(f"Analysis failed: {exc}")
            st.session_state["ran"] = False

    # Step 4 - Results
    if st.session_state["ran"] and st.session_state["result"] is not None:
        result = st.session_state["result"]

        st.divider()
        st.subheader("Step 4 - Results")

        total = len(result.matched) + len(result.name_error) + len(result.missing_feature)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total AA1 Features", f"{total:,}")
        m2.metric("Matched",            f"{len(result.matched):,}")
        m3.metric("Name Errors",        f"{len(result.name_error):,}")
        m4.metric("Missing in New",     f"{len(result.missing_feature):,}")

        fname = f"Matched_Data_{result.timestamp}.xlsx"
        st.download_button(
            label="Download Excel Report",
            data=st.session_state["excel_bytes"],
            file_name=fname,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )

        st.divider()

        tab_matched, tab_errors, tab_missing = st.tabs([
            f"All Matched AA1  ({len(result.matched):,})",
            f"Name Error  ({len(result.name_error):,})",
            f"Missing Feature  ({len(result.missing_feature):,})",
        ])

        def _show_table(df, key):
            search = st.text_input("Filter rows...", key=f"search_{key}",
                                   placeholder="Type country code, name, feat_id...")
            if search:
                mask = df.apply(
                    lambda col: col.astype(str).str.contains(search, case=False, na=False)
                ).any(axis=1)
                df = df[mask]
            st.dataframe(df, use_container_width=True, height=420)
            st.caption(f"{len(df):,} rows shown")

        with tab_matched:
            st.caption("Features where name is identical between old and new MNR.")
            _show_table(result.matched, "matched")

        with tab_errors:
            st.caption("Features present in both schemas but with a changed name.")
            if not result.name_error.empty:
                search_e = st.text_input("Filter rows...", key="search_errors",
                                         placeholder="Type country code, name, feat_id...")
                df_e = result.name_error
                if search_e:
                    mask = df_e.apply(
                        lambda col: col.astype(str).str.contains(search_e, case=False, na=False)
                    ).any(axis=1)
                    df_e = df_e[mask]
                st.dataframe(
                    df_e.style.applymap(lambda _: "background-color:#fef2f2",
                                        subset=["name_old", "name_new"]),
                    use_container_width=True, height=420,
                )
                st.caption(f"{len(df_e):,} rows shown")
            else:
                st.success("No name errors found - all names match!")

        with tab_missing:
            st.caption("Features in the old schema absent from the new schema.")
            _show_table(result.missing_feature, "missing")


st.markdown("""
    <div class="adp-footer">
        <strong>AA1 Name Checker</strong> &nbsp;|&nbsp;
        ADP Team &middot; TomTom &nbsp;|&nbsp;
        <a href="mailto:prabhakar.chaudhari@tomtom.com">prabhakar.chaudhari@tomtom.com</a>
    </div>
""", unsafe_allow_html=True)
