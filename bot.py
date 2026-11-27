"""
Skibidi Verse: Cards & Infection — Telegram RPG Bot
Стек: Python 3.10+, aiogram 3.x, aiosqlite (автоустановка при запуске).
"""

import asyncio
import html
import importlib
import importlib.util
import json
import logging
import math
import os
import random
import subprocess
import sys
import time
import uuid
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple


def ensure_dependencies(packages: Dict[str, str]) -> None:
    missing = [
        spec for mod, spec in packages.items() if importlib.util.find_spec(mod) is None
    ]
    if missing:
        print(f"📦 Установка библиотек: {', '.join(missing)}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
        importlib.invalidate_caches()
        print("✅ Готово!")


ensure_dependencies({"aiogram": "aiogram>=3.0.0", "aiosqlite": "aiosqlite"})

import aiosqlite
from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    TelegramObject,
)

# ==============================================================================
# 1. КОНФИГУРАЦИЯ, РАНГИ И КОНСТАНТЫ
# ==============================================================================

DEFAULT_BOT_TOKEN = "9149772940:AAGjZRlItcwcmWKOA9mUd_BDoj_IEkNfyzE"
DEFAULT_OWNER_ID = 5341904332

_env_tok = (os.getenv("BOT_TOKEN") or "").strip().strip('"').strip("'")
BOT_TOKEN = (
    _env_tok
    if (":" in _env_tok and _env_tok.split(":", 1)[0].isdigit() and _env_tok.split(":", 1)[1] and not any(c.isspace() for c in _env_tok))
    else DEFAULT_BOT_TOKEN
)
_env_own = (os.getenv("OWNER_ID") or "").strip()
OWNER_ID = int(_env_own) if _env_own.isdigit() else DEFAULT_OWNER_ID
DB_PATH = (os.getenv("DB_PATH") or "").strip() or "skibidi_cards.db"

MAX_DECK_SIZE = 4
MAX_CARD_LEVEL = 50
XP_PER_DAMAGE = 0.1
DMG_PCT_PER_LEVEL = 0.5
MARKET_COMMISSION_PCT = 20
DAILY_COOLDOWN = 86400

DEFAULT_SETTINGS: Dict[str, str] = {
    "maintenance": "0",
    "infected_mult": "1.20",
    "shiny_chance_pct": "1.0",
    "shiny_bonus_pct": "25",
    "admin_sign_pct": "10",
    "partner_sign_pct": "5",
    "p_common_price": "150",
    "p_common_bonus": "5",
    "p_upgraded_price": "450",
    "p_upgraded_bonus": "12",
    "p_elite_price": "1200",
    "p_elite_bonus": "22",
    "battle_delay_sec": "1.5",
    "wb_cooldown_sec": "60",
    "luck_event_mult": "1.0",
    "luck_event_end": "0",
    "coin_event_mult": "1.0",
    "coin_event_end": "0",
}

GAME_SETTINGS: Dict[str, str] = dict(DEFAULT_SETTINGS)

SETTING_META: Dict[str, Tuple[str, str, float, float]] = {
    "infected_mult": ("🦠 Множитель Инфектед", "float", 1.0, 5.0),
    "shiny_chance_pct": ("✨ Шанс Shiny (%)", "float", 0.1, 100.0),
    "shiny_bonus_pct": ("✨ Бонус Shiny (%)", "int", 5, 200),
    "admin_sign_pct": ("👑 Админ-сигна (+% ATK/HP)", "int", 1, 100),
    "partner_sign_pct": ("🤝 Партнёр-сигна (+% ATK/HP)", "int", 1, 100),
    "p_common_price": ("🦠 Цена Обыч. паразита", "int", 10, 50000),
    "p_common_bonus": ("🦠 Бонус Обыч. паразита (%)", "int", 1, 500),
    "p_upgraded_price": ("☣️ Цена Улучш. паразита", "int", 10, 100000),
    "p_upgraded_bonus": ("☣️ Бонус Улучш. паразита (%)", "int", 1, 500),
    "p_elite_price": ("💎 Цена Элит. паразита", "int", 10, 200000),
    "p_elite_bonus": ("💎 Бонус Элит. паразита (%)", "int", 1, 500),
    "battle_delay_sec": ("⏱ Пауза хода в бою (сек)", "float", 0.5, 4.0),
    "wb_cooldown_sec": ("🌍 КД Мирового Босса (сек)", "int", 5, 600),
}

# Редкости: key -> (название, эмодзи, вес, базовый шанс заражения %)
RARITIES: Dict[str, Tuple[str, str, int, float]] = {
    "common": ("Обычная", "⚪️", 1, 1.0),
    "uncommon": ("Необычная", "🟢", 2, 0.5),
    "rare": ("Редкая", "🔵", 3, 0.25),
    "epic": ("Эпическая", "🟣", 4, 0.125),
    "legendary": ("Легендарная", "🟡", 5, 0.0625),
    "mythic": ("Мифическая", "🔴", 6, 0.03125),
    "secret": ("Секретная", "⬛", 7, 0.015625),
}

SERIAL_RARITIES: Set[str] = {"mythic", "secret"}

FACTIONS: Dict[str, str] = {
    "skibidi": "🚽 Скибиди",
    "astro": "🌌 Астро-Скибиди",
    "alliance": "📷 Альянс",
    "infected": "🦠 Заражённые",
}

CARD_CLASSES: Dict[str, Tuple[str, str]] = {
    "Single": ("🎯", "Сильный удар по 1 цели"),
    "AOE": ("🌪", "Удар по всем живым врагам"),
    "Splash": ("🌊", "100% по цели + 50% остальным"),
    "Fire": ("🔥", "Удар + поджог цели"),
    "Booster": ("✨", "Усиливает ATK и HP всей колоде"),
    "Healer": ("💗", "Лечит союзника (-3% эфф./хил)"),
}

PARASITES: Dict[str, Tuple[str, str]] = {
    "common": ("🦠 Обычный паразит", "p_common"),
    "upgraded": ("☣️ Улучшенный паразит", "p_upgraded"),
    "elite": ("💎 Элитный паразит", "p_elite"),
}

# 31 ранг Скибиди-Туалетов: (название, мин. кубки, множ. сложности, множ. монет, +бонус заражения %)
SKIBIDI_RANKS: List[Tuple[str, int, float, float, int]] = [
    ("🚽 Скибиди-Новичок I", 0, 0.80, 1.00, 0),
    ("🚽 Скибиди-Новичок II", 50, 0.85, 1.05, 2),
    ("🚽 Скибиди-Новичок III", 100, 0.90, 1.10, 4),
    ("🚽 Скибиди-Новичок IV", 150, 0.95, 1.15, 6),
    ("🪖 Скибиди-Боец I", 200, 1.00, 1.20, 10),
    ("🪖 Скибиди-Боец II", 300, 1.05, 1.25, 13),
    ("🪖 Скибиди-Боец III", 400, 1.10, 1.30, 16),
    ("🪖 Скибиди-Боец IV", 500, 1.15, 1.35, 20),
    ("🦾 Скибиди-Мутант I", 650, 1.20, 1.40, 25),
    ("🦾 Скибиди-Мутант II", 800, 1.30, 1.50, 30),
    ("🦾 Скибиди-Мутант III", 950, 1.40, 1.60, 35),
    ("🦾 Скибиди-Мутант IV", 1100, 1.50, 1.70, 40),
    ("🧪 Скибиди-Учёный I", 1300, 1.80, 1.80, 45),
    ("🧪 Скибиди-Учёный II", 1500, 2.50, 1.90, 50),
    ("🧪 Скибиди-Учёный III", 1700, 3.20, 2.00, 55),
    ("🧪 Скибиди-Учёный IV", 1900, 4.00, 2.10, 60),
    ("🕶 G-Отряд I", 2200, 5.00, 2.50, 70),
    ("🕶 G-Отряд II", 2500, 6.50, 2.80, 75),
    ("🕶 G-Отряд III", 2800, 8.00, 3.20, 80),
    ("🕶 G-Отряд IV", 3100, 10.00, 3.60, 90),
    ("👑 G-Тойлет I", 3500, 13.00, 4.00, 100),
    ("👑 G-Тойлет II", 4000, 15.00, 4.50, 110),
    ("👑 G-Тойлет III", 4500, 17.00, 5.00, 120),
    ("👑 G-Тойлет IV", 5000, 20.00, 5.50, 135),
    ("🌌 Астро-Скибиди I", 5700, 24.00, 6.00, 150),
    ("🌌 Астро-Скибиди II", 6500, 28.00, 6.50, 165),
    ("🌌 Астро-Скибиди III", 7400, 32.00, 7.00, 180),
    ("🌌 Астро-Скибиди IV", 8400, 36.00, 7.50, 200),
    ("🌌 Астро-Скибиди V", 9500, 40.00, 8.00, 225),
    ("🌌 Астро-Скибиди VI", 10000, 60.00, 9.00, 250),
    ("🌌 Астро-Скибиди VII", 15000, 72.00, 10.00, 300),
]

# Сложности: key -> (название, множ. врагов, множ. кубков/монет, сдвиг пула редкостей, +бонус заражения %)
DIFFICULTIES: Dict[str, Tuple[str, float, float, int, int]] = {
    "easy": ("🟢 Лёгкий", 0.8, 0.6, -1, 0),
    "med": ("🟡 Средний", 1.1, 1.0, 0, 5),
    "hard": ("🔴 Сложный", 1.6, 1.4, 1, 12),
    "nightmare": ("☠️ Кошмар", 2.2, 1.8, 2, 22),
    "crazy": ("🤯 Crazy", 3.5, 2.5, 2, 35),
}

# Модификаторы боя: key -> (название, дельта монет, дельта кубков, +бонус заражения %)
BATTLE_MODS: Dict[str, Tuple[str, float, float, int]] = {
    "mod_enemy_hp": ("🔴 1.5x HP врагов (+30%💰/🏆, +8%🦠)", 0.30, 0.30, 8),
    "mod_enemy_stats": ("🔴 1.25x Статы ИИ (+25%💰/🏆, +6%🦠)", 0.25, 0.25, 6),
    "mod_enemy_regen": ("🔴 Реген врагов 5%/ход (+30%💰/🏆, +8%🦠)", 0.30, 0.30, 8),
    "mod_player_hp": ("🟢 1.3x HP вашей колоды (-30%💰)", -0.30, 0.0, 0),
    "mod_player_crit": ("🟢 +20% Крит игрока (-25%💰)", -0.25, 0.0, 0),
}

ADMIN_PERMS: Dict[str, str] = {
    "manage_cards": "🃏 Карты (создание/редактор/удаление)",
    "manage_crates": "📦 Крейты",
    "manage_currencies": "🪙 Валюты и дроп из каток",
    "manage_events": "🎉 Ивенты (Удача / Монеты)",
    "manage_settings": "🎛 Настройки баланса",
    "manage_bosses": "🌍 Мировой Босс",
    "manage_economy": "💰 Выдача ресурсов и карт",
    "manage_users": "👥 Игроки и баны",
    "broadcast": "📢 Рассылка",
    "sign_admin": "👑 Админ-сигна (+10% ATK/HP)",
    "manage_admins": "👮 Админы, Партнёры, техработы, БД",
}

ACTIVE_BATTLES: Dict[str, Dict[str, Any]] = {}
USERS_IN_BATTLE: Set[int] = set()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("skibidi_cards")


def cfg_float(k: str) -> float:
    try:
        return float(GAME_SETTINGS.get(k, DEFAULT_SETTINGS[k]))
    except (ValueError, TypeError):
        return float(DEFAULT_SETTINGS[k])


def cfg_int(k: str) -> int:
    try:
        return int(float(GAME_SETTINGS.get(k, DEFAULT_SETTINGS[k])))
    except (ValueError, TypeError):
        return int(float(DEFAULT_SETTINGS[k]))


def get_active_events() -> Tuple[float, int, float, int]:
    """Возвращает (luck_mult, luck_left_sec, coin_mult, coin_left_sec)."""
    now = int(time.time())
    l_end = cfg_int("luck_event_end")
    c_end = cfg_int("coin_event_end")
    l_mult = cfg_float("luck_event_mult") if l_end > now else 1.0
    c_mult = cfg_float("coin_event_mult") if c_end > now else 1.0
    return l_mult, max(0, l_end - now), c_mult, max(0, c_end - now)


def get_rank_info(trophies: int) -> Tuple[int, str, float, float, int]:
    """Возвращает (индекс 0..30, название, diff_mult, reward_mult, infect_bonus_pct)."""
    res = (0, SKIBIDI_RANKS[0][0], SKIBIDI_RANKS[0][2], SKIBIDI_RANKS[0][3], SKIBIDI_RANKS[0][4])
    for idx, (name, req, dm, rm, ib) in enumerate(SKIBIDI_RANKS):
        if trophies >= req:
            res = (idx, name, dm, rm, ib)
        else:
            break
    return res


def get_parasite_info(p_key: str) -> Tuple[str, str, int, int]:
    name, col = PARASITES[p_key]
    return name, col, cfg_int(f"p_{p_key}_price"), cfg_int(f"p_{p_key}_bonus")


def calc_infect_chance(base: float, bonus_pct: float, luck_mult: float = 1.0) -> float:
    """Формула: base * (1 + bonus_pct / 100) * luck_mult. Пример: 1% + 5% = 1.05%."""
    return min(95.0, round(float(base) * (1.0 + float(bonus_pct) / 100.0) * float(luck_mult), 5))


def fmt_pct(v: float) -> str:
    s = f"{float(v):.4f}".rstrip("0").rstrip(".")
    return s or "0"


def xp_needed(level: int) -> float:
    return 0.0 if level >= MAX_CARD_LEVEL else round(45.0 * (level ** 1.35), 1)


def apply_card_xp(level: int, xp: float, gained: float) -> Tuple[int, float, int]:
    if level >= MAX_CARD_LEVEL or gained <= 0:
        return min(level, MAX_CARD_LEVEL), (0.0 if level >= MAX_CARD_LEVEL else xp), 0
    xp = round(xp + gained, 2)
    ups = 0
    while level < MAX_CARD_LEVEL:
        need = xp_needed(level)
        if xp >= need:
            xp = round(xp - need, 2)
            level += 1
            ups += 1
        else:
            break
    if level >= MAX_CARD_LEVEL:
        xp = 0.0
    return level, xp, ups


# ==============================================================================
# 2. БАЗА ДАННЫХ (AIOSQLITE)
# ==============================================================================

class Database:
    def __init__(self, path: str):
        self.path = path

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT DEFAULT '',
                    full_name TEXT DEFAULT 'Игрок',
                    coins INTEGER DEFAULT 400,
                    trophies INTEGER DEFAULT 0,
                    p_common INTEGER DEFAULT 2,
                    p_upgraded INTEGER DEFAULT 0,
                    p_elite INTEGER DEFAULT 0,
                    armed_parasite TEXT DEFAULT 'none',
                    wins INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    total_damage REAL DEFAULT 0,
                    infections_success INTEGER DEFAULT 0,
                    pity_bonus INTEGER DEFAULT 0,
                    daily_streak INTEGER DEFAULT 0,
                    last_daily INTEGER DEFAULT 0,
                    is_banned INTEGER DEFAULT 0,
                    created_at INTEGER DEFAULT 0,
                    mod_enemy_hp INTEGER DEFAULT 0,
                    mod_enemy_stats INTEGER DEFAULT 0,
                    mod_enemy_regen INTEGER DEFAULT 0,
                    mod_player_hp INTEGER DEFAULT 0,
                    mod_player_crit INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS admins (
                    user_id INTEGER PRIMARY KEY,
                    added_by INTEGER DEFAULT 0,
                    perms_json TEXT DEFAULT '{}',
                    added_at INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS signers (
                    user_id INTEGER PRIMARY KEY,
                    role TEXT DEFAULT 'partner',
                    added_by INTEGER DEFAULT 0,
                    added_at INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS currencies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    drop_in_battles INTEGER DEFAULT 0,
                    drop_chance REAL DEFAULT 10.0,
                    drop_min INTEGER DEFAULT 1,
                    drop_max INTEGER DEFAULT 5
                );

                CREATE TABLE IF NOT EXISTS user_currencies (
                    user_id INTEGER NOT NULL,
                    currency_id INTEGER NOT NULL,
                    amount INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, currency_id)
                );

                CREATE TABLE IF NOT EXISTS cards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    faction TEXT DEFAULT 'skibidi',
                    rarity TEXT DEFAULT 'common',
                    class_type TEXT DEFAULT 'Single',
                    hp INTEGER NOT NULL,
                    atk INTEGER NOT NULL,
                    booster_dmg_mult REAL DEFAULT 1.15,
                    booster_hp_mult REAL DEFAULT 1.15,
                    hide_from_ai INTEGER DEFAULT 0,
                    description TEXT DEFAULT '',
                    photo_id TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS inventory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    card_id INTEGER NOT NULL,
                    level INTEGER DEFAULT 1,
                    xp REAL DEFAULT 0,
                    is_shiny INTEGER DEFAULT 0,
                    is_infected INTEGER DEFAULT 0,
                    serial_number INTEGER DEFAULT 0,
                    sign_type TEXT DEFAULT 'none',
                    signed_by TEXT DEFAULT '',
                    equip_slot INTEGER DEFAULT 0,
                    acquired_at INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS crates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    currency_id INTEGER DEFAULT 0,
                    price INTEGER NOT NULL,
                    cards_json TEXT DEFAULT '{}',
                    photo_id TEXT DEFAULT '',
                    active INTEGER DEFAULT 1
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
                    card_id INTEGER NOT NULL,
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
                await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
            await conn.commit()

        await self.reload_settings()
        await self.seed_defaults()

    async def reload_settings(self) -> None:
        async with aiosqlite.connect(self.path) as conn:
            for k, v in await (await conn.execute("SELECT key, value FROM settings")).fetchall():
                GAME_SETTINGS[k] = str(v)

    async def set_setting(self, key: str, value: str) -> None:
        GAME_SETTINGS[key] = str(value)
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
            await conn.commit()

    async def seed_defaults(self) -> None:
        async with aiosqlite.connect(self.path) as conn:
            c_cnt = (await (await conn.execute("SELECT COUNT(*) FROM cards")).fetchone())[0]
            if c_cnt == 0:
                cards = [
                    # Скибиди (игрок) + Альянс (враги для заражения) на все 7 редкостей
                    ("Скибиди-Пехотинец", "skibidi", "common", "Single", 115, 24, 1.0, 1.0, 1, "Стартовый боец Скибиди."),
                    ("Скибиди-Охранник", "skibidi", "common", "Splash", 130, 20, 1.0, 1.0, 1, "Крепкий передовой туалет."),
                    ("Камерамен-Рекрут", "alliance", "common", "Single", 110, 22, 1.0, 1.0, 0, "Базовый агент Альянса."),
                    ("Спикермен-Боец", "alliance", "common", "Splash", 105, 21, 1.0, 1.0, 0, "Звуковые волны по площади."),
                    ("Скибиди-Снайпер", "skibidi", "uncommon", "Single", 150, 38, 1.0, 1.0, 1, "Меткий стрелок с лазером."),
                    ("Камерамен-Штурмовик", "alliance", "uncommon", "Single", 155, 34, 1.0, 1.0, 0, "Усиленный агент с винтовкой."),
                    ("Медик-Камерамен", "alliance", "uncommon", "Healer", 145, 32, 1.0, 1.0, 0, "Подлечивает отряд Альянса."),
                    ("Скибиди-Пироман", "skibidi", "rare", "Fire", 210, 46, 1.0, 1.0, 1, "Поджигает цели огнемётом."),
                    ("ТВ-Мен Агент", "alliance", "rare", "AOE", 200, 38, 1.0, 1.0, 0, "Фиолетовый экран бьёт всех."),
                    ("Большой Спикермен", "alliance", "rare", "Splash", 250, 44, 1.0, 1.0, 0, "Мощный звуковой удар."),
                    ("Скибиди-Учёный", "skibidi", "epic", "Booster", 260, 30, 1.22, 1.18, 1, "Усиливает ATK и HP всей колоды."),
                    ("Вантузмен", "alliance", "epic", "Single", 290, 78, 1.0, 1.0, 0, "Бесстрашный герой с вантузами."),
                    ("Тёмный Спикермен", "alliance", "epic", "Fire", 280, 68, 1.0, 1.0, 0, "Атакует кинжалами и огнём."),
                    ("Скибиди-Мутант Берсерк", "skibidi", "legendary", "Splash", 440, 105, 1.0, 1.0, 1, "Яростный мутант с пилами."),
                    ("ТВ-Вумен", "alliance", "legendary", "Healer", 400, 95, 1.0, 1.0, 0, "Элитный хилер Альянса."),
                    ("Камера-Вумен", "alliance", "legendary", "Single", 420, 118, 1.0, 1.0, 0, "Смертоносная пушка на спине."),
                    ("G-Тойлет 4.0", "skibidi", "mythic", "AOE", 680, 140, 1.0, 1.0, 1, "Лидер Скибиди с 4 лазерами."),
                    ("Титан Спикермен", "alliance", "mythic", "AOE", 660, 138, 1.0, 1.0, 0, "Могучий звуковой титан."),
                    ("Титан Камерамен", "alliance", "mythic", "Splash", 760, 152, 1.0, 1.0, 0, "Бронированный титан с молотом."),
                    ("Астро-Джаггернаут", "astro", "secret", "Fire", 1150, 235, 1.0, 1.0, 1, "Секретный Астро-Скибиди воин."),
                    ("Титан ТВ-Мен (Улучш.)", "alliance", "secret", "AOE", 1100, 225, 1.0, 1.0, 0, "Легендарный титан с клинком!"),
                ]
                for c in cards:
                    await conn.execute(
                        """
                        INSERT INTO cards (name, faction, rarity, class_type, hp, atk, booster_dmg_mult, booster_hp_mult, hide_from_ai, description)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        c,
                    )
                await conn.commit()

            cr_cnt = (await (await conn.execute("SELECT COUNT(*) FROM crates")).fetchone())[0]
            if cr_cnt == 0:
                rows = await (await conn.execute("SELECT id, rarity FROM cards WHERE faction IN ('skibidi', 'astro')")).fetchall()
                w1, w2 = {}, {}
                m1 = {"common": 55, "uncommon": 25, "rare": 12, "epic": 5, "legendary": 2, "mythic": 1, "secret": 0}
                m2 = {"common": 5, "uncommon": 15, "rare": 28, "epic": 26, "legendary": 16, "mythic": 7, "secret": 3}
                for cid, rar in rows:
                    if m1.get(rar, 0) > 0:
                        w1[str(cid)] = m1[rar]
                    if m2.get(rar, 0) > 0:
                        w2[str(cid)] = m2[rar]
                if w1:
                    await conn.execute(
                        "INSERT INTO crates (name, description, currency_id, price, cards_json, active) VALUES (?, ?, 0, ?, ?, 1)",
                        ("📦 Скибиди-Кейс", "Базовый набор бойцов Скибиди.", 200, json.dumps(w1)),
                    )
                    await conn.execute(
                        "INSERT INTO crates (name, description, currency_id, price, cards_json, active) VALUES (?, ?, 0, ?, ?, 1)",
                        ("💎 Элитный G-Кейс", "Высокий шанс на Эпиков, Легенд, Мификов и Секретки!", 750, json.dumps(w2)),
                    )
                    await conn.commit()

    # -------------------- Пользователи --------------------

    async def ensure_user(self, uid: int, username: Optional[str], full_name: str) -> Tuple[Dict[str, Any], bool]:
        uname = (username or "").lower()
        fname = full_name or "Игрок"
        is_new = False
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            row = await (await conn.execute("SELECT * FROM users WHERE user_id = ?", (uid,))).fetchone()
            if not row:
                is_new = True
                now = int(time.time())
                await conn.execute("INSERT INTO users (user_id, username, full_name, created_at) VALUES (?, ?, ?, ?)", (uid, uname, fname, now))
                starters = await (await conn.execute("SELECT id FROM cards WHERE faction = 'skibidi' AND rarity IN ('common', 'uncommon') ORDER BY id ASC LIMIT 3")).fetchall()
                for idx, st in enumerate(starters, 1):
                    await conn.execute(
                        "INSERT INTO inventory (user_id, card_id, level, xp, is_shiny, is_infected, serial_number, equip_slot, acquired_at) VALUES (?, ?, 1, 0, 0, 0, 0, ?, ?)",
                        (uid, st["id"], idx, now),
                    )
                await conn.commit()
                row = await (await conn.execute("SELECT * FROM users WHERE user_id = ?", (uid,))).fetchone()
            elif row["username"] != uname or row["full_name"] != fname:
                await conn.execute("UPDATE users SET username = ?, full_name = ? WHERE user_id = ?", (uname, fname, uid))
                await conn.commit()
            return dict(row), is_new

    async def get_user(self, uid: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            r = await (await conn.execute("SELECT * FROM users WHERE user_id = ?", (uid,))).fetchone()
            return dict(r) if r else None

    async def find_user(self, q: str) -> Optional[Dict[str, Any]]:
        s = q.strip().lstrip("@").lower()
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            r = await (await conn.execute("SELECT * FROM users WHERE user_id = ?", (int(s),))).fetchone() if s.isdigit() else await (await conn.execute("SELECT * FROM users WHERE LOWER(username) = ?", (s,))).fetchone()
            return dict(r) if r else None

    async def update_user(self, uid: int, **kw: Any) -> None:
        if not kw:
            return
        cols = ", ".join(f"{k} = ?" for k in kw)
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute(f"UPDATE users SET {cols} WHERE user_id = ?", [*kw.values(), uid])
            await conn.commit()

    async def add_coins(self, uid: int, delta: int) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("UPDATE users SET coins = MAX(0, coins + ?) WHERE user_id = ?", (delta, uid))
            await conn.commit()

    async def add_trophies(self, uid: int, delta: int) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("UPDATE users SET trophies = MAX(0, trophies + ?) WHERE user_id = ?", (delta, uid))
            await conn.commit()

    async def add_parasite(self, uid: int, p_key: str, delta: int) -> None:
        col = PARASITES[p_key][1]
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute(f"UPDATE users SET {col} = MAX(0, {col} + ?) WHERE user_id = ?", (delta, uid))
            await conn.commit()

    async def get_active_uids(self) -> List[int]:
        async with aiosqlite.connect(self.path) as conn:
            return [r[0] for r in await (await conn.execute("SELECT user_id FROM users WHERE is_banned = 0")).fetchall()]

    # -------------------- Кастомные Валюты --------------------

    async def list_currencies(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            return [dict(r) for r in await (await conn.execute("SELECT * FROM currencies ORDER BY id ASC")).fetchall()]

    async def get_currency(self, cid: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            r = await (await conn.execute("SELECT * FROM currencies WHERE id = ?", (cid,))).fetchone()
            return dict(r) if r else None

    async def create_currency(self, name: str) -> int:
        async with aiosqlite.connect(self.path) as conn:
            cur = await conn.execute(
                "INSERT INTO currencies (name, drop_in_battles, drop_chance, drop_min, drop_max) VALUES (?, 0, 10.0, 1, 5)",
                (name,),
            )
            await conn.commit()
            return cur.lastrowid

    async def update_currency(self, cid: int, **kw: Any) -> None:
        if not kw:
            return
        cols = ", ".join(f"{k} = ?" for k in kw)
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute(f"UPDATE currencies SET {cols} WHERE id = ?", [*kw.values(), cid])
            await conn.commit()

    async def delete_currency(self, cid: int) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("DELETE FROM user_currencies WHERE currency_id = ?", (cid,))
            await conn.execute("UPDATE crates SET currency_id = 0 WHERE currency_id = ?", (cid,))
            await conn.execute("DELETE FROM currencies WHERE id = ?", (cid,))
            await conn.commit()

    async def get_user_currencies(self, uid: int) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            rows = await (await conn.execute(
                """
                SELECT c.id, c.name, COALESCE(uc.amount, 0) AS amount
                FROM currencies c
                LEFT JOIN user_currencies uc ON uc.currency_id = c.id AND uc.user_id = ?
                ORDER BY c.id ASC
                """,
                (uid,),
            )).fetchall()
            return [dict(r) for r in rows]

    async def get_user_currency_bal(self, uid: int, cid: int) -> int:
        if cid == 0:
            u = await self.get_user(uid)
            return u["coins"] if u else 0
        async with aiosqlite.connect(self.path) as conn:
            r = await (await conn.execute("SELECT amount FROM user_currencies WHERE user_id = ? AND currency_id = ?", (uid, cid))).fetchone()
            return r[0] if r else 0

    async def add_user_currency(self, uid: int, cid: int, delta: int) -> None:
        if cid == 0:
            await self.add_coins(uid, delta)
            return
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute(
                """
                INSERT INTO user_currencies (user_id, currency_id, amount) VALUES (?, ?, MAX(0, ?))
                ON CONFLICT(user_id, currency_id) DO UPDATE SET amount = MAX(0, amount + ?)
                """,
                (uid, cid, delta, delta),
            )
            await conn.commit()

    # -------------------- Админы и Сигнеры --------------------

    async def is_admin(self, uid: int) -> bool:
        if uid == OWNER_ID:
            return True
        async with aiosqlite.connect(self.path) as conn:
            return (await (await conn.execute("SELECT 1 FROM admins WHERE user_id = ?", (uid,))).fetchone()) is not None

    async def get_admin_perms(self, uid: int) -> Dict[str, bool]:
        if uid == OWNER_ID:
            return {k: True for k in ADMIN_PERMS}
        async with aiosqlite.connect(self.path) as conn:
            r = await (await conn.execute("SELECT perms_json FROM admins WHERE user_id = ?", (uid,))).fetchone()
            if not r:
                return {k: False for k in ADMIN_PERMS}
            try:
                saved = json.loads(r[0] or "{}")
            except json.JSONDecodeError:
                saved = {}
            return {k: bool(saved.get(k, False)) for k in ADMIN_PERMS}

    async def has_perm(self, uid: int, perm: str) -> bool:
        return (await self.get_admin_perms(uid)).get(perm, False)

    async def get_signer_role(self, uid: int) -> Optional[str]:
        if uid == OWNER_ID or await self.has_perm(uid, "sign_admin"):
            return "admin"
        async with aiosqlite.connect(self.path) as conn:
            r = await (await conn.execute("SELECT role FROM signers WHERE user_id = ?", (uid,))).fetchone()
            return r[0] if r else None

    async def list_admins(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            return [dict(r) for r in await (await conn.execute("SELECT a.user_id, u.full_name FROM admins a LEFT JOIN users u ON a.user_id = u.user_id")).fetchall()]

    async def add_admin(self, tid: int, by: int) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("INSERT OR IGNORE INTO admins (user_id, added_by, perms_json, added_at) VALUES (?, ?, ?, ?)", (tid, by, json.dumps({k: False for k in ADMIN_PERMS}), int(time.time())))
            await conn.commit()

    async def toggle_admin_perm(self, tid: int, perm: str) -> None:
        p = await self.get_admin_perms(tid)
        p[perm] = not p.get(perm, False)
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("UPDATE admins SET perms_json = ? WHERE user_id = ?", (json.dumps(p), tid))
            await conn.commit()

    async def remove_admin(self, tid: int) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("DELETE FROM admins WHERE user_id = ?", (tid,))
            await conn.commit()

    async def list_signers(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            return [dict(r) for r in await (await conn.execute("SELECT s.user_id, s.role, u.full_name FROM signers s LEFT JOIN users u ON s.user_id = u.user_id")).fetchall()]

    async def set_signer(self, tid: int, role: str, by: int) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("INSERT OR REPLACE INTO signers (user_id, role, added_by, added_at) VALUES (?, ?, ?, ?)", (tid, role, by, int(time.time())))
            await conn.commit()

    async def remove_signer(self, tid: int) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("DELETE FROM signers WHERE user_id = ?", (tid,))
            await conn.commit()

    async def log_admin(self, aid: int, action: str) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("INSERT INTO admin_logs (admin_id, action, created_at) VALUES (?, ?, ?)", (aid, action, int(time.time())))
            await conn.commit()

    async def get_admin_logs(self, limit: int = 15) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            return [dict(r) for r in await (await conn.execute("SELECT l.*, u.full_name FROM admin_logs l LEFT JOIN users u ON l.admin_id = u.user_id ORDER BY l.id DESC LIMIT ?", (limit,))).fetchall()]

    # -------------------- Карточки --------------------

    async def list_cards(self, ai_only: bool = False) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            sql = "SELECT * FROM cards" + (" WHERE hide_from_ai = 0" if ai_only else "") + " ORDER BY id ASC"
            return [dict(r) for r in await (await conn.execute(sql)).fetchall()]

    async def get_card(self, cid: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            r = await (await conn.execute("SELECT * FROM cards WHERE id = ?", (cid,))).fetchone()
            return dict(r) if r else None

    async def create_card(self, d: Dict[str, Any]) -> int:
        async with aiosqlite.connect(self.path) as conn:
            cur = await conn.execute(
                """
                INSERT INTO cards (name, faction, rarity, class_type, hp, atk, booster_dmg_mult, booster_hp_mult, hide_from_ai, description, photo_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    d["name"], d["faction"], d["rarity"], d["class_type"],
                    int(d["hp"]), int(d["atk"]),
                    float(d.get("booster_dmg_mult", 1.15)), float(d.get("booster_hp_mult", 1.15)),
                    int(d.get("hide_from_ai", 0)), d.get("description", ""), d.get("photo_id", ""),
                ),
            )
            await conn.commit()
            return cur.lastrowid

    async def update_card(self, cid: int, **kw: Any) -> None:
        if not kw:
            return
        cols = ", ".join(f"{k} = ?" for k in kw)
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute(f"UPDATE cards SET {cols} WHERE id = ?", [*kw.values(), cid])
            await conn.commit()

    async def delete_card(self, cid: int) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("DELETE FROM market WHERE inv_id IN (SELECT id FROM inventory WHERE card_id = ?)", (cid,))
            await conn.execute("DELETE FROM inventory WHERE card_id = ?", (cid,))
            await conn.execute("DELETE FROM cards WHERE id = ?", (cid,))
            await conn.commit()

    async def get_card_exist(self, cid: int) -> Tuple[int, int]:
        async with aiosqlite.connect(self.path) as conn:
            r = await (await conn.execute("SELECT COUNT(*), COALESCE(SUM(is_shiny), 0) FROM inventory WHERE card_id = ? AND user_id != ?", (cid, OWNER_ID))).fetchone()
            return (r[0] or 0, r[1] or 0) if r else (0, 0)

    # -------------------- Инвентарь и Серийные номера --------------------

    async def give_card(
        self, uid: int, card_id: int, is_shiny: int = 0, is_infected: int = 0, sign_type: str = "none", signed_by: str = ""
    ) -> Tuple[int, int]:
        """Выдаёт карту и автоматически назначает серийник [#0001] для Mythic/Secret (обычных и Shiny раздельно)."""
        card = await self.get_card(card_id)
        rarity = card["rarity"] if card else "common"
        async with aiosqlite.connect(self.path) as conn:
            serial = 0
            if rarity in SERIAL_RARITIES:
                row = await (await conn.execute(
                    "SELECT COALESCE(MAX(serial_number), 0) FROM inventory WHERE card_id = ? AND is_shiny = ?",
                    (card_id, is_shiny),
                )).fetchone()
                serial = (row[0] or 0) + 1
            cur = await conn.execute(
                """
                INSERT INTO inventory (user_id, card_id, level, xp, is_shiny, is_infected, serial_number, sign_type, signed_by, equip_slot, acquired_at)
                VALUES (?, ?, 1, 0, ?, ?, ?, ?, ?, 0, ?)
                """,
                (uid, card_id, is_shiny, is_infected, serial, sign_type, signed_by, int(time.time())),
            )
            await conn.commit()
            return cur.lastrowid, serial

    async def get_inventory(self, uid: int, only_equipped: bool = False) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            where = "i.user_id = ?" + (" AND i.equip_slot > 0" if only_equipped else "")
            order = "i.equip_slot ASC" if only_equipped else "i.equip_slot DESC, i.is_shiny DESC, i.is_infected DESC, i.level DESC, i.id ASC"
            rows = await (await conn.execute(
                f"""
                SELECT i.id AS inv_id, i.user_id, i.card_id, i.level, i.xp, i.is_shiny, i.is_infected,
                       i.serial_number, i.sign_type, i.signed_by, i.equip_slot,
                       c.name, c.faction, c.rarity, c.class_type, c.hp, c.atk,
                       c.booster_dmg_mult, c.booster_hp_mult, c.description, c.photo_id,
                       (SELECT m.id FROM market m WHERE m.inv_id = i.id) AS market_id
                FROM inventory i
                JOIN cards c ON i.card_id = c.id
                WHERE {where}
                ORDER BY {order}
                """,
                (uid,),
            )).fetchall()
            return [dict(r) for r in rows]

    async def get_inv_item(self, inv_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            r = await (await conn.execute(
                """
                SELECT i.id AS inv_id, i.user_id, i.card_id, i.level, i.xp, i.is_shiny, i.is_infected,
                       i.serial_number, i.sign_type, i.signed_by, i.equip_slot,
                       c.name, c.faction, c.rarity, c.class_type, c.hp, c.atk,
                       c.booster_dmg_mult, c.booster_hp_mult, c.description, c.photo_id,
                       (SELECT m.id FROM market m WHERE m.inv_id = i.id) AS market_id
                FROM inventory i JOIN cards c ON i.card_id = c.id WHERE i.id = ?
                """,
                (inv_id,),
            )).fetchone()
            return dict(r) if r else None

    async def set_equip_slot(self, uid: int, inv_id: int, slot: int) -> None:
        async with aiosqlite.connect(self.path) as conn:
            if slot > 0:
                await conn.execute("UPDATE inventory SET equip_slot = 0 WHERE user_id = ? AND equip_slot = ?", (uid, slot))
            await conn.execute("UPDATE inventory SET equip_slot = ? WHERE id = ? AND user_id = ?", (slot, inv_id, uid))
            await conn.commit()

    async def clear_equip(self, uid: int) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("UPDATE inventory SET equip_slot = 0 WHERE user_id = ?", (uid,))
            await conn.commit()

    async def update_inv_xp(self, inv_id: int, level: int, xp: float) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("UPDATE inventory SET level = ?, xp = ? WHERE id = ?", (level, xp, inv_id))
            await conn.commit()

    async def sign_inv_item(self, inv_id: int, sign_type: str, signed_by: str) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("UPDATE inventory SET sign_type = ?, signed_by = ? WHERE id = ?", (sign_type, signed_by, inv_id))
            await conn.commit()

    # -------------------- Крейты --------------------

    def _hydrate_crate(self, r: aiosqlite.Row) -> Dict[str, Any]:
        d = dict(r)
        try:
            d["cards"] = json.loads(d.get("cards_json") or "{}")
        except json.JSONDecodeError:
            d["cards"] = {}
        return d

    async def list_crates(self, active_only: bool = False) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            sql = "SELECT * FROM crates" + (" WHERE active = 1" if active_only else "") + " ORDER BY price ASC, id ASC"
            return [self._hydrate_crate(r) for r in await (await conn.execute(sql)).fetchall()]

    async def get_crate(self, cid: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            r = await (await conn.execute("SELECT * FROM crates WHERE id = ?", (cid,))).fetchone()
            return self._hydrate_crate(r) if r else None

    async def create_crate(self, name: str, desc: str, currency_id: int, price: int, cards_map: Dict[str, int], photo_id: str = "") -> int:
        async with aiosqlite.connect(self.path) as conn:
            cur = await conn.execute(
                "INSERT INTO crates (name, description, currency_id, price, cards_json, photo_id, active) VALUES (?, ?, ?, ?, ?, ?, 1)",
                (name, desc, currency_id, price, json.dumps(cards_map), photo_id),
            )
            await conn.commit()
            return cur.lastrowid

    async def update_crate(self, cid: int, **kw: Any) -> None:
        if "cards" in kw:
            kw["cards_json"] = json.dumps(kw.pop("cards"))
        if not kw:
            return
        cols = ", ".join(f"{k} = ?" for k in kw)
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute(f"UPDATE crates SET {cols} WHERE id = ?", [*kw.values(), cid])
            await conn.commit()

    async def delete_crate(self, cid: int) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("DELETE FROM crates WHERE id = ?", (cid,))
            await conn.commit()

    # -------------------- P2P Рынок (80% продавцу, 20% владельцу) --------------------

    async def list_market(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            rows = await (await conn.execute(
                """
                SELECT m.id AS market_id, m.seller_id, m.inv_id, m.price,
                       i.level, i.xp, i.is_shiny, i.is_infected, i.serial_number, i.sign_type, i.signed_by,
                       c.name, c.faction, c.rarity, c.class_type, c.hp, c.atk, c.booster_dmg_mult, c.booster_hp_mult, c.photo_id,
                       u.full_name AS seller_name
                FROM market m
                JOIN inventory i ON m.inv_id = i.id
                JOIN cards c ON i.card_id = c.id
                LEFT JOIN users u ON m.seller_id = u.user_id
                ORDER BY m.id DESC
                """
            )).fetchall()
            return [dict(r) for r in rows]

    async def create_market_lot(self, seller_id: int, inv_id: int, price: int) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("UPDATE inventory SET equip_slot = 0 WHERE id = ?", (inv_id,))
            await conn.execute("INSERT INTO market (seller_id, inv_id, price, created_at) VALUES (?, ?, ?, ?)", (seller_id, inv_id, price, int(time.time())))
            await conn.commit()

    async def buy_market_lot(self, market_id: int, buyer_id: int) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            lot = await (await conn.execute(
                "SELECT m.*, c.name FROM market m JOIN inventory i ON m.inv_id = i.id JOIN cards c ON i.card_id = c.id WHERE m.id = ?",
                (market_id,),
            )).fetchone()
            if not lot:
                return False, "Лот уже куплен или снят.", None
            if lot["seller_id"] == buyer_id:
                return False, "Нельзя купить свой собственный лот.", None
            buyer = await (await conn.execute("SELECT coins FROM users WHERE user_id = ?", (buyer_id,))).fetchone()
            if not buyer or buyer["coins"] < lot["price"]:
                return False, f"Недостаточно монет! Нужно {lot['price']} 💰.", None

            price = lot["price"]
            payout = int(price * (100 - MARKET_COMMISSION_PCT) / 100)
            comm = price - payout
            await conn.execute("UPDATE users SET coins = coins - ? WHERE user_id = ?", (price, buyer_id))
            await conn.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (payout, lot["seller_id"]))
            await conn.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (comm, OWNER_ID))
            await conn.execute("UPDATE inventory SET user_id = ?, equip_slot = 0 WHERE id = ?", (buyer_id, lot["inv_id"]))
            await conn.execute("DELETE FROM market WHERE id = ?", (market_id,))
            await conn.commit()
            res = dict(lot)
            res["payout"] = payout
            return True, "Покупка успешна!", res

    async def cancel_market_lot(self, market_id: int, seller_id: int) -> bool:
        async with aiosqlite.connect(self.path) as conn:
            cur = await conn.execute("DELETE FROM market WHERE id = ? AND seller_id = ?", (market_id, seller_id))
            await conn.commit()
            return cur.rowcount > 0

    # -------------------- Мировой Босс --------------------

    async def get_world_boss(self) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            r = await (await conn.execute(
                "SELECT wb.*, c.name, c.rarity, c.photo_id FROM world_boss wb JOIN cards c ON wb.card_id = c.id WHERE wb.active = 1 ORDER BY wb.id DESC LIMIT 1"
            )).fetchone()
            return dict(r) if r else None

    async def spawn_world_boss(self, card_id: int, max_hp: int) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("UPDATE world_boss SET active = 0 WHERE active = 1")
            await conn.execute("INSERT INTO world_boss (card_id, max_hp, current_hp, active, created_at) VALUES (?, ?, ?, 1, ?)", (card_id, max_hp, max_hp, int(time.time())))
            await conn.commit()

    async def stop_world_boss(self) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("UPDATE world_boss SET active = 0 WHERE active = 1")
            await conn.commit()

    async def get_wb_hit(self, bid: int, uid: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            r = await (await conn.execute("SELECT * FROM world_boss_hits WHERE boss_id = ? AND user_id = ?", (bid, uid))).fetchone()
            return dict(r) if r else None

    async def hit_wb(self, bid: int, uid: int, dmg: float) -> int:
        now = int(time.time())
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute(
                "INSERT INTO world_boss_hits (boss_id, user_id, damage, last_hit) VALUES (?, ?, ?, ?) ON CONFLICT(boss_id, user_id) DO UPDATE SET damage = damage + excluded.damage, last_hit = excluded.last_hit",
                (bid, uid, dmg, now),
            )
            await conn.execute("UPDATE world_boss SET current_hp = MAX(0, current_hp - ?) WHERE id = ?", (int(dmg), bid))
            rem = (await (await conn.execute("SELECT current_hp FROM world_boss WHERE id = ?", (bid,))).fetchone())[0]
            if rem <= 0:
                await conn.execute("UPDATE world_boss SET active = 0 WHERE id = ?", (bid,))
            await conn.commit()
            return rem

    async def get_wb_top(self, bid: int, limit: int = 10) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            return [dict(r) for r in await (await conn.execute("SELECT h.user_id, h.damage, u.username, u.full_name FROM world_boss_hits h LEFT JOIN users u ON h.user_id = u.user_id WHERE h.boss_id = ? ORDER BY h.damage DESC LIMIT ?", (bid, limit))).fetchall()]

    # -------------------- Топы и Глобальная статистика --------------------

    async def get_leaderboard(self, col: str, limit: int = 10) -> List[Dict[str, Any]]:
        c = col if col in {"trophies", "wins", "infections_success", "total_damage", "coins"} else "trophies"
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            return [dict(r) for r in await (await conn.execute(f"SELECT user_id, username, full_name, {c} AS val FROM users WHERE is_banned = 0 ORDER BY {c} DESC LIMIT ?", (limit,))).fetchall()]

    async def get_stats(self) -> Dict[str, int]:
        async with aiosqlite.connect(self.path) as conn:
            return {
                "users": (await (await conn.execute("SELECT COUNT(*) FROM users")).fetchone())[0],
                "cards": (await (await conn.execute("SELECT COUNT(*) FROM cards")).fetchone())[0],
                "crates": (await (await conn.execute("SELECT COUNT(*) FROM crates")).fetchone())[0],
                "currencies": (await (await conn.execute("SELECT COUNT(*) FROM currencies")).fetchone())[0],
                "market": (await (await conn.execute("SELECT COUNT(*) FROM market")).fetchone())[0],
            }


db = Database(DB_PATH)


# ==============================================================================
# 3. СТАТЫ КАРТ, 4v4 БОЕВОЙ ДВИЖОК И UI-ХЕЛПЕРЫ
# ==============================================================================

def esc(v: Any) -> str:
    return html.escape(str(v or ""))


def fmt_user(u: Dict[str, Any]) -> str:
    n = esc(u.get("full_name") or "Игрок")
    return f"<b>{n}</b> (@{esc(u['username'])})" if u.get("username") else f"<b>{n}</b> [<code>{u.get('user_id')}</code>]"


def make_bar(cur: float, mx: float, length: int = 8, fill: str = "🟩", empty: str = "⬜") -> str:
    if mx <= 0:
        return fill * length
    f = int(round(max(0.0, min(1.0, cur / mx)) * length))
    return fill * f + empty * (length - f)


def roll_shiny() -> int:
    l_mult, _, _, _ = get_active_events()
    chance = min(100.0, cfg_float("shiny_chance_pct") * l_mult)
    return 1 if (random.random() * 100.0) < chance else 0


def card_badges(item: Dict[str, Any]) -> str:
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


def fmt_serial(item: Dict[str, Any]) -> str:
    sn = int(item.get("serial_number") or 0)
    return f" <b>[#{sn:04d}]</b>" if sn > 0 else ""


def get_sign_text(item: Dict[str, Any]) -> str:
    st = item.get("sign_type", "none")
    if st == "none":
        return "Нет"
    pct = cfg_int("admin_sign_pct") if st == "admin" else cfg_int("partner_sign_pct")
    role = "👑 Админ-сигна" if st == "admin" else "🤝 Партнёр-сигна"
    who = f" ({esc(item.get('signed_by'))})" if item.get("signed_by") else ""
    return f"{role} (+{pct}% ATK/HP){who}"


def calc_card_stats(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Считает реальные боевые статы карты:
    - Уровень (1..50): +0.5% к урону за каждый уровень свыше 1
    - ✨ Shiny: +25% к ATK и HP
    - 🦠 Инфектед: x1.20 к ATK и HP (настраивается)
    - Сигны: Админ (+10% ATK/HP), Партнёр (+5% ATK/HP)
    """
    lvl = max(1, min(MAX_CARD_LEVEL, int(item.get("level", 1))))
    lvl_dmg = 1.0 + ((lvl - 1) * DMG_PCT_PER_LEVEL / 100.0)
    sh_mult = (1.0 + cfg_float("shiny_bonus_pct") / 100.0) if item.get("is_shiny") else 1.0
    inf_mult = cfg_float("infected_mult") if item.get("is_infected") else 1.0
    st = item.get("sign_type", "none")
    sgn_mult = 1.0 + (cfg_float("admin_sign_pct") / 100.0 if st == "admin" else (cfg_float("partner_sign_pct") / 100.0 if st == "partner" else 0.0))

    hp = max(1, int(round(item["hp"] * sh_mult * inf_mult * sgn_mult)))
    atk = max(1, int(round(item["atk"] * lvl_dmg * sh_mult * inf_mult * sgn_mult)))
    b_bonus = (1.05 if item.get("is_shiny") else 1.0) * (1.05 if item.get("is_infected") else 1.0)
    b_dmg = round(float(item.get("booster_dmg_mult", 1.15)) * b_bonus, 2)
    b_hp = round(float(item.get("booster_hp_mult", 1.15)) * b_bonus, 2)
    return {"hp": hp, "atk": atk, "power": hp + atk * 4, "b_dmg": b_dmg, "b_hp": b_hp, "lvl_pct": round((lvl - 1) * DMG_PCT_PER_LEVEL, 1)}


def format_card_info(item: Dict[str, Any], ex_tot: int = 0, ex_sh: int = 0) -> str:
    r_name, r_ico, _, base_inf = RARITIES.get(item["rarity"], ("Обычная", "⚪️", 1, 1.0))
    f_name = FACTIONS.get(item["faction"], item["faction"])
    cls = item["class_type"]
    c_ico, c_desc = CARD_CLASSES.get(cls, ("🎯", ""))
    st = calc_card_stats(item)
    lvl = int(item.get("level", 1))
    xp = float(item.get("xp", 0.0))
    need = xp_needed(lvl)

    xp_txt = (
        f"⭐ Ур. <b>{lvl}/{MAX_CARD_LEVEL}</b> (MAX | <b>+{st['lvl_pct']}%</b> урон)"
        if lvl >= MAX_CARD_LEVEL
        else f"⭐ Ур. <b>{lvl}/{MAX_CARD_LEVEL}</b> (<b>+{st['lvl_pct']}%</b> урон)\n   {make_bar(xp, need, 8)} {xp:.1f}/{need:.0f} XP"
    )
    status = "🏷 На P2P-рынке" if item.get("market_id") else (f"✅ Слот #{item['equip_slot']}" if item.get("equip_slot", 0) > 0 else "📦 В инвентаре")

    lines = [
        f"{r_ico} {c_ico} <b>{esc(item['name'])}</b>{fmt_serial(item)} {card_badges(item)}",
        f"Фракция: {f_name} | Редкость: <b>{r_name}</b>",
        f"Класс: <b>{cls}</b> — <i>{c_desc}</i>",
        f"Статус: {status}",
        "━━━━━━━━━━━━━━━━━━",
        "📈 <b>УРОВЕНЬ (1 урон = 0.1 XP):</b>",
        xp_txt,
        "",
        "⚔️ <b>ХАРАКТЕРИСТИКИ:</b>",
    ]
    if cls == "Booster":
        lines.append(f"• ❤️ HP: <b>{st['hp']}</b> | ✨ Бафф: ATK <b>x{st['b_dmg']}</b>, HP <b>x{st['b_hp']}</b>")
    elif cls == "Healer":
        lines.append(f"• 💗 Хил: <b>{st['atk']}</b> | ❤️ HP: <b>{st['hp']}</b>")
    else:
        lines.append(f"• ⚔️ Урон: <b>{st['atk']}</b> | ❤️ HP: <b>{st['hp']}</b> | ⚡ Мощь: <b>{st['power']}</b>")

    sh_t = f"✨ Shiny (+{cfg_int('shiny_bonus_pct')}%)" if item.get("is_shiny") else "Обычная"
    inf_t = f"🦠 Инфектед (x{cfg_float('infected_mult')})" if item.get("is_infected") else "Нет"
    lines.extend([
        "",
        "✨ <b>МОДИФИКАТОРЫ:</b>",
        f"• Мутация: <b>{sh_t}</b> | Заражение: <b>{inf_t}</b>",
        f"• Сигна: {get_sign_text(item)}",
        f"• 🌍 Существует: <b>{ex_tot}</b> шт. (✨ Shiny: <b>{ex_sh}</b>) | 🦠 Баз. зараж.: {fmt_pct(base_inf)}%",
    ])
    if item.get("description"):
        lines.append(f"\n📝 <i>{esc(item['description'])}</i>")
    return "\n".join(lines)


async def generate_enemy_team(rank_idx: int, diff_key: str) -> List[Dict[str, Any]]:
    """Подбирает команду врагов (Альянс / ИИ) под ранг игрока и выбранную сложность."""
    _, d_mult, _, shift, _ = DIFFICULTIES[diff_key]
    _, _, r_diff_mult, _, _ = (rank_idx, *SKIBIDI_RANKS[rank_idx][0:1], SKIBIDI_RANKS[rank_idx][2], SKIBIDI_RANKS[rank_idx][3], SKIBIDI_RANKS[rank_idx][4])

    all_ai = await db.list_cards(ai_only=True)
    if not all_ai:
        all_ai = await db.list_cards()
    by_rar: Dict[str, List[Dict[str, Any]]] = {}
    for c in all_ai:
        by_rar.setdefault(c["rarity"], []).append(c)

    # 7 тиров лиг соответствуют 7 редкостям
    tier = min(6, max(0, (rank_idx // 4) + shift))
    rar_order = ["common", "uncommon", "rare", "epic", "legendary", "mythic", "secret"]

    team = []
    used: Set[int] = set()
    stat_scale = max(0.65, (r_diff_mult ** 0.55) * d_mult)

    for _ in range(4):
        r = random.random()
        if r < 0.55:
            pick_t = tier
        elif r < 0.85:
            pick_t = max(0, tier - 1)
        else:
            pick_t = min(6, tier + 1)
        # Secret на высоких тирах или Crazy
        if pick_t == 6 and diff_key != "crazy" and rank_idx < 24:
            pick_t = 5

        pool = [c for c in by_rar.get(rar_order[pick_t], []) if c["id"] not in used]
        if not pool:
            pool = [c for c in all_ai if c["id"] not in used] or all_ai
        chosen = dict(random.choice(pool))
        used.add(chosen["id"])

        is_sh = 1 if random.random() < min(0.10, 0.015 * d_mult) else 0
        sh_m = (1.0 + cfg_float("shiny_bonus_pct") / 100.0) if is_sh else 1.0
        hp = max(30, int(chosen["hp"] * stat_scale * sh_m))
        atk = max(8, int(chosen["atk"] * stat_scale * sh_m))
        team.append({
            "card_id": chosen["id"],
            "name": chosen["name"],
            "rarity": chosen["rarity"],
            "class_type": chosen["class_type"],
            "hp": hp,
            "max_hp": hp,
            "atk": atk,
            "b_dmg": float(chosen.get("booster_dmg_mult", 1.15)),
            "b_hp": float(chosen.get("booster_hp_mult", 1.15)),
            "is_shiny": is_sh,
            "is_infected": 0,
            "burn": 0,
            "heal_eff": 1.0,
            "inv_id": 0,
        })
    return team


def build_player_unit(item: Dict[str, Any], hp_mult: float = 1.0) -> Dict[str, Any]:
    st = calc_card_stats(item)
    hp = max(1, int(st["hp"] * hp_mult))
    return {
        "inv_id": item["inv_id"],
        "card_id": item["card_id"],
        "name": item["name"],
        "rarity": item["rarity"],
        "class_type": item["class_type"],
        "hp": hp,
        "max_hp": hp,
        "atk": st["atk"],
        "b_dmg": st["b_dmg"],
        "b_hp": st["b_hp"],
        "is_shiny": item["is_shiny"],
        "is_infected": item["is_infected"],
        "sign_type": item["sign_type"],
        "burn": 0,
        "heal_eff": 1.0,
    }


def apply_boosters_team(team: List[Dict[str, Any]], label: str, logs: List[str]) -> None:
    for u in team:
        if u["class_type"] == "Booster":
            dm, hm = u["b_dmg"], u["b_hp"]
            for ally in team:
                ally["hp"] = int(ally["hp"] * hm)
                ally["max_hp"] = ally["hp"]
                if ally["class_type"] != "Booster":
                    ally["atk"] = int(ally["atk"] * dm)
            logs.append(f"✨ {esc(label)}: <b>{esc(u['name'])}</b> баффает отряд (⚔️x{dm} ❤️x{hm})")


def fmt_combat_unit(idx: int, u: Dict[str, Any]) -> str:
    if u["hp"] <= 0:
        return f"{idx}. 💀 <s>{esc(u['name'])}</s>"
    r_ico = RARITIES.get(u["rarity"], ("", "⚪️", 1, 1.0))[1]
    c_ico = CARD_CLASSES.get(u["class_type"], ("🎯", ""))[0]
    b = ("✨" if u.get("is_shiny") else "") + ("🦠" if u.get("is_infected") else "")
    st = " 🔥" if u.get("burn", 0) > 0 else ""
    if u["class_type"] == "Healer":
        hv = max(1, int(u["atk"] * u["heal_eff"]))
        return f"{idx}. {r_ico}{c_ico} <b>{esc(u['name'])}</b>{b} (💗{hv} | ❤️{u['hp']}/{u['max_hp']}){st}"
    return f"{idx}. {r_ico}{c_ico} <b>{esc(u['name'])}</b>{b} (⚔️{u['atk']} | ❤️{u['hp']}/{u['max_hp']}){st}"


def render_battle_screen(title: str, p_name: str, t1: List[Dict[str, Any]], e_name: str, t2: List[Dict[str, Any]], logs: List[str], rnd: int, inf_cnt: int) -> str:
    p_txt = "\n".join(fmt_combat_unit(i, u) for i, u in enumerate(t1, 1))
    e_txt = "\n".join(fmt_combat_unit(i, u) for i, u in enumerate(t2, 1))
    ev = "\n".join(f"• {l}" for l in logs[-3:]) if logs else "• <i>Бой начинается...</i>"
    inf_tag = f" | 🦠 Перехвачено: <b>{inf_cnt}</b>" if inf_cnt else ""
    return (
        f"{title} | <b>Раунд {rnd}</b>{inf_tag}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔵 <b>{esc(p_name)} (Скибиди):</b>\n{p_txt}\n\n"
        f"🔴 <b>{esc(e_name)} (Альянс):</b>\n{e_txt}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚡ <b>Лог боя:</b>\n{ev}"
    )


def perform_combat_turn(
    atk_team: List[Dict[str, Any]],
    def_team: List[Dict[str, Any]],
    is_player: bool,
    logs: List[str],
    dmg_tracker: Dict[int, float],
    infected_drops: List[Dict[str, Any]],
    infect_bonus_pct: float,
    luck_mult: float,
    crit_chance: float = 0.0,
) -> None:
    # Горение в начале хода атакующей стороны
    for u in atk_team:
        if u["hp"] > 0 and u["burn"] > 0:
            bd = u["burn"]
            u["hp"] = max(0, u["hp"] - bd)
            u["burn"] = 0
            if u["hp"] <= 0:
                logs.append(f"🔥 <b>{esc(u['name'])}</b> сгорел (-{bd}) ☠️")
                if not is_player:
                    _try_infect_enemy(u, infected_drops, infect_bonus_pct, luck_mult, logs)

    atk_alive = [u for u in atk_team if u["hp"] > 0]
    def_alive = [u for u in def_team if u["hp"] > 0]
    if not atk_alive or not def_alive:
        return

    actor = random.choice(atk_alive)
    cls = actor["class_type"]
    is_crit = crit_chance > 0 and random.random() < crit_chance
    base_dmg = max(1, int(actor["atk"] * (1.5 if is_crit else 1.0)))
    crit_tag = " 💥КРИТ!" if is_crit else ""

    def record_dmg(dealt: int) -> None:
        if is_player and actor.get("inv_id"):
            dmg_tracker[actor["inv_id"]] = dmg_tracker.get(actor["inv_id"], 0.0) + dealt

    def hit_target(target: Dict[str, Any], amount: int) -> bool:
        real = min(target["hp"], max(1, amount))
        target["hp"] = max(0, target["hp"] - real)
        record_dmg(real)
        if target["hp"] <= 0:
            if is_player:
                _try_infect_enemy(target, infected_drops, infect_bonus_pct, luck_mult, logs)
            return True
        return False

    if cls == "Booster":
        t = random.choice(def_alive)
        d = max(10, int(t["max_hp"] * 0.10))
        ko = " ☠️" if hit_target(t, d) else ""
        logs.append(f"✨ <b>{esc(actor['name'])}</b> ➔ {esc(t['name'])} (-{d}){ko}")
    elif cls == "Healer":
        others = [a for a in atk_alive if a is not actor]
        if others:
            t = min(others, key=lambda x: x["hp"] / max(1, x["max_hp"]))
            heal = max(5, int(base_dmg * actor["heal_eff"]))
            t["hp"] = min(t["max_hp"], t["hp"] + heal)
            actor["heal_eff"] = max(0.30, round(actor["heal_eff"] - 0.03, 2))
            record_dmg(heal)
            logs.append(f"💗 <b>{esc(actor['name'])}</b> лечит {esc(t['name'])} (+{heal}){crit_tag}")
        else:
            t = random.choice(def_alive)
            d = max(5, int(base_dmg * 0.35))
            ko = " ☠️" if hit_target(t, d) else ""
            logs.append(f"💗 <b>{esc(actor['name'])}</b> ➔ {esc(t['name'])} (-{d}){ko}")
    elif cls == "AOE":
        aoe_d = max(1, int(base_dmg * 0.72))
        kills = sum(1 for t in def_alive if hit_target(t, aoe_d))
        logs.append(f"🌪 <b>{esc(actor['name'])}</b> ➔ -{aoe_d} по всем!{crit_tag}" + (f" (☠️x{kills})" if kills else ""))
    elif cls == "Splash":
        main_t = random.choice(def_alive)
        sp_d = max(1, int(base_dmg * 0.5))
        kills = 1 if hit_target(main_t, base_dmg) else 0
        for t in def_alive:
            if t is not main_t and hit_target(t, sp_d):
                kills += 1
        logs.append(f"🌊 <b>{esc(actor['name'])}</b> ➔ {esc(main_t['name'])} (-{base_dmg}/-{sp_d}){crit_tag}" + (f" (☠️x{kills})" if kills else ""))
    elif cls == "Fire":
        t = random.choice(def_alive)
        t["burn"] += max(5, int(base_dmg * 0.45))
        ko = " ☠️" if hit_target(t, base_dmg) else ""
        logs.append(f"🔥 <b>{esc(actor['name'])}</b> ➔ {esc(t['name'])} (-{base_dmg} +🔥){crit_tag}{ko}")
    else:
        t = random.choice(def_alive)
        ko = " ☠️" if hit_target(t, base_dmg) else ""
        logs.append(f"🎯 <b>{esc(actor['name'])}</b> ➔ {esc(t['name'])} (-{base_dmg}){crit_tag}{ko}")


def _try_infect_enemy(
    enemy: Dict[str, Any],
    infected_drops: List[Dict[str, Any]],
    infect_bonus_pct: float,
    luck_mult: float,
    logs: List[str],
) -> None:
    base_ch = RARITIES.get(enemy["rarity"], ("", "", 1, 1.0))[3]
    total_ch = calc_infect_chance(base_ch, infect_bonus_pct, luck_mult)
    if (random.random() * 100.0) < total_ch:
        infected_drops.append({"card_id": enemy["card_id"], "name": enemy["name"], "rarity": enemy["rarity"], "chance": total_ch})
        logs.append(f"🦠💥 <b>ЗАРАЖЕНИЕ!</b> {esc(enemy['name'])} перехвачен ({fmt_pct(total_ch)}%)!")


async def render_view(target: Message | CallbackQuery, text: str, kb: Optional[InlineKeyboardMarkup] = None, photo: Optional[str] = None) -> None:
    if isinstance(target, Message):
        if photo:
            try:
                await target.answer_photo(photo=photo, caption=text[:1024], reply_markup=kb)
                return
            except TelegramBadRequest:
                pass
        await target.answer(text[:4096], reply_markup=kb)
        return
    msg = target.message
    if not msg:
        return
    has_p = bool(msg.photo)
    try:
        if photo:
            if has_p:
                await msg.edit_caption(caption=text[:1024], reply_markup=kb)
            else:
                try:
                    await msg.delete()
                except TelegramBadRequest:
                    pass
                await msg.answer_photo(photo=photo, caption=text[:1024], reply_markup=kb)
        else:
            if has_p:
                try:
                    await msg.delete()
                except TelegramBadRequest:
                    pass
                await msg.answer(text[:4096], reply_markup=kb)
            else:
                await msg.edit_text(text[:4096], reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            try:
                await msg.answer(text[:4096], reply_markup=kb)
            except Exception:
                pass


def main_reply_kb(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="⚔️ В бой (Альянс)"), KeyboardButton(text="🃏 Колода и Карты")],
        [KeyboardButton(text="📦 Крейты и Лаба"), KeyboardButton(text="🌐 Мультиплеер")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🏆 Рейтинг")],
    ]
    if is_admin:
        rows.append([KeyboardButton(text="⚙️ Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True, input_field_placeholder="Меню Скибиди-Туалетов...")


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
                    await event.answer("🚫 Вы заблокированы.")
                elif isinstance(event, CallbackQuery):
                    await event.answer("🚫 Вы заблокированы.", show_alert=True)
                return
            if GAME_SETTINGS.get("maintenance", "0") == "1" and not is_adm:
                if isinstance(event, Message):
                    await event.answer("🛠 <b>Идут техработы!</b> Скоро вернёмся.")
                elif isinstance(event, CallbackQuery):
                    await event.answer("🛠 Техработы.", show_alert=True)
                return
            data["db_user"] = user
            data["is_admin"] = is_adm
        return await handler(event, data)


# ==============================================================================
# 4. FSM СОСТОЯНИЯ
# ==============================================================================

class PlayerFSM(StatesGroup):
    search = State()
    market_price = State()


class CardFSM(StatesGroup):
    name = State()
    faction = State()
    rarity = State()
    cls = State()
    stats = State()
    boost = State()
    desc = State()
    photo = State()
    edit_val = State()


class CrateFSM(StatesGroup):
    name = State()
    curr = State()
    price = State()
    photo = State()
    builder = State()
    weight = State()
    edit_val = State()


class CurFSM(StatesGroup):
    name = State()
    drop_cfg = State()
    give_amt = State()


class AdminFSM(StatesGroup):
    add_adm = State()
    add_sgn = State()
    find_u = State()
    u_coins = State()
    bcast = State()
    wb_hp = State()
    set_val = State()
    ev_cfg = State()


# ==============================================================================
# 5. ОСНОВНОЙ РОУТЕР: СТАРТ, ПРОФИЛЬ, МОДЫ, ЭКИПИРОВКА 2.0, ИНФО
# ==============================================================================

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, is_admin: bool):
    await state.clear()
    _, is_new = await db.ensure_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    gift = "\n\n🎁 <b>Стартовый набор:</b> 3 Скибиди-бойца в колоде, 400 💰 и 2 🦠 паразита!" if is_new else ""
    await message.answer(
        f"🚽 <b>Skibidi Verse: Cards & Infection</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"• Играй за <b>Скибиди-Туалетов</b>, сражайся 4×4 против Альянса и поднимайся по <b>31 рангу</b>!\n"
        f"• При убийстве врага в бою есть шанс его <b>🦠 заразить</b> (чем выше ранг и паразит — тем выше шанс!).\n"
        f"• Качай карты в боях: <b>1 урон = 0.1 XP</b> (до 50 ур., +0.5% урона за ур.).\n"
        f"• Лови <b>✨ Shiny</b> и серийные номера <b>[#0001]</b> на Mythic/Secret!{gift}\n\n"
        f"👇 Выбирай раздел в меню снизу.",
        reply_markup=main_reply_kb(is_admin),
    )


@router.message(Command("panel"))
async def cmd_panel(message: Message, state: FSMContext, is_admin: bool):
    await state.clear()
    await message.answer("🚽 <b>Меню Skibidi Verse</b>", reply_markup=main_reply_kb(is_admin))


# -------------------- ПРОФИЛЬ И МОДИФИКАТОРЫ --------------------

async def build_profile_text(u: Dict[str, Any], is_self: bool = True) -> str:
    inv = await db.get_inventory(u["user_id"])
    eq = [c for c in inv if c["equip_slot"] > 0]
    power = sum(calc_card_stats(c)["power"] for c in eq)
    _, r_name, _, r_rew, r_inf = get_rank_info(u["trophies"])
    shiny_c = sum(1 for c in inv if c["is_shiny"])
    inf_c = sum(1 for c in inv if c["is_infected"])
    s_role = await db.get_signer_role(u["user_id"])
    badge = " | 👑 Админ-Сигнер" if s_role == "admin" else (" | 🤝 Партнёр-Сигнер" if s_role == "partner" else "")

    extra_curs = await db.get_user_currencies(u["user_id"])
    cur_lines = "\n".join(f"   • {esc(c['name'])}: <b>{c['amount']}</b>" for c in extra_curs)
    cur_block = f"\n{cur_lines}" if cur_lines else ""

    l_mult, l_sec, c_mult, c_sec = get_active_events()
    ev_parts = []
    if l_mult > 1.0:
        ev_parts.append(f"🍀 Удача x{l_mult} ({l_sec // 60}м)")
    if c_mult > 1.0:
        ev_parts.append(f"💰 Монеты x{c_mult} ({c_sec // 60}м)")
    ev_line = f"\n🎉 <b>Ивенты:</b> {' | '.join(ev_parts)}" if ev_parts else ""

    return (
        f"{'👤 <b>ВАШ ПРОФИЛЬ</b>' if is_self else '🔎 <b>ПРОФИЛЬ ИГРОКА</b>'}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🪪 {fmt_user(u)}{badge}\n"
        f"🎖 Ранг: <b>{r_name}</b> (🏆 {u['trophies']})\n"
        f"   └ Награды: <b>x{r_rew}</b> | Заражение: <b>+{r_inf}%</b> от шанса\n\n"
        f"💰 Монеты: <b>{u['coins']}</b>{cur_block}\n"
        f"🦠 Паразиты: Обыч. <b>{u['p_common']}</b> | Улучш. <b>{u['p_upgraded']}</b> | Элит. <b>{u['p_elite']}</b>\n\n"
        f"🛡 Колода: <b>{len(eq)}/{MAX_DECK_SIZE}</b> (⚡ Мощь: <b>{power}</b>)\n"
        f"🃏 Карт: <b>{len(inv)}</b> (✨Shiny: {shiny_c} | 🦠Зар.: {inf_c})\n"
        f"📊 Бои: <b>{u['wins']}W / {u['losses']}L</b> | 💥 Урон: <b>{int(u['total_damage'])}</b>\n"
        f"🦠 Заражений: <b>{u['infections_success']}</b> | 🎯 Пити: <b>+{u['pity_bonus']}%</b> | 🔥 Входы: <b>{u['daily_streak']} дн.</b>{ev_line}"
    )


def profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Ежедневка", callback_data="prof:daily"), InlineKeyboardButton(text="🧬 Моды боя", callback_data="prof:mods")],
            [InlineKeyboardButton(text="🔎 Найти игрока", callback_data="prof:search"), InlineKeyboardButton(text="🔄 Обновить", callback_data="prof:ref")],
        ]
    )


@router.message(F.text == "👤 Профиль")
async def menu_profile(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(await build_profile_text(await db.get_user(message.from_user.id), True), reply_markup=profile_kb())


@router.callback_query(F.data == "prof:ref")
async def cb_prof_ref(cb: CallbackQuery):
    await render_view(cb, await build_profile_text(await db.get_user(cb.from_user.id), True), profile_kb())
    await cb.answer("Обновлено!")


@router.callback_query(F.data == "prof:daily")
async def cb_prof_daily(cb: CallbackQuery):
    u = await db.get_user(cb.from_user.id)
    now = int(time.time())
    diff = now - u["last_daily"]
    if diff < DAILY_COOLDOWN:
        r = DAILY_COOLDOWN - diff
        await cb.answer(f"⏳ Через {r // 3600}ч {(r % 3600) // 60}м", show_alert=True)
        return
    streak = u["daily_streak"] + 1 if diff < DAILY_COOLDOWN * 2 else 1
    _, _, c_mult, _ = get_active_events()
    coins = int((150 + min(streak, 10) * 35) * c_mult)
    await db.update_user(u["user_id"], last_daily=now, daily_streak=streak)
    await db.add_coins(u["user_id"], coins)
    p_key = "upgraded" if streak % 3 == 0 else "common"
    await db.add_parasite(u["user_id"], p_key, 1)
    await cb.answer(f"🎁 +{coins} 💰 + 1 {PARASITES[p_key][0]} (День {streak})", show_alert=True)
    await render_view(cb, await build_profile_text(await db.get_user(u["user_id"]), True), profile_kb())


@router.callback_query(F.data == "prof:search")
async def cb_prof_search(cb: CallbackQuery, state: FSMContext):
    await state.set_state(PlayerFSM.search)
    await cb.message.answer("🔎 Введите <b>@username</b> или <b>ID</b> игрока:")
    await cb.answer()


@router.message(PlayerFSM.search)
async def fsm_prof_search(m: Message, state: FSMContext):
    await state.clear()
    t = await db.find_user(m.text or "")
    if not t:
        await m.answer("❌ Игрок не найден.")
        return
    await m.answer(await build_profile_text(t, is_self=(t["user_id"] == m.from_user.id)))


async def render_mods(target: Message | CallbackQuery, uid: int, back_cb: str = "prof:ref"):
    u = await db.get_user(uid)
    cm = sum(v[1] for k, v in BATTLE_MODS.items() if u.get(k))
    im = sum(v[3] for k, v in BATTLE_MODS.items() if u.get(k))
    txt = (
        f"🧬 <b>МОДИФИКАТОРЫ БОЯ</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"🔴 Дебаффы увеличивают монеты, кубки и <b>шанс заражения</b>.\n"
        f"🟢 Баффы упрощают бой, но режут монеты.\n\n"
        f"📊 Итог: Монеты <b>{max(0.2, 1.0 + cm):.2f}x</b> | Заражение: <b>+{im}%</b> от шанса"
    )
    rows = [[InlineKeyboardButton(text=f"{'✅' if u.get(k) else '❌'} {v[0]}", callback_data=f"mod:{k}:{back_cb}")] for k, v in BATTLE_MODS.items()]
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data=back_cb)])
    await render_view(target, txt, InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "prof:mods")
async def cb_prof_mods(cb: CallbackQuery):
    await render_mods(cb, cb.from_user.id, "prof:ref")
    await cb.answer()


@router.callback_query(F.data.startswith("mod:"))
async def cb_mod_toggle(cb: CallbackQuery):
    _, k, back = cb.data.split(":", 2)
    u = await db.get_user(cb.from_user.id)
    await db.update_user(cb.from_user.id, **{k: 0 if u.get(k) else 1})
    await render_mods(cb, cb.from_user.id, back)
    await cb.answer()


# -------------------- ЭКИПИРОВКА 2.0 + ИНВЕНТАРЬ + ИНФО О КАРТЕ --------------------

async def render_deck(target: Message | CallbackQuery, uid: int):
    inv = await db.get_inventory(uid)
    smap = {c["equip_slot"]: c for c in inv if c["equip_slot"] > 0}
    pwr = sum(calc_card_stats(c)["power"] for c in smap.values())
    nums = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]
    lines = [f"🛡 <b>БОЕВАЯ КОЛОДА ({len(smap)}/{MAX_DECK_SIZE})</b> | ⚡ Мощь: <b>{pwr}</b>", "━━━━━━━━━━━━━━━━━━"]
    s_btns = []
    for s in range(1, MAX_DECK_SIZE + 1):
        c = smap.get(s)
        if c:
            st = calc_card_stats(c)
            r_ico = RARITIES.get(c["rarity"], ("", "⚪️", 1, 1.0))[1]
            c_ico = CARD_CLASSES.get(c["class_type"], ("🎯", ""))[0]
            stat = f"✨x{st['b_dmg']}/x{st['b_hp']}" if c["class_type"] == "Booster" else (f"💗{st['atk']} ❤️{st['hp']}" if c["class_type"] == "Healer" else f"⚔️{st['atk']} ❤️{st['hp']}")
            lines.append(f"{nums[s - 1]} {r_ico}{c_ico} <b>{esc(c['name'])}</b>{fmt_serial(c)}{card_badges(c)} Ур.{c['level']} [{stat}]")
            s_btns.append(InlineKeyboardButton(text=f"{nums[s - 1]} {c['name'][:12]}", callback_data=f"eq:slot:{s}:0"))
        else:
            lines.append(f"{nums[s - 1]} ⬜ <i>[Пустой слот]</i>")
            s_btns.append(InlineKeyboardButton(text=f"{nums[s - 1]} Пусто", callback_data=f"eq:slot:{s}:0"))

    rows = [
        s_btns[:2], s_btns[2:],
        [InlineKeyboardButton(text="⚡ Авто-колода", callback_data="eq:auto"), InlineKeyboardButton(text="❌ Снять всех", callback_data="eq:clear")],
        [InlineKeyboardButton(text=f"🎒 Инвентарь ({len(inv)})", callback_data="inv:all:0"), InlineKeyboardButton(text="📖 Энциклопедия", callback_data="enc:0")],
    ]
    await render_view(target, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows))


async def render_slot_picker(target: Message | CallbackQuery, uid: int, slot: int, page: int = 0):
    inv = await db.get_inventory(uid)
    cur = next((c for c in inv if c["equip_slot"] == slot), None)
    avail = [c for c in inv if not c.get("market_id") and c["equip_slot"] == 0]
    avail.sort(key=lambda x: (RARITIES.get(x["rarity"], ("", "", 0, 0))[2], x["is_shiny"], x["is_infected"], calc_card_stats(x)["power"]), reverse=True)
    per = 6
    tp = max(1, (len(avail) + per - 1) // per)
    page = max(0, min(page, tp - 1))

    txt = f"🎯 <b>СЛОТ #{slot}</b>\nТекущая карта: {('<b>' + esc(cur['name']) + '</b> ' + card_badges(cur)) if cur else '<i>Пусто</i>'}"
    rows = []
    if cur:
        rows.append([InlineKeyboardButton(text="ℹ️ Инфо", callback_data=f"c:v:{cur['inv_id']}:deck:0"), InlineKeyboardButton(text="➖ Освободить", callback_data=f"eq:un:{cur['inv_id']}")])
    for c in avail[page * per : (page + 1) * per]:
        r_ico = RARITIES.get(c["rarity"], ("", "⚪️", 1, 1.0))[1]
        sn = f" #{c['serial_number']:04d}" if c["serial_number"] else ""
        rows.append([InlineKeyboardButton(text=f"{r_ico}{card_badges(c)} {c['name']}{sn} (Ур.{c['level']})", callback_data=f"eq:put:{slot}:{c['inv_id']}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"eq:slot:{slot}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{tp}", callback_data="noop"))
    if page < tp - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"eq:slot:{slot}:{page + 1}"))
    rows.extend([nav, [InlineKeyboardButton(text="🔙 К колоде", callback_data="eq:home")]])
    await render_view(target, txt, InlineKeyboardMarkup(inline_keyboard=rows))


async def render_inventory(target: Message | CallbackQuery, uid: int, flt: str = "all", page: int = 0):
    inv = await db.get_inventory(uid)
    if flt == "sh":
        fl = [c for c in inv if c["is_shiny"]]
    elif flt == "inf":
        fl = [c for c in inv if c["is_infected"]]
    elif flt == "eq":
        fl = [c for c in inv if c["equip_slot"] > 0]
    else:
        fl = inv

    # Группируем обычные дубликаты (без серийника, не в колоде, не на рынке)
    stacks: List[Tuple[Dict[str, Any], int]] = []
    seen: Dict[Tuple, int] = {}
    for c in fl:
        if c["equip_slot"] > 0 or c.get("market_id") or c["serial_number"] > 0:
            stacks.append((c, 1))
            continue
        k = (c["card_id"], c["is_shiny"], c["is_infected"], c["sign_type"], c["level"])
        if k in seen:
            idx = seen[k]
            stacks[idx] = (stacks[idx][0], stacks[idx][1] + 1)
        else:
            seen[k] = len(stacks)
            stacks.append((c, 1))

    stacks.sort(key=lambda x: (1 if x[0]["equip_slot"] > 0 else 0, RARITIES.get(x[0]["rarity"], ("", "", 0, 0))[2], x[0]["is_shiny"], x[0]["is_infected"], x[0]["level"]), reverse=True)
    per = 7
    tp = max(1, (len(stacks) + per - 1) // per)
    page = max(0, min(page, tp - 1))

    rows = [[
        InlineKeyboardButton(text="• Все •" if flt == "all" else "Все", callback_data="inv:all:0"),
        InlineKeyboardButton(text="• ✨ •" if flt == "sh" else "✨ Shiny", callback_data="inv:sh:0"),
        InlineKeyboardButton(text="• 🦠 •" if flt == "inf" else "🦠 Зар.", callback_data="inv:inf:0"),
        InlineKeyboardButton(text="• ✅ •" if flt == "eq" else "✅ Колода", callback_data="inv:eq:0"),
    ]]
    for c, qty in stacks[page * per : (page + 1) * per]:
        r_ico = RARITIES.get(c["rarity"], ("", "⚪️", 1, 1.0))[1]
        tag = f"✅#{c['equip_slot']} " if c["equip_slot"] > 0 else ("🏷 " if c.get("market_id") else "")
        sn = f" [#{c['serial_number']:04d}]" if c["serial_number"] else ""
        q = f" x{qty}" if qty > 1 else ""
        rows.append([InlineKeyboardButton(text=f"{tag}{r_ico}{card_badges(c)} {c['name']}{sn} (Ур.{c['level']}){q}", callback_data=f"c:v:{c['inv_id']}:{flt}:{page}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"inv:{flt}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{tp}", callback_data="noop"))
    if page < tp - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"inv:{flt}:{page + 1}"))
    rows.extend([nav, [InlineKeyboardButton(text="🛡 К колоде", callback_data="eq:home")]])
    await render_view(target, f"🎒 <b>ИНВЕНТАРЬ КАРТ</b> (Всего: {len(inv)})", InlineKeyboardMarkup(inline_keyboard=rows))


async def render_card_view(target: Message | CallbackQuery, uid: int, inv_id: int, flt: str, page: int):
    item = await db.get_inv_item(inv_id)
    if not item or item["user_id"] != uid:
        await render_deck(target, uid)
        return
    ex_t, ex_s = await db.get_card_exist(item["card_id"])
    txt = format_card_info(item, ex_t, ex_s)
    inv = await db.get_inventory(uid)
    used = {c["equip_slot"] for c in inv if c["equip_slot"] > 0}
    free = next((s for s in range(1, MAX_DECK_SIZE + 1) if s not in used), None)

    rows = []
    if not item.get("market_id"):
        if item["equip_slot"] > 0:
            rows.append([InlineKeyboardButton(text=f"➖ Снять со слота #{item['equip_slot']}", callback_data=f"c:un:{inv_id}:{flt}:{page}")])
        elif free:
            rows.append([InlineKeyboardButton(text=f"✅ Надеть в слот #{free}", callback_data=f"c:eq:{inv_id}:{free}:{flt}:{page}")])
        else:
            rows.append([InlineKeyboardButton(text="🔄 Колода полна (выбрать слот)", callback_data="eq:home")])
        act = []
        role = await db.get_signer_role(uid)
        if role:
            pct = cfg_int("admin_sign_pct") if role == "admin" else cfg_int("partner_sign_pct")
            act.append(InlineKeyboardButton(text=f"{'👑' if role == 'admin' else '🤝'} Подписать (+{pct}%)", callback_data=f"c:sgn:{inv_id}:{flt}:{page}"))
        act.append(InlineKeyboardButton(text="🏷 На Рынок", callback_data=f"c:sell:{inv_id}"))
        rows.append(act)
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="eq:home" if flt == "deck" else f"inv:{flt}:{page}")])
    await render_view(target, txt, InlineKeyboardMarkup(inline_keyboard=rows), photo=item.get("photo_id") or None)


async def render_encyclopedia(target: Message | CallbackQuery, uid: int, page: int = 0):
    cards = await db.list_cards()
    owned = {c["card_id"] for c in await db.get_inventory(uid)}
    cards.sort(key=lambda x: RARITIES.get(x["rarity"], ("", "", 0, 0))[2], reverse=True)
    per = 7
    tp = max(1, (len(cards) + per - 1) // per)
    page = max(0, min(page, tp - 1))

    lines = [f"📖 <b>ЭНЦИКЛОПЕДИЯ</b> (Открыто {len(owned)}/{len(cards)})", "━━━━━━━━━━━━━━━━━━"]
    for c in cards[page * per : (page + 1) * per]:
        ex_t, ex_s = await db.get_card_exist(c["id"])
        _, r_ico, _, b_inf = RARITIES.get(c["rarity"], ("", "⚪️", 1, 1.0))
        if c["id"] in owned:
            c_ico = CARD_CLASSES.get(c["class_type"], ("🎯", ""))[0]
            lines.append(f"✅ {r_ico}{c_ico} <b>{esc(c['name'])}</b> (⚔️{c['atk']} ❤️{c['hp']} | 🌍{ex_t} ✨{ex_s} | 🦠{fmt_pct(b_inf)}%)")
        else:
            lines.append(f"❓ {r_ico} <b>???</b> (🌍{ex_t} ✨{ex_s} | 🦠{fmt_pct(b_inf)}%)")
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"enc:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{tp}", callback_data="noop"))
    if page < tp - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"enc:{page + 1}"))
    await render_view(target, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=[nav, [InlineKeyboardButton(text="🔙 К колоде", callback_data="eq:home")]]))


@router.message(F.text == "🃏 Колода и Карты")
async def menu_deck(m: Message, state: FSMContext):
    await state.clear()
    await render_deck(m, m.from_user.id)


@router.callback_query(F.data == "eq:home")
async def cb_eq_home(cb: CallbackQuery):
    await render_deck(cb, cb.from_user.id)
    await cb.answer()


@router.callback_query(F.data.startswith("eq:slot:"))
async def cb_eq_slot(cb: CallbackQuery):
    _, _, s, p = cb.data.split(":")
    await render_slot_picker(cb, cb.from_user.id, int(s), int(p))
    await cb.answer()


@router.callback_query(F.data.startswith("eq:put:"))
async def cb_eq_put(cb: CallbackQuery):
    _, _, s, iid = cb.data.split(":")
    await db.set_equip_slot(cb.from_user.id, int(iid), int(s))
    await cb.answer(f"✅ Надето в слот #{s}!")
    await render_deck(cb, cb.from_user.id)


@router.callback_query(F.data.startswith("eq:un:"))
async def cb_eq_un(cb: CallbackQuery):
    await db.set_equip_slot(cb.from_user.id, int(cb.data.split(":")[2]), 0)
    await cb.answer("➖ Снято!")
    await render_deck(cb, cb.from_user.id)


@router.callback_query(F.data == "eq:clear")
async def cb_eq_clear(cb: CallbackQuery):
    await db.clear_equip(cb.from_user.id)
    await cb.answer("❌ Очищено!")
    await render_deck(cb, cb.from_user.id)


@router.callback_query(F.data == "eq:auto")
async def cb_eq_auto(cb: CallbackQuery):
    uid = cb.from_user.id
    inv = [c for c in await db.get_inventory(uid) if not c.get("market_id")]
    if not inv:
        await cb.answer("Инвентарь пуст!", show_alert=True)
        return
    await db.clear_equip(uid)
    chosen: List[Dict[str, Any]] = []
    boosters = sorted([c for c in inv if c["class_type"] == "Booster"], key=lambda x: calc_card_stats(x)["b_dmg"], reverse=True)
    if boosters:
        chosen.append(boosters[0])
    by_pwr = sorted(inv, key=lambda x: calc_card_stats(x)["power"], reverse=True)
    for c in by_pwr:
        if len(chosen) >= MAX_DECK_SIZE:
            break
        if c["inv_id"] not in {x["inv_id"] for x in chosen}:
            chosen.append(c)
    for idx, c in enumerate(chosen, 1):
        await db.set_equip_slot(uid, c["inv_id"], idx)
    await cb.answer("⚡ Оптимальная колода собрана!", show_alert=True)
    await render_deck(cb, uid)


@router.callback_query(F.data.startswith("inv:"))
async def cb_inv(cb: CallbackQuery):
    _, flt, p = cb.data.split(":")
    await render_inventory(cb, cb.from_user.id, flt, int(p))
    await cb.answer()


@router.callback_query(F.data.startswith("enc:"))
async def cb_enc(cb: CallbackQuery):
    await render_encyclopedia(cb, cb.from_user.id, int(cb.data.split(":")[1]))
    await cb.answer()


@router.callback_query(F.data.startswith("c:v:"))
async def cb_cv(cb: CallbackQuery):
    _, _, iid, flt, p = cb.data.split(":")
    await render_card_view(cb, cb.from_user.id, int(iid), flt, int(p))
    await cb.answer()


@router.callback_query(F.data.startswith("c:eq:"))
async def cb_ceq(cb: CallbackQuery):
    _, _, iid, sl, flt, p = cb.data.split(":")
    await db.set_equip_slot(cb.from_user.id, int(iid), int(sl))
    await cb.answer(f"✅ Надето в слот #{sl}!")
    await render_card_view(cb, cb.from_user.id, int(iid), flt, int(p))


@router.callback_query(F.data.startswith("c:un:"))
async def cb_cun(cb: CallbackQuery):
    _, _, iid, flt, p = cb.data.split(":")
    await db.set_equip_slot(cb.from_user.id, int(iid), 0)
    await cb.answer("➖ Снято!")
    await render_card_view(cb, cb.from_user.id, int(iid), flt, int(p))


@router.callback_query(F.data.startswith("c:sgn:"))
async def cb_csgn(cb: CallbackQuery):
    _, _, iid, flt, p = cb.data.split(":")
    uid = cb.from_user.id
    role = await db.get_signer_role(uid)
    if not role:
        await cb.answer("Нет прав Сигнера!", show_alert=True)
        return
    u = await db.get_user(uid)
    who = f"@{u['username']}" if u and u.get("username") else (u["full_name"] if u else str(uid))
    await db.sign_inv_item(int(iid), role, who)
    pct = cfg_int("admin_sign_pct") if role == "admin" else cfg_int("partner_sign_pct")
    await cb.answer(f"✍️ Подписано (+{pct}% ATK/HP)!", show_alert=True)
    await render_card_view(cb, uid, int(iid), flt, int(p))


@router.callback_query(F.data.startswith("c:sell:"))
async def cb_csell(cb: CallbackQuery, state: FSMContext):
    iid = int(cb.data.split(":")[2])
    it = await db.get_inv_item(iid)
    if not it or it["user_id"] != cb.from_user.id or it.get("market_id"):
        await cb.answer("Карта недоступна.", show_alert=True)
        return
    await state.set_state(PlayerFSM.market_price)
    await state.update_data(sell_id=iid)
    await cb.message.answer(f"🏷 Введите цену для <b>{esc(it['name'])}</b> (50–500000 💰).\n<i>Вы получите <b>80%</b>, комиссия рынка — <b>20%</b>.</i>")
    await cb.answer()


@router.message(PlayerFSM.market_price)
async def fsm_sell(m: Message, state: FSMContext):
    iid = (await state.get_data()).get("sell_id")
    await state.clear()
    try:
        pr = int((m.text or "").strip())
        if not (50 <= pr <= 500000):
            raise ValueError
    except ValueError:
        await m.answer("❌ Введите число от 50 до 500000.")
        return
    it = await db.get_inv_item(iid)
    if not it or it["user_id"] != m.from_user.id or it.get("market_id"):
        await m.answer("❌ Карта недоступна.")
        return
    await db.create_market_lot(m.from_user.id, iid, pr)
    await m.answer(f"✅ <b>{esc(it['name'])}</b> выставлена за <b>{pr} 💰</b> (получите {int(pr * 0.8)} 💰).")


# ==============================================================================
# 6. БОИ 4×4 ПРОТИВ АЛЬЯНСА, ПАРАЗИТЫ И ЗАРАЖЕНИЕ ПРИ УБИЙСТВЕ
# ==============================================================================

async def render_battle_hub(target: Message | CallbackQuery, uid: int):
    u = await db.get_user(uid)
    _, r_name, _, r_rew, r_inf = get_rank_info(u["trophies"])
    armed = u["armed_parasite"]
    if armed in PARASITES and u[PARASITES[armed][1]] <= 0:
        armed = "none"
        await db.update_user(uid, armed_parasite="none")
    p_bonus = cfg_int(f"p_{armed}_bonus") if armed in PARASITES else 0
    p_label = f"{PARASITES[armed][0]} (+{p_bonus}%)" if armed in PARASITES else "Без паразита (+0%)"
    mod_inf = sum(v[3] for k, v in BATTLE_MODS.items() if u.get(k))
    l_mult, _, c_mult, _ = get_active_events()
    tot_bonus = r_inf + p_bonus + u["pity_bonus"] + mod_inf
    ex_com = fmt_pct(calc_infect_chance(1.0, tot_bonus, l_mult))
    ex_leg = fmt_pct(calc_infect_chance(0.0625, tot_bonus, l_mult))

    text = (
        f"⚔️ <b>БИТВА ЗА СКИБИДИ-ТУАЛЕТОВ (4×4)</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎖 Ранг: <b>{r_name}</b> (🏆 {u['trophies']} | 💰 x{r_rew} | 🦠 +{r_inf}%)\n"
        f"🦠 Паразит на бой: <b>{p_label}</b>\n"
        f"🎯 Пити: <b>+{u['pity_bonus']}%</b> | 🧬 Моды: <b>+{mod_inf}%</b>\n"
        f"📊 Шанс заразить в бою: Common <b>{ex_com}%</b> | Leg <b>{ex_leg}%</b>\n"
        + (f"🎉 Ивенты: 🍀x{l_mult} | 💰x{c_mult}\n" if (l_mult > 1 or c_mult > 1) else "")
        + "\n👇 Выберите сложность отряда Альянса:"
    )
    rows = [
        [InlineKeyboardButton(text=f"{name} (💰x{sc} | 🦠+{ib}%)", callback_data=f"btl:go:{k}")]
        for k, (name, _, sc, _, ib) in DIFFICULTIES.items()
    ]
    rows.append([
        InlineKeyboardButton(text="🦠 Выбрать паразита", callback_data="btl:par"),
        InlineKeyboardButton(text="🧬 Модификаторы", callback_data="btl:mods"),
    ])
    await render_view(target, text, InlineKeyboardMarkup(inline_keyboard=rows))


@router.message(F.text == "⚔️ В бой (Альянс)")
async def menu_battle(m: Message, state: FSMContext):
    await state.clear()
    await render_battle_hub(m, m.from_user.id)


@router.callback_query(F.data == "btl:hub")
async def cb_btl_hub(cb: CallbackQuery):
