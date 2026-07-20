# Leave Deviation App — Quick Start Guide

A browser-based tool that compares leave recorded in **WTC** against leave recorded in **Workday** for each employee, and flags any deviation.

## Folder contents

| File | Purpose |
|---|---|
| `install_requirements.bat` | One-time (or occasional) setup: installs/updates Python and required packages. |
| `run_app.bat` | Double-click to launch the app in your browser. |
| `app.py` | The Streamlit web app (UI). |
| `leave_compare.py` | The comparison logic (matching, birthday detection, deviation calc). |
| `requirements.txt` | List of Python packages the app needs. |

## 1. First-time setup

Double-click **`install_requirements.bat`**.

- If Python isn't installed, it will try to install it automatically via `winget`. If that's not available on your PC, it opens the Python download page — install it and make sure to check **"Add python.exe to PATH"** during setup.
- If Python is already installed, it checks for updates and installs/updates the required packages (`streamlit`, `pandas`, `openpyxl`, `jinja2`).

You only need to re-run this if setup changes or a package needs updating.

## 2. Running the app

Double-click **`run_app.bat`**. It opens automatically in your browser at:

```
http://localhost:8502
```

(A different port than the default 8501, so it won't clash with other Streamlit apps you may already have running.)

If the browser doesn't open automatically, copy that address into your browser manually. Leave the black command-prompt window open while you use the app — closing it stops the app.

## 3. Using the app

1. **Upload the WTC Dump** (`.csv` — either comma-delimited or semicolon-delimited exports are supported) and the **Workday Dump** (`.xlsx`, the "General Time Off Takes Report") using the two upload boxes.
2. (Optional) Open **Advanced settings** to change the hours-per-day conversion if your team doesn't use an 8-hour day.
3. Set the **output folder path** and **file name** if you want the report saved to a specific location (defaults to your Desktop).
4. Click **Generate Report**.
5. Review the color-coded table on screen, then either:
   - **Save to output path** — writes the Excel file to the folder you specified, or
   - **Download report (.xlsx)** — downloads it via the browser.

## 4. Understanding the output columns

| Column | Meaning |
|---|---|
| **Lead Name** | The employee's manager, from Workday's "Manager" column. Shown as "N/A" if the employee has no matching Workday record. |
| **WTC Leave Entries** | Number of unique calendar dates with a net-positive leave amount in WTC (each date counts as 1, regardless of half-day/full-day). |
| **Workday Leave Entries** | Number of unique calendar dates with a net-positive leave amount in Workday, after netting all same-date records — including cancellations and rebookings — together. Only records with a valid, non-zero Approved value contribute to the net. |
| **Entries Deviation** | WTC Leave Entries − Workday Leave Entries. This is the number to act on, and it always equals (count of Missing Dates in Workday) − (count of Missing Dates in WTC), so it's fully traceable to the two Missing Dates columns. |
| **Birthday Leave (Yes/No)** | Whether any Birthday Leave was detected for this employee (birthday leave entries are excluded from the entry counts and comparison). |
| **Remarks** | Plain-English summary of the entry-count gap, noting Birthday Leave separately. |
| **Missing Dates in Workday** | Specific dates the employee took leave in WTC that have no matching entry in Workday. |
| **Missing Dates in WTC** | Specific dates recorded in Workday with no matching WTC entry. |

**Note on cancel-and-rebook chains:** Workday sometimes has several rows for the same date — e.g. a leave approved (+1), then cancelled (−1), then replaced with a different leave type (+0.5). These are netted together per date before counting entries: if the net comes out to zero (fully cancelled, nothing taken), that date isn't counted as an entry at all; if a positive net remains (a real leave was taken after the correction), it counts as exactly one entry — never inflated by the correction rows themselves. This keeps Entries Deviation always explainable by the Missing Dates columns.

Rows are color-coded: **red** = a real (non-zero) Entries Deviation exists; **green** = no real deviation, but Birthday Leave was excluded from the comparison.

Rows for employees found in only one system (no match in the other) are listed at the bottom of the table with an explanatory remark, rather than being dropped silently.

## 5. What the app handles automatically

- **Hours → days conversion**: WTC records leave in hours; the app converts using the hours-per-day setting (default 8).
- **WTC file format**: both comma-delimited and semicolon-delimited (quoted) WTC CSV exports are auto-detected and read correctly.
- **Birthday Leave detection**: flexible matching that catches spelling mistakes, abbreviations, extra spaces, and case differences (e.g. "Bday Leave", "B-Day Leave", "Birthday Off", "birthdey leave" are all recognized), so these can be excluded from the deviation calculation.
- **Name matching**: matches employees by name across both systems, tolerating parenthetical suffixes (e.g. "Nilima Tikone (On Leave)") and middle-name/suffix differences (e.g. "Nitin Shriram Patil" vs "Nitin Patil").
- **Duplicate Workday rows**: the Workday export sometimes contains two rows for the exact same leave request (one with a blank "Approved" value, one with the real number). The app detects and merges these into a single leave record.
- **Approved Leave Rule**: a Workday leave record is only counted if it has a valid, non-zero Approved value. Records where Approved is blank, empty, or 0 are excluded entirely from the comparison (not estimated or guessed).
- **Leave Count Rule**: a "leave entry" is a unique calendar date with a net-positive leave amount, regardless of whether it's a half-day or full-day. This gives you an entry-count comparison (WTC Leave Entries vs Workday Leave Entries) that's independent of duration.
- **Cancelled/reissued leave**: same-date records that cancel and re-book a leave (e.g. a `-1` correction alongside re-approvals) are netted per date before counting entries — a date that fully cancels out (net zero) isn't counted as an entry at all, and a date with a real leave remaining after correction counts as exactly one entry, never inflated by the correction rows.

## Troubleshooting

- **"Python was not found"** → run `install_requirements.bat` first.
- **Browser shows a different app / blank page** → make sure you're on `http://localhost:8502`, not 8501 (another app may be using that port).
- **Numbers look off for one employee** → check the **Missing Dates** columns for that row; they usually explain exactly which dates are causing the gap.
- **After clicking "Generate Report", the summary numbers show up but the table, Save button, and Download button are missing** → this means the optional `jinja2` package (needed for the color-coded table) isn't installed. Run `install_requirements.bat` again to install it, then reload the page. The app will also fall back to an uncolored table automatically if this happens, so you can still use Save/Download in the meantime.

## Manual installation (if the .bat files don't work)

Some PCs have restricted permissions, a proxy, or multiple Python installs that trip up the automated scripts. If so, do it by hand from Command Prompt:

1. Install Python from https://www.python.org/downloads/ — during setup, check **"Add python.exe to PATH"**. Restart your PC (or log out/in) afterward if prompted.
2. Open **Command Prompt** (Start menu → type `cmd`).
3. Navigate to the app folder:
   ```
   cd C:\Prabhakar\Leave_Deviation
   ```
4. Confirm Python is found:
   ```
   python --version
   ```
   This should print a version number. If it says "not recognized", PATH wasn't set — reinstall Python and check that box.
5. Install the required packages:
   ```
   python -m pip install streamlit pandas openpyxl jinja2
   ```
6. Confirm they installed correctly:
   ```
   python -c "import streamlit, pandas, openpyxl, jinja2; print('OK')"
   ```
   This should print `OK` with no errors. If it errors out, you likely have more than one Python on the PC — try `python -m pip install --user streamlit pandas openpyxl jinja2` instead.
7. Launch the app:
   ```
   python -m streamlit run app.py --server.port 8502
   ```
8. It should print a line like `Local URL: http://localhost:8502`. Open that address in your browser if it doesn't open automatically.
