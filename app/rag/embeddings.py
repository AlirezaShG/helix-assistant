"""Text -> vector."""

from typing import Protocol

from app.core.config import Settings


class Embedder(Protocol):
    name: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class LocalEmbedder:
    def __init__(self, model_name: str, cache_dir: str):
        from fastembed import TextEmbedding

        self.name = model_name
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.passage_embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return next(iter(self._model.query_embed(text))).tolist()


class OpenAIEmbedder:
    def __init__(self, settings: Settings):
        from openai import OpenAI

        self.name = settings.embedding_model
        self._client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url,
                              timeout=settings.llm_timeout_seconds)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(model=self.name, input=texts)
        return [item.embedding for item in response.data]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def create_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "local":
        return LocalEmbedder(settings.embedding_model, str(settings.embedding_cache_dir))
    if settings.embedding_provider == "openai":
        return OpenAIEmbedder(settings)
    raise ValueError(f"Unknown EMBEDDING_PROVIDER {settings.embedding_provider!r} (use 'local' or 'openai')")
