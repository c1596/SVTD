"""
Skibidi Verse: Cards & Infection — Telegram Card RPG Bot
Стек: Python 3.10+, aiogram 3.x, aiosqlite (автоматическая установка при запуске).

Возможности:
- Статичное нижнее меню + инлайн-управление без команд
- 4×4 бои за Скибиди-Туалетов против отрядов Альянса (без пропуска боя, кнопка «Сдаться»)
- 31 ранг Скибиди-Туалетов (чем выше ранг, тем выше награды и шанс заражения)
- Заражение врагов при убийстве в бою по дробной формуле (% от базового числа)
- Уровни карт за нанесённый урон (1 урон = 0.1 XP, макс 50 ур., +0.5% к урону/ур.)
- ✨ Shiny мутация, серийные номера [#0001] на Mythic/Secret, Админ (+10%) и Партнёр (+5%) сигны
- Инвентарь и Индекс в стиле GGTD Cards (стаки, фильтры, Существует/Shiny/Инфектед, пересчёт от удачи)
- Массовая покупка и крафт паразитов (x1, x3, x5, x10, x25, МАКС) + Крейты + Кастомные валюты
- Мировой Босс, P2P-рынок (80% продавцу / 20% комиссия владельцу), Ивенты Удачи и Монет
- Расширенная Админ-панель с гибкими правами, логами и бэкапом/восстановлением БД
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
    """Проверяет и автоматически устанавливает отсутствующие библиотеки через pip."""
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
            print("✅ Библиотеки успешно установлены!")
        except Exception as exc:
            print(f"❌ Ошибка при установке библиотек: {exc}")
            sys.exit(1)


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

_env_token = (os.getenv("BOT_TOKEN") or "").strip().strip('"').strip("'")
BOT_TOKEN = (
    _env_token
    if (
        ":" in _env_token
        and _env_token.split(":", 1)[0].isdigit()
        and _env_token.split(":", 1)[1]
        and not any(ch.isspace() for ch in _env_token)
    )
    else DEFAULT_BOT_TOKEN
)
_env_owner = (os.getenv("OWNER_ID") or "").strip()
OWNER_ID = int(_env_owner) if _env_owner.isdigit() else DEFAULT_OWNER_ID
DB_PATH = (os.getenv("DB_PATH") or "").strip() or "skibidi_cards.db"

MAX_DECK_SIZE = 4
MAX_CARD_LEVEL = 50
XP_PER_DAMAGE = 0.1         # 1 урон = 0.1 XP карте
DMG_PCT_PER_LEVEL = 0.5     # +0.5% к урону за каждый уровень свыше 1
MARKET_COMMISSION_PCT = 20  # 20% комиссия владельцу, 80% продавцу
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

# Сложности: key -> (название, множ. статов ИИ, множ. кубков/монет, сдвиг редкости, +бонус зараж.%)
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
    "manage_currencies": "🪙 Валюты и дроп из боёв",
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

                CREATE TABLE IF NOT EXISTS user_discovered (
                    user_id INTEGER NOT NULL,
                    card_id INTEGER NOT NULL,
                    PRIMARY KEY (user_id, card_id)
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
            # Синхронизируем таблицу открытых карт из уже существующего инвентаря
            await conn.execute("INSERT OR IGNORE INTO user_discovered (user_id, card_id) SELECT DISTINCT user_id, card_id FROM inventory")
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
                        "INSERT INTO cards (name, faction, rarity, class_type, hp, atk, booster_dmg_mult, booster_hp_mult, hide_from_ai, description) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    await conn.execute("INSERT OR IGNORE INTO user_discovered (user_id, card_id) VALUES (?, ?)", (uid, st["id"]))
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
            r = (
                await (await conn.execute("SELECT * FROM users WHERE user_id = ?", (int(s),))).fetchone()
                if s.isdigit()
                else await (await conn.execute("SELECT * FROM users WHERE LOWER(username) = ?", (s,))).fetchone()
            )
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
                "SELECT c.id, c.name, COALESCE(uc.amount, 0) AS amount FROM currencies c LEFT JOIN user_currencies uc ON uc.currency_id = c.id AND uc.user_id = ? ORDER BY c.id ASC",
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
                "INSERT INTO user_currencies (user_id, currency_id, amount) VALUES (?, ?, MAX(0, ?)) ON CONFLICT(user_id, currency_id) DO UPDATE SET amount = MAX(0, amount + ?)",
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

    # -------------------- Карточки и Статистика Индекса --------------------

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
                "INSERT INTO cards (name, faction, rarity, class_type, hp, atk, booster_dmg_mult, booster_hp_mult, hide_from_ai, description, photo_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            await conn.execute("DELETE FROM user_discovered WHERE card_id = ?", (cid,))
            await conn.execute("DELETE FROM cards WHERE id = ?", (cid,))
            await conn.commit()

    async def get_card_exist_stats(self, cid: int) -> Tuple[int, int, int]:
        """Возвращает (всего существует, ✨ Shiny, 🦠 Инфектед) у игроков (без владельца)."""
        async with aiosqlite.connect(self.path) as conn:
            r = await (await conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(is_shiny), 0), COALESCE(SUM(is_infected), 0) FROM inventory WHERE card_id = ? AND user_id != ?",
                (cid, OWNER_ID),
            )).fetchone()
            return (r[0] or 0, r[1] or 0, r[2] or 0) if r else (0, 0, 0)

    async def get_discovered_ids(self, uid: int) -> Set[int]:
        async with aiosqlite.connect(self.path) as conn:
            rows = await (await conn.execute(
                "SELECT card_id FROM user_discovered WHERE user_id = ? UNION SELECT DISTINCT card_id FROM inventory WHERE user_id = ?",
                (uid, uid),
            )).fetchall()
            return {r[0] for r in rows}

    # -------------------- Инвентарь и Серийные номера --------------------

    async def give_card(
        self, uid: int, card_id: int, is_shiny: int = 0, is_infected: int = 0, sign_type: str = "none", signed_by: str = ""
    ) -> Tuple[int, int]:
        """Выдаёт карту, отмечает в Индексе и назначает серийник [#0001] для Mythic/Secret (обычные/Shiny раздельно)."""
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
                "INSERT INTO inventory (user_id, card_id, level, xp, is_shiny, is_infected, serial_number, sign_type, signed_by, equip_slot, acquired_at) VALUES (?, ?, 1, 0, ?, ?, ?, ?, ?, 0, ?)",
                (uid, card_id, is_shiny, is_infected, serial, sign_type, signed_by, int(time.time())),
            )
            await conn.execute("INSERT OR IGNORE INTO user_discovered (user_id, card_id) VALUES (?, ?)", (uid, card_id))
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
                "SELECT m.*, i.card_id, c.name FROM market m JOIN inventory i ON m.inv_id = i.id JOIN cards c ON i.card_id = c.id WHERE m.id = ?",
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
            await conn.execute("INSERT OR IGNORE INTO user_discovered (user_id, card_id) VALUES (?, ?)", (buyer_id, lot["card_id"]))
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
# 3. СТАТЫ КАРТ, 4×4 БОЕВОЙ ДВИЖОК И UI-ХЕЛПЕРЫ
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


def fmt_rarity_badge(rarity: str) -> str:
    r_name, r_ico, _, _ = RARITIES.get(rarity, ("Обычная", "⚪️", 1, 1.0))
    return f"{r_ico} <b>{r_name.upper()}</b> {r_ico}"


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
    Считает боевые статы карты:
    - Уровень (1..50): +0.5% к урону за каждый уровень свыше 1
    - ✨ Shiny: +25% к ATK и HP
    - 🦠 Инфектед: x1.20 к ATK и HP
    - Сигны: Админ (+10% ATK/HP), Партнёр (+5% ATK/HP)
    """
    lvl = max(1, min(MAX_CARD_LEVEL, int(item.get("level", 1))))
    lvl_dmg = 1.0 + ((lvl - 1) * DMG_PCT_PER_LEVEL / 100.0)
    sh_mult = (1.0 + cfg_float("shiny_bonus_pct") / 100.0) if item.get("is_shiny") else 1.0
    inf_mult = cfg_float("infected_mult") if item.get("is_infected") else 1.0
    st = item.get("sign_type", "none")
    sgn_mult = 1.0 + (
        cfg_float("admin_sign_pct") / 100.0
        if st == "admin"
        else (cfg_float("partner_sign_pct") / 100.0 if st == "partner" else 0.0)
    )

    hp = max(1, int(round(item["hp"] * sh_mult * inf_mult * sgn_mult)))
    atk = max(1, int(round(item["atk"] * lvl_dmg * sh_mult * inf_mult * sgn_mult)))
    b_bonus = (1.05 if item.get("is_shiny") else 1.0) * (1.05 if item.get("is_infected") else 1.0)
    b_dmg = round(float(item.get("booster_dmg_mult", 1.15)) * b_bonus, 2)
    b_hp = round(float(item.get("booster_hp_mult", 1.15)) * b_bonus, 2)
    return {
        "hp": hp,
        "atk": atk,
        "power": hp + atk * 4,
        "b_dmg": b_dmg,
        "b_hp": b_hp,
        "lvl_pct": round((lvl - 1) * DMG_PCT_PER_LEVEL, 1),
    }


def format_card_info(item: Dict[str, Any], ex_tot: int = 0, ex_sh: int = 0, ex_inf: int = 0) -> str:
    _, r_ico, _, base_inf = RARITIES.get(item["rarity"], ("Обычная", "⚪️", 1, 1.0))
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
    status = (
        "🏷 На P2P-рынке"
        if item.get("market_id")
        else (f"✅ Слот #{item['equip_slot']}" if item.get("equip_slot", 0) > 0 else "📦 В инвентаре")
    )

    lines = [
        f"{r_ico} {c_ico} <b>{esc(item['name'])}</b>{fmt_serial(item)} {card_badges(item)}",
        f"Фракция: {f_name} | {fmt_rarity_badge(item['rarity'])}",
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
        f"• 🌍 Существует: <b>{ex_tot}</b> шт. (✨ Shiny: <b>{ex_sh}</b> | 🦠 Инф: <b>{ex_inf}</b>)",
        f"• 🦠 Базовый шанс заразить: <b>{fmt_pct(base_inf)}%</b>",
    ])
    if item.get("description"):
        lines.append(f"\n📝 <i>{esc(item['description'])}</i>")
    return "\n".join(lines)


async def generate_enemy_team(rank_idx: int, diff_key: str) -> List[Dict[str, Any]]:
    """Подбирает отряд Альянса под ранг Скибиди-игрока и выбранную сложность."""
    _, d_mult, _, shift, _ = DIFFICULTIES[diff_key]
    r_diff_mult = SKIBIDI_RANKS[rank_idx][2]

    all_ai = await db.list_cards(ai_only=True)
    if not all_ai:
        all_ai = await db.list_cards()
    by_rar: Dict[str, List[Dict[str, Any]]] = {}
    for c in all_ai:
        by_rar.setdefault(c["rarity"], []).append(c)

    tier = min(6, max(0, (rank_idx // 4) + shift))
    rar_order = ["common", "uncommon", "rare", "epic", "legendary", "mythic", "secret"]

    team = []
    used: Set[int] = set()
    stat_scale = max(0.65, (r_diff_mult ** 0.55) * d_mult)

    for _ in range(4):
        r = random.random()
        pick_t = tier if r < 0.55 else (max(0, tier - 1) if r < 0.85 else min(6, tier + 1))
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


def render_battle_screen(
    title: str,
    p_name: str,
    t1: List[Dict[str, Any]],
    e_name: str,
    t2: List[Dict[str, Any]],
    logs: List[str],
    rnd: int,
    inf_cnt: int,
) -> str:
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


async def render_view(
    target: Message | CallbackQuery,
    text: str,
    kb: Optional[InlineKeyboardMarkup] = None,
    photo: Optional[str] = None,
) -> None:
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
        [KeyboardButton(text="⚔️ В бой (Альянс)"), KeyboardButton(text="🛡 Колода")],
        [KeyboardButton(text="🎒 Инвентарь"), KeyboardButton(text="📖 Индекс")],
        [KeyboardButton(text="📦 Крейты и Лаба"), KeyboardButton(text="🌐 Мультиплеер")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🏆 Рейтинг")],
    ]
    if is_admin:
        rows.append([KeyboardButton(text="⚙️ Админ-панель")])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Меню Скибиди-Туалетов...",
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
# 5. ОСНОВНОЙ РОУТЕР: СТАРТ, ПРОФИЛЬ, МОДЫ, КОЛОДА, ИНВЕНТАРЬ И ИНДЕКС (GGTD STYLE)
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


# -------------------- КОЛОДА (ЭКИПИРОВКА 2.0) --------------------

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
            stat = (
                f"✨x{st['b_dmg']}/x{st['b_hp']}"
                if c["class_type"] == "Booster"
                else (f"💗{st['atk']} ❤️{st['hp']}" if c["class_type"] == "Healer" else f"⚔️{st['atk']} ❤️{st['hp']}")
            )
            lines.append(f"{nums[s - 1]} {r_ico}{c_ico} <b>{esc(c['name'])}</b>{fmt_serial(c)}{card_badges(c)} Ур.{c['level']} [{stat}]")
            s_btns.append(InlineKeyboardButton(text=f"{nums[s - 1]} {c['name'][:12]}", callback_data=f"eq:slot:{s}:0"))
        else:
            lines.append(f"{nums[s - 1]} ⬜ <i>[Пустой слот]</i>")
            s_btns.append(InlineKeyboardButton(text=f"{nums[s - 1]} Пусто", callback_data=f"eq:slot:{s}:0"))

    rows = [
        s_btns[:2], s_btns[2:],
        [InlineKeyboardButton(text="⚡ Авто-колода", callback_data="eq:auto"), InlineKeyboardButton(text="❌ Снять всех", callback_data="eq:clear")],
        [InlineKeyboardButton(text=f"🎒 Инвентарь ({len(inv)})", callback_data="inv:all:0"), InlineKeyboardButton(text="📖 Индекс", callback_data="idx:0")],
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


# -------------------- ИНВЕНТАРЬ (В СТИЛЕ GGTD CARDS) --------------------

async def render_inventory(target: Message | CallbackQuery, uid: int, flt: str = "all", page: int = 0):
    u = await db.get_user(uid)
    inv = await db.get_inventory(uid)

    if flt == "sh":
        fl = [c for c in inv if c["is_shiny"]]
    elif flt == "inf":
        fl = [c for c in inv if c["is_infected"]]
    elif flt == "eq":
        fl = [c for c in inv if c["equip_slot"] > 0]
    else:
        fl = inv

    # Группировка дубликатов (стаки), сохраняя уникальные с серийником, подписью, в колоде или на рынке отдельно
    stacks: List[Tuple[Dict[str, Any], int]] = []
    seen: Dict[Tuple, int] = {}
    for c in fl:
        if c["equip_slot"] > 0 or c.get("market_id") or c["serial_number"] > 0 or c["sign_type"] != "none":
            stacks.append((c, 1))
            continue
        k = (c["card_id"], c["is_shiny"], c["is_infected"], c["level"])
        if k in seen:
            idx = seen[k]
            stacks[idx] = (stacks[idx][0], stacks[idx][1] + 1)
        else:
            seen[k] = len(stacks)
            stacks.append((c, 1))

    # Сортировка как в GGTD Cards: подписанные -> редкость -> Shiny -> Инфектед -> уровень -> ID
    stacks.sort(
        key=lambda x: (
            1 if x[0]["sign_type"] != "none" else 0,
            RARITIES.get(x[0]["rarity"], ("", "", 0, 0))[2],
            x[0]["is_shiny"],
            x[0]["is_infected"],
            x[0]["level"],
            x[0]["card_id"],
        ),
        reverse=True,
    )

    per = 10
    tp = max(1, (len(stacks) + per - 1) // per)
    page = max(0, min(page, tp - 1))
    chunk = stacks[page * per : (page + 1) * per]

    unique_cnt = len({c["card_id"] for c in inv})
    shiny_cnt = sum(1 for c in inv if c["is_shiny"])
    inf_cnt = sum(1 for c in inv if c["is_infected"])
    flt_names = {"all": "Все", "sh": "✨ Shiny", "inf": "🦠 Заражённые", "eq": "✅ В колоде"}

    lines = [
        f"🎒 <b>ИНВЕНТАРЬ КАРТ — {flt_names.get(flt, 'Все')} (Стр. {page + 1}/{tp})</b>",
        f"🃏 Всего: <b>{len(inv)}</b> (Уник: {unique_cnt} | ✨{shiny_cnt} | 🦠{inf_cnt})",
        f"🦠 Паразиты: 🦠<b>{u['p_common']}</b> | ☣️<b>{u['p_upgraded']}</b> | 💎<b>{u['p_elite']}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    if not chunk:
        lines.append("<i>В этом разделе пока пусто.</i>")
    else:
        for idx, (c, qty) in enumerate(chunk, page * per + 1):
            r_ico = RARITIES.get(c["rarity"], ("", "⚪️", 1, 1.0))[1]
            c_ico = CARD_CLASSES.get(c["class_type"], ("🎯", ""))[0]
            tag = f"✅#{c['equip_slot']} " if c["equip_slot"] > 0 else ("🏷 " if c.get("market_id") else "")
            b = card_badges(c)
            sn = fmt_serial(c)
            sgn_str = f" <i>(✍️ {esc(c['signed_by'])})</i>" if c["sign_type"] != "none" and c.get("signed_by") else ""
            lines.append(f"{idx}. {tag}{r_ico}{c_ico} <b>{esc(c['name'])}</b>{sn}{b}{sgn_str} [Ур.{c['level']}] — <b>{qty} шт.</b>")

    lines.append("\n👇 <i>Нажмите на номер карты ниже, чтобы открыть Инфо, надеть или продать:</i>")

    rows: List[List[InlineKeyboardButton]] = [[
        InlineKeyboardButton(text="• Все •" if flt == "all" else "Все", callback_data="inv:all:0"),
        InlineKeyboardButton(text="• ✨ •" if flt == "sh" else "✨ Shiny", callback_data="inv:sh:0"),
        InlineKeyboardButton(text="• 🦠 •" if flt == "inf" else "🦠 Зар.", callback_data="inv:inf:0"),
        InlineKeyboardButton(text="• ✅ •" if flt == "eq" else "✅ Колода", callback_data="inv:eq:0"),
    ]]

    btn_row: List[InlineKeyboardButton] = []
    for idx, (c, _) in enumerate(chunk, page * per + 1):
        r_ico = RARITIES.get(c["rarity"], ("", "⚪️", 1, 1.0))[1]
        btn_row.append(InlineKeyboardButton(text=f"{idx}. {r_ico} {c['name'][:11]}", callback_data=f"c:v:{c['inv_id']}:{flt}:{page}"))
        if len(btn_row) == 2:
            rows.append(btn_row)
            btn_row = []
    if btn_row:
        rows.append(btn_row)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"inv:{flt}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{tp}", callback_data="noop"))
    if page < tp - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"inv:{flt}:{page + 1}"))
    rows.append(nav)
    rows.append([
        InlineKeyboardButton(text="🛡 Экипировка", callback_data="eq:home"),
        InlineKeyboardButton(text="📖 Индекс", callback_data="idx:0"),
    ])
    await render_view(target, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows))


async def render_card_view(target: Message | CallbackQuery, uid: int, inv_id: int, flt: str, page: int):
    item = await db.get_inv_item(inv_id)
    if not item or item["user_id"] != uid:
        await render_inventory(target, uid, "all", 0)
        return
    ex_t, ex_s, ex_i = await db.get_card_exist_stats(item["card_id"])
    txt = format_card_info(item, ex_t, ex_s, ex_i)
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


# -------------------- ИНДЕКС КАРТ (В СТИЛЕ GGTD CARDS) --------------------

async def render_index(target: Message | CallbackQuery, uid: int, page: int = 0):
    all_cards = await db.list_cards()
    discovered = await db.get_discovered_ids(uid)
    u = await db.get_user(uid)
    _, _, _, _, r_inf = get_rank_info(u["trophies"])
    l_mult, _, _, _ = get_active_events()

    # Собираем, из каких крейтов выпадает каждая карта и её реальный шанс в крейте
    crates = await db.list_crates(active_only=True)
    crate_sources: Dict[int, List[str]] = {}
    for cr in crates:
        w_map = cr["cards"]
        tot_w = 0.0
        eff_w: Dict[int, float] = {}
        by_id = {c["id"]: c for c in all_cards}
        for k, v in w_map.items():
            cid = int(k)
            if cid in by_id and float(v) > 0:
                fw = float(v) * (l_mult if by_id[cid]["rarity"] in ("epic", "legendary", "mythic", "secret") else 1.0)
                eff_w[cid] = fw
                tot_w += fw
        if tot_w > 0:
            for cid, fw in eff_w.items():
                pct = (fw / tot_w) * 100.0
                crate_sources.setdefault(cid, []).append(f"{cr['name']} ({pct:.2f}%)")

    # Сортировка как в GGTD Cards: от самых редких (Secret -> Mythic -> ... -> Common)
    all_cards.sort(key=lambda c: (RARITIES.get(c["rarity"], ("", "", 0, 0))[2], c["id"]), reverse=True)

    per = 6
    tp = max(1, (len(all_cards) + per - 1) // per)
    page = max(0, min(page, tp - 1))
    chunk = all_cards[page * per : (page + 1) * per]

    lines = [
        f"📖 <b>ИНДЕКС КАРТ (Стр. {page + 1}/{tp})</b>",
        f"🧩 Открыто: <b>{len(discovered)}/{len(all_cards)}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    if l_mult > 1.0:
        lines.append(f"🍀 <b>УДАЧА ПОВЫШЕНА (x{l_mult:.2f})! Шансы пересчитаны!</b>\n")

    for i, c in enumerate(chunk, page * per + 1):
        ex_tot, ex_sh, ex_inf = await db.get_card_exist_stats(c["id"])
        r_badge = fmt_rarity_badge(c["rarity"])
        c_ico = CARD_CLASSES.get(c["class_type"], ("🎯", ""))[0]
        base_inf = RARITIES.get(c["rarity"], ("", "", 1, 1.0))[3]
        eff_inf = calc_infect_chance(base_inf, r_inf, l_mult)

        src_parts = []
        if not c["hide_from_ai"]:
            src_parts.append(f"🦠 Зараж.: {fmt_pct(eff_inf)}%")
        if c["id"] in crate_sources:
            src_parts.append("📦 " + ", ".join(crate_sources[c["id"]][:2]))
        src_str = " | ".join(src_parts) if src_parts else "Эксклюзив"

        sub_exist = []
        if ex_sh > 0:
            sub_exist.append(f"✨ Shiny: {ex_sh}")
        if ex_inf > 0:
            sub_exist.append(f"🦠 Инф: {ex_inf}")
        sub_line = f"\n   └ <i>Из них: {', '.join(sub_exist)}</i>" if sub_exist else ""

        if c["id"] in discovered:
            if c["class_type"] == "Booster":
                stat_line = f"✨ Бафф: ATK x{c['booster_dmg_mult']} // HP x{c['booster_hp_mult']}"
            elif c["class_type"] == "Healer":
                stat_line = f"💗 Лечение: {c['atk']} // ❤️ Здоровье: {c['hp']}"
            else:
                stat_line = f"⚔️ Урон: {c['atk']} // ❤️ Здоровье: {c['hp']}"
            lines.append(
                f"{i}. {c_ico} <b>{esc(c['name'])}</b>\n"
                f"   └ 💎 {r_badge}\n"
                f"   └ 🎯 {src_str}\n"
                f"   └ {stat_line}\n"
                f"   └ 🌍 Существует: <b>{ex_tot} шт.</b>{sub_line}\n"
            )
        else:
            lines.append(
                f"{i}. <b>???</b> <i>(Не открыто)</i>\n"
                f"   └ 💎 {r_badge}\n"
                f"   └ 🎯 {src_str}\n"
                f"   └ 🌍 Существует: <b>{ex_tot} шт.</b>{sub_line}\n"
            )

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"idx:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{tp}", callback_data="noop"))
    if page < tp - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"idx:{page + 1}"))

    kb = InlineKeyboardMarkup(inline_keyboard=[
        nav,
        [InlineKeyboardButton(text="🎒 Инвентарь", callback_data="inv:all:0"), InlineKeyboardButton(text="🛡 Колода", callback_data="eq:home")],
    ])
    await render_view(target, "\n".join(lines), kb)


@router.message(F.text == "🛡 Колода")
async def menu_deck(m: Message, state: FSMContext):
    await state.clear()
    await render_deck(m, m.from_user.id)


@router.message(F.text == "🎒 Инвентарь")
async def menu_inv(m: Message, state: FSMContext):
    await state.clear()
    await render_inventory(m, m.from_user.id, "all", 0)


@router.message(F.text == "📖 Индекс")
async def menu_idx(m: Message, state: FSMContext):
    await state.clear()
    await render_index(m, m.from_user.id, 0)


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
    await cb.answer("❌ Колода очищена!")
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


@router.callback_query(F.data.startswith("idx:"))
async def cb_idx(cb: CallbackQuery):
    await render_index(cb, cb.from_user.id, int(cb.data.split(":")[1]))
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
# 6. БОИ 4×4 ПРОТИВ АЛЬЯНСА (БЕЗ ПРОПУСКА БОЯ!) И ЗАРАЖЕНИЕ ПРИ УБИЙСТВЕ
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
    await render_battle_hub(cb, cb.from_user.id)
    await cb.answer()


@router.callback_query(F.data == "btl:mods")
async def cb_btl_mods(cb: CallbackQuery):
    await render_mods(cb, cb.from_user.id, "btl:hub")
    await cb.answer()


@router.callback_query(F.data == "btl:par")
async def cb_btl_par(cb: CallbackQuery):
    u = await db.get_user(cb.from_user.id)
    armed = u["armed_parasite"]
    rows = [[InlineKeyboardButton(text=("✅ " if armed == "none" else "") + "Без паразита (+0%)", callback_data="btl:sp:none")]]
    for k in ("common", "upgraded", "elite"):
        name, col, _, bon = get_parasite_info(k)
        mark = "✅ " if armed == k else ""
        rows.append([InlineKeyboardButton(text=f"{mark}{name} (+{bon}%) — {u[col]} шт.", callback_data=f"btl:sp:{k}")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="btl:hub")])
    await render_view(
        cb,
        "🦠 <b>ВЫБОР ПАРАЗИТА НА БОЙ</b>\n1 паразит тратится при старте боя и усиливает шанс заражения всех 4 врагов.",
        InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("btl:sp:"))
async def cb_btl_sp(cb: CallbackQuery):
    p_key = cb.data.split(":")[2]
    uid = cb.from_user.id
    if p_key != "none":
        u = await db.get_user(uid)
        if u[PARASITES[p_key][1]] <= 0:
            await cb.answer("У вас нет этого паразита! Купите в Лаборатории.", show_alert=True)
            return
    await db.update_user(uid, armed_parasite=p_key)
    await cb.answer("✅ Паразит выбран!")
    await render_battle_hub(cb, uid)


@router.callback_query(F.data.startswith("btl:surr:"))
async def cb_btl_surr(cb: CallbackQuery):
    bid = cb.data.split(":")[2]
    st = ACTIVE_BATTLES.get(bid)
    if not st or cb.from_user.id != st["uid"]:
        await cb.answer("Бой уже завершён.")
        return
    st["surrendered"] = True
    await cb.answer("🏳️ Вы сдались!", show_alert=True)


@router.callback_query(F.data.startswith("btl:go:"))
async def cb_btl_go(cb: CallbackQuery):
    uid = cb.from_user.id
    if uid in USERS_IN_BATTLE:
        await cb.answer("Вы уже в бою!", show_alert=True)
        return
    deck = await db.get_inventory(uid, only_equipped=True)
    if not deck:
        await cb.answer("Сначала наденьте карты в «🛡 Колода»!", show_alert=True)
        return
    diff_key = cb.data.split(":")[2]
    if diff_key not in DIFFICULTIES:
        return
    USERS_IN_BATTLE.add(uid)
    await cb.answer("⚔️ Начинаем бой!")
    asyncio.create_task(run_4v4_battle_task(cb.message, uid, diff_key, deck))


async def safe_edit_btl(msg: Message, text: str, kb: Optional[InlineKeyboardMarkup] = None) -> None:
    try:
        await msg.edit_text(text[:4096], reply_markup=kb)
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        try:
            await msg.edit_text(text[:4096], reply_markup=kb)
        except Exception:
            pass
    except Exception:
        pass


async def run_4v4_battle_task(origin: Message, uid: int, diff_key: str, deck: List[Dict[str, Any]]) -> None:
    bid = uuid.uuid4().hex[:10]
    ACTIVE_BATTLES[bid] = {"uid": uid, "surrendered": False}
    try:
        u = await db.get_user(uid)
        r_idx, r_name, _, r_rew, r_inf = get_rank_info(u["trophies"])
        diff_name, _, diff_scale, _, diff_inf = DIFFICULTIES[diff_key]
        l_mult, _, c_mult, _ = get_active_events()

        # Расход выбранного паразита
        armed = u["armed_parasite"]
        p_bonus = 0
        if armed in PARASITES and u[PARASITES[armed][1]] > 0:
            await db.add_parasite(uid, armed, -1)
            p_bonus = cfg_int(f"p_{armed}_bonus")
        elif armed != "none":
            await db.update_user(uid, armed_parasite="none")

        mods = {k: u.get(k, 0) for k in BATTLE_MODS}
        mod_coin = sum(v[1] for k, v in BATTLE_MODS.items() if mods[k])
        mod_tr = sum(v[2] for k, v in BATTLE_MODS.items() if mods[k])
        mod_inf = sum(v[3] for k, v in BATTLE_MODS.items() if mods[k])

        infect_bonus_pct = r_inf + diff_inf + p_bonus + u["pity_bonus"] + mod_inf

        p_hp_m = 1.3 if mods["mod_player_hp"] else 1.0
        p_crit = 0.20 if mods["mod_player_crit"] else 0.0
        t1 = [build_player_unit(c, hp_mult=p_hp_m) for c in deck]
        t2 = await generate_enemy_team(r_idx, diff_key)

        if mods["mod_enemy_hp"]:
            for e in t2:
                e["hp"] = int(e["hp"] * 1.5)
                e["max_hp"] = e["hp"]
        if mods["mod_enemy_stats"]:
            for e in t2:
                e["hp"] = int(e["hp"] * 1.25)
                e["max_hp"] = e["hp"]
                e["atk"] = int(e["atk"] * 1.25)

        logs: List[str] = []
        apply_boosters_team(t1, u["full_name"], logs)
        apply_boosters_team(t2, f"Альянс ({diff_name})", logs)

        title = f"⚔️ {diff_name} | {r_name}"
        # Пропуск боя убран — оставлена только кнопка «Сдаться»
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏳️ Сдаться", callback_data=f"btl:surr:{bid}")]])
        msg = await origin.answer(render_battle_screen(title, u["full_name"], t1, f"Отряд ({diff_name})", t2, logs, 0, 0), reply_markup=kb)

        delay = cfg_float("battle_delay_sec")
        dmg_tracker: Dict[int, float] = {}
        infected_drops: List[Dict[str, Any]] = []
        st = ACTIVE_BATTLES[bid]
        winner = 0

        for rnd in range(1, 36):
            if st["surrendered"]:
                winner = 2
                break
            if not any(x["hp"] > 0 for x in t2):
                winner = 1
                break
            if not any(x["hp"] > 0 for x in t1):
                winner = 2
                break

            perform_combat_turn(t1, t2, True, logs, dmg_tracker, infected_drops, infect_bonus_pct, l_mult, crit_chance=p_crit)
            if any(x["hp"] > 0 for x in t2):
                if mods["mod_enemy_regen"]:
                    for e in t2:
                        if e["hp"] > 0:
                            e["hp"] = min(e["max_hp"], e["hp"] + max(2, int(e["max_hp"] * 0.05)))
                perform_combat_turn(t2, t1, False, logs, dmg_tracker, infected_drops, infect_bonus_pct, l_mult)

            await safe_edit_btl(msg, render_battle_screen(title, u["full_name"], t1, f"Отряд ({diff_name})", t2, logs, rnd, len(infected_drops)), kb)
            ticks = max(1, int(delay / 0.2))
            for _ in range(ticks):
                if st["surrendered"]:
                    break
                await asyncio.sleep(0.2)

        if winner == 0:
            r1 = sum(x["hp"] for x in t1) / max(1, sum(x["max_hp"] for x in t1))
            r2 = sum(x["hp"] for x in t2) / max(1, sum(x["max_hp"] for x in t2))
            winner = 1 if r1 >= r2 else 2

        total_dmg = sum(dmg_tracker.values())
        lvl_notes = []
        for inv_id, dmg in dmg_tracker.items():
            gained = round(dmg * XP_PER_DAMAGE, 2)
            if gained <= 0:
                continue
            item = await db.get_inv_item(inv_id)
            if item and item["user_id"] == uid:
                nl, nx, ups = apply_card_xp(item["level"], item["xp"], gained)
                await db.update_inv_xp(inv_id, nl, nx)
                if ups > 0:
                    lvl_notes.append(f"⭐ {esc(item['name'])} ➔ Ур.{nl}")

        fresh = await db.get_user(uid)
        if winner == 1:
            coins_won = max(15, int(random.randint(35, 85) * r_rew * diff_scale * max(0.2, 1.0 + mod_coin) * c_mult))
            base_tr = random.randint(1, 2) if r_idx >= 29 else max(5, 18 - int((r_idx / 28) * 11))
            tr_won = max(1, int(base_tr * diff_scale * (1.0 + mod_tr)))

            await db.add_coins(uid, coins_won)
            await db.add_trophies(uid, tr_won)

            cur_drops = []
            for cur in await db.list_currencies():
                if cur["drop_in_battles"] and (random.random() * 100.0) < (cur["drop_chance"] * l_mult):
                    amt = random.randint(cur["drop_min"], max(cur["drop_min"], cur["drop_max"]))
                    await db.add_user_currency(uid, cur["id"], amt)
                    cur_drops.append(f"+{amt} {esc(cur['name'])}")

            inf_lines = []
            for d in infected_drops:
                sh = roll_shiny()
                _, sn = await db.give_card(uid, d["card_id"], is_shiny=sh, is_infected=1)
                r_ico = RARITIES.get(d["rarity"], ("", "⚪️", 1, 1.0))[1]
                sn_s = f" <b>[#{sn:04d}]</b>" if sn else ""
                sh_s = " ✨<b>SHINY</b>" if sh else ""
                inf_lines.append(f"  └ 🦠 {r_ico} <b>{esc(d['name'])}</b>{sn_s}{sh_s} ({fmt_pct(d['chance'])}%)")

            new_pity = 0 if infected_drops else min(50, fresh["pity_bonus"] + 2)
            await db.update_user(
                uid,
                wins=fresh["wins"] + 1,
                total_damage=round(fresh["total_damage"] + total_dmg, 1),
                infections_success=fresh["infections_success"] + len(infected_drops),
                pity_bonus=new_pity,
            )

            fin = [
                f"🏆 <b>ПОБЕДА СКИБИДИ-ТУАЛЕТОВ!</b> ({diff_name})",
                "━━━━━━━━━━━━━━━━━━",
                f"💰 Монеты: <b>+{coins_won}</b>" + (f" (Ивент x{c_mult})" if c_mult > 1 else ""),
                f"🏆 Кубки: <b>+{tr_won}</b> | 💥 Урон: <b>{int(total_dmg)}</b>",
            ]
            if cur_drops:
                fin.append("🪙 Дроп валют: <b>" + ", ".join(cur_drops) + "</b>")
            if inf_lines:
                fin.append("\n🦠💥 <b>ЗАРАЖЁННЫЕ ТРОФЕИ:</b>\n" + "\n".join(inf_lines))
            else:
                fin.append(f"🎯 Заражений нет — Пити: <b>+{new_pity}%</b>")
            if lvl_notes:
                fin.append("📈 Ап уровней: " + ", ".join(lvl_notes[:4]))
        else:
            tr_loss = random.randint(25, 45) if r_idx >= 29 else 3
            await db.add_trophies(uid, -tr_loss)
            await db.update_user(uid, losses=fresh["losses"] + 1, total_damage=round(fresh["total_damage"] + total_dmg, 1))
            fin = [
                f"💀 <b>ПОРАЖЕНИЕ ОТ АЛЬЯНСА</b> ({diff_name})",
                "━━━━━━━━━━━━━━━━━━",
                f"🏆 Потеряно кубков: <b>-{tr_loss}</b> | 💥 Урон: <b>{int(total_dmg)}</b>",
                "<i>Заражённые враги сбежали (для захвата нужна победа).</i>",
            ]
            if lvl_notes:
                fin.append("📈 Ап уровней: " + ", ".join(lvl_notes[:4]))

        end_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔁 Ещё бой", callback_data=f"btl:go:{diff_key}"),
            InlineKeyboardButton(text="⚔️ К сложностям", callback_data="btl:hub"),
        ]])
        await safe_edit_btl(msg, "\n".join(fin), end_kb)
    except Exception as exc:
        logger.exception("Battle error: %s", exc)
    finally:
        ACTIVE_BATTLES.pop(bid, None)
        USERS_IN_BATTLE.discard(uid)


# ==============================================================================
# 7. КРЕЙТЫ И ЛАБОРАТОРИЯ (МАССОВАЯ ПОКУПКА И КРАФТ ПАРАЗИТОВ)
# ==============================================================================

async def render_lab(target: Message | CallbackQuery, uid: int):
    u = await db.get_user(uid)
    crates = await db.list_crates(active_only=True)
    curs = {c["id"]: c["name"] for c in await db.list_currencies()}
    cp, cb = cfg_int("p_common_price"), cfg_int("p_common_bonus")
    up, ub = cfg_int("p_upgraded_price"), cfg_int("p_upgraded_bonus")
    ep, eb = cfg_int("p_elite_price"), cfg_int("p_elite_bonus")
    l_mult, _, _, _ = get_active_events()

    txt = (
        f"📦 <b>КРЕЙТЫ И ЛАБОРАТОРИЯ</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"💰 Монеты: <b>{u['coins']}</b>\n"
        f"🦠 Паразиты: Обыч. <b>{u['p_common']}</b> | Улучш. <b>{u['p_upgraded']}</b> | Элит. <b>{u['p_elite']}</b>\n\n"
        f"🧪 <b>Паразиты (бонус % от шанса заражения):</b>\n"
        f"• 🦠 Обыч. (+{cb}% — {cp}💰)\n"
        f"• ☣️ Улучш. (+{ub}% — {up}💰)\n"
        f"• 💎 Элит. (+{eb}% — {ep}💰)\n\n"
        f"📦 <b>Кейсы</b> (✨ Shiny: <b>{fmt_pct(cfg_float('shiny_chance_pct') * l_mult)}%</b>):"
    )
    rows = [
        [
            InlineKeyboardButton(text=f"🦠 Купить Обыч. ({cp}💰)", callback_data="lab:pm:common"),
            InlineKeyboardButton(text=f"☣️ Купить Улучш. ({up}💰)", callback_data="lab:pm:upgraded"),
        ],
        [InlineKeyboardButton(text=f"💎 Купить Элитного ({ep}💰)", callback_data="lab:pm:elite")],
        [
            InlineKeyboardButton(text="⚗️ Крафт 3🦠➔1☣️", callback_data="lab:cr:upgraded:1"),
            InlineKeyboardButton(text="⚗️ МАКС 🦠➔☣️", callback_data="lab:cr:upgraded:max"),
        ],
        [
            InlineKeyboardButton(text="⚗️ Крафт 3☣️➔1💎", callback_data="lab:cr:elite:1"),
            InlineKeyboardButton(text="⚗️ МАКС ☣️➔💎", callback_data="lab:cr:elite:max"),
        ],
    ]
    for cr in crates:
        cname = "💰" if cr["currency_id"] == 0 else curs.get(cr["currency_id"], "🪙")
        rows.append([InlineKeyboardButton(text=f"📦 {cr['name']} — {cr['price']} {cname}", callback_data=f"cr:v:{cr['id']}")])
    await render_view(target, txt, InlineKeyboardMarkup(inline_keyboard=rows))


async def render_parasite_buy_menu(target: Message | CallbackQuery, uid: int, p_key: str):
    """Меню массовой покупки выбранного паразита (x1, x3, x5, x10, x25, МАКС)."""
    u = await db.get_user(uid)
    name, col, price, bonus = get_parasite_info(p_key)
    owned = u[col]
    max_buy = u["coins"] // price if price > 0 else 0

    txt = (
        f"🧪 <b>ПОКУПКА: {name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🦠 Бонус к шансу заражения: <b>+{bonus}%</b> от шанса\n"
        f"💵 Цена за 1 шт.: <b>{price} 💰</b>\n"
        f"💰 Ваш баланс: <b>{u['coins']}</b> | У вас есть: <b>{owned} шт.</b>\n\n"
        f"👇 Выберите количество для покупки:"
    )
    rows = [
        [
            InlineKeyboardButton(text=f"x1 ({price}💰)", callback_data=f"lab:buy:{p_key}:1"),
            InlineKeyboardButton(text=f"x3 ({price * 3}💰)", callback_data=f"lab:buy:{p_key}:3"),
            InlineKeyboardButton(text=f"x5 ({price * 5}💰)", callback_data=f"lab:buy:{p_key}:5"),
        ],
        [
            InlineKeyboardButton(text=f"x10 ({price * 10}💰)", callback_data=f"lab:buy:{p_key}:10"),
            InlineKeyboardButton(text=f"x25 ({price * 25}💰)", callback_data=f"lab:buy:{p_key}:25"),
        ],
    ]
    if max_buy > 0:
        rows.append([InlineKeyboardButton(text=f"🔥 Купить МАКС ({max_buy} шт. — {max_buy * price}💰)", callback_data=f"lab:buy:{p_key}:max")])
    rows.append([InlineKeyboardButton(text="🔙 Назад в Лабораторию", callback_data="lab:home")])
    await render_view(target, txt, InlineKeyboardMarkup(inline_keyboard=rows))


@router.message(F.text == "📦 Крейты и Лаба")
async def menu_lab(m: Message, state: FSMContext):
    await state.clear()
    await render_lab(m, m.from_user.id)


@router.callback_query(F.data == "lab:home")
async def cb_lab_home(cb: CallbackQuery):
    await render_lab(cb, cb.from_user.id)
    await cb.answer()


@router.callback_query(F.data.startswith("lab:pm:"))
async def cb_lab_pm(cb: CallbackQuery):
    p_key = cb.data.split(":")[2]
    if p_key not in PARASITES:
        return
    await render_parasite_buy_menu(cb, cb.from_user.id, p_key)
    await cb.answer()


@router.callback_query(F.data.startswith("lab:buy:"))
async def cb_lab_buy(cb: CallbackQuery):
    _, _, pk, amt_s = cb.data.split(":")
    if pk not in PARASITES:
        return
    name, _, price, _ = get_parasite_info(pk)
    u = await db.get_user(cb.from_user.id)

    amt = (u["coins"] // price if price > 0 else 0) if amt_s == "max" else int(amt_s)
    if amt <= 0:
        await cb.answer(f"Недостаточно монет! Нужно минимум {price} 💰.", show_alert=True)
        return
    cost = price * amt
    if u["coins"] < cost:
        await cb.answer(f"Недостаточно монет! Нужно {cost} 💰.", show_alert=True)
        return
    await db.add_coins(u["user_id"], -cost)
    await db.add_parasite(u["user_id"], pk, amt)
    await cb.answer(f"✅ Куплено {amt} шт. «{name}» (-{cost}💰)!", show_alert=True)
    await render_parasite_buy_menu(cb, u["user_id"], pk)


@router.callback_query(F.data.startswith("lab:cr:"))
async def cb_lab_cr(cb: CallbackQuery):
    _, _, tgt, mode = cb.data.split(":")
    src = "common" if tgt == "upgraded" else "upgraded"
    u = await db.get_user(cb.from_user.id)
    have = u[PARASITES[src][1]]
    crafts = (have // 3) if mode == "max" else (1 if have >= 3 else 0)
    if crafts <= 0:
        await cb.answer(f"Нужно минимум 3 шт. «{PARASITES[src][0]}»!", show_alert=True)
        return
    await db.add_parasite(u["user_id"], src, -(crafts * 3))
    await db.add_parasite(u["user_id"], tgt, crafts)
    await cb.answer(f"⚗️ Скрафчено {crafts} шт. «{PARASITES[tgt][0]}»!", show_alert=True)
    await render_lab(cb, u["user_id"])


@router.callback_query(F.data.startswith("cr:v:"))
async def cb_cr_view(cb: CallbackQuery):
    cid = int(cb.data.split(":")[2])
    cr = await db.get_crate(cid)
    if not cr or not cr["active"]:
        await cb.answer("Кейс недоступен.", show_alert=True)
        return
    cur_obj = await db.get_currency(cr["currency_id"]) if cr["currency_id"] else None
    cur_name = cur_obj["name"] if cur_obj else "💰 Монет"
    bal = await db.get_user_currency_bal(cb.from_user.id, cr["currency_id"])
    all_c = {str(x["id"]): x for x in await db.list_cards()}
    l_mult, _, _, _ = get_active_events()

    weighted = []
    for k, w in cr["cards"].items():
        co = all_c.get(str(k))
        if co and float(w) > 0:
            fw = float(w) * (l_mult if co["rarity"] in ("epic", "legendary", "mythic", "secret") else 1.0)
            weighted.append((co, fw))
    tot_w = sum(x[1] for x in weighted)
    weighted.sort(key=lambda x: x[1], reverse=True)

    lines = [
        f"📦 <b>{esc(cr['name'])}</b>",
        f"<i>{esc(cr['description'])}</i>" if cr["description"] else "",
        f"💵 Цена: <b>{cr['price']} {esc(cur_name)}</b> | Баланс: <b>{bal}</b>",
        "━━━━━━━━━━━━━━━━━━",
        "🎲 <b>Шансы:</b>",
    ]
    for co, fw in weighted[:12]:
        r_ico = RARITIES.get(co["rarity"], ("", "⚪️", 1, 1.0))[1]
        lines.append(f"• {r_ico} <b>{esc(co['name'])}</b> — {(fw / tot_w * 100):.2f}%")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Открыть x1 ({cr['price']})", callback_data=f"cr:op:{cid}:1"), InlineKeyboardButton(text=f"x5 ({cr['price'] * 5})", callback_data=f"cr:op:{cid}:5")],
        [InlineKeyboardButton(text=f"Открыть x10 ({cr['price'] * 10})", callback_data=f"cr:op:{cid}:10")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="lab:home")],
    ])
    await render_view(cb, "\n".join(x for x in lines if x), kb, photo=cr.get("photo_id") or None)
    await cb.answer()


@router.callback_query(F.data.startswith("cr:op:"))
async def cb_cr_open(cb: CallbackQuery):
    _, _, cid_s, amt_s = cb.data.split(":")
    cid, amt = int(cid_s), int(amt_s)
    cr = await db.get_crate(cid)
    if not cr or not cr["active"]:
        await cb.answer("Кейс недоступен.", show_alert=True)
        return
    uid = cb.from_user.id
    cost = cr["price"] * amt
    bal = await db.get_user_currency_bal(uid, cr["currency_id"])
    if bal < cost:
        await cb.answer(f"Недостаточно средств! Нужно {cost}.", show_alert=True)
        return
    all_c = {str(x["id"]): x for x in await db.list_cards()}
    l_mult, _, _, _ = get_active_events()
    pool, weights = [], []
    for k, w in cr["cards"].items():
        co = all_c.get(str(k))
        if co and float(w) > 0:
            pool.append(co)
            weights.append(float(w) * (l_mult if co["rarity"] in ("epic", "legendary", "mythic", "secret") else 1.0))
    if not pool:
        await cb.answer("Кейс пуст.", show_alert=True)
        return

    await db.add_user_currency(uid, cr["currency_id"], -cost)
    drops = random.choices(pool, weights=weights, k=amt)
    lines = [f"🎉 <b>ОТКРЫТО {amt}x «{esc(cr['name'])}»</b>", "━━━━━━━━━━━━━━━━━━"]
    counts: Dict[Tuple[str, str, int, int], int] = {}
    last_photo = None
    for c in drops:
        sh = roll_shiny()
        _, sn = await db.give_card(uid, c["id"], is_shiny=sh)
        r_ico = RARITIES.get(c["rarity"], ("", "⚪️", 1, 1.0))[1]
        key = (r_ico, c["name"], sh, sn)
        counts[key] = counts.get(key, 0) + 1
        if amt == 1:
            last_photo = c.get("photo_id") or None
    for (r_ico, name, sh, sn), q in counts.items():
        sh_s = "✨<b>SHINY</b> " if sh else ""
        sn_s = f" <b>[#{sn:04d}]</b>" if sn else ""
        q_s = f" x{q}" if q > 1 else ""
        lines.append(f"• {r_ico} {sh_s}<b>{esc(name)}</b>{sn_s}{q_s}")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"🔁 Ещё x{amt}", callback_data=f"cr:op:{cid}:{amt}"), InlineKeyboardButton(text="🔙 Назад", callback_data="lab:home")]])
    await render_view(cb, "\n".join(lines), kb, photo=last_photo)
    await cb.answer("🎉 Открыто!")


# ==============================================================================
# 8. МУЛЬТИПЛЕЕР: МИРОВОЙ БОСС И P2P-РЫНОК (80/20)
# ==============================================================================

def mp_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌍 Мировой Босс (Общий рейд)", callback_data="mp:wb")],
        [InlineKeyboardButton(text="🏪 P2P Рынок игроков (80/20)", callback_data="mp:mkt:0")],
    ])


@router.message(F.text == "🌐 Мультиплеер")
async def menu_mp(m: Message, state: FSMContext):
    await state.clear()
    wb = await db.get_world_boss()
    wb_s = f"🟢 {esc(wb['name'])} ({wb['current_hp']} HP)" if wb else "⚪️ Спит"
    await m.answer(
        f"🌐 <b>МУЛЬТИПЛЕЕР ХАБ</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"🌍 Мировой Босс: {wb_s}\n\n"
        f"• <b>🌍 Мировой Босс:</b> бейте Титана всем сервером — Топ-3 получают монеты и шанс заразить его.\n"
        f"• <b>🏪 P2P Рынок:</b> продажа редких ✨Shiny, 🦠Инфектед и серийных карт (80% продавцу, 20% комиссия).",
        reply_markup=mp_kb(),
    )


@router.callback_query(F.data == "mp:hub")
async def cb_mp_hub(cb: CallbackQuery):
    wb = await db.get_world_boss()
    wb_s = f"🟢 {esc(wb['name'])} ({wb['current_hp']} HP)" if wb else "⚪️ Спит"
    await render_view(cb, f"🌐 <b>МУЛЬТИПЛЕЕР ХАБ</b>\n🌍 Мировой Босс: {wb_s}", mp_kb())
    await cb.answer()


async def render_wb(target: Message | CallbackQuery):
    wb = await db.get_world_boss()
    if not wb:
        await render_view(target, "🌍 <b>МИРОВОЙ БОСС</b>\n\nСейчас Мировой Босс спит.", InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="mp:hub")]]))
        return
    top = await db.get_wb_top(wb["id"], 5)
    t_lines = [f"{i}. {fmt_user(x)} — <b>{int(x['damage'])}</b>" for i, x in enumerate(top, 1)]
    txt = (
        f"🌍 <b>МИРОВОЙ БОСС: {esc(wb['name'])}</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"{make_bar(wb['current_hp'], wb['max_hp'], 10, '🟥', '⬛')}\n"
        f"❤️ HP: <b>{wb['current_hp']} / {wb['max_hp']}</b>\n\n"
        f"🏆 <b>Топ-5 урона:</b>\n" + ("\n".join(t_lines) if t_lines else "<i>Ударь первым!</i>")
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚔️ Ударить колодой!", callback_data="mp:wb:hit")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="mp:wb"), InlineKeyboardButton(text="🔙 Назад", callback_data="mp:hub")],
    ])
    await render_view(target, txt, kb, photo=wb.get("photo_id") or None)


@router.callback_query(F.data == "mp:wb")
async def cb_wb(cb: CallbackQuery):
    await render_wb(cb)
    await cb.answer()


@router.callback_query(F.data == "mp:wb:hit")
async def cb_wb_hit(cb: CallbackQuery, bot: Bot):
    wb = await db.get_world_boss()
    if not wb:
        await cb.answer("Босс уже повержен!", show_alert=True)
        await render_wb(cb)
        return
    uid = cb.from_user.id
    prev = await db.get_wb_hit(wb["id"], uid)
    now = int(time.time())
    cd = cfg_int("wb_cooldown_sec")
    if prev and (now - prev["last_hit"]) < cd:
        await cb.answer(f"⏳ КД удара: {cd - (now - prev['last_hit'])} сек.", show_alert=True)
        return
    deck = await db.get_inventory(uid, only_equipped=True)
    if not deck:
        await cb.answer("Соберите колоду!", show_alert=True)
        return

    dmg = max(20.0, round(sum(calc_card_stats(c)["atk"] for c in deck) * random.uniform(1.1, 1.5), 1))
    rem = await db.hit_wb(wb["id"], uid, dmg)
    per_xp = round((dmg / len(deck)) * XP_PER_DAMAGE, 2)
    for c in deck:
        nl, nx, _ = apply_card_xp(c["level"], c["xp"], per_xp)
        await db.update_inv_xp(c["inv_id"], nl, nx)

    if rem <= 0:
        top = await db.get_wb_top(wb["id"], 10)
        l_mult, _, c_mult, _ = get_active_events()
        base_ch = RARITIES.get(wb["rarity"], ("", "", 1, 0.1))[3]
        wb_ch = calc_infect_chance(base_ch, 500, l_mult)
        for idx, p in enumerate(top, 1):
            coins = int(max(150, 950 - (idx - 1) * 140) * c_mult)
            await db.add_coins(p["user_id"], coins)
            extra = ""
            if idx <= 3 and (random.random() * 100.0) < wb_ch:
                sh = roll_shiny()
                _, sn = await db.give_card(p["user_id"], wb["card_id"], is_shiny=sh, is_infected=1)
                extra = f"\n🦠 <b>ВЫ ЗАРАЗИЛИ МИРОВОГО БОССА!</b>{' ✨SHINY' if sh else ''}{f' [#{sn:04d}]' if sn else ''}"
            try:
                await bot.send_message(p["user_id"], f"🌍🏆 <b>МИРОВОЙ БОСС {esc(wb['name'])} ПОВЕРЖЕН!</b>\nМесто #{idx} | 💰 +{coins}{extra}")
            except Exception:
                pass
        await cb.answer(f"💥 ФИНАЛЬНЫЙ УДАР -{int(dmg)}!", show_alert=True)
    else:
        await cb.answer(f"⚔️ Нанесено {int(dmg)} урона! Осталось {rem} HP.", show_alert=True)
    await render_wb(cb)


async def render_market(target: Message | CallbackQuery, uid: int, page: int = 0):
    lots = await db.list_market()
    per = 6
    tp = max(1, (len(lots) + per - 1) // per)
    page = max(0, min(page, tp - 1))
    rows = []
    for l in lots[page * per : (page + 1) * per]:
        r_ico = RARITIES.get(l["rarity"], ("", "⚪️", 1, 1.0))[1]
        sn = f" #{l['serial_number']:04d}" if l["serial_number"] else ""
        mine = " (Мой)" if l["seller_id"] == uid else ""
        rows.append([InlineKeyboardButton(text=f"{r_ico}{card_badges(l)} {l['name']}{sn} Ур.{l['level']} — {l['price']}💰{mine}", callback_data=f"mkt:v:{l['market_id']}:{page}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"mp:mkt:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{tp}", callback_data="noop"))
    if page < tp - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"mp:mkt:{page + 1}"))
    rows.extend([nav, [InlineKeyboardButton(text="🔙 Назад", callback_data="mp:hub")]])
    await render_view(target, f"🏪 <b>P2P РЫНОК</b> (80% продавцу / 20% комиссия)\nЛотов: <b>{len(lots)}</b>", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("mp:mkt:"))
async def cb_mp_mkt(cb: CallbackQuery):
    await render_market(cb, cb.from_user.id, int(cb.data.split(":")[2]))
    await cb.answer()


@router.callback_query(F.data.startswith("mkt:v:"))
async def cb_mkt_v(cb: CallbackQuery):
    _, _, lid_s, p_s = cb.data.split(":")
    lid, p = int(lid_s), int(p_s)
    lot = next((x for x in await db.list_market() if x["market_id"] == lid), None)
    if not lot:
        await cb.answer("Лот исчез.", show_alert=True)
        await render_market(cb, cb.from_user.id, p)
        return
    st = calc_card_stats(lot)
    txt = (
        f"🏷 <b>ЛОТ #{lid}</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"🃏 <b>{esc(lot['name'])}</b>{fmt_serial(lot)} {card_badges(lot)} (Ур.{lot['level']})\n"
        f"⚔️ ATK: <b>{st['atk']}</b> | ❤️ HP: <b>{st['hp']}</b> | Класс: <b>{lot['class_type']}</b>\n"
        f"✍️ Сигна: {get_sign_text(lot)}\n"
        f"👤 Продавец: <b>{esc(lot['seller_name'] or 'Игрок')}</b>\n💰 Цена: <b>{lot['price']}</b>"
    )
    act = (
        InlineKeyboardButton(text="❌ Снять с продажи", callback_data=f"mkt:c:{lid}:{p}")
        if lot["seller_id"] == cb.from_user.id
        else InlineKeyboardButton(text=f"✅ Купить ({lot['price']}💰)", callback_data=f"mkt:b:{lid}:{p}")
    )
    await render_view(cb, txt, InlineKeyboardMarkup(inline_keyboard=[[act], [InlineKeyboardButton(text="🔙 Назад", callback_data=f"mp:mkt:{p}")]]), photo=lot.get("photo_id") or None)
    await cb.answer()


@router.callback_query(F.data.startswith("mkt:b:"))
async def cb_mkt_b(cb: CallbackQuery, bot: Bot):
    _, _, lid_s, p_s = cb.data.split(":")
    ok, msg, lot = await db.buy_market_lot(int(lid_s), cb.from_user.id)
    await cb.answer(msg, show_alert=True)
    if ok and lot:
        try:
            await bot.send_message(lot["seller_id"], f"💰 <b>КАРТУ КУПИЛИ!</b> {esc(lot['name'])}\nЗачислено (80%): <b>+{lot['payout']} 💰</b>")
        except Exception:
            pass
    await render_market(cb, cb.from_user.id, int(p_s))


@router.callback_query(F.data.startswith("mkt:c:"))
async def cb_mkt_c(cb: CallbackQuery):
    _, _, lid_s, p_s = cb.data.split(":")
    await db.cancel_market_lot(int(lid_s), cb.from_user.id)
    await cb.answer("Снято!", show_alert=True)
    await render_market(cb, cb.from_user.id, int(p_s))


# ==============================================================================
# 9. РЕЙТИНГИ
# ==============================================================================

async def render_top(target: Message | CallbackQuery, mode: str = "trophies"):
    meta = {
        "trophies": ("🏆 Топ по Кубкам (Ранги)", "🏆"),
        "infections_success": ("🦠 Топ по Заражениям", "зараж."),
        "wins": ("⚔️ Топ по Победам", "побед"),
        "total_damage": ("💥 Топ по Урону", "урона"),
        "coins": ("💰 Топ Богачей", "💰"),
    }
    title, unit = meta.get(mode, meta["trophies"])
    med = ["🥇", "🥈", "🥉"]
    lines = [f"<b>{title}</b>", "━━━━━━━━━━━━━━━━━━"]
    for i, r in enumerate(await db.get_leaderboard(mode, 10), 1):
        m = med[i - 1] if i <= 3 else f"<b>{i}.</b>"
        extra = f" <i>({get_rank_info(int(r['val']))[1]})</i>" if mode == "trophies" else ""
        lines.append(f"{m} {fmt_user(r)} — <b>{int(r['val'])}</b> {unit}{extra}")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏆 Кубки", callback_data="top:trophies"), InlineKeyboardButton(text="🦠 Зараж.", callback_data="top:infections_success"), InlineKeyboardButton(text="⚔️ Победы", callback_data="top:wins")],
        [InlineKeyboardButton(text="💥 Урон", callback_data="top:total_damage"), InlineKeyboardButton(text="💰 Монеты", callback_data="top:coins")],
    ])
    await render_view(target, "\n".join(lines), kb)


@router.message(F.text == "🏆 Рейтинг")
async def menu_top(m: Message, state: FSMContext):
    await state.clear()
    await render_top(m, "trophies")


@router.callback_query(F.data.startswith("top:"))
async def cb_top(cb: CallbackQuery):
    await render_top(cb, cb.data.split(":")[1])
    await cb.answer()


# ==============================================================================
# 10. РАСШИРЕННАЯ АДМИН-ПАНЕЛЬ
# ==============================================================================

async def render_adm_home(target: Message | CallbackQuery, uid: int):
    p = await db.get_admin_perms(uid)
    st = await db.get_stats()
    maint = "🔴 ВКЛ" if GAME_SETTINGS.get("maintenance") == "1" else "🟢 ВЫКЛ"
    l_m, l_s, c_m, c_s = get_active_events()
    txt = (
        f"⚙️ <b>АДМИН-ПАНЕЛЬ SKIBIDI VERSE</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"👥 Игроков: <b>{st['users']}</b> | 🃏 Карт: <b>{st['cards']}</b> | 📦 Кейсов: <b>{st['crates']}</b>\n"
        f"🪙 Валют: <b>{st['currencies']}</b> | 🏪 Рынок: <b>{st['market']}</b> | 🛠 Техработы: <b>{maint}</b>\n"
        f"🎉 Ивенты: 🍀x{l_m} ({l_s // 60}м) | 💰x{c_m} ({c_s // 60}м)"
    )
    rows = []
    r1 = ([InlineKeyboardButton(text="🃏 Карты", callback_data="adm:cards:0")] if p.get("manage_cards") else []) + ([InlineKeyboardButton(text="📦 Крейты", callback_data="adm:crates")] if p.get("manage_crates") else [])
    if r1:
        rows.append(r1)
    r2 = ([InlineKeyboardButton(text="🪙 Валюты", callback_data="adm:curs")] if p.get("manage_currencies") else []) + ([InlineKeyboardButton(text="🎉 Ивенты", callback_data="adm:events")] if p.get("manage_events") else [])
    if r2:
        rows.append(r2)
    r3 = ([InlineKeyboardButton(text="🎛 Баланс", callback_data="adm:set:0")] if p.get("manage_settings") else []) + ([InlineKeyboardButton(text="🌍 Мировой Босс", callback_data="adm:wb")] if p.get("manage_bosses") else [])
    if r3:
        rows.append(r3)
    r4 = ([InlineKeyboardButton(text="👥 Игроки", callback_data="adm:users")] if (p.get("manage_users") or p.get("manage_economy")) else []) + ([InlineKeyboardButton(text="📢 Рассылка", callback_data="adm:bcast")] if p.get("broadcast") else [])
    if r4:
        rows.append(r4)
    if p.get("manage_admins"):
        rows.append([InlineKeyboardButton(text="👮 Админы", callback_data="adm:adms"), InlineKeyboardButton(text="🤝 Партнёры", callback_data="adm:sgns")])
        rows.append([InlineKeyboardButton(text=f"🛠 Техработы ({maint})", callback_data="adm:maint"), InlineKeyboardButton(text="💾 Бэкап БД", callback_data="adm:bkp")])
        rows.append([InlineKeyboardButton(text="📋 Логи", callback_data="adm:logs")])
    await render_view(target, txt, InlineKeyboardMarkup(inline_keyboard=rows))


@router.message(F.text == "⚙️ Админ-панель")
async def menu_adm(m: Message, state: FSMContext, is_admin: bool):
    if not is_admin:
        return
    await state.clear()
    await render_adm_home(m, m.from_user.id)


@router.callback_query(F.data == "adm:home")
async def cb_adm_home(cb: CallbackQuery, state: FSMContext):
    if not await db.is_admin(cb.from_user.id):
        return
    await state.clear()
    await render_adm_home(cb, cb.from_user.id)
    await cb.answer()


# --- КАРТЫ (СОЗДАНИЕ, РЕДАКТОР, УДАЛЕНИЕ) ---

async def render_adm_cards(target: Message | CallbackQuery, page: int = 0):
    cards = await db.list_cards()
    per = 7
    tp = max(1, (len(cards) + per - 1) // per)
    page = max(0, min(page, tp - 1))
    rows = [[InlineKeyboardButton(text="➕ Создать карту", callback_data="ac:new")]]
    for c in cards[page * per : (page + 1) * per]:
        r_ico = RARITIES.get(c["rarity"], ("", "⚪️", 1, 1.0))[1]
        ai = "🚫ИИ" if c["hide_from_ai"] else "🤖ИИ"
        rows.append([InlineKeyboardButton(text=f"{r_ico} #{c['id']} {c['name']} ({ai})", callback_data=f"ac:ed:{c['id']}:{page}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"adm:cards:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{tp}", callback_data="noop"))
    if page < tp - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"adm:cards:{page + 1}"))
    rows.extend([nav, [InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")]])
    await render_view(target, f"🃏 <b>КАРТЫ</b> ({len(cards)})", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("adm:cards:"))
async def cb_adm_cards(cb: CallbackQuery):
    if not await db.has_perm(cb.from_user.id, "manage_cards"):
        await cb.answer("Нет прав!", show_alert=True)
        return
    await render_adm_cards(cb, int(cb.data.split(":")[2]))
    await cb.answer()


@router.callback_query(F.data == "ac:new")
async def cb_ac_new(cb: CallbackQuery, state: FSMContext):
    await state.set_state(CardFSM.name)
    await cb.message.answer("🃏 Введите <b>название</b> новой карты:")
    await cb.answer()


@router.message(CardFSM.name)
async def fsm_ac_name(m: Message, state: FSMContext):
    await state.update_data(name=(m.text or "").strip())
    await state.set_state(CardFSM.faction)
    await m.answer("🏷 Выберите фракцию:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=v, callback_data=f"acf:{k}")] for k, v in FACTIONS.items()]))


@router.callback_query(CardFSM.faction, F.data.startswith("acf:"))
async def fsm_ac_fac(cb: CallbackQuery, state: FSMContext):
    fac = cb.data.split(":")[1]
    await state.update_data(faction=fac, hide_from_ai=1 if fac in ("skibidi", "astro") else 0)
    await state.set_state(CardFSM.rarity)
    await render_view(cb, "🌟 Выберите редкость:", InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{ico} {n} (🦠{fmt_pct(ch)}%)", callback_data=f"acr:{k}")] for k, (n, ico, _, ch) in RARITIES.items()]))
    await cb.answer()


@router.callback_query(CardFSM.rarity, F.data.startswith("acr:"))
async def fsm_ac_rar(cb: CallbackQuery, state: FSMContext):
    await state.update_data(rarity=cb.data.split(":")[1])
    await state.set_state(CardFSM.cls)
    await render_view(cb, "⚔️ Выберите боевой класс:", InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{ico} {k}", callback_data=f"acc:{k}")] for k, (ico, _) in CARD_CLASSES.items()]))
    await cb.answer()


@router.callback_query(CardFSM.cls, F.data.startswith("acc:"))
async def fsm_ac_cls(cb: CallbackQuery, state: FSMContext):
    cls = cb.data.split(":")[1]
    await state.update_data(class_type=cls)
    await state.set_state(CardFSM.stats)
    await cb.message.answer("❤️⚔️ Введите <b>HP</b> и <b>ATK</b> через пробел (например: <code>250 60</code>):")
    await cb.answer()


@router.message(CardFSM.stats)
async def fsm_ac_stats(m: Message, state: FSMContext):
    p = (m.text or "").split()
    try:
        hp, atk = int(p[0]), int(p[1])
    except (ValueError, IndexError):
        await m.answer("❌ Пример: <code>250 60</code>")
        return
    await state.update_data(hp=hp, atk=atk)
    d = await state.get_data()
    if d["class_type"] == "Booster":
        await state.set_state(CardFSM.boost)
        await m.answer("✨ Введите множители <b>ATK</b> и <b>HP</b> для Бустера (например: <code>1.25 1.15</code>):")
    else:
        await state.set_state(CardFSM.desc)
        await m.answer("📝 Введите описание (или <code>-</code>):")


@router.message(CardFSM.boost)
async def fsm_ac_boost(m: Message, state: FSMContext):
    p = (m.text or "").replace(",", ".").split()
    try:
        bd, bh = float(p[0]), float(p[1])
    except (ValueError, IndexError):
        await m.answer("❌ Пример: <code>1.25 1.15</code>")
        return
    await state.update_data(booster_dmg_mult=bd, booster_hp_mult=bh)
    await state.set_state(CardFSM.desc)
    await m.answer("📝 Введите описание (или <code>-</code>):")


@router.message(CardFSM.desc)
async def fsm_ac_desc(m: Message, state: FSMContext):
    t = (m.text or "").strip()
    await state.update_data(description="" if t == "-" else t)
    await state.set_state(CardFSM.photo)
    await m.answer("🖼 Отправьте фото карты (или <code>-</code>):")


@router.message(CardFSM.photo)
async def fsm_ac_photo(m: Message, state: FSMContext):
    pid = m.photo[-1].file_id if m.photo else ""
    await state.update_data(photo_id=pid)
    d = await state.get_data()
    cid = await db.create_card(d)
    await db.log_admin(m.from_user.id, f"Создал карту #{cid} {d['name']}")
    await state.clear()
    await m.answer(f"✅ Карта <b>{esc(d['name'])}</b> (#{cid}) создана!")
    await render_adm_card_ed(m, cid, 0)


async def render_adm_card_ed(target: Message | CallbackQuery, cid: int, page: int):
    c = await db.get_card(cid)
    if not c:
        await render_adm_cards(target, page)
        return
    txt = (
        f"🛠 <b>КАРТА #{c['id']} — {esc(c['name'])}</b>\n"
        f"Фракция: {FACTIONS.get(c['faction'])} | Редкость: <b>{c['rarity']}</b> | Класс: <b>{c['class_type']}</b>\n"
        f"❤️ HP: <b>{c['hp']}</b> | ⚔️ ATK: <b>{c['atk']}</b> | 🤖 Враг у ИИ: <b>{'Нет' if c['hide_from_ai'] else 'Да (можно заразить)'}</b>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Имя", callback_data=f"ac:f:{cid}:name:{page}"), InlineKeyboardButton(text="🖼 Фото", callback_data=f"ac:f:{cid}:photo_id:{page}")],
        [InlineKeyboardButton(text="❤️ HP", callback_data=f"ac:f:{cid}:hp:{page}"), InlineKeyboardButton(text="⚔️ ATK", callback_data=f"ac:f:{cid}:atk:{page}")],
        [InlineKeyboardButton(text="🌟 Редкость", callback_data=f"ac:f:{cid}:rarity:{page}"), InlineKeyboardButton(text="🎯 Класс", callback_data=f"ac:f:{cid}:class_type:{page}")],
        [InlineKeyboardButton(text=f"🤖 У ИИ: {'Скрыта' if c['hide_from_ai'] else 'Видна'}", callback_data=f"ac:ai:{cid}:{page}"), InlineKeyboardButton(text="🗑 Удалить", callback_data=f"ac:del:{cid}:{page}")],
        [InlineKeyboardButton(text="🔙 К картам", callback_data=f"adm:cards:{page}")],
    ])
    await render_view(target, txt, kb, photo=c.get("photo_id") or None)


@router.callback_query(F.data.startswith("ac:ed:"))
async def cb_ac_ed(cb: CallbackQuery):
    _, _, cid, p = cb.data.split(":")
    await render_adm_card_ed(cb, int(cid), int(p))
    await cb.answer()


@router.callback_query(F.data.startswith("ac:ai:"))
async def cb_ac_ai(cb: CallbackQuery):
    _, _, cid, p = cb.data.split(":")
    c = await db.get_card(int(cid))
    await db.update_card(int(cid), hide_from_ai=0 if c["hide_from_ai"] else 1)
    await render_adm_card_ed(cb, int(cid), int(p))
    await cb.answer("Переключено!")


@router.callback_query(F.data.startswith("ac:f:"))
async def cb_ac_f(cb: CallbackQuery, state: FSMContext):
    _, _, cid, f, p = cb.data.split(":")
    await state.set_state(CardFSM.edit_val)
    await state.update_data(cid=int(cid), field=f, page=int(p))
    await cb.message.answer(f"Введите новое значение для <b>{f}</b>:")
    await cb.answer()


@router.message(CardFSM.edit_val)
async def fsm_ac_f_save(m: Message, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    f = d["field"]
    try:
        if f == "photo_id":
            val: Any = m.photo[-1].file_id if m.photo else ""
        elif f in ("hp", "atk"):
            val = int((m.text or "").strip())
        elif f == "rarity":
            val = (m.text or "").strip().lower()
            if val not in RARITIES:
                raise ValueError
        elif f == "class_type":
            val = (m.text or "").strip()
            if val not in CARD_CLASSES:
                raise ValueError
        else:
            val = (m.text or "").strip()
    except ValueError:
        await m.answer("❌ Неверный формат.")
        return
    await db.update_card(d["cid"], **{f: val})
    await render_adm_card_ed(m, d["cid"], d["page"])


@router.callback_query(F.data.startswith("ac:del:"))
async def cb_ac_del(cb: CallbackQuery):
    _, _, cid, p = cb.data.split(":")
    await db.delete_card(int(cid))
    await cb.answer("🗑 Удалено!", show_alert=True)
    await render_adm_cards(cb, int(p))


# --- КАСТОМНЫЕ ВАЛЮТЫ ---

async def render_adm_curs(target: Message | CallbackQuery):
    curs = await db.list_currencies()
    rows = [[InlineKeyboardButton(text="➕ Создать валюту", callback_data="acu:new")]]
    for c in curs:
        dr = f"🎲{c['drop_chance']}% ({c['drop_min']}-{c['drop_max']})" if c["drop_in_battles"] else "🚫Без дропа"
        rows.append([InlineKeyboardButton(text=f"🪙 {c['name']} | {dr}", callback_data=f"acu:ed:{c['id']}")])
    rows.append([InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")])
    await render_view(target, "🪙 <b>КАСТОМНЫЕ ВАЛЮТЫ</b>\nМожно выдавать игрокам, продавать за них кейсы и включить дроп за победы!", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "adm:curs")
async def cb_adm_curs(cb: CallbackQuery):
    if not await db.has_perm(cb.from_user.id, "manage_currencies"):
        await cb.answer("Нет прав!", show_alert=True)
        return
    await render_adm_curs(cb)
    await cb.answer()


@router.callback_query(F.data == "acu:new")
async def cb_acu_new(cb: CallbackQuery, state: FSMContext):
    await state.set_state(CurFSM.name)
    await cb.message.answer("🪙 Введите название новой валюты (например <code>💎 Астро-Кристаллы</code>):")
    await cb.answer()


@router.message(CurFSM.name)
async def fsm_acu_name(m: Message, state: FSMContext):
    await state.clear()
    try:
        cid = await db.create_currency((m.text or "").strip())
        await db.log_admin(m.from_user.id, f"Создал валюту #{cid}")
        await render_adm_curs(m)
    except Exception:
        await m.answer("❌ Такая валюта уже существует.")


@router.callback_query(F.data.startswith("acu:ed:"))
async def cb_acu_ed(cb: CallbackQuery):
    cid = int(cb.data.split(":")[2])
    c = await db.get_currency(cid)
    if not c:
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🎲 Дроп в боях: {'ВКЛ' if c['drop_in_battles'] else 'ВЫКЛ'}", callback_data=f"acu:tgl:{cid}")],
        [InlineKeyboardButton(text=f"⚙️ Настроить дроп ({c['drop_chance']}% | {c['drop_min']}-{c['drop_max']})", callback_data=f"acu:cfg:{cid}")],
        [InlineKeyboardButton(text="🗑 Удалить валюту", callback_data=f"acu:del:{cid}")],
        [InlineKeyboardButton(text="🔙 К валютам", callback_data="adm:curs")],
    ])
    await render_view(cb, f"🪙 <b>Валюта: {esc(c['name'])}</b>", kb)
    await cb.answer()


@router.callback_query(F.data.startswith("acu:tgl:"))
async def cb_acu_tgl(cb: CallbackQuery):
    cid = int(cb.data.split(":")[2])
    c = await db.get_currency(cid)
    await db.update_currency(cid, drop_in_battles=0 if c["drop_in_battles"] else 1)
    cb.data = f"acu:ed:{cid}"
    await cb_acu_ed(cb)


@router.callback_query(F.data.startswith("acu:cfg:"))
async def cb_acu_cfg(cb: CallbackQuery, state: FSMContext):
    await state.set_state(CurFSM.drop_cfg)
    await state.update_data(cid=int(cb.data.split(":")[2]))
    await cb.message.answer("🎲 Введите через пробел: <code>шанс_% мин макс</code> (например: <code>15 1 5</code>):")
    await cb.answer()


@router.message(CurFSM.drop_cfg)
async def fsm_acu_cfg(m: Message, state: FSMContext):
    cid = (await state.get_data())["cid"]
    await state.clear()
    p = (m.text or "").replace(",", ".").split()
    try:
        ch, mn, mx = float(p[0]), int(p[1]), int(p[2])
    except (ValueError, IndexError):
        await m.answer("❌ Пример: <code>15 1 5</code>")
        return
    await db.update_currency(cid, drop_chance=ch, drop_min=mn, drop_max=mx, drop_in_battles=1)
    await render_adm_curs(m)


@router.callback_query(F.data.startswith("acu:del:"))
async def cb_acu_del(cb: CallbackQuery):
    await db.delete_currency(int(cb.data.split(":")[2]))
    await cb.answer("🗑 Удалено!", show_alert=True)
    await render_adm_curs(cb)


# --- КРЕЙТЫ (АДМИН) ---

async def render_adm_crates(target: Message | CallbackQuery):
    crates = await db.list_crates()
    rows = [[InlineKeyboardButton(text="➕ Создать Кейс", callback_data="ak:new")]]
    for c in crates:
        rows.append([InlineKeyboardButton(text=f"{'🟢' if c['active'] else '🔴'} {c['name']} ({c['price']})", callback_data=f"ak:ed:{c['id']}")])
    rows.append([InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")])
    await render_view(target, f"📦 <b>КРЕЙТЫ</b> ({len(crates)})", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "adm:crates")
async def cb_adm_crates(cb: CallbackQuery):
    if not await db.has_perm(cb.from_user.id, "manage_crates"):
        await cb.answer("Нет прав!", show_alert=True)
        return
    await render_adm_crates(cb)
    await cb.answer()


@router.callback_query(F.data == "ak:new")
async def cb_ak_new(cb: CallbackQuery, state: FSMContext):
    await state.set_state(CrateFSM.name)
    await state.update_data(cards={})
    await cb.message.answer("📦 Введите <b>название</b> кейса:")
    await cb.answer()


@router.message(CrateFSM.name)
async def fsm_ak_name(m: Message, state: FSMContext):
    await state.update_data(name=(m.text or "").strip())
    await state.set_state(CrateFSM.curr)
    rows = [[InlineKeyboardButton(text="💰 Монеты (Основная)", callback_data="akc:0")]]
    for c in await db.list_currencies():
        rows.append([InlineKeyboardButton(text=f"🪙 {c['name']}", callback_data=f"akc:{c['id']}")])
    await m.answer("🪙 Выберите валюту для покупки этого кейса:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(CrateFSM.curr, F.data.startswith("akc:"))
async def fsm_ak_curr(cb: CallbackQuery, state: FSMContext):
    await state.update_data(currency_id=int(cb.data.split(":")[1]))
    await state.set_state(CrateFSM.price)
    await cb.message.answer("💵 Введите <b>цену</b> и <b>описание</b> через `|` (например: <code>500 | Описание</code>):")
    await cb.answer()


@router.message(CrateFSM.price)
async def fsm_ak_price(m: Message, state: FSMContext):
    p = (m.text or "").split("|", 1)
    try:
        pr = int(p[0].strip())
    except ValueError:
        await m.answer("❌ Пример: <code>500 | Описание</code>")
        return
    await state.update_data(price=pr, desc=p[1].strip() if len(p) > 1 else "")
    await state.set_state(CrateFSM.photo)
    await m.answer("🖼 Отправьте фото кейса (или <code>-</code>):")


@router.message(CrateFSM.photo)
async def fsm_ak_photo(m: Message, state: FSMContext):
    await state.update_data(photo_id=m.photo[-1].file_id if m.photo else "")
    await _ak_builder(m, state)


async def _ak_builder(target: Message | CallbackQuery, state: FSMContext):
    d = await state.get_data()
    cmap = d.get("cards", {})
    all_c = await db.list_cards()
    by_id = {str(x["id"]): x for x in all_c}
    lines = [f"📦 <b>Состав «{esc(d['name'])}»</b>:"] + [f"• {esc(by_id[k]['name'])} — вес {w}" for k, w in cmap.items() if k in by_id]
    rows, row = [], []
    for c in all_c[:24]:
        row.append(InlineKeyboardButton(text=c["name"][:14], callback_data=f"akb:c:{c['id']}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if cmap:
        rows.append([InlineKeyboardButton(text="💾 Сохранить Кейс", callback_data="akb:save")])
    await state.set_state(CrateFSM.builder)
    await render_view(target, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(CrateFSM.builder, F.data.startswith("akb:c:"))
async def cb_akb_c(cb: CallbackQuery, state: FSMContext):
    await state.update_data(sel_c=cb.data.split(":")[2])
    await state.set_state(CrateFSM.weight)
    await cb.message.answer("⚖️ Введите вес выпадения (число):")
    await cb.answer()


@router.message(CrateFSM.weight)
async def fsm_akb_w(m: Message, state: FSMContext):
    try:
        w = int((m.text or "").strip())
    except ValueError:
        await m.answer("❌ Введите число.")
        return
    d = await state.get_data()
    cm = dict(d.get("cards", {}))
    cm[d["sel_c"]] = w
    await state.update_data(cards=cm)
    await _ak_builder(m, state)


@router.callback_query(CrateFSM.builder, F.data == "akb:save")
async def cb_akb_save(cb: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    await db.create_crate(d["name"], d["desc"], d["currency_id"], d["price"], d["cards"], d["photo_id"])
    await state.clear()
    await cb.answer("✅ Кейс создан!", show_alert=True)
    await render_adm_crates(cb)


@router.callback_query(F.data.startswith("ak:ed:"))
async def cb_ak_ed(cb: CallbackQuery):
    cid = int(cb.data.split(":")[2])
    c = await db.get_crate(cid)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Выкл" if c["active"] else "🟢 Вкл", callback_data=f"ak:tgl:{cid}"), InlineKeyboardButton(text="🗑 Удалить", callback_data=f"ak:del:{cid}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm:crates")],
    ])
    await render_view(cb, f"📦 <b>{esc(c['name'])}</b> (Цена: {c['price']})", kb)
    await cb.answer()


@router.callback_query(F.data.startswith("ak:tgl:"))
async def cb_ak_tgl(cb: CallbackQuery):
    cid = int(cb.data.split(":")[2])
    c = await db.get_crate(cid)
    await db.update_crate(cid, active=0 if c["active"] else 1)
    await render_adm_crates(cb)
    await cb.answer("Статус изменён!")


@router.callback_query(F.data.startswith("ak:del:"))
async def cb_ak_del(cb: CallbackQuery):
    await db.delete_crate(int(cb.data.split(":")[2]))
    await cb.answer("🗑 Удалено!", show_alert=True)
    await render_adm_crates(cb)


# --- ИВЕНТЫ (УДАЧА И МОНЕТЫ С РАССЫЛКОЙ) ---

@router.callback_query(F.data == "adm:events")
async def cb_adm_ev(cb: CallbackQuery):
    if not await db.has_perm(cb.from_user.id, "manage_events"):
        await cb.answer("Нет прав!", show_alert=True)
        return
    lm, ls, cm, cs = get_active_events()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍀 Запустить Ивент Удачи", callback_data="aev:luck"), InlineKeyboardButton(text="💰 Запустить Ивент Монет", callback_data="aev:coin")],
        [InlineKeyboardButton(text="🛑 Сбросить все ивенты", callback_data="aev:stop")],
        [InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")],
    ])
    await render_view(cb, f"🎉 <b>УПРАВЛЕНИЕ ИВЕНТАМИ</b>\n🍀 Удача: <b>x{lm}</b> ({ls // 60} мин.)\n💰 Монеты: <b>x{cm}</b> ({cs // 60} мин.)", kb)
    await cb.answer()


@router.callback_query(F.data.startswith("aev:"))
async def cb_aev(cb: CallbackQuery, state: FSMContext):
    act = cb.data.split(":")[1]
    if act == "stop":
        await db.set_setting("luck_event_end", "0")
        await db.set_setting("coin_event_end", "0")
        await cb.answer("🛑 Ивенты остановлены!", show_alert=True)
        await cb_adm_ev(cb)
        return
    await state.set_state(AdminFSM.ev_cfg)
    await state.update_data(ev_type=act)
    await cb.message.answer("🎉 Введите <b>множитель</b> и <b>минуты</b> через пробел (например: <code>2.0 60</code>):")
    await cb.answer()


@router.message(AdminFSM.ev_cfg)
async def fsm_aev_save(m: Message, state: FSMContext, bot: Bot):
    ev = (await state.get_data())["ev_type"]
    await state.clear()
    p = (m.text or "").replace(",", ".").split()
    try:
        mult, mins = float(p[0]), int(p[1])
    except (ValueError, IndexError):
        await m.answer("❌ Пример: <code>2.0 60</code>")
        return
    end = int(time.time()) + mins * 60
    if ev == "luck":
        await db.set_setting("luck_event_mult", str(mult))
        await db.set_setting("luck_event_end", str(end))
        note = f"🍀 <b>ГЛОБАЛЬНЫЙ ИВЕНТ УДАЧИ x{mult}</b> на <b>{mins} мин.</b>!\nУвеличены шансы заражения, ✨ Shiny и редких карт!"
    else:
        await db.set_setting("coin_event_mult", str(mult))
        await db.set_setting("coin_event_end", str(end))
        note = f"💰 <b>ГЛОБАЛЬНЫЙ ИВЕНТ МОНЕТ x{mult}</b> на <b>{mins} мин.</b>!\nВсе награды монет за бои увеличены!"
    await db.log_admin(m.from_user.id, f"Ивент {ev} x{mult} на {mins}м")
    await m.answer("✅ Ивент запущен! Рассылаем уведомление...")
    for uid in await db.get_active_uids():
        try:
            await bot.send_message(uid, note)
            await asyncio.sleep(0.03)
        except Exception:
            pass


# --- НАСТРОЙКИ БАЛАНСА ---

async def render_adm_set(target: Message | CallbackQuery, page: int = 0):
    keys = list(SETTING_META.keys())
    per = 7
    tp = max(1, (len(keys) + per - 1) // per)
    page = max(0, min(page, tp - 1))
    rows = [[InlineKeyboardButton(text=f"{SETTING_META[k][0]}: {GAME_SETTINGS.get(k)}", callback_data=f"as:{k}:{page}")] for k in keys[page * per : (page + 1) * per]]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"adm:set:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{tp}", callback_data="noop"))
    if page < tp - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"adm:set:{page + 1}"))
    rows.extend([nav, [InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")]])
    await render_view(target, "🎛 <b>НАСТРОЙКИ БАЛАНСА</b>", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("adm:set:"))
async def cb_adm_set(cb: CallbackQuery):
    if not await db.has_perm(cb.from_user.id, "manage_settings"):
        await cb.answer("Нет прав!", show_alert=True)
        return
    await render_adm_set(cb, int(cb.data.split(":")[2]))
    await cb.answer()


@router.callback_query(F.data.startswith("as:"))
async def cb_as(cb: CallbackQuery, state: FSMContext):
    _, k, p = cb.data.split(":")
    await state.set_state(AdminFSM.set_val)
    await state.update_data(k=k, p=int(p))
    t, vt, mn, mx = SETTING_META[k]
    await cb.message.answer(f"🎛 <b>{t}</b>\nТекущее: <code>{GAME_SETTINGS.get(k)}</code>\nНовое ({vt}, {mn}–{mx}):")
    await cb.answer()


@router.message(AdminFSM.set_val)
async def fsm_as(m: Message, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    k = d["k"]
    _, vt, mn, mx = SETTING_META[k]
    try:
        raw = (m.text or "").replace(",", ".").strip()
        v = int(raw) if vt == "int" else float(raw)
        if not (mn <= v <= mx):
            raise ValueError
    except ValueError:
        await m.answer(f"❌ От {mn} до {mx}.")
        return
    await db.set_setting(k, str(v))
    await render_adm_set(m, d["p"])


# --- МИРОВОЙ БОСС (АДМИН) ---

@router.callback_query(F.data == "adm:wb")
async def cb_adm_wb(cb: CallbackQuery):
    if not await db.has_perm(cb.from_user.id, "manage_bosses"):
        await cb.answer("Нет прав!", show_alert=True)
        return
    wb = await db.get_world_boss()
    bosses = [c for c in await db.list_cards() if c["rarity"] in ("legendary", "mythic", "secret")]
    rows = ([[InlineKeyboardButton(text="🛑 Остановить Босса", callback_data="awb:stop")]] if wb else []) + [
        [InlineKeyboardButton(text=f"🌍 {c['name']}", callback_data=f"awb:sp:{c['id']}")] for c in bosses[:10]
    ] + [[InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")]]
    await render_view(cb, f"🌍 <b>МИРОВОЙ БОСС</b>\n{('Активен: ' + esc(wb['name'])) if wb else 'Нет активного.'}", InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer()


@router.callback_query(F.data == "awb:stop")
async def cb_awb_stop(cb: CallbackQuery):
    await db.stop_world_boss()
    await cb.answer("🛑 Остановлен!", show_alert=True)
    await cb_adm_wb(cb)


@router.callback_query(F.data.startswith("awb:sp:"))
async def cb_awb_sp(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFSM.wb_hp)
    await state.update_data(cid=int(cb.data.split(":")[2]))
    await cb.message.answer("❤️ Введите HP Мирового Босса (например <code>25000</code>):")
    await cb.answer()


@router.message(AdminFSM.wb_hp)
async def fsm_awb_hp(m: Message, state: FSMContext, bot: Bot):
    cid = (await state.get_data())["cid"]
    await state.clear()
    try:
        hp = max(100, int((m.text or "").strip()))
    except ValueError:
        await m.answer("❌ Число.")
        return
    c = await db.get_card(cid)
    await db.spawn_world_boss(cid, hp)
    await m.answer(f"🌍 Запущен Мировой Босс <b>{esc(c['name'])}</b> ({hp} HP)!")
    for uid in await db.get_active_uids():
        try:
            await bot.send_message(uid, f"🚨🌍 <b>МИРОВОЙ БОСС: {esc(c['name'])} ({hp} HP)!</b>\nБей в «🌐 Мультиплеер → 🌍 Мировой Босс»!")
        except Exception:
            pass


# --- ИГРОКИ, ВЫДАЧА, РАССЫЛКА, АДМИНЫ, ПАРТНЁРЫ, ТЕХРАБОТЫ, БД ---

@router.callback_query(F.data == "adm:users")
async def cb_adm_u(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFSM.find_u)
    await cb.message.answer("👥 Введите <b>@username</b> или <b>ID</b> игрока:")
    await cb.answer()


@router.message(AdminFSM.find_u)
async def fsm_adm_u(m: Message, state: FSMContext):
    await state.clear()
    u = await db.find_user(m.text or "")
    if not u:
        await m.answer("❌ Игрок не найден.")
        return
    await render_adm_user(m, u["user_id"])


async def render_adm_user(target: Message | CallbackQuery, tid: int):
    u = await db.get_user(tid)
    txt = await build_profile_text(u, False) + f"\n🚫 Бан: <b>{'ДА' if u['is_banned'] else 'НЕТ'}</b>"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 +/- Монеты", callback_data=f"au:c:{tid}"), InlineKeyboardButton(text="🪙 Выдать валюту", callback_data=f"au:cur:{tid}")],
        [InlineKeyboardButton(text="🦠 +3 Обыч.", callback_data=f"au:p:common:{tid}"), InlineKeyboardButton(text="💎 +3 Элит.", callback_data=f"au:p:elite:{tid}")],
        [InlineKeyboardButton(text="🎁 Выдать карту", callback_data=f"au:gc:{tid}"), InlineKeyboardButton(text="✅ Разбан" if u["is_banned"] else "🚫 Бан", callback_data=f"au:ban:{tid}")],
        [InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")],
    ])
    await render_view(target, txt, kb)


@router.callback_query(F.data.startswith("au:c:"))
async def cb_au_c(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFSM.u_coins)
    await state.update_data(tid=int(cb.data.split(":")[2]))
    await cb.message.answer("💰 Введите сумму монет (+/-):")
    await cb.answer()


@router.message(AdminFSM.u_coins)
async def fsm_au_c(m: Message, state: FSMContext):
    tid = (await state.get_data())["tid"]
    await state.clear()
    try:
        await db.add_coins(tid, int((m.text or "").strip()))
    except ValueError:
        await m.answer("❌ Число.")
        return
    await render_adm_user(m, tid)


@router.callback_query(F.data.startswith("au:cur:"))
async def cb_au_cur(cb: CallbackQuery):
    tid = int(cb.data.split(":")[2])
    curs = await db.list_currencies()
    if not curs:
        await cb.answer("Нет кастомных валют.", show_alert=True)
        return
    rows = [[InlineKeyboardButton(text=c["name"], callback_data=f"au:cs:{tid}:{c['id']}")] for c in curs]
    await render_view(cb, "Выберите валюту:", InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer()


@router.callback_query(F.data.startswith("au:cs:"))
async def cb_au_cs(cb: CallbackQuery, state: FSMContext):
    _, _, tid, cid = cb.data.split(":")
    await state.set_state(CurFSM.give_amt)
    await state.update_data(tid=int(tid), cid=int(cid))
    await cb.message.answer("🪙 Введите количество валюты (+/-):")
    await cb.answer()


@router.message(CurFSM.give_amt)
async def fsm_au_cs(m: Message, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    try:
        await db.add_user_currency(d["tid"], d["cid"], int((m.text or "").strip()))
    except ValueError:
        await m.answer("❌ Число.")
        return
    await render_adm_user(m, d["tid"])


@router.callback_query(F.data.startswith("au:p:"))
async def cb_au_p(cb: CallbackQuery):
    _, _, pk, tid = cb.data.split(":")
    await db.add_parasite(int(tid), pk, 3)
    await cb.answer("✅ +3 паразита!", show_alert=True)
    await render_adm_user(cb, int(tid))


@router.callback_query(F.data.startswith("au:ban:"))
async def cb_au_ban(cb: CallbackQuery):
    tid = int(cb.data.split(":")[2])
    if tid == OWNER_ID:
        await cb.answer("Нельзя!", show_alert=True)
        return
    u = await db.get_user(tid)
    await db.update_user(tid, is_banned=0 if u["is_banned"] else 1)
    await render_adm_user(cb, tid)
    await cb.answer("Обновлено!")


@router.callback_query(F.data.startswith("au:gc:"))
async def cb_au_gc(cb: CallbackQuery):
    tid = int(cb.data.split(":")[2])
    rows = [[InlineKeyboardButton(text=f"#{c['id']} {c['name']}", callback_data=f"au:do:{tid}:{c['id']}")] for c in (await db.list_cards())[:20]]
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="adm:home")])
    await render_view(cb, f"🎁 Выберите карту для <code>{tid}</code>:", InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer()


@router.callback_query(F.data.startswith("au:do:"))
async def cb_au_do(cb: CallbackQuery):
    _, _, tid, cid = cb.data.split(":")
    _, sn = await db.give_card(int(tid), int(cid))
    await cb.answer(f"✅ Выдано!{f' [#{sn:04d}]' if sn else ''}", show_alert=True)
    await render_adm_user(cb, int(tid))


@router.callback_query(F.data == "adm:bcast")
async def cb_adm_bc(cb: CallbackQuery, state: FSMContext):
    if not await db.has_perm(cb.from_user.id, "broadcast"):
        await cb.answer("Нет прав!", show_alert=True)
        return
    await state.set_state(AdminFSM.bcast)
    await cb.message.answer("📢 Отправьте сообщение (текст или фото) для рассылки:")
    await cb.answer()


@router.message(AdminFSM.bcast)
async def fsm_adm_bc(m: Message, state: FSMContext):
    await state.clear()
    uids = await db.get_active_uids()
    ok = 0
    for uid in uids:
        try:
            await m.send_copy(chat_id=uid)
            ok += 1
            await asyncio.sleep(0.04)
        except Exception:
            pass
    await m.answer(f"✅ Рассылка завершена: <b>{ok}/{len(uids)}</b>")


async def render_adms(target: Message | CallbackQuery):
    rows = [[InlineKeyboardButton(text="➕ Добавить админа", callback_data="aa:add")]] + [
        [InlineKeyboardButton(text=f"👮 {a['full_name'] or a['user_id']} ({a['user_id']})", callback_data=f"aa:ed:{a['user_id']}")]
        for a in await db.list_admins()
    ] + [[InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")]]
    await render_view(target, f"👮 <b>АДМИНИСТРАТОРЫ</b> (Владелец: <code>{OWNER_ID}</code>)", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "adm:adms")
async def cb_adm_adms(cb: CallbackQuery):
    if not await db.has_perm(cb.from_user.id, "manage_admins"):
        await cb.answer("Нет прав!", show_alert=True)
        return
    await render_adms(cb)
    await cb.answer()


@router.callback_query(F.data == "aa:add")
async def cb_aa_add(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFSM.add_adm)
    await cb.message.answer("👮 Введите ID или @username нового админа:")
    await cb.answer()


@router.message(AdminFSM.add_adm)
async def fsm_aa_add(m: Message, state: FSMContext):
    await state.clear()
    u = await db.find_user(m.text or "")
    tid = u["user_id"] if u else (int(m.text.strip()) if (m.text or "").strip().isdigit() else 0)
    if not tid or tid == OWNER_ID:
        await m.answer("❌ Неверный ID.")
        return
    await db.add_admin(tid, m.from_user.id)
    await render_adm_perms(m, tid)


async def render_adm_perms(target: Message | CallbackQuery, tid: int):
    perms = await db.get_admin_perms(tid)
    rows = [[InlineKeyboardButton(text=f"{'✅' if perms.get(k) else '❌'} {v}", callback_data=f"aa:t:{tid}:{k}")] for k, v in ADMIN_PERMS.items()]
    rows.extend([[InlineKeyboardButton(text="🗑 Снять админа", callback_data=f"aa:d:{tid}")], [InlineKeyboardButton(text="🔙 К списку", callback_data="adm:adms")]])
    await render_view(target, f"👮 <b>Права админа <code>{tid}</code></b>", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("aa:ed:"))
async def cb_aa_ed(cb: CallbackQuery):
    await render_adm_perms(cb, int(cb.data.split(":")[2]))
    await cb.answer()


@router.callback_query(F.data.startswith("aa:t:"))
async def cb_aa_t(cb: CallbackQuery):
    _, _, tid, k = cb.data.split(":")
    await db.toggle_admin_perm(int(tid), k)
    await render_adm_perms(cb, int(tid))
    await cb.answer("Обновлено!")


@router.callback_query(F.data.startswith("aa:d:"))
async def cb_aa_d(cb: CallbackQuery):
    await db.remove_admin(int(cb.data.split(":")[2]))
    await cb.answer("🗑 Снят!", show_alert=True)
    await render_adms(cb)


@router.callback_query(F.data == "adm:sgns")
async def cb_adm_sgns(cb: CallbackQuery):
    if not await db.has_perm(cb.from_user.id, "manage_admins"):
        await cb.answer("Нет прав!", show_alert=True)
        return
    rows = [[InlineKeyboardButton(text="➕ Добавить Партнёра (+5% ATK/HP)", callback_data="asg:add")]] + [
        [InlineKeyboardButton(text=f"❌ {s['full_name'] or s['user_id']}", callback_data=f"asg:d:{s['user_id']}")] for s in await db.list_signers()
    ] + [[InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")]]
    await render_view(cb, "🤝 <b>ПАРТНЁРЫ-СИГНЕРЫ</b>", InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer()


@router.callback_query(F.data == "asg:add")
async def cb_asg_add(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFSM.add_sgn)
    await cb.message.answer("🤝 Введите ID или @username Партнёра:")
    await cb.answer()


@router.message(AdminFSM.add_sgn)
async def fsm_asg_add(m: Message, state: FSMContext):
    await state.clear()
    u = await db.find_user(m.text or "")
    tid = u["user_id"] if u else (int(m.text.strip()) if (m.text or "").strip().isdigit() else 0)
    if tid:
        await db.set_signer(tid, "partner", m.from_user.id)
        await m.answer(f"✅ Партнёр <code>{tid}</code> добавлен!")


@router.callback_query(F.data.startswith("asg:d:"))
async def cb_asg_d(cb: CallbackQuery):
    await db.remove_signer(int(cb.data.split(":")[2]))
    await cb.answer("Снят!", show_alert=True)
    await cb_adm_sgns(cb)


@router.callback_query(F.data == "adm:maint")
async def cb_adm_maint(cb: CallbackQuery):
    if not await db.has_perm(cb.from_user.id, "manage_admins"):
        return
    nxt = "0" if GAME_SETTINGS.get("maintenance") == "1" else "1"
    await db.set_setting("maintenance", nxt)
    await cb.answer("🛠 ВКЛ" if nxt == "1" else "🟢 ВЫКЛ", show_alert=True)
    await render_adm_home(cb, cb.from_user.id)


@router.callback_query(F.data == "adm:logs")
async def cb_adm_logs(cb: CallbackQuery):
    lines = ["📋 <b>ЛОГИ АДМИНОВ</b>", "━━━━━━━━━━━━━━━━━━"] + [
        f"• [{datetime.fromtimestamp(x['created_at']).strftime('%d.%m %H:%M')}] <b>{esc(x['full_name'] or x['admin_id'])}</b>: {esc(x['action'])}"
        for x in await db.get_admin_logs(15)
    ]
    await render_view(cb, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")]]))
    await cb.answer()


@router.callback_query(F.data == "adm:bkp")
async def cb_adm_bkp(cb: CallbackQuery):
    if not await db.has_perm(cb.from_user.id, "manage_admins"):
        return
    await cb.message.answer_document(FSInputFile(DB_PATH), caption="💾 Бэкап БД. Для восстановления отправьте этот .db файл обратно боту.")
    await cb.answer()


@router.message(F.document)
async def handle_db_restore(m: Message, bot: Bot):
    if m.from_user.id != OWNER_ID or not m.document or not (m.document.file_name or "").endswith(".db"):
        return
    f = await bot.get_file(m.document.file_id)
    await bot.download_file(f.file_path, DB_PATH)
    await db.reload_settings()
    await m.answer("✅ <b>База данных восстановлена!</b>")


@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery):
    await cb.answer()


# ==============================================================================
# 11. ФОНОВЫЙ БЭКАП И ЗАПУСК БОТА
# ==============================================================================

async def auto_backup_task(bot: Bot) -> None:
    while True:
        await asyncio.sleep(12 * 3600)
        try:
            await bot.send_document(OWNER_ID, FSInputFile(DB_PATH), caption="🕒 Автобэкап БД (12ч).")
        except Exception:
            pass


async def main() -> None:
    await db.init()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    mw = AccessMiddleware()
    dp.message.outer_middleware(mw)
    dp.callback_query.outer_middleware(mw)
    dp.include_router(router)

    asyncio.create_task(auto_backup_task(bot))
    me = await bot.get_me()
    logger.info("🚀 Бот @%s (ID: %s) запущен! Владелец: %s", me.username, me.id, OWNER_ID)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 Бот остановлен.")
