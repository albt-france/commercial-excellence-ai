-- 05 Forecast inputs (SIMULATED data): monthly revenue by country with the same month last year and the
-- trailing-12-month growth, i.e. everything the seasonal forecast in the notebook needs.
--   forecast(month m) = revenue(m - 12 months) x growth factor, growth factor = last 12 months / the 12 months before.

-- output: 05_forecast_inputs
WITH m AS (
    SELECT month, iso3, sum(revenue_eur) AS revenue_eur FROM sales GROUP BY ALL
), grid AS (                                 -- every country x month, zeros where nothing was invoiced
    SELECT c.iso3, d.month, coalesce(m.revenue_eur, 0) AS revenue_eur
    FROM countries c CROSS JOIN (SELECT DISTINCT month FROM sales) d
    LEFT JOIN m ON m.iso3 = c.iso3 AND m.month = d.month
)
SELECT g.iso3, g.month, g.revenue_eur,
       lag(g.revenue_eur, 12) OVER w                                                   AS revenue_ly,
       sum(g.revenue_eur) OVER (w ROWS BETWEEN 11 PRECEDING AND CURRENT ROW)            AS revenue_t12m,
       sum(g.revenue_eur) OVER (w ROWS BETWEEN 23 PRECEDING AND 12 PRECEDING)           AS revenue_t12m_ly,
       t.target_eur
FROM grid g
LEFT JOIN (SELECT month, iso3, sum(target_eur) AS target_eur FROM targets GROUP BY ALL) t USING (iso3, month)
WINDOW w AS (PARTITION BY g.iso3 ORDER BY g.month)
ORDER BY g.iso3, g.month;
