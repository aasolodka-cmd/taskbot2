import datetime as dt
import logging

from aiogram import Bot
from aiogram.types import FSInputFile
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from bot.config import (
    BANNER_CALL, BANNER_REPORT, BANNER_TASKS, EMOJI_MARK, EVENING_REPORT_TIME,
    MORNING_DIGEST_TIME, TASK_REMINDER_MINUTES, TIMEZONE, UPCOMING_DAYS,
    WEEKLY_SUMMARY_DAY, WEEKLY_SUMMARY_TIME,
)
from bot.database import async_session
from bot.models import (
    Call, CallParticipant, RecurringTask, RecurringTaskAssignee, ReminderLog,
    Task, TaskAssignee, TaskReminderLog, User,
)
from bot.utils import fmt_call_line, fmt_overdue_line, fmt_task_line, fmt_upcoming_line, now_msk, today_msk

logger = logging.getLogger(__name__)


async def _get_users(session):
    return (await session.execute(select(User).where(User.is_active == True))).scalars().all()  # noqa: E712


async def generate_recurring_tasks():
    """Штампует сегодняшние задачи из шаблонов повторяющихся задач. Гоняется в 00:05 мск."""
    today = today_msk()
    weekday = today.weekday()  # 0 = понедельник

    async with async_session() as session:
        templates = (
            await session.execute(select(RecurringTask).where(RecurringTask.is_active == True))  # noqa: E712
        ).scalars().all()

        for tpl in templates:
            if tpl.rule == "weekly" and tpl.weekday != weekday:
                continue
            # проверяем, не создана ли уже задача на сегодня из этого шаблона
            existing = (
                await session.execute(
                    select(Task).where(
                        Task.source_recurring_id == tpl.id,
                        Task.due_date == today,
                    )
                )
            ).scalar_one_or_none()
            if existing:
                continue

            task = Task(
                title=tpl.title,
                description=tpl.description,
                due_date=today,
                due_time=tpl.due_time,
                created_by=tpl.created_by,
                source_recurring_id=tpl.id,
            )
            session.add(task)
            await session.flush()

            assignee_ids = (
                await session.execute(
                    select(RecurringTaskAssignee.user_id).where(
                        RecurringTaskAssignee.recurring_task_id == tpl.id
                    )
                )
            ).scalars().all()
            for uid in assignee_ids:
                session.add(TaskAssignee(task_id=task.id, user_id=uid))

        await session.commit()


async def morning_digest(bot: Bot):
    from bot.keyboards import tasks_done_kb  # локальный импорт, чтобы избежать циклов

    today = today_msk()

    async with async_session() as session:
        users = await _get_users(session)
        admins = [u for u in users if u.is_admin]

        for user in users:
            my_tasks = (
                await session.execute(
                    select(Task)
                    .join(TaskAssignee, TaskAssignee.task_id == Task.id)
                    .where(
                        TaskAssignee.user_id == user.id,
                        Task.is_deleted == False,  # noqa: E712
                        Task.due_date == today,
                    )
                    .order_by(Task.due_time)
                )
            ).scalars().all()

            my_overdue = (
                await session.execute(
                    select(Task)
                    .join(TaskAssignee, TaskAssignee.task_id == Task.id)
                    .where(
                        TaskAssignee.user_id == user.id,
                        Task.is_deleted == False,  # noqa: E712
                        Task.due_date < today,
                        Task.is_done == False,  # noqa: E712
                    )
                )
            ).scalars().all()

            my_calls = (
                await session.execute(
                    select(Call)
                    .join(CallParticipant, CallParticipant.call_id == Call.id)
                    .where(
                        CallParticipant.user_id == user.id,
                        Call.is_cancelled == False,  # noqa: E712
                        Call.call_dt >= dt.datetime.combine(today, dt.time.min),
                        Call.call_dt <= dt.datetime.combine(today, dt.time.max),
                    )
                    .order_by(Call.call_dt)
                )
            ).scalars().all()

            my_upcoming = (
                await session.execute(
                    select(Task)
                    .join(TaskAssignee, TaskAssignee.task_id == Task.id)
                    .where(
                        TaskAssignee.user_id == user.id,
                        Task.is_deleted == False,  # noqa: E712
                        Task.is_done == False,  # noqa: E712
                        Task.due_date > today,
                        Task.due_date <= today + dt.timedelta(days=UPCOMING_DAYS),
                    )
                    .order_by(Task.due_date, Task.due_time)
                )
            ).scalars().all()

            if not my_tasks and not my_overdue and not my_calls and not my_upcoming:
                continue

            text = f"▪️ Список на {today.strftime('%d.%m.%Y')}\n\n"
            text += "Задачи на сегодня:\n"
            text += (
                "\n".join(fmt_task_line(t.title, t.due_time, t.is_done) for t in my_tasks)
                if my_tasks else f"{EMOJI_MARK} нет"
            )
            text += "\n\n"
            if my_calls:
                text += "Созвоны:\n" + "\n".join(
                    fmt_call_line(c.title, c.call_dt, c.zoom_link) for c in my_calls
                ) + "\n\n"
            text += "Просроченные:\n"
            text += (
                "\n".join(fmt_overdue_line(t.title, t.due_date, t.due_time) for t in my_overdue)
                if my_overdue else f"{EMOJI_MARK} нет"
            )
            text += "\n\n"
            text += "Скоро:\n"
            text += (
                "\n".join(fmt_upcoming_line(t.title, t.due_date, t.due_time) for t in my_upcoming)
                if my_upcoming else f"{EMOJI_MARK} нет"
            )

            open_tasks = [t for t in list(my_tasks) + list(my_overdue) + list(my_upcoming) if not t.is_done]

            try:
                await bot.send_photo(
                    user.id,
                    FSInputFile(BANNER_TASKS),
                    caption=text,
                    reply_markup=tasks_done_kb(open_tasks) if open_tasks else None,
                )
            except Exception:
                logger.exception("Не удалось отправить утренний список пользователю %s", user.id)

        # Полная сводка по всей команде — только админам
        for admin in admins:
            all_tasks = (
                await session.execute(
                    select(Task, User.full_name)
                    .join(TaskAssignee, TaskAssignee.task_id == Task.id)
                    .join(User, User.id == TaskAssignee.user_id)
                    .where(Task.is_deleted == False, Task.due_date == today)  # noqa: E712
                    .order_by(Task.due_time)
                )
            ).all()
            all_calls = (
                await session.execute(
                    select(Call)
                    .where(
                        Call.is_cancelled == False,  # noqa: E712
                        Call.call_dt >= dt.datetime.combine(today, dt.time.min),
                        Call.call_dt <= dt.datetime.combine(today, dt.time.max),
                    )
                    .order_by(Call.call_dt)
                )
            ).scalars().all()

            text = f"▪️ Команда, задачи на {today.strftime('%d.%m.%Y')}\n\n"
            if all_tasks:
                for task, full_name in all_tasks:
                    text += f"{fmt_task_line(task.title, task.due_time, task.is_done)} — {full_name}\n"
            else:
                text += "Задач на сегодня нет\n"
            if all_calls:
                text += "\nСозвоны:\n" + "\n".join(
                    fmt_call_line(c.title, c.call_dt, c.zoom_link) for c in all_calls
                )
            try:
                await bot.send_photo(admin.id, FSInputFile(BANNER_TASKS), caption=text)
            except Exception:
                logger.exception("Не удалось отправить сводку по команде админу %s", admin.id)


async def evening_report(bot: Bot):
    today = today_msk()
    async with async_session() as session:
        admins = [u for u in await _get_users(session) if u.is_admin]

        rows = (
            await session.execute(
                select(Task, User.full_name)
                .join(TaskAssignee, TaskAssignee.task_id == Task.id)
                .join(User, User.id == TaskAssignee.user_id)
                .where(Task.is_deleted == False, Task.due_date == today)  # noqa: E712
            )
        ).all()

    total = len(rows)
    done = sum(1 for t, _ in rows if t.is_done)
    not_done = [(t, name) for t, name in rows if not t.is_done]

    text = f"▪️ Итоги дня, {today.strftime('%d.%m.%Y')}\n\n"
    text += f"Всего задач на день: {total}\nВыполнено: {done}\nНе выполнено: {len(not_done)}\n"
    if not_done:
        text += "\nНе сделано:\n" + "\n".join(f"▪️ {t.title} — {name}" for t, name in not_done)

    for admin in admins:
        try:
            await bot.send_photo(admin.id, FSInputFile(BANNER_REPORT), caption=text)
        except Exception:
            logger.exception("Не удалось отправить вечерний отчёт админу %s", admin.id)


async def weekly_summary(bot: Bot):
    week_ago = today_msk() - dt.timedelta(days=7)
    async with async_session() as session:
        admins = [u for u in await _get_users(session) if u.is_admin]
        rows = (
            await session.execute(
                select(Task).where(Task.is_deleted == False, Task.due_date >= week_ago)  # noqa: E712
            )
        ).scalars().all()

    total = len(rows)
    done = sum(1 for t in rows if t.is_done)
    overdue = sum(1 for t in rows if not t.is_done and t.due_date < today_msk())

    text = (
        f"▪️ Недельная сводка по команде\n\n"
        f"Всего задач: {total}\nВыполнено: {done}\nПросрочено: {overdue}"
    )
    for admin in admins:
        try:
            await bot.send_photo(admin.id, FSInputFile(BANNER_REPORT), caption=text)
        except Exception:
            logger.exception("Не удалось отправить недельную сводку админу %s", admin.id)


async def check_call_reminders(bot: Bot):
    from bot.keyboards import call_reminder_kb  # локальный импорт, чтобы избежать циклов

    now = now_msk().replace(tzinfo=None)
    async with async_session() as session:
        calls = (
            await session.execute(
                select(Call).where(
                    Call.is_cancelled == False,  # noqa: E712
                    Call.call_dt >= now,
                    Call.call_dt <= now + dt.timedelta(hours=1, minutes=1),
                )
            )
        ).scalars().all()

        for call in calls:
            delta_min = (call.call_dt - now).total_seconds() / 60
            reminder_type = None
            if delta_min <= 60:
                reminder_type = "1h"
            if delta_min <= 5:
                reminder_type = "5m"
            if reminder_type is None:
                continue

            already_sent = (
                await session.execute(
                    select(ReminderLog).where(
                        ReminderLog.call_id == call.id,
                        ReminderLog.reminder_type == reminder_type,
                    )
                )
            ).scalar_one_or_none()
            if already_sent:
                continue

            participants = (
                await session.execute(
                    select(CallParticipant.user_id).where(CallParticipant.call_id == call.id)
                )
            ).scalars().all()

            label = "через час" if reminder_type == "1h" else "через 5 минут"
            text = f"▪️ Напоминание: «{call.title}» {label} ({call.call_dt.strftime('%H:%M')} мск)"
            if call.zoom_link:
                text += f"\n{call.zoom_link}"

            for uid in participants:
                try:
                    await bot.send_photo(
                        uid,
                        FSInputFile(BANNER_CALL),
                        caption=text,
                        reply_markup=call_reminder_kb(call.id) if reminder_type == "1h" else None,
                    )
                except Exception:
                    logger.exception("Не удалось отправить напоминание о созвоне %s пользователю %s", call.id, uid)

            session.add(ReminderLog(call_id=call.id, reminder_type=reminder_type))
            await session.commit()


async def check_task_reminders(bot: Bot):
    """Напоминание за TASK_REMINDER_MINUTES минут до дедлайна задачи (если у неё указано время)."""
    from bot.keyboards import task_reminder_kb  # локальный импорт, чтобы избежать циклов

    now = now_msk().replace(tzinfo=None)
    today = today_msk()

    async with async_session() as session:
        tasks = (
            await session.execute(
                select(Task).where(
                    Task.is_deleted == False,  # noqa: E712
                    Task.is_done == False,  # noqa: E712
                    Task.due_date == today,
                    Task.due_time.is_not(None),
                )
            )
        ).scalars().all()

        for task in tasks:
            deadline = dt.datetime.combine(task.due_date, task.due_time)
            delta_min = (deadline - now).total_seconds() / 60
            if delta_min < 0 or delta_min > TASK_REMINDER_MINUTES:
                continue

            already_sent = (
                await session.execute(
                    select(TaskReminderLog).where(
                        TaskReminderLog.task_id == task.id,
                        TaskReminderLog.reminder_type == "1h",
                    )
                )
            ).scalar_one_or_none()
            if already_sent:
                continue

            assignee_ids = (
                await session.execute(
                    select(TaskAssignee.user_id).where(TaskAssignee.task_id == task.id)
                )
            ).scalars().all()

            text = f"▪️ Напоминание: «{task.title}» — дедлайн в {task.due_time.strftime('%H:%M')} мск"

            for uid in assignee_ids:
                try:
                    await bot.send_message(uid, text, reply_markup=task_reminder_kb(task.id))
                except Exception:
                    logger.exception("Не удалось отправить напоминание о задаче %s пользователю %s", task.id, uid)

            session.add(TaskReminderLog(task_id=task.id, reminder_type="1h"))
            await session.commit()


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    m_hour, m_min = MORNING_DIGEST_TIME.split(":")
    scheduler.add_job(
        morning_digest,
        CronTrigger(hour=m_hour, minute=m_min, timezone=TIMEZONE),
        args=[bot],
        id="morning_digest",
    )

    e_hour, e_min = EVENING_REPORT_TIME.split(":")
    scheduler.add_job(
        evening_report,
        CronTrigger(hour=e_hour, minute=e_min, timezone=TIMEZONE),
        args=[bot],
        id="evening_report",
    )

    w_hour, w_min = WEEKLY_SUMMARY_TIME.split(":")
    scheduler.add_job(
        weekly_summary,
        CronTrigger(day_of_week=WEEKLY_SUMMARY_DAY, hour=w_hour, minute=w_min, timezone=TIMEZONE),
        args=[bot],
        id="weekly_summary",
    )

    scheduler.add_job(check_call_reminders, "interval", minutes=1, args=[bot], id="call_reminders")
    scheduler.add_job(check_task_reminders, "interval", minutes=1, args=[bot], id="task_reminders")
    scheduler.add_job(
        generate_recurring_tasks,
        CronTrigger(hour=0, minute=5, timezone=TIMEZONE),
        id="generate_recurring",
    )

    return scheduler
