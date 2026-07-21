"""
Core logic for Orbis Postal Area Source Preparation Checks.

Check 1: Deleted Entity ID Validation
──────────────────────────────────────
The identifier column in real source-prep deliveries is named ``Feature_Id``
(not ``Entity ID`` / ``entity_id`` — confirmed against actual delivery files;
"Entity ID" is only the business name for what that column holds).

Rule
1. A feature with Action_Flag = 'D' (Deletion) must not share its Feature_Id
   with any other feature carrying Action_Flag = 'U0' (Geometry Update),
   'U1' (Attribute Update), or 'U2' (Attribute + Geometry Update) — an
   entity cannot be both deleted and updated in the same delivery.
2. Checked across the entire source: every layer, attribute table, and
   name table, not just the polygon layer.

Note: source-prep deliveries carry no separate "Orbis ID" column — the
Feature_Id *is* the Orbis feature identifier in this context (it's called
Feature_Id because it's the tracking ID during source prep, before the
feature is committed to the Orbis database). There is nothing to
cross-reference it against within the source alone, so no such sub-check
is implemented here.

Check 2: Action Flag 'C' — Dummy UUID/Feature_Id Validation
─────────────────────────────────────────────────────────────
Every newly-created feature (Action_Flag = 'C', "Genesis") must carry a
placeholder ("dummy") UUID in the Feature_Id column, across all layers
including Postal Area main postal point records. Confirmed against real
deliveries, the Orbis dummy-UUID format is::

    00000000-0000-0000-0000-<12 digits>      (36 characters total)

e.g. ``00000000-0000-0000-0000-300040000006``. Reports rows where the
value is missing, not exactly 36 characters, and/or does not match that
format.

Check 3: Action Flag Consistency Validation
─────────────────────────────────────────────
For each Feature_Id, the Action_Flag must be identical across every
geometry layer, attribute table, and name table it appears in — e.g. a
feature that is 'U2' in the geometry layer cannot be 'U1' in an attribute
table for the same Feature_Id. Reports every Feature_Id (and its
contributing rows) where more than one distinct Action_Flag is found.

Check 4: Duplicate Feature_Id Validation
─────────────────────────────────────────
Each layer is scanned independently for Feature_Ids that appear more than
once. Confirmed against real deliveries: attribute tables (e.g.
``Postal_Attribute``) legitimately repeat the same Feature_Id — one row
per attribute key/value pair — so that is a business-permitted duplicate,
not a defect, and is excluded from flagging by default (layer names
containing "attribute"). Single-occurrence layers such as ``Postal_Point``
or ``Postal_Area`` should never repeat a Feature_Id; any repeat there is a
genuine error. The set of excluded layers is user-configurable.

Check 5: Vertex Spacing Validation
─────────────────────────────────────
Adapted from ``OrbisAreaVertex05m_Cleaner_V4_1.py``. Flags consecutive
vertices of a polygon ring whose real-world distance (computed via an
auto-selected local UTM projection, so the tolerance is always in true
meters regardless of input CRS) falls between a noise floor (1cm) and a
tolerance (default 0.5m) — near-duplicate/overly dense vertices. Unlike
the source script this is a pure validator — it never rewrites geometry.

Optionally, findings can be filtered against a VAD GeoPackage (same
naming convention as the VAD used elsewhere:
``<CC>_postal_layer_<LayerId>_revision_<RevisionId>.gpkg``) — findings
within 0.3m of an existing VAD boundary are treated as false positives
(pre-existing/approved geometry, not a new defect) and dropped, matching
the original script's behavior.

Check 6: Spike Angle Validation
───────────────────────────────
Adapted from ``spike_error_POSTAL 1.py``. Flags a vertex whose interior
angle is sharper than a threshold (default 15°) — a spike/needle
artifact. The source script actually removes spikes from the geometry;
here it is report-only, consistent with every other check in this tool.

Check 7: Self-Intersecting Polygon
─────────────────────────────────────
Adapted from ``Self_Intersecting_Polygon.py``. Every layer with polygon
geometry is scanned; a feature invalid specifically due to self-
intersection (checked via ``shapely.validation.explain_validity``) is
flagged, and the exact XY location of each self-intersection point is
computed by testing every pair of non-adjacent ring segments for
intersection.

Check 8: Layer Schema Validation
─────────────────────────────────────
Adapted from ``Orbis_AA_Check_LayerName_Field_Feat_Type 1.py``. Every
layer in the source is matched against the known Orbis layer definitions
(Postal_Area / Postal_Point / Postal_Attribute) and checked for: an
unrecognized layer name, missing expected fields, a geometry type that
doesn't match what's expected for that layer, and (where applicable)
Feature_Type values outside the expected set.

Check 9: Output Template Validation
─────────────────────────────────────
Adapted from ``Py_Script_Orbis_PD_Output_Template_Check_V5.py`` — the
"Output Template Check" tool referenced earlier in this project
(``PostalArea_Py_Script_For_QC``). A large bundle of layer-specific rules
covering all four layers (Postal_Area, Postal_Point, Postal_Attribute,
Postal_Name): field/geometry/Feature_Type conformance (own copy, with
slightly different expected values and an "extra fields" warning — kept
faithful to this script rather than merged with Check 8), null/blank
value scanning, Action_Flag value-set validation per layer, Feature_Id /
Postal_Point_Id length and duplicate rules, Feature_Type↔Attribute_Key
combination rules, postal_point attribute-count rules, and Postal_Name
text-format rules. Note: this script's Feature_Id/Action_Flag
cross-layer consistency check is intentionally **not** re-implemented
here — that logic is identical to Check 3, which already covers it.

Check 10: FID Not Match with VAD
─────────────────────────────────────
Ported from the standalone ``orbis_postal_checks`` tool (business title
from the original FME delivery: "Delete polygon entity ID should not be
present in update layer & that should be unique."). Unlike Checks 1-9,
this one needs a second input — a VAD GeoPackage/GDB (previous accepted
revision, same naming convention as the VAD used in Check 5:
``<CC>_postal_layer_<LayerId>_revision_<RevisionId>.gpkg``).

Rule: every non-Creation (Action_Flag != C) source record must have its
Feature_Id already present in the VAD, and that Feature_Id must be unique
within the source. Records failing either condition are flagged.

Caveat carried over from the original tool: the source FME workspace
(FID_Matchwith_VAD.fmw) is password-protected, so this is a best-effort
reproduction based on observed run logs and behavior, not a byte-for-byte
port of the FME transformer graph. Validate against a known-good FME run
before relying on this operationally.
"""
import io
import math
import os
import re
import tempfile
import zipfile
from typing import Any, Dict, Iterable, List, Optional, Tuple

import geopandas as gpd
import pandas as pd

# ── Shapefile export helpers (Checks 5, 6, 7) ─────────────────────────────
# Excel stays the primary report for every check; these three (the geometry
# checks) additionally support exporting the flagged issues as a shapefile
# so they can be opened directly in GIS software.

def build_point_gdf_from_xy(
    df: pd.DataFrame, x_col: str = "x", y_col: str = "y", crs: str = "EPSG:4326"
) -> gpd.GeoDataFrame:
    """Build a point GeoDataFrame from plain x/y (lon/lat) columns in a flagged_df."""
    if df.empty:
        return gpd.GeoDataFrame(df.copy(), geometry=[], crs=crs)
    geometry = gpd.points_from_xy(df[x_col], df[y_col])
    return gpd.GeoDataFrame(df.copy(), geometry=geometry, crs=crs)


def attach_source_polygon_geometry(
    df: pd.DataFrame, source_layers: Dict[str, gpd.GeoDataFrame]
) -> gpd.GeoDataFrame:
    """
    Re-attach each flagged row's original polygon geometry using its
    `source_layer` / `row_index` columns (the flagged_df itself drops
    geometry when it's built). Polygons are normalized to MultiPolygon so
    the shapefile schema stays consistent.
    """
    from shapely.geometry import MultiPolygon

    if df.empty:
        return gpd.GeoDataFrame(df.copy(), geometry=[], crs="EPSG:4326")

    geoms = []
    crs = "EPSG:4326"
    for _, row in df.iterrows():
        gdf = source_layers.get(row["source_layer"])
        geom = None
        if gdf is not None and row["row_index"] in gdf.index:
            geom = gdf.geometry.loc[row["row_index"]]
            if gdf.crs is not None:
                crs = gdf.crs
            if geom is not None and geom.geom_type == "Polygon":
                geom = MultiPolygon([geom])
        geoms.append(geom)
    return gpd.GeoDataFrame(df.copy(), geometry=geoms, crs=crs)


def write_shapefile_zip(gdf: gpd.GeoDataFrame, base_name: str) -> bytes:
    """Write a GeoDataFrame to a temporary shapefile and return its component files zipped."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        shp_path = os.path.join(tmp_dir, f"{base_name}.shp")
        gdf.to_file(shp_path, driver="ESRI Shapefile")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname in os.listdir(tmp_dir):
                zf.write(os.path.join(tmp_dir, fname), arcname=fname)
        return buf.getvalue()


def write_shapefile_to_path(gdf: gpd.GeoDataFrame, output_path: str) -> str:
    """Write a GeoDataFrame directly to a .shp path (creates sibling .shx/.dbf/.prj files)."""
    gdf.to_file(output_path, driver="ESRI Shapefile")
    return output_path


def write_shapefile_into_zip(zf: zipfile.ZipFile, gdf: gpd.GeoDataFrame, base_name: str) -> None:
    """Write a GeoDataFrame's shapefile component files directly into an already-open ZipFile."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        shp_path = os.path.join(tmp_dir, f"{base_name}.shp")
        gdf.to_file(shp_path, driver="ESRI Shapefile")
        for fname in os.listdir(tmp_dir):
            zf.write(os.path.join(tmp_dir, fname), arcname=fname)


# ── Column auto-detection ─────────────────────────────────────────────────

# "Feature_Id" is the confirmed real-world column name; the entity_id/id
# variants are kept as fallbacks for deliveries that might name it differently.
FEATURE_ID_CANDIDATES = [
    "feature_id", "featureid", "feature id",
    "entity_id", "entityid", "entity id",
]
ACTION_FLAG_CANDIDATES = ["action_flag", "actionflag", "action"]

ACTION_FLAG_MEANINGS = {
    "C":  "Creation",
    "D":  "Deletion",
    "U0": "Geometry Update",
    "U1": "Attribute Update",
    "U2": "Attribute + Geometry Update",
    "A":  "Association",
}

DELETE_FLAG = "D"
UPDATE_FLAGS = {"U0", "U1", "U2"}
CREATION_FLAG = "C"

# Orbis dummy-UUID format for newly-created (Action_Flag=C) features:
#   00000000-0000-<4 hex>-0000-<12 hex>   (groups 1, 2, 4 are always literal zero)
# Confirmed against two independent real deliveries, which use different
# numbering conventions for the varying groups:
#   00000000-0000-0000-0000-300040000006   (counter only in the 12-hex group)
#   00000000-0000-0001-0000-000000000001   (counter in the 4-hex group, mirrored/
#                                            zero-padded into the 12-hex group)
DUMMY_UUID_LENGTH = 36
DUMMY_UUID_REGEX = re.compile(r"^00000000-0000-[0-9A-Fa-f]{4}-0000-[0-9A-Fa-f]{12}$")


def detect_column(columns, candidates: List[str]) -> Optional[str]:
    """Case-insensitive match of the first candidate found in columns."""
    lut = {str(c).lower(): c for c in columns}
    for cand in candidates:
        match = lut.get(cand.lower())
        if match is not None:
            return match
    return None


# ── GPKG / GDB helpers ────────────────────────────────────────────────────

def list_layers(path: str) -> List[str]:
    import fiona
    return list(fiona.listlayers(path))


def read_layer(path: str, layer: str) -> gpd.GeoDataFrame:
    return gpd.read_file(path, layer=layer)


# ── Flatten every layer into one long index ───────────────────────────────

def build_feature_index(
    layers: Dict[str, gpd.GeoDataFrame],
    feature_id_override: Optional[str] = None,
    action_flag_override: Optional[str] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Flatten every layer (polygon layers, attribute tables, name tables — any
    table, spatial or not) into one long table of
    (source_layer, row_index, feature_id, action_flag).

    Returns (index_df, per_layer_column_resolution) so the caller can show
    which columns were auto-detected (or not found) per layer.
    """
    rows: List[pd.DataFrame] = []
    resolved: Dict[str, Any] = {}

    for lname, gdf in layers.items():
        try:
            geom_name = gdf.geometry.name
            df = pd.DataFrame(gdf.drop(columns=[geom_name], errors="ignore"))
        except Exception:
            df = pd.DataFrame(gdf)

        feature_col = feature_id_override or detect_column(df.columns, FEATURE_ID_CANDIDATES)
        action_col = action_flag_override or detect_column(df.columns, ACTION_FLAG_CANDIDATES)

        resolved[lname] = {
            "features": len(df),
            "feature_id_column": feature_col,
            "action_flag_column": action_col,
        }

        if feature_col is None:
            continue

        sub = pd.DataFrame({
            "source_layer": lname,
            "row_index": df.index,
            "feature_id": df[feature_col].astype(str).str.strip(),
            "action_flag": (
                df[action_col].astype(str).str.strip().str.upper()
                if action_col else pd.Series([None] * len(df), index=df.index)
            ),
        })
        rows.append(sub)

    index_df = (
        pd.concat(rows, ignore_index=True) if rows
        else pd.DataFrame(columns=["source_layer", "row_index", "feature_id", "action_flag"])
    )
    return index_df, resolved


# ── Check A: Deleted vs Updated Feature_Id conflicts ──────────────────────

def find_deleted_feature_conflicts(index_df: pd.DataFrame) -> pd.DataFrame:
    """
    Feature_Ids that appear with Action_Flag = D in one feature AND with
    Action_Flag in {U0, U1, U2} in another (possibly in a different layer).
    Returns every contributing row (both the D row(s) and the U0/U1/U2
    row(s)) for each conflicting Feature_Id.
    """
    empty = pd.DataFrame(columns=list(index_df.columns) + ["qc_reason"])
    if index_df.empty or index_df["action_flag"].isna().all():
        return empty

    deleted_ids = set(index_df.loc[index_df.action_flag == DELETE_FLAG, "feature_id"])
    updated_ids = set(index_df.loc[index_df.action_flag.isin(UPDATE_FLAGS), "feature_id"])
    conflict_ids = deleted_ids & updated_ids
    if not conflict_ids:
        return empty

    out = index_df[
        index_df.feature_id.isin(conflict_ids)
        & (index_df.action_flag.isin(UPDATE_FLAGS) | (index_df.action_flag == DELETE_FLAG))
    ].copy()
    out["qc_reason"] = "Feature_Id marked Deleted (D) elsewhere also carries an Update flag (U0/U1/U2)"
    return out.sort_values(["feature_id", "action_flag", "source_layer"]).reset_index(drop=True)


# ── Check C: Action Flag consistency across layers/tables ────────────────

def find_action_flag_inconsistencies(index_df: pd.DataFrame) -> pd.DataFrame:
    """
    Feature_Ids whose Action_Flag differs across the layers/tables it
    appears in (e.g. 'U2' in the geometry layer but 'U1' in an attribute
    table for the same Feature_Id). Returns every contributing row for
    each such Feature_Id.
    """
    empty = pd.DataFrame(columns=list(index_df.columns) + ["distinct_action_flags"])
    if index_df.empty or index_df["action_flag"].isna().all():
        return empty

    valid = index_df.dropna(subset=["action_flag"])
    valid = valid[~valid["action_flag"].str.lower().isin(["nan", "none", ""])]
    if valid.empty:
        return empty

    distinct_counts = valid.groupby("feature_id")["action_flag"].nunique()
    inconsistent_ids = distinct_counts[distinct_counts > 1].index

    if len(inconsistent_ids) == 0:
        return empty

    out = valid[valid.feature_id.isin(inconsistent_ids)].copy()
    flag_lists = out.groupby("feature_id")["action_flag"].transform(
        lambda s: ", ".join(sorted(set(s)))
    )
    out["distinct_action_flags"] = flag_lists
    return out.sort_values(["feature_id", "action_flag", "source_layer"]).reset_index(drop=True)


def run_action_flag_consistency_validation(
    layers: Dict[str, gpd.GeoDataFrame],
    feature_id_override: Optional[str] = None,
    action_flag_override: Optional[str] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Check 3. Returns (flagged_df, summary)."""
    index_df, resolved = build_feature_index(layers, feature_id_override, action_flag_override)

    flagged_df = find_action_flag_inconsistencies(index_df)

    skipped_layers = [
        lname for lname, info in resolved.items()
        if info["feature_id_column"] is None or info["action_flag_column"] is None
    ]

    summary = {
        "layers_scanned": list(layers.keys()),
        "layers_skipped_missing_columns": skipped_layers,
        "per_layer": resolved,
        "total_rows_indexed": len(index_df),
        "distinct_feature_ids": index_df["feature_id"].nunique() if not index_df.empty else 0,
        "inconsistent_feature_ids": flagged_df["feature_id"].nunique() if not flagged_df.empty else 0,
        "rows_involved": len(flagged_df),
    }

    return flagged_df, summary


def write_action_flag_consistency_report(flagged_df: pd.DataFrame, output_path: str) -> str:
    """Write Check 3 results to a single-sheet .xlsx report."""
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        flagged_df.to_excel(writer, sheet_name="Action_Flag_Consistency", index=False)
    return output_path


# ── Check 4: Duplicate Feature_Id within a layer ──────────────────────────

# Layers whose name contains one of these (case-insensitive) legitimately
# repeat the same Feature_Id by design (e.g. one row per attribute
# key/value pair) and are excluded from flagging by default.
DEFAULT_MULTI_ROW_LAYER_HINTS = ["attribute"]


def is_multi_row_by_convention(layer_name: str, hints: Optional[List[str]] = None) -> bool:
    hints = DEFAULT_MULTI_ROW_LAYER_HINTS if hints is None else hints
    lname_lower = str(layer_name).lower()
    return any(h.lower() in lname_lower for h in hints)


def find_duplicate_feature_ids(
    layers: Dict[str, gpd.GeoDataFrame],
    feature_id_override: Optional[str] = None,
    excluded_layers: Optional[List[str]] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Check 4: within each layer independently, flag Feature_Ids that appear
    more than once. Layers in ``excluded_layers`` are scanned (their
    duplicate count is still reported) but not flagged as errors — they
    represent business-permitted repeats. If ``excluded_layers`` is None,
    defaults to layers matched by :func:`is_multi_row_by_convention`.
    """
    auto_exclude = excluded_layers is None
    excluded_set = set(excluded_layers) if excluded_layers is not None else set()

    flagged_frames: List[pd.DataFrame] = []
    resolved: Dict[str, Any] = {}
    dup_feature_id_count_per_layer: Dict[str, int] = {}
    excluded_layers_used: List[str] = []

    for lname, gdf in layers.items():
        try:
            geom_name = gdf.geometry.name
            df = pd.DataFrame(gdf.drop(columns=[geom_name], errors="ignore"))
        except Exception:
            df = pd.DataFrame(gdf)

        feature_col = feature_id_override or detect_column(df.columns, FEATURE_ID_CANDIDATES)
        resolved[lname] = {"features": len(df), "feature_id_column": feature_col}

        if feature_col is None:
            continue

        ids = df[feature_col].astype(str).str.strip()
        counts = ids.value_counts()
        dup_ids = counts[counts > 1].index
        dup_feature_id_count_per_layer[lname] = int(len(dup_ids))

        if len(dup_ids) == 0:
            continue

        is_excluded = is_multi_row_by_convention(lname) if auto_exclude else (lname in excluded_set)
        if is_excluded:
            excluded_layers_used.append(lname)
            continue

        dup_mask = ids.isin(dup_ids)
        out = df[dup_mask].copy()
        out.insert(0, "duplicate_count", ids[dup_mask].map(counts).values)
        out.insert(0, "feature_id_value", ids[dup_mask].values)
        out.insert(0, "source_layer", lname)
        flagged_frames.append(out)

    flagged_df = (
        pd.concat(flagged_frames, ignore_index=True, sort=False) if flagged_frames
        else pd.DataFrame(columns=["source_layer", "feature_id_value", "duplicate_count"])
    )
    if not flagged_df.empty:
        flagged_df = flagged_df.sort_values(
            ["source_layer", "feature_id_value"]
        ).reset_index(drop=True)

    skipped_layers = [lname for lname, info in resolved.items() if info["feature_id_column"] is None]

    summary = {
        "layers_scanned": list(layers.keys()),
        "layers_skipped_no_feature_id_column": skipped_layers,
        "per_layer": resolved,
        "duplicate_feature_id_count_per_layer": dup_feature_id_count_per_layer,
        "layers_excluded_from_flagging": excluded_layers_used,
        "total_flagged_rows": len(flagged_df),
        "total_flagged_feature_ids": (
            flagged_df["feature_id_value"].nunique() if not flagged_df.empty else 0
        ),
    }

    return flagged_df, summary


def write_duplicate_feature_id_report(flagged_df: pd.DataFrame, output_path: str) -> str:
    """Write Check 4 results to a single-sheet .xlsx report."""
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        flagged_df.to_excel(writer, sheet_name="Duplicate_Feature_Id", index=False)
    return output_path


# ── Check 2: Action Flag 'C' — Dummy UUID/Feature_Id validation ───────────

def _dummy_uuid_reasons(raw_value: Any) -> List[str]:
    """Return the list of validation failures for one dummy-UUID value."""
    if pd.isna(raw_value):
        return ["Dummy UUID/Feature_Id is missing"]

    s = str(raw_value).strip()
    if s == "" or s.lower() in ("nan", "none"):
        return ["Dummy UUID/Feature_Id is missing"]

    reasons: List[str] = []
    if len(s) != DUMMY_UUID_LENGTH:
        reasons.append(f"Length is {len(s)} characters, expected {DUMMY_UUID_LENGTH}")
    if not DUMMY_UUID_REGEX.match(s):
        reasons.append(
            "Does not follow the Orbis dummy UUID format "
            "(00000000-0000-0000-0000-<12 hex digits>)"
        )
    return reasons


def validate_creation_dummy_uuid(
    layers: Dict[str, gpd.GeoDataFrame],
    feature_id_override: Optional[str] = None,
    action_flag_override: Optional[str] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Check 2: every Action_Flag = 'C' (Creation / Genesis) feature, across
    every layer (polygon, attribute, name, main postal point — anything
    with a detectable Feature_Id + Action_Flag column pair), must carry a
    dummy UUID matching the Orbis format. Returns (flagged_df, summary).
    """
    flagged_frames: List[pd.DataFrame] = []
    resolved: Dict[str, Any] = {}
    creation_counts: Dict[str, int] = {}

    for lname, gdf in layers.items():
        try:
            geom_name = gdf.geometry.name
            df = pd.DataFrame(gdf.drop(columns=[geom_name], errors="ignore"))
        except Exception:
            df = pd.DataFrame(gdf)

        feature_col = feature_id_override or detect_column(df.columns, FEATURE_ID_CANDIDATES)
        action_col = action_flag_override or detect_column(df.columns, ACTION_FLAG_CANDIDATES)

        resolved[lname] = {
            "features": len(df),
            "feature_id_column": feature_col,
            "action_flag_column": action_col,
        }

        if feature_col is None or action_col is None:
            continue

        action_upper = df[action_col].astype(str).str.strip().str.upper()
        creation_mask = action_upper == CREATION_FLAG
        creation_counts[lname] = int(creation_mask.sum())

        if not creation_mask.any():
            continue

        sub = df[creation_mask].copy()
        raw_ids = sub[feature_col]
        reasons_series = raw_ids.apply(_dummy_uuid_reasons)
        flagged_mask = reasons_series.apply(len) > 0

        if not flagged_mask.any():
            continue

        out = sub[flagged_mask].copy()
        out.insert(0, "qc_reason", reasons_series[flagged_mask].apply("; ".join))
        out.insert(0, "feature_id_value", raw_ids[flagged_mask].astype(str))
        out.insert(0, "source_layer", lname)
        flagged_frames.append(out)

    flagged_df = (
        pd.concat(flagged_frames, ignore_index=True, sort=False) if flagged_frames
        else pd.DataFrame(columns=["source_layer", "feature_id_value", "qc_reason"])
    )

    skipped_layers = [
        lname for lname, info in resolved.items()
        if info["feature_id_column"] is None or info["action_flag_column"] is None
    ]

    summary = {
        "layers_scanned": list(layers.keys()),
        "layers_skipped_missing_columns": skipped_layers,
        "per_layer": resolved,
        "creation_rows_per_layer": creation_counts,
        "total_creation_rows_checked": sum(creation_counts.values()),
        "total_flagged": len(flagged_df),
    }

    return flagged_df, summary


def write_dummy_uuid_report(flagged_df: pd.DataFrame, output_path: str) -> str:
    """Write Check 2 results to a single-sheet .xlsx report."""
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        flagged_df.to_excel(writer, sheet_name="Creation_Dummy_UUID_Check", index=False)
    return output_path


# ── Orchestration ─────────────────────────────────────────────────────────

def run_deleted_entity_id_validation(
    layers: Dict[str, gpd.GeoDataFrame],
    feature_id_override: Optional[str] = None,
    action_flag_override: Optional[str] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Check 1. Returns (conflicts_df, summary)."""
    index_df, resolved = build_feature_index(layers, feature_id_override, action_flag_override)

    conflicts_df = find_deleted_feature_conflicts(index_df)

    skipped_layers = [
        lname for lname, info in resolved.items() if info["feature_id_column"] is None
    ]

    summary = {
        "layers_scanned": list(layers.keys()),
        "layers_skipped_no_feature_id_column": skipped_layers,
        "per_layer": resolved,
        "total_rows_indexed": len(index_df),
        "distinct_feature_ids": index_df["feature_id"].nunique() if not index_df.empty else 0,
        "deleted_vs_updated_conflicts": {
            "conflicting_feature_ids": conflicts_df["feature_id"].nunique() if not conflicts_df.empty else 0,
            "rows_involved": len(conflicts_df),
        },
    }

    return conflicts_df, summary


# ── Output ────────────────────────────────────────────────────────────────

def write_report(conflicts_df: pd.DataFrame, output_path: str) -> str:
    """Write Check 1 results to a single-sheet .xlsx report."""
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        conflicts_df.to_excel(writer, sheet_name="Deleted_vs_Updated_ID", index=False)
    return output_path


# ── Check 5: Geometry Validation — Vertex Error ───────────────────────────

VERTEX_MIN_DIST_M = 0.01      # ignore sub-1cm noise (floating point artifacts)
VERTEX_ROUND_DIGITS = 7       # coordinate snap precision
DEFAULT_VERTEX_TOLERANCE_M = 0.5
SPIKE_ANGLE_DEFAULT_DEG = 15  # interior angle sharper than this = spike
VAD_DIST_TOLERANCE_M = 0.3    # VAD false-positive filter radius

_utm_transformer_cache: Dict[Any, Any] = {}


def _get_utm_transformer(lon: float, lat: float):
    from pyproj import Transformer
    zone = int((lon + 180) / 6) + 1
    key = (zone, lat >= 0)
    if key not in _utm_transformer_cache:
        epsg = 32600 + zone if lat >= 0 else 32700 + zone
        _utm_transformer_cache[key] = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    return _utm_transformer_cache[key]


def _segment_length_m(x1: float, y1: float, x2: float, y2: float) -> float:
    t = _get_utm_transformer((x1 + x2) / 2, (y1 + y2) / 2)
    ux1, uy1 = t.transform(x1, y1)
    ux2, uy2 = t.transform(x2, y2)
    return math.hypot(ux2 - ux1, uy2 - uy1)


def _calculate_vertex_angle(p1, p2, p3) -> float:
    """Interior angle (degrees) at p2, formed by p1-p2-p3."""
    v1 = (p1[0] - p2[0], p1[1] - p2[1])
    v2 = (p3[0] - p2[0], p3[1] - p2[1])
    mag1 = math.hypot(*v1)
    mag2 = math.hypot(*v2)
    if mag1 == 0 or mag2 == 0:
        return 180.0
    cosang = (v1[0] * v2[0] + v1[1] * v2[1]) / (mag1 * mag2)
    cosang = max(-1.0, min(1.0, cosang))
    return math.degrees(math.acos(cosang))


def _check_ring_vertex_spacing(coords: List[Tuple[float, float]], tol: float) -> List[Dict[str, Any]]:
    """Flag consecutive-vertex segments shorter than `tol` meters (real-world)."""
    issues = []
    ring = coords[:-1] if len(coords) > 1 and coords[0] == coords[-1] else coords
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        x1, y1 = round(x1, VERTEX_ROUND_DIGITS), round(y1, VERTEX_ROUND_DIGITS)
        x2, y2 = round(x2, VERTEX_ROUND_DIGITS), round(y2, VERTEX_ROUND_DIGITS)
        if (x1, y1) == (x2, y2):
            continue
        d = _segment_length_m(x1, y1, x2, y2)
        if VERTEX_MIN_DIST_M < d < tol:
            issues.append({"vtx_idx": i, "dist_m": round(d, 6), "x": x1, "y": y1})
    return issues


def _check_ring_spike_angles(coords: List[Tuple[float, float]], angle_limit: float) -> List[Dict[str, Any]]:
    """Flag vertices whose interior angle is sharper than `angle_limit` degrees."""
    issues = []
    if len(coords) < 5:
        return issues
    n = len(coords) - 1 if coords[0] == coords[-1] else len(coords)
    for i in range(n):
        prev_pt = coords[i - 1]
        curr_pt = coords[i]
        next_pt = coords[(i + 1) % n]
        angle = _calculate_vertex_angle(prev_pt, curr_pt, next_pt)
        if angle < angle_limit:
            issues.append({"vtx_idx": i, "angle_deg": round(angle, 3), "x": curr_pt[0], "y": curr_pt[1]})
    return issues


def _iter_polygon_rings(geom):
    """Yield (ring_name, coords) for every ring (exterior + interior) of a Polygon/MultiPolygon."""
    if geom is None or geom.is_empty:
        return
    if geom.geom_type == "Polygon":
        yield "ext", list(geom.exterior.coords)
        for i, interior in enumerate(geom.interiors):
            yield f"int{i}", list(interior.coords)
    elif geom.geom_type == "MultiPolygon":
        for pi, poly in enumerate(geom.geoms):
            yield f"ext{pi}", list(poly.exterior.coords)
            for i, interior in enumerate(poly.interiors):
                yield f"int{pi}_{i}", list(interior.coords)


def load_vad_boundaries(vad_layers: Dict[str, gpd.GeoDataFrame]) -> Optional[gpd.GeoDataFrame]:
    """Flatten every polygon layer of a VAD source into one set of boundary lines (EPSG:4326)."""
    all_data = []
    for _lname, gdf in vad_layers.items():
        if gdf.empty:
            continue
        work = gdf[gdf.geom_type.isin(["Polygon", "MultiPolygon"])]
        if work.empty:
            continue
        if work.crs is None:
            work = work.set_crs("EPSG:4326")
        else:
            work = work.to_crs("EPSG:4326")
        work = work.copy()
        work["geometry"] = work.geometry.boundary
        all_data.append(work[["geometry"]])

    if not all_data:
        return None
    return gpd.GeoDataFrame(pd.concat(all_data, ignore_index=True), crs="EPSG:4326")


def filter_vertex_issues_against_vad(
    flagged_df: pd.DataFrame,
    vad_boundaries: Optional[gpd.GeoDataFrame],
    dist_tol_m: float = VAD_DIST_TOLERANCE_M,
) -> Tuple[pd.DataFrame, int]:
    """
    Drop vertex-spacing findings that sit within `dist_tol_m` of an existing
    VAD boundary (pre-existing/approved geometry — not a new defect).
    Returns (filtered_df, removed_count). No-op if vad_boundaries is None or
    flagged_df has no rows.
    """
    if flagged_df.empty or vad_boundaries is None or vad_boundaries.empty:
        return flagged_df, 0

    points = gpd.GeoDataFrame(
        flagged_df,
        geometry=gpd.points_from_xy(flagged_df["x"], flagged_df["y"]),
        crs="EPSG:4326",
    ).to_crs("EPSG:3857")
    vad_m = vad_boundaries.to_crs("EPSG:3857")

    sindex = vad_m.sindex
    mask = [False] * len(points)
    for i, pt in enumerate(points.geometry):
        candidates = list(sindex.intersection(pt.buffer(dist_tol_m).bounds))
        for c in candidates:
            if pt.distance(vad_m.geometry.iloc[c]) <= dist_tol_m:
                mask[i] = True
                break

    removed = sum(mask)
    keep = [not m for m in mask]
    return flagged_df[keep].reset_index(drop=True), removed


def validate_vertex_spacing(
    layers: Dict[str, gpd.GeoDataFrame],
    tolerance_m: float = DEFAULT_VERTEX_TOLERANCE_M,
    vad_boundaries: Optional[gpd.GeoDataFrame] = None,
    vad_dist_tol_m: float = VAD_DIST_TOLERANCE_M,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Check 5 (from OrbisAreaVertex05m_Cleaner_V4_1.py). Flags consecutive-
    vertex segments shorter than `tolerance_m` (real-world meters via
    auto-UTM), longer than a 1cm noise floor. Optionally filtered against
    a VAD to drop pre-existing/approved-boundary false positives. Returns
    (flagged_df, summary); flagged_df has plain x/y columns (WGS84 lon/lat).
    """
    rows: List[Dict[str, Any]] = []
    per_layer: Dict[str, Any] = {}

    for lname, gdf in layers.items():
        polygon_mask = gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
        sub = gdf[polygon_mask]
        per_layer[lname] = {"features": len(gdf), "polygon_features": len(sub)}
        if sub.empty:
            continue

        try:
            work = sub if sub.crs is None else sub.to_crs("EPSG:4326")
        except Exception:
            work = sub

        _utm_transformer_cache.clear()

        for idx, geom in zip(work.index, work.geometry):
            for ring_name, coords in _iter_polygon_rings(geom):
                for iss in _check_ring_vertex_spacing(coords, tolerance_m):
                    rows.append({
                        "source_layer": lname, "row_index": idx, "ring": ring_name,
                        "vtx_idx": iss["vtx_idx"], "dist_m": iss["dist_m"],
                        "x": iss["x"], "y": iss["y"],
                    })

    flagged_df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["source_layer", "row_index", "ring", "vtx_idx", "dist_m", "x", "y"]
    )

    vad_removed = 0
    if vad_boundaries is not None and not flagged_df.empty:
        flagged_df, vad_removed = filter_vertex_issues_against_vad(
            flagged_df, vad_boundaries, vad_dist_tol_m
        )

    summary = {
        "layers_scanned": list(layers.keys()),
        "per_layer": per_layer,
        "tolerance_m": tolerance_m,
        "vad_filtering_applied": vad_boundaries is not None,
        "vad_false_positives_removed": vad_removed,
        "total_flagged": len(flagged_df),
    }

    return flagged_df, summary


def write_vertex_spacing_report(flagged_df: pd.DataFrame, output_path: str) -> str:
    """Write Check 5 results to a single-sheet .xlsx report."""
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        flagged_df.to_excel(writer, sheet_name="Vertex_Spacing", index=False)
    return output_path


# ── Check 6: Spike Angle Validation ───────────────────────────────────────

def validate_spike_angles(
    layers: Dict[str, gpd.GeoDataFrame],
    angle_deg: float = SPIKE_ANGLE_DEFAULT_DEG,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Check 6 (from spike_error_POSTAL 1.py). Flags vertices whose interior
    angle is sharper than `angle_deg`. Unlike the original script this is
    report-only — it never removes the spike from the source geometry.
    Returns (flagged_df, summary); flagged_df has plain x/y columns.
    """
    rows: List[Dict[str, Any]] = []
    per_layer: Dict[str, Any] = {}

    for lname, gdf in layers.items():
        polygon_mask = gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
        sub = gdf[polygon_mask]
        per_layer[lname] = {"features": len(gdf), "polygon_features": len(sub)}
        if sub.empty:
            continue

        for idx, geom in zip(sub.index, sub.geometry):
            for ring_name, coords in _iter_polygon_rings(geom):
                for iss in _check_ring_spike_angles(coords, angle_deg):
                    rows.append({
                        "source_layer": lname, "row_index": idx, "ring": ring_name,
                        "vtx_idx": iss["vtx_idx"], "angle_deg": iss["angle_deg"],
                        "x": iss["x"], "y": iss["y"],
                    })

    flagged_df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["source_layer", "row_index", "ring", "vtx_idx", "angle_deg", "x", "y"]
    )

    summary = {
        "layers_scanned": list(layers.keys()),
        "per_layer": per_layer,
        "angle_deg": angle_deg,
        "total_flagged": len(flagged_df),
    }

    return flagged_df, summary


def write_spike_angle_report(flagged_df: pd.DataFrame, output_path: str) -> str:
    """Write Check 6 results to a single-sheet .xlsx report."""
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        flagged_df.to_excel(writer, sheet_name="Spike_Angle", index=False)
    return output_path


# ── Check 7: Self-Intersecting Polygon ────────────────────────────────────

def _get_self_intersection_points(geom) -> List[Tuple[float, float]]:
    """
    Return exact (x, y) self-intersection locations in a polygon geometry,
    by testing every pair of non-adjacent ring segments for intersection.
    """
    from shapely.geometry import LineString

    if geom is None or geom.is_empty or geom.is_valid:
        return []

    intersection_points: List[Tuple[float, float]] = []

    rings = [ring for _name, ring in _iter_polygon_rings(geom)]

    for coords in rings:
        n = len(coords)
        segments = [LineString([coords[i], coords[i + 1]]) for i in range(n - 1)]

        for i in range(len(segments)):
            for j in range(i + 2, len(segments)):
                if i == 0 and j == len(segments) - 1:
                    continue  # adjacent segments share a point — not a self-intersection
                seg_i, seg_j = segments[i], segments[j]
                if not seg_i.intersects(seg_j):
                    continue
                inter = seg_i.intersection(seg_j)
                if inter.is_empty:
                    continue
                if inter.geom_type == "Point":
                    intersection_points.append((inter.x, inter.y))
                elif inter.geom_type == "MultiPoint":
                    intersection_points.extend((pt.x, pt.y) for pt in inter.geoms)
                elif inter.geom_type == "LineString":
                    intersection_points.extend((c[0], c[1]) for c in inter.coords)

    seen = set()
    unique_points = []
    for x, y in intersection_points:
        key = (round(x, 8), round(y, 8))
        if key not in seen:
            seen.add(key)
            unique_points.append((x, y))
    return unique_points


def find_self_intersecting_polygons(
    layers: Dict[str, gpd.GeoDataFrame],
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """
    Check 6. Scans every layer with polygon geometry for features invalid
    due to self-intersection. Returns (failed_polygons_df,
    intersection_points_df, summary).
    """
    from shapely.validation import explain_validity

    all_failed_rows: List[Dict[str, Any]] = []
    all_point_records: List[Dict[str, Any]] = []
    layer_summary: Dict[str, Any] = {}

    for lname, gdf in layers.items():
        geom_types = gdf.geometry.geom_type.dropna().unique().tolist()
        polygon_types = [t for t in geom_types if "Polygon" in t]
        if not polygon_types:
            layer_summary[lname] = {
                "total": len(gdf), "status": f"Skipped (no polygon geometry: {geom_types})",
            }
            continue

        geom_col = gdf.geometry.name
        failed_rows: List[Dict[str, Any]] = []
        point_records: List[Dict[str, Any]] = []

        for idx, row in gdf.iterrows():
            geom = row[geom_col]
            if geom is None or geom.is_empty or geom.is_valid:
                continue

            reason = explain_validity(geom).lower()
            is_self_intersect = any(
                kw in reason for kw in ["self-intersection", "ring self-intersection", "self intersection"]
            )
            if not is_self_intersect:
                continue

            xy_points = _get_self_intersection_points(geom)

            failed_row = {k: v for k, v in row.items() if k != geom_col}
            failed_row["source_layer"] = lname
            failed_row["row_index"] = idx
            failed_row["issue"] = explain_validity(geom)
            failed_row["intersection_point_count"] = len(xy_points)
            failed_rows.append(failed_row)

            attrs = {k: v for k, v in row.items() if k != geom_col}
            for pt_num, (x, y) in enumerate(xy_points, start=1):
                point_record = dict(attrs)
                point_record["source_layer"] = lname
                point_record["row_index"] = idx
                point_record["pt_num"] = pt_num
                point_record["x_coord"] = round(x, 8)
                point_record["y_coord"] = round(y, 8)
                point_record["issue"] = explain_validity(geom)
                point_records.append(point_record)

        layer_summary[lname] = {
            "total": len(gdf),
            "passed": len(gdf) - len(failed_rows),
            "failed": len(failed_rows),
            "points": len(point_records),
            "status": "OK",
        }
        all_failed_rows.extend(failed_rows)
        all_point_records.extend(point_records)

    failed_df = pd.DataFrame(all_failed_rows) if all_failed_rows else pd.DataFrame(
        columns=["source_layer", "row_index", "issue", "intersection_point_count"]
    )
    points_df = pd.DataFrame(all_point_records) if all_point_records else pd.DataFrame(
        columns=["source_layer", "row_index", "pt_num", "x_coord", "y_coord", "issue"]
    )

    summary = {
        "layers_scanned": list(layers.keys()),
        "per_layer": layer_summary,
        "total_failed_features": len(failed_df),
        "total_intersection_points": len(points_df),
    }

    return failed_df, points_df, summary


def write_self_intersection_report(failed_df: pd.DataFrame, points_df: pd.DataFrame, output_path: str) -> str:
    """Write Check 7 results to a two-sheet .xlsx report."""
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        failed_df.to_excel(writer, sheet_name="Failed_Polygons", index=False)
        points_df.to_excel(writer, sheet_name="Intersection_Points", index=False)
    return output_path


# ── Check 8: Layer Schema Validation ──────────────────────────────────────

LAYER_SCHEMA_DEFS = [
    {
        "layer_names": ["Postal_Area"],
        "expected_fields": [
            "Feature_Id", "Country_Code", "Feature_Type",
            "Boundary", "Postal_Point_Id", "Action_Flag",
        ],
        "expected_geom_type": "MultiPolygon",
        "expected_feat_type": ["Postal area", "postalarea"],
    },
    {
        "layer_names": ["Postal_Point"],
        "expected_fields": ["Feature_Id", "Country_Code", "postal", "Action_Flag"],
        "expected_geom_type": "Point",
        "expected_feat_type": None,
    },
    {
        "layer_names": ["Postal_Attribute"],
        "expected_fields": [
            "Feature_Id", "Country_Code", "Feature_Type",
            "Attribute_Key", "Attribute_Value", "Action_Flag",
        ],
        "expected_geom_type": "Point",
        "expected_feat_type": ["postal_point", "postalarea"],
    },
]


def _fiona_geom_type(source_path: Optional[str], layer: str) -> Optional[str]:
    """Return the layer-declared geometry type via fiona, or None if unavailable."""
    if not source_path:
        return None
    try:
        import fiona
        with fiona.open(source_path, layer=layer) as src:
            return src.schema["geometry"]
    except Exception:
        return None


def _layer_columns(gdf: gpd.GeoDataFrame) -> List[str]:
    try:
        return list(pd.DataFrame(gdf.drop(columns=[gdf.geometry.name], errors="ignore")).columns)
    except Exception:
        return list(pd.DataFrame(gdf).columns)


def validate_layer_schema(
    layers: Dict[str, gpd.GeoDataFrame],
    source_path: Optional[str] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Check 8. Matches each layer against LAYER_SCHEMA_DEFS and flags an
    unrecognized layer name, missing expected fields, a geometry-type
    mismatch, and (where defined) unexpected Feature_Type values.
    `source_path` is optional — if given, the declared layer geometry type
    is read via fiona (matching the original script exactly); otherwise
    it's approximated from the loaded GeoDataFrame's observed geom types.
    """
    rows: List[Dict[str, Any]] = []
    per_layer: Dict[str, Any] = {}

    for lname, gdf in layers.items():
        matched_def = next((d for d in LAYER_SCHEMA_DEFS if lname in d["layer_names"]), None)

        if matched_def is None:
            rows.append({
                "source_layer": lname, "severity": "ERROR", "rule": "Unknown layer",
                "message": f"Layer Name '{lname}' does not match any of the expected layers.",
            })
            per_layer[lname] = {"matched": False}
            continue

        per_layer[lname] = {"matched": True}
        cols = _layer_columns(gdf)

        for field in matched_def["expected_fields"]:
            if field not in cols:
                rows.append({
                    "source_layer": lname, "severity": "ERROR", "rule": "Missing field",
                    "message": f"Field Name '{field}' is missing in layer '{lname}'.",
                })

        geom_type = _fiona_geom_type(source_path, lname)
        if geom_type is None:
            observed = gdf.geometry.geom_type.dropna().unique().tolist()
            geom_type = observed[0] if len(observed) == 1 else ("/".join(observed) if observed else "Unknown")
        if geom_type != matched_def["expected_geom_type"]:
            rows.append({
                "source_layer": lname, "severity": "ERROR", "rule": "Geometry type",
                "message": (
                    f"Incorrect geometry type for layer '{lname}'. "
                    f"Expected '{matched_def['expected_geom_type']}', got '{geom_type}'."
                ),
            })

        expected_feat_type = matched_def.get("expected_feat_type")
        if expected_feat_type and "Feature_Type" in cols:
            unique_feat_types = gdf["Feature_Type"].dropna().unique().tolist()
            mismatched = [t for t in unique_feat_types if t not in expected_feat_type]
            if mismatched:
                rows.append({
                    "source_layer": lname, "severity": "ERROR", "rule": "Feature_Type",
                    "message": f"Layer '{lname}' contains unexpected 'Feature_Type' values: {mismatched}.",
                })

    flagged_df = (
        pd.DataFrame(rows) if rows
        else pd.DataFrame(columns=["source_layer", "severity", "rule", "message"])
    )

    summary = {
        "layers_scanned": list(layers.keys()),
        "per_layer": per_layer,
        "total_flagged": len(flagged_df),
    }
    return flagged_df, summary


def write_layer_schema_report(flagged_df: pd.DataFrame, output_path: str) -> str:
    """Write Check 8 results to a single-sheet .xlsx report."""
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        flagged_df.to_excel(writer, sheet_name="Layer_Schema", index=False)
    return output_path


# ── Check 9: Output Template Validation ───────────────────────────────────

OUTPUT_TEMPLATE_LAYER_CONFIGS = [
    {
        "layer_names": ["Postal_Area"],
        "expected_fields": [
            "Feature_Id", "Country_Code", "Feature_Type",
            "Boundary", "Postal_Point_Id", "Action_Flag",
        ],
        "expected_geom_type": "MultiPolygon",
        "expected_feat_type": ["postalarea"],
    },
    {
        "layer_names": ["Postal_Point"],
        "expected_fields": ["Feature_Id", "Country_Code", "postal", "Action_Flag"],
        "expected_geom_type": "Point",
        "expected_feat_type": None,
    },
    {
        "layer_names": ["Postal_Attribute"],
        "expected_fields": [
            "Feature_Id", "Country_Code", "Feature_Type",
            "Attribute_Key", "Attribute_Value", "Action_Flag",
        ],
        "expected_geom_type": "Point",
        "expected_feat_type": ["postal_point", "postalarea"],
    },
    {
        "layer_names": ["Postal_Name"],
        "expected_fields": [
            "Feature_Id", "Name_Type", "Primary_Name", "Name_text",
            "Language_code", "ISO_Script", "Action_Flag",
        ],
        "expected_geom_type": "Point",
        "expected_feat_type": ["Standard_Name"],
    },
]

_NAME_TEXT_VALID_PATTERN = re.compile(r"^[A-Za-z0-9\s\-'\._]+$")


def _row(layer: str, severity: str, rule: str, message: str) -> Dict[str, Any]:
    return {"source_layer": layer, "severity": severity, "rule": rule, "message": message}


def _ot_check_fields(layer: str, cols: List[str], expected_fields: List[str]) -> List[Dict[str, Any]]:
    rows = []
    missing = [f for f in expected_fields if f not in cols]
    extra = [f for f in cols if f not in expected_fields]
    for field in missing:
        rows.append(_row(layer, "ERROR", "Missing field", f"Field Name '{field}' is missing in layer {layer}."))
    if extra:
        rows.append(_row(layer, "WARNING", "Extra field",
                          f"Layer '{layer}' contains extra fields: {', '.join(extra)}."))
    return rows


def _ot_check_geometry(layer: str, geom_type: Optional[str], expected_geom_type: str) -> List[Dict[str, Any]]:
    if geom_type is not None and geom_type != expected_geom_type:
        return [_row(layer, "ERROR", "Geometry type",
                      f"Incorrect geometry type for layer '{layer}'. Expected '{expected_geom_type}', got {geom_type}.")]
    return []


def _ot_check_feature_types(layer: str, df: pd.DataFrame, expected_feat_types) -> List[Dict[str, Any]]:
    rows = []
    if "Feature_Type" in df.columns and expected_feat_types:
        invalid_types = [t for t in df["Feature_Type"].dropna().unique() if t not in expected_feat_types]
        if invalid_types:
            rows.append(_row(layer, "ERROR", "Feature_Type",
                              f"Layer '{layer}' has invalid 'Feature_Type' values: {', '.join(map(str, invalid_types))}."))
    return rows


def _ot_check_null_or_blank(layer: str, df: pd.DataFrame) -> List[Dict[str, Any]]:
    rows = []
    for column in df.columns:
        if df[column].dtype != "object":
            continue
        try:
            null_values = df[column].isnull()
            invisible_values = df[column].notnull() & (df[column].astype(str).str.strip() == "")
            invalid_rows = df.index[null_values | invisible_values].tolist()
        except Exception:
            continue
        if invalid_rows:
            limited = invalid_rows[:100]
            rows.append(_row(
                layer, "ERROR", "Null/blank value",
                f"Layer '{layer}' has null or no visible value in column '{column}' "
                f"for rows (1st 100 errors) id+1: {limited}.",
            ))
    return rows


def _ot_check_postal_area(layer: str, df: pd.DataFrame) -> List[Dict[str, Any]]:
    rows = []

    if "Action_Flag" in df.columns:
        invalid_flags = df.loc[~df["Action_Flag"].isin(["U0", "U2", "C", "D"]), "Action_Flag"].dropna().unique()
        if invalid_flags.size > 0:
            rows.append(_row(layer, "ERROR", "Action_Flag",
                              f"Layer '{layer}' contains unexpected 'Action_Flag' values: {', '.join(map(str, invalid_flags))}."))

    if "Feature_Id" in df.columns and "Postal_Point_Id" in df.columns:
        duplicate_features = df[df.duplicated(subset=["Feature_Id"], keep=False)]
        if not duplicate_features.empty:
            rows.append(_row(layer, "ERROR", "Duplicate Feature_Id",
                              f"Duplicate Feature_Id values found in {layer} layer: "
                              f"{duplicate_features['Feature_Id'].astype(str).tolist()}"))

        matched_ids = df[df["Feature_Id"].astype(str).str.strip().isin(
            df["Postal_Point_Id"].astype(str).str.strip()
        )]
        if not matched_ids.empty:
            rows.append(_row(layer, "ERROR", "Feature_Id/Postal_Point_Id collision",
                              f"Feature_Id values match Postal_Point_Id in {layer} layer: "
                              + matched_ids[["Feature_Id", "Postal_Point_Id"]].astype(str).to_string(index=False)))

    if "Boundary" in df.columns and not (df["Boundary"] == "postal_code").all():
        rows.append(_row(layer, "ERROR", "Boundary",
                          f"Layer '{layer}' has 'Boundary' values not equal to 'postal_code'."))

    if "Feature_Id" in df.columns:
        try:
            if df["Feature_Id"].astype(str).str.len().le(30).any():
                rows.append(_row(layer, "ERROR", "Feature_Id length",
                                  f"Layer '{layer}' contains 'Feature_Id' values with length <= 30."))
        except Exception:
            pass
        if df["Feature_Id"].duplicated().any():
            duplicates = df[df["Feature_Id"].duplicated()]["Feature_Id"].astype(str).tolist()
            rows.append(_row(layer, "ERROR", "Duplicate Feature_Id",
                              f"Layer '{layer}' contains duplicate 'Feature_Id' values: {duplicates}."))

    if "Postal_Point_Id" in df.columns and "Action_Flag" in df.columns:
        filtered_df = df[df["Action_Flag"] != "D"]
        try:
            if filtered_df["Postal_Point_Id"].astype(str).str.len().le(30).any():
                rows.append(_row(layer, "ERROR", "Postal_Point_Id length",
                                  f"Layer '{layer}' contains 'Postal_Point_Id' with length <= 30 (excluding 'Action_Flag' D)."))
        except Exception:
            pass
        if filtered_df["Postal_Point_Id"].duplicated().any():
            duplicates = filtered_df[filtered_df["Postal_Point_Id"].duplicated()]["Postal_Point_Id"].astype(str).tolist()
            rows.append(_row(layer, "ERROR", "Duplicate Postal_Point_Id",
                              f"Layer '{layer}' contains duplicate 'Postal_Point_Id' values "
                              f"(excluding 'Action_Flag' D): {duplicates}."))

    return rows


def _ot_check_postal_point(layer: str, df: pd.DataFrame) -> List[Dict[str, Any]]:
    rows = []

    if "Action_Flag" in df.columns:
        invalid_flags = df.loc[~df["Action_Flag"].isin(["U0", "U2", "C", "D"]), "Action_Flag"].dropna().unique()
        if invalid_flags.size > 0:
            rows.append(_row(layer, "ERROR", "Action_Flag",
                              f"Layer '{layer}' contains unexpected 'Action_Flag' values: {', '.join(map(str, invalid_flags))}."))

    if "postal" in df.columns and not df["postal"].isin(["main", "detailed"]).all():
        rows.append(_row(layer, "ERROR", "postal",
                          f"Layer '{layer}' has 'postal' values other than 'main' or 'detailed'."))

    if "Feature_Id" in df.columns:
        try:
            if df["Feature_Id"].astype(str).str.len().le(30).any():
                rows.append(_row(layer, "ERROR", "Feature_Id length",
                                  f"Layer '{layer}' contains 'Feature_Id' values with length <= 30."))
        except Exception:
            pass
        if df["Feature_Id"].duplicated().any():
            duplicates = df[df["Feature_Id"].duplicated()]["Feature_Id"].astype(str).tolist()
            rows.append(_row(layer, "ERROR", "Duplicate Feature_Id",
                              f"Layer '{layer}' contains duplicate Feature_Id values: {duplicates}."))

    return rows


def _ot_check_postal_attribute(layer: str, df: pd.DataFrame) -> List[Dict[str, Any]]:
    rows = []

    if "Action_Flag" in df.columns:
        invalid_flags = df.loc[~df["Action_Flag"].isin(["C", "U1", "U2"]), "Action_Flag"].dropna().unique()
        if invalid_flags.size > 0:
            rows.append(_row(layer, "ERROR", "Action_Flag",
                              f"Layer '{layer}' contains unexpected 'Action_Flag' values: {', '.join(map(str, invalid_flags))}."))

    if "Feature_Type" in df.columns and "Attribute_Key" in df.columns:
        invalid_rows = df[
            ~(
                ((df["Feature_Type"] == "postal_point")
                 & df["Attribute_Key"].isin(["postal_code", "postal_code_main", "postal_code_sub"]))
                | ((df["Feature_Type"] == "postalarea") & (df["Attribute_Key"] == "postal_code"))
            )
        ]
        if not invalid_rows.empty:
            rows.append(_row(layer, "ERROR", "Feature_Type/Attribute_Key",
                              f"Layer '{layer}' contains mismatched 'Feature_Type' and 'Attribute_Key' values: "
                              + invalid_rows[["Feature_Type", "Attribute_Key"]].astype(str).to_string(index=False)))

    if "Feature_Type" in df.columns and "Feature_Id" in df.columns:
        postal_point_df = df[df["Feature_Type"] == "postal_point"]
        feature_id_counts = postal_point_df["Feature_Id"].value_counts()
        invalid_feature_ids = feature_id_counts[feature_id_counts < 2].index.tolist()
        if invalid_feature_ids:
            rows.append(_row(layer, "ERROR", "postal_point occurrence count",
                              f"Layer '{layer}' contains 'postal_point' Feature_Id(s) with fewer than 2 records: {invalid_feature_ids}."))

    if "Feature_Type" in df.columns and "Feature_Id" in df.columns and "Attribute_Key" in df.columns:
        postal_point_df = df[df["Feature_Type"] == "postal_point"]

        sub_code_ids = postal_point_df.loc[
            postal_point_df["Attribute_Key"] == "postal_code_sub", "Feature_Id"
        ].unique()
        invalid_sub_code_ids = [
            fid for fid in sub_code_ids
            if postal_point_df[postal_point_df["Feature_Id"] == fid].shape[0] != 3
        ]
        if invalid_sub_code_ids:
            rows.append(_row(layer, "ERROR", "postal_code_sub occurrence count",
                              f"Layer '{layer}' contains 'postal_point' Feature_Id(s) with 'postal_code_sub' "
                              f"that do not have exactly 3 records: {invalid_sub_code_ids}."))

        other_code_df = postal_point_df[postal_point_df["Attribute_Key"] != "postal_code_sub"]
        other_code_counts = other_code_df["Feature_Id"].value_counts()
        invalid_other_code_ids = other_code_counts[other_code_counts != 2].index.tolist()
        if invalid_other_code_ids:
            rows.append(_row(layer, "ERROR", "Non-sub occurrence count",
                              f"Layer '{layer}' contains 'postal_point' Feature_Id(s) with Attribute_Key not "
                              f"'postal_code_sub' that do not have exactly 2 records: {invalid_other_code_ids}."))

    return rows


def _ot_check_postal_name(layer: str, df: pd.DataFrame) -> List[Dict[str, Any]]:
    rows = []

    if "Action_Flag" in df.columns:
        invalid_flags = df.loc[~df["Action_Flag"].isin(["C", "U1", "U2"]), "Action_Flag"].dropna().unique()
        if invalid_flags.size > 0:
            rows.append(_row(layer, "ERROR", "Action_Flag",
                              f"Layer '{layer}' contains unexpected 'Action_Flag' values: {', '.join(map(str, invalid_flags))}."))

    if {"Name_Type", "Primary_Name", "Name_text"}.issubset(df.columns):
        name_text = df["Name_text"].astype(str)
        invalid_rows = df.loc[
            (df["Name_Type"] != "Standard_Name")
            | (~df["Primary_Name"].isin(["TRUE", "FALSE"]))
            | (name_text.str.strip() != name_text)
            | (name_text.str.contains(r"\s{2,}"))
        ]
        if not invalid_rows.empty:
            rows.append(_row(layer, "ERROR", "Name_Type/Primary_Name/Name_text",
                              f"Layer '{layer}' contains invalid rows based on 'Name_Type', 'Primary_Name', "
                              f"or 'Name_Text' checks. Rows id +1: {invalid_rows.index.tolist()}."))

        invalid_chars_rows = df.loc[~name_text.str.match(_NAME_TEXT_VALID_PATTERN)]
        if not invalid_chars_rows.empty:
            bad_values = invalid_chars_rows["Name_text"].tolist()
            rows.append(_row(layer, "ERROR", "Name_text characters",
                              f"Layer '{layer}' contains 'Name_text' values with invalid characters: {bad_values}."))

    return rows


_OT_LAYER_SPECIFIC = {
    "Postal_Area": _ot_check_postal_area,
    "Postal_Point": _ot_check_postal_point,
    "Postal_Attribute": _ot_check_postal_attribute,
    "Postal_Name": _ot_check_postal_name,
}


def validate_output_template(
    layers: Dict[str, gpd.GeoDataFrame],
    source_path: Optional[str] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Check 9 (from Py_Script_Orbis_PD_Output_Template_Check_V5.py). Runs the
    full "Output Template Check" rule set — field/geometry/Feature_Type
    conformance, null/blank value scanning, per-layer Action_Flag value
    sets, ID length/duplicate rules, Feature_Type<->Attribute_Key rules,
    postal_point occurrence-count rules, and Postal_Name text-format rules
    — across whichever of Postal_Area / Postal_Point / Postal_Attribute /
    Postal_Name layers are present. Returns (flagged_df, summary).
    """
    rows: List[Dict[str, Any]] = []
    per_layer: Dict[str, Any] = {}

    for config in OUTPUT_TEMPLATE_LAYER_CONFIGS:
        for lname in config["layer_names"]:
            if lname not in layers:
                per_layer[lname] = {"present": False}
                continue

            gdf = layers[lname]
            df = pd.DataFrame(gdf) if not hasattr(gdf, "geometry") else pd.DataFrame(
                gdf.drop(columns=[gdf.geometry.name], errors="ignore")
            )
            cols = list(df.columns)
            per_layer[lname] = {"present": True, "features": len(df)}

            rows.extend(_ot_check_fields(lname, cols, config["expected_fields"]))

            geom_type = _fiona_geom_type(source_path, lname)
            if geom_type is None and hasattr(gdf, "geometry"):
                observed = gdf.geometry.geom_type.dropna().unique().tolist()
                geom_type = observed[0] if len(observed) == 1 else (
                    "/".join(observed) if observed else None
                )
            rows.extend(_ot_check_geometry(lname, geom_type, config["expected_geom_type"]))

            rows.extend(_ot_check_feature_types(lname, df, config.get("expected_feat_type")))
            rows.extend(_ot_check_null_or_blank(lname, df))

            specific = _OT_LAYER_SPECIFIC.get(lname)
            if specific is not None:
                try:
                    rows.extend(specific(lname, df))
                except Exception as exc:
                    rows.append(_row(lname, "ERROR", "Check failed",
                                      f"Layer-specific validation raised an error: {exc}"))

    flagged_df = (
        pd.DataFrame(rows) if rows
        else pd.DataFrame(columns=["source_layer", "severity", "rule", "message"])
    )

    summary = {
        "layers_present": [l for l, info in per_layer.items() if info.get("present")],
        "layers_missing": [l for l, info in per_layer.items() if not info.get("present")],
        "per_layer": per_layer,
        "total_flagged": len(flagged_df),
        "errors": int((flagged_df["severity"] == "ERROR").sum()) if not flagged_df.empty else 0,
        "warnings": int((flagged_df["severity"] == "WARNING").sum()) if not flagged_df.empty else 0,
    }
    return flagged_df, summary


def write_output_template_report(flagged_df: pd.DataFrame, output_path: str) -> str:
    """Write Check 9 results to a single-sheet .xlsx report."""
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        flagged_df.to_excel(writer, sheet_name="Output_Template_Check", index=False)
    return output_path


# ── Check 10: FID Not Match with VAD ──────────────────────────────────────

# VAD files use "orbis_id" (not Feature_Id) as their identifier column,
# so the VAD side needs its own broader candidate list.
VAD_ID_CANDIDATES = FEATURE_ID_CANDIDATES + ["orbis_id", "orbisid", "orbis id", "fid", "id"]


def build_vad_id_pool(
    vad_layers: Dict[str, gpd.GeoDataFrame],
    vad_id_override: Optional[str] = None,
) -> Tuple[set, Dict[str, Optional[str]]]:
    """Pool every ID value found across the selected VAD layers into one set."""
    id_pool: set = set()
    resolved_cols: Dict[str, Optional[str]] = {}

    for lname, gdf in vad_layers.items():
        col = vad_id_override or detect_column(gdf.columns, VAD_ID_CANDIDATES)
        resolved_cols[lname] = col
        if col is None:
            continue
        values = gdf[col].dropna().astype(str).str.strip()
        id_pool.update(values.tolist())

    return id_pool, resolved_cols


def analyze_fid_not_match_with_vad(
    source_layers: Dict[str, gpd.GeoDataFrame],
    vad_layers: Dict[str, gpd.GeoDataFrame],
    excluded_action_flags: Iterable[str] = ("C",),
    feature_id_override: Optional[str] = None,
    action_flag_override: Optional[str] = None,
    vad_id_override: Optional[str] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Check 10. Every non-Creation (Action_Flag != C) source record must
    have its Feature_Id already present in the VAD, and that Feature_Id
    must be unique within the source. Returns (flagged_df, summary).
    """
    excluded_upper = {str(f).strip().upper() for f in excluded_action_flags}
    vad_id_pool, vad_resolved_cols = build_vad_id_pool(vad_layers, vad_id_override)

    flagged_frames: List[pd.DataFrame] = []
    layer_summaries: Dict[str, Any] = {}
    skipped_layers: List[str] = []

    for lname, gdf in source_layers.items():
        feature_col = feature_id_override or detect_column(gdf.columns, FEATURE_ID_CANDIDATES)
        action_col = action_flag_override or detect_column(gdf.columns, ACTION_FLAG_CANDIDATES)

        if feature_col is None:
            skipped_layers.append(lname)
            layer_summaries[lname] = {
                "checked": 0, "flagged": 0,
                "reason": f"No Feature_Id column found (tried: {FEATURE_ID_CANDIDATES})",
            }
            continue

        try:
            df = pd.DataFrame(gdf.drop(columns=[gdf.geometry.name], errors="ignore"))
        except Exception:
            df = pd.DataFrame(gdf)

        if action_col is not None:
            flags = df[action_col].astype(str).str.strip().str.upper()
            in_scope = ~flags.isin(excluded_upper)
        else:
            in_scope = pd.Series(True, index=df.index)

        scoped = df[in_scope].copy()
        if scoped.empty:
            layer_summaries[lname] = {
                "checked": 0, "flagged": 0,
                "feature_id_column": feature_col, "action_flag_column": action_col,
            }
            continue

        id_values = scoped[feature_col].astype(str).str.strip()
        not_in_vad = ~id_values.isin(vad_id_pool)
        duplicated = id_values.duplicated(keep=False)

        violation = not_in_vad | duplicated
        n_checked = len(scoped)
        n_flagged = int(violation.sum())

        layer_summaries[lname] = {
            "checked": n_checked,
            "flagged": n_flagged,
            "feature_id_column": feature_col,
            "action_flag_column": action_col,
            "not_in_vad": int(not_in_vad.sum()),
            "duplicate_in_source": int(duplicated.sum()),
        }

        if n_flagged == 0:
            continue

        reasons = []
        for is_missing, is_dup in zip(not_in_vad[violation], duplicated[violation]):
            parts = []
            if is_missing:
                parts.append("Feature_Id not found in VAD")
            if is_dup:
                parts.append("Duplicate Feature_Id in source")
            reasons.append("; ".join(parts))

        out = scoped[violation].copy()
        out.insert(0, "qc_reason", reasons)
        out.insert(0, "feature_id_value", id_values[violation].values)
        out.insert(0, "source_layer", lname)
        flagged_frames.append(out)

    flagged_df = (
        pd.concat(flagged_frames, ignore_index=True, sort=False) if flagged_frames
        else pd.DataFrame(columns=["source_layer", "feature_id_value", "qc_reason"])
    )

    summary = {
        "excluded_action_flags": sorted(excluded_upper),
        "vad_layers_used": list(vad_layers.keys()),
        "vad_id_column_by_layer": vad_resolved_cols,
        "vad_id_pool_size": len(vad_id_pool),
        "source_layers_skipped_no_feature_id_column": skipped_layers,
        "per_layer": layer_summaries,
        "total_checked": sum(v.get("checked", 0) for v in layer_summaries.values()),
        "total_flagged": len(flagged_df),
    }

    return flagged_df, summary


def write_fid_not_match_with_vad_report(flagged_df: pd.DataFrame, output_path: str) -> str:
    """Write Check 10 results to a single-sheet .xlsx report."""
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        flagged_df.to_excel(writer, sheet_name="FID_Not_Match_with_VAD"[:31], index=False)
    return output_path
