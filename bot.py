"""
Skibidi Verse: Cards & Infection — Telegram Card RPG Bot (Часть 1 из 3)
Стек: Python 3.10+, aiogram 3.x, aiosqlite (автоматическая установка при запуске).

Сборка файла:
Просто скопируй подряд Часть 1 + Часть 2 + Часть 3 в один файл bot.py.
"""

import asyncio
import html
import importlib
import importlib.util
import json
import logging
import os
import random
import re
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
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramConflictError,
    TelegramRetryAfter,
    TelegramUnauthorizedError,
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    TelegramObject,
)

# ==============================================================================
# 1. КОНФИГУРАЦИЯ, 31 РАНГ (АНГЛ.) И КОНСТАНТЫ
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

# Автовыбор постоянного тома /data (если есть на хостинге) или рядом со скриптом
_env_db = (os.getenv("DB_PATH") or "").strip()
if _env_db:
    DB_PATH = _env_db
elif os.path.isdir("/data") and os.access("/data", os.W_OK):
    DB_PATH = "/data/skibidi_cards.db"
else:
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skibidi_cards.db")

MAX_DECK_SIZE = 4
MAX_CARD_LEVEL = 50
XP_PER_DAMAGE = 0.1           # 1 урон = 0.1 XP карте
DMG_PCT_PER_LEVEL = 0.5       # +0.5% к урону за каждый уровень свыше 1
MARKET_COMMISSION_PCT = 20    # 20% комиссия владельцу, 80% продавцу
DAILY_COOLDOWN = 86400
MAX_CHILD_BOTS_PER_USER = 2
INITIAL_COINS = 100

DEFAULT_SETTINGS: Dict[str, str] = {
    "maintenance": "0",
    "allow_child_bots": "1",
    "starter_card_id": "0",
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
    "infected_mult": ("🦠 Множитель Infected", "float", 1.0, 5.0),
    "shiny_chance_pct": ("✨ Шанс Shiny (%)", "float", 0.0001, 100.0),
    "shiny_bonus_pct": ("✨ Бонус Shiny (%)", "float", 0.01, 500.0),
    "admin_sign_pct": ("👑 Админ-сигна (+% ATK/HP)", "float", 0.01, 200.0),
    "partner_sign_pct": ("🤝 Партнёр-сигна (+% ATK/HP)", "float", 0.01, 200.0),
    "p_common_price": ("🦠 Цена Обыч. паразита", "int", 10, 50000),
    "p_common_bonus": ("🦠 Бонус Обыч. паразита (%)", "float", 0.01, 500.0),
    "p_upgraded_price": ("☣️ Цена Улучш. паразита", "int", 10, 100000),
    "p_upgraded_bonus": ("☣️ Бонус Улучш. паразита (%)", "float", 0.01, 500.0),
    "p_elite_price": ("💎 Цена Элит. паразита", "int", 10, 200000),
    "p_elite_bonus": ("💎 Бонус Элит. паразита (%)", "float", 0.01, 500.0),
    "battle_delay_sec": ("⏱ Пауза хода в бою (сек)", "float", 0.5, 4.0),
    "wb_cooldown_sec": ("🌍 КД Мирового Босса (сек)", "int", 5, 600),
}

# Базовые редкости (сидятся в таблицу rarities, можно добавлять/редактировать/удалять)
DEFAULT_RARITIES: List[Tuple[str, str, str, int, float, int]] = [
    ("common", "Common", "⚪️", 1, 1.0, 0),
    ("uncommon", "Uncommon", "🟢", 2, 0.5, 0),
    ("rare", "Rare", "🔵", 3, 0.25, 0),
    ("epic", "Epic", "🟣", 4, 0.125, 0),
    ("legendary", "Legendary", "🟡", 5, 0.0625, 0),
    ("mythic", "Mythic", "🔴", 6, 0.03125, 1),
    ("secret", "Secret", "⬛", 7, 0.015625, 1),
]

RARITIES_CACHE: Dict[str, Dict[str, Any]] = {}

FACTIONS: Dict[str, str] = {
    "skibidi": "🚽 Skibidi",
    "astro": "🌌 Astro",
    "alliance": "📷 Alliance",
    "infected": "🦠 Infected",
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

# 31 ранг Скибиди-Туалетов (на англ.): (Rank, Trophies, AI Mult, Coins Mult, Infect Bonus %)
SKIBIDI_RANKS: List[Tuple[str, int, float, float, int]] = [
    ("🚽 Skibidi Rookie I", 0, 0.80, 1.00, 0),
    ("🚽 Skibidi Rookie II", 50, 0.85, 1.05, 2),
    ("🚽 Skibidi Rookie III", 100, 0.90, 1.10, 4),
    ("🚽 Skibidi Rookie IV", 150, 0.95, 1.15, 6),
    ("🪖 Skibidi Trooper I", 200, 1.00, 1.20, 10),
    ("🪖 Skibidi Trooper II", 300, 1.05, 1.25, 13),
    ("🪖 Skibidi Trooper III", 400, 1.10, 1.30, 16),
    ("🪖 Skibidi Trooper IV", 500, 1.15, 1.35, 20),
    ("🦾 Skibidi Mutant I", 650, 1.20, 1.40, 25),
    ("🦾 Skibidi Mutant II", 800, 1.30, 1.50, 30),
    ("🦾 Skibidi Mutant III", 950, 1.40, 1.60, 35),
    ("🦾 Skibidi Mutant IV", 1100, 1.50, 1.70, 40),
    ("🧪 Skibidi Scientist I", 1300, 1.80, 1.80, 45),
    ("🧪 Skibidi Scientist II", 1500, 2.50, 1.90, 50),
    ("🧪 Skibidi Scientist III", 1700, 3.20, 2.00, 55),
    ("🧪 Skibidi Scientist IV", 1900, 4.00, 2.10, 60),
    ("🕶 G-Squad I", 2200, 5.00, 2.50, 70),
    ("🕶 G-Squad II", 2500, 6.50, 2.80, 75),
    ("🕶 G-Squad III", 2800, 8.00, 3.20, 80),
    ("🕶 G-Squad IV", 3100, 10.00, 3.60, 90),
    ("👑 G-Toilet I", 3500, 13.00, 4.00, 100),
    ("👑 G-Toilet II", 4000, 15.00, 4.50, 110),
    ("👑 G-Toilet III", 4500, 17.00, 5.00, 120),
    ("👑 G-Toilet IV", 5000, 20.00, 5.50, 135),
    ("🌌 Astro Skibidi I", 5700, 24.00, 6.00, 150),
    ("🌌 Astro Skibidi II", 6500, 28.00, 6.50, 165),
    ("🌌 Astro Skibidi III", 7400, 32.00, 7.00, 180),
    ("🌌 Astro Skibidi IV", 8400, 36.00, 7.50, 200),
    ("🌌 Astro Skibidi V", 9500, 40.00, 8.00, 225),
    ("🌌 Astro Skibidi VI", 10000, 60.00, 9.00, 250),
    ("🌌 Astro Skibidi VII", 15000, 72.00, 10.00, 300),
]

DIFFICULTIES: Dict[str, Tuple[str, float, float, int, int]] = {
    "easy": ("🟢 Easy", 0.8, 0.6, -1, 0),
    "med": ("🟡 Medium", 1.1, 1.0, 0, 5),
    "hard": ("🔴 Hard", 1.6, 1.4, 1, 12),
    "nightmare": ("☠️ Nightmare", 2.2, 1.8, 2, 22),
    "crazy": ("🤯 Crazy", 3.5, 2.5, 3, 35),
}

BATTLE_MODS: Dict[str, Tuple[str, float, float, int]] = {
    "mod_enemy_hp": ("🔴 1.5x HP врагов (+30%💰/🏆, +8%🦠)", 0.30, 0.30, 8),
    "mod_enemy_stats": ("🔴 1.25x Статы ИИ (+25%💰/🏆, +6%🦠)", 0.25, 0.25, 6),
    "mod_enemy_regen": ("🔴 Реген врагов 5%/ход (+30%💰/🏆, +8%🦠)", 0.30, 0.30, 8),
    "mod_player_hp": ("🟢 1.3x HP вашей колоды (-30%💰)", -0.30, 0.0, 0),
    "mod_player_crit": ("🟢 +20% Крит игрока (-25%💰)", -0.25, 0.0, 0),
}

ADMIN_PERMS: Dict[str, str] = {
    "manage_cards": "🃏 Карты (создание/редактор/удаление/старт)",
    "manage_rarities": "🌟 Редкости (создание/редактор/удаление)",
    "manage_crates": "📦 Крейты (создание/редактор/шансы)",
    "manage_currencies": "🪙 Валюты и дроп из боёв",
    "manage_events": "🎉 Ивенты (Удача / Монеты)",
    "manage_settings": "🎛 Настройки баланса",
    "manage_bosses": "🌍 Мировой Босс",
    "manage_economy": "💰 Выдача ресурсов и карт",
    "manage_users": "👥 Игроки и баны",
    "broadcast": "📢 Рассылка",
    "sign_admin": "👑 Админ-сигна (+10% ATK/HP)",
    "manage_child_bots": "🤖 Управление дочерними ботами",
    "manage_admins": "👮 Админы, Партнёры, техработы, БД",
}

ACTIVE_BATTLES: Dict[str, Dict[str, Any]] = {}
USERS_IN_BATTLE: Set[int] = set()
MAIN_BOT: Optional[Bot] = None
MAIN_DP: Optional[Dispatcher] = None

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


def parse_float(raw: Optional[str]) -> float:
    """Парсит целые и дробные числа с точкой, запятой или знаком % (напр. '2.5%', '0,125%')."""
    s = (raw or "").strip().replace("%", "").replace("x", "").replace("х", "").replace(",", ".").strip()
    val = float(s)
    if val != val or val in (float("inf"), float("-inf")):
        raise ValueError("Invalid float")
    return val


def get_rarity(key: str) -> Dict[str, Any]:
    if key in RARITIES_CACHE:
        return RARITIES_CACHE[key]
    return {"key": key, "name": key.capitalize(), "emoji": "⚪️", "weight": 1, "infect_chance": 1.0, "has_serial": 0}


def sorted_rarities(reverse: bool = False) -> List[Dict[str, Any]]:
    return sorted(RARITIES_CACHE.values(), key=lambda r: (r["weight"], r["name"]), reverse=reverse)


def get_active_events() -> Tuple[float, int, float, int]:
    now = int(time.time())
    l_end = cfg_int("luck_event_end")
    c_end = cfg_int("coin_event_end")
    l_mult = cfg_float("luck_event_mult") if l_end > now else 1.0
    c_mult = cfg_float("coin_event_mult") if c_end > now else 1.0
    return l_mult, max(0, l_end - now), c_mult, max(0, c_end - now)


def get_rank_info(trophies: int) -> Tuple[int, str, float, float, int]:
    res = (0, SKIBIDI_RANKS[0][0], SKIBIDI_RANKS[0][2], SKIBIDI_RANKS[0][3], SKIBIDI_RANKS[0][4])
    for idx, (name, req, dm, rm, ib) in enumerate(SKIBIDI_RANKS):
        if trophies >= req:
            res = (idx, name, dm, rm, ib)
        else:
            break
    return res


def get_parasite_info(p_key: str) -> Tuple[str, str, int, float]:
    name, col = PARASITES[p_key]
    return name, col, cfg_int(f"p_{p_key}_price"), cfg_float(f"p_{p_key}_bonus")


def calc_infect_chance(base: float, bonus_pct: float, luck_mult: float = 1.0) -> float:
    """Формула: base * (1 + bonus_pct / 100) * luck_mult. Пример: 1% + 5% = 1.05%."""
    return min(95.0, round(float(base) * (1.0 + float(bonus_pct) / 100.0) * float(luck_mult), 6))


def fmt_pct(v: float) -> str:
    s = f"{float(v):.6f}".rstrip("0").rstrip(".")
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
# 2. БАЗА ДАННЫХ (AIOSQLITE) — АВТОМИГРАЦИЯ, ОНЛАЙН-БЭКАП И СТАРТОВЫЙ ЮНИТ
# ==============================================================================

class Database:
    def __init__(self, path: str):
        self.path = path

    async def init(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        async with aiosqlite.connect(self.path) as conn:
            await conn.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT DEFAULT '',
                    full_name TEXT DEFAULT 'Игрок',
                    coins INTEGER DEFAULT {INITIAL_COINS},
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

                CREATE TABLE IF NOT EXISTS rarities (
                    key TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    emoji TEXT DEFAULT '⚪️',
                    weight INTEGER DEFAULT 1,
                    infect_chance REAL DEFAULT 1.0,
                    has_serial INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS child_bots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id INTEGER NOT NULL,
                    token TEXT NOT NULL UNIQUE,
                    bot_id INTEGER DEFAULT 0,
                    username TEXT DEFAULT '',
                    title TEXT DEFAULT '',
                    is_active INTEGER DEFAULT 1,
                    is_banned INTEGER DEFAULT 0,
                    updates_count INTEGER DEFAULT 0,
                    last_error TEXT DEFAULT '',
                    created_at INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS admins (
                    user_id INTEGER PRIMARY KEY,
                    added_by INTEGER DEFAULT 0,
                    perms_json TEXT DEFAULT '{{}}',
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
                    cards_json TEXT DEFAULT '{{}}',
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
            await self._auto_migrate(conn)
            await conn.execute("INSERT OR IGNORE INTO user_discovered (user_id, card_id) SELECT DISTINCT user_id, card_id FROM inventory")
            for k, v in DEFAULT_SETTINGS.items():
                await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

            r_cnt = (await (await conn.execute("SELECT COUNT(*) FROM rarities")).fetchone())[0]
            if r_cnt == 0:
                for rk, rn, re_, rw, rich, rser in DEFAULT_RARITIES:
                    await conn.execute(
                        "INSERT OR IGNORE INTO rarities (key, name, emoji, weight, infect_chance, has_serial) VALUES (?, ?, ?, ?, ?, ?)",
                        (rk, rn, re_, rw, rich, rser),
                    )
            await conn.commit()

        await self.reload_settings()
        await self.reload_rarities()

    async def _auto_migrate(self, conn: aiosqlite.Connection) -> None:
        """Автоматически добавляет недостающие колонки при восстановлении старого бэкапа после обновы."""
        expected: Dict[str, List[Tuple[str, str]]] = {
            "users": [
                ("username", "TEXT DEFAULT ''"),
                ("full_name", "TEXT DEFAULT 'Игрок'"),
                ("coins", f"INTEGER DEFAULT {INITIAL_COINS}"),
                ("trophies", "INTEGER DEFAULT 0"),
                ("p_common", "INTEGER DEFAULT 2"),
                ("p_upgraded", "INTEGER DEFAULT 0"),
                ("p_elite", "INTEGER DEFAULT 0"),
                ("armed_parasite", "TEXT DEFAULT 'none'"),
                ("wins", "INTEGER DEFAULT 0"),
                ("losses", "INTEGER DEFAULT 0"),
                ("total_damage", "REAL DEFAULT 0"),
                ("infections_success", "INTEGER DEFAULT 0"),
                ("pity_bonus", "INTEGER DEFAULT 0"),
                ("daily_streak", "INTEGER DEFAULT 0"),
                ("last_daily", "INTEGER DEFAULT 0"),
                ("is_banned", "INTEGER DEFAULT 0"),
                ("created_at", "INTEGER DEFAULT 0"),
                ("mod_enemy_hp", "INTEGER DEFAULT 0"),
                ("mod_enemy_stats", "INTEGER DEFAULT 0"),
                ("mod_enemy_regen", "INTEGER DEFAULT 0"),
                ("mod_player_hp", "INTEGER DEFAULT 0"),
                ("mod_player_crit", "INTEGER DEFAULT 0"),
            ],
            "rarities": [
                ("name", "TEXT DEFAULT 'Common'"),
                ("emoji", "TEXT DEFAULT '⚪️'"),
                ("weight", "INTEGER DEFAULT 1"),
                ("infect_chance", "REAL DEFAULT 1.0"),
                ("has_serial", "INTEGER DEFAULT 0"),
            ],
            "child_bots": [
                ("bot_id", "INTEGER DEFAULT 0"),
                ("username", "TEXT DEFAULT ''"),
                ("title", "TEXT DEFAULT ''"),
                ("is_active", "INTEGER DEFAULT 1"),
                ("is_banned", "INTEGER DEFAULT 0"),
                ("updates_count", "INTEGER DEFAULT 0"),
                ("last_error", "TEXT DEFAULT ''"),
                ("created_at", "INTEGER DEFAULT 0"),
            ],
            "cards": [
                ("faction", "TEXT DEFAULT 'skibidi'"),
                ("rarity", "TEXT DEFAULT 'common'"),
                ("class_type", "TEXT DEFAULT 'Single'"),
                ("booster_dmg_mult", "REAL DEFAULT 1.15"),
                ("booster_hp_mult", "REAL DEFAULT 1.15"),
                ("hide_from_ai", "INTEGER DEFAULT 0"),
                ("description", "TEXT DEFAULT ''"),
                ("photo_id", "TEXT DEFAULT ''"),
            ],
            "inventory": [
                ("level", "INTEGER DEFAULT 1"),
                ("xp", "REAL DEFAULT 0"),
                ("is_shiny", "INTEGER DEFAULT 0"),
                ("is_infected", "INTEGER DEFAULT 0"),
                ("serial_number", "INTEGER DEFAULT 0"),
                ("sign_type", "TEXT DEFAULT 'none'"),
                ("signed_by", "TEXT DEFAULT ''"),
                ("equip_slot", "INTEGER DEFAULT 0"),
                ("acquired_at", "INTEGER DEFAULT 0"),
            ],
            "crates": [
                ("description", "TEXT DEFAULT ''"),
                ("currency_id", "INTEGER DEFAULT 0"),
                ("cards_json", "TEXT DEFAULT '{}'"),
                ("photo_id", "TEXT DEFAULT ''"),
                ("active", "INTEGER DEFAULT 1"),
            ],
            "currencies": [
                ("drop_in_battles", "INTEGER DEFAULT 0"),
                ("drop_chance", "REAL DEFAULT 10.0"),
                ("drop_min", "INTEGER DEFAULT 1"),
                ("drop_max", "INTEGER DEFAULT 5"),
            ],
        }
        for table, cols in expected.items():
            cur = await conn.execute(f"PRAGMA table_info({table})")
            existing = {r[1] for r in await cur.fetchall()}
            for col_name, col_def in cols:
                if col_name not in existing:
                    await conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")

    async def backup_to_file(self, dst_path: str) -> None:
        """Создаёт целый, небитый онлайн-снимок SQLite БД (безопасно во время работы бота)."""
        async with aiosqlite.connect(self.path) as src:
            async with aiosqlite.connect(dst_path) as dst:
                await src.backup(dst)

    async def reload_settings(self) -> None:
        async with aiosqlite.connect(self.path) as conn:
            for k, v in await (await conn.execute("SELECT key, value FROM settings")).fetchall():
                GAME_SETTINGS[k] = str(v)

    async def set_setting(self, key: str, value: str) -> None:
        GAME_SETTINGS[key] = str(value)
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
            await conn.commit()

    # -------------------- Редкости --------------------

    async def reload_rarities(self) -> None:
        RARITIES_CACHE.clear()
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            rows = await (await conn.execute("SELECT * FROM rarities ORDER BY weight ASC, name ASC")).fetchall()
            for r in rows:
                RARITIES_CACHE[r["key"]] = dict(r)

    async def create_rarity(self, key: str, name: str, emoji: str, weight: int, infect_chance: float, has_serial: int) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute(
                "INSERT INTO rarities (key, name, emoji, weight, infect_chance, has_serial) VALUES (?, ?, ?, ?, ?, ?)",
                (key, name, emoji, weight, infect_chance, has_serial),
            )
            await conn.commit()
        await self.reload_rarities()

    async def update_rarity(self, key: str, **kw: Any) -> None:
        if not kw:
            return
        cols = ", ".join(f"{k} = ?" for k in kw)
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute(f"UPDATE rarities SET {cols} WHERE key = ?", [*kw.values(), key])
            await conn.commit()
        await self.reload_rarities()

    async def delete_rarity(self, key: str) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("DELETE FROM rarities WHERE key = ?", (key,))
            await conn.commit()
        await self.reload_rarities()

    # -------------------- Дочерние боты --------------------

    async def list_child_bots(self, owner_id: Optional[int] = None) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            if owner_id is not None:
                rows = await (await conn.execute(
                    "SELECT cb.*, u.username AS owner_username, u.full_name AS owner_name FROM child_bots cb LEFT JOIN users u ON cb.owner_id = u.user_id WHERE cb.owner_id = ? ORDER BY cb.id ASC",
                    (owner_id,),
                )).fetchall()
            else:
                rows = await (await conn.execute(
                    "SELECT cb.*, u.username AS owner_username, u.full_name AS owner_name FROM child_bots cb LEFT JOIN users u ON cb.owner_id = u.user_id ORDER BY cb.id DESC"
                )).fetchall()
            return [dict(r) for r in rows]

    async def get_child_bot(self, cb_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            r = await (await conn.execute(
                "SELECT cb.*, u.username AS owner_username, u.full_name AS owner_name FROM child_bots cb LEFT JOIN users u ON cb.owner_id = u.user_id WHERE cb.id = ?",
                (cb_id,),
            )).fetchone()
            return dict(r) if r else None

    async def get_child_bot_by_token(self, token: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as conn:
            conn.row_factory = aiosqlite.Row
            r = await (await conn.execute("SELECT * FROM child_bots WHERE token = ?", (token,))).fetchone()
            return dict(r) if r else None

    async def create_child_bot(self, owner_id: int, token: str, bot_id: int, username: str, title: str) -> int:
        async with aiosqlite.connect(self.path) as conn:
            cur = await conn.execute(
                "INSERT INTO child_bots (owner_id, token, bot_id, username, title, is_active, is_banned, updates_count, last_error, created_at) VALUES (?, ?, ?, ?, ?, 1, 0, 0, '', ?)",
                (owner_id, token, bot_id, username, title, int(time.time())),
            )
            await conn.commit()
            return cur.lastrowid

    async def update_child_bot(self, cb_id: int, **kw: Any) -> None:
        if not kw:
            return
        cols = ", ".join(f"{k} = ?" for k in kw)
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute(f"UPDATE child_bots SET {cols} WHERE id = ?", [*kw.values(), cb_id])
            await conn.commit()

    async def inc_child_bot_updates(self, cb_id: int, delta: int = 1) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("UPDATE child_bots SET updates_count = updates_count + ? WHERE id = ?", (delta, cb_id))
            await conn.commit()

    async def delete_child_bot(self, cb_id: int) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("DELETE FROM child_bots WHERE id = ?", (cb_id,))
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
                await conn.execute(
                    "INSERT INTO users (user_id, username, full_name, coins, created_at) VALUES (?, ?, ?, ?, ?)",
                    (uid, uname, fname, INITIAL_COINS, now),
                )
                starter_id = cfg_int("starter_card_id")
                if starter_id > 0:
                    st_card = await (await conn.execute("SELECT id, rarity FROM cards WHERE id = ?", (starter_id,))).fetchone()
                    if st_card:
                        rar_info = get_rarity(st_card["rarity"])
                        serial = 0
                        if rar_info.get("has_serial"):
                            srow = await (await conn.execute(
                                "SELECT COALESCE(MAX(serial_number), 0) FROM inventory WHERE card_id = ? AND is_shiny = 0",
                                (starter_id,),
                            )).fetchone()
                            serial = (srow[0] or 0) + 1
                        await conn.execute(
                            "INSERT INTO inventory (user_id, card_id, level, xp, is_shiny, is_infected, serial_number, sign_type, signed_by, equip_slot, acquired_at) VALUES (?, ?, 1, 0, 0, 0, ?, 'none', '', 1, ?)",
                            (uid, starter_id, serial, now),
                        )
                        await conn.execute("INSERT OR IGNORE INTO user_discovered (user_id, card_id) VALUES (?, ?)", (uid, starter_id))
                await conn.commit()
                row = await (await conn.execute("SELECT * FROM users WHERE user_id = ?", (uid,))).fetchone()
            elif row["username"] != uname or row["full_name"] != fname:
                await conn.execute("UPDATE users SET username = ?, full_name = ? WHERE user_id = ?", (uname, fname, uid))
                await conn.commit()
            return dict(row), is_new

    async def get_users_without_cards(self) -> List[int]:
        async with aiosqlite.connect(self.path) as conn:
            rows = await (await conn.execute(
                "SELECT u.user_id FROM users u LEFT JOIN inventory i ON u.user_id = i.user_id WHERE i.id IS NULL"
            )).fetchall()
            return [r[0] for r in rows]

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
        card = await self.get_card(card_id)
        rar_info = get_rarity(card["rarity"]) if card else get_rarity("common")
        async with aiosqlite.connect(self.path) as conn:
            serial = 0
            if rar_info.get("has_serial"):
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

    async def create_crate(self, name: str, desc: str, currency_id: int, price: int, cards_map: Dict[str, float], photo_id: str = "") -> int:
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
                "rarities": (await (await conn.execute("SELECT COUNT(*) FROM rarities")).fetchone())[0],
                "crates": (await (await conn.execute("SELECT COUNT(*) FROM crates")).fetchone())[0],
                "currencies": (await (await conn.execute("SELECT COUNT(*) FROM currencies")).fetchone())[0],
                "market": (await (await conn.execute("SELECT COUNT(*) FROM market")).fetchone())[0],
                "child_bots": (await (await conn.execute("SELECT COUNT(*) FROM child_bots")).fetchone())[0],
            }


db = Database(DB_PATH)


# ==============================================================================
# 3. МЕНЕДЖЕР ДОЧЕРНИХ БОТОВ (ДИНАМИЧЕСКИЙ POLLING ЧЕРЕЗ feed_update)
# ==============================================================================

BOT_COMMANDS_LIST = [
    BotCommand(command="start", description="Главное меню / Показать кнопки"),
    BotCommand(command="linkbot", description="Привязать своего бота (макс. 2)"),
]


class ChildBotManager:
    """Управляет запуском, остановкой и мониторингом дочерних ботов в реальном времени."""

    def __init__(self) -> None:
        self.tasks: Dict[int, asyncio.Task] = {}
        self.bots: Dict[int, Bot] = {}

    def is_running(self, cb_id: int) -> bool:
        t = self.tasks.get(cb_id)
        return bool(t and not t.done())

    async def start_bot(self, cb_row: Dict[str, Any]) -> Tuple[bool, str]:
        cb_id = cb_row["id"]
        if self.is_running(cb_id):
            return True, "Бот уже запущен."
        if cb_row.get("is_banned"):
            return False, "Бот заблокирован администрацией."
        if not MAIN_DP:
            return False, "Диспетчер не инициализирован."

        bot = Bot(token=cb_row["token"], default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        try:
            me = await bot.get_me()
            await bot.set_my_commands(BOT_COMMANDS_LIST)
            await bot.delete_webhook(drop_pending_updates=True)
            await db.update_child_bot(cb_id, bot_id=me.id, username=me.username or "", title=me.full_name or "", is_active=1, last_error="")
        except Exception as exc:
            await bot.session.close()
            err = str(exc)[:180]
            await db.update_child_bot(cb_id, is_active=0, last_error=err)
            return False, f"Ошибка запуска: {err}"

        self.bots[cb_id] = bot
        self.tasks[cb_id] = asyncio.create_task(self._poll_loop(cb_id, bot, cb_row["owner_id"]))
        logger.info("🤖 Дочерний бот #%s (@%s) запущен!", cb_id, me.username)
        return True, f"Бот @{me.username} запущен!"

    async def stop_bot(self, cb_id: int, mark_db_inactive: bool = True) -> None:
        task = self.tasks.pop(cb_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        bot = self.bots.pop(cb_id, None)
        if bot:
            try:
                await bot.session.close()
            except Exception:
                pass
        if mark_db_inactive:
            await db.update_child_bot(cb_id, is_active=0)

    async def start_all_active(self) -> int:
        started = 0
        for row in await db.list_child_bots():
            if row["is_active"] and not row["is_banned"]:
                ok, _ = await self.start_bot(row)
                if ok:
                    started += 1
        return started

    async def stop_all(self, mark_db_inactive: bool = False) -> None:
        for cb_id in list(self.tasks.keys()):
            await self.stop_bot(cb_id, mark_db_inactive=mark_db_inactive)

    async def _safe_feed(self, bot: Bot, update: Any) -> None:
        try:
            if MAIN_DP:
                await MAIN_DP.feed_update(bot, update)
        except Exception as exc:
            logger.exception("Child bot update error: %s", exc)

    async def _poll_loop(self, cb_id: int, bot: Bot, owner_id: int) -> None:
        offset = 0
        allowed = MAIN_DP.resolve_used_update_types() if MAIN_DP else ["message", "callback_query"]
        try:
            while True:
                try:
                    updates = await bot.get_updates(offset=offset, timeout=25, allowed_updates=allowed)
                    if updates:
                        await db.inc_child_bot_updates(cb_id, len(updates))
                    for upd in updates:
                        offset = upd.update_id + 1
                        asyncio.create_task(self._safe_feed(bot, upd))
                except TelegramUnauthorizedError:
                    await db.update_child_bot(cb_id, is_active=0, last_error="Токен отозван или недействителен")
                    if MAIN_BOT:
                        try:
                            await MAIN_BOT.send_message(owner_id, f"⚠️ Ваш дочерний бот #{cb_id} остановлен: токен стал недействительным.")
                        except Exception:
                            pass
                    break
                except TelegramConflictError:
                    await db.update_child_bot(cb_id, last_error="Конфликт polling (бот запущен где-то ещё)")
                    await asyncio.sleep(5)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    await db.update_child_bot(cb_id, last_error=str(exc)[:180])
                    await asyncio.sleep(3)
        except asyncio.CancelledError:
            pass
        finally:
            self.tasks.pop(cb_id, None)
            self.bots.pop(cb_id, None)
            try:
                await bot.session.close()
            except Exception:
                pass


child_manager = ChildBotManager()
# ==============================================================================
# 4. СТАТЫ КАРТ, ПОДБОР ВРАГОВ ПО ТАБЛИЦЕ РАНГОВ, 4×4 БОЕВОЙ ДВИЖОК И UI-ХЕЛПЕРЫ
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


def fmt_rarity_badge(rarity_key: str) -> str:
    r = get_rarity(rarity_key)
    return f"{r['emoji']} <b>{esc(r['name'].upper())}</b> {r['emoji']}"


def get_sign_text(item: Dict[str, Any]) -> str:
    st = item.get("sign_type", "none")
    if st == "none":
        return "Нет"
    pct = cfg_float("admin_sign_pct") if st == "admin" else cfg_float("partner_sign_pct")
    role = "👑 Admin Sign" if st == "admin" else "🤝 Partner Sign"
    who = f" ({esc(item.get('signed_by'))})" if item.get("signed_by") else ""
    return f"{role} (+{fmt_pct(pct)}% ATK/HP){who}"


def calc_card_stats(item: Dict[str, Any]) -> Dict[str, Any]:
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
    r = get_rarity(item["rarity"])
    f_name = FACTIONS.get(item["faction"], item["faction"])
    cls = item["class_type"]
    c_ico, c_desc = CARD_CLASSES.get(cls, ("🎯", ""))
    st = calc_card_stats(item)
    lvl = int(item.get("level", 1))
    xp = float(item.get("xp", 0.0))
    need = xp_needed(lvl)

    xp_txt = (
        f"⭐ Lvl <b>{lvl}/{MAX_CARD_LEVEL}</b> (MAX | <b>+{st['lvl_pct']}%</b> ATK)"
        if lvl >= MAX_CARD_LEVEL
        else f"⭐ Lvl <b>{lvl}/{MAX_CARD_LEVEL}</b> (<b>+{st['lvl_pct']}%</b> ATK)\n   {make_bar(xp, need, 8)} {xp:.1f}/{need:.0f} XP"
    )
    status = (
        "🏷 На P2P-рынке"
        if item.get("market_id")
        else (f"✅ Слот #{item['equip_slot']}" if item.get("equip_slot", 0) > 0 else "📦 В инвентаре")
    )

    lines = [
        f"{r['emoji']} {c_ico} <b>{esc(item['name'])}</b>{fmt_serial(item)} {card_badges(item)}",
        f"Фракция: {f_name} | {fmt_rarity_badge(item['rarity'])}",
        f"Class: <b>{cls}</b> — <i>{c_desc}</i>",
        f"Статус: {status}",
        "━━━━━━━━━━━━━━━━━━",
        "📈 <b>УРОВЕНЬ (1 урон = 0.1 XP):</b>",
        xp_txt,
        "",
        "⚔️ <b>ХАРАКТЕРИСТИКИ:</b>",
    ]
    if cls == "Booster":
        lines.append(f"• ❤️ HP: <b>{st['hp']}</b> | ✨ Buff: ATK <b>x{st['b_dmg']}</b>, HP <b>x{st['b_hp']}</b>")
    elif cls == "Healer":
        lines.append(f"• 💗 Heal: <b>{st['atk']}</b> | ❤️ HP: <b>{st['hp']}</b>")
    else:
        lines.append(f"• ⚔️ ATK: <b>{st['atk']}</b> | ❤️ HP: <b>{st['hp']}</b> | ⚡ Power: <b>{st['power']}</b>")

    sh_t = f"✨ Shiny (+{fmt_pct(cfg_float('shiny_bonus_pct'))}%)" if item.get("is_shiny") else "Normal"
    inf_t = f"🦠 Infected (x{cfg_float('infected_mult')})" if item.get("is_infected") else "None"
    lines.extend([
        "",
        "✨ <b>МОДИФИКАТОРЫ:</b>",
        f"• Мутация: <b>{sh_t}</b> | Заражение: <b>{inf_t}</b>",
        f"• Сигна: {get_sign_text(item)}",
        f"• 🌍 Exist: <b>{ex_tot}</b> (✨ Shiny: <b>{ex_sh}</b> | 🦠 Infected: <b>{ex_inf}</b>)",
        f"• 🦠 Баз. шанс заразить: <b>{fmt_pct(r['infect_chance'])}%</b>",
    ])
    if item.get("description"):
        lines.append(f"\n📝 <i>{esc(item['description'])}</i>")
    return "\n".join(lines)


def _rank_base_tiers(rank_idx: int) -> Dict[int, float]:
    """
    Возвращает базовое распределение тиров редкостей (0=Common..6=Secret)
    для сложности Medium строго по таблице из 31 ранга:
      - Rookie I (0): Common
      - Rookie II-IV (1..3): Common, Uncommon
      - Trooper I (4): Uncommon
      - Trooper II-IV (5..7): Uncommon, Rare
      - Mutant I (8): Rare
      - Mutant II-IV (9..11): Rare, Epic
      - Scientist I (12): Epic
      - Scientist II-IV (13..15): Epic, Legendary
      - G-Squad I (16): Legendary
      - G-Squad II-IV (17..19): Legendary, Mythic
      - G-Toilet I-IV (20..23): Mythic
      - Astro Skibidi I-VII (24..30): Mythic, Secret
    """
    if rank_idx == 0:
        return {0: 100.0}
    if 1 <= rank_idx <= 3:
        return {0: 65.0, 1: 35.0}
    if rank_idx == 4:
        return {1: 100.0}
    if 5 <= rank_idx <= 7:
        return {1: 60.0, 2: 40.0}
    if rank_idx == 8:
        return {2: 100.0}
    if 9 <= rank_idx <= 11:
        return {2: 60.0, 3: 40.0}
    if rank_idx == 12:
        return {3: 100.0}
    if 13 <= rank_idx <= 15:
        return {3: 60.0, 4: 40.0}
    if rank_idx == 16:
        return {4: 100.0}
    if 17 <= rank_idx <= 19:
        return {4: 60.0, 5: 40.0}
    if 20 <= rank_idx <= 23:
        return {5: 100.0}
    # Astro Skibidi I–VII (24..30)
    sec_w = min(65.0, 25.0 + (rank_idx - 24) * 6.5)
    return {5: round(100.0 - sec_w, 1), 6: round(sec_w, 1)}


def _apply_difficulty_to_tiers(base_tiers: Dict[int, float], diff_key: str) -> Dict[int, float]:
    """
    Сдвигает базовые тиры таблицы рангов в зависимости от сложности:
      - Easy: на 1 тир ниже (на ранних рангах строго Common / Uncommon)
      - Medium: ровно по таблице рангов
      - Hard: на 1 тир выше
      - Nightmare: на 2 тира выше (минимум Epic — без Common/Uncommon/Rare мусора)
      - Crazy: на 2–3 тира выше (минимум Legendary — Legendary/Mythic/Secret)
    """
    shifted: Dict[int, float] = {}
    if diff_key == "easy":
        for t, w in base_tiers.items():
            nt = max(0, t - 1)
            shifted[nt] = shifted.get(nt, 0.0) + w
    elif diff_key == "med":
        shifted = dict(base_tiers)
    elif diff_key == "hard":
        for t, w in base_tiers.items():
            nt = min(6, t + 1)
            shifted[nt] = shifted.get(nt, 0.0) + w
    elif diff_key == "nightmare":
        for t, w in base_tiers.items():
            nt = min(6, max(3, t + 2))
            shifted[nt] = shifted.get(nt, 0.0) + w
        if len(shifted) == 1 and 3 in shifted:
            shifted = {3: 65.0, 4: 35.0}
    elif diff_key == "crazy":
        for t, w in base_tiers.items():
            nt = min(6, max(4, t + 2))
            nt2 = min(6, max(4, t + 3))
            shifted[nt] = shifted.get(nt, 0.0) + w * 0.6
            shifted[nt2] = shifted.get(nt2, 0.0) + w * 0.4
    else:
        shifted = dict(base_tiers)
    return shifted


def _enemy_team_size(rank_idx: int) -> int:
    """
    На Skibidi Rookie I–III у врага от 1 до 3 юнитов (плавный рост для новичков):
      - Skibidi Rookie I   (0): 1–2 юнита
      - Skibidi Rookie II  (1): 2 юнита
      - Skibidi Rookie III (2): 2–3 юнита
      - Skibidi Rookie IV+ (3+): 4 юнита
    """
    if rank_idx == 0:
        return random.randint(1, 2)
    if rank_idx == 1:
        return 2
    if rank_idx == 2:
        return random.randint(2, 3)
    return 4


async def generate_enemy_team(rank_idx: int, diff_key: str) -> List[Dict[str, Any]]:
    """
    Подбирает отряд врагов строго по таблице рангов, сложности и количеству юнитов.
    Если карт разрешённой редкости меньше нужного количества, дублируются карты
    ЭТОЙ ЖЕ редкости (исключает случайное появление Мификов в Easy и Анкамонок в Nightmare).
    """
    _, d_mult, _, _, _ = DIFFICULTIES[diff_key]
    r_diff_mult = SKIBIDI_RANKS[rank_idx][2]

    all_ai = await db.list_cards(ai_only=True)
    if not all_ai:
        all_ai = await db.list_cards()
    if not all_ai:
        return []

    by_rar: Dict[str, List[Dict[str, Any]]] = {}
    for c in all_ai:
        by_rar.setdefault(c["rarity"], []).append(c)

    rar_list = sorted_rarities(reverse=False)
    rar_keys = [r["key"] for r in rar_list] or ["common"]
    max_idx = len(rar_keys) - 1

    base_tiers = _rank_base_tiers(rank_idx)
    raw_dist = _apply_difficulty_to_tiers(base_tiers, diff_key)

    # Маппим стандартные 0..6 на фактическое число редкостей в БД (работает и с кастомными!)
    mapped_weights: Dict[int, float] = {}
    for std_tier, weight in raw_dist.items():
        idx = min(max_idx, max(0, int(round(std_tier * max_idx / 6.0)))) if max_idx > 0 else 0
        mapped_weights[idx] = mapped_weights.get(idx, 0.0) + float(weight)

    # Оставляем только разрешённые тиры, для которых реально есть карты в БД
    avail_allowed = {idx: w for idx, w in mapped_weights.items() if by_rar.get(rar_keys[idx])}

    # Если в разрешённых тирах нет ни одной карты — берём ближайший существующий тир
    if not avail_allowed:
        avg_target = sum(i * w for i, w in mapped_weights.items()) / max(1.0, sum(mapped_weights.values()))
        prefer_low = diff_key in ("easy", "med")
        existing_indices = [i for i, k in enumerate(rar_keys) if by_rar.get(k)]
        if existing_indices:
            best_idx = min(
                existing_indices,
                key=lambda i: (abs(i - avg_target), i if prefer_low else -i),
            )
            avail_allowed = {best_idx: 100.0}
        else:
            avail_allowed = {0: 100.0}

    allowed_indices = list(avail_allowed.keys())
    allowed_weights = [avail_allowed[i] for i in allowed_indices]

    stat_scale = max(0.65, (r_diff_mult ** 0.55) * d_mult)
    league = min(6, max(0, rank_idx // 4))
    enemy_shiny_ch = 0.0 if (diff_key == "easy" and league < 3) else min(0.10, 0.012 * d_mult)
    team_size = _enemy_team_size(rank_idx)

    team: List[Dict[str, Any]] = []
    used: Set[int] = set()

    for _ in range(team_size):
        pick_idx = random.choices(allowed_indices, weights=allowed_weights, k=1)[0]
        tier_cards = by_rar.get(rar_keys[pick_idx]) or all_ai

        fresh = [c for c in tier_cards if c["id"] not in used]
        chosen = dict(random.choice(fresh if fresh else tier_cards))
        used.add(chosen["id"])

        is_sh = 1 if (enemy_shiny_ch > 0 and random.random() < enemy_shiny_ch) else 0
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
    r_ico = get_rarity(u["rarity"])["emoji"]
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
    inf_tag = f" | 🦠 Infected: <b>{inf_cnt}</b>" if inf_cnt else ""
    return (
        f"{title} | <b>Раунд {rnd}</b>{inf_tag}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔵 <b>{esc(p_name)} (Skibidi):</b>\n{p_txt}\n\n"
        f"🔴 <b>{esc(e_name)} (Alliance — {len(t2)}):</b>\n{e_txt}\n"
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
    base_ch = float(get_rarity(enemy["rarity"])["infect_chance"])
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
    crit_tag = " 💥CRIT!" if is_crit else ""

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
    """
    Точное расположение кнопок 3×3:
    колода      играть        инвентарь
    профиль     крейты        индекс
    лидерборд   админ панель  мультиплеер
    """
    row3 = [KeyboardButton(text="🏆 Лидерборд")]
    if is_admin:
        row3.append(KeyboardButton(text="⚙️ Админ-панель"))
    row3.append(KeyboardButton(text="🌐 Мультиплеер"))

    rows = [
        [KeyboardButton(text="🛡 Колода"), KeyboardButton(text="⚔️ Играть"), KeyboardButton(text="🎒 Инвентарь")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="📦 Крейты"), KeyboardButton(text="📖 Индекс")],
        row3,
    ]
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=False,
        input_field_placeholder="Меню Skibidi Verse...",
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
# 5. FSM СОСТОЯНИЯ
# ==============================================================================

class PlayerFSM(StatesGroup):
    search = State()
    market_price = State()
    link_bot_token = State()


class RarityFSM(StatesGroup):
    create = State()
    edit_val = State()


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
    edit_field = State()
    edit_weight = State()


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
# 6. ОСНОВНОЙ РОУТЕР: /start, /linkbot, ПРОФИЛЬ, КОЛОДА, ИНВЕНТАРЬ, ИНДЕКС
# ==============================================================================

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, is_admin: bool):
    await state.clear()
    _, is_new = await db.ensure_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    gift = ""
    if is_new:
        st_id = cfg_int("starter_card_id")
        st_card = await db.get_card(st_id) if st_id > 0 else None
        st_txt = f" и стартовый юнит <b>{esc(st_card['name'])}</b> (уже в слоте #1)!" if st_card else "!"
        gift = f"\n\n🎁 <b>Стартовый набор:</b> {INITIAL_COINS} 💰, 2 🦠 паразита{st_txt}"
    kb_inline = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔽 Скрыть нижнее меню", callback_data="ui:hide_menu")]])
    await message.answer(
        f"🚽 <b>Skibidi Verse: Cards & Infection</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"• Играй за <b>Скибиди-Туалетов</b>, сражайся 4×4 против Альянса и поднимайся по <b>31 рангу</b>!\n"
        f"• При убийстве врага в бою есть шанс его <b>🦠 заразить</b> (чем выше ранг и паразит — тем выше шанс!).\n"
        f"• Качай карты в боях: <b>1 урон = 0.1 XP</b> (до 50 ур., +0.5% ATK за уровень).\n"
        f"• Привяжи своего дочернего бота через /linkbot (до {MAX_CHILD_BOTS_PER_USER} шт.).{gift}\n\n"
        f"👇 Используй меню снизу (можно свернуть кнопкой Telegram или скрыть кнопкой ниже).",
        reply_markup=main_reply_kb(is_admin),
    )
    await message.answer("⚙️ <i>Управление видимостью меню (вернуть меню — /start):</i>", reply_markup=kb_inline)


@router.callback_query(F.data == "ui:hide_menu")
async def cb_hide_menu(cb: CallbackQuery):
    await cb.message.answer("🔽 Нижнее меню скрыто. Чтобы вернуть его обратно — нажмите /start.", reply_markup=ReplyKeyboardRemove())
    await cb.answer("Меню скрыто!")


# -------------------- ДОЧЕРНИЕ БОТЫ (/linkbot ДЛЯ ИГРОКОВ) --------------------

async def render_user_linkbot(target: Message | CallbackQuery, uid: int):
    my_bots = await db.list_child_bots(owner_id=uid)
    allow = GAME_SETTINGS.get("allow_child_bots", "1") == "1"
    lines = [
        f"🤖 <b>МОИ ДОЧЕРНИЕ БОТЫ ({len(my_bots)}/{MAX_CHILD_BOTS_PER_USER})</b>",
        "━━━━━━━━━━━━━━━━━━",
        "Вы можете привязать до <b>2</b> собственных ботов из @BotFather — они будут работать на той же базе данных и с тем же прогрессом!\n",
    ]
    rows: List[List[InlineKeyboardButton]] = []
    if not my_bots:
        lines.append("<i>У вас пока нет привязанных ботов.</i>")
    else:
        for b in my_bots:
            if b["is_banned"]:
                st = "🚫 Заблокирован"
            elif child_manager.is_running(b["id"]):
                st = "🟢 Работает"
            else:
                st = "🔴 Остановлен"
            uname = f"@{esc(b['username'])}" if b["username"] else f"Bot #{b['id']}"
            err = f"\n   └ ⚠️ <i>{esc(b['last_error'])}</i>" if b.get("last_error") else ""
            lines.append(f"• {uname} — {st} | Запросов: <b>{b['updates_count']}</b>{err}")
            btn_row = []
            if not b["is_banned"]:
                if child_manager.is_running(b["id"]):
                    btn_row.append(InlineKeyboardButton(text=f"⏹ Стоп {b['username'] or b['id']}", callback_data=f"lb:stop:{b['id']}"))
                else:
                    btn_row.append(InlineKeyboardButton(text=f"▶️ Старт {b['username'] or b['id']}", callback_data=f"lb:start:{b['id']}"))
            btn_row.append(InlineKeyboardButton(text="🗑 Отвязать", callback_data=f"lb:del:{b['id']}"))
            rows.append(btn_row)

    if len(my_bots) < MAX_CHILD_BOTS_PER_USER and allow:
        rows.append([InlineKeyboardButton(text="➕ Привязать нового бота", callback_data="lb:add")])
    elif not allow:
        lines.append("\n🔒 <i>Привязка новых ботов временно отключена администрацией.</i>")

    await render_view(target, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows) if rows else None)


@router.message(Command("linkbot"))
async def cmd_linkbot(m: Message, state: FSMContext):
    await state.clear()
    await render_user_linkbot(m, m.from_user.id)


@router.callback_query(F.data == "lb:add")
async def cb_lb_add(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id
    if GAME_SETTINGS.get("allow_child_bots", "1") != "1":
        await cb.answer("Привязка новых ботов отключена!", show_alert=True)
        return
    if len(await db.list_child_bots(owner_id=uid)) >= MAX_CHILD_BOTS_PER_USER:
        await cb.answer(f"Максимум {MAX_CHILD_BOTS_PER_USER} бота!", show_alert=True)
        return
    await state.set_state(PlayerFSM.link_bot_token)
    await cb.message.answer(
        "🔑 Отправьте <b>API-токен</b> вашего бота от @BotFather.\n"
        "<i>Пример: <code>1234567890:AAF_...</code> (сообщение с токеном лучше удалить после привязки, бот сам сотрёт его, если сможет).</i>"
    )
    await cb.answer()


@router.message(PlayerFSM.link_bot_token)
async def fsm_lb_token(m: Message, state: FSMContext):
    token = (m.text or "").strip()
    uid = m.from_user.id
    await state.clear()
    try:
        await m.delete()
    except Exception:
        pass

    if len(await db.list_child_bots(owner_id=uid)) >= MAX_CHILD_BOTS_PER_USER:
        await m.answer(f"❌ Достигнут лимит: максимум {MAX_CHILD_BOTS_PER_USER} бота.")
        return
    if not re.match(r"^\d{5,}:[A-Za-z0-9_-]{20,}$", token):
        await m.answer("❌ Некорректный формат токена! Получите токен в @BotFather и попробуйте снова через /linkbot.")
        return
    if token == BOT_TOKEN or await db.get_child_bot_by_token(token):
        await m.answer("❌ Этот бот уже привязан в системе!")
        return

    wait_msg = await m.answer("⏳ Проверяю токен и запускаю дочернего бота...")
    test_bot = Bot(token=token)
    try:
        me = await test_bot.get_me()
    except Exception as exc:
        await wait_msg.edit_text(f"❌ Токен не прошёл проверку Telegram: <code>{esc(str(exc)[:150])}</code>")
        return
    finally:
        await test_bot.session.close()

    cb_id = await db.create_child_bot(uid, token, me.id, me.username or "", me.full_name or "")
    row = await db.get_child_bot(cb_id)
    ok, msg_txt = await child_manager.start_bot(row)
    if ok:
        await wait_msg.edit_text(f"✅ Дочерний бот <b>@{esc(me.username)}</b> успешно привязан и запущен! Напишите ему /start.")
        if MAIN_BOT and uid != OWNER_ID:
            try:
                await MAIN_BOT.send_message(OWNER_ID, f"🤖 Новый дочерний бот <b>@{esc(me.username)}</b> привязан игроком <code>{uid}</code>.")
            except Exception:
                pass
    else:
        await wait_msg.edit_text(f"⚠️ Бот сохранён, но не запустился: {esc(msg_txt)}")


@router.callback_query(F.data.startswith("lb:start:"))
async def cb_lb_start(cb: CallbackQuery):
    cb_id = int(cb.data.split(":")[2])
    row = await db.get_child_bot(cb_id)
    if not row or row["owner_id"] != cb.from_user.id:
        await cb.answer("Бот не найден.", show_alert=True)
        return
    ok, msg_txt = await child_manager.start_bot(row)
    await cb.answer(msg_txt, show_alert=not ok)
    await render_user_linkbot(cb, cb.from_user.id)


@router.callback_query(F.data.startswith("lb:stop:"))
async def cb_lb_stop(cb: CallbackQuery):
    cb_id = int(cb.data.split(":")[2])
    row = await db.get_child_bot(cb_id)
    if not row or row["owner_id"] != cb.from_user.id:
        await cb.answer("Бот не найден.", show_alert=True)
        return
    await child_manager.stop_bot(cb_id, mark_db_inactive=True)
    await cb.answer("⏹ Бот остановлен.")
    await render_user_linkbot(cb, cb.from_user.id)


@router.callback_query(F.data.startswith("lb:del:"))
async def cb_lb_del(cb: CallbackQuery):
    cb_id = int(cb.data.split(":")[2])
    row = await db.get_child_bot(cb_id)
    if not row or row["owner_id"] != cb.from_user.id:
        await cb.answer("Бот не найден.", show_alert=True)
        return
    await child_manager.stop_bot(cb_id, mark_db_inactive=False)
    await db.delete_child_bot(cb_id)
    await cb.answer("🗑 Бот отвязан!", show_alert=True)
    await render_user_linkbot(cb, cb.from_user.id)


# -------------------- ПРОФИЛЬ И МОДИФИКАТОРЫ --------------------

async def build_profile_text(u: Dict[str, Any], is_self: bool = True) -> str:
    inv = await db.get_inventory(u["user_id"])
    eq = [c for c in inv if c["equip_slot"] > 0]
    power = sum(calc_card_stats(c)["power"] for c in eq)
    _, r_name, _, r_rew, r_inf = get_rank_info(u["trophies"])
    shiny_c = sum(1 for c in inv if c["is_shiny"])
    inf_c = sum(1 for c in inv if c["is_infected"])
    s_role = await db.get_signer_role(u["user_id"])
    badge = " | 👑 Admin Signer" if s_role == "admin" else (" | 🤝 Partner Signer" if s_role == "partner" else "")

    extra_curs = await db.get_user_currencies(u["user_id"])
    cur_lines = "\n".join(f"   • {esc(c['name'])}: <b>{c['amount']}</b>" for c in extra_curs)
    cur_block = f"\n{cur_lines}" if cur_lines else ""

    l_mult, l_sec, c_mult, c_sec = get_active_events()
    ev_parts = []
    if l_mult > 1.0:
        ev_parts.append(f"🍀 Luck x{l_mult} ({l_sec // 60}м)")
    if c_mult > 1.0:
        ev_parts.append(f"💰 Coins x{c_mult} ({c_sec // 60}м)")
    ev_line = f"\n🎉 <b>Ивенты:</b> {' | '.join(ev_parts)}" if ev_parts else ""

    return (
        f"{'👤 <b>ВАШ ПРОФИЛЬ</b>' if is_self else '🔎 <b>ПРОФИЛЬ ИГРОКА</b>'}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🪪 {fmt_user(u)}{badge}\n"
        f"🎖 Rank: <b>{r_name}</b> (🏆 {u['trophies']})\n"
        f"   └ Награды: <b>x{r_rew}</b> | Заражение: <b>+{r_inf}%</b> от шанса\n\n"
        f"💰 Монеты: <b>{u['coins']}</b>{cur_block}\n"
        f"🦠 Паразиты: Обыч. <b>{u['p_common']}</b> | Улучш. <b>{u['p_upgraded']}</b> | Элит. <b>{u['p_elite']}</b>\n\n"
        f"🛡 Колода: <b>{len(eq)}/{MAX_DECK_SIZE}</b> (⚡ Power: <b>{power}</b>)\n"
        f"🃏 Карт: <b>{len(inv)}</b> (✨Shiny: {shiny_c} | 🦠Infected: {inf_c})\n"
        f"📊 Бои: <b>{u['wins']}W / {u['losses']}L</b> | 💥 Урон: <b>{int(u['total_damage'])}</b>\n"
        f"🦠 Заражений: <b>{u['infections_success']}</b> | 🎯 Пити: <b>+{u['pity_bonus']}%</b> | 🔥 Входы: <b>{u['daily_streak']} дн.</b>{ev_line}"
    )


def profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Ежедневка", callback_data="prof:daily"), InlineKeyboardButton(text="🧬 Моды боя", callback_data="prof:mods")],
            [InlineKeyboardButton(text="🔎 Найти игрока", callback_data="prof:search"), InlineKeyboardButton(text="🤖 Мои боты", callback_data="prof:bots")],
            [InlineKeyboardButton(text="🔽 Скрыть меню", callback_data="ui:hide_menu"), InlineKeyboardButton(text="🔄 Обновить", callback_data="prof:ref")],
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


@router.callback_query(F.data == "prof:bots")
async def cb_prof_bots(cb: CallbackQuery):
    await render_user_linkbot(cb, cb.from_user.id)
    await cb.answer()


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


# -------------------- КОЛОДА --------------------

async def render_deck(target: Message | CallbackQuery, uid: int):
    inv = await db.get_inventory(uid)
    smap = {c["equip_slot"]: c for c in inv if c["equip_slot"] > 0}
    pwr = sum(calc_card_stats(c)["power"] for c in smap.values())
    nums = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]
    lines = [f"🛡 <b>БОЕВАЯ КОЛОДА ({len(smap)}/{MAX_DECK_SIZE})</b> | ⚡ Power: <b>{pwr}</b>", "━━━━━━━━━━━━━━━━━━"]
    s_btns = []
    for s in range(1, MAX_DECK_SIZE + 1):
        c = smap.get(s)
        if c:
            st = calc_card_stats(c)
            r_ico = get_rarity(c["rarity"])["emoji"]
            c_ico = CARD_CLASSES.get(c["class_type"], ("🎯", ""))[0]
            stat = (
                f"✨x{st['b_dmg']}/x{st['b_hp']}"
                if c["class_type"] == "Booster"
                else (f"💗{st['atk']} ❤️{st['hp']}" if c["class_type"] == "Healer" else f"⚔️{st['atk']} ❤️{st['hp']}")
            )
            lines.append(f"{nums[s - 1]} {r_ico}{c_ico} <b>{esc(c['name'])}</b>{fmt_serial(c)}{card_badges(c)} Lvl.{c['level']} [{stat}]")
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
    avail.sort(key=lambda x: (get_rarity(x["rarity"])["weight"], x["is_shiny"], x["is_infected"], calc_card_stats(x)["power"]), reverse=True)
    per = 6
    tp = max(1, (len(avail) + per - 1) // per)
    page = max(0, min(page, tp - 1))

    txt = f"🎯 <b>СЛОТ #{slot}</b>\nТекущая карта: {('<b>' + esc(cur['name']) + '</b> ' + card_badges(cur)) if cur else '<i>Пусто</i>'}"
    rows = []
    if cur:
        rows.append([InlineKeyboardButton(text="ℹ️ Инфо", callback_data=f"c:v:{cur['inv_id']}:deck:0"), InlineKeyboardButton(text="➖ Освободить", callback_data=f"eq:un:{cur['inv_id']}")])
    for c in avail[page * per : (page + 1) * per]:
        r_ico = get_rarity(c["rarity"])["emoji"]
        sn = f" #{c['serial_number']:04d}" if c["serial_number"] else ""
        rows.append([InlineKeyboardButton(text=f"{r_ico}{card_badges(c)} {c['name']}{sn} (Lvl.{c['level']})", callback_data=f"eq:put:{slot}:{c['inv_id']}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"eq:slot:{slot}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{tp}", callback_data="noop"))
    if page < tp - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"eq:slot:{slot}:{page + 1}"))
    rows.extend([nav, [InlineKeyboardButton(text="🔙 К колоде", callback_data="eq:home")]])
    await render_view(target, txt, InlineKeyboardMarkup(inline_keyboard=rows))


# -------------------- ИНВЕНТАРЬ (GGTD STYLE) --------------------

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

    stacks.sort(
        key=lambda x: (
            1 if x[0]["sign_type"] != "none" else 0,
            get_rarity(x[0]["rarity"])["weight"],
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
    flt_names = {"all": "Все", "sh": "✨ Shiny", "inf": "🦠 Infected", "eq": "✅ В колоде"}

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
            r_ico = get_rarity(c["rarity"])["emoji"]
            c_ico = CARD_CLASSES.get(c["class_type"], ("🎯", ""))[0]
            tag = f"✅#{c['equip_slot']} " if c["equip_slot"] > 0 else ("🏷 " if c.get("market_id") else "")
            b = card_badges(c)
            sn = fmt_serial(c)
            sgn_str = f" <i>(✍️ {esc(c['signed_by'])})</i>" if c["sign_type"] != "none" and c.get("signed_by") else ""
            lines.append(f"{idx}. {tag}{r_ico}{c_ico} <b>{esc(c['name'])}</b>{sn}{b}{sgn_str} [Lvl.{c['level']}] — <b>{qty} шт.</b>")

    lines.append("\n👇 <i>Выберите карту ниже, чтобы открыть Инфо, надеть или продать:</i>")

    rows: List[List[InlineKeyboardButton]] = [[
        InlineKeyboardButton(text="• Все •" if flt == "all" else "Все", callback_data="inv:all:0"),
        InlineKeyboardButton(text="• ✨ •" if flt == "sh" else "✨ Shiny", callback_data="inv:sh:0"),
        InlineKeyboardButton(text="• 🦠 •" if flt == "inf" else "🦠 Inf", callback_data="inv:inf:0"),
        InlineKeyboardButton(text="• ✅ •" if flt == "eq" else "✅ Колода", callback_data="inv:eq:0"),
    ]]

    btn_row: List[InlineKeyboardButton] = []
    for idx, (c, _) in enumerate(chunk, page * per + 1):
        r_ico = get_rarity(c["rarity"])["emoji"]
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
        InlineKeyboardButton(text="🛡 Колода", callback_data="eq:home"),
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
            pct = cfg_float("admin_sign_pct") if role == "admin" else cfg_float("partner_sign_pct")
            act.append(InlineKeyboardButton(text=f"{'👑' if role == 'admin' else '🤝'} Подписать (+{fmt_pct(pct)}%)", callback_data=f"c:sgn:{inv_id}:{flt}:{page}"))
        act.append(InlineKeyboardButton(text="🏷 На Рынок", callback_data=f"c:sell:{inv_id}"))
        rows.append(act)
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="eq:home" if flt == "deck" else f"inv:{flt}:{page}")])
    await render_view(target, txt, InlineKeyboardMarkup(inline_keyboard=rows), photo=item.get("photo_id") or None)


# -------------------- ИНДЕКС КАРТ (ДО 8 ЮНИТОВ НА СТРАНИЦУ, EXIST НА АНГЛ) --------------------

async def render_index(target: Message | CallbackQuery, uid: int, page: int = 0):
    all_cards = await db.list_cards()
    if not all_cards:
        await render_view(
            target,
            "📖 <b>INDEX КАРТ</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n<i>В базе пока нет ни одного юнита. Админ может создать их в Админ-панели!</i>",
            InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🛡 Колода", callback_data="eq:home")]]),
        )
        return

    discovered = await db.get_discovered_ids(uid)
    u = await db.get_user(uid)
    _, _, _, _, r_inf = get_rank_info(u["trophies"])
    l_mult, _, _, _ = get_active_events()

    crates = await db.list_crates(active_only=True)
    crate_sources: Dict[int, List[str]] = {}
    for cr in crates:
        w_map = cr["cards"]
        tot_w = sum(float(v) for v in w_map.values() if float(v) > 0)
        if tot_w <= 0:
            continue
        for cid_s, w_val in w_map.items():
            if float(w_val) > 0:
                pct = (float(w_val) / tot_w) * 100.0
                crate_sources.setdefault(int(cid_s), []).append(f"{cr['name']} ({fmt_pct(pct)}%)")

    all_cards.sort(key=lambda c: (get_rarity(c["rarity"])["weight"], c["id"]), reverse=True)

    per = 8
    tp = max(1, (len(all_cards) + per - 1) // per)
    page = max(0, min(page, tp - 1))
    chunk = all_cards[page * per : (page + 1) * per]

    lines = [
        f"📖 <b>INDEX КАРТ (Стр. {page + 1}/{tp})</b>",
        f"🧩 Открыто: <b>{len(discovered)}/{len(all_cards)}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    if l_mult > 1.0:
        lines.append(f"🍀 <b>LUCK EVENT x{l_mult}!</b> Шансы пересчитаны!\n")

    for idx, c in enumerate(chunk, page * per + 1):
        ex_t, ex_s, ex_i = await db.get_card_exist_stats(c["id"])
        r = get_rarity(c["rarity"])
        c_ico = CARD_CLASSES.get(c["class_type"], ("🎯", ""))[0]
        eff_inf = calc_infect_chance(float(r["infect_chance"]), r_inf, l_mult)

        mut_parts = []
        if ex_s > 0:
            mut_parts.append(f"✨ Shiny: {ex_s}")
        if ex_i > 0:
            mut_parts.append(f"🦠 Infected: {ex_i}")
        mut_str = f" ({', '.join(mut_parts)})" if mut_parts else ""

        src_parts = []
        if not c["hide_from_ai"]:
            src_parts.append(f"🦠 Infect: {fmt_pct(eff_inf)}%")
        if c["id"] in crate_sources:
            src_parts.append("📦 " + ", ".join(crate_sources[c["id"]][:2]))
        src_str = " | ".join(src_parts) if src_parts else "Exclusive"

        if c["id"] in discovered:
            if c["class_type"] == "Booster":
                stat_l = f"✨ Buff: ATK x{c['booster_dmg_mult']} / HP x{c['booster_hp_mult']}"
            elif c["class_type"] == "Healer":
                stat_l = f"💗 Heal: {c['atk']} | ❤️ HP: {c['hp']}"
            else:
                stat_l = f"⚔️ ATK: {c['atk']} | ❤️ HP: {c['hp']}"
            lines.append(
                f"{idx}. {r['emoji']}{c_ico} <b>{esc(c['name'])}</b> [{c['class_type']}]\n"
                f"   └ {fmt_rarity_badge(c['rarity'])} | {src_str}\n"
                f"   └ {stat_l}\n"
                f"   └ 🌍 Exist: <b>{ex_t}</b>{mut_str}"
            )
        else:
            lines.append(
                f"{idx}. <b>???</b> (Locked)\n"
                f"   └ {fmt_rarity_badge(c['rarity'])} | {src_str}\n"
                f"   └ 🌍 Exist: <b>{ex_t}</b>{mut_str}"
            )

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"idx:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{tp}", callback_data="noop"))
    if page < tp - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"idx:{page + 1}"))
    kb = InlineKeyboardMarkup(inline_keyboard=[nav, [InlineKeyboardButton(text="🎒 Инвентарь", callback_data="inv:all:0"), InlineKeyboardButton(text="🛡 Колода", callback_data="eq:home")]])
    await render_view(target, "\n".join(lines), kb)


@router.message(F.text == "🛡 Колода")
async def menu_deck(m: Message, state: FSMContext):
    await state.clear()
    await render_deck(m, m.from_user.id)


@router.message(F.text == "🎒 Инвентарь")
async def menu_inventory(m: Message, state: FSMContext):
    await state.clear()
    await render_inventory(m, m.from_user.id, "all", 0)


@router.message(F.text == "📖 Индекс")
async def menu_index(m: Message, state: FSMContext):
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
    pct = cfg_float("admin_sign_pct") if role == "admin" else cfg_float("partner_sign_pct")
    await cb.answer(f"✍️ Signed (+{fmt_pct(pct)}% ATK/HP)!", show_alert=True)
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
# 7. БОИ 4×4 ПРОТИВ АЛЬЯНСА (БЕЗ ПРОПУСКА, 31 РАНГ, ЗАРАЖЕНИЕ ПРИ УБИЙСТВЕ)
# ==============================================================================

async def render_battle_hub(target: Message | CallbackQuery, uid: int):
    u = await db.get_user(uid)
    rank_idx, r_name, _, r_rew, r_inf = get_rank_info(u["trophies"])
    armed = u["armed_parasite"]
    if armed in PARASITES and u[PARASITES[armed][1]] <= 0:
        armed = "none"
        await db.update_user(uid, armed_parasite="none")
    p_bonus = cfg_float(f"p_{armed}_bonus") if armed in PARASITES else 0.0
    p_label = f"{PARASITES[armed][0]} (+{fmt_pct(p_bonus)}%)" if armed in PARASITES else "Без паразита (+0%)"
    mod_inf = sum(v[3] for k, v in BATTLE_MODS.items() if u.get(k))
    l_mult, _, c_mult, _ = get_active_events()
    tot_bonus = r_inf + p_bonus + u["pity_bonus"] + mod_inf

    sample_rar = sorted_rarities(reverse=False)
    sample_line = ""
    if sample_rar:
        low_r = sample_rar[0]
        high_r = sample_rar[-1]
        c_low = fmt_pct(calc_infect_chance(low_r["infect_chance"], tot_bonus, l_mult))
        c_high = fmt_pct(calc_infect_chance(high_r["infect_chance"], tot_bonus, l_mult))
        sample_line = f"📊 Infect шанс: {low_r['name']} <b>{c_low}%</b> | {high_r['name']} <b>{c_high}%</b>\n"

    enemy_cnt_hint = "1–2" if rank_idx == 0 else ("2" if rank_idx == 1 else ("2–3" if rank_idx == 2 else "4"))
    text = (
        f"⚔️ <b>БИТВА ЗА SKIBIDI (4×4)</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎖 Rank: <b>{r_name}</b> (🏆 {u['trophies']} | 💰 x{r_rew} | 🦠 +{r_inf}%)\n"
        f"👾 Врагов на ранге: <b>{enemy_cnt_hint} шт.</b>\n"
        f"🦠 Паразит на бой: <b>{p_label}</b>\n"
        f"🎯 Пити: <b>+{u['pity_bonus']}%</b> | 🧬 Моды: <b>+{mod_inf}%</b>\n"
        f"{sample_line}"
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


@router.message(F.text == "⚔️ Играть")
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
    cur = u["armed_parasite"]
    rows = [[InlineKeyboardButton(text=("✅ " if cur == "none" else "") + "Без паразита (+0%)", callback_data="btl:setp:none")]]
    for k in ("common", "upgraded", "elite"):
        name, col, _, bon = get_parasite_info(k)
        cnt = u[col]
        rows.append([InlineKeyboardButton(text=f"{'✅ ' if cur == k else ''}{name} (+{fmt_pct(bon)}%) — {cnt} шт.", callback_data=f"btl:setp:{k}")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="btl:hub")])
    await render_view(cb, "🦠 <b>ВЫБОР ПАРАЗИТА НА БОЙ</b>\n1 паразит тратится в начале боя и усиливает шанс заражения всех врагов.", InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer()


@router.callback_query(F.data.startswith("btl:setp:"))
async def cb_btl_setp(cb: CallbackQuery):
    pk = cb.data.split(":")[2]
    u = await db.get_user(cb.from_user.id)
    if pk != "none" and u[PARASITES[pk][1]] <= 0:
        await cb.answer("У вас нет этого паразита! Купите в «📦 Крейты».", show_alert=True)
        return
    await db.update_user(cb.from_user.id, armed_parasite=pk)
    await render_battle_hub(cb, cb.from_user.id)
    await cb.answer("✅ Паразит выбран!")


@router.callback_query(F.data.startswith("btl:surr:"))
async def cb_btl_surr(cb: CallbackQuery):
    bid = cb.data.split(":")[2]
    st = ACTIVE_BATTLES.get(bid)
    if not st or st["uid"] != cb.from_user.id:
        await cb.answer("Бой завершён.")
        return
    st["surrendered"] = True
    await cb.answer("🏳️ Вы сдались!", show_alert=True)


def _cleanup_stale_user_battle(uid: int) -> None:
    """Снимает зависшую блокировку боя, если он не активен или идёт дольше 180 сек."""
    now = time.monotonic()
    has_live = False
    for bid, st in list(ACTIVE_BATTLES.items()):
        if st.get("uid") == uid:
            if (now - st.get("started_at", now)) > 180.0:
                ACTIVE_BATTLES.pop(bid, None)
            else:
                has_live = True
    if not has_live:
        USERS_IN_BATTLE.discard(uid)


async def _battle_sleep(st: Dict[str, Any], seconds: float) -> None:
    """Пауза между раундами с мгновенной реакцией на кнопку «Сдаться»."""
    end_t = time.monotonic() + max(0.25, seconds)
    while time.monotonic() < end_t:
        if st.get("surrendered"):
            break
        await asyncio.sleep(min(0.25, max(0.05, end_t - time.monotonic())))


async def _deliver_battle_final(
    msg: Optional[Message],
    origin: Message,
    text: str,
    kb: InlineKeyboardMarkup,
    flood_until: float,
) -> None:
    """Гарантированно доставляет финальный экран боя, даже если чат поймал Flood Control."""
    wait_left = flood_until - time.monotonic()
    if wait_left > 0:
        await asyncio.sleep(min(wait_left, 35.0))

    for _ in range(2):
        try:
            if msg is not None:
                await asyncio.wait_for(msg.edit_text(text[:4096], reply_markup=kb), timeout=12.0)
                return
        except TelegramRetryAfter as e:
            await asyncio.sleep(min(e.retry_after + 0.5, 35.0))
            continue
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                return
            break
        except Exception:
            break

    for _ in range(2):
        try:
            await asyncio.wait_for(origin.answer(text[:4096], reply_markup=kb), timeout=12.0)
            return
        except TelegramRetryAfter as e:
            await asyncio.sleep(min(e.retry_after + 0.5, 35.0))
        except Exception:
            return


@router.callback_query(F.data.startswith("btl:go:"))
async def cb_btl_go(cb: CallbackQuery):
    uid = cb.from_user.id
    _cleanup_stale_user_battle(uid)
    if uid in USERS_IN_BATTLE:
        await cb.answer("Вы уже в бою!", show_alert=True)
        return
    deck = await db.get_inventory(uid, only_equipped=True)
    if not deck:
        await cb.answer("Сначала наденьте карты в «🛡 Колода»!", show_alert=True)
        return
    if not await db.list_cards():
        await cb.answer("В базе пока нет ни одной карты!", show_alert=True)
        return
    diff_key = cb.data.split(":")[2]
    if diff_key not in DIFFICULTIES:
        return

    USERS_IN_BATTLE.add(uid)
    try:
        await cb.answer("⚔️ Выходим на арену!")
    except Exception:
        pass
    asyncio.create_task(run_4v4_battle_task(cb.message, uid, diff_key, deck))


async def run_4v4_battle_task(origin: Message, uid: int, diff_key: str, deck: List[Dict[str, Any]]) -> None:
    bid = uuid.uuid4().hex[:10]
    ACTIVE_BATTLES[bid] = {"uid": uid, "surrendered": False, "started_at": time.monotonic()}
    try:
        u = await db.get_user(uid)
        rank_idx, r_name, _, r_rew_mult, r_inf_bonus = get_rank_info(u["trophies"])
        d_name, _, d_rew_scale, _, d_inf_bonus = DIFFICULTIES[diff_key]
        l_mult, _, c_event_mult, _ = get_active_events()

        # Расход выбранного паразита
        armed = u["armed_parasite"]
        p_bonus = 0.0
        p_used_label = ""
        if armed in PARASITES and u[PARASITES[armed][1]] > 0:
            await db.add_parasite(uid, armed, -1)
            p_bonus = cfg_float(f"p_{armed}_bonus")
            p_used_label = f" | {PARASITES[armed][0]}"
            if u[PARASITES[armed][1]] - 1 <= 0:
                await db.update_user(uid, armed_parasite="none")

        mods = {k: u.get(k, 0) for k in BATTLE_MODS}
        mod_coin_d = sum(v[1] for k, v in BATTLE_MODS.items() if mods.get(k))
        mod_tr_d = sum(v[2] for k, v in BATTLE_MODS.items() if mods.get(k))
        mod_inf_b = sum(v[3] for k, v in BATTLE_MODS.items() if mods.get(k))

        total_inf_bonus = r_inf_bonus + d_inf_bonus + p_bonus + u["pity_bonus"] + mod_inf_b

        t1 = [build_player_unit(c, 1.3 if mods.get("mod_player_hp") else 1.0) for c in deck]
        t2 = await generate_enemy_team(rank_idx, diff_key)
        if not t2:
            await origin.answer("❌ В базе нет карт-врагов для боя!")
            return
        if mods.get("mod_enemy_hp"):
            for e in t2:
                e["hp"] = int(e["hp"] * 1.5)
                e["max_hp"] = e["hp"]
        if mods.get("mod_enemy_stats"):
            for e in t2:
                e["hp"] = int(e["hp"] * 1.25)
                e["max_hp"] = e["hp"]
                e["atk"] = int(e["atk"] * 1.25)

        logs: List[str] = []
        apply_boosters_team(t1, u["full_name"], logs)
        apply_boosters_team(t2, f"Alliance {d_name}", logs)

        dmg_tracker: Dict[int, float] = {}
        infected_drops: List[Dict[str, Any]] = []
        crit_ch = 0.20 if mods.get("mod_player_crit") else 0.0
        delay = max(1.0, cfg_float("battle_delay_sec"))
        title = f"⚔️ {d_name}{p_used_label}"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏳️ Сдаться", callback_data=f"btl:surr:{bid}")]])

        msg: Optional[Message] = None
        flood_until = 0.0
        init_text = render_battle_screen(title, u["full_name"], t1, d_name, t2, logs, 0, 0)
        for _ in range(2):
            try:
                msg = await asyncio.wait_for(origin.answer(init_text, reply_markup=kb), timeout=12.0)
                break
            except TelegramRetryAfter as e:
                flood_until = time.monotonic() + e.retry_after + 1.0
                await asyncio.sleep(min(e.retry_after + 0.5, 30.0))
            except Exception:
                break

        last_edit_ts = time.monotonic()
        edits_count = 0
        winner = 0
        st = ACTIVE_BATTLES[bid]

        await _battle_sleep(st, min(delay, 1.5))

        for rnd in range(1, 36):
            if st["surrendered"]:
                winner = 2
                break
            if not any(x["hp"] > 0 for x in t1):
                winner = 2
                break
            if not any(x["hp"] > 0 for x in t2):
                winner = 1
                break

            perform_combat_turn(t1, t2, True, logs, dmg_tracker, infected_drops, total_inf_bonus, l_mult, crit_ch)
            if not any(x["hp"] > 0 for x in t2):
                winner = 1
                break

            if mods.get("mod_enemy_regen"):
                for e in t2:
                    if e["hp"] > 0 and e["hp"] < e["max_hp"]:
                        e["hp"] = min(e["max_hp"], e["hp"] + max(1, int(e["max_hp"] * 0.05)))
            perform_combat_turn(t2, t1, False, logs, dmg_tracker, infected_drops, total_inf_bonus, l_mult, 0.0)
            if not any(x["hp"] > 0 for x in t1):
                winner = 2
                break

            # Анти-флуд: не более ~18-19 правок/мин, чтобы Telegram никогда не вешал Flood Control
            now_t = time.monotonic()
            min_edit_gap = 1.5 if edits_count == 0 else max(delay, 3.2)
            if msg is not None and now_t >= flood_until and (now_t - last_edit_ts) >= min_edit_gap:
                screen = render_battle_screen(title, u["full_name"], t1, d_name, t2, logs, rnd, len(infected_drops))
                try:
                    await asyncio.wait_for(msg.edit_text(screen, reply_markup=kb), timeout=10.0)
                    last_edit_ts = time.monotonic()
                    edits_count += 1
                except TelegramRetryAfter as e:
                    # Не замораживаем бой — пропускаем промежуточные правки до конца КД
                    flood_until = time.monotonic() + e.retry_after + 1.0
                except Exception:
                    pass

            await _battle_sleep(st, delay)

        if winner == 0:
            r1 = sum(x["hp"] for x in t1) / max(1, sum(x["max_hp"] for x in t1))
            r2 = sum(x["hp"] for x in t2) / max(1, sum(x["max_hp"] for x in t2))
            winner = 1 if r1 >= r2 else 2

        total_dmg = sum(dmg_tracker.values())
        lvl_ups: List[str] = []
        for iid, dmg in dmg_tracker.items():
            it = await db.get_inv_item(iid)
            if not it:
                continue
            nl, nx, ups = apply_card_xp(it["level"], it["xp"], round(dmg * XP_PER_DAMAGE, 2))
            await db.update_inv_xp(iid, nl, nx)
            if ups > 0:
                lvl_ups.append(f"⭐ {esc(it['name'])} ➔ Lvl.{nl}!")

        fresh_u = await db.get_user(uid)
        coin_mod_mult = max(0.2, 1.0 + mod_coin_d)
        tr_mod_mult = max(0.5, 1.0 + mod_tr_d)

        if winner == 1:
            coins_won = max(20, int(random.randint(35, 85) * r_rew_mult * d_rew_scale * coin_mod_mult * c_event_mult))
            base_tr = random.randint(1, 2) if rank_idx >= 29 else max(5, 18 - int((rank_idx / 28) * 11))
            tr_won = max(1, int(base_tr * d_rew_scale * tr_mod_mult))

            await db.add_coins(uid, coins_won)
            await db.add_trophies(uid, tr_won)

            cur_drops: List[str] = []
            for cur in await db.list_currencies():
                if cur["drop_in_battles"] and (random.random() * 100.0) < (cur["drop_chance"] * l_mult):
                    amt = random.randint(max(1, cur["drop_min"]), max(cur["drop_min"], cur["drop_max"]))
                    await db.add_user_currency(uid, cur["id"], amt)
                    cur_drops.append(f"+{amt} {esc(cur['name'])}")

            inf_lines: List[str] = []
            for d in infected_drops:
                sh = roll_shiny()
                _, sn = await db.give_card(uid, d["card_id"], is_shiny=sh, is_infected=1)
                sn_s = f" <b>[#{sn:04d}]</b>" if sn else ""
                sh_s = " ✨<b>SHINY!</b>" if sh else ""
                inf_lines.append(f"🦠 <b>{esc(d['name'])}</b>{sn_s}{sh_s} ({fmt_pct(d['chance'])}%)")

            new_pity = 0 if infected_drops else min(50, fresh_u["pity_bonus"] + 2)
            await db.update_user(
                uid,
                wins=fresh_u["wins"] + 1,
                total_damage=round(fresh_u["total_damage"] + total_dmg, 1),
                infections_success=fresh_u["infections_success"] + len(infected_drops),
                pity_bonus=new_pity,
            )

            _, new_r_name, _, _, _ = get_rank_info(fresh_u["trophies"] + tr_won)
            rank_up = f"\n🎉 <b>НОВЫЙ РАНГ: {new_r_name}!</b>" if new_r_name != r_name else ""
            res_lines = [
                f"🏆 <b>ПОБЕДА SKIBIDI!</b> ({d_name})",
                "━━━━━━━━━━━━━━━━━━",
                f"💰 Монеты: <b>+{coins_won}</b>" + (f" (Ивент x{c_event_mult})" if c_event_mult > 1 else ""),
                f"🏆 Кубки: <b>+{tr_won}</b> (Всего: {fresh_u['trophies'] + tr_won}){rank_up}",
                f"💥 Урон: <b>{int(total_dmg)}</b> (+{round(total_dmg * XP_PER_DAMAGE, 1)} XP картам)",
            ]
            if cur_drops:
                res_lines.append("🪙 Дроп валют: <b>" + ", ".join(cur_drops) + "</b>")
            if lvl_ups:
                res_lines.append("📈 Прокачка: " + ", ".join(lvl_ups[:3]))
            if inf_lines:
                res_lines.append("\n🦠💥 <b>ЗАРАЖЁННЫЕ ТРОФЕИ:</b>\n" + "\n".join(inf_lines))
            else:
                res_lines.append(f"\n🎯 Пити заражения: <b>+{new_pity}%</b>")
        else:
            tr_lost = random.randint(25, 45) if rank_idx >= 29 else 4
            await db.add_trophies(uid, -tr_lost)
            await db.update_user(uid, losses=fresh_u["losses"] + 1, total_damage=round(fresh_u["total_damage"] + total_dmg, 1))
            res_lines = [
                f"💀 <b>ПОРАЖЕНИЕ ({d_name})</b>",
                "━━━━━━━━━━━━━━━━━━",
                f"🏆 Потеряно кубков: <b>-{tr_lost}</b>",
                f"💥 Урон: <b>{int(total_dmg)}</b> (карты получили опыт!)",
            ]
            if infected_drops:
                res_lines.append("<i>⚠️ Заражённые в бою враги сбежали, т.к. отряд проиграл.</i>")

        fin_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⚔️ Ещё бой", callback_data=f"btl:go:{diff_key}"), InlineKeyboardButton(text="🔙 В меню боя", callback_data="btl:hub")]])
        await _deliver_battle_final(msg, origin, "\n".join(res_lines), fin_kb, flood_until)
    except Exception as exc:
        logger.exception("Battle error: %s", exc)
    finally:
        ACTIVE_BATTLES.pop(bid, None)
        USERS_IN_BATTLE.discard(uid)

# ==============================================================================
# 8. КРЕЙТЫ И ЛАБОРАТОРИЯ (МАССОВАЯ ПОКУПКА И КРАФТ ПАРАЗИТОВ)
# ==============================================================================

async def render_lab(target: Message | CallbackQuery, uid: int):
    u = await db.get_user(uid)
    crates = await db.list_crates(active_only=True)
    curs = {c["id"]: c["name"] for c in await db.list_currencies()}
    u_curs = await db.get_user_currencies(uid)
    l_mult, _, _, _ = get_active_events()

    cp, cb_ = cfg_int("p_common_price"), cfg_float("p_common_bonus")
    up, ub = cfg_int("p_upgraded_price"), cfg_float("p_upgraded_bonus")
    ep, eb = cfg_int("p_elite_price"), cfg_float("p_elite_bonus")

    extra_bal = " | ".join(f"{esc(c['name'])}: <b>{c['amount']}</b>" for c in u_curs)
    text = (
        f"📦 <b>КРЕЙТЫ И ЛАБОРАТОРИЯ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Монеты: <b>{u['coins']}</b>" + (f"\n🪙 {extra_bal}" if extra_bal else "") + "\n"
        f"🦠 Паразиты: Обыч. <b>{u['p_common']}</b> | Улучш. <b>{u['p_upgraded']}</b> | Элит. <b>{u['p_elite']}</b>\n\n"
        f"🧪 <b>Паразиты (нажмите, чтобы купить x1 / x5 / x10 / МАКС):</b>\n"
        f"• 🦠 Обычный: <b>+{fmt_pct(cb_)}%</b> ({cp}💰)\n"
        f"• ☣️ Улучшенный: <b>+{fmt_pct(ub)}%</b> ({up}💰)\n"
        f"• 💎 Элитный: <b>+{fmt_pct(eb)}%</b> ({ep}💰)\n\n"
        f"📦 <b>Крейты</b> (✨ Shiny: {fmt_pct(cfg_float('shiny_chance_pct') * l_mult)}%):"
    )
    if not crates:
        text += "\n<i>Крейтов пока нет. Админ может создать их в Админ-панели.</i>"

    rows = [
        [
            InlineKeyboardButton(text=f"🦠 Обыч. ({cp}💰)", callback_data="lab:pview:common"),
            InlineKeyboardButton(text=f"☣️ Улучш. ({up}💰)", callback_data="lab:pview:upgraded"),
        ],
        [InlineKeyboardButton(text=f"💎 Элитный паразит ({ep}💰)", callback_data="lab:pview:elite")],
        [
            InlineKeyboardButton(text="⚗️ 3🦠➔1☣️", callback_data="lab:cr:upgraded:1"),
            InlineKeyboardButton(text="МАКС 🦠➔☣️", callback_data="lab:cr:upgraded:max"),
        ],
        [
            InlineKeyboardButton(text="⚗️ 3☣️➔1💎", callback_data="lab:cr:elite:1"),
            InlineKeyboardButton(text="МАКС ☣️➔💎", callback_data="lab:cr:elite:max"),
        ],
    ]
    for cr in crates:
        cname = "💰" if cr["currency_id"] == 0 else curs.get(cr["currency_id"], "💰")
        rows.append([InlineKeyboardButton(text=f"📦 {cr['name']} — {cr['price']} {cname}", callback_data=f"cr:i:{cr['id']}")])
    await render_view(target, text, InlineKeyboardMarkup(inline_keyboard=rows))


async def render_parasite_buy_menu(target: Message | CallbackQuery, uid: int, p_key: str):
    u = await db.get_user(uid)
    name, col, price, bon = get_parasite_info(p_key)
    owned = u[col]
    max_can = u["coins"] // price if price > 0 else 0

    text = (
        f"🧪 <b>ПОКУПКА: {name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Ваш баланс: <b>{u['coins']} монет</b>\n"
        f"🎒 В наличии: <b>{owned} шт.</b>\n"
        f"🦠 Бонус к шансу заражения: <b>+{fmt_pct(bon)}%</b> от базового шанса\n"
        f"💵 Цена за 1 шт.: <b>{price} 💰</b>\n\n"
        f"👇 Выберите, сколько паразитов купить:"
    )
    rows = [
        [
            InlineKeyboardButton(text=f"x1 ({price}💰)", callback_data=f"lab:b:{p_key}:1"),
            InlineKeyboardButton(text=f"x3 ({price * 3}💰)", callback_data=f"lab:b:{p_key}:3"),
            InlineKeyboardButton(text=f"x5 ({price * 5}💰)", callback_data=f"lab:b:{p_key}:5"),
        ],
        [
            InlineKeyboardButton(text=f"x10 ({price * 10}💰)", callback_data=f"lab:b:{p_key}:10"),
            InlineKeyboardButton(text=f"x25 ({price * 25}💰)", callback_data=f"lab:b:{p_key}:25"),
        ],
    ]
    if max_can > 0:
        rows.append([InlineKeyboardButton(text=f"🔥 Купить МАКС ({max_can} шт. за {max_can * price}💰)", callback_data=f"lab:b:{p_key}:max")])
    rows.append([InlineKeyboardButton(text="🔙 В Лабораторию", callback_data="lab:home")])
    await render_view(target, text, InlineKeyboardMarkup(inline_keyboard=rows))


@router.message(F.text == "📦 Крейты")
async def menu_lab(m: Message, state: FSMContext):
    await state.clear()
    await render_lab(m, m.from_user.id)


@router.callback_query(F.data == "lab:home")
async def cb_lab_home(cb: CallbackQuery):
    await render_lab(cb, cb.from_user.id)
    await cb.answer()


@router.callback_query(F.data.startswith("lab:pview:"))
async def cb_lab_pview(cb: CallbackQuery):
    pk = cb.data.split(":")[2]
    if pk not in PARASITES:
        return
    await render_parasite_buy_menu(cb, cb.from_user.id, pk)
    await cb.answer()


@router.callback_query(F.data.startswith("lab:b:"))
async def cb_lab_buy(cb: CallbackQuery):
    _, _, pk, amt_s = cb.data.split(":")
    if pk not in PARASITES:
        return
    name, _, price, _ = get_parasite_info(pk)
    u = await db.get_user(cb.from_user.id)

    if amt_s == "max":
        amt = u["coins"] // price if price > 0 else 0
        if amt <= 0:
            await cb.answer(f"Недостаточно монет! Минимум {price} 💰.", show_alert=True)
            return
    else:
        amt = max(1, int(amt_s))

    total_cost = price * amt
    if u["coins"] < total_cost:
        await cb.answer(f"Нужно {total_cost} 💰 (у вас {u['coins']} 💰)!", show_alert=True)
        return
    await db.add_coins(u["user_id"], -total_cost)
    await db.add_parasite(u["user_id"], pk, amt)
    await cb.answer(f"✅ Куплено {amt}x {name} за {total_cost} 💰!", show_alert=True)
    await render_parasite_buy_menu(cb, u["user_id"], pk)


@router.callback_query(F.data.startswith("lab:cr:"))
async def cb_lab_craft(cb: CallbackQuery):
    _, _, tgt, mode = cb.data.split(":")
    src = "common" if tgt == "upgraded" else "upgraded"
    u = await db.get_user(cb.from_user.id)
    have = u[PARASITES[src][1]]
    crafts = (have // 3) if mode == "max" else (1 if have >= 3 else 0)
    if crafts <= 0:
        await cb.answer(f"Нужно минимум 3x {PARASITES[src][0]}!", show_alert=True)
        return
    await db.add_parasite(u["user_id"], src, -(crafts * 3))
    await db.add_parasite(u["user_id"], tgt, crafts)
    await cb.answer(f"⚗️ Скрафчено {crafts}x {PARASITES[tgt][0]}!", show_alert=True)
    await render_lab(cb, u["user_id"])


@router.callback_query(F.data.startswith("cr:i:"))
async def cb_cr_info(cb: CallbackQuery):
    cid = int(cb.data.split(":")[2])
    cr = await db.get_crate(cid)
    if not cr or not cr["active"]:
        await cb.answer("Крейт недоступен.", show_alert=True)
        return
    cur_obj = await db.get_currency(cr["currency_id"]) if cr["currency_id"] else None
    cur_name = cur_obj["name"] if cur_obj else "💰 Монет"
    bal = await db.get_user_currency_bal(cb.from_user.id, cr["currency_id"])
    all_c = {str(c["id"]): c for c in await db.list_cards()}
    l_mult, _, _, _ = get_active_events()

    tot = 0.0
    eff = []
    for k, w in cr["cards"].items():
        co = all_c.get(str(k))
        if not co or float(w) <= 0:
            continue
        r = get_rarity(co["rarity"])
        ew = float(w) * (l_mult if r["weight"] >= 4 else 1.0)
        tot += ew
        eff.append((co, ew))

    lines = [
        f"📦 <b>{esc(cr['name'])}</b>",
        f"<i>{esc(cr['description'])}</i>" if cr["description"] else "",
        f"💵 Цена: <b>{cr['price']} {esc(cur_name)}</b> | Ваш баланс: <b>{bal}</b>",
        f"✨ Шанс Shiny: <b>{fmt_pct(cfg_float('shiny_chance_pct') * l_mult)}%</b>",
        "━━━━━━━━━━━━━━━━━━",
        "🎲 <b>Шансы выпадения:</b>",
    ]
    for co, ew in sorted(eff, key=lambda x: x[1], reverse=True):
        r_ico = get_rarity(co["rarity"])["emoji"]
        lines.append(f"• {r_ico} <b>{esc(co['name'])}</b> — {fmt_pct(ew / tot * 100)}%")
    if not eff:
        lines.append("<i>Крейт пуст.</i>")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Открыть x1 ({cr['price']})", callback_data=f"cr:o:{cid}:1"), InlineKeyboardButton(text=f"x5 ({cr['price'] * 5})", callback_data=f"cr:o:{cid}:5")],
        [InlineKeyboardButton(text=f"Открыть x10 ({cr['price'] * 10})", callback_data=f"cr:o:{cid}:10")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="lab:home")],
    ])
    await render_view(cb, "\n".join(x for x in lines if x != ""), kb, photo=cr.get("photo_id") or None)
    await cb.answer()


@router.callback_query(F.data.startswith("cr:o:"))
async def cb_cr_open(cb: CallbackQuery):
    _, _, cid_s, amt_s = cb.data.split(":")
    cid, amt = int(cid_s), int(amt_s)
    cr = await db.get_crate(cid)
    if not cr or not cr["active"]:
        await cb.answer("Крейт недоступен.", show_alert=True)
        return
    uid = cb.from_user.id
    cost = cr["price"] * amt
    bal = await db.get_user_currency_bal(uid, cr["currency_id"])
    if bal < cost:
        await cb.answer(f"Недостаточно средств! Нужно {cost}.", show_alert=True)
        return
    all_c = {str(c["id"]): c for c in await db.list_cards()}
    l_mult, _, _, _ = get_active_events()
    pool, weights = [], []
    for k, w in cr["cards"].items():
        co = all_c.get(str(k))
        if co and float(w) > 0:
            r = get_rarity(co["rarity"])
            pool.append(co)
            weights.append(float(w) * (l_mult if r["weight"] >= 4 else 1.0))
    if not pool:
        await cb.answer("Крейт пуст!", show_alert=True)
        return

    await db.add_user_currency(uid, cr["currency_id"], -cost)
    dropped = random.choices(pool, weights=weights, k=amt)
    lines = [f"🎉 <b>ОТКРЫТО {amt}x «{esc(cr['name'])}»</b>", "━━━━━━━━━━━━━━━━━━"]
    summary: Dict[Tuple[str, str, int, int], int] = {}
    photo = None
    for co in dropped:
        sh = roll_shiny()
        _, sn = await db.give_card(uid, co["id"], is_shiny=sh)
        r_ico = get_rarity(co["rarity"])["emoji"]
        key = (r_ico, co["name"], sh, sn)
        summary[key] = summary.get(key, 0) + 1
        if amt == 1:
            photo = co.get("photo_id") or None
    for (r_ico, name, sh, sn), cnt in summary.items():
        sh_s = "✨<b>SHINY</b> " if sh else ""
        sn_s = f" <b>[#{sn:04d}]</b>" if sn else ""
        lines.append(f"• {r_ico} {sh_s}<b>{esc(name)}</b>{sn_s} — x{cnt}")

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"🔁 Ещё x{amt}", callback_data=f"cr:o:{cid}:{amt}"), InlineKeyboardButton(text="🔙 Назад", callback_data="lab:home")]])
    await render_view(cb, "\n".join(lines), kb, photo=photo)
    await cb.answer("🎉 Открыто!")


# ==============================================================================
# 9. МУЛЬТИПЛЕЕР (МИРОВОЙ БОСС + P2P-РЫНОК 80/20) И ЛИДЕРБОРД
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
    st = f"🟢 {esc(wb['name'])} ({wb['current_hp']} HP)" if wb else "⚪️ Спит"
    await m.answer(f"🌐 <b>МУЛЬТИПЛЕЕР ХАБ</b>\n━━━━━━━━━━━━━━━━━━\n🌍 Мировой Босс: {st}\n🏪 P2P Рынок: 80% продавцу, 20% комиссия.", reply_markup=mp_kb())


@router.callback_query(F.data == "mp:hub")
async def cb_mp_hub(cb: CallbackQuery):
    wb = await db.get_world_boss()
    st = f"🟢 {esc(wb['name'])} ({wb['current_hp']} HP)" if wb else "⚪️ Спит"
    await render_view(cb, f"🌐 <b>МУЛЬТИПЛЕЕР ХАБ</b>\n🌍 Мировой Босс: {st}", mp_kb())
    await cb.answer()


async def render_wb(target: Message | CallbackQuery):
    wb = await db.get_world_boss()
    if not wb:
        await render_view(target, "🌍 <b>МИРОВОЙ БОСС</b>\n\nСейчас Мировой Босс отдыхает.", InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="mp:hub")]]))
        return
    top = await db.get_wb_top(wb["id"], 5)
    t_txt = "\n".join(f"{i}. {fmt_user(t)} — <b>{int(t['damage'])}</b>" for i, t in enumerate(top, 1)) or "<i>Ударь первым!</i>"
    txt = (
        f"🌍 <b>МИРОВОЙ БОСС: {esc(wb['name'])}</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"{make_bar(wb['current_hp'], wb['max_hp'], 10, '🟥', '⬛')}\n"
        f"❤️ HP: <b>{wb['current_hp']} / {wb['max_hp']}</b>\n\n"
        f"🏆 <b>Топ-5 по урону:</b>\n{t_txt}\n\n"
        f"🎁 Топ-3 при добивании получают крупные монеты и шанс заразить Босса!"
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
    cd = cfg_int("wb_cooldown_sec")
    now = int(time.time())
    if prev and (now - prev["last_hit"]) < cd:
        await cb.answer(f"⏳ Перезарядка: {cd - (now - prev['last_hit'])} сек.", show_alert=True)
        return
    deck = await db.get_inventory(uid, only_equipped=True)
    if not deck:
        await cb.answer("Сначала соберите колоду!", show_alert=True)
        return

    dmg = max(20.0, round(sum(calc_card_stats(c)["atk"] for c in deck) * random.uniform(1.3, 1.8), 1))
    rem = await db.hit_wb(wb["id"], uid, dmg)
    xp_each = round((dmg / len(deck)) * XP_PER_DAMAGE, 2)
    for c in deck:
        nl, nx, _ = apply_card_xp(c["level"], c["xp"], xp_each)
        await db.update_inv_xp(c["inv_id"], nl, nx)

    if rem <= 0:
        top = await db.get_wb_top(wb["id"], 10)
        l_mult, _, c_mult, _ = get_active_events()
        base_ch = float(get_rarity(wb["rarity"])["infect_chance"])
        wb_ch = calc_infect_chance(base_ch, 100, l_mult)
        for idx, p in enumerate(top, 1):
            p_uid = p["user_id"]
            coins = int(max(150, 950 - (idx - 1) * 140) * c_mult)
            await db.add_coins(p_uid, coins)
            extra = ""
            if idx <= 3 and (random.random() * 100.0) < wb_ch:
                sh = roll_shiny()
                _, sn = await db.give_card(p_uid, wb["card_id"], is_shiny=sh, is_infected=1)
                extra = f"\n🦠 <b>ВЫ ЗАРАЗИЛИ МИРОВОГО БОССА!</b> {esc(wb['name'])}{f' [#{sn:04d}]' if sn else ''}{' ✨SHINY!' if sh else ''}"
            try:
                await bot.send_message(p_uid, f"🌍🏆 <b>МИРОВОЙ БОСС {esc(wb['name'])} ПОВЕРЖЕН!</b>\nМесто: <b>#{idx}</b> | 💰 <b>+{coins}</b>{extra}")
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
    for lot in lots[page * per : (page + 1) * per]:
        r_ico = get_rarity(lot["rarity"])["emoji"]
        sn = f" #{lot['serial_number']:04d}" if lot["serial_number"] else ""
        mine = " (Мой)" if lot["seller_id"] == uid else ""
        rows.append([InlineKeyboardButton(text=f"{r_ico}{card_badges(lot)} {lot['name']}{sn} Lvl.{lot['level']} — {lot['price']}💰{mine}", callback_data=f"mkt:v:{lot['market_id']}:{page}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"mp:mkt:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{tp}", callback_data="noop"))
    if page < tp - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"mp:mkt:{page + 1}"))
    rows.extend([nav, [InlineKeyboardButton(text="🔙 Назад", callback_data="mp:hub")]])
    await render_view(target, f"🏪 <b>P2P РЫНОК</b> (80% продавцу / 20% комиссия)\nЛотов: <b>{len(lots)}</b>", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("mp:mkt:"))
async def cb_mkt_p(cb: CallbackQuery):
    await render_market(cb, cb.from_user.id, int(cb.data.split(":")[2]))
    await cb.answer()


@router.callback_query(F.data.startswith("mkt:v:"))
async def cb_mkt_v(cb: CallbackQuery):
    _, _, lid_s, p_s = cb.data.split(":")
    lid, p = int(lid_s), int(p_s)
    lot = next((x for x in await db.list_market() if x["market_id"] == lid), None)
    if not lot:
        await cb.answer("Лот недоступен.", show_alert=True)
        await render_market(cb, cb.from_user.id, p)
        return
    st = calc_card_stats(lot)
    txt = (
        f"🏷 <b>ЛОТ #{lid}</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"🃏 <b>{esc(lot['name'])}</b>{fmt_serial(lot)} {card_badges(lot)} (Lvl.{lot['level']})\n"
        f"Class: <b>{lot['class_type']}</b> | ⚔️ ATK: <b>{st['atk']}</b> | ❤️ HP: <b>{st['hp']}</b>\n"
        f"Sign: {get_sign_text(lot)}\n"
        f"👤 Продавец: <b>{esc(lot['seller_name'] or 'Игрок')}</b>\n💰 Цена: <b>{lot['price']} монет</b>"
    )
    act = (
        InlineKeyboardButton(text="❌ Снять с продажи", callback_data=f"mkt:c:{lid}:{p}")
        if lot["seller_id"] == cb.from_user.id
        else InlineKeyboardButton(text=f"✅ Купить за {lot['price']} 💰", callback_data=f"mkt:b:{lid}:{p}")
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
            await bot.send_message(lot["seller_id"], f"💰 Вашу карту <b>{esc(lot['name'])}</b> купили! Зачислено (80%): <b>+{lot['payout']} 💰</b>")
        except Exception:
            pass
    await render_market(cb, cb.from_user.id, int(p_s))


@router.callback_query(F.data.startswith("mkt:c:"))
async def cb_mkt_c(cb: CallbackQuery):
    _, _, lid_s, p_s = cb.data.split(":")
    ok = await db.cancel_market_lot(int(lid_s), cb.from_user.id)
    await cb.answer("Снято!" if ok else "Ошибка.", show_alert=True)
    await render_market(cb, cb.from_user.id, int(p_s))


async def render_top(target: Message | CallbackQuery, mode: str = "trophies"):
    meta = {
        "trophies": ("🏆 Топ по Кубкам (Ranks)", "🏆"),
        "infections_success": ("🦠 Топ по Заражениям", "infects"),
        "wins": ("⚔️ Топ по Победам", "wins"),
        "total_damage": ("💥 Топ по Урону", "dmg"),
        "coins": ("💰 Топ Богачей", "💰"),
    }
    title, unit = meta.get(mode, meta["trophies"])
    rows_db = await db.get_leaderboard(mode, 10)
    meds = ["🥇", "🥈", "🥉"]
    lines = [f"<b>{title}</b>", "━━━━━━━━━━━━━━━━━━"]
    for i, r in enumerate(rows_db, 1):
        m = meds[i - 1] if i <= 3 else f"<b>{i}.</b>"
        extra = f" <i>({get_rank_info(int(r['val']))[1]})</i>" if mode == "trophies" else ""
        lines.append(f"{m} {fmt_user(r)} — <b>{int(r['val'])}</b> {unit}{extra}")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏆 Кубки", callback_data="top:trophies"), InlineKeyboardButton(text="🦠 Зараж.", callback_data="top:infections_success"), InlineKeyboardButton(text="⚔️ Победы", callback_data="top:wins")],
        [InlineKeyboardButton(text="💥 Урон", callback_data="top:total_damage"), InlineKeyboardButton(text="💰 Монеты", callback_data="top:coins")],
    ])
    await render_view(target, "\n".join(lines), kb)


@router.message(F.text == "🏆 Лидерборд")
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

async def render_admin_home(target: Message | CallbackQuery, uid: int):
    perms = await db.get_admin_perms(uid)
    st = await db.get_stats()
    maint = "🔴 ВКЛ" if GAME_SETTINGS.get("maintenance") == "1" else "🟢 ВЫКЛ"
    running_cb = sum(1 for cid in child_manager.tasks if child_manager.is_running(cid))
    l_m, l_s, c_m, c_s = get_active_events()
    ev_s = f"🍀x{l_m} ({l_s // 60}м) | 💰x{c_m} ({c_s // 60}м)" if (l_m > 1 or c_m > 1) else "нет"
    txt = (
        f"⚙️ <b>АДМИН-ПАНЕЛЬ SKIBIDI VERSE</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"👥 Игроков: <b>{st['users']}</b> | 🃏 Карт: <b>{st['cards']}</b> | 🌟 Редкостей: <b>{st['rarities']}</b>\n"
        f"📦 Крейтов: <b>{st['crates']}</b> | 🪙 Валют: <b>{st['currencies']}</b> | 🏪 Рынок: <b>{st['market']}</b>\n"
        f"🤖 Дочерних ботов: <b>{st['child_bots']}</b> (🟢 онлайн: <b>{running_cb}</b>)\n"
        f"🎉 Ивенты: <b>{ev_s}</b> | 🛠 Техработы: <b>{maint}</b>"
    )
    rows = []
    r1 = []
    if perms.get("manage_cards"):
        r1.append(InlineKeyboardButton(text="🃏 Карты", callback_data="adm:cards:0"))
    if perms.get("manage_rarities"):
        r1.append(InlineKeyboardButton(text="🌟 Редкости", callback_data="adm:rar:0"))
    if r1:
        rows.append(r1)
    r2 = []
    if perms.get("manage_crates"):
        r2.append(InlineKeyboardButton(text="📦 Крейты", callback_data="adm:cr"))
    if perms.get("manage_currencies"):
        r2.append(InlineKeyboardButton(text="🪙 Валюты", callback_data="adm:cur"))
    if r2:
        rows.append(r2)
    r3 = []
    if perms.get("manage_events"):
        r3.append(InlineKeyboardButton(text="🎉 Ивенты", callback_data="adm:ev"))
    if perms.get("manage_settings"):
        r3.append(InlineKeyboardButton(text="🎛 Баланс", callback_data="adm:set:0"))
    if r3:
        rows.append(r3)
    r4 = []
    if perms.get("manage_bosses"):
        r4.append(InlineKeyboardButton(text="🌍 Мировой Босс", callback_data="adm:wb"))
    if perms.get("manage_child_bots"):
        r4.append(InlineKeyboardButton(text=f"🤖 Дочерние боты ({st['child_bots']})", callback_data="adm:cbots:0"))
    if r4:
        rows.append(r4)
    r5 = []
    if perms.get("manage_users") or perms.get("manage_economy"):
        r5.append(InlineKeyboardButton(text="👥 Игроки", callback_data="adm:users"))
    if perms.get("broadcast"):
        r5.append(InlineKeyboardButton(text="📢 Рассылка", callback_data="adm:bcast"))
    if r5:
        rows.append(r5)
    if perms.get("manage_admins"):
        rows.append([InlineKeyboardButton(text="👮 Админы", callback_data="adm:admins"), InlineKeyboardButton(text="🤝 Партнёры", callback_data="adm:sgn")])
        rows.append([InlineKeyboardButton(text=f"🛠 Техработы ({maint})", callback_data="adm:maint"), InlineKeyboardButton(text="💾 Бэкап БД", callback_data="adm:bak")])
        rows.append([InlineKeyboardButton(text="📋 Логи админов", callback_data="adm:logs")])
    await render_view(target, txt, InlineKeyboardMarkup(inline_keyboard=rows))


@router.message(F.text == "⚙️ Админ-панель")
async def menu_admin(m: Message, state: FSMContext, is_admin: bool):
    if not is_admin:
        return
    await state.clear()
    await render_admin_home(m, m.from_user.id)


@router.callback_query(F.data == "adm:home")
async def cb_adm_home(cb: CallbackQuery, state: FSMContext):
    if not await db.is_admin(cb.from_user.id):
        await cb.answer("Нет доступа!", show_alert=True)
        return
    await state.clear()
    await render_admin_home(cb, cb.from_user.id)
    await cb.answer()


# --- АДМИН: РЕДКОСТИ (СОЗДАНИЕ, РЕДАКТОР, УДАЛЕНИЕ) ---

async def render_adm_rarities(target: Message | CallbackQuery):
    rars = sorted_rarities(reverse=True)
    rows = [[InlineKeyboardButton(text="➕ Создать Редкость", callback_data="arar:new")]]
    for r in rars:
        ser = " #️⃣" if r["has_serial"] else ""
        rows.append([
            InlineKeyboardButton(
                text=f"{r['emoji']} {r['name']} (W:{r['weight']} | 🦠{fmt_pct(r['infect_chance'])}%{ser})",
                callback_data=f"arar:ed:{r['key']}",
            )
        ])
    rows.append([InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")])
    await render_view(target, f"🌟 <b>УПРАВЛЕНИЕ РЕДКОСТЯМИ</b> ({len(rars)})", InlineKeyboardMarkup(inline_keyboard=rows))


async def render_adm_rarity_editor(target: Message | CallbackQuery, r_key: str):
    if r_key not in RARITIES_CACHE:
        await render_adm_rarities(target)
        return
    r = RARITIES_CACHE[r_key]
    txt = (
        f"🌟 <b>РЕДКОСТЬ: {r['emoji']} {esc(r['name'])}</b> [<code>{r['key']}</code>]\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"• Вес (порядок сортировки): <b>{r['weight']}</b>\n"
        f"• 🦠 Базовый шанс заражения: <b>{fmt_pct(r['infect_chance'])}%</b>\n"
        f"• #️⃣ Серийные номера [#0001]: <b>{'ВКЛ' if r['has_serial'] else 'ВЫКЛ'}</b>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Name", callback_data=f"arar:f:{r_key}:name"), InlineKeyboardButton(text="😀 Emoji", callback_data=f"arar:f:{r_key}:emoji")],
        [InlineKeyboardButton(text="⚖️ Weight", callback_data=f"arar:f:{r_key}:weight"), InlineKeyboardButton(text="🦠 Infect %", callback_data=f"arar:f:{r_key}:infect_chance")],
        [InlineKeyboardButton(text=f"#️⃣ Серийники: {'ВКЛ' if r['has_serial'] else 'ВЫКЛ'}", callback_data=f"arar:ser:{r_key}")],
        [InlineKeyboardButton(text="🗑 Удалить редкость", callback_data=f"arar:del:{r_key}")],
        [InlineKeyboardButton(text="🔙 К редкостям", callback_data="adm:rar:0")],
    ])
    await render_view(target, txt, kb)


@router.callback_query(F.data.startswith("adm:rar:"))
async def cb_adm_rar(cb: CallbackQuery):
    if not await db.has_perm(cb.from_user.id, "manage_rarities"):
        await cb.answer("Нет прав!", show_alert=True)
        return
    await render_adm_rarities(cb)
    await cb.answer()


@router.callback_query(F.data == "arar:new")
async def cb_arar_new(cb: CallbackQuery, state: FSMContext):
    await state.set_state(RarityFSM.create)
    await cb.message.answer(
        "🌟 <b>Создание новой редкости</b>\n"
        "Введите через <code>|</code>:\n"
        "<code>Name | Emoji | Weight | InfectChance% | Serial(0/1)</code>\n\n"
        "Пример: <code>Divine | 🌈 | 8 | 0.125% | 1</code>"
    )
    await cb.answer()


@router.message(RarityFSM.create)
async def fsm_arar_create(m: Message, state: FSMContext):
    await state.clear()
    parts = [p.strip() for p in (m.text or "").split("|")]
    try:
        name = parts[0]
        emoji = parts[1] if len(parts) > 1 and parts[1] else "✨"
        weight = int(parts[2]) if len(parts) > 2 else (max((r["weight"] for r in RARITIES_CACHE.values()), default=0) + 1)
        inf_ch = parse_float(parts[3]) if len(parts) > 3 else 0.01
        if not (0.0 <= inf_ch <= 100.0):
            raise ValueError
        has_ser = 1 if (len(parts) > 4 and parts[4] == "1") else 0
        key = re.sub(r"[^a-z0-9_]", "", name.lower().replace(" ", "_")) or f"rar_{int(time.time())}"
        if key in RARITIES_CACHE:
            await m.answer(f"❌ Редкость с ключом <code>{key}</code> уже существует!")
            return
    except (ValueError, IndexError):
        await m.answer("❌ Неверный формат! Пример: <code>Divine | 🌈 | 8 | 0.125% | 1</code>")
        return
    await db.create_rarity(key, name, emoji, weight, inf_ch, has_ser)
    await db.log_admin(m.from_user.id, f"Создал редкость {name} ({key})")
    await m.answer(f"✅ Редкость {emoji} <b>{esc(name)}</b> создана!")
    await render_adm_rarities(m)


@router.callback_query(F.data.startswith("arar:ed:"))
async def cb_arar_ed(cb: CallbackQuery):
    await render_adm_rarity_editor(cb, cb.data.split(":")[2])
    await cb.answer()


@router.callback_query(F.data.startswith("arar:ser:"))
async def cb_arar_ser(cb: CallbackQuery):
    rk = cb.data.split(":")[2]
    r = get_rarity(rk)
    await db.update_rarity(rk, has_serial=0 if r["has_serial"] else 1)
    await render_adm_rarity_editor(cb, rk)
    await cb.answer("Обновлено!")


@router.callback_query(F.data.startswith("arar:f:"))
async def cb_arar_f(cb: CallbackQuery, state: FSMContext):
    _, _, rk, fld = cb.data.split(":")
    await state.set_state(RarityFSM.edit_val)
    await state.update_data(rk=rk, fld=fld)
    await cb.message.answer(f"Введите новое значение для <b>{fld}</b> (для процента можно дробное, напр. <code>0.125%</code>):")
    await cb.answer()


@router.message(RarityFSM.edit_val)
async def fsm_arar_ed_val(m: Message, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    rk, fld = d["rk"], d["fld"]
    try:
        raw = (m.text or "").strip()
        if fld == "weight":
            val: Any = int(raw)
        elif fld == "infect_chance":
            val = parse_float(raw)
            if not (0.0 <= val <= 100.0):
                raise ValueError
        else:
            val = raw
    except ValueError:
        await m.answer("❌ Неверный формат. Пример процента: <code>2.5%</code> или <code>0.125</code>.")
        return
    await db.update_rarity(rk, **{fld: val})
    await render_adm_rarity_editor(m, rk)


@router.callback_query(F.data.startswith("arar:del:"))
async def cb_arar_del(cb: CallbackQuery):
    rk = cb.data.split(":")[2]
    if len(RARITIES_CACHE) <= 1:
        await cb.answer("Нельзя удалить последнюю редкость!", show_alert=True)
        return
    cards_using = [c for c in await db.list_cards() if c["rarity"] == rk]
    if cards_using:
        await cb.answer(f"Нельзя удалить: {len(cards_using)} карт используют эту редкость!", show_alert=True)
        return
    await db.delete_rarity(rk)
    await db.log_admin(cb.from_user.id, f"Удалил редкость {rk}")
    await cb.answer("🗑 Редкость удалена!", show_alert=True)
    await render_adm_rarities(cb)


# --- АДМИН: ДОЧЕРНИЕ БОТЫ (МОНИТОРИНГ И ПОЛНЫЙ КОНТРОЛЬ) ---

async def render_adm_child_bots(target: Message | CallbackQuery, page: int = 0):
    all_bots = await db.list_child_bots()
    running = sum(1 for b in all_bots if child_manager.is_running(b["id"]))
    allow = GAME_SETTINGS.get("allow_child_bots", "1") == "1"
    per = 6
    tp = max(1, (len(all_bots) + per - 1) // per)
    page = max(0, min(page, tp - 1))

    txt = (
        f"🤖 <b>УПРАВЛЕНИЕ ДОЧЕРНИМИ БОТАМИ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Всего ботов: <b>{len(all_bots)}</b> | 🟢 Работают: <b>{running}</b>\n"
        f"Привязка новых (/linkbot): <b>{'🟢 Разрешена' if allow else '🔴 Запрещена'}</b>"
    )
    rows: List[List[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="▶️ Запустить все", callback_data="acb:all:start"),
            InlineKeyboardButton(text="⏹ Остановить все", callback_data="acb:all:stop"),
        ],
        [InlineKeyboardButton(text=f"🔓 Привязка /linkbot: {'ВКЛ' if allow else 'ВЫКЛ'}", callback_data="acb:tgl_allow")],
    ]
    for b in all_bots[page * per : (page + 1) * per]:
        st = "🚫" if b["is_banned"] else ("🟢" if child_manager.is_running(b["id"]) else "🔴")
        uname = f"@{b['username']}" if b["username"] else f"Bot#{b['id']}"
        rows.append([InlineKeyboardButton(text=f"{st} {uname} | 👤{b['owner_id']} | ⚡{b['updates_count']}", callback_data=f"acb:v:{b['id']}:{page}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"adm:cbots:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{tp}", callback_data="noop"))
    if page < tp - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"adm:cbots:{page + 1}"))
    rows.extend([nav, [InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")]])
    await render_view(target, txt, InlineKeyboardMarkup(inline_keyboard=rows))


async def render_adm_child_bot_detail(target: Message | CallbackQuery, cb_id: int, page: int):
    b = await db.get_child_bot(cb_id)
    if not b:
        await render_adm_child_bots(target, page)
        return
    is_run = child_manager.is_running(cb_id)
    st = "🚫 ЗАБАНЕН" if b["is_banned"] else ("🟢 РАБОТАЕТ" if is_run else "🔴 ОСТАНОВЛЕН")
    tok_masked = b["token"][:10] + "..." + b["token"][-6:]
    dt = datetime.fromtimestamp(b["created_at"]).strftime("%d.%m.%Y %H:%M") if b["created_at"] else "—"
    owner_lbl = f"<b>{esc(b['owner_name'] or 'Игрок')}</b> (@{esc(b['owner_username'])})" if b.get("owner_username") else f"<code>{b['owner_id']}</code>"
    err = f"\n⚠️ Последняя ошибка: <code>{esc(b['last_error'])}</code>" if b.get("last_error") else ""

    txt = (
        f"🤖 <b>ДОЧЕРНИЙ БОТ #{b['id']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"• Username: <b>@{esc(b['username'] or '—')}</b> ({esc(b['title'])})\n"
        f"• Bot ID: <code>{b['bot_id']}</code> | Статус: <b>{st}</b>\n"
        f"• Владелец: {owner_lbl} [<code>{b['owner_id']}</code>]\n"
        f"• Токен: <code>{esc(tok_masked)}</code>\n"
        f"• Обработано апдейтов: <b>{b['updates_count']}</b>\n"
        f"• Привязан: <code>{dt}</code>{err}"
    )
    rows = [
        [
            InlineKeyboardButton(text="⏹ Остановить" if is_run else "▶️ Запустить", callback_data=f"acb:{'stop' if is_run else 'start'}:{cb_id}:{page}"),
            InlineKeyboardButton(text="✅ Разбанить" if b["is_banned"] else "🚫 Забанить", callback_data=f"acb:ban:{cb_id}:{page}"),
        ],
        [InlineKeyboardButton(text="🗑 Удалить бота", callback_data=f"acb:del:{cb_id}:{page}")],
        [InlineKeyboardButton(text="🔙 К списку ботов", callback_data=f"adm:cbots:{page}")],
    ]
    await render_view(target, txt, InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("adm:cbots:"))
async def cb_adm_cbots(cb: CallbackQuery):
    if not await db.has_perm(cb.from_user.id, "manage_child_bots"):
        await cb.answer("Нет прав!", show_alert=True)
        return
    await render_adm_child_bots(cb, int(cb.data.split(":")[2]))
    await cb.answer()


@router.callback_query(F.data == "acb:tgl_allow")
async def cb_acb_allow(cb: CallbackQuery):
    nxt = "0" if GAME_SETTINGS.get("allow_child_bots", "1") == "1" else "1"
    await db.set_setting("allow_child_bots", nxt)
    await db.log_admin(cb.from_user.id, f"allow_child_bots={nxt}")
    await render_adm_child_bots(cb, 0)
    await cb.answer("Обновлено!")


@router.callback_query(F.data.startswith("acb:all:"))
async def cb_acb_all(cb: CallbackQuery):
    act = cb.data.split(":")[2]
    if act == "start":
        cnt = await child_manager.start_all_active()
        await cb.answer(f"▶️ Запущено ботов: {cnt}", show_alert=True)
    else:
        await child_manager.stop_all(mark_db_inactive=True)
        await cb.answer("⏹ Все дочерние боты остановлены!", show_alert=True)
    await render_adm_child_bots(cb, 0)


@router.callback_query(F.data.startswith("acb:v:"))
async def cb_acb_v(cb: CallbackQuery):
    _, _, cid_s, p_s = cb.data.split(":")
    await render_adm_child_bot_detail(cb, int(cid_s), int(p_s))
    await cb.answer()


@router.callback_query(F.data.startswith("acb:start:"))
async def cb_acb_start(cb: CallbackQuery):
    _, _, cid_s, p_s = cb.data.split(":")
    row = await db.get_child_bot(int(cid_s))
    if row:
        ok, msg = await child_manager.start_bot(row)
        await cb.answer(msg, show_alert=not ok)
    await render_adm_child_bot_detail(cb, int(cid_s), int(p_s))


@router.callback_query(F.data.startswith("acb:stop:"))
async def cb_acb_stop(cb: CallbackQuery):
    _, _, cid_s, p_s = cb.data.split(":")
    await child_manager.stop_bot(int(cid_s), mark_db_inactive=True)
    await cb.answer("⏹ Остановлен!")
    await render_adm_child_bot_detail(cb, int(cid_s), int(p_s))


@router.callback_query(F.data.startswith("acb:ban:"))
async def cb_acb_ban(cb: CallbackQuery):
    _, _, cid_s, p_s = cb.data.split(":")
    cid = int(cid_s)
    row = await db.get_child_bot(cid)
    if not row:
        return
    nxt = 0 if row["is_banned"] else 1
    if nxt == 1:
        await child_manager.stop_bot(cid, mark_db_inactive=True)
    await db.update_child_bot(cid, is_banned=nxt)
    await db.log_admin(cb.from_user.id, f"ChildBot #{cid} ban={nxt}")
    await cb.answer("🚫 Бот забанен!" if nxt else "✅ Бот разбанен!", show_alert=True)
    await render_adm_child_bot_detail(cb, cid, int(p_s))


@router.callback_query(F.data.startswith("acb:del:"))
async def cb_acb_del(cb: CallbackQuery):
    _, _, cid_s, p_s = cb.data.split(":")
    cid = int(cid_s)
    row = await db.get_child_bot(cid)
    await child_manager.stop_bot(cid, mark_db_inactive=False)
    await db.delete_child_bot(cid)
    await db.log_admin(cb.from_user.id, f"Удалил дочернего бота #{cid}")
    if row and MAIN_BOT:
        try:
            await MAIN_BOT.send_message(row["owner_id"], f"🗑 Ваш дочерний бот <b>@{esc(row['username'] or str(cid))}</b> был удалён администрацией.")
        except Exception:
            pass
    await cb.answer("🗑 Бот удалён!", show_alert=True)
    await render_adm_child_bots(cb, int(p_s))


# --- АДМИН: КАРТЫ И ВЫБОР СТАРТОВОГО ЮНИТА ---

async def render_adm_cards(target: Message | CallbackQuery, page: int = 0):
    cards = await db.list_cards()
    per = 6
    tp = max(1, (len(cards) + per - 1) // per)
    page = max(0, min(page, tp - 1))

    st_id = cfg_int("starter_card_id")
    st_card = await db.get_card(st_id) if st_id > 0 else None
    st_lbl = f"🎁 Стартовый юнит: {st_card['name']}" if st_card else "🎁 Стартовый юнит: Не выбран"

    rows = [
        [InlineKeyboardButton(text="➕ Создать карту", callback_data="ac:new")],
        [InlineKeyboardButton(text=st_lbl, callback_data="ast:list:0")],
    ]
    for c in cards[page * per : (page + 1) * per]:
        r_ico = get_rarity(c["rarity"])["emoji"]
        rows.append([InlineKeyboardButton(text=f"{r_ico} #{c['id']} {c['name']} ({c['class_type']} | ⚔️{c['atk']})", callback_data=f"ac:ed:{c['id']}:{page}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"adm:cards:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{tp}", callback_data="noop"))
    if page < tp - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"adm:cards:{page + 1}"))
    rows.extend([nav, [InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")]])
    await render_view(target, f"🃏 <b>КАРТЫ</b> (Всего: {len(cards)})", InlineKeyboardMarkup(inline_keyboard=rows))


async def render_adm_starter_picker(target: Message | CallbackQuery, page: int = 0):
    cards = await db.list_cards()
    st_id = cfg_int("starter_card_id")
    cur_c = await db.get_card(st_id) if st_id > 0 else None
    cur_txt = f"<b>{esc(cur_c['name'])}</b> (#{cur_c['id']})" if cur_c else "<i>Не выбран (0 карт на старте)</i>"

    per = 7
    tp = max(1, (len(cards) + per - 1) // per)
    page = max(0, min(page, tp - 1))

    txt = (
        f"🎁 <b>ВЫБОР СТАРТОВОГО ЮНИТА</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Сейчас выбран: {cur_txt}\n\n"
        f"<i>Этот юнит автоматически выдаётся новым игрокам при первом заходе (/start) и сразу надевается в Слот #1.</i>"
    )
    rows: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="❌ Без стартового юнита", callback_data="ast:set:0")]
    ]
    if cur_c:
        rows.append([InlineKeyboardButton(text="📨 Выдать его всем, у кого 0 карт", callback_data="ast:give_empty")])
    for c in cards[page * per : (page + 1) * per]:
        r_ico = get_rarity(c["rarity"])["emoji"]
        mark = "✅ " if c["id"] == st_id else ""
        rows.append([InlineKeyboardButton(text=f"{mark}{r_ico} #{c['id']} {c['name']} ({c['class_type']})", callback_data=f"ast:set:{c['id']}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"ast:list:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{tp}", callback_data="noop"))
    if page < tp - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"ast:list:{page + 1}"))
    rows.extend([nav, [InlineKeyboardButton(text="🔙 К картам", callback_data="adm:cards:0")]])
    await render_view(target, txt, InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("ast:list:"))
async def cb_ast_list(cb: CallbackQuery):
    if not await db.has_perm(cb.from_user.id, "manage_cards"):
        await cb.answer("Нет прав!", show_alert=True)
        return
    await render_adm_starter_picker(cb, int(cb.data.split(":")[2]))
    await cb.answer()


@router.callback_query(F.data.startswith("ast:set:"))
async def cb_ast_set(cb: CallbackQuery):
    if not await db.has_perm(cb.from_user.id, "manage_cards"):
        await cb.answer("Нет прав!", show_alert=True)
        return
    cid = int(cb.data.split(":")[2])
    await db.set_setting("starter_card_id", str(cid))
    if cid > 0:
        c = await db.get_card(cid)
        await db.log_admin(cb.from_user.id, f"Стартовый юнит: #{cid} {c['name'] if c else ''}")
        await cb.answer(f"✅ Стартовый юнит: {c['name'] if c else cid}!", show_alert=True)
    else:
        await db.log_admin(cb.from_user.id, "Сбросил стартового юнита")
        await cb.answer("❌ Стартовый юнит отключён.", show_alert=True)
    await render_adm_starter_picker(cb, 0)


@router.callback_query(F.data == "ast:give_empty")
async def cb_ast_give_empty(cb: CallbackQuery):
    if not await db.has_perm(cb.from_user.id, "manage_cards"):
        await cb.answer("Нет прав!", show_alert=True)
        return
    sid = cfg_int("starter_card_id")
    card = await db.get_card(sid) if sid > 0 else None
    if not card:
        await cb.answer("Стартовый юнит не выбран!", show_alert=True)
        return
    empty_uids = await db.get_users_without_cards()
    for uid in empty_uids:
        inv_id, _ = await db.give_card(uid, sid)
        await db.set_equip_slot(uid, inv_id, 1)
    await db.log_admin(cb.from_user.id, f"Выдал стартового юнита #{sid} {len(empty_uids)} игрокам без карт")
    await cb.answer(f"✅ Выдано «{card['name']}» игрокам без карт: {len(empty_uids)} чел.!", show_alert=True)


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
    await cb.message.answer("🃏 Введите <b>название</b> карты:")
    await cb.answer()


@router.message(CardFSM.name)
async def fsm_ac_name(m: Message, state: FSMContext):
    await state.update_data(name=(m.text or "").strip())
    await state.set_state(CardFSM.faction)
    await m.answer("🏷 Фракция:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=v, callback_data=f"acf:{k}")] for k, v in FACTIONS.items()]))


@router.callback_query(CardFSM.faction, F.data.startswith("acf:"))
async def fsm_ac_fac(cb: CallbackQuery, state: FSMContext):
    fac = cb.data.split(":")[1]
    await state.update_data(faction=fac, hide_from_ai=1 if fac in ("skibidi", "astro") else 0)
    await state.set_state(CardFSM.rarity)
    rars = sorted_rarities(reverse=False)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{r['emoji']} {r['name']} ({fmt_pct(r['infect_chance'])}%)", callback_data=f"acrar:{r['key']}")] for r in rars])
    await render_view(cb, "🌟 Rarity:", kb)
    await cb.answer()


@router.callback_query(CardFSM.rarity, F.data.startswith("acrar:"))
async def fsm_ac_rar(cb: CallbackQuery, state: FSMContext):
    await state.update_data(rarity=cb.data.split(":")[1])
    await state.set_state(CardFSM.cls)
    await render_view(cb, "⚔️ Class:", InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{ico} {k} — {desc}", callback_data=f"acc:{k}")] for k, (ico, desc) in CARD_CLASSES.items()]))
    await cb.answer()


@router.callback_query(CardFSM.cls, F.data.startswith("acc:"))
async def fsm_ac_cls(cb: CallbackQuery, state: FSMContext):
    cls = cb.data.split(":")[1]
    await state.update_data(class_type=cls)
    await state.set_state(CardFSM.stats)
    await cb.message.answer("❤️⚔️ Введите <b>HP</b> и <b>ATK</b> (или Heal для Healer) через пробел (напр. <code>300 75</code>):")
    await cb.answer()


@router.message(CardFSM.stats)
async def fsm_ac_stats(m: Message, state: FSMContext):
    p = (m.text or "").split()
    try:
        hp, atk = int(p[0]), int(p[1])
    except (ValueError, IndexError):
        await m.answer("❌ Пример: <code>300 75</code>")
        return
    await state.update_data(hp=hp, atk=atk)
    d = await state.get_data()
    if d["class_type"] == "Booster":
        await state.set_state(CardFSM.boost)
        await m.answer("✨ Введите множители <b>ATK</b> и <b>HP</b> баффа (напр. <code>1.25 1.15</code>):")
    else:
        await state.set_state(CardFSM.desc)
        await m.answer("📝 Введите описание (или <code>-</code>):")


@router.message(CardFSM.boost)
async def fsm_ac_boost(m: Message, state: FSMContext):
    p = (m.text or "").split()
    try:
        bd, bh = parse_float(p[0]), parse_float(p[1])
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
    await render_adm_card_editor(m, cid, 0)


async def render_adm_card_editor(target: Message | CallbackQuery, cid: int, page: int):
    c = await db.get_card(cid)
    if not c:
        await render_adm_cards(target, page)
        return
    fake = {**c, "level": 1, "xp": 0, "is_shiny": 0, "is_infected": 0, "serial_number": 0, "sign_type": "none", "signed_by": "", "equip_slot": 0}
    ai_st = "Скрыта от ИИ" if c["hide_from_ai"] else "Враг в боях ИИ"
    txt = f"🛠 <b>РЕДАКТОР КАРТЫ #{cid}</b> ({ai_st})\n" + format_card_info(fake)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Имя", callback_data=f"ac:f:{cid}:name:{page}"), InlineKeyboardButton(text="🖼 Фото", callback_data=f"ac:f:{cid}:photo_id:{page}")],
        [InlineKeyboardButton(text="❤️ HP", callback_data=f"ac:f:{cid}:hp:{page}"), InlineKeyboardButton(text="⚔️ ATK", callback_data=f"ac:f:{cid}:atk:{page}")],
        [InlineKeyboardButton(text="🌟 Rarity", callback_data=f"ac:f:{cid}:rarity:{page}"), InlineKeyboardButton(text="🎯 Class", callback_data=f"ac:f:{cid}:class_type:{page}")],
        [InlineKeyboardButton(text=f"🤖 ИИ: {ai_st}", callback_data=f"ac:ai:{cid}:{page}"), InlineKeyboardButton(text="🗑 Удалить", callback_data=f"ac:del:{cid}:{page}")],
        [InlineKeyboardButton(text="🔙 К картам", callback_data=f"adm:cards:{page}")],
    ])
    await render_view(target, txt, kb, photo=c.get("photo_id") or None)


@router.callback_query(F.data.startswith("ac:ed:"))
async def cb_ac_ed(cb: CallbackQuery):
    _, _, c, p = cb.data.split(":")
    await render_adm_card_editor(cb, int(c), int(p))
    await cb.answer()


@router.callback_query(F.data.startswith("ac:ai:"))
async def cb_ac_ai(cb: CallbackQuery):
    _, _, c, p = cb.data.split(":")
    card = await db.get_card(int(c))
    await db.update_card(int(c), hide_from_ai=0 if card["hide_from_ai"] else 1)
    await render_adm_card_editor(cb, int(c), int(p))
    await cb.answer("Переключено!")


@router.callback_query(F.data.startswith("ac:f:"))
async def cb_ac_f(cb: CallbackQuery, state: FSMContext):
    _, _, c, fld, p = cb.data.split(":")
    await state.set_state(CardFSM.edit_val)
    await state.update_data(cid=int(c), fld=fld, page=int(p))
    extra = (
        f" (доступны: {', '.join(RARITIES_CACHE.keys())})"
        if fld == "rarity"
        else (f" (доступны: {', '.join(CARD_CLASSES.keys())})" if fld == "class_type" else "")
    )
    await cb.message.answer(f"Введите новое значение для <b>{fld}</b>{extra}:")
    await cb.answer()


@router.message(CardFSM.edit_val)
async def fsm_ac_ed_val(m: Message, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    cid, fld, page = d["cid"], d["fld"], d["page"]
    try:
        if fld == "photo_id":
            val: Any = m.photo[-1].file_id if m.photo else ""
        elif fld in ("hp", "atk"):
            val = int((m.text or "").strip())
        elif fld == "rarity":
            val = (m.text or "").strip().lower()
            if val not in RARITIES_CACHE:
                raise ValueError
        elif fld == "class_type":
            val = (m.text or "").strip()
            if val not in CARD_CLASSES:
                raise ValueError
        else:
            val = (m.text or "").strip()
    except ValueError:
        await m.answer("❌ Неверное значение.")
        return
    await db.update_card(cid, **{fld: val})
    await render_adm_card_editor(m, cid, page)


@router.callback_query(F.data.startswith("ac:del:"))
async def cb_ac_del(cb: CallbackQuery):
    _, _, c, p = cb.data.split(":")
    await db.delete_card(int(c))
    await db.log_admin(cb.from_user.id, f"Удалил карту #{c}")
    await cb.answer("🗑 Удалено!", show_alert=True)
    await render_adm_cards(cb, int(p))


# --- АДМИН: КАСТОМНЫЕ ВАЛЮТЫ ---

async def render_adm_currencies(target: Message | CallbackQuery):
    curs = await db.list_currencies()
    rows = [[InlineKeyboardButton(text="➕ Создать валюту", callback_data="acu:new")]]
    for c in curs:
        dr = f"🟢 {fmt_pct(c['drop_chance'])}% ({c['drop_min']}-{c['drop_max']})" if c["drop_in_battles"] else "🔴 без дропа"
        rows.append([InlineKeyboardButton(text=f"🪙 {c['name']} | {dr}", callback_data=f"acu:ed:{c['id']}")])
    rows.append([InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")])
    await render_view(target, f"🪙 <b>КАСТОМНЫЕ ВАЛЮТЫ</b> ({len(curs)})\nМогут выпадать в боях и использоваться в крейтах.", InlineKeyboardMarkup(inline_keyboard=rows))


async def render_adm_currency_editor(target: Message | CallbackQuery, cid: int):
    c = await db.get_currency(cid)
    if not c:
        await render_adm_currencies(target)
        return
    txt = (
        f"🪙 <b>Валюта: {esc(c['name'])}</b> [ID: {cid}]\n"
        f"Дроп в боях: <b>{'🟢 ВКЛ' if c['drop_in_battles'] else '🔴 ВЫКЛ'}</b>\n"
        f"Шанс: <b>{fmt_pct(c['drop_chance'])}%</b> | Кол-во: <b>{c['drop_min']}–{c['drop_max']}</b>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{'🔴 Выкл дроп' if c['drop_in_battles'] else '🟢 Вкл дроп в боях'}", callback_data=f"acu:tgl:{cid}")],
        [InlineKeyboardButton(text="🎲 Настроить шанс и кол-во", callback_data=f"acu:cfg:{cid}")],
        [InlineKeyboardButton(text="🗑 Удалить валюту", callback_data=f"acu:del:{cid}")],
        [InlineKeyboardButton(text="🔙 К валютам", callback_data="adm:cur")],
    ])
    await render_view(target, txt, kb)


@router.callback_query(F.data == "adm:cur")
async def cb_adm_cur(cb: CallbackQuery):
    if not await db.has_perm(cb.from_user.id, "manage_currencies"):
        await cb.answer("Нет прав!", show_alert=True)
        return
    await render_adm_currencies(cb)
    await cb.answer()


@router.callback_query(F.data == "acu:new")
async def cb_acu_new(cb: CallbackQuery, state: FSMContext):
    await state.set_state(CurFSM.name)
    await cb.message.answer("🪙 Введите название новой валюты (напр. <code>💎 Кристаллы</code> или <code>⚡ Астро-Энергия</code>):")
    await cb.answer()


@router.message(CurFSM.name)
async def fsm_acu_name(m: Message, state: FSMContext):
    await state.clear()
    try:
        cid = await db.create_currency((m.text or "").strip())
        await db.log_admin(m.from_user.id, f"Создал валюту #{cid} {m.text}")
        await m.answer(f"✅ Валюта <b>{esc(m.text)}</b> создана!")
        await render_adm_currencies(m)
    except Exception:
        await m.answer("❌ Такая валюта уже существует.")


@router.callback_query(F.data.startswith("acu:ed:"))
async def cb_acu_ed(cb: CallbackQuery):
    await render_adm_currency_editor(cb, int(cb.data.split(":")[2]))
    await cb.answer()


@router.callback_query(F.data.startswith("acu:tgl:"))
async def cb_acu_tgl(cb: CallbackQuery):
    cid = int(cb.data.split(":")[2])
    c = await db.get_currency(cid)
    if not c:
        await cb.answer("Валюта не найдена.", show_alert=True)
        return
    new_val = 0 if c["drop_in_battles"] else 1
    await db.update_currency(cid, drop_in_battles=new_val)
    await render_adm_currency_editor(cb, cid)
    await cb.answer("🟢 Дроп в боях ВКЛЮЧЁН!" if new_val else "🔴 Дроп в боях ВЫКЛЮЧЕН!")


@router.callback_query(F.data.startswith("acu:cfg:"))
async def cb_acu_cfg(cb: CallbackQuery, state: FSMContext):
    await state.set_state(CurFSM.drop_cfg)
    await state.update_data(cid=int(cb.data.split(":")[2]))
    await cb.message.answer("🎲 Введите через пробел: <code>шанс% мин макс</code> (пример: <code>2.5% 1 5</code> или <code>0.125 1 3</code>):")
    await cb.answer()


@router.message(CurFSM.drop_cfg)
async def fsm_acu_cfg(m: Message, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    p = (m.text or "").split()
    try:
        ch, mn, mx = parse_float(p[0]), int(p[1]), int(p[2])
        if not (0.0 <= ch <= 100.0) or mn < 1 or mx < mn:
            raise ValueError
    except (ValueError, IndexError):
        await m.answer("❌ Пример: <code>2.5% 1 5</code> или <code>0.125 1 3</code>")
        return
    await db.update_currency(d["cid"], drop_chance=ch, drop_min=mn, drop_max=mx, drop_in_battles=1)
    await m.answer("✅ Параметры дропа сохранены!")
    await render_adm_currency_editor(m, d["cid"])


@router.callback_query(F.data.startswith("acu:del:"))
async def cb_acu_del(cb: CallbackQuery):
    await db.delete_currency(int(cb.data.split(":")[2]))
    await cb.answer("🗑 Удалено!", show_alert=True)
    await render_adm_currencies(cb)


# --- АДМИН: КРЕЙТЫ (СОЗДАНИЕ + ПОЛНЫЙ РЕДАКТОР СОЗДАННЫХ КРЕЙТОВ И ШАНСОВ) ---

async def render_adm_crates(target: Message | CallbackQuery):
    crates = await db.list_crates()
    curs = {c["id"]: c["name"] for c in await db.list_currencies()}
    rows = [[InlineKeyboardButton(text="➕ Создать Крейт", callback_data="acr:new")]]
    for c in crates:
        cn = "💰" if c["currency_id"] == 0 else curs.get(c["currency_id"], "💰")
        rows.append([InlineKeyboardButton(text=f"{'🟢' if c['active'] else '🔴'} {c['name']} ({c['price']} {cn})", callback_data=f"acr:ed:{c['id']}")])
    rows.append([InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")])
    await render_view(target, f"📦 <b>КРЕЙТЫ</b> ({len(crates)})", InlineKeyboardMarkup(inline_keyboard=rows))


async def render_adm_crate_editor(target: Message | CallbackQuery, cid: int):
    c = await db.get_crate(cid)
    if not c:
        await render_adm_crates(target)
        return
    cur_obj = await db.get_currency(c["currency_id"]) if c["currency_id"] else None
    cur_name = cur_obj["name"] if cur_obj else "💰 Монеты"
    all_c = {str(x["id"]): x for x in await db.list_cards()}
    cmap = c["cards"]
    tot_w = sum(float(v) for v in cmap.values() if float(v) > 0)

    lines = [
        f"📦 <b>РЕДАКТОР КРЕЙТА #{cid}: {esc(c['name'])}</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"• Статус: <b>{'🟢 Активен' if c['active'] else '🔴 Выключен'}</b>",
        f"• Цена: <b>{c['price']} {esc(cur_name)}</b>",
        f"• Описание: <i>{esc(c['description'] or '—')}</i>",
        f"• Фото: <b>{'Есть' if c.get('photo_id') else 'Нет'}</b>",
        "",
        "🎲 <b>Карты и шансы в крейте:</b>",
    ]
    if not cmap or tot_w <= 0:
        lines.append("<i>Пусто — добавьте карты!</i>")
    else:
        for k, w in sorted(cmap.items(), key=lambda kv: float(kv[1]), reverse=True):
            co = all_c.get(str(k))
            cname = co["name"] if co else f"#{k}"
            r_ico = get_rarity(co["rarity"])["emoji"] if co else "❓"
            pct = (float(w) / tot_w) * 100.0
            lines.append(f"• {r_ico} <b>{esc(cname)}</b> — вес <b>{fmt_pct(w)}</b> ({fmt_pct(pct)}%)")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Название", callback_data=f"acre:f:{cid}:name"), InlineKeyboardButton(text="📝 Описание", callback_data=f"acre:f:{cid}:description")],
        [InlineKeyboardButton(text="💵 Цена", callback_data=f"acre:f:{cid}:price"), InlineKeyboardButton(text="🪙 Валюта", callback_data=f"acre:cur:{cid}")],
        [InlineKeyboardButton(text="🖼 Фото", callback_data=f"acre:f:{cid}:photo_id"), InlineKeyboardButton(text="🎲 Карты и шансы", callback_data=f"acre:cards:{cid}:0")],
        [InlineKeyboardButton(text="🔴 Выключить" if c["active"] else "🟢 Включить", callback_data=f"acr:tgl:{cid}"), InlineKeyboardButton(text="🗑 Удалить", callback_data=f"acr:del:{cid}")],
        [InlineKeyboardButton(text="🔙 К крейтам", callback_data="adm:cr")],
    ])
    await render_view(target, "\n".join(lines), kb, photo=c.get("photo_id") or None)


async def render_adm_crate_cards(target: Message | CallbackQuery, cid: int, page: int = 0):
    c = await db.get_crate(cid)
    if not c:
        await render_adm_crates(target)
        return
    all_c = {str(x["id"]): x for x in await db.list_cards()}
    items = sorted(c["cards"].items(), key=lambda kv: float(kv[1]), reverse=True)
    tot_w = sum(float(v) for _, v in items if float(v) > 0)

    per = 7
    tp = max(1, (len(items) + per - 1) // per)
    page = max(0, min(page, tp - 1))

    txt = (
        f"🎲 <b>КАРТЫ И ШАНСЫ: «{esc(c['name'])}»</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Нажмите на карту, чтобы изменить её вес/шанс (введите <code>0</code>, чтобы убрать из крейта):"
    )
    rows: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="➕ Добавить карту в крейт", callback_data=f"acre:cadd:{cid}:0")]
    ]
    for k, w in items[page * per : (page + 1) * per]:
        co = all_c.get(str(k))
        cname = co["name"] if co else f"#{k}"
        r_ico = get_rarity(co["rarity"])["emoji"] if co else "❓"
        pct = (float(w) / tot_w * 100.0) if tot_w > 0 else 0.0
        rows.append([
            InlineKeyboardButton(text=f"{r_ico} {cname[:14]} | {fmt_pct(w)} ({fmt_pct(pct)}%)", callback_data=f"acre:cw:{cid}:{k}"),
            InlineKeyboardButton(text="🗑", callback_data=f"acre:cdel:{cid}:{k}:{page}"),
        ])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"acre:cards:{cid}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{tp}", callback_data="noop"))
    if page < tp - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"acre:cards:{cid}:{page + 1}"))
    rows.extend([nav, [InlineKeyboardButton(text="🔙 К крейту", callback_data=f"acr:ed:{cid}")]])
    await render_view(target, txt, InlineKeyboardMarkup(inline_keyboard=rows))


async def render_adm_crate_add_card(target: Message | CallbackQuery, cid: int, page: int = 0):
    c = await db.get_crate(cid)
    if not c:
        return
    cards = await db.list_cards()
    per = 10
    tp = max(1, (len(cards) + per - 1) // per)
    page = max(0, min(page, tp - 1))

    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for card in cards[page * per : (page + 1) * per]:
        mark = "✅ " if str(card["id"]) in c["cards"] else ""
        r_ico = get_rarity(card["rarity"])["emoji"]
        row.append(InlineKeyboardButton(text=f"{mark}{r_ico}{card['name'][:12]}", callback_data=f"acre:cw:{cid}:{card['id']}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"acre:cadd:{cid}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{tp}", callback_data="noop"))
    if page < tp - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"acre:cadd:{cid}:{page + 1}"))
    rows.extend([nav, [InlineKeyboardButton(text="🔙 К составу", callback_data=f"acre:cards:{cid}:0")]])
    await render_view(target, f"➕ <b>Выберите карту для добавления в «{esc(c['name'])}»</b>:", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "adm:cr")
async def cb_adm_cr(cb: CallbackQuery):
    if not await db.has_perm(cb.from_user.id, "manage_crates"):
        await cb.answer("Нет прав!", show_alert=True)
        return
    await render_adm_crates(cb)
    await cb.answer()


@router.callback_query(F.data == "acr:new")
async def cb_acr_new(cb: CallbackQuery, state: FSMContext):
    if not await db.list_cards():
        await cb.answer("Сначала создайте хотя бы 1 карту!", show_alert=True)
        return
    await state.set_state(CrateFSM.name)
    await state.update_data(cards={})
    await cb.message.answer("📦 Введите <b>название</b> крейта:")
    await cb.answer()


@router.message(CrateFSM.name)
async def fsm_acr_name(m: Message, state: FSMContext):
    await state.update_data(name=(m.text or "").strip())
    await state.set_state(CrateFSM.curr)
    curs = await db.list_currencies()
    rows = [[InlineKeyboardButton(text="💰 Монеты (базовая)", callback_data="acrc:0")]]
    for c in curs:
        rows.append([InlineKeyboardButton(text=c["name"], callback_data=f"acrc:{c['id']}")])
    await m.answer("🪙 Выберите валюту покупки крейта:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(CrateFSM.curr, F.data.startswith("acrc:"))
async def fsm_acr_cur(cb: CallbackQuery, state: FSMContext):
    await state.update_data(currency_id=int(cb.data.split(":")[1]))
    await state.set_state(CrateFSM.price)
    await cb.message.answer("💵 Введите <code>цена | описание</code> (напр. <code>500 | Топовый кейс</code>):")
    await cb.answer()


@router.message(CrateFSM.price)
async def fsm_acr_price(m: Message, state: FSMContext):
    p = (m.text or "").split("|", 1)
    try:
        pr = int(p[0].strip())
    except ValueError:
        await m.answer("❌ Пример: <code>500 | Описание</code>")
        return
    await state.update_data(price=pr, desc=p[1].strip() if len(p) > 1 else "")
    await state.set_state(CrateFSM.photo)
    await m.answer("🖼 Отправьте фото крейта (или <code>-</code>):")


@router.message(CrateFSM.photo)
async def fsm_acr_photo(m: Message, state: FSMContext):
    await state.update_data(photo_id=m.photo[-1].file_id if m.photo else "")
    await _show_cr_builder(m, state)


async def _show_cr_builder(target: Message | CallbackQuery, state: FSMContext):
    d = await state.get_data()
    cmap = d.get("cards", {})
    all_c = await db.list_cards()
    by_id = {str(x["id"]): x for x in all_c}
    lines = [f"📦 <b>Состав «{esc(d['name'])}»</b>:"] + [
        f"• {esc(by_id[k]['name']) if k in by_id else k} — вес/шанс <b>{fmt_pct(w)}</b>"
        for k, w in cmap.items()
    ]
    rows, row = [], []
    for c in all_c[:24]:
        row.append(InlineKeyboardButton(text=c["name"][:14], callback_data=f"acrb:c:{c['id']}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if cmap:
        rows.append([InlineKeyboardButton(text="💾 Сохранить Крейт", callback_data="acrb:save")])
    await state.set_state(CrateFSM.builder)
    await render_view(target, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(CrateFSM.builder, F.data.startswith("acrb:c:"))
async def cb_acrb_c(cb: CallbackQuery, state: FSMContext):
    await state.update_data(sel_c=cb.data.split(":")[2])
    await state.set_state(CrateFSM.weight)
    await cb.message.answer("⚖️ Введите вес / шанс выпадения (можно дробное, напр. <code>20</code>, <code>2.5%</code>, <code>0.125%</code>):")
    await cb.answer()


@router.message(CrateFSM.weight)
async def fsm_acrb_w(m: Message, state: FSMContext):
    try:
        w = parse_float(m.text)
        if w <= 0:
            raise ValueError
    except ValueError:
        await m.answer("❌ Введите положительное число (напр. <code>2.5%</code> или <code>0.125</code>).")
        return
    d = await state.get_data()
    cm = dict(d.get("cards", {}))
    cm[d["sel_c"]] = w
    await state.update_data(cards=cm)
    await _show_cr_builder(m, state)


@router.callback_query(CrateFSM.builder, F.data == "acrb:save")
async def cb_acrb_save(cb: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    cid = await db.create_crate(d["name"], d["desc"], d["currency_id"], d["price"], d["cards"], d["photo_id"])
    await db.log_admin(cb.from_user.id, f"Создал крейт #{cid} {d['name']}")
    await state.clear()
    await cb.answer("✅ Крейт создан!", show_alert=True)
    await render_adm_crate_editor(cb, cid)


@router.callback_query(F.data.startswith("acr:ed:"))
async def cb_acr_ed(cb: CallbackQuery):
    await render_adm_crate_editor(cb, int(cb.data.split(":")[2]))
    await cb.answer()


@router.callback_query(F.data.startswith("acr:tgl:"))
async def cb_acr_tgl(cb: CallbackQuery):
    cid = int(cb.data.split(":")[2])
    c = await db.get_crate(cid)
    if c:
        await db.update_crate(cid, active=0 if c["active"] else 1)
    await render_adm_crate_editor(cb, cid)
    await cb.answer("Статус изменён!")


@router.callback_query(F.data.startswith("acr:del:"))
async def cb_acr_del(cb: CallbackQuery):
    cid = int(cb.data.split(":")[2])
    await db.delete_crate(cid)
    await db.log_admin(cb.from_user.id, f"Удалил крейт #{cid}")
    await cb.answer("🗑 Крейт удалён!", show_alert=True)
    await render_adm_crates(cb)


@router.callback_query(F.data.startswith("acre:f:"))
async def cb_acre_f(cb: CallbackQuery, state: FSMContext):
    _, _, cid_s, fld = cb.data.split(":")
    await state.set_state(CrateFSM.edit_field)
    await state.update_data(cid=int(cid_s), fld=fld)
    hint = "Отправьте новое фото крейта (или <code>-</code> чтобы убрать):" if fld == "photo_id" else f"Введите новое значение для <b>{fld}</b>:"
    await cb.message.answer(hint)
    await cb.answer()


@router.message(CrateFSM.edit_field)
async def fsm_acre_f_save(m: Message, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    cid, fld = d["cid"], d["fld"]
    try:
        if fld == "photo_id":
            val: Any = m.photo[-1].file_id if m.photo else ""
        elif fld == "price":
            val = max(1, int((m.text or "").strip()))
        else:
            t = (m.text or "").strip()
            val = "" if (fld == "description" and t == "-") else t
    except ValueError:
        await m.answer("❌ Неверный формат значения.")
        return
    await db.update_crate(cid, **{fld: val})
    await db.log_admin(m.from_user.id, f"Изменил крейт #{cid}: {fld}")
    await m.answer("✅ Крейт обновлён!")
    await render_adm_crate_editor(m, cid)


@router.callback_query(F.data.startswith("acre:cur:"))
async def cb_acre_cur(cb: CallbackQuery):
    cid = int(cb.data.split(":")[2])
    curs = await db.list_currencies()
    rows = [[InlineKeyboardButton(text="💰 Монеты (базовая)", callback_data=f"acre:setcur:{cid}:0")]]
    for cur in curs:
        rows.append([InlineKeyboardButton(text=cur["name"], callback_data=f"acre:setcur:{cid}:{cur['id']}")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"acr:ed:{cid}")])
    await render_view(cb, "🪙 Выберите новую валюту покупки для крейта:", InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer()


@router.callback_query(F.data.startswith("acre:setcur:"))
async def cb_acre_setcur(cb: CallbackQuery):
    _, _, cid_s, cur_s = cb.data.split(":")
    cid = int(cid_s)
    await db.update_crate(cid, currency_id=int(cur_s))
    await cb.answer("✅ Валюта изменена!")
    await render_adm_crate_editor(cb, cid)


@router.callback_query(F.data.startswith("acre:cards:"))
async def cb_acre_cards(cb: CallbackQuery):
    _, _, cid_s, p_s = cb.data.split(":")
    await render_adm_crate_cards(cb, int(cid_s), int(p_s))
    await cb.answer()


@router.callback_query(F.data.startswith("acre:cadd:"))
async def cb_acre_cadd(cb: CallbackQuery):
    _, _, cid_s, p_s = cb.data.split(":")
    await render_adm_crate_add_card(cb, int(cid_s), int(p_s))
    await cb.answer()


@router.callback_query(F.data.startswith("acre:cw:"))
async def cb_acre_cw(cb: CallbackQuery, state: FSMContext):
    _, _, cid_s, card_s = cb.data.split(":")
    card = await db.get_card(int(card_s))
    cname = card["name"] if card else f"#{card_s}"
    await state.set_state(CrateFSM.edit_weight)
    await state.update_data(cid=int(cid_s), card_id=str(card_s))
    await cb.message.answer(
        f"⚖️ Введите новый вес / шанс для <b>{esc(cname)}</b>\n"
        f"(можно дробное: <code>2.5%</code>, <code>0.125</code>, или <code>0</code> чтобы убрать из крейта):"
    )
    await cb.answer()


@router.message(CrateFSM.edit_weight)
async def fsm_acre_cw_save(m: Message, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    cid, card_s = d["cid"], d["card_id"]
    try:
        w = parse_float(m.text)
        if w < 0:
            raise ValueError
    except ValueError:
        await m.answer("❌ Введите число >= 0 (напр. <code>2.5%</code>, <code>0.125</code> или <code>0</code>).")
        return
    c = await db.get_crate(cid)
    if not c:
        await m.answer("❌ Крейт не найден.")
        return
    cmap = dict(c["cards"])
    if w == 0:
        cmap.pop(card_s, None)
        note = "🗑 Карта убрана из крейта!"
    else:
        cmap[card_s] = w
        note = f"✅ Вес/шанс обновлён на <b>{fmt_pct(w)}</b>!"
    await db.update_crate(cid, cards=cmap)
    await db.log_admin(m.from_user.id, f"Изменил состав крейта #{cid} (карта #{card_s} -> {w})")
    await m.answer(note)
    await render_adm_crate_cards(m, cid, 0)


@router.callback_query(F.data.startswith("acre:cdel:"))
async def cb_acre_cdel(cb: CallbackQuery):
    _, _, cid_s, card_s, p_s = cb.data.split(":")
    cid = int(cid_s)
    c = await db.get_crate(cid)
    if c:
        cmap = dict(c["cards"])
        cmap.pop(card_s, None)
        await db.update_crate(cid, cards=cmap)
    await cb.answer("🗑 Карта убрана из крейта!")
    await render_adm_crate_cards(cb, cid, int(p_s))


# --- АДМИН: ИВЕНТЫ (УДАЧА И МОНЕТЫ С РАССЫЛКОЙ) ---

async def render_adm_events(target: Message | CallbackQuery):
    lm, ls, cm, cs = get_active_events()
    txt = (
        f"🎉 <b>УПРАВЛЕНИЕ ИВЕНТАМИ</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"🍀 Ивент Удачи: <b>x{lm}</b> ({ls // 60} мин. ост.)\n"
        f"💰 Ивент Монет: <b>x{cm}</b> ({cs // 60} мин. ост.)\n\n"
        f"При запуске ивента бот автоматически оповестит всех игроков!"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍀 Запустить Ивент Удачи", callback_data="aev:luck"), InlineKeyboardButton(text="💰 Запустить Ивент Монет", callback_data="aev:coin")],
        [InlineKeyboardButton(text="🛑 Остановить все ивенты", callback_data="aev:stop")],
        [InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")],
    ])
    await render_view(target, txt, kb)


@router.callback_query(F.data == "adm:ev")
async def cb_adm_ev(cb: CallbackQuery):
    if not await db.has_perm(cb.from_user.id, "manage_events"):
        await cb.answer("Нет прав!", show_alert=True)
        return
    await render_adm_events(cb)
    await cb.answer()


@router.callback_query(F.data == "aev:stop")
async def cb_aev_stop(cb: CallbackQuery):
    await db.set_setting("luck_event_end", "0")
    await db.set_setting("coin_event_end", "0")
    await cb.answer("🛑 Ивенты остановлены!", show_alert=True)
    await render_adm_events(cb)


@router.callback_query(F.data.in_({"aev:luck", "aev:coin"}))
async def cb_aev_start(cb: CallbackQuery, state: FSMContext):
    ev_type = cb.data.split(":")[1]
    await state.set_state(AdminFSM.ev_cfg)
    await state.update_data(ev_type=ev_type)
    await cb.message.answer("🎉 Введите <code>множитель минуты</code> через пробел (напр. <code>2.5 60</code> — x2.5 на 60 минут):")
    await cb.answer()


@router.message(AdminFSM.ev_cfg)
async def fsm_aev_save(m: Message, state: FSMContext, bot: Bot):
    d = await state.get_data()
    await state.clear()
    p = (m.text or "").split()
    try:
        mult, mins = parse_float(p[0]), int(p[1])
        if mult < 1.0 or mins <= 0:
            raise ValueError
    except (ValueError, IndexError):
        await m.answer("❌ Пример: <code>2.5 60</code>")
        return
    end_ts = str(int(time.time()) + mins * 60)
    if d["ev_type"] == "luck":
        await db.set_setting("luck_event_mult", str(mult))
        await db.set_setting("luck_event_end", end_ts)
        ann = f"🍀 <b>ГЛОБАЛЬНЫЙ ИВЕНТ УДАЧИ x{mult}!</b>\nШансы на редкие карты, ✨ Shiny и заражение увеличены на <b>{mins} мин.</b>!"
    else:
        await db.set_setting("coin_event_mult", str(mult))
        await db.set_setting("coin_event_end", end_ts)
        ann = f"💰 <b>ГЛОБАЛЬНЫЙ ИВЕНТ МОНЕТ x{mult}!</b>\nВсе награды монетами увеличены на <b>{mins} мин.</b>!"
    await db.log_admin(m.from_user.id, f"Запустил ивент {d['ev_type']} x{mult} на {mins}м")
    await m.answer("✅ Ивент запущен! Рассылаю уведомление...")
    for uid in await db.get_active_uids():
        try:
            await bot.send_message(uid, ann)
            await asyncio.sleep(0.03)
        except Exception:
            pass


# --- АДМИН: НАСТРОЙКИ БАЛАНСА, МИРОВОЙ БОСС, ИГРОКИ, РАССЫЛКА, ПРАВА, БД ---

async def render_adm_settings(target: Message | CallbackQuery, page: int = 0):
    keys = list(SETTING_META.keys())
    per = 6
    tp = max(1, (len(keys) + per - 1) // per)
    page = max(0, min(page, tp - 1))
    rows = [[InlineKeyboardButton(text=f"{SETTING_META[k][0]}: {GAME_SETTINGS.get(k)}", callback_data=f"aset:{k}:{page}")] for k in keys[page * per : (page + 1) * per]]
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
    await render_adm_settings(cb, int(cb.data.split(":")[2]))
    await cb.answer()


@router.callback_query(F.data.startswith("aset:"))
async def cb_aset(cb: CallbackQuery, state: FSMContext):
    _, k, p = cb.data.split(":")
    title, vt, mn, mx = SETTING_META[k]
    await state.set_state(AdminFSM.set_val)
    await state.update_data(k=k, p=int(p))
    await cb.message.answer(f"🎛 <b>{title}</b>\nТекущее: <code>{GAME_SETTINGS.get(k)}</code>\nВведите новое ({vt}, {mn}..{mx}, можно с дробной частью и %):")
    await cb.answer()


@router.message(AdminFSM.set_val)
async def fsm_aset(m: Message, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    k, p = d["k"], d["p"]
    _, vt, mn, mx = SETTING_META[k]
    try:
        num = int(parse_float(m.text)) if vt == "int" else parse_float(m.text)
        if not (mn <= num <= mx):
            raise ValueError
    except ValueError:
        await m.answer(f"❌ Введите число от {mn} до {mx} (можно с точкой/запятой и %).")
        return
    await db.set_setting(k, str(num))
    await render_adm_settings(m, p)


@router.callback_query(F.data == "adm:wb")
async def cb_adm_wb(cb: CallbackQuery):
    if not await db.has_perm(cb.from_user.id, "manage_bosses"):
        await cb.answer("Нет прав!", show_alert=True)
        return
    wb = await db.get_world_boss()
    cards = sorted(await db.list_cards(), key=lambda c: get_rarity(c["rarity"])["weight"], reverse=True)[:10]
    rows = []
    if wb:
        rows.append([InlineKeyboardButton(text="🛑 Остановить Босса", callback_data="awb:stop")])
    for c in cards:
        rows.append([InlineKeyboardButton(text=f"🌍 Запустить: {c['name']}", callback_data=f"awb:sp:{c['id']}")])
    rows.append([InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")])
    st = f"Активен: <b>{esc(wb['name'])}</b> ({wb['current_hp']}/{wb['max_hp']} HP)" if wb else "Нет активного."
    await render_view(cb, f"🌍 <b>МИРОВОЙ БОСС</b>\n{st}", InlineKeyboardMarkup(inline_keyboard=rows))
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
    await cb.message.answer("❤️ Введите HP Мирового Босса (напр. <code>25000</code>):")
    await cb.answer()


@router.message(AdminFSM.wb_hp)
async def fsm_awb_hp(m: Message, state: FSMContext, bot: Bot):
    d = await state.get_data()
    await state.clear()
    try:
        hp = max(100, int((m.text or "").strip()))
    except ValueError:
        await m.answer("❌ Введите число.")
        return
    c = await db.get_card(d["cid"])
    await db.spawn_world_boss(c["id"], hp)
    await m.answer(f"🌍 Мировой Босс <b>{esc(c['name'])}</b> ({hp} HP) запущен!")
    for uid in await db.get_active_uids():
        try:
            await bot.send_message(uid, f"🚨🌍 <b>ПОЯВИЛСЯ МИРОВОЙ БОСС: {esc(c['name'])}!</b>\n❤️ HP: <b>{hp}</b>\nЗаходи в «🌐 Мультиплеер → 🌍 Мировой Босс»!")
        except Exception:
            pass


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
        await m.answer("❌ Не найден.")
        return
    await render_adm_user_card(m, u["user_id"])


async def render_adm_user_card(target: Message | CallbackQuery, t_uid: int):
    u = await db.get_user(t_uid)
    txt = await build_profile_text(u, False) + f"\n\n🚫 Бан: <b>{'ДА' if u['is_banned'] else 'НЕТ'}</b>"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 +/- Монеты", callback_data=f"au:c:{t_uid}"), InlineKeyboardButton(text="🪙 Выдать валюту", callback_data=f"au:cur:{t_uid}")],
        [InlineKeyboardButton(text="🦠 +5 Обыч.", callback_data=f"au:p:common:{t_uid}"), InlineKeyboardButton(text="💎 +5 Элит.", callback_data=f"au:p:elite:{t_uid}")],
        [InlineKeyboardButton(text="🎁 Выдать Карту", callback_data=f"au:gc:{t_uid}"), InlineKeyboardButton(text="✅ Разбан" if u["is_banned"] else "🚫 Бан", callback_data=f"au:ban:{t_uid}")],
        [InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")],
    ])
    await render_view(target, txt, kb)


@router.callback_query(F.data.startswith("au:c:"))
async def cb_auc(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFSM.u_coins)
    await state.update_data(t=int(cb.data.split(":")[2]))
    await cb.message.answer("💰 Введите сумму монет (отрицательное — списать):")
    await cb.answer()


@router.message(AdminFSM.u_coins)
async def fsm_auc(m: Message, state: FSMContext):
    t = (await state.get_data())["t"]
    await state.clear()
    try:
        d = int((m.text or "").strip())
    except ValueError:
        await m.answer("❌ Число.")
        return
    await db.add_coins(t, d)
    await render_adm_user_card(m, t)


@router.callback_query(F.data.startswith("au:cur:"))
async def cb_au_cur(cb: CallbackQuery):
    t = int(cb.data.split(":")[2])
    curs = await db.list_currencies()
    if not curs:
        await cb.answer("Сначала создайте кастомную валюту!", show_alert=True)
        return
    rows = [[InlineKeyboardButton(text=c["name"], callback_data=f"au:cs:{t}:{c['id']}")] for c in curs]
    await render_view(cb, "Выберите валюту для выдачи:", InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer()


@router.callback_query(F.data.startswith("au:cs:"))
async def cb_au_cs(cb: CallbackQuery, state: FSMContext):
    _, _, t, cid = cb.data.split(":")
    await state.set_state(CurFSM.give_amt)
    await state.update_data(t=int(t), cid=int(cid))
    await cb.message.answer("🔢 Сколько выдать?")
    await cb.answer()


@router.message(CurFSM.give_amt)
async def fsm_au_cs(m: Message, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    try:
        amt = int((m.text or "").strip())
    except ValueError:
        await m.answer("❌ Число.")
        return
    await db.add_user_currency(d["t"], d["cid"], amt)
    await render_adm_user_card(m, d["t"])


@router.callback_query(F.data.startswith("au:p:"))
async def cb_aup(cb: CallbackQuery):
    _, _, pk, t = cb.data.split(":")
    await db.add_parasite(int(t), pk, 5)
    await cb.answer("✅ +5 паразитов!", show_alert=True)
    await render_adm_user_card(cb, int(t))


@router.callback_query(F.data.startswith("au:ban:"))
async def cb_auban(cb: CallbackQuery):
    t = int(cb.data.split(":")[2])
    if t == OWNER_ID:
        await cb.answer("Нельзя забанить владельца!", show_alert=True)
        return
    u = await db.get_user(t)
    await db.update_user(t, is_banned=0 if u["is_banned"] else 1)
    await render_adm_user_card(cb, t)
    await cb.answer("Готово!")


@router.callback_query(F.data.startswith("au:gc:"))
async def cb_augc(cb: CallbackQuery):
    t = int(cb.data.split(":")[2])
    cards = await db.list_cards()
    if not cards:
        await cb.answer("В базе нет карт!", show_alert=True)
        return
    rows = [[InlineKeyboardButton(text=f"#{c['id']} {c['name']}", callback_data=f"au:gdo:{t}:{c['id']}")] for c in cards[:24]]
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="adm:home")])
    await render_view(cb, f"🎁 Выдать карту игроку <code>{t}</code>:", InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer()


@router.callback_query(F.data.startswith("au:gdo:"))
async def cb_augdo(cb: CallbackQuery):
    _, _, t, cid = cb.data.split(":")
    _, sn = await db.give_card(int(t), int(cid))
    await cb.answer(f"✅ Выдано!{f' [#{sn:04d}]' if sn else ''}", show_alert=True)
    await render_adm_user_card(cb, int(t))


@router.callback_query(F.data == "adm:bcast")
async def cb_bcast(cb: CallbackQuery, state: FSMContext):
    if not await db.has_perm(cb.from_user.id, "broadcast"):
        await cb.answer("Нет прав!", show_alert=True)
        return
    await state.set_state(AdminFSM.bcast)
    await cb.message.answer("📢 Отправьте сообщение для рассылки всем игрокам:")
    await cb.answer()


@router.message(AdminFSM.bcast)
async def fsm_bcast(m: Message, state: FSMContext):
    await state.clear()
    uids = await db.get_active_uids()
    ok = 0
    for uid in uids:
        try:
            await m.send_copy(uid)
            ok += 1
            await asyncio.sleep(0.04)
        except Exception:
            pass
    await m.answer(f"✅ Доставлено: <b>{ok}/{len(uids)}</b>")


async def render_admins(target: Message | CallbackQuery):
    adms = await db.list_admins()
    rows = [[InlineKeyboardButton(text="➕ Добавить админа", callback_data="aa:add")]]
    for a in adms:
        rows.append([InlineKeyboardButton(text=f"👮 {a['full_name'] or a['user_id']} ({a['user_id']})", callback_data=f"aa:ed:{a['user_id']}")])
    rows.append([InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")])
    await render_view(target, f"👮 <b>АДМИНЫ</b> (Владелец: <code>{OWNER_ID}</code>)", InlineKeyboardMarkup(inline_keyboard=rows))


async def render_adm_perms(target: Message | CallbackQuery, tid: int):
    p = await db.get_admin_perms(tid)
    rows = [[InlineKeyboardButton(text=f"{'✅' if p.get(k) else '❌'} {lbl}", callback_data=f"aa:t:{tid}:{k}")] for k, lbl in ADMIN_PERMS.items()]
    rows.extend([[InlineKeyboardButton(text="🗑 Снять админа", callback_data=f"aa:d:{tid}")], [InlineKeyboardButton(text="🔙 К списку", callback_data="adm:admins")]])
    await render_view(target, f"👮 <b>Права <code>{tid}</code></b>:", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "adm:admins")
async def cb_admins(cb: CallbackQuery):
    if not await db.has_perm(cb.from_user.id, "manage_admins"):
        await cb.answer("Нет прав!", show_alert=True)
        return
    await render_admins(cb)
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


@router.callback_query(F.data.startswith("aa:ed:"))
async def cb_aa_ed(cb: CallbackQuery):
    await render_adm_perms(cb, int(cb.data.split(":")[2]))
    await cb.answer()


@router.callback_query(F.data.startswith("aa:t:"))
async def cb_aa_t(cb: CallbackQuery):
    _, _, t, k = cb.data.split(":")
    await db.toggle_admin_perm(int(t), k)
    await render_adm_perms(cb, int(t))
    await cb.answer("Обновлено!")


@router.callback_query(F.data.startswith("aa:d:"))
async def cb_aa_d(cb: CallbackQuery):
    await db.remove_admin(int(cb.data.split(":")[2]))
    await cb.answer("🗑 Снят!", show_alert=True)
    await render_admins(cb)


@router.callback_query(F.data == "adm:sgn")
async def cb_adm_sgn(cb: CallbackQuery):
    if not await db.has_perm(cb.from_user.id, "manage_admins"):
        await cb.answer("Нет прав!", show_alert=True)
        return
    sgns = await db.list_signers()
    rows = [[InlineKeyboardButton(text="➕ Добавить Партнёра (+5% ATK/HP)", callback_data="asg:add")]]
    for s in sgns:
        rows.append([InlineKeyboardButton(text=f"❌ {s['full_name'] or s['user_id']}", callback_data=f"asg:d:{s['user_id']}")])
    rows.append([InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")])
    await render_view(cb, "🤝 <b>ПАРТНЁРЫ-СИГНЕРЫ</b> (+5% ATK/HP)\nАдмин-сигна (+10% ATK/HP) выдаётся через право <code>sign_admin</code>.", InlineKeyboardMarkup(inline_keyboard=rows))
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
    if not tid:
        await m.answer("❌ Не найден.")
        return
    await db.set_signer(tid, "partner", m.from_user.id)
    await m.answer(f"✅ Партнёр <code>{tid}</code> добавлен!")


@router.callback_query(F.data.startswith("asg:d:"))
async def cb_asg_d(cb: CallbackQuery):
    await db.remove_signer(int(cb.data.split(":")[2]))
    await cb.answer("Снят!", show_alert=True)
    await cb_adm_sgn(cb)


@router.callback_query(F.data == "adm:maint")
async def cb_maint(cb: CallbackQuery):
    if not await db.has_perm(cb.from_user.id, "manage_admins"):
        await cb.answer("Нет прав!", show_alert=True)
        return
    nxt = "0" if GAME_SETTINGS.get("maintenance") == "1" else "1"
    await db.set_setting("maintenance", nxt)
    await cb.answer("🛠 Техработы ВКЛ" if nxt == "1" else "🟢 ВЫКЛ", show_alert=True)
    await render_admin_home(cb, cb.from_user.id)


@router.callback_query(F.data == "adm:logs")
async def cb_logs(cb: CallbackQuery):
    lgs = await db.get_admin_logs(15)
    lines = ["📋 <b>ЛОГИ АДМИНОВ</b>", "━━━━━━━━━━━━━━━━━━"] + [
        f"• [{datetime.fromtimestamp(x['created_at']).strftime('%d.%m %H:%M')}] <b>{esc(x['full_name'] or x['admin_id'])}</b>: {esc(x['action'])}"
        for x in lgs
    ]
    await render_view(cb, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="adm:home")]]))
    await cb.answer()


# --- НАДЁЖНЫЙ ОНЛАЙН-БЭКАП И ВОССТАНОВЛЕНИЕ БД ПОСЛЕ ЛЮБЫХ ОБНОВ/ПЕРЕСБОРОК ---

@router.callback_query(F.data == "adm:bak")
async def cb_bak(cb: CallbackQuery):
    if not await db.has_perm(cb.from_user.id, "manage_admins"):
        await cb.answer("Нет прав!", show_alert=True)
        return
    tmp_bak = f"{DB_PATH}.snap_{int(time.time())}.db"
    try:
        await db.backup_to_file(tmp_bak)
        await cb.message.answer_document(
            FSInputFile(tmp_bak, filename="skibidi_cards_backup.db"),
            caption=(
                "💾 <b>Чистый онлайн-бэкап БД Skibidi Verse.</b>\n"
                "Даже если бот будет полностью пересобран или выйдет обнова — просто отправьте этот "
                "<code>.db</code> файл обратно боту (только Владелец), и все данные восстановятся с автомиграцией!"
            ),
        )
        await cb.answer("Бэкап отправлен!")
    except Exception as exc:
        await cb.answer(f"Ошибка бэкапа: {exc}", show_alert=True)
    finally:
        if os.path.exists(tmp_bak):
            try:
                os.remove(tmp_bak)
            except Exception:
                pass


@router.message(F.document)
async def handle_db_upload(m: Message, bot: Bot):
    if m.from_user.id != OWNER_ID or not m.document:
        return
    fname = (m.document.file_name or "").lower()
    if not fname.endswith((".db", ".sqlite", ".sqlite3")):
        return

    wait_msg = await m.answer("⏳ Проверяю и восстанавливаю базу данных...")
    tmp_in = f"{DB_PATH}.incoming_{int(time.time())}"
    try:
        f = await bot.get_file(m.document.file_id)
        await bot.download_file(f.file_path, tmp_in)

        # 1. Проверяем, что файл — целая база SQLite
        with open(tmp_in, "rb") as fp:
            header = fp.read(16)
        if header != b"SQLite format 3\x00":
            await wait_msg.edit_text("❌ Файл не является корректной базой SQLite!")
            return
        async with aiosqlite.connect(tmp_in) as chk:
            res = await (await chk.execute("PRAGMA integrity_check")).fetchone()
            if not res or res[0] != "ok":
                await wait_msg.edit_text(f"❌ База повреждена: <code>{esc(res)}</code>")
                return

        # 2. Останавливаем текущих дочерних ботов перед заменой БД
        await child_manager.stop_all(mark_db_inactive=False)

        # 3. Страховочный снимок текущей БД и атомарная замена файла
        if os.path.exists(DB_PATH):
            try:
                await db.backup_to_file(f"{DB_PATH}.prev_bak")
            except Exception:
                pass
        for suffix in ("-wal", "-shm", "-journal"):
            jpath = DB_PATH + suffix
            if os.path.exists(jpath):
                try:
                    os.remove(jpath)
                except Exception:
                    pass
        os.replace(tmp_in, DB_PATH)

        # 4. Запускаем init + автомиграцию (добавит новые таблицы/колонки из обновы, сохранив все данные!)
        await db.init()

        # 5. Перезапускаем дочерних ботов из восстановленной БД
        started_cb = await child_manager.start_all_active()
        st = await db.get_stats()
        await wait_msg.edit_text(
            f"✅ <b>База данных успешно восстановлена и обновлена!</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👥 Игроков: <b>{st['users']}</b> | 🃏 Карт: <b>{st['cards']}</b>\n"
            f"🌟 Редкостей: <b>{st['rarities']}</b> | 📦 Крейтов: <b>{st['crates']}</b>\n"
            f"🪙 Валют: <b>{st['currencies']}</b> | 🏪 Рынок: <b>{st['market']}</b>\n"
            f"🤖 Дочерних ботов запущено: <b>{started_cb}/{st['child_bots']}</b>"
        )
    except Exception as exc:
        logger.exception("DB restore failed: %s", exc)
        await wait_msg.edit_text(f"❌ Ошибка восстановления БД: <code>{esc(str(exc)[:200])}</code>")
    finally:
        if os.path.exists(tmp_in):
            try:
                os.remove(tmp_in)
            except Exception:
                pass


@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery):
    await cb.answer()


# ==============================================================================
# 11. ЗАПУСК ГЛАВНОГО И ДОЧЕРНИХ БОТОВ
# ==============================================================================

async def auto_backup_task(bot: Bot) -> None:
    while True:
        await asyncio.sleep(12 * 3600)
        tmp_bak = f"{DB_PATH}.auto_{int(time.time())}.db"
        try:
            await db.backup_to_file(tmp_bak)
            await bot.send_document(OWNER_ID, FSInputFile(tmp_bak, filename="skibidi_cards_auto_backup.db"), caption="🕒 Автобэкап БД (12ч).")
        except Exception as exc:
            logger.warning("Backup error: %s", exc)
        finally:
            if os.path.exists(tmp_bak):
                try:
                    os.remove(tmp_bak)
                except Exception:
                    pass


async def main() -> None:
    global MAIN_BOT, MAIN_DP
    await db.init()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    MAIN_BOT = bot
    MAIN_DP = dp

    mw = AccessMiddleware()
    dp.message.outer_middleware(mw)
    dp.callback_query.outer_middleware(mw)
    dp.include_router(router)

    await bot.set_my_commands(BOT_COMMANDS_LIST)
    asyncio.create_task(auto_backup_task(bot))

    started_children = await child_manager.start_all_active()
    me = await bot.get_me()
    logger.info("🚀 Главный бот @%s запущен! Владелец: %s | Дочерних ботов запущено: %s", me.username, OWNER_ID, started_children)

    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await child_manager.stop_all(mark_db_inactive=False)
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 Бот остановлен.")
