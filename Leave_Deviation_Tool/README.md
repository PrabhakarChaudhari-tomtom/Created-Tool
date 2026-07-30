# Leave Deviation Tool

A browser-based Streamlit app that compares leave recorded in **WTC** against leave recorded in **Workday** for each employee, and flags any deviation between the two systems.

Full documentation: see the [Confluence page](https://tomtom.atlassian.net/wiki/spaces/ADP/pages/2184544449/WTC+vs+Workday+-+Leave+Deviation+Tool) or `QUICK_START.md` in this folder.

## Quick start

1. `install_requirements.bat` - one-time setup (installs Python + required packages: streamlit, pandas, openpyxl, Pillow, jinja2).
2. `run_app.bat` - launches the app at http://localhost:8502.
3. Upload the WTC dump (.csv, comma- or semicolon-delimited) and the Workday "General Time Off Takes Report" (.xlsx), click **Generate Report**, then Save or Download the result.

## Files

| File | Purpose |
|---|---|
| `app.py` | Streamlit UI |
| `leave_compare.py` | Core comparison logic - name matching, birthday-leave detection, per-date netting, entry-count comparison |
| `requirements.txt` | Python dependencies |
| `install_requirements.bat` | Setup script |
| `run_app.bat` | Launch script |
| `QUICK_START.md` | Standalone quick-start guide |

## Business rules

- **Leave Count Rule**: a leave entry is a unique calendar date with a net-positive leave amount (half-day and full-day both count as 1; same-date cancellations/rebookings are netted first).
- **Approved Leave Rule**: Workday records with a blank, empty, or 0 Approved value are excluded from the comparison entirely.
- **Birthday Leave detection**: fuzzy text matching (typos, abbreviations, spacing, case) excludes Birthday Leave from the comparison.

Note: TomTom brand assets (logo files) and the Word installation guide used in the internal shareable package are not included in this public source copy - see the Confluence page for the full package.
