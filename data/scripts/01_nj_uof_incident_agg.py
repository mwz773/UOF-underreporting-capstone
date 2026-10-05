'''
Since there can be multiple incident IDs for each arrest
 (if multiple officers were incolved in same incident, we 
 have make sure only one unique incident is merged with arrests data).

'''

import re
import pandas as pd

path = "/Users/zhangmandy/repos/UOF-underreporting-capstone/data/raw/nj_uof/2024/NJOAG_UOF_2024.csv"
df = pd.read_csv(path, dtype=str, encoding="cp1252")
print(df.shape)

JUNK_PATTERN = re.compile(r"[^A-Z0-9\-/\. ]")

# 1. normalize Incident ID into clean grouping key -- Some mismatches by slight formatting errors (non-std chars, decimals, etc.)
def normalize_incident_key(s):
    if pd.isna(s):
        return s
    s = str(s).upper().strip()
    s = JUNK_PATTERN.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

df["_incident_key"] = df["Incident ID"].apply(normalize_incident_key)

print("distinct Incident ID (raw):       ", df["Incident ID"].nunique())
print("distinct Incident ID (normalized):", df["_incident_key"].nunique())


dt = pd.to_datetime(df["Incident Date"], errors= "coerce")
df["_dt"] = dt

# How many same incidents filed on different day? 
# incidents with disagreeing dates: 6456 of 57219
date_counts = df.groupby("_incident_key")["_dt"].nunique()
inconsistent = date_counts[date_counts > 1]
print(f"incidents with disagreeing dates: {len(inconsistent)} of {date_counts.shape[0]}")

# How many same incidents filed on different month? --> matters more since we are aggregating on monthly basis
# incidents with disagreeing MONTHS: 256 of 57219 (0.45%)
month_counts = df.groupby("_incident_key")["_dt"].apply(lambda s: s.dt.to_period("M").nunique())
month_inconsistent = month_counts[month_counts > 1]
print(f"incidents with disagreeing MONTHS: {len(month_inconsistent)} of {month_counts.shape[0]} "
      f"({len(month_inconsistent)/month_counts.shape[0]:.2%})")


#---------------------------------------------------------------------------------------------------------
# Collapse officer rows to one row per incident 
other_flag = df["Other Officer Involved"].astype(str).str.upper().eq("TRUE")
df["_other_flag"] = other_flag

# take first agency name, first county, earliest date filed, note how many unique dates there are on the same incident, count how many forms of same incident
incidents = (
    df.groupby("_incident_key")
    .agg(
        agency_name = ("Agency Name", "first"),
        county = ("County", "first"),
        incident_date = ("_dt", "min"),
        incident_date_nunique = ("_dt", "nunique"),
        officers_reported = ("Form ID", "count"),
        any_other_officer_flag = ("_other_flag", "any"),    
        )
        .reset_index()
)

print(f"{len(df)} officer rows -> {len(incidents)} incidents "
      f"({len(df)/len(incidents):.2f} rows/incident average)")


#---------------------------------------------------------------------------------------------------------
# Aggregate incidents to agency-month

incidents_dated = incidents.dropna(subset=["incident_date"]).copy()
incidents_dated["year_month"] = incidents_dated["incident_date"].dt.to_period("M").astype(str)

agency_month = (
    incidents_dated.groupby(["agency_name", "year_month"])
      .size()
      .reset_index(name="incidents_total")
      .sort_values(["agency_name", "year_month"])
)

print(agency_month.head(20))


incidents.to_csv("../interim/incidents.csv", index=False)
agency_month.to_csv("../interim/agency_month.csv", index=False)

