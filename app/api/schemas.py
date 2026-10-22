"""
Request and response models of the HTTP API.

Pydantic validates every request before our code sees it (FastAPI answers
422 with the reason), and the response models produce the schema shown at /docs.
"""

from typing import Any

from pydantic import BaseModel, Field, field_validator


class QuestionRequest(BaseModel):
    question: str = Field(
        min_length=1,
        max_length=1000,
        examples=["What share of delivered revenue in Q1 2026 came from hospitals?"],
    )

    @field_validator("question")
    @classmethod
    def normalise(cls, value: str) -> str:
        value = " ".join(value.split())  # collapse whitespace and newlines
        if len(value) < 3:
            raise ValueError("the question is empty or too short")
        return value


class SourceModel(BaseModel):
    document: str
    section: str
    page: int
    score: float


class DocumentResponse(BaseModel):
    question: str
    found: bool
    answer: str
    sources: list[SourceModel]
    evidence: list[str] = Field(description="Sentences quoted from the documents that the answer rests on")
    search_query: str
    retrieved: list[dict[str, Any]]


class SQLResponse(BaseModel):
    question: str
    status: str = Field(description="ok | no_query | rejected | failed")
    sql: str | None
    explanation: str
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    attempts: int
    error: str | None


class StepModel(BaseModel):
    agent: str = Field(description="document_agent | sql_agent | calculator")
    tool: str
    input: dict[str, Any]
    output: dict[str, Any]


class AskResponse(BaseModel):
    answer: str
    route: list[str] = Field(description="Components used, in the order they were first called")
    steps: list[StepModel]
    sources: list[SourceModel]
    sql: list[str]
    elapsed_ms: int
