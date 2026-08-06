from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder


class AssigneeCB(CallbackData, prefix="asg"):
    user_id: int
    session: str  # уникальный идентификатор сессии выбора (напр. "task" или "call")


class AssigneeDoneCB(CallbackData, prefix="asgdone"):
    session: str


class TaskDoneCB(CallbackData, prefix="taskdone"):
    task_id: int


class TaskDeleteCB(CallbackData, prefix="taskdel"):
    task_id: int


class TaskRescheduleCB(CallbackData, prefix="taskresch"):
    task_id: int


class CallCancelCB(CallbackData, prefix="callcancel"):
    call_id: int


class CallAckCB(CallbackData, prefix="callack"):
    call_id: int


def assignee_multiselect_kb(users: list, selected: set[int], session: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for u in users:
        mark = "☑️" if u.id in selected else "▫️"
        kb.button(
            text=f"{mark} {u.full_name}",
            callback_data=AssigneeCB(user_id=u.id, session=session),
        )
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text="Готово ▪️", callback_data=AssigneeDoneCB(session=session).pack()))
    return kb.as_markup()


def task_item_kb(task_id: int, is_admin: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Сделано ✅", callback_data=TaskDoneCB(task_id=task_id))
    if is_admin:
        kb.button(text="Перенести дедлайн", callback_data=TaskRescheduleCB(task_id=task_id))
        kb.button(text="Удалить", callback_data=TaskDeleteCB(task_id=task_id))
    kb.adjust(1)
    return kb.as_markup()


def call_item_kb(call_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Отменить созвон", callback_data=CallCancelCB(call_id=call_id))
    kb.adjust(1)
    return kb.as_markup()


def call_reminder_kb(call_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Готово ✅", callback_data=CallAckCB(call_id=call_id))
    kb.adjust(1)
    return kb.as_markup()


def tasks_done_kb(tasks: list) -> InlineKeyboardMarkup:
    """Одна кнопка на каждую задачу — жмут, когда сделано."""
    kb = InlineKeyboardBuilder()
    for t in tasks:
        kb.button(text=f"Сделано: {t.title}", callback_data=TaskDoneCB(task_id=t.id))
    kb.adjust(1)
    return kb.as_markup()


def task_reminder_kb(task_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Сделано ✅", callback_data=TaskDoneCB(task_id=task_id))
    kb.adjust(1)
    return kb.as_markup()


def main_menu_kb(is_admin: bool) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text="Мои задачи"), KeyboardButton(text="Моя статистика")]]
    if is_admin:
        rows.append([KeyboardButton(text="Новая задача"), KeyboardButton(text="Повторяющаяся задача")])
        rows.append([KeyboardButton(text="Новый созвон"), KeyboardButton(text="Команда")])
        rows.append([KeyboardButton(text="Управление задачами"), KeyboardButton(text="Отчёт (CSV)")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)
