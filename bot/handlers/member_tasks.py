import datetime as dt

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy import select

from bot.config import EMOJI_MARK, UPCOMING_DAYS
from bot.database import async_session
from bot.keyboards import TaskDoneCB, tasks_done_kb
from bot.models import Task, TaskAssignee, User
from bot.utils import fmt_task_line, fmt_overdue_line, fmt_upcoming_line, today_msk

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

        upcoming = (
            await session.execute(
                select(Task)
                .join(TaskAssignee, TaskAssignee.task_id == Task.id)
                .where(
                    TaskAssignee.user_id == user_id,
                    Task.is_deleted == False,  # noqa: E712
                    Task.is_done == False,  # noqa: E712
                    Task.due_date > today,
                    Task.due_date <= today + dt.timedelta(days=UPCOMING_DAYS),
                )
                .order_by(Task.due_date, Task.due_time)
            )
        ).scalars().all()

    if not rows and not overdue and not upcoming:
        await message.answer("Задач нет ▪️")
        return

    text = f"▪️ Список задач на {today.strftime('%d.%m.%Y')}\n\n"
    text += "Задачи на сегодня:\n"
    text += "\n".join(fmt_task_line(t.title, t.due_time, t.is_done) for t in rows) if rows else f"{EMOJI_MARK} нет"
    text += "\n\n"
    text += "Просроченные:\n"
    text += (
        "\n".join(fmt_overdue_line(t.title, t.due_date, t.due_time) for t in overdue)
        if overdue else f"{EMOJI_MARK} нет"
    )
    text += "\n\n"
    text += "Скоро:\n"
    text += (
        "\n".join(fmt_upcoming_line(t.title, t.due_date, t.due_time) for t in upcoming)
        if upcoming else f"{EMOJI_MARK} нет"
    )

    open_tasks = [t for t in list(rows) + list(overdue) + list(upcoming) if not t.is_done]
    await message.answer(text.strip(), reply_markup=tasks_done_kb(open_tasks) if open_tasks else None)


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

    # убираем нажатую кнопку из клавиатуры, остальные кнопки задач оставляем как есть
    markup = query.message.reply_markup
    if markup:
        new_rows = [
            [btn for btn in row if btn.callback_data != query.data]
            for row in markup.inline_keyboard
        ]
        new_rows = [row for row in new_rows if row]
        try:
            await query.message.edit_reply_markup(
                reply_markup=InlineKeyboardMarkup(inline_keyboard=new_rows) if new_rows else None
            )
        except Exception:
            pass
