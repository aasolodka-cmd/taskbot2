import datetime as dt

import pytz

from bot.config import TIMEZONE, EMOJI_MARK, EMOJI_DONE

MSK = pytz.timezone(TIMEZONE)


def now_msk() -> dt.datetime:
    return dt.datetime.now(MSK)


def today_msk() -> dt.date:
    return now_msk().date()


def fmt_date(d: dt.date) -> str:
    return d.strftime("%d.%m.%Y")


def fmt_time(t: dt.time | None) -> str:
    return t.strftime("%H:%M") if t else "—"


def fmt_task_line(title: str, due_time, is_done: bool) -> str:
    mark = EMOJI_DONE if is_done else EMOJI_MARK
    time_part = f" (до {fmt_time(due_time)})" if due_time else ""
    return f"{mark} {title}{time_part}"


def fmt_overdue_line(title: str, due_date: dt.date, due_time) -> str:
    time_part = f", {fmt_time(due_time)}" if due_time else ""
    return f"{EMOJI_MARK} {title} — с {fmt_date(due_date)}{time_part}"


def fmt_upcoming_line(title: str, due_date: dt.date, due_time) -> str:
    time_part = f" {fmt_time(due_time)}" if due_time else ""
    return f"{EMOJI_MARK} {title} — до {fmt_date(due_date)}{time_part}"


def fmt_call_line(title: str, call_dt: dt.datetime, zoom_link: str | None) -> str:
    line = f"{EMOJI_MARK} {title} — {call_dt.strftime('%H:%M')}"
    if zoom_link:
        line += f"\n   {zoom_link}"
    return line
