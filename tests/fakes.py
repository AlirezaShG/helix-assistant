"""
Test doubles, so the logic can be tested offline, fast and deterministically.

- FakeChatModel replaces the LLM: it returns pre-scripted answers and records
  what it was asked. It supports the three ways the code uses an LLM:
  .invoke(), .with_structured_output(...).invoke() and .bind_tools(...).invoke().
- HashEmbedder replaces the embedding model with a bag-of-words vector, so
  "late payment fee" is close to a chunk containing those words. Crude, but
  enough to test the retrieval plumbing without downloading a model.
"""

import hashlib
import math
import re


class FakeChatModel:
    def __init__(self, replies=None, structured=None):
        self.replies = list(replies or [])  # for .invoke() / .bind_tools().invoke()
        self.structured = list(structured or [])  # for .with_structured_output().invoke()
        self.calls = []  # every message list the model received

    def invoke(self, messages, *args, **kwargs):
        self.calls.append(messages)
        if not self.replies:
            raise AssertionError("FakeChatModel.invoke called more often than scripted")
        return self.replies.pop(0)

    def bind_tools(self, tools, **kwargs):
        return self

    def with_structured_output(self, schema, **kwargs):
        model = self

        class _Structured:
            def invoke(self, messages, *args, **kw):
                model.calls.append(messages)
                if not model.structured:
                    raise AssertionError("structured output requested more often than scripted")
                return model.structured.pop(0)

        return _Structured()


STOPWORDS = {"a", "an", "and", "are", "as", "be", "by", "do", "for", "how", "in", "is", "it", "of", "on",
             "or", "the", "to", "what", "when", "which", "who", "with"}


class HashEmbedder:
    name = "hash-bow-256"
    dimensions = 256

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            if word in STOPWORDS:
                continue
            index = int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dimensions
            vector[index] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    def embed_documents(self, texts):
        return [self._vector(t) for t in texts]

    def embed_query(self, text):
        return self._vector(text)
