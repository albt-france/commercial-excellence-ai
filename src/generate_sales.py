"""Generate the SIMULATED commercial data, calibrated on the REAL market size of each country.

Usage:  python src/generate_sales.py          (seed 42: same output on every run)
Inputs : data/clean/countries.csv (real: OECD angioplasty counts, World Bank population and health spending)
Outputs: data/clean/
  market_size.csv  ESTIMATE  country x product line x year: real PCI count x assumed devices per PCI x assumed price
  products.csv     SIMULATED product lines (generic, no brand names)
  accounts.csv     SIMULATED hospitals (fictional ids, no real hospital names)
  sales.csv        SIMULATED invoiced sales, month x account x product line, Jan 2023 - Oct 2026
  targets.csv      SIMULATED monthly targets 2024-2026, country x product line
Nothing here is Cordis data: Cordis is a private company and publishes no sales detail.
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CLEAN = ROOT / "data" / "clean"
rng = np.random.default_rng(42)

FIRST, LAST = "2023-01", "2026-10"          # data "as of" 31 Oct 2026
months = pd.period_range(FIRST, LAST, freq="M")
countries = pd.read_csv(CLEAN / "countries.csv")

# ---------------- product lines (assumptions, documented in SOURCES.md) ----------------
# devices per PCI procedure in the whole market, reference net price in Germany 2024 (EUR),
# yearly price erosion, our relative strength by line, share of hospitals that buy the line from us
PRODUCTS = pd.DataFrame([
    # id, name, family, units_per_pci, ref_price, erosion, line_strength, buy_prob
    ("DXC", "Diagnostic catheters", "Coronary", 2.5, 28, -0.010, 1.60, 0.95),
    ("GWR", "Guidewires", "Coronary", 1.6, 65, -0.010, 1.20, 0.90),
    ("PTB", "PTCA balloons", "Coronary", 1.8, 160, -0.030, 1.00, 0.85),
    ("DES", "Coronary stents", "Coronary", 1.5, 380, -0.050, 0.60, 0.70),
    ("DCB", "Drug-coated balloons", "Coronary", 0.2, 750, -0.040, 0.80, 0.45),
    ("PER", "Peripheral devices", "Endovascular", 0.35, 420, -0.020, 1.10, 0.50),
], columns=["product_id", "product_line", "family", "units_per_pci", "ref_price_eur", "price_erosion",
            "line_strength", "buy_prob"])
DCB_MARKET_GROWTH = 0.12                    # DCB use grows faster than PCI (assumption)

# ---------------- country commercial profile (SIMULATED) ----------------
# strength = our share of the market (before line multipliers) in 2024; trend = yearly change of that share
PROFILE = {  # iso3: (strength, share trend per year, planned target growth 2024-26)
    "FRA": (0.140, -0.02, 0.05), "BEL": (0.130, 0.00, 0.05), "ESP": (0.120, 0.05, 0.07), "ITA": (0.110, 0.02, 0.05),
    "CHE": (0.110, 0.01, 0.05), "NLD": (0.100, 0.00, 0.04), "ISR": (0.110, 0.02, 0.06), "AUS": (0.100, 0.02, 0.06),
    "PRT": (0.100, 0.00, 0.04), "DEU": (0.075, 0.02, 0.05), "GBR": (0.085, 0.01, 0.05), "AUT": (0.085, 0.00, 0.04),
    "SWE": (0.080, -0.01, 0.03), "KOR": (0.050, 0.10, 0.12), "NZL": (0.080, 0.00, 0.04),
    "TUR": (0.030, 0.18, 0.20), "POL": (0.045, 0.14, 0.16), "ROU": (0.045, 0.08, 0.12), "CZE": (0.055, 0.03, 0.06),
}
SOUTH, NORTH = {"ITA", "ESP", "PRT", "FRA"}, {"DEU", "AUT", "CHE", "BEL", "NLD", "GBR", "SWE", "POL", "CZE", "ROU"}


def seasonality(iso3):
    """Monthly activity index (mean 1). Quarter-end pushes, August holidays in Europe,
    Lunar New Year / Chuseok in Korea, southern-summer January in Oceania."""
    s = np.array([0.97, 0.98, 1.06, 0.98, 1.00, 1.05, 0.96, 0.80, 1.06, 1.06, 1.04, 0.90])
    if iso3 in SOUTH:
        s[7] = 0.62
    elif iso3 in {"TUR", "ISR"}:
        s[7] = 0.88
    elif iso3 == "KOR":
        s = np.array([0.95, 0.90, 1.06, 1.02, 1.03, 1.05, 1.00, 0.96, 0.95, 0.96, 1.05, 1.02])
    elif iso3 in {"AUS", "NZL"}:
        s = np.array([0.76, 0.98, 1.08, 0.97, 1.05, 1.06, 1.04, 1.05, 1.06, 1.05, 1.06, 0.86])
    return s / s.mean()


# ---------------- market size (real PCI x assumptions) ----------------
deu_hx = countries.loc[countries.iso3 == "DEU", "health_exp_per_capita_usd"].item()
countries["price_index"] = np.clip((countries.health_exp_per_capita_usd / deu_hx) ** 0.35, 0.45, 1.25).round(3)
mkt = []
for _, c in countries.iterrows():
    g = float(np.clip(c.pci_cagr, -0.02, 0.06))          # projection beyond the last real year, capped
    for year in range(2023, 2027):
        if year <= c.pci_year:
            pci = c.pci_procedures * (1 + g) ** (year - c.pci_year)   # back-cast years before last real one
            src = "real" if year == c.pci_year else "interpolated"
        else:
            pci = c.pci_procedures * (1 + g) ** (year - c.pci_year)
            src = "projected"
        for _, p in PRODUCTS.iterrows():
            units = pci * p.units_per_pci * ((1 + DCB_MARKET_GROWTH) ** (year - 2024) if p.product_id == "DCB" else 1)
            price = p.ref_price_eur * c.price_index * (1 + p.price_erosion) ** (year - 2024)
            mkt.append((c.iso3, year, p.product_id, round(pci), src, round(units), round(price, 2), round(units * price)))
market = pd.DataFrame(mkt, columns=["iso3", "year", "product_id", "pci_procedures", "pci_source",
                                    "market_units", "market_price_eur", "market_value_eur"])
# use the real yearly counts where the OECD has them (2023, 2024, 2025 for some countries)
series = pd.read_csv(CLEAN / "market_series.csv")
real = series.dropna(subset=["pci_procedures"]).set_index(["iso3", "year"])["pci_procedures"]
for i, r in market.iterrows():
    if (r.iso3, r.year) in real.index:
        k = real[(r.iso3, r.year)] / r.pci_procedures
        market.loc[i, ["pci_procedures", "market_units", "market_value_eur"]] = [
            round(real[(r.iso3, r.year)]), round(r.market_units * k), round(r.market_value_eur * k)]
        market.loc[i, "pci_source"] = "real"

# ---------------- accounts (SIMULATED) ----------------
TYPES = ["University hospital", "Public general hospital", "Private hospital", "Cardiac centre"]
acc_rows = []
for _, c in countries.iterrows():
    strength = PROFILE[c.iso3][0]
    n_core = int(np.clip(round(c.pci_procedures * strength / 420), 6, 80))
    n_new = {"TUR": 12, "POL": 4, "KOR": 4, "ROU": 3, "ESP": 3, "AUS": 2}.get(c.iso3, int(rng.integers(0, 2)))
    for k in range(n_core + n_new):
        is_new = k >= n_core
        acc_rows.append(dict(
            account_id=f"{c.iso2}-{k + 1:03d}", iso3=c.iso3,
            account_type=rng.choice(TYPES, p=[0.25, 0.40, 0.25, 0.10]),
            weight=float(rng.lognormal(0, 1.0)) * (0.35 if is_new else 1.0),
            is_new=is_new,
            start=(pd.Period("2025-01", "M") + int(rng.integers(0, 18))) if is_new else pd.Period(FIRST, "M"),
            growth=float(rng.normal(0, 0.06))))
acc = pd.DataFrame(acc_rows)
acc["account_name"] = "Hospital " + acc.account_id
core = acc[~acc.is_new]
acc["weight"] = acc.weight / acc.iso3.map(core.groupby("iso3").weight.sum())   # core accounts sum to 1 per country
acc["size_pct"] = acc.groupby("iso3").weight.rank(pct=True)
acc["discount"] = (0.04 + 0.12 * acc.size_pct).round(3)

# account events: churn in the past, competitor wins in 2026 (the "at-risk" accounts)
acc["end"] = None
acc["decline_start"] = None
acc["decline_to"] = 1.0
for iso3, n in {"FRA": 3, "ITA": 2, "GBR": 1, "DEU": 1, "NLD": 1, "BEL": 1, "AUS": 1}.items():
    big = acc[(acc.iso3 == iso3) & ~acc.is_new].sort_values("weight", ascending=False).index[1:1 + 3 * n:3]
    for i in big:   # every third large account: a competitor wins a tender in 2026
        acc.loc[i, "decline_start"] = pd.Period("2026-04", "M") + int(rng.integers(0, 5))
        acc.loc[i, "decline_to"] = float(rng.choice([0.0, 0.3, 0.5, 0.6]))
small = acc[~acc.is_new & acc.decline_start.isna() & (acc.size_pct < 0.6)].sample(10, random_state=7).index
for i in small:     # ordinary churn 2023-2025
    acc.loc[i, "end"] = pd.Period("2023-06", "M") + int(rng.integers(0, 30))

# which lines each account buys from us
buys = pd.DataFrame({p: rng.random(len(acc)) < bp for p, bp in zip(PRODUCTS.product_id, PRODUCTS.buy_prob)})
buys["DXC"] = True                                  # every account buys diagnostic catheters
biggest = acc[~acc.is_new].groupby("iso3").weight.idxmax()
buys.loc[biggest.values, :] = True                   # the largest account of each country buys every line
line_w = buys.mul(acc.weight, axis=0)
core_mask = ~acc.is_new
norm = line_w[core_mask].groupby(acc.iso3[core_mask]).sum()
line_w = line_w / norm.reindex(acc.iso3).values

# ---------------- monthly sales ----------------
mk = market.set_index(["iso3", "year", "product_id"])
seas = {c: seasonality(c) for c in countries.iso3}
pi = countries.set_index("iso3").price_index
prod = PRODUCTS.set_index("product_id")
rows = []
for m in months:
    t = (m.year - 2024) + (m.month - 1) / 12
    for i, a in acc.iterrows():
        if m < a.start or (pd.notna(a.end) and m > a.end):
            continue
        strength, trend, _ = PROFILE[a.iso3]
        act = 1.0
        if a.is_new:                                       # 6-month ramp-up
            act = min(1.0, ((m - a.start).n + 1) / 6)
        if pd.notna(a.decline_start) and m >= a.decline_start:
            k = min(1.0, ((m - a.decline_start).n + 1) / 3)  # falls over 3 months
            act *= 1 - k * (1 - a.decline_to)
        if act <= 0:
            continue
        acc_factor = act * np.exp(a.growth * t) * np.exp(np.log1p(trend) * t)
        for pid in PRODUCTS.product_id:
            w = line_w.at[i, pid]
            if w == 0:
                continue
            mu = (mk.loc[(a.iso3, m.year, pid), "market_units"] / 12 * seas[a.iso3][m.month - 1]
                  * strength * prod.at[pid, "line_strength"] * w * acc_factor * rng.lognormal(0, 0.12))
            units = int(rng.poisson(mu)) if mu < 50 else int(round(mu))
            if units == 0:
                continue
            list_price = prod.at[pid, "ref_price_eur"] * pi[a.iso3] * (1 + prod.at[pid, "price_erosion"]) ** t
            if a.iso3 == "DEU" and pid == "DES" and m.year >= 2026:
                list_price *= 0.90                          # 2026 German stent tender: -10% price
            if a.iso3 == "TUR" and m.year >= 2026:
                list_price *= 0.93                          # lira depreciation: EUR prices -7%
            price = list_price * (1 - a.discount) * rng.normal(1, 0.015)
            rows.append((m.to_timestamp(), a.account_id, a.iso3, pid, units, round(price, 2), round(units * price, 2)))
sales = pd.DataFrame(rows, columns=["month", "account_id", "iso3", "product_id", "units", "net_price_eur", "revenue_eur"])

# ---------------- targets (SIMULATED): last year's actual x (1 + planned growth), phased monthly ----------------
s = sales.assign(year=sales.month.dt.year, mon=sales.month.dt.month)
annual = s.groupby(["iso3", "product_id", "year"]).revenue_eur.sum()
profile = s.groupby(["iso3", "year", "mon"]).revenue_eur.sum()
profile = profile / profile.groupby(level=[0, 1]).transform("sum")
trows = []
for (iso3, pid, year), rev in annual.items():
    ty = year + 1
    if ty > 2026:
        continue
    growth = PROFILE[iso3][2]
    if pid == "DCB":
        growth += 0.06
    if year == 2025 and iso3 in {"TUR", "POL", "KOR", "ROU"}:
        # 2025 is a partial year for newly opened accounts: target on the run-rate of Q4 2025 instead
        q4 = s[(s.iso3 == iso3) & (s.product_id == pid) & (s.year == 2025) & (s.mon >= 10)].revenue_eur.sum()
        rev = max(rev, q4 * 4 * 0.92)
    tot = rev * (1 + growth)
    for mon in range(1, 13):
        trows.append((pd.Timestamp(ty, mon, 1), iso3, pid, round(tot * profile[(iso3, year, mon)], 2)))
targets = pd.DataFrame(trows, columns=["month", "iso3", "product_id", "target_eur"])

# ---------------- write ----------------
CLEAN.mkdir(parents=True, exist_ok=True)
market.to_csv(CLEAN / "market_size.csv", index=False)
PRODUCTS.drop(columns=["line_strength", "buy_prob"]).to_csv(CLEAN / "products.csv", index=False)
acc_out = acc.assign(first_month=acc.start.dt.to_timestamp() if hasattr(acc.start, "dt") else acc.start.map(lambda p: p.to_timestamp()))
acc_out[["account_id", "account_name", "iso3", "account_type", "first_month"]].to_csv(CLEAN / "accounts.csv", index=False)
sales.to_csv(CLEAN / "sales.csv", index=False)
# answer key: the events built into the simulation, to score the account alert (sql/04) against the truth
key = pd.concat([
    acc[acc.decline_start.notna()].assign(event="competitor win (volume falls over 3 months)",
                                          event_month=lambda d: d.decline_start.astype(str), keeps_share=lambda d: d.decline_to),
    acc[acc.end.notna()].assign(event="churn (stops buying)", event_month=lambda d: d.end.astype(str), keeps_share=0.0),
    acc[acc.is_new].assign(event="new account (6-month ramp-up)", event_month=lambda d: d.start.astype(str), keeps_share=None),
])[["account_id", "iso3", "event", "event_month", "keeps_share"]]
key.to_csv(CLEAN / "simulation_answer_key.csv", index=False)
targets.to_csv(CLEAN / "targets.csv", index=False)
countries.to_csv(CLEAN / "countries.csv", index=False)       # adds price_index

# ---------------- sanity checks ----------------
y = s.groupby(["iso3", "product_id", "year"]).units.sum().rename("our_units").reset_index()
chk = y.merge(market, on=["iso3", "product_id", "year"])
chk["share"] = chk.our_units / chk.market_units
yr = chk[chk.year == 2025].pivot(index="iso3", columns="product_id", values="share").round(3)
print("Unit share of market, 2025 (expected: a few % to ~20%):\n", yr)
print("\nRevenue by year (EUR m):", (s.groupby("year").revenue_eur.sum() / 1e6).round(1).to_dict())
tt = targets.assign(year=targets.month.dt.year).groupby("year").target_eur.sum() / 1e6
print("Targets by year (EUR m):", tt.round(1).to_dict())
print(f"rows: sales {len(sales):,}, accounts {len(acc):,}, targets {len(targets):,}")
