"""EmbeddingProvider: local now, remote later -- the two real implementations
that justify this being an interface at all (see CLAUDE.md rule #5).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

InputType = Literal["query", "passage"]


class EmbeddingProvider(ABC):
    @property
    @abstractmethod
    def model_name(self) -> str:
        """Canonical identifier stored in document_embeddings.model_name --
        lets an old and a new embedding generation coexist during a future
        model migration (see migrations/0003_document_embeddings.sql)."""
        ...

    @property
    @abstractmethod
    def dimensions(self) -> int: ...

    @abstractmethod
    def embed(self, texts: list[str], *, input_type: InputType = "query") -> list[list[float]]: ...


class LocalE5EmbeddingProvider(EmbeddingProvider):
    """`sentence-transformers` + `intfloat/multilingual-e5-base` (or `bge-m3`),
    CPU, 0 EUR marginal cost. Multilingual is not optional here: the arbitrage
    strategy reasons over Japanese/Korean/Portuguese content, and an
    English-only model would be blind to the most profitable part of that
    signal.

    For our use (symmetric similarity/clustering/dedup, never asymmetric
    query-vs-passage retrieval), the E5 model card recommends prefixing *all*
    inputs with "query: " uniformly rather than splitting query/passage --
    hence the default. "passage" is reserved for a future asymmetric-retrieval
    use case this project doesn't have yet.
    """

    def __init__(
        self,
        model_name: str = "intfloat/multilingual-e5-base",
        device: str = "cpu",
        dimensions: int = 768,
    ) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name, device=device)
        self._model_name = model_name
        self._dimensions = dimensions

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed(self, texts: list[str], *, input_type: InputType = "query") -> list[list[float]]:
        prefixed = [f"{input_type}: {text}" for text in texts]
        vectors = self._model.encode(prefixed, normalize_embeddings=True)
        return [list(map(float, vector)) for vector in vectors]
