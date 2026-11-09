"""Monthly Business Review, generated in one command.

Usage:  python ai/mbr_generator.py --month 2026-10            (uses Claude if ANTHROPIC_API_KEY is set)
        python ai/mbr_generator.py --month 2026-10 --offline  (template text, no LLM)
Steps:
  1. facts    SQL on data/commercial.duckdb (read-only) -> one JSON document, numbers already rounded for display
  2. writing  Claude writes the summary from that JSON only (prompt: ai/prompts/mbr_system.md)
  3. check    every number in the text must exist in the JSON; otherwise one retry with the list of bad numbers,
              then the summary is REJECTED and the deterministic template is used instead
Output: docs/mbr/MBR_<month>.md and docs/mbr/facts_<month>.json
"""
import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (ROOT, MODEL, call_claude, check_numbers, connect_read_only, has_api_key,  # noqa: E402
                    load_prompt, to_json)

OUT = ROOT / "docs" / "mbr"


def eur(x):
    return f"EUR {x / 1e6:.2f} m" if abs(x) >= 1e6 else f"EUR {x / 1e3:.0f} k"


def pct(x):
    return f"{x * 100:+.1f}%"


def build_facts(month, iso3=None):
    """month: 'YYYY-MM'; iso3: one country (e.g. 'FRA') or None for all countries.
    All figures come from SQL; Python only formats them."""
    m = dt.date.fromisoformat(month + "-01")
    y0 = dt.date(m.year, 1, 1)
    ly_m, ly_y0 = m.replace(year=m.year - 1), dt.date(m.year - 1, 1, 1)
    con = connect_read_only()
    p = {"m": m, "y0": y0, "lym": ly_m, "ly0": ly_y0, "c": iso3}
    cf = "AND iso3 = $c" if iso3 else ""             # country filter added to every query
    cfr = "AND r.iso3 = $c" if iso3 else ""

    def params(sql):          # DuckDB wants exactly the named parameters the query uses
        return {k: v for k, v in p.items() if f"${k}" in sql}

    def one(sql):
        return con.execute(sql, params(sql)).df()

    tot = one("""
        SELECT sum(revenue_eur) FILTER (WHERE month = $m)                 AS rev_m,
               sum(target_eur)  FILTER (WHERE month = $m)                 AS tgt_m,
               sum(revenue_eur) FILTER (WHERE month = $lym)               AS rev_m_ly,
               sum(revenue_eur) FILTER (WHERE month BETWEEN $y0 AND $m)   AS rev_ytd,
               sum(target_eur)  FILTER (WHERE month BETWEEN $y0 AND $m)   AS tgt_ytd,
               sum(revenue_eur) FILTER (WHERE month BETWEEN $ly0 AND $lym) AS rev_ytd_ly
        FROM v_monthly WHERE TRUE {cf}""".replace("{cf}", cf)).iloc[0]
    fy_target = one(f"SELECT sum(target_eur) AS t FROM targets WHERE year(month) = year($m) {cf}").t.iloc[0]

    def by(dim_sql, key):
        return one(f"""
            SELECT {dim_sql} AS name,
                   sum(revenue_eur) FILTER (WHERE month BETWEEN $y0 AND $m)    AS rev,
                   sum(target_eur)  FILTER (WHERE month BETWEEN $y0 AND $m)    AS tgt,
                   sum(revenue_eur) FILTER (WHERE month BETWEEN $ly0 AND $lym) AS rev_ly
            FROM v_monthly v JOIN countries c USING (iso3) JOIN products p USING (product_id)
            WHERE TRUE {cf}
            GROUP BY 1""").assign(gap=lambda d: d.rev - d.tgt).sort_values("gap")

    region, country, line = by("c.region", "region"), by("c.country", "country"), by("p.product_line", "line")

    def row(r, label):
        return {label: r["name"], "revenue_ytd": eur(r.rev), "gap_to_target": eur(r.gap),
                "vs_target": pct(r.rev / r.tgt - 1), "vs_last_year": pct(r.rev / r.rev_ly - 1)}

    pvm = one(f"""
        WITH cells AS (
            SELECT iso3, product_id,
                   sum(units)       FILTER (WHERE month BETWEEN $ly0 AND $lym) AS q0,
                   sum(revenue_eur) FILTER (WHERE month BETWEEN $ly0 AND $lym) AS r0,
                   sum(units)       FILTER (WHERE month BETWEEN $y0 AND $m)    AS q1,
                   sum(revenue_eur) FILTER (WHERE month BETWEEN $y0 AND $m)    AS r1
            FROM sales WHERE TRUE {cf} GROUP BY ALL
        ), c2 AS (
            SELECT iso3, product_id, coalesce(q0, 0) q0, coalesce(r0, 0) r0, coalesce(q1, 0) q1, coalesce(r1, 0) r1,
                   CASE WHEN coalesce(q0, 0) > 0 THEN r0 / q0 ELSE r1 / q1 END AS p0,
                   CASE WHEN coalesce(q1, 0) > 0 THEN r1 / q1 ELSE r0 / q0 END AS p1
            FROM cells
        ), ctry AS (
            SELECT iso3, sum(q0) q0, sum(r0) r0, sum(q1) q1, sum(r1) r1, sum(q1 * p0) r1p0, sum(q1 * (p1 - p0)) price
            FROM c2 GROUP BY iso3
        )
        SELECT sum(r0) r0, sum((q1 - q0) * r0 / q0) volume, sum(r1p0 - q1 * r0 / q0) mix, sum(price) price, sum(r1) r1
        FROM ctry""").iloc[0]
    worst_price = one(f"""
        WITH c AS (
            SELECT product_id, iso3,
                   sum(units) FILTER (WHERE month BETWEEN $y0 AND $m) q1,
                   sum(revenue_eur) FILTER (WHERE month BETWEEN $y0 AND $m) / sum(units) FILTER (WHERE month BETWEEN $y0 AND $m) p1,
                   sum(revenue_eur) FILTER (WHERE month BETWEEN $ly0 AND $lym) / sum(units) FILTER (WHERE month BETWEEN $ly0 AND $lym) p0
            FROM sales WHERE TRUE {cf} GROUP BY ALL
        )
        SELECT pr.product_line, sum(q1 * (p1 - p0)) AS price_effect, sum(q1 * (p1 - p0)) / sum(q1 * p0) AS price_change
        FROM c JOIN products pr USING (product_id) WHERE p0 IS NOT NULL AND p1 IS NOT NULL
        GROUP BY 1 ORDER BY price_effect LIMIT 1""").iloc[0]

    risk = one(f"""
        SELECT r.account_id, c.country, a.account_type, r.rev_3m, r.rev_3m_ly
        FROM v_account_rolling r JOIN accounts a USING (account_id) JOIN countries c ON c.iso3 = r.iso3
        WHERE r.month = $m AND r.rev_3m_ly >= 30000 AND r.rev_3m <= 0.7 * r.rev_3m_ly {cfr}
        ORDER BY r.rev_3m_ly - r.rev_3m DESC""")
    con.close()

    below = country[country.gap < 0]
    facts = {
        "period": {"month": m.strftime("%B %Y"), "year_to_date": f"January-{m.strftime('%B %Y')}",
                   "same_period_last_year": f"January-{ly_m.strftime('%B %Y')}"},
        "scope": country.name.iloc[0] if iso3 else "All countries (EMEA and APAC)",
        "data_label": "SIMULATED sales data (case study)",
        "month": {"revenue": eur(tot.rev_m), "target": eur(tot.tgt_m), "vs_target": pct(tot.rev_m / tot.tgt_m - 1),
                  "revenue_same_month_last_year": eur(tot.rev_m_ly), "vs_last_year": pct(tot.rev_m / tot.rev_m_ly - 1)},
        "year_to_date": {"revenue": eur(tot.rev_ytd), "target": eur(tot.tgt_ytd), "gap_to_target": eur(tot.rev_ytd - tot.tgt_ytd),
                         "vs_target": pct(tot.rev_ytd / tot.tgt_ytd - 1), "revenue_last_year": eur(tot.rev_ytd_ly),
                         "vs_last_year": pct(tot.rev_ytd / tot.rev_ytd_ly - 1), "full_year_target": eur(fy_target)},
        "regions": [row(r, "region") for _, r in region.iterrows()],
        "countries_below_target": {"count": int(len(below)), "out_of": int(len(country)),
                                   "largest_gaps": [row(r, "country") for _, r in below.head(3).iterrows()]},
        "countries_above_target_largest": [row(r, "country") for _, r in country[country.gap > 0].iloc[::-1].head(3).iterrows()],
        "product_lines": [row(r, "product_line") for _, r in line.iterrows()],
        "country_pvm_note": None,
        "price_volume_mix_ytd": {"revenue_last_year": eur(pvm.r0), "volume_effect": eur(pvm.volume), "mix_effect": eur(pvm.mix),
                                 "price_effect": eur(pvm.price), "revenue_this_year": eur(pvm.r1),
                                 "largest_price_erosion": {"product_line": worst_price.product_line,
                                                           "price_effect": eur(worst_price.price_effect),
                                                           "price_change": pct(worst_price.price_change)}},
        "at_risk_accounts": {
            "rule": "last 3 months at least 30% below the same 3 months last year, accounts with at least EUR 30 k last year",
            "count": int(len(risk)),
            "largest": [{"account_id": r.account_id, "country": r.country, "type": r.account_type,
                         "revenue_last_3_months": eur(r.rev_3m), "same_3_months_last_year": eur(r.rev_3m_ly),
                         "change": pct(r.rev_3m / r.rev_3m_ly - 1)} for _, r in risk.head(5).iterrows()]},
    }
    facts.pop("country_pvm_note")
    if iso3:                      # a country review has no region / country ranking sections
        for k in ["regions", "countries_below_target", "countries_above_target_largest"]:
            facts.pop(k)
    return facts


def offline_summary(f):
    """Deterministic template: used without an API key, and as the fallback when a generated text is rejected."""
    y, mo = f["year_to_date"], f["month"]
    lines = [f"**Headline** - {f['period']['month']}: revenue {mo['revenue']} ({mo['vs_target']} vs target); "
             f"year to date {y['revenue']}, {y['vs_target']} vs target ({y['gap_to_target']}).", "",
             "### Performance",
             f"- Month: {mo['revenue']} vs target {mo['target']} ({mo['vs_target']}); {mo['vs_last_year']} vs last year.",
             f"- Year to date: {y['revenue']} vs target {y['target']} ({y['vs_target']}); {y['vs_last_year']} vs last year."]
    lines += [f"- {r['region']}: {r['revenue_ytd']}, {r['vs_target']} vs target, {r['vs_last_year']} vs last year." for r in f.get("regions", [])]
    lines += ["", "### What drives the gap"]
    lines += [f"- {r['country']}: {r['gap_to_target']} vs target ({r['vs_target']})." for r in f.get("countries_below_target", {}).get("largest_gaps", [])]
    lines += [f"- {r['country']}: {r['gap_to_target']} above target ({r['vs_target']})." for r in f.get("countries_above_target_largest", [])]
    lines += [f"- {r['product_line']}: {r['gap_to_target']} vs target ({r['vs_target']})." for r in f["product_lines"][:2]]
    pv = f["price_volume_mix_ytd"]
    lines += [f"- Price-volume-mix vs last year: volume {pv['volume_effect']}, mix {pv['mix_effect']}, price {pv['price_effect']}; "
              f"largest price erosion on {pv['largest_price_erosion']['product_line']} ({pv['largest_price_erosion']['price_change']})."]
    lines += ["", "### Watch list"]
    if f["at_risk_accounts"]["largest"]:
        lines += [f"- {a['account_id']} ({a['country']}, {a['type']}): {a['revenue_last_3_months']} in the last 3 months "
                  f"vs {a['same_3_months_last_year']} a year earlier ({a['change']})." for a in f["at_risk_accounts"]["largest"]]
    else:
        lines += ["- No account meets the at-risk rule this month."]
    lines += ["", "### Suggested actions", "- Review the countries with the largest gaps with their country managers.",
              "- Call the accounts on the watch list before the next order cycle."]
    return "\n".join(lines)


def generate(month, offline=False, retry=True, iso3=None):
    facts = build_facts(month, iso3)
    result = {"month": month, "iso3": iso3, "mode": "offline", "attempts": 0, "unsupported_first": None,
              "unsupported_final": [], "numbers_cited": 0, "accepted": True, "usage": []}
    text = None
    if not offline and has_api_key():
        system = load_prompt("mbr_system.md")
        user = to_json(facts)
        result["mode"] = "llm"
        for attempt in range(2 if retry else 1):
            result["attempts"] += 1
            try:
                draft, usage = call_claude(system, user, effort="medium")
            except RuntimeError as e:          # refusal: keep the template
                result["error"] = str(e)
                break
            result["usage"].append(usage)
            cited, bad = check_numbers(draft, facts)
            if result["unsupported_first"] is None:
                result["unsupported_first"] = bad
            if not bad:
                text, result["numbers_cited"] = draft, len(cited)
                break
            # retry once, telling the model exactly which numbers are not in the facts
            user = (to_json(facts) + "\n\nYour previous draft cited numbers that are not in these facts: "
                    + ", ".join(bad) + ". Rewrite it using only numbers exactly as they appear above.")
            result["unsupported_final"] = bad
        if text is None:
            result["accepted"] = False
    if text is None:
        text = offline_summary(facts)
        cited, bad = check_numbers(text, facts)
        result["numbers_cited"], result["template_unsupported"] = len(cited), bad
        if result["mode"] == "llm":
            result["mode"] = "llm rejected -> template"
    else:
        result["unsupported_final"] = []
    result["text"], result["facts"] = text, facts
    return result


def write(result):
    OUT.mkdir(parents=True, exist_ok=True)
    stem = result["month"] + (f"_{result['iso3']}" if result.get("iso3") else "")
    scope = f"{result['facts']['scope']} - " if result.get("iso3") else ""
    header = (f"# Monthly Business Review - {scope}{result['facts']['period']['month']}\n\n"
              f"> SIMULATED data · independent case study, not affiliated with Cordis · generated by `ai/mbr_generator.py` "
              f"({'Claude ' + MODEL if result['mode'] == 'llm' else result['mode']}) from "
              f"[facts_{stem}.json](facts_{stem}.json) · number check: {result['numbers_cited']} numbers cited, "
              f"{len(result['unsupported_final'])} not found in the facts.\n\n")
    (OUT / f"MBR_{stem}.md").write_text(header + result["text"] + "\n", encoding="utf-8")
    (OUT / f"facts_{stem}.json").write_text(to_json(result["facts"]), encoding="utf-8")
    return OUT / f"MBR_{stem}.md"


def country_list():
    from common import connect_read_only as c
    con = c()
    try:
        return [r[0] for r in con.execute("SELECT iso3 FROM countries ORDER BY iso3").fetchall()]
    finally:
        con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", default="2026-10")
    ap.add_argument("--country", help="ISO3 code, e.g. FRA. Default: all countries together")
    ap.add_argument("--all-countries", action="store_true", help="the overall review + one review per country")
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()
    scopes = [None] + country_list() if a.all_countries else [a.country]
    log = []
    for iso3 in scopes:
        res = generate(a.month, offline=a.offline, iso3=iso3)
        path = write(res)
        log.append((iso3 or "ALL", res["mode"], res["numbers_cited"], len(res["unsupported_first"] or []),
                    len(res["unsupported_final"]), res["accepted"]))
        if len(scopes) == 1:
            print(res["text"])
        print(f"[{iso3 or 'ALL'} · mode {res['mode']} · {res['numbers_cited']} numbers cited · unsupported in first draft: "
              f"{res['unsupported_first']} · accepted: {res['accepted']}] -> {path.relative_to(ROOT)}")
    if len(scopes) > 1:
        import csv
        with open(OUT / f"run_{a.month}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["scope", "mode", "numbers_cited", "unsupported_first_draft", "unsupported_final", "accepted"])
            w.writerows(log)
