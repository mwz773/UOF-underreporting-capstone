import duckdb

duckdb.sql("""
  DESCRIBE SELECT * FROM read_csv('/Users/zhangmandy/repos/UOF-underreporting-capstone/data/raw/nibrs/39868-0005-Data.tsv',
    delim='\t', header=true, all_varchar=true)
""").show()
