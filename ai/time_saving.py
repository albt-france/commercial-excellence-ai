"""Conservative estimate of the analyst time saved each month. Every hypothesis is written next to its number.

Usage:  python ai/time_saving.py      (after ai/run_eval.py: the text-to-SQL accuracy comes from ai/eval_summary.csv)
Output: data/output/ai_time_saving.csv
Principle: a human still reviews every generated output, so review time is counted on the automated side, and
questions the AI gets wrong are counted as fully manual.
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
s = pd.read_csv(ROOT / "ai" / "eval_summary.csv").set_index("metric")["value"]
acc = float(s["sql_accuracy"])
countries = 19

QUESTIONS, MANUAL_MIN, CHECK_MIN = 40, 30, 5
rows = [
    ("Monthly business reviews (overall + 19 countries)",
     countries * 1.5 + 3, countries * 0.25 + 0.75,
     f"Manual: 1.5 h per country pack (extract, reconcile, bridge, comment) + 3 h for the overall review. "
     f"Automated: one command, then 15 min human review per country and 45 min for the overall review."),
    ("Ad-hoc sales questions",
     QUESTIONS * MANUAL_MIN / 60, QUESTIONS * CHECK_MIN / 60 + QUESTIONS * (1 - acc) * MANUAL_MIN / 60,
     f"{QUESTIONS} questions a month at {MANUAL_MIN} min each by hand. Automated: {CHECK_MIN} min to check the SQL shown with "
     f"each answer; the {1 - acc:.0%} the AI gets wrong in the test set are redone by hand."),
    ("Account risk watch list",
     4.0, 0.5,
     "Manual: 4 h a month to rebuild 3-month trends per hospital in Excel. Automated: SQL alert, 30 min to review the list."),
]
df = pd.DataFrame(rows, columns=["task", "manual_hours", "automated_hours", "assumption"])
df["hours_saved"] = df.manual_hours - df.automated_hours
df.insert(0, "order", range(1, len(df) + 1))
tot = pd.DataFrame([{"order": len(df) + 1, "task": "Total per month", "manual_hours": df.manual_hours.sum(),
                     "automated_hours": df.automated_hours.sum(), "hours_saved": df.hours_saved.sum(),
                     "assumption": "Excludes the one-off build (about 2 weeks) and the API cost (a few euros a month at this volume)."}])
df = pd.concat([df, tot], ignore_index=True).round(1)
df.to_csv(ROOT / "data" / "output" / "ai_time_saving.csv", index=False)
print(df[["task", "manual_hours", "automated_hours", "hours_saved"]].to_string(index=False))
