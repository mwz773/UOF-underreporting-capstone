import duckdb
# con = duckdb.connect("data/nibrs.duckdb")
con = duckdb.connect("nibrs.duckdb")

# structure
# con.sql("DESCRIBE nibrs_agency_month").show()
# con.sql("DESCRIBE nibrs_group_b_agency").show()
# con.sql("DESCRIBE arrests").show()
con.sql("DESCRIBE nj_batch_header").show()

con.sql("""
SELECT 
    COUNT(*) AS n_rows,
    COUNT(*) FILTER (WHERE TRIM(data_ori_added) = '' OR data_ori_added IS NULL) AS blank
FROM nj_batch_header
""").show()

con.sql("""
SELECT agency_inactive_dt, COUNT(*) AS n
FROM nj_batch_header
GROUP BY agency_inactive_dt
ORDER BY n DESC
""").show()



# # plain preview, first rows
# con.sql("SELECT * FROM nibrs_agency_month ORDER BY ori, month LIMIT 20").show()
# con.sql("SELECT * FROM nibrs_group_b_agency ORDER BY group_b_arrests DESC LIMIT 20").show()


# cols = ["incident_num","arrest_txn_no","arrestee_seq_no","arrest_date","arrest_type",
#         "ucr_arrest_offense_code","age","sex","race","ethnicity","disposition_juvenile"]

# for col in cols:
#     print(f"--- {col} ---")
#     con.sql(f"""
#         SELECT part,
#                COUNT(*) AS n,
#                COUNT(*) FILTER (WHERE TRIM({col}) = '' OR {col} IS NULL) AS blank,
#                COUNT(DISTINCT {col}) AS n_distinct
#         FROM arrests
#         GROUP BY part
#         ORDER BY part
#     """).show()


# con.sql("""
# SELECT part,
#        COUNT(*) AS n_rows,
#        COUNT(DISTINCT (ori, incident_num)) AS n_distinct_pairs
# FROM arrests
# GROUP BY part
# """).show()