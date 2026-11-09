-- 02 Sales vs target (SIMULATED data).
-- Grain of the output: month x country x product line; the YTD tables compare Jan-Oct 2026 with target and with Jan-Oct 2025.

CREATE OR REPLACE VIEW v_monthly AS
SELECT coalesce(s.month, t.month)       AS month,
       coalesce(s.iso3, t.iso3)         AS iso3,
       coalesce(s.product_id, t.product_id) AS product_id,
       coalesce(s.units, 0)             AS units,
       coalesce(s.revenue_eur, 0)       AS revenue_eur,
       t.target_eur
FROM (SELECT month, iso3, product_id, sum(units) AS units, sum(revenue_eur) AS revenue_eur
      FROM sales GROUP BY ALL) s
FULL OUTER JOIN targets t
  ON s.month = t.month AND s.iso3 = t.iso3 AND s.product_id = t.product_id
WHERE coalesce(s.month, t.month) <= (SELECT as_of_month FROM calendar);   -- no future months

-- output: 02_monthly_country_product
SELECT * FROM v_monthly ORDER BY month, iso3, product_id;

-- output: 02_ytd_country
SELECT m.iso3, co.country, co.region,
       sum(revenue_eur) FILTER (WHERE m.month >= c.ytd_start)                                          AS revenue_ytd,
       sum(target_eur)  FILTER (WHERE m.month >= c.ytd_start)                                          AS target_ytd,
       sum(revenue_eur) FILTER (WHERE m.month BETWEEN c.ly_ytd_start AND c.ly_as_of_month)             AS revenue_ytd_ly,
       revenue_ytd - target_ytd                                                                        AS gap_to_target,
       revenue_ytd / target_ytd - 1                                                                    AS vs_target_pct,
       revenue_ytd / revenue_ytd_ly - 1                                                                AS growth_yoy,
       (SELECT sum(target_eur) FROM targets t WHERE t.iso3 = m.iso3 AND year(t.month) = year(c.as_of_month)) AS target_full_year
FROM v_monthly m
JOIN countries co USING (iso3)
CROSS JOIN calendar c
GROUP BY m.iso3, co.country, co.region, c.as_of_month
ORDER BY gap_to_target;

-- output: 02_ytd_product
SELECT m.product_id, p.product_line,
       sum(revenue_eur) FILTER (WHERE m.month >= c.ytd_start)                              AS revenue_ytd,
       sum(target_eur)  FILTER (WHERE m.month >= c.ytd_start)                              AS target_ytd,
       sum(revenue_eur) FILTER (WHERE m.month BETWEEN c.ly_ytd_start AND c.ly_as_of_month) AS revenue_ytd_ly,
       revenue_ytd - target_ytd       AS gap_to_target,
       revenue_ytd / target_ytd - 1   AS vs_target_pct,
       revenue_ytd / revenue_ytd_ly - 1 AS growth_yoy
FROM v_monthly m
JOIN products p USING (product_id)
CROSS JOIN calendar c
GROUP BY m.product_id, p.product_line
ORDER BY gap_to_target;
