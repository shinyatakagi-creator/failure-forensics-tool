import hashlib
import os

import numpy as np
from dotenv import load_dotenv

load_dotenv()

HAS_API_KEY = bool(os.environ.get("OPENAI_API_KEY"))
GEN_MODEL = os.environ.get("GEN_MODEL", "gpt-4o-mini")
# Judge must differ from the generator so it doesn't share its blind spots.
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "gpt-4o")

_STOPWORDS = {
    "the", "a", "an", "to", "of", "in", "on", "is", "are", "for", "and",
    "or", "with", "at", "by", "do", "i", "what", "how", "can", "you", "my",
}

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI()
    return _client


def embed(text: str) -> np.ndarray:
    if HAS_API_KEY:
        resp = _get_client().embeddings.create(model="text-embedding-3-small", input=text)
        return np.array(resp.data[0].embedding)
    # ponytail: no API key -> deterministic hash-based bag-of-words vector, no network needed.
    # upgrade: set OPENAI_API_KEY, real embeddings kick in with no code change.
    vec = np.zeros(256)
    for word in text.lower().split():
        word = word.strip(".,?!:;")
        if word in _STOPWORDS:
            continue
        idx = int(hashlib.sha256(word.encode()).hexdigest(), 16) % 256
        vec[idx] += 1
    return vec


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom else 0.0


def complete(prompt: str, system: str = "", model: str | None = None) -> str:
    if HAS_API_KEY:
        resp = _get_client().chat.completions.create(
            model=model or GEN_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content or ""
    # ponytail: no API key -> templated offline answer instead of a real completion.
    # upgrade: set OPENAI_API_KEY for real generations.
    return f"Based on the available context: {prompt[:200]}"
