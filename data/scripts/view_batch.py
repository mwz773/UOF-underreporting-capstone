import duckdb

con = duckdb.connect("data/nibrs.duckdb")
con.sql("ATTACH 'nibrs.duckdb' AS bh_db")

# Finding: 30 NJ agencies shown to have the DEC-1-2024 inactive date at time of building data extract files. All of them have 0 group A and 0 Group B arrests.
con.sql("""
SELECT bh.ori, bh.agency_inactive_dt,
       COALESCE(a.total_custodial, 0) AS custodial_arrests,
       COALESCE(gb.group_b_arrests, 0) AS group_b_arrests
FROM bh_db.nj_batch_header bh
LEFT JOIN (SELECT ori, SUM(custodial_arrests) AS total_custodial FROM nibrs_agency_month GROUP BY ori) a
       ON bh.ori = a.ori
LEFT JOIN nibrs_group_b_agency gb ON bh.ori = gb.ori
WHERE bh.agency_inactive_dt = '01-DEC-2024'
ORDER BY custodial_arrests DESC
""").show()

# Finding: 247 out of 690 show up as having zero arrests records of any kind. only 30 flagged inactive, 217 agencies are flagged as active but not reporting any arrests.
con.sql("""
SELECT bh.ori, bh.agency_inactive_dt,
       COALESCE(a.total_custodial, 0) AS custodial_arrests,
       COALESCE(gb.group_b_arrests, 0) AS group_b_arrests
FROM bh_db.nj_batch_header bh
LEFT JOIN (SELECT ori, SUM(custodial_arrests) AS total_custodial FROM nibrs_agency_month GROUP BY ori) a
       ON bh.ori = a.ori
LEFT JOIN nibrs_group_b_agency gb ON bh.ori = gb.ori
WHERE a.ori IS NULL AND gb.ori IS NULL
""").show()

# How big are these departments that are not reporting?
# Finding: some of these are pretty big! population group 30 are cities with 100,000=249,999 people, group 20 are cities with 50,000-99,000 people.
con.sql("""
SELECT bh.ori, bh.population_group, bh.population_current_1
FROM bh_db.nj_batch_header bh
LEFT JOIN (SELECT ori, SUM(custodial_arrests) AS total_custodial FROM nibrs_agency_month GROUP BY ori) a
       ON bh.ori = a.ori
LEFT JOIN nibrs_group_b_agency gb ON bh.ori = gb.ori
WHERE a.ori IS NULL AND gb.ori IS NULL
  AND (bh.agency_inactive_dt IS NULL OR TRIM(bh.agency_inactive_dt) = '')
ORDER BY TRY_CAST(bh.population_current_1 AS BIGINT) DESC
""").show()


# Finding: City names with populations greater than 25,000
con.sql("""
SELECT bh.ori, bh.city_name, bh.population_group, bh.population_current_1,
FROM bh_db.nj_batch_header bh
LEFT JOIN (SELECT ori, SUM(custodial_arrests) AS total_custodial FROM nibrs_agency_month GROUP BY ori) a
       ON bh.ori = a.ori
LEFT JOIN nibrs_group_b_agency gb ON bh.ori = gb.ori
WHERE a.ori IS NULL AND gb.ori IS NULL
  AND (bh.agency_inactive_dt IS NULL OR TRIM(bh.agency_inactive_dt) = '')
  AND TRY_CAST(bh.population_current_1 AS BIGINT) > 25000
ORDER BY TRY_CAST(bh.population_current_1 AS BIGINT) DESC
""").show()

# Finding: Camden, which reported zero arrests, was found under a different ORI of same city name having REPORTED arrests -- Camden City PD became Camden County PD
con.sql("""
SELECT bh.ori, bh.city_name, bh.population_current_1,
       COALESCE(a.total_custodial, 0) AS custodial_arrests,
       COALESCE(gb.group_b_arrests, 0) AS group_b_arrests
FROM bh_db.nj_batch_header bh
LEFT JOIN (SELECT ori, SUM(custodial_arrests) AS total_custodial FROM nibrs_agency_month GROUP BY ori) a
       ON bh.ori = a.ori
LEFT JOIN nibrs_group_b_agency gb ON bh.ori = gb.ori
WHERE bh.city_name LIKE '%CAMDEN%'
""").show()


# create table showing duplicate city names and the arrests data
con.sql("""
COPY (
    WITH multi_ori_cities AS (
        SELECT city_name
        FROM bh_db.nj_batch_header
        WHERE agency_inactive_dt IS NULL OR TRIM(agency_inactive_dt) = ''
        GROUP BY city_name
        HAVING COUNT(*) > 1
    )
    SELECT bh.city_name, bh.ori,
           TRY_CAST(bh.population_current_1 AS BIGINT) AS population,
           COALESCE(a.total_custodial, 0) AS custodial_arrests,
           COALESCE(gb.group_b_arrests, 0) AS group_b_arrests
    FROM bh_db.nj_batch_header bh
    LEFT JOIN (SELECT ori, SUM(custodial_arrests) AS total_custodial FROM nibrs_agency_month GROUP BY ori) a
           ON bh.ori = a.ori
    LEFT JOIN nibrs_group_b_agency gb ON bh.ori = gb.ori
    WHERE bh.city_name IN (SELECT city_name FROM multi_ori_cities)
    ORDER BY bh.city_name, custodial_arrests DESC
) TO 'data/interim/nj_multi_ori_cities_review.csv' (HEADER, DELIMITER ',')
""")


con.sql("""
WITH city_totals AS (
    SELECT bh.city_name,
           SUM(COALESCE(a.total_custodial, 0) + COALESCE(gb.group_b_arrests, 0)) AS city_total_arrests
    FROM bh_db.nj_batch_header bh
    LEFT JOIN (SELECT ori, SUM(custodial_arrests) AS total_custodial FROM nibrs_agency_month GROUP BY ori) a
           ON bh.ori = a.ori
    LEFT JOIN nibrs_group_b_agency gb ON bh.ori = gb.ori
    WHERE bh.agency_inactive_dt IS NULL OR TRIM(bh.agency_inactive_dt) = ''
    GROUP BY bh.city_name
)
SELECT bh.ori, bh.city_name,
       TRY_CAST(bh.population_current_1 AS BIGINT) AS population,
       COALESCE(a.total_custodial, 0) AS custodial_arrests,
       COALESCE(gb.group_b_arrests, 0) AS group_b_arrests
FROM bh_db.nj_batch_header bh
LEFT JOIN (SELECT ori, SUM(custodial_arrests) AS total_custodial FROM nibrs_agency_month GROUP BY ori) a
       ON bh.ori = a.ori
LEFT JOIN nibrs_group_b_agency gb ON bh.ori = gb.ori
JOIN city_totals ct ON bh.city_name = ct.city_name
WHERE COALESCE(a.total_custodial, 0) = 0
  AND COALESCE(gb.group_b_arrests, 0) = 0
  AND TRY_CAST(bh.population_current_1 AS BIGINT) > 5000
  AND ct.city_total_arrests > 0
ORDER BY TRY_CAST(bh.population_current_1 AS BIGINT) DESC
""").show()


con.sql("""
WITH all_cities AS (
    SELECT city_name
    FROM bh_db.nj_batch_header
    GROUP BY city_name
    HAVING COUNT(*) > 1
)
SELECT bh.city_name, bh.ori, bh.agency_inactive_dt,
       TRY_CAST(bh.population_current_1 AS BIGINT) AS population,
       COALESCE(a.total_custodial, 0) AS custodial_arrests,
       COALESCE(gb.group_b_arrests, 0) AS group_b_arrests
FROM bh_db.nj_batch_header bh
LEFT JOIN (SELECT ori, SUM(custodial_arrests) AS total_custodial FROM nibrs_agency_month GROUP BY ori) a
       ON bh.ori = a.ori
LEFT JOIN nibrs_group_b_agency gb ON bh.ori = gb.ori
WHERE bh.city_name IN (SELECT city_name FROM all_cities)
ORDER BY bh.city_name, custodial_arrests DESC
""").show()