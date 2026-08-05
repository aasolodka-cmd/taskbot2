import datetime as dt

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from bot.database import async_session
from bot.keyboards import TaskDoneCB, task_item_kb
from bot.models import Task, TaskAssignee, User
from bot.utils import fmt_task_line, fmt_overdue_line, today_msk

router = Router()


@router.message(Command("mytasks"))
async def cmd_mytasks(message: Message):
    user_id = message.from_user.id
    today = today_msk()

    async with async_session() as session:
        user = await session.get(User, user_id)
        if user is None:
            await message.answer("Сначала напиши /start.")
            return

        rows = (
            await session.execute(
                select(Task)
                .join(TaskAssignee, TaskAssignee.task_id == Task.id)
                .where(
                    TaskAssignee.user_id == user_id,
                    Task.is_deleted == False,  # noqa: E712
                    Task.due_date == today,
                )
                .order_by(Task.due_time)
            )
        ).scalars().all()

        overdue = (
            await session.execute(
                select(Task)
                .join(TaskAssignee, TaskAssignee.task_id == Task.id)
                .where(
                    TaskAssignee.user_id == user_id,
                    Task.is_deleted == False,  # noqa: E712
                    Task.due_date < today,
                    Task.is_done == False,  # noqa: E712
                )
                .order_by(Task.due_date)
            )
        ).scalars().all()

    if not rows and not overdue:
        await message.answer("На сегодня задач нет ▪️")
        return

    if rows:
        text = f"▪️ Твои задачи на {today.strftime('%d.%m.%Y')}:\n\n"
        text += "\n".join(fmt_task_line(t.title, t.due_time, t.is_done) for t in rows)
        await message.answer(text)
        for t in rows:
            if not t.is_done:
                await message.answer(t.title, reply_markup=task_item_kb(t.id, is_admin=user.is_admin))

    if overdue:
        text = "▪️ Просроченные задачи:\n\n"
        text += "\n".join(fmt_overdue_line(t.title, t.due_date, t.due_time) for t in overdue)
        await message.answer(text)
        for t in overdue:
            await message.answer(t.title, reply_markup=task_item_kb(t.id, is_admin=user.is_admin))


@router.message(F.text == "Мои задачи")
async def btn_mytasks(message: Message):
    await cmd_mytasks(message)


@router.callback_query(TaskDoneCB.filter())
async def cb_task_done(query: CallbackQuery, callback_data: TaskDoneCB):
    async with async_session() as session:
        task = await session.get(Task, callback_data.task_id)
        if task is None:
            await query.answer("Задача не найдена", show_alert=True)
            return
        task.is_done = True
        task.done_at = dt.datetime.utcnow()
        await session.commit()
    await query.answer("Отмечено как сделано ✅")
    await query.message.edit_text(f"{query.message.text}\n\n✅ Выполнено")
