import duckdb

# Replacing header codes with names

BATCH_RENAME = {
    "BH001": "segment_level",    
    "BH002": "num_state_cd",
    "BH003": "ori",
    "BH005": "data_ori_added",
    "BH006": "data_ori_went_nibrs",
    "BH007": "city_name",
    "BH008": "state_abr",
    "BH009": "population_group",
    "BH010": "country_div",
    "BH011": "country_region",
    "BH012": "agency_indicator",
    "BH016": "judicial_district",
    "BH018": "agency_inactive_dt",
    "BH019": "population_current_1",


}



con = duckdb.connect("nibrs.duckdb")

sel = ", ".join(f'"{old}" AS {new}' for old, new in BATCH_RENAME.items())
con.sql(f"""
CREATE OR REPLACE TABLE stg_batch_header AS
SELECT {sel}, FIPS_STATE
FROM read_csv('/Users/zhangmandy/repos/UOF-underreporting-capstone/data/raw/nibrs/39868-0001-Data.tsv', delim='\t', header=true, all_varchar=true)
""")

con.sql("""
CREATE OR REPLACE TABLE nj_batch_header AS
SELECT * FROM stg_batch_header WHERE FIPS_STATE = '34'
""")
con.sql("COPY nj_batch_header TO 'data/interim/nj_batch_header.parquet'")


