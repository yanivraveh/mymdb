import threading
from typing import List, Tuple

import numpy as np
import faiss  # provided by faiss-cpu
from sentence_transformers import SentenceTransformer
from django.db.models import Prefetch

from .models import Movie, Genre, Actor, Director


_lock = threading.Lock()
_built = False
_index = None  # type: ignore
_movie_ids: List[int] = []
_embedder = None  # type: ignore


def _compose_movie_text(movie: Movie) -> str:
    genre_names = ", ".join(g.name for g in movie.genres.all())
    director_name = ""
    if movie.director_id:
        director_name = f"{movie.director.first_name} {movie.director.last_name}".strip()
    actor_names = ", ".join(
        f"{a.first_name} {a.last_name}".strip() for a in movie.main_actors.all()
    )
    parts = [movie.title or "", movie.description or "", genre_names, director_name, actor_names]
    # Trim overly long descriptions for embedding stability
    return "\n".join(p[:2000] for p in parts if p)


def _l2_normalize(x: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(x, axis=1, keepdims=True) + 1e-12
    return x / norms


def _get_embedder(model_name: str) -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer(model_name)
    return _embedder


def build_index(max_docs: int = 500, model_name: str = "all-MiniLM-L6-v2") -> None:
    global _built, _index, _movie_ids
    with _lock:
        if _built:
            return

        qs = (
            Movie.objects.all()
            .prefetch_related(
                Prefetch("genres", queryset=Genre.objects.only("id", "name")),
                Prefetch("main_actors", queryset=Actor.objects.only("id", "first_name", "last_name")),
            )
            .select_related("director")
            .only("id", "title", "description", "director__first_name", "director__last_name")
        )
        docs: List[Tuple[int, str]] = []
        count = 0
        for m in qs.iterator(chunk_size=200):
            docs.append((m.id, _compose_movie_text(m)))
            count += 1
            if max_docs and count >= max_docs:
                break

        if not docs:
            _index = None
            _movie_ids = []
            _built = True
            return

        movie_ids, texts = zip(*docs)
        embedder = _get_embedder(model_name)
        emb = embedder.encode(list(texts), convert_to_numpy=True).astype("float32")
        emb = _l2_normalize(emb)

        dim = emb.shape[1]
        index = faiss.IndexFlatIP(dim)  # cosine via normalized vectors
        index.add(emb)

        _index = index
        _movie_ids = list(movie_ids)
        _built = True


def retrieve(query: str, top_k: int = 5, model_name: str = "all-MiniLM-L6-v2", max_docs: int = 500) -> List[int]:
    global _index
    if not _built or _index is None:
        build_index(max_docs=max_docs, model_name=model_name)
    if _index is None:
        return []
    embedder = _get_embedder(model_name)
    q = embedder.encode([query], convert_to_numpy=True).astype("float32")
    q = _l2_normalize(q)
    k = max(1, min(top_k, len(_movie_ids)))
    scores, idxs = _index.search(q, k)
    order = idxs[0].tolist()
    return [_movie_ids[i] for i in order if 0 <= i < len(_movie_ids)]


def refresh(max_docs: int = 500, model_name: str = "all-MiniLM-L6-v2") -> None:
    """Rebuild the FAISS index (blocking)."""
    global _built, _index, _movie_ids
    with _lock:
        _built = False
        _index = None
        _movie_ids = []
    build_index(max_docs=max_docs, model_name=model_name)


