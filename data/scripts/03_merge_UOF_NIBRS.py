import argparse
 
import pandas as pd
 
UOF_INCIDENTS_PATH = "/Users/zhangmandy/repos/UOF-underreporting-capstone/data/interim/incidents.csv"
CROSSWALK_PATH = "/Users/zhangmandy/repos/UOF-underreporting-capstone/data/interim/agency_name_ori_crosswalk.csv"
NIBRS_AGENCY_MONTH_PATH = "/Users/zhangmandy/repos/UOF-underreporting-capstone/data/processed/nibrs_agency_month_2024.parquet"
OUT_PATH = "/Users/zhangmandy/repos/UOF-underreporting-capstone/data/processed/uof_nibrs_agency_month.csv"


incidents = pd.read_csv(UOF_INCIDENTS_PATH)
crosswalk = pd.read_csv(CROSSWALK_PATH)
nibrs = pd.read_parquet(NIBRS_AGENCY_MONTH_PATH)
#  ======================================================================================================
# Only want UOF data in the window of the NIBRS 2024 data
WINDOW_START = "2024-01"
WINDOW_END = "2024-12"


incidents["incident_date"] = pd.to_datetime(incidents["incident_date"])
incidents["year_month"] = incidents["incident_date"].dt.to_period("M").astype(str)

n_before = len(incidents)
incidents_2024 = incidents[incidents["year_month"].between(WINDOW_START, WINDOW_END)].copy()
n_after = len(incidents_2024)

print(f"incidents before windowing: {n_before}")
print(f"incidents in {WINDOW_START}..{WINDOW_END}: {n_after} ({n_after/n_before:.1%})")


#  ======================================================================================================
# Now using the agency_name_ori_crosswalk, assign the agencies in 'incidents.csv' a ORI -- needed to merge to NIBRS arrests
incidents_2024 = incidents_2024.merge(crosswalk[["agency_name", "ori"]], on="agency_name", how="left")

unmatched = incidents_2024[incidents_2024["ori"].isna()]
n_total = len(incidents_2024)
n_unmatched = len(unmatched)

print(f"incidents_2024: {n_total} rows")
print(f"unmatched (no ori): {n_unmatched} ({n_unmatched/n_total:.1%})")
print(unmatched["agency_name"].value_counts())

#  ======================================================================================================
# drop unmatched rows

incidents_2024_matched = incidents_2024.dropna(subset=["ori"]).copy()
print(f"incidents_2024_matched: {len(incidents_2024_matched)} rows (dropped {len(incidents_2024) - len(incidents_2024_matched)})")

#  ======================================================================================================
# Aggregate all UOF incidents to the month level on ori, year_month. For every ORI, month, gives total UOF incidents. -- since Arrests are agency-month level
uof_agency_month = (
    incidents_2024_matched.groupby(["ori","year_month"])
    .size()
    .reset_index(name="incidents_total")
)
print(f"uof_agency_month: {len(uof_agency_month)} rows")
print(f"distinct ORIs: {uof_agency_month['ori'].nunique()}")
print(uof_agency_month.head())

#  ======================================================================================================
# Merge on agency-month level with NIBRS arrest data
nibrs["month"] = pd.to_datetime(nibrs["month"])

nibrs["year_month"] = nibrs["month"].dt.to_period("M").astype(str) # add year-month to nibrs 

n_before = len(nibrs)
nibrs_2024 = nibrs[nibrs["year_month"].between("2024-01", "2024-12")][["ori", "year_month", "custodial_arrests"]].copy()
nibrs_2024 = nibrs_2024.rename(columns={"custodial_arrests": "custodial_arrests_part_a"})
n_after = len(nibrs_2024)

combined = pd.merge(uof_agency_month, nibrs_2024, on=["ori", "year_month"], how="outer")

n_both = combined.dropna(subset=["incidents_total", "custodial_arrests"]).shape[0]
n_uof_only = combined[combined["custodial_arrests"].isna() & combined["incidents_total"].notna()].shape[0]
n_nibrs_only = combined[combined["incidents_total"].isna() & combined["custodial_arrests"].notna()].shape[0]

print(f"combined: {len(combined)} rows")
print(f"  both sides:  {n_both}")
print(f"  UOF only:    {n_uof_only}")
print(f"  NIBRS only:  {n_nibrs_only}")

'''
combined: 4356 rows
  both sides:  1818
  UOF only:    1055 # agencies that NIBRS never sees, not single missed months -- of 475 ORIs with UOF incidents, 352 appear in NIBRS, 163 never appear in NIBRS
  NIBRS only:  1483 # ORI-month has NIBRS arrest but zero rows in UOF table for that month 
                    # can be from 1. department actually used no force on anyone they arrested
                                2. department did not submit UOF report for that month



    May be so many ORIs not reported in NIBRS because GROUP B arrests are not in the arrests NIBRS table
    Decided to not include bc Group B arrests do not have date column
    Might be way NIBRS table are not seeing more ORIs
'''
# print(f"incidents: {len(incidents)} rows, {incidents['agency_name'].nunique()} agencies")
# print(f"crosswalk: {len(crosswalk)} agency_name -> ori mappings")
# print(f"nibrs: {len(nibrs)} rows, {nibrs['ori'].nunique()} ORIs, months {nibrs['month'].min()} to {nibrs['month'].max()}")