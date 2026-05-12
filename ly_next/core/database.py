"""PostgreSQL (sessions/tasks/messages) and pgvector-backed RAG chunks."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    delete,
    desc,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import DeclarativeBase

from ly_next.core.config import config
from ly_next.core.logger import get_logger

logger = get_logger(__name__)

RAG_EMBEDDING_DIM = 1536


class Base(DeclarativeBase):
    pass


class BaseModel:
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Session(Base, BaseModel):
    __tablename__ = "sessions"
    name = Column(String(255), nullable=False)
    status = Column(String(50), default="active")
    metadata_ = Column("metadata", MutableDict.as_mutable(JSONB), default=dict)
    messages = Column(JSON, default=list)

    __table_args__ = (
        Index("ix_sessions_status", "status"),
        Index("ix_sessions_created_at", "created_at"),
    )


class Message(Base, BaseModel):
    __tablename__ = "messages"
    session_id = Column(PG_UUID(as_uuid=True), nullable=False)
    role = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    metadata_ = Column("metadata", MutableDict.as_mutable(JSONB), default=dict)

    __table_args__ = (
        Index("ix_messages_session_id", "session_id"),
        Index("ix_messages_created_at", "created_at"),
    )


class Task(Base, BaseModel):
    __tablename__ = "tasks"
    name = Column(String(255), nullable=False)
    status = Column(String(50), default="pending")
    progress = Column(Float, default=0.0)
    result = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    message = Column(Text, nullable=True, default="")
    started_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    metadata_ = Column("metadata", MutableDict.as_mutable(JSONB), default=dict)

    __table_args__ = (
        Index("ix_tasks_status", "status"),
        Index("ix_tasks_created_at", "created_at"),
    )


class RagChunk(Base, BaseModel):
    __tablename__ = "rag_chunks"
    source_path = Column(String(1024), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(RAG_EMBEDDING_DIM), nullable=False)

    __table_args__ = (
        Index("ix_rag_chunks_source_path", "source_path"),
        Index("ix_rag_chunks_chunk_index", "chunk_index"),
    )


class Database:
    _instance: "Database | None" = None

    def __new__(cls) -> "Database":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._engine = None
        self._session_factory = None
        self._initialized = True

    async def connect(self) -> None:
        if self._engine is not None:
            return
        pool_size = config.get("database.pool_size", 10)
        max_overflow = config.get("database.max_overflow", 20)
        echo = bool(config.get("database.sql_echo", False))
        last_exc: Exception | None = None
        urls = config.iter_database_urls()
        for idx, url in enumerate(urls):
            eng = None
            try:
                eng = create_async_engine(
                    url,
                    pool_size=pool_size,
                    max_overflow=max_overflow,
                    echo=echo,
                )
                async with eng.connect() as conn:
                    await conn.execute(text("SELECT 1"))
                self._engine = eng
                self._session_factory = async_sessionmaker(
                    self._engine, class_=AsyncSession, expire_on_commit=False
                )
                eng = None
                if idx > 0:
                    logger.info("Database connected (fallback candidate #%s)", idx)
                else:
                    logger.info("Database connected")
                return
            except Exception as e:
                last_exc = e
            finally:
                if eng is not None:
                    await eng.dispose()
        if last_exc:
            raise last_exc
        raise RuntimeError("No database URLs configured")

    async def disconnect(self) -> None:
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
            logger.info("Database disconnected")

    async def create_tables(self) -> None:
        if self._engine is None:
            await self.connect()
        async with self._engine.connect() as conn:
            vector_ok = True
            try:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                await conn.commit()
            except Exception as e:
                vector_ok = False
                with suppress(Exception):
                    await conn.rollback()
                logger.warning(
                    "pgvector extension not available (%s). RAG vector persistence disabled. "
                    "Install pgvector and run `CREATE EXTENSION vector;`.",
                    e,
                )

            async with conn.begin():
                await conn.run_sync(Session.__table__.create, checkfirst=True)
                await conn.run_sync(Task.__table__.create, checkfirst=True)
                for stmt in (
                    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS message TEXT",
                    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ",
                    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS ended_at TIMESTAMPTZ",
                ):
                    with suppress(Exception):
                        await conn.execute(text(stmt))

                await conn.run_sync(Message.__table__.create, checkfirst=True)
                if vector_ok:
                    await conn.run_sync(RagChunk.__table__.create, checkfirst=True)

        logger.info("Database tables ensured")

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        if self._session_factory is None:
            await self.connect()
        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def replace_rag_chunks(self, rows: list[tuple[str, int, str, list[float]]]) -> None:
        if self._engine is None:
            await self.connect()
        async with self.session() as s:
            await s.execute(delete(RagChunk))
            for source_path, chunk_index, content, emb in rows:
                if len(emb) != RAG_EMBEDDING_DIM:
                    raise ValueError(
                        f"RAG embedding length {len(emb)} != expected {RAG_EMBEDDING_DIM}"
                    )
                s.add(
                    RagChunk(
                        source_path=source_path[:1024],
                        chunk_index=chunk_index,
                        content=content,
                        embedding=emb,
                    )
                )

    async def search_rag_chunks(
        self, query_embedding: list[float], limit: int
    ) -> list[tuple[float, str]]:
        if len(query_embedding) != RAG_EMBEDDING_DIM:
            return []
        async with self.session() as s:
            dist = func.cosine_distance(RagChunk.embedding, query_embedding)
            result = await s.execute(select(RagChunk, dist).order_by(dist).limit(limit))
            out: list[tuple[float, str]] = []
            for row, d in result.all():
                try:
                    dv = float(d)
                except (TypeError, ValueError):
                    dv = 1.0
                out.append((max(0.0, 1.0 - dv), row.content))
            return out

    async def get_session(self, session_id) -> Session | None:
        async with self.session() as s:
            result = await s.execute(select(Session).where(Session.id == session_id))
            return result.scalar_one_or_none()

    async def create_session(self, name: str, metadata: dict = None) -> Session:
        async with self.session() as s:
            session = Session(name=name, metadata_=metadata or {})
            s.add(session)
            await s.flush()
            await s.refresh(session)
            return session

    async def list_sessions(self, limit: int = 100, status: str = None) -> list[Session]:
        async with self.session() as s:
            query = select(Session).order_by(desc(Session.created_at)).limit(limit)
            if status:
                query = query.where(Session.status == status)
            result = await s.execute(query)
            return list(result.scalars().all())

    async def create_message(
        self, session_id, role: str, content: str, metadata: dict = None
    ) -> Message:
        async with self.session() as s:
            message = Message(
                session_id=session_id, role=role, content=content, metadata_=metadata or {}
            )
            s.add(message)
            await s.flush()
            await s.refresh(message)
            return message

    async def get_messages(self, session_id, limit: int = 100) -> list[Message]:
        async with self.session() as s:
            result = await s.execute(
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(desc(Message.created_at))
                .limit(limit)
            )
            return list(result.scalars().all())

    async def create_task(self, name: str, metadata: dict = None) -> Task:
        async with self.session() as s:
            task = Task(name=name, metadata_=metadata or {})
            s.add(task)
            await s.flush()
            await s.refresh(task)
            return task

    def _parse_task_uuid(self, task_id: Any) -> UUID | None:
        if isinstance(task_id, UUID):
            return task_id
        try:
            return UUID(str(task_id))
        except (ValueError, TypeError):
            return None

    async def list_tasks(self, status: str | None = None, limit: int = 100) -> list[Task]:
        async with self.session() as s:
            q = select(Task).order_by(desc(Task.created_at)).limit(limit)
            if status:
                q = q.where(Task.status == status)
            res = await s.execute(q)
            return list(res.scalars().all())

    async def get_task_row(self, task_id: Any) -> Task | None:
        uid = self._parse_task_uuid(task_id)
        if uid is None:
            return None
        async with self.session() as s:
            res = await s.execute(select(Task).where(Task.id == uid))
            return res.scalar_one_or_none()

    async def delete_task_row(self, task_id: Any) -> bool:
        uid = self._parse_task_uuid(task_id)
        if uid is None:
            return False
        async with self.session() as s:
            res = await s.execute(delete(Task).where(Task.id == uid))
            return res.rowcount > 0

    async def clear_tasks_by_status(self, statuses: tuple[str, ...]) -> int:
        async with self.session() as s:
            res = await s.execute(delete(Task).where(Task.status.in_(statuses)))
            return int(res.rowcount or 0)

    async def update_task(
        self,
        task_id: Any,
        status: str | None = None,
        progress: float | None = None,
        result: Any = None,
        error: str | None = None,
        message: str | None = None,
    ) -> Task | None:
        uid = self._parse_task_uuid(task_id)
        if uid is None:
            return None
        async with self.session() as s:
            result_q = await s.execute(select(Task).where(Task.id == uid))
            task = result_q.scalar_one_or_none()
            if not task:
                return None
            now = datetime.now(timezone.utc)
            if status is not None:
                task.status = status
                if status == "running" and task.started_at is None:
                    task.started_at = now
                if status in ("completed", "failed", "stopped"):
                    task.ended_at = now
            if progress is not None:
                task.progress = progress
            if result is not None:
                task.result = result
            if error is not None:
                task.error = error
            if message is not None:
                task.message = message
            await s.flush()
            return task


db = Database()
