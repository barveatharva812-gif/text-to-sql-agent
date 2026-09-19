# Text-to-SQL Agent

Ask questions in plain English. The agent converts them to SQL, runs them against
a sample e-commerce SQLite database, and explains the result back in natural language.

## Features
- Natural language → SQL using Claude
- Read-only guardrail (blocks INSERT/UPDATE/DELETE/DROP etc.)
- Schema-aware query generation (handles JOINs across tables)
- Plain-English explanation of results
- Simple Streamlit UI

## Setup

```bash
pip install -r requirements.txt
python setup_database.py   # creates ecommerce.db with sample data
streamlit run app.py
```

Paste your Anthropic API key in the sidebar (get one at console.anthropic.com).

## Database schema
- **customers**: customer_id, name, city, signup_date
- **products**: product_id, name, category, price
- **orders**: order_id, customer_id, order_date, status
- **order_items**: order_item_id, order_id, product_id, quantity

## Example questions to try
- "Which city has the most customers?"
- "Top 5 customers by total spend"
- "Which product category sells best in Pune?"
- "How many orders were cancelled?"
- "Average order value by city"
- "Show me all pending orders from June 2024"

## Next steps (to level up the project)
- [ ] Add conversational memory for follow-up questions
- [ ] Add few-shot examples to improve accuracy on ambiguous questions
- [ ] Add a query cache to avoid re-generating SQL for repeated questions
- [ ] Deploy on Streamlit Community Cloud
- [ ] Write an eval script: 20 test questions + expected results, measure accuracy
- [ ] Swap in a bigger/messier public dataset (e.g. Chinook, Northwind)

## Tech stack
Python, SQLite, Anthropic API (Claude), Streamlit
