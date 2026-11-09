"""Generate the Power BI semantic model (TMDL) for powerbi/CommercialExcellence.SemanticModel.

Usage:  python src/build_semantic_model.py      (close Power BI Desktop first: the definition folder is rewritten)
Star schema:
  facts       Sales (month x hospital x product line), Targets (month x country x product line), Market (country x line x year)
  dimensions  Date, Country (region, REAL procedures and population), Product, Account (hospital, segment, risk flag)
  analysis    outputs of sql/, the notebook and ai/run_eval.py (whitespace, bridge, forecast, AI evaluation)
The same logic transposes to Oracle Analytics Cloud: the tables become the OAC semantic model (logical layer),
and each measure below is defined once there as a logical column.
"""
import shutil
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "powerbi" / "CommercialExcellence.SemanticModel"
DEF = MODEL / "definition"
DATA_FOLDER = str(ROOT / "data") + "\\"

NS = uuid.UUID("8d3f6a10-2b7c-4e55-9c1a-6e0b5d2f7a31")
def tag(*parts):  # stable lineage tags: same name -> same tag on every rebuild
    return str(uuid.uuid5(NS, "/".join(parts)))

# type -> (TMDL dataType, Power Query type, default format string)
TYPES = {
    "text": ("string", "type text", None),
    "int": ("int64", "Int64.Type", "#,0"),
    "num": ("double", "type number", None),
    "date": ("dateTime", "type date", "dd mmm yyyy"),
    "bool": ("boolean", "type logical", None),
}
EUR, PCT, PCT1 = {"fmt": "#,0"}, {"fmt": "0%"}, {"fmt": "0.0%"}


def pq_types(cols):
    return "{" + ", ".join(f'{{"{c}", {TYPES[t][1]}}}' for c, t, *_ in cols) + "}"


def csv_source(path, cols, extra_steps=()):
    """path relative to the DataFolder parameter, e.g. 'clean\\sales.csv'. Keeps only the declared columns."""
    names = "{" + ", ".join(f'"{c}"' for c, *_ in cols) + "}"
    return [f'Source = Csv.Document(File.Contents(DataFolder & "{path}"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv])',
            "Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars=true])",
            f"Selected = Table.SelectColumns(Promoted, {names})",
            f'Typed = Table.TransformColumnTypes(Selected, {pq_types(cols)}, "en-US")', *extra_steps]


T = {}
# ---------------- facts ----------------
T["Sales"] = dict(cols=[("month", "date", {"fmt": "mmm yyyy"}), ("account_id", "text"), ("iso3", "text"), ("product_id", "text"),
                        ("units", "int"), ("net_price_eur", "num", {"fmt": "#,0.00"}), ("revenue_eur", "num", EUR)],
                  source=lambda c: csv_source("clean\\sales.csv", c),
                  note="SIMULATED invoiced sales: month x hospital x product line, Jan 2023 - Oct 2026 (src/generate_sales.py)")
T["Targets"] = dict(cols=[("month", "date", {"fmt": "mmm yyyy"}), ("iso3", "text"), ("product_id", "text"), ("target_eur", "num", EUR)],
                    source=lambda c: csv_source("clean\\targets.csv", c), note="SIMULATED monthly targets 2024-2026")
T["Market"] = dict(cols=[("iso3", "text"), ("year", "int", {"fmt": "0"}), ("product_id", "text"), ("pci_procedures", "int"),
                         ("pci_source", "text"), ("market_units", "int"), ("market_price_eur", "num", {"fmt": "#,0.00"}),
                         ("market_value_eur", "num", EUR)],
                   source=lambda c: csv_source("clean\\market_size.csv", c),
                   note="ESTIMATE: real OECD procedure count x assumed devices per procedure x assumed price")

# ---------------- dimensions ----------------
T["Date"] = dict(cols=[("Date", "date", {"key": True}), ("Month", "text", {"sort": "MonthKey"}), ("MonthKey", "int", {"hidden": True, "fmt": "0"}),
                       ("MonthStart", "date", {"fmt": "mmm yyyy"}), ("Year", "int", {"fmt": "0"}), ("MonthNo", "int", {"fmt": "0"}),
                       ("Quarter", "text")],
                 source=lambda c: [
                     "Dates = List.Dates(#date(2023, 1, 1), Duration.Days(#date(2026, 12, 31) - #date(2023, 1, 1)) + 1, #duration(1, 0, 0, 0))",
                     "T = Table.FromList(Dates, Splitter.SplitByNothing(), type table [Date = date])",
                     'M = Table.AddColumn(T, "Month", each Date.ToText([Date], "MMM yyyy", "en-US"), type text)',
                     'K = Table.AddColumn(M, "MonthKey", each Date.Year([Date]) * 100 + Date.Month([Date]), Int64.Type)',
                     'S = Table.AddColumn(K, "MonthStart", each Date.StartOfMonth([Date]), type date)',
                     'Y = Table.AddColumn(S, "Year", each Date.Year([Date]), Int64.Type)',
                     'N = Table.AddColumn(Y, "MonthNo", each Date.Month([Date]), Int64.Type)',
                     'Typed = Table.AddColumn(N, "Quarter", each "Q" & Text.From(Date.QuarterOfYear([Date])), type text)'],
                 data_category="Time")
T["Country"] = dict(cols=[("iso3", "text", {"key": True}), ("iso2", "text"), ("country", "text"), ("region", "text"), ("subregion", "text"),
                          ("pci_year", "int", {"fmt": "0"}), ("pci_procedures", "int"), ("pci_per_100k", "num", {"fmt": "0"}),
                          ("pci_cagr", "num", PCT1), ("population", "int"), ("gdp_per_capita_usd", "int"),
                          ("health_exp_per_capita_usd", "int"), ("price_index", "num", {"fmt": "0.00"})],
                    source=lambda c: csv_source("clean\\countries.csv", c),
                    note="REAL: OECD coronary angioplasty counts (CM36_TRS), World Bank population, GDP and health spending")
T["Product"] = dict(cols=[("product_id", "text", {"key": True}), ("product_line", "text"), ("family", "text"),
                          ("units_per_pci", "num", {"fmt": "0.00"}), ("ref_price_eur", "num", EUR), ("price_erosion", "num", PCT1)],
                    source=lambda c: csv_source("clean\\products.csv", c), note="Generic product lines (no brand names)")
ACC = [("country", "text"), ("region", "text"), ("first_invoice", "date"), ("revenue_l12m", "num", EUR), ("revenue_p12m", "num", EUR),
       ("revenue_l3m", "num", EUR), ("revenue_l3m_ly", "num", EUR), ("growth_l12m", "num", PCT), ("growth_l3m", "num", PCT),
       ("is_new_account", "bool"), ("risk_flag", "text"), ("revenue_rank", "int"), ("cum_revenue_share", "num", PCT1),
       ("size_percentile", "num", PCT1), ("segment", "text")]
T["Account"] = dict(cols=[("account_id", "text", {"key": True}), ("account_name", "text"), ("account_type", "text")] + ACC,
                    source=lambda c: [
                        'Base = Table.SelectColumns(Table.PromoteHeaders(Csv.Document(File.Contents(DataFolder & "clean\\accounts.csv"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]), [PromoteAllScalars=true]), {"account_id", "account_name", "account_type"})',
                        'Card = Table.PromoteHeaders(Csv.Document(File.Contents(DataFolder & "output\\04_accounts.csv"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]), [PromoteAllScalars=true])',
                        f'CardCols = Table.SelectColumns(Card, {{"account_id", {", ".join(chr(34) + a[0] + chr(34) for a in ACC)}}})',
                        'Merged = Table.NestedJoin(Base, {"account_id"}, CardCols, {"account_id"}, "card", JoinKind.LeftOuter)',
                        f'Expanded = Table.ExpandTableColumn(Merged, "card", {{{", ".join(chr(34) + a[0] + chr(34) for a in ACC)}}})',
                        'Filled = Table.ReplaceValue(Table.ReplaceValue(Expanded, null, "6 · No sales in the last 24 months", Replacer.ReplaceValue, {"segment"}), null, "Inactive", Replacer.ReplaceValue, {"risk_flag"})',
                        f'Typed = Table.TransformColumnTypes(Filled, {pq_types(c)}, "en-US")'],
                    note="SIMULATED hospitals, with the account scorecard of sql/04_account_risk.sql (segment, risk flag, Pareto rank)")

# ---------------- analysis tables (data/output) ----------------
def out(file, cols, note=None, extra=()):
    return dict(cols=cols, source=lambda c, f=file, e=extra: csv_source("output\\" + f, c, e), note=note)

T["Whitespace"] = out("01_market_whitespace.csv", [
    ("iso3", "text"), ("country", "text"), ("region", "text"), ("market_value_eur", "num", EUR), ("revenue_l12m", "num", EUR),
    ("share_value", "num", PCT1), ("benchmark_share", "num", PCT1), ("untapped_potential_eur", "num", EUR),
    ("potential_rank", "int"), ("potential_share", "num", PCT), ("quadrant", "text"), ("revenue_growth_l12m", "num", PCT)],
    "Market size vs our share, untapped potential (sql/01_market_size.sql)")
T["PCI Trend"] = out("01_market_trend.csv", [("iso3", "text"), ("year", "int", {"fmt": "0"}), ("pci_procedures", "int"),
                                             ("pci_per_100k", "num", {"fmt": "0"})], "REAL OECD procedure counts by year")
T["PVM Bridge"] = out("03_pvm_total.csv", [("step_order", "int", {"hidden": True}), ("step", "text", {"sort": "step_order"}),
                                           ("value", "num", EUR), ("kind", "text")], "Price-volume-mix bridge, Jan-Oct 2025 -> 2026")
T["PVM Country"] = out("03_pvm_country.csv", [("iso3", "text"), ("country", "text"), ("revenue_ly", "num", EUR), ("revenue_cy", "num", EUR),
                                             ("volume_effect", "num", EUR), ("mix_effect", "num", EUR), ("price_effect", "num", EUR),
                                             ("total_change", "num", EUR), ("closure_check", "num", {"fmt": "0.00"})])
T["PVM Product"] = out("03_pvm_product.csv", [("product_id", "text"), ("product_line", "text"), ("revenue_ly", "num", EUR),
                                             ("revenue_cy", "num", EUR), ("units_growth", "num", PCT1), ("price_effect", "num", EUR),
                                             ("price_change_pct", "num", PCT1)])
T["Account Segments"] = out("04_segments.csv", [("segment", "text"), ("accounts", "int"), ("revenue_l12m", "num", EUR),
                                                ("revenue_share", "num", PCT), ("growth", "num", PCT)])
T["At-risk Rolling"] = out("04_account_rolling_at_risk.csv", [("account_id", "text"), ("month", "date", {"fmt": "mmm yyyy"}),
                                                              ("rev_3m", "num", EUR), ("rev_3m_ly", "num", EUR)],
                           "Rolling 3-month revenue of the flagged accounts vs the same 3 months a year earlier")
T["Forecast Monthly"] = out("05_forecast_monthly.csv", [("month", "date", {"fmt": "mmm yyyy"}), ("actual", "num", EUR),
                                                        ("holdout_pred", "num", EUR), ("forecast", "num", EUR), ("target", "num", EUR)])
T["Forecast Country"] = out("05_forecast_country.csv", [("iso3", "text"), ("country", "text"), ("revenue_ytd", "num", EUR),
                                                        ("forecast_nov_dec", "num", EUR), ("forecast_fy", "num", EUR), ("target_fy", "num", EUR),
                                                        ("gap_fy", "num", EUR), ("vs_target_fy", "num", PCT1), ("holdout_mape", "num", PCT1)])
T["Forecast Scenarios"] = out("05_forecast_scenarios.csv", [("scenario", "text", {"sort": "order"}), ("revenue_fy", "num", EUR),
                                                            ("target_fy", "num", EUR), ("gap", "num", EUR), ("vs_target", "num", PCT1),
                                                            ("order", "int", {"hidden": True})])
T["Forecast Models"] = out("05_forecast_models.csv", [("model", "text"), ("mape_total", "num", PCT1),
                                                      ("mape_country_median", "num", PCT1), ("error_6m_total", "num", PCT1)])
T["AI SQL Eval"] = out("ai_eval_results.csv", [("id", "int", {"fmt": "0"}), ("category", "text"), ("question", "text"),
                                               ("gold_answer", "text"), ("generated_answer", "text"), ("correct", "bool"),
                                               ("error_type", "text"), ("analysis", "text")],
                       "30 test questions: gold SQL written by hand vs SQL generated by Claude (ai/run_eval.py)")
T["AI MBR Eval"] = out("ai_eval_mbr.csv", [("month", "text"), ("numbers_cited", "int"), ("unsupported_first_draft", "int"),
                                           ("attempts", "int"), ("unsupported_final", "int"), ("accepted", "bool"), ("words", "int")])
T["AI Guards"] = out("ai_eval_guards.csv", [("test", "text"), ("passed", "bool")])
T["AI Time Saving"] = out("ai_time_saving.csv", [("order", "int", {"hidden": True}), ("task", "text", {"sort": "order"}),
                                                 ("manual_hours", "num", {"fmt": "0.0"}), ("automated_hours", "num", {"fmt": "0.0"}),
                                                 ("hours_saved", "num", {"fmt": "0.0"}), ("assumption", "text")])

# ---------------- measures ----------------
ASOF = "VAR a = [As-of Month]"
YTD = "DATESBETWEEN ( 'Date'[Date], DATE ( YEAR ( a ), 1, 1 ), EOMONTH ( a, 0 ) )"
YTD_LY = "DATESBETWEEN ( 'Date'[Date], DATE ( YEAR ( a ) - 1, 1, 1 ), EOMONTH ( EDATE ( a, -12 ), 0 ) )"
L12M = "DATESBETWEEN ( 'Date'[Date], EDATE ( a, -11 ), EOMONTH ( a, 0 ) )"
MEASURES = [
    # name, expression, format, folder
    ("Revenue", "SUM ( Sales[revenue_eur] )", "#,0", "1 Sales"),
    ("Revenue (EUR m)", "DIVIDE ( [Revenue], 1000000 )", "#,0.0", "1 Sales"),
    ("Units", "SUM ( Sales[units] )", "#,0", "1 Sales"),
    ("Avg Net Price", "DIVIDE ( [Revenue], [Units] )", "#,0.00", "1 Sales"),
    ("As-of Month", "CALCULATE ( MAX ( Sales[month] ), REMOVEFILTERS () )", "mmm yyyy", "1 Sales"),
    ("Revenue YTD", f"{ASOF} RETURN CALCULATE ( [Revenue], {YTD} )", "#,0", "1 Sales"),
    ("Revenue YTD (EUR m)", "DIVIDE ( [Revenue YTD], 1000000 )", "#,0.0", "1 Sales"),
    ("Revenue YTD LY", f"{ASOF} RETURN CALCULATE ( [Revenue], {YTD_LY} )", "#,0", "1 Sales"),
    ("Revenue YTD Growth", "DIVIDE ( [Revenue YTD], [Revenue YTD LY] ) - 1", "+0.0%;-0.0%", "1 Sales"),
    ("Revenue L12M", f"{ASOF} RETURN CALCULATE ( [Revenue], {L12M} )", "#,0", "1 Sales"),
    ("Revenue LY", "CALCULATE ( [Revenue], DATEADD ( 'Date'[Date], -1, YEAR ) )", "#,0", "1 Sales"),
    ("Revenue YoY", "DIVIDE ( [Revenue], [Revenue LY] ) - 1", "+0.0%;-0.0%", "1 Sales"),
    ("Target", "SUM ( Targets[target_eur] )", "#,0", "2 Targets"),
    ("Target YTD", f"{ASOF} RETURN CALCULATE ( [Target], {YTD} )", "#,0", "2 Targets"),
    ("Target YTD (EUR m)", "DIVIDE ( [Target YTD], 1000000 )", "#,0.0", "2 Targets"),
    ("Gap to Target YTD", "[Revenue YTD] - [Target YTD]", "#,0", "2 Targets"),
    ("Gap to Target YTD (EUR m)", "DIVIDE ( [Gap to Target YTD], 1000000 )", "+#,0.00;-#,0.00", "2 Targets"),
    ("vs Target YTD", "DIVIDE ( [Revenue YTD], [Target YTD] ) - 1", "+0.0%;-0.0%", "2 Targets"),
    ("Target FY", f"{ASOF} RETURN CALCULATE ( [Target], DATESBETWEEN ( 'Date'[Date], DATE ( YEAR ( a ), 1, 1 ), DATE ( YEAR ( a ), 12, 31 ) ) )", "#,0", "2 Targets"),
    ("Gap Colour", 'IF ( [Gap to Target YTD] < 0, "#D03B3B", "#2A78D6" )', None, "2 Targets"),
    ("PCI Procedures", "SUM ( Country[pci_procedures] )", "#,0", "3 Market"),
    ("PCI per 100k", "AVERAGE ( Country[pci_per_100k] )", "#,0", "3 Market"),
    ("PCI Growth p.a. since 2019", "AVERAGE ( Country[pci_cagr] )", "+0.0%;-0.0%", "3 Market"),
    ("Market Value 2026", "CALCULATE ( SUM ( Market[market_value_eur] ), Market[year] = 2026 )", "#,0", "3 Market"),
    ("Market Share L12M", "DIVIDE ( [Revenue L12M], [Market Value 2026] )", "0.0%", "3 Market"),
    ("Untapped Potential", "SUM ( Whitespace[untapped_potential_eur] )", "#,0", "3 Market"),
    ("Untapped Potential (EUR m)", "DIVIDE ( [Untapped Potential], 1000000 )", "#,0.0", "3 Market"),
    ("Benchmark Share", "MAX ( Whitespace[benchmark_share] )", "0.0%", "3 Market"),
    ("Market Value (EUR m)", "DIVIDE ( SUM ( Whitespace[market_value_eur] ), 1000000 )", "#,0", "3 Market"),
    ("Value Share", "DIVIDE ( SUM ( Whitespace[revenue_l12m] ), SUM ( Whitespace[market_value_eur] ) )", "0.0%", "3 Market"),
    ("Bridge Value", "SUM ( 'PVM Bridge'[value] )", "#,0", "4 Price-volume-mix"),
    ("Volume Effect", "SUM ( 'PVM Country'[volume_effect] )", "#,0", "4 Price-volume-mix"),
    ("Mix Effect", "SUM ( 'PVM Country'[mix_effect] )", "#,0", "4 Price-volume-mix"),
    ("Price Effect", "SUM ( 'PVM Country'[price_effect] )", "#,0", "4 Price-volume-mix"),
    ("Revenue Change", "SUM ( 'PVM Country'[total_change] )", "#,0", "4 Price-volume-mix"),
    ("Bridge Closure Check", "[Volume Effect] + [Mix Effect] + [Price Effect] - [Revenue Change]", "#,0.00", "4 Price-volume-mix"),
    ("Price Change by Line", "AVERAGE ( 'PVM Product'[price_change_pct] )", "+0.0%;-0.0%", "4 Price-volume-mix"),
    ("Active Accounts", "CALCULATE ( COUNTROWS ( Account ), Account[revenue_l12m] > 0, NOT ISBLANK ( Account[revenue_l12m] ) )", "#,0", "5 Accounts"),
    ("At-risk Accounts", 'CALCULATE ( COUNTROWS ( Account ), Account[risk_flag] = "At risk" )', "#,0", "5 Accounts"),
    ("At-risk Revenue L3M", 'CALCULATE ( SUM ( Account[revenue_l3m] ), Account[risk_flag] = "At risk" )', "#,0", "5 Accounts"),
    ("At-risk Revenue L3M LY", 'CALCULATE ( SUM ( Account[revenue_l3m_ly] ), Account[risk_flag] = "At risk" )', "#,0", "5 Accounts"),
    ("Top 20% Accounts Revenue Share",
     "DIVIDE ( CALCULATE ( SUM ( Account[revenue_l12m] ), Account[size_percentile] < 0.2, NOT ISBLANK ( Account[size_percentile] ) ), SUM ( Account[revenue_l12m] ) )",
     "0%", "5 Accounts"),
    ("New Accounts Revenue Share", "DIVIDE ( CALCULATE ( SUM ( Account[revenue_l12m] ), Account[is_new_account] = TRUE () ), SUM ( Account[revenue_l12m] ) )",
     "0.0%", "5 Accounts"),
    ("Cumulative Revenue Share", "MAX ( Account[cum_revenue_share] )", "0%", "5 Accounts"),
    ("Segment Revenue Share", "SUM ( 'Account Segments'[revenue_share] )", "0%", "5 Accounts"),
    ("Segment Account Share", "DIVIDE ( SUM ( 'Account Segments'[accounts] ), CALCULATE ( SUM ( 'Account Segments'[accounts] ), ALL ( 'Account Segments' ) ) )", "0%", "5 Accounts"),
    ("At-risk Rolling 3M", "SUM ( 'At-risk Rolling'[rev_3m] )", "#,0", "5 Accounts"),
    ("At-risk Rolling 3M LY", "SUM ( 'At-risk Rolling'[rev_3m_ly] )", "#,0", "5 Accounts"),
    ("Monthly Actual", "SUM ( 'Forecast Monthly'[actual] )", "#,0", "6 Forecast"),
    ("Hold-out Prediction", "SUM ( 'Forecast Monthly'[holdout_pred] )", "#,0", "6 Forecast"),
    ("Monthly Forecast", "SUM ( 'Forecast Monthly'[forecast] )", "#,0", "6 Forecast"),
    ("Monthly Target", "SUM ( 'Forecast Monthly'[target] )", "#,0", "6 Forecast"),
    ("FY Forecast", "SUM ( 'Forecast Country'[forecast_fy] )", "#,0", "6 Forecast"),
    ("FY Forecast (EUR m)", "DIVIDE ( [FY Forecast], 1000000 )", "#,0.0", "6 Forecast"),
    ("FY Target (EUR m)", "DIVIDE ( SUM ( 'Forecast Country'[target_fy] ), 1000000 )", "#,0.0", "6 Forecast"),
    ("FY Gap (EUR m)", "[FY Forecast (EUR m)] - [FY Target (EUR m)]", "+#,0.0;-#,0.0", "6 Forecast"),
    ("FY vs Target", "DIVIDE ( [FY Forecast (EUR m)], [FY Target (EUR m)] ) - 1", "+0.0%;-0.0%", "6 Forecast"),
    ("Scenario Revenue (EUR m)", "DIVIDE ( SUM ( 'Forecast Scenarios'[revenue_fy] ), 1000000 )", "#,0.0", "6 Forecast"),
    ("Hold-out MAPE", "CALCULATE ( MIN ( 'Forecast Models'[mape_total] ), 'Forecast Models'[model] = \"Seasonal x trailing growth\" )", "0.0%", "6 Forecast"),
    ("SQL Questions", "COUNTROWS ( 'AI SQL Eval' )", "0", "7 AI evaluation"),
    ("SQL Correct", "CALCULATE ( COUNTROWS ( 'AI SQL Eval' ), 'AI SQL Eval'[correct] = TRUE () )", "0", "7 AI evaluation"),
    ("SQL Accuracy", "DIVIDE ( [SQL Correct], [SQL Questions] )", "0%", "7 AI evaluation"),
    ("SQL Wrong", "[SQL Questions] - [SQL Correct]", "0", "7 AI evaluation"),
    ("MBR Numbers Cited", "SUM ( 'AI MBR Eval'[numbers_cited] )", "#,0", "7 AI evaluation"),
    ("MBR Unsupported (first draft)", "SUM ( 'AI MBR Eval'[unsupported_first_draft] )", "0", "7 AI evaluation"),
    ("MBR Unsupported (published)", "SUM ( 'AI MBR Eval'[unsupported_final] )", "0", "7 AI evaluation"),
    ("Guard Tests Passed", "CALCULATE ( COUNTROWS ( 'AI Guards' ), 'AI Guards'[passed] = TRUE () )", "0", "7 AI evaluation"),
    ("Hours Saved per Month", "SUM ( 'AI Time Saving'[hours_saved] )", "0", "7 AI evaluation"),
]

RELATIONSHIPS = [
    ("Sales", "month", "Date", "Date"), ("Sales", "iso3", "Country", "iso3"), ("Sales", "product_id", "Product", "product_id"),
    ("Sales", "account_id", "Account", "account_id"),
    ("Targets", "month", "Date", "Date"), ("Targets", "iso3", "Country", "iso3"), ("Targets", "product_id", "Product", "product_id"),
    ("Market", "iso3", "Country", "iso3"), ("Market", "product_id", "Product", "product_id"),
    ("Whitespace", "iso3", "Country", "iso3"), ("PCI Trend", "iso3", "Country", "iso3"),
    ("PVM Country", "iso3", "Country", "iso3"), ("Forecast Country", "iso3", "Country", "iso3"),
    ("At-risk Rolling", "account_id", "Account", "account_id"),
]


# ---------------- writers ----------------
def q(name):
    return f"'{name}'" if any(ch in name for ch in " -()%&·.") or name[0].isdigit() else name


def write_table(name, spec):
    cols = spec["cols"]
    out = [f"table {q(name)}", f"\tlineageTag: {tag(name)}"]
    if spec.get("data_category"):
        out.append(f"\tdataCategory: {spec['data_category']}")
    out.append("")
    for c, t, *opt in cols:
        o = opt[0] if opt else {}
        dt, _, fmt = TYPES[t]
        out.append(f"\tcolumn {q(c)}")
        out.append(f"\t\tdataType: {dt}")
        if o.get("key"):
            out.append("\t\tisKey")
        if o.get("hidden"):
            out.append("\t\tisHidden")
        f = o.get("fmt", fmt)
        if f:
            out.append(f"\t\tformatString: {f}")
        out.append(f"\t\tlineageTag: {tag(name, c)}")
        out.append("\t\tsummarizeBy: none")
        out.append(f"\t\tsourceColumn: {c}")
        if o.get("sort"):
            out.append(f"\t\tsortByColumn: {o['sort']}")
        if t == "date":
            out += ["", "\t\tannotation UnderlyingDateTimeDataType = Date"]
        out.append("")
    steps = spec["source"](cols)
    out += [f"\tpartition {q(name)} = m", "\t\tmode: import", "\t\tsource =", "\t\t\t\tlet"]
    out += [f"\t\t\t\t\t{s}{',' if i < len(steps) - 1 else ''}" for i, s in enumerate(steps)]
    out += ["\t\t\t\tin", "\t\t\t\t\t" + steps[-1].split(" = ")[0], ""]
    if spec.get("note"):
        out.insert(0, f"/// {spec['note']}")
    return "\n".join(out) + "\n"


def write_measures():
    out = ["table _Measures", f"\tlineageTag: {tag('_Measures')}", ""]
    for name, expr, fmt, folder in MEASURES:
        out.append(f"\tmeasure {q(name)} = {expr}")
        if fmt:
            out.append(f"\t\tformatString: {fmt}")
        out += [f"\t\tdisplayFolder: {folder}", f"\t\tlineageTag: {tag('_Measures', name)}", ""]
    out += ["\tcolumn _", "\t\tdataType: string", "\t\tisHidden", f"\t\tlineageTag: {tag('_Measures', '_')}",
            "\t\tsummarizeBy: none", "\t\tsourceColumn: _", "",
            "\tpartition _Measures = m", "\t\tmode: import", "\t\tsource = #table(type table [_ = text], {})", ""]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    if DEF.exists():
        shutil.rmtree(DEF)
    (DEF / "tables").mkdir(parents=True)
    order = list(T) + ["_Measures"]
    (DEF / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1606\n\n", encoding="utf-8")
    (DEF / "model.tmdl").write_text(
        "model Model\n\tculture: en-US\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n\tsourceQueryCulture: en-US\n"
        "\tdataAccessOptions\n\t\tlegacyRedirects\n\t\treturnErrorValuesAsNull\n\n"
        "annotation __PBI_TimeIntelligenceEnabled = 0\n\n"
        f"annotation PBI_QueryOrder = [{','.join(chr(34) + n + chr(34) for n in order + ['DataFolder'])}]\n\n"
        + "".join(f"ref table {q(n)}\n" for n in order) + "\n", encoding="utf-8")
    (DEF / "expressions.tmdl").write_text(
        f'expression DataFolder = "{DATA_FOLDER}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]\n'
        f"\tlineageTag: {tag('DataFolder')}\n\n\tannotation PBI_ResultType = Text\n\n", encoding="utf-8")
    rels = []
    for i, (ft, fc, tt, tc) in enumerate(RELATIONSHIPS, 1):
        rels += [f"relationship rel_{i:02d}", f"\tfromColumn: {q(ft)}.{q(fc)}", f"\ttoColumn: {q(tt)}.{q(tc)}", ""]
    (DEF / "relationships.tmdl").write_text("\n".join(rels) + "\n", encoding="utf-8")
    for name, spec in T.items():
        (DEF / "tables" / f"{name}.tmdl").write_text(write_table(name, spec), encoding="utf-8")
    (DEF / "tables" / "_Measures.tmdl").write_text(write_measures(), encoding="utf-8")
    (MODEL / "definition.pbism").write_text('{\n  "version": "4.2",\n  "settings": {}\n}', encoding="utf-8")
    (MODEL / ".platform").write_text(
        '{\n  "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",\n'
        '  "metadata": {\n    "type": "SemanticModel",\n    "displayName": "CommercialExcellence"\n  },\n'
        f'  "config": {{\n    "version": "2.0",\n    "logicalId": "{tag("model-logical")}"\n  }}\n}}', encoding="utf-8")
    print(f"{len(T)} tables, {len(MEASURES)} measures, {len(RELATIONSHIPS)} relationships -> {DEF}")
