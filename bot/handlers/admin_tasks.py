import datetime as dt

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from bot.database import async_session
from bot.keyboards import (
    AssigneeCB, AssigneeDoneCB, TaskDeleteCB, TaskRescheduleCB,
    assignee_multiselect_kb,
)
from bot.models import RecurringTask, RecurringTaskAssignee, Task, TaskAssignee, User
from bot.utils import fmt_time

router = Router()


def admin_only(user_id: int, session_users: dict) -> bool:
    return session_users.get(user_id, False)


async def is_admin(user_id: int) -> bool:
    async with async_session() as session:
        user = await session.get(User, user_id)
        return bool(user and user.is_admin)


# ---------- /team ----------

@router.message(Command("team"))
async def cmd_team(message: Message):
    if not await is_admin(message.from_user.id):
        return
    async with async_session() as session:
        users = (await session.execute(select(User).where(User.is_active == True))).scalars().all()  # noqa: E712
    lines = [f"▪️ {u.full_name} — {'админ' if u.is_admin else 'участник'}" for u in users]
    await message.answer("Команда:\n\n" + "\n".join(lines))


# ---------- Создание обычной задачи ----------

class NewTaskFSM(StatesGroup):
    title = State()
    assignees = State()
    due_date = State()
    due_time = State()


@router.message(Command("newtask"))
async def cmd_newtask(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    await state.set_state(NewTaskFSM.title)
    await message.answer("Название задачи?")


@router.message(NewTaskFSM.title)
async def newtask_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text, selected=set())
    async with async_session() as session:
        users = (await session.execute(select(User).where(User.is_active == True))).scalars().all()  # noqa: E712
    await state.update_data(session_id=f"task-{message.from_user.id}")
    await state.set_state(NewTaskFSM.assignees)
    await message.answer(
        "Кто ответственный? Можно выбрать несколько.",
        reply_markup=assignee_multiselect_kb(users, set(), f"task-{message.from_user.id}"),
    )


@router.callback_query(AssigneeCB.filter(F.session.startswith("task-")))
async def newtask_toggle_assignee(query: CallbackQuery, callback_data: AssigneeCB, state: FSMContext):
    data = await state.get_data()
    selected = set(data.get("selected", set()))
    if callback_data.user_id in selected:
        selected.discard(callback_data.user_id)
    else:
        selected.add(callback_data.user_id)
    await state.update_data(selected=selected)
    async with async_session() as session:
        users = (await session.execute(select(User).where(User.is_active == True))).scalars().all()  # noqa: E712
    await query.message.edit_reply_markup(
        reply_markup=assignee_multiselect_kb(users, selected, callback_data.session)
    )
    await query.answer()


@router.callback_query(AssigneeDoneCB.filter(F.session.startswith("task-")))
async def newtask_assignees_done(query: CallbackQuery, callback_data: AssigneeDoneCB, state: FSMContext):
    data = await state.get_data()
    if not data.get("selected"):
        await query.answer("Выбери хотя бы одного ответственного", show_alert=True)
        return
    await state.set_state(NewTaskFSM.due_date)
    await query.message.answer("Дедлайн, дата в формате ДД.ММ.ГГГГ (например 12.08.2026):")
    await query.answer()


@router.message(NewTaskFSM.due_date)
async def newtask_due_date(message: Message, state: FSMContext):
    try:
        due_date = dt.datetime.strptime(message.text.strip(), "%d.%m.%Y").date()
    except ValueError:
        await message.answer("Не понял дату. Формат: ДД.ММ.ГГГГ")
        return
    await state.update_data(due_date=due_date.isoformat())
    await state.set_state(NewTaskFSM.due_time)
    await message.answer("Время дедлайна, формат ЧЧ:ММ (или «-», если без времени):")


@router.message(NewTaskFSM.due_time)
async def newtask_due_time(message: Message, state: FSMContext):
    text = message.text.strip()
    due_time = None
    if text != "-":
        try:
            due_time = dt.datetime.strptime(text, "%H:%M").time()
        except ValueError:
            await message.answer("Не понял время. Формат: ЧЧ:ММ или «-»")
            return

    data = await state.get_data()
    async with async_session() as session:
        task = Task(
            title=data["title"],
            due_date=dt.date.fromisoformat(data["due_date"]),
            due_time=due_time,
            created_by=message.from_user.id,
        )
        session.add(task)
        await session.flush()
        for uid in data["selected"]:
            session.add(TaskAssignee(task_id=task.id, user_id=uid))
        await session.commit()

    await message.answer(
        f"Готово ▪️ Задача «{data['title']}» создана на {dt.date.fromisoformat(data['due_date']).strftime('%d.%m.%Y')}"
        f"{' ' + fmt_time(due_time) if due_time else ''}. Появится в утреннем списке."
    )
    await state.clear()


# ---------- Повторяющиеся задачи ----------

class NewRecurringFSM(StatesGroup):
    title = State()
    rule = State()
    weekday = State()
    time = State()
    assignees = State()


@router.message(Command("newrecurring"))
async def cmd_newrecurring(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    await state.set_state(NewRecurringFSM.title)
    await message.answer("Название повторяющейся задачи?")


@router.message(NewRecurringFSM.title)
async def newrec_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(NewRecurringFSM.rule)
    await message.answer("Повторять: напиши «daily» (каждый день) или «weekly» (раз в неделю)")


@router.message(NewRecurringFSM.rule)
async def newrec_rule(message: Message, state: FSMContext):
    rule = message.text.strip().lower()
    if rule not in ("daily", "weekly"):
        await message.answer("Напиши «daily» или «weekly»")
        return
    await state.update_data(rule=rule)
    if rule == "weekly":
        await state.set_state(NewRecurringFSM.weekday)
        await message.answer("В какой день недели? 1-Пн, 2-Вт, 3-Ср, 4-Чт, 5-Пт, 6-Сб, 7-Вс")
    else:
        await state.set_state(NewRecurringFSM.time)
        await message.answer("Время дедлайна, формат ЧЧ:ММ:")


@router.message(NewRecurringFSM.weekday)
async def newrec_weekday(message: Message, state: FSMContext):
    try:
        wd = int(message.text.strip())
        assert 1 <= wd <= 7
    except (ValueError, AssertionError):
        await message.answer("Введи число от 1 до 7")
        return
    await state.update_data(weekday=wd - 1)  # python: 0=понедельник
    await state.set_state(NewRecurringFSM.time)
    await message.answer("Время дедлайна, формат ЧЧ:ММ:")


@router.message(NewRecurringFSM.time)
async def newrec_time(message: Message, state: FSMContext):
    try:
        due_time = dt.datetime.strptime(message.text.strip(), "%H:%M").time()
    except ValueError:
        await message.answer("Формат: ЧЧ:ММ")
        return
    await state.update_data(due_time=due_time.isoformat(), selected=set())
    session_id = f"rec-{message.from_user.id}"
    await state.update_data(session_id=session_id)
    async with async_session() as session:
        users = (await session.execute(select(User).where(User.is_active == True))).scalars().all()  # noqa: E712
    await state.set_state(NewRecurringFSM.assignees)
    await message.answer(
        "Кто ответственный?",
        reply_markup=assignee_multiselect_kb(users, set(), session_id),
    )


@router.callback_query(AssigneeCB.filter(F.session.startswith("rec-")))
async def newrec_toggle_assignee(query: CallbackQuery, callback_data: AssigneeCB, state: FSMContext):
    data = await state.get_data()
    selected = set(data.get("selected", set()))
    if callback_data.user_id in selected:
        selected.discard(callback_data.user_id)
    else:
        selected.add(callback_data.user_id)
    await state.update_data(selected=selected)
    async with async_session() as session:
        users = (await session.execute(select(User).where(User.is_active == True))).scalars().all()  # noqa: E712
    await query.message.edit_reply_markup(
        reply_markup=assignee_multiselect_kb(users, selected, callback_data.session)
    )
    await query.answer()


@router.callback_query(AssigneeDoneCB.filter(F.session.startswith("rec-")))
async def newrec_done(query: CallbackQuery, callback_data: AssigneeDoneCB, state: FSMContext):
    data = await state.get_data()
    if not data.get("selected"):
        await query.answer("Выбери хотя бы одного ответственного", show_alert=True)
        return
    async with async_session() as session:
        rt = RecurringTask(
            title=data["title"],
            rule=data["rule"],
            weekday=data.get("weekday"),
            due_time=dt.time.fromisoformat(data["due_time"]),
            created_by=query.from_user.id,
        )
        session.add(rt)
        await session.flush()
        for uid in data["selected"]:
            session.add(RecurringTaskAssignee(recurring_task_id=rt.id, user_id=uid))
        await session.commit()
    await query.message.answer(f"Готово ▪️ Повторяющаяся задача «{data['title']}» создана.")
    await query.answer()
    await state.clear()


# ---------- Перенос дедлайна и удаление (только админ) ----------

class RescheduleFSM(StatesGroup):
    waiting_date = State()


@router.callback_query(TaskRescheduleCB.filter())
async def cb_reschedule_start(query: CallbackQuery, callback_data: TaskRescheduleCB, state: FSMContext):
    if not await is_admin(query.from_user.id):
        await query.answer("Только админ может переносить дедлайн", show_alert=True)
        return
    await state.update_data(reschedule_task_id=callback_data.task_id)
    await state.set_state(RescheduleFSM.waiting_date)
    await query.message.answer("Новая дата дедлайна, формат ДД.ММ.ГГГГ (время можно добавить через пробел ЧЧ:ММ):")
    await query.answer()


@router.message(RescheduleFSM.waiting_date)
async def reschedule_apply(message: Message, state: FSMContext):
    parts = message.text.strip().split()
    try:
        new_date = dt.datetime.strptime(parts[0], "%d.%m.%Y").date()
        new_time = dt.datetime.strptime(parts[1], "%H:%M").time() if len(parts) > 1 else None
    except (ValueError, IndexError):
        await message.answer("Формат: ДД.ММ.ГГГГ или ДД.ММ.ГГГГ ЧЧ:ММ")
        return
    data = await state.get_data()
    async with async_session() as session:
        task = await session.get(Task, data["reschedule_task_id"])
        if task is None:
            await message.answer("Задача не найдена")
            await state.clear()
            return
        task.due_date = new_date
        if new_time:
            task.due_time = new_time
        await session.commit()
        title = task.title
    await message.answer(f"Дедлайн задачи «{title}» перенесён на {new_date.strftime('%d.%m.%Y')}"
                          f"{' ' + parts[1] if len(parts) > 1 else ''} ▪️")
    await state.clear()


@router.callback_query(TaskDeleteCB.filter())
async def cb_task_delete(query: CallbackQuery, callback_data: TaskDeleteCB):
    if not await is_admin(query.from_user.id):
        await query.answer("Только админ может удалять задачи", show_alert=True)
        return
    async with async_session() as session:
        task = await session.get(Task, callback_data.task_id)
        if task:
            task.is_deleted = True
            await session.commit()
    await query.answer("Задача удалена")
    await query.message.edit_text(f"{query.message.text}\n\n🗑 Удалено")
