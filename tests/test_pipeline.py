import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.pipeline.docs import search_docs
from app.pipeline.run import run_pipeline


def test_retrieval_picks_matching_doc():
    assert "Vacation" in search_docs("What is the vacation policy?")
    assert "Expense" in search_docs("How do I submit an expense report?")


def test_degenerate_output_flagged_as_failed():
    result = run_pipeline("")
    assert result["failed"] is True
    assert result["reason"] == "empty or degenerate output"


def test_tool_exception_flagged_as_failed():
    result = run_pipeline("What is 10 / 0?")
    assert result["failed"] is True
    assert "exception" in result["reason"]


def test_normal_query_succeeds():
    result = run_pipeline("What is the vacation policy?")
    assert result["output"]
    assert result["failed"] is False


if __name__ == "__main__":
    test_retrieval_picks_matching_doc()
    test_degenerate_output_flagged_as_failed()
    test_tool_exception_flagged_as_failed()
    test_normal_query_succeeds()
    print("all pipeline smoke tests passed")
