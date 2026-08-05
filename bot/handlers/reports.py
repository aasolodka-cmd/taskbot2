import csv
import datetime as dt
import io

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message
from sqlalchemy import select

from bot.database import async_session
from bot.handlers.admin_tasks import is_admin
from bot.models import Task, TaskAssignee, User
from bot.utils import today_msk

router = Router()


@router.message(Command("report"))
async def cmd_report(message: Message):
    if not await is_admin(message.from_user.id):
        return

    async with async_session() as session:
        rows = (
            await session.execute(
                select(Task, User)
                .join(TaskAssignee, TaskAssignee.task_id == Task.id)
                .join(User, User.id == TaskAssignee.user_id)
                .where(Task.is_deleted == False)  # noqa: E712
                .order_by(Task.due_date)
            )
        ).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Задача", "Ответственный", "Дедлайн (дата)", "Дедлайн (время)", "Статус"])
    for task, user in rows:
        writer.writerow([
            task.title,
            user.full_name,
            task.due_date.strftime("%d.%m.%Y"),
            task.due_time.strftime("%H:%M") if task.due_time else "",
            "сделано" if task.is_done else "в работе",
        ])

    data = buf.getvalue().encode("utf-8-sig")
    filename = f"team_report_{today_msk().strftime('%Y-%m-%d')}.csv"
    await message.answer_document(BufferedInputFile(data, filename=filename), caption="Выгрузка по команде ▪️")


@router.message(F.text == "Отчёт (CSV)")
async def btn_report(message: Message):
    await cmd_report(message)


@router.message(Command("mystats"))
async def cmd_mystats(message: Message):
    user_id = message.from_user.id
    week_ago = today_msk() - dt.timedelta(days=7)

    async with async_session() as session:
        rows = (
            await session.execute(
                select(Task)
                .join(TaskAssignee, TaskAssignee.task_id == Task.id)
                .where(
                    TaskAssignee.user_id == user_id,
                    Task.is_deleted == False,  # noqa: E712
                    Task.due_date >= week_ago,
                )
            )
        ).scalars().all()

    total = len(rows)
    done = sum(1 for t in rows if t.is_done)
    overdue = sum(1 for t in rows if not t.is_done and t.due_date < today_msk())

    text = (
        f"▪️ Твоя статистика за последние 7 дней:\n\n"
        f"Всего задач: {total}\n"
        f"Выполнено: {done}\n"
        f"Просрочено: {overdue}\n"
    )
    await message.answer(text)


@router.message(F.text == "Моя статистика")
async def btn_mystats(message: Message):
    await cmd_mystats(message)
