"""
Text-to-SQL Agent
------------------
A Streamlit app where users ask questions in plain English and the
agent converts them to SQL, runs the query against a SQLite database,
and explains the result back in natural language.

Run: streamlit run app.py
"""

import os
import re
import sqlite3
import streamlit as st
from anthropic import Anthropic

DB_PATH = "ecommerce.db"

# ---------- Setup ----------
st.set_page_config(page_title="Text-to-SQL Agent", page_icon="🗄️")
st.title("🗄️ Text-to-SQL Agent")
st.caption("Ask questions about the sample e-commerce database in plain English.")

api_key = st.sidebar.text_input("Anthropic API Key", type="password")
if not api_key:
    st.sidebar.warning("Paste your Anthropic API key to get started.")
    st.stop()

client = Anthropic(api_key=api_key)


# ---------- Helpers ----------
def get_schema() -> str:
    """Reads the DB schema so the model knows what tables/columns exist."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT sql FROM sqlite_master WHERE type='table'")
    schema = "\n".join(row[0] for row in cur.fetchall() if row[0])
    conn.close()
    return schema


def is_safe_query(sql: str) -> bool:
    """Only allow read-only SELECT queries. Blocks writes/deletes as a guardrail."""
    forbidden = r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|ATTACH|REPLACE)\b"
    return sql.strip().upper().startswith("SELECT") and not re.search(forbidden, sql, re.IGNORECASE)


def generate_sql(question: str, schema: str) -> str:
    system_prompt = f"""You are a SQL expert. Given a database schema and a
question in plain English, write a single SQLite SELECT query that answers it.

Schema:
{schema}

Rules:
- Only output the raw SQL query, nothing else. No markdown, no explanation.
- Only generate SELECT statements. Never write/modify data.
- Use proper JOINs when the question needs data from multiple tables.
"""
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system=system_prompt,
        messages=[{"role": "user", "content": question}],
    )
    sql = response.content[0].text.strip()
    sql = re.sub(r"^```sql|```$", "", sql, flags=re.MULTILINE).strip()
    return sql


def run_query(sql: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(sql)
    columns = [desc[0] for desc in cur.description]
    rows = cur.fetchall()
    conn.close()
    return columns, rows


# ---------- Retry logic (the new part) ----------
# Idea: if the SQL the model wrote fails to run, don't give up immediately.
# Show the model the exact error, ask it to fix the query, and try again.
# We cap it at MAX_RETRIES attempts so we never loop forever / burn API credits.
MAX_RETRIES = 3


def fix_sql(question: str, schema: str, bad_sql: str, error_message: str) -> str:
    """Asks the model to correct a SQL query given the error it produced."""
    system_prompt = f"""You are a SQL expert. A SQL query you wrote failed to run.
Look at the error and the schema, then write a corrected SQLite SELECT query.

Schema:
{schema}

Rules:
- Only output the raw corrected SQL query, nothing else. No markdown, no explanation.
- Only generate SELECT statements.
"""
    user_message = f"""Original question: {question}

Query that failed:
{bad_sql}

Error message:
{error_message}

Write a corrected query."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    sql = response.content[0].text.strip()
    sql = re.sub(r"^```sql|```$", "", sql, flags=re.MULTILINE).strip()
    return sql


def generate_sql_with_retry(question: str, schema: str):
    """
    Tries to generate + run a working SQL query.
    Returns (final_sql, columns, rows, attempt_log).
    attempt_log is a list of dicts we use to show the user what happened
    at each attempt -- this is great for learning/debugging.
    """
    attempt_log = []
    sql = generate_sql(question, schema)

    for attempt in range(1, MAX_RETRIES + 1):
        attempt_log.append({"attempt": attempt, "sql": sql, "error": None})

        # Safety check happens on every attempt, not just the first one.
        if not is_safe_query(sql):
            attempt_log[-1]["error"] = "Blocked: not a read-only SELECT query."
            raise ValueError("Generated query failed the safety check.")

        try:
            columns, rows = run_query(sql)
            return sql, columns, rows, attempt_log  # success! stop retrying
        except sqlite3.Error as e:
            attempt_log[-1]["error"] = str(e)
            if attempt == MAX_RETRIES:
                # We've used up all our tries -- give up and let the caller
                # show the error to the user instead of retrying forever.
                raise
            # Ask the model to fix its own mistake before trying again.
            sql = fix_sql(question, schema, sql, str(e))

    # Should never reach here, but keeps type-checkers happy.
    raise RuntimeError("Retry loop exited unexpectedly.")


def explain_result(question: str, columns, rows) -> str:
    preview = str(rows[:20])  # cap what we send back to the model
    prompt = f"""Question: {question}
Columns: {columns}
Result rows: {preview}

Explain this result in 1-3 plain-English sentences. Be concise and direct."""
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


# ---------- UI ----------
if not os.path.exists(DB_PATH):
    st.error(f"Database not found. Run `python setup_database.py` first.")
    st.stop()

with st.expander("📋 View database schema"):
    st.code(get_schema(), language="sql")

question = st.text_input(
    "Ask a question",
    placeholder="e.g. Which city has the most customers?",
)

if st.button("Ask") and question:
    schema = get_schema()

    try:
        with st.spinner("Generating SQL (with auto-retry on errors)..."):
            sql, columns, rows, attempt_log = generate_sql_with_retry(question, schema)

        # Show every attempt the agent made -- this is the part that teaches
        # you what "retry logic" actually looks like under the hood.
        if len(attempt_log) > 1:
            with st.expander(f"🔁 Agent needed {len(attempt_log)} attempts (click to see why)"):
                for a in attempt_log:
                    st.markdown(f"**Attempt {a['attempt']}**")
                    st.code(a["sql"], language="sql")
                    if a["error"]:
                        st.error(f"Error: {a['error']}")
                    else:
                        st.success("✅ This one worked.")

        st.subheader("Final SQL")
        st.code(sql, language="sql")

        st.subheader("Result")
        if rows:
            st.dataframe([dict(zip(columns, row)) for row in rows])
            with st.spinner("Explaining result..."):
                explanation = explain_result(question, columns, rows)
            st.subheader("Answer")
            st.write(explanation)
        else:
            st.info("Query ran successfully but returned no rows.")

    except sqlite3.Error as e:
        st.error(f"SQL execution error after {MAX_RETRIES} attempts: {e}")
    except ValueError as e:
        st.error(f"⚠️ {e}")

st.divider()
st.caption("Try: 'top 5 customers by total spend', 'which category sells best in Pune', "
           "'how many orders were cancelled', 'average order value by city'")
