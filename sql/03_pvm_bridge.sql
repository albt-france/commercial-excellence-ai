-- 03 Price-volume-mix bridge, Jan-Oct 2025 -> Jan-Oct 2026 (SIMULATED data).
-- Cells = product lines within a country. For each country c (P = revenue / units, 0 = last year, 1 = this year):
--   Volume = (Q1_c - Q0_c) x P0avg_c                    P0avg_c = R0_c / Q0_c (last year's average price in c)
--   Mix    = sum_i Q1_i x P0_i  -  Q1_c x P0avg_c       (selling more of the expensive lines raises revenue)
--   Price  = sum_i Q1_i x (P1_i - P0_i)                 (same units, new price)
-- Volume + Mix + Price = R1_c - R0_c exactly. The total bridge is the sum of the country bridges,
-- so it closes too (country mix is part of each country's volume). A line sold in only one of the two
-- periods has no price effect (P0_i := P1_i if Q0_i = 0): all its revenue counts as volume / mix.

CREATE OR REPLACE VIEW v_pvm_cells AS
WITH periods AS (
    SELECT s.iso3, s.product_id,
           sum(units)       FILTER (WHERE s.month BETWEEN c.ly_ytd_start AND c.ly_as_of_month) AS q0,
           sum(revenue_eur) FILTER (WHERE s.month BETWEEN c.ly_ytd_start AND c.ly_as_of_month) AS r0,
           sum(units)       FILTER (WHERE s.month >= c.ytd_start) AS q1,
           sum(revenue_eur) FILTER (WHERE s.month >= c.ytd_start) AS r1
    FROM sales s CROSS JOIN calendar c
    GROUP BY s.iso3, s.product_id
)
SELECT iso3, product_id,
       coalesce(q0, 0) AS q0, coalesce(r0, 0) AS r0, coalesce(q1, 0) AS q1, coalesce(r1, 0) AS r1,
       CASE WHEN coalesce(q0, 0) > 0 THEN r0 / q0 ELSE r1 / q1 END AS p0,
       CASE WHEN coalesce(q1, 0) > 0 THEN r1 / q1 ELSE r0 / q0 END AS p1
FROM periods;

CREATE OR REPLACE VIEW v_pvm_country AS
WITH c AS (
    SELECT iso3,
           sum(q0) AS q0, sum(r0) AS r0, sum(q1) AS q1, sum(r1) AS r1,
           sum(q1 * p0) AS r1_at_p0,                     -- this year's units at last year's prices
           sum(q1 * (p1 - p0)) AS price_effect
    FROM v_pvm_cells GROUP BY iso3
)
SELECT iso3, q0, r0, q1, r1,
       (q1 - q0) * (r0 / q0)            AS volume_effect,
       r1_at_p0 - q1 * (r0 / q0)        AS mix_effect,
       price_effect,
       r1 - r0                          AS total_change
FROM c;

-- output: 03_pvm_country
SELECT p.iso3, co.country, co.region, p.r0 AS revenue_ly, p.r1 AS revenue_cy,
       p.volume_effect, p.mix_effect, p.price_effect, p.total_change,
       p.volume_effect + p.mix_effect + p.price_effect - p.total_change AS closure_check   -- must be 0
FROM v_pvm_country p JOIN countries co USING (iso3)
ORDER BY p.total_change;

-- output: 03_pvm_total
-- the five bars of the waterfall, in display order
WITH t AS (SELECT sum(r0) r0, sum(volume_effect) v, sum(mix_effect) m, sum(price_effect) p, sum(r1) r1 FROM v_pvm_country)
SELECT 1 AS step_order, 'Revenue Jan-Oct 2025' AS step, r0 AS value, 'total' AS kind FROM t
UNION ALL SELECT 2, 'Volume', v, 'effect' FROM t
UNION ALL SELECT 3, 'Mix', m, 'effect' FROM t
UNION ALL SELECT 4, 'Price', p, 'effect' FROM t
UNION ALL SELECT 5, 'Revenue Jan-Oct 2026', r1, 'total' FROM t
ORDER BY step_order;

-- output: 03_pvm_product
-- price effect by product line (sum over countries) and units growth
SELECT c.product_id, pr.product_line,
       sum(c.r0) AS revenue_ly, sum(c.r1) AS revenue_cy,
       sum(c.q1) / sum(c.q0) - 1 AS units_growth,
       sum(c.q1 * (c.p1 - c.p0)) AS price_effect,
       sum(c.q1 * (c.p1 - c.p0)) / sum(c.q1 * c.p0) AS price_change_pct     -- price index at this year's units
FROM v_pvm_cells c JOIN products pr USING (product_id)
GROUP BY c.product_id, pr.product_line
ORDER BY price_effect;
