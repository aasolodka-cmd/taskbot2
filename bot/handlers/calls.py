import datetime as dt
import logging

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, Message
from sqlalchemy import select

from bot.config import BANNER_CALL
from bot.database import async_session
from bot.handlers.admin_tasks import is_admin
from bot.keyboards import (
    AssigneeCB, AssigneeDoneCB, CallAckCB, CallCancelCB, assignee_multiselect_kb, call_item_kb,
)
from bot.models import Call, CallParticipant, User

router = Router()
logger = logging.getLogger(__name__)


class NewCallFSM(StatesGroup):
    title = State()
    participants = State()
    date = State()
    time = State()
    link = State()


@router.message(Command("newcall"))
async def cmd_newcall(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    await state.set_state(NewCallFSM.title)
    await message.answer("Название созвона?")


@router.message(F.text == "Новый созвон")
async def btn_newcall(message: Message, state: FSMContext):
    await cmd_newcall(message, state)


@router.message(NewCallFSM.title)
async def newcall_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text, selected=set())
    session_id = f"call-{message.from_user.id}"
    await state.update_data(session_id=session_id)
    async with async_session() as session:
        users = (await session.execute(select(User).where(User.is_active == True))).scalars().all()  # noqa: E712
    await state.set_state(NewCallFSM.participants)
    await message.answer("Кто участвует?", reply_markup=assignee_multiselect_kb(users, set(), session_id))


@router.callback_query(AssigneeCB.filter(F.session.startswith("call-")))
async def newcall_toggle(query: CallbackQuery, callback_data: AssigneeCB, state: FSMContext):
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


@router.callback_query(AssigneeDoneCB.filter(F.session.startswith("call-")))
async def newcall_participants_done(query: CallbackQuery, callback_data: AssigneeDoneCB, state: FSMContext):
    data = await state.get_data()
    if not data.get("selected"):
        await query.answer("Выбери хотя бы одного участника", show_alert=True)
        return
    await state.set_state(NewCallFSM.date)
    await query.message.answer("Дата созвона, формат ДД.ММ.ГГГГ:")
    await query.answer()


@router.message(NewCallFSM.date)
async def newcall_date(message: Message, state: FSMContext):
    try:
        d = dt.datetime.strptime(message.text.strip(), "%d.%m.%Y").date()
    except ValueError:
        await message.answer("Формат: ДД.ММ.ГГГГ")
        return
    await state.update_data(date=d.isoformat())
    await state.set_state(NewCallFSM.time)
    await message.answer("Время созвона, формат ЧЧ:ММ (по мск):")


@router.message(NewCallFSM.time)
async def newcall_time(message: Message, state: FSMContext):
    try:
        t = dt.datetime.strptime(message.text.strip(), "%H:%M").time()
    except ValueError:
        await message.answer("Формат: ЧЧ:ММ")
        return
    await state.update_data(time=t.isoformat())
    await state.set_state(NewCallFSM.link)
    await message.answer("Ссылка на созвон (или «-», если без ссылки):")


@router.message(NewCallFSM.link)
async def newcall_link(message: Message, state: FSMContext, bot: Bot):
    link = None if message.text.strip() == "-" else message.text.strip()
    data = await state.get_data()
    call_dt = dt.datetime.combine(dt.date.fromisoformat(data["date"]), dt.time.fromisoformat(data["time"]))

    async with async_session() as session:
        call = Call(
            title=data["title"],
            call_dt=call_dt,
            zoom_link=link,
            created_by=message.from_user.id,
        )
        session.add(call)
        await session.flush()
        participant_ids = list(data["selected"])
        for uid in participant_ids:
            session.add(CallParticipant(call_id=call.id, user_id=uid))
        await session.commit()
        call_id = call.id

    await message.answer(f"Готово ▪️ Созвон «{data['title']}» назначен на {call_dt.strftime('%d.%m.%Y %H:%M')} мск.")
    await state.clear()

    # уведомление участникам о новом созвоне (сразу, отдельным сообщением)
    text = (
        f"Назначен новый созвон ▪️\n\n"
        f"«{data['title']}»\n"
        f"{call_dt.strftime('%d.%m.%Y %H:%M')} мск"
    )
    if link:
        text += f"\n{link}"
    for uid in participant_ids:
        try:
            await bot.send_photo(uid, FSInputFile(BANNER_CALL), caption=text)
        except Exception:
            logger.exception("Не удалось отправить уведомление о новом созвоне пользователю %s", uid)


@router.callback_query(CallCancelCB.filter())
async def cb_call_cancel(query: CallbackQuery, callback_data: CallCancelCB, bot: Bot):
    async with async_session() as session:
        call = await session.get(Call, callback_data.call_id)
        if call is None:
            await query.answer("Созвон не найден", show_alert=True)
            return
        is_creator = call.created_by == query.from_user.id
        admin = await is_admin(query.from_user.id)
        if not (is_creator or admin):
            await query.answer("Отменить может только админ или создатель созвона", show_alert=True)
            return
        call.is_cancelled = True
        title = call.title
        participants = (
            await session.execute(select(CallParticipant.user_id).where(CallParticipant.call_id == call.id))
        ).scalars().all()
        await session.commit()

    await query.answer("Созвон отменён")
    await query.message.edit_text(f"{query.message.text}\n\n❌ Отменено")
    for uid in participants:
        try:
            await bot.send_message(uid, f"Созвон «{title}» отменён ▪️")
        except Exception:
            logger.exception("Не удалось отправить уведомление об отмене созвона пользователю %s", uid)


@router.callback_query(CallAckCB.filter())
async def cb_call_ack(query: CallbackQuery, callback_data: CallAckCB):
    await query.answer("Принято ✅")
    try:
        await query.message.edit_caption(caption=f"{query.message.caption}\n\n✅ Принято")
    except Exception:
        pass
