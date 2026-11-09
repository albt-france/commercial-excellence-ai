# %% [markdown]
# # Commercial Excellence with AI - analysis notebook
#
# Independent case study for an international cardiovascular device business. **Not affiliated with Cordis.**
# Data labels used everywhere:
# - **REAL**: OECD angioplasty counts, World Bank population and health spending (`data/SOURCES.md`).
# - **ESTIMATE**: market value = real procedure count x assumed devices per procedure x assumed price.
# - **SIMULATED**: sales, targets and hospitals (`src/generate_sales.py`, seed 42).
#
# Run `src/get_public_data.py`, `src/generate_sales.py` and `src/run_sql.py` first: this notebook reads `data/output/`.
# Every number shown in the report is written to `data/output/kpis.csv` at the end.

# %%
from pathlib import Path
import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
os.chdir(ROOT)
OUT = ROOT / "data" / "output"
pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 20)
pd.set_option("display.float_format", lambda x: f"{x:,.3f}")
K = {}          # every number quoted in the report

AS_OF = pd.Timestamp("2026-10-01")
K["as_of_month"] = 202610

# %% [markdown]
# ## 1. Where is the potential in EMEA and APAC? (REAL market + SIMULATED sales)
# Market size comes from the real number of coronary angioplasties (PCI) per country. Our share is our last-12-month
# revenue divided by the estimated 2026 market value. **Untapped potential** = market x benchmark share - our revenue,
# where the benchmark is the 75th percentile of country shares (what our better countries already achieve).

# %%
ws = pd.read_csv(OUT / "01_market_whitespace.csv")
show = ws[["country", "region", "pci_procedures", "pci_per_100k", "pci_cagr", "market_value_eur", "revenue_l12m",
           "share_value", "untapped_potential_eur", "quadrant"]]
show

# %%
K["countries"] = len(ws)
K["pci_total"] = ws.pci_procedures.sum()
K["market_value_total_m"] = ws.market_value_eur.sum() / 1e6
K["revenue_l12m_m"] = ws.revenue_l12m.sum() / 1e6
K["share_total"] = ws.revenue_l12m.sum() / ws.market_value_eur.sum()
K["benchmark_share"] = ws.benchmark_share.iloc[0]
K["potential_total_m"] = ws.untapped_potential_eur.sum() / 1e6
top = ws.sort_values("untapped_potential_eur", ascending=False).reset_index(drop=True)
for i in range(3):
    K[f"potential_{i+1}_country"] = top.loc[i, "country"]
    K[f"potential_{i+1}_m"] = top.loc[i, "untapped_potential_eur"] / 1e6
    K[f"potential_{i+1}_share"] = top.loc[i, "share_value"]
K["potential_top2_pct"] = top.loc[:1, "untapped_potential_eur"].sum() / ws.untapped_potential_eur.sum()
tur = ws.set_index("iso3").loc["TUR"]
K["tur_pci"] = tur.pci_procedures
K["tur_pci_per_100k"] = tur.pci_per_100k
K["tur_pci_cagr"] = tur.pci_cagr
K["tur_pci_year"] = tur.pci_year
deu = ws.set_index("iso3").loc["DEU"]
K["deu_pci_per_100k"] = deu.pci_per_100k
hi = ws.sort_values("pci_per_100k", ascending=False).iloc[0]
lo = ws.sort_values("pci_per_100k").iloc[0]
K["pci_per_100k_max"], K["pci_per_100k_max_country"] = hi.pci_per_100k, hi.country
K["pci_per_100k_min"], K["pci_per_100k_min_country"] = lo.pci_per_100k, lo.country
{k: v for k, v in K.items() if not k.startswith("as_of")}

# %%
fig, ax = plt.subplots(figsize=(8, 5))
ax.scatter(ws.market_value_eur / 1e6, ws.share_value * 100, s=20 + ws.untapped_potential_eur / 4e4, color="#2A78D6", alpha=0.6)
for _, r in ws.iterrows():
    ax.annotate(r.iso3, (r.market_value_eur / 1e6, r.share_value * 100), fontsize=8)
ax.axhline(K["benchmark_share"] * 100, ls="--", color="#52514E")
ax.set_xlabel("Estimated 2026 market, EUR m"); ax.set_ylabel("Our value share, %")
ax.set_title("Market size vs share (bubble = untapped potential)")
plt.show()

# %% [markdown]
# ## 2. What explains the gap to target? (SIMULATED)
# Year to date = January-October. The price-volume-mix bridge must close exactly: the effects add up to the change in revenue.

# %%
ytd = pd.read_csv(OUT / "02_ytd_country.csv")
ytdp = pd.read_csv(OUT / "02_ytd_product.csv")
K["revenue_ytd_m"] = ytd.revenue_ytd.sum() / 1e6
K["target_ytd_m"] = ytd.target_ytd.sum() / 1e6
K["revenue_ytd_ly_m"] = ytd.revenue_ytd_ly.sum() / 1e6
K["gap_ytd_m"] = K["revenue_ytd_m"] - K["target_ytd_m"]
K["vs_target_ytd"] = K["revenue_ytd_m"] / K["target_ytd_m"] - 1
K["growth_ytd"] = K["revenue_ytd_m"] / K["revenue_ytd_ly_m"] - 1
K["target_fy_m"] = ytd.target_full_year.sum() / 1e6
neg = ytd[ytd.gap_to_target < 0].sort_values("gap_to_target")
K["gap_fra_deu_m"] = ytd.set_index("iso3").loc[["FRA", "DEU"], "gap_to_target"].sum() / 1e6
K["gap_fra_deu_share"] = K["gap_fra_deu_m"] / K["gap_ytd_m"]
K["countries_below_target"] = int((ytd.gap_to_target < 0).sum())
for iso in ["FRA", "DEU", "TUR", "POL", "KOR", "ESP"]:
    r = ytd.set_index("iso3").loc[iso]
    K[f"{iso.lower()}_vs_target"] = r.vs_target_pct
    K[f"{iso.lower()}_gap_m"] = r.gap_to_target / 1e6
    K[f"{iso.lower()}_growth"] = r.growth_yoy
ytd[["country", "revenue_ytd", "target_ytd", "gap_to_target", "vs_target_pct", "growth_yoy"]]

# %%
pvm = pd.read_csv(OUT / "03_pvm_total.csv").set_index("step")
pvc = pd.read_csv(OUT / "03_pvm_country.csv")
pvp = pd.read_csv(OUT / "03_pvm_product.csv")
r0, r1 = pvm.loc["Revenue Jan-Oct 2025", "value"], pvm.loc["Revenue Jan-Oct 2026", "value"]
effects = pvm.loc[["Volume", "Mix", "Price"], "value"]
assert abs(effects.sum() - (r1 - r0)) < 0.01, "bridge does not close"
assert pvc.closure_check.abs().max() < 0.01
print(f"R0 {r0:,.0f} + volume {effects['Volume']:,.0f} + mix {effects['Mix']:,.0f} + price {effects['Price']:,.0f} "
      f"= {r0 + effects.sum():,.0f}  (R1 = {r1:,.0f})")
K["pvm_volume_m"], K["pvm_mix_m"], K["pvm_price_m"] = effects["Volume"] / 1e6, effects["Mix"] / 1e6, effects["Price"] / 1e6
K["pvm_change_m"] = (r1 - r0) / 1e6
des = pvp.set_index("product_id").loc["DES"]
K["des_price_change"] = des.price_change_pct
K["des_price_effect_m"] = des.price_effect / 1e6
K["des_price_share"] = des.price_effect / effects["Price"]
K["dcb_units_growth"] = pvp.set_index("product_id").loc["DCB", "units_growth"]
deu_pvm = pvc.set_index("iso3").loc["DEU"]
K["deu_price_effect_m"] = deu_pvm.price_effect / 1e6
fra_pvm = pvc.set_index("iso3").loc["FRA"]
K["fra_volume_effect_m"] = fra_pvm.volume_effect / 1e6
pvp

# %%
steps = ["Revenue Jan-Oct 2025", "Volume", "Mix", "Price", "Revenue Jan-Oct 2026"]
vals = pvm.loc[steps, "value"].values / 1e6
base = [0, vals[0], vals[0] + vals[1], vals[0] + vals[1] + vals[2], 0]
heights = [vals[0], vals[1], vals[2], vals[3], vals[4]]
colors = ["#B4B2A9", "#2A78D6", "#2A78D6", "#D03B3B", "#B4B2A9"]
fig, ax = plt.subplots(figsize=(8, 4))
for i, (b, h, c) in enumerate(zip(base, heights, colors)):
    ax.bar(i, h, bottom=b if i not in (0, 4) else 0, color=c)
ax.set_xticks(range(5), steps, fontsize=8); ax.set_ylim(vals[0] * 0.9, max(vals) * 1.05)
ax.set_title("Price-volume-mix bridge, EUR m"); plt.show()

# %% [markdown]
# ## 3. Which hospitals carry growth, and which may leave? (SIMULATED)

# %%
acc = pd.read_csv(OUT / "04_accounts.csv")
K["accounts_active"] = int((acc.revenue_l12m > 0).sum())
top20 = acc[acc.size_percentile < 0.2]
K["top20_accounts"] = len(top20)
K["top20_revenue_share"] = top20.revenue_l12m.sum() / acc.revenue_l12m.sum()
K["accounts_for_80pct"] = int((acc.cum_revenue_share < 0.8).sum() + 1)
K["accounts_for_80pct_share"] = K["accounts_for_80pct"] / K["accounts_active"]
risk = acc[acc.risk_flag != "OK"]
K["at_risk_accounts"] = len(risk)
K["at_risk_l3m_ly_k"] = risk.revenue_l3m_ly.sum() / 1e3
K["at_risk_l3m_k"] = risk.revenue_l3m.sum() / 1e3
K["at_risk_lost_run_rate_m"] = (risk.revenue_l3m_ly.sum() - risk.revenue_l3m.sum()) * 4 / 1e6   # annualised
K["at_risk_l12m_share"] = risk.revenue_l12m.sum() / acc.revenue_l12m.sum()
K["at_risk_fra"] = int((risk.iso3 == "FRA").sum())
new = acc[acc.is_new_account]
K["new_accounts"] = len(new)
K["new_accounts_revenue_share"] = new.revenue_l12m.sum() / acc.revenue_l12m.sum()
K["new_accounts_tur"] = int((new.iso3 == "TUR").sum())
seg = (acc.groupby("segment").agg(accounts=("account_id", "count"), revenue_l12m=("revenue_l12m", "sum"),
                                  revenue_p12m=("revenue_p12m", "sum"))
       .assign(revenue_share=lambda d: d.revenue_l12m / d.revenue_l12m.sum(),
               growth=lambda d: d.revenue_l12m / d.revenue_p12m - 1))
seg.reset_index().to_csv(OUT / "04_segments.csv", index=False)
K["seg_defend_accounts"] = int(seg.loc["2 · Big & declining: defend", "accounts"])
K["seg_defend_share"] = seg.loc["2 · Big & declining: defend", "revenue_share"]
risk[["account_id", "country", "account_type", "revenue_l3m_ly", "revenue_l3m", "growth_l3m"]].sort_values("revenue_l3m_ly", ascending=False)

# %% [markdown]
# **Does the alert find the right hospitals?** The simulation keeps an answer key of the events it built in
# (`data/clean/simulation_answer_key.csv`, not loaded into the database). The alert is scored against it.

# %%
key = pd.read_csv("data/clean/simulation_answer_key.csv")
lost = set(key.loc[key.event.str.startswith("competitor"), "account_id"])
flagged = set(risk.account_id)
K["alert_true_positives"] = len(flagged & lost)
K["alert_false_alarms"] = len(flagged - lost)
K["alert_missed"] = len(lost - flagged)
print(f"injected competitor wins: {len(lost)} | flagged: {len(flagged)} | caught: {K['alert_true_positives']} | "
      f"false alarms: {K['alert_false_alarms']} | missed: {K['alert_missed']}")

# %%
seg

# %% [markdown]
# ## 4. Will we hit the annual target? Forecast validated on a hold-out (SIMULATED)
# Model, per country: **forecast(month m) = revenue(m - 12) x g**, where g = last 12 months / the 12 months before at the
# forecast origin. It keeps each country's seasonality (August holidays, Lunar New Year...) and its recent growth.
# **Validation**: origin April 2026, forecast May-October 2026 (6 months the model never saw), compare with actuals,
# and with a naive baseline (same month last year, g = 1).

# %%
fi = pd.read_csv(OUT / "05_forecast_inputs.csv", parse_dates=["month"])
piv = fi.pivot(index="month", columns="iso3", values="revenue_eur").sort_index()

def seasonal_growth_forecast(history, horizon, use_growth=True):
    """history: month x country revenue up to the origin. Returns month x country forecasts for the next `horizon` months."""
    origin = history.index.max()
    g = history.iloc[-12:].sum() / history.iloc[-24:-12].sum() if use_growth else pd.Series(1.0, index=history.columns)
    months = pd.date_range(origin + pd.offsets.MonthBegin(1), periods=horizon, freq="MS")
    return pd.DataFrame({m: history.loc[m - pd.DateOffset(years=1)] * g for m in months}).T, g

def mape(actual, pred):
    return float((abs(actual - pred) / actual).mean())

HOLD_ORIGIN = pd.Timestamp("2026-04-01")
hist = piv.loc[:HOLD_ORIGIN]
pred, g_hold = seasonal_growth_forecast(hist, 6)
naive, _ = seasonal_growth_forecast(hist, 6, use_growth=False)
act = piv.loc[pred.index]
models = pd.DataFrame({
    "model": ["Seasonal x trailing growth", "Naive: same month last year"],
    "mape_total": [mape(act.sum(axis=1), pred.sum(axis=1)), mape(act.sum(axis=1), naive.sum(axis=1))],
    "mape_country_median": [np.median([mape(act[c], pred[c]) for c in act]), np.median([mape(act[c], naive[c]) for c in act])],
    "error_6m_total": [pred.values.sum() / act.values.sum() - 1, naive.values.sum() / act.values.sum() - 1],
})
models.to_csv(OUT / "05_forecast_models.csv", index=False)
K["mape_total"] = models.loc[0, "mape_total"]
K["mape_naive_total"] = models.loc[1, "mape_total"]
K["mape_country_median"] = models.loc[0, "mape_country_median"]
K["holdout_bias"] = models.loc[0, "error_6m_total"]
country_mape = pd.Series({c: mape(act[c], pred[c]) for c in act}, name="holdout_mape")
# Why does the model over-forecast the hold-out? Compare with what the at-risk accounts lost over the same months.
sales = pd.read_csv("data/clean/sales.csv", parse_dates=["month"])
ar = sales[sales.account_id.isin(acc.loc[acc.risk_flag != "OK", "account_id"])]
lost_hold = (ar[ar.month.between("2025-05-01", "2025-10-01")].revenue_eur.sum()
             - ar[ar.month.between("2026-05-01", "2026-10-01")].revenue_eur.sum())
K["holdout_overforecast_m"] = (pred.values.sum() - act.values.sum()) / 1e6
K["holdout_at_risk_drop_m"] = lost_hold / 1e6
print(f"over-forecast {K['holdout_overforecast_m']:.2f} m vs at-risk accounts' drop {K['holdout_at_risk_drop_m']:.2f} m")
models

# %%
FINAL_ORIGIN = AS_OF
fc, g_final = seasonal_growth_forecast(piv.loc[:FINAL_ORIGIN], 2)        # November and December 2026
tgt = fi.pivot(index="month", columns="iso3", values="target_eur")
# targets for the forecast months come from targets.csv (02 only kept months up to the as-of month)
targets = pd.read_csv("data/clean/targets.csv", parse_dates=["month"])
tgt_fy = targets[targets.month.dt.year == 2026].groupby("iso3").target_eur.sum()
ytd_c = piv.loc["2026-01-01":FINAL_ORIGIN].sum()
by_c = pd.DataFrame({"revenue_ytd": ytd_c, "forecast_nov_dec": fc.sum(), "target_fy": tgt_fy,
                     "growth_factor": g_final, "holdout_mape": country_mape})
by_c["forecast_fy"] = by_c.revenue_ytd + by_c.forecast_nov_dec
by_c["gap_fy"] = by_c.forecast_fy - by_c.target_fy
by_c["vs_target_fy"] = by_c.forecast_fy / by_c.target_fy - 1
by_c = by_c.join(pd.read_csv("data/clean/countries.csv").set_index("iso3")[["country", "region"]])
by_c.sort_values("gap_fy").reset_index().rename(columns={"index": "iso3"}).to_csv(OUT / "05_forecast_country.csv", index=False)

fy = by_c.forecast_fy.sum()
K["forecast_nov_dec_m"] = by_c.forecast_nov_dec.sum() / 1e6
K["forecast_fy_m"] = fy / 1e6
K["target_fy_check_m"] = by_c.target_fy.sum() / 1e6
K["forecast_gap_m"] = (fy - by_c.target_fy.sum()) / 1e6
K["forecast_vs_target"] = fy / by_c.target_fy.sum() - 1
K["fy_2025_m"] = piv.loc["2025-01-01":"2025-12-01"].values.sum() / 1e6
K["forecast_growth_fy"] = fy / 1e6 / K["fy_2025_m"] - 1
K["countries_fy_on_target"] = int((by_c.gap_fy >= 0).sum())
need = by_c.target_fy.sum() - by_c.revenue_ytd.sum()
K["needed_nov_dec_m"] = need / 1e6
K["needed_uplift"] = need / by_c.forecast_nov_dec.sum() - 1
by_c.sort_values("gap_fy")[["country", "revenue_ytd", "forecast_nov_dec", "forecast_fy", "target_fy", "gap_fy", "holdout_mape"]]

# %%
# Scenarios for November-December: the hold-out error gives the band; the at-risk accounts give a recovery case.
band = K["mape_total"]
nd = by_c.forecast_nov_dec.sum()
recover = (risk.revenue_l3m_ly.sum() - risk.revenue_l3m.sum()) / 3 * 2 * 0.5     # win back half of the lost run-rate for 2 months
naive_fc, _ = seasonal_growth_forecast(piv.loc[:FINAL_ORIGIN], 2, use_growth=False)
scen = pd.DataFrame([
    ("Low: forecast - hold-out error", by_c.revenue_ytd.sum() + nd * (1 - band)),
    ("Naive: Nov-Dec = last year", by_c.revenue_ytd.sum() + naive_fc.values.sum()),
    ("Base forecast", fy),
    ("High: forecast + hold-out error", by_c.revenue_ytd.sum() + nd * (1 + band)),
    ("Base + win back half of at-risk accounts", fy + recover),
], columns=["scenario", "revenue_fy"])
scen["target_fy"] = by_c.target_fy.sum()
scen["gap"] = scen.revenue_fy - scen.target_fy
scen["vs_target"] = scen.revenue_fy / scen.target_fy - 1
scen["order"] = range(1, len(scen) + 1)
scen.to_csv(OUT / "05_forecast_scenarios.csv", index=False)
K["scenario_low_vs_target"] = scen.vs_target.min()
K["scenario_best_vs_target"] = scen.vs_target.max()
K["scenario_best_gap_m"] = scen.gap.max() / 1e6
K["scenario_recover_gain_m"] = recover / 1e6
scen

# %%
# Monthly series for the report: actual, hold-out prediction, forecast and target (all countries)
tot = pd.DataFrame({"actual": piv.sum(axis=1)})
tot["holdout_pred"] = pred.sum(axis=1)
tot = tot.reindex(pd.date_range("2024-01-01", "2026-12-01", freq="MS"))
tot.loc[fc.index, "forecast"] = fc.sum(axis=1)
tot.loc[AS_OF, "forecast"] = tot.loc[AS_OF, "actual"]          # joins the forecast line to the last actual
tot["target"] = targets.groupby("month").target_eur.sum()
tot.loc[tot.index > AS_OF, "actual"] = np.nan
tot.index.name = "month"
tot.reset_index().to_csv(OUT / "05_forecast_monthly.csv", index=False)

fig, ax = plt.subplots(figsize=(9, 4))
ax.plot(tot.index, tot.actual / 1e6, color="#0B0B0B", label="actual")
ax.plot(tot.index, tot.holdout_pred / 1e6, color="#5598E7", label="hold-out prediction")
ax.plot(tot.index, tot.forecast / 1e6, color="#2A78D6", ls="-", lw=2, label="forecast")
ax.plot(tot.index, tot.target / 1e6, color="#B4B2A9", ls="--", label="target")
ax.legend(); ax.set_title("Monthly revenue, EUR m"); plt.show()

# %% [markdown]
# ## 5. Save the numbers used in the report

# %%
kp = pd.DataFrame([(k, v) for k, v in K.items()], columns=["key", "value"])
kp.to_csv(OUT / "kpis.csv", index=False)
print(len(kp), "numbers -> data/output/kpis.csv")
kp
