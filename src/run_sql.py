"""Load data/clean into a DuckDB database, then run every query in sql/ and save the results to data/output/.

Usage:  python src/run_sql.py
- data/commercial.duckdb is rebuilt on every run. The AI scripts (ai/) open it in READ-ONLY mode.
- A .sql file can hold several statements. Each result to save is preceded by a line
  "-- output: <name>" and is written to data/output/<name>.csv.
"""
import re
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
CLEAN, OUT, SQL = ROOT / "data" / "clean", ROOT / "data" / "output", ROOT / "sql"
DB = ROOT / "data" / "commercial.duckdb"
OUT.mkdir(exist_ok=True)
DB.unlink(missing_ok=True)

con = duckdb.connect(str(DB))
TABLES = {  # table: (file, explicit column types where auto-detection could guess wrong)
    "countries": "countries.csv", "products": "products.csv", "accounts": "accounts.csv",
    "market_size": "market_size.csv", "sales": "sales.csv", "targets": "targets.csv",
}
for t, f in TABLES.items():
    con.execute(f"CREATE TABLE {t} AS SELECT * FROM read_csv_auto('{(CLEAN / f).as_posix()}', header = true)")
# analysis calendar: the data is "as of" the last invoiced month
con.execute("""
CREATE TABLE calendar AS
SELECT max(month) AS as_of_month,
       CAST(date_trunc('year', max(month)) AS DATE) AS ytd_start,
       CAST(max(month) - INTERVAL 1 YEAR AS DATE) AS ly_as_of_month,
       CAST(date_trunc('year', max(month)) - INTERVAL 1 YEAR AS DATE) AS ly_ytd_start
FROM sales""")

for q in sorted(SQL.glob("*.sql")):
    text = q.read_text(encoding="utf-8")
    parts = re.split(r"^-- output: *(\S+) *$", text, flags=re.M)
    if parts[0].strip():                                   # setup statements (views) before the first output
        con.execute(parts[0])
    for name, body in zip(parts[1::2], parts[2::2]):
        df = con.execute(body).df()
        df.to_csv(OUT / f"{name}.csv", index=False)
        print(f"== {q.name} -> {name}.csv: {len(df)} rows")
con.close()
print(f"database: {DB}")
