import os
import sys
import streamlit as st
import pandas as pd

# Heavy geospatial imports (geopandas, shapely, pyproj) live inside analyzer.py.
# We import lazily so the Streamlit page renders instantly on first load.
# list_layers is cached so it won't re-read the GDB on every UI rerun.
@st.cache_data(show_spinner=False)
def _cached_list_layers(path: str):
    from analyzer import list_layers
    return list_layers(path)


@st.cache_data(show_spinner=False)
def _cached_get_geom_type(path: str, layer=None) -> str:
    """Return the geometry type string for a layer ('Polygon', 'Point', etc.)."""
    try:
        import fiona
        kwargs = {"layer": layer} if layer else {}
        with fiona.open(path, **kwargs) as f:
            return f.schema.get("geometry", "Unknown")
    except Exception:
        try:
            import geopandas as gpd
            kwargs = {"layer": layer} if layer else {}
            gdf = gpd.read_file(path, rows=5, **kwargs)
            types = gdf.geometry.geom_type.dropna().unique().tolist()
            return types[0] if types else "Unknown"
        except Exception:
            return "Unknown"


@st.cache_data(show_spinner=False)
def _cached_get_columns(path: str, layer=None):
    """Return non-geometry column names for a dataset layer (fast, no full read)."""
    try:
        import fiona
        kwargs = {"layer": layer} if layer else {}
        with fiona.open(path, **kwargs) as f:
            return list(f.schema["properties"].keys())
    except Exception:
        try:
            import geopandas as gpd
            kwargs = {"layer": layer} if layer else {}
            gdf = gpd.read_file(path, rows=1, **kwargs)
            return [c for c in gdf.columns if c != "geometry"]
        except Exception:
            return []


def _is_polygon_type(geom_type: str) -> bool:
    """Return True if the geometry type is polygon-like."""
    return any(t in geom_type for t in ("Polygon", "polygon", "Surface"))


st.set_page_config(
    page_title="Postal Area Quality Check",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Global CSS — inject into the Streamlit app shell so the header bar can go full-width
st.markdown(
    """
    <style>
    /* Remove top padding so header bar touches the top edge */
    section.main > div.block-container {
        padding-top: 0 !important;
    }
    div[data-testid="metric-container"] {
        background: #f0f4ff;
        border-radius: 8px;
        padding: 8px 16px;
    }
    .adp-footer {
        text-align: center;
        padding: 16px 0 6px 0;
        color: #6b7280;
        font-size: 14px;
        border-top: 1px solid #e5e7eb;
        margin-top: 8px;
    }
    .adp-footer strong { color: #1a56db; font-size: 15px; }
    .adp-footer a     { color: #1a56db; text-decoration: none; font-size: 15px; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── TomTom header bar ────────────────────────────────────────────────────────
# Try to load the official logo from the Leave Deviation tool folder.
# Falls back to a built-in base64 SVG if the file is not found.
import base64 as _b64

def _load_logo_b64() -> tuple:
    """Return (data_uri, mime_type) for the TomTom logo.

    Fully dynamic — no hardcoded user paths.
    Searches the tool folder, parent folders, the current user's profile
    directories, and all available drive letters with common TomTom folder
    names. Falls back to a built-in SVG pin+wordmark if nothing is found.
    """
    _img_exts   = (".png", ".svg", ".jpg", ".jpeg", ".ico")
    _logo_names = ["TomTom_logo", "tomtom_logo", "TomTomLogo",
                   "TomTom", "tomtom", "Logo", "logo"]
    _mime_map   = {".png": "image/png", ".svg": "image/svg+xml",
                   ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                   ".ico": "image/x-icon"}

    # ── Dynamic path roots ───────────────────────────────────────────────────
    _tool_dir  = os.path.dirname(os.path.abspath(__file__))
    _user_home = os.path.expanduser("~")                      # works on all OS

    # Windows environment variables for additional profile paths
    _userprofile = os.environ.get("USERPROFILE", _user_home)
    _appdata     = os.environ.get("APPDATA", "")
    _onedrive    = os.environ.get("OneDrive", os.path.join(_user_home, "OneDrive"))
    _username    = os.environ.get("USERNAME", os.environ.get("USER", ""))

    # Common TomTom-related subfolder names that any user might have
    _tt_folders = ["TomTom", "TomTom_logo", "Leave_Deviation",
                   "ADP", "ADP_Tools", "Tools", "Logos", "Assets",
                   "PD_Quality", "Geo_Converter", "AA1_Check"]

    _search_dirs = []

    # Priority 1 — tool folder itself + up to 3 parent levels
    _p = _tool_dir
    for _ in range(4):
        _search_dirs.append(_p)
        _search_dirs.extend(os.path.join(_p, n) for n in _tt_folders)
        _parent = os.path.dirname(_p)
        if _parent == _p:
            break
        _p = _parent

    # Priority 2 — current user's profile folders (dynamic, works for any user)
    for _base in [_userprofile, _user_home, _onedrive]:
        if not _base:
            continue
        for _sub in ["Desktop", "Documents", "Downloads", "Pictures",
                     "OneDrive", "OneDrive - TomTom"] + _tt_folders:
            _search_dirs.append(os.path.join(_base, _sub))
        # User root itself
        _search_dirs.append(_base)

    # Priority 3 — every available drive letter × common TomTom folder names
    for _drv in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        _root = f"{_drv}:\\"
        if os.path.isdir(_root):
            _search_dirs.append(_root)
            for _n in _tt_folders + [_username] if _username else _tt_folders:
                _search_dirs.append(os.path.join(_root, _n))
                for _sub in _tt_folders:
                    _search_dirs.append(os.path.join(_root, _n, _sub))

    # ── Build candidate file list ────────────────────────────────────────────
    _candidates = []
    for _d in _search_dirs:
        try:
            if os.path.isdir(_d):
                # Scan directory for any file whose name starts with a logo name
                for _f in sorted(os.listdir(_d)):
                    _fl = _f.lower()
                    if any(_fl.startswith(n.lower()) for n in _logo_names) \
                            and _fl.endswith(_img_exts):
                        _candidates.append(os.path.join(_d, _f))
                # Also try exact name + extension combos
                for _name in _logo_names:
                    for _ext in _img_exts:
                        _candidates.append(os.path.join(_d, _name + _ext))
        except PermissionError:
            continue

    # De-duplicate while preserving order
    _seen, _deduped = set(), []
    for _p in _candidates:
        if _p not in _seen:
            _seen.add(_p)
            _deduped.append(_p)

    for _path in _deduped:
        if os.path.isfile(_path):
            _ext  = os.path.splitext(_path)[1].lower()
            _mime = _mime_map.get(_ext, "image/png")
            try:
                with open(_path, "rb") as _fh:
                    _data = _b64.b64encode(_fh.read()).decode()
                return f"data:{_mime};base64,{_data}", _mime
            except Exception:
                continue

    # Built-in fallback: teardrop pin + "tomtom" wordmark SVG (220×60 viewBox)
    _svg = "PHN2ZyB3aWR0aD0iMjIwIiBoZWlnaHQ9IjYwIiB2aWV3Qm94PSIwIDAgMjIwIDYwIiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPgogIDxwYXRoIGQ9Ik0yOCA0QzE3LjUgNCA5IDEyLjUgOSAyM0M5IDM0IDI4IDU2IDI4IDU2QzI4IDU2IDQ3IDM0IDQ3IDIzQzQ3IDEyLjUgMzguNSA0IDI4IDRaIiBmaWxsPSIjRTIyMzFBIi8+CiAgPGNpcmNsZSBjeD0iMjgiIGN5PSIyMiIgcj0iOSIgZmlsbD0id2hpdGUiLz4KICA8dGV4dCB4PSI1OCIgeT0iNDAiIGZvbnQtZmFtaWx5PSJBcmlhbCBCbGFjayxBcmlhbCBSb3VuZGVkIE1UIEJvbGQsQXJpYWwgQm9sZCxBcmlhbCxzYW5zLXNlcmlmIiBmb250LXdlaWdodD0iOTAwIiBmb250LXNpemU9IjMwIiBmaWxsPSJ3aGl0ZSIgbGV0dGVyLXNwYWNpbmc9IjAiPnRvbXRvbTwvdGV4dD4KPC9zdmc+"
    return f"data:image/svg+xml;base64,{_svg}", "image/svg+xml"


_logo_uri, _ = _load_logo_b64()

st.markdown(
    f"""
    <div style="
        background:#111111;
        padding:10px 28px;
        width:100%;
        box-sizing:border-box;
        border-bottom:2px solid #2a2a2a;
    ">
      <img src="{_logo_uri}" height="52" alt="TomTom"
           style="display:block;" />
    </div>
    """,
    unsafe_allow_html=True,
)

# ── Tool title + credits ─────────────────────────────────────────────────────
st.markdown(
    """
    <div style="padding:18px 0 4px 0;">
      <div style="font-size:30px; font-weight:700; color:#FFFFFF; margin:0 0 5px 0; line-height:1.2;">
        Postal Area Quality Check Tool
      </div>
      <div style="font-size:13px; color:#9CA3AF; margin:0 0 8px 0;">
        Spike Detection &nbsp;|&nbsp; Sliver Detection &nbsp;|&nbsp;
        Failed Geometry &nbsp;|&nbsp; Multipart Validation
      </div>
      <div style="font-size:15px; color:#D1D5DB;">
        &copy;&nbsp;
        <strong style="color:#60A5FA; font-size:16px;">ADP Team, TomTom</strong>
        &nbsp;&nbsp;|&nbsp;&nbsp;
        <a href="mailto:prabhakar.chaudhari@tomtom.com"
           style="color:#60A5FA; font-size:15px; text-decoration:none;">
          prabhakar.chaudhari@tomtom.com
        </a>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)
st.divider()

_defaults = {
    "result": None, "ran": False, "out_path": "", "excel_bytes": None,
    "excel_name": "", "src_path": "", "mds_path": "", "out_dir": "",
    "out_format": "", "saved_paths": [],
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ---------------------------------------------------------------------------
# Browse helpers — exact same pattern as GeoConverter tool
# ---------------------------------------------------------------------------

def _browse_folder(state_key: str, title: str = "Select folder") -> None:
    """Open OS folder picker; store result in session state (GeoConverter pattern)."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", 1)
        path = filedialog.askdirectory(title=title)
        root.destroy()
        if path:
            st.session_state[state_key] = os.path.normpath(path)
    except Exception as e:
        st.warning(f"Folder browser unavailable: {e}. Please type the path manually.")


def _browse_file(state_key: str, title: str = "Select file") -> None:
    """Open OS file picker; store result in session state (GeoConverter pattern)."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", 1)
        path = filedialog.askopenfilename(
            title=title,
            filetypes=[
                ("Geospatial files", "*.shp *.gpkg"),
                ("Shapefile",        "*.shp"),
                ("GeoPackage",       "*.gpkg"),
                ("All files",        "*.*"),
            ],
        )
        root.destroy()
        if path:
            st.session_state[state_key] = os.path.normpath(path)
    except Exception as e:
        st.warning(f"File browser unavailable: {e}. Please type the path manually.")


# ---------------------------------------------------------------------------
# Step 1: Input Datasets
# ---------------------------------------------------------------------------
st.subheader("Step 1 - Input Datasets")
st.caption("Browse to a .gdb folder or select a .shp / .gpkg file for both Source and MDS.")

# ── Source GDB / SHP ──────────────────────────────────────────────────────
col_src_gdb, col_src_shp, col_src_txt = st.columns([1, 1, 5])
with col_src_gdb:
    st.markdown("<div style='padding-top:4px'>", unsafe_allow_html=True)
    if st.button("📂 GDB", key="src_browse_gdb", use_container_width=True):
        _browse_folder("src_path", "Select Source GDB folder")
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
with col_src_shp:
    st.markdown("<div style='padding-top:4px'>", unsafe_allow_html=True)
    if st.button("📁 SHP", key="src_browse_shp", use_container_width=True):
        _browse_file("src_path", "Select Source Shapefile or GeoPackage")
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
with col_src_txt:
    src_typed = st.text_input(
        "Source Dataset (.gdb / .shp / .gpkg)",
        value=st.session_state["src_path"],
        placeholder=r"C:\Path\To\Source.gdb  (or .shp / .gpkg)",
        label_visibility="visible",
    )
    st.session_state["src_path"] = src_typed

source_gdb = st.session_state["src_path"]

source_layers = []   # list of layer names to process
if source_gdb and os.path.exists(source_gdb):
    try:
        src_all = _cached_list_layers(source_gdb)
        _is_src_shp = source_gdb.lower().endswith(".shp")
        if _is_src_shp:
            # Shapefile: single layer — no selection widget needed
            source_layers = src_all
            st.info(f"ℹ️ Shapefile — **{src_all[0]}** will be processed directly.")
        elif len(src_all) == 1:
            _picked = st.selectbox("Source Layer", src_all, key="src_layer")
            source_layers = [_picked]
            st.success(f"✓ 1 layer found in {os.path.basename(source_gdb)}")
        else:
            _src_geom_types  = {lyr: _cached_get_geom_type(source_gdb, lyr) for lyr in src_all}
            _src_poly_layers = [l for l in src_all if _is_polygon_type(_src_geom_types[l])]
            _src_nonpoly     = [l for l in src_all if not _is_polygon_type(_src_geom_types[l])]
            _default_src     = _src_poly_layers if _src_poly_layers else src_all
            _picked = st.multiselect(
                "Source Layers  (uncheck to exclude)",
                options=src_all,
                default=_default_src,
                key="src_layers",
                help="Polygon layers selected by default. Non-polygon layers are excluded automatically.",
            )
            source_layers = _picked if _picked else _default_src
            if _src_nonpoly:
                st.warning(
                    f"⚠️ Non-polygon layer(s) found and excluded: "
                    + ", ".join(f"**{l}** ({_src_geom_types[l]})" for l in _src_nonpoly)
                )
            st.success(
                f"✓ {len(src_all)} layers found — "
                f"**{len(source_layers)}** selected for processing"
            )
    except Exception as e:
        st.error(f"Cannot read Source: {e}")
elif source_gdb:
    st.warning("Source path not found")

st.write("")

# ── MDS GDB / SHP ─────────────────────────────────────────────────────────
col_mds_gdb, col_mds_shp, col_mds_txt = st.columns([1, 1, 5])
with col_mds_gdb:
    st.markdown("<div style='padding-top:4px'>", unsafe_allow_html=True)
    if st.button("📂 GDB", key="mds_browse_gdb", use_container_width=True):
        _browse_folder("mds_path", "Select MDS GDB folder")
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
with col_mds_shp:
    st.markdown("<div style='padding-top:4px'>", unsafe_allow_html=True)
    if st.button("📁 SHP", key="mds_browse_shp", use_container_width=True):
        _browse_file("mds_path", "Select MDS Shapefile or GeoPackage")
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
with col_mds_txt:
    mds_typed = st.text_input(
        "MDS Dataset (.gdb / .shp / .gpkg)",
        value=st.session_state["mds_path"],
        placeholder=r"C:\Path\To\MDS.gdb  (or .shp / .gpkg)",
        label_visibility="visible",
    )
    st.session_state["mds_path"] = mds_typed

mds_gdb = st.session_state["mds_path"]

mds_layers = []   # list of layer names to process
if mds_gdb and os.path.exists(mds_gdb):
    try:
        mds_all = _cached_list_layers(mds_gdb)
        _is_mds_shp = mds_gdb.lower().endswith(".shp")
        if _is_mds_shp:
            mds_layers = mds_all
            st.info(f"ℹ️ Shapefile — **{mds_all[0]}** will be processed directly.")
        elif len(mds_all) == 1:
            _picked_m = st.selectbox("MDS Layer", mds_all, key="mds_layer")
            mds_layers = [_picked_m]
            st.success(f"✓ 1 layer found in {os.path.basename(mds_gdb)}")
        else:
            # Detect geometry types and split into polygon vs non-polygon layers
            _mds_geom_types = {
                lyr: _cached_get_geom_type(mds_gdb, lyr) for lyr in mds_all
            }
            _poly_layers    = [l for l in mds_all if _is_polygon_type(_mds_geom_types[l])]
            _nonpoly_layers = [l for l in mds_all if not _is_polygon_type(_mds_geom_types[l])]

            # Default selection: polygon layers only (non-polygon excluded automatically)
            _default_mds = _poly_layers if _poly_layers else mds_all
            _picked_m = st.multiselect(
                "MDS Layers  (uncheck to exclude)",
                options=mds_all,
                default=_default_mds,
                key="mds_layers",
                help=(
                    "Polygon layers are selected by default. "
                    "Point/line layers are deselected automatically — "
                    "the QC checks require polygon geometry."
                ),
            )
            mds_layers = _picked_m if _picked_m else _default_mds

            # Warn if non-polygon layers were found and auto-excluded
            if _nonpoly_layers:
                _nl_info = ", ".join(
                    f"**{l}** ({_mds_geom_types[l]})" for l in _nonpoly_layers
                )
                st.warning(
                    f"⚠️ Non-polygon layer(s) found and excluded from default selection: "
                    f"{_nl_info}. These would produce incorrect geometry outputs — "
                    f"the QC tool requires Polygon layers."
                )
            # Warn if user manually included a non-polygon layer
            _selected_nonpoly = [l for l in mds_layers if l in _nonpoly_layers]
            if _selected_nonpoly:
                st.error(
                    f"❌ Non-polygon layer(s) selected: "
                    f"{', '.join(_selected_nonpoly)}. "
                    f"Please deselect them — running QC on Point/Line geometry will "
                    f"give wrong results."
                )

            st.success(
                f"✓ {len(mds_all)} layers found  "
                f"({len(_poly_layers)} polygon, {len(_nonpoly_layers)} other) — "
                f"**{len(mds_layers)}** selected for processing"
            )
    except Exception as e:
        st.error(f"Cannot read MDS: {e}")
elif mds_gdb:
    st.warning("MDS path not found")

st.divider()


# ---------------------------------------------------------------------------
# Step 2: Parameters + Check Selection
# ---------------------------------------------------------------------------
st.subheader("Step 2 - Quality Check Parameters")

spike_angle = st.number_input(
    "Spike Angle Threshold (degrees)",
    min_value=1.0, max_value=45.0, value=15.0, step=1.0,
    help="FME default: 15 deg (SpikeRemoverFactory SPIKE_ANGLE=15)",
)

buffer_dist_m = st.number_input(
    "Buffer Distance (metres) — Step 3 geometry comparison threshold",
    min_value=1.0, max_value=10000.0, value=200.0, step=1.0,
    help=(
        "Sets the split threshold for the Failed Geometry check.\n"
        "Outputs produced:\n"
        "  • Less than 1 m        — coordinate noise (optional)\n"
        "  • 1 m to Buffer value  — minor deviations\n"
        "  • Greater than Buffer  — major errors\n"
        "Different countries can use different values without changing the tool."
    ),
)

st.write("")
st.caption("Select checks to run (all enabled by default):")
cc1, cc2, cc3, cc4, cc5 = st.columns(5)
with cc1:
    run_spike        = st.checkbox("Spike Detection",    value=True, key="chk_spike")
with cc2:
    run_sliver       = st.checkbox("Sliver Detection",   value=True, key="chk_sliver")
with cc3:
    run_buffer       = st.checkbox("Failed Geometry",    value=True,  key="chk_buffer")
with cc4:
    run_multipart    = st.checkbox("Multipart Check",    value=True,  key="chk_multipart")
with cc5:
    run_poly_quality = st.checkbox("Polygon Quality",    value=False, key="chk_poly_quality")

if not any([run_spike, run_sliver, run_buffer, run_multipart, run_poly_quality]):
    st.warning("No checks selected — all checks will run by default.")
    run_spike = run_sliver = run_buffer = run_multipart = run_poly_quality = True

include_lt1m = st.checkbox(
    "Include < 1 m noise layer in output  (Geometry_Failed_Less_Than_1m)",
    value=False,
    key="chk_lt1m",
    help=(
        "When unchecked (default), coordinate-rounding noise parts are still detected "
        "and used by the internal noise filter, but the layer is NOT written to the "
        "output file and is not shown in the results tabs.\n"
        "Enable only if you want to inspect sub-1m artefacts explicitly."
    ),
)

# ── Step 3 ID Column Mapping ──────────────────────────────────────────────
st.write("")
_both_loaded = (
    source_gdb and os.path.exists(source_gdb) and bool(source_layers) and
    mds_gdb and os.path.exists(mds_gdb) and bool(mds_layers)
)
ui_src_id = None   # default: let auto-detection decide
ui_mds_id = None

with st.expander(
    "Step 3 — ID Column Mapping  (auto-detected; expand only if geometry check gives 0 rows)",
    expanded=False,
):
    if _both_loaded:
        try:
            _src_lyr_for_cols = (
                None if source_gdb.lower().endswith(".shp")
                else source_layers[0]
            )
            _mds_lyr_for_cols = (
                None if mds_gdb.lower().endswith(".shp")
                else mds_layers[0]
            )
            _src_cols0 = _cached_get_columns(source_gdb, _src_lyr_for_cols)
            _mds_cols0 = _cached_get_columns(mds_gdb,    _mds_lyr_for_cols)

            st.caption(
                "Step 3 (Failed Geometry check) matches Source and MDS features by ID value. "
                "The tool auto-detects the right columns — first by name, then by value overlap. "
                "If auto-detection picks the wrong columns (or gives 0 rows), "
                "select the correct ID columns manually below."
            )
            _oc1, _oc2 = st.columns(2)
            with _oc1:
                _src_id_raw = st.selectbox(
                    "Source ID Column",
                    options=["(auto)"] + _src_cols0,
                    key="src_id_override",
                    help="Column in Source whose values identify each postal area feature.",
                )
            with _oc2:
                _mds_id_raw = st.selectbox(
                    "MDS ID Column",
                    options=["(auto)"] + _mds_cols0,
                    key="mds_id_override",
                    help="Column in MDS whose values match the Source ID column above.",
                )
            ui_src_id = None if _src_id_raw == "(auto)" else _src_id_raw
            ui_mds_id = None if _mds_id_raw == "(auto)" else _mds_id_raw
            if ui_src_id and ui_mds_id:
                st.success(
                    f"✎ Manual override: Source.**{ui_src_id}** ↔ MDS.**{ui_mds_id}**  "
                    "(this will override auto-detection)"
                )
            else:
                st.info(
                    "Both set to **(auto)** — ID columns will be detected automatically at run time. "
                    "The matched columns will be shown in the Step 5 summary."
                )
        except Exception as _e:
            st.caption(f"Column preview unavailable: {_e}")
    else:
        st.info("Load both datasets above to enable ID column override.")

st.divider()


# ---------------------------------------------------------------------------
# Step 3: Output Path + Format
# ---------------------------------------------------------------------------
st.subheader("Step 3 - Output Path")
default_out = st.session_state["out_dir"] or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "Output")

if not st.session_state["out_dir"]:
    st.session_state["out_dir"] = default_out

col_out_btn, col_out_txt = st.columns([1, 5])
with col_out_btn:
    st.markdown("<div style='padding-top:4px'>", unsafe_allow_html=True)
    if st.button("📂 Browse", key="out_browse", use_container_width=True):
        _browse_folder("out_dir", "Select output folder")
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
with col_out_txt:
    out_typed = st.text_input(
        "Output Folder",
        value=st.session_state["out_dir"],
        help="QC results will be saved here",
    )
    st.session_state["out_dir"] = out_typed

out_dir = st.session_state["out_dir"] or default_out

st.write("")
st.caption("Output format:")
fmt_choice = st.radio(
    "Output format",
    options=["Both (GeoPackage + Shapefile)", "GeoPackage only", "Shapefile only"],
    index=0,
    horizontal=True,
    label_visibility="collapsed",
)

st.divider()


# ---------------------------------------------------------------------------
# Step 4: Run
# ---------------------------------------------------------------------------
st.subheader("Step 4 - Run Quality Checks")

def _pair_layers(src: list, mds: list) -> list:
    """Return list of (src_layer, mds_layer) tuples to run QC on.

    Pairing rules (in priority order):
    1. If both sides share any layer names → pair matching names only.
    2. Otherwise → pair by position (zip, extras are dropped).
    """
    if not src or not mds:
        return []
    common = set(src) & set(mds)
    if common:
        return [(s, s) for s in src if s in common]
    return list(zip(src, mds))


missing = []
if not source_gdb or not os.path.exists(source_gdb): missing.append("Source Dataset")
if not source_layers:                                 missing.append("Source Layer(s)")
if not mds_gdb    or not os.path.exists(mds_gdb):    missing.append("MDS Dataset")
if not mds_layers:                                    missing.append("MDS Layer(s)")
if not out_dir:                                       missing.append("Output Folder")

if missing:
    st.info(f"Complete before running: {', '.join(missing)}")

run_clicked = st.button("Run All QC Checks", type="primary", disabled=bool(missing))

if run_clicked:
    progress_bar = st.progress(0, text="Loading geospatial libraries...")
    status_box   = st.empty()

    # Import analyzer here (not at module level) so the page loads instantly.
    from analyzer import run_qc, merge_qc_results, write_gpkg, write_shp, to_excel_bytes  # noqa: E402

    layer_pairs = _pair_layers(source_layers, mds_layers)
    _n_pairs    = len(layer_pairs)

    def _make_progress(pair_idx: int, pair_n: int):
        def _cb(step, total, msg):
            base   = pair_idx / max(pair_n, 1)
            span   = 1.0      / max(pair_n, 1)
            pct    = int((base + span * step / max(total, 1)) * 90)
            prefix = f"[{pair_idx+1}/{pair_n}] " if pair_n > 1 else ""
            progress_bar.progress(pct, text=f"{prefix}{msg}")
            status_box.info(f"{prefix}{msg}")
        return _cb

    try:
        _all_results = []
        for _pi, (_src_lyr, _mds_lyr) in enumerate(layer_pairs):
            _r = run_qc(
                source_gdb=source_gdb,
                mds_gdb=mds_gdb,
                source_layer=_src_lyr,
                mds_layer=_mds_lyr,
                spike_angle=spike_angle,
                buffer_dist_m=buffer_dist_m,
                run_spike=run_spike,
                run_sliver=run_sliver,
                run_buffer=run_buffer,
                run_multipart=run_multipart,
                run_poly_quality=run_poly_quality,
                progress_callback=_make_progress(_pi, _n_pairs),
                source_id_col=ui_src_id,
                mds_id_col=ui_mds_id,
            )
            # When multiple layers are processed, tag each row with its layer name
            if _n_pairs > 1:
                for _attr in ["spike", "sliver", "geom_lt1", "geom_lt_buf",
                               "geom_gt_buf", "multipart", "poly_quality"]:
                    _gdf = getattr(_r, _attr)
                    if _gdf is not None and len(_gdf) > 0:
                        _gdf.insert(0, "_layer", _src_lyr)
            _all_results.append(_r)

        result = merge_qc_results(_all_results)
        st.session_state["include_lt1m"] = include_lt1m

        progress_bar.progress(95, text="Writing output files...")
        status_box.info("Writing output files...")
        os.makedirs(out_dir, exist_ok=True)
        ts = result.timestamp

        gpkg_path = os.path.join(out_dir, f"QC_Results_{ts}.gpkg")
        shp_path  = os.path.join(out_dir, f"QC_Results_{ts}_SHP")
        out_path  = gpkg_path          # default for info display
        saved     = []

        write_gpkg_flag = fmt_choice in ("Both (GeoPackage + Shapefile)", "GeoPackage only")
        write_shp_flag  = fmt_choice in ("Both (GeoPackage + Shapefile)", "Shapefile only")

        if write_gpkg_flag:
            try:
                write_gpkg(result, gpkg_path)
                saved.append(f"GeoPackage: `{gpkg_path}`")
                out_path = gpkg_path
            except Exception as gpkg_err:
                st.warning(f"GeoPackage write failed ({gpkg_err}).")

        if write_shp_flag:
            try:
                write_shp(result, shp_path)
                saved.append(f"Shapefile folder: `{shp_path}`")
                if not write_gpkg_flag:
                    out_path = shp_path
            except Exception as shp_err:
                st.warning(f"Shapefile write failed ({shp_err}).")

        out_format = fmt_choice

        excel_bytes = to_excel_bytes(result)
        excel_name  = f"QC_Results_{ts}.xlsx"

        progress_bar.progress(100, text="Done!")
        status_box.empty()

        st.session_state.update({
            "result":      result,
            "ran":         True,
            "out_path":    out_path,
            "out_format":  out_format,
            "saved_paths": saved,
            "excel_bytes": excel_bytes,
            "excel_name":  excel_name,
        })

        s = result.summary
        _t = int(s['effective_threshold_m'])
        _lt1_part = f"Geo Failed <1m: **{s['geom_lt1_count']}** | " if include_lt1m else ""
        st.success(
            f"QC complete!  "
            f"Spikes: **{s['spike_count']}** | "
            f"Slivers: **{s['sliver_count']}** | "
            + _lt1_part +
            f"Geo Failed 1-{_t}m: **{s['geom_lt_buf_count']}** | "
            f"Geo Failed >{_t}m: **{s['geom_gt_buf_count']}** | "
            f"Multipart discrepancies: **{s['multipart_discrepancy_count']}**"
        )
        for path_msg in saved:
            st.info(f"Saved — {path_msg}")

    except Exception as exc:
        progress_bar.empty()
        status_box.empty()
        st.error(f"QC failed: {exc}")
        import traceback
        st.code(traceback.format_exc())
        st.session_state["ran"] = False



# ---------------------------------------------------------------------------
# Step 5: Results
# ---------------------------------------------------------------------------
if st.session_state["ran"] and st.session_state["result"]:
    result       = st.session_state["result"]
    s            = result.summary
    include_lt1m = st.session_state.get("include_lt1m", False)
    _cr          = s.get("checks_run", {})   # dict[check_key -> bool]
    _t           = int(s["effective_threshold_m"])

    st.divider()
    st.subheader("Step 5 - Results Summary")

    # ── Summary table (only enabled checks) ─────────────────────────────────
    _report_rows = [
        ("Source Features", s["source_feature_count"], "-"),
        ("MDS Features",    s["mds_feature_count"],    "-"),
    ]
    if _cr.get("spike", True):
        _report_rows.append((
            "Spike Vertices  (Spike_Output)", s["spike_count"],
            f"MDS angle <= {s['spike_angle_threshold']} deg",
        ))
    if _cr.get("sliver", True):
        _report_rows.append((
            "Sliver Polygons (Sliver_Suspicious_Area_Output)", s["sliver_count"],
            "Gap area rounds to 0 (6 d.p.)",
        ))
    if _cr.get("buffer", True):
        if include_lt1m:
            _report_rows.append((
                "Geometry_Failed < 1 m", s["geom_lt1_count"],
                "Sym-diff parts < 1 m — coordinate rounding / positional noise",
            ))
        _report_rows.append((
            f"Geometry_Failed 1-{_t} m", s["geom_lt_buf_count"],
            f"Sym-diff parts: deviation 1–{_t} m (minor)",
        ))
        _report_rows.append((
            f"Geometry_Failed > {_t} m", s["geom_gt_buf_count"],
            f"Sym-diff parts: deviation > {_t} m (major)",
        ))
    if _cr.get("multipart", True):
        _report_rows += [
            ("Source Multipart", s["src_multipart_count"], "-"),
            ("MDS Multipart",    s["mds_multipart_count"], "-"),
            ("Multipart — Extra in MDS",  s.get("multipart_extra_count", 0),
             "MDS parts with no matching Source part (over-updated)"),
            ("Multipart — Missing in MDS", s.get("multipart_missing_count", 0),
             "Source parts not found in MDS (update missing)"),
        ]
    if _cr.get("poly_quality", True):
        _report_rows.append((
            "Polygon Quality Check", s["poly_quality_count"],
            "Sym-diff parts (by UUID) with bounding-box deviation > 5 m (hardcoded)",
        ))

    # Note ID columns used for Step 3
    _s3_src = s.get("step3_src_id_col")
    _s3_mds = s.get("step3_mds_id_col")
    if _cr.get("buffer", True):
        if _s3_src and _s3_mds:
            _id_note = (
                f"Source.{_s3_src} ↔ MDS.{_s3_mds}"
                if _s3_src != _s3_mds
                else f"Matched by: {_s3_src}"
            )
        else:
            _id_note = "⚠ No common ID column found — Step 3 was skipped"
        _report_rows.append(("  Step 3 ID columns used", "", _id_note))

    # Note skipped checks
    _label_map = {
        "spike": "Spike Detection", "sliver": "Sliver Detection",
        "buffer": "Failed Geometry", "multipart": "Multipart Check",
        "poly_quality": "Polygon Quality Check",
    }
    _skipped = [_label_map[k] for k, v in _cr.items() if not v]
    if _skipped:
        _report_rows.append((
            "Checks skipped (not run)", ", ".join(_skipped), "Output layers omitted",
        ))

    report_df = pd.DataFrame(_report_rows, columns=["Check", "Count", "Threshold / Notes"])
    st.dataframe(report_df, use_container_width=True, hide_index=True)

    # ── Metric cards (only enabled checks) ──────────────────────────────────
    _metrics = []
    if _cr.get("spike", True):
        _metrics.append(("Spike Vertices",    s["spike_count"],                       None))
    if _cr.get("sliver", True):
        _metrics.append(("Sliver Polygons",   s["sliver_count"],                      None))
    if _cr.get("buffer", True):
        if include_lt1m:
            _metrics.append(("Geo Failed <1m", s["geom_lt1_count"],                   None))
        _metrics.append((f"Geo Failed 1-{_t}m", s["geom_lt_buf_count"],               None))
        _metrics.append((f"Geo Failed >{_t}m",  s["geom_gt_buf_count"],               None))
    if _cr.get("multipart", True):
        _metrics.append(("MP Extra in MDS",  s.get("multipart_extra_count", 0),
                          "MDS parts with no matching Source part"))
    if _cr.get("poly_quality", True):
        _metrics.append(("Polygon QC Errors", s["poly_quality_count"],                None))

    if _metrics:
        _mcols = st.columns(len(_metrics))
        for _col, (_label, _val, _help) in zip(_mcols, _metrics):
            if _help:
                _col.metric(_label, _val, help=_help)
            else:
                _col.metric(_label, _val)

    # ── Download + saved paths ───────────────────────────────────────────────
    dl_col, info_col = st.columns([1, 3])
    with dl_col:
        if st.session_state.get("excel_bytes"):
            st.download_button(
                label="Download Excel Report",
                data=st.session_state["excel_bytes"],
                file_name=st.session_state["excel_name"],
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
            )
    with info_col:
        for path_msg in st.session_state.get("saved_paths", []):
            st.info(f"Saved — {path_msg}")

    st.divider()

    # ── Tabs (only enabled checks) ────────────────────────────────────────
    def _show(df, key, caption):
        st.caption(caption)
        if df is None or len(df) == 0:
            st.success("No issues found.")
            return
        display_df = df.drop(columns=["geometry"], errors="ignore")
        search = st.text_input("Filter rows...", key=f"s_{key}", placeholder="Type to filter...")
        if search:
            mask = display_df.apply(
                lambda col: col.astype(str).str.contains(search, case=False, na=False)
            ).any(axis=1)
            display_df = display_df[mask]
        st.dataframe(display_df, use_container_width=True, height=3