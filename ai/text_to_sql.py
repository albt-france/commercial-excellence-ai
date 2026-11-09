"""Ask the sales data a question in plain English; the answer always shows the SQL it came from.

Usage:  python ai/text_to_sql.py "Which country missed target most in Q3?"
Steps:
  1. Claude writes one DuckDB query from the schema and business definitions (ai/prompts/text_to_sql_system.md),
     returned as structured JSON {sql, assumptions}.
  2. Guard: only a single SELECT / WITH query passes; the database is opened READ-ONLY with file and network
     access disabled, so even a query that slipped through could not change data or read files.
  3. The query runs; Claude phrases a one-sentence answer from the result rows, and the same number check as the
     MBR verifies that every number in that sentence is in the result. The SQL is printed with the answer.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import call_claude, check_numbers, connect_read_only, load_prompt  # noqa: E402

SQL_SCHEMA = {
    "type": "object",
    "properties": {"sql": {"type": "string"}, "assumptions": {"type": "string"}},
    "required": ["sql", "assumptions"],
    "additionalProperties": False,
}
FORBIDDEN = re.compile(r"\b(insert|update|delete|create|drop|alter|attach|detach|copy|pragma|install|load|export|import|"
                       r"call|set|vacuum|checkpoint|read_csv\w*|read_parquet|read_json\w*|glob)\b", re.I)


class UnsafeQuery(ValueError):
    pass


def guard(sql):
    """Accept one SELECT / WITH statement and nothing else."""
    s = sql.strip().rstrip(";").strip()
    s_no_strings = re.sub(r"'[^']*'", "''", s)              # ignore words inside string literals
    if ";" in s_no_strings:
        raise UnsafeQuery("more than one statement")
    if not re.match(r"^(with|select)\b", s_no_strings, re.I):
        raise UnsafeQuery("not a SELECT query")
    m = FORBIDDEN.search(re.sub(r"--[^\n]*", "", s_no_strings))
    if m:
        raise UnsafeQuery(f"forbidden keyword: {m.group(0)}")
    return s


def generate_sql(question):
    text, usage = call_claude(load_prompt("text_to_sql_system.md"), question, schema=SQL_SCHEMA, effort="medium")
    out = json.loads(text)
    return out["sql"], out["assumptions"], usage


def run_sql(sql, max_rows=200):
    con = connect_read_only()
    try:
        cur = con.execute(guard(sql))
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(max_rows)
    finally:
        con.close()
    return cols, rows


ANSWER_SYSTEM = """You answer a sales question in one or two sentences using only the query result given.
Write numbers exactly as they appear in the result, or as a percentage when the column is a fraction
(0.054 -> 5.4%), rounded to one decimal. Euro amounts: write them as given, with thousands separators allowed.
Do not mention SQL. If the result is empty, say that no data matches."""


def phrase_answer(question, cols, rows):
    result = [dict(zip(cols, r)) for r in rows[:20]]
    text, _ = call_claude(ANSWER_SYSTEM, json.dumps({"question": question, "result": result}, default=str), effort="low")
    # the number check allows a fraction shown as a percentage (0.054 -> 5.4) and rounding to 1 decimal or to units
    facts = []
    for r in result:
        for v in r.values():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                facts += [v, round(v, 1), round(v), round(v * 100, 1), round(v, 2), round(v * 100), round(v / 1e6, 1),
                          round(v / 1e6, 2), round(v / 1e3), round(v / 1e3, 1)]
            else:
                facts.append(str(v))
    _, bad = check_numbers(text, facts + [question])
    return text, bad


def ask(question, phrase=True):
    sql, assumptions, _ = generate_sql(question)
    cols, rows = run_sql(sql)
    answer, bad = phrase_answer(question, cols, rows) if phrase else (None, [])
    return {"question": question, "sql": sql, "assumptions": assumptions, "columns": cols, "rows": rows,
            "answer": answer, "unsupported_numbers": bad}


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "Which country missed target most in Q3?"
    r = ask(q)
    print(f"Q: {r['question']}\n")
    print(f"A: {r['answer']}" + (f"   [!] numbers not found in the result: {r['unsupported_numbers']}" if r["unsupported_numbers"] else ""))
    print("\nResult:")
    print("  " + " | ".join(r["columns"]))
    for row in r["rows"][:10]:
        print("  " + " | ".join(f"{v:,.4f}" if isinstance(v, float) else str(v) for v in row))
    print(f"\nSQL used:\n{r['sql']}\n\nAssumptions: {r['assumptions']}")
