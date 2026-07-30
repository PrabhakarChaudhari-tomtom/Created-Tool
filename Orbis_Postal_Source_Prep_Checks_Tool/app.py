"""
Orbis Postal Area Source Preparation Checks — Streamlit UI
Check 1: Deleted Entity ID Validation
Check 2: Action Flag 'C' — Dummy UUID/Feature_Id Validation
Check 3: Action Flag Consistency Validation
Check 4: Duplicate Feature_Id Validation
Check 5: Vertex Spacing Validation
Check 6: Spike Angle Validation
Check 7: Self-Intersecting Polygon
Check 8: Layer Schema Validation
Check 9: Output Template Validation
Check 10: FID Not Match with VAD
Run:  streamlit run app.py
"""
import io
import os
import zipfile
from typing import Dict

import pandas as pd
import streamlit as st

from checks import (
    ACTION_FLAG_MEANINGS,
    DEFAULT_VERTEX_TOLERANCE_M,
    DUMMY_UUID_LENGTH,
    FEATURE_ID_CANDIDATES,
    ACTION_FLAG_CANDIDATES,
    SPIKE_ANGLE_DEFAULT_DEG,
    VAD_DIST_TOLERANCE_M,
    analyze_fid_not_match_with_vad,
    attach_source_polygon_geometry,
    build_point_gdf_from_xy,
    detect_column,
    find_duplicate_feature_ids,
    find_self_intersecting_polygons,
    is_multi_row_by_convention,
    list_layers,
    load_vad_boundaries,
    read_layer,
    run_action_flag_consistency_validation,
    run_deleted_entity_id_validation,
    validate_creation_dummy_uuid,
    validate_layer_schema,
    validate_output_template,
    validate_spike_angles,
    validate_vertex_spacing,
    write_action_flag_consistency_report,
    write_dummy_uuid_report,
    write_duplicate_feature_id_report,
    write_fid_not_match_with_vad_report,
    write_layer_schema_report,
    write_output_template_report,
    write_report,
    write_self_intersection_report,
    write_shapefile_into_zip,
    write_shapefile_to_path,
    write_shapefile_zip,
    write_spike_angle_report,
    write_vertex_spacing_report,
)

CHECK_1 = "Check 1 — Deleted Entity ID Validation"
CHECK_2 = "Check 2 — Action Flag 'C' Dummy UUID/Feature_Id Validation"
CHECK_3 = "Check 3 — Action Flag Consistency Validation"
CHECK_4 = "Check 4 — Duplicate Feature_Id Validation"
CHECK_5 = "Check 5 — Vertex Spacing Validation"
CHECK_6 = "Check 6 — Spike Angle Validation"
CHECK_7 = "Check 7 — Self-Intersecting Polygon"
CHECK_8 = "Check 8 — Layer Schema Validation"
CHECK_9 = "Check 9 — Output Template Validation"
CHECK_10 = "Check 10 — FID Not Match with VAD"

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Orbis Postal Source Prep QC",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    div[data-testid="metric-container"] {
        background:#f0f4ff; border-radius:8px; padding:8px 16px;
    }
    .block-container { padding-top:2rem; }
    .adp-footer {
        text-align:center; padding:14px 0 4px 0;
        color:#6b7280; font-size:13px; letter-spacing:0.4px;
    }
    .adp-footer strong { color:#1a56db; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown(
    '<h1 style="margin-bottom:0.2rem;">'
    '<span style="font-size:1.1em;">🧾</span>'
    ' <span style="color:#16a34a;">Orbis Postal Area Source Preparation Checks</span>'
    '</h1>',
    unsafe_allow_html=True,
)

_defaults = {
    "source_path": "",
    "layers_all": [],
    "layers_data": {},
    "feature_col_override": "",
    "action_col_override": "",
    "vad_path": "",
    "vad_layers_all": [],
    "vad_layers_data": {},
    "output_dir": "",
    "conflicts_df": None,
    "summary": None,
    "dummy_flagged_df": None,
    "dummy_summary": None,
    "flag_consistency_df": None,
    "flag_consistency_summary": None,
    "dup_flagged_df": None,
    "dup_summary": None,
    "dup_excluded_layers": [],
    "vertex_flagged_df": None,
    "vertex_summary": None,
    "vertex_tolerance_m": DEFAULT_VERTEX_TOLERANCE_M,
    "vad_dist_tol_m": VAD_DIST_TOLERANCE_M,
    "spike_flagged_df": None,
    "spike_summary": None,
    "spike_angle_deg": SPIKE_ANGLE_DEFAULT_DEG,
    "si_failed_df": None,
    "si_points_df": None,
    "si_summary": None,
    "schema_flagged_df": None,
    "schema_summary": None,
    "ot_flagged_df": None,
    "ot_summary": None,
    "fid_vad_excluded_flags": [],
    "fid_vad_flagged_df": None,
    "fid_vad_summary": None,
    "run_all_done": False,
    "run_all_errors": {},
    "selected_run_done": False,
    "selected_run_errors": {},
    "selected_run_labels": [],
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

active_check = st.radio(
    "Active check",
    options=[CHECK_1, CHECK_2, CHECK_3, CHECK_4, CHECK_5, CHECK_6, CHECK_7, CHECK_8, CHECK_9, CHECK_10],
    horizontal=True, label_visibility="collapsed",
)

if active_check == CHECK_1:
    st.caption(
        "A feature with Action_Flag = **D** (Deletion) must not share its **Feature_Id** with any "
        "feature carrying Action_Flag **U0 / U1 / U2** (Update). Checked across every layer, "
        "attribute table, and name table in the source."
    )
elif active_check == CHECK_2:
    st.caption(
        "Every Action_Flag = **C** (Creation / Genesis) feature — including Postal Area main "
        "postal point records — must carry a dummy UUID/Feature_Id in the Orbis format "
        f"(**{DUMMY_UUID_LENGTH} characters**, `00000000-0000-XXXX-0000-XXXXXXXXXXXX`). "
        "Reports records where it's missing, the wrong length, or the wrong format."
    )
elif active_check == CHECK_3:
    st.caption(
        "For each Feature_Id, the Action_Flag must be identical across every geometry layer, "
        "attribute table, and name table it appears in — a Feature_Id that's **U2** in the "
        "geometry layer must also be **U2** everywhere else it's referenced. Reports every "
        "Feature_Id (and its contributing rows) where the Action_Flag disagrees."
    )
elif active_check == CHECK_4:
    st.caption(
        "Each layer is scanned **independently** for Feature_Ids that appear more than once "
        "(e.g. within Postal_Point). Layers where repeats are expected by business rule "
        "(attribute tables, by default) can be excluded from flagging."
    )
elif active_check == CHECK_5:
    st.caption(
        "Adapted from `OrbisAreaVertex05m_Cleaner_V4_1.py`. Flags consecutive vertices of a "
        "polygon ring closer than a real-world-meters tolerance (default 0.5m). Pure "
        "validator — never modifies the source geometry. Optionally filters out findings "
        "that coincide with an existing VAD boundary (pre-existing/approved, not a new defect) "
        "— load the VAD input in Step ① to enable this."
    )
elif active_check == CHECK_6:
    st.caption(
        "Adapted from `spike_error_POSTAL 1.py`. Flags a vertex whose interior angle is "
        "sharper than a threshold (default 15°) — a spike/needle artifact. Unlike the "
        "original script, this is report-only: it never removes the spike from the geometry."
    )
elif active_check == CHECK_7:
    st.caption(
        "Adapted from `Self_Intersecting_Polygon.py`. Every polygon layer is scanned for "
        "features that are invalid specifically due to **self-intersection**, and the exact "
        "XY location of each self-intersection point is computed."
    )
elif active_check == CHECK_8:
    st.caption(
        "Adapted from `Orbis_AA_Check_LayerName_Field_Feat_Type.py`. Matches each layer "
        "against the known Orbis layer definitions (Postal_Area / Postal_Point / "
        "Postal_Attribute) — flags an unrecognized layer name, missing expected fields, a "
        "geometry-type mismatch, and unexpected Feature_Type values."
    )
elif active_check == CHECK_9:
    st.caption(
        "Adapted from `Py_Script_Orbis_PD_Output_Template_Check_V5.py` (the \"Output "
        "Template Check\"). A large rule set across Postal_Area / Postal_Point / "
        "Postal_Attribute / Postal_Name: field/geometry/Feature_Type conformance, "
        "null/blank scanning, Action_Flag value sets, ID length/duplicate rules, "
        "Feature_Type↔Attribute_Key rules, occurrence-count rules, and Postal_Name "
        "text-format rules. (Feature_Id/Action_Flag cross-layer consistency is already "
        "covered by Check 3 and isn't repeated here.)"
    )
else:
    st.caption(
        "Ported from the standalone `orbis_postal_checks` tool (business title: \"Delete "
        "polygon entity ID should not be present in update layer & that should be unique.\"). "
        "Requires the **VAD** input from Step ① (previous accepted revision). Every "
        "non-Creation (Action_Flag != C) source record must already have its Feature_Id in "
        "the VAD, and it must be unique within the source."
    )
st.divider()


def _browse_file(key: str) -> None:
    """
    on_click callback for a "Browse file" button. Callbacks run BEFORE the
    script reruns/re-instantiates widgets, so writing to
    st.session_state[key] here is safe — doing the same write from inside
    a normal `if st.button(...):` block is NOT safe, because that code runs
    AFTER the same-keyed widget has already been instantiated earlier in
    that same script pass, and Streamlit raises (silently caught, then
    wiped by the immediate rerun) rather than letting the box update.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", 1)
        path = filedialog.askopenfilename(
            title="Select source GeoPackage / File Geodatabase",
            filetypes=[("GeoPackage", "*.gpkg"), ("All files", "*.*")],
        )
        root.destroy()
        if path:
            st.session_state[key] = os.path.normpath(path)
    except Exception as e:
        st.session_state[f"_{key}_browse_error"] = str(e)


def _browse_folder(key: str) -> None:
    """on_click callback for a "Browse .gdb" button — see _browse_file for why this must be a callback."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", 1)
        path = filedialog.askdirectory(title="Select .gdb folder")
        root.destroy()
        if path:
            st.session_state[key] = os.path.normpath(path)
    except Exception as e:
        st.session_state[f"_{key}_browse_error"] = str(e)


def _show_browse_error(key: str) -> None:
    """Render (and clear) any browse error stashed by _browse_file/_browse_folder for this widget key."""
    err_key = f"_{key}_browse_error"
    if st.session_state.get(err_key):
        st.warning(f"File/folder browser unavailable: {st.session_state[err_key]}. Please type the path manually.")
        st.session_state[err_key] = ""


def _output_dir() -> str:
    """Preferred save directory: the global output path if set, else next to the source file."""
    return st.session_state.output_dir or os.path.dirname(st.session_state.source_path or ".")


def _clean_path(raw: str) -> str:
    """
    Normalize a user-typed/pasted path: strips whitespace and surrounding
    quotes — Windows "Copy as path" wraps paths in double quotes, which
    otherwise makes os.path.exists() silently fail and leaves the "Load"
    button stuck disabled with no visible error.
    """
    return (raw or "").strip().strip('"').strip("'").strip()


def _render_shapefile_export(gdf, default_base_name: str, key_prefix: str) -> None:
    """Download (.zip of .shp/.shx/.dbf/.prj) + save-to-path controls for a GeoDataFrame."""
    is_empty = gdf.empty
    zip_bytes = write_shapefile_zip(gdf, default_base_name) if not is_empty else b""
    st.download_button(
        "⬇ Download shapefile (.zip)", data=zip_bytes, file_name=f"{default_base_name}.zip",
        mime="application/zip", disabled=is_empty, key=f"{key_prefix}_download_shp",
    )
    shp_save_path = st.text_input(
        "…or save shapefile directly to a path on this machine (.shp — sibling files created automatically)",
        value=str(os.path.join(_output_dir(), f"{default_base_name}.shp")),
        key=f"{key_prefix}_save_shp_path",
    )
    if st.button("💾  Save shapefile to path", key=f"{key_prefix}_save_shp_btn", disabled=is_empty):
        try:
            write_shapefile_to_path(gdf, shp_save_path)
            st.success(f"✅ Saved to `{shp_save_path}`")
        except Exception as exc:
            st.error(f"**Save failed:** {exc}")


# ── Run-check helpers (shared by the per-check "Run" button and "Run ALL") ─────
def _run_check1():
    conflicts_df, summary = run_deleted_entity_id_validation(
        layers=st.session_state.layers_data,
        feature_id_override=st.session_state.feature_col_override.strip() or None,
        action_flag_override=st.session_state.action_col_override.strip() or None,
    )
    st.session_state.conflicts_df = conflicts_df
    st.session_state.summary = summary


def _run_check2():
    dummy_flagged_df, dummy_summary = validate_creation_dummy_uuid(
        layers=st.session_state.layers_data,
        feature_id_override=st.session_state.feature_col_override.strip() or None,
        action_flag_override=st.session_state.action_col_override.strip() or None,
    )
    st.session_state.dummy_flagged_df = dummy_flagged_df
    st.session_state.dummy_summary = dummy_summary


def _run_check3():
    flag_consistency_df, flag_consistency_summary = run_action_flag_consistency_validation(
        layers=st.session_state.layers_data,
        feature_id_override=st.session_state.feature_col_override.strip() or None,
        action_flag_override=st.session_state.action_col_override.strip() or None,
    )
    st.session_state.flag_consistency_df = flag_consistency_df
    st.session_state.flag_consistency_summary = flag_consistency_summary


def _run_check4():
    dup_flagged_df, dup_summary = find_duplicate_feature_ids(
        layers=st.session_state.layers_data,
        feature_id_override=st.session_state.feature_col_override.strip() or None,
        excluded_layers=st.session_state.dup_excluded_layers,
    )
    st.session_state.dup_flagged_df = dup_flagged_df
    st.session_state.dup_summary = dup_summary


def _run_check5():
    vad_boundaries = None
    if st.session_state.vad_layers_data:
        vad_boundaries = load_vad_boundaries(st.session_state.vad_layers_data)
    vertex_flagged_df, vertex_summary = validate_vertex_spacing(
        layers=st.session_state.layers_data,
        tolerance_m=st.session_state.vertex_tolerance_m,
        vad_boundaries=vad_boundaries,
        vad_dist_tol_m=st.session_state.vad_dist_tol_m,
    )
    st.session_state.vertex_flagged_df = vertex_flagged_df
    st.session_state.vertex_summary = vertex_summary


def _run_check6():
    spike_flagged_df, spike_summary = validate_spike_angles(
        layers=st.session_state.layers_data,
        angle_deg=st.session_state.spike_angle_deg,
    )
    st.session_state.spike_flagged_df = spike_flagged_df
    st.session_state.spike_summary = spike_summary


def _run_check7():
    si_failed_df, si_points_df, si_summary = find_self_intersecting_polygons(
        layers=st.session_state.layers_data,
    )
    st.session_state.si_failed_df = si_failed_df
    st.session_state.si_points_df = si_points_df
    st.session_state.si_summary = si_summary


def _run_check8():
    schema_flagged_df, schema_summary = validate_layer_schema(
        layers=st.session_state.layers_data,
        source_path=st.session_state.source_path,
    )
    st.session_state.schema_flagged_df = schema_flagged_df
    st.session_state.schema_summary = schema_summary


def _run_check9():
    ot_flagged_df, ot_summary = validate_output_template(
        layers=st.session_state.layers_data,
        source_path=st.session_state.source_path,
    )
    st.session_state.ot_flagged_df = ot_flagged_df
    st.session_state.ot_summary = ot_summary


def _run_check10():
    if not st.session_state.vad_layers_data:
        raise ValueError("VAD layer data not loaded — load the VAD input in Step ① first.")
    fid_vad_flagged_df, fid_vad_summary = analyze_fid_not_match_with_vad(
        source_layers=st.session_state.layers_data,
        vad_layers=st.session_state.vad_layers_data,
        excluded_action_flags=st.session_state.fid_vad_excluded_flags or ("C",),
        feature_id_override=st.session_state.feature_col_override.strip() or None,
        action_flag_override=st.session_state.action_col_override.strip() or None,
    )
    st.session_state.fid_vad_flagged_df = fid_vad_flagged_df
    st.session_state.fid_vad_summary = fid_vad_summary


# Registry describing every check: used to drive "Run ALL Checks" and the combined report.
CHECK_REGISTRY = [
    {"label": CHECK_1, "runner": _run_check1, "df_state": "conflicts_df",
     "sheet_name": "Deleted_vs_Updated_ID", "default_name": "Deleted_Entity_ID_Validation.xlsx"},
    {"label": CHECK_2, "runner": _run_check2, "df_state": "dummy_flagged_df",
     "sheet_name": "Creation_Dummy_UUID_Check", "default_name": "Creation_Dummy_UUID_Validation.xlsx"},
    {"label": CHECK_3, "runner": _run_check3, "df_state": "flag_consistency_df",
     "sheet_name": "Action_Flag_Consistency", "default_name": "Action_Flag_Consistency_Validation.xlsx"},
    {"label": CHECK_4, "runner": _run_check4, "df_state": "dup_flagged_df",
     "sheet_name": "Duplicate_Feature_Id", "default_name": "Duplicate_Feature_Id_Validation.xlsx"},
    {"label": CHECK_5, "runner": _run_check5, "df_state": "vertex_flagged_df",
     "sheet_name": "Vertex_Spacing", "default_name": "Vertex_Spacing_Validation.xlsx",
     "shapefiles": [
         {"caption": "Point at each flagged vertex", "base_name": "Vertex_Spacing_Points",
          "builder": lambda: build_point_gdf_from_xy(st.session_state.vertex_flagged_df, "x", "y")},
     ]},
    {"label": CHECK_6, "runner": _run_check6, "df_state": "spike_flagged_df",
     "sheet_name": "Spike_Angle", "default_name": "Spike_Angle_Validation.xlsx",
     "shapefiles": [
         {"caption": "Point at each flagged spike vertex", "base_name": "Spike_Angle_Points",
          "builder": lambda: build_point_gdf_from_xy(st.session_state.spike_flagged_df, "x", "y")},
     ]},
    {"label": CHECK_7, "runner": _run_check7, "df_state": "si_failed_df",
     "sheet_name": "Failed_Polygons", "extra_df_state": "si_points_df",
     "extra_sheet_name": "Intersection_Points", "default_name": "Self_Intersecting_Polygon_Validation.xlsx",
     "shapefiles": [
         {"caption": "Failed polygons (original geometry)", "base_name": "Self_Intersecting_Polygons",
          "builder": lambda: attach_source_polygon_geometry(
              st.session_state.si_failed_df, st.session_state.layers_data)},
         {"caption": "Self-intersection points", "base_name": "Self_Intersection_Points",
          "builder": lambda: build_point_gdf_from_xy(st.session_state.si_points_df, "x_coord", "y_coord")},
     ]},
    {"label": CHECK_8, "runner": _run_check8, "df_state": "schema_flagged_df",
     "sheet_name": "Layer_Schema", "default_name": "Layer_Schema_Validation.xlsx"},
    {"label": CHECK_9, "runner": _run_check9, "df_state": "ot_flagged_df",
     "sheet_name": "Output_Template_Check", "default_name": "Output_Template_Validation.xlsx"},
    {"label": CHECK_10, "runner": _run_check10, "df_state": "fid_vad_flagged_df",
     "sheet_name": "FID_Not_Match_with_VAD", "default_name": "FID_Not_Match_with_VAD.xlsx"},
]


def _write_combined_report(path_or_buf, entries=CHECK_REGISTRY) -> None:
    with pd.ExcelWriter(path_or_buf, engine="openpyxl") as writer:
        for entry in entries:
            df = st.session_state.get(entry["df_state"])
            if df is None:
                continue
            df.to_excel(writer, sheet_name=entry["sheet_name"][:31], index=False)
            extra_key = entry.get("extra_df_state")
            if extra_key and st.session_state.get(extra_key) is not None:
                st.session_state[extra_key].to_excel(
                    writer, sheet_name=entry["extra_sheet_name"][:31], index=False
                )


def _run_checks(entries) -> Dict[str, str]:
    """Run the given CHECK_REGISTRY entries, returning {label: error_str} for any that failed."""
    errors = {}
    for entry in entries:
        try:
            entry["runner"]()
        except Exception as exc:
            errors[entry["label"]] = str(exc)
    return errors


def _render_check_results(entries, errors: Dict[str, str], key_prefix: str, default_name: str) -> None:
    """Renders the pass/fail summary table + combined report download/save controls for `entries`."""
    ok_count = sum(1 for e in entries if e["label"] not in errors)
    st.success(f"✅ Ran {ok_count}/{len(entries)} checks successfully.")

    summary_rows = []
    for entry in entries:
        if entry["label"] in errors:
            summary_rows.append({
                "Check": entry["label"], "Status": "⚠ Skipped/Failed",
                "Flagged rows": "—", "Note": errors[entry["label"]],
            })
        else:
            df = st.session_state.get(entry["df_state"])
            summary_rows.append({
                "Check": entry["label"], "Status": "✅ Done",
                "Flagged rows": len(df) if df is not None else 0, "Note": "",
            })
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

    shapefile_items = [
        (entry, shp) for entry in entries if entry["label"] not in errors
        for shp in entry.get("shapefiles", [])
        if not shp["builder"]().empty
    ]

    st.markdown("##### Output — one Excel report + a shapefile per geometry check")
    if shapefile_items:
        names = ", ".join(f"{shp['base_name']}.shp" for _e, shp in shapefile_items)
        st.caption(f"Excel: **{default_name}**  |  Shapefiles: **{names}**")
    else:
        st.caption(f"Excel: **{default_name}**")

    c1, c2 = st.columns(2)
    if c1.button("💾  Save ALL outputs to Output folder", key=f"{key_prefix}_save_all_btn", type="primary"):
        try:
            out_dir = _output_dir()
            excel_path = os.path.join(out_dir, default_name)
            _write_combined_report(excel_path, entries)
            saved = [excel_path]
            for entry, shp in shapefile_items:
                shp_path = os.path.join(out_dir, f"{shp['base_name']}.shp")
                write_shapefile_to_path(shp["builder"](), shp_path)
                saved.append(shp_path)
            st.success("✅ Saved:\n" + "\n".join(f"- `{p}`" for p in saved))
        except Exception as exc:
            st.error(f"**Save failed:** {exc}")

    # Built once (right after the run, in the button handler that called us) — never rebuilt on
    # every unrelated rerun, since writing real shapefiles for thousands of points is not free.
    zip_bytes = st.session_state.get(f"{key_prefix}_zip_bytes", b"")
    c2.download_button(
        "⬇ Download everything (.zip)", data=zip_bytes,
        file_name=os.path.splitext(default_name)[0] + "_AllOutputs.zip",
        mime="application/zip", key=f"{key_prefix}_download_all_btn", disabled=not zip_bytes,
    )


def _build_everything_zip_bytes(entries, errors: Dict[str, str], default_name: str) -> bytes:
    """Combined Excel + every non-empty shapefile for `entries`, bundled into one zip."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        excel_bytes = io.BytesIO()
        _write_combined_report(excel_bytes, entries)
        zf.writestr(default_name, excel_bytes.getvalue())
        for entry in entries:
            if entry["label"] in errors:
                continue
            for shp in entry.get("shapefiles", []):
                gdf = shp["builder"]()
                if gdf.empty:
                    continue
                write_shapefile_into_zip(zf, gdf, shp["base_name"])
    return buf.getvalue()


# ── Step 1: Input ─────────────────────────────────────────────────────────────
st.subheader("① Input")

st.markdown("##### Source delivery (GeoPackage or File Geodatabase) — required")
if "source_path_input" not in st.session_state:
    st.session_state.source_path_input = st.session_state.source_path
c_path, c_b1, c_b2 = st.columns([4, 1, 1])
src_path = c_path.text_input(
    "Source path",
    placeholder=r"C:\data\ORPA_..._Attr_V1.gpkg   |   C:\data\Delivery.gdb",
    label_visibility="collapsed", key="source_path_input",
)
c_b1.button(
    "📁 Browse file", use_container_width=True, key="browse_source_file_btn",
    on_click=_browse_file, args=("source_path_input",),
)
c_b2.button(
    "📂 Browse .gdb", use_container_width=True, key="browse_source_gdb_btn",
    on_click=_browse_folder, args=("source_path_input",),
)
_show_browse_error("source_path_input")
st.session_state.source_path = _clean_path(src_path)

src_valid = bool(st.session_state.source_path and os.path.exists(st.session_state.source_path))
if st.session_state.source_path and not src_valid:
    st.warning("⚠ Source path not found.")

if st.button("📂  Load layers", type="primary", disabled=not src_valid):
    with st.spinner("Listing layers …"):
        try:
            st.session_state.layers_all = list_layers(st.session_state.source_path)
            st.session_state.conflicts_df = None
            st.session_state.summary = None
            st.session_state.dummy_flagged_df = None
            st.session_state.dummy_summary = None
            st.session_state.flag_consistency_df = None
            st.session_state.flag_consistency_summary = None
            st.session_state.dup_flagged_df = None
            st.session_state.dup_summary = None
            st.session_state.vertex_flagged_df = None
            st.session_state.vertex_summary = None
            st.session_state.spike_flagged_df = None
            st.session_state.spike_summary = None
            st.session_state.si_failed_df = None
            st.session_state.si_points_df = None
            st.session_state.si_summary = None
            st.session_state.schema_flagged_df = None
            st.session_state.schema_summary = None
            st.session_state.ot_flagged_df = None
            st.session_state.ot_summary = None
            st.session_state.fid_vad_flagged_df = None
            st.session_state.fid_vad_summary = None
            st.session_state.run_all_done = False
            st.session_state.run_all_errors = {}
            st.session_state.selected_run_done = False
            st.session_state.selected_run_errors = {}
            st.session_state.selected_run_labels = []
            st.success(f"Loaded — **{len(st.session_state.layers_all)}** layer(s) found.")
        except Exception as exc:
            st.error(f"**Error reading layers:** {exc}")

st.markdown(
    "##### VAD (previous accepted revision, GeoPackage or File Geodatabase) — "
    "required for Check 10, optional for Check 5"
)
if "vad_path_input" not in st.session_state:
    st.session_state.vad_path_input = st.session_state.vad_path
v_path, v_b1, v_b2 = st.columns([4, 1, 1])
vad_path_val = v_path.text_input(
    "VAD path",
    placeholder=r"C:\data\<CC>_postal_layer_<LayerId>_revision_<RevisionId>.gpkg   |   C:\data\VAD.gdb",
    label_visibility="collapsed", key="vad_path_input",
)
v_b1.button(
    "📁 Browse file", use_container_width=True, key="browse_vad_file_btn",
    on_click=_browse_file, args=("vad_path_input",),
)
v_b2.button(
    "📂 Browse .gdb", use_container_width=True, key="browse_vad_gdb_btn",
    on_click=_browse_folder, args=("vad_path_input",),
)
_show_browse_error("vad_path_input")
st.session_state.vad_path = _clean_path(vad_path_val)

vad_valid = bool(st.session_state.vad_path and os.path.exists(st.session_state.vad_path))
if st.session_state.vad_path and not vad_valid:
    st.warning("⚠ VAD path not found.")

if st.button("📂  Load VAD layers", disabled=not vad_valid, key="load_vad_btn"):
    with st.spinner("Listing VAD layers …"):
        try:
            st.session_state.vad_layers_all = list_layers(st.session_state.vad_path)
            st.session_state.vad_layers_data = {}
            st.success(f"Loaded — **{len(st.session_state.vad_layers_all)}** VAD layer(s) found.")
        except Exception as exc:
            st.error(f"**Error reading VAD layers:** {exc}")

if st.session_state.vad_layers_all:
    vad_sel = st.multiselect(
        "VAD layers to read (used for Check 5's boundary filter and Check 10's Feature_Id pool)",
        options=st.session_state.vad_layers_all,
        default=st.session_state.vad_layers_all,
        key="vad_layers_select",
    )
    if vad_sel and st.button("🔍 Load VAD layer data", key="load_vad_data_btn"):
        with st.spinner("Reading VAD layers …"):
            try:
                st.session_state.vad_layers_data = {
                    l: read_layer(st.session_state.vad_path, l) for l in vad_sel
                }
            except Exception as exc:
                st.error(f"**Error reading VAD layer data:** {exc}")

st.markdown("##### Output folder — where saved reports go by default")
if "output_dir_input" not in st.session_state:
    st.session_state.output_dir_input = st.session_state.output_dir
o_path, o_b1 = st.columns([5, 1])
output_dir_val = o_path.text_input(
    "Output folder",
    placeholder=r"C:\data\reports  (blank = save next to the source file)",
    label_visibility="collapsed", key="output_dir_input",
)
o_b1.button(
    "📂 Browse", use_container_width=True, key="browse_output_btn",
    on_click=_browse_folder, args=("output_dir_input",),
)
_show_browse_error("output_dir_input")
st.session_state.output_dir = _clean_path(output_dir_val)
if st.session_state.output_dir and not os.path.isdir(st.session_state.output_dir):
    st.warning("⚠ Output folder not found.")

st.divider()
st.subheader("⚡ Run ALL 10 checks — single click")
st.caption(
    "Loads every layer from the Source (and the VAD, if a path is given above) automatically, "
    "then runs all 10 checks with default settings and gives you one combined report. No need "
    "to step through Layers & column mapping first."
)
def _auto_load_source_and_vad() -> None:
    """Loads every source layer (and VAD layer, if valid) without the manual Step ② flow."""
    st.session_state.layers_all = list_layers(st.session_state.source_path)
    st.session_state.layers_data = {
        l: read_layer(st.session_state.source_path, l) for l in st.session_state.layers_all
    }
    st.session_state.dup_excluded_layers = [
        l for l in st.session_state.layers_all if is_multi_row_by_convention(l)
    ]
    if vad_valid:
        st.session_state.vad_layers_all = list_layers(st.session_state.vad_path)
        st.session_state.vad_layers_data = {
            l: read_layer(st.session_state.vad_path, l) for l in st.session_state.vad_layers_all
        }


if st.button("🚀  RUN ALL CHECKS NOW", type="primary", disabled=not src_valid, key="one_click_run_all_btn"):
    with st.spinner("Loading layers and running all 10 checks — this may take a while on large polygon layers …"):
        try:
            _auto_load_source_and_vad()
            st.session_state.run_all_errors = _run_checks(CHECK_REGISTRY)
            st.session_state.run_all_done = True
            st.session_state.quick_zip_bytes = _build_everything_zip_bytes(
                CHECK_REGISTRY, st.session_state.run_all_errors, "All_Checks_Report.xlsx"
            )
        except Exception as exc:
            st.error(f"**Failed to load layers and run checks:** {exc}")

if st.session_state.run_all_done:
    _render_check_results(CHECK_REGISTRY, st.session_state.run_all_errors, "quick", "All_Checks_Report.xlsx")

st.divider()
st.subheader("🎯 Run a custom selection of checks — single click")
st.caption(
    "Pick any combination of checks (e.g. Check 3 & 4, or Checks 1 through 5) and run just "
    "those right away — loads every layer from the Source (and VAD, if given) automatically, "
    "same as above, but only runs the checks you pick."
)
quick_selected_labels = st.multiselect(
    "Checks to run", options=[e["label"] for e in CHECK_REGISTRY], key="quick_selected_checks_multiselect",
)
if st.button(
    "🚀  RUN SELECTED CHECKS NOW", type="primary",
    disabled=not (src_valid and quick_selected_labels), key="one_click_run_selected_btn",
):
    quick_selected_entries = [e for e in CHECK_REGISTRY if e["label"] in quick_selected_labels]
    with st.spinner(f"Loading layers and running {len(quick_selected_entries)} selected check(s) …"):
        try:
            _auto_load_source_and_vad()
            st.session_state.selected_run_errors = _run_checks(quick_selected_entries)
            st.session_state.selected_run_labels = quick_selected_labels
            st.session_state.selected_run_done = True
            st.session_state.quick_selected_zip_bytes = _build_everything_zip_bytes(
                quick_selected_entries, st.session_state.selected_run_errors, "Selected_Checks_Report.xlsx"
            )
        except Exception as exc:
            st.error(f"**Failed to load layers and run checks:** {exc}")

if st.session_state.selected_run_done:
    quick_selected_entries = [
        e for e in CHECK_REGISTRY if e["label"] in st.session_state.selected_run_labels
    ]
    _render_check_results(
        quick_selected_entries, st.session_state.selected_run_errors, "quick_selected", "Selected_Checks_Report.xlsx"
    )

# ── Step 2: Layer & column mapping ─────────────────────────────────────────────
if st.session_state.layers_all:
    st.divider()
    st.subheader("② Layers & column mapping")

    sel_layers = st.multiselect(
        "Layers to include (all polygon layers, attribute tables, name tables, "
        "and main postal point records)",
        options=st.session_state.layers_all,
        default=st.session_state.layers_all,
    )

    if sel_layers and st.button("🔍 Inspect columns"):
        with st.spinner("Reading selected layers …"):
            try:
                st.session_state.layers_data = {
                    l: read_layer(st.session_state.source_path, l) for l in sel_layers
                }
            except Exception as exc:
                st.error(f"**Error reading selected layers:** {exc}")

    if st.session_state.layers_data:
        needs_feature_columns = active_check in (CHECK_1, CHECK_2, CHECK_3, CHECK_4, CHECK_10)
        needs_geometry_only = active_check in (CHECK_5, CHECK_6, CHECK_7, CHECK_8, CHECK_9)

        if needs_feature_columns:
            rows = []
            for lname, gdf in st.session_state.layers_data.items():
                try:
                    cols = pd.DataFrame(gdf.drop(columns=[gdf.geometry.name], errors="ignore")).columns
                except Exception:
                    cols = pd.DataFrame(gdf).columns
                rows.append({
                    "layer": lname,
                    "features": len(gdf),
                    "auto-detected Feature_Id column": detect_column(cols, FEATURE_ID_CANDIDATES) or "⚠ not found",
                    "auto-detected Action_Flag column": detect_column(cols, ACTION_FLAG_CANDIDATES) or "(none)",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            c1, c2 = st.columns(2)
            st.session_state.feature_col_override = c1.text_input(
                "Override Feature_Id column (all layers)",
                value=st.session_state.feature_col_override,
                placeholder=f"blank = auto-detect ({', '.join(FEATURE_ID_CANDIDATES)})",
            )
            st.session_state.action_col_override = c2.text_input(
                "Override Action_Flag column (all layers)",
                value=st.session_state.action_col_override,
                placeholder=f"blank = auto-detect ({', '.join(ACTION_FLAG_CANDIDATES)})",
            )

            if active_check == CHECK_4:
                layer_names = list(st.session_state.layers_data.keys())
                auto_default = [l for l in layer_names if is_multi_row_by_convention(l)]
                st.session_state.dup_excluded_layers = st.multiselect(
                    "Layers where a repeated Feature_Id is expected by business rule "
                    "(excluded from flagging — duplicate count is still reported)",
                    options=layer_names,
                    default=[l for l in auto_default if l in layer_names] or None,
                    help="Defaults to layers whose name contains \"attribute\" — "
                         "attribute tables legitimately carry one row per key/value pair.",
                )

            if active_check == CHECK_10:
                if not st.session_state.vad_layers_data:
                    st.caption(
                        "⚠ Load the VAD input in Step ① (Load VAD layers → select layers → "
                        "Load VAD layer data) before running this check."
                    )
                all_flag_values = set()
                for gdf in st.session_state.layers_data.values():
                    action_col = detect_column(gdf.columns, ACTION_FLAG_CANDIDATES)
                    if action_col:
                        all_flag_values.update(
                            gdf[action_col].dropna().astype(str).str.strip().str.upper().unique().tolist()
                        )
                if all_flag_values:
                    flag_options = sorted(all_flag_values)
                    st.session_state.fid_vad_excluded_flags = st.multiselect(
                        "Action_Flag values to EXCLUDE from the check (records not expected in VAD yet)",
                        options=flag_options,
                        default=[f for f in flag_options if f == "C"],
                        format_func=lambda f: f"{f} — {ACTION_FLAG_MEANINGS.get(f, 'Unknown')}",
                    )

            with st.expander("Action_Flag meanings"):
                st.table(pd.DataFrame(
                    [{"flag": k, "meaning": v} for k, v in ACTION_FLAG_MEANINGS.items()]
                ))

        elif needs_geometry_only:
            st.caption(f"Layers loaded: {', '.join(st.session_state.layers_data.keys())}")

            if active_check == CHECK_5:
                st.session_state.vertex_tolerance_m = st.number_input(
                    "Vertex spacing tolerance (meters)",
                    min_value=0.01, value=float(st.session_state.vertex_tolerance_m), step=0.05,
                    help="Flags consecutive vertices closer than this real-world distance "
                         "(and further than a 1cm noise floor).",
                )
                if st.session_state.vad_layers_data:
                    st.session_state.vad_dist_tol_m = st.number_input(
                        "VAD match tolerance (meters)",
                        min_value=0.01, value=float(st.session_state.vad_dist_tol_m), step=0.05,
                        help="Findings within this distance of a VAD boundary are treated as "
                             "pre-existing/approved and filtered out.",
                    )
                else:
                    st.caption(
                        "ℹ Load the VAD input in Step ① to filter out pre-existing/approved "
                        "false positives (optional)."
                    )

            elif active_check == CHECK_6:
                st.session_state.spike_angle_deg = st.number_input(
                    "Spike angle threshold (degrees)",
                    min_value=0.1, value=float(st.session_state.spike_angle_deg), step=1.0,
                    help="Flags a vertex whose interior angle is sharper than this.",
                )

        # ── Step 3: Run check ──────────────────────────────────────────────
        st.divider()
        st.subheader("③ Run check")

        if active_check == CHECK_1:
            if st.button("▶  Run Deleted Entity ID Validation", type="primary"):
                with st.spinner("Checking …"):
                    try:
                        _run_check1()
                    except Exception as exc:
                        st.error(f"**Check failed:** {exc}")
        elif active_check == CHECK_2:
            if st.button("▶  Run Dummy UUID/Feature_Id Validation", type="primary"):
                with st.spinner("Checking …"):
                    try:
                        _run_check2()
                    except Exception as exc:
                        st.error(f"**Check failed:** {exc}")
        elif active_check == CHECK_3:
            if st.button("▶  Run Action Flag Consistency Validation", type="primary"):
                with st.spinner("Checking …"):
                    try:
                        _run_check3()
                    except Exception as exc:
                        st.error(f"**Check failed:** {exc}")
        elif active_check == CHECK_4:
            if st.button("▶  Run Duplicate Feature_Id Validation", type="primary"):
                with st.spinner("Checking …"):
                    try:
                        _run_check4()
                    except Exception as exc:
                        st.error(f"**Check failed:** {exc}")
        elif active_check == CHECK_5:
            if st.button("▶  Run Vertex Spacing Validation", type="primary"):
                with st.spinner("Checking … (may take a while on large polygon layers)"):
                    try:
                        _run_check5()
                    except Exception as exc:
                        st.error(f"**Check failed:** {exc}")
        elif active_check == CHECK_6:
            if st.button("▶  Run Spike Angle Validation", type="primary"):
                with st.spinner("Checking …"):
                    try:
                        _run_check6()
                    except Exception as exc:
                        st.error(f"**Check failed:** {exc}")
        elif active_check == CHECK_7:
            if st.button("▶  Run Self-Intersecting Polygon Check", type="primary"):
                with st.spinner("Checking …"):
                    try:
                        _run_check7()
                    except Exception as exc:
                        st.error(f"**Check failed:** {exc}")
        elif active_check == CHECK_8:
            if st.button("▶  Run Layer Schema Validation", type="primary"):
                with st.spinner("Checking …"):
                    try:
                        _run_check8()
                    except Exception as exc:
                        st.error(f"**Check failed:** {exc}")
        elif active_check == CHECK_9:
            if st.button("▶  Run Output Template Validation", type="primary"):
                with st.spinner("Checking …"):
                    try:
                        _run_check9()
                    except Exception as exc:
                        st.error(f"**Check failed:** {exc}")
        else:
            vad_ready = bool(st.session_state.vad_layers_data)
            if not vad_ready:
                st.caption("⚠ Load VAD layer data in Step ① before running this check.")
            if st.button("▶  Run FID Not Match with VAD", type="primary", disabled=not vad_ready):
                with st.spinner("Checking …"):
                    try:
                        _run_check10()
                    except Exception as exc:
                        st.error(f"**Check failed:** {exc}")

    # ── Step 4: Results ──────────────────────────────────────────────────────
    if active_check == CHECK_1 and st.session_state.summary is not None:
        summary = st.session_state.summary
        conflicts_df = st.session_state.conflicts_df

        m1, m2, m3 = st.columns(3)
        m1.metric("Rows indexed", summary["total_rows_indexed"])
        m2.metric("Distinct Feature_Ids", summary["distinct_feature_ids"])
        m3.metric("Deleted↔Updated conflicts",
                  summary["deleted_vs_updated_conflicts"]["conflicting_feature_ids"])

        if summary["layers_skipped_no_feature_id_column"]:
            st.warning(
                "⚠ Skipped layer(s) with no detectable Feature_Id column: "
                + ", ".join(summary["layers_skipped_no_feature_id_column"])
            )

        with st.expander("Per-layer breakdown"):
            st.json(summary["per_layer"])

        st.markdown("#### Deleted vs Updated Feature_Id conflicts")
        st.caption(
            "Same Feature_Id appears with Action_Flag = D in one feature and "
            "U0 / U1 / U2 in another."
        )
        st.dataframe(conflicts_df, use_container_width=True, height=260)

        st.divider()
        st.subheader("④ Save report")

        default_name = "Deleted_Entity_ID_Validation.xlsx"
        out_name = st.text_input("Output filename", value=default_name, key="out_name_check1")

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            conflicts_df.to_excel(writer, sheet_name="Deleted_vs_Updated_ID", index=False)
        st.download_button(
            "⬇ Download report", data=buf.getvalue(), file_name=out_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_check1",
        )

        save_path = st.text_input(
            "…or save directly to a path on this machine",
            value=str(os.path.join(_output_dir(), out_name)),
            key="save_path_check1",
        )
        if st.button("💾  Save to path", key="save_btn_check1"):
            try:
                write_report(conflicts_df, save_path)
                st.success(f"✅ Saved to `{save_path}`")
            except Exception as exc:
                st.error(f"**Save failed:** {exc}")

    if active_check == CHECK_2 and st.session_state.dummy_summary is not None:
        summary = st.session_state.dummy_summary
        flagged_df = st.session_state.dummy_flagged_df

        m1, m2, m3 = st.columns(3)
        m1.metric("Layers scanned", len(summary["layers_scanned"]))
        m2.metric("Creation (C) rows checked", summary["total_creation_rows_checked"])
        m3.metric("Flagged", summary["total_flagged"])

        if summary["layers_skipped_missing_columns"]:
            st.warning(
                "⚠ Skipped layer(s) with no detectable Feature_Id and/or Action_Flag column: "
                + ", ".join(summary["layers_skipped_missing_columns"])
            )

        with st.expander("Per-layer breakdown"):
            st.json({
                "per_layer": summary["per_layer"],
                "creation_rows_per_layer": summary["creation_rows_per_layer"],
            })

        st.markdown("#### Flagged Action_Flag = C records")
        st.caption(
            "Dummy UUID/Feature_Id is missing, not exactly "
            f"{DUMMY_UUID_LENGTH} characters, and/or doesn't match the Orbis dummy UUID format."
        )
        st.dataframe(flagged_df, use_container_width=True, height=320)

        st.divider()
        st.subheader("④ Save report")

        default_name = "Creation_Dummy_UUID_Validation.xlsx"
        out_name = st.text_input("Output filename", value=default_name, key="out_name_check2")

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            flagged_df.to_excel(writer, sheet_name="Creation_Dummy_UUID_Check", index=False)
        st.download_button(
            "⬇ Download report", data=buf.getvalue(), file_name=out_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_check2",
        )

        save_path = st.text_input(
            "…or save directly to a path on this machine",
            value=str(os.path.join(_output_dir(), out_name)),
            key="save_path_check2",
        )
        if st.button("💾  Save to path", key="save_btn_check2"):
            try:
                write_dummy_uuid_report(flagged_df, save_path)
                st.success(f"✅ Saved to `{save_path}`")
            except Exception as exc:
                st.error(f"**Save failed:** {exc}")

    if active_check == CHECK_3 and st.session_state.flag_consistency_summary is not None:
        summary = st.session_state.flag_consistency_summary
        flagged_df = st.session_state.flag_consistency_df

        m1, m2, m3 = st.columns(3)
        m1.metric("Distinct Feature_Ids", summary["distinct_feature_ids"])
        m2.metric("Inconsistent Feature_Ids", summary["inconsistent_feature_ids"])
        m3.metric("Rows involved", summary["rows_involved"])

        if summary["layers_skipped_missing_columns"]:
            st.warning(
                "⚠ Skipped layer(s) with no detectable Feature_Id and/or Action_Flag column: "
                + ", ".join(summary["layers_skipped_missing_columns"])
            )

        with st.expander("Per-layer breakdown"):
            st.json(summary["per_layer"])

        st.markdown("#### Feature_Ids with inconsistent Action_Flag")
        st.caption(
            "Same Feature_Id carries a different Action_Flag in different "
            "layers/tables (e.g. U2 in the geometry layer vs U1 in an attribute table)."
        )
        st.dataframe(flagged_df, use_container_width=True, height=320)

        st.divider()
        st.subheader("④ Save report")

        default_name = "Action_Flag_Consistency_Validation.xlsx"
        out_name = st.text_input("Output filename", value=default_name, key="out_name_check3")

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            flagged_df.to_excel(writer, sheet_name="Action_Flag_Consistency", index=False)
        st.download_button(
            "⬇ Download report", data=buf.getvalue(), file_name=out_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_check3",
        )

        save_path = st.text_input(
            "…or save directly to a path on this machine",
            value=str(os.path.join(_output_dir(), out_name)),
            key="save_path_check3",
        )
        if st.button("💾  Save to path", key="save_btn_check3"):
            try:
                write_action_flag_consistency_report(flagged_df, save_path)
                st.success(f"✅ Saved to `{save_path}`")
            except Exception as exc:
                st.error(f"**Save failed:** {exc}")

    if active_check == CHECK_4 and st.session_state.dup_summary is not None:
        summary = st.session_state.dup_summary
        flagged_df = st.session_state.dup_flagged_df

        m1, m2, m3 = st.columns(3)
        m1.metric("Layers scanned", len(summary["layers_scanned"]))
        m2.metric("Flagged Feature_Ids", summary["total_flagged_feature_ids"])
        m3.metric("Flagged rows", summary["total_flagged_rows"])

        if summary["layers_skipped_no_feature_id_column"]:
            st.warning(
                "⚠ Skipped layer(s) with no detectable Feature_Id column: "
                + ", ".join(summary["layers_skipped_no_feature_id_column"])
            )
        if summary["layers_excluded_from_flagging"]:
            st.info(
                "ℹ Duplicate Feature_Ids found but **not flagged** (business-permitted) in: "
                + ", ".join(summary["layers_excluded_from_flagging"])
            )

        with st.expander("Per-layer breakdown"):
            st.json({
                "per_layer": summary["per_layer"],
                "duplicate_feature_id_count_per_layer": summary["duplicate_feature_id_count_per_layer"],
            })

        st.markdown("#### Duplicate Feature_Ids within a layer")
        st.caption(
            "Same Feature_Id appears more than once within the same layer/feature type "
            "(excludes layers marked as business-permitted above)."
        )
        st.dataframe(flagged_df, use_container_width=True, height=320)

        st.divider()
        st.subheader("④ Save report")

        default_name = "Duplicate_Feature_Id_Validation.xlsx"
        out_name = st.text_input("Output filename", value=default_name, key="out_name_check4")

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            flagged_df.to_excel(writer, sheet_name="Duplicate_Feature_Id", index=False)
        st.download_button(
            "⬇ Download report", data=buf.getvalue(), file_name=out_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_check4",
        )

        save_path = st.text_input(
            "…or save directly to a path on this machine",
            value=str(os.path.join(_output_dir(), out_name)),
            key="save_path_check4",
        )
        if st.button("💾  Save to path", key="save_btn_check4"):
            try:
                write_duplicate_feature_id_report(flagged_df, save_path)
                st.success(f"✅ Saved to `{save_path}`")
            except Exception as exc:
                st.error(f"**Save failed:** {exc}")

    if active_check == CHECK_5 and st.session_state.vertex_summary is not None:
        summary = st.session_state.vertex_summary
        flagged_df = st.session_state.vertex_flagged_df

        m1, m2 = st.columns(2)
        m1.metric("Total flagged", summary["total_flagged"])
        m2.metric("Tolerance (m)", summary["tolerance_m"])

        if summary["vad_filtering_applied"]:
            st.info(
                f"ℹ VAD filtering removed **{summary['vad_false_positives_removed']}** "
                "false positive(s) within the match tolerance."
            )

        with st.expander("Per-layer breakdown"):
            st.json(summary["per_layer"])

        st.markdown("#### Vertex spacing issues")
        st.caption("x / y are in WGS84 (lon/lat); dist_m is the real-world segment length.")
        st.dataframe(flagged_df, use_container_width=True, height=320)

        st.divider()
        st.subheader("④ Save report")

        default_name = "Vertex_Spacing_Validation.xlsx"
        out_name = st.text_input("Output filename", value=default_name, key="out_name_check5")

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            flagged_df.to_excel(writer, sheet_name="Vertex_Spacing", index=False)
        st.download_button(
            "⬇ Download report", data=buf.getvalue(), file_name=out_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_check5",
        )

        save_path = st.text_input(
            "…or save directly to a path on this machine",
            value=str(os.path.join(_output_dir(), out_name)),
            key="save_path_check5",
        )
        if st.button("💾  Save to path", key="save_btn_check5"):
            try:
                write_vertex_spacing_report(flagged_df, save_path)
                st.success(f"✅ Saved to `{save_path}`")
            except Exception as exc:
                st.error(f"**Save failed:** {exc}")

        st.markdown("##### Shapefile export (point at each flagged vertex)")
        _render_shapefile_export(
            build_point_gdf_from_xy(flagged_df, "x", "y"), "Vertex_Spacing_Points", "check5"
        )

    if active_check == CHECK_6 and st.session_state.spike_summary is not None:
        summary = st.session_state.spike_summary
        flagged_df = st.session_state.spike_flagged_df

        m1, m2 = st.columns(2)
        m1.metric("Total flagged", summary["total_flagged"])
        m2.metric("Angle threshold (°)", summary["angle_deg"])

        with st.expander("Per-layer breakdown"):
            st.json(summary["per_layer"])

        st.markdown("#### Spike angle issues")
        st.caption("x / y are in WGS84 (lon/lat); angle_deg is the vertex's interior angle.")
        st.dataframe(flagged_df, use_container_width=True, height=320)

        st.divider()
        st.subheader("④ Save report")

        default_name = "Spike_Angle_Validation.xlsx"
        out_name = st.text_input("Output filename", value=default_name, key="out_name_check6")

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            flagged_df.to_excel(writer, sheet_name="Spike_Angle", index=False)
        st.download_button(
            "⬇ Download report", data=buf.getvalue(), file_name=out_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_check6",
        )

        save_path = st.text_input(
            "…or save directly to a path on this machine",
            value=str(os.path.join(_output_dir(), out_name)),
            key="save_path_check6",
        )
        if st.button("💾  Save to path", key="save_btn_check6"):
            try:
                write_spike_angle_report(flagged_df, save_path)
                st.success(f"✅ Saved to `{save_path}`")
            except Exception as exc:
                st.error(f"**Save failed:** {exc}")

        st.markdown("##### Shapefile export (point at each flagged spike vertex)")
        _render_shapefile_export(
            build_point_gdf_from_xy(flagged_df, "x", "y"), "Spike_Angle_Points", "check6"
        )

    if active_check == CHECK_7 and st.session_state.si_summary is not None:
        summary = st.session_state.si_summary
        failed_df = st.session_state.si_failed_df
        points_df = st.session_state.si_points_df

        m1, m2 = st.columns(2)
        m1.metric("Failed (self-intersecting) features", summary["total_failed_features"])
        m2.metric("Intersection points", summary["total_intersection_points"])

        with st.expander("Per-layer breakdown"):
            st.json(summary["per_layer"])

        st.markdown("#### Failed polygons")
        st.caption("Features invalid specifically due to self-intersection.")
        st.dataframe(failed_df, use_container_width=True, height=260)

        st.markdown("#### Self-intersection points")
        st.caption("Exact XY location of each self-intersection (WGS84 lon/lat).")
        st.dataframe(points_df, use_container_width=True, height=260)

        st.divider()
        st.subheader("④ Save report")

        default_name = "Self_Intersecting_Polygon_Validation.xlsx"
        out_name = st.text_input("Output filename", value=default_name, key="out_name_check7")

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            failed_df.to_excel(writer, sheet_name="Failed_Polygons", index=False)
            points_df.to_excel(writer, sheet_name="Intersection_Points", index=False)
        st.download_button(
            "⬇ Download report", data=buf.getvalue(), file_name=out_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_check7",
        )

        save_path = st.text_input(
            "…or save directly to a path on this machine",
            value=str(os.path.join(_output_dir(), out_name)),
            key="save_path_check7",
        )
        if st.button("💾  Save to path", key="save_btn_check7"):
            try:
                write_self_intersection_report(failed_df, points_df, save_path)
                st.success(f"✅ Saved to `{save_path}`")
            except Exception as exc:
                st.error(f"**Save failed:** {exc}")

        st.markdown("##### Shapefile export — failed polygons (original geometry)")
        _render_shapefile_export(
            attach_source_polygon_geometry(failed_df, st.session_state.layers_data),
            "Self_Intersecting_Polygons", "check7_poly",
        )

        st.markdown("##### Shapefile export — self-intersection points")
        _render_shapefile_export(
            build_point_gdf_from_xy(points_df, "x_coord", "y_coord"), "Self_Intersection_Points", "check7_pts"
        )

    if active_check == CHECK_8 and st.session_state.schema_summary is not None:
        summary = st.session_state.schema_summary
        flagged_df = st.session_state.schema_flagged_df

        m1, m2 = st.columns(2)
        m1.metric("Layers scanned", len(summary["layers_scanned"]))
        m2.metric("Flagged", summary["total_flagged"])

        with st.expander("Per-layer breakdown"):
            st.json(summary["per_layer"])

        st.markdown("#### Layer schema findings")
        st.caption("Unrecognized layer names, missing fields, geometry-type mismatches, unexpected Feature_Type values.")
        st.dataframe(flagged_df, use_container_width=True, height=320)

        st.divider()
        st.subheader("④ Save report")

        default_name = "Layer_Schema_Validation.xlsx"
        out_name = st.text_input("Output filename", value=default_name, key="out_name_check8")

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            flagged_df.to_excel(writer, sheet_name="Layer_Schema", index=False)
        st.download_button(
            "⬇ Download report", data=buf.getvalue(), file_name=out_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_check8",
        )

        save_path = st.text_input(
            "…or save directly to a path on this machine",
            value=str(os.path.join(_output_dir(), out_name)),
            key="save_path_check8",
        )
        if st.button("💾  Save to path", key="save_btn_check8"):
            try:
                write_layer_schema_report(flagged_df, save_path)
                st.success(f"✅ Saved to `{save_path}`")
            except Exception as exc:
                st.error(f"**Save failed:** {exc}")

    if active_check == CHECK_9 and st.session_state.ot_summary is not None:
        summary = st.session_state.ot_summary
        flagged_df = st.session_state.ot_flagged_df

        m1, m2, m3 = st.columns(3)
        m1.metric("Layers present", len(summary["layers_present"]))
        m2.metric("Errors", summary["errors"])
        m3.metric("Warnings", summary["warnings"])

        if summary["layers_missing"]:
            st.info("ℹ Layers not present in this source: " + ", ".join(summary["layers_missing"]))

        with st.expander("Per-layer breakdown"):
            st.json(summary["per_layer"])

        st.markdown("#### Output template findings")
        st.caption(
            "Full Output Template Check rule set (field/geometry/Feature_Type conformance, "
            "null/blank scanning, Action_Flag value sets, ID length/duplicate rules, "
            "Feature_Type↔Attribute_Key rules, occurrence-count rules, Postal_Name text rules)."
        )
        st.dataframe(flagged_df, use_container_width=True, height=380)

        st.divider()
        st.subheader("④ Save report")

        default_name = "Output_Template_Validation.xlsx"
        out_name = st.text_input("Output filename", value=default_name, key="out_name_check9")

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            flagged_df.to_excel(writer, sheet_name="Output_Template_Check", index=False)
        st.download_button(
            "⬇ Download report", data=buf.getvalue(), file_name=out_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_check9",
        )

        save_path = st.text_input(
            "…or save directly to a path on this machine",
            value=str(os.path.join(_output_dir(), out_name)),
            key="save_path_check9",
        )
        if st.button("💾  Save to path", key="save_btn_check9"):
            try:
                write_output_template_report(flagged_df, save_path)
                st.success(f"✅ Saved to `{save_path}`")
            except Exception as exc:
                st.error(f"**Save failed:** {exc}")

    if active_check == CHECK_10 and st.session_state.fid_vad_summary is not None:
        summary = st.session_state.fid_vad_summary
        flagged_df = st.session_state.fid_vad_flagged_df

        m1, m2, m3 = st.columns(3)
        m1.metric("Records checked", summary["total_checked"])
        m2.metric("Records flagged", summary["total_flagged"])
        m3.metric("VAD Feature_Id pool size", summary["vad_id_pool_size"])

        if summary["source_layers_skipped_no_feature_id_column"]:
            st.warning(
                "⚠ Skipped layer(s) with no detectable Feature_Id column: "
                + ", ".join(summary["source_layers_skipped_no_feature_id_column"])
            )

        with st.expander("Per-layer breakdown"):
            st.json({
                "excluded_action_flags": summary["excluded_action_flags"],
                "vad_layers_used": summary["vad_layers_used"],
                "vad_id_column_by_layer": summary["vad_id_column_by_layer"],
                "per_layer": summary["per_layer"],
            })

        st.markdown("#### Flagged records")
        st.caption(
            "Feature_Id is missing from the VAD, and/or duplicated within the source "
            "(among non-excluded Action_Flag records)."
        )
        st.dataframe(flagged_df, use_container_width=True, height=320)

        st.divider()
        st.subheader("④ Save report")

        default_name = "FID_Not_Match_with_VAD.xlsx"
        out_name = st.text_input("Output filename", value=default_name, key="out_name_check10")

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            flagged_df.to_excel(writer, sheet_name="FID_Not_Match_with_VAD"[:31], index=False)
        st.download_button(
            "⬇ Download report", data=buf.getvalue(), file_name=out_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_check10",
        )

        save_path = st.text_input(
            "…or save directly to a path on this machine",
            value=str(os.path.join(_output_dir(), out_name)),
            key="save_path_check10",
        )
        if st.button("💾  Save to path", key="save_btn_check10"):
            try:
                write_fid_not_match_with_vad_report(flagged_df, save_path)
                st.success(f"✅ Saved to `{save_path}`")
            except Exception as exc:
                st.error(f"**Save failed:** {exc}")

# ── Footer ────────────────────────────────────────────────────────────────────
st.divider()
st.markdown(
    '<div class="adp-footer">Developed by <strong>ADP-Pune</strong> &nbsp;|&nbsp; '
    'Mentor: <a href="mailto:prabhakar.chaudhari@tomtom.com" style="color:#1a56db;text-decoration:none;">'
    'prabhakar.chaudhari@tomtom.com</a></div>',
    unsafe_allow_html=True,
)
