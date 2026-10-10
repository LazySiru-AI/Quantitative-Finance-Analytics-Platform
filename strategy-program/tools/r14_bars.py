"""First stored bar for the two symbols whose absence failed three families each.

The SELECTION.md memo attributes both shortfalls to pre-IPO gaps. That is a claim about the store,
so it is read from the store rather than from memory of when those companies listed.
"""
import duckdb

con = duckdb.connect()
for sym in ("META", "AVGO", "SPY"):
    p = f"data/store/bars/interval=1d/symbol={sym}/bars.parquet"
    r = con.execute(f"select min(ts)::date, max(ts)::date, count(*) from read_parquet('{p}')").fetchone()
    print(f"{sym:6} first={r[0]}  last={r[1]}  rows={r[2]}")
print()
for sym, a, b in (("META", "2011-05-26", "2012-06-06"), ("AVGO", "2007-10-09", "2009-03-09")):
    p = f"data/store/bars/interval=1d/symbol={sym}/bars.parquet"
    n = con.execute(
        f"select count(*) from read_parquet('{p}') where ts::date between '{a}' and '{b}'"
    ).fetchone()[0]
    print(f"{sym:6} bars inside {a}..{b}: {n}")
