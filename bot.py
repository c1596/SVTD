"""
Skibidi Verse Tower Defense — Telegram Card RPG, Wave Raids, Boss Infection & Live 4v4 PvP Bot
Стек: Python 3.10+, aiogram 3.x, aiosqlite

Функционал:
- Автоустановка недостающих библиотек (aiogram, aiosqlite)
- Статичное нижнее меню + инлайн-навигация
- Компактный живой 4v4 автобой в одном сообщении (с отображением Урона, HP, Скорости и статусов)
- 6 боевых классов (Single, AOE, Splash, Fire, Booster, Healer) + порядок слотов 1..4
- PvE Рейды по волнам с модификаторами боя и Фазой Заражения Босса
- Два уровня заражения: Обычный Инфектед и Астро-Инфектед (настраиваемые множители в Админке)
- Единственная мутация: ✨ Shiny (1% отовсюду, +25% к статам — настраивается в Админке)
- Сигны: Партнёр (+10% урон или скорость) и Админ (+20% урон или скорость)
- Рейтинговая PvP Арена (призраки игроков + AI-боты + кубки и лиги) + Live PvP дуэли со ставками
- Мировой Босс, P2P Рынок, Лаборатория паразитов и настраиваемые Крейты
- Расширенная Админ-панель: гибкие права, конструктор/редактор карт и крейтов, настройки баланса, бэкап/восстановление БД
"""

import asyncio
import html
import importlib
import importlib.util
import json
import logging
import os
import random
import subprocess
import sys
import time
import uuid
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple


def ensure_dependencies(packages: Dict[str, str]) -> None:
    """Проверяет наличие нужных библиотек и при их отсутствии устанавливает их через pip."""
    missing = [
        pip_spec
        for module_name, pip_spec in packages.items()
        if importlib.util.find_spec(module_name) is None
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
from aiogram.filters import CommandStart
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
DB_PATH = (os.getenv("DB_PATH") or "").strip() or "skibidi_verse.db"

MAX_DECK_SIZE = 4
DAILY_COOLDOWN = 86400

# Настройки игры по умолчанию (все редактируются в Админ-панели и сохраняются в БД)
DEFAULT_GAME_SETTINGS: Dict[str, str] = {
    "maintenance": "0",
    "infected_normal_mult": "1.20",   # Сила обычного заражения (+20%)
    "infected_astro_mult": "1.45",    # Сила астро-заражения (+45%)
    "shiny_chance_pct": "1.0",        # Шанс ✨ Shiny отовсюду (%)
    "shiny_bonus_pct": "25",          # Бонус ✨ Shiny к статам (%)
    "partner_sign_pct": "10",         # Бонус Партнёр-сигны (урон/скорость %)
    "admin_sign_pct": "20",           # Бонус Админ-сигны (урон/скорость %)
    "raid_waves": "3",                # Кол-во волн в рейде до босса включительно
    "battle_speed_sec": "1.5",        # Задержка между ходами в экране боя (сек)
    "wb_cooldown_sec": "60",          # КД удара по Мировому Боссу (сек)
    "event_coin_mult": "1.0",         # Ивент-множитель монет
    "event_luck_mult": "1.0",         # Ивент-множитель удачи (редкие карты и Shiny)
    "p_common_price": "150",
    "p_common_bonus": "5",
    "p_upgraded_price": "450",
    "p_upgraded_bonus": "18",
    "p_astro_price": "1200",
    "p_astro_bonus": "35",
}

# Кэш настроек в памяти (обновляется при старте и при любом изменении в админке)
GAME_SETTINGS: Dict[str, str] = dict(DEFAULT_GAME_SETTINGS)

# Описания редактируемых параметров для Админ-панели
SETTING_META: Dict[str, Tuple[str, str, float, float]] = {
    "infected_normal_mult": ("🦠 Множитель Обыч. Инфектед", "float", 1.0, 5.0),
    "infected_astro_mult": ("🌌 Множитель Астро-Инфектед", "float", 1.0, 5.0),
    "shiny_chance_pct": ("✨ Шанс Shiny (%)", "float", 0.1, 100.0),
    "shiny_bonus_pct": ("✨ Бонус Shiny к статам (%)", "int", 5, 200),
    "partner_sign_pct": ("🤝 Бонус Партнёр-сигны (%)", "int", 1, 100),
    "admin_sign_pct": ("👑 Бонус Админ-сигны (%)", "int", 1, 150),
    "raid_waves": ("🌊 Волн в рейде", "int", 1, 6),
    "battle_speed_sec": ("⏱ Пауза хода в бою (сек)", "float", 0.6, 4.0),
    "wb_cooldown_sec": ("🌍 КД Мирового Босса (сек)", "int", 5, 600),
    "event_coin_mult": ("💰 Ивент-множитель монет", "float", 0.5, 10.0),
    "event_luck_mult": ("🍀 Ивент-множитель удачи", "float", 1.0, 10.0),
    "p_common_price": ("🦠 Цена Обыч. паразита", "int", 10, 50000),
    "p_common_bonus": ("🦠 Бонус шанса Обыч. паразита (%)", "int", 1, 80),
    "p_upgraded_price": ("☣️ Цена Улучш. паразита", "int", 10, 100000),
    "p_upgraded_bonus": ("☣️ Бонус шанса Улучш. паразита (%)", "int", 1, 85),
    "p_astro_price": ("🌌 Цена Астро-паразита", "int", 10, 200000),
    "p_astro_bonus": ("🌌 Бонус шанса Астро-паразита (%)", "int", 1, 95),
}

FACTIONS: Dict[str, str] = {
    "alliance": "📷 Альянс",
    "skibidi": "🚽 Скибиди",
    "astro": "🌌 Астро",
    "infected": "🦠 Заражённые",
}

RARITIES: Dict[str, Tuple[str, str, int]] = {
    "common": ("Обычная", "⚪️", 55),
    "rare": ("Редкая", "🟢", 25),
    "epic": ("Эпическая", "🟣", 12),
    "legendary": ("Легендарная", "🟡", 5),
    "mythic": ("Мифическая", "🔴", 2),
    "secret": ("Секретная", "🌌", 1),
}

# 6 боевых классов (как в классическом карточном движке)
CARD_CLASSES: Dict[str, Tuple[str, str]] = {
    "Single": ("🎯", "Одиночная атака (сильный удар по 1 цели)"),
    "AOE": ("🌪", "Массовая атака (бьёт всех живых врагов)"),
    "Splash": ("🌊", "Сплеш (100% по цели + 50% по остальным)"),
    "Fire": ("🔥", "Огонь (бьёт и поджигает цель)"),
    "Booster": ("✨", "Бустер (усиливает Урон и HP всей колоды)"),
    "Healer": ("💗", "Хилер (лечит раненого союзника)"),
}

# Типы заражения экземпляра карты
INFECTED_TYPES: Dict[str, Tuple[str, str]] = {
    "none": ("Обычный", ""),
    "normal": ("🦠 Заражённый", "🦠"),
    "astro": ("🌌 Астро-Заражённый", "🌌🦠"),
}

# Типы паразитов: key -> (название, поле в users, тип заражения при успехе)
PARASITES_META: Dict[str, Tuple[str, str, str]] = {
    "common": ("🦠 Обычный паразит", "p_common", "normal"),
    "upgraded": ("☣️ Улучшенный паразит", "p_upgraded", "normal"),
    "astro": ("🌌 Астро-паразит", "p_astro", "astro"),
}

# PvE модификаторы боя (дебаффы усиливают награду и шанс заражения)
PVE_MODIFIERS: Dict[str, Tuple[str, str, float, int]] = {
    # key -> (название, тип debuff/buff, дельта монет, дельта шанса заражения %)
    "mod_enemy_hp": ("🔴 1.5x HP врагов (+30%💰, +4%🦠)", "debuff", 0.30, 4),
    "mod_enemy_atk": ("🔴 1.25x Урон врагов (+25%💰, +3%🦠)", "debuff", 0.25, 3),
    "mod_enemy_regen": ("🔴 Реген врагов 5%/ход (+30%💰, +4%🦠)", "debuff", 0.30, 4),
    "mod_player_hp": ("🟢 1.3x HP вашей колоды (-30%💰)", "buff", -0.30, 0),
    "mod_player_crit": ("🟢 +20% Шанс крита (-25%💰)", "buff", -0.25, 0),
}

# Гранулярные права админов
ADMIN_PERMS: Dict[str, str] = {
    "manage_cards": "🃏 Создание/редактирование/удаление карт",
    "manage_crates": "📦 Создание и настройка крейтов",
    "manage_settings": "🎛 Настройки баланса, инфектед, Shiny, ивентов",
    "manage_bosses": "🌍 Запуск и управление Мировым Боссом",
    "manage_economy": "💰 Выдача монет, паразитов и карт",
    "manage_users": "👥 Просмотр игроков, баны и разбаны",
    "broadcast": "📢 Рассылка сообщений всем игрокам",
    "sign_admin": "👑 Админ-сигна (+20% урон/скорость)",
    "manage_admins": "👮 Управление админами, партнёрами и БД",
}

# Оперативные состояния активных боёв и фаз заражения
USERS_IN_BATTLE: Set[int] = set()
ACTIVE_BATTLES: Dict[str, Dict[str, Any]] = {}   # battle_id -> {skip, surrendered, participants}
PENDING_INFECTIONS: Dict[int, Dict[str, Any]] = {}  # user_id -> данные для фазы заражения

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("skibidi_bot")


def cfg_float(key: str) -> float:
    try:
        return float(GAME_SETTINGS.get(key, DEFAULT_GAME_SETTINGS[key]))
    except (ValueError, TypeError):
        return float(DEFAULT_GAME_SETTINGS[key])


def cfg_int(key: str) -> int:
    try:
        return int(float(GAME_SETTINGS.get(key, DEFAULT_GAME_SETTINGS[key])))
    except (ValueError, TypeError):
        return int(float(DEFAULT_GAME_SETTINGS[key]))


def get_parasite_info(p_key: str) -> Tuple[str, str, str, int, int]:
    """Возвращает (название, колонка БД, тип заражения, цена, бонус шанса %)."""
    name, col, inf_type = PARASITES_META[p_key]
    price = cfg_int(f"p_{p_key}_price")
    bonus = cfg_int(f"p_{p_key}_bonus")
    return name, col, inf_type, price, bonus


# ==============================================================================
# 2. БАЗА ДАННЫХ И АВТОМИГРАЦИИ (AIOSQLITE)
# ==============================================================================

class Database:
    """Асинхронная БД SQLite со смарт-миграциями существующих таблиц."""

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
                    coins INTEGER DEFAULT 350,
                    trophies INTEGER DEFAULT 0,
                    arena_streak INTEGER DEFAULT 0,
                    p_common INTEGER DEFAULT 2,
                    p_upgraded INTEGER DEFAULT 0,
                    p_astro INTEGER DEFAULT 0,
                    pvp_wins INTEGER DEFAULT 0,
                    pvp_losses INTEGER DEFAULT 0,
                    bosses_killed INTEGER DEFAULT 0,
                    infections_success INTEGER DEFAULT 0,
                    infections_fail INTEGER DEFAULT 0,
                    pity_bonus INTEGER DEFAULT 0,
                    daily_streak INTEGER DEFAULT 0,
                    last_daily INTEGER DEFAULT 0,
                    is_banned INTEGER DEFAULT 0,
                    created_at INTEGER DEFAULT 0,
                    mod_enemy_hp INTEGER DEFAULT 0,
                    mod_enemy_atk INTEGER DEFAULT 0,
                    mod_enemy_regen INTEGER DEFAULT 0,
                    mod_player_hp INTEGER DEFAULT 0,
                    mod_player_crit INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS admins (
                    user_id INTEGER PRIMARY KEY,
                    added_by INTEGER,
                    perms_json TEXT DEFAULT '{}',
                    added_at INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS signers (
                    user_id INTEGER PRIMARY KEY,
                    role TEXT NOT NULL DEFAULT 'partner',
                    added_by INTEGER DEFAULT 0,
                    added_at INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS cards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    faction TEXT NOT NULL,
                    rarity TEXT NOT NULL,
                    class_type TEXT DEFAULT 'Single',
                    hp INTEGER NOT NULL,
                    atk INTEGER NOT NULL,
                    booster_dmg_mult REAL DEFAULT 1.15,
                    booster_hp_mult REAL DEFAULT 1.15,
                    description TEXT DEFAULT '',
                    image_id TEXT DEFAULT '',
                    is_boss INTEGER DEFAULT 0,
                    boss_hp INTEGER DEFAULT 0,
                    boss_atk INTEGER DEFAULT 0,
                    infect_chance INTEGER DEFAULT 0,
                    infected_card_id INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS inventory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    card_id INTEGER NOT NULL,
                    level INTEGER DEFAULT 1,
                    mutation TEXT DEFAULT 'none',
                    infected_type TEXT DEFAULT 'none',
                    sign_type TEXT DEFAULT 'none',
                    sign_stat TEXT DEFAULT 'none',
                    signed_by TEXT DEFAULT '',
                    in_deck INTEGER DEFAULT 0,
                    deck_pos INTEGER DEFAULT 0,
                    acquired_at INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS crates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    price INTEGER NOT NULL,
                    weights_json TEXT NOT NULL,
                    shiny_chance REAL DEFAULT 1.0,
                    active INTEGER DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS market (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    seller_id INTEGER NOT NULL,
                    inv_id INTEGER NOT NULL UNIQUE,
                    price INTEGER NOT NULL,
                    created_at INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS pvp_challenges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    creator_id INTEGER NOT NULL,
                    target_id INTEGER DEFAULT 0,
                    bet INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'open',
                    created_at INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS world_boss (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    card_id INTEGER NOT NULL,
                    max_hp INTEGER NOT NULL,
                    current_hp INTEGER NOT NULL,
                    atk INTEGER NOT NULL,
                    active INTEGER DEFAULT 1,
                    created_at INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS world_boss_hits (
                    boss_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    damage INTEGER DEFAULT 0,
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

            # Безопасные миграции на случай обновления старой БД
            migrations = [
                ("users", "trophies", "INTEGER DEFAULT 0"),
                ("users", "arena_streak", "INTEGER DEFAULT 0"),
                ("users", "mod_enemy_hp", "INTEGER DEFAULT 0"),
                ("users", "mod_enemy_atk", "INTEGER DEFAULT 0"),
                ("users", "mod_enemy_regen", "INTEGER DEFAULT 0"),
                ("users", "mod_player_hp", "INTEGER DEFAULT 0"),
                ("users", "mod_player_crit", "INTEGER DEFAULT 0"),
                ("cards", "class_type", "TEXT DEFAULT 'Single'"),
                ("cards", "booster_dmg_mult", "REAL DEFAULT 1.15"),
                ("cards", "booster_hp_mult", "REAL DEFAULT 1.15"),
                ("inventory", "infected_type", "TEXT DEFAULT 'none'"),
                ("inventory", "sign_type", "TEXT DEFAULT 'none'"),
                ("inventory", "sign_stat", "TEXT DEFAULT 'none'"),
                ("inventory", "signed_by", "TEXT DEFAULT ''"),
                ("inventory", "deck_pos", "INTEGER DEFAULT 0"),
            ]
            for table, col, definition in migrations:
                try:
                    await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
                except aiosqlite.OperationalError:
                    pass

            # Очищаем устаревшие штаммы, оставляя только 'none' и 'shiny'
            await db.execute(
                "UPDATE inventory SET mutation = 'none' WHERE mutation NOT IN ('none', 'shiny')"
            )

            for k, v in DEFAULT_GAME_SETTINGS.items():
                await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
            await db.commit()

        await self.reload_settings()
        await self.seed_default_cards()
        await self.seed_default_crates()

    async def reload_settings(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT key, value FROM settings")
            rows = await cur.fetchall()
            for k, v in rows:
                GAME_SETTINGS[k] = str(v)

    async def get_setting(self, key: str, default: str = "0") -> str:
        if key in GAME_SETTINGS:
            return GAME_SETTINGS[key]
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = await cur.fetchone()
            val = row[0] if row else default
            GAME_SETTINGS[key] = val
            return val

    async def set_setting(self, key: str, value: str) -> None:
        GAME_SETTINGS[key] = str(value)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value))
            )
            await db.commit()

    async def seed_default_cards(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT COUNT(*) FROM cards")
            row = await cur.fetchone()
            if row and row[0] > 0:
                return

            base_cards = [
                # (name, faction, rarity, class_type, hp, atk, b_dmg, b_hp, desc, is_boss, b_hp_raid, b_atk_raid, inf_ch, inf_id)
                ("Камерамен", "alliance", "common", "Single", 120, 26, 1.0, 1.0, "Базовый боец Альянса.", 0, 0, 0, 0, 0),
                ("Спикермен", "alliance", "common", "Splash", 110, 24, 1.0, 1.0, "Звуковые волны задевают соседние цели.", 0, 0, 0, 0, 0),
                ("Скибиди-Охранник", "skibidi", "common", "Single", 135, 22, 1.0, 1.0, "Крепкий передовой скибидист.", 0, 0, 0, 0, 0),
                ("ТВ-Мен", "alliance", "rare", "AOE", 140, 25, 1.0, 1.0, "Фиолетовое свечение бьёт по всем врагам.", 0, 0, 0, 0, 0),
                ("Скибиди-Пироман", "skibidi", "rare", "Fire", 150, 32, 1.0, 1.0, "Поджигает цель, нанося урон горением.", 0, 0, 0, 0, 0),
                ("Вантузмен", "alliance", "epic", "Single", 190, 56, 1.0, 1.0, "Бесстрашный герой с двумя вантузами.", 0, 0, 0, 0, 0),
                ("Скибиди-Учёный", "skibidi", "epic", "Booster", 180, 20, 1.18, 1.15, "Усиливает урон и HP всей команды.", 0, 0, 0, 0, 0),
                ("ТВ-Вумен", "alliance", "legendary", "Healer", 220, 58, 1.0, 1.0, "Лечит союзников и спасает отряд в волнах.", 0, 0, 0, 0, 0),
                ("Астро-Разведчик", "astro", "legendary", "Splash", 250, 62, 1.0, 1.0, "Быстрый перехватчик Астро с плазмой.", 0, 0, 0, 0, 0),
                ("Заражённый Титан Спикермен", "infected", "mythic", "AOE", 340, 62, 1.0, 1.0, "Заражённый титан с плазменными пушками!", 0, 0, 0, 0, 0),
                ("Заражённый Титан Камерамен", "infected", "mythic", "Splash", 410, 84, 1.0, 1.0, "Бронированный титан под контролем паразита.", 0, 0, 0, 0, 0),
                ("Заражённый Астро Детейнер", "infected", "secret", "Fire", 460, 108, 1.0, 1.0, "Опаснейший Астро-воин с клешнями.", 0, 0, 0, 0, 0),
            ]
            for c in base_cards:
                await db.execute(
                    """
                    INSERT INTO cards (
                        name, faction, rarity, class_type, hp, atk, booster_dmg_mult, booster_hp_mult,
                        description, is_boss, boss_hp, boss_atk, infect_chance, infected_card_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    c,
                )

            async def get_id(name: str) -> int:
                c = await db.execute("SELECT id FROM cards WHERE name = ?", (name,))
                r = await c.fetchone()
                return r[0] if r else 0

            inf_tsm = await get_id("Заражённый Титан Спикермен")
            inf_tcm = await get_id("Заражённый Титан Камерамен")
            inf_astro = await get_id("Заражённый Астро Детейнер")

            bosses = [
                ("Титан Спикермен (Босс)", "alliance", "legendary", "AOE", 310, 56, 1.0, 1.0, "Звуковой титан. Можно заразить после волн!", 1, 560, 42, 18, inf_tsm),
                ("Титан Камерамен (Босс)", "alliance", "mythic", "Splash", 370, 74, 1.0, 1.0, "Бронированный титан с молотом.", 1, 880, 60, 12, inf_tcm),
                ("Астро Детейнер (Босс)", "astro", "secret", "Fire", 420, 96, 1.0, 1.0, "Элитный перехватчик Астро. Очень трудно заразить!", 1, 1300, 82, 8, inf_astro),
            ]
            for b in bosses:
                await db.execute(
                    """
                    INSERT INTO cards (
                        name, faction, rarity, class_type, hp, atk, booster_dmg_mult, booster_hp_mult,
                        description, is_boss, boss_hp, boss_atk, infect_chance, infected_card_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    b,
                )
            await db.commit()

    async def seed_default_crates(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT COUNT(*) FROM crates")
            row = await cur.fetchone()
            if row and row[0] > 0:
                return

            defaults = [
                (
                    "📦 Обычный Кейс",
                    "Базовый кейс для быстрого старта коллекции.",
                    250,
                    json.dumps({"common": 55, "rare": 28, "epic": 12, "legendary": 4, "mythic": 1, "secret": 0}),
                    1.0,
                ),
                (
                    "💎 Элитный Кейс",
                    "Повышенный шанс на Эпических, Легендарных и Мифических юнитов!",
                    750,
                    json.dumps({"common": 15, "rare": 30, "epic": 30, "legendary": 17, "mythic": 6, "secret": 2}),
                    1.0,
                ),
                (
                    "🌌 Астро-Кейс",
                    "Редчайший контейнер с высоким шансом на Легенд и Секретки.",
                    1800,
                    json.dumps({"common": 0, "rare": 15, "epic": 32, "legendary": 32, "mythic": 15, "secret": 6}),
                    1.0,
                ),
            ]
            for name, desc, price, wj, sh in defaults:
                await db.execute(
                    "INSERT INTO crates (name, description, price, weights_json, shiny_chance, active) VALUES (?, ?, ?, ?, ?, 1)",
                    (name, desc, price, wj, sh),
                )
            await db.commit()

    # -------------------- Пользователи --------------------

    async def ensure_user(self, user_id: int, username: Optional[str], full_name: str) -> Tuple[Dict[str, Any], bool]:
        uname = (username or "").lower()
        fname = full_name or "Игрок"
        is_new = False
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = await cur.fetchone()
            if not row:
                is_new = True
                now = int(time.time())
                await db.execute(
                    "INSERT INTO users (user_id, username, full_name, created_at) VALUES (?, ?, ?, ?)",
                    (user_id, uname, fname, now),
                )
                starter_cur = await db.execute(
                    "SELECT id FROM cards WHERE is_boss = 0 AND rarity IN ('common', 'rare') ORDER BY id ASC LIMIT 3"
                )
                starters = await starter_cur.fetchall()
                for idx, st in enumerate(starters, 1):
                    await db.execute(
                        "INSERT INTO inventory (user_id, card_id, level, mutation, infected_type, in_deck, deck_pos, acquired_at) VALUES (?, ?, 1, 'none', 'none', 1, ?, ?)",
                        (user_id, st["id"], idx, now),
                    )
                await db.commit()
                cur = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
                row = await cur.fetchone()
            else:
                if row["username"] != uname or row["full_name"] != fname:
                    await db.execute(
                        "UPDATE users SET username = ?, full_name = ? WHERE user_id = ?",
                        (uname, fname, user_id),
                    )
                    await db.commit()
            return dict(row), is_new

    async def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = await cur.fetchone()
            return dict(row) if row else None

    async def find_user(self, query: str) -> Optional[Dict[str, Any]]:
        q = query.strip().lstrip("@").lower()
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            if q.isdigit():
                cur = await db.execute("SELECT * FROM users WHERE user_id = ?", (int(q),))
            else:
                cur = await db.execute("SELECT * FROM users WHERE LOWER(username) = ?", (q,))
            row = await cur.fetchone()
            return dict(row) if row else None

    async def update_user(self, user_id: int, **kwargs: Any) -> None:
        if not kwargs:
            return
        cols = ", ".join(f"{k} = ?" for k in kwargs.keys())
        vals = list(kwargs.values()) + [user_id]
        async with aiosqlite.connect(self.path) as db:
            await db.execute(f"UPDATE users SET {cols} WHERE user_id = ?", vals)
            await db.commit()

    async def add_coins(self, user_id: int, delta: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE users SET coins = MAX(0, coins + ?) WHERE user_id = ?",
                (delta, user_id),
            )
            await db.commit()

    async def add_trophies(self, user_id: int, delta: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE users SET trophies = MAX(0, trophies + ?) WHERE user_id = ?",
                (delta, user_id),
            )
            await db.commit()

    async def add_parasite(self, user_id: int, p_type: str, delta: int) -> None:
        col = PARASITES_META[p_type][1]
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                f"UPDATE users SET {col} = MAX(0, {col} + ?) WHERE user_id = ?",
                (delta, user_id),
            )
            await db.commit()

    async def get_all_active_user_ids(self) -> List[int]:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT user_id FROM users WHERE is_banned = 0")
            return [r[0] for r in await cur.fetchall()]

    async def find_ghost_opponent(self, exclude_uid: int, target_trophies: int) -> Optional[Dict[str, Any]]:
        """Находит реального игрока с собранной колодой для Арены (Призрак)."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT u.user_id, u.username, u.full_name, u.trophies
                FROM users u
                WHERE u.user_id != ? AND u.is_banned = 0
                  AND EXISTS (SELECT 1 FROM inventory i WHERE i.user_id = u.user_id AND i.in_deck = 1)
                ORDER BY ABS(u.trophies - ?) ASC, RANDOM()
                LIMIT 5
                """,
                (exclude_uid, target_trophies),
            )
            rows = [dict(r) for r in await cur.fetchall()]
            return random.choice(rows) if rows else None

    # -------------------- Админы и Сигнеры --------------------

    async def is_admin(self, user_id: int) -> bool:
        if user_id == OWNER_ID:
            return True
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
            return (await cur.fetchone()) is not None

    async def get_admin_perms(self, user_id: int) -> Dict[str, bool]:
        if user_id == OWNER_ID:
            return {k: True for k in ADMIN_PERMS}
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT perms_json FROM admins WHERE user_id = ?", (user_id,))
            row = await cur.fetchone()
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
        """Возвращает 'admin' (20%), 'partner' (10%) или None."""
        if user_id == OWNER_ID or await self.has_perm(user_id, "sign_admin"):
            return "admin"
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT role FROM signers WHERE user_id = ?", (user_id,))
            row = await cur.fetchone()
            return row[0] if row else None

    async def list_signers(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT s.user_id, s.role, u.username, u.full_name
                FROM signers s
                LEFT JOIN users u ON s.user_id = u.user_id
                ORDER BY s.role ASC, s.added_at DESC
                """
            )
            return [dict(r) for r in await cur.fetchall()]

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

    async def list_admins(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT a.user_id, a.perms_json, a.added_at, u.username, u.full_name
                FROM admins a
                LEFT JOIN users u ON a.user_id = u.user_id
                ORDER BY a.added_at DESC
                """
            )
            return [dict(r) for r in await cur.fetchall()]

    async def add_admin(self, target_id: int, added_by: int) -> None:
        default_perms = {k: False for k in ADMIN_PERMS}
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO admins (user_id, added_by, perms_json, added_at) VALUES (?, ?, ?, ?)",
                (target_id, added_by, json.dumps(default_perms), int(time.time())),
            )
            await db.commit()

    async def toggle_admin_perm(self, target_id: int, perm: str) -> Dict[str, bool]:
        perms = await self.get_admin_perms(target_id)
        perms[perm] = not perms.get(perm, False)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE admins SET perms_json = ? WHERE user_id = ?",
                (json.dumps(perms), target_id),
            )
            await db.commit()
        return perms

    async def remove_admin(self, target_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM admins WHERE user_id = ?", (target_id,))
            await db.commit()

    async def log_admin(self, admin_id: int, action: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO admin_logs (admin_id, action, created_at) VALUES (?, ?, ?)",
                (admin_id, action, int(time.time())),
            )
            await db.commit()

    async def get_admin_logs(self, limit: int = 15) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT l.*, u.username, u.full_name
                FROM admin_logs l
                LEFT JOIN users u ON l.admin_id = u.user_id
                ORDER BY l.id DESC LIMIT ?
                """,
                (limit,),
            )
            return [dict(r) for r in await cur.fetchall()]

    # -------------------- Карточки --------------------

    async def create_card(self, data: Dict[str, Any]) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                """
                INSERT INTO cards (
                    name, faction, rarity, class_type, hp, atk, booster_dmg_mult, booster_hp_mult,
                    description, image_id, is_boss, boss_hp, boss_atk, infect_chance, infected_card_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["name"],
                    data["faction"],
                    data["rarity"],
                    data.get("class_type", "Single"),
                    int(data["hp"]),
                    int(data["atk"]),
                    float(data.get("booster_dmg_mult", 1.15)),
                    float(data.get("booster_hp_mult", 1.15)),
                    data.get("description", ""),
                    data.get("image_id", ""),
                    int(data.get("is_boss", 0)),
                    int(data.get("boss_hp", 0)),
                    int(data.get("boss_atk", 0)),
                    int(data.get("infect_chance", 0)),
                    int(data.get("infected_card_id", 0)),
                ),
            )
            await db.commit()
            return cur.lastrowid

    async def get_card(self, card_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM cards WHERE id = ?", (card_id,))
            row = await cur.fetchone()
            return dict(row) if row else None

    async def list_cards(self, only_bosses: bool = False) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            sql = "SELECT * FROM cards"
            if only_bosses:
                sql += " WHERE is_boss = 1"
            sql += " ORDER BY id ASC"
            cur = await db.execute(sql)
            return [dict(r) for r in await cur.fetchall()]

    async def update_card(self, card_id: int, **kwargs: Any) -> None:
        if not kwargs:
            return
        cols = ", ".join(f"{k} = ?" for k in kwargs.keys())
        vals = list(kwargs.values()) + [card_id]
        async with aiosqlite.connect(self.path) as db:
            await db.execute(f"UPDATE cards SET {cols} WHERE id = ?", vals)
            await db.commit()

    async def delete_card(self, card_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "DELETE FROM market WHERE inv_id IN (SELECT id FROM inventory WHERE card_id = ?)",
                (card_id,),
            )
            await db.execute("DELETE FROM inventory WHERE card_id = ?", (card_id,))
            await db.execute("DELETE FROM cards WHERE id = ?", (card_id,))
            await db.commit()

    # -------------------- Крейты --------------------

    async def list_crates(self, only_active: bool = False) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            sql = "SELECT * FROM crates"
            if only_active:
                sql += " WHERE active = 1"
            sql += " ORDER BY price ASC, id ASC"
            cur = await db.execute(sql)
            return [dict(r) for r in await cur.fetchall()]

    async def get_crate(self, crate_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM crates WHERE id = ?", (crate_id,))
            row = await cur.fetchone()
            return dict(row) if row else None

    async def create_crate(self, name: str, description: str, price: int, weights: Dict[str, int], shiny_chance: float) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "INSERT INTO crates (name, description, price, weights_json, shiny_chance, active) VALUES (?, ?, ?, ?, ?, 1)",
                (name, description, price, json.dumps(weights), shiny_chance),
            )
            await db.commit()
            return cur.lastrowid

    async def update_crate(self, crate_id: int, **kwargs: Any) -> None:
        if not kwargs:
            return
        cols = ", ".join(f"{k} = ?" for k in kwargs.keys())
        vals = list(kwargs.values()) + [crate_id]
        async with aiosqlite.connect(self.path) as db:
            await db.execute(f"UPDATE crates SET {cols} WHERE id = ?", vals)
            await db.commit()

    async def delete_crate(self, crate_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM crates WHERE id = ?", (crate_id,))
            await db.commit()

    # -------------------- Инвентарь и Колода --------------------

    async def give_card(
        self,
        user_id: int,
        card_id: int,
        mutation: str = "none",
        infected_type: str = "none",
        sign_type: str = "none",
        sign_stat: str = "none",
        signed_by: str = "",
    ) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                """
                INSERT INTO inventory (
                    user_id, card_id, level, mutation, infected_type,
                    sign_type, sign_stat, signed_by, in_deck, deck_pos, acquired_at
                ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, 0, 0, ?)
                """,
                (user_id, card_id, mutation, infected_type, sign_type, sign_stat, signed_by, int(time.time())),
            )
            await db.commit()
            return cur.lastrowid

    async def get_inventory(self, user_id: int, only_deck: bool = False) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            where = "i.user_id = ?"
            order = "i.in_deck DESC, i.deck_pos ASC, i.level DESC, c.atk DESC"
            if only_deck:
                where += " AND i.in_deck = 1"
                order = "i.deck_pos ASC, i.id ASC"
            cur = await db.execute(
                f"""
                SELECT i.id AS inv_id, i.user_id, i.card_id, i.level, i.mutation, i.infected_type,
                       i.sign_type, i.sign_stat, i.signed_by, i.in_deck, i.deck_pos,
                       c.name, c.faction, c.rarity, c.class_type, c.hp, c.atk,
                       c.booster_dmg_mult, c.booster_hp_mult, c.description, c.image_id,
                       (SELECT m.id FROM market m WHERE m.inv_id = i.id) AS market_id
                FROM inventory i
                JOIN cards c ON i.card_id = c.id
                WHERE {where}
                ORDER BY {order}
                """,
                (user_id,),
            )
            return [dict(r) for r in await cur.fetchall()]

    async def get_inv_item(self, inv_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT i.id AS inv_id, i.user_id, i.card_id, i.level, i.mutation, i.infected_type,
                       i.sign_type, i.sign_stat, i.signed_by, i.in_deck, i.deck_pos,
                       c.name, c.faction, c.rarity, c.class_type, c.hp, c.atk,
                       c.booster_dmg_mult, c.booster_hp_mult, c.description, c.image_id,
                       (SELECT m.id FROM market m WHERE m.inv_id = i.id) AS market_id
                FROM inventory i
                JOIN cards c ON i.card_id = c.id
                WHERE i.id = ?
                """,
                (inv_id,),
            )
            row = await cur.fetchone()
            return dict(row) if row else None

    async def set_in_deck(self, user_id: int, inv_id: int, in_deck: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            if in_deck == 1:
                cur = await db.execute(
                    "SELECT COALESCE(MAX(deck_pos), 0) FROM inventory WHERE user_id = ? AND in_deck = 1",
                    (user_id,),
                )
                max_pos = (await cur.fetchone())[0]
                await db.execute(
                    "UPDATE inventory SET in_deck = 1, deck_pos = ? WHERE id = ?",
                    (max_pos + 1, inv_id),
                )
            else:
                await db.execute("UPDATE inventory SET in_deck = 0, deck_pos = 0 WHERE id = ?", (inv_id,))
            await db.commit()
        await self.normalize_deck_positions(user_id)

    async def normalize_deck_positions(self, user_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "SELECT id FROM inventory WHERE user_id = ? AND in_deck = 1 ORDER BY deck_pos ASC, id ASC",
                (user_id,),
            )
            rows = await cur.fetchall()
            for idx, r in enumerate(rows, 1):
                await db.execute("UPDATE inventory SET deck_pos = ? WHERE id = ?", (idx, r[0]))
            await db.commit()

    async def move_deck_slot(self, user_id: int, inv_id: int, direction: str) -> bool:
        await self.normalize_deck_positions(user_id)
        deck = await self.get_inventory(user_id, only_deck=True)
        idx = next((i for i, c in enumerate(deck) if c["inv_id"] == inv_id), -1)
        if idx == -1:
            return False
        swap_idx = idx - 1 if direction == "up" else idx + 1
        if not (0 <= swap_idx < len(deck)):
            return False
        a, b = deck[idx], deck[swap_idx]
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE inventory SET deck_pos = ? WHERE id = ?", (b["deck_pos"], a["inv_id"]))
            await db.execute("UPDATE inventory SET deck_pos = ? WHERE id = ?", (a["deck_pos"], b["inv_id"]))
            await db.commit()
        return True

    async def upgrade_inv_card(self, inv_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE inventory SET level = level + 1 WHERE id = ?", (inv_id,))
            await db.commit()

    async def sign_inv_card(self, inv_id: int, sign_type: str, sign_stat: str, signed_by: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE inventory SET sign_type = ?, sign_stat = ?, signed_by = ? WHERE id = ?",
                (sign_type, sign_stat, signed_by, inv_id),
            )
            await db.commit()

    # -------------------- P2P Рынок --------------------

    async def list_market(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT m.id AS market_id, m.seller_id, m.inv_id, m.price,
                       i.level, i.mutation, i.infected_type, i.sign_type, i.sign_stat, i.signed_by,
                       c.name, c.faction, c.rarity, c.class_type, c.hp, c.atk,
                       c.booster_dmg_mult, c.booster_hp_mult, c.image_id,
                       u.username AS seller_username, u.full_name AS seller_name
                FROM market m
                JOIN inventory i ON m.inv_id = i.id
                JOIN cards c ON i.card_id = c.id
                LEFT JOIN users u ON m.seller_id = u.user_id
                ORDER BY m.id DESC
                """
            )
            return [dict(r) for r in await cur.fetchall()]

    async def create_market_lot(self, seller_id: int, inv_id: int, price: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE inventory SET in_deck = 0, deck_pos = 0 WHERE id = ?", (inv_id,))
            await db.execute(
                "INSERT INTO market (seller_id, inv_id, price, created_at) VALUES (?, ?, ?, ?)",
                (seller_id, inv_id, price, int(time.time())),
            )
            await db.commit()
        await self.normalize_deck_positions(seller_id)

    async def buy_market_lot(self, market_id: int, buyer_id: int) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT m.*, i.card_id, i.level, i.mutation, c.name
                FROM market m
                JOIN inventory i ON m.inv_id = i.id
                JOIN cards c ON i.card_id = c.id
                WHERE m.id = ?
                """,
                (market_id,),
            )
            lot = await cur.fetchone()
            if not lot:
                return False, "Лот уже куплен или снят с продажи.", None
            if lot["seller_id"] == buyer_id:
                return False, "Нельзя купить свой собственный лот.", None

            bcur = await db.execute("SELECT coins FROM users WHERE user_id = ?", (buyer_id,))
            buyer = await bcur.fetchone()
            if not buyer or buyer["coins"] < lot["price"]:
                return False, f"Недостаточно монет! Нужно {lot['price']} 💰.", None

            await db.execute("UPDATE users SET coins = coins - ? WHERE user_id = ?", (lot["price"], buyer_id))
            await db.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (lot["price"], lot["seller_id"]))
            await db.execute("UPDATE inventory SET user_id = ?, in_deck = 0, deck_pos = 0 WHERE id = ?", (buyer_id, lot["inv_id"]))
            await db.execute("DELETE FROM market WHERE id = ?", (market_id,))
            await db.commit()
            return True, "Покупка успешна!", dict(lot)

    async def cancel_market_lot(self, market_id: int, seller_id: int) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "DELETE FROM market WHERE id = ? AND seller_id = ?", (market_id, seller_id)
            )
            await db.commit()
            return cur.rowcount > 0

    # -------------------- PvP Вызовы --------------------

    async def create_pvp_challenge(self, creator_id: int, target_id: int, bet: int) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "INSERT INTO pvp_challenges (creator_id, target_id, bet, status, created_at) VALUES (?, ?, ?, 'open', ?)",
                (creator_id, target_id, bet, int(time.time())),
            )
            await db.commit()
            return cur.lastrowid

    async def list_open_pvp(self, user_id: int) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT p.*, u.username, u.full_name, u.pvp_wins, u.trophies
                FROM pvp_challenges p
                JOIN users u ON p.creator_id = u.user_id
                WHERE p.status = 'open' AND (p.target_id = 0 OR p.target_id = ? OR p.creator_id = ?)
                ORDER BY p.id DESC LIMIT 20
                """,
                (user_id, user_id),
            )
            return [dict(r) for r in await cur.fetchall()]

    async def get_pvp_challenge(self, ch_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM pvp_challenges WHERE id = ?", (ch_id,))
            row = await cur.fetchone()
            return dict(row) if row else None

    async def close_pvp_challenge(self, ch_id: int, status: str = "done") -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE pvp_challenges SET status = ? WHERE id = ?", (status, ch_id))
            await db.commit()

    # -------------------- Мировой Босс --------------------

    async def get_active_world_boss(self) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT wb.*, c.name, c.faction, c.rarity, c.image_id, c.infect_chance, c.infected_card_id
                FROM world_boss wb
                JOIN cards c ON wb.card_id = c.id
                WHERE wb.active = 1
                ORDER BY wb.id DESC LIMIT 1
                """
            )
            row = await cur.fetchone()
            return dict(row) if row else None

    async def spawn_world_boss(self, card_id: int, max_hp: int, atk: int) -> int:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE world_boss SET active = 0 WHERE active = 1")
            cur = await db.execute(
                "INSERT INTO world_boss (card_id, max_hp, current_hp, atk, active, created_at) VALUES (?, ?, ?, ?, 1, ?)",
                (card_id, max_hp, max_hp, atk, int(time.time())),
            )
            await db.commit()
            return cur.lastrowid

    async def get_world_boss_hit(self, boss_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM world_boss_hits WHERE boss_id = ? AND user_id = ?",
                (boss_id, user_id),
            )
            row = await cur.fetchone()
            return dict(row) if row else None

    async def hit_world_boss(self, boss_id: int, user_id: int, damage: int) -> int:
        now = int(time.time())
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO world_boss_hits (boss_id, user_id, damage, last_hit)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(boss_id, user_id) DO UPDATE SET
                    damage = damage + excluded.damage,
                    last_hit = excluded.last_hit
                """,
                (boss_id, user_id, damage, now),
            )
            await db.execute(
                "UPDATE world_boss SET current_hp = MAX(0, current_hp - ?) WHERE id = ?",
                (damage, boss_id),
            )
            cur = await db.execute("SELECT current_hp FROM world_boss WHERE id = ?", (boss_id,))
            row = await cur.fetchone()
            rem = row[0] if row else 0
            if rem <= 0:
                await db.execute("UPDATE world_boss SET active = 0 WHERE id = ?", (boss_id,))
            await db.commit()
            return rem

    async def get_world_boss_top(self, boss_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT h.user_id, h.damage, u.username, u.full_name
                FROM world_boss_hits h
                LEFT JOIN users u ON h.user_id = u.user_id
                WHERE h.boss_id = ?
                ORDER BY h.damage DESC LIMIT ?
                """,
                (boss_id, limit),
            )
            return [dict(r) for r in await cur.fetchall()]

    async def stop_world_boss(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE world_boss SET active = 0 WHERE active = 1")
            await db.commit()

    # -------------------- Топы и Глобальная статистика --------------------

    async def get_leaderboard(self, column: str, limit: int = 10) -> List[Dict[str, Any]]:
        allowed = {"trophies", "pvp_wins", "coins", "infections_success", "bosses_killed"}
        col = column if column in allowed else "trophies"
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                f"SELECT user_id, username, full_name, {col} AS val FROM users WHERE is_banned = 0 ORDER BY {col} DESC LIMIT ?",
                (limit,),
            )
            return [dict(r) for r in await cur.fetchall()]

    async def get_global_stats(self) -> Dict[str, int]:
        async with aiosqlite.connect(self.path) as db:
            u = (await (await db.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
            c = (await (await db.execute("SELECT COUNT(*) FROM cards")).fetchone())[0]
            i = (await (await db.execute("SELECT COUNT(*) FROM inventory")).fetchone())[0]
            m = (await (await db.execute("SELECT COUNT(*) FROM market")).fetchone())[0]
            cr = (await (await db.execute("SELECT COUNT(*) FROM crates")).fetchone())[0]
            return {"users": u, "cards": c, "inventory": i, "market": m, "crates": cr}


db = Database(DB_PATH)


# ==============================================================================
# 3. СТАТЫ КАРТ, SHINY, СИГНЫ, ЗАРАЖЕНИЕ И ЖИВОЙ 4v4 БОЕВОЙ ДВИЖОК
# ==============================================================================

def esc(text: Any) -> str:
    return html.escape(str(text or ""))


def format_user_link(user: Dict[str, Any]) -> str:
    name = esc(user.get("full_name") or "Игрок")
    uname = user.get("username")
    if uname:
        return f"<b>{name}</b> (@{esc(uname)})"
    return f"<b>{name}</b> [<code>{user.get('user_id')}</code>]"


def roll_shiny(custom_chance_pct: Optional[float] = None) -> str:
    """Роллит единственную мутацию ✨ Shiny (по умолчанию 1% * ивент удачи)."""
    base = custom_chance_pct if custom_chance_pct is not None else cfg_float("shiny_chance_pct")
    chance = min(100.0, base * cfg_float("event_luck_mult"))
    return "shiny" if (random.random() * 100.0) < chance else "none"


def get_league(trophies: int) -> str:
    if trophies >= 2000:
        return "🌌 Астро-Легенда"
    if trophies >= 1300:
        return "💎 Титановая Лига"
    if trophies >= 700:
        return "🥇 Золотая Лига"
    if trophies >= 300:
        return "🥈 Серебряная Лига"
    return "🥉 Бронзовая Лига"


def get_sign_label(item: Dict[str, Any]) -> str:
    st = item.get("sign_type", "none")
    stat = item.get("sign_stat", "none")
    if st == "none":
        return "Нет"
    pct = cfg_int("admin_sign_pct") if st == "admin" else cfg_int("partner_sign_pct")
    role_name = "👑 Админ-сигна" if st == "admin" else "🤝 Партнёр-сигна"
    stat_name = f"⚔️+{pct}% Урон" if stat == "power" else f"⚡️+{pct}% Скорость"
    who = f" ({esc(item.get('signed_by'))})" if item.get("signed_by") else ""
    return f"{role_name}: {stat_name}{who}"


def calc_card_stats(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Считает реальные боевые параметры карты с учётом:
    - Уровня (+10%/ур.)
    - Мутации ✨ Shiny (+25% по умолчанию)
    - Типа заражения (Обычный Инфектед / Астро-Инфектед — из настроек Админки)
    - Сигны (Партнёр +10% / Админ +20% на Урон или Скорость атаки)
    """
    lvl = max(1, int(item.get("level", 1)))
    lvl_mult = 1.0 + (lvl - 1) * 0.10

    is_shiny = item.get("mutation") == "shiny"
    shiny_mult = (1.0 + cfg_float("shiny_bonus_pct") / 100.0) if is_shiny else 1.0

    inf_type = item.get("infected_type", "none")
    if inf_type == "astro":
        inf_mult = cfg_float("infected_astro_mult")
    elif inf_type == "normal":
        inf_mult = cfg_float("infected_normal_mult")
    else:
        inf_mult = 1.0

    sign_type = item.get("sign_type", "none")
    sign_stat = item.get("sign_stat", "none")
    sign_pct = (
        cfg_float("admin_sign_pct") / 100.0
        if sign_type == "admin"
        else (cfg_float("partner_sign_pct") / 100.0 if sign_type == "partner" else 0.0)
    )
    sign_atk_mult = (1.0 + sign_pct) if sign_stat == "power" else 1.0
    speed_mult = (1.0 + sign_pct) if sign_stat == "speed" else 1.0

    hp = max(1, int(item["hp"] * lvl_mult * shiny_mult * inf_mult))
    atk = max(1, int(item["atk"] * lvl_mult * shiny_mult * inf_mult * sign_atk_mult))

    b_dmg = round(float(item.get("booster_dmg_mult", 1.15)) * (1.0 + (lvl - 1) * 0.02) * (1.05 if is_shiny else 1.0), 2)
    b_hp = round(float(item.get("booster_hp_mult", 1.15)) * (1.0 + (lvl - 1) * 0.02) * (1.05 if is_shiny else 1.0), 2)

    return {
        "hp": hp,
        "atk": atk,
        "speed": round(speed_mult, 2),
        "booster_dmg_mult": b_dmg,
        "booster_hp_mult": b_hp,
    }


def calc_deck_summary(deck: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_hp = 0
    total_atk = 0
    factions: Dict[str, int] = {}

    for card in deck:
        st = calc_card_stats(card)
        total_hp += st["hp"]
        total_atk += int(st["atk"] * st["speed"])
        f = card["faction"]
        factions[f] = factions.get(f, 0) + 1

    synergies: List[str] = []
    if factions.get("alliance", 0) >= 2:
        total_hp = int(total_hp * 1.15)
        synergies.append("📷 Альянс (+15% HP)")
    if factions.get("infected", 0) >= 2:
        total_atk = int(total_atk * 1.18)
        synergies.append("🦠 Рой Паразитов (+18% ATK)")
    if factions.get("skibidi", 0) >= 2:
        total_atk = int(total_atk * 1.12)
        synergies.append("🚽 Хаос Скибиди (+12% ATK)")
    if factions.get("astro", 0) >= 2:
        total_hp = int(total_hp * 1.10)
        total_atk = int(total_atk * 1.12)
        synergies.append("🌌 Превосходство Астро (+10% HP, +12% ATK)")

    power = total_hp + total_atk * 4
    return {
        "hp": total_hp,
        "atk": total_atk,
        "power": power,
        "synergies": synergies,
    }


def make_hp_bar(current: int, maximum: int, length: int = 10) -> str:
    if maximum <= 0:
        return "⬛" * length
    ratio = max(0.0, min(1.0, current / maximum))
    filled = int(round(ratio * length))
    return "🟥" * filled + "⬛" * (length - filled)


def build_combat_unit(item: Dict[str, Any], side: int, hp_mult: float = 1.0, atk_mult: float = 1.0, is_boss_unit: bool = False) -> Dict[str, Any]:
    """Превращает карту инвентаря или шаблон врага в боевой юнит для 4v4 движка."""
    st = calc_card_stats(item)
    hp = max(1, int(st["hp"] * hp_mult))
    atk = max(1, int(st["atk"] * atk_mult))
    speed = st["speed"]
    if item.get("faction") == "astro":
        speed = round(speed + 0.08, 2)  # Астро немного быстрее

    return {
        "name": item["name"],
        "faction": item.get("faction", "alliance"),
        "rarity": item.get("rarity", "common"),
        "class_type": item.get("class_type", "Single"),
        "hp": hp,
        "max_hp": hp,
        "atk": atk,
        "speed": speed,
        "gauge": 0.0,
        "booster_dmg_mult": st["booster_dmg_mult"],
        "booster_hp_mult": st["booster_hp_mult"],
        "mutation": item.get("mutation", "none"),
        "infected_type": item.get("infected_type", "none"),
        "sign_type": item.get("sign_type", "none"),
        "sign_stat": item.get("sign_stat", "none"),
        "burn": 0,
        "stunned": False,
        "heal_eff": 1.0,
        "is_boss_unit": is_boss_unit,
        "side": side,
    }


def apply_team_start_buffs(team: List[Dict[str, Any]], team_label: str, log: List[str]) -> None:
    """Применяет фракционные синергии и баффы карт класса Booster в начале боя."""
    factions: Dict[str, int] = {}
    for u in team:
        factions[u["faction"]] = factions.get(u["faction"], 0) + 1

    if factions.get("alliance", 0) >= 2:
        for u in team:
            u["hp"] = int(u["hp"] * 1.15)
            u["max_hp"] = u["hp"]
    if factions.get("infected", 0) >= 2:
        for u in team:
            u["atk"] = int(u["atk"] * 1.18)
    if factions.get("skibidi", 0) >= 2:
        for u in team:
            u["atk"] = int(u["atk"] * 1.12)
    if factions.get("astro", 0) >= 2:
        for u in team:
            u["hp"] = int(u["hp"] * 1.10)
            u["max_hp"] = u["hp"]
            u["atk"] = int(u["atk"] * 1.12)

    for u in team:
        if u["class_type"] == "Booster":
            dm = u["booster_dmg_mult"]
            hm = u["booster_hp_mult"]
            for ally in team:
                ally["hp"] = int(ally["hp"] * hm)
                ally["max_hp"] = ally["hp"]
                if ally["class_type"] != "Booster":
                    ally["atk"] = int(ally["atk"] * dm)
            log.append(f"✨ {esc(team_label)}: <b>{esc(u['name'])}</b> баффает отряд (⚔️x{dm}, ❤️x{hm})")


def format_unit_line(idx: int, u: Dict[str, Any]) -> str:
    """Компактная строка юнита в бою — обязательно показывает УРОН и HP!"""
    if u["hp"] <= 0:
        return f"{idx}. 💀 <s>{esc(u['name'])}</s>"

    cls_ico = "👑" if u.get("is_boss_unit") else CARD_CLASSES.get(u["class_type"], ("🎯", ""))[0]
    badges = ""
    if u.get("mutation") == "shiny":
        badges += "✨"
    if u.get("infected_type") == "astro":
        badges += "🌌🦠"
    elif u.get("infected_type") == "normal":
        badges += "🦠"
    if u.get("sign_type") == "admin":
        badges += "👑"
    elif u.get("sign_type") == "partner":
        badges += "🤝"

    statuses = ""
    if u.get("burn", 0) > 0:
        statuses += " 🔥"
    if u.get("stunned"):
        statuses += " 💫"

    spd_str = f" ⚡️{u['speed']}x" if u["speed"] > 1.0 else ""

    if u["class_type"] == "Healer":
        heal_v = max(1, int(u["atk"] * u["heal_eff"]))
        stat_str = f"💗{heal_v} | ❤️{u['hp']}/{u['max_hp']}"
    elif u["class_type"] == "Booster":
        stat_str = f"⚔️{u['atk']} | ❤️{u['hp']}/{u['max_hp']}"
    else:
        stat_str = f"⚔️{u['atk']} | ❤️{u['hp']}/{u['max_hp']}"

    return f"{idx}. {cls_ico} <b>{esc(u['name'])}</b>{badges} ({stat_str}){spd_str}{statuses}"


def render_battle_board(
    title: str,
    p1_name: str,
    t1: List[Dict[str, Any]],
    p2_name: str,
    t2: List[Dict[str, Any]],
    logs: List[str],
    round_num: int,
) -> str:
    """Компактный экран боя 4×4 (помещается на один экран телефона)."""
    t1_txt = "\n".join(format_unit_line(i, u) for i, u in enumerate(t1, 1))
    t2_txt = "\n".join(format_unit_line(i, u) for i, u in enumerate(t2, 1))
    recent = "\n".join(f"• {line}" for line in logs[-3:]) if logs else "• <i>Бой начинается...</i>"
    return (
        f"{title} | <b>Ход {round_num}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔵 <b>{esc(p1_name)}:</b>\n{t1_txt}\n\n"
        f"🔴 <b>{esc(p2_name)}:</b>\n{t2_txt}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚡ <b>События:</b>\n{recent}"
    )


def battle_controls_kb(battle_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⏩ Пропустить", callback_data=f"btl:skip:{battle_id}"),
                InlineKeyboardButton(text="🏳️ Сдаться", callback_data=f"btl:surr:{battle_id}"),
            ]
        ]
    )


def execute_unit_action(
    attacker: Dict[str, Any],
    allies: List[Dict[str, Any]],
    enemies: List[Dict[str, Any]],
    logs: List[str],
    crit_bonus: float = 0.0,
) -> None:
    """Выполняет 1 действие юнита с учётом класса, горения, критов и паразитного контроля."""
    if attacker["hp"] <= 0:
        return

    # Урон от горения перед действием
    if attacker["burn"] > 0:
        burn_dmg = attacker["burn"]
        attacker["hp"] = max(0, attacker["hp"] - burn_dmg)
        attacker["burn"] = 0
        if attacker["hp"] <= 0:
            logs.append(f"🔥 <b>{esc(attacker['name'])}</b> сгорел (-{burn_dmg}) ☠️")
            return
        logs.append(f"🔥 <b>{esc(attacker['name'])}</b> горит (-{burn_dmg})")

    if attacker["stunned"]:
        attacker["stunned"] = False
        logs.append(f"💫 <b>{esc(attacker['name'])}</b> оглушён и пропускает ход!")
        return

    alive_enemies = [u for u in enemies if u["hp"] > 0]
    alive_allies = [u for u in allies if u["hp"] > 0]
    if not alive_enemies:
        return

    # Выбор цели: с 65% вероятностью бьёт первый живой слот (Фронт/Танк!), иначе случайного
    primary = alive_enemies[0] if (len(alive_enemies) == 1 or random.random() < 0.65) else random.choice(alive_enemies)

    cls = attacker["class_type"]
    crit_chance = 0.15 + crit_bonus
    is_crit = random.random() < crit_chance
    base_dmg = int(attacker["atk"] * random.uniform(0.92, 1.10) * (1.45 if is_crit else 1.0))
    crit_tag = " 💥КРИТ!" if is_crit else ""

    if cls == "Healer":
        injured = [a for a in alive_allies if a is not attacker and a["hp"] < a["max_hp"]]
        others = [a for a in alive_allies if a is not attacker]
        if injured or others:
            target = min(injured, key=lambda x: x["hp"] / x["max_hp"]) if injured else random.choice(others)
            heal = max(5, int(base_dmg * attacker["heal_eff"]))
            target["hp"] = min(target["max_hp"], target["hp"] + heal)
            attacker["heal_eff"] = max(0.35, round(attacker["heal_eff"] - 0.03, 2))
            logs.append(f"💗 <b>{esc(attacker['name'])}</b> лечит {esc(target['name'])} (+{heal}){crit_tag}")
            return
        # Если хилер остался один — бьёт слабо
        dmg = max(5, int(base_dmg * 0.4))
        primary["hp"] = max(0, primary["hp"] - dmg)
        ko = " ☠️" if primary["hp"] <= 0 else ""
        logs.append(f"💗 <b>{esc(attacker['name'])}</b> ➔ {esc(primary['name'])} (-{dmg}){ko}")
        return

    if cls == "Booster":
        dmg = max(attacker["atk"], int(primary["max_hp"] * 0.09))
        primary["hp"] = max(0, primary["hp"] - dmg)
        ko = " ☠️" if primary["hp"] <= 0 else ""
        logs.append(f"✨ <b>{esc(attacker['name'])}</b> импульсом ➔ {esc(primary['name'])} (-{dmg}){ko}")
        return

    if cls == "AOE":
        aoe_dmg = max(1, int(base_dmg * 0.72))
        kills = 0
        for e in alive_enemies:
            e["hp"] = max(0, e["hp"] - aoe_dmg)
            if e["hp"] <= 0:
                kills += 1
        ko = f" (☠️x{kills})" if kills else ""
        logs.append(f"🌪 <b>{esc(attacker['name'])}</b> ➔ -{aoe_dmg} по всем!{crit_tag}{ko}")
        return

    if cls == "Splash":
        sp_dmg = max(1, int(base_dmg * 0.48))
        primary["hp"] = max(0, primary["hp"] - base_dmg)
        kills = 1 if primary["hp"] <= 0 else 0
        for e in alive_enemies:
            if e is not primary:
                e["hp"] = max(0, e["hp"] - sp_dmg)
                if e["hp"] <= 0:
                    kills += 1
        ko = f" (☠️x{kills})" if kills else ""
        logs.append(f"🌊 <b>{esc(attacker['name'])}</b> ➔ {esc(primary['name'])} (-{base_dmg} / -{sp_dmg}){crit_tag}{ko}")
        return

    if cls == "Fire":
        primary["hp"] = max(0, primary["hp"] - base_dmg)
        burn_v = max(5, int(base_dmg * 0.35))
        primary["burn"] += burn_v
        ko = " ☠️" if primary["hp"] <= 0 else ""
        logs.append(f"🔥 <b>{esc(attacker['name'])}</b> ➔ {esc(primary['name'])} (-{base_dmg} +🔥{burn_v}){crit_tag}{ko}")
        return

    # Single target + пассивка заражённых (12% шанс оглушить паразитом)
    primary["hp"] = max(0, primary["hp"] - base_dmg)
    stun_tag = ""
    if primary["hp"] > 0 and (attacker["faction"] == "infected" or attacker["infected_type"] != "none"):
        if random.random() < 0.12:
            primary["stunned"] = True
            stun_tag = " 🦠ОГЛУШЁН!"
    ko = " ☠️" if primary["hp"] <= 0 else ""
    logs.append(f"🎯 <b>{esc(attacker['name'])}</b> ➔ {esc(primary['name'])} (-{base_dmg}){crit_tag}{stun_tag}{ko}")


def next_acting_unit(t1: List[Dict[str, Any]], t2: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """ATB-шкала скорости: +10% / +20% скорость от сигн реально даёт больше ходов!"""
    alive = [u for u in t1 + t2 if u["hp"] > 0]
    if not alive:
        return None
    while True:
        ready = [u for u in alive if u["gauge"] >= 100.0]
        if ready:
            ready.sort(key=lambda x: (x["gauge"], random.random()), reverse=True)
            actor = ready[0]
            actor["gauge"] -= 100.0
            return actor
        for u in alive:
            u["gauge"] += 25.0 * u["speed"]


async def safe_edit_battle(msg: Message, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None) -> None:
    try:
        await msg.edit_text(text, reply_markup=reply_markup)
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        try:
            await msg.edit_text(text, reply_markup=reply_markup)
        except Exception:
            pass
    except TelegramBadRequest:
        pass
    except Exception:
        pass


async def run_live_skirmish(
    messages: List[Message],
    battle_id: str,
    title: str,
    p1_id: int,
    p1_name: str,
    t1: List[Dict[str, Any]],
    p2_id: int,
    p2_name: str,
    t2: List[Dict[str, Any]],
    p1_crit_bonus: float = 0.0,
    enemy_regen: bool = False,
    apply_start_buffs: bool = True,
) -> Tuple[int, List[str]]:
    """
    Проводит живой компактный 4v4 бой, обновляя 1 или 2 сообщения (для дуэли).
    Возвращает: (1 если победил t1, 2 если победил t2, 0 ничья; финальный лог).
    """
    state = ACTIVE_BATTLES[battle_id]
    logs: List[str] = []
    if apply_start_buffs:
        apply_team_start_buffs(t1, p1_name, logs)
        apply_team_start_buffs(t2, p2_name, logs)

    step_delay = cfg_float("battle_speed_sec")
    kb = battle_controls_kb(battle_id)

    if not state["skip"]:
        board = render_battle_board(title, p1_name, t1, p2_name, t2, logs, 0)
        for m in messages:
            await safe_edit_battle(m, board, kb)
        await asyncio.sleep(min(1.2, step_delay))

    round_num = 0
    max_actions = 45

    while round_num < max_actions:
        if p1_id in state["surrendered"]:
            logs.append(f"🏳️ <b>{esc(p1_name)}</b> сдался!")
            return 2, logs
        if p2_id and p2_id in state["surrendered"]:
            logs.append(f"🏳️ <b>{esc(p2_name)}</b> сдался!")
            return 1, logs

        t1_alive = [u for u in t1 if u["hp"] > 0]
        t2_alive = [u for u in t2 if u["hp"] > 0]
        if not t1_alive and not t2_alive:
            return 0, logs
        if not t2_alive:
            return 1, logs
        if not t1_alive:
            return 2, logs

        round_num += 1
        actor = next_acting_unit(t1, t2)
        if not actor:
            break

        if actor["side"] == 1:
            execute_unit_action(actor, t1, t2, logs, crit_bonus=p1_crit_bonus)
        else:
            if enemy_regen and actor["hp"] > 0 and actor["hp"] < actor["max_hp"]:
                reg = max(2, int(actor["max_hp"] * 0.05))
                actor["hp"] = min(actor["max_hp"], actor["hp"] + reg)
            execute_unit_action(actor, t2, t1, logs, crit_bonus=0.0)

        if not state["skip"]:
            board = render_battle_board(title, p1_name, t1, p2_name, t2, logs, round_num)
            for m in messages:
                await safe_edit_battle(m, board, kb)
            # Дробная пауза, чтобы мгновенно реагировать на «Пропустить» и «Сдаться»
            ticks = max(1, int(step_delay / 0.2))
            for _ in range(ticks):
                if state["skip"] or state["surrendered"]:
                    break
                await asyncio.sleep(0.2)

    # Если достигнут лимит ходов — побеждает сторона с большим % оставшегося HP
    rem1 = sum(u["hp"] for u in t1) / max(1, sum(u["max_hp"] for u in t1))
    rem2 = sum(u["hp"] for u in t2) / max(1, sum(u["max_hp"] for u in t2))
    return (1 if rem1 >= rem2 else 2), logs


async def build_pve_wave_enemies(boss: Dict[str, Any], wave_num: int, total_waves: int, mods: Dict[str, int]) -> List[Dict[str, Any]]:
    """Генерирует врагов для конкретной волны рейда (1..N-1 мобы, N — Босс + охрана)."""
    all_normal = [c for c in await db.list_cards() if not c["is_boss"]]
    hp_m = 1.5 if mods.get("mod_enemy_hp") else 1.0
    atk_m = 1.25 if mods.get("mod_enemy_atk") else 1.0

    enemies: List[Dict[str, Any]] = []
    if wave_num < total_waves:
        # Обычная волна: 2-3 врага, масштабированные под силу босса
        count = 2 if wave_num == 1 else 3
        pool = [c for c in all_normal if c["rarity"] in ("common", "rare", "epic")] or all_normal
        scale_hp = max(0.35, (boss["boss_hp"] / (count * 220)) * (0.65 + wave_num * 0.2))
        scale_atk = max(0.35, (boss["boss_atk"] / 65) * (0.60 + wave_num * 0.15))
        for _ in range(count):
            tpl = dict(random.choice(pool))
            tpl["hp"] = max(45, int(tpl["hp"] * scale_hp))
            tpl["atk"] = max(10, int(tpl["atk"] * scale_atk))
            enemies.append(build_combat_unit(tpl, side=2, hp_mult=hp_m, atk_mult=atk_m))
    else:
        # Финальная волна — БОСС + 1 охранник
        boss_tpl = dict(boss)
        boss_tpl["hp"] = max(120, boss["boss_hp"])
        boss_tpl["atk"] = max(18, boss["boss_atk"])
        enemies.append(build_combat_unit(boss_tpl, side=2, hp_mult=hp_m, atk_mult=atk_m, is_boss_unit=True))

        guards = [c for c in all_normal if c["rarity"] in ("common", "rare")] or all_normal
        if guards:
            g = dict(random.choice(guards))
            g["hp"] = max(60, int(boss["boss_hp"] * 0.22))
            g["atk"] = max(12, int(boss["boss_atk"] * 0.45))
            enemies.append(build_combat_unit(g, side=2, hp_mult=hp_m, atk_mult=atk_m))

    return enemies


async def generate_arena_bot_team(player_power: int) -> Tuple[str, List[Dict[str, Any]]]:
    """Генерирует сбалансированную команду AI-бота для Рейтинговой Арены."""
    bot_names = [
        "🤖 Отряд Скибиди-Альфа",
        "🤖 Патруль Камераменов",
        "🤖 Астро-Перехватчики",
        "🤖 Лаборатория Учёного",
        "🤖 Заражённый Легион",
    ]
    all_normal = [c for c in await db.list_cards() if not c["is_boss"]]
    if not all_normal:
        return "🤖 Бот-Страж", []

    count = random.choice([3, 4])
    chosen = [dict(random.choice(all_normal)) for _ in range(count)]
    raw_units = [build_combat_unit(c, side=2) for c in chosen]
    raw_power = sum(u["hp"] + u["atk"] * 4 for u in raw_units)
    target = max(300, int(player_power * random.uniform(0.88, 1.08)))
    factor = max(0.5, min(4.0, target / max(1, raw_power)))

    for u in raw_units:
        u["hp"] = max(50, int(u["hp"] * factor))
        u["max_hp"] = u["hp"]
        u["atk"] = max(12, int(u["atk"] * factor))

    return random.choice(bot_names), raw_units


# ==============================================================================
# 4. УНИВЕРСАЛЬНЫЙ РЕНДЕР И КЛАВИАТУРЫ
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
                await target.answer_photo(photo=photo, caption=text, reply_markup=reply_markup)
                return
            except TelegramBadRequest:
                pass
        await target.answer(text, reply_markup=reply_markup)
        return

    msg = target.message
    if not msg:
        return
    has_photo = bool(msg.photo)
    try:
        if photo:
            if has_photo:
                await msg.edit_caption(caption=text, reply_markup=reply_markup)
            else:
                try:
                    await msg.delete()
                except TelegramBadRequest:
                    pass
                await msg.answer_photo(photo=photo, caption=text, reply_markup=reply_markup)
        else:
            if has_photo:
                try:
                    await msg.delete()
                except TelegramBadRequest:
                    pass
                await msg.answer(text, reply_markup=reply_markup)
            else:
                await msg.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return
        try:
            await msg.answer(text, reply_markup=reply_markup)
        except Exception:
            pass


def main_reply_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🃏 Колода и Карты")],
        [KeyboardButton(text="👹 Рейды Волн"), KeyboardButton(text="🌐 Мультиплеер")],
        [KeyboardButton(text="🧪 Лаборатория и Кейсы"), KeyboardButton(text="🏆 Рейтинг")],
    ]
    if is_admin:
        rows.append([KeyboardButton(text="⚙️ Админ-панель")])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Выберите раздел в меню...",
    )


def format_card_text(card: Dict[str, Any], inv_item: Optional[Dict[str, Any]] = None) -> str:
    r_name, r_ico, _ = RARITIES.get(card["rarity"], ("Обычная", "⚪️", 1))
    f_name = FACTIONS.get(card["faction"], card["faction"])
    cls = card.get("class_type", "Single")
    cls_ico, cls_desc = CARD_CLASSES.get(cls, ("🎯", ""))

    if inv_item:
        st = calc_card_stats(inv_item)
        lvl = inv_item["level"]
        shiny_txt = f"✨ <b>Shiny (+{cfg_int('shiny_bonus_pct')}%)</b>" if inv_item["mutation"] == "shiny" else "Обычная"
        inf_name = INFECTED_TYPES.get(inv_item.get("infected_type", "none"), ("Нет", ""))[0]
        if inv_item.get("infected_type") == "normal":
            inf_name += f" (x{cfg_float('infected_normal_mult')})"
        elif inv_item.get("infected_type") == "astro":
            inf_name += f" (x{cfg_float('infected_astro_mult')})"
        sign_txt = get_sign_label(inv_item)
        deck_tag = f"✅ В колоде (Слот #{inv_item.get('deck_pos', 1)})" if inv_item["in_deck"] else "📦 В инвентаре"
        market_tag = " | 🏷 На рынке" if inv_item.get("market_id") else ""

        lines = [
            f"{r_ico} {cls_ico} <b>{esc(card['name'])}</b>  <i>(Ур. {lvl})</i>",
            f"Фракция: {f_name} | Редкость: {r_name}",
            f"Класс: <b>{cls}</b> — <i>{cls_desc}</i>",
            f"Мутация: {shiny_txt} | Заражение: <b>{inf_name}</b>",
            f"Сигна: {sign_txt}",
            f"Статус: {deck_tag}{market_tag}",
            "",
            f"❤️ HP: <b>{st['hp']}</b>   |   ⚔️ Урон: <b>{st['atk']}</b>   |   ⚡️ Скорость: <b>{st['speed']}x</b>",
        ]
        if cls == "Booster":
            lines.append(f"✨ Бафф отряду: Урон <b>x{st['booster_dmg_mult']}</b> | HP <b>x{st['booster_hp_mult']}</b>")
    else:
        lines = [
            f"{r_ico} {cls_ico} <b>{esc(card['name'])}</b>  [ID: <code>{card['id']}</code>]",
            f"Фракция: {f_name} | Редкость: {r_name} | Класс: <b>{cls}</b>",
            f"❤️ HP: <b>{card['hp']}</b>   |   ⚔️ Урон: <b>{card['atk']}</b>",
        ]
        if cls == "Booster":
            lines.append(f"✨ Бафф: Урон x{card.get('booster_dmg_mult', 1.15)} | HP x{card.get('booster_hp_mult', 1.15)}")
        if card.get("is_boss"):
            lines.append(
                f"👹 <b>БОСС РЕЙДА:</b> HP {card['boss_hp']} | ATK {card['boss_atk']} | 🦠 Баз. заражение: {card['infect_chance']}%"
            )
            lines.append(f"🔗 ID заражённой версии: <code>{card.get('infected_card_id', 0)}</code>")

    if card.get("description"):
        lines.append(f"\n📝 <i>{esc(card['description'])}</i>")
    return "\n".join(lines)


# ==============================================================================
# 5. MIDDLEWARE
# ==============================================================================

class AccessMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user and not tg_user.is_bot:
            user, _ = await db.ensure_user(tg_user.id, tg_user.username, tg_user.full_name)
            is_adm = await db.is_admin(tg_user.id)

            if user["is_banned"] and not is_adm:
                if isinstance(event, Message):
                    await event.answer("🚫 Ваш аккаунт заблокирован администрацией.")
                elif isinstance(event, CallbackQuery):
                    await event.answer("🚫 Вы заблокированы.", show_alert=True)
                return

            if GAME_SETTINGS.get("maintenance", "0") == "1" and not is_adm:
                if isinstance(event, Message):
                    await event.answer("🛠 <b>Идут технические работы!</b>\nБот скоро вернётся с обновлениями.")
                elif isinstance(event, CallbackQuery):
                    await event.answer("🛠 Идут техработы, попробуйте позже.", show_alert=True)
                return

            data["db_user"] = user
            data["is_admin"] = is_adm

        return await handler(event, data)


# ==============================================================================
# 6. FSM СОСТОЯНИЯ
# ==============================================================================

class CardCreateFSM(StatesGroup):
    name = State()
    faction = State()
    rarity = State()
    class_type = State()
    hp = State()
    atk = State()
    booster_mults = State()
    description = State()
    image = State()
    is_boss = State()
    boss_hp = State()
    boss_atk = State()
    infect_chance = State()
    infected_card_id = State()
    confirm = State()


class CardEditFSM(StatesGroup):
    waiting_value = State()


class CrateFSM(StatesGroup):
    name = State()
    description = State()
    price = State()
    weights = State()
    shiny_chance = State()
    edit_value = State()


class AdminFSM(StatesGroup):
    add_admin = State()
    add_signer = State()
    find_user = State()
    user_coins = State()
    broadcast = State()
    world_boss_hp = State()
    setting_value = State()


class PlayerFSM(StatesGroup):
    profile_search = State()
    market_price = State()
    pvp_bet = State()
    pvp_target = State()


# ==============================================================================
# 7. ОСНОВНЫЕ ОБРАБОТЧИКИ ИГРОКА
# ==============================================================================

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, is_admin: bool):
    await state.clear()
    _, is_new = await db.ensure_user(
        message.from_user.id, message.from_user.username, message.from_user.full_name
    )
    bonus_msg = (
        "\n\n🎁 <b>Стартовый набор выдан:</b> 3 юнита в колоде, 350 💰 и 2 🦠 паразита!"
        if is_new
        else ""
    )
    text = (
        f"🚽 <b>Skibidi Verse Tower Defense</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"• Проходи <b>волны рейдов</b> 4×4 и <b>заражай боссов</b> Обычным или Астро-паразитом!\n"
        f"• Лови редчайшие <b>✨ Shiny</b> версии (шанс {cfg_float('shiny_chance_pct')}%, +{cfg_int('shiny_bonus_pct')}% к статам) отовсюду.\n"
        f"• Сражайся на <b>PvP Арене</b> за кубки и лиги, вызывай друзей на живые дуэли и торгуй на P2P-рынке.{bonus_msg}\n\n"
        f"👇 Выбирай раздел в <b>статичном меню снизу</b>."
    )
    await message.answer(text, reply_markup=main_reply_keyboard(is_admin))


# -------------------- ПРОФИЛЬ И МОДИФИКАТОРЫ --------------------

async def build_profile_text(user: Dict[str, Any], is_self: bool = True) -> str:
    inv = await db.get_inventory(user["user_id"])
    deck = [c for c in inv if c["in_deck"]]
    summary = calc_deck_summary(deck)

    unique_cards = len({c["card_id"] for c in inv})
    shiny_cards = sum(1 for c in inv if c["mutation"] == "shiny")
    infected_cards = sum(1 for c in inv if c["infected_type"] != "none" or c["faction"] == "infected")
    total_pvp = user["pvp_wins"] + user["pvp_losses"]
    winrate = round((user["pvp_wins"] / total_pvp) * 100, 1) if total_pvp > 0 else 0.0
    total_inf = user["infections_success"] + user["infections_fail"]
    inf_rate = round((user["infections_success"] / total_inf) * 100, 1) if total_inf > 0 else 0.0
    reg_date = datetime.fromtimestamp(user["created_at"]).strftime("%d.%m.%Y") if user["created_at"] else "—"

    signer_role = await db.get_signer_role(user["user_id"])
    role_badge = ""
    if signer_role == "admin":
        role_badge = " | 👑 Админ-Сигнер"
    elif signer_role == "partner":
        role_badge = " | 🤝 Партнёр-Сигнер"

    syn_text = ", ".join(summary["synergies"]) if summary["synergies"] else "нет"
    header = "👤 <b>ВАШ ПРОФИЛЬ</b>" if is_self else "🔎 <b>ПРОФИЛЬ ИГРОКА</b>"

    return (
        f"{header}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🪪 {format_user_link(user)}{role_badge}\n"
        f"🏆 Лига: <b>{get_league(user['trophies'])}</b> (<b>{user['trophies']}</b> кубков)\n"
        f"📅 В игре с: <code>{reg_date}</code>\n\n"
        f"💰 Монеты: <b>{user['coins']}</b>\n"
        f"🦠 Паразиты: Обыч. <b>{user['p_common']}</b> | Улучш. <b>{user['p_upgraded']}</b> | Астро <b>{user['p_astro']}</b>\n\n"
        f"🛡 <b>Боевая колода ({len(deck)}/{MAX_DECK_SIZE}):</b>\n"
        f"   ⚡ Мощь: <b>{summary['power']}</b> (❤️ {summary['hp']} | ⚔️ {summary['atk']})\n"
        f"   🔗 Синергии: <i>{syn_text}</i>\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"   🃏 Карт: <b>{len(inv)}</b> (Уник: {unique_cards} | ✨Shiny: {shiny_cards} | 🦠Зар: {infected_cards})\n"
        f"   ⚔️ PvP: <b>{user['pvp_wins']}W / {user['pvp_losses']}L</b> ({winrate}%) | Серия Арены: {user['arena_streak']}🔥\n"
        f"   👹 Боссов: <b>{user['bosses_killed']}</b> | 🦠 Заражений: <b>{user['infections_success']}</b>/{total_inf} ({inf_rate}%)\n"
        f"   🎯 Пити заражения: <b>+{user['pity_bonus']}%</b> | 🔥 Входы: <b>{user['daily_streak']} дн.</b>"
    )


def profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎁 Ежедневный бонус", callback_data="prof:daily"),
                InlineKeyboardButton(text="🧬 Модификаторы PvE", callback_data="prof:mods"),
            ],
            [
                InlineKeyboardButton(text="🔎 Найти игрока", callback_data="prof:search"),
                InlineKeyboardButton(text="🔄 Обновить", callback_data="prof:refresh"),
            ],
        ]
    )


@router.message(F.text == "👤 Профиль")
async def menu_profile(message: Message, state: FSMContext, db_user: Dict[str, Any]):
    await state.clear()
    fresh = await db.get_user(db_user["user_id"])
    await message.answer(await build_profile_text(fresh, True), reply_markup=profile_kb())


@router.callback_query(F.data == "prof:refresh")
async def cb_prof_refresh(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    await render_view(callback, await build_profile_text(user, True), profile_kb())
    await callback.answer("Обновлено!")


@router.callback_query(F.data == "prof:daily")
async def cb_prof_daily(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    now = int(time.time())
    diff = now - user["last_daily"]
    if diff < DAILY_COOLDOWN:
        rem = DAILY_COOLDOWN - diff
        await callback.answer(f"⏳ Доступно через {rem // 3600}ч {(rem % 3600) // 60}м!", show_alert=True)
        return

    streak = user["daily_streak"] + 1 if diff < DAILY_COOLDOWN * 2 else 1
    coins_reward = int((150 + min(streak, 10) * 35) * cfg_float("event_coin_mult"))
    await db.update_user(user["user_id"], last_daily=now, daily_streak=streak)
    await db.add_coins(user["user_id"], coins_reward)

    if streak % 3 == 0:
        await db.add_parasite(user["user_id"], "upgraded", 1)
        extra = " + 1 ☣️ Улучш. паразит!"
    else:
        await db.add_parasite(user["user_id"], "common", 1)
        extra = " + 1 🦠 Обыч. паразит!"

    await callback.answer(f"🎁 +{coins_reward} 💰{extra} (День {streak})", show_alert=True)
    fresh = await db.get_user(user["user_id"])
    await render_view(callback, await build_profile_text(fresh, True), profile_kb())


@router.callback_query(F.data == "prof:search")
async def cb_prof_search(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PlayerFSM.profile_search)
    await callback.message.answer("🔎 Введите <b>@username</b> или <b>Telegram ID</b> игрока:")
    await callback.answer()


@router.message(PlayerFSM.profile_search)
async def fsm_prof_search(message: Message, state: FSMContext):
    await state.clear()
    target = await db.find_user(message.text or "")
    if not target:
        await message.answer("❌ Игрок не найден.")
        return
    await message.answer(await build_profile_text(target, is_self=(target["user_id"] == message.from_user.id)))


async def render_pve_mods(target: Message | CallbackQuery, user_id: int, back_cb: str = "prof:refresh"):
    u = await db.get_user(user_id)
    coin_bonus = sum(m[2] for k, m in PVE_MODIFIERS.items() if u.get(k))
    inf_bonus = sum(m[3] for k, m in PVE_MODIFIERS.items() if u.get(k))
    text = (
        f"🧬 <b>МОДИФИКАТОРЫ БОЯ (PvE РЕЙДЫ)</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Усложнения (🔴) увеличивают награду в монетах и <b>шанс заражения босса</b>!\n"
        f"Усиления (🟢) упрощают бой, но снижают монеты.\n\n"
        f"📊 Текущий итог: Монеты <b>{max(0.2, 1.0 + coin_bonus):.2f}x</b> | Шанс заражения: <b>+{inf_bonus}% 🦠</b>"
    )
    rows = []
    for k, (label, _, _, _) in PVE_MODIFIERS.items():
        ico = "✅" if u.get(k) else "❌"
        rows.append([InlineKeyboardButton(text=f"{ico} {label}", callback_data=f"pmod:{k}:{back_cb}")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data=back_cb)])
    await render_view(target, text, InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "prof:mods")
async def cb_prof_mods(callback: CallbackQuery):
    await render_pve_mods(callback, callback.from_user.id, "prof:refresh")
    await callback.answer()


@router.callback_query(F.data == "raid:mods")
async def cb_raid_mods(callback: CallbackQuery):
    await render_pve_mods(callback, callback.from_user.id, "raid:menu")
    await callback.answer()


@router.callback_query(F.data.startswith("pmod:"))
async def cb_pmod_toggle(callback: CallbackQuery):
    parts = callback.data.split(":", 2)
    mod_key, back_cb = parts[1], parts[2]
    if mod_key not in PVE_MODIFIERS:
        return
    u = await db.get_user(callback.from_user.id)
    nxt = 0 if u.get(mod_key) else 1
    await db.update_user(callback.from_user.id, **{mod_key: nxt})
    await render_pve_mods(callback, callback.from_user.id, back_cb)
    await callback.answer()


# -------------------- КОЛОДА, ИНВЕНТАРЬ И СИГНЫ --------------------

async def render_inventory_page(target: Message | CallbackQuery, user_id: int, page: int = 0):
    inv = await db.get_inventory(user_id)
    deck = [c for c in inv if c["in_deck"]]
    summary = calc_deck_summary(deck)

    per_page = 6
    total_pages = max(1, (len(inv) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    chunk = inv[page * per_page : (page + 1) * per_page]

    deck_lines = []
    for idx, c in enumerate(deck, 1):
        st = calc_card_stats(c)
        cls_ico = CARD_CLASSES.get(c["class_type"], ("🎯", ""))[0]
        sh = "✨" if c["mutation"] == "shiny" else ""
        inf = INFECTED_TYPES.get(c["infected_type"], ("", ""))[1]
        sgn = "👑" if c["sign_type"] == "admin" else ("🤝" if c["sign_type"] == "partner" else "")
        spd = f" ⚡️{st['speed']}x" if st["speed"] > 1.0 else ""
        role_hint = "🛡" if idx == 1 else ""
        deck_lines.append(
            f"{idx}.{role_hint} {cls_ico} <b>{esc(c['name'])}</b>{sh}{inf}{sgn} — ⚔️{st['atk']} | ❤️{st['hp']}{spd}"
        )

    text = (
        f"🃏 <b>КОЛОДА И ИНВЕНТАРЬ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚔️ <b>Колода ({len(deck)}/{MAX_DECK_SIZE}) | Мощь: {summary['power']}</b>\n"
        f"<i>Слот #1 — Фронт (принимает удары первым)</i>\n"
        + ("\n".join(deck_lines) if deck_lines else "<i>Колода пуста — выберите карты ниже!</i>")
        + f"\n\n📦 Всего карт: <b>{len(inv)}</b> | Стр. {page + 1}/{total_pages}"
    )

    buttons: List[List[InlineKeyboardButton]] = []
    for item in chunk:
        r_ico = RARITIES.get(item["rarity"], ("", "⚪️", 1))[1]
        mark = f"✅#{item['deck_pos']} " if item["in_deck"] else ("🏷 " if item.get("market_id") else "")
        sh = "✨" if item["mutation"] == "shiny" else ""
        inf = INFECTED_TYPES.get(item["infected_type"], ("", ""))[1]
        sgn = "✍️" if item["sign_type"] != "none" else ""
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{mark}{r_ico}{sh}{inf}{sgn} {item['name']} (Ур.{item['level']})",
                    callback_data=f"inv:view:{item['inv_id']}:{page}",
                )
            ]
        )

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"inv:page:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"📄 {page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"inv:page:{page + 1}"))
    buttons.append(nav)

    await render_view(target, text, InlineKeyboardMarkup(inline_keyboard=buttons))


async def render_inv_item_view(target: Message | CallbackQuery, user_id: int, inv_id: int, page: int):
    item = await db.get_inv_item(inv_id)
    if not item or item["user_id"] != user_id:
        await render_inventory_page(target, user_id, page)
        return

    upgrade_cost = 120 * item["level"]
    text = format_card_text(item, inv_item=item)
    text += f"\n\n⬆️ Прокачка до Ур.{item['level'] + 1}: <b>{upgrade_cost} 💰</b> (+10% статов)"

    kb_rows = []
    if not item.get("market_id"):
        deck_btn = (
            InlineKeyboardButton(text="➖ Из колоды", callback_data=f"inv:deck:{inv_id}:0:{page}")
            if item["in_deck"]
            else InlineKeyboardButton(text="➕ В колоду", callback_data=f"inv:deck:{inv_id}:1:{page}")
        )
        kb_rows.append([deck_btn, InlineKeyboardButton(text=f"⬆️ Улучшить ({upgrade_cost}💰)", callback_data=f"inv:upg:{inv_id}:{page}")])
        if item["in_deck"]:
            kb_rows.append(
                [
                    InlineKeyboardButton(text="⬆️ Слот выше", callback_data=f"inv:move:{inv_id}:up:{page}"),
                    InlineKeyboardButton(text="⬇️ Слот ниже", callback_data=f"inv:move:{inv_id}:down:{page}"),
                ]
            )
        signer_role = await db.get_signer_role(user_id)
        if signer_role:
            lbl = "👑 Подписать (Админ)" if signer_role == "admin" else "🤝 Подписать (Партнёр)"
            kb_rows.append([InlineKeyboardButton(text=lbl, callback_data=f"sign:open:{inv_id}:{page}")])
        kb_rows.append([InlineKeyboardButton(text="🏷 Выставить на Рынок", callback_data=f"inv:sell:{inv_id}")])
    else:
        kb_rows.append([InlineKeyboardButton(text="🏷 Карта выставлена на рынке", callback_data="noop")])

    kb_rows.append([InlineKeyboardButton(text="🔙 К инвентарю", callback_data=f"inv:page:{page}")])
    await render_view(target, text, InlineKeyboardMarkup(inline_keyboard=kb_rows), photo=item.get("image_id") or None)


@router.message(F.text == "🃏 Колода и Карты")
async def menu_inventory(message: Message, state: FSMContext):
    await state.clear()
    await render_inventory_page(message, message.from_user.id, 0)


@router.callback_query(F.data.startswith("inv:page:"))
async def cb_inv_page(callback: CallbackQuery):
    await render_inventory_page(callback, callback.from_user.id, int(callback.data.split(":")[2]))
    await callback.answer()


@router.callback_query(F.data.startswith("inv:view:"))
async def cb_inv_view(callback: CallbackQuery):
    _, _, inv_id_s, page_s = callback.data.split(":")
    await render_inv_item_view(callback, callback.from_user.id, int(inv_id_s), int(page_s))
    await callback.answer()


@router.callback_query(F.data.startswith("inv:deck:"))
async def cb_inv_deck(callback: CallbackQuery):
    _, _, inv_id_s, mode_s, page_s = callback.data.split(":")
    inv_id, mode, page = int(inv_id_s), int(mode_s), int(page_s)
    uid = callback.from_user.id
    item = await db.get_inv_item(inv_id)
    if not item or item["user_id"] != uid:
        await callback.answer("Ошибка доступа.", show_alert=True)
        return
    if mode == 1:
        if item.get("market_id"):
            await callback.answer("Сначала снимите карту с рынка!", show_alert=True)
            return
        deck = await db.get_inventory(uid, only_deck=True)
        if len(deck) >= MAX_DECK_SIZE:
            await callback.answer(f"В колоде максимум {MAX_DECK_SIZE} карты!", show_alert=True)
            return
    await db.set_in_deck(uid, inv_id, mode)
    await callback.answer("✅ В колоде!" if mode else "📦 Убрано.")
    await render_inv_item_view(callback, uid, inv_id, page)


@router.callback_query(F.data.startswith("inv:move:"))
async def cb_inv_move(callback: CallbackQuery):
    _, _, inv_id_s, direction, page_s = callback.data.split(":")
    ok = await db.move_deck_slot(callback.from_user.id, int(inv_id_s), direction)
    await callback.answer("Позиция изменена!" if ok else "Дальше двигать нельзя.")
    await render_inv_item_view(callback, callback.from_user.id, int(inv_id_s), int(page_s))


@router.callback_query(F.data.startswith("inv:upg:"))
async def cb_inv_upgrade(callback: CallbackQuery):
    _, _, inv_id_s, page_s = callback.data.split(":")
    inv_id, page = int(inv_id_s), int(page_s)
    uid = callback.from_user.id
    item = await db.get_inv_item(inv_id)
    if not item or item["user_id"] != uid:
        await callback.answer("Карта не найдена.", show_alert=True)
        return
    if item["level"] >= 20:
        await callback.answer("Максимум 20 уровень!", show_alert=True)
        return
    cost = 120 * item["level"]
    user = await db.get_user(uid)
    if user["coins"] < cost:
        await callback.answer(f"Нужно {cost} 💰!", show_alert=True)
        return
    await db.add_coins(uid, -cost)
    await db.upgrade_inv_card(inv_id)
    await callback.answer(f"⬆️ Уровень {item['level'] + 1}!", show_alert=True)
    await render_inv_item_view(callback, uid, inv_id, page)


@router.callback_query(F.data.startswith("sign:open:"))
async def cb_sign_open(callback: CallbackQuery):
    _, _, inv_id_s, page_s = callback.data.split(":")
    inv_id, page = int(inv_id_s), int(page_s)
    uid = callback.from_user.id
    role = await db.get_signer_role(uid)
    if not role:
        await callback.answer("У вас нет прав Сигнера!", show_alert=True)
        return
    item = await db.get_inv_item(inv_id)
    if not item or item["user_id"] != uid:
        await callback.answer("Карта не найдена.", show_alert=True)
        return

    pct = cfg_int("admin_sign_pct") if role == "admin" else cfg_int("partner_sign_pct")
    role_title = "👑 Админ-сигна" if role == "admin" else "🤝 Партнёр-сигна"
    text = (
        f"✍️ <b>{role_title}</b> для <b>{esc(item['name'])}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Выберите усиление, которое даст подпись:\n"
        f"• ⚔️ <b>+{pct}% к урону</b>\n"
        f"• ⚡️ <b>+{pct}% к скорости атаки</b> (бьёт чаще в 4×4 боях)"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"⚔️ +{pct}% Урон", callback_data=f"sign:apply:{inv_id}:{role}:power:{page}"),
                InlineKeyboardButton(text=f"⚡️ +{pct}% Скорость", callback_data=f"sign:apply:{inv_id}:{role}:speed:{page}"),
            ],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"inv:view:{inv_id}:{page}")],
        ]
    )
    await render_view(callback, text, kb)
    await callback.answer()


@router.callback_query(F.data.startswith("sign:apply:"))
async def cb_sign_apply(callback: CallbackQuery):
    _, _, inv_id_s, role, stat, page_s = callback.data.split(":")
    inv_id, page = int(inv_id_s), int(page_s)
    uid = callback.from_user.id
    actual_role = await db.get_signer_role(uid)
    if actual_role != role and actual_role != "admin":
        await callback.answer("Нет прав на эту сигну!", show_alert=True)
        return
    item = await db.get_inv_item(inv_id)
    if not item or item["user_id"] != uid:
        await callback.answer("Карта не найдена.", show_alert=True)
        return
    u = await db.get_user(uid)
    who = f"@{u['username']}" if u and u.get("username") else (u["full_name"] if u else str(uid))
    await db.sign_inv_card(inv_id, role, stat, who)
    await callback.answer("✍️ Карта успешно подписана!", show_alert=True)
    await render_inv_item_view(callback, uid, inv_id, page)


@router.callback_query(F.data.startswith("inv:sell:"))
async def cb_inv_sell(callback: CallbackQuery, state: FSMContext):
    inv_id = int(callback.data.split(":")[2])
    item = await db.get_inv_item(inv_id)
    if not item or item["user_id"] != callback.from_user.id or item.get("market_id"):
        await callback.answer("Карта недоступна.", show_alert=True)
        return
    await state.set_state(PlayerFSM.market_price)
    await state.update_data(sell_inv_id=inv_id)
    await callback.message.answer(f"🏷 Введите цену для <b>{esc(item['name'])}</b> (50 — 500000 💰):")
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
        await message.answer("❌ Введите число от 50 до 500000.")
        return
    item = await db.get_inv_item(inv_id)
    if not item or item["user_id"] != message.from_user.id or item.get("market_id"):
        await message.answer("❌ Карта больше недоступна.")
        return
    await db.create_market_lot(message.from_user.id, inv_id, price)
    await message.answer(f"✅ <b>{esc(item['name'])}</b> выставлена на P2P-рынок за <b>{price} 💰</b>!")


# -------------------- РЕЙДЫ ПО ВОЛНАМ И ФАЗА ЗАРАЖЕНИЯ --------------------

async def render_raids_menu(target: Message | CallbackQuery, user_id: int):
    bosses = await db.list_cards(only_bosses=True)
    if not bosses:
        await render_view(target, "👹 Пока нет доступных боссов. Админ может создать их в Админ-панели!")
        return
    u = await db.get_user(user_id)
    waves = cfg_int("raid_waves")
    mod_inf = sum(m[3] for k, m in PVE_MODIFIERS.items() if u.get(k))
    text = (
        f"👹 <b>РЕЙДЫ ПО ВОЛНАМ (Skibidi TD + Заражение)</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Пробей <b>{waves} волны</b> врагов на автобое 4×4, добей Босса и запусти паразита!\n"
        f"🎯 Пити заражения: <b>+{u['pity_bonus']}%</b> | Моды: <b>+{mod_inf}% 🦠</b>\n"
        f"✨ Шанс Shiny при заражении: <b>{cfg_float('shiny_chance_pct')}%</b>\n\n"
        f"Выберите рейд:"
    )
    rows = []
    for b in bosses:
        r_ico = RARITIES.get(b["rarity"], ("", "⚪️", 1))[1]
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{r_ico} {b['name']} (HP {b['boss_hp']} | 🦠{b['infect_chance']}%)",
                    callback_data=f"raid:start:{b['id']}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="🧬 Модификаторы боя (Бонус 🦠)", callback_data="raid:mods")])
    await render_view(target, text, InlineKeyboardMarkup(inline_keyboard=rows))


@router.message(F.text == "👹 Рейды Волн")
async def menu_raids(message: Message, state: FSMContext):
    await state.clear()
    await render_raids_menu(message, message.from_user.id)


@router.callback_query(F.data == "raid:menu")
async def cb_raid_menu(callback: CallbackQuery):
    await render_raids_menu(callback, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data.startswith("btl:skip:"))
async def cb_battle_skip(callback: CallbackQuery):
    bid = callback.data.split(":")[2]
    st = ACTIVE_BATTLES.get(bid)
    if not st or callback.from_user.id not in st["participants"]:
        await callback.answer("Бой уже завершён.")
        return
    st["skip"] = True
    await callback.answer("⏩ Перематываем к итогам...")


@router.callback_query(F.data.startswith("btl:surr:"))
async def cb_battle_surr(callback: CallbackQuery):
    bid = callback.data.split(":")[2]
    st = ACTIVE_BATTLES.get(bid)
    if not st or callback.from_user.id not in st["participants"]:
        await callback.answer("Бой уже завершён.")
        return
    st["surrendered"].add(callback.from_user.id)
    await callback.answer("🏳️ Вы сдались!", show_alert=True)


@router.callback_query(F.data.startswith("raid:start:"))
async def cb_raid_start(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid in USERS_IN_BATTLE:
        await callback.answer("Вы уже участвуете в бою!", show_alert=True)
        return
    boss_id = int(callback.data.split(":")[2])
    boss = await db.get_card(boss_id)
    if not boss or not boss["is_boss"]:
        await callback.answer("Босс не найден!", show_alert=True)
        return
    deck = await db.get_inventory(uid, only_deck=True)
    if not deck:
        await callback.answer("Поставьте хотя бы 1 карту в колоду!", show_alert=True)
        return

    USERS_IN_BATTLE.add(uid)
    await callback.answer("🌊 Выдвигаемся на волны!")
    asyncio.create_task(run_pve_wave_raid_task(callback.message, uid, boss, deck))


async def run_pve_wave_raid_task(origin_msg: Message, uid: int, boss: Dict[str, Any], deck: List[Dict[str, Any]]):
    battle_id = uuid.uuid4().hex[:10]
    ACTIVE_BATTLES[battle_id] = {"skip": False, "surrendered": set(), "participants": {uid}}
    try:
        user = await db.get_user(uid)
        mods = {k: user.get(k, 0) for k in PVE_MODIFIERS}
        total_waves = max(1, cfg_int("raid_waves"))
        p_hp_mult = 1.3 if mods.get("mod_player_hp") else 1.0
        p_crit_bonus = 0.20 if mods.get("mod_player_crit") else 0.0
        e_regen = bool(mods.get("mod_enemy_regen"))

        p_team = [build_combat_unit(c, side=1, hp_mult=p_hp_mult) for c in deck]
        # Баффы колоды игрока применяем 1 раз на весь забег по волнам
        init_log: List[str] = []
        apply_team_start_buffs(p_team, user["full_name"], init_log)

        battle_msg = await origin_msg.answer(
            f"🌊 <b>РЕЙД: {esc(boss['name'])}</b>\n⏳ Подготовка к Волне 1/{total_waves}..."
        )

        survived_all = True
        for wave in range(1, total_waves + 1):
            if wave > 1:
                # Небольшое восстановление (+20% HP) живым юнитам между волнами
                for u in p_team:
                    if u["hp"] > 0:
                        u["hp"] = min(u["max_hp"], u["hp"] + int(u["max_hp"] * 0.20))
                        u["burn"] = 0
                        u["stunned"] = False
                        u["gauge"] = 0.0

            enemies = await build_pve_wave_enemies(boss, wave, total_waves, mods)
            wave_label = f"👑 ВОЛНА {wave}/{total_waves} — БОСС" if wave == total_waves else f"🌊 ВОЛНА {wave}/{total_waves}"
            enemy_title = boss["name"] if wave == total_waves else f"Отряд Скибиди (Волна {wave})"

            # Если игрок нажал «Пропустить» на волне, весь рейд доигрывается быстро
            winner, _ = await run_live_skirmish(
                messages=[battle_msg],
                battle_id=battle_id,
                title=wave_label,
                p1_id=uid,
                p1_name=user["full_name"],
                t1=p_team,
                p2_id=0,
                p2_name=enemy_title,
                t2=enemies,
                p1_crit_bonus=p_crit_bonus,
                enemy_regen=e_regen,
                apply_start_buffs=False,
            )
            if winner != 1:
                survived_all = False
                await safe_edit_battle(
                    battle_msg,
                    f"💀 <b>ПОРАЖЕНИЕ НА ВОЛНЕ {wave}/{total_waves}!</b>\n"
                    f"Отряд не выдержал натиск в рейде <b>{esc(boss['name'])}</b>.\n\n"
                    f"💡 Совет: поставьте Хилера/Бустера, прокачайте карты или проверьте слот #1 (Танк).",
                )
                break

            if wave < total_waves and not ACTIVE_BATTLES[battle_id]["skip"]:
                await safe_edit_battle(
                    battle_msg,
                    f"✅ <b>ВОЛНА {wave}/{total_waves} ЗАЧИЩЕНА!</b>\n"
                    f"💗 Живые юниты восстановили +20% HP. Готовимся к следующей волне...",
                )
                await asyncio.sleep(1.3)

        if survived_all:
            mod_coin_delta = sum(m[2] for k, m in PVE_MODIFIERS.items() if mods.get(k))
            mod_inf_delta = sum(m[3] for k, m in PVE_MODIFIERS.items() if mods.get(k))
            coin_mult = max(0.2, 1.0 + mod_coin_delta) * cfg_float("event_coin_mult")
            coin_reward = max(60, int((boss["boss_hp"] // 4) * coin_mult))

            await db.add_coins(uid, coin_reward)
            fresh_u = await db.get_user(uid)
            await db.update_user(uid, bosses_killed=fresh_u["bosses_killed"] + 1)

            PENDING_INFECTIONS[uid] = {
                "boss_id": boss["id"],
                "boss_name": boss["name"],
                "boss_image": boss.get("image_id") or "",
                "base_chance": boss["infect_chance"],
                "mod_bonus": mod_inf_delta,
                "infected_card_id": boss["infected_card_id"],
            }

            kb_rows = []
            for p_key in ("common", "upgraded", "astro"):
                p_name, p_col, inf_t, _, p_bonus = get_parasite_info(p_key)
                cnt = fresh_u[p_col]
                total_ch = min(95, boss["infect_chance"] + p_bonus + fresh_u["pity_bonus"] + mod_inf_delta)
                tag = "🌌Астро" if inf_t == "astro" else "🦠Обыч."
                kb_rows.append(
                    [
                        InlineKeyboardButton(
                            text=f"{p_name} ({cnt} шт.) — {total_ch}% [{tag}]",
                            callback_data=f"raid:inf:{p_key}",
                        )
                    ]
                )
            kb_rows.append([InlineKeyboardButton(text="❌ Пропустить заражение", callback_data="raid:inf:skip")])

            win_text = (
                f"🏆 <b>ВСЕ {total_waves} ВОЛНЫ ПРОЙДЕНЫ! БОСС ПОВЕРЖЕН!</b>\n"
                f"👑 Цель: <b>{esc(boss['name'])}</b>\n"
                f"💰 Награда: <b>+{coin_reward} монет</b>\n\n"
                f"🦠 <b>ФАЗА ЗАРАЖЕНИЯ ОТКРЫТА!</b>\n"
                f"База: {boss['infect_chance']}% + Пити: +{fresh_u['pity_bonus']}% + Моды: +{mod_inf_delta}%\n"
                f"• Обыч./Улучш. паразит ➔ <b>🦠 Инфектед (x{cfg_float('infected_normal_mult')})</b>\n"
                f"• Астро-паразит ➔ <b>🌌 Астро-Инфектед (x{cfg_float('infected_astro_mult')})</b>\n"
                f"• Шанс ✨ Shiny: <b>{cfg_float('shiny_chance_pct')}%</b>"
            )
            await safe_edit_battle(battle_msg, win_text, InlineKeyboardMarkup(inline_keyboard=kb_rows))

    except Exception as exc:
        logger.exception("Raid error: %s", exc)
    finally:
        ACTIVE_BATTLES.pop(battle_id, None)
        USERS_IN_BATTLE.discard(uid)


@router.callback_query(F.data.startswith("raid:inf:"))
async def cb_raid_infect(callback: CallbackQuery):
    uid = callback.from_user.id
    inf_data = PENDING_INFECTIONS.get(uid)
    if not inf_data:
        await callback.answer("Фаза заражения уже завершена.", show_alert=True)
        return

    p_key = callback.data.split(":")[2]
    if p_key == "skip":
        PENDING_INFECTIONS.pop(uid, None)
        await render_view(callback, "💨 Вы забрали монеты и отступили без заражения.")
        await callback.answer()
        return

    if p_key not in PARASITES_META:
        return

    p_name, p_col, inf_type, _, p_bonus = get_parasite_info(p_key)
    user = await db.get_user(uid)
    if user[p_col] <= 0:
        await callback.answer(f"У вас нет «{p_name}»! Купите в Лаборатории.", show_alert=True)
        return

    PENDING_INFECTIONS.pop(uid, None)
    await db.add_parasite(uid, p_key, -1)

    total_chance = min(95, inf_data["base_chance"] + p_bonus + user["pity_bonus"] + inf_data["mod_bonus"])
    roll = random.randint(1, 100)

    if roll <= total_chance:
        target_cid = inf_data["infected_card_id"]
        reward_card = (await db.get_card(target_cid) if target_cid else None) or await db.get_card(inf_data["boss_id"])
        shiny = roll_shiny()

        await db.give_card(uid, reward_card["id"], mutation=shiny, infected_type=inf_type)
        await db.update_user(uid, infections_success=user["infections_success"] + 1, pity_bonus=0)

        inf_mult = cfg_float("infected_astro_mult") if inf_type == "astro" else cfg_float("infected_normal_mult")
        inf_label = INFECTED_TYPES[inf_type][0]
        shiny_line = f"\n✨ <b>НЕВЕРОЯТНО! ВЫПАЛ SHINY (+{cfg_int('shiny_bonus_pct')}%)!</b>" if shiny == "shiny" else ""

        text = (
            f"🦠💥 <b>УСПЕШНОЕ ЗАРАЖЕНИЕ!</b> (Шанс {total_chance}%)\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎁 Получена карта: <b>{esc(reward_card['name'])}</b>\n"
            f"🧬 Тип заражения: <b>{inf_label} (x{inf_mult} к статам)</b>{shiny_line}\n\n"
            f"<i>Поставьте нового титана в «🃏 Колода и Карты»!</i>"
        )
        await render_view(callback, text, photo=reward_card.get("image_id") or None)
        await callback.answer("🦠 ЗАРАЖЁН!", show_alert=True)
    else:
        new_pity = min(35, user["pity_bonus"] + 3)
        await db.update_user(uid, infections_fail=user["infections_fail"] + 1, pity_bonus=new_pity)
        await render_view(
            callback,
            f"💔 <b>ЗАРАЖЕНИЕ ПРОВАЛИЛОСЬ...</b> (Шанс {total_chance}%, выпало {roll})\n"
            f"{esc(inf_data['boss_name'])} сбросил паразита!\n\n"
            f"🎯 Пити увеличен до <b>+{new_pity}%</b> на следующую попытку.",
        )
        await callback.answer("Неудача, Пити вырос!")


# -------------------- МУЛЬТИПЛЕЕР (АРЕНА, ЖИВЫЕ ДУЭЛИ, МИРОВОЙ БОСС, РЫНОК) --------------------

def mp_hub_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏟 Рейтинговая Арена 4×4 (Кубки)", callback_data="pvp:arena")],
            [InlineKeyboardButton(text="⚔️ Живые PvP Дуэли и Ставки", callback_data="mp:pvp")],
            [InlineKeyboardButton(text="🌍 Мировой Босс (Общий рейд)", callback_data="mp:wb")],
            [InlineKeyboardButton(text="🏪 P2P Рынок игроков", callback_data="mp:market:0")],
        ]
    )


@router.message(F.text == "🌐 Мультиплеер")
async def menu_multiplayer(message: Message, state: FSMContext):
    await state.clear()
    wb = await db.get_active_world_boss()
    wb_st = f"🟢 АКТИВЕН ({wb['name']} — {wb['current_hp']} HP)" if wb else "⚪️ Спит"
    u = await db.get_user(message.from_user.id)
    text = (
        f"🌐 <b>МУЛЬТИПЛЕЕР ХАБ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🏆 Твоя лига: <b>{get_league(u['trophies'])}</b> ({u['trophies']} 🏆)\n"
        f"🌍 Мировой Босс: {wb_st}\n\n"
        f"• <b>🏟 Рейтинговая Арена:</b> мгновенный живой бой 4×4 против колод других игроков (Призраков) или AI-ботов за кубки и паразитов.\n"
        f"• <b>⚔️ Живые Дуэли:</b> прямой бой с другим игроком в реальном времени со ставками.\n"
        f"• <b>🏪 P2P Рынок:</b> продажа и покупка редких Shiny и заражённых карт."
    )
    await message.answer(text, reply_markup=mp_hub_kb())


@router.callback_query(F.data == "mp:hub")
async def cb_mp_hub(callback: CallbackQuery):
    u = await db.get_user(callback.from_user.id)
    wb = await db.get_active_world_boss()
    wb_st = f"🟢 {wb['name']} ({wb['current_hp']} HP)" if wb else "⚪️ Спит"
    await render_view(
        callback,
        f"🌐 <b>МУЛЬТИПЛЕЕР ХАБ</b>\n🏆 {get_league(u['trophies'])} ({u['trophies']} 🏆) | 🌍 Босс: {wb_st}",
        mp_hub_kb(),
    )
    await callback.answer()


# --- РЕЙТИНГОВАЯ АРЕНА 4x4 (ПРИЗРАКИ ИГРОКОВ + AI БОТЫ) ---

@router.callback_query(F.data == "pvp:arena")
async def cb_pvp_arena(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid in USERS_IN_BATTLE:
        await callback.answer("Вы уже в бою!", show_alert=True)
        return
    deck = await db.get_inventory(uid, only_deck=True)
    if not deck:
        await callback.answer("Сначала соберите колоду!", show_alert=True)
        return

    USERS_IN_BATTLE.add(uid)
    await callback.answer("🏟 Подбираем соперника...")
    asyncio.create_task(run_arena_battle_task(callback.message, uid, deck))


async def run_arena_battle_task(origin_msg: Message, uid: int, deck: List[Dict[str, Any]]):
    battle_id = uuid.uuid4().hex[:10]
    ACTIVE_BATTLES[battle_id] = {"skip": False, "surrendered": set(), "participants": {uid}}
    try:
        user = await db.get_user(uid)
        summary = calc_deck_summary(deck)
        t1 = [build_combat_unit(c, side=1) for c in deck]

        # 65% шанс подобрать реальную колоду-призрак другого игрока, иначе AI-бота
        ghost = await db.find_ghost_opponent(uid, user["trophies"])
        if ghost and random.random() < 0.70:
            g_deck = await db.get_inventory(ghost["user_id"], only_deck=True)
            opp_name = f"{ghost['full_name']} (👻 {ghost['trophies']}🏆)"
            t2 = [build_combat_unit(c, side=2) for c in g_deck]
        else:
            opp_name, t2 = await generate_arena_bot_team(summary["power"])

        if not t2:
            await origin_msg.answer("❌ Не удалось сгенерировать соперника.")
            return

        msg = await origin_msg.answer(f"🏟 <b>АРЕНА 4×4:</b> {esc(user['full_name'])} vs {esc(opp_name)}...")
        winner, _ = await run_live_skirmish(
            messages=[msg],
            battle_id=battle_id,
            title="🏟 АРЕНА 4×4",
            p1_id=uid,
            p1_name=user["full_name"],
            t1=t1,
            p2_id=0,
            p2_name=opp_name,
            t2=t2,
        )

        if winner == 1:
            trophies_gain = random.randint(16, 24)
            coins_gain = int(random.randint(60, 110) * cfg_float("event_coin_mult"))
            new_streak = user["arena_streak"] + 1
            await db.add_trophies(uid, trophies_gain)
            await db.add_coins(uid, coins_gain)
            await db.update_user(uid, pvp_wins=user["pvp_wins"] + 1, arena_streak=new_streak)

            streak_bonus = ""
            if new_streak % 5 == 0:
                await db.add_parasite(uid, "upgraded", 1)
                streak_bonus = "\n🔥 <b>СЕРИЯ 5 ПОБЕД!</b> Бонус: +1 ☣️ Улучшенный паразит!"
            elif new_streak % 3 == 0:
                await db.add_parasite(uid, "common", 1)
                streak_bonus = "\n🔥 <b>СЕРИЯ 3 ПОБЕД!</b> Бонус: +1 🦠 Обычный паразит!"

            res_text = (
                f"🏆 <b>ПОБЕДА НА АРЕНЕ!</b>\n"
                f"Соперник: <b>{esc(opp_name)}</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🏆 Кубки: <b>+{trophies_gain}</b> (Всего: {user['trophies'] + trophies_gain})\n"
                f"💰 Награда: <b>+{coins_gain} монет</b>\n"
                f"🔥 Серия побед: <b>{new_streak}</b>{streak_bonus}"
            )
        else:
            trophies_loss = random.randint(8, 12)
            await db.add_trophies(uid, -trophies_loss)
            await db.update_user(uid, pvp_losses=user["pvp_losses"] + 1, arena_streak=0)
            res_text = (
                f"💀 <b>ПОРАЖЕНИЕ НА АРЕНЕ</b>\n"
                f"Соперник: <b>{esc(opp_name)}</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🏆 Потеряно кубков: <b>-{trophies_loss}</b>\n"
                f"💡 Попробуйте поменять порядок слотов в колоде или улучшить карты!"
            )

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="🏟 Ещё бой!", callback_data="pvp:arena"),
                    InlineKeyboardButton(text="🔙 В Мультиплеер", callback_data="mp:hub"),
                ]
            ]
        )
        await safe_edit_battle(msg, res_text, kb)
    except Exception as exc:
        logger.exception("Arena error: %s", exc)
    finally:
        ACTIVE_BATTLES.pop(battle_id, None)
        USERS_IN_BATTLE.discard(uid)


# --- ЖИВЫЕ PvP ДУЭЛИ И СТАВКИ ---

async def render_pvp_lobby(target: Message | CallbackQuery, user_id: int):
    challenges = await db.list_open_pvp(user_id)
    text = (
        f"⚔️ <b>ЖИВЫЕ PvP ДУЭЛИ 4×4</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Прими вызов и наблюдай живой бой одновременно с соперником!\n"
        f"Активных вызовов: <b>{len(challenges)}</b>"
    )
    rows = [
        [
            InlineKeyboardButton(text="➕ Открытый вызов", callback_data="pvp:new:open"),
            InlineKeyboardButton(text="🎯 Вызов @игроку", callback_data="pvp:new:direct"),
        ]
    ]
    for ch in challenges[:8]:
        is_mine = ch["creator_id"] == user_id
        bet_str = f"💰{ch['bet']}" if ch["bet"] > 0 else "Дружеский"
        tag = "🎯" if ch["target_id"] else ""
        if is_mine:
            rows.append([InlineKeyboardButton(text=f"❌ Отменить свой ({tag}{bet_str})", callback_data=f"pvp:cancel:{ch['id']}")])
        else:
            cname = ch["full_name"] or "Игрок"
            rows.append([InlineKeyboardButton(text=f"⚔️ {tag}{cname} ({ch['trophies']}🏆) | {bet_str}", callback_data=f"pvp:accept:{ch['id']}")])
    rows.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="mp:pvp"), InlineKeyboardButton(text="🔙 Назад", callback_data="mp:hub")])
    await render_view(target, text, InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "mp:pvp")
async def cb_pvp_lobby(callback: CallbackQuery):
    await render_pvp_lobby(callback, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data.startswith("pvp:new:"))
async def cb_pvp_new(callback: CallbackQuery, state: FSMContext):
    mode = callback.data.split(":")[2]
    if not await db.get_inventory(callback.from_user.id, only_deck=True):
        await callback.answer("Соберите колоду!", show_alert=True)
        return
    await state.update_data(pvp_mode=mode, pvp_target_id=0)
    if mode == "direct":
        await state.set_state(PlayerFSM.pvp_target)
        await callback.message.answer("🎯 Введите <b>@username</b> или <b>ID</b> соперника:")
    else:
        await state.set_state(PlayerFSM.pvp_bet)
        await callback.message.answer("💰 Введите ставку в монетах (или <b>0</b> для дружеской дуэли):")
    await callback.answer()


@router.message(PlayerFSM.pvp_target)
async def fsm_pvp_target(message: Message, state: FSMContext):
    target = await db.find_user(message.text or "")
    if not target or target["user_id"] == message.from_user.id:
        await state.clear()
        await message.answer("❌ Соперник не найден.")
        return
    await state.update_data(pvp_target_id=target["user_id"])
    await state.set_state(PlayerFSM.pvp_bet)
    await message.answer(f"🎯 Соперник: {format_user_link(target)}.\n💰 Введите ставку (или <b>0</b>):")


@router.message(PlayerFSM.pvp_bet)
async def fsm_pvp_bet(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    try:
        bet = int((message.text or "").strip())
        if not (0 <= bet <= 100000):
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите число от 0 до 100000.")
        return
    user = await db.get_user(message.from_user.id)
    if user["coins"] < bet:
        await message.answer(f"❌ Недостаточно монет (у вас {user['coins']} 💰).")
        return
    target_id = data.get("pvp_target_id", 0)
    ch_id = await db.create_pvp_challenge(user["user_id"], target_id, bet)
    if target_id:
        try:
            await bot.send_message(
                target_id,
                f"⚔️ <b>ВЫЗОВ НА ЖИВУЮ PvP-ДУЭЛЬ 4×4!</b>\nСоперник: {format_user_link(user)}\n💰 Ставка: <b>{bet} монет</b>",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="⚔️ Принять бой!", callback_data=f"pvp:accept:{ch_id}")]]
                ),
            )
        except Exception:
            pass
        await message.answer(f"✅ Личный вызов отправлен! Ставка: <b>{bet} 💰</b>.")
    else:
        await message.answer(f"✅ Открытый вызов создан! Ставка: <b>{bet} 💰</b>.")


@router.callback_query(F.data.startswith("pvp:cancel:"))
async def cb_pvp_cancel(callback: CallbackQuery):
    ch_id = int(callback.data.split(":")[2])
    ch = await db.get_pvp_challenge(ch_id)
    if ch and ch["creator_id"] == callback.from_user.id and ch["status"] == "open":
        await db.close_pvp_challenge(ch_id, "cancelled")
        await callback.answer("❌ Отменено.")
    await render_pvp_lobby(callback, callback.from_user.id)


@router.callback_query(F.data.startswith("pvp:accept:"))
async def cb_pvp_accept(callback: CallbackQuery, bot: Bot):
    ch_id = int(callback.data.split(":")[2])
    ch = await db.get_pvp_challenge(ch_id)
    uid = callback.from_user.id
    if not ch or ch["status"] != "open":
        await callback.answer("Вызов неактуален.", show_alert=True)
        return
    if ch["creator_id"] == uid or (ch["target_id"] and ch["target_id"] != uid):
        await callback.answer("Нельзя принять этот вызов!", show_alert=True)
        return
    if uid in USERS_IN_BATTLE or ch["creator_id"] in USERS_IN_BATTLE:
        await callback.answer("Один из игроков уже в бою!", show_alert=True)
        return

    u1 = await db.get_user(ch["creator_id"])
    u2 = await db.get_user(uid)
    deck1 = await db.get_inventory(u1["user_id"], only_deck=True)
    deck2 = await db.get_inventory(u2["user_id"], only_deck=True)
    if not deck1 or not deck2:
        await callback.answer("У одного из игроков пустая колода!", show_alert=True)
        return
    if u1["coins"] < ch["bet"] or u2["coins"] < ch["bet"]:
        await callback.answer("Не хватает монет на ставку!", show_alert=True)
        return

    await db.close_pvp_challenge(ch_id, "done")
    USERS_IN_BATTLE.add(u1["user_id"])
    USERS_IN_BATTLE.add(u2["user_id"])
    await callback.answer("⚔️ Начинаем живую дуэль!")
    asyncio.create_task(run_live_duel_task(bot, u1, u2, deck1, deck2, ch["bet"]))


async def run_live_duel_task(
    bot: Bot,
    u1: Dict[str, Any],
    u2: Dict[str, Any],
    deck1: List[Dict[str, Any]],
    deck2: List[Dict[str, Any]],
    bet: int,
):
    battle_id = uuid.uuid4().hex[:10]
    p1_id, p2_id = u1["user_id"], u2["user_id"]
    ACTIVE_BATTLES[battle_id] = {"skip": False, "surrendered": set(), "participants": {p1_id, p2_id}}
    try:
        t1 = [build_combat_unit(c, side=1) for c in deck1]
        t2 = [build_combat_unit(c, side=2) for c in deck2]
        msgs: List[Message] = []
        for pid in (p1_id, p2_id):
            try:
                m = await bot.send_message(pid, f"⚔️ <b>ЖИВАЯ ДУЭЛЬ:</b> {esc(u1['full_name'])} vs {esc(u2['full_name'])}!")
                msgs.append(m)
            except Exception:
                pass

        winner, _ = await run_live_skirmish(
            messages=msgs,
            battle_id=battle_id,
            title="⚔️ PvP ДУЭЛЬ 4×4",
            p1_id=p1_id,
            p1_name=u1["full_name"],
            t1=t1,
            p2_id=p2_id,
            p2_name=u2["full_name"],
            t2=t2,
        )

        win_u = u1 if winner == 1 else u2
        lose_u = u2 if winner == 1 else u1
        arena_bonus = 40
        await db.update_user(win_u["user_id"], pvp_wins=win_u["pvp_wins"] + 1)
        await db.update_user(lose_u["user_id"], pvp_losses=lose_u["pvp_losses"] + 1)
        await db.add_coins(win_u["user_id"], bet + arena_bonus)
        if bet > 0:
            await db.add_coins(lose_u["user_id"], -bet)

        fin = (
            f"🏁 <b>ИТОГИ ДУЭЛИ 4×4</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👑 Победитель: <b>{esc(win_u['full_name'])}</b>\n"
            f"💰 Приз: <b>+{bet + arena_bonus} монет</b>"
        )
        for m in msgs:
            await safe_edit_battle(m, fin)
    except Exception as exc:
        logger.exception("Live duel error: %s", exc)
    finally:
        ACTIVE_BATTLES.pop(battle_id, None)
        USERS_IN_BATTLE.discard(p1_id)
        USERS_IN_BATTLE.discard(p2_id)


# --- МИРОВОЙ БОСС ---

async def render_world_boss(target: Message | CallbackQuery):
    wb = await db.get_active_world_boss()
    if not wb:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В Мультиплеер", callback_data="mp:hub")]])
        await render_view(target, "🌍 <b>МИРОВОЙ БОСС</b>\n\nСейчас ни один Мировой Босс не активен.", kb)
        return
    top = await db.get_world_boss_top(wb["id"], limit=5)
    top_lines = [f"{i}. {format_user_link(t)} — <b>{t['damage']}</b> урона" for i, t in enumerate(top, 1)]
    text = (
        f"🌍 <b>МИРОВОЙ БОСС: {esc(wb['name'])}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{make_hp_bar(wb['current_hp'], wb['max_hp'], 12)}\n"
        f"❤️ HP: <b>{wb['current_hp']} / {wb['max_hp']}</b>\n\n"
        f"🏆 <b>Топ-5 по урону:</b>\n"
        + ("\n".join(top_lines) if top_lines else "<i>Будь первым, кто ударит!</i>")
        + "\n\n🎁 Топ-3 при добивании получают крупные монеты и шанс на <b>🌌 Астро-Инфектед</b> + ✨ Shiny!"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚔️ Ударить колодой!", callback_data="mp:wb:hit")],
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="mp:wb"), InlineKeyboardButton(text="🔙 Назад", callback_data="mp:hub")],
        ]
    )
    await render_view(target, text, kb, photo=wb.get("image_id") or None)


@router.callback_query(F.data == "mp:wb")
async def cb_wb_view(callback: CallbackQuery):
    await render_world_boss(callback)
    await callback.answer()


@router.callback_query(F.data == "mp:wb:hit")
async def cb_wb_hit(callback: CallbackQuery, bot: Bot):
    wb = await db.get_active_world_boss()
    if not wb:
        await callback.answer("Мировой босс уже повержен!", show_alert=True)
        await render_world_boss(callback)
        return
    uid = callback.from_user.id
    prev = await db.get_world_boss_hit(wb["id"], uid)
    now = int(time.time())
    cd = cfg_int("wb_cooldown_sec")
    if prev and (now - prev["last_hit"]) < cd:
        await callback.answer(f"⏳ Перезарядка удара: {cd - (now - prev['last_hit'])} сек.", show_alert=True)
        return
    deck = await db.get_inventory(uid, only_deck=True)
    if not deck:
        await callback.answer("Поставьте карты в колоду!", show_alert=True)
        return

    s = calc_deck_summary(deck)
    dmg = int(s["atk"] * random.uniform(1.1, 1.5))
    rem_hp = await db.hit_world_boss(wb["id"], uid, dmg)

    if rem_hp <= 0:
        top = await db.get_world_boss_top(wb["id"], limit=10)
        reward_card = (await db.get_card(wb["infected_card_id"]) if wb.get("infected_card_id") else None) or await db.get_card(wb["card_id"])
        for idx, participant in enumerate(top, 1):
            p_uid = participant["user_id"]
            coins = int(max(150, 900 - (idx - 1) * 150) * cfg_float("event_coin_mult"))
            await db.add_coins(p_uid, coins)
            extra = ""
            if idx <= 3 and random.randint(1, 100) <= min(80, wb["infect_chance"] + 35):
                sh = roll_shiny()
                inf_t = "astro" if idx == 1 else "normal"
                await db.give_card(p_uid, reward_card["id"], mutation=sh, infected_type=inf_t)
                sh_txt = " ✨SHINY!" if sh == "shiny" else ""
                extra = f"\n🦠 <b>ВЫ ЗАРАЗИЛИ МИРОВОГО БОССА!</b> Карта: <b>{esc(reward_card['name'])}</b> ({INFECTED_TYPES[inf_t][0]}){sh_txt}"
            try:
                await bot.send_message(
                    p_uid,
                    f"🌍🏆 <b>МИРОВОЙ БОСС {esc(wb['name'])} ПОВЕРЖЕН!</b>\n"
                    f"Место: <b>#{idx}</b> (урон: {participant['damage']}) | 💰 <b>+{coins} монет</b>{extra}",
                )
            except Exception:
                pass
        await callback.answer(f"💥 ФИНАЛЬНЫЙ УДАР -{dmg}! Босс повержен!", show_alert=True)
    else:
        await callback.answer(f"⚔️ Нанесено {dmg} урона! Осталось {rem_hp} HP.", show_alert=True)
    await render_world_boss(callback)


# --- P2P РЫНОК ---

async def render_market_page(target: Message | CallbackQuery, user_id: int, page: int = 0):
    lots = await db.list_market()
    per_page = 6
    total_pages = max(1, (len(lots) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    chunk = lots[page * per_page : (page + 1) * per_page]

    text = (
        f"🏪 <b>P2P РЫНОК ИГРОКОВ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Лотов: <b>{len(lots)}</b> | Стр. {page + 1}/{total_pages}"
    )
    rows = []
    for lot in chunk:
        r_ico = RARITIES.get(lot["rarity"], ("", "⚪️", 1))[1]
        sh = "✨" if lot["mutation"] == "shiny" else ""
        inf = INFECTED_TYPES.get(lot["infected_type"], ("", ""))[1]
        sgn = "✍️" if lot["sign_type"] != "none" else ""
        mine = " (Мой)" if lot["seller_id"] == user_id else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{r_ico}{sh}{inf}{sgn} {lot['name']} Ур.{lot['level']} — {lot['price']}💰{mine}",
                    callback_data=f"mkt:view:{lot['market_id']}:{page}",
                )
            ]
        )
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


@router.callback_query(F.data.startswith("mkt:view:"))
async def cb_market_view(callback: CallbackQuery):
    _, _, lot_id_s, page_s = callback.data.split(":")
    lot_id, page = int(lot_id_s), int(page_s)
    lot = next((x for x in await db.list_market() if x["market_id"] == lot_id), None)
    if not lot:
        await callback.answer("Лот больше не существует.", show_alert=True)
        await render_market_page(callback, callback.from_user.id, page)
        return
    st = calc_card_stats(lot)
    sh = "✨ Shiny" if lot["mutation"] == "shiny" else "Обычная"
    inf = INFECTED_TYPES.get(lot["infected_type"], ("Нет", ""))[0]
    text = (
        f"🏷 <b>ЛОТ #{lot['market_id']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🃏 <b>{esc(lot['name'])}</b> (Ур. {lot['level']} | {lot['class_type']})\n"
        f"Мутация: <b>{sh}</b> | Заражение: <b>{inf}</b>\n"
        f"Сигна: {get_sign_label(lot)}\n"
        f"❤️ HP: <b>{st['hp']}</b> | ⚔️ Урон: <b>{st['atk']}</b> | ⚡️ Скорость: <b>{st['speed']}x</b>\n"
        f"👤 Продавец: <b>{esc(lot['seller_name'] or 'Игрок')}</b>\n"
        f"💰 Цена: <b>{lot['price']} монет</b>"
    )
    act_btn = (
        InlineKeyboardButton(text="❌ Снять с продажи", callback_data=f"mkt:cancel:{lot_id}:{page}")
        if lot["seller_id"] == callback.from_user.id
        else InlineKeyboardButton(text=f"✅ Купить за {lot['price']} 💰", callback_data=f"mkt:buy:{lot_id}:{page}")
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[act_btn], [InlineKeyboardButton(text="🔙 Назад", callback_data=f"mp:market:{page}")]])
    await render_view(callback, text, kb, photo=lot.get("image_id") or None)
    await callback.answer()


@router.callback_query(F.data.startswith("mkt:buy:"))
async def cb_market_buy(callback: CallbackQuery, bot: Bot):
    _, _, lot_id_s, page_s = callback.data.split(":")
    ok, msg, lot = await db.buy_market_lot(int(lot_id_s), callback.from_user.id)
    await callback.answer(msg, show_alert=True)
    if ok and lot:
        try:
            await bot.send_message(
                lot["seller_id"],
                f"💰 <b>ВАШУ КАРТУ КУПИЛИ!</b>\nКарта: <b>{esc(lot['name'])}</b> | Зачислено: <b>+{lot['price']} 💰</b>",
            )
        except Exception:
            pass
    await render_market_page(callback, callback.from_user.id, int(page_s))


@router.callback_query(F.data.startswith("mkt:cancel:"))
async def cb_market_cancel(callback: CallbackQuery):
    _, _, lot_id_s, page_s = callback.data.split(":")
    ok = await db.cancel_market_lot(int(lot_id_s), callback.from_user.id)
    await callback.answer("Снято с продажи!" if ok else "Ошибка.", show_alert=True)
    await render_market_page(callback, callback.from_user.id, int(page_s))


# -------------------- ЛАБОРАТОРИЯ ПАРАЗИТОВ И НАСТРАИВАЕМЫЕ КРЕЙТЫ --------------------

async def render_lab(target: Message | CallbackQuery, user_id: int):
    user = await db.get_user(user_id)
    crates = await db.list_crates(only_active=True)

    c_price, c_bon = cfg_int("p_common_price"), cfg_int("p_common_bonus")
    u_price, u_bon = cfg_int("p_upgraded_price"), cfg_int("p_upgraded_bonus")
    a_price, a_bon = cfg_int("p_astro_price"), cfg_int("p_astro_bonus")

    text = (
        f"🧪 <b>ЛАБОРАТОРИЯ И КРЕЙТЫ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Монеты: <b>{user['coins']}</b>\n"
        f"🦠 Паразиты: Обыч. <b>{user['p_common']}</b> | Улучш. <b>{user['p_upgraded']}</b> | Астро <b>{user['p_astro']}</b>\n\n"
        f"🦠 <b>Паразиты:</b>\n"
        f"• Обычный (+{c_bon}% ➔ Инфектед x{cfg_float('infected_normal_mult')})\n"
        f"• Улучшенный (+{u_bon}% ➔ Инфектед x{cfg_float('infected_normal_mult')})\n"
        f"• Астро (+{a_bon}% ➔ Астро-Инфектед x{cfg_float('infected_astro_mult')})\n\n"
        f"📦 <b>Доступные крейты (шанс ✨Shiny {cfg_float('shiny_chance_pct')}%):</b>"
    )
    rows = [
        [
            InlineKeyboardButton(text=f"🦠 Обыч. ({c_price}💰)", callback_data="shop:buy:common"),
            InlineKeyboardButton(text=f"☣️ Улучш. ({u_price}💰)", callback_data="shop:buy:upgraded"),
        ],
        [InlineKeyboardButton(text=f"🌌 Астро-паразит ({a_price}💰)", callback_data="shop:buy:astro")],
        [
            InlineKeyboardButton(text="⚗️ 3🦠 ➔ 1☣️ Крафт", callback_data="shop:craft:upgraded"),
            InlineKeyboardButton(text="⚗️ 3☣️ ➔ 1🌌 Крафт", callback_data="shop:craft:astro"),
        ],
    ]
    for cr in crates:
        rows.append([InlineKeyboardButton(text=f"{cr['name']} — {cr['price']}💰", callback_data=f"shop:crate:{cr['id']}")])

    await render_view(target, text, InlineKeyboardMarkup(inline_keyboard=rows))


@router.message(F.text == "🧪 Лаборатория и Кейсы")
async def menu_lab(message: Message, state: FSMContext):
    await state.clear()
    await render_lab(message, message.from_user.id)


@router.callback_query(F.data.startswith("shop:buy:"))
async def cb_shop_buy(callback: CallbackQuery):
    p_key = callback.data.split(":")[2]
    p_name, _, _, price, _ = get_parasite_info(p_key)
    user = await db.get_user(callback.from_user.id)
    if user["coins"] < price:
        await callback.answer(f"Нужно {price} 💰!", show_alert=True)
        return
    await db.add_coins(user["user_id"], -price)
    await db.add_parasite(user["user_id"], p_key, 1)
    await callback.answer(f"✅ Куплен: {p_name}!", show_alert=True)
    await render_lab(callback, user["user_id"])


@router.callback_query(F.data.startswith("shop:craft:"))
async def cb_shop_craft(callback: CallbackQuery):
    target_p = callback.data.split(":")[2]
    user = await db.get_user(callback.from_user.id)
    src_p = "common" if target_p == "upgraded" else "upgraded"
    src_col = PARASITES_META[src_p][1]
    if user[src_col] < 3:
        await callback.answer(f"Нужно минимум 3 шт. «{PARASITES_META[src_p][0]}»!", show_alert=True)
        return
    await db.add_parasite(user["user_id"], src_p, -3)
    await db.add_parasite(user["user_id"], target_p, 1)
    await callback.answer(f"⚗️ Скрафчен: {PARASITES_META[target_p][0]}!", show_alert=True)
    await render_lab(callback, user["user_id"])


@router.callback_query(F.data.startswith("shop:crate:"))
async def cb_shop_crate(callback: CallbackQuery):
    crate_id = int(callback.data.split(":")[2])
    crate = await db.get_crate(crate_id)
    if not crate or not crate["active"]:
        await callback.answer("Крейт недоступен.", show_alert=True)
        return
    user = await db.get_user(callback.from_user.id)
    if user["coins"] < crate["price"]:
        await callback.answer(f"Нужно {crate['price']} 💰!", show_alert=True)
        return

    all_cards = [c for c in await db.list_cards() if not c["is_boss"]]
    if not all_cards:
        await callback.answer("Нет карт для выпадения.", show_alert=True)
        return

    try:
        r_weights = json.loads(crate["weights_json"] or "{}")
    except json.JSONDecodeError:
        r_weights = {}

    luck = cfg_float("event_luck_mult")
    card_weights = []
    for c in all_cards:
        rw = float(r_weights.get(c["rarity"], 0))
        if rw > 0 and c["rarity"] in ("epic", "legendary", "mythic", "secret"):
            rw *= luck
        card_weights.append(rw)

    if sum(card_weights) <= 0:
        card_weights = [1.0] * len(all_cards)

    dropped = random.choices(all_cards, weights=card_weights, k=1)[0]
    shiny = roll_shiny(float(crate.get("shiny_chance", cfg_float("shiny_chance_pct"))))
    await db.add_coins(user["user_id"], -crate["price"])
    await db.give_card(user["user_id"], dropped["id"], mutation=shiny)

    r_name, r_ico, _ = RARITIES.get(dropped["rarity"], ("Обычная", "⚪️", 1))
    cls_ico = CARD_CLASSES.get(dropped.get("class_type", "Single"), ("🎯", ""))[0]
    sh_banner = f"\n✨ <b>ВЫПАЛ SHINY (+{cfg_int('shiny_bonus_pct')}% к статам)!</b>" if shiny == "shiny" else ""
    await callback.answer(f"🎉 Выпало: {dropped['name']}!", show_alert=True)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"🔁 Открыть ещё ({crate['price']}💰)", callback_data=f"shop:crate:{crate_id}"),
                InlineKeyboardButton(text="🔙 В Лабораторию", callback_data="shop:back"),
            ]
        ]
    )
    await render_view(
        callback,
        f"📦 <b>{esc(crate['name'])}</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"Выпала карта:\n{r_ico} {cls_ico} <b>{esc(dropped['name'])}</b> ({r_name}){sh_banner}\n"
        f"❤️ HP: {dropped['hp']} | ⚔️ Урон: {dropped['atk']}",
        kb,
        photo=dropped.get("image_id") or None,
    )


@router.callback_query(F.data == "shop:back")
async def cb_shop_back(callback: CallbackQuery):
    await render_lab(callback, callback.from_user.id)
    await callback.answer()


# -------------------- РЕЙТИНГИ --------------------

async def render_top(target: Message | CallbackQuery, mode: str = "trophies"):
    titles = {
        "trophies": ("🏆 Топ по Кубкам Арены", "🏆"),
        "pvp_wins": ("⚔️ Топ по PvP победам", "побед"),
        "infections_success": ("🦠 Топ по Заражениям", "зараж."),
        "coins": ("💰 Топ Богачей", "монет"),
        "bosses_killed": ("👹 Топ Охотников на Боссов", "боссов"),
    }
    title, unit = titles.get(mode, titles["trophies"])
    leaders = await db.get_leaderboard(mode, limit=10)
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for idx, row in enumerate(leaders, 1):
        m = medals[idx - 1] if idx <= 3 else f"{idx}."
        extra = f" ({get_league(row['val'])})" if mode == "trophies" else ""
        lines.append(f"{m} {format_user_link(row)} — <b>{row['val']}</b> {unit}{extra}")

    text = f"{title}\n━━━━━━━━━━━━━━━━━━\n" + ("\n".join(lines) if lines else "<i>Список пока пуст.</i>")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🏆 Кубки", callback_data="top:trophies"),
                InlineKeyboardButton(text="⚔️ PvP", callback_data="top:pvp_wins"),
                InlineKeyboardButton(text="🦠 Зараж.", callback_data="top:infections_success"),
            ],
            [
                InlineKeyboardButton(text="💰 Монеты", callback_data="top:coins"),
                InlineKeyboardButton(text="👹 Боссы", callback_data="top:bosses_killed"),
            ],
        ]
    )
    await render_view(target, text, kb)


@router.message(F.text == "🏆 Рейтинг")
async def menu_top(message: Message, state: FSMContext):
    await state.clear()
    await render_top(message, "trophies")


@router.callback_query(F.data.startswith("top:"))
async def cb_top_switch(callback: CallbackQuery):
    await render_top(callback, callback.data.split(":")[1])
    await callback.answer()


# ==============================================================================
# 8. РАСШИРЕННАЯ АДМИН-ПАНЕЛЬ
# ==============================================================================

async def check_adm_perm(callback: CallbackQuery, perm: str) -> bool:
    if not await db.has_perm(callback.from_user.id, perm):
        await callback.answer("⛔️ У вас нет прав на этот раздел!", show_alert=True)
        return False
    return True


async def render_admin_home(target: Message | CallbackQuery, user_id: int):
    if not await db.is_admin(user_id):
        return
    perms = await db.get_admin_perms(user_id)
    st = await db.get_global_stats()
    maint = "🔴 ВКЛ" if GAME_SETTINGS.get("maintenance", "0") == "1" else "🟢 ВЫКЛ"
    role = "👑 Владелец" if user_id == OWNER_ID else "👮 Администратор"

    text = (
        f"⚙️ <b>АДМИН-ПАНЕЛЬ</b> ({role})\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👥 Игроков: <b>{st['users']}</b> | 🃏 Карт: <b>{st['cards']}</b> | 📦 Крейтов: <b>{st['crates']}</b>\n"
        f"🎒 В инвентарях: <b>{st['inventory']}</b> | 🏪 На рынке: <b>{st['market']}</b>\n"
        f"🛠 Техработы: <b>{maint}</b>\n"
        f"🍀 Удача: <b>x{cfg_float('event_luck_mult')}</b> | 💰 Монеты: <b>x{cfg_float('event_coin_mult')}</b>"
    )
    rows: List[List[InlineKeyboardButton]] = []
    if perms.get("manage_cards"):
        rows.append([
            InlineKeyboardButton(text="➕ Создать карту", callback_data="adm:card:new"),
            InlineKeyboardButton(text="🃏 Список / Редактор", callback_data="adm:cards:0"),
        ])
    if perms.get("manage_crates"):
        rows.append([InlineKeyboardButton(text="📦 Управление Крейтами", callback_data="adm:crates")])
    if perms.get("manage_settings"):
        rows.append([InlineKeyboardButton(text="🎛 Настройки баланса / Shiny / Ивенты", callback_data="adm:settings:0")])
    if perms.get("manage_bosses"):
        rows.append([InlineKeyboardButton(text="🌍 Мировой Босс", callback_data="adm:wb")])
    if perms.get("manage_users") or perms.get("manage_economy"):
        rows.append([InlineKeyboardButton(text="👥 Игроки и Экономика", callback_data="adm:users")])
    if perms.get("broadcast"):
        rows.append([InlineKeyboardButton(text="📢 Рассылка всем", callback_data="adm:broadcast")])
    if perms.get("manage_admins"):
        rows.append([
            InlineKeyboardButton(text="👮 Админы", callback_data="adm:admins"),
            InlineKeyboardButton(text="✍️ Сигнеры", callback_data="adm:signers"),
        ])
        rows.append([
            InlineKeyboardButton(text=f"🛠 Техработы: {maint}", callback_data="adm:maint"),
            InlineKeyboardButton(text="💾 Скачать БД", callback_data="adm:backup"),
        ])
        rows.append([InlineKeyboardButton(text="📜 Лог действий админов", callback_data="adm:logs")])

    await render_view(target, text, InlineKeyboardMarkup(inline_keyboard=rows))


@router.message(F.text == "⚙️ Админ-панель")
async def menu_admin(message: Message, state: FSMContext):
    if not await db.is_admin(message.from_user.id):
        return
    await state.clear()
    await render_admin_home(message, message.from_user.id)


@router.callback_query(F.data == "adm:home")
async def cb_adm_home(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await render_admin_home(callback, callback.from_user.id)
    await callback.answer()


# -------------------- КОНСТРУКТОР КАРТОЧЕК --------------------

@router.callback_query(F.data == "adm:card:new")
async def cb_adm_card_new(callback: CallbackQuery, state: FSMContext):
    if not await check_adm_perm(callback, "manage_cards"):
        return
    await state.clear()
    await state.set_state(CardCreateFSM.name)
    await callback.message.answer("🃏 <b>Создание карты (1/9)</b>\nВведите <b>название</b> карточки:")
    await callback.answer()


@router.message(CardCreateFSM.name)
async def fsm_cc_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if len(name) < 2 or len(name) > 60:
        await message.answer("❌ Название от 2 до 60 символов.")
        return
    await state.update_data(name=name)
    await state.set_state(CardCreateFSM.faction)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=v, callback_data=f"cc:fac:{k}")] for k, v in FACTIONS.items()]
    )
    await message.answer("🃏 <b>Шаг 2/9:</b> Выберите <b>фракцию</b>:", reply_markup=kb)


@router.callback_query(CardCreateFSM.faction, F.data.startswith("cc:fac:"))
async def fsm_cc_fac(callback: CallbackQuery, state: FSMContext):
    await state.update_data(faction=callback.data.split(":")[2])
    await state.set_state(CardCreateFSM.rarity)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{ico} {name}", callback_data=f"cc:rar:{k}")]
            for k, (name, ico, _) in RARITIES.items()
        ]
    )
    await render_view(callback, "🃏 <b>Шаг 3/9:</b> Выберите <b>редкость</b>:", kb)
    await callback.answer()


@router.callback_query(CardCreateFSM.rarity, F.data.startswith("cc:rar:"))
async def fsm_cc_rar(callback: CallbackQuery, state: FSMContext):
    await state.update_data(rarity=callback.data.split(":")[2])
    await state.set_state(CardCreateFSM.class_type)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{ico} {k} — {desc[:32]}", callback_data=f"cc:cls:{k}")]
            for k, (ico, desc) in CARD_CLASSES.items()
        ]
    )
    await render_view(callback, "🃏 <b>Шаг 4/9:</b> Выберите <b>боевой класс</b>:", kb)
    await callback.answer()


@router.callback_query(CardCreateFSM.class_type, F.data.startswith("cc:cls:"))
async def fsm_cc_cls(callback: CallbackQuery, state: FSMContext):
    cls = callback.data.split(":")[2]
    await state.update_data(class_type=cls, booster_dmg_mult=1.15, booster_hp_mult=1.15)
    await state.set_state(CardCreateFSM.hp)
    await render_view(callback, f"🃏 <b>Шаг 5/9:</b> Класс <b>{cls}</b>.\nВведите базовое <b>❤️ HP</b> (целое число):")
    await callback.answer()


@router.message(CardCreateFSM.hp)
async def fsm_cc_hp(message: Message, state: FSMContext):
    try:
        hp = int((message.text or "").strip())
        if hp <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите положительное число HP.")
        return
    await state.update_data(hp=hp)
    await state.set_state(CardCreateFSM.atk)
    cls = (await state.get_data()).get("class_type", "Single")
    lbl = "💗 силу лечения" if cls == "Healer" else "⚔️ урон (ATK)"
    await message.answer(f"🃏 <b>Шаг 6/9:</b> Введите базовую <b>{lbl}</b> (целое число):")


@router.message(CardCreateFSM.atk)
async def fsm_cc_atk(message: Message, state: FSMContext):
    try:
        atk = int((message.text or "").strip())
        if atk < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите число >= 0.")
        return
    await state.update_data(atk=atk)
    data = await state.get_data()
    if data.get("class_type") == "Booster":
        await state.set_state(CardCreateFSM.booster_mults)
        await message.answer(
            "✨ Для <b>Booster</b> введите два множителя через пробел (Урон HP), например: <code>1.20 1.15</code>"
        )
        return
    await state.set_state(CardCreateFSM.description)
    await message.answer("🃏 <b>Шаг 7/9:</b> Введите <b>описание</b> (или <code>-</code> чтобы пропустить):")


@router.message(CardCreateFSM.booster_mults)
async def fsm_cc_booster_mults(message: Message, state: FSMContext):
    try:
        parts = (message.text or "").replace(",", ".").split()
        dm, hm = float(parts[0]), float(parts[1])
        if not (1.0 <= dm <= 5.0 and 1.0 <= hm <= 5.0):
            raise ValueError
    except Exception:
        await message.answer("❌ Формат: два числа от 1.0 до 5.0, например <code>1.2 1.15</code>")
        return
    await state.update_data(booster_dmg_mult=dm, booster_hp_mult=hm)
    await state.set_state(CardCreateFSM.description)
    await message.answer("🃏 <b>Шаг 7/9:</b> Введите <b>описание</b> (или <code>-</code> чтобы пропустить):")


@router.message(CardCreateFSM.description)
async def fsm_cc_desc(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    await state.update_data(description="" if raw == "-" else raw[:300])
    await state.set_state(CardCreateFSM.image)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏭ Без фото", callback_data="cc:noimg")]])
    await message.answer("🃏 <b>Шаг 8/9:</b> Отправьте <b>фото</b> карточки или нажмите «Без фото»:", reply_markup=kb)


@router.callback_query(CardCreateFSM.image, F.data == "cc:noimg")
async def fsm_cc_noimg(callback: CallbackQuery, state: FSMContext):
    await state.update_data(image_id="")
    await ask_cc_is_boss(callback, state)
    await callback.answer()


@router.message(CardCreateFSM.image, F.photo)
async def fsm_cc_img(message: Message, state: FSMContext):
    await state.update_data(image_id=message.photo[-1].file_id)
    await ask_cc_is_boss(message, state)


async def ask_cc_is_boss(target: Message | CallbackQuery, state: FSMContext):
    await state.set_state(CardCreateFSM.is_boss)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👹 Да, Босс рейда", callback_data="cc:boss:1"),
                InlineKeyboardButton(text="🃏 Нет, обычная карта", callback_data="cc:boss:0"),
            ]
        ]
    )
    await render_view(target, "🃏 <b>Шаг 9/9:</b> Эта карта будет <b>Боссом рейда</b> с заражением?", kb)


@router.callback_query(CardCreateFSM.is_boss, F.data.startswith("cc:boss:"))
async def fsm_cc_is_boss(callback: CallbackQuery, state: FSMContext):
    is_b = int(callback.data.split(":")[2])
    await state.update_data(is_boss=is_b, boss_hp=0, boss_atk=0, infect_chance=0, infected_card_id=0)
    if is_b == 1:
        await state.set_state(CardCreateFSM.boss_hp)
        await render_view(callback, "👹 Введите <b>HP Босса</b> в финальной волне рейда (например: 900):")
    else:
        await show_cc_preview(callback, state)
    await callback.answer()


@router.message(CardCreateFSM.boss_hp)
async def fsm_cc_bhp(message: Message, state: FSMContext):
    try:
        v = int((message.text or "").strip())
        if v <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите целое число > 0.")
        return
    await state.update_data(boss_hp=v)
    await state.set_state(CardCreateFSM.boss_atk)
    await message.answer("👹 Введите <b>урон (ATK) Босса</b> в рейде (например: 65):")


@router.message(CardCreateFSM.boss_atk)
async def fsm_cc_batk(message: Message, state: FSMContext):
    try:
        v = int((message.text or "").strip())
        if v <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите целое число > 0.")
        return
    await state.update_data(boss_atk=v)
    await state.set_state(CardCreateFSM.infect_chance)
    await message.answer("🦠 Введите <b>базовый шанс заражения</b> в % (от 1 до 90):")


@router.message(CardCreateFSM.infect_chance)
async def fsm_cc_infch(message: Message, state: FSMContext):
    try:
        v = int((message.text or "").strip())
        if not (1 <= v <= 95):
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите число от 1 до 95.")
        return
    await state.update_data(infect_chance=v)
    await state.set_state(CardCreateFSM.infected_card_id)
    cards = await db.list_cards()
    sample = "\n".join(f"<code>{c['id']}</code> — {esc(c['name'])}" for c in cards[-12:])
    await message.answer(
        f"🔗 Введите <b>ID карты</b>, в которую превратится босс при заражении (или <code>0</code> — выдаст самого себя):\n\n{sample}"
    )


@router.message(CardCreateFSM.infected_card_id)
async def fsm_cc_infid(message: Message, state: FSMContext):
    try:
        v = int((message.text or "").strip())
        if v < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите число >= 0.")
        return
    await state.update_data(infected_card_id=v)
    await show_cc_preview(message, state)


async def show_cc_preview(target: Message | CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.set_state(CardCreateFSM.confirm)
    preview = dict(data, id="NEW")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Сохранить карту", callback_data="cc:save"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="adm:home"),
            ]
        ]
    )
    await render_view(
        target,
        f"👁 <b>ПРЕВЬЮ НОВОЙ КАРТЫ</b>\n━━━━━━━━━━━━━━━━━━\n{format_card_text(preview)}",
        kb,
        photo=data.get("image_id") or None,
    )


@router.callback_query(CardCreateFSM.confirm, F.data == "cc:save")
async def fsm_cc_save(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    new_id = await db.create_card(data)
    await db.log_admin(callback.from_user.id, f"Создал карту #{new_id} ({data['name']})")
    await callback.answer(f"✅ Карта #{new_id} создана!", show_alert=True)
    await render_adm_card_detail(callback, new_id, 0)


# -------------------- СПИСОК, ТОЧЕЧНОЕ РЕДАКТИРОВАНИЕ И УДАЛЕНИЕ КАРТ --------------------

async def render_adm_cards_list(target: Message | CallbackQuery, page: int = 0):
    cards = await db.list_cards()
    per_page = 8
    total_pages = max(1, (len(cards) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    chunk = cards[page * per_page : (page + 1) * per_page]

    rows = []
    for c in chunk:
        r_ico = RARITIES.get(c["rarity"], ("", "⚪️", 1))[1]
        cls_ico = CARD_CLASSES.get(c.get("class_type", "Single"), ("🎯", ""))[0]
        b_tag = "👹 " if c["is_boss"] else ""
        rows.append([
            InlineKeyboardButton(
                text=f"#{c['id']} {b_tag}{r_ico}{cls_ico} {c['name']}",
                callback_data=f"adm:cview:{c['id']}:{page}",
            )
        ])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"adm:cards:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"adm:cards:{page + 1}"))
    rows.append(nav)
    rows.append([
        InlineKeyboardButton(text="➕ Новая карта", callback_data="adm:card:new"),
        InlineKeyboardButton(text="🔙 Админка", callback_data="adm:home"),
    ])
    await render_view(target, f"🃏 <b>КАТАЛОГ КАРТ ({len(cards)})</b>\nВыберите карту для редактирования:", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("adm:cards:"))
async def cb_adm_cards_list(callback: CallbackQuery):
    if not await check_adm_perm(callback, "manage_cards"):
        return
    await render_adm_cards_list(callback, int(callback.data.split(":")[2]))
    await callback.answer()


async def render_adm_card_detail(target: Message | CallbackQuery, card_id: int, page: int = 0):
    card = await db.get_card(card_id)
    if not card:
        await render_adm_cards_list(target, page)
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✏️ Название", callback_data=f"adm:cedit:{card_id}:name:{page}"),
                InlineKeyboardButton(text="🖼 Фото", callback_data=f"adm:cedit:{card_id}:image_id:{page}"),
            ],
            [
                InlineKeyboardButton(text="❤️ HP", callback_data=f"adm:cedit:{card_id}:hp:{page}"),
                InlineKeyboardButton(text="⚔️ Урон", callback_data=f"adm:cedit:{card_id}:atk:{page}"),
            ],
            [
                InlineKeyboardButton(text="🎭 Фракция", callback_data=f"adm:cpick:{card_id}:faction:{page}"),
                InlineKeyboardButton(text="🌟 Редкость", callback_data=f"adm:cpick:{card_id}:rarity:{page}"),
            ],
            [
                InlineKeyboardButton(text="⚔️ Класс", callback_data=f"adm:cpick:{card_id}:class_type:{page}"),
                InlineKeyboardButton(text="📝 Описание", callback_data=f"adm:cedit:{card_id}:description:{page}"),
            ],
            [
                InlineKeyboardButton(text="✨ Буст множ.", callback_data=f"adm:cedit:{card_id}:booster_mults:{page}"),
                InlineKeyboardButton(text=f"👹 Босс: {'ДА' if card['is_boss'] else 'НЕТ'}", callback_data=f"adm:ctogboss:{card_id}:{page}"),
            ],
            [
                InlineKeyboardButton(text="👹 HP/ATK Босса", callback_data=f"adm:cedit:{card_id}:boss_stats:{page}"),
                InlineKeyboardButton(text="🦠 Шанс/ID Зар.", callback_data=f"adm:cedit:{card_id}:infect_cfg:{page}"),
            ],
            [
                InlineKeyboardButton(text="🗑 Удалить карту", callback_data=f"adm:cdelask:{card_id}:{page}"),
                InlineKeyboardButton(text="🔙 К списку", callback_data=f"adm:cards:{page}"),
            ],
        ]
    )
    await render_view(target, f"✏️ <b>РЕДАКТОР КАРТЫ</b>\n━━━━━━━━━━━━━━━━━━\n{format_card_text(card)}", kb, photo=card.get("image_id") or None)


@router.callback_query(F.data.startswith("adm:cview:"))
async def cb_adm_cview(callback: CallbackQuery):
    if not await check_adm_perm(callback, "manage_cards"):
        return
    _, _, cid_s, page_s = callback.data.split(":")
    await render_adm_card_detail(callback, int(cid_s), int(page_s))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:ctogboss:"))
async def cb_adm_ctogboss(callback: CallbackQuery):
    if not await check_adm_perm(callback, "manage_cards"):
        return
    _, _, cid_s, page_s = callback.data.split(":")
    cid, page = int(cid_s), int(page_s)
    c = await db.get_card(cid)
    if c:
        nxt = 0 if c["is_boss"] else 1
        upd = {"is_boss": nxt}
        if nxt == 1 and c["boss_hp"] <= 0:
            upd.update({"boss_hp": max(400, c["hp"] * 2), "boss_atk": max(30, c["atk"]), "infect_chance": 15})
        await db.update_card(cid, **upd)
        await db.log_admin(callback.from_user.id, f"Переключил is_boss={nxt} у карты #{cid}")
    await render_adm_card_detail(callback, cid, page)
    await callback.answer("Обновлено!")


@router.callback_query(F.data.startswith("adm:cpick:"))
async def cb_adm_cpick(callback: CallbackQuery):
    if not await check_adm_perm(callback, "manage_cards"):
        return
    _, _, cid_s, field, page_s = callback.data.split(":")
    cid, page = int(cid_s), int(page_s)
    rows = []
    if field == "faction":
        rows = [[InlineKeyboardButton(text=v, callback_data=f"adm:cset:{cid}:faction:{k}:{page}")] for k, v in FACTIONS.items()]
    elif field == "rarity":
        rows = [[InlineKeyboardButton(text=f"{ico} {n}", callback_data=f"adm:cset:{cid}:rarity:{k}:{page}")] for k, (n, ico, _) in RARITIES.items()]
    elif field == "class_type":
        rows = [[InlineKeyboardButton(text=f"{ico} {k}", callback_data=f"adm:cset:{cid}:class_type:{k}:{page}")] for k, (ico, _) in CARD_CLASSES.items()]
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"adm:cview:{cid}:{page}")])
    await render_view(callback, f"Выберите новое значение для <b>{field}</b>:", InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:cset:"))
async def cb_adm_cset(callback: CallbackQuery):
    if not await check_adm_perm(callback, "manage_cards"):
        return
    _, _, cid_s, field, val, page_s = callback.data.split(":")
    cid, page = int(cid_s), int(page_s)
    await db.update_card(cid, **{field: val})
    await db.log_admin(callback.from_user.id, f"Карта #{cid}: {field}={val}")
    await render_adm_card_detail(callback, cid, page)
    await callback.answer("✅ Сохранено!")


@router.callback_query(F.data.startswith("adm:cedit:"))
async def cb_adm_cedit(callback: CallbackQuery, state: FSMContext):
    if not await check_adm_perm(callback, "manage_cards"):
        return
    _, _, cid_s, field, page_s = callback.data.split(":")
    await state.set_state(CardEditFSM.waiting_value)
    await state.update_data(cid=int(cid_s), field=field, page=int(page_s))
    hints = {
        "name": "Введите новое <b>название</b>:",
        "image_id": "Отправьте новое <b>фото</b> (или <code>-</code> чтобы удалить фото):",
        "hp": "Введите новое <b>❤️ HP</b>:",
        "atk": "Введите новый <b>⚔️ Урон (или лечение)</b>:",
        "description": "Введите новое <b>описание</b> (или <code>-</code> чтобы очистить):",
        "booster_mults": "Введите два множителя Бустера через пробел (Урон HP), например: <code>1.25 1.20</code>",
        "boss_stats": "Введите <b>HP и ATK Босса</b> через пробел, например: <code>1000 75</code>",
        "infect_cfg": "Введите <b>Шанс(%) и ID заражённой карты</b> через пробел, например: <code>15 10</code>",
    }
    await callback.message.answer(f"✏️ {hints.get(field, 'Введите новое значение:')}")
    await callback.answer()


@router.message(CardEditFSM.waiting_value)
async def fsm_card_edit_save(message: Message, state: FSMContext):
    data = await state.get_data()
    cid, field, page = data["cid"], data["field"], data["page"]
    try:
        if field == "image_id":
            if message.photo:
                await db.update_card(cid, image_id=message.photo[-1].file_id)
            elif (message.text or "").strip() == "-":
                await db.update_card(cid, image_id="")
            else:
                await message.answer("❌ Отправьте фото или <code>-</code>.")
                return
        elif field in ("hp", "atk"):
            v = int((message.text or "").strip())
            if v < 0:
                raise ValueError
            await db.update_card(cid, **{field: v})
        elif field == "name":
            v = (message.text or "").strip()
            if len(v) < 2:
                raise ValueError
            await db.update_card(cid, name=v[:60])
        elif field == "description":
            raw = (message.text or "").strip()
            await db.update_card(cid, description="" if raw == "-" else raw[:300])
        elif field == "booster_mults":
            p = (message.text or "").replace(",", ".").split()
            await db.update_card(cid, booster_dmg_mult=float(p[0]), booster_hp_mult=float(p[1]))
        elif field == "boss_stats":
            p = (message.text or "").split()
            await db.update_card(cid, boss_hp=int(p[0]), boss_atk=int(p[1]))
        elif field == "infect_cfg":
            p = (message.text or "").split()
            await db.update_card(cid, infect_chance=max(0, min(95, int(p[0]))), infected_card_id=max(0, int(p[1])))
    except Exception:
        await message.answer("❌ Некорректный формат. Попробуйте ещё раз.")
        return

    await state.clear()
    await db.log_admin(message.from_user.id, f"Изменил карту #{cid} ({field})")
    await render_adm_card_detail(message, cid, page)


@router.callback_query(F.data.startswith("adm:cdelask:"))
async def cb_adm_cdelask(callback: CallbackQuery):
    if not await check_adm_perm(callback, "manage_cards"):
        return
    _, _, cid_s, page_s = callback.data.split(":")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🗑 ДА, удалить навсегда", callback_data=f"adm:cdel:{cid_s}:{page_s}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data=f"adm:cview:{cid_s}:{page_s}"),
            ]
        ]
    )
    await render_view(callback, f"⚠️ Вы уверены, что хотите удалить карту <b>#{cid_s}</b>? Она исчезнет и из инвентарей!", kb)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:cdel:"))
async def cb_adm_cdel(callback: CallbackQuery):
    if not await check_adm_perm(callback, "manage_cards"):
        return
    _, _, cid_s, page_s = callback.data.split(":")
    cid = int(cid_s)
    await db.delete_card(cid)
    await db.log_admin(callback.from_user.id, f"Удалил карту #{cid}")
    await callback.answer("🗑 Карта удалена!", show_alert=True)
    await render_adm_cards_list(callback, int(page_s))


# -------------------- УПРАВЛЕНИЕ КРЕЙТАМИ --------------------

async def render_adm_crates(target: Message | CallbackQuery):
    crates = await db.list_crates(only_active=False)
    rows = []
    for cr in crates:
        st = "🟢" if cr["active"] else "🔴"
        rows.append([
            InlineKeyboardButton(
                text=f"{st} {cr['name']} — {cr['price']}💰 (✨{cr['shiny_chance']}%)",
                callback_data=f"adm:crview:{cr['id']}",
            )
        ])
    rows.append([
        InlineKeyboardButton(text="➕ Создать Крейт", callback_data="adm:crnew"),
        InlineKeyboardButton(text="🔙 Админка", callback_data="adm:home"),
    ])
    await render_view(target, f"📦 <b>УПРАВЛЕНИЕ КРЕЙТАМИ ({len(crates)})</b>", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "adm:crates")
async def cb_adm_crates(callback: CallbackQuery):
    if not await check_adm_perm(callback, "manage_crates"):
        return
    await render_adm_crates(callback)
    await callback.answer()


async def render_adm_crate_detail(target: Message | CallbackQuery, crate_id: int):
    cr = await db.get_crate(crate_id)
    if not cr:
        await render_adm_crates(target)
        return
    st = "🟢 Активен" if cr["active"] else "🔴 Скрыт"
    text = (
        f"📦 <b>КРЕЙТ #{cr['id']}: {esc(cr['name'])}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Статус: {st} | Цена: <b>{cr['price']} 💰</b> | ✨ Shiny: <b>{cr['shiny_chance']}%</b>\n"
        f"Шансы редкостей: <code>{esc(cr['weights_json'])}</code>\n"
        f"📝 <i>{esc(cr['description'])}</i>"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✏️ Название", callback_data=f"adm:credit:{crate_id}:name"),
                InlineKeyboardButton(text="💰 Цена", callback_data=f"adm:credit:{crate_id}:price"),
            ],
            [
                InlineKeyboardButton(text="🎲 Веса редкостей", callback_data=f"adm:credit:{crate_id}:weights_json"),
                InlineKeyboardButton(text="✨ Шанс Shiny%", callback_data=f"adm:credit:{crate_id}:shiny_chance"),
            ],
            [
                InlineKeyboardButton(text="👁 Вкл/Выкл", callback_data=f"adm:crtog:{crate_id}"),
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"adm:crdel:{crate_id}"),
            ],
            [InlineKeyboardButton(text="🔙 К крейтам", callback_data="adm:crates")],
        ]
    )
    await render_view(target, text, kb)


@router.callback_query(F.data.startswith("adm:crview:"))
async def cb_adm_crview(callback: CallbackQuery):
    if not await check_adm_perm(callback, "manage_crates"):
        return
    await render_adm_crate_detail(callback, int(callback.data.split(":")[2]))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:crtog:"))
async def cb_adm_crtog(callback: CallbackQuery):
    if not await check_adm_perm(callback, "manage_crates"):
        return
    cid = int(callback.data.split(":")[2])
    cr = await db.get_crate(cid)
    if cr:
        await db.update_crate(cid, active=(0 if cr["active"] else 1))
    await render_adm_crate_detail(callback, cid)
    await callback.answer("Обновлено!")


@router.callback_query(F.data.startswith("adm:crdel:"))
async def cb_adm_crdel(callback: CallbackQuery):
    if not await check_adm_perm(callback, "manage_crates"):
        return
    cid = int(callback.data.split(":")[2])
    await db.delete_crate(cid)
    await db.log_admin(callback.from_user.id, f"Удалил крейт #{cid}")
    await callback.answer("🗑 Крейт удалён!", show_alert=True)
    await render_adm_crates(callback)


@router.callback_query(F.data.startswith("adm:credit:"))
async def cb_adm_credit(callback: CallbackQuery, state: FSMContext):
    if not await check_adm_perm(callback, "manage_crates"):
        return
    _, _, cid_s, field = callback.data.split(":")
    await state.set_state(CrateFSM.edit_value)
    await state.update_data(crate_id=int(cid_s), field=field)
    if field == "weights_json":
        hint = "Введите 6 чисел через пробел (common rare epic legendary mythic secret), например: <code>40 30 18 8 3 1</code>"
    else:
        hint = f"Введите новое значение для <b>{field}</b>:"
    await callback.message.answer(f"✏️ {hint}")
    await callback.answer()


@router.message(CrateFSM.edit_value)
async def fsm_crate_edit_save(message: Message, state: FSMContext):
    data = await state.get_data()
    cid, field = data["crate_id"], data["field"]
    raw = (message.text or "").strip()
    try:
        if field == "price":
            await db.update_crate(cid, price=max(1, int(raw)))
        elif field == "shiny_chance":
            await db.update_crate(cid, shiny_chance=max(0.0, min(100.0, float(raw.replace(",", ".")))))
        elif field == "weights_json":
            nums = [max(0, int(x)) for x in raw.split()]
            if len(nums) != 6:
                raise ValueError
            keys = ["common", "rare", "epic", "legendary", "mythic", "secret"]
            await db.update_crate(cid, weights_json=json.dumps(dict(zip(keys, nums))))
        else:
            await db.update_crate(cid, **{field: raw[:60]})
    except Exception:
        await message.answer("❌ Некорректный формат.")
        return
    await state.clear()
    await db.log_admin(message.from_user.id, f"Изменил крейт #{cid} ({field})")
    await render_adm_crate_detail(message, cid)


@router.callback_query(F.data == "adm:crnew")
async def cb_adm_crnew(callback: CallbackQuery, state: FSMContext):
    if not await check_adm_perm(callback, "manage_crates"):
        return
    await state.set_state(CrateFSM.name)
    await callback.message.answer("📦 Введите <b>название</b> нового крейта (например: <code>🔥 Огненный Кейс</code>):")
    await callback.answer()


@router.message(CrateFSM.name)
async def fsm_cr_name(message: Message, state: FSMContext):
    await state.update_data(name=(message.text or "Кейс").strip()[:50])
    await state.set_state(CrateFSM.description)
    await message.answer("📝 Введите краткое <b>описание</b> крейта:")


@router.message(CrateFSM.description)
async def fsm_cr_desc(message: Message, state: FSMContext):
    await state.update_data(description=(message.text or "").strip()[:200])
    await state.set_state(CrateFSM.price)
    await message.answer("💰 Введите <b>цену</b> крейта в монетах:")


@router.message(CrateFSM.price)
async def fsm_cr_price(message: Message, state: FSMContext):
    try:
        p = int((message.text or "").strip())
        if p <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите целое число > 0.")
        return
    await state.update_data(price=p)
    await state.set_state(CrateFSM.weights)
    await message.answer(
        "🎲 Введите 6 весов редкостей через пробел (common rare epic legendary mythic secret):\n"
        "Например: <code>45 30 15 7 2 1</code>"
    )


@router.message(CrateFSM.weights)
async def fsm_cr_weights(message: Message, state: FSMContext):
    try:
        nums = [max(0, int(x)) for x in (message.text or "").split()]
        if len(nums) != 6 or sum(nums) <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Нужно ровно 6 целых чисел (сумма > 0).")
        return
    keys = ["common", "rare", "epic", "legendary", "mythic", "secret"]
    await state.update_data(weights=dict(zip(keys, nums)))
    await state.set_state(CrateFSM.shiny_chance)
    await message.answer("✨ Введите шанс выпадения <b>Shiny</b> в % (например: <code>1.0</code>):")


@router.message(CrateFSM.shiny_chance)
async def fsm_cr_shiny(message: Message, state: FSMContext):
    try:
        sh = float((message.text or "").replace(",", ".").strip())
        if not (0.0 <= sh <= 100.0):
            raise ValueError
    except ValueError:
        await message.answer("❌ Число от 0 до 100.")
        return
    d = await state.get_data()
    await state.clear()
    cid = await db.create_crate(d["name"], d["description"], d["price"], d["weights"], sh)
    await db.log_admin(message.from_user.id, f"Создал крейт #{cid} ({d['name']})")
    await render_adm_crate_detail(message, cid)


# -------------------- НАСТРОЙКИ БАЛАНСА, SHINY, СИГН И ИВЕНТОВ --------------------

async def render_adm_settings(target: Message | CallbackQuery, page: int = 0):
    keys = list(SETTING_META.keys())
    per_page = 6
    total_pages = max(1, (len(keys) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    chunk = keys[page * per_page : (page + 1) * per_page]

    rows = []
    for k in chunk:
        label = SETTING_META[k][0]
        val = GAME_SETTINGS.get(k, DEFAULT_GAME_SETTINGS[k])
        rows.append([InlineKeyboardButton(text=f"{label}: {val}", callback_data=f"adm:setedit:{k}:{page}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"adm:settings:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"adm:settings:{page + 1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔙 Админка", callback_data="adm:home")])
    await render_view(target, "🎛 <b>НАСТРОЙКИ БАЛАНСА И ИВЕНТОВ</b>\nНажмите параметр, чтобы изменить его:", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("adm:settings:"))
async def cb_adm_settings(callback: CallbackQuery):
    if not await check_adm_perm(callback, "manage_settings"):
        return
    await render_adm_settings(callback, int(callback.data.split(":")[2]))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:setedit:"))
async def cb_adm_setedit(callback: CallbackQuery, state: FSMContext):
    if not await check_adm_perm(callback, "manage_settings"):
        return
    _, _, key, page_s = callback.data.split(":")
    if key not in SETTING_META:
        return
    label, typ, mn, mx = SETTING_META[key]
    await state.set_state(AdminFSM.setting_value)
    await state.update_data(set_key=key, set_page=int(page_s))
    await callback.message.answer(
        f"🎛 <b>{label}</b>\nТекущее: <code>{GAME_SETTINGS.get(key)}</code>\nВведите новое значение ({typ}, от {mn} до {mx}):"
    )
    await callback.answer()


@router.message(AdminFSM.setting_value)
async def fsm_adm_set_save(message: Message, state: FSMContext):
    data = await state.get_data()
    key, page = data["set_key"], data["set_page"]
    label, typ, mn, mx = SETTING_META[key]
    raw = (message.text or "").replace(",", ".").strip()
    try:
        val = int(float(raw)) if typ == "int" else round(float(raw), 2)
        if not (mn <= val <= mx):
            raise ValueError
    except ValueError:
        await message.answer(f"❌ Введите число от {mn} до {mx}.")
        return
    await state.clear()
    await db.set_setting(key, str(val))
    await db.log_admin(message.from_user.id, f"Настройка {key} = {val}")
    await message.answer(f"✅ <b>{label}</b> изменено на <b>{val}</b>!")
    await render_adm_settings(message, page)


# -------------------- МИРОВОЙ БОСС (АДМИНКА) --------------------

@router.callback_query(F.data == "adm:wb")
async def cb_adm_wb(callback: CallbackQuery):
    if not await check_adm_perm(callback, "manage_bosses"):
        return
    wb = await db.get_active_world_boss()
    bosses = await db.list_cards(only_bosses=True)
    status = f"🟢 Активен: <b>{esc(wb['name'])}</b> ({wb['current_hp']}/{wb['max_hp']} HP)" if wb else "⚪️ Сейчас не запущен"
    rows = []
    for b in bosses[:8]:
        rows.append([InlineKeyboardButton(text=f"🚀 Запустить: {b['name']}", callback_data=f"adm:wbspawn:{b['id']}")])
    if wb:
        rows.append([InlineKeyboardButton(text="🛑 Остановить текущего Босса", callback_data="adm:wbstop")])
    rows.append([InlineKeyboardButton(text="🔙 Админка", callback_data="adm:home")])
    await render_view(callback, f"🌍 <b>УПРАВЛЕНИЕ МИРОВЫМ БОССОМ</b>\n{status}", InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:wbspawn:"))
async def cb_adm_wbspawn(callback: CallbackQuery, state: FSMContext):
    if not await check_adm_perm(callback, "manage_bosses"):
        return
    await state.set_state(AdminFSM.world_boss_hp)
    await state.update_data(wb_card_id=int(callback.data.split(":")[2]))
    await callback.message.answer("🌍 Введите <b>HP Мирового Босса</b> (например: <code>25000</code>):")
    await callback.answer()


@router.message(AdminFSM.world_boss_hp)
async def fsm_adm_wb_hp(message: Message, state: FSMContext):
    cid = (await state.get_data()).get("wb_card_id")
    await state.clear()
    try:
        hp = int((message.text or "").strip())
        if hp < 500:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите число >= 500.")
        return
    card = await db.get_card(cid)
    if not card:
        await message.answer("❌ Карта босса не найдена.")
        return
    await db.spawn_world_boss(cid, hp, max(50, card["boss_atk"]))
    await db.log_admin(message.from_user.id, f"Запустил Мирового Босса {card['name']} ({hp} HP)")
    await message.answer(f"🌍🚀 Мировой Босс <b>{esc(card['name'])}</b> ({hp} HP) запущен!")


@router.callback_query(F.data == "adm:wbstop")
async def cb_adm_wbstop(callback: CallbackQuery):
    if not await check_adm_perm(callback, "manage_bosses"):
        return
    await db.stop_world_boss()
    await db.log_admin(callback.from_user.id, "Остановил Мирового Босса")
    await callback.answer("🛑 Мировой Босс остановлен!", show_alert=True)
    await cb_adm_wb(callback)


# -------------------- УПРАВЛЕНИЕ ИГРОКАМИ И ЭКОНОМИКОЙ --------------------

@router.callback_query(F.data == "adm:users")
async def cb_adm_users(callback: CallbackQuery, state: FSMContext):
    if not (await db.has_perm(callback.from_user.id, "manage_users") or await db.has_perm(callback.from_user.id, "manage_economy")):
        await callback.answer("⛔️ Нет прав!", show_alert=True)
        return
    await state.set_state(AdminFSM.find_user)
    await callback.message.answer("👥 Введите <b>@username</b> или <b>Telegram ID</b> игрока для управления:")
    await callback.answer()


async def render_adm_user_card(target: Message | CallbackQuery, target_uid: int):
    u = await db.get_user(target_uid)
    if not u:
        await render_view(target, "❌ Игрок не найден.")
        return
    ban_st = "🚫 ЗАБАНЕН" if u["is_banned"] else "🟢 Активен"
    text = (
        f"👤 <b>УПРАВЛЕНИЕ ИГРОКОМ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{format_user_link(u)} | Статус: {ban_st}\n"
        f"💰 Монеты: <b>{u['coins']}</b> | 🏆 Кубки: <b>{u['trophies']}</b>\n"
        f"🦠 Паразиты: {u['p_common']} / {u['p_upgraded']} / {u['p_astro']}"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💰 +/- Монеты", callback_data=f"adm:ucoins:{target_uid}"),
                InlineKeyboardButton(text="🃏 Выдать карту", callback_data=f"adm:ugivec:{target_uid}:0"),
            ],
            [
                InlineKeyboardButton(text="+3 🦠 Обыч.", callback_data=f"adm:upara:{target_uid}:common"),
                InlineKeyboardButton(text="+2 ☣️ Улучш.", callback_data=f"adm:upara:{target_uid}:upgraded"),
                InlineKeyboardButton(text="+1 🌌 Астро", callback_data=f"adm:upara:{target_uid}:astro"),
            ],
            [
                InlineKeyboardButton(text="🚫 Бан / Разбан", callback_data=f"adm:uban:{target_uid}"),
                InlineKeyboardButton(text="🔙 Админка", callback_data="adm:home"),
            ],
        ]
    )
    await render_view(target, text, kb)


@router.message(AdminFSM.find_user)
async def fsm_adm_find_user(message: Message, state: FSMContext):
    await state.clear()
    u = await db.find_user(message.text or "")
    if not u:
        await message.answer("❌ Игрок не найден.")
        return
    await render_adm_user_card(message, u["user_id"])


@router.callback_query(F.data.startswith("adm:ucoins:"))
async def cb_adm_ucoins(callback: CallbackQuery, state: FSMContext):
    if not await check_adm_perm(callback, "manage_economy"):
        return
    await state.set_state(AdminFSM.user_coins)
    await state.update_data(target_uid=int(callback.data.split(":")[2]))
    await callback.message.answer("💰 Введите сумму монет (например <code>1000</code> или <code>-500</code>):")
    await callback.answer()


@router.message(AdminFSM.user_coins)
async def fsm_adm_ucoins_save(message: Message, state: FSMContext):
    t_uid = (await state.get_data()).get("target_uid")
    await state.clear()
    try:
        delta = int((message.text or "").strip())
    except ValueError:
        await message.answer("❌ Введите целое число.")
        return
    await db.add_coins(t_uid, delta)
    await db.log_admin(message.from_user.id, f"Изменил баланс {t_uid} на {delta:+d}💰")
    await render_adm_user_card(message, t_uid)


@router.callback_query(F.data.startswith("adm:upara:"))
async def cb_adm_upara(callback: CallbackQuery):
    if not await check_adm_perm(callback, "manage_economy"):
        return
    _, _, uid_s, p_type = callback.data.split(":")
    t_uid = int(uid_s)
    qty = 3 if p_type == "common" else (2 if p_type == "upgraded" else 1)
    await db.add_parasite(t_uid, p_type, qty)
    await db.log_admin(callback.from_user.id, f"Выдал +{qty} {p_type} игроку {t_uid}")
    await callback.answer(f"✅ Выдано +{qty}!", show_alert=True)
    await render_adm_user_card(callback, t_uid)


@router.callback_query(F.data.startswith("adm:uban:"))
async def cb_adm_uban(callback: CallbackQuery):
    if not await check_adm_perm(callback, "manage_users"):
        return
    t_uid = int(callback.data.split(":")[2])
    if t_uid == OWNER_ID:
        await callback.answer("Нельзя забанить владельца!", show_alert=True)
        return
    u = await db.get_user(t_uid)
    if u:
        nxt = 0 if u["is_banned"] else 1
        await db.update_user(t_uid, is_banned=nxt)
        await db.log_admin(callback.from_user.id, f"Бан={nxt} для игрока {t_uid}")
    await render_adm_user_card(callback, t_uid)
    await callback.answer("Статус обновлён!")


@router.callback_query(F.data.startswith("adm:ugivec:"))
async def cb_adm_ugivec(callback: CallbackQuery):
    if not await check_adm_perm(callback, "manage_economy"):
        return
    _, _, uid_s, page_s = callback.data.split(":")
    t_uid, page = int(uid_s), int(page_s)
    cards = await db.list_cards()
    per_page = 8
    total_pages = max(1, (len(cards) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    chunk = cards[page * per_page : (page + 1) * per_page]

    rows = [
        [InlineKeyboardButton(text=f"#{c['id']} {c['name']}", callback_data=f"adm:ugivepick:{t_uid}:{c['id']}")]
        for c in chunk
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"adm:ugivec:{t_uid}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"adm:ugivec:{t_uid}:{page + 1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔙 К игроку", callback_data=f"adm:uopen:{t_uid}")])
    await render_view(callback, f"🎁 Выберите карту для выдачи игроку <code>{t_uid}</code>:", InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:uopen:"))
async def cb_adm_uopen(callback: CallbackQuery):
    await render_adm_user_card(callback, int(callback.data.split(":")[2]))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:ugivepick:"))
async def cb_adm_ugivepick(callback: CallbackQuery):
    if not await check_adm_perm(callback, "manage_economy"):
        return
    _, _, uid_s, cid_s = callback.data.split(":")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚪️ Обычная", callback_data=f"adm:ugivedo:{uid_s}:{cid_s}:none:none")],
            [InlineKeyboardButton(text="✨ Shiny", callback_data=f"adm:ugivedo:{uid_s}:{cid_s}:shiny:none")],
            [InlineKeyboardButton(text="🦠 Обыч. Инфектед", callback_data=f"adm:ugivedo:{uid_s}:{cid_s}:none:normal")],
            [InlineKeyboardButton(text="🌌 Астро-Инфектед", callback_data=f"adm:ugivedo:{uid_s}:{cid_s}:none:astro")],
            [InlineKeyboardButton(text="✨🌌 Shiny Астро-Инфектед", callback_data=f"adm:ugivedo:{uid_s}:{cid_s}:shiny:astro")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"adm:ugivec:{uid_s}:0")],
        ]
    )
    await render_view(callback, "Выберите вариант выдачи карты:", kb)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:ugivedo:"))
async def cb_adm_ugivedo(callback: CallbackQuery, bot: Bot):
    if not await check_adm_perm(callback, "manage_economy"):
        return
    _, _, uid_s, cid_s, mut, inf_t = callback.data.split(":")
    t_uid, cid = int(uid_s), int(cid_s)
    card = await db.get_card(cid)
    if not card:
        await callback.answer("Карта не найдена.", show_alert=True)
        return
    await db.give_card(t_uid, cid, mutation=mut, infected_type=inf_t)
    await db.log_admin(callback.from_user.id, f"Выдал карту #{cid} ({mut}/{inf_t}) игроку {t_uid}")
    try:
        await bot.send_message(t_uid, f"🎁 Администрация выдала вам карту: <b>{esc(card['name'])}</b>!")
    except Exception:
        pass
    await callback.answer("✅ Карта выдана!", show_alert=True)
    await render_adm_user_card(callback, t_uid)


# -------------------- АДМИНЫ, ПАРТНЁРЫ-СИГНЕРЫ, РАССЫЛКА И БД --------------------

async def render_adm_admins(target: Message | CallbackQuery):
    admins = await db.list_admins()
    rows = []
    for a in admins:
        name = a["full_name"] or str(a["user_id"])
        rows.append([InlineKeyboardButton(text=f"👮 {name} ({a['user_id']})", callback_data=f"adm:aperms:{a['user_id']}")])
    rows.append([
        InlineKeyboardButton(text="➕ Добавить админа", callback_data="adm:aadd"),
        InlineKeyboardButton(text="🔙 Админка", callback_data="adm:home"),
    ])
    await render_view(target, f"👮 <b>АДМИНИСТРАТОРЫ ({len(admins)})</b>\nНажмите на админа, чтобы переключить права:", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "adm:admins")
async def cb_adm_admins(callback: CallbackQuery):
    if not await check_adm_perm(callback, "manage_admins"):
        return
    await render_adm_admins(callback)
    await callback.answer()


@router.callback_query(F.data == "adm:aadd")
async def cb_adm_aadd(callback: CallbackQuery, state: FSMContext):
    if not await check_adm_perm(callback, "manage_admins"):
        return
    await state.set_state(AdminFSM.add_admin)
    await callback.message.answer("👮 Введите <b>@username</b> или <b>Telegram ID</b> нового администратора:")
    await callback.answer()


@router.message(AdminFSM.add_admin)
async def fsm_adm_aadd(message: Message, state: FSMContext):
    await state.clear()
    u = await db.find_user(message.text or "")
    if not u:
        await message.answer("❌ Игрок не найден в базе (он должен сначала нажать /start).")
        return
    await db.add_admin(u["user_id"], message.from_user.id)
    await db.log_admin(message.from_user.id, f"Назначил админом {u['user_id']}")
    await render_adm_admin_perms(message, u["user_id"])


async def render_adm_admin_perms(target: Message | CallbackQuery, target_uid: int):
    perms = await db.get_admin_perms(target_uid)
    u = await db.get_user(target_uid)
    title = format_user_link(u) if u else f"<code>{target_uid}</code>"
    rows = []
    for p_key, p_desc in ADMIN_PERMS.items():
        ico = "✅" if perms.get(p_key) else "❌"
        rows.append([InlineKeyboardButton(text=f"{ico} {p_desc}", callback_data=f"adm:atog:{target_uid}:{p_key}")])
    rows.append([
        InlineKeyboardButton(text="🗑 Снять админа", callback_data=f"adm:adel:{target_uid}"),
        InlineKeyboardButton(text="🔙 К списку", callback_data="adm:admins"),
    ])
    await render_view(target, f"👮 <b>ПРАВА АДМИНА:</b> {title}", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("adm:aperms:"))
async def cb_adm_aperms(callback: CallbackQuery):
    if not await check_adm_perm(callback, "manage_admins"):
        return
    await render_adm_admin_perms(callback, int(callback.data.split(":")[2]))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:atog:"))
async def cb_adm_atog(callback: CallbackQuery):
    if not await check_adm_perm(callback, "manage_admins"):
        return
    _, _, uid_s, p_key = callback.data.split(":")
    t_uid = int(uid_s)
    await db.toggle_admin_perm(t_uid, p_key)
    await db.log_admin(callback.from_user.id, f"Переключил право {p_key} у {t_uid}")
    await render_adm_admin_perms(callback, t_uid)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:adel:"))
async def cb_adm_adel(callback: CallbackQuery):
    if not await check_adm_perm(callback, "manage_admins"):
        return
    t_uid = int(callback.data.split(":")[2])
    await db.remove_admin(t_uid)
    await db.log_admin(callback.from_user.id, f"Снял админа {t_uid}")
    await callback.answer("🗑 Администратор снят!", show_alert=True)
    await render_adm_admins(callback)


# --- СИГНЕРЫ (ПАРТНЁРЫ +10% И АДМИНЫ +20%) ---

async def render_adm_signers(target: Message | CallbackQuery):
    signers = await db.list_signers()
    rows = []
    for s in signers:
        ico = "👑" if s["role"] == "admin" else "🤝"
        name = s["full_name"] or str(s["user_id"])
        rows.append([InlineKeyboardButton(text=f"❌ Убрать {ico} {name}", callback_data=f"adm:sdel:{s['user_id']}")])
    rows.append([
        InlineKeyboardButton(text="➕ Партнёр (+10%)", callback_data="adm:sadd:partner"),
        InlineKeyboardButton(text="➕ Админ-Сигнер (+20%)", callback_data="adm:sadd:admin"),
    ])
    rows.append([InlineKeyboardButton(text="🔙 Админка", callback_data="adm:home")])
    await render_view(target, f"✍️ <b>СИГНЕРЫ ({len(signers)})</b>\nНажмите на сигнера, чтобы снять права:", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "adm:signers")
async def cb_adm_signers(callback: CallbackQuery):
    if not await check_adm_perm(callback, "manage_admins"):
        return
    await render_adm_signers(callback)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:sadd:"))
async def cb_adm_sadd(callback: CallbackQuery, state: FSMContext):
    if not await check_adm_perm(callback, "manage_admins"):
        return
    role = callback.data.split(":")[2]
    await state.set_state(AdminFSM.add_signer)
    await state.update_data(signer_role=role)
    await callback.message.answer(f"✍️ Введите <b>@username</b> или <b>ID</b> игрока для выдачи роли <b>{role}</b>:")
    await callback.answer()


@router.message(AdminFSM.add_signer)
async def fsm_adm_sadd(message: Message, state: FSMContext):
    role = (await state.get_data()).get("signer_role", "partner")
    await state.clear()
    u = await db.find_user(message.text or "")
    if not u:
        await message.answer("❌ Игрок не найден.")
        return
    await db.set_signer(u["user_id"], role, message.from_user.id)
    await db.log_admin(message.from_user.id, f"Выдал роль сигнера ({role}) игроку {u['user_id']}")
    await render_adm_signers(message)


@router.callback_query(F.data.startswith("adm:sdel:"))
async def cb_adm_sdel(callback: CallbackQuery):
    if not await check_adm_perm(callback, "manage_admins"):
        return
    uid = int(callback.data.split(":")[2])
    await db.remove_signer(uid)
    await db.log_admin(callback.from_user.id, f"Снял сигнера {uid}")
    await render_adm_signers(callback)
    await callback.answer("Снято!")


# --- РАССЫЛКА, ТЕХРАБОТЫ, ЛОГИ, БЭКАП И ВОССТАНОВЛЕНИЕ БД ---

@router.callback_query(F.data == "adm:broadcast")
async def cb_adm_broadcast(callback: CallbackQuery, state: FSMContext):
    if not await check_adm_perm(callback, "broadcast"):
        return
    await state.set_state(AdminFSM.broadcast)
    await callback.message.answer("📢 Отправьте сообщение (текст или фото с подписью) для рассылки всем игрокам:")
    await callback.answer()


@router.message(AdminFSM.broadcast)
async def fsm_adm_broadcast(message: Message, state: FSMContext):
    await state.clear()
    uids = await db.get_all_active_user_ids()
    ok = 0
    for uid in uids:
        try:
            await message.send_copy(chat_id=uid)
            ok += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
    await db.log_admin(message.from_user.id, f"Рассылка: доставлено {ok}/{len(uids)}")
    await message.answer(f"✅ Рассылка завершена: <b>{ok}/{len(uids)}</b> доставлено.")


@router.callback_query(F.data == "adm:maint")
async def cb_adm_maint(callback: CallbackQuery):
    if not await check_adm_perm(callback, "manage_admins"):
        return
    nxt = "0" if GAME_SETTINGS.get("maintenance", "0") == "1" else "1"
    await db.set_setting("maintenance", nxt)
    await db.log_admin(callback.from_user.id, f"Техработы={nxt}")
    await render_admin_home(callback, callback.from_user.id)
    await callback.answer("Обновлено!")


@router.callback_query(F.data == "adm:logs")
async def cb_adm_logs(callback: CallbackQuery):
    if not await check_adm_perm(callback, "manage_admins"):
        return
    logs = await db.get_admin_logs(limit=15)
    lines = []
    for l in logs:
        dt = datetime.fromtimestamp(l["created_at"]).strftime("%d.%m %H:%M") if l["created_at"] else ""
        who = esc(l["full_name"] or str(l["admin_id"]))
        lines.append(f"<code>{dt}</code> <b>{who}</b>: {esc(l['action'])}")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Админка", callback_data="adm:home")]])
    await render_view(callback, "📜 <b>ПОСЛЕДНИЕ ДЕЙСТВИЯ АДМИНОВ</b>\n━━━━━━━━━━━━━━━━━━\n" + ("\n".join(lines) or "<i>Пусто</i>"), kb)
    await callback.answer()


@router.callback_query(F.data == "adm:backup")
async def cb_adm_backup(callback: CallbackQuery):
    if not await check_adm_perm(callback, "manage_admins"):
        return
    if os.path.exists(DB_PATH):
        await callback.message.answer_document(
            FSInputFile(DB_PATH),
            caption="💾 Бэкап БД. Чтобы восстановить БД — просто отправьте .db файл боту.",
        )
    await callback.answer()


@router.message(F.document)
async def handle_db_restore(message: Message, bot: Bot):
    if message.from_user.id != OWNER_ID:
        return
    doc = message.document
    if not doc or not (doc.file_name or "").endswith(".db"):
        return
    file = await bot.get_file(doc.file_id)
    for ext in ("-wal", "-shm", "-journal"):
        try:
            os.remove(f"{DB_PATH}{ext}")
        except OSError:
            pass
    await bot.download_file(file.file_path, DB_PATH)
    await db.init()
    await message.answer("✅ <b>База данных успешно восстановлена и мигрирована!</b>")


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    await callback.answer()


# ==============================================================================
# 9. ФОНОВЫЕ ЗАДАЧИ И ТОЧКА ВХОДА
# ==============================================================================

async def auto_backup_loop(bot: Bot) -> None:
    while True:
        await asyncio.sleep(12 * 3600)
        try:
            if os.path.exists(DB_PATH):
                await bot.send_document(OWNER_ID, FSInputFile(DB_PATH), caption="💾 Автобэкап БД Skibidi Verse.")
        except Exception as exc:
            logger.warning("Auto backup failed: %s", exc)


async def main() -> None:
    await db.init()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(AccessMiddleware())
    dp.callback_query.middleware(AccessMiddleware())
    dp.include_router(router)

    asyncio.create_task(auto_backup_loop(bot))
    logger.info("🚀 Skibidi Verse Tower Defense Bot запущен! Владелец: %s", OWNER_ID)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен.")
