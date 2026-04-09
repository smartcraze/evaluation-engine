import os
from datetime import datetime
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import DateTime, Float, JSON, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

load_dotenv()


class Base(DeclarativeBase):
    pass


class EvaluationJob(Base):
    __tablename__ = "evaluation_jobs"

    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="submitted")
    mode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_check_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    marks: Mapped[float | None] = mapped_column(Float, nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    matched_keywords: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    missing_keywords: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


def _database_url() -> str:
    return os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://myuser:mypassword@localhost:5432/mydb",
    )


engine = create_async_engine(_database_url(), future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def upsert_job(
    *,
    request_id: str,
    status: str,
    mode: str | None = None,
    request_check_url: str | None = None,
    extracted_text: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    async with SessionLocal() as session:
        job = await session.get(EvaluationJob, request_id)
        if job is None:
            job = EvaluationJob(
                request_id=request_id,
                status=status,
                mode=mode,
                request_check_url=request_check_url,
                extracted_text=extracted_text,
                payload=payload,
            )
            session.add(job)
        else:
            job.status = status
            if mode is not None:
                job.mode = mode
            if request_check_url is not None:
                job.request_check_url = request_check_url
            if extracted_text is not None:
                job.extracted_text = extracted_text
            if payload is not None:
                job.payload = payload
        await session.commit()


async def get_job(request_id: str) -> EvaluationJob | None:
    async with SessionLocal() as session:
        stmt = select(EvaluationJob).where(EvaluationJob.request_id == request_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


async def save_evaluation(
    *,
    request_id: str,
    marks: float,
    remarks: str,
    matched_keywords: list[str],
    missing_keywords: list[str],
    model_name: str,
) -> None:
    async with SessionLocal() as session:
        job = await session.get(EvaluationJob, request_id)
        if job is None:
            raise RuntimeError("request_id not found")

        job.status = "completed"
        job.marks = marks
        job.remarks = remarks
        job.matched_keywords = matched_keywords
        job.missing_keywords = missing_keywords
        job.model_name = model_name
        await session.commit()
