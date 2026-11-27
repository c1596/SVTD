"""
Skibidi Verse Tower Defense — Telegram TD-бот с созданием каток (лобби 1–4 игрока),
конструктором юнитов/мобов/карт/волн/крейтов, заражением боссов, уровнями юнитов за урон и P2P-рынком.

Стек: Python 3.10+, aiogram 3.x, aiosqlite, Pillow (автоустановка при запуске).
"""

import asyncio
import html
import importlib
import importlib.util
import io
import json
import logging
import math
import os
import random
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple


def ensure_dependencies(packages: Dict[str, str]) -> None:
    """Автоматически устанавливает недостающие библиотеки перед запуском бота."""
    missing = [
        pip_spec
        for mod_name, pip_spec in packages.items()
        if importlib.util.find_spec(mod_name) is None
    ]
    if missing:
        print(f"📦 Установка отсутствующих библиотек: {', '.join(missing)}...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
            importlib.invalidate_caches()
            print("✅ Библиотеки установлены!")
        except Exception as exc:
            print(f"❌ Ошибка установки библиотек: {exc}")
            sys.exit(1)


ensure_dependencies({
    "aiogram": "aiogram>=3.0.0",
    "aiosqlite": "aiosqlite",
    "PIL": "Pillow",
})

import aiosqlite
from PIL import Image, ImageDraw, ImageFont
from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    TelegramObject,
)

# ==============================================================================
# 1. КОНФИГУРАЦИЯ И КОНСТАНТЫ
# ==============================================================================

DEFAULT_BOT_TOKEN = "9149772940:AAGjZRlItcwcmWKOA9mUd_BDoj_IEkNfyzE"
DEFAULT_OWNER_ID = 5341904332

_env_token = (os.getenv("BOT_TOKEN") or "").strip().strip('"').strip("'")
if (
    ":" in _env_token
    and _env_token.split(":", 1)[0].isdigit()
    and _env_token.split(":", 1)[1]
    and not any(ch.isspace() for ch in _env_token)
):
    BOT_TOKEN = _env_token
else:
    BOT_TOKEN = DEFAULT_BOT_TOKEN

_env_owner = (os.getenv("OWNER_ID") or "").strip()
OWNER_ID = int(_env_owner) if _env_owner.isdigit() else DEFAULT_OWNER_ID
DB_PATH = (os.getenv("DB_PATH") or "").strip() or "skibidi_verse_td.db"

MAX_DECK_SIZE = 5
MAX_UNIT_LEVEL = 50
UNIT_XP_PER_DAMAGE = 0.1        # 1 урон = 0.1 опыта юниту
UNIT_DMG_PCT_PER_LEVEL = 0.5    # +0.5% к урону за каждый уровень
MARKET_COMMISSION_PCT = 20      # 20% комиссия владельцу, 80% продавцу
DAILY_COOLDOWN = 86400

FONT_FILE = "bot_font.ttf"
FONT_URL = "https://github.com/googlefonts/roboto/raw/main/src/hinted/Roboto-Bold.ttf"
if not os.path.exists(FONT_FILE):
    try:
        with urllib.request.urlopen(FONT_URL, timeout=5) as resp:
            with open(FONT_FILE, "wb") as f:
                f.write(resp.read())
    except Exception:
        pass

# Настройки баланса по умолчанию (редактируются в Админ-панели)
DEFAULT_SETTINGS: Dict[str, str] = {
    "maintenance": "0",
    "coins_per_damage": "0.5",       # Монет внутри катки за 1 ед. урона
    "turn_time_noskip": "6",         # Секунд на ход без авто-скипа
    "turn_time_skip": "3",           # Секунд на ход с авто-скипом
    "infected_mult": "1.20",         # Множитель урона 🦠 Инфектед (+20%)
    "shiny_chance_pct": "1.0",       # Базовый шанс ✨ Shiny (%)
    "shiny_bonus_pct": "25",         # Бонус ✨ Shiny к статам (%)
    "partner_sign_disc_pct": "10",   # Скидка Партнёр-сигны на поставку/апгрейд (%)
    "admin_sign_disc_pct": "20",     # Скидка Админ-сигны на поставку/апгрейд (%)
    "p_common_price": "150",
    "p_common_bonus": "5",           # +5% к шансу заражения (напр. 1% + 5% = 6%)
    "p_upgraded_price": "450",
    "p_upgraded_bonus": "12",        # +12% к шансу заражения
    "p_elite_price": "1200",
    "p_elite_bonus": "22",           # +22% к шансу заражения
    "wb_cooldown_sec": "60",         # КД удара по Мировому Боссу
    "event_coin_mult": "1.0",        # Ивент-множитель наград
    "event_luck_mult": "1.0",        # Ивент-множитель удачи Shiny
}

GAME_SETTINGS: Dict[str, str] = dict(DEFAULT_SETTINGS)

SETTING_META: Dict[str, Tuple[str, str, float, float]] = {
    "coins_per_damage": ("🪙 Монет в катке за 1 урон", "float", 0.05, 10.0),
    "turn_time_noskip": ("⏱ Длительность хода (обыч., сек)", "int", 2, 20),
    "turn_time_skip": ("⏩ Длительность хода (скип, сек)", "int", 1, 10),
    "infected_mult": ("🦠 Множитель 🦠 Инфектед", "float", 1.0, 5.0),
    "shiny_chance_pct": ("✨ Шанс Shiny (%)", "float", 0.1, 100.0),
    "shiny_bonus_pct": ("✨ Бонус Shiny к статам (%)", "int", 5, 200),
    "partner_sign_disc_pct": ("🤝 Скидка Партнёр-сигны (%)", "int", 1, 60),
    "admin_sign_disc_pct": ("👑 Скидка Админ-сигны (%)", "int", 1, 70),
    "p_common_price": ("🦠 Цена Обыч. паразита", "int", 10, 50000),
    "p_common_bonus": ("🦠 +Шанс Обыч. паразита (%)", "int", 1, 80),
    "p_upgraded_price": ("☣️ Цена Улучш. паразита", "int", 10, 100000),
    "p_upgraded_bonus": ("☣️ +Шанс Улучш. паразита (%)", "int", 1, 85),
    "p_elite_price": ("💎 Цена Элит. паразита", "int", 10, 200000),
    "p_elite_bonus": ("💎 +Шанс Элит. паразита (%)", "int", 1, 95),
    "wb_cooldown_sec": ("🌍 КД Мирового Босса (сек)", "int", 5, 600),
    "event_coin_mult": ("💰 Ивент-множитель монет", "float", 0.5, 10.0),
    "event_luck_mult": ("🍀 Ивент-множитель удачи Shiny", "float", 1.0, 10.0),
}

FACTIONS: Dict[str, str] = {
    "alliance": "📷 Альянс",
    "skibidi": "🚽 Скибиди",
    "astro": "🌌 Астро",
    "infected": "🦠 Заражённые",
}

RARITIES: Dict[str, Tuple[str, str, int]] = {
    "common": ("Обычный", "⚪️", 1),
    "rare": ("Редкий", "🟢", 2),
    "epic": ("Эпический", "🟣", 3),
    "legendary": ("Легендарный", "🟡", 4),
    "mythic": ("Мифический", "🔴", 5),
    "secret": ("Секретный", "🌌", 6),
}

# Мультиклассы юнитов (включая новый класс «Кнокбек»)
UNIT_CLASSES: List[str] = [
    "Одиночный",
    "Сплеш",
    "АОЕ",
    "Саппорт",
    "Ферма",
    "Замедление",
    "Оглушение",
    "Горение",
    "Кнокбек",
]

ATTACKING_CLASSES: Set[str] = {
    "Одиночный", "Сплеш", "АОЕ", "Замедление", "Оглушение", "Горение", "Кнокбек"
}

# Типы паразитов (Астро-Инфектед убран — все дают стандартный 🦠 Инфектед, но разный +шанс)
PARASITES_META: Dict[str, Tuple[str, str]] = {
    "common": ("🦠 Обычный паразит", "p_common"),
    "upgraded": ("☣️ Улучшенный паразит", "p_upgraded"),
    "elite": ("💎 Элитный паразит", "p_elite"),
}

ADMIN_PERMS: Dict[str, str] = {
    "manage_units": "🃏 Создание/редактирование/удаление юнитов",
    "manage_mobs": "👾 Создание/редактирование/удаление мобов",
    "manage_maps": "🗺 Создание/редактирование карт и волн",
    "manage_crates": "📦 Создание/редактирование крейтов и баннеров",
    "manage_settings": "🎛 Настройки баланса, Инфектед, Shiny, ивентов",
    "manage_bosses": "🌍 Запуск и управление Мировым Боссом",
    "manage_economy": "💰 Выдача монет, паразитов и юнитов",
    "manage_users": "👥 Просмотр игроков и баны",
    "broadcast": "📢 Рассылка сообщений всем игрокам",
    "sign_admin": "👑 Админ-сигна (-20% цена/прокачка)",
    "manage_admins": "👮 Админы, Партнёры-сигнеры, техработы и БД",
}

# Оперативное состояние активных каток, задач, фаз заражения и кеш фото
ACTIVE_BATTLES: Dict[int, Dict[str, Any]] = {}
BATTLE_COUNTER = 1
USER_TO_BATTLE: Dict[int, int] = {}
BATTLE_TASKS: Dict[int, asyncio.Task] = {}
PENDING_INFECTIONS: Dict[int, Dict[str, Any]] = {}
IMAGE_CACHE: Dict[str, bytes] = {}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("skibidi_td")


def cfg_float(key: str) -> float:
    try:
        return float(GAME_SETTINGS.get(key, DEFAULT_SETTINGS[key]))
    except (ValueError, TypeError):
        return float(DEFAULT_SETTINGS[key])


def cfg_int(key: str) -> int:
    try:
        return int(float(GAME_SETTINGS.get(key, DEFAULT_SETTINGS[key])))
    except (ValueError, TypeError):
        return int(float(DEFAULT_SETTINGS[key]))


def get_parasite_info(p_key: str) -> Tuple[str, str, int, int]:
    """Возвращает (название, колонка БД, цена, +бонус к шансу в % от числа)."""
    name, col = PARASITES_META[p_key]
    return name, col, cfg_int(f"p_{p_key}_price"), cfg_int(f"p_{p_key}_bonus")


def calc_infect_chance(base_chance: float, bonus_pct: float = 0.0, pity_pct: float = 0.0) -> float:
    """
    Считает итоговый шанс заражения как процент от базового числа:
    base_chance * (1 + (bonus_pct + pity_pct) / 100).
    Пример: 1% + 5% = 1.05%.
    """
    total = float(base_chance) * (1.0 + (float(bonus_pct) + float(pity_pct)) / 100.0)
    return min(95.0, round(total, 2))


def fmt_pct(value: float) -> str:
    """Красиво форматирует процент (1.05 -> '1.05', 2.00 -> '2')."""
    s = f"{float(value):.2f}".rstrip("0").rstrip(".")
    return s or "0"


def xp_required_for_level(level: int) -> float:
    """Сколько опыта нужно юниту для перехода с `level` на `level + 1`."""
    if level >= MAX_UNIT_LEVEL:
        return 0.0
    return round(50.0 * (level ** 1.35), 1)


def apply_unit_xp(level: int, xp: float, gained_xp: float) -> Tuple[int, float, int]:
    """Начисляет опыт юниту, возвращает (новый_уровень, остаток_xp, сколько_уровней_поднято)."""
    if level >= MAX_UNIT_LEVEL or gained_xp <= 0:
        return min(level, MAX_UNIT_LEVEL), 0.0 if level >= MAX_UNIT_LEVEL else xp, 0
    xp = round(xp + gained_xp, 2)
    ups = 0
    while level < MAX_UNIT_LEVEL:
        need = xp_required_for_level(level)
        if xp >= need:
            xp = round(xp - need, 2)
            level += 1
            ups += 1
        else:
            break
    if level >= MAX_UNIT_LEVEL:
        xp = 0.0
    return level, xp, ups


# ==============================================================================
# 2. БАЗА ДАННЫХ (AIOSQLITE)
# ==============================================================================

class Database:
    def __init__(self, path: str):
        self.path = path

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT DEFAULT '',
                    full_name TEXT DEFAULT 'Игрок',
                    coins INTEGER DEFAULT 400,
                    p_common INTEGER DEFAULT 2,
                    p_upgraded INTEGER DEFAULT 0,
                    p_elite INTEGER DEFAULT 0,
                    wins INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    total_damage REAL DEFAULT 0,
                    bosses_killed INTEGER DEFAULT 0,
                    infections_success INTEGER DEFAULT 0,
                    infections_fail INTEGER DEFAULT 0,
                    pity_bonus INTEGER DEFAULT 0,
                    daily_streak INTEGER DEFAULT 0,
                    last_daily INTEGER DEFAULT 0,
                    is_banned INTEGER DEFAULT 0,
                    created_at INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS admins (
                    user_id INTEGER PRIMARY KEY,
                    added_by INTEGER DEFAULT 0,
                    perms_json TEXT DEFAULT '{}',
                    added_at INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS signers (
                    user_id INTEGER PRIMARY KEY,
                    role TEXT NOT NULL DEFAULT 'partner',
                    added_by INTEGER DEFAULT 0,
                    added_at INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS units (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    faction TEXT DEFAULT 'alliance',
                    rarity TEXT DEFAULT 'common',
                    classes_json TEXT DEFAULT '["Одиночный"]',
                    deploy_cost INTEGER DEFAULT 50,
                    supply_limit INTEGER DEFAULT 4,
                    damage REAL DEFAULT 15,
                    cd REAL DEFAULT 1.5,
                    cd_boost REAL DEFAULT 1.0,
                    dmg_boost REAL DEFAULT 1.0,
                    income INTEGER DEFAULT 0,
                    slow_percent INTEGER DEFAULT 0,
                    slow_duration REAL DEFAULT 0,
                    slow_cd REAL DEFAULT 10,
                    stun_chance INTEGER DEFAULT 0,
                    stun_duration INTEGER DEFAULT 0,
                    burn_chance INTEGER DEFAULT 0,
                    burn_damage REAL DEFAULT 0,
                    burn_duration INTEGER DEFAULT 0,
                    knockback_power REAL DEFAULT 0,
                    upgrades_json TEXT DEFAULT '{}',
                    description TEXT DEFAULT '',
                    photo_id TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS mobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    hp INTEGER NOT NULL,
                    defense_percent INTEGER DEFAULT 0,
                    is_boss INTEGER DEFAULT 0,
                    infect_chance INTEGER DEFAULT 0,
                    infected_unit_id INTEGER DEFAULT 0,
                    photo_id TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS maps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    photo_id TEXT DEFAULT '',
                    starting_coins INTEGER DEFAULT 120,
                    base_hp INTEGER DEFAULT 100,
                    waves_json TEXT DEFAULT '[]',
                    win_coins INTEGER DEFAULT 250,
                    lose_coins INTEGER DEFAULT 35
                );

                CREATE TABLE IF NOT EXISTS crates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    price INTEGER NOT NULL,
                    photo_id TEXT DEFAULT '',
                    units_json TEXT DEFAULT '{}',
                    banners_json TEXT DEFAULT '[]',
                    current_banner INTEGER DEFAULT 0,
                    active INTEGER DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS inventory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    unit_id INTEGER NOT NULL,
                    level INTEGER DEFAULT 1,
                    xp REAL DEFAULT 0,
                    is_shiny INTEGER DEFAULT 0,
                    is_infected INTEGER DEFAULT 0,
                    sign_type TEXT DEFAULT 'none',
                    signed_by TEXT DEFAULT '',
                    equip_slot INTEGER DEFAULT 0,
                    acquired_at INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS market (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    seller_id INTEGER NOT NULL,
                    inv_id INTEGER NOT NULL UNIQUE,
                    price INTEGER NOT NULL,
                    created_at INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS world_boss (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mob_id INTEGER NOT NULL,
                    max_hp INTEGER NOT NULL,
                    current_hp INTEGER NOT NULL,
                    active INTEGER DEFAULT 1,
                    created_at INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS world_boss_hits (
                    boss_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    damage REAL DEFAULT 0,
                    last_hit INTEGER DEFAULT 0,
                    PRIMARY KEY (boss_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );

                CREATE TABLE IF NOT EXISTS admin_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id INTEGER,
                    action TEXT,
                    created_at INTEGER
                );
                """
            )
            for k, v in DEFAULT_SETTINGS.items():
                await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
            await db.commit()

        await self.reload_settings()
        await self.seed_defaults()

    async def reload_settings(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT key, value FROM settings")
            for k, v in await cur.fetchall():
                GAME_SETTINGS[k] = str(v)

    async def set_setting(self, key: str, value: str) -> None:
        GAME_SETTINGS[key] = str(value)
        async with aiosqlite.connect(self.path) as db:
            await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
            await db.commit()

    async def seed_defaults(self) -> None:
        """Заполняет стартовых юнитов, мобов, карты и крейты, если база пуста."""
        async with aiosqlite.connect(self.path) as db:
            u_cnt = (await (await db.execute("SELECT COUNT(*) FROM units")).fetchone())[0]
            if u_cnt == 0:
                default_units = [
                    (
                        "Камерамен", "alliance", "common", ["Одиночный"], 40, 5, 16, 1.3,
                        1.0, 1.0, 0, 0, 0, 10, 0, 0, 0, 0, 0, 0,
                        {"2": {"cost": 70, "damage": 26, "cd": 1.15}, "3": {"cost": 140, "damage": 42, "cd": 1.0}},
                        "Надёжный стартовый стрелок Альянса.",
                    ),
                    (
                        "Спикермен-Отбойник", "alliance", "common", ["Сплеш", "Кнокбек"], 70, 4, 18, 1.8,
                        1.0, 1.0, 0, 0, 0, 10, 0, 0, 0, 0, 0, 4,
                        {"2": {"cost": 110, "damage": 30, "knockback_power": 6}, "3": {"cost": 210, "damage": 48, "knockback_power": 8}},
                        "Звуковой волной бьёт сплешем и отталкивает врагов (Кнокбек 4).",
                    ),
                    (
                        "Скибиди-Фермер", "skibidi", "rare", ["Ферма"], 90, 3, 0, 2.0,
                        1.0, 1.0, 45, 0, 0, 10, 0, 0, 0, 0, 0, 0,
                        {"2": {"cost": 150, "income": 95}, "3": {"cost": 300, "income": 180}},
                        "Приносит монеты в конце каждой волны.",
                    ),
                    (
                        "ТВ-Мен Замедлитель", "alliance", "rare", ["АОЕ", "Замедление"], 110, 3, 18, 2.0,
                        1.0, 1.0, 0, 25, 2, 10, 0, 0, 0, 0, 0, 0,
                        {"2": {"cost": 180, "damage": 32, "slow_percent": 35}, "3": {"cost": 340, "damage": 52, "slow_percent": 45}},
                        "Фиолетовый экран бьёт по площади и замедляет волну.",
                    ),
                    (
                        "Скибиди-Пироман", "skibidi", "epic", ["Сплеш", "Горение"], 140, 3, 30, 1.5,
                        1.0, 1.0, 0, 0, 0, 10, 0, 0, 45, 18, 3, 0,
                        {"2": {"cost": 240, "damage": 48, "burn_damage": 32}, "3": {"cost": 450, "damage": 75, "burn_damage": 55}},
                        "Поджигает врагов сплешем, нанося сильный урон горением.",
                    ),
                    (
                        "Скибиди-Учёный", "skibidi", "epic", ["Саппорт"], 150, 2, 0, 2.0,
                        0.85, 1.20, 0, 0, 0, 10, 0, 0, 0, 0, 0, 0,
                        {"2": {"cost": 260, "cd_boost": 0.78, "dmg_boost": 1.32}, "3": {"cost": 480, "cd_boost": 0.70, "dmg_boost": 1.45}},
                        "Ускоряет перезарядку и усиливает урон всех союзников на поле.",
                    ),
                    (
                        "Вантузмен-Глитч", "alliance", "legendary", ["Одиночный", "Оглушение"], 200, 3, 62, 1.1,
                        1.0, 1.0, 0, 0, 0, 10, 20, 1, 0, 0, 0, 0,
                        {"2": {"cost": 350, "damage": 105, "cd": 0.95}, "3": {"cost": 650, "damage": 165, "stun_chance": 30}},
                        "Молниеносные атаки с шансом оглушить цель.",
                    ),
                    (
                        "Заражённый Титан Спикермен", "infected", "mythic", ["АОЕ", "Кнокбек"], 320, 2, 85, 1.4,
                        1.0, 1.0, 0, 0, 0, 10, 0, 0, 0, 0, 0, 6,
                        {"2": {"cost": 520, "damage": 145, "knockback_power": 8}, "3": {"cost": 900, "damage": 230, "cd": 1.15}},
                        "Заражённый титан с плазменными пушками и отталкиванием!",
                    ),
                    (
                        "Заражённый Титан Камерамен", "infected", "mythic", ["Сплеш", "Горение", "Оглушение"], 380, 2, 115, 1.3,
                        1.0, 1.0, 0, 0, 0, 10, 18, 1, 35, 45, 3, 0,
                        {"2": {"cost": 620, "damage": 195, "burn_damage": 75}, "3": {"cost": 1100, "damage": 310, "cd": 1.05}},
                        "Тяжёлый заражённый титан с молотом и пламенем ядра.",
                    ),
                    (
                        "Заражённый G-Man 4.0", "infected", "secret", ["АОЕ", "Горение", "Кнокбек"], 480, 1, 160, 1.25,
                        1.0, 1.0, 0, 0, 0, 10, 0, 0, 50, 70, 3, 8,
                        {"2": {"cost": 800, "damage": 270, "knockback_power": 10}, "3": {"cost": 1450, "damage": 430, "cd": 1.0}},
                        "Секретный лидер Скибиди с лазерами и мощным кнокбеком!",
                    ),
                ]
                for u in default_units:
                    await db.execute(
                        """
                        INSERT INTO units (
                            name, faction, rarity, classes_json, deploy_cost, supply_limit,
                            damage, cd, cd_boost, dmg_boost, income,
                            slow_percent, slow_duration, slow_cd,
                            stun_chance, stun_duration,
                            burn_chance, burn_damage, burn_duration,
                            knockback_power, upgrades_json, description
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            u[0], u[1], u[2], json.dumps(u[3], ensure_ascii=False), u[4], u[5],
                            u[6], u[7], u[8], u[9], u[10],
                            u[11], u[12], u[13], u[14], u[15],
                            u[16], u[17], u[18], u[19], json.dumps(u[20], ensure_ascii=False), u[21],
                        ),
                    )
                await db.commit()

            m_cnt = (await (await db.execute("SELECT COUNT(*) FROM mobs")).fetchone())[0]
            if m_cnt == 0:
                async def uid_by_name(n: str) -> int:
                    r = await (await db.execute("SELECT id FROM units WHERE name = ?", (n,))).fetchone()
                    return r[0] if r else 0

                u_tsm = await uid_by_name("Заражённый Титан Спикермен")
                u_tcm = await uid_by_name("Заражённый Титан Камерамен")
                u_gman = await uid_by_name("Заражённый G-Man 4.0")

                default_mobs = [
                    ("Скибиди-Пехотинец", 90, 0, 0, 0, 0),
                    ("Бронированный Скибиди", 180, 25, 0, 0, 0),
                    ("Скибиди-Пильщик", 320, 15, 0, 0, 0),
                    ("Астро-Штурмовик", 520, 35, 0, 0, 0),
                    ("Титан Спикермен (Босс)", 1100, 15, 1, 2, u_tsm),
                    ("Титан Камерамен (Босс)", 2400, 25, 1, 1, u_tcm),
                    ("G-Man 4.0 (Босс)", 4800, 35, 1, 1, u_gman),
                ]
                for mob in default_mobs:
                    await db.execute(
                        "INSERT INTO mobs (name, hp, defense_percent, is_boss, infect_chance, infected_unit_id) VALUES (?, ?, ?, ?, ?, ?)",
                        mob,
                    )
                await db.commit()

            map_cnt = (await (await db.execute("SELECT COUNT(*) FROM maps")).fetchone())[0]
            if map_cnt == 0:
                async def mid_by_name(n: str) -> int:
                    r = await (await db.execute("SELECT id FROM mobs WHERE name = ?", (n,))).fetchone()
                    return r[0] if r else 1

                m1 = await mid_by_name("Скибиди-Пехотинец")
                m2 = await mid_by_name("Бронированный Скибиди")
                m3 = await mid_by_name("Скибиди-Пильщик")
                m4 = await mid_by_name("Астро-Штурмовик")
                b1 = await mid_by_name("Титан Спикермен (Босс)")
                b2 = await mid_by_name("Титан Камерамен (Босс)")
                b3 = await mid_by_name("G-Man 4.0 (Босс)")

                default_maps = [
                    (
                        "🏙 Город Альянса (🟢 Легко)", 120, 100, 220, 40,
                        [
                            {"turns": 5, "mobs": [{"id": m1, "count": 3}]},
                            {"turns": 6, "mobs": [{"id": m1, "count": 4}, {"id": m2, "count": 1}]},
                            {"turns": 6, "mobs": [{"id": m2, "count": 3}]},
                            {"turns": 7, "mobs": [{"id": m2, "count": 2}, {"id": m3, "count": 2}]},
                            {"turns": 9, "mobs": [{"id": b1, "count": 1}, {"id": m1, "count": 2}]},
                        ],
                    ),
                    (
                        "🧪 База Учёного (🟡 Средне)", 160, 100, 480, 75,
                        [
                            {"turns": 5, "mobs": [{"id": m1, "count": 5}, {"id": m2, "count": 2}]},
                            {"turns": 6, "mobs": [{"id": m2, "count": 4}]},
                            {"turns": 6, "mobs": [{"id": m3, "count": 3}, {"id": m2, "count": 2}]},
                            {"turns": 7, "mobs": [{"id": m3, "count": 4}, {"id": m4, "count": 1}]},
                            {"turns": 7, "mobs": [{"id": m4, "count": 3}]},
                            {"turns": 10, "mobs": [{"id": b2, "count": 1}, {"id": m2, "count": 3}]},
                        ],
                    ),
                    (
                        "🌌 Астро-Вторжение (🔴 Сложно)", 220, 100, 950, 140,
                        [
                            {"turns": 6, "mobs": [{"id": m2, "count": 5}, {"id": m3, "count": 2}]},
                            {"turns": 6, "mobs": [{"id": m3, "count": 5}]},
                            {"turns": 7, "mobs": [{"id": m4, "count": 4}, {"id": m3, "count": 2}]},
                            {"turns": 8, "mobs": [{"id": b1, "count": 1}, {"id": m4, "count": 3}]},
                            {"turns": 8, "mobs": [{"id": m4, "count": 6}]},
                            {"turns": 12, "mobs": [{"id": b3, "count": 1}, {"id": m4, "count": 3}]},
                        ],
                    ),
                ]
                for name, sc, bhp, wc, lc, waves in default_maps:
                    await db.execute(
                        "INSERT INTO maps (name, starting_coins, base_hp, win_coins, lose_coins, waves_json) VALUES (?, ?, ?, ?, ?, ?)",
                        (name, sc, bhp, wc, lc, json.dumps(waves)),
                    )
                await db.commit()

            cr_cnt = (await (await db.execute("SELECT COUNT(*) FROM crates")).fetchone())[0]
            if cr_cnt == 0:
                rows = await (await db.execute("SELECT id, rarity FROM units WHERE faction != 'infected'")).fetchall()
                w_basic = {}
                w_elite = {}
                map_w_basic = {"common": 55, "rare": 26, "epic": 12, "legendary": 5, "mythic": 2, "secret": 1}
                map_w_elite = {"common": 10, "rare": 28, "epic": 32, "legendary": 20, "mythic": 8, "secret": 2}
                for uid, rar in rows:
                    w_basic[str(uid)] = map_w_basic.get(rar, 10)
                    w_elite[str(uid)] = map_w_elite.get(rar, 10)
                if w_basic:
                    await db.execute(
                        "INSERT INTO crates (name, description, price, units_json, banners_json, current_banner, active) VALUES (?, ?, ?, ?, ?, 0, 1)",
                        ("📦 Базовый Крейт", "Отличный кейс для сбора стартовой колоды.", 200, json.dumps(w_basic), json.dumps([{"units": w_basic}])),
                    )
                    await db.execute(
                        "INSERT INTO crates (name, description, price, units_json, banners_json, current_banner, active) VALUES (?, ?, ?, ?, ?, 0, 1)",
                        ("💎 Элитный Крейт", "Высокий шанс на Эпических и Легендарных юнитов!", 650, json.dumps(w_elite), json.dumps([{"units": w_elite}])),
                    )
                    await db.commit()

    # -------------------- Пользователи --------------------

    async def ensure_user(self, user_id: int, username: Optional[str], full_name: str) -> Tuple[Dict[str, Any], bool]:
        uname = (username or "").lower()
        fname = full_name or "Игрок"
        is_new = False
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))).fetchone()
            if not row:
                is_new = True
                now = int(time.time())
                await db.execute(
                    "INSERT INTO users (user_id, username, full_name, created_at) VALUES (?, ?, ?, ?)",
                    (user_id, uname, fname, now),
                )
                starters = await (await db.execute("SELECT id FROM units WHERE rarity = 'common' ORDER BY id ASC LIMIT 2")).fetchall()
                for idx, st in enumerate(starters, 1):
                    await db.execute(
                        "INSERT INTO inventory (user_id, unit_id, level, xp, is_shiny, is_infected, equip_slot, acquired_at) VALUES (?, ?, 1, 0, 0, 0, ?, ?)",
                        (user_id, st["id"], idx, now),
                    )
                await db.commit()
                row = await (await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))).fetchone()
            elif row["username"] != uname or row["full_name"] != fname:
                await db.execute("UPDATE users SET username = ?, full_name = ? WHERE user_id = ?", (uname, fname, user_id))
                await db.commit()
            return dict(row), is_new

    async def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))).fetchone()
            return dict(row) if row else None

    async def find_user(self, query: str) -> Optional[Dict[str, Any]]:
        q = query.strip().lstrip("@").lower()
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            if q.isdigit():
                row = await (await db.execute("SELECT * FROM users WHERE user_id = ?", (int(q),))).fetchone()
            else:
                row = await (await db.execute("SELECT * FROM users WHERE LOWER(username) = ?", (q,))).fetchone()
            return dict(row) if row else None

    async def update_user(self, user_id: int, **kwargs: Any) -> None:
        if not kwargs:
            return
        cols = ", ".join(f"{k} = ?" for k in kwargs)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(f"UPDATE users SET {cols} WHERE user_id = ?", [*kwargs.values(), user_id])
            await db.commit()

    async def add_coins(self, user_id: int, delta: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE users SET coins = MAX(0, coins + ?) WHERE user_id = ?", (delta, user_id))
            await db.commit()

    async def add_parasite(self, user_id: int, p_key: str, delta: int) -> None:
        col = PARASITES_META[p_key][1]
        async with aiosqlite.connect(self.path) as db:
            await db.execute(f"UPDATE users SET {col} = MAX(0, {col} + ?) WHERE user_id = ?", (delta, user_id))
            await db.commit()

    async def get_all_active_user_ids(self) -> List[int]:
        async with aiosqlite.connect(self.path) as db:
            return [r[0] for r in await (await db.execute("SELECT user_id FROM users WHERE is_banned = 0")).fetchall()]

    # -------------------- Админы и Сигнеры --------------------

    async def is_admin(self, user_id: int) -> bool:
        if user_id == OWNER_ID:
            return True
        async with aiosqlite.connect(self.path) as db:
            return (await (await db.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))).fetchone()) is not None

    async def get_admin_perms(self, user_id: int) -> Dict[str, bool]:
        if user_id == OWNER_ID:
            return {k: True for k in ADMIN_PERMS}
        async with aiosqlite.connect(self.path) as db:
            row = await (await db.execute("SELECT perms_json FROM admins WHERE user_id = ?", (user_id,))).fetchone()
            if not row:
                return {k: False for k in ADMIN_PERMS}
            try:
                saved = json.loads(row[0] or "{}")
            except json.JSONDecodeError:
                saved = {}
            return {k: bool(saved.get(k, False)) for k in ADMIN_PERMS}

    async def has_perm(self, user_id: int, perm: str) -> bool:
        return (await self.get_admin_perms(user_id)).get(perm, False)

    async def get_signer_role(self, user_id: int) -> Optional[str]:
        if user_id == OWNER_ID or await self.has_perm(user_id, "sign_admin"):
            return "admin"
        async with aiosqlite.connect(self.path) as db:
            row = await (await db.execute("SELECT role FROM signers WHERE user_id = ?", (user_id,))).fetchone()
            return row[0] if row else None

    async def list_admins(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await (await db.execute(
                "SELECT a.user_id, u.username, u.full_name FROM admins a LEFT JOIN users u ON a.user_id = u.user_id ORDER BY a.added_at DESC"
            )).fetchall()
            return [dict(r) for r in rows]

    async def add_admin(self, target_id: int, added_by: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO admins (user_id, added_by, perms_json, added_at) VALUES (?, ?, ?, ?)",
                (target_id, added_by, json.dumps({k: False for k in ADMIN_PERMS}), int(time.time())),
            )
            await db.commit()

    async def toggle_admin_perm(self, target_id: int, perm: str) -> None:
        perms = await self.get_admin_perms(target_id)
        perms[perm] = not perms.get(perm, False)
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE admins SET perms_json = ? WHERE user_id = ?", (json.dumps(perms), target_id))
            await db.commit()

    async def remove_admin(self, target_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM admins WHERE user_id = ?", (target_id,))
            await db.commit()

    async def list_signers(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await (await db.execute(
                "SELECT s.user_id, s.role, u.username, u.full_name FROM signers s LEFT JOIN users u ON s.user_id = u.user_id"
            )).fetchall()
            return [dict(r) for r in rows]

    async def set_signer(self, target_id: int, role: str, added_by: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO signers (user_id, role, added_by, added_at) VALUES (?, ?, ?, ?)",
                (target_id, role, added_by, int(time.time())),
            )
            await db.commit()

    async def remove_signer(self, target_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM signers WHERE user_id = ?", (target_id,))
            await db.commit()

    async def log_admin(self, admin_id: int, action: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("INSERT INTO admin_logs (admin_id, action, created_at) VALUES (?, ?, ?)", (admin_id, action, int(time.time())))
            await db.commit()

    async def get_admin_logs(self, limit: int = 15) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await (await db.execute(
                "SELECT l.*, u.full_name FROM admin_logs l LEFT JOIN users u ON l.admin_id = u.user_id ORDER BY l.id DESC LIMIT ?",
                (limit,),
            )).fetchall()
            return [dict(r) for r in rows]

    # -------------------- Юниты --------------------

    def _hydrate_unit(self, row: aiosqlite.Row) -> Dict[str, Any]:
        d = dict(row)
        try:
            d["classes"] = json.loads(d.get("classes_json") or '["Одиночный"]')
        except json.JSONDecodeError:
            d["classes"] = ["Одиночный"]
        try:
            d["upgrades"] = json.loads(d.get("upgrades_json") or "{}")
        except json.JSONDecodeError:
            d["upgrades"] = {}
        return d

    async def list_units(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await (await db.execute("SELECT * FROM units ORDER BY id ASC")).fetchall()
            return [self._hydrate_unit(r) for r in rows]

    async def get_unit(self, unit_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute("SELECT * FROM units WHERE id = ?", (unit_id,))).fetchone()
            return self._hydrate_unit(row) if row else None

    async def create_unit(self, d: Dict[str, Any]) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                """
                INSERT INTO units (
                    name, faction, rarity, classes_json, deploy_cost, supply_limit,
                    damage, cd, cd_boost, dmg_boost, income,
                    slow_percent, slow_duration, slow_cd,
                    stun_chance, stun_duration, burn_chance, burn_damage, burn_duration,
                    knockback_power, upgrades_json, description, photo_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    d["name"], d.get("faction", "alliance"), d.get("rarity", "common"),
                    json.dumps(d.get("classes", ["Одиночный"]), ensure_ascii=False),
                    int(d.get("deploy_cost", 50)), int(d.get("supply_limit", 4)),
                    float(d.get("damage", 0)), float(d.get("cd", 1.5)),
                    float(d.get("cd_boost", 1.0)), float(d.get("dmg_boost", 1.0)),
                    int(d.get("income", 0)),
                    int(d.get("slow_percent", 0)), float(d.get("slow_duration", 0)), float(d.get("slow_cd", 10)),
                    int(d.get("stun_chance", 0)), int(d.get("stun_duration", 0)),
                    int(d.get("burn_chance", 0)), float(d.get("burn_damage", 0)), int(d.get("burn_duration", 0)),
                    float(d.get("knockback_power", 0)),
                    json.dumps(d.get("upgrades", {}), ensure_ascii=False),
                    d.get("description", ""), d.get("photo_id", ""),
                ),
            )
            await db.commit()
            return cur.lastrowid

    async def update_unit(self, unit_id: int, **kwargs: Any) -> None:
        if "classes" in kwargs:
            kwargs["classes_json"] = json.dumps(kwargs.pop("classes"), ensure_ascii=False)
        if "upgrades" in kwargs:
            kwargs["upgrades_json"] = json.dumps(kwargs.pop("upgrades"), ensure_ascii=False)
        if not kwargs:
            return
        cols = ", ".join(f"{k} = ?" for k in kwargs)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(f"UPDATE units SET {cols} WHERE id = ?", [*kwargs.values(), unit_id])
            await db.commit()

    async def delete_unit(self, unit_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM market WHERE inv_id IN (SELECT id FROM inventory WHERE unit_id = ?)", (unit_id,))
            await db.execute("DELETE FROM inventory WHERE unit_id = ?", (unit_id,))
            await db.execute("DELETE FROM units WHERE id = ?", (unit_id,))
            await db.commit()

    async def get_unit_exist_counts(self, unit_id: int) -> Tuple[int, int]:
        """Возвращает (всего существует у игроков, из них Shiny)."""
        async with aiosqlite.connect(self.path) as db:
            row = await (await db.execute(
                "SELECT COUNT(*), COALESCE(SUM(is_shiny), 0) FROM inventory WHERE unit_id = ? AND user_id != ?",
                (unit_id, OWNER_ID),
            )).fetchone()
            return (row[0] or 0, row[1] or 0) if row else (0, 0)

    # -------------------- Мобы --------------------

    async def list_mobs(self, only_bosses: bool = False) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            sql = "SELECT * FROM mobs" + (" WHERE is_boss = 1" if only_bosses else "") + " ORDER BY id ASC"
            return [dict(r) for r in await (await db.execute(sql)).fetchall()]

    async def get_mob(self, mob_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute("SELECT * FROM mobs WHERE id = ?", (mob_id,))).fetchone()
            return dict(row) if row else None

    async def create_mob(self, d: Dict[str, Any]) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "INSERT INTO mobs (name, hp, defense_percent, is_boss, infect_chance, infected_unit_id, photo_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    d["name"], int(d["hp"]), int(d.get("defense_percent", 0)),
                    int(d.get("is_boss", 0)), int(d.get("infect_chance", 0)),
                    int(d.get("infected_unit_id", 0)), d.get("photo_id", ""),
                ),
            )
            await db.commit()
            return cur.lastrowid

    async def update_mob(self, mob_id: int, **kwargs: Any) -> None:
        if not kwargs:
            return
        cols = ", ".join(f"{k} = ?" for k in kwargs)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(f"UPDATE mobs SET {cols} WHERE id = ?", [*kwargs.values(), mob_id])
            await db.commit()

    async def delete_mob(self, mob_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM mobs WHERE id = ?", (mob_id,))
            await db.commit()

    # -------------------- Карты и Волны --------------------

    def _hydrate_map(self, row: aiosqlite.Row) -> Dict[str, Any]:
        d = dict(row)
        try:
            d["waves"] = json.loads(d.get("waves_json") or "[]")
        except json.JSONDecodeError:
            d["waves"] = []
        return d

    async def list_maps(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await (await db.execute("SELECT * FROM maps ORDER BY id ASC")).fetchall()
            return [self._hydrate_map(r) for r in rows]

    async def get_map(self, map_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute("SELECT * FROM maps WHERE id = ?", (map_id,))).fetchone()
            return self._hydrate_map(row) if row else None

    async def create_map(self, d: Dict[str, Any]) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "INSERT INTO maps (name, photo_id, starting_coins, base_hp, waves_json, win_coins, lose_coins) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    d["name"], d.get("photo_id", ""), int(d.get("starting_coins", 120)),
                    int(d.get("base_hp", 100)), json.dumps(d.get("waves", [])),
                    int(d.get("win_coins", 200)), int(d.get("lose_coins", 30)),
                ),
            )
            await db.commit()
            return cur.lastrowid

    async def update_map(self, map_id: int, **kwargs: Any) -> None:
        if "waves" in kwargs:
            kwargs["waves_json"] = json.dumps(kwargs.pop("waves"))
        if not kwargs:
            return
        cols = ", ".join(f"{k} = ?" for k in kwargs)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(f"UPDATE maps SET {cols} WHERE id = ?", [*kwargs.values(), map_id])
            await db.commit()

    async def delete_map(self, map_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM maps WHERE id = ?", (map_id,))
            await db.commit()

    # -------------------- Крейты и Баннеры (из doorstdbot.py) --------------------

    def _hydrate_crate(self, row: aiosqlite.Row) -> Dict[str, Any]:
        d = dict(row)
        try:
            d["units"] = json.loads(d.get("units_json") or "{}")
        except json.JSONDecodeError:
            d["units"] = {}
        try:
            d["banners"] = json.loads(d.get("banners_json") or "[]")
        except json.JSONDecodeError:
            d["banners"] = []
        if not d["banners"]:
            d["banners"] = [{"units": d["units"]}]
        return d

    async def list_crates(self, only_active: bool = False) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            sql = "SELECT * FROM crates" + (" WHERE active = 1" if only_active else "") + " ORDER BY price ASC, id ASC"
            return [self._hydrate_crate(r) for r in await (await db.execute(sql)).fetchall()]

    async def get_crate(self, crate_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute("SELECT * FROM crates WHERE id = ?", (crate_id,))).fetchone()
            return self._hydrate_crate(row) if row else None

    async def create_crate(self, name: str, desc: str, price: int, photo_id: str, units: Dict[str, int]) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "INSERT INTO crates (name, description, price, photo_id, units_json, banners_json, current_banner, active) VALUES (?, ?, ?, ?, ?, ?, 0, 1)",
                (name, desc, price, photo_id, json.dumps(units), json.dumps([{"units": units}])),
            )
            await db.commit()
            return cur.lastrowid

    async def update_crate(self, crate_id: int, **kwargs: Any) -> None:
        if "units" in kwargs:
            kwargs["units_json"] = json.dumps(kwargs.pop("units"))
        if "banners" in kwargs:
            kwargs["banners_json"] = json.dumps(kwargs.pop("banners"))
        if not kwargs:
            return
        cols = ", ".join(f"{k} = ?" for k in kwargs)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(f"UPDATE crates SET {cols} WHERE id = ?", [*kwargs.values(), crate_id])
            await db.commit()

    async def delete_crate(self, crate_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM crates WHERE id = ?", (crate_id,))
            await db.commit()

    # -------------------- Инвентарь, Слоты и Уровни Юнитов --------------------

    async def give_unit(
        self,
        user_id: int,
        unit_id: int,
        is_shiny: int = 0,
        is_infected: int = 0,
        sign_type: str = "none",
        signed_by: str = "",
    ) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                """
                INSERT INTO inventory (
                    user_id, unit_id, level, xp, is_shiny, is_infected,
                    sign_type, signed_by, equip_slot, acquired_at
                ) VALUES (?, ?, 1, 0, ?, ?, ?, ?, 0, ?)
                """,
                (user_id, unit_id, is_shiny, is_infected, sign_type, signed_by, int(time.time())),
            )
            await db.commit()
            return cur.lastrowid

    def _hydrate_inv(self, row: aiosqlite.Row) -> Dict[str, Any]:
        d = dict(row)
        try:
            d["classes"] = json.loads(d.get("classes_json") or '["Одиночный"]')
        except json.JSONDecodeError:
            d["classes"] = ["Одиночный"]
        try:
            d["upgrades"] = json.loads(d.get("upgrades_json") or "{}")
        except json.JSONDecodeError:
            d["upgrades"] = {}
        return d

    async def get_inventory(self, user_id: int, only_equipped: bool = False) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            where = "i.user_id = ?" + (" AND i.equip_slot > 0" if only_equipped else "")
            order = "i.equip_slot ASC" if only_equipped else "i.equip_slot DESC, i.is_shiny DESC, i.is_infected DESC, i.level DESC, i.id ASC"
            rows = await (await db.execute(
                f"""
                SELECT i.id AS inv_id, i.user_id, i.unit_id, i.level, i.xp,
                       i.is_shiny, i.is_infected, i.sign_type, i.signed_by, i.equip_slot,
                       u.name, u.faction, u.rarity, u.classes_json, u.deploy_cost, u.supply_limit,
                       u.damage, u.cd, u.cd_boost, u.dmg_boost, u.income,
                       u.slow_percent, u.slow_duration, u.slow_cd,
                       u.stun_chance, u.stun_duration, u.burn_chance, u.burn_damage, u.burn_duration,
                       u.knockback_power, u.upgrades_json, u.description, u.photo_id,
                       (SELECT m.id FROM market m WHERE m.inv_id = i.id) AS market_id
                FROM inventory i
                JOIN units u ON i.unit_id = u.id
                WHERE {where}
                ORDER BY {order}
                """,
                (user_id,),
            )).fetchall()
            return [self._hydrate_inv(r) for r in rows]

    async def get_inv_item(self, inv_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute(
                """
                SELECT i.id AS inv_id, i.user_id, i.unit_id, i.level, i.xp,
                       i.is_shiny, i.is_infected, i.sign_type, i.signed_by, i.equip_slot,
                       u.name, u.faction, u.rarity, u.classes_json, u.deploy_cost, u.supply_limit,
                       u.damage, u.cd, u.cd_boost, u.dmg_boost, u.income,
                       u.slow_percent, u.slow_duration, u.slow_cd,
                       u.stun_chance, u.stun_duration, u.burn_chance, u.burn_damage, u.burn_duration,
                       u.knockback_power, u.upgrades_json, u.description, u.photo_id,
                       (SELECT m.id FROM market m WHERE m.inv_id = i.id) AS market_id
                FROM inventory i
                JOIN units u ON i.unit_id = u.id
                WHERE i.id = ?
                """,
                (inv_id,),
            )).fetchone()
            return self._hydrate_inv(row) if row else None

    async def set_equip_slot(self, user_id: int, inv_id: int, slot: int) -> None:
        """Назначает юнита в конкретный слот 1..5 (или 0 для снятия)."""
        async with aiosqlite.connect(self.path) as db:
            if slot > 0:
                await db.execute("UPDATE inventory SET equip_slot = 0 WHERE user_id = ? AND equip_slot = ?", (user_id, slot))
            await db.execute("UPDATE inventory SET equip_slot = ? WHERE id = ? AND user_id = ?", (slot, inv_id, user_id))
            await db.commit()

    async def clear_equip(self, user_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE inventory SET equip_slot = 0 WHERE user_id = ?", (user_id,))
            await db.commit()

    async def update_inv_progress(self, inv_id: int, level: int, xp: float) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE inventory SET level = ?, xp = ? WHERE id = ?", (level, xp, inv_id))
            await db.commit()

    async def sign_inv_item(self, inv_id: int, sign_type: str, signed_by: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE inventory SET sign_type = ?, signed_by = ? WHERE id = ?", (sign_type, signed_by, inv_id))
            await db.commit()

    # -------------------- P2P Рынок (80% продавцу, 20% владельцу) --------------------

    async def list_market(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await (await db.execute(
                """
                SELECT m.id AS market_id, m.seller_id, m.inv_id, m.price,
                       i.level, i.xp, i.is_shiny, i.is_infected, i.sign_type, i.signed_by,
                       u.name, u.faction, u.rarity, u.classes_json, u.deploy_cost, u.supply_limit,
                       u.damage, u.cd, u.cd_boost, u.dmg_boost, u.income,
                       u.slow_percent, u.slow_duration, u.slow_cd,
                       u.stun_chance, u.stun_duration, u.burn_chance, u.burn_damage, u.burn_duration,
                       u.knockback_power, u.upgrades_json, u.photo_id,
                       us.username AS seller_username, us.full_name AS seller_name
                FROM market m
                JOIN inventory i ON m.inv_id = i.id
                JOIN units u ON i.unit_id = u.id
                LEFT JOIN users us ON m.seller_id = us.user_id
                ORDER BY m.id DESC
                """
            )).fetchall()
            return [self._hydrate_inv(r) for r in rows]

    async def create_market_lot(self, seller_id: int, inv_id: int, price: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE inventory SET equip_slot = 0 WHERE id = ?", (inv_id,))
            await db.execute(
                "INSERT INTO market (seller_id, inv_id, price, created_at) VALUES (?, ?, ?, ?)",
                (seller_id, inv_id, price, int(time.time())),
            )
            await db.commit()

    async def buy_market_lot(self, market_id: int, buyer_id: int) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            lot = await (await db.execute(
                """
                SELECT m.*, i.unit_id, i.level, i.is_shiny, i.is_infected, u.name
                FROM market m
                JOIN inventory i ON m.inv_id = i.id
                JOIN units u ON i.unit_id = u.id
                WHERE m.id = ?
                """,
                (market_id,),
            )).fetchone()
            if not lot:
                return False, "Лот уже куплен или снят.", None
            if lot["seller_id"] == buyer_id:
                return False, "Нельзя купить свой собственный лот.", None

            buyer = await (await db.execute("SELECT coins FROM users WHERE user_id = ?", (buyer_id,))).fetchone()
            if not buyer or buyer["coins"] < lot["price"]:
                return False, f"Недостаточно монет! Нужно {lot['price']} 💰.", None

            price = lot["price"]
            seller_payout = int(price * (100 - MARKET_COMMISSION_PCT) / 100)
            commission = price - seller_payout

            await db.execute("UPDATE users SET coins = coins - ? WHERE user_id = ?", (price, buyer_id))
            await db.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (seller_payout, lot["seller_id"]))
            # 20% комиссия зачисляется владельцу бота (OWNER_ID)
            await db.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (commission, OWNER_ID))
            await db.execute("UPDATE inventory SET user_id = ?, equip_slot = 0 WHERE id = ?", (buyer_id, lot["inv_id"]))
            await db.execute("DELETE FROM market WHERE id = ?", (market_id,))
            await db.commit()

            res = dict(lot)
            res["seller_payout"] = seller_payout
            res["commission"] = commission
            return True, "Покупка успешна!", res

    async def cancel_market_lot(self, market_id: int, seller_id: int) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("DELETE FROM market WHERE id = ? AND seller_id = ?", (market_id, seller_id))
            await db.commit()
            return cur.rowcount > 0

    # -------------------- Мировой Босс --------------------

    async def get_active_world_boss(self) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute(
                """
                SELECT wb.*, m.name, m.defense_percent, m.infect_chance, m.infected_unit_id, m.photo_id
                FROM world_boss wb
                JOIN mobs m ON wb.mob_id = m.id
                WHERE wb.active = 1
                ORDER BY wb.id DESC LIMIT 1
                """
            )).fetchone()
            return dict(row) if row else None

    async def spawn_world_boss(self, mob_id: int, max_hp: int) -> int:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE world_boss SET active = 0 WHERE active = 1")
            cur = await db.execute(
                "INSERT INTO world_boss (mob_id, max_hp, current_hp, active, created_at) VALUES (?, ?, ?, 1, ?)",
                (mob_id, max_hp, max_hp, int(time.time())),
            )
            await db.commit()
            return cur.lastrowid

    async def get_world_boss_hit(self, boss_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute("SELECT * FROM world_boss_hits WHERE boss_id = ? AND user_id = ?", (boss_id, user_id))).fetchone()
            return dict(row) if row else None

    async def hit_world_boss(self, boss_id: int, user_id: int, damage: float) -> int:
        now = int(time.time())
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO world_boss_hits (boss_id, user_id, damage, last_hit) VALUES (?, ?, ?, ?)
                ON CONFLICT(boss_id, user_id) DO UPDATE SET damage = damage + excluded.damage, last_hit = excluded.last_hit
                """,
                (boss_id, user_id, damage, now),
            )
            await db.execute("UPDATE world_boss SET current_hp = MAX(0, current_hp - ?) WHERE id = ?", (int(damage), boss_id))
            rem = (await (await db.execute("SELECT current_hp FROM world_boss WHERE id = ?", (boss_id,))).fetchone())[0]
            if rem <= 0:
                await db.execute("UPDATE world_boss SET active = 0 WHERE id = ?", (boss_id,))
            await db.commit()
            return rem

    async def get_world_boss_top(self, boss_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await (await db.execute(
                "SELECT h.user_id, h.damage, u.username, u.full_name FROM world_boss_hits h LEFT JOIN users u ON h.user_id = u.user_id WHERE h.boss_id = ? ORDER BY h.damage DESC LIMIT ?",
                (boss_id, limit),
            )).fetchall()
            return [dict(r) for r in rows]

    async def stop_world_boss(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE world_boss SET active = 0 WHERE active = 1")
            await db.commit()

    # -------------------- Топы и Глобальная статистика --------------------

    async def get_leaderboard(self, column: str, limit: int = 10) -> List[Dict[str, Any]]:
        allowed = {"wins", "coins", "infections_success", "bosses_killed", "total_damage"}
        col = column if column in allowed else "wins"
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await (await db.execute(
                f"SELECT user_id, username, full_name, {col} AS val FROM users WHERE is_banned = 0 ORDER BY {col} DESC LIMIT ?",
                (limit,),
            )).fetchall()
            return [dict(r) for r in rows]

    async def get_global_stats(self) -> Dict[str, int]:
        async with aiosqlite.connect(self.path) as db:
            return {
                "users": (await (await db.execute("SELECT COUNT(*) FROM users")).fetchone())[0],
                "units": (await (await db.execute("SELECT COUNT(*) FROM units")).fetchone())[0],
                "mobs": (await (await db.execute("SELECT COUNT(*) FROM mobs")).fetchone())[0],
                "maps": (await (await db.execute("SELECT COUNT(*) FROM maps")).fetchone())[0],
                "crates": (await (await db.execute("SELECT COUNT(*) FROM crates")).fetchone())[0],
                "market": (await (await db.execute("SELECT COUNT(*) FROM market")).fetchone())[0],
            }


db = Database(DB_PATH)


# ==============================================================================
# 3. МАТЕМАТИКА СТАТОВ ЮНИТОВ, СИГН, SHINY, ИНФЕКТЕД И PILLOW-РЕНДЕР
# ==============================================================================

def esc(v: Any) -> str:
    return html.escape(str(v or ""))


def format_user_link(user: Dict[str, Any]) -> str:
    name = esc(user.get("full_name") or "Игрок")
    uname = user.get("username")
    return f"<b>{name}</b> (@{esc(uname)})" if uname else f"<b>{name}</b> [<code>{user.get('user_id')}</code>]"


def make_bar(cur: float, mx: float, length: int = 10, fill: str = "🟩", empty: str = "⬜") -> str:
    if mx <= 0:
        return fill * length
    r = max(0.0, min(1.0, cur / mx))
    f = int(round(r * length))
    return fill * f + empty * (length - f)


def roll_shiny() -> int:
    chance = min(100.0, cfg_float("shiny_chance_pct") * cfg_float("event_luck_mult"))
    return 1 if (random.random() * 100.0) < chance else 0


def get_sign_discount_pct(sign_type: str) -> int:
    if sign_type == "admin":
        return cfg_int("admin_sign_disc_pct")
    if sign_type == "partner":
        return cfg_int("partner_sign_disc_pct")
    return 0


def get_sign_label(item: Dict[str, Any]) -> str:
    st = item.get("sign_type", "none")
    if st == "none":
        return "Нет"
    disc = get_sign_discount_pct(st)
    role = "👑 Админ-сигна" if st == "admin" else "🤝 Партнёр-сигна"
    who = f" от {esc(item.get('signed_by'))}" if item.get("signed_by") else ""
    return f"{role} (-{disc}% цена/прокачка{who})"


def calc_unit_battle_stats(item: Dict[str, Any], tier: int = 1) -> Dict[str, Any]:
    """
    Рассчитывает точные боевые параметры юнита на конкретном тире в катке (1..N) с учётом:
    - Тира апгрейда в бою (из upgrades_json)
    - Постоянного уровня юнита за урон (1..50, +0.5% к урону за каждый уровень свыше 1)
    - Мутации ✨ Shiny (+25% к урону/доходу/эффектам)
    - Заражения 🦠 Инфектед (x1.20 к урону, настраивается в Админке)
    - Сигны (-10% или -20% к цене поставки и прокачки в катке!)
    """
    st = {
        "name": item["name"],
        "classes": list(item.get("classes") or ["Одиночный"]),
        "deploy_cost": int(item.get("deploy_cost", 50)),
        "supply_limit": int(item.get("supply_limit", 4)),
        "damage": float(item.get("damage", 0)),
        "cd": max(0.15, float(item.get("cd", 1.5))),
        "cd_boost": float(item.get("cd_boost", 1.0)),
        "dmg_boost": float(item.get("dmg_boost", 1.0)),
        "income": int(item.get("income", 0)),
        "slow_percent": int(item.get("slow_percent", 0)),
        "slow_duration": float(item.get("slow_duration", 0)),
        "slow_cd": float(item.get("slow_cd", 10)),
        "stun_chance": int(item.get("stun_chance", 0)),
        "stun_duration": int(item.get("stun_duration", 0)),
        "burn_chance": int(item.get("burn_chance", 0)),
        "burn_damage": float(item.get("burn_damage", 0)),
        "burn_duration": int(item.get("burn_duration", 0)),
        "knockback_power": float(item.get("knockback_power", 0)),
    }

    upgrades = item.get("upgrades") or {}
    for t in range(2, tier + 1):
        u = upgrades.get(str(t))
        if not u:
            continue
        for k in (
            "damage", "cd", "cd_boost", "dmg_boost", "income",
            "slow_percent", "slow_duration", "slow_cd",
            "stun_chance", "stun_duration", "burn_chance", "burn_damage", "burn_duration",
            "knockback_power",
        ):
            if u.get(k) is not None:
                st[k] = u[k]

    # Постоянный уровень юнита (1..50): +0.5% к урону за каждый уровень
    lvl = max(1, min(MAX_UNIT_LEVEL, int(item.get("level", 1))))
    lvl_dmg_mult = 1.0 + ((lvl - 1) * UNIT_DMG_PCT_PER_LEVEL / 100.0)

    is_shiny = bool(item.get("is_shiny"))
    shiny_mult = (1.0 + cfg_float("shiny_bonus_pct") / 100.0) if is_shiny else 1.0

    is_infected = bool(item.get("is_infected"))
    inf_mult = cfg_float("infected_mult") if is_infected else 1.0

    st["damage"] = round(st["damage"] * lvl_dmg_mult * shiny_mult * inf_mult, 1)
    st["burn_damage"] = round(st["burn_damage"] * lvl_dmg_mult * shiny_mult * inf_mult, 1)
    if is_shiny:
        st["income"] = int(st["income"] * (1.0 + cfg_float("shiny_bonus_pct") / 200.0))
        if st["slow_percent"] > 0:
            st["slow_percent"] = min(80, st["slow_percent"] + 5)
        if st["stun_chance"] > 0:
            st["stun_chance"] = min(80, st["stun_chance"] + 5)

    # Сигны уменьшают стоимость поставки и апгрейдов в катке
    disc_pct = get_sign_discount_pct(item.get("sign_type", "none"))
    st["sign_disc_pct"] = disc_pct
    st["deploy_cost"] = max(1, int(round(st["deploy_cost"] * (1.0 - disc_pct / 100.0))))

    # Подсчёт DPS
    has_atk = any(c in ATTACKING_CLASSES for c in st["classes"])
    st["dps"] = round(st["damage"] / st["cd"], 1) if (has_atk and st["damage"] > 0) else 0.0
    st["lvl_bonus_pct"] = round((lvl - 1) * UNIT_DMG_PCT_PER_LEVEL, 1)
    return st


def get_tier_upgrade_cost(item: Dict[str, Any], next_tier: int) -> Optional[int]:
    upg = (item.get("upgrades") or {}).get(str(next_tier))
    if not upg:
        return None
    base_cost = int(upg.get("cost", 100))
    disc_pct = get_sign_discount_pct(item.get("sign_type", "none"))
    return max(1, int(round(base_cost * (1.0 - disc_pct / 100.0))))


def unit_badges(item: Dict[str, Any]) -> str:
    b = ""
    if item.get("is_shiny"):
        b += "✨"
    if item.get("is_infected"):
        b += "🦠"
    if item.get("sign_type") == "admin":
        b += "👑"
    elif item.get("sign_type") == "partner":
        b += "🤝"
    return b


def format_unit_info_card(
    item: Dict[str, Any],
    exist_total: int = 0,
    exist_shiny: int = 0,
    show_upgrades: bool = False,
) -> str:
    """Улучшенная карточка «Инфо о юните»: чистая структура, DPS, XP-шкала, кнокбек и таблица тиров."""
    r_name, r_ico, _ = RARITIES.get(item["rarity"], ("Обычный", "⚪️", 1))
    f_name = FACTIONS.get(item.get("faction", "alliance"), "📷 Альянс")
    st = calc_unit_battle_stats(item, tier=1)
    badges = unit_badges(item)
    lvl = int(item.get("level", 1))
    xp = float(item.get("xp", 0.0))
    need_xp = xp_required_for_level(lvl)

    if show_upgrades:
        upgrades = item.get("upgrades") or {}
        lines = [
            f"{r_ico} <b>{esc(item['name'])}</b> {badges} — <b>Апгрейды в катке</b>",
            f"<i>Скидка от сигны: -{st['sign_disc_pct']}%</i>" if st["sign_disc_pct"] else "<i>Скидка от сигны: нет</i>",
            "━━━━━━━━━━━━━━━━━━",
            f"🔹 <b>Тир 1 (База)</b> | 💰 Поставка: <b>{st['deploy_cost']}</b>",
        ]
        if st["damage"] > 0:
            lines.append(f"   └ ⚔️ {st['damage']} | ⏱ {st['cd']}с | ⚡ DPS: <b>{st['dps']}/с</b>")
        if "Ферма" in st["classes"]:
            lines.append(f"   └ 🌾 Доход: <b>+{st['income']}/волна</b>")
        if "Саппорт" in st["classes"]:
            lines.append(f"   └ ✨ Бафф: КД x{st['cd_boost']} | Урон x{st['dmg_boost']}")
        if "Кнокбек" in st["classes"] and st["knockback_power"] > 0:
            lines.append(f"   └ 💨 Кнокбек: <b>{st['knockback_power']}</b>")

        if not upgrades:
            lines.append("\n<i>Дополнительные тиры прокачки не настроены.</i>")
        else:
            for t_str in sorted(upgrades.keys(), key=lambda x: int(x)):
                t_num = int(t_str)
                ts = calc_unit_battle_stats(item, tier=t_num)
                cost = get_tier_upgrade_cost(item, t_num)
                lines.append(f"\n⬆️ <b>Тир {t_num}</b> | 💰 Апгрейд: <b>{cost}</b>")
                if ts["damage"] > 0:
                    lines.append(f"   └ ⚔️ {ts['damage']} | ⏱ {ts['cd']}с | ⚡ DPS: <b>{ts['dps']}/с</b>")
                if "Ферма" in ts["classes"]:
                    lines.append(f"   └ 🌾 Доход: <b>+{ts['income']}/волна</b>")
                if "Саппорт" in ts["classes"]:
                    lines.append(f"   └ ✨ Бафф: КД x{ts['cd_boost']} | Урон x{ts['dmg_boost']}")
                if "Кнокбек" in ts["classes"] and ts["knockback_power"] > 0:
                    lines.append(f"   └ 💨 Кнокбек: <b>{ts['knockback_power']}</b>")
                if "Замедление" in ts["classes"] and ts["slow_percent"] > 0:
                    lines.append(f"   └ ❄️ Замедление: <b>-{ts['slow_percent']}%</b> ({ts['slow_duration']}х)")
                if "Горение" in ts["classes"] and ts["burn_damage"] > 0:
                    lines.append(f"   └ 🔥 Горение: {ts['burn_chance']}% | {ts['burn_damage']}/х ({ts['burn_duration']}х)")
                if "Оглушение" in ts["classes"] and ts["stun_chance"] > 0:
                    lines.append(f"   └ ⚡ Стан: {ts['stun_chance']}% ({ts['stun_duration']}х)")
        return "\n".join(lines)

    xp_line = (
        f"⭐ Ур. <b>{lvl}/{MAX_UNIT_LEVEL}</b> (MAX | <b>+{st['lvl_bonus_pct']}%</b> урон)"
        if lvl >= MAX_UNIT_LEVEL
        else f"⭐ Ур. <b>{lvl}/{MAX_UNIT_LEVEL}</b> (<b>+{st['lvl_bonus_pct']}%</b> урон)\n"
             f"   {make_bar(xp, need_xp, 8)} {xp:.1f}/{need_xp:.0f} XP"
    )

    slot_txt = f"✅ Надет в <b>Слот #{item['equip_slot']}</b>" if item.get("equip_slot", 0) > 0 else "📦 В инвентаре"
    if item.get("market_id"):
        slot_txt = "🏷 Выставлен на P2P-рынке"

    base_cost = int(item.get("deploy_cost", 50))
    cost_str = (
        f"<s>{base_cost}</s> <b>{st['deploy_cost']}</b> (-{st['sign_disc_pct']}%)"
        if st["sign_disc_pct"] > 0
        else f"<b>{st['deploy_cost']}</b>"
    )

    lines = [
        f"{r_ico} <b>{esc(item['name'])}</b> {badges}",
        f"Фракция: {f_name} | Редкость: <b>{r_name}</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"🏷 Классы: <b>{', '.join(st['classes'])}</b>",
        f"💰 Поставка: {cost_str} | 🛑 Лимит на поле: <b>{st['supply_limit']} шт.</b>",
        f"📌 Статус: {slot_txt}",
        "",
        f"📈 <b>ПРОГРЕСС ЮНИТА (1 урон = 0.1 XP):</b>",
        xp_line,
        "",
        "⚔️ <b>БОЕВЫЕ ХАРАКТЕРИСТИКИ (Тир 1):</b>",
    ]
    if st["damage"] > 0:
        lines.append(f"• ⚔️ Урон: <b>{st['damage']}</b> | ⏱ КД: <b>{st['cd']}с</b> | ⚡ DPS: <b>{st['dps']}/с</b>")
    if "Ферма" in st["classes"]:
        lines.append(f"• 🌾 Ферма: <b>+{st['income']} 💰 / волна</b>")
    if "Саппорт" in st["classes"]:
        lines.append(f"• ✨ Саппорт: КД <b>x{st['cd_boost']}</b> | Урон <b>x{st['dmg_boost']}</b>")
    if "Кнокбек" in st["classes"] and st["knockback_power"] > 0:
        lines.append(f"• 💨 Кнокбек: <b>{st['knockback_power']}</b> (отталкивает врага назад по волне)")
    if "Замедление" in st["classes"] and st["slow_percent"] > 0:
        lines.append(f"• ❄️ Замедление: <b>-{st['slow_percent']}%</b> на {st['slow_duration']}х (КД {st['slow_cd']}с)")
    if "Оглушение" in st["classes"] and st["stun_chance"] > 0:
        lines.append(f"• ⚡ Оглушение: <b>{st['stun_chance']}%</b> на {st['stun_duration']}х")
    if "Горение" in st["classes"] and st["burn_damage"] > 0:
        lines.append(f"• 🔥 Горение: <b>{st['burn_chance']}%</b> | {st['burn_damage']}/х на {st['burn_duration']}х")

    shiny_txt = f"✨ Shiny (+{cfg_int('shiny_bonus_pct')}%)" if item.get("is_shiny") else "Обычная"
    inf_txt = f"🦠 Инфектед (x{cfg_float('infected_mult')})" if item.get("is_infected") else "Нет"
    lines.extend([
        "",
        "✨ <b>МОДИФИКАТОРЫ:</b>",
        f"• Мутация: <b>{shiny_txt}</b> | Заражение: <b>{inf_txt}</b>",
        f"• Сигна: {get_sign_label(item)}",
        f"• 🌍 Существует у игроков: <b>{exist_total}</b> шт. (✨ Shiny: <b>{exist_shiny}</b>)",
    ])
    if item.get("description"):
        lines.append(f"\n📝 <i>{esc(item['description'])}</i>")
    return "\n".join(lines)


def _draw_battle_image_sync(
    img_bytes: bytes, total_hp: int, wave: int, total_waves: int, turn: int, total_turns: int, slow_pct: int = 0
) -> Optional[bytes]:
    """Рисует сводку волны поверх фона карты/моба с помощью Pillow."""
    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
        draw = ImageDraw.Draw(img)
        font_size = max(18, img.height // 12)
        font = None
        if os.path.exists(FONT_FILE):
            try:
                font = ImageFont.truetype(FONT_FILE, size=font_size)
            except Exception:
                pass
        if not font:
            font = ImageFont.load_default()

        def draw_label(txt: str, pos: Tuple[int, int], anchor_y: str = "center", fill: str = "white") -> None:
            bbox = draw.textbbox((0, 0), txt, font=font)
            w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
            x = pos[0] - w / 2
            y = pos[1] if anchor_y == "top" else (pos[1] - h / 2 if anchor_y == "center" else pos[1] - h)
            for dx in (-2, -1, 0, 1, 2):
                for dy in (-2, -1, 0, 1, 2):
                    if dx or dy:
                        draw.text((x + dx, y + dy), txt, font=font, fill="black")
            draw.text((x, y), txt, font=font, fill=fill)

        draw_label(f"HP врагов: {total_hp}", (img.width // 2, 10), "top", "#FFEEEE")
        draw_label(f"Волна: {wave}/{total_waves}", (img.width // 2, img.height // 2), "center", "#FFFFFF")
        draw_label(f"Ход: {turn}/{total_turns}", (img.width // 2, img.height - 10), "bottom", "#FFFFCC")
        if slow_pct > 0:
            draw_label(f"Замедление: -{slow_pct}%", (img.width // 2, img.height // 4), "center", "#00FFFF")

        out = io.BytesIO()
        img.convert("RGB").save(out, format="JPEG", quality=80, optimize=True)
        return out.getvalue()
    except Exception:
        return None


# ==============================================================================
# 4. УНИВЕРСАЛЬНЫЙ UI-РЕНДЕР И MIDDLEWARE
# ==============================================================================

async def render_view(
    target: Message | CallbackQuery,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    photo: Optional[str] = None,
) -> None:
    if isinstance(target, Message):
        if photo:
            try:
                await target.answer_photo(photo=photo, caption=text[:1024], reply_markup=reply_markup)
                return
            except TelegramBadRequest:
                pass
        await target.answer(text[:4096], reply_markup=reply_markup)
        return

    msg = target.message
    if not msg:
        return
    has_photo = bool(msg.photo)
    try:
        if photo:
            if has_photo:
                await msg.edit_caption(caption=text[:1024], reply_markup=reply_markup)
            else:
                try:
                    await msg.delete()
                except TelegramBadRequest:
                    pass
                await msg.answer_photo(photo=photo, caption=text[:1024], reply_markup=reply_markup)
        else:
            if has_photo:
                try:
                    await msg.delete()
                except TelegramBadRequest:
                    pass
                await msg.answer(text[:4096], reply_markup=reply_markup)
            else:
                await msg.edit_text(text[:4096], reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return
        try:
            await msg.answer(text[:4096], reply_markup=reply_markup)
        except Exception:
            pass


def main_reply_kb(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="⚔️ Играть (Катки)"), KeyboardButton(text="🃏 Колода и Юниты")],
        [KeyboardButton(text="📦 Крейты и Лаба"), KeyboardButton(text="🌐 Мультиплеер")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🏆 Рейтинг")],
    ]
    if is_admin:
        rows.append([KeyboardButton(text="⚙️ Админ-панель")])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Выберите раздел в меню...",
    )


class AccessMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user") or getattr(event, "from_user", None)
        if tg_user and not tg_user.is_bot:
            user, _ = await db.ensure_user(tg_user.id, tg_user.username, tg_user.full_name)
            is_adm = await db.is_admin(tg_user.id)
            if user["is_banned"] and not is_adm:
                if isinstance(event, Message):
                    await event.answer("🚫 Ваш аккаунт заблокирован.")
                elif isinstance(event, CallbackQuery):
                    await event.answer("🚫 Вы заблокированы.", show_alert=True)
                return
            if GAME_SETTINGS.get("maintenance", "0") == "1" and not is_adm:
                if isinstance(event, Message):
                    await event.answer("🛠 <b>Технические работы!</b> Бот скоро вернётся.")
                elif isinstance(event, CallbackQuery):
                    await event.answer("🛠 Идут техработы.", show_alert=True)
                return
            data["db_user"] = user
            data["is_admin"] = is_adm
        return await handler(event, data)


# ==============================================================================
# 5. FSM СОСТОЯНИЯ
# ==============================================================================

class PlayerFSM(StatesGroup):
    profile_search = State()
    market_price = State()


class UnitCreateFSM(StatesGroup):
    classes = State()
    name = State()
    faction = State()
    rarity = State()
    photo = State()
    deploy_cost = State()
    supply_limit = State()
    atk_stats = State()
    support_stats = State()
    farm_income = State()
    slow_stats = State()
    stun_stats = State()
    burn_stats = State()
    knockback_power = State()
    description = State()


class UnitEditFSM(StatesGroup):
    waiting_value = State()
    upg_tier = State()
    upg_data = State()


class MobCreateFSM(StatesGroup):
    name = State()
    hp = State()
    defense = State()
    photo = State()
    is_boss = State()
    infect_cfg = State()


class MobEditFSM(StatesGroup):
    waiting_value = State()


class MapCreateFSM(StatesGroup):
    name = State()
    photo = State()
    rewards = State()
    wave_builder = State()
    mob_count = State()
    wave_turns = State()


class MapWaveEditFSM(StatesGroup):
    mob_count = State()
    wave_turns = State()
    map_field = State()


class CrateFSM(StatesGroup):
    name = State()
    desc = State()
    price = State()
    photo = State()
    builder = State()
    weight = State()
    edit_field = State()


class AdminFSM(StatesGroup):
    add_admin = State()
    add_signer = State()
    find_user = State()
    user_coins = State()
    broadcast = State()
    wb_hp = State()
    setting_val = State()


# ==============================================================================
# 6. ОСНОВНОЙ РОУТЕР: СТАРТ, ПРОФИЛЬ, ЭКИПИРОВКА 2.0, ИНФО О ЮНИТЕ
# ==============================================================================

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, is_admin: bool):
    await state.clear()
    _, is_new = await db.ensure_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    gift = "\n\n🎁 <b>Стартовый набор:</b> 2 юнита в колоде, 400 💰 и 2 🦠 паразита!" if is_new else ""
    text = (
        f"🚽 <b>Skibidi Verse Tower Defense</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"• Создавай <b>TD-катки (Соло или Кооп 1–4)</b>, расставляй юнитов и отбивай волны!\n"
        f"• Добивай <b>Боссов</b> в конце карты и запускай паразитов, чтобы получить <b>🦠 Инфектед</b> юнита.\n"
        f"• Качай юнитов в боях: <b>1 урон = 0.1 XP</b>, до <b>50 ур.</b> (+0.5% урона за уровень)!\n"
        f"• Лови <b>✨ Shiny</b> ({cfg_float('shiny_chance_pct')}%) и торгуй на <b>P2P-рынке</b>.{gift}\n\n"
        f"👇 Выбирай раздел в меню снизу."
    )
    await message.answer(text, reply_markup=main_reply_kb(is_admin))


@router.message(Command("panel"))
async def cmd_panel(message: Message, state: FSMContext, is_admin: bool):
    await state.clear()
    await message.answer("🎮 <b>Панель Skibidi Verse TD</b>", reply_markup=main_reply_kb(is_admin))


# -------------------- ПРОФИЛЬ --------------------

async def build_profile_text(user: Dict[str, Any], is_self: bool = True) -> str:
    inv = await db.get_inventory(user["user_id"])
    eq = [c for c in inv if c["equip_slot"] > 0]
    total_dps = round(sum(calc_unit_battle_stats(c, 1)["dps"] for c in eq), 1)
    unique_cnt = len({c["unit_id"] for c in inv})
    shiny_cnt = sum(1 for c in inv if c["is_shiny"])
    inf_cnt = sum(1 for c in inv if c["is_infected"])
    tot_inf = user["infections_success"] + user["infections_fail"]
    inf_rate = round((user["infections_success"] / tot_inf) * 100, 1) if tot_inf else 0.0
    reg_date = datetime.fromtimestamp(user["created_at"]).strftime("%d.%m.%Y") if user["created_at"] else "—"

    s_role = await db.get_signer_role(user["user_id"])
    role_badge = " | 👑 Админ-Сигнер" if s_role == "admin" else (" | 🤝 Партнёр-Сигнер" if s_role == "partner" else "")
    title = "👤 <b>ВАШ ПРОФИЛЬ</b>" if is_self else "🔎 <b>ПРОФИЛЬ ИГРОКА</b>"

    return (
        f"{title}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🪪 {format_user_link(user)}{role_badge}\n"
        f"📅 В игре с: <code>{reg_date}</code>\n\n"
        f"💰 Монеты: <b>{user['coins']}</b>\n"
        f"🦠 Паразиты: Обыч. <b>{user['p_common']}</b> | Улучш. <b>{user['p_upgraded']}</b> | Элит. <b>{user['p_elite']}</b>\n\n"
        f"🛡 <b>Колода ({len(eq)}/{MAX_DECK_SIZE}):</b> ⚡ Базовый DPS: <b>{total_dps}/с</b>\n"
        f"🃏 Юнитов: <b>{len(inv)}</b> (Уник: {unique_cnt} | ✨Shiny: {shiny_cnt} | 🦠Инфект: {inf_cnt})\n\n"
        f"📊 <b>Статистика каток:</b>\n"
        f"   🏆 Побед: <b>{user['wins']}</b> | 💀 Поражений: <b>{user['losses']}</b>\n"
        f"   💥 Общий урон: <b>{int(user['total_damage'])}</b> | 👹 Боссов: <b>{user['bosses_killed']}</b>\n"
        f"   🦠 Заражений: <b>{user['infections_success']}</b>/{tot_inf} ({inf_rate}%) | 🎯 Пити: <b>+{user['pity_bonus']}%</b>\n"
        f"   🔥 Серия входов: <b>{user['daily_streak']} дн.</b>"
    )


def profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎁 Ежедневный бонус", callback_data="prof:daily"),
                InlineKeyboardButton(text="🔎 Найти игрока", callback_data="prof:search"),
            ],
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="prof:refresh")],
        ]
    )


@router.message(F.text == "👤 Профиль")
async def menu_profile(message: Message, state: FSMContext, db_user: Dict[str, Any]):
    await state.clear()
    await message.answer(await build_profile_text(await db.get_user(db_user["user_id"]), True), reply_markup=profile_kb())


@router.callback_query(F.data == "prof:refresh")
async def cb_prof_refresh(callback: CallbackQuery):
    await render_view(callback, await build_profile_text(await db.get_user(callback.from_user.id), True), profile_kb())
    await callback.answer("Обновлено!")


@router.callback_query(F.data == "prof:daily")
async def cb_prof_daily(callback: CallbackQuery):
    u = await db.get_user(callback.from_user.id)
    now = int(time.time())
    diff = now - u["last_daily"]
    if diff < DAILY_COOLDOWN:
        rem = DAILY_COOLDOWN - diff
        await callback.answer(f"⏳ Доступно через {rem // 3600}ч {(rem % 3600) // 60}м", show_alert=True)
        return
    streak = u["daily_streak"] + 1 if diff < DAILY_COOLDOWN * 2 else 1
    coins = int((150 + min(streak, 10) * 35) * cfg_float("event_coin_mult"))
    await db.update_user(u["user_id"], last_daily=now, daily_streak=streak)
    await db.add_coins(u["user_id"], coins)
    if streak % 3 == 0:
        await db.add_parasite(u["user_id"], "upgraded", 1)
        extra = " + 1 ☣️ Улучш. паразит"
    else:
        await db.add_parasite(u["user_id"], "common", 1)
        extra = " + 1 🦠 Обыч. паразит"
    await callback.answer(f"🎁 +{coins} 💰{extra} (День {streak})", show_alert=True)
    await render_view(callback, await build_profile_text(await db.get_user(u["user_id"]), True), profile_kb())


@router.callback_query(F.data == "prof:search")
async def cb_prof_search(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PlayerFSM.profile_search)
    await callback.message.answer("🔎 Введите <b>@username</b> или <b>Telegram ID</b> игрока:")
    await callback.answer()


@router.message(PlayerFSM.profile_search)
async def fsm_prof_search(message: Message, state: FSMContext):
    await state.clear()
    t = await db.find_user(message.text or "")
    if not t:
        await message.answer("❌ Игрок не найден.")
        return
    await message.answer(await build_profile_text(t, is_self=(t["user_id"] == message.from_user.id)))


# -------------------- ЭКИПИРОВКА 2.0 + ИНВЕНТАРЬ СО СТАКАМИ + ИНФО О ЮНИТЕ --------------------

async def render_deck_screen(target: Message | CallbackQuery, user_id: int):
    inv = await db.get_inventory(user_id)
    slot_map = {c["equip_slot"]: c for c in inv if c["equip_slot"] > 0}
    total_dps = round(sum(calc_unit_battle_stats(c, 1)["dps"] for c in slot_map.values()), 1)

    lines = [
        f"🛡 <b>МОЯ КОЛОДА ({len(slot_map)}/{MAX_DECK_SIZE})</b> | ⚡ DPS: <b>{total_dps}/с</b>",
        "━━━━━━━━━━━━━━━━━━",
    ]
    slot_nums = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
    slot_buttons = []
    for s in range(1, MAX_DECK_SIZE + 1):
        c = slot_map.get(s)
        if c:
            st = calc_unit_battle_stats(c, 1)
            r_ico = RARITIES.get(c["rarity"], ("", "⚪️", 1))[1]
            b = unit_badges(c)
            if "Ферма" in st["classes"] and st["dps"] == 0:
                stat_txt = f"🌾+{st['income']} | 💰{st['deploy_cost']}"
            elif "Саппорт" in st["classes"] and st["dps"] == 0:
                stat_txt = f"✨x{st['dmg_boost']} | 💰{st['deploy_cost']}"
            else:
                kb_s = f" 💨{st['knockback_power']}" if "Кнокбек" in st["classes"] and st["knockback_power"] > 0 else ""
                stat_txt = f"⚔️{st['damage']} ⏱{st['cd']}с{kb_s} | 💰{st['deploy_cost']}"
            lines.append(f"{slot_nums[s - 1]} {r_ico} <b>{esc(c['name'])}</b>{b} (Ур.{c['level']}) [{stat_txt}]")
            slot_buttons.append(InlineKeyboardButton(text=f"{slot_nums[s - 1]} {c['name'][:12]}", callback_data=f"eq:slot:{s}:0"))
        else:
            lines.append(f"{slot_nums[s - 1]} ⬜ <i>[Пустой слот]</i>")
            slot_buttons.append(InlineKeyboardButton(text=f"{slot_nums[s - 1]} Пусто", callback_data=f"eq:slot:{s}:0"))

    lines.append("\n👇 <i>Нажмите на слот, чтобы быстро надеть/сменить юнита, или откройте Инвентарь:</i>")

    rows = [slot_buttons[:3], slot_buttons[3:]]
    rows.append([
        InlineKeyboardButton(text="⚡ Авто-колода", callback_data="eq:auto"),
        InlineKeyboardButton(text="❌ Снять всех", callback_data="eq:clear"),
    ])
    rows.append([
        InlineKeyboardButton(text=f"🎒 Инвентарь ({len(inv)})", callback_data="inv:all:0"),
        InlineKeyboardButton(text="📖 Энциклопедия", callback_data="enc:0"),
    ])
    await render_view(target, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows))


async def render_slot_picker(target: Message | CallbackQuery, user_id: int, slot: int, page: int = 0):
    inv = await db.get_inventory(user_id)
    cur_item = next((c for c in inv if c["equip_slot"] == slot), None)
    # Исключаем карты на рынке и надетые в другие слоты (можно надеть только не выставленные на рынок)
    avail = [c for c in inv if not c.get("market_id") and c["equip_slot"] == 0]
    avail.sort(
        key=lambda x: (
            RARITIES.get(x["rarity"], ("", "", 0))[2],
            x["is_shiny"],
            x["is_infected"],
            x["level"],
            calc_unit_battle_stats(x, 1)["dps"],
        ),
        reverse=True,
    )

    per_page = 6
    total_pages = max(1, (len(avail) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    chunk = avail[page * per_page : (page + 1) * per_page]

    cur_txt = f"<b>{esc(cur_item['name'])}</b> {unit_badges(cur_item)} (Ур.{cur_item['level']})" if cur_item else "<i>Пусто</i>"
    text = f"🎯 <b>ВЫБОР ЮНИТА В СЛОТ #{slot}</b>\nСейчас в слоте: {cur_txt}\n━━━━━━━━━━━━━━━━━━"

    rows = []
    if cur_item:
        rows.append([
            InlineKeyboardButton(text="ℹ️ Инфо о текущем", callback_data=f"u:v:{cur_item['inv_id']}:deck:0"),
            InlineKeyboardButton(text="➖ Освободить слот", callback_data=f"eq:unset:{cur_item['inv_id']}"),
        ])
    for c in chunk:
        r_ico = RARITIES.get(c["rarity"], ("", "⚪️", 1))[1]
        st = calc_unit_battle_stats(c, 1)
        b = unit_badges(c)
        rows.append([
            InlineKeyboardButton(
                text=f"{r_ico}{b} {c['name']} (Ур.{c['level']} | 💰{st['deploy_cost']})",
                callback_data=f"eq:put:{slot}:{c['inv_id']}",
            )
        ])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"eq:slot:{slot}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"eq:slot:{slot}:{page + 1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔙 К колоде", callback_data="eq:home")])
    await render_view(target, text, InlineKeyboardMarkup(inline_keyboard=rows))


async def render_inventory_list(target: Message | CallbackQuery, user_id: int, flt: str = "all", page: int = 0):
    inv = await db.get_inventory(user_id)
    if flt == "shiny":
        filtered = [c for c in inv if c["is_shiny"]]
    elif flt == "inf":
        filtered = [c for c in inv if c["is_infected"]]
    elif flt == "eq":
        filtered = [c for c in inv if c["equip_slot"] > 0]
    else:
        filtered = inv

    # Группировка (стаки) одинаковых экземпляров без рынка и не в колоде
    stacks: List[Tuple[Dict[str, Any], int]] = []
    seen_map: Dict[Tuple, int] = {}
    for item in filtered:
        if item["equip_slot"] > 0 or item.get("market_id"):
            stacks.append((item, 1))
            continue
        key = (item["unit_id"], item["is_shiny"], item["is_infected"], item["sign_type"], item["signed_by"], item["level"])
        if key in seen_map:
            idx = seen_map[key]
            stacks[idx] = (stacks[idx][0], stacks[idx][1] + 1)
        else:
            seen_map[key] = len(stacks)
            stacks.append((item, 1))

    stacks.sort(
        key=lambda x: (
            1 if x[0]["equip_slot"] > 0 else 0,
            RARITIES.get(x[0]["rarity"], ("", "", 0))[2],
            x[0]["is_shiny"],
            x[0]["is_infected"],
            x[0]["level"],
        ),
        reverse=True,
    )

    per_page = 7
    total_pages = max(1, (len(stacks) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    chunk = stacks[page * per_page : (page + 1) * per_page]

    flt_titles = {"all": "Все", "shiny": "✨ Shiny", "inf": "🦠 Зараж.", "eq": "✅ В колоде"}
    text = (
        f"🎒 <b>ИНВЕНТАРЬ ЮНИТОВ</b> [{flt_titles.get(flt, 'Все')}]\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Всего юнитов: <b>{len(inv)}</b> | Нажмите на юнита для подробного Инфо и надевания:"
    )

    rows = [
        [
            InlineKeyboardButton(text="• Все •" if flt == "all" else "Все", callback_data="inv:all:0"),
            InlineKeyboardButton(text="• ✨ •" if flt == "shiny" else "✨ Shiny", callback_data="inv:shiny:0"),
            InlineKeyboardButton(text="• 🦠 •" if flt == "inf" else "🦠 Зараж.", callback_data="inv:inf:0"),
            InlineKeyboardButton(text="• ✅ •" if flt == "eq" else "✅ Колода", callback_data="inv:eq:0"),
        ]
    ]
    for item, qty in chunk:
        r_ico = RARITIES.get(item["rarity"], ("", "⚪️", 1))[1]
        b = unit_badges(item)
        tag = f"✅#{item['equip_slot']} " if item["equip_slot"] > 0 else ("🏷 " if item.get("market_id") else "")
        q_str = f" x{qty}" if qty > 1 else ""
        rows.append([
            InlineKeyboardButton(
                text=f"{tag}{r_ico}{b} {item['name']} (Ур.{item['level']}){q_str}",
                callback_data=f"u:v:{item['inv_id']}:{flt}:{page}",
            )
        ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"inv:{flt}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"inv:{flt}:{page + 1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton(text="🛡 К Колоде", callback_data="eq:home")])
    await render_view(target, text, InlineKeyboardMarkup(inline_keyboard=rows))


async def render_unit_info(
    target: Message | CallbackQuery, user_id: int, inv_id: int, back_flt: str, page: int, show_upgrades: bool = False
):
    item = await db.get_inv_item(inv_id)
    if not item or item["user_id"] != user_id:
        await render_deck_screen(target, user_id)
        return

    ex_tot, ex_sh = await db.get_unit_exist_counts(item["unit_id"])
    text = format_unit_info_card(item, ex_tot, ex_sh, show_upgrades=show_upgrades)

    inv = await db.get_inventory(user_id)
    used_slots = {c["equip_slot"] for c in inv if c["equip_slot"] > 0}
    free_slot = next((s for s in range(1, MAX_DECK_SIZE + 1) if s not in used_slots), None)

    rows = []
    if not item.get("market_id"):
        if item["equip_slot"] > 0:
            rows.append([InlineKeyboardButton(text=f"➖ Снять со Слота #{item['equip_slot']}", callback_data=f"u:un:{inv_id}:{back_flt}:{page}")])
        elif free_slot:
            rows.append([InlineKeyboardButton(text=f"✅ Надеть в Слот #{free_slot}", callback_data=f"u:eq:{inv_id}:{free_slot}:{back_flt}:{page}")])
        else:
            rows.append([InlineKeyboardButton(text="🔄 Колода полна (выбрать слот)", callback_data="eq:home")])

    if show_upgrades:
        rows.append([InlineKeyboardButton(text="📊 Основное инфо и статы", callback_data=f"u:v:{inv_id}:{back_flt}:{page}")])
    else:
        rows.append([InlineKeyboardButton(text="📈 Апгрейды в катке (Тиры)", callback_data=f"u:up:{inv_id}:{back_flt}:{page}")])

    action_row = []
    if not item.get("market_id"):
        signer_role = await db.get_signer_role(user_id)
        if signer_role:
            disc = get_sign_discount_pct(signer_role)
            lbl = f"👑 Подписать (-{disc}%)" if signer_role == "admin" else f"🤝 Подписать (-{disc}%)"
            action_row.append(InlineKeyboardButton(text=lbl, callback_data=f"u:sgn:{inv_id}:{back_flt}:{page}"))
        action_row.append(InlineKeyboardButton(text="🏷 На Рынок", callback_data=f"u:sell:{inv_id}"))
    if action_row:
        rows.append(action_row)

    back_cb = "eq:home" if back_flt == "deck" else f"inv:{back_flt}:{page}"
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data=back_cb)])
    await render_view(target, text, InlineKeyboardMarkup(inline_keyboard=rows), photo=item.get("photo_id") or None)


async def render_encyclopedia(target: Message | CallbackQuery, user_id: int, page: int = 0):
    units = await db.list_units()
    inv = await db.get_inventory(user_id)
    owned_ids = {c["unit_id"] for c in inv}

    units.sort(key=lambda u: RARITIES.get(u["rarity"], ("", "", 0))[2], reverse=True)
    per_page = 6
    total_pages = max(1, (len(units) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    chunk = units[page * per_page : (page + 1) * per_page]

    lines = [
        f"📖 <b>ЭНЦИКЛОПЕДИЯ ЮНИТОВ</b> (Открыто {len(owned_ids)}/{len(units)})",
        "━━━━━━━━━━━━━━━━━━",
    ]
    for u in chunk:
        ex_tot, ex_sh = await db.get_unit_exist_counts(u["id"])
        r_ico = RARITIES.get(u["rarity"], ("", "⚪️", 1))[1]
        if u["id"] in owned_ids:
            cls_s = ", ".join(u["classes"])
            lines.append(
                f"✅ {r_ico} <b>{esc(u['name'])}</b> [{cls_s}]\n"
                f"   └ ⚔️{u['damage']} | ⏱{u['cd']}с | 💰{u['deploy_cost']} | 🌍 {ex_tot} (✨{ex_sh})"
            )
        else:
            lines.append(f"❓ {r_ico} <b>???</b> | 🌍 Существует: {ex_tot} (✨{ex_sh})")

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"enc:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"enc:{page + 1}"))
    kb = InlineKeyboardMarkup(inline_keyboard=[nav, [InlineKeyboardButton(text="🔙 К Колоде", callback_data="eq:home")]])
    await render_view(target, "\n".join(lines), kb)


@router.message(F.text == "🃏 Колода и Юниты")
async def menu_deck(message: Message, state: FSMContext):
    await state.clear()
    await render_deck_screen(message, message.from_user.id)


@router.callback_query(F.data == "eq:home")
async def cb_eq_home(callback: CallbackQuery):
    await render_deck_screen(callback, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data.startswith("eq:slot:"))
async def cb_eq_slot(callback: CallbackQuery):
    _, _, s_s, p_s = callback.data.split(":")
    await render_slot_picker(callback, callback.from_user.id, int(s_s), int(p_s))
    await callback.answer()


@router.callback_query(F.data.startswith("eq:put:"))
async def cb_eq_put(callback: CallbackQuery):
    _, _, s_s, inv_s = callback.data.split(":")
    await db.set_equip_slot(callback.from_user.id, int(inv_s), int(s_s))
    await callback.answer(f"✅ Надето в Слот #{s_s}!")
    await render_deck_screen(callback, callback.from_user.id)


@router.callback_query(F.data.startswith("eq:unset:"))
async def cb_eq_unset(callback: CallbackQuery):
    inv_id = int(callback.data.split(":")[2])
    await db.set_equip_slot(callback.from_user.id, inv_id, 0)
    await callback.answer("➖ Снято со слота!")
    await render_deck_screen(callback, callback.from_user.id)


@router.callback_query(F.data == "eq:clear")
async def cb_eq_clear(callback: CallbackQuery):
    await db.clear_equip(callback.from_user.id)
    await callback.answer("❌ Колода очищена!")
    await render_deck_screen(callback, callback.from_user.id)


@router.callback_query(F.data == "eq:auto")
async def cb_eq_auto(callback: CallbackQuery):
    uid = callback.from_user.id
    inv = [c for c in await db.get_inventory(uid) if not c.get("market_id")]
    if not inv:
        await callback.answer("Инвентарь пуст!", show_alert=True)
        return
    await db.clear_equip(uid)

    chosen: List[Dict[str, Any]] = []
    used_unit_ids: Set[int] = set()

    # Сначала 1 лучшая Ферма (если есть) и 1 лучший Саппорт (если есть)
    farms = sorted([c for c in inv if "Ферма" in c["classes"]], key=lambda x: calc_unit_battle_stats(x, 1)["income"], reverse=True)
    if farms:
        chosen.append(farms[0])
        used_unit_ids.add(farms[0]["unit_id"])
    supps = sorted([c for c in inv if "Саппорт" in c["classes"] and c["unit_id"] not in used_unit_ids], key=lambda x: calc_unit_battle_stats(x, 1)["dmg_boost"], reverse=True)
    if supps:
        chosen.append(supps[0])
        used_unit_ids.add(supps[0]["unit_id"])

    # Остальные слоты — самые сильные по DPS (уникальные сначала, потом любые)
    dmg_sorted = sorted(inv, key=lambda x: (calc_unit_battle_stats(x, 1)["dps"], x["level"]), reverse=True)
    for c in dmg_sorted:
        if len(chosen) >= MAX_DECK_SIZE:
            break
        if c["inv_id"] not in {x["inv_id"] for x in chosen} and c["unit_id"] not in used_unit_ids:
            chosen.append(c)
            used_unit_ids.add(c["unit_id"])
    for c in dmg_sorted:
        if len(chosen) >= MAX_DECK_SIZE:
            break
        if c["inv_id"] not in {x["inv_id"] for x in chosen}:
            chosen.append(c)

    for idx, c in enumerate(chosen, 1):
        await db.set_equip_slot(uid, c["inv_id"], idx)
    await callback.answer("⚡ Оптимальная колода собрана!", show_alert=True)
    await render_deck_screen(callback, uid)


@router.callback_query(F.data.startswith("inv:"))
async def cb_inv_list(callback: CallbackQuery):
    _, flt, p_s = callback.data.split(":")
    await render_inventory_list(callback, callback.from_user.id, flt, int(p_s))
    await callback.answer()


@router.callback_query(F.data.startswith("enc:"))
async def cb_enc(callback: CallbackQuery):
    await render_encyclopedia(callback, callback.from_user.id, int(callback.data.split(":")[1]))
    await callback.answer()


@router.callback_query(F.data.startswith("u:v:"))
async def cb_unit_view(callback: CallbackQuery):
    _, _, inv_s, flt, p_s = callback.data.split(":")
    await render_unit_info(callback, callback.from_user.id, int(inv_s), flt, int(p_s), show_upgrades=False)
    await callback.answer()


@router.callback_query(F.data.startswith("u:up:"))
async def cb_unit_upg_view(callback: CallbackQuery):
    _, _, inv_s, flt, p_s = callback.data.split(":")
    await render_unit_info(callback, callback.from_user.id, int(inv_s), flt, int(p_s), show_upgrades=True)
    await callback.answer()


@router.callback_query(F.data.startswith("u:eq:"))
async def cb_unit_quick_equip(callback: CallbackQuery):
    _, _, inv_s, slot_s, flt, p_s = callback.data.split(":")
    await db.set_equip_slot(callback.from_user.id, int(inv_s), int(slot_s))
    await callback.answer(f"✅ Надето в Слот #{slot_s}!")
    await render_unit_info(callback, callback.from_user.id, int(inv_s), flt, int(p_s), False)


@router.callback_query(F.data.startswith("u:un:"))
async def cb_unit_quick_unequip(callback: CallbackQuery):
    _, _, inv_s, flt, p_s = callback.data.split(":")
    await db.set_equip_slot(callback.from_user.id, int(inv_s), 0)
    await callback.answer("➖ Снято с колоды!")
    await render_unit_info(callback, callback.from_user.id, int(inv_s), flt, int(p_s), False)


@router.callback_query(F.data.startswith("u:sgn:"))
async def cb_unit_sign(callback: CallbackQuery):
    _, _, inv_s, flt, p_s = callback.data.split(":")
    uid = callback.from_user.id
    role = await db.get_signer_role(uid)
    if not role:
        await callback.answer("Нет прав Сигнера!", show_alert=True)
        return
    u = await db.get_user(uid)
    who = f"@{u['username']}" if u and u.get("username") else (u["full_name"] if u else str(uid))
    await db.sign_inv_item(int(inv_s), role, who)
    disc = get_sign_discount_pct(role)
    await callback.answer(f"✍️ Подписано! Юнит дешевле на -{disc}% в катке!", show_alert=True)
    await render_unit_info(callback, uid, int(inv_s), flt, int(p_s), False)


@router.callback_query(F.data.startswith("u:sell:"))
async def cb_unit_sell(callback: CallbackQuery, state: FSMContext):
    inv_id = int(callback.data.split(":")[2])
    item = await db.get_inv_item(inv_id)
    if not item or item["user_id"] != callback.from_user.id or item.get("market_id"):
        await callback.answer("Юнит недоступен.", show_alert=True)
        return
    await state.set_state(PlayerFSM.market_price)
    await state.update_data(sell_inv_id=inv_id)
    await callback.message.answer(
        f"🏷 Введите цену для <b>{esc(item['name'])}</b> (от 50 до 500000 💰).\n"
        f"<i>Напоминание: вы получите <b>80%</b> суммы, комиссия рынка <b>20%</b>.</i>"
    )
    await callback.answer()


@router.message(PlayerFSM.market_price)
async def fsm_market_price(message: Message, state: FSMContext):
    inv_id = (await state.get_data()).get("sell_inv_id")
    await state.clear()
    try:
        price = int((message.text or "").strip())
        if not (50 <= price <= 500000):
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите целое число от 50 до 500000.")
        return
    item = await db.get_inv_item(inv_id)
    if not item or item["user_id"] != message.from_user.id or item.get("market_id"):
        await message.answer("❌ Юнит больше недоступен.")
        return
    await db.create_market_lot(message.from_user.id, inv_id, price)
    payout = int(price * (100 - MARKET_COMMISSION_PCT) / 100)
    await message.answer(
        f"✅ <b>{esc(item['name'])}</b> выставлен на P2P-рынок за <b>{price} 💰</b>!\n"
        f"После продажи вы получите <b>{payout} 💰</b> (80%)."
    )


# ==============================================================================
# 7. TD-КАТКИ: СОЗДАНИЕ ЛОББИ (1–4 ИГРОКА), ВОЛНЫ, КНОКБЕК И ЗАРАЖЕНИЕ БОССОВ
# ==============================================================================

async def render_play_menu(target: Message | CallbackQuery, user_id: int):
    maps = await db.list_maps()
    open_lobbies = [b for b in ACTIVE_BATTLES.values() if not b["started"] and len(b["players"]) < 4]

    text = (
        f"⚔️ <b>СОЗДАНИЕ КАТКИ (Skibidi Verse TD)</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Выберите карту, чтобы создать лобби (Соло или Кооп до 4 игроков).\n"
        f"Открытых кооп-лобби сейчас: <b>{len(open_lobbies)}</b>\n"
        f"💡 <i>Юниты в катке получают <b>0.1 XP за 1 урон</b> (до 50 ур.!)</i>"
    )
    rows = []
    for m in maps:
        w_cnt = len(m["waves"])
        rows.append([
            InlineKeyboardButton(
                text=f"🗺 {m['name']} ({w_cnt} волн | 🏆{m['win_coins']}💰)",
                callback_data=f"td:create:{m['id']}",
            )
        ])
    if open_lobbies:
        rows.append([InlineKeyboardButton(text=f"👥 Открытые Лобби ({len(open_lobbies)})", callback_data="td:lobbies")])
    if user_id in USER_TO_BATTLE:
        bid = USER_TO_BATTLE[user_id]
        rows.append([InlineKeyboardButton(text="🏳️ Выйти из текущей катки", callback_data=f"td:leave:{bid}")])

    await render_view(target, text, InlineKeyboardMarkup(inline_keyboard=rows))


@router.message(F.text == "⚔️ Играть (Катки)")
async def menu_play(message: Message, state: FSMContext):
    await state.clear()
    await render_play_menu(message, message.from_user.id)


@router.callback_query(F.data == "td:lobbies")
async def cb_td_lobbies(callback: CallbackQuery):
    open_lobbies = [b for b in ACTIVE_BATTLES.values() if not b["started"] and len(b["players"]) < 4]
    if not open_lobbies:
        await callback.answer("Открытых лобби пока нет — создайте своё!", show_alert=True)
        await render_play_menu(callback, callback.from_user.id)
        return
    rows = []
    for b in open_lobbies[:10]:
        rows.append([
            InlineKeyboardButton(
                text=f"🚪 #{b['id']} {b['map']['name']} ({len(b['players'])}/4) — {b['host_name']}",
                callback_data=f"td:join:{b['id']}",
            )
        ])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="td:menu")])
    await render_view(callback, "👥 <b>ОТКРЫТЫЕ КООП-ЛОББИ</b>\nНажмите, чтобы присоединиться:", InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data == "td:menu")
async def cb_td_menu(callback: CallbackQuery):
    await render_play_menu(callback, callback.from_user.id)
    await callback.answer()


def build_lobby_text(b: Dict[str, Any]) -> str:
    p_lines = [f"• <b>{esc(p['name'])}</b> ({len(p['deck'])} юнитов)" for p in b["players"].values()]
    hp_scale = {1: "1.0x", 2: "1.5x", 3: "2.25x", 4: "3.0x"}.get(len(b["players"]), "3.0x")
    return (
        f"🚪 <b>ЛОББИ #{b['id']} — {esc(b['map']['name'])}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🌊 Волн: <b>{len(b['map']['waves'])}</b> | 🏰 База: <b>{b['base_hp']} HP</b> | 💪 Масштаб HP мобов: <b>{hp_scale}</b>\n"
        f"🏆 Победа: <b>{b['map']['win_coins']} 💰</b> | 📉 Поражение: <b>{b['map']['lose_coins']} 💰</b>\n\n"
        f"👥 <b>Игроки ({len(b['players'])}/4):</b>\n" + "\n".join(p_lines) + "\n\n"
        f"<i>Другие игроки могут присоединиться через «🌐 Мультиплеер → Открытые Лобби» или кнопку ниже (в группе).</i>"
    )


def build_lobby_kb(bid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="▶️ НАЧАТЬ КАТКУ", callback_data=f"td:start:{bid}"),
                InlineKeyboardButton(text="👥 Присоединиться", callback_data=f"td:join:{bid}"),
            ],
            [InlineKeyboardButton(text="❌ Закрыть / Выйти", callback_data=f"td:leave:{bid}")],
        ]
    )


async def sync_lobby_messages(b: Dict[str, Any], bot: Bot) -> None:
    txt = build_lobby_text(b)
    kb = build_lobby_kb(b["id"])
    for chat_id, msg_id in list(b["messages"].items()):
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=txt, reply_markup=kb)
        except Exception:
            pass


@router.callback_query(F.data.startswith("td:create:"))
async def cb_td_create(callback: CallbackQuery):
    global BATTLE_COUNTER
    uid = callback.from_user.id
    if uid in USER_TO_BATTLE:
        await callback.answer("Вы уже находитесь в катке/лобби!", show_alert=True)
        return
    deck = await db.get_inventory(uid, only_equipped=True)
    if not deck:
        await callback.answer("Сначала наденьте юнитов в «🃏 Колода и Юниты»!", show_alert=True)
        return

    map_id = int(callback.data.split(":")[2])
    m_data = await db.get_map(map_id)
    if not m_data or not m_data["waves"]:
        await callback.answer("Карта пуста или не найдена.", show_alert=True)
        return

    bid = BATTLE_COUNTER
    BATTLE_COUNTER += 1
    u = await db.get_user(uid)

    battle = {
        "id": bid,
        "map": m_data,
        "host_id": uid,
        "host_name": u["full_name"],
        "is_group": callback.message.chat.type in {"group", "supergroup"},
        "started": False,
        "auto_skip": False,
        "base_hp": float(m_data["base_hp"]),
        "max_base_hp": float(m_data["base_hp"]),
        "current_wave": 1,
        "current_turn": 1,
        "mobs": [],
        "slow_effects": [],
        "bosses_killed_in_match": [],
        "players": {
            uid: {
                "name": u["full_name"],
                "coins": float(m_data["starting_coins"]),
                "deck": deck,
                "deployed": [],  # {"inv_id", "item", "tier", "time_bank", "slow_timer"}
                "damage_dealt": 0.0,
                "damage_by_inv": {},
                "mobs_killed": 0,
                "ui_mode": "deploy",
            }
        },
        "messages": {},  # chat_id -> message_id
        "msg_has_photo": {},  # chat_id -> bool
    }
    ACTIVE_BATTLES[bid] = battle
    USER_TO_BATTLE[uid] = bid

    msg = await callback.message.answer(build_lobby_text(battle), reply_markup=build_lobby_kb(bid))
    battle["messages"][msg.chat.id] = msg.message_id
    battle["msg_has_photo"][msg.chat.id] = False
    await callback.answer("🚪 Лобби создано!")


@router.callback_query(F.data.startswith("td:join:"))
async def cb_td_join(callback: CallbackQuery, bot: Bot):
    bid = int(callback.data.split(":")[2])
    uid = callback.from_user.id
    b = ACTIVE_BATTLES.get(bid)
    if not b or b["started"]:
        await callback.answer("Лобби уже запущено или закрыто.", show_alert=True)
        return
    if uid in b["players"]:
        await callback.answer("Вы уже в этом лобби!")
        return
    if uid in USER_TO_BATTLE:
        await callback.answer("Вы уже в другом бою!", show_alert=True)
        return
    if len(b["players"]) >= 4:
        await callback.answer("Лобби заполнено (макс. 4)!", show_alert=True)
        return
    deck = await db.get_inventory(uid, only_equipped=True)
    if not deck:
        await callback.answer("Сначала наденьте юнитов в колоду!", show_alert=True)
        return

    u = await db.get_user(uid)
    b["players"][uid] = {
        "name": u["full_name"],
        "coins": float(b["map"]["starting_coins"]),
        "deck": deck,
        "deployed": [],
        "damage_dealt": 0.0,
        "damage_by_inv": {},
        "mobs_killed": 0,
        "ui_mode": "deploy",
    }
    USER_TO_BATTLE[uid] = bid

    # Если игрок зашёл из лички в чужое лобби — создаём ему собственное окно лобби/боя
    if callback.message.chat.id not in b["messages"]:
        m = await callback.message.answer(build_lobby_text(b), reply_markup=build_lobby_kb(bid))
        b["messages"][m.chat.id] = m.message_id
        b["msg_has_photo"][m.chat.id] = False

    await sync_lobby_messages(b, bot)
    await callback.answer("✅ Вы присоединились к лобби!")


@router.callback_query(F.data.startswith("td:leave:"))
async def cb_td_leave(callback: CallbackQuery, bot: Bot):
    bid = int(callback.data.split(":")[2])
    uid = callback.from_user.id
    b = ACTIVE_BATTLES.get(bid)
    if not b:
        USER_TO_BATTLE.pop(uid, None)
        await callback.answer("Катка уже завершена.")
        return

    if uid == b["host_id"] or len(b["players"]) <= 1:
        await cleanup_battle(bid, bot, "🏳️ Лобби закрыто хостом.")
        await callback.answer("Лобби закрыто.")
    elif uid in b["players"]:
        b["players"].pop(uid, None)
        USER_TO_BATTLE.pop(uid, None)
        b["messages"].pop(uid, None)
        if not b["started"]:
            await sync_lobby_messages(b, bot)
        await callback.answer("Вы вышли из лобби.")


async def spawn_wave_mobs(b: Dict[str, Any], wave_idx: int) -> None:
    wave = b["map"]["waves"][wave_idx]
    p_cnt = len(b["players"])
    hp_mult = {1: 1.0, 2: 1.5, 3: 2.25, 4: 3.0}.get(p_cnt, 3.0)
    turns = float(wave.get("turns", 6))

    mobs_out = []
    for entry in wave.get("mobs", []):
        m = await db.get_mob(int(entry["id"]))
        if not m:
            continue
        scaled_hp = max(1, int(m["hp"] * hp_mult))
        for _ in range(int(entry.get("count", 1))):
            mobs_out.append({
                "mob_id": m["id"],
                "name": m["name"],
                "hp": float(scaled_hp),
                "max_hp": float(scaled_hp),
                "def": int(m.get("defense_percent", 0)),
                "is_boss": bool(m.get("is_boss")),
                "infect_chance": int(m.get("infect_chance", 0)),
                "infected_unit_id": int(m.get("infected_unit_id", 0)),
                "photo_id": m.get("photo_id", ""),
                "turns_left": turns,
                "kb_accum": 0.0,
                "kb_pushes": 0,
                "stun_turns": 0,
                "burn_turns": 0,
                "burn_dmg": 0.0,
            })
    b["mobs"] = mobs_out


def build_battle_kb(b: Dict[str, Any], viewer_uid: int) -> InlineKeyboardMarkup:
    bid = b["id"]
    p = b["players"].get(viewer_uid) or next(iter(b["players"].values()))
    mode = p.get("ui_mode", "deploy")
    skip_txt = "🟢 Вкл" if b["auto_skip"] else "🔴 Выкл"

    rows = [
        [
            InlineKeyboardButton(text=f"⏩ Авто-скип ({skip_txt})", callback_data=f"b:sk:{bid}"),
            InlineKeyboardButton(text="🏳️ Сдаться", callback_data=f"b:sr:{bid}"),
        ],
        [
            InlineKeyboardButton(
                text="• 🛡 Поставить •" if mode == "deploy" else "🛡 Поставить",
                callback_data=f"b:md:{bid}:deploy",
            ),
            InlineKeyboardButton(
                text="• ⬆️ Апгрейд •" if mode == "upgrade" else "⬆️ Апгрейд",
                callback_data=f"b:md:{bid}:upgrade",
            ),
        ],
    ]

    if mode == "deploy":
        row = []
        for item in p["deck"]:
            st = calc_unit_battle_stats(item, 1)
            cnt = sum(1 for d in p["deployed"] if d["inv_id"] == item["inv_id"])
            b_ico = unit_badges(item)
            row.append(
                InlineKeyboardButton(
                    text=f"{b_ico}{item['name'][:11]} ({cnt}/{st['supply_limit']}) 💰{st['deploy_cost']}",
                    callback_data=f"b:dp:{bid}:{item['inv_id']}",
                )
            )
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
    else:
        shown: Set[Tuple[int, int]] = set()
        for dep in p["deployed"]:
            nxt = dep["tier"] + 1
            cost = get_tier_upgrade_cost(dep["item"], nxt)
            if cost is None:
                continue
            key = (dep["inv_id"], dep["tier"])
            if key in shown:
                continue
            shown.add(key)
            rows.append([
                InlineKeyboardButton(
                    text=f"⬆️ {dep['item']['name']} (Тир {dep['tier']}➔{nxt}) | 💰{cost}",
                    callback_data=f"b:up:{bid}:{dep['inv_id']}:{dep['tier']}",
                )
            ])
        if not shown:
            rows.append([InlineKeyboardButton(text="Нет доступных апгрейдов", callback_data="noop")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_battle_text(b: Dict[str, Any], viewer_uid: int) -> str:
    m_data = b["map"]
    total_waves = len(m_data["waves"])
    w_turns = m_data["waves"][b["current_wave"] - 1]["turns"]
    slow_pct = min(75, sum(e["percent"] for e in b["slow_effects"]))
    total_hp = int(sum(m["hp"] for m in b["mobs"]))
    delay = cfg_int("turn_time_skip") if b["auto_skip"] else cfg_int("turn_time_noskip")

    lines = [
        f"🗺 <b>{esc(m_data['name'])}</b> | 🌊 <b>Волна {b['current_wave']}/{total_waves}</b> | ⏱ Ход {b['current_turn']}/{w_turns}",
        f"🏰 База: <b>{b['base_hp']:.1f}/{b['max_base_hp']:.0f} HP</b> | ❤️ HP врагов: <b>{total_hp}</b>",
    ]
    if slow_pct > 0:
        lines.append(f"❄️ <b>Замедление врагов: -{slow_pct}%</b>")
    lines.append("━━━━━━━━━━━━━━━━━━")

    for m in b["mobs"][:5]:
        ico = "👑" if m["is_boss"] else "👾"
        def_s = f" 🛡{m['def']}%" if m["def"] > 0 else ""
        st_s = ""
        if m["burn_turns"] > 0:
            st_s += " 🔥"
        if m["stun_turns"] > 0:
            st_s += " ⚡"
        if m["kb_pushes"] > 0:
            st_s += f" 💨+{m['kb_pushes']}х"
        lines.append(f"{ico} <b>{esc(m['name'])}</b>: ❤️{int(m['hp'])}/{int(m['max_hp'])}{def_s} (⏳{math.ceil(m['turns_left'])}х){st_s}")
    if len(b["mobs"]) > 5:
        lines.append(f"<i>...и ещё {len(b['mobs']) - 5} врагов</i>")

    lines.append("━━━━━━━━━━━━━━━━━━")
    for uid, p in b["players"].items():
        mark = "👉 " if uid == viewer_uid else "• "
        lines.append(f"{mark}<b>{esc(p['name'])}</b>: 💰 <b>{int(p['coins'])}</b> | 💥 {int(p['damage_dealt'])}")

    vp = b["players"].get(viewer_uid) or next(iter(b["players"].values()))
    if vp["ui_mode"] == "deploy":
        lines.append("\n🛡 <b>Ваши юниты на поле:</b>")
        counts: Dict[Tuple[int, int], Tuple[Dict[str, Any], int]] = {}
        for dep in vp["deployed"]:
            k = (dep["inv_id"], dep["tier"])
            counts[k] = (dep["item"], counts.get(k, (dep["item"], 0))[1] + 1)
        if not counts:
            lines.append("<i>Поставьте юнита кнопками ниже!</i>")
        else:
            for (inv_id, tier), (item, cnt) in counts.items():
                st = calc_unit_battle_stats(item, tier)
                extra = f"🌾+{st['income']}" if ("Ферма" in st["classes"] and st["damage"] == 0) else (
                    f"✨x{st['dmg_boost']}" if ("Саппорт" in st["classes"] and st["damage"] == 0) else f"⚔️{st['damage']}"
                )
                lines.append(f"• {esc(item['name'])} Т{tier} (x{cnt}) — {extra}")
    else:
        lines.append("\n⬆️ <b>Апгрейды юнитов на поле:</b>")
        lines.append("<i>Выберите юнита ниже для повышения тира.</i>")

    lines.append(f"\n⏱ <i>Следующий ход через {delay}с</i>")
    return "\n".join(lines)


async def update_battle_ui(bid: int, bot: Bot) -> None:
    b = ACTIVE_BATTLES.get(bid)
    if not b:
        return

    # Готовим Pillow-картинку (если у карты или первого моба есть photo_id)
    photo_id = b["map"].get("photo_id") or (b["mobs"][0]["photo_id"] if b["mobs"] else "")
    drawn_bytes: Optional[bytes] = None
    if photo_id:
        if photo_id not in IMAGE_CACHE:
            try:
                bio = io.BytesIO()
                await bot.download(photo_id, destination=bio)
                IMAGE_CACHE[photo_id] = bio.getvalue()
            except Exception:
                pass
        if photo_id in IMAGE_CACHE:
            w_turns = b["map"]["waves"][b["current_wave"] - 1]["turns"]
            slow_pct = min(75, sum(e["percent"] for e in b["slow_effects"]))
            total_hp = int(sum(m["hp"] for m in b["mobs"]))
            drawn_bytes = await asyncio.to_thread(
                _draw_battle_image_sync,
                IMAGE_CACHE[photo_id], total_hp, b["current_wave"], len(b["map"]["waves"]),
                b["current_turn"], w_turns, slow_pct,
            )

    for chat_id, msg_id in list(b["messages"].items()):
        viewer_uid = chat_id if chat_id in b["players"] else b["host_id"]
        txt = build_battle_text(b, viewer_uid)
        kb = build_battle_kb(b, viewer_uid)
        has_photo = b["msg_has_photo"].get(chat_id, False)

        try:
            if drawn_bytes:
                media_file = BufferedInputFile(drawn_bytes, filename="wave.jpg")
                if has_photo:
                    await bot.edit_message_media(
                        chat_id=chat_id,
                        message_id=msg_id,
                        media=InputMediaPhoto(media=media_file, caption=txt[:1024], parse_mode=ParseMode.HTML),
                        reply_markup=kb,
                    )
                else:
                    try:
                        await bot.delete_message(chat_id=chat_id, message_id=msg_id)
                    except Exception:
                        pass
                    nm = await bot.send_photo(chat_id=chat_id, photo=media_file, caption=txt[:1024], reply_markup=kb)
                    b["messages"][chat_id] = nm.message_id
                    b["msg_has_photo"][chat_id] = True
            else:
                if has_photo:
                    await bot.edit_message_caption(chat_id=chat_id, message_id=msg_id, caption=txt[:1024], reply_markup=kb)
                else:
                    await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=txt[:4096], reply_markup=kb)
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except Exception:
            pass


@router.callback_query(F.data.startswith("td:start:"))
async def cb_td_start(callback: CallbackQuery, bot: Bot):
    bid = int(callback.data.split(":")[2])
    b = ACTIVE_BATTLES.get(bid)
    if not b or b["started"]:
        await callback.answer("Бой уже идёт или не найден.", show_alert=True)
        return
    if callback.from_user.id != b["host_id"] and not await db.is_admin(callback.from_user.id):
        await callback.answer("Только создатель лобби может начать бой!", show_alert=True)
        return

    b["started"] = True
    await spawn_wave_mobs(b, 0)
    await update_battle_ui(bid, bot)
    BATTLE_TASKS[bid] = asyncio.create_task(td_battle_loop(bid, bot))
    await callback.answer("⚔️ Бой начался!")


async def td_battle_loop(bid: int, bot: Bot) -> None:
    try:
        while bid in ACTIVE_BATTLES:
            b = ACTIVE_BATTLES[bid]
            delay = cfg_int("turn_time_skip") if b["auto_skip"] else cfg_int("turn_time_noskip")
            await asyncio.sleep(delay)
            if bid not in ACTIVE_BATTLES:
                break
            await process_td_turn(bid, bot, float(delay))
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.exception("TD battle loop error: %s", exc)
        if bid in ACTIVE_BATTLES:
            await cleanup_battle(bid, bot, "⚠️ Ошибка боя, катка завершена.")


async def process_td_turn(bid: int, bot: Bot, delay: float) -> None:
    b = ACTIVE_BATTLES.get(bid)
    if not b:
        return

    coins_per_dmg = cfg_float("coins_per_damage")

    # 1. Ищем лучшие баффы Саппортов и применяем Замедление
    best_cd_mult = 1.0
    best_dmg_mult = 1.0
    for p in b["players"].values():
        for dep in p["deployed"]:
            st = calc_unit_battle_stats(dep["item"], dep["tier"])
            if "Саппорт" in st["classes"]:
                best_cd_mult = min(best_cd_mult, st["cd_boost"])
                best_dmg_mult = max(best_dmg_mult, st["dmg_boost"])
            if "Замедление" in st["classes"] and b["mobs"] and st["slow_percent"] > 0:
                dep["slow_timer"] = dep.get("slow_timer", st["slow_cd"]) + delay
                if dep["slow_timer"] >= st["slow_cd"]:
                    dep["slow_timer"] -= st["slow_cd"]
                    b["slow_effects"].append({"percent": st["slow_percent"], "turns": max(1, int(st["slow_duration"]))})

    # 2. Урон от горения
    for m in b["mobs"]:
        if m["burn_turns"] > 0 and m["hp"] > 0:
            actual = min(m["hp"], m["burn_dmg"])
            m["hp"] = round(m["hp"] - m["burn_dmg"], 2)
            m["burn_turns"] -= 1
            if actual > 0 and b["players"]:
                rp = random.choice(list(b["players"].values()))
                rp["coins"] += actual * coins_per_dmg
                rp["damage_dealt"] += actual
            if m["hp"] <= 0 and m["is_boss"]:
                b["bosses_killed_in_match"].append(m)
    b["mobs"] = [m for m in b["mobs"] if m["hp"] > 0]

    # 3. Атаки всех размещённых юнитов (включая Кнокбек!)
    for p in b["players"].values():
        for dep in p["deployed"]:
            st = calc_unit_battle_stats(dep["item"], dep["tier"])
            cls = st["classes"]
            if not any(c in ATTACKING_CLASSES for c in cls) or st["damage"] <= 0:
                continue

            actual_cd = max(0.15, st["cd"] * best_cd_mult)
            dmg_base = st["damage"] * best_dmg_mult
            dep["time_bank"] = dep.get("time_bank", 0.0) + delay

            while dep["time_bank"] >= actual_cd and b["mobs"]:
                dep["time_bank"] -= actual_cd
                inv_id = dep["inv_id"]

                # Определяем цели по типу атаки
                if "АОЕ" in cls:
                    targets = b["mobs"][:10]
                elif "Сплеш" in cls:
                    targets = b["mobs"][:5]
                else:
                    targets = [b["mobs"][0]]

                for m in targets:
                    dmg_done = round(dmg_base * (1.0 - m["def"] / 100.0), 2)
                    real_dmg = min(m["hp"], max(0.5, dmg_done))
                    m["hp"] = round(m["hp"] - real_dmg, 2)

                    p["coins"] += real_dmg * coins_per_dmg
                    p["damage_dealt"] += real_dmg
                    p["damage_by_inv"][inv_id] = p["damage_by_inv"].get(inv_id, 0.0) + real_dmg

                    # Статус-эффекты
                    if "Оглушение" in cls and st["stun_chance"] > 0 and random.randint(1, 100) <= st["stun_chance"]:
                        m["stun_turns"] = max(m["stun_turns"], st["stun_duration"])
                    if "Горение" in cls and st["burn_chance"] > 0 and random.randint(1, 100) <= st["burn_chance"]:
                        m["burn_turns"] = max(m["burn_turns"], st["burn_duration"])
                        m["burn_dmg"] = max(m["burn_dmg"], st["burn_damage"])

                    # Механика КНОКБЕКА: мягко отталкивает моба назад (+1 ход до базы за каждые 10 очков, макс +3; боссов x0.5 и макс +1)
                    if "Кнокбек" in cls and st["knockback_power"] > 0 and m["hp"] > 0:
                        max_push = 1 if m["is_boss"] else 3
                        if m["kb_pushes"] < max_push:
                            m["kb_accum"] += st["knockback_power"] * (0.5 if m["is_boss"] else 1.0)
                            while m["kb_accum"] >= 10.0 and m["kb_pushes"] < max_push:
                                m["kb_accum"] -= 10.0
                                m["kb_pushes"] += 1
                                m["turns_left"] += 1.0

                    if m["hp"] <= 0:
                        p["mobs_killed"] += 1
                        if m["is_boss"]:
                            b["bosses_killed_in_match"].append(m)

                b["mobs"] = [m for m in b["mobs"] if m["hp"] > 0]

    # 4. Продвижение мобов к базе (с учётом замедления, стана и кнокбека)
    slow_pct = min(75, sum(e["percent"] for e in b["slow_effects"]))
    step = max(0.25, 1.0 - slow_pct / 100.0)
    surviving = []
    for m in b["mobs"]:
        if m["stun_turns"] > 0:
            m["stun_turns"] -= 1
            surviving.append(m)
            continue
        m["turns_left"] -= step
        if m["turns_left"] <= 0:
            b["base_hp"] = round(b["base_hp"] - max(1.0, m["hp"] / 10.0), 1)
        else:
            surviving.append(m)
    b["mobs"] = surviving

    b["slow_effects"] = [
        {"percent": e["percent"], "turns": e["turns"] - 1}
        for e in b["slow_effects"]
        if e["turns"] - 1 > 0
    ]

    if b["base_hp"] <= 0:
        b["base_hp"] = 0.0
        await finish_td_battle(bid, bot, is_win=False)
        return

    # 5. Переход на следующую волну или завершение катки
    if not b["mobs"]:
        for p in b["players"].values():
            farm_inc = sum(
                calc_unit_battle_stats(dep["item"], dep["tier"])["income"]
                for dep in p["deployed"]
                if "Ферма" in dep["item"]["classes"]
            )
            p["coins"] += farm_inc + 15  # Базовый бонус за зачищенную волну

        b["current_wave"] += 1
        b["current_turn"] = 1
        if b["current_wave"] > len(b["map"]["waves"]):
            await finish_td_battle(bid, bot, is_win=True)
            return
        await spawn_wave_mobs(b, b["current_wave"] - 1)
    else:
        b["current_turn"] += 1

    await update_battle_ui(bid, bot)


async def finish_td_battle(bid: int, bot: Bot, is_win: bool) -> None:
    b = ACTIVE_BATTLES.get(bid)
    if not b:
        return

    m_data = b["map"]
    base_reward = int((m_data["win_coins"] if is_win else m_data["lose_coins"]) * cfg_float("event_coin_mult"))
    mvp_uid = max(b["players"], key=lambda uid: b["players"][uid]["damage_dealt"], default=None)
    bosses_killed = b["bosses_killed_in_match"]

    lines = [
        f"🏆 <b>ПОБЕДА НА КАРТЕ «{esc(m_data['name'])}»!</b>" if is_win else f"💀 <b>ПОРАЖЕНИЕ НА ВОЛНЕ {b['current_wave']}!</b>",
        "━━━━━━━━━━━━━━━━━━",
    ]

    for uid, p in b["players"].items():
        u = await db.get_user(uid)
        await db.add_coins(uid, base_reward)
        await db.update_user(
            uid,
            wins=u["wins"] + (1 if is_win else 0),
            losses=u["losses"] + (0 if is_win else 1),
            total_damage=round(u["total_damage"] + p["damage_dealt"], 1),
            bosses_killed=u["bosses_killed"] + len(bosses_killed),
        )

        # Начисляем XP юнитам за нанесённый урон (1 урон = 0.1 XP, макс 50 ур.)
        lvl_up_notes = []
        for inv_id, dmg in p["damage_by_inv"].items():
            gained_xp = round(dmg * UNIT_XP_PER_DAMAGE, 2)
            if gained_xp <= 0:
                continue
            item = await db.get_inv_item(inv_id)
            if not item or item["user_id"] != uid:
                continue
            new_lvl, new_xp, ups = apply_unit_xp(item["level"], item["xp"], gained_xp)
            await db.update_inv_progress(inv_id, new_lvl, new_xp)
            if ups > 0:
                lvl_up_notes.append(f"⭐ {esc(item['name'])} ➔ Ур.{new_lvl}!")

        mvp_tag = " 👑MVP" if uid == mvp_uid and len(b["players"]) > 1 else ""
        lines.append(f"• <b>{esc(p['name'])}</b>{mvp_tag}: +{base_reward} 💰 | 💥 {int(p['damage_dealt'])} урона")
        if lvl_up_notes:
            lines.append("   └ " + ", ".join(lvl_up_notes[:3]))

    summary_text = "\n".join(lines)
    chat_ids = list(b["messages"].keys())
    player_ids = list(b["players"].keys())
    await cleanup_battle(bid, bot)

    for cid in chat_ids:
        try:
            await bot.send_message(cid, summary_text)
        except Exception:
            pass

    # ФАЗА ЗАРАЖЕНИЯ БОССА (если убит хотя бы один Босс на карте)
    if bosses_killed:
        last_boss = bosses_killed[-1]
        base_ch = float(last_boss["infect_chance"])
        base_str = fmt_pct(base_ch)
        for uid in player_ids:
            u = await db.get_user(uid)
            PENDING_INFECTIONS[uid] = {
                "boss_name": last_boss["name"],
                "base_chance": base_ch,
                "infected_unit_id": int(last_boss["infected_unit_id"]),
            }
            kb_rows = []
            for p_key in ("common", "upgraded", "elite"):
                p_name, p_col, _, p_bonus = get_parasite_info(p_key)
                cnt = u[p_col]
                total_ch = calc_infect_chance(base_ch, p_bonus, u["pity_bonus"])
                kb_rows.append([
                    InlineKeyboardButton(
                        text=f"{p_name} ({cnt} шт.) — {fmt_pct(total_ch)}% ({base_str}% +{p_bonus}%)",
                        callback_data=f"td:inf:{p_key}",
                    )
                ])
            kb_rows.append([InlineKeyboardButton(text="❌ Пропустить", callback_data="td:inf:skip")])
            inf_text = (
                f"🦠 <b>ФАЗА ЗАРАЖЕНИЯ БОССА!</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"👑 Повержен: <b>{esc(last_boss['name'])}</b>\n"
                f"Базовый шанс: <b>{base_str}%</b> | 🎯 Пити: <b>+{u['pity_bonus']}%</b> от шанса\n"
                f"При успехе вы получите <b>🦠 Инфектед (x{cfg_float('infected_mult')})</b> версию босса!\n\n"
                f"👇 Выберите паразита для запуска:"
            )
            try:
                await bot.send_message(uid, inf_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
            except Exception:
                pass


async def cleanup_battle(bid: int, bot: Bot, notice: Optional[str] = None) -> None:
    b = ACTIVE_BATTLES.pop(bid, None)
    task = BATTLE_TASKS.pop(bid, None)
    if task and not task.done():
        task.cancel()
    if not b:
        return
    for uid in list(b["players"].keys()):
        if USER_TO_BATTLE.get(uid) == bid:
            USER_TO_BATTLE.pop(uid, None)
    for chat_id, msg_id in list(b["messages"].items()):
        try:
            await bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass
        if notice:
            try:
                await bot.send_message(chat_id, notice)
            except Exception:
                pass


# --- Обработчики кнопок внутри активной катки ---

@router.callback_query(F.data.startswith("b:md:"))
async def cb_b_mode(callback: CallbackQuery, bot: Bot):
    _, _, bid_s, mode = callback.data.split(":")
    bid = int(bid_s)
    b = ACTIVE_BATTLES.get(bid)
    if not b or callback.from_user.id not in b["players"]:
        await callback.answer("Вы не в этой катке.", show_alert=True)
        return
    b["players"][callback.from_user.id]["ui_mode"] = mode
    await update_battle_ui(bid, bot)
    await callback.answer()


@router.callback_query(F.data.startswith("b:sk:"))
async def cb_b_skip(callback: CallbackQuery, bot: Bot):
    bid = int(callback.data.split(":")[2])
    b = ACTIVE_BATTLES.get(bid)
    if not b or callback.from_user.id != b["host_id"]:
        await callback.answer("Только хост может менять Авто-скип!", show_alert=True)
        return
    b["auto_skip"] = not b["auto_skip"]
    await update_battle_ui(bid, bot)
    await callback.answer(f"Авто-скип: {'ВКЛ' if b['auto_skip'] else 'ВЫКЛ'}")


@router.callback_query(F.data.startswith("b:sr:"))
async def cb_b_surr(callback: CallbackQuery, bot: Bot):
    bid = int(callback.data.split(":")[2])
    b = ACTIVE_BATTLES.get(bid)
    if not b or callback.from_user.id != b["host_id"]:
        await callback.answer("Только хост может сдаться!", show_alert=True)
        return
    await callback.answer("🏳️ Вы сдались!")
    await finish_td_battle(bid, bot, is_win=False)


@router.callback_query(F.data.startswith("b:dp:"))
async def cb_b_deploy(callback: CallbackQuery, bot: Bot):
    _, _, bid_s, inv_s = callback.data.split(":")
    bid, inv_id = int(bid_s), int(inv_s)
    uid = callback.from_user.id
    b = ACTIVE_BATTLES.get(bid)
    if not b or uid not in b["players"]:
        await callback.answer("Вы не в этой катке.", show_alert=True)
        return
    p = b["players"][uid]
    item = next((c for c in p["deck"] if c["inv_id"] == inv_id), None)
    if not item:
        await callback.answer("Юнит не в вашей колоде.", show_alert=True)
        return
    st = calc_unit_battle_stats(item, 1)
    cnt = sum(1 for d in p["deployed"] if d["inv_id"] == inv_id)
    if cnt >= st["supply_limit"]:
        await callback.answer(f"Достигнут лимит ({st['supply_limit']} шт.)!", show_alert=True)
        return
    if p["coins"] < st["deploy_cost"]:
        await callback.answer(f"Недостаточно монет! Нужно {st['deploy_cost']} 💰.", show_alert=True)
        return
    p["coins"] -= st["deploy_cost"]
    p["deployed"].append({"inv_id": inv_id, "item": item, "tier": 1, "time_bank": 0.0, "slow_timer": 0.0})
    await update_battle_ui(bid, bot)
    await callback.answer(f"🛡 {item['name']} выставлен (-{st['deploy_cost']}💰)")

@router.callback_query(F.data.startswith("b:up:"))
async def cb_b_upgrade(callback: CallbackQuery, bot: Bot):
    _, _, bid_s, inv_s, tier_s = callback.data.split(":")
    bid, inv_id, tier = int(bid_s), int(inv_s), int(tier_s)
    uid = callback.from_user.id
    b = ACTIVE_BATTLES.get(bid)
    if not b or uid not in b["players"]:
        await callback.answer("Вы не в этой катке.", show_alert=True)
        return
    p = b["players"][uid]
    target = next((d for d in p["deployed"] if d["inv_id"] == inv_id and d["tier"] == tier), None)
    if not target:
        await callback.answer("Юнит не найден или уже улучшен!", show_alert=True)
        return
    nxt_tier = tier + 1
    cost = get_tier_upgrade_cost(target["item"], nxt_tier)
    if cost is None:
        await callback.answer("Максимальный тир в катке достигнут!", show_alert=True)
        return
    if p["coins"] < cost:
        await callback.answer(f"Недостаточно монет! Нужно {cost} 💰.", show_alert=True)
        return
    p["coins"] -= cost
    target["tier"] = nxt_tier
    await update_battle_ui(bid, bot)
    await callback.answer(f"⬆️ {target['item']['name']} ➔ Тир {nxt_tier} (-{cost}💰)")


# --- ФАЗА ЗАРАЖЕНИЯ БОССА (шанс = база + бонус паразита + пити) ---

@router.callback_query(F.data.startswith("td:inf:"))
async def cb_td_infect(callback: CallbackQuery):
    uid = callback.from_user.id
    inf = PENDING_INFECTIONS.get(uid)
    if not inf:
        await callback.answer("Фаза заражения уже завершена.", show_alert=True)
        return

    p_key = callback.data.split(":")[2]
    if p_key == "skip":
        PENDING_INFECTIONS.pop(uid, None)
        await render_view(callback, "💨 Вы пропустили заражение и вернулись на базу.")
        await callback.answer()
        return

    if p_key not in PARASITES_META:
        return
    p_name, p_col, _, p_bonus = get_parasite_info(p_key)
    u = await db.get_user(uid)
    if u[p_col] <= 0:
        await callback.answer(f"У вас нет «{p_name}»! Купите в «📦 Крейты и Лаба».", show_alert=True)
        return

    PENDING_INFECTIONS.pop(uid, None)
    await db.add_parasite(uid, p_key, -1)

    # Итоговый шанс: base * (1 + (p_bonus + pity) / 100), напр. 1% + 5% = 1.05%
    total_chance = calc_infect_chance(inf["base_chance"], p_bonus, u["pity_bonus"])
    ch_str = fmt_pct(total_chance)
    base_str = fmt_pct(inf["base_chance"])
    roll = random.random() * 100.0

    if roll < total_chance:
        target_unit = await db.get_unit(inf["infected_unit_id"]) if inf["infected_unit_id"] else None
        if not target_unit:
            all_u = await db.list_units()
            target_unit = next((x for x in all_u if x["faction"] == "infected"), all_u[0] if all_u else None)

        if not target_unit:
            await render_view(callback, "❌ В базе нет юнита для выдачи. Обратитесь к админу.")
            await callback.answer()
            return

        shiny = roll_shiny()
        await db.give_unit(uid, target_unit["id"], is_shiny=shiny, is_infected=1)
        await db.update_user(uid, infections_success=u["infections_success"] + 1, pity_bonus=0)

        sh_txt = f"\n✨ <b>ВЫПАЛ SHINY (+{cfg_int('shiny_bonus_pct')}%)!</b>" if shiny else ""
        text = (
            f"🦠💥 <b>УСПЕШНОЕ ЗАРАЖЕНИЕ!</b> (Шанс {ch_str}%: {base_str}% +{p_bonus}%)\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎁 Получен юнит: <b>{esc(target_unit['name'])}</b>\n"
            f"🧬 Статус: <b>🦠 Инфектед (x{cfg_float('infected_mult')} урон)</b>{sh_txt}\n\n"
            f"<i>Наденьте его в «🃏 Колода и Юниты»!</i>"
        )
        await render_view(callback, text, photo=target_unit.get("photo_id") or None)
        await callback.answer("🦠 ЗАРАЖЁН!", show_alert=True)
    else:
        new_pity = min(35, u["pity_bonus"] + 2)
        await db.update_user(uid, infections_fail=u["infections_fail"] + 1, pity_bonus=new_pity)
        await render_view(
            callback,
            f"💔 <b>ЗАРАЖЕНИЕ НЕ СРАБОТАЛО...</b> (Шанс {ch_str}%, выпало {roll:.2f})\n"
            f"{esc(inf['boss_name'])} сбросил паразита!\n"
            f"🎯 Пити заражения увеличен до <b>+{new_pity}%</b> от шанса.",
        )
        await callback.answer("Неудача, Пити вырос!")


# ==============================================================================
# 8. ЛАБОРАТОРИЯ ПАРАЗИТОВ И КРЕЙТЫ (С БАННЕРАМИ И SHINY)
# ==============================================================================

async def render_lab_and_crates(target: Message | CallbackQuery, user_id: int):
    u = await db.get_user(user_id)
    crates = await db.list_crates(only_active=True)

    cp, cb = cfg_int("p_common_price"), cfg_int("p_common_bonus")
    up, ub = cfg_int("p_upgraded_price"), cfg_int("p_upgraded_bonus")
    ep, eb = cfg_int("p_elite_price"), cfg_int("p_elite_bonus")

    text = (
        f"📦 <b>КРЕЙТЫ И ЛАБОРАТОРИЯ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Монеты: <b>{u['coins']}</b>\n"
        f"🦠 Паразиты: Обыч. <b>{u['p_common']}</b> | Улучш. <b>{u['p_upgraded']}</b> | Элит. <b>{u['p_elite']}</b>\n\n"
        f"🧪 <b>Паразиты (увеличивают шанс босса на % от числа, напр. 1% + 5% = 1.05%):</b>\n"
        f"• 🦠 Обычный: <b>+{cb}%</b> к шансу ({cp}💰)\n"
        f"• ☣️ Улучшенный: <b>+{ub}%</b> к шансу ({up}💰)\n"
        f"• 💎 Элитный: <b>+{eb}%</b> к шансу ({ep}💰)\n\n"
        f"📦 <b>Крейты (шанс ✨Shiny: {cfg_float('shiny_chance_pct')}%):</b>"
    )
    rows = [
        [
            InlineKeyboardButton(text=f"🦠 Обыч. ({cp}💰)", callback_data="lab:buy:common"),
            InlineKeyboardButton(text=f"☣️ Улучш. ({up}💰)", callback_data="lab:buy:upgraded"),
        ],
        [InlineKeyboardButton(text=f"💎 Элитный паразит ({ep}💰)", callback_data="lab:buy:elite")],
        [
            InlineKeyboardButton(text="⚗️ 3🦠 ➔ 1☣️", callback_data="lab:craft:upgraded"),
            InlineKeyboardButton(text="⚗️ 3☣️ ➔ 1💎", callback_data="lab:craft:elite"),
        ],
    ]
    for cr in crates:
        rows.append([InlineKeyboardButton(text=f"📦 {cr['name']} — {cr['price']} 💰", callback_data=f"cr:info:{cr['id']}")])

    await render_view(target, text, InlineKeyboardMarkup(inline_keyboard=rows))


@router.message(F.text == "📦 Крейты и Лаба")
async def menu_lab(message: Message, state: FSMContext):
    await state.clear()
    await render_lab_and_crates(message, message.from_user.id)


@router.callback_query(F.data == "lab:home")
async def cb_lab_home(callback: CallbackQuery):
    await render_lab_and_crates(callback, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data.startswith("lab:buy:"))
async def cb_lab_buy(callback: CallbackQuery):
    p_key = callback.data.split(":")[2]
    p_name, _, price, _ = get_parasite_info(p_key)
    u = await db.get_user(callback.from_user.id)
    if u["coins"] < price:
        await callback.answer(f"Нужно {price} 💰!", show_alert=True)
        return
    await db.add_coins(u["user_id"], -price)
    await db.add_parasite(u["user_id"], p_key, 1)
    await callback.answer(f"✅ Куплен: {p_name}!", show_alert=True)
    await render_lab_and_crates(callback, u["user_id"])


@router.callback_query(F.data.startswith("lab:craft:"))
async def cb_lab_craft(callback: CallbackQuery):
    target = callback.data.split(":")[2]
    src = "common" if target == "upgraded" else "upgraded"
    u = await db.get_user(callback.from_user.id)
    if u[PARASITES_META[src][1]] < 3:
        await callback.answer(f"Нужно 3 шт. «{PARASITES_META[src][0]}»!", show_alert=True)
        return
    await db.add_parasite(u["user_id"], src, -3)
    await db.add_parasite(u["user_id"], target, 1)
    await callback.answer(f"⚗️ Скрафчен: {PARASITES_META[target][0]}!", show_alert=True)
    await render_lab_and_crates(callback, u["user_id"])


@router.callback_query(F.data.startswith("cr:info:"))
async def cb_crate_info(callback: CallbackQuery):
    cid = int(callback.data.split(":")[2])
    cr = await db.get_crate(cid)
    if not cr or not cr["active"]:
        await callback.answer("Крейт недоступен.", show_alert=True)
        return
    units_map = cr["units"]
    total_w = sum(units_map.values())
    all_u = {str(x["id"]): x for x in await db.list_units()}

    lines = [
        f"📦 <b>{esc(cr['name'])}</b>",
        f"<i>{esc(cr['description'])}</i>" if cr["description"] else "",
        f"💰 Цена: <b>{cr['price']} монет</b> | ✨ Shiny: <b>{cfg_float('shiny_chance_pct')}%</b>",
        "━━━━━━━━━━━━━━━━━━",
        "🎲 <b>Шансы выпадения:</b>",
    ]
    if total_w > 0:
        sorted_entries = sorted(units_map.items(), key=lambda kv: kv[1], reverse=True)
        for uid_s, w in sorted_entries:
            u_obj = all_u.get(str(uid_s))
            if not u_obj:
                continue
            r_ico = RARITIES.get(u_obj["rarity"], ("", "⚪️", 1))[1]
            pct = (w / total_w) * 100.0
            lines.append(f"• {r_ico} <b>{esc(u_obj['name'])}</b> — {pct:.2f}%")
    else:
        lines.append("<i>Крейт пуст.</i>")

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"Открыть x1 ({cr['price']}💰)", callback_data=f"cr:open:{cid}:1"),
                InlineKeyboardButton(text=f"x5 ({cr['price'] * 5}💰)", callback_data=f"cr:open:{cid}:5"),
            ],
            [InlineKeyboardButton(text=f"Открыть x10 ({cr['price'] * 10}💰)", callback_data=f"cr:open:{cid}:10")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="lab:home")],
        ]
    )
    await render_view(callback, "\n".join(x for x in lines if x != ""), kb, photo=cr.get("photo_id") or None)
    await callback.answer()


@router.callback_query(F.data.startswith("cr:open:"))
async def cb_crate_open(callback: CallbackQuery):
    _, _, cid_s, amt_s = callback.data.split(":")
    cid, amt = int(cid_s), int(amt_s)
    cr = await db.get_crate(cid)
    if not cr or not cr["active"]:
        await callback.answer("Крейт недоступен.", show_alert=True)
        return
    u = await db.get_user(callback.from_user.id)
    cost = cr["price"] * amt
    if u["coins"] < cost:
        await callback.answer(f"Недостаточно монет! Нужно {cost} 💰.", show_alert=True)
        return

    all_u = {str(x["id"]): x for x in await db.list_units()}
    valid = [(all_u[k], float(v)) for k, v in cr["units"].items() if str(k) in all_u and float(v) > 0]
    if not valid:
        await callback.answer("В крейте нет доступных юнитов.", show_alert=True)
        return

    await db.add_coins(u["user_id"], -cost)
    pool = [x[0] for x in valid]
    weights = [x[1] for x in valid]
    dropped = random.choices(pool, weights=weights, k=amt)

    summary: Dict[Tuple[str, str, int], int] = {}
    last_photo = None
    for unit in dropped:
        sh = roll_shiny()
        await db.give_unit(u["user_id"], unit["id"], is_shiny=sh)
        r_ico = RARITIES.get(unit["rarity"], ("", "⚪️", 1))[1]
        key = (r_ico, unit["name"], sh)
        summary[key] = summary.get(key, 0) + 1
        if amt == 1:
            last_photo = unit.get("photo_id") or None

    lines = [f"🎉 <b>ОТКРЫТО {amt}x «{esc(cr['name'])}»</b>", "━━━━━━━━━━━━━━━━━━"]
    for (r_ico, name, sh), cnt in summary.items():
        sh_s = "✨ <b>SHINY</b> " if sh else ""
        lines.append(f"• {r_ico} {sh_s}<b>{esc(name)}</b> — x{cnt}")

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"🔁 Ещё x{amt} ({cost}💰)", callback_data=f"cr:open:{cid}:{amt}"),
                InlineKeyboardButton(text="🔙 К крейтам", callback_data="lab:home"),
            ]
        ]
    )
    await render_view(callback, "\n".join(lines), kb, photo=last_photo)
    await callback.answer("🎉 Открыто!")


# ==============================================================================
# 9. МУЛЬТИПЛЕЕР: КООП-ЛОББИ, МИРОВОЙ БОСС И P2P-РЫНОК (80% / 20% КОМИССИЯ)
# ==============================================================================

def mp_hub_kb() -> InlineKeyboardMarkup:
    open_cnt = sum(1 for b in ACTIVE_BATTLES.values() if not b["started"] and len(b["players"]) < 4)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"👥 Открытые Кооп-Лобби ({open_cnt})", callback_data="td:lobbies")],
            [InlineKeyboardButton(text="🌍 Мировой Босс (Общий рейд)", callback_data="mp:wb")],
            [InlineKeyboardButton(text="🏪 P2P Рынок игроков (80/20)", callback_data="mp:market:0")],
        ]
    )


@router.message(F.text == "🌐 Мультиплеер")
async def menu_mp(message: Message, state: FSMContext):
    await state.clear()
    wb = await db.get_active_world_boss()
    wb_st = f"🟢 АКТИВЕН ({esc(wb['name'])} — {wb['current_hp']} HP)" if wb else "⚪️ Спит"
    text = (
        f"🌐 <b>МУЛЬТИПЛЕЕР ХАБ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🌍 Мировой Босс: {wb_st}\n\n"
        f"• <b>👥 Кооп-Лобби:</b> заходи в катки к другим игрокам (до 4 человек) и делите награды + заражение босса.\n"
        f"• <b>🌍 Мировой Босс:</b> бейте общего босса всем сервером — Топ-3 получают монеты и шанс заразить его.\n"
        f"• <b>🏪 P2P Рынок:</b> продажа редких ✨Shiny, 🦠Инфектед и прокачанных юнитов (80% продавцу, 20% комиссия)."
    )
    await message.answer(text, reply_markup=mp_hub_kb())


@router.callback_query(F.data == "mp:hub")
async def cb_mp_hub(callback: CallbackQuery):
    wb = await db.get_active_world_boss()
    wb_st = f"🟢 {esc(wb['name'])} ({wb['current_hp']} HP)" if wb else "⚪️ Спит"
    await render_view(callback, f"🌐 <b>МУЛЬТИПЛЕЕР ХАБ</b>\n🌍 Мировой Босс: {wb_st}", mp_hub_kb())
    await callback.answer()


# --- МИРОВОЙ БОСС ---

async def render_world_boss(target: Message | CallbackQuery):
    wb = await db.get_active_world_boss()
    if not wb:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В Мультиплеер", callback_data="mp:hub")]])
        await render_view(target, "🌍 <b>МИРОВОЙ БОСС</b>\n\nСейчас Мировой Босс отдыхает. Ждите запуска от админа!", kb)
        return
    top = await db.get_world_boss_top(wb["id"], 5)
    top_lines = [f"{i}. {format_user_link(t)} — <b>{int(t['damage'])}</b> урона" for i, t in enumerate(top, 1)]
    text = (
        f"🌍 <b>МИРОВОЙ БОСС: {esc(wb['name'])}</b> (🛡{wb['defense_percent']}%)\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{make_bar(wb['current_hp'], wb['max_hp'], 10, '🟥', '⬛')}\n"
        f"❤️ HP: <b>{wb['current_hp']} / {wb['max_hp']}</b>\n\n"
        f"🏆 <b>Топ-5 по урону:</b>\n" + ("\n".join(top_lines) if top_lines else "<i>Ударь первым!</i>")
        + "\n\n🎁 Топ-3 при добивании получают крупные монеты и повышенный шанс заражения!"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚔️ Ударить колодой!", callback_data="mp:wb:hit")],
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="mp:wb"), InlineKeyboardButton(text="🔙 Назад", callback_data="mp:hub")],
        ]
    )
    await render_view(target, text, kb, photo=wb.get("photo_id") or None)


@router.callback_query(F.data == "mp:wb")
async def cb_wb(callback: CallbackQuery):
    await render_world_boss(callback)
    await callback.answer()


@router.callback_query(F.data == "mp:wb:hit")
async def cb_wb_hit(callback: CallbackQuery, bot: Bot):
    wb = await db.get_active_world_boss()
    if not wb:
        await callback.answer("Босс уже повержен!", show_alert=True)
        await render_world_boss(callback)
        return
    uid = callback.from_user.id
    prev = await db.get_world_boss_hit(wb["id"], uid)
    now = int(time.time())
    cd = cfg_int("wb_cooldown_sec")
    if prev and (now - prev["last_hit"]) < cd:
        await callback.answer(f"⏳ Перезарядка удара: {cd - (now - prev['last_hit'])} сек.", show_alert=True)
        return
    deck = await db.get_inventory(uid, only_equipped=True)
    if not deck:
        await callback.answer("Сначала наденьте юнитов в колоду!", show_alert=True)
        return

    # Урон = суммарный 10-секундный залп колоды с учётом брони Мирового Босса
    raw_dps = sum(calc_unit_battle_stats(c, 1)["dps"] for c in deck)
    dmg = max(10.0, round(raw_dps * 10.0 * (1.0 - wb["defense_percent"] / 100.0) * random.uniform(0.9, 1.15), 1))
    rem = await db.hit_world_boss(wb["id"], uid, dmg)

    # Юниты тоже получают XP за удар по Мировому Боссу!
    per_unit_xp = round((dmg / len(deck)) * UNIT_XP_PER_DAMAGE, 2)
    for c in deck:
        nl, nx, _ = apply_unit_xp(c["level"], c["xp"], per_unit_xp)
        await db.update_inv_progress(c["inv_id"], nl, nx)

    if rem <= 0:
        top = await db.get_world_boss_top(wb["id"], 10)
        reward_u = await db.get_unit(wb["infected_unit_id"]) if wb.get("infected_unit_id") else None
        wb_inf_chance = calc_infect_chance(wb["infect_chance"], 25)
        for idx, part in enumerate(top, 1):
            p_uid = part["user_id"]
            coins = int(max(150, 900 - (idx - 1) * 140) * cfg_float("event_coin_mult"))
            await db.add_coins(p_uid, coins)
            extra = ""
            if idx <= 3 and reward_u and (random.random() * 100.0) < wb_inf_chance:
                sh = roll_shiny()
                await db.give_unit(p_uid, reward_u["id"], is_shiny=sh, is_infected=1)
                extra = f"\n🦠 <b>ВЫ ЗАРАЗИЛИ МИРОВОГО БОССА!</b> Получен: <b>{esc(reward_u['name'])}</b>{' ✨SHINY!' if sh else ''}"
            try:
                await bot.send_message(
                    p_uid,
                    f"🌍🏆 <b>МИРОВОЙ БОСС {esc(wb['name'])} ПОВЕРЖЕН!</b>\n"
                    f"Место: <b>#{idx}</b> (урон: {int(part['damage'])}) | 💰 <b>+{coins}</b>{extra}",
                )
            except Exception:
                pass
        await callback.answer(f"💥 ФИНАЛЬНЫЙ УДАР -{int(dmg)}! Босс повержен!", show_alert=True)
    else:
        await callback.answer(f"⚔️ Нанесено {int(dmg)} урона! Осталось {rem} HP.", show_alert=True)
    await render_world_boss(callback)


# --- P2P РЫНОК (80% продавцу, 20% комиссия владельцу) ---

async def render_market_page(target: Message | CallbackQuery, user_id: int, page: int = 0):
    lots = await db.list_market()
    per_page = 6
    total_pages = max(1, (len(lots) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    chunk = lots[page * per_page : (page + 1) * per_page]

    text = (
        f"🏪 <b>P2P РЫНОК ИГРОКОВ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Комиссия рынка: <b>{MARKET_COMMISSION_PCT}%</b> (продавец получает <b>80%</b>).\n"
        f"Лотов: <b>{len(lots)}</b> | Стр. {page + 1}/{total_pages}"
    )
    rows = []
    for lot in chunk:
        r_ico = RARITIES.get(lot["rarity"], ("", "⚪️", 1))[1]
        b = unit_badges(lot)
        mine = " (Мой)" if lot["seller_id"] == user_id else ""
        rows.append([
            InlineKeyboardButton(
                text=f"{r_ico}{b} {lot['name']} Ур.{lot['level']} — {lot['price']}💰{mine}",
                callback_data=f"mkt:v:{lot['market_id']}:{page}",
            )
        ])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"mp:market:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"mp:market:{page + 1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔙 В Мультиплеер", callback_data="mp:hub")])
    await render_view(target, text, InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("mp:market:"))
async def cb_market_page(callback: CallbackQuery):
    await render_market_page(callback, callback.from_user.id, int(callback.data.split(":")[2]))
    await callback.answer()


@router.callback_query(F.data.startswith("mkt:v:"))
async def cb_market_view(callback: CallbackQuery):
    _, _, lot_s, page_s = callback.data.split(":")
    lot_id, page = int(lot_s), int(page_s)
    lot = next((x for x in await db.list_market() if x["market_id"] == lot_id), None)
    if not lot:
        await callback.answer("Лот больше не существует.", show_alert=True)
        await render_market_page(callback, callback.from_user.id, page)
        return
    st = calc_unit_battle_stats(lot, 1)
    text = (
        f"🏷 <b>ЛОТ #{lot['market_id']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🃏 <b>{esc(lot['name'])}</b> {unit_badges(lot)} (Ур. {lot['level']}/{MAX_UNIT_LEVEL})\n"
        f"🏷 Классы: <b>{', '.join(st['classes'])}</b>\n"
        f"⚔️ Урон: <b>{st['damage']}</b> | ⏱ {st['cd']}с | ⚡ DPS: <b>{st['dps']}/с</b> | 💰 Поставка: <b>{st['deploy_cost']}</b>\n"
        f"✍️ Сигна: {get_sign_label(lot)}\n"
        f"👤 Продавец: <b>{esc(lot['seller_name'] or 'Игрок')}</b>\n"
        f"💰 Цена: <b>{lot['price']} монет</b>"
    )
    act = (
        InlineKeyboardButton(text="❌ Снять с продажи", callback_data=f"mkt:c:{lot_id}:{page}")
        if lot["seller_id"] == callback.from_user.id
        else InlineKeyboardButton(text=f"✅ Купить за {lot['price']} 💰", callback_data=f"mkt:b:{lot_id}:{page}")
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[act], [InlineKeyboardButton(text="🔙 Назад", callback_data=f"mp:market:{page}")]])
    await render_view(callback, text, kb, photo=lot.get("photo_id") or None)
    await callback.answer()


@router.callback_query(F.data.startswith("mkt:b:"))
async def cb_market_buy(callback: CallbackQuery, bot: Bot):
    _, _, lot_s, page_s = callback.data.split(":")
    ok, msg, lot = await db.buy_market_lot(int(lot_s), callback.from_user.id)
    await callback.answer(msg, show_alert=True)
    if ok and lot:
        try:
            await bot.send_message(
                lot["seller_id"],
                f"💰 <b>ВАШЕГО ЮНИТА КУПИЛИ НА РЫНКЕ!</b>\n"
                f"Юнит: <b>{esc(lot['name'])}</b>\n"
                f"Цена сделки: {lot['price']} 💰 | Зачислено вам (80%): <b>+{lot['seller_payout']} 💰</b>",
            )
        except Exception:
            pass
    await render_market_page(callback, callback.from_user.id, int(page_s))


@router.callback_query(F.data.startswith("mkt:c:"))
async def cb_market_cancel(callback: CallbackQuery):
    _, _, lot_s, page_s = callback.data.split(":")
    ok = await db.cancel_market_lot(int(lot_s), callback.from_user.id)
    await callback.answer("Лот снят!" if ok else "Ошибка.", show_alert=True)
    await render_market_page(callback, callback.from_user.id, int(page_s))


# ==============================================================================
# 10. РЕЙТИНГИ
# ==============================================================================

async def render_top(target: Message | CallbackQuery, mode: str = "wins"):
    meta = {
        "wins": ("🏆 Топ по Победам в катках", "побед"),
        "total_damage": ("💥 Топ по Общему Урону", "урона"),
        "infections_success": ("🦠 Топ по Заражениям", "зараж."),
        "bosses_killed": ("👹 Топ Охотников на Боссов", "боссов"),
        "coins": ("💰 Топ Богачей", "монет"),
    }
    title, unit = meta.get(mode, meta["wins"])
    rows_db = await db.get_leaderboard(mode, 10)
    medals = ["🥇", "🥈", "🥉"]
    lines = [f"<b>{title}</b>", "━━━━━━━━━━━━━━━━━━"]
    for i, r in enumerate(rows_db, 1):
        m = medals[i - 1] if i <= 3 else f"<b>{i}.</b>"
        val = int(r["val"])
        lines.append(f"{m} {format_user_link(r)} — <b>{val}</b> {unit}")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🏆 Победы", callback_data="top:wins"),
                InlineKeyboardButton(text="💥 Урон", callback_data="top:total_damage"),
                InlineKeyboardButton(text="🦠 Зараж.", callback_data="top:infections_success"),
            ],
            [
                InlineKeyboardButton(text="👹 Боссы", callback_data="top:bosses_killed"),
                InlineKeyboardButton(text="💰 Монеты", callback_data="top:coins"),
            ],
        ]
    )
    await render_view(target, "\n".join(lines), kb)


@router.message(F.text == "🏆 Рейтинг")
async def menu_top(message: Message, state: FSMContext):
    await state.clear()
    await render_top(message, "wins")


@router.callback_query(F.data.startswith("top:"))
async def cb_top(callback: CallbackQuery):
    await render_top(callback, callback.data.split(":")[1])
    await callback.answer()


# ==============================================================================
# 11. РАСШИРЕННАЯ АДМИН-ПАНЕЛЬ (ГРАНУЛЯРНЫЕ ПРАВА + ВСЕ КОНСТРУКТОРЫ)
# ==============================================================================

async def render_admin_home(target: Message | CallbackQuery, uid: int):
    perms = await db.get_admin_perms(uid)
    st = await db.get_global_stats()
    maint = "🔴 ВКЛ" if GAME_SETTINGS.get("maintenance") == "1" else "🟢 ВЫКЛ"
    text = (
        f"⚙️ <b>АДМИН-ПАНЕЛЬ SKIBIDI VERSE TD</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👥 Игроков: <b>{st['users']}</b> | 🃏 Юнитов: <b>{st['units']}</b> | 👾 Мобов: <b>{st['mobs']}</b>\n"
        f"🗺 Карт: <b>{st['maps']}</b> | 📦 Крейтов: <b>{st['crates']}</b> | 🏪 Рынок: <b>{st['market']}</b>\n"
        f"🛠 Техработы: <b>{maint}</b>"
    )
    rows = []
    r1 = []
    if perms.get("manage_units"):
        r1.append(InlineKeyboardButton(text="🃏 Юниты", callback_data="adm:units:0"))
    if perms.get("manage_mobs"):
        r1.append(InlineKeyboardButton(text="👾 Мобы", callback_data="adm:mobs:0"))
    if r1:
        rows.append(r1)

    r2 = []
    if perms.get("manage_maps"):
        r2.append(InlineKeyboardButton(text="🗺 Карты и Волны", callback_data="adm:maps:0"))
    if perms.get("manage_crates"):
        r2.append(InlineKeyboardButton(text="📦 Крейты", callback_data="adm:crates:0"))
    if r2:
        rows.append(r2)

    r3 = []
    if perms.get("manage_settings"):
        r3.append(InlineKeyboardButton(text="🎛 Настройки баланса", callback_data="adm:set:0"))
    if perms.get("manage_bosses"):
        r3.append(InlineKeyboardButton(text="🌍 Мировой Босс", callback_data="adm:wb"))
    if r3:
        rows.append(r3)

    r4 = []
    if perms.get("manage_users") or perms.get("manage_economy"):
        r4.append(InlineKeyboardButton(text="👥 Игроки и Выдача", callback_data="adm:users"))
    if perms.get("broadcast"):
        r4.append(InlineKeyboardButton(text="📢 Рассылка", callback_data="adm:bcast"))
    if r4:
        rows.append(r4)

    if perms.get("manage_admins"):
        rows.append([
            InlineKeyboardButton(text="👮 Админы", callback_data="adm:admins"),
            InlineKeyboardButton(text="🤝 Партнёры", callback_data="adm:signers"),
        ])
        rows.append([
            InlineKeyboardButton(text=f"🛠 Техработы ({maint})", callback_data="adm:maint"),
            InlineKeyboardButton(text="💾 Бэкап БД", callback_data="adm:backup"),
        ])
        rows.append([InlineKeyboardButton(text="📋 Логи админов", callback_data="adm:logs")])

    await render_view(target, text, InlineKeyboardMarkup(inline_keyboard=rows))


@router.message(F.text == "⚙️ Админ-панель")
async def menu_admin(message: Message, state: FSMContext, is_admin: bool):
    if not is_admin:
        return
    await state.clear()
    await render_admin_home(message, message.from_user.id)


@router.callback_query(F.data == "adm:home")
async def cb_adm_home(callback: CallbackQuery, state: FSMContext):
    if not await db.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа!", show_alert=True)
        return
    await state.clear()
    await render_admin_home(callback, callback.from_user.id)
    await callback.answer()


# ==================== АДМИН: ЮНИТЫ (СОЗДАНИЕ, РЕДАКТОР, ТИРЫ, КНОКБЕК) ====================

async def render_adm_units(target: Message | CallbackQuery, page: int = 0):
    units = await db.list_units()
    per_page = 6
    total_pages = max(1, (len(units) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    chunk = units[page * per_page : (page + 1) * per_page]

    rows = [[InlineKeyboardButton(text="➕ Создать нового Юнита", callback_data="au:new")]]
    for u in chunk:
        r_ico = RARITIES.get(u["rarity"], ("", "⚪️", 1))[1]
        rows.append([InlineKeyboardButton(text=f"{r_ico} #{u['id']} {u['name']} (⚔️{u['damage']} | 💰{u['deploy_cost']})", callback_data=f"au:ed:{u['id']}:{page}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"adm:units:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"adm:units:{page + 1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")])
    await render_view(target, f"🃏 <b>УПРАВЛЕНИЕ ЮНИТАМИ</b> (Всего: {len(units)})", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("adm:units:"))
async def cb_adm_units(callback: CallbackQuery):
    if not await db.has_perm(callback.from_user.id, "manage_units"):
        await callback.answer("Нет прав manage_units!", show_alert=True)
        return
    await render_adm_units(callback, int(callback.data.split(":")[2]))
    await callback.answer()


def unit_classes_kb(selected: List[str], prefix: str) -> InlineKeyboardMarkup:
    rows, row = [], []
    for c in UNIT_CLASSES:
        mark = "✅" if c in selected else "⬜"
        row.append(InlineKeyboardButton(text=f"{mark} {c}", callback_data=f"{prefix}:{c}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="💾 Готово / Далее", callback_data=f"{prefix}:DONE")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "au:new")
async def cb_au_new(callback: CallbackQuery, state: FSMContext):
    if not await db.has_perm(callback.from_user.id, "manage_units"):
        await callback.answer("Нет прав!", show_alert=True)
        return
    await state.set_state(UnitCreateFSM.classes)
    await state.update_data(classes=[])
    await render_view(callback, "🃏 <b>Создание Юнита — Шаг 1</b>\nВыберите классы (можно несколько, включая <b>Кнокбек</b>):", unit_classes_kb([], "ucls"))
    await callback.answer()


@router.callback_query(UnitCreateFSM.classes, F.data.startswith("ucls:"))
async def fsm_au_classes(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":")[1]
    data = await state.get_data()
    cls = list(data.get("classes", []))
    if val == "DONE":
        if not cls:
            await callback.answer("Выберите хотя бы 1 класс!", show_alert=True)
            return
        await state.set_state(UnitCreateFSM.name)
        await callback.message.answer("📝 Введите <b>название</b> юнита:")
        await callback.answer()
        return
    if val in cls:
        cls.remove(val)
    else:
        cls.append(val)
    await state.update_data(classes=cls)
    await callback.message.edit_reply_markup(reply_markup=unit_classes_kb(cls, "ucls"))
    await callback.answer()


@router.message(UnitCreateFSM.name)
async def fsm_au_name(message: Message, state: FSMContext):
    await state.update_data(name=(message.text or "").strip())
    await state.set_state(UnitCreateFSM.faction)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=v, callback_data=f"ufac:{k}")] for k, v in FACTIONS.items()])
    await message.answer("🏷 Выберите <b>фракцию</b>:", reply_markup=kb)


@router.callback_query(UnitCreateFSM.faction, F.data.startswith("ufac:"))
async def fsm_au_faction(callback: CallbackQuery, state: FSMContext):
    await state.update_data(faction=callback.data.split(":")[1])
    await state.set_state(UnitCreateFSM.rarity)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{ico} {n}", callback_data=f"urar:{k}")] for k, (n, ico, _) in RARITIES.items()])
    await render_view(callback, "🌟 Выберите <b>редкость</b>:", kb)
    await callback.answer()


@router.callback_query(UnitCreateFSM.rarity, F.data.startswith("urar:"))
async def fsm_au_rarity(callback: CallbackQuery, state: FSMContext):
    await state.update_data(rarity=callback.data.split(":")[1])
    await state.set_state(UnitCreateFSM.photo)
    await callback.message.answer("🖼 Отправьте <b>фото</b> юнита (или напишите <code>-</code> чтобы пропустить):")
    await callback.answer()


@router.message(UnitCreateFSM.photo)
async def fsm_au_photo(message: Message, state: FSMContext):
    pid = message.photo[-1].file_id if message.photo else ""
    await state.update_data(photo_id=pid)
    await state.set_state(UnitCreateFSM.deploy_cost)
    await message.answer("💰 Введите <b>цену поставки</b> и <b>лимит на поле</b> через пробел (например: <code>120 4</code>):")


@router.message(UnitCreateFSM.deploy_cost)
async def fsm_au_cost_limit(message: Message, state: FSMContext):
    parts = (message.text or "").split()
    try:
        cost = int(parts[0])
        lim = int(parts[1]) if len(parts) > 1 else 4
    except (ValueError, IndexError):
        await message.answer("❌ Введите два числа, например: <code>120 4</code>")
        return
    await state.update_data(deploy_cost=cost, supply_limit=lim)
    await _au_next_class_step(message, state)


async def _au_next_class_step(message: Message, state: FSMContext):
    d = await state.get_data()
    cls = d.get("classes", [])
    if any(c in ATTACKING_CLASSES for c in cls) and "damage" not in d:
        await state.set_state(UnitCreateFSM.atk_stats)
        await message.answer("⚔️ Введите <b>Урон</b> и <b>КД (сек)</b> через пробел (например: <code>45 1.3</code>):")
        return
    if "Саппорт" in cls and "cd_boost" not in d:
        await state.set_state(UnitCreateFSM.support_stats)
        await message.answer("✨ <b>[Саппорт]</b> Введите <b>множитель КД</b> и <b>множитель Урона</b> через пробел (например: <code>0.85 1.25</code>):")
        return
    if "Ферма" in cls and "income" not in d:
        await state.set_state(UnitCreateFSM.farm_income)
        await message.answer("🌾 <b>[Ферма]</b> Введите доход монет за волну (число, например <code>60</code>):")
        return
    if "Замедление" in cls and "slow_percent" not in d:
        await state.set_state(UnitCreateFSM.slow_stats)
        await message.answer("❄️ <b>[Замедление]</b> Введите <b>% замедления</b>, <b>длительность (ходы)</b> и <b>КД (сек)</b> через пробел (например: <code>25 2 10</code>):")
        return
    if "Оглушение" in cls and "stun_chance" not in d:
        await state.set_state(UnitCreateFSM.stun_stats)
        await message.answer("⚡ <b>[Оглушение]</b> Введите <b>шанс %</b> и <b>длительность (ходы)</b> через пробел (например: <code>20 1</code>):")
        return
    if "Горение" in cls and "burn_chance" not in d:
        await state.set_state(UnitCreateFSM.burn_stats)
        await message.answer("🔥 <b>[Горение]</b> Введите <b>шанс %</b>, <b>урон/ход</b> и <b>длительность (ходы)</b> (например: <code>40 20 3</code>):")
        return
    if "Кнокбек" in cls and "knockback_power" not in d:
        await state.set_state(UnitCreateFSM.knockback_power)
        await message.answer("💨 <b>[Кнокбек]</b> Введите силу отталкивания (любое число, например <code>4</code>, <code>6</code>, <code>8</code>):")
        return

    await state.set_state(UnitCreateFSM.description)
    await message.answer("📝 Введите короткое <b>описание</b> юнита (или <code>-</code>):")


@router.message(UnitCreateFSM.atk_stats)
async def fsm_au_atk(message: Message, state: FSMContext):
    p = (message.text or "").replace(",", ".").split()
    try:
        dmg, cd = float(p[0]), float(p[1])
    except (ValueError, IndexError):
        await message.answer("❌ Пример: <code>45 1.3</code>")
        return
    await state.update_data(damage=dmg, cd=cd)
    await _au_next_class_step(message, state)


@router.message(UnitCreateFSM.support_stats)
async def fsm_au_sup(message: Message, state: FSMContext):
    p = (message.text or "").replace(",", ".").split()
    try:
        cb, db_ = float(p[0]), float(p[1])
    except (ValueError, IndexError):
        await message.answer("❌ Пример: <code>0.85 1.25</code>")
        return
    await state.update_data(cd_boost=cb, dmg_boost=db_)
    await _au_next_class_step(message, state)


@router.message(UnitCreateFSM.farm_income)
async def fsm_au_farm(message: Message, state: FSMContext):
    try:
        inc = int((message.text or "").strip())
    except ValueError:
        await message.answer("❌ Введите число.")
        return
    await state.update_data(income=inc)
    await _au_next_class_step(message, state)


@router.message(UnitCreateFSM.slow_stats)
async def fsm_au_slow(message: Message, state: FSMContext):
    p = (message.text or "").replace(",", ".").split()
    try:
        sp, sd, scd = int(p[0]), float(p[1]), float(p[2])
    except (ValueError, IndexError):
        await message.answer("❌ Пример: <code>25 2 10</code>")
        return
    await state.update_data(slow_percent=sp, slow_duration=sd, slow_cd=scd)
    await _au_next_class_step(message, state)


@router.message(UnitCreateFSM.stun_stats)
async def fsm_au_stun(message: Message, state: FSMContext):
    p = (message.text or "").split()
    try:
        sc, sd = int(p[0]), int(p[1])
    except (ValueError, IndexError):
        await message.answer("❌ Пример: <code>20 1</code>")
        return
    await state.update_data(stun_chance=sc, stun_duration=sd)
    await _au_next_class_step(message, state)


@router.message(UnitCreateFSM.burn_stats)
async def fsm_au_burn(message: Message, state: FSMContext):
    p = (message.text or "").replace(",", ".").split()
    try:
        bc, bd, bdur = int(p[0]), float(p[1]), int(p[2])
    except (ValueError, IndexError):
        await message.answer("❌ Пример: <code>40 20 3</code>")
        return
    await state.update_data(burn_chance=bc, burn_damage=bd, burn_duration=bdur)
    await _au_next_class_step(message, state)


@router.message(UnitCreateFSM.knockback_power)
async def fsm_au_kb(message: Message, state: FSMContext):
    try:
        kp = float((message.text or "").replace(",", ".").strip())
    except ValueError:
        await message.answer("❌ Введите число (например <code>4</code> или <code>6</code>).")
        return
    await state.update_data(knockback_power=kp)
    await _au_next_class_step(message, state)


@router.message(UnitCreateFSM.description)
async def fsm_au_desc(message: Message, state: FSMContext):
    txt = (message.text or "").strip()
    await state.update_data(description="" if txt == "-" else txt)
    d = await state.get_data()
    uid_new = await db.create_unit(d)
    await db.log_admin(message.from_user.id, f"Создал юнита #{uid_new} {d['name']}")
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✏️ Редактировать / Добавить Тиры", callback_data=f"au:ed:{uid_new}:0")]])
    await message.answer(f"✅ Юнит <b>{esc(d['name'])}</b> (#{uid_new}) успешно создан!", reply_markup=kb)


async def render_adm_unit_editor(target: Message | CallbackQuery, unit_id: int, page: int):
    u = await db.get_unit(unit_id)
    if not u:
        await render_adm_units(target, page)
        return
    fake_item = {**u, "level": 1, "xp": 0, "is_shiny": 0, "is_infected": 0, "sign_type": "none", "signed_by": "", "equip_slot": 0}
    txt = f"🛠 <b>РЕДАКТОР ЮНИТА #{u['id']}</b>\n" + format_unit_info_card(fake_item, 0, 0, False)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Имя", callback_data=f"au:f:{unit_id}:name:{page}"), InlineKeyboardButton(text="🖼 Фото", callback_data=f"au:f:{unit_id}:photo_id:{page}")],
            [InlineKeyboardButton(text="⚔️ Урон", callback_data=f"au:f:{unit_id}:damage:{page}"), InlineKeyboardButton(text="⏱ КД", callback_data=f"au:f:{unit_id}:cd:{page}")],
            [InlineKeyboardButton(text="💰 Цена", callback_data=f"au:f:{unit_id}:deploy_cost:{page}"), InlineKeyboardButton(text="🛑 Лимит", callback_data=f"au:f:{unit_id}:supply_limit:{page}")],
            [InlineKeyboardButton(text="💨 Кнокбек", callback_data=f"au:f:{unit_id}:knockback_power:{page}"), InlineKeyboardButton(text="🌾 Ферма", callback_data=f"au:f:{unit_id}:income:{page}")],
            [InlineKeyboardButton(text="🌟 Редкость", callback_data=f"au:f:{unit_id}:rarity:{page}"), InlineKeyboardButton(text="🏷 Классы", callback_data=f"au:cls:{unit_id}:{page}")],
            [InlineKeyboardButton(text="⬆️ Настроить Тиры (2..4)", callback_data=f"au:upg:{unit_id}:{page}")],
            [InlineKeyboardButton(text="🗑 Удалить юнита", callback_data=f"au:del:{unit_id}:{page}")],
            [InlineKeyboardButton(text="🔙 К юнитам", callback_data=f"adm:units:{page}")],
        ]
    )
    await render_view(target, txt, kb, photo=u.get("photo_id") or None)


@router.callback_query(F.data.startswith("au:ed:"))
async def cb_au_ed(callback: CallbackQuery):
    _, _, u_s, p_s = callback.data.split(":")
    await render_adm_unit_editor(callback, int(u_s), int(p_s))
    await callback.answer()


@router.callback_query(F.data.startswith("au:f:"))
async def cb_au_field(callback: CallbackQuery, state: FSMContext):
    _, _, u_s, field, p_s = callback.data.split(":")
    await state.set_state(UnitEditFSM.waiting_value)
    await state.update_data(unit_id=int(u_s), field=field, page=int(p_s))
    hint = "Отправьте новое фото (или `-`):" if field == "photo_id" else (
        f"Введите редкость ({', '.join(RARITIES.keys())}):" if field == "rarity" else f"Введите новое значение для <b>{field}</b>:"
    )
    await callback.message.answer(hint)
    await callback.answer()


@router.message(UnitEditFSM.waiting_value)
async def fsm_au_field_save(message: Message, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    uid_e, field, page = d["unit_id"], d["field"], d["page"]
    try:
        if field == "photo_id":
            val: Any = message.photo[-1].file_id if message.photo else ""
        elif field in ("deploy_cost", "supply_limit", "income"):
            val = int((message.text or "").strip())
        elif field in ("damage", "cd", "knockback_power"):
            val = float((message.text or "").replace(",", ".").strip())
        elif field == "rarity":
            val = (message.text or "").strip().lower()
            if val not in RARITIES:
                raise ValueError
        else:
            val = (message.text or "").strip()
    except ValueError:
        await message.answer("❌ Неверный формат значения.")
        return
    await db.update_unit(uid_e, **{field: val})
    await db.log_admin(message.from_user.id, f"Изменил юнита #{uid_e}: {field}")
    await message.answer("✅ Сохранено!")
    await render_adm_unit_editor(message, uid_e, page)


@router.callback_query(F.data.startswith("au:cls:"))
async def cb_au_cls_open(callback: CallbackQuery, state: FSMContext):
    _, _, u_s, p_s = callback.data.split(":")
    u = await db.get_unit(int(u_s))
    if not u:
        return
    await state.update_data(ed_u_id=u["id"], ed_u_page=int(p_s), ed_u_cls=list(u["classes"]))
    await render_view(callback, f"🏷 Классы для <b>{esc(u['name'])}</b>:", unit_classes_kb(u["classes"], "eucls"))
    await callback.answer()


@router.callback_query(F.data.startswith("eucls:"))
async def cb_eucls_toggle(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":")[1]
    d = await state.get_data()
    cls = list(d.get("ed_u_cls", []))
    if val == "DONE":
        await db.update_unit(d["ed_u_id"], classes=cls or ["Одиночный"])
        await state.clear()
        await render_adm_unit_editor(callback, d["ed_u_id"], d["ed_u_page"])
        await callback.answer("✅ Классы сохранены!")
        return
    if val in cls:
        cls.remove(val)
    else:
        cls.append(val)
    await state.update_data(ed_u_cls=cls)
    await callback.message.edit_reply_markup(reply_markup=unit_classes_kb(cls, "eucls"))
    await callback.answer()


@router.callback_query(F.data.startswith("au:upg:"))
async def cb_au_upg(callback: CallbackQuery, state: FSMContext):
    _, _, u_s, p_s = callback.data.split(":")
    await state.set_state(UnitEditFSM.upg_tier)
    await state.update_data(upg_u_id=int(u_s), upg_page=int(p_s))
    await callback.message.answer(
        "⬆️ <b>Настройка Тира апгрейда в катке</b>\n"
        "Введите номер тира (например <code>2</code>, <code>3</code> или <code>4</code>):"
    )
    await callback.answer()


@router.message(UnitEditFSM.upg_tier)
async def fsm_au_upg_tier(message: Message, state: FSMContext):
    try:
        tier = int((message.text or "").strip())
        if not (2 <= tier <= 6):
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите число от 2 до 6.")
        return
    await state.update_data(upg_tier=tier)
    await state.set_state(UnitEditFSM.upg_data)
    await message.answer(
        f"Введите параметры для <b>Тира {tier}</b> в формате:\n"
        f"<code>цена урон кд кнокбек доход</code>\n"
        f"Ставьте <code>-</code>, если параметр не меняется (пример: <code>250 80 1.1 6 -</code>):"
    )


@router.message(UnitEditFSM.upg_data)
async def fsm_au_upg_save(message: Message, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    parts = (message.text or "").replace(",", ".").split()
    try:
        entry: Dict[str, Any] = {"cost": int(parts[0])}
        if len(parts) > 1 and parts[1] != "-":
            entry["damage"] = float(parts[1])
        if len(parts) > 2 and parts[2] != "-":
            entry["cd"] = float(parts[2])
        if len(parts) > 3 and parts[3] != "-":
            entry["knockback_power"] = float(parts[3])
        if len(parts) > 4 and parts[4] != "-":
            entry["income"] = int(parts[4])
    except (ValueError, IndexError):
        await message.answer("❌ Неверный формат! Пример: <code>250 80 1.1 - -</code>")
        return
    u = await db.get_unit(d["upg_u_id"])
    upgs = dict(u["upgrades"])
    upgs[str(d["upg_tier"])] = entry
    await db.update_unit(u["id"], upgrades=upgs)
    await message.answer(f"✅ Тир {d['upg_tier']} сохранён!")
    await render_adm_unit_editor(message, u["id"], d["upg_page"])


@router.callback_query(F.data.startswith("au:del:"))
async def cb_au_del(callback: CallbackQuery):
    _, _, u_s, p_s = callback.data.split(":")
    await db.delete_unit(int(u_s))
    await db.log_admin(callback.from_user.id, f"Удалил юнита #{u_s}")
    await callback.answer("🗑 Юнит удалён!", show_alert=True)
    await render_adm_units(callback, int(p_s))


# ==================== АДМИН: МОБЫ (ТОЛЬКО HP, % БРОНИ, БОСС И ЗАРАЖЕНИЕ) ====================

async def render_adm_mobs(target: Message | CallbackQuery, page: int = 0):
    mobs = await db.list_mobs()
    per_page = 6
    total_pages = max(1, (len(mobs) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    chunk = mobs[page * per_page : (page + 1) * per_page]

    rows = [[InlineKeyboardButton(text="➕ Создать нового Моба", callback_data="am:new")]]
    for m in chunk:
        ico = "👑" if m["is_boss"] else "👾"
        rows.append([InlineKeyboardButton(text=f"{ico} #{m['id']} {m['name']} (❤️{m['hp']} | 🛡{m['defense_percent']}%)", callback_data=f"am:ed:{m['id']}:{page}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"adm:mobs:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"adm:mobs:{page + 1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")])
    await render_view(target, f"👾 <b>УПРАВЛЕНИЕ МОБАМИ</b> (Всего: {len(mobs)})", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("adm:mobs:"))
async def cb_adm_mobs(callback: CallbackQuery):
    if not await db.has_perm(callback.from_user.id, "manage_mobs"):
        await callback.answer("Нет прав manage_mobs!", show_alert=True)
        return
    await render_adm_mobs(callback, int(callback.data.split(":")[2]))
    await callback.answer()


@router.callback_query(F.data == "am:new")
async def cb_am_new(callback: CallbackQuery, state: FSMContext):
    await state.set_state(MobCreateFSM.name)
    await callback.message.answer("👾 Введите <b>название</b> моба:")
    await callback.answer()


@router.message(MobCreateFSM.name)
async def fsm_am_name(message: Message, state: FSMContext):
    await state.update_data(name=(message.text or "").strip())
    await state.set_state(MobCreateFSM.hp)
    await message.answer("❤️ Введите <b>HP моба</b> и <b>% брони</b> через пробел (например: <code>500 20</code>, без брони — <code>500 0</code>):")


@router.message(MobCreateFSM.hp)
async def fsm_am_hp_def(message: Message, state: FSMContext):
    p = (message.text or "").split()
    try:
        hp = int(p[0])
        df = max(0, min(90, int(p[1]) if len(p) > 1 else 0))
    except (ValueError, IndexError):
        await message.answer("❌ Пример: <code>500 20</code>")
        return
    await state.update_data(hp=hp, defense_percent=df)
    await state.set_state(MobCreateFSM.photo)
    await message.answer("🖼 Отправьте <b>фото</b> моба (или <code>-</code>):")


@router.message(MobCreateFSM.photo)
async def fsm_am_photo(message: Message, state: FSMContext):
    pid = message.photo[-1].file_id if message.photo else ""
    await state.update_data(photo_id=pid)
    await state.set_state(MobCreateFSM.is_boss)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👑 Да, Босс (заражаемый)", callback_data="amb:1"), InlineKeyboardButton(text="👾 Обычный моб", callback_data="amb:0")]])
    await message.answer("Этот моб является <b>Боссом</b> с механикой заражения?", reply_markup=kb)


@router.callback_query(MobCreateFSM.is_boss, F.data.startswith("amb:"))
async def fsm_am_boss(callback: CallbackQuery, state: FSMContext):
    is_b = int(callback.data.split(":")[1])
    await state.update_data(is_boss=is_b)
    if is_b == 0:
        d = await state.get_data()
        mid = await db.create_mob(d)
        await db.log_admin(callback.from_user.id, f"Создал моба #{mid} {d['name']}")
        await state.clear()
        await render_view(callback, f"✅ Моб <b>{esc(d['name'])}</b> (#{mid}) создан!")
        await callback.answer()
        return
    units = await db.list_units()
    hint = "\n".join(f"<code>{u['id']}</code> — {esc(u['name'])}" for u in units[-12:])
    await state.set_state(MobCreateFSM.infect_cfg)
    await callback.message.answer(
        f"🦠 Введите <b>базовый шанс заражения (%)</b> и <b>ID заражённого юнита</b> через пробел (например: <code>1 8</code>):\n\n{hint}"
    )
    await callback.answer()


@router.message(MobCreateFSM.infect_cfg)
async def fsm_am_inf(message: Message, state: FSMContext):
    p = (message.text or "").split()
    try:
        ch, uid_inf = int(p[0]), int(p[1])
    except (ValueError, IndexError):
        await message.answer("❌ Пример: <code>1 8</code>")
        return
    await state.update_data(infect_chance=ch, infected_unit_id=uid_inf)
    d = await state.get_data()
    mid = await db.create_mob(d)
    await db.log_admin(message.from_user.id, f"Создал босса #{mid} {d['name']}")
    await state.clear()
    await message.answer(f"✅ Босс <b>{esc(d['name'])}</b> (#{mid}) создан! (Баз. шанс заражения: {ch}%)")


async def render_adm_mob_editor(target: Message | CallbackQuery, mob_id: int, page: int):
    m = await db.get_mob(mob_id)
    if not m:
        await render_adm_mobs(target, page)
        return
    txt = (
        f"👾 <b>МОБ #{m['id']} — {esc(m['name'])}</b>\n"
        f"❤️ HP: <b>{m['hp']}</b> | 🛡 Броня: <b>{m['defense_percent']}%</b>\n"
        f"👑 Босс: <b>{'Да' if m['is_boss'] else 'Нет'}</b> | 🦠 Баз. шанс зараж.: <b>{m['infect_chance']}%</b> | ID юнита: <code>{m['infected_unit_id']}</code>"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Имя", callback_data=f"am:f:{mob_id}:name:{page}"), InlineKeyboardButton(text="🖼 Фото", callback_data=f"am:f:{mob_id}:photo_id:{page}")],
            [InlineKeyboardButton(text="❤️ HP", callback_data=f"am:f:{mob_id}:hp:{page}"), InlineKeyboardButton(text="🛡 Броня %", callback_data=f"am:f:{mob_id}:defense_percent:{page}")],
            [InlineKeyboardButton(text="🦠 Шанс зараж.%", callback_data=f"am:f:{mob_id}:infect_chance:{page}"), InlineKeyboardButton(text="🔗 ID юнита", callback_data=f"am:f:{mob_id}:infected_unit_id:{page}")],
            [InlineKeyboardButton(text="🗑 Удалить моба", callback_data=f"am:del:{mob_id}:{page}")],
            [InlineKeyboardButton(text="🔙 К мобам", callback_data=f"adm:mobs:{page}")],
        ]
    )
    await render_view(target, txt, kb, photo=m.get("photo_id") or None)


@router.callback_query(F.data.startswith("am:ed:"))
async def cb_am_ed(callback: CallbackQuery):
    _, _, m_s, p_s = callback.data.split(":")
    await render_adm_mob_editor(callback, int(m_s), int(p_s))
    await callback.answer()


@router.callback_query(F.data.startswith("am:f:"))
async def cb_am_field(callback: CallbackQuery, state: FSMContext):
    _, _, m_s, field, p_s = callback.data.split(":")
    await state.set_state(MobEditFSM.waiting_value)
    await state.update_data(mob_id=int(m_s), field=field, page=int(p_s))
    await callback.message.answer(f"Введите новое значение для <b>{field}</b>:")
    await callback.answer()


@router.message(MobEditFSM.waiting_value)
async def fsm_am_field_save(message: Message, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    mid, field, page = d["mob_id"], d["field"], d["page"]
    try:
        if field == "photo_id":
            val: Any = message.photo[-1].file_id if message.photo else ""
        elif field in ("hp", "defense_percent", "infect_chance", "infected_unit_id"):
            val = int((message.text or "").strip())
        else:
            val = (message.text or "").strip()
    except ValueError:
        await message.answer("❌ Неверный формат.")
        return
    await db.update_mob(mid, **{field: val})
    await message.answer("✅ Обновлено!")
    await render_adm_mob_editor(message, mid, page)


@router.callback_query(F.data.startswith("am:del:"))
async def cb_am_del(callback: CallbackQuery):
    _, _, m_s, p_s = callback.data.split(":")
    await db.delete_mob(int(m_s))
    await callback.answer("🗑 Моб удалён!", show_alert=True)
    await render_adm_mobs(callback, int(p_s))


# ==================== АДМИН: КАРТЫ И ТОЧЕЧНЫЙ РЕДАКТОР ВОЛН ====================

async def render_adm_maps(target: Message | CallbackQuery, page: int = 0):
    maps = await db.list_maps()
    rows = [[InlineKeyboardButton(text="➕ Создать новую Карту", callback_data="amp:new")]]
    for m in maps:
        rows.append([InlineKeyboardButton(text=f"🗺 #{m['id']} {m['name']} ({len(m['waves'])} волн)", callback_data=f"amp:ed:{m['id']}")])
    rows.append([InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")])
    await render_view(target, f"🗺 <b>КАРТЫ И ВОЛНЫ</b> (Всего: {len(maps)})", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("adm:maps:"))
async def cb_adm_maps(callback: CallbackQuery):
    if not await db.has_perm(callback.from_user.id, "manage_maps"):
        await callback.answer("Нет прав manage_maps!", show_alert=True)
        return
    await render_adm_maps(callback)
    await callback.answer()


@router.callback_query(F.data == "amp:new")
async def cb_amp_new(callback: CallbackQuery, state: FSMContext):
    await state.set_state(MapCreateFSM.name)
    await callback.message.answer("🗺 Введите <b>название карты</b>:")
    await callback.answer()


@router.message(MapCreateFSM.name)
async def fsm_amp_name(message: Message, state: FSMContext):
    await state.update_data(name=(message.text or "").strip())
    await state.set_state(MapCreateFSM.photo)
    await message.answer("🖼 Отправьте <b>фон карты</b> (фото для Pillow-рендера) или <code>-</code>:")


@router.message(MapCreateFSM.photo)
async def fsm_amp_photo(message: Message, state: FSMContext):
    pid = message.photo[-1].file_id if message.photo else ""
    await state.update_data(photo_id=pid)
    await state.set_state(MapCreateFSM.rewards)
    await message.answer("💰 Введите через пробел: <code>старт_монеты HP_базы награда_победа награда_поражение</code>\nПример: <code>150 100 350 50</code>")


@router.message(MapCreateFSM.rewards)
async def fsm_amp_rewards(message: Message, state: FSMContext):
    p = (message.text or "").split()
    try:
        sc, bhp, wc, lc = int(p[0]), int(p[1]), int(p[2]), int(p[3])
    except (ValueError, IndexError):
        await message.answer("❌ Пример: <code>150 100 350 50</code>")
        return
    d = await state.get_data()
    mid = await db.create_map({"name": d["name"], "photo_id": d["photo_id"], "starting_coins": sc, "base_hp": bhp, "win_coins": wc, "lose_coins": lc, "waves": [{"turns": 6, "mobs": []}]})
    await db.log_admin(message.from_user.id, f"Создал карту #{mid} {d['name']}")
    await state.clear()
    await message.answer(f"✅ Карта <b>{esc(d['name'])}</b> создана! Теперь добавьте мобов в волны:")
    await render_adm_map_editor(message, mid)


async def render_adm_map_editor(target: Message | CallbackQuery, map_id: int):
    m = await db.get_map(map_id)
    if not m:
        await render_adm_maps(target)
        return
    txt = (
        f"🗺 <b>КАРТА #{m['id']} — {esc(m['name'])}</b>\n"
        f"💰 Старт: {m['starting_coins']} | 🏰 База: {m['base_hp']} HP | 🏆 Победа: {m['win_coins']} | 📉 Пораж.: {m['lose_coins']}\n"
        f"🌊 Волн: <b>{len(m['waves'])}</b>"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌊 Редактор Волн (Точечный)", callback_data=f"mw:list:{map_id}")],
            [InlineKeyboardButton(text="✏️ Имя", callback_data=f"amp:f:{map_id}:name"), InlineKeyboardButton(text="🖼 Фон", callback_data=f"amp:f:{map_id}:photo_id")],
            [InlineKeyboardButton(text="🏆 Награда победа", callback_data=f"amp:f:{map_id}:win_coins"), InlineKeyboardButton(text="💰 Старт монеты", callback_data=f"amp:f:{map_id}:starting_coins")],
            [InlineKeyboardButton(text="🗑 Удалить карту", callback_data=f"amp:del:{map_id}")],
            [InlineKeyboardButton(text="🔙 К картам", callback_data="adm:maps:0")],
        ]
    )
    await render_view(target, txt, kb, photo=m.get("photo_id") or None)


@router.callback_query(F.data.startswith("amp:ed:"))
async def cb_amp_ed(callback: CallbackQuery):
    await render_adm_map_editor(callback, int(callback.data.split(":")[2]))
    await callback.answer()


@router.callback_query(F.data.startswith("amp:f:"))
async def cb_amp_f(callback: CallbackQuery, state: FSMContext):
    _, _, m_s, field = callback.data.split(":")
    await state.set_state(MapWaveEditFSM.map_field)
    await state.update_data(map_id=int(m_s), field=field)
    await callback.message.answer(f"Введите новое значение для <b>{field}</b>:")
    await callback.answer()


@router.message(MapWaveEditFSM.map_field)
async def fsm_amp_f_save(message: Message, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    mid, field = d["map_id"], d["field"]
    try:
        val: Any = (message.photo[-1].file_id if message.photo else "") if field == "photo_id" else (
            int((message.text or "").strip()) if field in ("win_coins", "lose_coins", "starting_coins", "base_hp") else (message.text or "").strip()
        )
    except ValueError:
        await message.answer("❌ Неверный формат.")
        return
    await db.update_map(mid, **{field: val})
    await render_adm_map_editor(message, mid)


@router.callback_query(F.data.startswith("amp:del:"))
async def cb_amp_del(callback: CallbackQuery):
    await db.delete_map(int(callback.data.split(":")[2]))
    await callback.answer("🗑 Карта удалена!", show_alert=True)
    await render_adm_maps(callback)


async def render_wave_list(target: Message | CallbackQuery, map_id: int):
    m = await db.get_map(map_id)
    if not m:
        return
    rows, row = [], []
    for i, _ in enumerate(m["waves"]):
        row.append(InlineKeyboardButton(text=f"Волна {i + 1}", callback_data=f"mw:sel:{map_id}:{i}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="➕ Добавить волну в конец", callback_data=f"mw:addw:{map_id}")])
    rows.append([InlineKeyboardButton(text="🔙 К карте", callback_data=f"amp:ed:{map_id}")])
    await render_view(target, f"🌊 <b>Волны карты «{esc(m['name'])}»</b> ({len(m['waves'])} шт.)", InlineKeyboardMarkup(inline_keyboard=rows))


async def render_wave_editor(target: Message | CallbackQuery, map_id: int, widx: int):
    m = await db.get_map(map_id)
    if not m or not (0 <= widx < len(m["waves"])):
        return
    w = m["waves"][widx]
    all_mobs = {x["id"]: x for x in await db.list_mobs()}
    lines = [f"🌊 <b>Волна {widx + 1}</b> (Карта: {esc(m['name'])})", f"⏱ Длительность: <b>{w['turns']} ходов</b>\n", "👾 <b>Мобы:</b>"]
    if not w["mobs"]:
        lines.append("<i>Пусто — добавьте мобов!</i>")
    else:
        for e in w["mobs"]:
            mo = all_mobs.get(int(e["id"]))
            lines.append(f"• {esc(mo['name']) if mo else '#' + str(e['id'])} ×<b>{e['count']}</b>")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить моба", callback_data=f"mw:amob:{map_id}:{widx}"), InlineKeyboardButton(text="⏱ Ходы", callback_data=f"mw:turn:{map_id}:{widx}")],
            [InlineKeyboardButton(text="🧹 Очистить мобов", callback_data=f"mw:clr:{map_id}:{widx}"), InlineKeyboardButton(text="🗑 Удалить волну", callback_data=f"mw:delw:{map_id}:{widx}")],
            [InlineKeyboardButton(text="🔙 К волнам", callback_data=f"mw:list:{map_id}")],
        ]
    )
    await render_view(target, "\n".join(lines), kb)


@router.callback_query(F.data.startswith("mw:list:"))
async def cb_mw_list(callback: CallbackQuery):
    await render_wave_list(callback, int(callback.data.split(":")[2]))
    await callback.answer()


@router.callback_query(F.data.startswith("mw:addw:"))
async def cb_mw_addw(callback: CallbackQuery):
    mid = int(callback.data.split(":")[2])
    m = await db.get_map(mid)
    waves = list(m["waves"]) + [{"turns": 7, "mobs": []}]
    await db.update_map(mid, waves=waves)
    await render_wave_list(callback, mid)
    await callback.answer("➕ Волна добавлена!")


@router.callback_query(F.data.startswith("mw:sel:"))
async def cb_mw_sel(callback: CallbackQuery):
    _, _, m_s, w_s = callback.data.split(":")
    await render_wave_editor(callback, int(m_s), int(w_s))
    await callback.answer()


@router.callback_query(F.data.startswith("mw:clr:"))
async def cb_mw_clr(callback: CallbackQuery):
    _, _, m_s, w_s = callback.data.split(":")
    mid, widx = int(m_s), int(w_s)
    m = await db.get_map(mid)
    m["waves"][widx]["mobs"] = []
    await db.update_map(mid, waves=m["waves"])
    await render_wave_editor(callback, mid, widx)
    await callback.answer("Очищено!")


@router.callback_query(F.data.startswith("mw:delw:"))
async def cb_mw_delw(callback: CallbackQuery):
    _, _, m_s, w_s = callback.data.split(":")
    mid, widx = int(m_s), int(w_s)
    m = await db.get_map(mid)
    if len(m["waves"]) <= 1:
        await callback.answer("Нельзя удалить последнюю волну!", show_alert=True)
        return
    m["waves"].pop(widx)
    await db.update_map(mid, waves=m["waves"])
    await render_wave_list(callback, mid)
    await callback.answer("🗑 Удалено!")


@router.callback_query(F.data.startswith("mw:amob:"))
async def cb_mw_amob(callback: CallbackQuery):
    _, _, m_s, w_s = callback.data.split(":")
    mobs = await db.list_mobs()
    rows, row = [], []
    for mo in mobs:
        ico = "👑" if mo["is_boss"] else "👾"
        row.append(InlineKeyboardButton(text=f"{ico} {mo['name'][:14]}", callback_data=f"mw:smob:{m_s}:{w_s}:{mo['id']}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"mw:sel:{m_s}:{w_s}")])
    await render_view(callback, "Выберите моба для волны:", InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith("mw:smob:"))
async def cb_mw_smob(callback: CallbackQuery, state: FSMContext):
    _, _, m_s, w_s, mob_s = callback.data.split(":")
    await state.set_state(MapWaveEditFSM.mob_count)
    await state.update_data(map_id=int(m_s), widx=int(w_s), mob_id=int(mob_s))
    await callback.message.answer("🔢 Введите количество этих мобов:")
    await callback.answer()


@router.message(MapWaveEditFSM.mob_count)
async def fsm_mw_mob_cnt(message: Message, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    try:
        cnt = max(1, int((message.text or "").strip()))
    except ValueError:
        await message.answer("❌ Введите число.")
        return
    m = await db.get_map(d["map_id"])
    m["waves"][d["widx"]]["mobs"].append({"id": d["mob_id"], "count": cnt})
    await db.update_map(d["map_id"], waves=m["waves"])
    await render_wave_editor(message, d["map_id"], d["widx"])


@router.callback_query(F.data.startswith("mw:turn:"))
async def cb_mw_turn(callback: CallbackQuery, state: FSMContext):
    _, _, m_s, w_s = callback.data.split(":")
    await state.set_state(MapWaveEditFSM.wave_turns)
    await state.update_data(map_id=int(m_s), widx=int(w_s))
    await callback.message.answer("⏱ Введите количество ходов на эту волну:")
    await callback.answer()


@router.message(MapWaveEditFSM.wave_turns)
async def fsm_mw_turn_save(message: Message, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    try:
        turns = max(1, int((message.text or "").strip()))
    except ValueError:
        await message.answer("❌ Введите число.")
        return
    m = await db.get_map(d["map_id"])
    m["waves"][d["widx"]]["turns"] = turns
    await db.update_map(d["map_id"], waves=m["waves"])
    await render_wave_editor(message, d["map_id"], d["widx"])


# ==================== АДМИН: КРЕЙТЫ ====================

async def render_adm_crates(target: Message | CallbackQuery):
    crates = await db.list_crates()
    rows = [[InlineKeyboardButton(text="➕ Создать Крейт", callback_data="acr:new")]]
    for c in crates:
        st = "🟢" if c["active"] else "🔴"
        rows.append([InlineKeyboardButton(text=f"{st} {c['name']} ({c['price']}💰)", callback_data=f"acr:ed:{c['id']}")])
    rows.append([InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")])
    await render_view(target, f"📦 <b>УПРАВЛЕНИЕ КРЕЙТАМИ</b> ({len(crates)})", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("adm:crates:"))
async def cb_adm_crates(callback: CallbackQuery):
    if not await db.has_perm(callback.from_user.id, "manage_crates"):
        await callback.answer("Нет прав!", show_alert=True)
        return
    await render_adm_crates(callback)
    await callback.answer()


@router.callback_query(F.data == "acr:new")
async def cb_acr_new(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CrateFSM.name)
    await state.update_data(units={})
    await callback.message.answer("📦 Введите <b>название</b> крейта:")
    await callback.answer()


@router.message(CrateFSM.name)
async def fsm_acr_name(message: Message, state: FSMContext):
    await state.update_data(name=(message.text or "").strip())
    await state.set_state(CrateFSM.price)
    await message.answer("💰 Введите <b>цену</b> крейта и <b>описание</b> через `|` (например: <code>500 | Топовый кейс</code>):")


@router.message(CrateFSM.price)
async def fsm_acr_price(message: Message, state: FSMContext):
    parts = (message.text or "").split("|", 1)
    try:
        price = int(parts[0].strip())
    except ValueError:
        await message.answer("❌ Пример: <code>500 | Описание</code>")
        return
    desc = parts[1].strip() if len(parts) > 1 else ""
    await state.update_data(price=price, desc=desc)
    await state.set_state(CrateFSM.photo)
    await message.answer("🖼 Отправьте <b>фото</b> крейта (или <code>-</code>):")


@router.message(CrateFSM.photo)
async def fsm_acr_photo(message: Message, state: FSMContext):
    pid = message.photo[-1].file_id if message.photo else ""
    await state.update_data(photo_id=pid)
    await _show_crate_builder(message, state)


async def _show_crate_builder(target: Message | CallbackQuery, state: FSMContext):
    d = await state.get_data()
    u_map = d.get("units", {})
    all_u = await db.list_units()
    by_id = {str(x["id"]): x for x in all_u}
    lines = [f"📦 <b>Состав крейта «{esc(d['name'])}»</b>:"]
    for k, w in u_map.items():
        lines.append(f"• {esc(by_id[k]['name']) if k in by_id else k} — вес <b>{w}</b>")
    rows, row = [], []
    for u in all_u:
        row.append(InlineKeyboardButton(text=u["name"][:14], callback_data=f"acrb:u:{u['id']}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if u_map:
        rows.append([InlineKeyboardButton(text="💾 Сохранить Крейт", callback_data="acrb:save")])
    await state.set_state(CrateFSM.builder)
    await render_view(target, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(CrateFSM.builder, F.data.startswith("acrb:u:"))
async def cb_acrb_u(callback: CallbackQuery, state: FSMContext):
    await state.update_data(sel_u=callback.data.split(":")[2])
    await state.set_state(CrateFSM.weight)
    await callback.message.answer("⚖️ Введите вес выпадения (число, например <code>20</code>):")
    await callback.answer()


@router.message(CrateFSM.weight)
async def fsm_acrb_w(message: Message, state: FSMContext):
    try:
        w = int((message.text or "").strip())
    except ValueError:
        await message.answer("❌ Введите целое число.")
        return
    d = await state.get_data()
    u_map = dict(d.get("units", {}))
    u_map[d["sel_u"]] = w
    await state.update_data(units=u_map)
    await _show_crate_builder(message, state)


@router.callback_query(CrateFSM.builder, F.data == "acrb:save")
async def cb_acrb_save(callback: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    cid = await db.create_crate(d["name"], d["desc"], d["price"], d["photo_id"], d["units"])
    await db.log_admin(callback.from_user.id, f"Создал крейт #{cid} {d['name']}")
    await state.clear()
    await callback.answer("✅ Крейт создан!", show_alert=True)
    await render_adm_crates(callback)


@router.callback_query(F.data.startswith("acr:ed:"))
async def cb_acr_ed(callback: CallbackQuery):
    cid = int(callback.data.split(":")[2])
    c = await db.get_crate(cid)
    if not c:
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"💰 Цена ({c['price']})", callback_data=f"acr:f:{cid}:price"), InlineKeyboardButton(text="✏️ Имя", callback_data=f"acr:f:{cid}:name")],
            [InlineKeyboardButton(text=f"{'🔴 Выключить' if c['active'] else '🟢 Включить'}", callback_data=f"acr:tgl:{cid}"), InlineKeyboardButton(text="🗑 Удалить", callback_data=f"acr:del:{cid}")],
            [InlineKeyboardButton(text="🔙 К крейтам", callback_data="adm:crates:0")],
        ]
    )
    await render_view(callback, f"📦 <b>Крейт #{cid} — {esc(c['name'])}</b>\nЦена: {c['price']} 💰", kb)
    await callback.answer()


@router.callback_query(F.data.startswith("acr:f:"))
async def cb_acr_f(callback: CallbackQuery, state: FSMContext):
    _, _, cid_s, field = callback.data.split(":")
    await state.set_state(CrateFSM.edit_field)
    await state.update_data(cid=int(cid_s), field=field)
    await callback.message.answer(f"Введите новое значение для <b>{field}</b>:")
    await callback.answer()


@router.message(CrateFSM.edit_field)
async def fsm_acr_f_save(message: Message, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    try:
        val: Any = int((message.text or "").strip()) if d["field"] == "price" else (message.text or "").strip()
    except ValueError:
        await message.answer("❌ Неверный формат.")
        return
    await db.update_crate(d["cid"], **{d["field"]: val})
    await render_adm_crates(message)


@router.callback_query(F.data.startswith("acr:tgl:"))
async def cb_acr_tgl(callback: CallbackQuery):
    cid = int(callback.data.split(":")[2])
    c = await db.get_crate(cid)
    await db.update_crate(cid, active=0 if c["active"] else 1)
    await render_adm_crates(callback)
    await callback.answer("Статус изменён!")


@router.callback_query(F.data.startswith("acr:del:"))
async def cb_acr_del(callback: CallbackQuery):
    await db.delete_crate(int(callback.data.split(":")[2]))
    await callback.answer("🗑 Удалено!", show_alert=True)
    await render_adm_crates(callback)


# ==================== АДМИН: НАСТРОЙКИ БАЛАНСА, МИРОВОЙ БОСС, ИГРОКИ, ПРАВА, БД ====================

async def render_adm_settings(target: Message | CallbackQuery, page: int = 0):
    keys = list(SETTING_META.keys())
    per_page = 6
    total_pages = max(1, (len(keys) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    chunk = keys[page * per_page : (page + 1) * per_page]

    rows = []
    for k in chunk:
        title = SETTING_META[k][0]
        cur_v = GAME_SETTINGS.get(k, DEFAULT_SETTINGS[k])
        rows.append([InlineKeyboardButton(text=f"{title}: {cur_v}", callback_data=f"aset:{k}:{page}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"adm:set:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"adm:set:{page + 1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")])
    await render_view(target, "🎛 <b>НАСТРОЙКИ БАЛАНСА И ИВЕНТОВ</b>\nНажмите на параметр для изменения:", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("adm:set:"))
async def cb_adm_set(callback: CallbackQuery):
    if not await db.has_perm(callback.from_user.id, "manage_settings"):
        await callback.answer("Нет прав!", show_alert=True)
        return
    await render_adm_settings(callback, int(callback.data.split(":")[2]))
    await callback.answer()


@router.callback_query(F.data.startswith("aset:"))
async def cb_aset(callback: CallbackQuery, state: FSMContext):
    _, key, p_s = callback.data.split(":")
    title, vtype, mn, mx = SETTING_META[key]
    await state.set_state(AdminFSM.setting_val)
    await state.update_data(s_key=key, s_page=int(p_s))
    await callback.message.answer(f"🎛 <b>{title}</b>\nТекущее: <code>{GAME_SETTINGS.get(key)}</code>\nВведите новое ({vtype}, от {mn} до {mx}):")
    await callback.answer()


@router.message(AdminFSM.setting_val)
async def fsm_aset_save(message: Message, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    key, page = d["s_key"], d["s_page"]
    _, vtype, mn, mx = SETTING_META[key]
    try:
        raw = (message.text or "").replace(",", ".").strip()
        num = int(raw) if vtype == "int" else float(raw)
        if not (mn <= num <= mx):
            raise ValueError
    except ValueError:
        await message.answer(f"❌ Введите число от {mn} до {mx}.")
        return
    await db.set_setting(key, str(num))
    await db.log_admin(message.from_user.id, f"Изменил настройку {key}={num}")
    await message.answer(f"✅ Настройка <b>{key}</b> обновлена на <code>{num}</code>!")
    await render_adm_settings(message, page)


# --- МИРОВОЙ БОСС (АДМИН) ---

@router.callback_query(F.data == "adm:wb")
async def cb_adm_wb(callback: CallbackQuery):
    if not await db.has_perm(callback.from_user.id, "manage_bosses"):
        await callback.answer("Нет прав!", show_alert=True)
        return
    wb = await db.get_active_world_boss()
    bosses = await db.list_mobs(only_bosses=True)
    rows = []
    if wb:
        rows.append([InlineKeyboardButton(text="🛑 Остановить Мирового Босса", callback_data="awb:stop")])
    for b in bosses:
        rows.append([InlineKeyboardButton(text=f"🌍 Запустить: {b['name']}", callback_data=f"awb:sp:{b['id']}")])
    rows.append([InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")])
    st = f"Активен: <b>{esc(wb['name'])}</b> ({wb['current_hp']}/{wb['max_hp']} HP)" if wb else "Нет активного босса."
    await render_view(callback, f"🌍 <b>УПРАВЛЕНИЕ МИРОВЫМ БОССОМ</b>\n{st}", InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data == "awb:stop")
async def cb_awb_stop(callback: CallbackQuery):
    await db.stop_world_boss()
    await callback.answer("🛑 Остановлен!", show_alert=True)
    await cb_adm_wb(callback)


@router.callback_query(F.data.startswith("awb:sp:"))
async def cb_awb_sp(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFSM.wb_hp)
    await state.update_data(wb_mob_id=int(callback.data.split(":")[2]))
    await callback.message.answer("❤️ Введите запас <b>HP Мирового Босса</b> (например <code>25000</code>):")
    await callback.answer()


@router.message(AdminFSM.wb_hp)
async def fsm_awb_hp(message: Message, state: FSMContext, bot: Bot):
    d = await state.get_data()
    await state.clear()
    try:
        hp = max(100, int((message.text or "").strip()))
    except ValueError:
        await message.answer("❌ Введите число.")
        return
    mob = await db.get_mob(d["wb_mob_id"])
    await db.spawn_world_boss(mob["id"], hp)
    await db.log_admin(message.from_user.id, f"Запустил Мирового Босса {mob['name']} ({hp} HP)")
    await message.answer(f"🌍 Мировой Босс <b>{esc(mob['name'])}</b> ({hp} HP) запущен!")
    for uid in await db.get_all_active_user_ids():
        try:
            await bot.send_message(uid, f"🚨🌍 <b>ПОЯВИЛСЯ МИРОВОЙ БОСС: {esc(mob['name'])}!</b>\n❤️ HP: <b>{hp}</b>\nЗаходи в «🌐 Мультиплеер → 🌍 Мировой Босс»!")
        except Exception:
            pass


# --- ИГРОКИ И ЭКОНОМИКА ---

@router.callback_query(F.data == "adm:users")
async def cb_adm_users(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFSM.find_user)
    await callback.message.answer("👥 Введите <b>@username</b> или <b>Telegram ID</b> игрока:")
    await callback.answer()


@router.message(AdminFSM.find_user)
async def fsm_adm_find_u(message: Message, state: FSMContext):
    await state.clear()
    u = await db.find_user(message.text or "")
    if not u:
        await message.answer("❌ Игрок не найден.")
        return
    await render_adm_user_card(message, u["user_id"])


async def render_adm_user_card(target: Message | CallbackQuery, target_uid: int):
    u = await db.get_user(target_uid)
    txt = await build_profile_text(u, False) + f"\n\n🚫 Бан: <b>{'ДА' if u['is_banned'] else 'НЕТ'}</b>"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💰 +/- Монеты", callback_data=f"aus:coins:{target_uid}"), InlineKeyboardButton(text="🦠 +3 Обыч.", callback_data=f"aus:p:common:{target_uid}")],
            [InlineKeyboardButton(text="💎 +3 Элит. паразита", callback_data=f"aus:p:elite:{target_uid}"), InlineKeyboardButton(text="🎁 Выдать Юнита", callback_data=f"aus:gu:{target_uid}")],
            [InlineKeyboardButton(text="✅ Разбанить" if u["is_banned"] else "🚫 Забанить", callback_data=f"aus:ban:{target_uid}")],
            [InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")],
        ]
    )
    await render_view(target, txt, kb)


@router.callback_query(F.data.startswith("aus:coins:"))
async def cb_aus_coins(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFSM.user_coins)
    await state.update_data(t_uid=int(callback.data.split(":")[2]))
    await callback.message.answer("💰 Введите сумму монет (отрицательное — списать, например <code>1000</code> или <code>-500</code>):")
    await callback.answer()


@router.message(AdminFSM.user_coins)
async def fsm_aus_coins(message: Message, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    try:
        delta = int((message.text or "").strip())
    except ValueError:
        await message.answer("❌ Введите целое число.")
        return
    await db.add_coins(d["t_uid"], delta)
    await db.log_admin(message.from_user.id, f"Изменил баланс {d['t_uid']} на {delta}")
    await render_adm_user_card(message, d["t_uid"])


@router.callback_query(F.data.startswith("aus:p:"))
async def cb_aus_p(callback: CallbackQuery):
    _, _, p_key, uid_s = callback.data.split(":")
    await db.add_parasite(int(uid_s), p_key, 3)
    await callback.answer("✅ Выдано +3 паразита!", show_alert=True)
    await render_adm_user_card(callback, int(uid_s))


@router.callback_query(F.data.startswith("aus:ban:"))
async def cb_aus_ban(callback: CallbackQuery):
    t_uid = int(callback.data.split(":")[2])
    if t_uid == OWNER_ID:
        await callback.answer("Нельзя забанить владельца!", show_alert=True)
        return
    u = await db.get_user(t_uid)
    nxt = 0 if u["is_banned"] else 1
    await db.update_user(t_uid, is_banned=nxt)
    await db.log_admin(callback.from_user.id, f"Бан={nxt} для {t_uid}")
    await render_adm_user_card(callback, t_uid)
    await callback.answer("Статус бана изменён!")


@router.callback_query(F.data.startswith("aus:gu:"))
async def cb_aus_gu(callback: CallbackQuery):
    t_uid = int(callback.data.split(":")[2])
    units = await db.list_units()
    rows = [[InlineKeyboardButton(text=f"#{u['id']} {u['name']}", callback_data=f"aus:do:{t_uid}:{u['id']}")] for u in units[:20]]
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="adm:home")])
    await render_view(callback, f"🎁 Выберите юнита для выдачи игроку <code>{t_uid}</code>:", InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith("aus:do:"))
async def cb_aus_do(callback: CallbackQuery):
    _, _, t_s, u_s = callback.data.split(":")
    await db.give_unit(int(t_s), int(u_s))
    await db.log_admin(callback.from_user.id, f"Выдал юнита #{u_s} игроку {t_s}")
    await callback.answer("✅ Юнит выдан!", show_alert=True)
    await render_adm_user_card(callback, int(t_s))


# --- РАССЫЛКА ---

@router.callback_query(F.data == "adm:bcast")
async def cb_adm_bcast(callback: CallbackQuery, state: FSMContext):
    if not await db.has_perm(callback.from_user.id, "broadcast"):
        await callback.answer("Нет прав!", show_alert=True)
        return
    await state.set_state(AdminFSM.broadcast)
    await callback.message.answer("📢 Отправьте сообщение (текст или фото с подписью) для рассылки всем игрокам:")
    await callback.answer()


@router.message(AdminFSM.broadcast)
async def fsm_adm_bcast(message: Message, state: FSMContext):
    await state.clear()
    uids = await db.get_all_active_user_ids()
    ok = 0
    for uid in uids:
        try:
            await message.send_copy(chat_id=uid)
            ok += 1
            await asyncio.sleep(0.04)
        except Exception:
            pass
    await db.log_admin(message.from_user.id, f"Рассылка: доставлено {ok}/{len(uids)}")
    await message.answer(f"✅ Рассылка завершена! Доставлено: <b>{ok}/{len(uids)}</b>")


# --- АДМИНЫ, ПАРТНЁРЫ-СИГНЕРЫ, ТЕХРАБОТЫ, ЛОГИ, БЭКАП И ВОССТАНОВЛЕНИЕ БД ---

async def render_admins_list(target: Message | CallbackQuery):
    admins = await db.list_admins()
    rows = [[InlineKeyboardButton(text="➕ Добавить админа", callback_data="aadm:add")]]
    for a in admins:
        name = a["full_name"] or str(a["user_id"])
        rows.append([InlineKeyboardButton(text=f"👮 {name} ({a['user_id']})", callback_data=f"aadm:ed:{a['user_id']}")])
    rows.append([InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")])
    await render_view(target, f"👮 <b>АДМИНИСТРАТОРЫ</b> (Владелец: <code>{OWNER_ID}</code>)", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "adm:admins")
async def cb_adm_admins(callback: CallbackQuery):
    if not await db.has_perm(callback.from_user.id, "manage_admins"):
        await callback.answer("Нет прав!", show_alert=True)
        return
    await render_admins_list(callback)
    await callback.answer()


@router.callback_query(F.data == "aadm:add")
async def cb_aadm_add(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFSM.add_admin)
    await callback.message.answer("👮 Введите <b>Telegram ID</b> или <b>@username</b> нового админа:")
    await callback.answer()


@router.message(AdminFSM.add_admin)
async def fsm_aadm_add(message: Message, state: FSMContext):
    await state.clear()
    u = await db.find_user(message.text or "")
    t_uid = u["user_id"] if u else (int(message.text.strip()) if (message.text or "").strip().isdigit() else 0)
    if not t_uid or t_uid == OWNER_ID:
        await message.answer("❌ Неверный ID.")
        return
    await db.add_admin(t_uid, message.from_user.id)
    await db.log_admin(message.from_user.id, f"Добавил админа {t_uid}")
    await render_admin_perms(message, t_uid)


async def render_admin_perms(target: Message | CallbackQuery, t_uid: int):
    perms = await db.get_admin_perms(t_uid)
    rows = []
    for k, label in ADMIN_PERMS.items():
        ico = "✅" if perms.get(k) else "❌"
        rows.append([InlineKeyboardButton(text=f"{ico} {label}", callback_data=f"aadm:tgl:{t_uid}:{k}")])
    rows.append([InlineKeyboardButton(text="🗑 Снять админа", callback_data=f"aadm:del:{t_uid}")])
    rows.append([InlineKeyboardButton(text="🔙 К списку", callback_data="adm:admins")])
    await render_view(target, f"👮 <b>Права админа <code>{t_uid}</code></b>\nНажимайте на пункты для переключения:", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("aadm:ed:"))
async def cb_aadm_ed(callback: CallbackQuery):
    await render_admin_perms(callback, int(callback.data.split(":")[2]))
    await callback.answer()


@router.callback_query(F.data.startswith("aadm:tgl:"))
async def cb_aadm_tgl(callback: CallbackQuery):
    _, _, uid_s, perm = callback.data.split(":")
    await db.toggle_admin_perm(int(uid_s), perm)
    await render_admin_perms(callback, int(uid_s))
    await callback.answer("Обновлено!")


@router.callback_query(F.data.startswith("aadm:del:"))
async def cb_aadm_del(callback: CallbackQuery):
    t_uid = int(callback.data.split(":")[2])
    await db.remove_admin(t_uid)
    await db.log_admin(callback.from_user.id, f"Снял админа {t_uid}")
    await callback.answer("🗑 Админ снят!", show_alert=True)
    await render_admins_list(callback)


@router.callback_query(F.data == "adm:signers")
async def cb_adm_signers(callback: CallbackQuery):
    if not await db.has_perm(callback.from_user.id, "manage_admins"):
        await callback.answer("Нет прав!", show_alert=True)
        return
    signers = await db.list_signers()
    rows = [[InlineKeyboardButton(text="➕ Добавить Партнёра (-10%)", callback_data="asgn:add")]]
    for s in signers:
        name = s["full_name"] or str(s["user_id"])
        rows.append([InlineKeyboardButton(text=f"❌ {name} ({s['role']})", callback_data=f"asgn:del:{s['user_id']}")])
    rows.append([InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")])
    await render_view(
        callback,
        f"🤝 <b>ПАРТНЁРЫ-СИГНЕРЫ</b>\nПартнёры дают скидку <b>-{cfg_int('partner_sign_disc_pct')}%</b> на поставку/прокачку, Админы с правом <code>sign_admin</code> — <b>-{cfg_int('admin_sign_disc_pct')}%</b>.",
        InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data == "asgn:add")
async def cb_asgn_add(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFSM.add_signer)
    await callback.message.answer("🤝 Введите <b>@username</b> или <b>ID</b> игрока для выдачи роли Партнёра-Сигнера:")
    await callback.answer()


@router.message(AdminFSM.add_signer)
async def fsm_asgn_add(message: Message, state: FSMContext):
    await state.clear()
    u = await db.find_user(message.text or "")
    t_uid = u["user_id"] if u else (int(message.text.strip()) if (message.text or "").strip().isdigit() else 0)
    if not t_uid:
        await message.answer("❌ Игрок не найден.")
        return
    await db.set_signer(t_uid, "partner", message.from_user.id)
    await message.answer(f"✅ Игрок <code>{t_uid}</code> назначен Партнёром-Сигнером!")


@router.callback_query(F.data.startswith("asgn:del:"))
async def cb_asgn_del(callback: CallbackQuery):
    await db.remove_signer(int(callback.data.split(":")[2]))
    await callback.answer("Снят!", show_alert=True)
    await cb_adm_signers(callback)


@router.callback_query(F.data == "adm:maint")
async def cb_adm_maint(callback: CallbackQuery):
    if not await db.has_perm(callback.from_user.id, "manage_admins"):
        await callback.answer("Нет прав!", show_alert=True)
        return
    nxt = "0" if GAME_SETTINGS.get("maintenance") == "1" else "1"
    await db.set_setting("maintenance", nxt)
    await db.log_admin(callback.from_user.id, f"Техработы={nxt}")
    await callback.answer("🛠 Техработы ВКЛ" if nxt == "1" else "🟢 Техработы ВЫКЛ", show_alert=True)
    await render_admin_home(callback, callback.from_user.id)


@router.callback_query(F.data == "adm:logs")
async def cb_adm_logs(callback: CallbackQuery):
    logs = await db.get_admin_logs(15)
    lines = ["📋 <b>ПОСЛЕДНИЕ ДЕЙСТВИЯ АДМИНОВ</b>", "━━━━━━━━━━━━━━━━━━"]
    for lg in logs:
        ts = datetime.fromtimestamp(lg["created_at"]).strftime("%d.%m %H:%M")
        lines.append(f"• [{ts}] <b>{esc(lg['full_name'] or lg['admin_id'])}</b>: {esc(lg['action'])}")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")]])
    await render_view(callback, "\n".join(lines), kb)
    await callback.answer()


@router.callback_query(F.data == "adm:backup")
async def cb_adm_backup(callback: CallbackQuery):
    if not await db.has_perm(callback.from_user.id, "manage_admins"):
        await callback.answer("Нет прав!", show_alert=True)
        return
    await callback.message.answer_document(
        FSInputFile(DB_PATH),
        caption="💾 <b>Бэкап БД Skibidi Verse TD.</b>\nЧтобы восстановить БД, отправьте этот <code>.db</code> файл обратно боту (только Владелец).",
    )
    await callback.answer("Файл отправлен!")


@router.message(F.document)
async def handle_db_restore(message: Message, bot: Bot):
    if message.from_user.id != OWNER_ID:
        return
    if not message.document or not (message.document.file_name or "").endswith(".db"):
        return
    file = await bot.get_file(message.document.file_id)
    await bot.download_file(file.file_path, DB_PATH)
    await db.reload_settings()
    await message.answer("✅ <b>База данных успешно восстановлена!</b>")


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    await callback.answer()


# ==============================================================================
# 12. ФОНОВЫЕ ЗАДАЧИ И ЗАПУСК БОТА
# ==============================================================================

async def auto_backup_task(bot: Bot) -> None:
    while True:
        await asyncio.sleep(12 * 3600)
        try:
            await bot.send_document(OWNER_ID, FSInputFile(DB_PATH), caption="🕒 Автобэкап БД (раз в 12ч).")
        except Exception as exc:
            logger.warning("Auto backup failed: %s", exc)


async def hourly_crate_rotation_task() -> None:
    while True:
        await asyncio.sleep(3600)
        try:
            for c in await db.list_crates():
                banners = c.get("banners") or []
                if len(banners) > 1:
                    nxt = (c.get("current_banner", 0) + 1) % len(banners)
                    await db.update_crate(c["id"], current_banner=nxt, units=banners[nxt]["units"])
        except Exception as exc:
            logger.warning("Crate rotation error: %s", exc)


async def main() -> None:
    await db.init()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    mw = AccessMiddleware()
    dp.message.outer_middleware(mw)
    dp.callback_query.outer_middleware(mw)
    dp.include_router(router)

    asyncio.create_task(auto_backup_task(bot))
    asyncio.create_task(hourly_crate_rotation_task())

    me = await bot.get_me()
    logger.info("🚀 Бот @%s (ID: %s) запущен! Владелец: %s", me.username, me.id, OWNER_ID)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 Бот остановлен.")
