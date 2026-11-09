-- 04 Accounts: concentration, segments and risk alerts (SIMULATED data).
-- A complete account x month grid (zeros where nothing was invoiced) lets window functions compare like with like:
--   rolling 3 months = this month + the 2 before; same 3 months last year = LAG 12 of the rolling sum.
-- Risk alert: last 3 months at least 30% below the same 3 months last year, on an account that made at least
-- EUR 30k in those 3 months last year. Lost: nothing invoiced in the last 3 months.

CREATE OR REPLACE VIEW v_account_month AS
WITH grid AS (
    SELECT a.account_id, a.iso3, m.month
    FROM accounts a
    CROSS JOIN (SELECT DISTINCT month FROM sales) m
), rev AS (
    SELECT account_id, month, sum(revenue_eur) AS revenue_eur FROM sales GROUP BY ALL
)
SELECT g.account_id, g.iso3, g.month, coalesce(r.revenue_eur, 0) AS revenue_eur
FROM grid g LEFT JOIN rev r USING (account_id, month);

CREATE OR REPLACE VIEW v_account_rolling AS
WITH rolling AS (                -- step 1: rolling sums (window functions cannot be nested, hence two steps)
    SELECT *,
           sum(revenue_eur) OVER (PARTITION BY account_id ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)  AS rev_3m,
           sum(revenue_eur) OVER (PARTITION BY account_id ORDER BY month ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS rev_12m
    FROM v_account_month
)
SELECT *,                        -- step 2: the same rolling sums 12 months earlier
       lag(rev_3m, 12)  OVER (PARTITION BY account_id ORDER BY month) AS rev_3m_ly,
       lag(rev_12m, 12) OVER (PARTITION BY account_id ORDER BY month) AS rev_12m_ly
FROM rolling;

CREATE OR REPLACE VIEW v_accounts AS
WITH last AS (
    SELECT r.* FROM v_account_rolling r WHERE r.month = (SELECT as_of_month FROM calendar)
), first_sale AS (
    SELECT account_id, min(month) AS first_invoice FROM sales GROUP BY account_id
), prev3 AS (     -- the 3 months before the last 3 (sequential view of the trend)
    SELECT account_id, rev_3m AS rev_prev_3m FROM v_account_rolling
    WHERE month = (SELECT as_of_month - INTERVAL 3 MONTH FROM calendar)
)
SELECT l.account_id, a.account_name, l.iso3, co.country, co.region, a.account_type, f.first_invoice,
       l.rev_12m AS revenue_l12m, l.rev_12m_ly AS revenue_p12m,
       l.rev_3m AS revenue_l3m, l.rev_3m_ly AS revenue_l3m_ly, p.rev_prev_3m,
       l.rev_12m / nullif(l.rev_12m_ly, 0) - 1 AS growth_l12m,
       l.rev_3m / nullif(l.rev_3m_ly, 0) - 1   AS growth_l3m,
       f.first_invoice >= DATE '2025-01-01'    AS is_new_account,
       CASE WHEN l.rev_3m_ly >= 30000 AND l.rev_3m = 0 THEN 'Lost'
            WHEN l.rev_3m_ly >= 30000 AND l.rev_3m <= 0.7 * l.rev_3m_ly THEN 'At risk'
            ELSE 'OK' END AS risk_flag
FROM last l
JOIN accounts a USING (account_id)
JOIN countries co ON co.iso3 = l.iso3
LEFT JOIN first_sale f USING (account_id)
LEFT JOIN prev3 p USING (account_id)
WHERE l.rev_12m > 0 OR l.rev_12m_ly > 0;

-- output: 04_accounts
WITH ranked AS (
    SELECT *,
           row_number() OVER (ORDER BY revenue_l12m DESC)                                        AS revenue_rank,
           sum(revenue_l12m) OVER (ORDER BY revenue_l12m DESC ROWS UNBOUNDED PRECEDING)
             / sum(revenue_l12m) OVER ()                                                          AS cum_revenue_share,
           percent_rank() OVER (ORDER BY revenue_l12m DESC)                                      AS size_percentile
    FROM v_accounts
)
SELECT *,
       CASE WHEN is_new_account THEN '5 · New (since 2025)'
            WHEN size_percentile < 0.2 AND growth_l12m >= 0 THEN '1 · Big & growing: protect'
            WHEN size_percentile < 0.2 THEN '2 · Big & declining: defend'
            WHEN growth_l12m >= 0.05 THEN '3 · Smaller & growing: develop'
            ELSE '4 · Smaller & flat or declining: serve efficiently' END AS segment
FROM ranked
ORDER BY revenue_rank;

-- output: 04_account_rolling_at_risk
-- monthly rolling-3-month revenue vs last year for the flagged accounts (chart of the alert)
SELECT r.account_id, r.month, r.rev_3m, r.rev_3m_ly
FROM v_account_rolling r
JOIN v_accounts a USING (account_id)
WHERE a.risk_flag <> 'OK' AND r.month >= DATE '2025-01-01'
ORDER BY r.account_id, r.month;
