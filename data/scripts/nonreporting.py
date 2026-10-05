"""
Investigation: why do 217 NJ NIBRS agencies that are NOT flagged inactive
report zero Group A (custodial) and zero Group B arrests across the full
Jan 2024-Apr 2025 window, when several of them are real, sizable cities?

Goal: distinguish agencies whose zero-arrest status is explainable
(administrative duplicate/successor ORI, non-municipal agency type, small
real population) from agencies that look like genuine non-reporters worth
flagging in the thesis.

Scope / limitation: this only resolves WHOLE-WINDOW zero-arrest agencies.
It says nothing about month-level reporting gaps for agencies that have
SOME real arrest activity elsewhere in nibrs_agency_month - that's a
separate, still-open problem (see densification notes).
"""

import duckdb

con = duckdb.connect("data/nibrs.duckdb")
con.sql("ATTACH 'nibrs.duckdb' AS bh_db")

# ---------------------------------------------------------------------------
# Step 1: Baseline. How many NJ agencies total, and how many are flagged
# inactive (agency_inactive_dt = '01-DEC-2024', a status flag, not a real
# per-agency historical date - see nj_batch_header investigation notes)?
#
# Result: 609 total | 30 flagged_inactive | 579 flagged_active
# ---------------------------------------------------------------------------
con.sql("""
SELECT
    COUNT(*) AS total_agencies,
    COUNT(*) FILTER (WHERE agency_inactive_dt = '01-DEC-2024') AS flagged_inactive,
    COUNT(*) FILTER (WHERE agency_inactive_dt IS NULL OR TRIM(agency_inactive_dt) = '') AS flagged_active
FROM bh_db.nj_batch_header
""").show()


# ---------------------------------------------------------------------------
# Step 2: Of the 579 active-flagged agencies, how many report ZERO custodial
# (Group A) and ZERO Group B arrests across the entire window? This is the
# actual puzzle - the 30 inactive ones are already explained.
#
# Result: 217 agencies (out of 609 total) report zero arrests of any kind.
# ---------------------------------------------------------------------------
con.sql("""
SELECT COUNT(*) AS n_zero_active
FROM bh_db.nj_batch_header bh
LEFT JOIN (SELECT ori, SUM(custodial_arrests) AS total_custodial FROM nibrs_agency_month GROUP BY ori) a ON bh.ori = a.ori
LEFT JOIN nibrs_group_b_agency gb ON bh.ori = gb.ori
WHERE COALESCE(a.total_custodial, 0) = 0 AND COALESCE(gb.group_b_arrests, 0) = 0
  AND (bh.agency_inactive_dt IS NULL OR TRIM(bh.agency_inactive_dt) = '')
""").show()


# ---------------------------------------------------------------------------
# Step 3: Before assuming these 217 are all "real" non-reporting police
# departments, check agency_indicator (BH012 codebook: 1=City, 2=County,
# 3=University, 4=State Police, 5=Special Agency, 6=Other state, 7=Tribal).
#
# Result: 148 City | 23 Special Agency | 22 State Police | 15 County |
#         5 University | 4 Other state agencies
#
# Most (148/217) ARE real city-type agencies, so this doesn't dissolve the
# puzzle on its own - but ~69 of the 217 are non-municipal agency types
# (special/state/university/county/tribal), where zero arrests over 16
# months is far more plausible and less interesting to flag.
# ---------------------------------------------------------------------------
con.sql("""
SELECT bh.agency_indicator, COUNT(*) AS n
FROM bh_db.nj_batch_header bh
LEFT JOIN (SELECT ori, SUM(custodial_arrests) AS total_custodial FROM nibrs_agency_month GROUP BY ori) a ON bh.ori = a.ori
LEFT JOIN nibrs_group_b_agency gb ON bh.ori = gb.ori
WHERE COALESCE(a.total_custodial, 0) = 0 AND COALESCE(gb.group_b_arrests, 0) = 0
  AND (bh.agency_inactive_dt IS NULL OR TRIM(bh.agency_inactive_dt) = '')
GROUP BY bh.agency_indicator
ORDER BY n DESC
""").show()


# ---------------------------------------------------------------------------
# Step 4: Of the 217 zero-arrest active agencies, how many share a city_name
# with at least one other ORI in the batch header (a signal that the zero
# might be explained by an administrative duplicate / successor agency,
# e.g. the Camden city PD -> Camden County PD consolidation found earlier)
# versus genuinely standalone (no other ORI uses that name)?
#
# Result: 109 share a name with another ORI | 108 are standalone
# ---------------------------------------------------------------------------
con.sql("""
WITH city_counts AS (
    SELECT city_name, COUNT(*) AS n_oris FROM bh_db.nj_batch_header GROUP BY city_name
)
SELECT
    COUNT(*) AS n_zero_active,
    COUNT(*) FILTER (WHERE cc.n_oris > 1) AS shares_name_with_other_ori,
    COUNT(*) FILTER (WHERE cc.n_oris = 1) AS standalone
FROM bh_db.nj_batch_header bh
LEFT JOIN (SELECT ori, SUM(custodial_arrests) AS total_custodial FROM nibrs_agency_month GROUP BY ori) a ON bh.ori = a.ori
LEFT JOIN nibrs_group_b_agency gb ON bh.ori = gb.ori
JOIN city_counts cc ON bh.city_name = cc.city_name
WHERE COALESCE(a.total_custodial, 0) = 0 AND COALESCE(gb.group_b_arrests, 0) = 0
  AND (bh.agency_inactive_dt IS NULL OR TRIM(bh.agency_inactive_dt) = '')
""").show()


# ---------------------------------------------------------------------------
# Step 5: For the 109 duplicate-name zero-arrest agencies, split into:
#   - successor_exists: another ORI sharing this city_name DOES have real
#     arrest activity (e.g. Camden, Edison, Trenton, Williamstown's SP00s)
#     -> explained; exclude from the non-reporting claim
#   - whole_cluster_zero: EVERY ORI sharing this name reports zero
#     (e.g. Totowa, Hamilton, Flemington, Phillipsburg) -> genuinely open
# ---------------------------------------------------------------------------
con.sql("""
WITH city_totals AS (
    SELECT bh.city_name,
           SUM(COALESCE(a.total_custodial, 0) + COALESCE(gb.group_b_arrests, 0)) AS city_total_arrests,
           COUNT(*) AS n_oris
    FROM bh_db.nj_batch_header bh
    LEFT JOIN (SELECT ori, SUM(custodial_arrests) AS total_custodial FROM nibrs_agency_month GROUP BY ori) a ON bh.ori = a.ori
    LEFT JOIN nibrs_group_b_agency gb ON bh.ori = gb.ori
    GROUP BY bh.city_name
)
SELECT bh.ori, bh.city_name, bh.agency_indicator,
       TRY_CAST(bh.population_current_1 AS BIGINT) AS population,
       ct.n_oris,
       CASE WHEN ct.city_total_arrests > 0 THEN 'successor_exists' ELSE 'whole_cluster_zero' END AS category
FROM bh_db.nj_batch_header bh
LEFT JOIN (SELECT ori, SUM(custodial_arrests) AS total_custodial FROM nibrs_agency_month GROUP BY ori) a ON bh.ori = a.ori
LEFT JOIN nibrs_group_b_agency gb ON bh.ori = gb.ori
JOIN city_totals ct ON bh.city_name = ct.city_name
WHERE COALESCE(a.total_custodial, 0) = 0 AND COALESCE(gb.group_b_arrests, 0) = 0
  AND (bh.agency_inactive_dt IS NULL OR TRIM(bh.agency_inactive_dt) = '')
  AND ct.n_oris > 1
ORDER BY category, population DESC
""").show()


# ---------------------------------------------------------------------------
# Step 6: For the 108 standalone zero-arrest agencies (no duplicate name to
# check against a successor), population is the plausibility signal - a
# department covering 1,000 people reporting zero arrests over 16 months is
# plausible; one covering 70,000+ is not.
# ---------------------------------------------------------------------------
con.sql("""
SELECT bh.ori, bh.city_name, bh.agency_indicator,
       TRY_CAST(bh.population_current_1 AS BIGINT) AS population
FROM bh_db.nj_batch_header bh
LEFT JOIN (SELECT ori, SUM(custodial_arrests) AS total_custodial FROM nibrs_agency_month GROUP BY ori) a ON bh.ori = a.ori
LEFT JOIN nibrs_group_b_agency gb ON bh.ori = gb.ori
WHERE COALESCE(a.total_custodial, 0) = 0 AND COALESCE(gb.group_b_arrests, 0) = 0
  AND (bh.agency_inactive_dt IS NULL OR TRIM(bh.agency_inactive_dt) = '')
  AND bh.city_name IN (SELECT city_name FROM bh_db.nj_batch_header GROUP BY city_name HAVING COUNT(*) = 1)
ORDER BY population DESC
""").show()


# ---------------------------------------------------------------------------
# Step 7: FINAL CANDIDATE LIST. Combines both whole_cluster_zero duplicates
# and standalone agencies, filtered to:
#   - agency_indicator = '1' (real City-type department, not special/state/
#     university/county/tribal)
#   - population > 5,000 (not a trivially small department)
#   - city_total_arrests = 0 (no successor ORI anywhere under this name
#     has any real activity - rules out Camden-style consolidations)
#
# This is the defensible "likely genuine non-reporting" list - 77 agencies,
# a conservative subset of the broader 217 (the rest are explained by a
# successor ORI or are lower-confidence non-city/small-population cases).
# Together with the 30 inactive-flagged agencies, this gives 107 agencies
# that can be confidently excluded/flagged in the densified panel - though
# note this only resolves WHOLE-WINDOW zero agencies, not month-level
# gaps for agencies with partial reporting (see densification limitations).
# ---------------------------------------------------------------------------
con.sql("""
WITH city_totals AS (
    SELECT city_name,
           SUM(COALESCE(a.total_custodial, 0) + COALESCE(gb.group_b_arrests, 0)) AS city_total_arrests
    FROM bh_db.nj_batch_header bh
    LEFT JOIN (SELECT ori, SUM(custodial_arrests) AS total_custodial FROM nibrs_agency_month GROUP BY ori) a ON bh.ori = a.ori
    LEFT JOIN nibrs_group_b_agency gb ON bh.ori = gb.ori
    GROUP BY city_name
)
SELECT bh.ori, bh.city_name, bh.agency_indicator,
       TRY_CAST(bh.population_current_1 AS BIGINT) AS population
FROM bh_db.nj_batch_header bh
LEFT JOIN (SELECT ori, SUM(custodial_arrests) AS total_custodial FROM nibrs_agency_month GROUP BY ori) a ON bh.ori = a.ori
LEFT JOIN nibrs_group_b_agency gb ON bh.ori = gb.ori
JOIN city_totals ct ON bh.city_name = ct.city_name
WHERE COALESCE(a.total_custodial, 0) = 0 AND COALESCE(gb.group_b_arrests, 0) = 0
  AND (bh.agency_inactive_dt IS NULL OR TRIM(bh.agency_inactive_dt) = '')
  AND bh.agency_indicator = '1'
  AND TRY_CAST(bh.population_current_1 AS BIGINT) > 5000
  AND ct.city_total_arrests = 0
ORDER BY population DESC
""").show()


# ---------------------------------------------------------------------------
# Export: write the full audit trail for the 77 final candidates to CSV,
# including every sibling ORI under the same city_name for context (every
# sibling will show 0/0 arrests by construction, since city_total_arrests
# was required to be 0 - this makes that guarantee visibly checkable rather
# than just asserted). row_type marks which rows are the actual flagged
# candidates vs. sibling context.
# ---------------------------------------------------------------------------
con.sql("""
COPY (
    WITH city_totals AS (
        SELECT bh.city_name,
               SUM(COALESCE(a.total_custodial, 0) + COALESCE(gb.group_b_arrests, 0)) AS city_total_arrests
        FROM bh_db.nj_batch_header bh
        LEFT JOIN (SELECT ori, SUM(custodial_arrests) AS total_custodial FROM nibrs_agency_month GROUP BY ori) a ON bh.ori = a.ori
        LEFT JOIN nibrs_group_b_agency gb ON bh.ori = gb.ori
        GROUP BY bh.city_name
    ),
    final_candidates AS (
        SELECT bh.ori, bh.city_name
        FROM bh_db.nj_batch_header bh
        LEFT JOIN (SELECT ori, SUM(custodial_arrests) AS total_custodial FROM nibrs_agency_month GROUP BY ori) a ON bh.ori = a.ori
        LEFT JOIN nibrs_group_b_agency gb ON bh.ori = gb.ori
        JOIN city_totals ct ON bh.city_name = ct.city_name
        WHERE COALESCE(a.total_custodial, 0) = 0 AND COALESCE(gb.group_b_arrests, 0) = 0
          AND (bh.agency_inactive_dt IS NULL OR TRIM(bh.agency_inactive_dt) = '')
          AND bh.agency_indicator = '1'
          AND TRY_CAST(bh.population_current_1 AS BIGINT) > 5000
          AND ct.city_total_arrests = 0
    )
    SELECT bh.city_name, bh.ori, bh.agency_indicator, bh.agency_inactive_dt,
           TRY_CAST(bh.population_current_1 AS BIGINT) AS population,
           COALESCE(a.total_custodial, 0) AS custodial_arrests,
           COALESCE(gb.group_b_arrests, 0) AS group_b_arrests,
           CASE WHEN fc.ori IS NOT NULL THEN 'FLAGGED_CANDIDATE' ELSE 'sibling_context' END AS row_type
    FROM bh_db.nj_batch_header bh
    LEFT JOIN (SELECT ori, SUM(custodial_arrests) AS total_custodial FROM nibrs_agency_month GROUP BY ori) a ON bh.ori = a.ori
    LEFT JOIN nibrs_group_b_agency gb ON bh.ori = gb.ori
    LEFT JOIN final_candidates fc ON bh.ori = fc.ori
    WHERE bh.city_name IN (SELECT city_name FROM final_candidates)
    ORDER BY bh.city_name, row_type, population DESC
) TO 'data/processed/nj_zero_reporting_candidates_full_context.csv' (HEADER, DELIMITER ',')
""")