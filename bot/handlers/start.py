from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select

from bot.config import ADMIN_IDS
from bot.database import async_session
from bot.models import User

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message):
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        is_admin = message.from_user.id in ADMIN_IDS
        if user is None:
            user = User(
                id=message.from_user.id,
                username=message.from_user.username,
                full_name=message.from_user.full_name,
                is_admin=is_admin,
                is_active=True,
            )
            session.add(user)
        else:
            # обновляем на случай смены имени/юзернейма, но НЕ трогаем регистрацию заново
            user.username = message.from_user.username
            user.full_name = message.from_user.full_name
            user.is_active = True
            if is_admin:
                user.is_admin = True
        await session.commit()

    role = "администратор" if is_admin else "участник команды"
    text = (
        f"Привет! Ты зарегистрирован(а) как {role}.\n\n"
        "▪️ Каждое утро в 10:00 мск сюда будет приходить список твоих задач и созвонов на день.\n"
        "▪️ Отмечай задачи выполненными кнопкой «Сделано ✅».\n"
    )
    if is_admin:
        text += (
            "\nТы админ, тебе доступны команды:\n"
            "/newtask — создать задачу\n"
            "/newrecurring — создать повторяющуюся задачу\n"
            "/newcall — назначить созвон\n"
            "/report — отчёты и выгрузка по команде\n"
            "/team — список команды\n"
        )
    text += "\n/mytasks — мои задачи\n/mystats — моя статистика"
    await message.answer(text)
