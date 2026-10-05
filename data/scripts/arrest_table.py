import duckdb
con = duckdb.connect("data/nibrs.duckdb")

con.sql("SELECT COUNT(*) FROM arrests WHERE arrest_date IS NULL OR arrest_date = ''").show()

# checking min/max date to confirm year , counting unparsable dates (most likely group B;s daate in different columns)
con.sql("""
SELECT 
    MIN(try_strptime(TRIM(arrest_date), '%d-%b-%Y')) AS min_date,
    MAX(try_strptime(TRIM(arrest_date), '%d-%b-%Y')) AS max_date,
    COUNT(*) FILTER (WHERE try_strptime(TRIM(arrest_date), '%d-%b-%Y') IS NULL) AS unparseable
FROM arrests
""").show()


ARREST_RENAME = {
    "ORI": "ori",
    "INCNUM": "incident_num",
    "V6007": "arrest_txn_no",
    "V6006": "arrestee_seq_no",
    "V6008": "arrest_date",
    "V6009": "arrest_type",
    "V6011": "ucr_arrest_offense_code",
    "V6014": "age",
    "V6015": "sex",
    "V6016": "race",
    "V6017": "ethnicity",
    "V6019": "disposition_juvenile",
}

sel = ", ".join(f'"{old}" AS {new}' for old, new in ARREST_RENAME.items())

# Step 1: raw parsed + renamed + part label, NJ only, arrest segments only
con.sql(f"""
CREATE OR REPLACE TABLE stg_arrestee_nj AS
SELECT {sel},
    CASE WHEN SEGMENT = '06' THEN 'A'
         WHEN SEGMENT = '07' THEN 'B'
         WHEN SEGMENT = 'W6' THEN 'W'
    END AS part
FROM read_csv('/Users/zhangmandy/repos/UOF-underreporting-capstone/data/raw/nibrs/39868-0005-Data.tsv',
    delim='\t', header=true, all_varchar=true)
WHERE FIPS_STATE = '34' AND SEGMENT IN ('06', '07')
""")

# Step 2: final custodial-filtered table — this is what everything downstream uses
'''
1: On-View Arrest 
2: Summoned / Cited 
3: Taken Into Custody 
'''

con.sql("""
CREATE OR REPLACE TABLE arrests AS
SELECT *
FROM stg_arrestee_nj
WHERE (part = 'A' AND arrest_type IN ('1', '3'))
   OR (part = 'B')
""")



# --- Group A only: monthly custodial-arrest panel ---
con.sql("""
CREATE OR REPLACE TABLE nibrs_agency_month AS
SELECT
    ori,
    date_trunc('month', try_strptime(TRIM(arrest_date), '%d-%b-%Y'))::DATE AS month,
    COUNT(*) AS custodial_arrests
FROM arrests
WHERE part = 'A'
  AND try_strptime(TRIM(arrest_date), '%d-%b-%Y') IS NOT NULL
GROUP BY ori, month
ORDER BY ori, month
""")

# --- Group B: agency-level aggregate only, no month (can't be dated) ---
con.sql("""
CREATE OR REPLACE TABLE nibrs_group_b_agency AS
SELECT
    ori,
    COUNT(*) AS group_b_arrests
FROM arrests
WHERE part = 'B'
GROUP BY ori
ORDER BY ori
""")

con.sql("COPY arrests TO 'data/processed/arrests_nj_2024.parquet'")
con.sql("COPY nibrs_agency_month TO 'data/processed/nibrs_agency_month_2024.parquet'")
con.sql("COPY nibrs_group_b_agency TO 'data/processed/nibrs_group_b_agency_2024.parquet'")



# --- Sanity checks ---
con.sql("SELECT COUNT(*) AS n_agency_months, COUNT(DISTINCT ori) AS n_agencies, SUM(custodial_arrests) AS total_custodial FROM nibrs_agency_month").show()
con.sql("SELECT COUNT(DISTINCT ori) AS n_agencies, SUM(group_b_arrests) AS total_group_b FROM nibrs_group_b_agency").show()
con.sql("SELECT MIN(month) AS min_month, MAX(month) AS max_month FROM nibrs_agency_month").show()


# # Checks — now pointed at the tables that actually exist
# con.sql("SELECT COUNT(*) FROM stg_arrestee_nj").show()
# con.sql("SELECT part, COUNT(*) FROM arrests GROUP BY part").show()

# con.sql("""
# SELECT *, COUNT(*)
# FROM stg_arrestee_nj
# GROUP BY ALL
# HAVING COUNT(*) > 1
# """).show()