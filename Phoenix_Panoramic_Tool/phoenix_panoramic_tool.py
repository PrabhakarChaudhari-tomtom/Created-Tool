"""
Phoenix Safety Camera Tool + MNR Panoramic Session Data
========================================================
Combines:
  1. Phoenix API camera download (same as original Phoneix_Search_Tool_V1)
  2. MNR PostgreSQL panoramic session lookup
  3. Panoramic session columns stamped on every output row
"""

import requests
import pandas as pd
from urllib.parse import urlencode
from datetime import datetime, timedelta, timezone
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import threading
import psycopg2
import psycopg2.extras

# ─────────────────────────────────────────────
# MNR Database Config
# ─────────────────────────────────────────────
# Panoramix DB — global coverage (all countries including BRA)
# Table: panoramix.sessions   Column: sessionname
DB_CONFIG = {
    "host":     "panoramixdbro.tomtomgroup.com",
    "port":     5432,
    "database": "panoramix",
    "user":     "reader",
    "password": "reader",
    "connect_timeout": 10
}
PANO_TABLE  = "panoramix.sessions"
PANO_COL    = "sessionname"

# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────
API_URL      = "https://phoenix.prod-cambridge.tti.az.tt3.com/modcon/searchCameras"
CAMERA_TYPES = [
    "FIXED_SPEED_CAM", "RED_LIGHT_CAM", "RED_LIGHT_SPEED_CAM",
    "RESTRICTED_AREA_ENTRY", "SPEED_ENFORCEMENT_ZONE",
    "AVERAGE_SPEED_ZONE", "LIKELY_MOBILE_ZONE"
]
KEYWORDS = [
    'variable speed', 'added for test', 'bidi', 'deleted for test',
    'eco zone', 'TBC', 'roadworks/ rework', 'mpl/MP', 'MAP_ADDED',
    'KAE', 'inactive', 'for customers safety', 'Double camera', 'REF25'
]

# Panoramic session columns added to every output
PANO_COLS = ['Panoramic_Session_ID', 'Panoramic_Session_Year_Month',
             'Panoramic_Table', 'Panoramic_Row_Count']

# Global session state
pano_session = {
    "session_id":  "",
    "year_month":  "",
    "table":       "",
    "row_count":   ""
}

# ─────────────────────────────────────────────
# MNR DB helpers
# ─────────────────────────────────────────────
def _db_connect(country_code=None):
    return psycopg2.connect(**DB_CONFIG)


def fetch_all_session_tables():
    """
    Return a list of dicts, one per panoramic/session/moma table:
      { schema, table, columns, row_count, date_col, preview_df }
    """
    conn = _db_connect()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_type = 'BASE TABLE'
          AND table_schema NOT IN ('pg_catalog','information_schema')
          AND (lower(table_name) LIKE '%panoram%'
               OR lower(table_name) LIKE '%session%'
               OR lower(table_name) LIKE '%moma%')
        ORDER BY table_schema, table_name;
    """)
    tables = cur.fetchall()
    result = []

    for t in tables:
        schema, tname = t['table_schema'], t['table_name']
        full = f'"{schema}"."{tname}"'

        cur.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema=%s AND table_name=%s
            ORDER BY ordinal_position;
        """, (schema, tname))
        cols = cur.fetchall()

        try:
            cur.execute(f"SELECT COUNT(*) AS cnt FROM {full};")
            cnt = cur.fetchone()['cnt']
        except Exception:
            conn.rollback(); cnt = 0

        date_col = next(
            (c['column_name'] for c in cols
             if any(k in c['column_name'].lower()
                    for k in ['date','time','created','start','end','modified'])
             and c['data_type'] in (
                 'timestamp with time zone','timestamp without time zone',
                 'date','timestamp'
             )),
            None
        )

        try:
            if date_col:
                cur.execute(f'SELECT * FROM {full} ORDER BY "{date_col}" DESC LIMIT 20;')
            else:
                cur.execute(f'SELECT * FROM {full} LIMIT 20;')
            rows = cur.fetchall()
            df_preview = pd.DataFrame(rows) if rows else pd.DataFrame()
        except Exception:
            conn.rollback(); df_preview = pd.DataFrame()

        result.append({
            "schema":     schema,
            "table":      tname,
            "full":       full,
            "columns":    cols,
            "row_count":  cnt,
            "date_col":   date_col,
            "preview_df": df_preview
        })

    cur.close(); conn.close()
    return result


def fetch_all_db_tables():
    """Return all tables in the DB (schema, name, size)."""
    conn = _db_connect()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT table_schema, table_name,
               pg_size_pretty(pg_total_relation_size(
                   quote_ident(table_schema)||'.'||quote_ident(table_name)
               )) AS size
        FROM information_schema.tables
        WHERE table_type='BASE TABLE'
          AND table_schema NOT IN ('pg_catalog','information_schema')
        ORDER BY table_schema, table_name;
    """)
    rows = cur.fetchall()
    cur.close(); conn.close()
    return rows


# ─────────────────────────────────────────────
# DB Explorer Window
# ─────────────────────────────────────────────
def open_db_explorer():
    win = tk.Toplevel(root)
    win.title("MNR DB Explorer — Panoramic Sessions")
    win.geometry("1000x640")
    win.grab_set()

    # Header bar
    bar = tk.Frame(win, bg="#1A237E"); bar.pack(fill="x")
    tk.Label(bar, text="MNR PostgreSQL  |  Panoramic Session Explorer",
             bg="#1A237E", fg="white", font=("Arial",11,"bold")).pack(side="left", padx=12, pady=7)
    status_var = tk.StringVar(value="Connecting…")
    tk.Label(bar, textvariable=status_var, bg="#1A237E", fg="#FFF176",
             font=("Arial",9)).pack(side="left", padx=10)
    tk.Button(bar, text="↻ Refresh", bg="#0D47A1", fg="white",
              command=lambda: _reload()).pack(side="right", padx=8, pady=4)

    nb = ttk.Notebook(win); nb.pack(fill="both", expand=True, padx=6, pady=6)

    # ── Tab 1: All tables ──
    tab_all = ttk.Frame(nb); nb.add(tab_all, text="All DB Tables")
    fr = tk.Frame(tab_all); fr.pack(fill="both", expand=True)
    vsb1 = tk.Scrollbar(fr, orient="vertical")
    hsb1 = tk.Scrollbar(fr, orient="horizontal")
    tree_all = ttk.Treeview(fr, columns=("Schema","Table","Size"),
                            show="headings", yscrollcommand=vsb1.set, xscrollcommand=hsb1.set)
    vsb1.config(command=tree_all.yview); hsb1.config(command=tree_all.xview)
    vsb1.pack(side="right", fill="y"); hsb1.pack(side="bottom", fill="x")
    tree_all.pack(fill="both", expand=True)
    for c,w in [("Schema",160),("Table",320),("Size",100)]:
        tree_all.heading(c, text=c); tree_all.column(c, width=w)

    # ── Tab 2: Session tables ──
    tab_sess = ttk.Frame(nb); nb.add(tab_sess, text="Panoramic / Session Tables")
    sess_container = tk.Frame(tab_sess); sess_container.pack(fill="both", expand=True)

    def _build_session_tabs(session_tables):
        for w in sess_container.winfo_children():
            w.destroy()

        if not session_tables:
            tk.Label(sess_container,
                     text="No panoramic / session / moma tables found in this DB.",
                     fg="red", font=("Arial",10)).pack(pady=30)
            return

        nb2 = ttk.Notebook(sess_container); nb2.pack(fill="both", expand=True)

        for info in session_tables:
            label = f"{info['table']}  ({info['row_count']} rows)"
            tab   = ttk.Frame(nb2); nb2.add(tab, text=info['table'])

            # Info strip
            hdr = tk.Frame(tab, bg="#E8EAF6"); hdr.pack(fill="x")
            tk.Label(hdr, text=f"Schema: {info['schema']}",
                     bg="#E8EAF6", font=("Arial",8,"bold")).pack(side="left", padx=10, pady=4)
            tk.Label(hdr, text=f"Rows: {info['row_count']}",
                     bg="#E8EAF6").pack(side="left", padx=10)
            tk.Label(hdr, text=f"Date col: {info['date_col'] or 'not found'}",
                     bg="#E8EAF6").pack(side="left", padx=10)

            # Columns list
            col_info = "  |  ".join(
                f"{c['column_name']} ({c['data_type']})" for c in info['columns']
            )
            tk.Label(tab, text=col_info, wraplength=940, justify="left",
                     fg="#555", font=("Arial",8)).pack(anchor="w", padx=8, pady=(2,0))

            # Data grid
            df = info["preview_df"]
            if df.empty:
                tk.Label(tab, text="(no rows)", fg="gray").pack(pady=10)
            else:
                col_list = list(df.columns)
                fr2 = tk.Frame(tab); fr2.pack(fill="both", expand=True, padx=4, pady=4)
                vsb = tk.Scrollbar(fr2, orient="vertical")
                hsb = tk.Scrollbar(fr2, orient="horizontal")
                tv  = ttk.Treeview(fr2, columns=col_list, show="headings",
                                   yscrollcommand=vsb.set, xscrollcommand=hsb.set, height=10)
                vsb.config(command=tv.yview); hsb.config(command=tv.xview)
                vsb.pack(side="right", fill="y"); hsb.pack(side="bottom", fill="x")
                tv.pack(fill="both", expand=True)

                for col in col_list:
                    tv.heading(col, text=col)
                    tv.column(col, width=150, anchor="w")

                for _, row in df.iterrows():
                    tv.insert("", "end", values=[
                        ("" if (not isinstance(v, str) and pd.isna(v)) else str(v)[:80])
                        for v in [row[c] for c in col_list]
                    ])

            # Apply button
            def _apply(inf=info, d=df):
                _apply_session(inf, d)
            tk.Button(tab, text="✔  Use Latest Session from this Table",
                      bg="#1B5E20", fg="white", font=("Arial",9,"bold"),
                      command=_apply).pack(pady=6)

    def _apply_session(info, df):
        if df.empty:
            messagebox.showwarning("Empty", "No rows in this table.", parent=win)
            return
        row      = df.iloc[0]
        id_col   = next(
            (c['column_name'] for c in info['columns']
             if any(k in c['column_name'].lower() for k in ['id','session','name'])),
            info['columns'][0]['column_name']
        )
        sess_id  = str(row.get(id_col, ""))
        ym       = ""
        if info['date_col'] and info['date_col'] in row:
            dt = pd.to_datetime(str(row[info['date_col']]), errors='coerce')
            ym = dt.strftime("%Y_%m") if not pd.isna(dt) else str(row[info['date_col']])

        pano_session.update({
            "session_id": sess_id,
            "year_month": ym,
            "table":      f"{info['schema']}.{info['table']}",
            "row_count":  str(info['row_count'])
        })
        session_id_var.set(sess_id)
        session_ym_var.set(ym)
        session_tbl_var.set(f"{info['schema']}.{info['table']}")
        session_rows_var.set(str(info['row_count']))
        session_status_var.set(f"✅  Session set from {info['schema']}.{info['table']}  |  ID: {sess_id}  |  {ym}")
        log(f"✅ Panoramic session applied: {sess_id}  ({ym})  from {info['schema']}.{info['table']}")
        messagebox.showinfo("Session Applied",
                            f"Session ID : {sess_id}\nYear-Month : {ym}\nTable      : {info['schema']}.{info['table']}",
                            parent=win)

    def _reload():
        status_var.set("Connecting…")
        win.update_idletasks()
        def _work():
            try:
                all_tbl  = fetch_all_db_tables()
                sess_tbl = fetch_all_session_tables()
                win.after(0, lambda: _populate(all_tbl, sess_tbl))
            except Exception as e:
                win.after(0, lambda: status_var.set(f"Error: {e}"))
        threading.Thread(target=_work, daemon=True).start()

    def _populate(all_tbl, sess_tbl):
        # Fill all-tables tab
        for item in tree_all.get_children():
            tree_all.delete(item)
        for t in all_tbl:
            tree_all.insert("", "end", values=(t['table_schema'], t['table_name'], t['size']))

        # Fill session tabs
        _build_session_tabs(sess_tbl)
        status_var.set(
            f"Connected  ·  {len(all_tbl)} tables total  ·  "
            f"{len(sess_tbl)} panoramic/session tables"
        )

    _reload()


# ─────────────────────────────────────────────
# Quick Fetch Latest Session (no explorer)
# ─────────────────────────────────────────────
def quick_fetch_session():
    def _work():
        session_status_var.set("Connecting to MNR DB…")
        root.update_idletasks()
        try:
            tables = fetch_all_session_tables()
            if not tables:
                session_status_var.set("❌  No panoramic/session tables found.")
                return
            # Pick first table that has a date col and data
            chosen = next((t for t in tables if t['date_col'] and not t['preview_df'].empty), None)
            if not chosen:
                chosen = tables[0]
            df   = chosen['preview_df']
            row  = df.iloc[0] if not df.empty else None
            if row is None:
                session_status_var.set("❌  Table found but no rows.")
                return
            id_col = next(
                (c['column_name'] for c in chosen['columns']
                 if any(k in c['column_name'].lower() for k in ['id','session','name'])),
                chosen['columns'][0]['column_name']
            )
            sess_id = str(row.get(id_col, ""))
            ym = ""
            if chosen['date_col'] and chosen['date_col'] in row:
                dt = pd.to_datetime(str(row[chosen['date_col']]), errors='coerce')
                ym = dt.strftime("%Y_%m") if not pd.isna(dt) else str(row[chosen['date_col']])
            pano_session.update({
                "session_id": sess_id, "year_month": ym,
                "table": f"{chosen['schema']}.{chosen['table']}",
                "row_count": str(chosen['row_count'])
            })
            session_id_var.set(sess_id)
            session_ym_var.set(ym)
            session_tbl_var.set(f"{chosen['schema']}.{chosen['table']}")
            session_rows_var.set(str(chosen['row_count']))
            session_status_var.set(
                f"✅  {sess_id}  |  {ym}  |  {chosen['schema']}.{chosen['table']}"
            )
            log(f"✅ Latest panoramic session: {sess_id} ({ym}) from {chosen['schema']}.{chosen['table']}")
        except Exception as e:
            session_status_var.set(f"❌  DB Error: {e}")
    threading.Thread(target=_work, daemon=True).start()


# ─────────────────────────────────────────────
# Spatial: assign panoramic session per camera
# ─────────────────────────────────────────────
import ast as _ast

def _extract_lonlat(coord_value):
    """
    Return (lon, lat) floats from a camera coordinates field, or (None, None).
    The Phoenix API returns [lat, lon] order, so we swap to (lon, lat) for PostGIS.
    """
    try:
        if isinstance(coord_value, str):
            coord_value = _ast.literal_eval(coord_value)
        if isinstance(coord_value, list) and len(coord_value) >= 2:
            if isinstance(coord_value[0], (int, float)):
                lat, lon = float(coord_value[0]), float(coord_value[1])
                return lon, lat  # PostGIS expects (lon, lat)
            if isinstance(coord_value[0], list) and len(coord_value[0]) >= 2:
                lat, lon = float(coord_value[0][0]), float(coord_value[0][1])
                return lon, lat
    except Exception:
        pass
    return None, None


def assign_sessions_to_cameras(df, country_code=None, buffer_m=5.0):
    """
    Insert camera coordinates into a temp table, then run one spatial JOIN:
    - Within 5m  → pick latest session by date  (exact road match)
    - Outside 5m → pick nearest session          (fallback)
    Uses DISTINCT ON so each camera gets exactly one session row.
    """
    PANO_COLS = ["Panoramic_Session_Name", "Panoramic_Session_Year_Month"]

    # Collect (public_id, lon, lat) with correct coordinate order
    cam_rows = []
    for _, row in df.iterrows():
        lon, lat = _extract_lonlat(row.get("coordinates", ""))
        if lon is not None and lat is not None:
            try:
                pid = str(int(float(str(row.get("publicId", "")))))
            except Exception:
                pid = str(row.get("publicId", ""))
            cam_rows.append((pid, lon, lat))

    if not cam_rows:
        for col in PANO_COLS:
            df[col] = ""
        return df

    try:
        conn = _db_connect(country_code)
    except Exception as e:
        log(f"   ❌ DB connect failed: {e}")
        for col in PANO_COLS:
            df[col] = ""
        return df

    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    log(f"   🔌 DB connected. Inserting {len(cam_rows)} camera coordinates…")

    try:
        # Temp table — dropped automatically at end of session
        cur.execute("""
            CREATE TEMP TABLE IF NOT EXISTS _cam_coords (
                public_id TEXT,
                lon       DOUBLE PRECISION,
                lat       DOUBLE PRECISION
            ) ON COMMIT DELETE ROWS;
        """)
        cur.execute("DELETE FROM _cam_coords;")

        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO _cam_coords (public_id, lon, lat) VALUES %s",
            cam_rows
        )

        # One query for all cameras:
        # Step 1 (inner): use bounding-box index (&&) to find all sessions
        #   whose geometry passes within ~5km of the camera. Group by session_name
        #   so each session appears once regardless of how many segments it has.
        # Step 2 (outer): among those distinct sessions, pick the one with the
        #   latest capture date encoded in the session_name (YYYY_MM_DD part).
        # KNN finds 50 nearest session geometries per camera (index-based, fast).
        # Among those, latest capture date (from sessionname) wins.
        # Post-query filter applies: only sessions ≤ 5m AND year ≥ 2021 are kept.
        cur.execute("""
            SELECT DISTINCT ON (c.public_id)
                c.public_id,
                sr.sessionname AS session_name,
                ROUND(ST_Distance(
                    sr.geometry::geography,
                    ST_SetSRID(ST_Point(c.lon, c.lat), 4326)::geography
                )::numeric, 1) AS dist_m
            FROM _cam_coords c
            CROSS JOIN LATERAL (
                SELECT sessionname, geometry
                FROM panoramix.sessions
                ORDER BY geometry <-> ST_SetSRID(ST_Point(c.lon, c.lat), 4326)
                LIMIT 50
            ) sr
            ORDER BY
                c.public_id,
                CASE WHEN ST_Distance(
                    sr.geometry::geography,
                    ST_SetSRID(ST_Point(c.lon, c.lat), 4326)::geography
                ) <= 5 THEN 0 ELSE 1 END,
                SUBSTRING(sr.sessionname FROM '[0-9]{4}_[0-9]{2}_[0-9]{2}') DESC;
        """)
        rows = cur.fetchall()
        conn.commit()
        log(f"   🔍 Query returned {len(rows)} session matches.")

    except Exception as e:
        import traceback
        conn.rollback()
        cur.close(); conn.close()
        log(f"   ❌ Session DB error: {e}")
        log(f"   ❌ Detail: {traceback.format_exc()}")
        for col in PANO_COLS:
            df[col] = ""
        return df

    cur.close(); conn.close()

    def _clean_id(v):
        s = str(v).strip()
        try:
            return str(int(float(s)))
        except Exception:
            return s

    def _ym_from_name(session_name):
        """Extract YYYY_MM from session name e.g. FZT-6579_2023_05_25__16_03_22 -> 2023_05"""
        try:
            parts = str(session_name).split("_")
            for i, p in enumerate(parts):
                if len(p) == 4 and p.isdigit() and 2000 <= int(p) <= 2100:
                    return f"{p}_{parts[i+1].zfill(2)}"
        except Exception:
            pass
        return ""

    # Only assign if session is within buffer_m (same road) AND capture year >= 2021.
    # Any session farther than buffer_m or older than 2021 → blank.
    def _valid_session(session_name, dist_m):
        if not session_name:
            return False
        if dist_m is None or float(dist_m) > buffer_m:
            return False
        ym = _ym_from_name(session_name)          # e.g. "2021_03"
        if not ym:
            return False
        try:
            year = int(ym.split("_")[0])
            return year >= 2021
        except Exception:
            return False

    lookup = {
        r["public_id"]: r["session_name"]
        if _valid_session(r["session_name"], r["dist_m"])
        else ""
        for r in rows
    }

    df["Panoramic_Session_Name"]       = df["publicId"].map(lambda x: lookup.get(_clean_id(x), ""))
    df["Panoramic_Session_Year_Month"] = df["Panoramic_Session_Name"].map(_ym_from_name)

    matched   = df["Panoramic_Session_Name"].ne("").sum()
    unmatched = df["Panoramic_Session_Name"].eq("").sum()
    log(f"   📊 Panoramic match: {matched} cameras assigned  |  {unmatched} cameras with no coverage (blank)")
    if unmatched == len(df):
        log(f"   ⚠  No panoramic sessions found within 50km — this country may not have panoramic coverage.")

    return df


# ─────────────────────────────────────────────
# Phoenix Camera Download
# ─────────────────────────────────────────────
def _fetch_one_type(country_code, cam_type, expiry_from, expiry_to, reported_from, reported_to):
    """Fetch cameras for a single camera type. Returns list of records or []."""
    params = {
        "countryCode":      country_code,
        "cameraTypes":      cam_type,
        "expiryDateFrom":   expiry_from,
        "expiryDateTo":     expiry_to,
        "reportedDateFrom": reported_from,
        "reportedDateTo":   reported_to
    }
    for attempt in range(1, 4):
        try:
            resp = requests.get(API_URL, params=params, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []
        except requests.exceptions.Timeout:
            if attempt == 3:
                log(f"   ⏳ {cam_type}: timed out after 3 attempts, skipping.")
                return []
        except Exception as e:
            if attempt == 3:
                log(f"   ❌ {cam_type}: {e}")
                return []
    return []


def download_cameras(country_code, expiry_from, expiry_to, reported_from, reported_to, buffer_m=5.0):
    from concurrent.futures import ThreadPoolExecutor, as_completed

    log(f"   🔄 Downloading {len(CAMERA_TYPES)} camera types in parallel…")

    all_records = []
    with ThreadPoolExecutor(max_workers=len(CAMERA_TYPES)) as executor:
        futures = {
            executor.submit(
                _fetch_one_type, country_code, cam_type,
                expiry_from, expiry_to, reported_from, reported_to
            ): cam_type
            for cam_type in CAMERA_TYPES
        }
        for future in as_completed(futures):
            cam_type = futures[future]
            records  = future.result()
            log(f"   ✓ {cam_type}: {len(records)} cameras")
            all_records.extend(records)

    if not all_records:
        return None

    data = all_records

    df = pd.json_normalize(data, sep='.')
    for col in ["lastModerationDate", "expiryDate", "createDate"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)

    df.rename(columns={"id": "publicId", "frc": "FRC",
                       "speedLimit.limit": "speed"}, inplace=True)
    def _start_coord(val):
        try:
            import ast
            v = ast.literal_eval(str(val)) if isinstance(val, str) else val
            if isinstance(v, list) and len(v) >= 2:
                if isinstance(v[0], list):
                    lat, lon = v[0][0], v[0][1]
                else:
                    lat, lon = v[0], v[1]
                return f"{lat}, {lon}"
        except Exception:
            pass
        return ""
    df["coordinates"] = df.get("geometry.coordinates", "").apply(_start_coord)

    for col in ["addReportsCount", "confirmReportsCount", "deleteReportsCount"]:
        df[col] = pd.to_numeric(df.get(col, 0), errors="coerce").fillna(0).astype(int)
    df["allReportsCount"] = df["addReportsCount"] + df["confirmReportsCount"] + df["deleteReportsCount"]
    df["deletePercentage"] = df.apply(
        lambda r: round(r["deleteReportsCount"] / r["allReportsCount"] * 100, 2)
                  if r["allReportsCount"] > 0 else 0.0, axis=1
    )

    def kw_match(comment):
        if pd.isna(comment): return ""
        return "; ".join(kw for kw in KEYWORDS if kw.lower() in comment.lower())
    df["MatchedKeywords"] = df["lastModerationComment"].apply(kw_match) if "lastModerationComment" in df.columns else ""

    # ── Assign panoramic session to each camera via PostGIS road match ──
    try:
        log(f"   🗺  Querying panoramic sessions for {len(df)} cameras  (buffer: {buffer_m} m, year ≥ 2021)…")
        cc = df["countryCode"].iloc[0] if "countryCode" in df.columns and len(df) > 0 else None
        df = assign_sessions_to_cameras(df, country_code=cc, buffer_m=buffer_m)
        log(f"   ✅ Panoramic sessions assigned.")
    except Exception as e:
        import traceback
        log(f"   ❌ Session assignment failed: {e}")
        log(f"   ❌ Detail: {traceback.format_exc()}")
        for col in ["Panoramic_Session_Name", "Panoramic_Session_Year_Month"]:
            if col not in df.columns:
                df[col] = ""

    ordered = [
        'publicId','countryCode','type','FRC','speed','speedLimit.unit',
        'bearing','openLR','createDate','expiryDate','lastModerationDate',
        'lastModerationReporter','lastModerationResource','lastModerationMoma',
        'lastModerationTrigger','lastModerationComment','linkedZonePublicId',
        'addReportsCount','confirmReportsCount','deleteReportsCount',
        'allReportsCount','deletePercentage','MatchedKeywords','coordinates',
        'Panoramic_Session_Name','Panoramic_Session_Year_Month'
    ]
    df = df[[c for c in ordered if c in df.columns]]

    now       = datetime.now(timezone.utc)
    c10       = now - timedelta(days=365 * 10)
    c4        = now - timedelta(days=365 * 4)
    lmd       = pd.to_datetime(df["lastModerationDate"], errors="coerce")
    df["lastModerationDate"] = lmd

    df_4_10   = df[(lmd > c10) & (lmd <= c4)].copy()
    df_4_10.sort_values("lastModerationDate", inplace=True)
    df_4_10["Moderation_Year"] = df_4_10["lastModerationDate"].dt.year

    df_kw     = df[df["MatchedKeywords"] != ""].copy().sort_values("lastModerationDate")
    df_zero   = df[df["allReportsCount"] == 0].copy().sort_values("lastModerationDate")
    df_del    = df[df["deleteReportsCount"] > 0].copy().sort_values("deletePercentage", ascending=False)

    # Strip timezone for Excel
    for dc in ["lastModerationDate","expiryDate","createDate"]:
        for sub in [df, df_4_10, df_kw, df_zero, df_del]:
            if dc in sub.columns:
                sub[dc] = sub[dc].dt.tz_localize(None)

    return df, df_4_10, df_kw, df_zero, df_del


# ─────────────────────────────────────────────
# Main Process
# ─────────────────────────────────────────────
def log(msg):
    log_text.insert(tk.END, msg + "\n")
    log_text.see(tk.END)

def run_process_thread():
    threading.Thread(target=run_process, daemon=True).start()

def run_process():
    countries     = country_entry.get().strip()
    output_folder = output_entry.get().strip()

    if not countries or not output_folder:
        messagebox.showwarning("Missing input", "Enter country codes and output folder.")
        return

    try:
        pano_buffer_m = float(pano_buffer_entry.get().strip())
        if pano_buffer_m <= 0:
            raise ValueError
    except ValueError:
        messagebox.showwarning("Invalid input", "Panoramic Buffer Distance must be a positive number (e.g. 5).")
        return
    if not pano_session["session_id"]:
        if not messagebox.askyesno("No Session",
            "No panoramic session fetched yet.\nContinue without session info?"):
            return

    country_list  = [c.strip().upper() for c in countries.split(",")]
    today         = datetime.utcnow()
    exp_from      = (today - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
    exp_to        = (today + timedelta(days=365*20)).strftime("%Y-%m-%dT23:59:59Z")
    rep_from      = (today - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00Z")
    rep_to        = today.strftime("%Y-%m-%dT23:59:59Z")

    all_raw, all_4_10, all_kw, all_zero, all_del = [], [], [], [], []
    progress_bar["maximum"] = len(country_list)

    for i, cc in enumerate(country_list, 1):
        log(f"📍 [{i}/{len(country_list)}] Downloading cameras for {cc}…")
        try:
            result = download_cameras(cc, exp_from, exp_to, rep_from, rep_to, buffer_m=pano_buffer_m)
            if result:
                r, d4, dk, dz, dd = result
                log(f"   ✓ {len(r)} cameras | 4-10yr: {len(d4)} | keyword: {len(dk)} | zero-reports: {len(dz)} | high-delete: {len(dd)}")
                all_raw.append(r); all_4_10.append(d4); all_kw.append(dk)
                all_zero.append(dz); all_del.append(dd)
            else:
                log(f"   ⚠  No data returned for {cc}")
        except Exception as e:
            log(f"   ❌ Error for {cc}: {e}")
        progress_bar["value"] = i
        root.update_idletasks()

    if not all_raw:
        messagebox.showwarning("No data", "No camera data retrieved for any country.")
        return

    os.makedirs(output_folder, exist_ok=True)
    df_all = pd.concat(all_raw, ignore_index=True)

    # ── CSV (raw) ──
    csv_path = os.path.join(output_folder, "Combined_Camera_Report.csv")
    df_all.to_csv(csv_path, index=False, encoding="utf-8-sig")
    log(f"✅ CSV saved: {csv_path}")

    # ── Excel (filtered sheets) ──
    xl_path = os.path.join(output_folder, "Combined_Camera_Filter_Report.xlsx")
    with pd.ExcelWriter(xl_path, engine="xlsxwriter") as w:
        if all_4_10:
            pd.concat(all_4_10, ignore_index=True).to_excel(w, sheet_name="Date_Filter_4_10_Years", index=False)
        if all_kw:
            pd.concat(all_kw, ignore_index=True).to_excel(w, sheet_name="KeyWord_Filter", index=False)
        if all_zero:
            pd.concat(all_zero, ignore_index=True).to_excel(w, sheet_name="AllReports_Zero", index=False)
        if all_del:
            pd.concat(all_del, ignore_index=True).to_excel(w, sheet_name="DeleteReports_NotZero", index=False)
        df_all.to_excel(w, sheet_name="Raw_Data", index=False)
    log(f"✅ Excel saved: {xl_path}")

    ym    = pano_session["year_month"] or "N/A"
    sid   = pano_session["session_id"] or "N/A"
    messagebox.showinfo("Done",
        f"Process complete!\n\n"
        f"Panoramic Session : {sid}\n"
        f"Year-Month        : {ym}\n\n"
        f"Files saved to:\n{output_folder}"
    )


# ─────────────────────────────────────────────
# GUI
# ─────────────────────────────────────────────
root = tk.Tk()
root.title("Phoenix Safety Camera Tool  +  MNR Panoramic Data")
root.geometry("820x620")
root.resizable(False, False)

# ── Title bar ──
title_bar = tk.Frame(root, bg="#1A237E"); title_bar.pack(fill="x")
tk.Label(title_bar,
         text="Phoenix Safety Camera  +  MNR Panoramic Session",
         bg="#1A237E", fg="white", font=("Arial",12,"bold")).pack(side="left", padx=14, pady=8)
tk.Label(title_bar,
         text="Created By: Prabhakar.Chaudhari@tomtom.com",
         bg="#1A237E", fg="#B0BEC5", font=("Arial",11)).pack(side="right", padx=14, pady=8)

# ── Panoramic Session Panel ──
f_sess = tk.LabelFrame(root, text="MNR Panoramic Session", padx=8, pady=6,
                        font=("Arial",9,"bold"))
f_sess.pack(fill="x", padx=10, pady=(8,3))

# Row 0 — fields
tk.Label(f_sess, text="Session ID:").grid(row=0, column=0, sticky="w")
session_id_var = tk.StringVar()
tk.Entry(f_sess, textvariable=session_id_var, width=26, state="readonly",
         bg="#F9FBE7").grid(row=0, column=1, padx=5)

tk.Label(f_sess, text="Year-Month:").grid(row=0, column=2, sticky="w", padx=(10,0))
session_ym_var = tk.StringVar()
tk.Entry(f_sess, textvariable=session_ym_var, width=12, state="readonly",
         bg="#F9FBE7").grid(row=0, column=3, padx=5)

tk.Label(f_sess, text="Table:").grid(row=0, column=4, sticky="w", padx=(10,0))
session_tbl_var = tk.StringVar()
tk.Entry(f_sess, textvariable=session_tbl_var, width=26, state="readonly",
         bg="#F9FBE7").grid(row=0, column=5, padx=5)

tk.Label(f_sess, text="Rows:").grid(row=0, column=6, sticky="w", padx=(10,0))
session_rows_var = tk.StringVar()
tk.Entry(f_sess, textvariable=session_rows_var, width=8, state="readonly",
         bg="#F9FBE7").grid(row=0, column=7, padx=5)

# Row 1 — buttons
btn_frame = tk.Frame(f_sess); btn_frame.grid(row=1, column=0, columnspan=8, pady=(6,0), sticky="w")
tk.Button(btn_frame, text="⚡ Fetch Latest Session", bg="#1565C0", fg="white",
          command=quick_fetch_session).pack(side="left", padx=(0,8))
tk.Button(btn_frame, text="🔍 Explore DB / All Sessions", bg="#6A1B9A", fg="white",
          command=open_db_explorer).pack(side="left")
tk.Label(btn_frame, text="ⓘ  For display only — does not affect output",
         fg="#888", font=("Arial", 8, "italic")).pack(side="left", padx=14)

# Row 2 — status
session_status_var = tk.StringVar(value="Not connected  —  click Fetch or Explore DB")
tk.Label(f_sess, textvariable=session_status_var, fg="gray",
         wraplength=780, justify="left", font=("Arial",8)).grid(
    row=2, column=0, columnspan=8, sticky="w", pady=(4,0))

# ── Camera Download Panel ──
f_dl = tk.LabelFrame(root, text="Camera Download (Phoenix API)", padx=8, pady=6,
                      font=("Arial",9,"bold"))
f_dl.pack(fill="x", padx=10, pady=4)

tk.Label(f_dl, text="Country Codes (comma-separated, e.g.  AUT, FRA, DEU, EGY):").pack(anchor="w")
country_entry = tk.Entry(f_dl, width=90); country_entry.pack(fill="x", pady=(0,4))

tk.Label(f_dl, text="Output Folder:").pack(anchor="w")
f_path = tk.Frame(f_dl); f_path.pack(fill="x")
output_entry = tk.Entry(f_path, width=76); output_entry.pack(side="left")
tk.Button(f_path, text="Browse",
          command=lambda: (output_entry.delete(0,tk.END),
                           output_entry.insert(0, filedialog.askdirectory()))
          ).pack(side="left", padx=6)

# ── Pano buffer input ──
f_buf = tk.Frame(f_dl); f_buf.pack(fill="x", pady=(6,0))
tk.Label(f_buf, text="Panoramic Buffer Distance (m):",
         font=("Arial", 9)).pack(side="left")
pano_buffer_entry = tk.Entry(f_buf, width=8, justify="center")
pano_buffer_entry.insert(0, "5")
pano_buffer_entry.pack(side="left", padx=6)
tk.Label(f_buf,
         text="Sessions within this distance are considered present on the road.  (recommended: 5 m)",
         fg="#555", font=("Arial", 8, "italic")).pack(side="left")

# ── Start button ──
tk.Button(root, text="▶   Start Download + Export", command=run_process_thread,
          bg="#2E7D32", fg="white", font=("Arial",10,"bold"), pady=7
          ).pack(fill="x", padx=10, pady=6)

# ── Progress ──
tk.Label(root, text="Progress:").pack(anchor="w", padx=10)
progress_bar = ttk.Progressbar(root, orient="horizontal", length=800, mode="determinate")
progress_bar.pack(padx=10, pady=(0,4))

# ── Log ──
tk.Label(root, text="Log:").pack(anchor="w", padx=10)
f_log = tk.Frame(root); f_log.pack(fill="both", expand=True, padx=10, pady=(0,8))
log_text = tk.Text(f_log, height=9, width=96, font=("Consolas",8))
sb_log = tk.Scrollbar(f_log, command=log_text.yview)
log_text.configure(yscrollcommand=sb_log.set)
log_text.pack(side="left", fill="both", expand=True)
sb_log.pack(side="right", fill="y")

log("Ready.  Fetch a panoramic session from the MNR DB before starting the process.")

root.mainloop()
