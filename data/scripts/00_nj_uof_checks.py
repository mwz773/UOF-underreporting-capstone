"""
NJOAG Use-of-Force data diagnostics.

Checks the open items flagged in claude/UOF_Data_Reference.md against the
full export (the doc's conclusions were based on a 10-row sample, so these
need to be confirmed at scale before you rely on them in the merge code):

  1. Does Incident ID always equal County + "-" + Agency Name + "-" +
     Incident Case Number?
  2. Is Report Number unique per row, and does it match the
     UOF<YY>-<M>-<seq> pattern? (duplicates could indicate the
     "Benchmark Form Number" reassignment flow described in the portal FAQ)
  3. Does Incident Date's year/month agree with the year/month embedded in
     Report Number? (matters for deciding which field defines the
     agency-month bucket)
  4. How often does one incident (Incident ID) span multiple officer rows,
     and is that consistent with the "Other Officer Involved" flag?
  5. Are there any Form ID duplicates, or (County, Agency, Case Number)
     collisions that don't match the Incident ID count?

Usage:
    python uof_data_diagnostics.py path/to/export.csv
    python uof_data_diagnostics.py path/to/export.xlsx --sheet "Sheet1"

Requires: pandas (openpyxl too, if reading .xlsx)
"""
import argparse
import re

import pandas as pd

ID_COLS = [
    "Form ID", "County", "Agency Name", "Incident ID",
    "Report Number", "Incident Case Number", "Incident Date",
]

REPORT_NUMBER_PATTERN = re.compile(r"^UOF(\d{2})-(\d{1,2})-(\d+)$")


CSV_ENCODINGS_TO_TRY = ["utf-8-sig", "cp1252", "latin-1"]


def load(path, sheet=None):
    if path.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(path, sheet_name=sheet or 0, dtype=str)
    else:
        last_err = None
        df = None
        for enc in CSV_ENCODINGS_TO_TRY:
            try:
                df = pd.read_csv(path, dtype=str, encoding=enc)
                print(f"  (read with encoding={enc})")
                break
            except UnicodeDecodeError as e:
                last_err = e
                continue
        if df is None:
            raise last_err
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in ID_COLS if c not in df.columns]
    if missing:
        print(f"WARNING: missing expected columns: {missing}")
    return df


def check_incident_id_formula(df):
    print("\n=== 1. Incident ID formula check ===")
    needed = {"County", "Agency Name", "Incident Case Number", "Incident ID"}
    if not needed.issubset(df.columns):
        print("  skipped (missing columns)")
        return
    expected = (
        df["County"].str.upper().str.strip() + "-"
        + df["Agency Name"].str.upper().str.strip() + "-"
        + df["Incident Case Number"].str.upper().str.strip()
    )
    actual = df["Incident ID"].str.upper().str.strip()
    mismatch = df[expected != actual]
    print(f"  rows checked: {len(df)}")
    print(f"  mismatches:   {len(mismatch)} ({len(mismatch) / max(len(df), 1):.1%})")
    if len(mismatch):
        cols = ["Form ID", "County", "Agency Name", "Incident Case Number", "Incident ID"]
        print("  sample mismatches:")
        print(mismatch[cols].head(10).to_string(index=False))


def check_report_number(df):
    print("\n=== 2. Report Number uniqueness / stability ===")
    if not {"Form ID", "Report Number"}.issubset(df.columns):
        print("  skipped (missing columns)")
        return
    dupe_report = df["Report Number"].duplicated(keep=False)
    print(f"  distinct Form ID:        {df['Form ID'].nunique()}")
    print(f"  distinct Report Number:  {df['Report Number'].nunique()}")
    print(f"  rows with duplicated Report Number: {dupe_report.sum()}")
    if dupe_report.sum():
        cols = [c for c in ["Form ID", "Report Number", "Agency Name", "Incident ID", "Officer Name"] if c in df.columns]
        print("  sample duplicates (could be reassignment, or a data-entry collision):")
        print(df[dupe_report][cols].sort_values("Report Number").head(10).to_string(index=False))
    bad_format = df["Report Number"].dropna().apply(lambda x: REPORT_NUMBER_PATTERN.match(x) is None)
    print(f"  rows not matching UOF<YY>-<M>-<seq> pattern: {bad_format.sum()}")


def check_date_vs_report_number(df):
    print("\n=== 3. Incident Date vs Report Number embedded year-month ===")
    if not {"Incident Date", "Report Number"}.issubset(df.columns):
        print("  skipped (missing columns)")
        return
    dt = pd.to_datetime(df["Incident Date"], errors="coerce")

    def extract(rn):
        m = REPORT_NUMBER_PATTERN.match(str(rn))
        if not m:
            return (None, None)
        return (2000 + int(m.group(1)), int(m.group(2)))

    extracted = df["Report Number"].apply(extract)
    rn_year = extracted.apply(lambda t: t[0])
    rn_month = extracted.apply(lambda t: t[1])
    valid = rn_year.notna() & dt.notna()
    mismatch = (dt.dt.year != rn_year) | (dt.dt.month != rn_month)
    n_valid = valid.sum()
    n_mismatch = (mismatch & valid).sum()
    print(f"  rows comparable: {n_valid}")
    print(f"  mismatches:      {n_mismatch} ({n_mismatch / max(n_valid, 1):.1%})")
    if n_mismatch:
        cols = ["Form ID", "Incident Date", "Report Number"]
        print(df.loc[mismatch & valid, cols].head(10).to_string(index=False))


def check_multi_officer_incidents(df):
    print("\n=== 4. Multi-officer incident structure ===")
    if "Incident ID" not in df.columns:
        print("  skipped (missing columns)")
        return
    counts = df.groupby("Incident ID").size()
    print(f"  distinct incidents:               {counts.shape[0]}")
    print(f"  total officer-report rows:        {len(df)}")
    print(f"  incidents with >1 officer report: {(counts > 1).sum()} ({(counts > 1).mean():.1%})")
    print(f"  max officer reports in one incident: {counts.max()}")
    if "Other Officer Involved" in df.columns:
        flagged = df["Other Officer Involved"].astype(str).str.upper().eq("TRUE")
        flagged_incident_sizes = df[flagged].groupby("Incident ID").size()
        inconsistent = flagged_incident_sizes[flagged_incident_sizes < 2]
        print(f"  rows flagged 'Other Officer Involved'=TRUE but incident has <2 rows total: {len(inconsistent)}")


def check_other_officer_followup(df, max_examples=10):
    print("\n=== 6. 'Other Officer Involved' follow-up (loose Agency+Date match) ===")
    needed = {"Incident ID", "Other Officer Involved", "Agency Name", "Incident Date", "Form ID"}
    if not needed.issubset(df.columns):
        print("  skipped (missing columns)")
        return
    incident_sizes = df.groupby("Incident ID").size()
    flagged = df["Other Officer Involved"].astype(str).str.upper().eq("TRUE")
    df = df.copy()
    df["_incident_size"] = df["Incident ID"].map(incident_sizes)
    orphans = df[flagged & (df["_incident_size"] < 2)]
    print(f"  orphan rows (flagged TRUE, incident has <2 rows): {len(orphans)}")
    if orphans.empty:
        return

    # Build a lookup: (Agency Name, Incident Date) -> set of Incident IDs seen there
    lookup = df.groupby(["Agency Name", "Incident Date"])["Incident ID"].agg(set)

    resolved, unresolved = [], []
    for _, row in orphans.iterrows():
        key = (row["Agency Name"], row["Incident Date"])
        candidates = lookup.get(key, set())
        other_incident_ids = candidates - {row["Incident ID"]}
        if other_incident_ids:
            resolved.append((row["Form ID"], row["Agency Name"], row["Incident Date"], row["Incident ID"], other_incident_ids))
        else:
            unresolved.append((row["Form ID"], row["Agency Name"], row["Incident Date"], row["Incident ID"]))

    print(f"  orphans with >=1 other same-agency/same-date incident nearby: {len(resolved)} "
          f"(possible Incident ID join failures worth hand-checking)")
    print(f"  orphans with no same-agency/same-date candidate at all:       {len(unresolved)} "
          f"(more likely a genuine missing second report)")

    if resolved:
        print(f"\n  sample possible join failures (first {min(max_examples, len(resolved))}):")
        for form_id, agency, date, incident_id, others in resolved[:max_examples]:
            print(f"    Form ID {form_id} | {agency} | {date}")
            print(f"      this row's Incident ID:   {incident_id}")
            print(f"      other Incident ID(s) same agency+date: {sorted(others)[:5]}")


def check_collisions(df):
    print("\n=== 5. Key collision checks ===")
    if "Form ID" in df.columns:
        print(f"  duplicated Form ID rows: {df['Form ID'].duplicated().sum()}")
    if {"County", "Agency Name", "Incident Case Number"}.issubset(df.columns):
        combo = df["County"] + "|" + df["Agency Name"] + "|" + df["Incident Case Number"]
        n_combo = combo.nunique()
        print(f"  distinct (County, Agency, Case Number) combos: {n_combo}")
        if "Incident ID" in df.columns:
            print(f"  distinct Incident ID values:                   {df['Incident ID'].nunique()}  (should match the line above)")


def main():
    ap = argparse.ArgumentParser(description="Diagnostics for the NJOAG Use-of-Force data export")
    ap.add_argument("path", help="CSV or Excel export from the NJOAG UOF dashboard")
    ap.add_argument("--sheet", default=None, help="Excel sheet name, if the file is .xlsx")
    args = ap.parse_args()

    df = load(args.path, args.sheet)
    print(f"Loaded {len(df)} rows, {len(df.columns)} columns from {args.path}")

    check_incident_id_formula(df)
    check_report_number(df)
    check_date_vs_report_number(df)
    check_multi_officer_incidents(df)
    check_other_officer_followup(df)
    check_collisions(df)


if __name__ == "__main__":
    main()