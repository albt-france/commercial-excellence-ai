"""Write ai/eval_questions.csv: 30 core business questions + 10 harder "stress" questions, each with a
reference SQL query written by hand.
The reference answer of each question is the result of its gold SQL (computed in ai/run_eval.py).

Usage:  python ai/build_eval_questions.py
"""
import csv
from pathlib import Path

YTD = "month BETWEEN DATE '2026-01-01' AND DATE '2026-10-01'"
LY = "month BETWEEN DATE '2025-01-01' AND DATE '2025-10-01'"
Q = [
    # id, category, question, gold SQL
    ("simple", "What was total revenue year to date?",
     f"SELECT sum(revenue_eur) AS revenue FROM sales WHERE {YTD}"),
    ("target", "What is year-to-date revenue versus target, as a percentage?",
     f"SELECT (SELECT sum(revenue_eur) FROM sales WHERE {YTD}) / (SELECT sum(target_eur) FROM targets WHERE {YTD}) - 1 AS vs_target"),
    ("simple", "How much revenue did we make in 2025?",
     "SELECT sum(revenue_eur) AS revenue FROM sales WHERE year(month) = 2025"),
    ("ranking", "Which country had the highest revenue year to date?",
     f"SELECT c.country, sum(s.revenue_eur) AS revenue FROM sales s JOIN countries c USING (iso3) WHERE {YTD} GROUP BY 1 ORDER BY 2 DESC LIMIT 1"),
    ("target", "Which country missed target most in Q3?",
     "WITH r AS (SELECT iso3, sum(revenue_eur) rev FROM sales WHERE month BETWEEN DATE '2026-07-01' AND DATE '2026-09-01' GROUP BY 1), "
     "t AS (SELECT iso3, sum(target_eur) tgt FROM targets WHERE month BETWEEN DATE '2026-07-01' AND DATE '2026-09-01' GROUP BY 1) "
     "SELECT c.country, r.rev - t.tgt AS gap FROM r JOIN t USING (iso3) JOIN countries c USING (iso3) ORDER BY gap LIMIT 1"),
    ("growth", "Which product line grew fastest year to date versus the same period last year?",
     f"SELECT p.product_line, sum(revenue_eur) FILTER (WHERE {YTD}) / sum(revenue_eur) FILTER (WHERE {LY}) - 1 AS growth "
     "FROM sales s JOIN products p USING (product_id) GROUP BY 1 ORDER BY 2 DESC LIMIT 1"),
    ("simple", "What was revenue in the APAC region in Q2?",
     "SELECT sum(revenue_eur) AS revenue FROM sales s JOIN countries c USING (iso3) "
     "WHERE c.region = 'APAC' AND month BETWEEN DATE '2026-04-01' AND DATE '2026-06-01'"),
    ("target", "List the three countries with the largest gap to target year to date.",
     f"WITH r AS (SELECT iso3, sum(revenue_eur) rev FROM sales WHERE {YTD} GROUP BY 1), "
     f"t AS (SELECT iso3, sum(target_eur) tgt FROM targets WHERE {YTD} GROUP BY 1) "
     "SELECT c.country, r.rev - t.tgt AS gap FROM r JOIN t USING (iso3) JOIN countries c USING (iso3) ORDER BY gap LIMIT 3"),
    ("target", "How many countries are below target year to date?",
     f"WITH r AS (SELECT iso3, sum(revenue_eur) rev FROM sales WHERE {YTD} GROUP BY 1), "
     f"t AS (SELECT iso3, sum(target_eur) tgt FROM targets WHERE {YTD} GROUP BY 1) "
     "SELECT count(*) AS countries_below_target FROM r JOIN t USING (iso3) WHERE r.rev < t.tgt"),
    ("price", "What is the average net price of coronary stents in Germany year to date, and in the same period last year?",
     f"SELECT sum(revenue_eur) FILTER (WHERE {YTD}) / sum(units) FILTER (WHERE {YTD}) AS price_ytd, "
     f"sum(revenue_eur) FILTER (WHERE {LY}) / sum(units) FILTER (WHERE {LY}) AS price_ly "
     "FROM sales WHERE iso3 = 'DEU' AND product_id = 'DES'"),
    ("market", "What was our market share in France in 2025?",
     "SELECT (SELECT sum(revenue_eur) FROM sales WHERE iso3 = 'FRA' AND year(month) = 2025) / "
     "(SELECT sum(market_value_eur) FROM market_size WHERE iso3 = 'FRA' AND year = 2025) AS market_share"),
    ("market", "Which country has the most coronary angioplasties per 100,000 inhabitants?",
     "SELECT country, pci_per_100k FROM countries ORDER BY pci_per_100k DESC LIMIT 1"),
    ("accounts", "How many active accounts did we have in October 2026?",
     "SELECT count(DISTINCT account_id) AS active_accounts FROM sales WHERE month = DATE '2026-10-01' AND revenue_eur > 0"),
    ("accounts", "How many new accounts have we opened since January 2025?",
     "SELECT count(*) AS new_accounts FROM (SELECT account_id, min(month) AS first_invoice FROM sales GROUP BY 1) "
     "WHERE first_invoice >= DATE '2025-01-01'"),
    ("accounts", "What share of year-to-date revenue comes from new accounts?",
     "WITH f AS (SELECT account_id, min(month) AS first_invoice FROM sales GROUP BY 1) "
     f"SELECT sum(revenue_eur) FILTER (WHERE f.first_invoice >= DATE '2025-01-01') / sum(revenue_eur) AS share "
     f"FROM sales s JOIN f USING (account_id) WHERE {YTD}"),
    ("ranking", "Which account generated the most revenue year to date?",
     f"SELECT account_id, sum(revenue_eur) AS revenue FROM sales WHERE {YTD} GROUP BY 1 ORDER BY 2 DESC LIMIT 1"),
    ("simple", "What was revenue from university hospitals year to date?",
     f"SELECT sum(revenue_eur) AS revenue FROM sales s JOIN accounts a USING (account_id) "
     f"WHERE a.account_type = 'University hospital' AND {YTD}"),
    ("time", "By what percentage did revenue change from July 2026 to August 2026?",
     "SELECT sum(revenue_eur) FILTER (WHERE month = DATE '2026-08-01') / sum(revenue_eur) FILTER (WHERE month = DATE '2026-07-01') - 1 AS change FROM sales"),
    ("growth", "How many drug-coated balloons did we sell year to date, and how much did units grow versus the same period last year?",
     f"SELECT sum(units) FILTER (WHERE {YTD}) AS units_ytd, sum(units) FILTER (WHERE {YTD}) / sum(units) FILTER (WHERE {LY}) - 1 AS growth "
     "FROM sales WHERE product_id = 'DCB'"),
    ("time", "Which month of 2025 had the lowest revenue?",
     "SELECT month, sum(revenue_eur) AS revenue FROM sales WHERE year(month) = 2025 GROUP BY 1 ORDER BY 2 LIMIT 1"),
    ("target", "What is the full-year 2026 revenue target?",
     "SELECT sum(target_eur) AS target FROM targets WHERE year(month) = 2026"),
    ("target", "How much revenue is still needed in November and December to reach the 2026 target?",
     f"SELECT (SELECT sum(target_eur) FROM targets WHERE year(month) = 2026) - (SELECT sum(revenue_eur) FROM sales WHERE {YTD}) AS needed"),
    ("target", "What was the gap to target for Spain in Q2?",
     "SELECT (SELECT sum(revenue_eur) FROM sales WHERE iso3 = 'ESP' AND month BETWEEN DATE '2026-04-01' AND DATE '2026-06-01') - "
     "(SELECT sum(target_eur) FROM targets WHERE iso3 = 'ESP' AND month BETWEEN DATE '2026-04-01' AND DATE '2026-06-01') AS gap"),
    ("target", "In which product line did we miss target the most in France year to date?",
     f"WITH r AS (SELECT product_id, sum(revenue_eur) rev FROM sales WHERE iso3 = 'FRA' AND {YTD} GROUP BY 1), "
     f"t AS (SELECT product_id, sum(target_eur) tgt FROM targets WHERE iso3 = 'FRA' AND {YTD} GROUP BY 1) "
     "SELECT p.product_line, r.rev - t.tgt AS gap FROM r JOIN t USING (product_id) JOIN products p USING (product_id) ORDER BY gap LIMIT 1"),
    ("growth", "What is the revenue growth of Türkiye year to date versus the same period last year?",
     f"SELECT sum(revenue_eur) FILTER (WHERE {YTD}) / sum(revenue_eur) FILTER (WHERE {LY}) - 1 AS growth FROM sales WHERE iso3 = 'TUR'"),
    ("market", "Which country has the largest estimated market value in 2026?",
     "SELECT c.country, sum(m.market_value_eur) AS market_value FROM market_size m JOIN countries c USING (iso3) "
     "WHERE m.year = 2026 GROUP BY 1 ORDER BY 2 DESC LIMIT 1"),
    ("simple", "What percentage of year-to-date revenue comes from EMEA?",
     f"SELECT sum(revenue_eur) FILTER (WHERE c.region = 'EMEA') / sum(revenue_eur) AS emea_share "
     f"FROM sales s JOIN countries c USING (iso3) WHERE {YTD}"),
    ("accounts", "How many accounts bought drug-coated balloons this year?",
     f"SELECT count(DISTINCT account_id) AS accounts FROM sales WHERE product_id = 'DCB' AND units > 0 AND {YTD}"),
    ("accounts", "What was the average revenue per active account in 2025?",
     "SELECT sum(revenue_eur) / count(DISTINCT account_id) AS revenue_per_account FROM sales WHERE year(month) = 2025 AND revenue_eur > 0"),
    ("out of scope", "What was our revenue in Japan last year?",
     "SELECT 'cannot answer' AS answer"),
]

# STRESS set: vaguer wording, definitions the prompt does not spell out, multi-step logic.
# The gold SQL states the interpretation a Commercial Excellence analyst would use.
L3M, L3M_LY = "month BETWEEN DATE '2026-08-01' AND DATE '2026-10-01'", "month BETWEEN DATE '2025-08-01' AND DATE '2025-10-01'"
STRESS = [
    ("growth", "Which subregion grew fastest this year?",
     f"SELECT c.subregion, sum(revenue_eur) FILTER (WHERE {YTD}) / sum(revenue_eur) FILTER (WHERE {LY}) - 1 AS growth "
     "FROM sales s JOIN countries c USING (iso3) GROUP BY 1 ORDER BY 2 DESC LIMIT 1"),
    ("accounts", "What share of the hospitals that bought from us in 2024 bought nothing in 2025?",
     "WITH a24 AS (SELECT DISTINCT account_id FROM sales WHERE year(month) = 2024 AND revenue_eur > 0), "
     "a25 AS (SELECT DISTINCT account_id FROM sales WHERE year(month) = 2025 AND revenue_eur > 0) "
     "SELECT count(*) FILTER (WHERE a25.account_id IS NULL) / count(*) AS churn_rate FROM a24 LEFT JOIN a25 USING (account_id)"),
    ("accounts", "Which three hospitals lost the most revenue in the last three months compared with a year earlier?",
     f"SELECT account_id, sum(revenue_eur) FILTER (WHERE {L3M}) - sum(revenue_eur) FILTER (WHERE {L3M_LY}) AS change "
     "FROM sales GROUP BY 1 ORDER BY 2 LIMIT 3"),
    ("market", "In how many countries is our market share above 10% in 2025?",
     "WITH r AS (SELECT iso3, sum(revenue_eur) rev FROM sales WHERE year(month) = 2025 GROUP BY 1), "
     "m AS (SELECT iso3, sum(market_value_eur) mv FROM market_size WHERE year = 2025 GROUP BY 1) "
     "SELECT count(*) AS countries FROM r JOIN m USING (iso3) WHERE rev / mv > 0.10"),
    ("market", "Which product line has our highest market share across all countries in 2025?",
     "WITH r AS (SELECT product_id, sum(revenue_eur) rev FROM sales WHERE year(month) = 2025 GROUP BY 1), "
     "m AS (SELECT product_id, sum(market_value_eur) mv FROM market_size WHERE year = 2025 GROUP BY 1) "
     "SELECT p.product_line, rev / mv AS share FROM r JOIN m USING (product_id) JOIN products p USING (product_id) ORDER BY 2 DESC LIMIT 1"),
    ("time", "What was revenue last quarter?",
     "SELECT sum(revenue_eur) AS revenue FROM sales WHERE month BETWEEN DATE '2026-07-01' AND DATE '2026-09-01'"),
    ("accounts", "How many hospitals bought all six product lines this year?",
     f"SELECT count(*) AS accounts FROM (SELECT account_id FROM sales WHERE {YTD} AND units > 0 GROUP BY 1 HAVING count(DISTINCT product_id) = 6)"),
    ("simple", "What share of Germany's revenue this year comes from coronary stents?",
     f"SELECT sum(revenue_eur) FILTER (WHERE product_id = 'DES') / sum(revenue_eur) AS share FROM sales WHERE iso3 = 'DEU' AND {YTD}"),
    ("growth", "Which country added the most revenue in euros this year versus last year?",
     f"SELECT c.country, sum(revenue_eur) FILTER (WHERE {YTD}) - sum(revenue_eur) FILTER (WHERE {LY}) AS change "
     "FROM sales s JOIN countries c USING (iso3) GROUP BY 1 ORDER BY 2 DESC LIMIT 1"),
    ("target", "How did we do against target last month?",
     "SELECT (SELECT sum(revenue_eur) FROM sales WHERE month = DATE '2026-10-01') / "
     "(SELECT sum(target_eur) FROM targets WHERE month = DATE '2026-10-01') - 1 AS vs_target"),
]

out = Path(__file__).resolve().parent / "eval_questions.csv"
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["id", "set", "category", "question", "gold_sql"])
    for i, (cat, q, sql) in enumerate(Q, 1):
        w.writerow([i, "core", cat, q, sql])
    for i, (cat, q, sql) in enumerate(STRESS, len(Q) + 1):
        w.writerow([i, "stress", cat, q, sql])
print(f"{len(Q)} core + {len(STRESS)} stress questions -> {out}")
