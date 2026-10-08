import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.pipeline.run import run_pipeline

QUERIES = [
    "What is the vacation policy?",
    "How do I submit an expense report?",
    "What is 12 + 30?",
    "Can I work remotely full time?",
    "Who do I contact for IT support?",
    "What are the password requirements?",
    "How many vacation days do new hires get?",
    "What is 100 / 4?",
    "How do I onboard a new laptop?",
    "What is the expense limit for client dinners?",
]

FAULT_QUERIES = [
    "",                 # triggers the degenerate-output check
    "What is 10 / 0?",  # triggers the tool-exception check
]


def main():
    random.seed(0)
    n = int(sys.argv[1]) if len(sys.argv) > 1 else len(QUERIES)  # e.g. 40 to get 30+ runs to label
    for q in (QUERIES * (n // len(QUERIES) + 1))[:n]:
        if random.random() < 0.2:
            q = random.choice(FAULT_QUERIES)
        result = run_pipeline(q)
        print(result["trace_id"], "FAILED" if result["failed"] else "ok", result["reason"] or "")


if __name__ == "__main__":
    main()
