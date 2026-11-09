"""Measure how reliable the AI layer is. Spends API credit (about 110 Claude calls, a few euros).

Usage:  python ai/run_eval.py              (all parts)
        python ai/run_eval.py --part sql   (or mbr, guards)
A. Text-to-SQL: 30 core questions asked 3 times each + 10 harder "stress" questions (ai/eval_questions.csv).
   A generated query is CORRECT when its result holds the same rows and values as the hand-written gold query
   (numbers within 0.1%; a fraction may come back x100; extra columns allowed; out-of-scope must say 'cannot answer').
B. MBR grounding: one review per month, January-October 2026. Counts the numbers cited and those not found in the facts.
C. Guards: the checks must catch a tampered number and block writes / file access.
Outputs: ai/eval_results.csv, ai/eval_mbr.csv, ai/eval_guards.csv, ai/eval_summary.csv (copied to data/output/).
"""
import argparse
import datetime as dt
import math
import shutil
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, check_numbers, connect_read_only  # noqa: E402
import mbr_generator  # noqa: E402
import text_to_sql  # noqa: E402

AI = ROOT / "ai"
OUT = ROOT / "data" / "output"


# ---------------------------------------------------------------- result comparison
def _norm(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, (dt.date, dt.datetime, pd.Timestamp)):
        return pd.Timestamp(v).strftime("%Y-%m-%d")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return str(v).strip().lower()


def _num_eq(a, b):
    for x in (b, b / 100, b * 100):
        if math.isclose(a, x, rel_tol=1e-3, abs_tol=1e-6):
            return True
    return False


def _row_matches(gold_row, pred_row):
    """Every gold value must appear somewhere in the predicted row (extra columns are allowed)."""
    pred = [_norm(v) for v in pred_row]
    for g in (_norm(v) for v in gold_row):
        if isinstance(g, float):
            if not any(isinstance(p, float) and _num_eq(g, p) for p in pred):
                return False
        elif g not in pred:
            return False
    return True


def results_match(gold_rows, pred_rows):
    if gold_rows and _norm(gold_rows[0][0]) == "cannot answer":        # out-of-scope question
        # strict: an empty or NULL result is NOT accepted - the user must be told the data does not cover it
        return "cannot answer" in [_norm(v) for r in pred_rows for v in r]
    if len(gold_rows) != len(pred_rows):
        return False
    remaining = list(pred_rows)
    for g in gold_rows:
        hit = next((p for p in remaining if _row_matches(g, p)), None)
        if hit is None:
            return False
        remaining.remove(hit)
    return True


def compact(rows, cols):
    def f(v):
        return f"{v:,.4f}" if isinstance(v, float) else str(v)
    return "; ".join(", ".join(f"{c}={f(v)}" for c, v in zip(cols, r)) for r in rows[:5])


# ---------------------------------------------------------------- A. text-to-SQL
def eval_sql(repeats=3):
    """Core questions are asked `repeats` times (the model is not deterministic); stress questions once each."""
    qs = pd.read_csv(AI / "eval_questions.csv")
    rows = []
    jobs = [(run, q) for run in range(1, repeats + 1) for _, q in qs[qs.set == "core"].iterrows()]
    jobs += [(1, q) for _, q in qs[qs.set == "stress"].iterrows()]
    for run, q in jobs:
        gcols, grows = text_to_sql.run_sql(q.gold_sql)
        rec = {"run": run, "id": q.id, "set": q.set, "category": q.category, "question": q.question,
               "gold_answer": compact(grows, gcols), "gold_sql": q.gold_sql}
        t0 = time.time()
        try:
            sql, assumptions, usage = text_to_sql.generate_sql(q.question)
            rec.update(generated_sql=sql, assumptions=assumptions, input_tokens=usage["input_tokens"],
                       output_tokens=usage["output_tokens"])
            pcols, prows = text_to_sql.run_sql(sql)
            rec["generated_answer"] = compact(prows, pcols)
            rec["correct"] = results_match(grows, prows)
            rec["error_type"] = "" if rec["correct"] else (
                "no 'cannot answer' for out-of-scope question" if grows[0][0] == "cannot answer"
                else "different row count" if len(grows) != len(prows) else "different values")
        except text_to_sql.UnsafeQuery as e:
            rec.update(correct=False, error_type=f"blocked by guard: {e}")
        except Exception as e:                                          # SQL error
            rec.update(correct=False, error_type=f"SQL error: {type(e).__name__}: {str(e)[:120]}")
        rec["seconds"] = round(time.time() - t0, 1)
        rows.append(rec)
        print(f"run {run} {q.id:>2} {'OK ' if rec['correct'] else 'BAD'} {q.question[:70]}  {rec.get('error_type', '')}", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(AI / "eval_results.csv", index=False)
    return df


# ---------------------------------------------------------------- B. MBR grounding
def eval_mbr():
    rows = []
    for m in range(1, 11):
        month = f"2026-{m:02d}"
        r = mbr_generator.generate(month)
        mbr_generator.write(r)
        rows.append({"month": month, "mode": r["mode"], "numbers_cited": r["numbers_cited"],
                     "unsupported_first_draft": len(r["unsupported_first"] or []),
                     "unsupported_first_draft_values": " ".join(r["unsupported_first"] or []),
                     "attempts": r["attempts"], "unsupported_final": len(r["unsupported_final"]), "accepted": r["accepted"],
                     "words": len(r["text"].split())})
        print(rows[-1])
    df = pd.DataFrame(rows)
    df.to_csv(AI / "eval_mbr.csv", index=False)
    return df


# ---------------------------------------------------------------- C. guards
def eval_guards():
    tests = []
    facts = mbr_generator.build_facts("2026-10")
    good = mbr_generator.offline_summary(facts)
    tampered = good.replace(facts["year_to_date"]["revenue"].split()[1], "96.35", 1)     # one wrong figure
    tests.append(("Number check accepts the template built from the facts", not check_numbers(good, facts)[1]))
    tests.append(("Number check rejects a summary with one altered figure", bool(check_numbers(tampered, facts)[1])))
    invented = good + "\n- Market share reached 12.3% in Germany."
    tests.append(("Number check rejects an invented statistic", bool(check_numbers(invented, facts)[1])))
    for bad_sql in ["DROP TABLE sales", "SELECT 1; DELETE FROM sales", "SELECT * FROM read_csv_auto('data/clean/sales.csv')",
                    "COPY sales TO 'leak.csv'", "ATTACH 'other.duckdb'", "UPDATE targets SET target_eur = 0"]:
        try:
            text_to_sql.guard(bad_sql)
            blocked = False
        except text_to_sql.UnsafeQuery:
            blocked = True
        tests.append((f"SQL guard blocks: {bad_sql}", blocked))
    con = connect_read_only()            # second line of defence: even without the guard, the connection refuses
    for bad_sql in ["CREATE TABLE x AS SELECT 1", "SELECT * FROM read_csv_auto('data/clean/sales.csv')"]:
        try:
            con.execute(bad_sql)
            refused = False
        except Exception:
            refused = True
        tests.append((f"Read-only connection refuses: {bad_sql}", refused))
    con.close()
    df = pd.DataFrame(tests, columns=["test", "passed"])
    df.to_csv(AI / "eval_guards.csv", index=False)
    print(df.to_string(index=False))
    return df


def summary():
    rows = []
    if (AI / "eval_results.csv").exists():
        r = pd.read_csv(AI / "eval_results.csv")
        core, stress = r[r.set == "core"], r[r.set == "stress"]
        first = core[core.run == 1]
        stable = core.groupby("id").correct.agg(["all", "any"])
        rows += [("sql_questions", len(first)), ("sql_correct", int(first.correct.sum())), ("sql_accuracy", first.correct.mean()),
                 ("sql_runs", int(core.run.max())), ("sql_trials", len(core)), ("sql_trials_correct", int(core.correct.sum())),
                 ("sql_trial_accuracy", core.correct.mean()),
                 ("sql_questions_always_right", int(stable["all"].sum())), ("sql_questions_never_right", int((~stable["any"]).sum())),
                 ("stress_questions", len(stress)), ("stress_correct", int(stress.correct.sum())),
                 ("sql_errors", int(r.error_type.fillna("").str.startswith("SQL error").sum())),
                 ("sql_blocked", int(r.error_type.fillna("").str.startswith("blocked").sum())),
                 ("sql_avg_seconds", r.seconds.mean())]
        for cat, g in first.groupby("category"):
            rows.append((f"sql_correct_{cat.replace(' ', '_')}", f"{int(g.correct.sum())}/{len(g)}"))
    if (AI / "eval_mbr.csv").exists():
        m = pd.read_csv(AI / "eval_mbr.csv")
        rows += [("mbr_reviews", len(m)), ("mbr_numbers_cited", int(m.numbers_cited.sum())),
                 ("mbr_unsupported_first_draft", int(m.unsupported_first_draft.sum())),
                 ("mbr_retried", int((m.attempts > 1).sum())), ("mbr_unsupported_final", int(m.unsupported_final.sum())),
                 ("mbr_accepted", int(m.accepted.sum()))]
    if (AI / "eval_guards.csv").exists():
        gd = pd.read_csv(AI / "eval_guards.csv")
        rows += [("guard_tests", len(gd)), ("guard_passed", int(gd.passed.sum()))]
    s = pd.DataFrame(rows, columns=["metric", "value"])
    s.to_csv(AI / "eval_summary.csv", index=False)
    for f in ["eval_mbr.csv", "eval_guards.csv", "eval_summary.csv"]:
        if (AI / f).exists():
            shutil.copy(AI / f, OUT / f"ai_{f}")
    if (AI / "eval_results.csv").exists():
        # the error analysis is written by a person after reading each failure (ai/eval_error_analysis.csv)
        r = pd.read_csv(AI / "eval_results.csv")
        notes = AI / "eval_error_analysis.csv"
        r["analysis"] = r.id.map(pd.read_csv(notes).set_index("id")["analysis"]) if notes.exists() else ""
        r = r[r.run == 1]                       # one row per question in the report; all runs stay in ai/eval_results.csv
        r.to_csv(OUT / "ai_eval_results.csv", index=False)
    print(s.to_string(index=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", choices=["sql", "mbr", "guards", "summary"])
    ap.add_argument("--repeats", type=int, default=3)
    a = ap.parse_args()
    if a.part in (None, "guards"):
        eval_guards()
    if a.part in (None, "sql"):
        eval_sql(a.repeats)
    if a.part in (None, "mbr"):
        eval_mbr()
    summary()
