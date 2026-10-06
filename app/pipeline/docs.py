import pathlib

from app.pipeline import llm

DOCS_DIR = pathlib.Path(__file__).resolve().parents[2] / "data" / "docs"

_cache = None


def _load():
    global _cache
    if _cache is None:
        texts = [(path.stem, path.read_text()) for path in sorted(DOCS_DIR.glob("*.md"))]
        _cache = [(stem, text, llm.embed(text)) for stem, text in texts]
    return _cache


def search_docs(query: str) -> str:
    chunks = _load()
    if not chunks or not query.strip():
        return ""
    q_vec = llm.embed(query)
    best = max(chunks, key=lambda c: llm.cosine(c[2], q_vec))
    return best[1]
