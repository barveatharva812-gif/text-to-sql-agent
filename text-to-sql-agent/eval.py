"""
Evaluation harness for the Text-to-SQL agent.
Run: python eval.py
Requires GROQ_API_KEY as an environment variable.
"""

import os
import time
import sqlite3
import re
from groq import Groq

DB_PATH = "ecommerce.db"
MODEL = "openai/gpt-oss-120b"
MAX_RETRIES = 3

TEST_QUESTIONS = [
    "Which city has the most customers?",
    "Top 5 customers by total spend",
    "Which product category sells best?",
    "How many orders were cancelled?",
    "Average order value by city",
    "Which customers have never placed an order?",
    "What is the most popular product by quantity sold?",
    "How many products are in each category?",
    "Show total revenue for completed orders only",
    "Which customer signed up most recently?",
    "What percentage of orders are pending?",
    "List all products priced over 1000",
    "How many distinct customers ordered the Yoga Mat?",
    "What is the average number of items per order?",
    "Which city generates the highest total revenue?",
    "How many orders has each customer placed, ranked highest first?",
    "What is the cheapest product in each category?",
    "How many orders were placed in the last 6 months of the dataset?",
    "Which product has never been ordered?",
    "What is the total quantity sold per product?",
]


def get_client():
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise SystemExit("Set GROQ_API_KEY as an environment variable first.")
    return Groq(api_key=api_key)


def get_schema():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT sql FROM sqlite_master WHERE type='table'")
    schema = "\n".join(row[0] for row in cur.fetchall() if row[0])
    conn.close()
    return schema


def is_safe_query(sql):
    forbidden = r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|ATTACH|REPLACE)\b"
    return sql.strip().upper().startswith("SELECT") and not re.search(forbidden, sql, re.IGNORECASE)


def generate_sql(client, question, schema, feedback=None):
    system_prompt = f"""You are a SQL expert. Given a database schema and a
question in plain English, write a single SQLite SELECT query that answers it.

Schema:
{schema}

Rules:
- Only output the raw SQL query, nothing else. No markdown, no explanation.
- Only generate SELECT statements.
- Use proper JOINs when needed.
"""
    user_content = question
    if feedback:
        user_content = f"{question}\n\n(Previous attempt failed: {feedback}. Fix it.)"

    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=500,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    )
    sql = response.choices[0].message.content.strip()
    sql = re.sub(r"^```sql|```$", "", sql, flags=re.MULTILINE).strip()
    return sql


def run_question(client, question, schema):
    start = time.time()
    feedback = None
    attempts = 0

    for attempt in range(1, MAX_RETRIES + 1):
        attempts = attempt
        sql = generate_sql(client, question, schema, feedback)

        if not is_safe_query(sql):
            return {"success": False, "attempts": attempts, "error": "failed safety check",
                    "sql": sql, "latency": time.time() - start}

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        try:
            cur.execute(sql)
            cur.fetchall()
            conn.close()
            return {"success": True, "attempts": attempts, "error": None,
                    "sql": sql, "latency": time.time() - start}
        except sqlite3.Error as e:
            conn.close()
            feedback = str(e)
            if attempt == MAX_RETRIES:
                return {"success": False, "attempts": attempts, "error": str(e),
                        "sql": sql, "latency": time.time() - start}

    return {"success": False, "attempts": attempts, "error": "unknown", "sql": "", "latency": time.time() - start}


def main():
    client = get_client()
    schema = get_schema()

    if not os.path.exists(DB_PATH):
        raise SystemExit("ecommerce.db not found. Run `python setup_database.py` first.")

    results = []
    print(f"Running {len(TEST_QUESTIONS)} test questions against {MODEL}...\n")

    for i, q in enumerate(TEST_QUESTIONS, 1):
        result = run_question(client, q, schema)
        results.append(result)
        status = "PASS" if result["success"] else "FAIL"
        retry_note = f" (took {result['attempts']} attempts)" if result["attempts"] > 1 else ""
        print(f"[{i:2d}/{len(TEST_QUESTIONS)}] {status}{retry_note} - {q}")
        if not result["success"]:
            print(f"          error: {result['error']}")

    passed = sum(r["success"] for r in results)
    total = len(results)
    first_try = sum(1 for r in results if r["success"] and r["attempts"] == 1)
    avg_latency = sum(r["latency"] for r in results) / total
    needed_retry = sum(1 for r in results if r["attempts"] > 1)

    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    print(f"Accuracy: {passed}/{total} ({passed/total*100:.1f}%)")
    print(f"First-try success: {first_try}/{total} ({first_try/total*100:.1f}%)")
    print(f"Questions that needed a retry: {needed_retry}/{total}")
    print(f"Average latency per question: {avg_latency:.2f}s")


if __name__ == "__main__":
    main()
