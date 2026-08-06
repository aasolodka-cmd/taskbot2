import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# Список telegram_id админов через запятую в переменной ADMIN_IDS
_raw_admins = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = {int(x.strip()) for x in _raw_admins.split(",") if x.strip()}

TIMEZONE = "Europe/Moscow"

# Время утреннего списка и вечернего отчёта (по МСК)
MORNING_DIGEST_TIME = "10:00"
EVENING_REPORT_TIME = "22:00"

# День и время недельной сводки (по МСК)
WEEKLY_SUMMARY_DAY = "fri"   # mon/tue/wed/thu/fri/sat/sun
WEEKLY_SUMMARY_TIME = "18:00"

# Два эмодзи, которыми оформляется всё сообщения — и только они
EMOJI_MARK = "▪️"
EMOJI_DONE = "✅"

# За сколько минут до дедлайна задачи слать напоминание (если у задачи указано время)
TASK_REMINDER_MINUTES = 60

# На сколько дней вперёд (не считая сегодня) показывать блок «Скоро» в утреннем списке
UPCOMING_DAYS = 3

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
BANNER_TASKS = os.path.join(ASSETS_DIR, "banner-zadachi-na-den.png")
BANNER_REPORT = os.path.join(ASSETS_DIR, "banner-otchet.png")
BANNER_CALL = os.path.join(ASSETS_DIR, "banner-sozvon.png")
