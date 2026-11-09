-- 01 Market size and whitespace by country.
-- REAL: OECD angioplasty counts (pci_*), population. ESTIMATE: market value (real PCI x assumed devices per PCI x assumed price).
-- SIMULATED: our revenue. Share = our last-12-month revenue / estimated 2026 market value.
-- Whitespace (untapped potential) = market value x benchmark share - our revenue, floored at 0.
-- Benchmark share = 75th percentile of country shares: what our better countries already achieve.

CREATE OR REPLACE VIEW v_market_2026 AS
SELECT iso3,
       sum(market_value_eur) AS market_value_eur,
       sum(market_units)     AS market_units
FROM market_size
WHERE year = 2026
GROUP BY iso3;

CREATE OR REPLACE VIEW v_l12m AS            -- last 12 months (Nov 2025 - Oct 2026) and the 12 months before
SELECT s.iso3,
       sum(revenue_eur) FILTER (WHERE s.month >  c.as_of_month - INTERVAL 12 MONTH)                       AS revenue_l12m,
       sum(revenue_eur) FILTER (WHERE s.month <= c.as_of_month - INTERVAL 12 MONTH
                                  AND s.month >  c.as_of_month - INTERVAL 24 MONTH)                        AS revenue_p12m
FROM sales s CROSS JOIN calendar c
GROUP BY s.iso3;

CREATE OR REPLACE VIEW v_whitespace AS
WITH base AS (
    SELECT co.iso3, co.country, co.region, co.subregion,
           co.pci_year, co.pci_procedures, co.pci_per_100k, co.pci_cagr, co.population,
           m.market_value_eur, l.revenue_l12m, l.revenue_p12m,
           l.revenue_l12m / m.market_value_eur AS share_value
    FROM countries co
    JOIN v_market_2026 m USING (iso3)
    JOIN v_l12m l USING (iso3)
), bench AS (
    SELECT quantile_cont(share_value, 0.75) AS benchmark_share FROM base
)
SELECT b.*,
       bench.benchmark_share,
       greatest(b.market_value_eur * bench.benchmark_share - b.revenue_l12m, 0) AS untapped_potential_eur,
       b.revenue_l12m / b.revenue_p12m - 1 AS revenue_growth_l12m
FROM base b CROSS JOIN bench;

-- output: 01_market_whitespace
SELECT *,
       rank() OVER (ORDER BY untapped_potential_eur DESC)                         AS potential_rank,
       untapped_potential_eur / sum(untapped_potential_eur) OVER ()               AS potential_share,
       CASE WHEN share_value >= benchmark_share THEN 'Defend: share at benchmark'
            WHEN market_value_eur >= median(market_value_eur) OVER () THEN 'Invest: big market, low share'
            ELSE 'Develop selectively: small market, low share' END               AS quadrant
FROM v_whitespace
ORDER BY untapped_potential_eur DESC;

-- output: 01_market_trend
-- REAL procedure counts by year (2015 onwards) for the trend chart
SELECT ms.iso3, co.country, co.region, ms.year, ms.pci_procedures, ms.pci_per_100k, ms.population
FROM read_csv_auto('data/clean/market_series.csv') ms
JOIN countries co USING (iso3)
WHERE ms.pci_procedures IS NOT NULL AND ms.year >= 2015
ORDER BY ms.iso3, ms.year;
