"""Generate the Power BI report pages (PBIR format) for powerbi/CommercialExcellence.Report.

Usage:  python src/build_report_pages.py      (close Power BI Desktop first, or let it reload)
Every number written in titles and text boxes is read from data/output/kpis.csv (notebook) and
ai/eval_summary.csv (AI evaluation), so the text always matches the SQL, notebook and evaluation results.
Layout, palette and helpers are the same as the Rovio, PlayersBest and Marketplace case studies.
"""
import csv
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "powerbi" / "CommercialExcellence.Report"
PAGES = REPORT / "definition" / "pages"
OUT = ROOT / "data" / "output"
VC_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.4.0/schema.json"
PAGE_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json"
PAGES_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.1.0/schema.json"
M = "_Measures"

INK, INK2, MUTED = "#0B0B0B", "#52514E", "#898781"
BLUE, GREY, RED = "#2A78D6", "#B4B2A9", "#D03B3B"
SEQ = {"100": "#CDE2FB", "250": "#86B6EF", "350": "#5598E7", "450": "#2A78D6", "650": "#104281"}
AUTHOR = "Independent case study · Not affiliated with Cordis"
SRC_REAL = "Real: OECD Health Statistics, surgical procedures CM36_TRS (coronary angioplasty); World Bank WDI"
SRC_SIM = "Simulated sales, targets and hospitals (src/generate_sales.py, seed 42), calibrated on real OECD market size"
TAG_MIX, TAG_SIM, TAG_AI = "PUBLIC + SIMULATED DATA", "SIMULATED DATA", "SIMULATED DATA · AI"

# ---------- numbers from the analysis ----------
K = {}
for r in csv.DictReader(open(OUT / "kpis.csv", encoding="utf-8")):
    try:
        K[r["key"]] = float(r["value"])
    except ValueError:
        K[r["key"]] = r["value"]
S = {r["metric"]: r["value"] for r in csv.DictReader(open(ROOT / "ai" / "eval_summary.csv", encoding="utf-8"))}
TS = list(csv.DictReader(open(OUT / "ai_time_saving.csv", encoding="utf-8")))
N_MEASURES = sum(1 for line in open(ROOT / "powerbi" / "CommercialExcellence.SemanticModel" / "definition" / "tables" / "_Measures.tmdl",
                                    encoding="utf-8") if line.startswith("\tmeasure "))
def pct(x, d=0): return f"{x * 100:.{d}f}%"
def spct(x, d=1): return f"{x * 100:+.{d}f}%"
def n(x): return f"{x:,.0f}"
def m1(x): return f"EUR {x:,.1f} m"
HOURS = float(TS[-1]["hours_saved"])
SQL_OK, SQL_N = int(S["sql_correct"]), int(S["sql_questions"])
TRIALS_OK, TRIALS = int(S["sql_trials_correct"]), int(S["sql_trials"])
STRESS_OK, STRESS_N = int(S["stress_correct"]), int(S["stress_questions"])
NUMS, UNSUP = int(S["mbr_numbers_cited"]), int(S["mbr_unsupported_final"])
RUN = list(csv.DictReader(open(ROOT / "docs" / "mbr" / "run_2026-10.csv", encoding="utf-8")))
REVIEWS = int(S["mbr_reviews"]) + len(RUN)                                   # 10 monthly + 20 October scopes
NUMS_ALL = NUMS + sum(int(r["numbers_cited"]) for r in RUN)
UNSUP_ALL = UNSUP + sum(int(r["unsupported_final"]) for r in RUN)
at_risk_drop = 1 - K["at_risk_l3m_k"] / K["at_risk_l3m_ly_k"]


# ---------- expression helpers ----------
def raw(v):
    if isinstance(v, bool):
        s = "true" if v else "false"
    elif isinstance(v, (int, float)):
        s = f"{v}D"
    else:
        s = "'" + str(v).replace("'", "''") + "'"
    return {"Literal": {"Value": s}}

def lit(v): return {"expr": raw(v)}
def color(hexv): return {"solid": {"color": lit(hexv)}}
def col(table, column): return {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": column}}
def meas(name): return {"Measure": {"Expression": {"SourceRef": {"Entity": M}}, "Property": name}}
def agg(table, column, fn=0): return {"Aggregation": {"Expression": col(table, column), "Function": fn}}

AGG_NAME = {0: "Sum", 1: "Avg", 3: "Min", 4: "Max"}
def qref(field):
    if "Column" in field:
        c = field["Column"]
        return f'{c["Expression"]["SourceRef"]["Entity"]}.{c["Property"]}'
    if "Measure" in field:
        return f'{M}.{field["Measure"]["Property"]}'
    a = field["Aggregation"]
    c = a["Expression"]["Column"]
    return f'{AGG_NAME[a["Function"]]}({c["Expression"]["SourceRef"]["Entity"]}.{c["Property"]})'

def proj(field, label=None):
    p = {"field": field, "queryRef": qref(field)}
    if "Column" in field:
        p["nativeQueryRef"] = field["Column"]["Property"]
    elif "Measure" in field:
        p["nativeQueryRef"] = field["Measure"]["Property"]
    else:
        prop = field["Aggregation"]["Expression"]["Column"]["Property"]
        p["nativeQueryRef"] = f"{AGG_NAME[field['Aggregation']['Function']]} of {prop}"
        p["displayName"] = prop
    if label:
        p["displayName"] = label
    return p

def C(t, c): return col(t, c)

def series_color(field, hexv):
    return {"properties": {"fill": color(hexv)}, "selector": {"metadata": qref(field)}}

def measure_fill(measure_name):
    """Bar colour taken from a measure that returns a hex code (conditional formatting by field value)."""
    return {"properties": {"fill": {"solid": {"color": {"expr": meas(measure_name)}}}},
            "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}]}}

def ref_line(value, label, hexv=INK2, selector_id="1"):
    return {"properties": {"show": lit(True), "value": lit(value), "displayName": lit(label), "lineColor": color(hexv),
                           "style": lit("dashed"), "dataLabelShow": lit(True), "dataLabelColor": color(hexv)},
            "selector": {"id": selector_id}}

def bg_rule(field, lo, hi):
    rule = {"min": {"color": raw(lo)}, "max": {"color": raw(hi)}, "nullColoringStrategy": {"strategy": raw("asZero")}}
    return {"properties": {"backColor": {"solid": {"color": {"expr": {"FillRule": {"Input": field, "FillRule": {"linearGradient2": rule}}}}}}},
            "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": qref(field)}}

def table_style(extra_values=(), size=12, wrap=False):
    fs = {"properties": {"fontSize": lit(size), **({"wordWrap": lit(True)} if wrap else {})}}
    return {"values": [fs, *extra_values], "columnHeaders": [{"properties": {"fontSize": lit(size), "fontColor": color(INK2)}}],
            "total": [{"properties": {"totals": lit(False)}}]}

def no_legend(extra=None):
    o = {"legend": [{"properties": {"show": lit(False)}}]}
    o.update(extra or {})
    return o

def labels_on(hexv=INK):
    return [{"properties": {"show": lit(True), "color": color(hexv)}}]


# ---------- page / visual builders ----------
class Page:
    def __init__(self, pid, name):
        self.pid, self.name, self.visuals, self.n = pid, name, [], 0

    def _add(self, vid, x, y, w, h, visual):
        self.n += 1
        self.visuals.append({"$schema": VC_SCHEMA, "name": vid,
                             "position": {"x": round(x), "y": round(y), "z": self.n * 1000,
                                          "height": round(h), "width": round(w), "tabOrder": self.n * 1000},
                             "visual": visual})
        return vid

    def chart(self, vid, vtype, x, y, w, h, roles, title=None, objects=None, labels=None, sort=None, only=None):
        labels = labels or {}
        visual = {"visualType": vtype,
                  "query": {"queryState": {r: {"projections": [proj(f, labels.get(qref(f))) for f in fs]}
                                           for r, fs in roles.items() if fs}},
                  "drillFilterOtherVisuals": True}
        if sort:
            field, direction = sort
            visual["query"]["sortDefinition"] = {"sort": [{"field": field, "direction": direction}], "isDefaultSort": False}
        if objects:
            visual["objects"] = objects
        visual["visualContainerObjects"] = {"subTitle": [{"properties": {"show": lit(False)}}],
                                            "title": [{"properties": {"show": lit(bool(title)), **({"text": lit(title)} if title else {})}}]}
        self._add(vid, x, y, w, h, visual)
        if only:  # visual-level filter: (table, column, values, negate)
            table, column, values, negate = only
            vals = [[{"Literal": {"Value": f"{v}L"}}] if isinstance(v, int) and not isinstance(v, bool) else [raw(v)] for v in values]
            cond = {"In": {"Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "t"}}, "Property": column}}], "Values": vals}}
            if negate:
                cond = {"Not": {"Expression": cond}}
            self.visuals[-1]["filterConfig"] = {"filters": [{
                "name": "visualFilter", "type": "Categorical", "field": col(table, column),
                "filter": {"Version": 2, "From": [{"Name": "t", "Entity": table, "Type": 0}], "Where": [{"Condition": cond}]}}]}
        return vid

    def text(self, vid, x, y, w, h, paragraphs, boxed=False):
        paras = [{"textRuns": [{"value": t, "textStyle": {"fontSize": f"{s}pt", "color": c, **({"fontWeight": "bold"} if b else {})}}
                               for t, s, c, b in runs]} for runs in paragraphs]
        visual = {"visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": paras}}]},
                  "visualContainerObjects": {"background": [{"properties": {"show": lit(boxed)}}],
                                             "border": [{"properties": {"show": lit(boxed)}}],
                                             **({"padding": [{"properties": {"top": lit(16), "bottom": lit(16), "left": lit(20), "right": lit(20)}}]}
                                                if boxed else {})}}
        return self._add(vid, x, y, w, h, visual)

    def header(self, title, conclusion, tag):
        self.text("title", 32, 20, 1500, 56, [[(title, 24, INK, True)]])
        self.text("tag", 1540, 28, 348, 40, [[(tag.upper(), 10, INK2, True)]])
        self.text("conclusion", 32, 76, 1856, 64, [[(conclusion, 13, INK2, False)]])

    def footer(self, source):
        self.text("footer", 32, 1040, 1856, 32, [[(source + "   ·   " + AUTHOR, 9, MUTED, False)]])

    def card(self, vid, x, y, w, h, measure, title):
        return self.chart(vid, "card", x, y, w, h, {"Values": [meas(measure)]}, title,
                          {"labels": [{"properties": {"color": color(INK), "fontSize": lit(28), "labelDisplayUnits": lit(1)}}],
                           "categoryLabels": [{"properties": {"show": lit(False)}}]})

    def write(self):
        d = PAGES / self.pid
        if d.exists():
            shutil.rmtree(d)
        (d / "visuals").mkdir(parents=True)
        page = {"$schema": PAGE_SCHEMA, "name": self.pid, "displayName": self.name, "displayOption": "FitToPage",
                "height": 1080, "width": 1920}
        (d / "page.json").write_text(json.dumps(page, indent=2, ensure_ascii=False), encoding="utf-8")
        for v in self.visuals:
            vd = d / "visuals" / v["name"]
            vd.mkdir()
            (vd / "visual.json").write_text(json.dumps(v, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------- layout grid ----------
L, R, TOP, BOT, GAP = 32, 1888, 156, 1028, 24
W = R - L

def cols(k, x0=L, x1=R):
    w = (x1 - x0 - (k - 1) * GAP) / k
    return [(x0 + i * (w + GAP), w) for i in range(k)]

def kpi_row(p, items, y=TOP, h=120, x0=L, x1=R):
    for (x, w), (m, t) in zip(cols(len(items), x0, x1), items):
        p.card("kpi_" + "".join(ch for ch in m if ch.isalnum())[:30], x, y, w, h, m, t)
    return y + h + GAP

def hero_row(p, heroes, y=TOP, h=250):
    for i, ((x, w), (num, txt, tg)) in enumerate(zip(cols(len(heroes)), heroes)):
        p.text(f"hero{i+1}", x, y, w, h, [[(tg, 10, INK2, True)], [(num, 44, INK, True)], [(txt, 15, INK2, False)]], boxed=True)
    return y + h + GAP

pages = []

# ======================= Page 0 - Overview =======================
p = Page("a0c1d2e3f4a5b6c7d8e9", "Overview")
p.text("title", 32, 20, 1500, 56, [[("Commercial Excellence with AI: market whitespace, sales performance and an automated business review", 22, INK, True)]])
p.text("tag", 1540, 28, 348, 40, [[(TAG_MIX, 10, INK2, True)]])
p.text("conclusion", 32, 76, 1856, 64, [[(
    f"A case study for an international cardiovascular device business in EMEA and APAC. The real market size ({n(K['countries'])} countries, "
    f"{n(K['pci_total'])} coronary angioplasties a year, OECD) is combined with simulated sales of six generic product lines, "
    "analysed with SQL, Python and Power BI, then reported automatically by Claude with a check on every number.", 13, INK2, False)]])
y2 = hero_row(p, [
    (m1(K["potential_total_m"]), f"untapped potential a year. {K['potential_1_country']} and {K['potential_2_country']} hold "
     f"{pct(K['potential_top2_pct'])} of it: big markets where our share is {pct(K['potential_1_share'], 1)} and "
     f"{pct(K['potential_2_share'], 1)}, vs an {pct(K['benchmark_share'], 1)} benchmark.", "REAL + SIMULATED · PAGE 1"),
    (spct(K["vs_target_ytd"]), f"year to date vs target ({m1(K['gap_ytd_m'])}). France and Germany explain {pct(K['gap_fra_deu_share'])} "
     f"of the gap; stent price erosion alone cost {m1(-K['des_price_effect_m'])}.", "SIMULATED · PAGE 2"),
    (f"{n(K['at_risk_accounts'])} hospitals", f"flagged at risk ({spct(-at_risk_drop, 0)} in 3 months). The 2026 forecast ends "
     f"{pct(-K['forecast_vs_target'], 1)} below target, and even the best scenario misses.", "SIMULATED · PAGES 3-4"),
    (f"{SQL_OK}/{SQL_N}", f"test questions answered correctly by text-to-SQL. {UNSUP_ALL} of the {n(NUMS_ALL)} numbers in {REVIEWS} "
     "reviews written by Claude could not be traced back to SQL.", "AI · PAGE 5"),
])
(x1, w1), (x2, w2) = cols(2)
BH = 370
p.text("questions", x1, y2, w1, BH, [
    [("Business questions", 22, INK, True)], [("", 12, INK, False)],
    [("1 · Market   ", 17, BLUE, True), ("Where is the potential in EMEA and APAC?", 17, INK, False)],
    [("2 · Performance   ", 17, BLUE, True), ("What explains the gap to target?", 17, INK, False)],
    [("3 · Customers   ", 17, BLUE, True), ("Which hospitals carry growth, and which may leave?", 17, INK, False)],
    [("4 · Forecast   ", 17, BLUE, True), ("Will we hit the annual target?", 17, INK, False)],
    [("5 · AI   ", 17, BLUE, True), ("How can AI save the team time without inventing numbers?", 17, INK, False)],
    [("", 12, INK, False)],
    [("Recommendation: ", 17, INK, True),
     (f"defend first: win back the {n(K['at_risk_accounts'])} at-risk hospitals and hold stent prices in tenders; then invest where big "
      f"markets have a low share ({K['potential_1_country']}, {K['potential_2_country']}); automate the monthly review to free about "
      f"{HOURS:.0f} analyst hours a month for that work.", 17, INK2, False)],
], boxed=True)
p.text("data", x2, y2, w2, BH, [
    [("Data & methods", 22, INK, True)], [("", 12, INK, False)],
    [("REAL   ", 14, INK2, True), ("OECD Health Statistics: coronary angioplasties by country (latest year 2024, Türkiye 2025, "
                                    "New Zealand 2023); World Bank population, GDP and health spending.", 16, INK, False)],
    [("SIMULATED   ", 14, INK2, True), ("sales of 357 fictional hospitals, 6 generic product lines, Jan 2023 - Oct 2026, "
                                         "with targets; market shares of 2-25% on the real market size.", 16, INK, False)],
    [("SQL   ", 14, INK2, True), ("whitespace, sales vs target, price-volume-mix bridge, account alerts with window functions (DuckDB).", 16, INK, False)],
    [("Python   ", 14, INK2, True), ("seasonal forecast checked on 6 months it never saw.", 16, INK, False)],
    [("AI   ", 14, INK2, True), ("Claude API: monthly review written from SQL facts with a number check; text-to-SQL on a "
                                 f"read-only database; tested on {SQL_N + STRESS_N} questions.", 16, INK, False)],
    [("Power BI   ", 14, INK2, True), (f"star schema (3 facts, 4 dimensions), {N_MEASURES} DAX measures.", 16, INK, False)],
], boxed=True)
y3 = y2 + BH + GAP
p.text("howto", L, y3, W, BOT - y3, [
    [("How to read this report", 17, INK, True)],
    [("Titles  ", 14, INK2, True), ("state the conclusion of the page.     ", 15, INK, False),
     ("Year to date  ", 14, INK2, True), ("January-October 2026 vs the same months of 2025.     ", 15, INK, False),
     ("Blue  ", 14, INK2, True), ("= data, ", 15, INK, False), ("grey  ", 14, INK2, True), ("= comparison, ", 15, INK, False),
     ("red  ", 14, INK2, True), ("= below target or at risk; dashed lines mark targets and thresholds.     ", 15, INK, False),
     ("Labels  ", 14, INK2, True), ("REAL, ESTIMATE and SIMULATED are kept apart on every page.", 15, INK, False)],
    [("", 6, INK, False)],
    [("How it was built  ", 14, INK2, True),
     ("I used Claude Code to write the scripts efficiently. I made the decisions: the business questions, which data to use "
      "and how to simulate it, the methods, the checks and the page design, and I reviewed every result.", 15, INK, False)],
], boxed=True)
p.footer(SRC_REAL + "   ·   " + SRC_SIM)
pages.append(p)

# ======================= Page 1 - Market whitespace =======================
p = Page("b1d2e3f4a5b6c7d8e9f0", "1 · Market whitespace")
p.header(f"{K['potential_1_country']} and {K['potential_2_country']} hold {pct(K['potential_top2_pct'])} of the "
         f"{m1(K['potential_total_m'])} untapped potential",
         f"Real angioplasty rates range from {n(K['pci_per_100k_min'])} per 100,000 people ({K['pci_per_100k_min_country']}) to "
         f"{n(K['pci_per_100k_max'])} ({K['pci_per_100k_max_country']}, +{pct(K['tur_pci_cagr'], 1)} a year since 2019). "
         f"Both are big markets where our share is low. Potential = estimated market x benchmark share ({pct(K['benchmark_share'], 1)}, "
         "our top quartile of countries) - our last-12-month revenue. Market value is an estimate (real procedures x assumed devices and prices).", TAG_MIX)
(xa, wa), (xb, wb) = cols(2)
h = 500
pk = meas("PCI per 100k")
p.chart("pciRate", "clusteredBarChart", xa, TOP, wa, h, {"Category": [C("Country", "country")], "Y": [pk]},
        f"REAL · Coronary angioplasties per 100,000 inhabitants, latest OECD year",
        no_legend({"dataPoint": [{"properties": {"fill": color(BLUE)}}], "labels": labels_on(),
                   "categoryAxis": [{"properties": {"fontSize": lit(9)}}]}),
        labels={qref(pk): "Procedures per 100k"}, sort=(pk, "Descending"))
sx, sy, ss = meas("Market Value (EUR m)"), meas("Value Share"), meas("Untapped Potential")
p.chart("matrix", "scatterChart", xb, TOP, wb, h,
        {"Category": [C("Whitespace", "country")], "X": [sx], "Y": [sy], "Size": [ss]},
        f"Market size vs our share (bubble = untapped potential; dashed = {pct(K['benchmark_share'], 1)} benchmark)",
        {"categoryLabels": [{"properties": {"show": lit(True), "color": color(INK2)}}],
         "dataPoint": [{"properties": {"fill": color(BLUE)}}],
         "y1AxisReferenceLine": [ref_line(round(K["benchmark_share"], 4), "benchmark")],
         "valueAxis": [{"properties": {"start": lit(0)}}]},
        labels={qref(sx): "Estimated 2026 market, EUR m", qref(sy): "Our value share", qref(ss): "Untapped potential"})
y = TOP + h + GAP
up = meas("Untapped Potential (EUR m)")
p.chart("potential", "clusteredColumnChart", xa, y, wa, BOT - y, {"Category": [C("Whitespace", "country")], "Y": [up]},
        "Untapped potential by country, EUR m a year (countries at or above the benchmark have none)",
        no_legend({"dataPoint": [{"properties": {"fill": color(BLUE)}}], "labels": labels_on(),
                   "categoryAxis": [{"properties": {"fontSize": lit(9)}}]}),
        labels={qref(up): "EUR m"}, sort=(up, "Descending"),
        only=("Whitespace", "quadrant", ["Defend: share at benchmark"], True))
wc = ["country", "market_value_eur", "share_value", "untapped_potential_eur", "quadrant"]
p.chart("whiteTable", "tableEx", xb, y, wb, BOT - y,
        {"Values": [C("Whitespace", c) for c in wc] + [C("Country", "pci_cagr")]},
        "Where to invest: market, share, potential and real procedure growth since 2019",
        table_style([bg_rule(C("Whitespace", "untapped_potential_eur"), "#FCFCFB", SEQ["250"])], size=10),
        labels={"Whitespace.country": "Country", "Whitespace.region": "Region", "Whitespace.market_value_eur": "Market 2026 (est.)",
                "Whitespace.revenue_l12m": "Our revenue L12M", "Whitespace.share_value": "Share",
                "Whitespace.untapped_potential_eur": "Potential", "Whitespace.quadrant": "Decision",
                "Country.pci_cagr": "PCI growth p.a."},
        sort=(C("Whitespace", "untapped_potential_eur"), "Descending"))
p.footer(SRC_REAL + "   ·   Market value: estimate   ·   " + SRC_SIM)
pages.append(p)

# ======================= Page 2 - Sales performance =======================
p = Page("c2e3f4a5b6c7d8e9f0a1", "2 · Sales performance")
p.header(f"Revenue is {pct(-K['vs_target_ytd'], 1)} below target year to date: France and Germany explain "
         f"{pct(K['gap_fra_deu_share'])} of the {m1(-K['gap_ytd_m'])} gap",
         f"Revenue still grew {spct(K['growth_ytd'])} on last year: volume added {m1(K['pvm_volume_m'])} and mix {m1(K['pvm_mix_m'])} "
         f"(more drug-coated balloons, {spct(K['dcb_units_growth'], 0)} units), but price took {m1(-K['pvm_price_m'])}. Coronary stents "
         f"lost {pct(-K['des_price_change'], 1)} of price ({pct(K['des_price_share'])} of the price effect), Germany "
         f"{m1(-K['deu_price_effect_m'])} after its 2026 stent tender. The bridge closes exactly.", TAG_SIM)
y = kpi_row(p, [("Revenue YTD (EUR m)", "Revenue Jan-Oct 2026, EUR m"), ("Target YTD (EUR m)", "Target Jan-Oct 2026, EUR m"),
                ("Gap to Target YTD (EUR m)", "Gap to target, EUR m"), ("Revenue YTD Growth", "Growth vs Jan-Oct 2025")])
lw = W * 0.38
gp = meas("Gap to Target YTD (EUR m)")
p.chart("gapCountry", "clusteredBarChart", L, y, lw, BOT - y, {"Category": [C("Country", "country")], "Y": [gp]},
        "Gap to target by country, EUR m (red = below target)",
        no_legend({"dataPoint": [measure_fill("Gap Colour")], "labels": labels_on()}),
        labels={qref(gp): "Gap, EUR m"}, sort=(gp, "Ascending"))
rx = L + lw + GAP
rh = (BOT - y - GAP) * 0.5
bv = meas("Bridge Value")
p.chart("bridge", "waterfallChart", rx, y, R - rx, rh, {"Category": [C("PVM Bridge", "step")], "Y": [bv]},
        "Price-volume-mix bridge, Jan-Oct 2025 to Jan-Oct 2026 (last bar = total 2026), EUR",
        {"sentimentColors": [{"properties": {"increaseFill": color(BLUE), "decreaseFill": color(RED), "totalFill": color(GREY)}}],
         "labels": labels_on(), "legend": [{"properties": {"show": lit(False)}}],
         "valueAxis": [{"properties": {"start": lit(85000000)}}]},
        labels={qref(bv): "EUR"}, sort=(C("PVM Bridge", "step"), "Ascending"),
        only=("PVM Bridge", "step_order", [1, 2, 3, 4], False))
y2 = y + rh + GAP
(xc, wc_), (xd, wd) = cols(2, rx, R)
pc = ["country", "revenue_ly", "volume_effect", "mix_effect", "price_effect", "total_change"]
p.chart("pvmCountry", "tableEx", xc, y2, wc_, BOT - y2, {"Values": [C("PVM Country", c) for c in pc]},
        "Bridge by country (volume + mix + price = change)",
        table_style([bg_rule(C("PVM Country", "price_effect"), "#F4C7C6", "#FCFCFB")], size=10),
        labels={"PVM Country.country": "Country", "PVM Country.revenue_ly": "2025 YTD", "PVM Country.volume_effect": "Volume",
                "PVM Country.mix_effect": "Mix", "PVM Country.price_effect": "Price", "PVM Country.total_change": "Change"},
        sort=(C("PVM Country", "total_change"), "Ascending"))
pl = meas("Price Change by Line")
p.chart("priceLine", "clusteredBarChart", xd, y2, wd, BOT - y2, {"Category": [C("PVM Product", "product_line")], "Y": [pl]},
        "Net price change by product line, vs Jan-Oct 2025",
        no_legend({"dataPoint": [{"properties": {"fill": color(RED)}}], "labels": labels_on()}),
        labels={qref(pl): "Price change"}, sort=(pl, "Ascending"))
p.footer(SRC_SIM)
pages.append(p)

# ======================= Page 3 - Customers =======================
p = Page("d3f4a5b6c7d8e9f0a1b2", "3 · Customers")
p.header(f"{n(K['at_risk_accounts'])} hospitals are at risk: their last 3 months are {pct(at_risk_drop)} below a year earlier",
         f"The top 20% of hospitals make {pct(K['top20_revenue_share'])} of revenue, so a few lost tenders move the year: the flagged "
         f"accounts ({K['at_risk_fra']:.0f} in France) have lost a run-rate of about {m1(K['at_risk_lost_run_rate_m'])} a year. "
         f"Alert = last 3 months at least 30% below the same months last year, on accounts worth EUR 30 k+: it caught "
         f"{K['alert_true_positives']:.0f} of the {K['alert_true_positives'] + K['alert_missed']:.0f} losses built into the simulation, "
         f"{K['alert_false_alarms']:.0f} false alarms. "
         f"New hospitals since 2025 ({n(K['new_accounts'])}, {n(K['new_accounts_tur'])} in Türkiye) bring only "
         f"{pct(K['new_accounts_revenue_share'], 1)} of revenue so far.", TAG_SIM)
y = kpi_row(p, [("Active Accounts", "Hospitals buying (last 12 months)"), ("Top 20% Accounts Revenue Share", "Revenue share of the top 20%"),
                ("At-risk Accounts", "Hospitals flagged at risk"), ("New Accounts Revenue Share", "Revenue share of new hospitals")])
h = 360
INACTIVE = ("Account", "segment", ["6 · No sales in the last 24 months"], True)
cu = meas("Cumulative Revenue Share")
p.chart("pareto", "lineChart", xa, y, wa, h, {"Category": [C("Account", "size_percentile")], "Y": [cu]},
        "Cumulative share of revenue by hospital rank (Pareto curve, dashed = 80%)",
        no_legend({"dataPoint": [{"properties": {"fill": color(BLUE)}}], "categoryAxis": [{"properties": {"axisType": lit("Scalar")}}],
                   "valueAxis": [{"properties": {"start": lit(0), "end": lit(1)}}], "y1AxisReferenceLine": [ref_line(0.8, "80%")]}),
        labels={"Account.size_percentile": "Hospitals ranked by revenue (share of all)"}, only=INACTIVE)
sa, sr = meas("Segment Account Share"), meas("Segment Revenue Share")
p.chart("segments", "clusteredBarChart", xb, y, wb, h, {"Category": [C("Account Segments", "segment")], "Y": [sa, sr]},
        "Segments: share of hospitals (grey) vs share of revenue (blue), last 12 months",
        {"dataPoint": [series_color(sa, GREY), series_color(sr, BLUE)], "labels": labels_on()},
        labels={qref(sa): "Hospitals", qref(sr): "Revenue"}, sort=(C("Account Segments", "segment"), "Ascending"))
y += h + GAP
rc = ["account_id", "country", "account_type", "revenue_l3m_ly", "revenue_l3m", "growth_l3m", "segment"]
p.chart("riskTable", "tableEx", xa, y, wa, BOT - y, {"Values": [C("Account", c) for c in rc]},
        "Watch list: hospitals at risk, largest first (call before the next order cycle)",
        table_style([bg_rule(C("Account", "growth_l3m"), "#F4C7C6", "#FCFCFB")], size=11),
        labels={"Account.account_id": "Hospital", "Account.country": "Country", "Account.account_type": "Type",
                "Account.revenue_l3m_ly": "Aug-Oct 2025", "Account.revenue_l3m": "Aug-Oct 2026", "Account.growth_l3m": "Change",
                "Account.segment": "Segment"},
        sort=(C("Account", "revenue_l3m_ly"), "Descending"), only=("Account", "risk_flag", ["At risk"], False))
r3, r3l = meas("At-risk Rolling 3M"), meas("At-risk Rolling 3M LY")
p.chart("riskTrend", "lineChart", xb, y, wb, BOT - y, {"Category": [C("At-risk Rolling", "month")], "Y": [r3l, r3]},
        "The flagged hospitals together: rolling 3-month revenue (red) vs a year earlier (grey)",
        {"dataPoint": [series_color(r3, RED), series_color(r3l, GREY)], "valueAxis": [{"properties": {"start": lit(0)}}]},
        labels={qref(r3): "Rolling 3 months", qref(r3l): "Same months last year"})
p.footer(SRC_SIM)
pages.append(p)

# ======================= Page 4 - Forecast & business review =======================
p = Page("e4a5b6c7d8e9f0a1b2c3", "4 · Forecast")
p.header(f"2026 will end about {m1(-K['forecast_gap_m'])} ({pct(-K['forecast_vs_target'], 1)}) below target: even the best scenario misses",
         f"Forecast per country = same month last year x trailing 12-month growth. Checked on May-Oct 2026, hidden from the model: "
         f"{pct(K['mape_total'], 1)} monthly error. It over-forecast by EUR {K['holdout_overforecast_m']:.2f} m, almost exactly what the "
         f"at-risk hospitals lost (EUR {K['holdout_at_risk_drop_m']:.2f} m): the model cannot see lost tenders, the account alert can. "
         f"Reaching target would need {spct(K['needed_uplift'], 0)} on the November-December forecast.", TAG_SIM)
y = kpi_row(p, [("FY Forecast (EUR m)", "2026 forecast, EUR m"), ("FY Target (EUR m)", "2026 target, EUR m"),
                ("FY Gap (EUR m)", "Forecast gap to target, EUR m"), ("Hold-out MAPE", "Monthly error on 6 hidden months")])
h = 380
fa, fh, ff, ft = meas("Monthly Actual"), meas("Hold-out Prediction"), meas("Monthly Forecast"), meas("Monthly Target")
p.chart("forecastLine", "lineChart", L, y, W, h, {"Category": [C("Forecast Monthly", "month")], "Y": [fa, fh, ff, ft]},
        "Monthly revenue: actual (black), hold-out check (light blue), forecast Nov-Dec (blue), target (grey)",
        {"dataPoint": [series_color(fa, INK), series_color(fh, SEQ["250"]), series_color(ff, BLUE), series_color(ft, GREY)],
         "valueAxis": [{"properties": {"start": lit(0)}}]},
        labels={qref(fa): "Actual", qref(fh): "Hold-out prediction", qref(ff): "Forecast", qref(ft): "Target"})
y += h + GAP
(x1, w1), (x2, w2), (x3, w3) = cols(3)
sv = meas("Scenario Revenue (EUR m)")
p.chart("scenarios", "clusteredBarChart", x1, y, w1, BOT - y, {"Category": [C("Forecast Scenarios", "scenario")], "Y": [sv]},
        f"Full-year 2026 by scenario, EUR m (dashed = target {m1(K['target_fy_m'])})",
        no_legend({"dataPoint": [{"properties": {"fill": color(BLUE)}}], "labels": labels_on(),
                   "valueAxis": [{"properties": {"start": lit(100)}}],
                   "y1AxisReferenceLine": [ref_line(round(K["target_fy_m"], 1), "target")]}),
        labels={qref(sv): "EUR m"}, sort=(C("Forecast Scenarios", "scenario"), "Ascending"))
fc = ["country", "forecast_fy", "target_fy", "gap_fy", "vs_target_fy", "holdout_mape"]
p.chart("countryFc", "tableEx", x2, y, w2, BOT - y, {"Values": [C("Forecast Country", c) for c in fc]},
        "Full-year forecast by country (hold-out error per country)",
        table_style([bg_rule(C("Forecast Country", "gap_fy"), "#F4C7C6", "#FCFCFB")], size=10),
        labels={"Forecast Country.country": "Country", "Forecast Country.forecast_fy": "Forecast", "Forecast Country.target_fy": "Target",
                "Forecast Country.gap_fy": "Gap", "Forecast Country.vs_target_fy": "vs target", "Forecast Country.holdout_mape": "Error"},
        sort=(C("Forecast Country", "gap_fy"), "Ascending"))
mc = ["model", "mape_total", "mape_country_median", "error_6m_total"]
p.chart("models", "tableEx", x3, y, w3, (BOT - y) * 0.48, {"Values": [C("Forecast Models", c) for c in mc]},
        "Hold-out check, May-Oct 2026", table_style(size=11),
        labels={"Forecast Models.model": "Model", "Forecast Models.mape_total": "Error, total",
                "Forecast Models.mape_country_median": "Error, median country", "Forecast Models.error_6m_total": "Bias"})
ty = y + (BOT - y) * 0.48 + GAP
p.text("reading", x3, ty, w3, BOT - ty, [
    [("How to read it", 14, INK, True)],
    [(f"The naive model (same month last year) has a lower total error ({pct(K['mape_naive_total'], 1)}) but a higher error per "
      f"country. Both say the year misses by about {pct(-K['forecast_vs_target'], 0)}.", 12, INK2, False)],
], boxed=True)
p.footer(SRC_SIM)
pages.append(p)

# ======================= Page 5 - AI-automated reporting =======================
p = Page("f5b6c7d8e9f0a1b2c3d4", "5 · AI-automated reporting")
p.header(f"Claude got {SQL_OK} of {SQL_N} test questions right and wrote {REVIEWS} reviews with {UNSUP_ALL} untraceable numbers",
         "Deterministic work stays in SQL: every figure is computed first, then Claude only writes from those facts. A check extracts each "
         "number from the text and rejects the review if one is not in the facts. Questions in plain English become read-only SQL, and "
         "each answer shows its query. Reliability is measured, not assumed.", TAG_AI)
y = hero_row(p, [
    (f"{SQL_OK}/{SQL_N}", f"core questions right; {TRIALS_OK}/{TRIALS} over {S['sql_runs']} runs, as the model is not deterministic.",
     "TEXT-TO-SQL · ACCURACY"),
    (f"{STRESS_OK}/{STRESS_N}", "harder questions: vague wording ('last quarter') or definitions not in the prompt.",
     "TEXT-TO-SQL · STRESS TEST"),
    (f"{UNSUP_ALL} / {n(NUMS_ALL)}", f"numbers in {REVIEWS} generated reviews not found in the SQL facts; "
     f"{S['guard_passed']}/{S['guard_tests']} guard tests pass.", "REVIEWS · GROUNDING"),
    (f"~{HOURS:.0f} h", "saved a month, conservative: a person still reviews every output.", "TIME SAVED · ESTIMATE"),
], h=230)
lw = W * 0.30
p.text("pipeline", L, y, lw, BOT - y, [
    [("How it works", 17, INK, True)], [("", 6, INK, False)],
    [("1 · Facts in SQL  ", 14, BLUE, True), ("month vs target, gaps, price-volume-mix, at-risk hospitals: one JSON per review.", 13, INK, False)],
    [("2 · Claude writes  ", 14, BLUE, True), ("a one-page review from that JSON only (prompt in ai/prompts/).", 13, INK, False)],
    [("3 · Number check  ", 14, BLUE, True), ("any figure not in the JSON rejects the draft: one retry, then a plain template.", 13, INK, False)],
    [("4 · Questions  ", 14, BLUE, True), ("plain English to one SELECT; read-only database, file access off; the SQL is shown.", 13, INK, False)],
    [("", 6, INK, False)],
    [("SQL or LLM?  ", 14, INK, True), ("Numbers, joins, targets and forecasts: SQL and Python, always. The LLM writes and translates: "
                                        "summaries, plain-English questions. It never computes a figure that goes to management.", 13, INK2, False)],
    [("", 6, INK, False)],
    [("One command  ", 14, INK, True), ("python ai/mbr_generator.py --month 2026-10 --all-countries writes 20 reviews.", 13, INK2, False)],
], boxed=True)
mx = L + lw + GAP
(xa, wa), (xb, wb) = cols(2, mx, R)
th = (BOT - y - GAP) * 0.5
mb = ["month", "numbers_cited", "unsupported_first_draft", "unsupported_final", "accepted"]
p.chart("mbrEval", "tableEx", xa, y, wa, th, {"Values": [C("AI MBR Eval", c) for c in mb]},
        "Monthly reviews generated for Jan-Oct 2026: numbers cited and numbers not found",
        table_style(size=11),
        labels={"AI MBR Eval.month": "Month", "AI MBR Eval.numbers_cited": "Numbers cited",
                "AI MBR Eval.unsupported_first_draft": "Not found (draft)", "AI MBR Eval.unsupported_final": "Not found (published)",
                "AI MBR Eval.accepted": "Accepted"},
        sort=(C("AI MBR Eval", "month"), "Ascending"))
ts = ["task", "manual_hours", "automated_hours", "hours_saved"]
p.chart("timeSaving", "tableEx", xb, y, wb, th, {"Values": [C("AI Time Saving", c) for c in ts]},
        "Hours a month: by hand vs automated with review (assumptions in the README)", table_style(size=11, wrap=True),
        labels={"AI Time Saving.task": "Task", "AI Time Saving.manual_hours": "By hand", "AI Time Saving.automated_hours": "Automated",
                "AI Time Saving.hours_saved": "Saved"},
        sort=(C("AI Time Saving", "task"), "Ascending"))
y2 = y + th + GAP
qc, qn = meas("SQL Correct"), meas("SQL Wrong")
p.chart("sqlCategory", "barChart", xa, y2, wa, BOT - y2, {"Category": [C("AI SQL Eval", "category")], "Y": [qc, qn]},
        "Test questions by type (30 core + 10 stress), first run: right (blue), wrong (red)",
        {"dataPoint": [series_color(qc, BLUE), series_color(qn, RED)], "labels": labels_on("#FFFFFF"),
         "categoryAxis": [{"properties": {"fontSize": lit(8)}}]},
        labels={qref(qc): "Right", qref(qn): "Wrong"})
ERR = list(csv.DictReader(open(ROOT / "ai" / "eval_error_analysis.csv", encoding="utf-8")))
QTEXT = {r["id"]: r["question"] for r in csv.DictReader(open(ROOT / "ai" / "eval_questions.csv", encoding="utf-8"))}
paras = [[("Every wrong answer, read and explained", 14, INK, True)], [("", 6, INK, False)]]
for e in ERR:
    paras += [[(f"Q{e['id']} · {QTEXT[e['id']]}", 12, RED, True)], [(e["analysis"], 12, INK2, False)], [("", 6, INK, False)]]
p.text("sqlErrors", xb, y2, wb, BOT - y2, paras, boxed=True)
p.footer(SRC_SIM + "   ·   AI: Claude (claude-opus-5-5) via the Anthropic API; evaluation in ai/run_eval.py")
pages.append(p)

# ---------- write ----------
PAGES.mkdir(parents=True, exist_ok=True)
keep = {pg.pid for pg in pages}
for d in PAGES.iterdir():
    if d.is_dir() and d.name not in keep:
        shutil.rmtree(d)
for pg in pages:
    pg.write()
meta = {"$schema": PAGES_SCHEMA, "pageOrder": [pg.pid for pg in pages], "activePageName": pages[0].pid}
(PAGES / "pages.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
print("pages:", [(pg.name.encode("ascii", "replace").decode(), len(pg.visuals)) for pg in pages])
