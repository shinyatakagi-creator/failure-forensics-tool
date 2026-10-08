import pathlib

from app.pipeline import llm

DOCS_DIR = pathlib.Path(__file__).resolve().parents[2] / "data" / "docs"

_cache: dict = {}


def _load(docs_dir):
    if docs_dir not in _cache:
        texts = [(path.stem, path.read_text()) for path in sorted(docs_dir.glob("*.md"))]
        _cache[docs_dir] = [(stem, text, llm.embed(text)) for stem, text in texts]
    return _cache[docs_dir]


def search_docs(query: str, docs_dir: pathlib.Path = DOCS_DIR) -> str:
    chunks = _load(docs_dir)
    if not chunks or not query.strip():
        return ""
    q_vec = llm.embed(query)
    best = max(chunks, key=lambda c: llm.cosine(c[2], q_vec))
    return best[1]
