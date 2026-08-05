import datetime as dt

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Date, Time, ForeignKey, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # telegram_id
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(128))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)


class RecurringTask(Base):
    """Шаблон повторяющейся задачи, из которого каждый день/неделю штампуются обычные Task."""
    __tablename__ = "recurring_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    rule: Mapped[str] = mapped_column(String(16))  # daily / weekly
    weekday: Mapped[int | None] = mapped_column(nullable=True)  # 0=понедельник, для weekly
    due_time: Mapped[dt.time] = mapped_column(Time)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    assignees: Mapped[list["RecurringTaskAssignee"]] = relationship(
        back_populates="recurring_task", cascade="all, delete-orphan"
    )


class RecurringTaskAssignee(Base):
    __tablename__ = "recurring_task_assignees"

    id: Mapped[int] = mapped_column(primary_key=True)
    recurring_task_id: Mapped[int] = mapped_column(ForeignKey("recurring_tasks.id"))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))

    recurring_task: Mapped["RecurringTask"] = relationship(back_populates="assignees")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_date: Mapped[dt.date] = mapped_column(Date)
    due_time: Mapped[dt.time | None] = mapped_column(Time, nullable=True)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    is_done: Mapped[bool] = mapped_column(Boolean, default=False)
    done_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    source_recurring_id: Mapped[int | None] = mapped_column(
        ForeignKey("recurring_tasks.id"), nullable=True
    )

    assignees: Mapped[list["TaskAssignee"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class TaskAssignee(Base):
    __tablename__ = "task_assignees"
    __table_args__ = (UniqueConstraint("task_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))

    task: Mapped["Task"] = relationship(back_populates="assignees")


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(256))
    call_dt: Mapped[dt.datetime] = mapped_column(DateTime)  # хранится в МСК, naive
    zoom_link: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    is_cancelled: Mapped[bool] = mapped_column(Boolean, default=False)

    participants: Mapped[list["CallParticipant"]] = relationship(
        back_populates="call", cascade="all, delete-orphan"
    )


class CallParticipant(Base):
    __tablename__ = "call_participants"
    __table_args__ = (UniqueConstraint("call_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id"))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))

    call: Mapped["Call"] = relationship(back_populates="participants")


class ReminderLog(Base):
    """Чтобы не слать одно и то же напоминание дважды."""
    __tablename__ = "reminder_log"
    __table_args__ = (UniqueConstraint("call_id", "reminder_type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id"))
    reminder_type: Mapped[str] = mapped_column(String(16))  # new / 1h / 5m
    sent_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
