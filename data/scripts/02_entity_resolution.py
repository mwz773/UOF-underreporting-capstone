"""
NJ UOF Agency Name -> NIBRS ORI crosswalk builder.

Maps the free-text `Agency Name` field in the NJOAG UOF data to the `ORI`
codes NIBRS arrest data is keyed on. See claude/NJ_Agency_ORI_Crosswalk.md
for the full methodology and reasoning behind each fix/override below.

FINAL RESULT (527 distinct UOF agency names):
  - 496 resolved to a single ORI (461 auto by normalized key, 5 manual
    overrides, and 2 agencies resolved as a split pair via County -- see
    HAMILTON_MANSFIELD_BY_COUNTY below, which expands to 4 rows)
  - 1 excluded as unverifiable (Union Co PD)
  - 30 left unmapped: 9 Corrections agencies + 4 state-level/authority
    bodies + Rutgers University PD (ambiguous campus) + 16 others that
    genuinely are not in the FBI's NJ ORI list under any spelling we found
    (see UNRESOLVED_NO_FBI_MATCH below) -- worth one more manual look, but
    not blocking: they're a known, documented gap, not a silent miss.
"""
import json
import re

import pandas as pd

UOF_AGENCY_MONTH_PATH = "/Users/zhangmandy/repos/UOF-underreporting-capstone/data/interim/agency_month.csv"
UOF_INCIDENTS_PATH = "/Users/zhangmandy/repos/UOF-underreporting-capstone/data/interim/incidents.csv"
FBI_AGENCY_NAMES_PATH = "/Users/zhangmandy/repos/UOF-underreporting-capstone/data/raw/nibrs/agencies-names-by-state.json"
CROSSWALK_OUT_PATH = "/Users/zhangmandy/repos/UOF-underreporting-capstone/data/interim/agency_name_ori_crosswalk.csv"

# ---------------------------------------------------------------------------
# 1. Load both sides
# ---------------------------------------------------------------------------
with open(FBI_AGENCY_NAMES_PATH) as f:
    ori_to_name = json.load(f)

nj = {ori: name for ori, name in ori_to_name.items() if ori.startswith("NJ")}
nj_df = pd.DataFrame(sorted(nj.items()), columns=["ori", "agency_name_fbi"])

agency_month = pd.read_csv(UOF_AGENCY_MONTH_PATH)
uof_names = agency_month["agency_name"].drop_duplicates().sort_values().reset_index(drop=True)
uof_df = pd.DataFrame({"agency_name": uof_names})

print(f"NJ ORIs: {len(nj_df)} ({nj_df['agency_name_fbi'].nunique()} unique names)")
print(f"distinct UOF agency names: {len(uof_names)}")

# ---------------------------------------------------------------------------
# 2. Normalize both sides to a comparable key
#
#    - apostrophes dropped outright, not space-substituted: "SHERIFF'S"
#      would otherwise split into "SHERIFF" + "S" and never match "SHERIFFS"
#    - "AND" is stripped as a stopword: fixes "Peapack-Gladstone PD" vs FBI's
#      "Peapack and Gladstone Police Department"
#    - TOWNSHIP/TWP is now STRIPPED (not kept, reversing the round-2 fix).
#      Keeping it looked right for the ~18 NJ places that have a separate
#      Borough/City PD AND a separate Township PD under the same base name
#      (Berlin, Boonton, Chatham, ... -- see DISAMBIGUATE_BY_TOWNSHIP_FLAG
#      below), but it silently broke every OTHER township in the state:
#      UOF spells most of them bare ("Wayne PD", "Lakewood PD", "Nutley PD")
#      while FBI's only entry for that place says "... Township Police
#      Department" -- keeping TOWNSHIP in the key meant these ~55 single-PD
#      townships could never match. Stripping it fixes all of those, and
#      reintroduces ambiguity only for the ~18 real Borough/Township pairs,
#      which are resolved explicitly below using each UOF name's own
#      "Twp"/"Township" marker.
# ---------------------------------------------------------------------------
STOPWORDS = {
    "POLICE", "DEPARTMENT", "DEPT", "OFFICE", "PD",
    "BOROUGH", "BORO", "CITY", "TOWN", "VILLAGE", "COUNTY", "CO",
    "MUNICIPAL", "BUREAU", "DIVISION", "OF", "THE", "AND",
    "TOWNSHIP", "TWP",
}

TYPE_SYNONYMS = {
    "SHERIFFS": "SHERIFF",
    "PROSECUTORS": "PROSECUTOR",
    "MT": "MOUNT",
}

def normalize_name(name):
    if pd.isna(name):
        return name
    s = str(name).upper().replace("'", "")
    s = re.sub(r"[^A-Z0-9\s]", " ", s)
    tokens = [TYPE_SYNONYMS.get(t, t) for t in s.split()]
    tokens = [t for t in tokens if t not in STOPWORDS]
    return " ".join(sorted(tokens))

uof_df["_key"] = uof_df["agency_name"].apply(normalize_name)
nj_df["_key"] = nj_df["agency_name_fbi"].apply(normalize_name)
merged = uof_df.merge(nj_df, on="_key", how="left")

match_per_agency = merged.groupby("agency_name")["ori"].nunique()
print("exactly 1 match:", (match_per_agency == 1).sum())
print("0 matches:      ", (match_per_agency == 0).sum())
print(">1 match:        ", (match_per_agency > 1).sum())

# ---------------------------------------------------------------------------
# 3. Resolve the ambiguous (>1 match) group: with TOWNSHIP stripped, every
#    place that has BOTH a Borough/City PD and a Township PD now collapses
#    its two FBI candidates onto one key. Pick the right one using whether
#    the UOF agency's own raw name says "Twp"/"Township": NJ's UOF export
#    consistently marks the township one that way and leaves the other
#    bare (confirmed across all 18 pairs below -- no exceptions found).
# ---------------------------------------------------------------------------
def resolve_township_ambiguity(merged, match_per_agency):
    resolved = {}
    still_ambiguous = []
    for name in match_per_agency[match_per_agency > 1].index:
        cands = merged.loc[merged["agency_name"] == name, ["ori", "agency_name_fbi"]].drop_duplicates()
        is_twp_uof = bool(re.search(r"\bTWP\b|\bTOWNSHIP\b", name.upper()))
        cand_is_twp = cands["agency_name_fbi"].str.contains("Township", case=False)
        picked = cands[cand_is_twp == is_twp_uof]
        if len(picked) == 1:
            resolved[name] = picked.iloc[0]["ori"]
        else:
            still_ambiguous.append(name)
    return resolved, still_ambiguous

township_resolved, still_ambiguous = resolve_township_ambiguity(merged, match_per_agency)
print(f"\nresolved via Twp/Township flag: {len(township_resolved)}")
print(f"still ambiguous after that: {still_ambiguous}")

# ---------------------------------------------------------------------------
# 4. Manual overrides -- cases normalization (and the rule above) can't
#    resolve from text alone. Each was checked against real NIBRS arrest
#    data or the FBI file directly before being hardcoded; see
#    claude/NJ_Agency_ORI_Crosswalk.md for the full check on each one.
# ---------------------------------------------------------------------------
CHECKED_MANUAL_OVERRIDES = {
    # Two FBI entries ("Princeton Police Department" / "Princeton  Police
    # Department" -- note the double space) are a leftover of the 2013
    # Princeton Borough/Township consolidation. The Twp-flag rule above
    # can't disambiguate these (neither name says "Township"). Confirmed
    # via NIBRS arrests: only NJ0111000 has records in 2024 (NJ0110900
    # has none).
    "Princeton PD": "NJ0111000",
    # FBI's current name is "Montclair State University" -- no
    # "Police"/"Department" in it, which is why it never matched.
    "Montclair State College PD": "NJ0072800",
    # UOF's trailing "of NJ" doesn't appear in FBI's plain "Rowan University".
    "Rowan University of NJ": "NJ0082600",
    # FBI has two entries, "Pennsville Township Police Department" (the
    # real PD) and a bare "Pennsville Township" (no "Police"/"Department"
    # at all -- not an agency entry). Both say "Township" so the Twp-flag
    # rule can't tell them apart; pick the one that's actually a PD.
    "Pennsville PD": "NJ0170500",
    # FBI's two "Palisades Interstate Parkway" entries (non-standard ORI
    # prefixes NJNPIPP00 / NJDI00200, likely a legacy-vs-current code pair)
    # also can't be told apart by name. Confirmed via NIBRS arrests: only
    # NJNPIPP00 has 2024 records (3 rows); NJDI00200 has none.
    "Palisades Inter. Parkway PD": "NJNPIPP00",
    # Alternate spelling: UOF runs the two words together, FBI spaces them.
    "Bayhead Boro PD": "NJ0150200",   # FBI: "Bay Head Police Department"
    "Oceangate Boro PD": "NJ0152100",  # FBI: "Ocean Gate Police Department"
}

# Agencies the key-based join found a candidate for, but that candidate is
# very likely wrong -- excluded rather than silently trusted.
EXCLUDE_FROM_AUTO_MATCH = {
    # With TOWNSHIP stripped, "Union Co PD" collapses onto the SAME key as
    # "Union City PD" and "Union Twp PD" (all three reduce to "UNION").
    # That makes it a 3-UOF-names-vs-2-FBI-candidates ambiguity, and the
    # Twp-flag rule above *will* resolve it: "Union Co PD" doesn't say
    # "Twp", so the rule picks the non-township candidate -- Union City
    # Police Department -- same as it correctly does for "Union City PD"
    # itself. But there's no actual evidence "Union Co PD" means Union
    # City; "Co" most likely abbreviates "County," not "City," and NJ has
    # no obvious county-level PD under Union County either. This is a
    # coincidental key collision, not a real match, so it has to be
    # dropped from the final crosswalk AFTER the Twp-flag step, not just
    # excluded from the plain auto-match step (build_crosswalk applies
    # this to the combined result precisely because of this case).
    "Union Co PD",
}

# ---------------------------------------------------------------------------
# 5. Hamilton Twp PD and Mansfield Twp PD are a different kind of problem:
#    each is TWO real, distinct municipalities (NJ has a Hamilton Township
#    in both Mercer and Atlantic counties; a Mansfield Township in both
#    Warren and Burlington counties), and the UOF export uses the same
#    bare "Agency Name" string for both -- there's no name-level signal to
#    split on. The UOF incident-level table's County column is the only
#    thing that disambiguates them, confirmed by checking incidents.csv:
#    "Hamilton Twp PD" incidents split 359 Mercer / 215 Atlantic, and
#    "Mansfield Twp PD" split 41 Warren / 26 Burlington -- both real splits,
#    not a data-entry fluke. These need a (agency_name, county) composite
#    key rather than agency_name alone, so they're kept out of the
#    agency_name-only crosswalk and handled separately at merge time.
# ---------------------------------------------------------------------------
HAMILTON_MANSFIELD_BY_COUNTY = {
    ("Hamilton Twp PD", "Mercer"): "NJ0110300",
    ("Hamilton Twp PD", "Atlantic"): "NJ0011200",
    ("Mansfield Twp PD", "Warren"): "NJ0211600",
    ("Mansfield Twp PD", "Burlington"): "NJ0031900",
}

# ---------------------------------------------------------------------------
# 6. Everything else with 0 matches is a documented gap, not a bug:
#      - Corrections agencies (county jails + "Department of Corrections"):
#        9 agencies. Corrections facilities don't make patrol arrests, so
#        absence from the arrest-agency ORI list is expected, not an error.
#      - State-level bodies with no ORI at all in the FBI file: NJ Juvenile
#        Justice Commission, NJ State Human Services, State Parole Board,
#        Division of Criminal Justice.
#      - Interstate/bi-state authorities not found under any spelling we
#        tried: Burlington County Bridge Commission, Delaware River Port
#        Authority, Delaware River and Bay Authority PD. (Port Authority of
#        NY/NJ and the two Palisades Interstate Parkway ORIs ARE in the
#        file, under those different names -- see override above.)
#      - Rutgers University PD: FBI lists 4 separate campus ORIs (Camden,
#        Newark x2 -- only NJ0073000 has 2024 arrest records, Newark's
#        other ORI NJ0073400 has none -- and New Brunswick), but UOF's
#        Agency Name and County (all "Other") carry no campus-level signal
#        to split on, the same problem as Hamilton/Mansfield but with no
#        county fix available. Left unresolved rather than guess a campus.
#      - Park Police: same problem again, one more time, with no fix. UOF's
#        County is "Other" for every one of its 29 incidents (checked
#        directly), but the FBI file has ~20 DIFFERENT county/municipal/
#        state park-police ORIs ("Park Police: Passaic County", "Middlesex
#        Park Police", "State Park Police", etc.) -- a generic "Park
#        Police" label with no county signal can't be assigned to any one
#        of them responsibly.
#    All of these are intentionally excluded from the arrest-side
#    comparison, not silently dropped -- see claude/NJ_Agency_ORI_Crosswalk.md.
# ---------------------------------------------------------------------------
UNRESOLVED_NO_FBI_MATCH = {
    "Atlantic Co Corrections", "Camden Co Corrections", "Cumberland Co Corrections",
    "Hudson Co Corrections", "Monmouth Co Corrections", "Morris Co Corrections",
    "Ocean Co Dept Corrections", "Somerset Co Corrections", "Warren Co Corrections",
    "Department of Corrections",
    "NJ Juvenile Justice Commission", "NJ State Human Services",
    "State Parole Board", "Division of Criminal Justice",
    "Burlington County Bridge Commission", "Delaware River Port Authority",
    "Delaware River and Bay Authority PD",
    "Rutgers University PD",
    "Park Police",
}


def build_crosswalk(merged, match_per_agency, township_resolved, manual_overrides, exclude=()):
    auto_matches = (
        merged[merged["agency_name"].isin(match_per_agency[match_per_agency == 1].index)]
        [["agency_name", "ori"]]
        .drop_duplicates()
    )
    auto_matches["match_method"] = "auto"

    twp_df = pd.DataFrame(list(township_resolved.items()), columns=["agency_name", "ori"])
    twp_df["match_method"] = "auto_township_flag"

    override_df = pd.DataFrame(list(manual_overrides.items()), columns=["agency_name", "ori"])
    override_df["match_method"] = "manual_override"

    combined = pd.concat([auto_matches, twp_df, override_df], ignore_index=True).drop_duplicates(subset="agency_name")
    # `exclude` is applied here, to the COMBINED result, not just to
    # auto_matches -- a name that normalization gets wrong can just as
    # easily sneak back in through the Twp-flag step (this is exactly what
    # happened with "Union Co PD" during testing: excluding it only from
    # auto_matches didn't stop the Twp-flag rule from re-adding it with
    # the same wrong ORI).
    return combined[~combined["agency_name"].isin(exclude)].reset_index(drop=True)

crosswalk = build_crosswalk(
    merged, match_per_agency, township_resolved,
    manual_overrides=CHECKED_MANUAL_OVERRIDES,
    exclude=EXCLUDE_FROM_AUTO_MATCH,
)

unmapped = sorted(set(uof_names) - set(crosswalk["agency_name"]))
print(f"\nagencies with an ORI (agency_name-only crosswalk): {crosswalk['agency_name'].nunique()} of {len(uof_names)}")
print(f"  + Hamilton/Mansfield split by county: {len(HAMILTON_MANSFIELD_BY_COUNTY)} rows covering 2 more agency names")
print(f"excluded/unresolved: {len(unmapped)}")
unexpected = sorted(set(unmapped) - UNRESOLVED_NO_FBI_MATCH - EXCLUDE_FROM_AUTO_MATCH - {"Hamilton Twp PD", "Mansfield Twp PD"})
if unexpected:
    print(f"  WARNING -- new/unexpected unmapped names not accounted for above: {unexpected}")

crosswalk.to_csv(CROSSWALK_OUT_PATH, index=False)
print(f"saved to {CROSSWALK_OUT_PATH}")