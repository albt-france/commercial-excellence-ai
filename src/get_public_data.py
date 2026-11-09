"""Download the REAL public data used for market sizing, then build data/clean/countries.csv.

Usage:  python src/get_public_data.py
Sources (see data/SOURCES.md):
  - OECD Health Statistics, dataflow OECD.ELS.HD:DSD_HEALTH_PROC@DF_SURG_PROC (v1.2),
    procedure CM36_TRS "Transluminal coronary angioplasty" (ICD-9-CM 36.01, 36.02, 36.05),
    units PRC (procedures, all modes = inpatient + day case) and PRC_10P5PS (per 100 000 persons).
  - World Bank WDI: SP.POP.TOTL (population), NY.GDP.PCAP.CD (GDP per capita, current USD),
    SH.XPD.CHEX.PC.CD (current health expenditure per capita, current USD).
Raw files are written to data/raw/ with the download date in data/raw/download_log.csv.
"""
import csv
import datetime as dt
import io
import json
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW, CLEAN = ROOT / "data" / "raw", ROOT / "data" / "clean"
RAW.mkdir(parents=True, exist_ok=True)
CLEAN.mkdir(parents=True, exist_ok=True)

# Markets covered by the case study: EMEA + APAC countries with an OECD angioplasty series.
# Japan, Singapore, China, India... have no CM36_TRS series at the OECD, so they are out of scope.
COUNTRIES = {
    # iso3: (name, region, subregion)
    "DEU": ("Germany", "EMEA", "DACH"), "AUT": ("Austria", "EMEA", "DACH"), "CHE": ("Switzerland", "EMEA", "DACH"),
    "FRA": ("France", "EMEA", "France & Benelux"), "BEL": ("Belgium", "EMEA", "France & Benelux"),
    "NLD": ("Netherlands", "EMEA", "France & Benelux"),
    "ITA": ("Italy", "EMEA", "Southern Europe"), "ESP": ("Spain", "EMEA", "Southern Europe"),
    "PRT": ("Portugal", "EMEA", "Southern Europe"),
    "GBR": ("United Kingdom", "EMEA", "UK & Nordics"), "SWE": ("Sweden", "EMEA", "UK & Nordics"),
    "POL": ("Poland", "EMEA", "Central & Eastern Europe"), "CZE": ("Czechia", "EMEA", "Central & Eastern Europe"),
    "ROU": ("Romania", "EMEA", "Central & Eastern Europe"),
    "TUR": ("Türkiye", "EMEA", "Middle East"), "ISR": ("Israel", "EMEA", "Middle East"),
    "KOR": ("Korea", "APAC", "North Asia"), "AUS": ("Australia", "APAC", "Oceania"), "NZL": ("New Zealand", "APAC", "Oceania"),
}
ISO2 = {"DEU": "DE", "AUT": "AT", "CHE": "CH", "FRA": "FR", "BEL": "BE", "NLD": "NL", "ITA": "IT", "ESP": "ES", "PRT": "PT",
        "GBR": "GB", "SWE": "SE", "POL": "PL", "CZE": "CZ", "ROU": "RO", "TUR": "TR", "ISR": "IL", "KOR": "KR", "AUS": "AU", "NZL": "NZ"}

OECD_URL = ("https://sdmx.oecd.org/public/rest/data/OECD.ELS.HD,DSD_HEALTH_PROC@DF_SURG_PROC,1.2/"
            "{areas}..PRC+PRC_10P5PS.CM36_TRS..............?startPeriod=2014&dimensionAtObservation=AllDimensions")
WB_URL = "https://api.worldbank.org/v2/country/{areas}/indicator/{ind}?format=json&date=2014:2025&per_page=2000"
WB_INDICATORS = {"SP.POP.TOTL": "population", "NY.GDP.PCAP.CD": "gdp_per_capita_usd",
                 "SH.XPD.CHEX.PC.CD": "health_exp_per_capita_usd"}


def get(url, accept=None):
    req = urllib.request.Request(url, headers={"User-Agent": "case-study-data-download/1.0",
                                               **({"Accept": accept} if accept else {})})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


log = []
today = dt.date.today().isoformat()

# ---------- OECD: coronary angioplasty ----------
oecd_raw = get(OECD_URL.format(areas="+".join(COUNTRIES)), accept="application/vnd.sdmx.data+csv; charset=utf-8")
(RAW / "oecd_surg_proc_CM36_TRS.csv").write_bytes(oecd_raw)
log.append(("oecd_surg_proc_CM36_TRS.csv", "OECD.ELS.HD:DSD_HEALTH_PROC@DF_SURG_PROC(1.2) CM36_TRS, PRC + PRC_10P5PS",
            OECD_URL.format(areas="+".join(COUNTRIES)), today))
o = pd.read_csv(io.BytesIO(oecd_raw))
o = o[o["MODE_PROVISION"] == "_T"]                      # total = inpatient + day case
pci = o.pivot_table(index=["REF_AREA", "TIME_PERIOD"], columns="UNIT_MEASURE", values="OBS_VALUE", aggfunc="first").reset_index()
pci.columns.name = None
pci = pci.rename(columns={"REF_AREA": "iso3", "TIME_PERIOD": "year", "PRC": "pci_procedures", "PRC_10P5PS": "pci_per_100k"})
pci = pci[pci["iso3"].isin(COUNTRIES)].sort_values(["iso3", "year"])

# ---------- World Bank ----------
wb_rows = []
for ind, name in WB_INDICATORS.items():
    url = WB_URL.format(areas=";".join(COUNTRIES), ind=ind)
    js = json.loads(get(url))
    (RAW / f"worldbank_{ind}.json").write_text(json.dumps(js, indent=1), encoding="utf-8")
    log.append((f"worldbank_{ind}.json", f"World Bank WDI {ind}", url, today))
    for r in js[1]:
        if r["value"] is not None:
            wb_rows.append((r["countryiso3code"], int(r["date"]), name, r["value"]))
wb = pd.DataFrame(wb_rows, columns=["iso3", "year", "indicator", "value"])
wb_wide = wb.pivot_table(index=["iso3", "year"], columns="indicator", values="value").reset_index()
wb_wide.columns.name = None

# ---------- long table: country x year ----------
series = pci.merge(wb_wide, on=["iso3", "year"], how="outer").sort_values(["iso3", "year"])
series = series[series["iso3"].isin(COUNTRIES) & series["year"].between(2014, 2025)]
series.to_csv(CLEAN / "market_series.csv", index=False)

# ---------- one row per country: latest real values ----------
rows = []
for iso3, (name, region, sub) in COUNTRIES.items():
    s = series[(series.iso3 == iso3) & series.pci_procedures.notna()].set_index("year")
    last = int(s.index.max())
    base = 2019   # growth measured from the last pre-COVID year, the same base for every country
    cagr = (s.loc[last, "pci_procedures"] / s.loc[base, "pci_procedures"]) ** (1 / (last - base)) - 1
    w = series[(series.iso3 == iso3)].set_index("year")
    def latest(col):
        v = w[col].dropna()
        return float(v.iloc[-1]), int(v.index[-1])
    pop, pop_y = latest("population")
    gdp, gdp_y = latest("gdp_per_capita_usd")
    hx, hx_y = latest("health_exp_per_capita_usd")
    rows.append(dict(iso3=iso3, iso2=ISO2[iso3], country=name, region=region, subregion=sub,
                     pci_year=last, pci_procedures=int(s.loc[last, "pci_procedures"]),
                     pci_per_100k=round(float(s.loc[last, "pci_per_100k"]), 1),
                     pci_base_year=base, pci_base=int(s.loc[base, "pci_procedures"]), pci_cagr=round(cagr, 4),
                     population=int(pop), population_year=pop_y,
                     gdp_per_capita_usd=round(gdp), gdp_year=gdp_y,
                     health_exp_per_capita_usd=round(hx), health_exp_year=hx_y))
countries = pd.DataFrame(rows)
countries.to_csv(CLEAN / "countries.csv", index=False)

with open(RAW / "download_log.csv", "w", newline="", encoding="utf-8") as f:
    wr = csv.writer(f)
    wr.writerow(["file", "series", "url", "downloaded_on"])
    wr.writerows(log)

print(countries[["iso3", "country", "pci_year", "pci_procedures", "pci_per_100k", "pci_cagr", "population",
                 "gdp_per_capita_usd", "health_exp_per_capita_usd", "health_exp_year"]].to_string(index=False))
