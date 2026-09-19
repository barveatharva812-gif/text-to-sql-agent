"""
Text-to-SQL Agent
------------------
A chat-style Streamlit app where users ask questions in plain English.
The agent converts them to SQL, validates the query, runs it, retries on
failure, and explains the result -- while remembering earlier questions
so follow-ups like "and for Pune?" work.

Run: streamlit run app.py
"""

import os
import re
import sqlite3
import streamlit as st
from groq import Groq

DB_PATH = "ecommerce.db"
MODEL = "openai/gpt-oss-120b"
MAX_RETRIES = 3
HISTORY_TURNS = 3  # how many previous Q&A pairs to include as context

# ---------- Setup ----------
st.set_page_config(page_title="Text-to-SQL Agent", page_icon="🗄️")
st.title("🗄️ Text-to-SQL Agent")
st.caption("Ask questions about the sample e-commerce database. Follow-up questions work too.")

api_key = st.sidebar.text_input("Groq API Key", type="password")
st.sidebar.caption("Free key: console.groq.com/keys")
if not api_key:
    st.sidebar.warning("Paste your Groq API key to get started.")
    st.stop()

client = Groq(api_key=api_key)

# Chat history lives in session_state so it survives across reruns
# (Streamlit reruns the whole script on every interaction).
if "history" not in st.session_state:
    st.session_state.history = []  # list of {"question", "sql", "answer"}

if st.sidebar.button("🗑️ Clear conversation"):
    st.session_state.history = []
    st.rerun()


# ---------- Helpers ----------
def get_schema() -> str:
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


def validate_query(sql: str):
    """
    Checks whether SQLite considers this query valid WITHOUT actually
    running it. SQLite's query planner raises the same 'no such
    column/table' errors here as it would on execution, so this catches
    mistakes cheaply before we touch real data.
    Returns (is_valid, error_message_or_None).
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute(f"EXPLAIN QUERY PLAN {sql}")
        return True, None
    except sqlite3.Error as e:
        return False, str(e)
    finally:
        conn.close()


FEW_SHOT_EXAMPLES = """
Example 1:
Q: How many orders are pending?
A: SELECT COUNT(*) FROM orders WHERE status = 'pending';

Example 2:
Q: Which customers have never placed an order?
A: SELECT c.name FROM customers c LEFT JOIN orders o ON c.customer_id = o.customer_id WHERE o.order_id IS NULL;

Example 3:
Q: Total revenue per product category
A: SELECT p.category, SUM(p.price * oi.quantity) AS revenue
   FROM order_items oi
   JOIN products p ON oi.product_id = p.product_id
   GROUP BY p.category;
"""


def build_history_context() -> str:
    """Turns the last few Q&A pairs into text the model can use for follow-ups."""
    recent = st.session_state.history[-HISTORY_TURNS:]
    if not recent:
        return ""
    lines = ["Conversation so far (for resolving follow-up questions like 'and for Pune?'):"]
    for turn in recent:
        lines.append(f"Q: {turn['question']}")
        lines.append(f"SQL used: {turn['sql']}")
    return "\n".join(lines)


def generate_sql(question: str, schema: str, feedback: str = None) -> str:
    """
    Generates SQL for a question. If `feedback` is given (an error from a
    previous attempt), the model is asked to fix that specific problem.
    """
    system_prompt = f"""You are a SQL expert. Given a database schema, a
conversation history, and a question in plain English, write a single
SQLite SELECT query that answers it.

Schema:
{schema}

{FEW_SHOT_EXAMPLES}

{build_history_context()}

Rules:
- Only output the raw SQL query, nothing else. No markdown, no explanation.
- Only generate SELECT statements. Never write/modify data.
- Use proper JOINs when the question needs data from multiple tables.
- If the question is a follow-up (e.g. "and for Pune?", "what about last month?"),
  use the conversation history to understand what it refers to.
"""
    user_content = question
    if feedback:
        user_content = f"{question}\n\n(Your previous attempt failed: {feedback}. Fix it.)"

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


def run_query(sql: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(sql)
    columns = [desc[0] for desc in cur.description]
    rows = cur.fetchall()
    conn.close()
    return columns, rows


def generate_sql_with_retry(question: str, schema: str):
    """
    Generates SQL, validates it (without running), and if invalid or the
    real execution fails, feeds the error back to the model and retries.
    Returns (final_sql, columns, rows, attempt_log).
    """
    attempt_log = []
    feedback = None

    for attempt in range(1, MAX_RETRIES + 1):
        sql = generate_sql(question, schema, feedback)
        attempt_log.append({"attempt": attempt, "sql": sql, "stage": None, "error": None})

        if not is_safe_query(sql):
            attempt_log[-1]["stage"] = "safety check"
            attempt_log[-1]["error"] = "Not a read-only SELECT query."
            raise ValueError("Generated query failed the safety check.")

        # Validate BEFORE running -- catches typos/bad columns cheaply.
        valid, val_error = validate_query(sql)
        if not valid:
            attempt_log[-1]["stage"] = "validation"
            attempt_log[-1]["error"] = val_error
            if attempt == MAX_RETRIES:
                raise sqlite3.Error(val_error)
            feedback = val_error
            continue

        try:
            columns, rows = run_query(sql)
            attempt_log[-1]["stage"] = "success"
            return sql, columns, rows, attempt_log
        except sqlite3.Error as e:
            attempt_log[-1]["stage"] = "execution"
            attempt_log[-1]["error"] = str(e)
            if attempt == MAX_RETRIES:
                raise
            feedback = str(e)

    raise RuntimeError("Retry loop exited unexpectedly.")


def explain_result(question: str, columns, rows) -> str:
    preview = str(rows[:20])
    prompt = f"""Question: {question}
Columns: {columns}
Result rows: {preview}

Explain this result in 1-3 plain-English sentences. Be concise and direct."""
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content.strip()


# ---------- UI ----------
if not os.path.exists(DB_PATH):
    # On Streamlit Cloud the .db file isn't in git (it's generated data),
    # so build it automatically on first run instead of erroring out.
    import subprocess
    subprocess.run(["python", "setup_database.py"], check=True)

with st.expander("📋 View database schema"):
    st.code(get_schema(), language="sql")

# Replay the conversation so far as chat bubbles
for turn in st.session_state.history:
    with st.chat_message("user"):
        st.write(turn["question"])
    with st.chat_message("assistant"):
        st.code(turn["sql"], language="sql")
        st.write(turn["answer"])

question = st.chat_input("Ask a question, or a follow-up like 'and for Pune?'")

if question:
    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        schema = get_schema()
        try:
            with st.spinner("Generating SQL (validating + auto-retry on errors)..."):
                sql, columns, rows, attempt_log = generate_sql_with_retry(question, schema)

            if len(attempt_log) > 1:
                with st.expander(f"🔁 Needed {len(attempt_log)} attempts (click to see why)"):
                    for a in attempt_log:
                        st.markdown(f"**Attempt {a['attempt']}** — stage: `{a['stage']}`")
                        st.code(a["sql"], language="sql")
                        if a["error"]:
                            st.error(f"Error: {a['error']}")
                        else:
                            st.success("✅ This one worked.")

            st.code(sql, language="sql")

            if rows:
                st.dataframe([dict(zip(columns, row)) for row in rows])
                with st.spinner("Explaining result..."):
                    answer = explain_result(question, columns, rows)
                st.write(answer)
            else:
                answer = "Query ran successfully but returned no rows."
                st.info(answer)

            # Save this turn so future questions can refer back to it.
            st.session_state.history.append({"question": question, "sql": sql, "answer": answer})

        except sqlite3.Error as e:
            st.error(f"SQL error after {MAX_RETRIES} attempts: {e}")
        except ValueError as e:
            st.error(f"⚠️ {e}")

st.divider()
st.caption("Try: 'top 5 customers by total spend' → then follow up with 'and only from Mumbai?'")
