from aiogram import Dispatcher

from bot.handlers import start, admin_tasks, member_tasks, calls, reports


def register_all_handlers(dp: Dispatcher):
    dp.include_router(start.router)
    dp.include_router(admin_tasks.router)
    dp.include_router(member_tasks.router)
    dp.include_router(calls.router)
    dp.include_router(reports.router)
