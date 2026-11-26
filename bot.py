"""
Skibidi Verse Tower Defense — Telegram RPG / Card PvP & Boss Infection Bot
Стек: Python 3.10+, aiogram 3.x, aiosqlite

Установка зависимостей:
    pip install aiogram aiosqlite

Запуск:
    1. Укажите BOT_TOKEN и OWNER_ID ниже (или через переменные окружения).
    2. Запустите: python bot.py
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
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple


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
from aiogram.exceptions import TelegramBadRequest
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

BOT_TOKEN = os.getenv("BOT_TOKEN", "9149772940:AAGjZRlItcwcmWKOA9mUd_BDoj_IEkNfyzE")
OWNER_ID = int(os.getenv("OWNER_ID", "5341904332"))  # Ваш Telegram ID (Главный владелец)
DB_PATH = os.getenv("DB_PATH", "skibidi_verse.db")

MAX_DECK_SIZE = 4
WORLD_BOSS_COOLDOWN = 60  # Секунд между ударами по Мировому Боссу
DAILY_COOLDOWN = 86400    # 24 часа

# Фракции
FACTIONS: Dict[str, str] = {
    "alliance": "📷 Альянс",
    "skibidi": "🚽 Скибиди",
    "astro": "🌌 Астро",
    "infected": "🦠 Заражённые",
}

# Редкости (название, эмодзи, вес для выпадения из кейсов)
RARITIES: Dict[str, Tuple[str, str, int]] = {
    "common": ("Обычная", "⚪️", 55),
    "rare": ("Редкая", "🟢", 25),
    "epic": ("Эпическая", "🟣", 12),
    "legendary": ("Легендарная", "🟡", 5),
    "mythic": ("Мифическая", "🔴", 2),
    "secret": ("Секретная", "🌌", 1),
}

# Штаммы (мутации) при заражении боссов: ключ -> (название, множитель HP, множитель ATK)
MUTATIONS: Dict[str, Tuple[str, float, float]] = {
    "none": ("Без штамма", 1.0, 1.0),
    "toxic": ("🧪 Токсичный", 1.0, 1.15),
    "armored": ("🛡 Бронированный", 1.20, 1.0),
    "astro": ("⚡ Астро-Штамм", 1.15, 1.15),
    "alpha": ("💀 Альфа-Паразит", 1.10, 1.25),
}

# Типы паразитов: ключ -> (название, поле в БД, бонус к шансу %, цена в монетах, шанс мутации %)
PARASITES: Dict[str, Tuple[str, str, int, int, int]] = {
    "common": ("🦠 Обычный паразит", "p_common", 5, 150, 25),
    "upgraded": ("☣️ Улучшенный паразит", "p_upgraded", 18, 450, 55),
    "astro": ("🌌 Астро-паразит", "p_astro", 35, 1200, 90),
}

# Гранулярные права администраторов
ADMIN_PERMS: Dict[str, str] = {
    "manage_cards": "🃏 Создание/редактирование/удаление карт",
    "manage_bosses": "🌍 Запуск и управление Мировым Боссом",
    "manage_economy": "💰 Выдача монет, паразитов и карт",
    "manage_users": "👥 Просмотр игроков, баны и разбаны",
    "broadcast": "📢 Рассылка сообщений всем игрокам",
    "manage_admins": "👮 Назначение админов и выдача прав",
}

# Активные PvE-рейды в оперативной памяти: user_id -> dict состояния боя
ACTIVE_RAIDS: Dict[int, Dict[str, Any]] = {}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("skibidi_bot")


# ==============================================================================
# 2. БАЗА ДАННЫХ (AIOSQLITE)
# ==============================================================================

class Database:
    """Асинхронная обёртка над SQLite для хранения всех данных игры и админки."""

    def __init__(self, path: str):
        self.path = path

    async def init(self) -> None:
        """Создаёт все таблицы и наполняет стартовыми карточками при первом запуске."""
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT DEFAULT '',
                    full_name TEXT DEFAULT 'Игрок',
                    coins INTEGER DEFAULT 300,
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
                    created_at INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS admins (
                    user_id INTEGER PRIMARY KEY,
                    added_by INTEGER,
                    perms_json TEXT DEFAULT '{}',
                    added_at INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS cards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    faction TEXT NOT NULL,
                    rarity TEXT NOT NULL,
                    hp INTEGER NOT NULL,
                    atk INTEGER NOT NULL,
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
                    in_deck INTEGER DEFAULT 0,
                    acquired_at INTEGER DEFAULT 0
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
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES ('maintenance', '0')"
            )
            await db.commit()

        await self.seed_default_cards()

    async def seed_default_cards(self) -> None:
        """Добавляет стартовый набор юнитов и боссов Skibidi Verse, если таблица пуста."""
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT COUNT(*) FROM cards")
            row = await cur.fetchone()
            if row and row[0] > 0:
                return

            # Сначала добавляем обычных юнитов и заражённые версии боссов
            base_cards = [
                # (name, faction, rarity, hp, atk, desc, is_boss, boss_hp, boss_atk, infect_chance, infected_id)
                ("Камерамен", "alliance", "common", 110, 24, "Базовый боец Альянса. Надёжный старт.", 0, 0, 0, 0, 0),
                ("Спикермен", "alliance", "common", 100, 28, "Атакует звуковыми волнами.", 0, 0, 0, 0, 0),
                ("ТВ-Мен", "alliance", "rare", 135, 36, "Ослепляет врагов фиолетовым свечением.", 0, 0, 0, 0, 0),
                ("Вантузмен", "alliance", "epic", 180, 52, "Бесстрашный герой с двумя вантузами.", 0, 0, 0, 0, 0),
                ("ТВ-Вумен", "alliance", "legendary", 220, 68, "Специалист по очищению от паразитов.", 0, 0, 0, 0, 0),
                ("Скибиди-Учёный", "skibidi", "epic", 195, 48, "Создатель паразитов и кибер-улучшений.", 0, 0, 0, 0, 0),
                ("Заражённый Титан Спикермен", "infected", "mythic", 340, 88, "Заражённый титан с плазменными пушками!", 0, 0, 0, 0, 0),
                ("Заражённый Титан Камерамен", "infected", "mythic", 390, 82, "Бронированный титан под контролем паразита.", 0, 0, 0, 0, 0),
                ("Заражённый Астро Детейнер", "infected", "secret", 440, 105, "Опаснейший Астро-воин с клешнями.", 0, 0, 0, 0, 0),
            ]
            for c in base_cards:
                await db.execute(
                    """
                    INSERT INTO cards (name, faction, rarity, hp, atk, description, is_boss, boss_hp, boss_atk, infect_chance, infected_card_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    c,
                )

            # Получаем ID заражённых версий для привязки к боссам
            async def get_id(name: str) -> int:
                c = await db.execute("SELECT id FROM cards WHERE name = ?", (name,))
                r = await c.fetchone()
                return r[0] if r else 0

            inf_tsm = await get_id("Заражённый Титан Спикермен")
            inf_tcm = await get_id("Заражённый Титан Камерамен")
            inf_astro = await get_id("Заражённый Астро Детейнер")

            # Добавляем боссов для рейдов
            bosses = [
                ("Титан Спикермен (Босс)", "alliance", "legendary", 310, 78, "Мощный звуковой титан. Можно заразить в рейде!", 1, 520, 48, 18, inf_tsm),
                ("Титан Камерамен (Босс)", "alliance", "mythic", 360, 74, "Легендарный защитник с молотом. Высокая броня.", 1, 780, 62, 12, inf_tcm),
                ("Астро Детейнер (Босс)", "astro", "secret", 410, 96, "Элитный перехватчик Астро. Очень трудно заразить!", 1, 1150, 85, 8, inf_astro),
            ]
            for b in bosses:
                await db.execute(
                    """
                    INSERT INTO cards (name, faction, rarity, hp, atk, description, is_boss, boss_hp, boss_atk, infect_chance, infected_card_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    b,
                )
            await db.commit()

    # -------------------- Пользователи --------------------

    async def ensure_user(self, user_id: int, username: Optional[str], full_name: str) -> Tuple[Dict[str, Any], bool]:
        """Создаёт игрока при первом входе (и выдаёт стартовую колоду) или обновляет ник."""
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
                # Выдаём 3 стартовые карты и сразу ставим их в колоду
                starter_cur = await db.execute(
                    "SELECT id FROM cards WHERE is_boss = 0 AND rarity IN ('common', 'rare') ORDER BY id ASC LIMIT 3"
                )
                starters = await starter_cur.fetchall()
                for st in starters:
                    await db.execute(
                        "INSERT INTO inventory (user_id, card_id, level, mutation, in_deck, acquired_at) VALUES (?, ?, 1, 'none', 1, ?)",
                        (user_id, st["id"], now),
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
        """Поиск игрока по ID или @username."""
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

    async def add_parasite(self, user_id: int, p_type: str, delta: int) -> None:
        col = PARASITES[p_type][1]
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                f"UPDATE users SET {col} = MAX(0, {col} + ?) WHERE user_id = ?",
                (delta, user_id),
            )
            await db.commit()

    async def get_all_active_user_ids(self) -> List[int]:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT user_id FROM users WHERE is_banned = 0")
            rows = await cur.fetchall()
            return [r[0] for r in rows]

    # -------------------- Права и Админка --------------------

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
        perms = await self.get_admin_perms(user_id)
        return perms.get(perm, False)

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

    async def get_setting(self, key: str, default: str = "0") -> str:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = await cur.fetchone()
            return row[0] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
            )
            await db.commit()

    # -------------------- Карточки --------------------

    async def create_card(self, data: Dict[str, Any]) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                """
                INSERT INTO cards (
                    name, faction, rarity, hp, atk, description, image_id,
                    is_boss, boss_hp, boss_atk, infect_chance, infected_card_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["name"],
                    data["faction"],
                    data["rarity"],
                    int(data["hp"]),
                    int(data["atk"]),
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
            # Удаляем связанные лоты на рынке и копии из инвентаря
            await db.execute(
                "DELETE FROM market WHERE inv_id IN (SELECT id FROM inventory WHERE card_id = ?)",
                (card_id,),
            )
            await db.execute("DELETE FROM inventory WHERE card_id = ?", (card_id,))
            await db.execute("DELETE FROM cards WHERE id = ?", (card_id,))
            await db.commit()

    # -------------------- Инвентарь и Колода --------------------

    async def give_card(self, user_id: int, card_id: int, mutation: str = "none") -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "INSERT INTO inventory (user_id, card_id, level, mutation, in_deck, acquired_at) VALUES (?, ?, 1, ?, 0, ?)",
                (user_id, card_id, mutation, int(time.time())),
            )
            await db.commit()
            return cur.lastrowid

    async def get_inventory(self, user_id: int, only_deck: bool = False) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            where = "i.user_id = ?"
            if only_deck:
                where += " AND i.in_deck = 1"
            cur = await db.execute(
                f"""
                SELECT i.id AS inv_id, i.user_id, i.card_id, i.level, i.mutation, i.in_deck,
                       c.name, c.faction, c.rarity, c.hp, c.atk, c.description, c.image_id,
                       (SELECT m.id FROM market m WHERE m.inv_id = i.id) AS market_id
                FROM inventory i
                JOIN cards c ON i.card_id = c.id
                WHERE {where}
                ORDER BY i.in_deck DESC, i.level DESC, c.atk DESC
                """,
                (user_id,),
            )
            return [dict(r) for r in await cur.fetchall()]

    async def get_inv_item(self, inv_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT i.id AS inv_id, i.user_id, i.card_id, i.level, i.mutation, i.in_deck,
                       c.name, c.faction, c.rarity, c.hp, c.atk, c.description, c.image_id,
                       (SELECT m.id FROM market m WHERE m.inv_id = i.id) AS market_id
                FROM inventory i
                JOIN cards c ON i.card_id = c.id
                WHERE i.id = ?
                """,
                (inv_id,),
            )
            row = await cur.fetchone()
            return dict(row) if row else None

    async def set_in_deck(self, inv_id: int, in_deck: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE inventory SET in_deck = ? WHERE id = ?", (in_deck, inv_id))
            await db.commit()

    async def upgrade_inv_card(self, inv_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE inventory SET level = level + 1 WHERE id = ?", (inv_id,))
            await db.commit()

    # -------------------- P2P Рынок --------------------

    async def list_market(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT m.id AS market_id, m.seller_id, m.inv_id, m.price,
                       i.level, i.mutation,
                       c.name, c.faction, c.rarity, c.hp, c.atk, c.image_id,
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
            await db.execute("UPDATE inventory SET in_deck = 0 WHERE id = ?", (inv_id,))
            await db.execute(
                "INSERT INTO market (seller_id, inv_id, price, created_at) VALUES (?, ?, ?, ?)",
                (seller_id, inv_id, price, int(time.time())),
            )
            await db.commit()

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

            # Атомарный обмен
            await db.execute("UPDATE users SET coins = coins - ? WHERE user_id = ?", (lot["price"], buyer_id))
            await db.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (lot["price"], lot["seller_id"]))
            await db.execute("UPDATE inventory SET user_id = ?, in_deck = 0 WHERE id = ?", (buyer_id, lot["inv_id"]))
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

    # -------------------- PvP Арена --------------------

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
                SELECT p.*, u.username, u.full_name, u.pvp_wins
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

    # -------------------- Статистика и Топы --------------------

    async def get_leaderboard(self, column: str, limit: int = 10) -> List[Dict[str, Any]]:
        allowed = {"pvp_wins", "coins", "infections_success", "bosses_killed"}
        col = column if column in allowed else "pvp_wins"
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
            return {"users": u, "cards": c, "inventory": i, "market": m}


db = Database(DB_PATH)


# ==============================================================================
# 3. ИГРОВЫЕ РАСЧЁТЫ, СИНЕГРИИ И БОЕВОЙ ДВИЖОК
# ==============================================================================

def esc(text: Any) -> str:
    """Безопасное экранирование HTML для Telegram."""
    return html.escape(str(text or ""))


def format_user_link(user: Dict[str, Any]) -> str:
    name = esc(user.get("full_name") or "Игрок")
    uname = user.get("username")
    if uname:
        return f"<b>{name}</b> (@{esc(uname)})"
    return f"<b>{name}</b> [<code>{user.get('user_id')}</code>]"


def calc_card_stats(item: Dict[str, Any]) -> Tuple[int, int]:
    """Считает реальные HP и ATK карты с учётом уровня (+10%/ур.) и штамма мутации."""
    lvl = max(1, int(item.get("level", 1)))
    mut_key = item.get("mutation", "none")
    _, hp_mult, atk_mult = MUTATIONS.get(mut_key, ("", 1.0, 1.0))
    lvl_mult = 1.0 + (lvl - 1) * 0.10
    hp = int(item["hp"] * lvl_mult * hp_mult)
    atk = int(item["atk"] * lvl_mult * atk_mult)
    return hp, atk


def calc_deck_summary(deck: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Считает суммарную мощь колоды и активные синергии фракций."""
    total_hp = 0
    total_atk = 0
    factions: Dict[str, int] = {}

    for card in deck:
        hp, atk = calc_card_stats(card)
        total_hp += hp
        total_atk += atk
        f = card["faction"]
        factions[f] = factions.get(f, 0) + 1

    synergies: List[str] = []
    # Синергии за 2+ карты одной фракции
    if factions.get("alliance", 0) >= 2:
        total_hp = int(total_hp * 1.15)
        synergies.append("📷 Единство Альянса (+15% HP)")
    if factions.get("infected", 0) >= 2:
        total_atk = int(total_atk * 1.18)
        synergies.append("🦠 Рой Паразитов (+18% ATK + шанс оглушения)")
    if factions.get("skibidi", 0) >= 2:
        total_atk = int(total_atk * 1.12)
        synergies.append("🚽 Хаос Скибиди (+12% ATK)")
    if factions.get("astro", 0) >= 2:
        total_hp = int(total_hp * 1.10)
        total_atk = int(total_atk * 1.12)
        synergies.append("🌌 Превосходство Астро (+10% HP, +12% ATK)")

    has_infected_stun = factions.get("infected", 0) >= 1
    power = total_hp + total_atk * 4
    return {
        "hp": total_hp,
        "atk": total_atk,
        "power": power,
        "synergies": synergies,
        "has_infected_stun": has_infected_stun,
    }


def get_rank_title(user: Dict[str, Any]) -> str:
    """Звание игрока на основе его достижений."""
    score = user["pvp_wins"] * 3 + user["infections_success"] * 5 + user["bosses_killed"]
    if score >= 120:
        return "🌌 Повелитель Титанов"
    if score >= 60:
        return "🦠 Альфа-Учёный"
    if score >= 25:
        return "⚔️ Элитный Агент"
    if score >= 8:
        return "📷 Охотник на Боссов"
    return "🚽 Новобранец"


def make_hp_bar(current: int, maximum: int, length: int = 10) -> str:
    if maximum <= 0:
        return "⬜" * length
    ratio = max(0.0, min(1.0, current / maximum))
    filled = int(round(ratio * length))
    return "🟥" * filled + "⬛" * (length - filled)


def simulate_pvp_battle(
    deck1: List[Dict[str, Any]],
    deck2: List[Dict[str, Any]],
    name1: str,
    name2: str,
) -> Tuple[int, str]:
    """
    Пошаговая симуляция PvP-дуэли двух колод.
    Возвращает: (1 если победил первый, 2 если второй; подробный боевой лог).
    """
    s1 = calc_deck_summary(deck1)
    s2 = calc_deck_summary(deck2)

    hp1, max_hp1 = max(1, s1["hp"]), max(1, s1["hp"])
    hp2, max_hp2 = max(1, s2["hp"]), max(1, s2["hp"])
    atk1, atk2 = max(1, s1["atk"]), max(1, s2["atk"])

    logs = [
        f"⚔️ <b>PvP ДУЭЛЬ: {esc(name1)} vs {esc(name2)}</b>",
        f"👤 {esc(name1)}: ❤️ {max_hp1} | ⚔️ {atk1}",
        f"👤 {esc(name2)}: ❤️ {max_hp2} | ⚔️ {atk2}",
        "",
    ]

    turn = 1
    while hp1 > 0 and hp2 > 0 and turn <= 15:
        # Ход 1-го игрока
        stun2 = False
        dmg1 = int(atk1 * random.uniform(0.85, 1.20))
        crit1 = random.random() < 0.18
        if crit1:
            dmg1 = int(dmg1 * 1.45)
        hp2 = max(0, hp2 - dmg1)
        note1 = " 💥КРИТ!" if crit1 else ""
        if s1["has_infected_stun"] and random.random() < 0.14:
            stun2 = True
            note1 += " 🦠ПАРАЗИТ!"
        logs.append(f"🔹 <b>Раунд {turn}:</b> {esc(name1)} ➔ <b>-{dmg1}</b>{note1} (HP врага: {hp2})")
        if hp2 <= 0:
            break

        # Ход 2-го игрока
        if stun2:
            logs.append(f"   🦠 {esc(name2)} оглушён паразитом и пропускает атаку!")
        else:
            dmg2 = int(atk2 * random.uniform(0.85, 1.20))
            crit2 = random.random() < 0.18
            if crit2:
                dmg2 = int(dmg2 * 1.45)
            hp1 = max(0, hp1 - dmg2)
            note2 = " 💥КРИТ!" if crit2 else ""
            logs.append(f"🔸 {esc(name2)} ➔ <b>-{dmg2}</b>{note2} (HP: {hp1})")
        turn += 1

    winner = 1 if hp1 >= hp2 else 2
    win_name = name1 if winner == 1 else name2
    logs.append("")
    logs.append(f"🏆 <b>Победитель: {esc(win_name)}!</b>")
    return winner, "\n".join(logs)


# ==============================================================================
# 4. УНИВЕРСАЛЬНЫЙ РЕНДЕР СООБЩЕНИЙ И КЛАВИАТУРЫ
# ==============================================================================

async def render_view(
    target: Message | CallbackQuery,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    photo: Optional[str] = None,
) -> None:
    """
    Умная отрисовка: безопасно редактирует текст или фото, а при смене типа
    (текст <-> фото) удаляет старое сообщение и отправляет новое без крашей.
    """
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
    """
    Статичное нижнее меню (кнопка рядом с полем ввода на ПК и панель снизу на телефоне).
    """
    rows = [
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🃏 Колода и Карты")],
        [KeyboardButton(text="👹 Рейды Боссов"), KeyboardButton(text="🌐 Мультиплеер")],
        [KeyboardButton(text="🧪 Лаборатория и Магазин"), KeyboardButton(text="🏆 Рейтинг")],
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
    """Красивое описание карточки (как шаблонной, так и из инвентаря игрока)."""
    r_name, r_ico, _ = RARITIES.get(card["rarity"], ("Обычная", "⚪️", 1))
    f_name = FACTIONS.get(card["faction"], card["faction"])

    if inv_item:
        hp, atk = calc_card_stats(inv_item)
        lvl = inv_item["level"]
        mut_name = MUTATIONS.get(inv_item["mutation"], ("Без штамма", 1.0, 1.0))[0]
        deck_tag = "✅ В колоде" if inv_item["in_deck"] else "📦 В инвентаре"
        market_tag = " | 🏷 На рынке" if inv_item.get("market_id") else ""
        lines = [
            f"{r_ico} <b>{esc(card['name'])}</b>  <i>(Ур. {lvl})</i>",
            f"Фракция: {f_name} | Редкость: {r_name}",
            f"Штамм: <b>{mut_name}</b>",
            f"Статус: {deck_tag}{market_tag}",
            "",
            f"❤️ HP: <b>{hp}</b>   |   ⚔️ Атака: <b>{atk}</b>",
        ]
    else:
        lines = [
            f"{r_ico} <b>{esc(card['name'])}</b>  [ID: <code>{card['id']}</code>]",
            f"Фракция: {f_name} | Редкость: {r_name}",
            f"❤️ HP: <b>{card['hp']}</b>   |   ⚔️ Атака: <b>{card['atk']}</b>",
        ]
        if card.get("is_boss"):
            lines.append(
                f"👹 <b>БОСС РЕЙДА:</b> HP {card['boss_hp']} | ATK {card['boss_atk']} | 🦠 Баз. заражение: {card['infect_chance']}%"
            )
            lines.append(f"🔗 ID заражённой версии: <code>{card.get('infected_card_id', 0)}</code>")

    if card.get("description"):
        lines.append(f"\n📝 <i>{esc(card['description'])}</i>")
    return "\n".join(lines)


# ==============================================================================
# 5. MIDDLEWARE (АВТОРЕГИСТРАЦИЯ, БАНЫ, РЕЖИМ ТЕХРАБОТ)
# ==============================================================================

class AccessMiddleware(BaseMiddleware):
    """Проверяет регистрацию, блокировку пользователя и режим техработ."""

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

            maint = await db.get_setting("maintenance", "0")
            if maint == "1" and not is_adm:
                if isinstance(event, Message):
                    await event.answer("🛠 <b>Идут технические работы!</b>\nБот скоро вернётся с обновлениями.")
                elif isinstance(event, CallbackQuery):
                    await event.answer("🛠 Идут техработы, попробуйте позже.", show_alert=True)
                return

            data["db_user"] = user
            data["is_admin"] = is_adm

        return await handler(event, data)


# ==============================================================================
# 6. FSM СОСТОЯНИЯ (КОНСТРУКТОР КАРТ, РЕДАКТОР, РЫНОК, PVP, АДМИНКА)
# ==============================================================================

class CardCreateFSM(StatesGroup):
    name = State()
    faction = State()
    rarity = State()
    hp = State()
    atk = State()
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


class AdminFSM(StatesGroup):
    add_admin = State()
    find_user = State()
    user_coins = State()
    broadcast = State()
    world_boss_hp = State()


class PlayerFSM(StatesGroup):
    profile_search = State()
    market_price = State()
    pvp_bet = State()
    pvp_target = State()


# ==============================================================================
# 7. РОУТЕР И ОСНОВНЫЕ ОБРАБОТЧИКИ ИГРОКА
# ==============================================================================

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, is_admin: bool):
    await state.clear()
    user, is_new = await db.ensure_user(
        message.from_user.id, message.from_user.username, message.from_user.full_name
    )
    bonus_msg = (
        "\n\n🎁 <b>Стартовый набор выдан:</b> 3 юнита уже в колоде, 300 💰 и 2 🦠 паразита!"
        if is_new
        else ""
    )
    text = (
        f"🚽 <b>Добро пожаловать в Skibidi Verse Tower Defense!</b>\n\n"
        f"Собирай мощную колоду, сражайся с Титанами в рейдах и <b>заражай поверженных боссов паразитами</b>, "
        f"чтобы заполучить их уникальные мутировавшие версии!\n\n"
        f"⚔️ Дерись с игроками на PvP-арене, бей общего Мирового Босса и торгуй редкими картами на P2P-рынке.{bonus_msg}\n\n"
        f"👇 Используй <b>статичное меню снизу</b> для навигации."
    )
    await message.answer(text, reply_markup=main_reply_keyboard(is_admin))


# -------------------- ПРОФИЛЬ И СТАТИСТИКА --------------------

async def build_profile_text(user: Dict[str, Any], is_self: bool = True) -> str:
    inv = await db.get_inventory(user["user_id"])
    deck = [c for c in inv if c["in_deck"]]
    summary = calc_deck_summary(deck)

    unique_cards = len({c["card_id"] for c in inv})
    infected_cards = sum(1 for c in inv if c["faction"] == "infected" or c["mutation"] != "none")
    total_pvp = user["pvp_wins"] + user["pvp_losses"]
    winrate = round((user["pvp_wins"] / total_pvp) * 100, 1) if total_pvp > 0 else 0.0
    total_inf = user["infections_success"] + user["infections_fail"]
    inf_rate = round((user["infections_success"] / total_inf) * 100, 1) if total_inf > 0 else 0.0
    reg_date = datetime.fromtimestamp(user["created_at"]).strftime("%d.%m.%Y") if user["created_at"] else "—"

    syn_text = "\n".join(f"   • {s}" for s in summary["synergies"]) if summary["synergies"] else "   • Нет активных синергий"
    header = "👤 <b>ВАШ ПРОФИЛЬ</b>" if is_self else "🔎 <b>ПРОФИЛЬ ИГРОКА</b>"

    return (
        f"{header}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🪪 Игрок: {format_user_link(user)}\n"
        f"🎖 Звание: <b>{get_rank_title(user)}</b>\n"
        f"📅 В игре с: <code>{reg_date}</code>\n\n"
        f"💰 Баланс: <b>{user['coins']}</b> монет\n"
        f"🦠 Паразиты: Обыч. <b>{user['p_common']}</b> | Улучш. <b>{user['p_upgraded']}</b> | Астро <b>{user['p_astro']}</b>\n\n"
        f"🛡 <b>Боевая колода ({len(deck)}/{MAX_DECK_SIZE}):</b>\n"
        f"   ⚡ Мощь: <b>{summary['power']}</b> (❤️ {summary['hp']} | ⚔️ {summary['atk']})\n"
        f"{syn_text}\n\n"
        f"📊 <b>Подробная статистика:</b>\n"
        f"   🃏 Карт всего: <b>{len(inv)}</b> (Уникальных: {unique_cards} | Заражённых: {infected_cards})\n"
        f"   ⚔️ PvP: <b>{user['pvp_wins']}W / {user['pvp_losses']}L</b> (Винрейт: {winrate}%)\n"
        f"   👹 Боссов побеждено: <b>{user['bosses_killed']}</b>\n"
        f"   🦠 Заражений: <b>{user['infections_success']}</b> удач / {user['infections_fail']} неудач ({inf_rate}%)\n"
        f"   🎯 Усталость брони (Пити): <b>+{user['pity_bonus']}%</b> к след. заражению\n"
        f"   🔥 Серия ежедневных входов: <b>{user['daily_streak']} дн.</b>"
    )


def profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎁 Ежедневный бонус", callback_data="prof:daily"),
                InlineKeyboardButton(text="🔎 Найти игрока", callback_data="prof:search"),
            ],
            [InlineKeyboardButton(text="🔄 Обновить статистику", callback_data="prof:refresh")],
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
        h, m = rem // 3600, (rem % 3600) // 60
        await callback.answer(f"⏳ Бонус будет доступен через {h}ч {m}м!", show_alert=True)
        return

    streak = user["daily_streak"] + 1 if diff < DAILY_COOLDOWN * 2 else 1
    coins_reward = 150 + min(streak, 10) * 35
    extra_text = ""
    await db.update_user(user["user_id"], last_daily=now, daily_streak=streak)
    await db.add_coins(user["user_id"], coins_reward)

    if streak % 3 == 0:
        await db.add_parasite(user["user_id"], "upgraded", 1)
        extra_text = " + 1 ☣️ Улучшенный паразит!"
    else:
        await db.add_parasite(user["user_id"], "common", 1)
        extra_text = " + 1 🦠 Обычный паразит!"

    await callback.answer(f"🎁 Получено {coins_reward} 💰{extra_text} (День {streak})", show_alert=True)
    fresh = await db.get_user(user["user_id"])
    await render_view(callback, await build_profile_text(fresh, True), profile_kb())


@router.callback_query(F.data == "prof:search")
async def cb_prof_search(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PlayerFSM.profile_search)
    await callback.message.answer("🔎 Введите <b>@username</b> или <b>Telegram ID</b> игрока для просмотра профиля:")
    await callback.answer()


@router.message(PlayerFSM.profile_search)
async def fsm_prof_search(message: Message, state: FSMContext):
    await state.clear()
    target = await db.find_user(message.text or "")
    if not target:
        await message.answer("❌ Игрок не найден в базе бота.")
        return
    await message.answer(await build_profile_text(target, is_self=(target["user_id"] == message.from_user.id)))


# -------------------- КОЛОДА И ИНВЕНТАРЬ --------------------

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
        hp, atk = calc_card_stats(c)
        r_ico = RARITIES.get(c["rarity"], ("", "⚪️", 1))[1]
        deck_lines.append(f"{idx}. {r_ico} <b>{esc(c['name'])}</b> (Ур.{c['level']}) — ❤️{hp} ⚔️{atk}")

    text = (
        f"🃏 <b>КОЛОДА И ИНВЕНТАРЬ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚔️ <b>Активная колода ({len(deck)}/{MAX_DECK_SIZE}) | Мощь: {summary['power']}:</b>\n"
        + ("\n".join(deck_lines) if deck_lines else "<i>Колода пуста — выберите карты ниже!</i>")
        + f"\n\n📦 Всего карт: <b>{len(inv)}</b> | Страница {page + 1}/{total_pages}\n"
        f"Нажмите на карту для осмотра, экипировки, прокачки или продажи:"
    )

    buttons: List[List[InlineKeyboardButton]] = []
    for item in chunk:
        r_ico = RARITIES.get(item["rarity"], ("", "⚪️", 1))[1]
        mark = "✅ " if item["in_deck"] else ("🏷 " if item.get("market_id") else "")
        mut_mark = "🧬" if item["mutation"] != "none" else ""
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{mark}{r_ico}{mut_mark} {item['name']} (Ур.{item['level']})",
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


@router.message(F.text == "🃏 Колода и Карты")
async def menu_inventory(message: Message, state: FSMContext):
    await state.clear()
    await render_inventory_page(message, message.from_user.id, 0)


@router.callback_query(F.data.startswith("inv:page:"))
async def cb_inv_page(callback: CallbackQuery):
    page = int(callback.data.split(":")[2])
    await render_inventory_page(callback, callback.from_user.id, page)
    await callback.answer()


@router.callback_query(F.data.startswith("inv:view:"))
async def cb_inv_view(callback: CallbackQuery):
    _, _, inv_id_s, page_s = callback.data.split(":")
    inv_id, page = int(inv_id_s), int(page_s)
    item = await db.get_inv_item(inv_id)
    if not item or item["user_id"] != callback.from_user.id:
        await callback.answer("Карта не найдена.", show_alert=True)
        return

    upgrade_cost = 120 * item["level"]
    text = format_card_text(item, inv_item=item)
    text += f"\n\n⬆️ Прокачка до Ур.{item['level'] + 1}: <b>{upgrade_cost} 💰</b> (+10% к статам)"

    kb_rows = []
    if not item.get("market_id"):
        deck_btn = (
            InlineKeyboardButton(text="➖ Убрать из колоды", callback_data=f"inv:deck:{inv_id}:0:{page}")
            if item["in_deck"]
            else InlineKeyboardButton(text="➕ В колоду", callback_data=f"inv:deck:{inv_id}:1:{page}")
        )
        kb_rows.append([deck_btn, InlineKeyboardButton(text=f"⬆️ Улучшить ({upgrade_cost}💰)", callback_data=f"inv:upg:{inv_id}:{page}")])
        kb_rows.append([InlineKeyboardButton(text="🏷 Выставить на Рынок", callback_data=f"inv:sell:{inv_id}")])
    else:
        kb_rows.append([InlineKeyboardButton(text="🏷 Карта выставлена на рынке", callback_data="noop")])

    kb_rows.append([InlineKeyboardButton(text="🔙 Назад к инвентарю", callback_data=f"inv:page:{page}")])
    await render_view(callback, text, InlineKeyboardMarkup(inline_keyboard=kb_rows), photo=item.get("image_id") or None)
    await callback.answer()


@router.callback_query(F.data.startswith("inv:deck:"))
async def cb_inv_deck(callback: CallbackQuery):
    _, _, inv_id_s, mode_s, page_s = callback.data.split(":")
    inv_id, mode, page = int(inv_id_s), int(mode_s), int(page_s)
    item = await db.get_inv_item(inv_id)
    if not item or item["user_id"] != callback.from_user.id:
        await callback.answer("Ошибка доступа.", show_alert=True)
        return

    if mode == 1:
        if item.get("market_id"):
            await callback.answer("Сначала снимите карту с рынка!", show_alert=True)
            return
        deck = await db.get_inventory(callback.from_user.id, only_deck=True)
        if len(deck) >= MAX_DECK_SIZE:
            await callback.answer(f"В колоде максимум {MAX_DECK_SIZE} карты! Сначала уберите другую.", show_alert=True)
            return

    await db.set_in_deck(inv_id, mode)
    await callback.answer("✅ Добавлено в колоду!" if mode else "📦 Убрано из колоды.")
    # Перерисовываем карточку
    callback.data = f"inv:view:{inv_id}:{page}"
    await cb_inv_view(callback)


@router.callback_query(F.data.startswith("inv:upg:"))
async def cb_inv_upgrade(callback: CallbackQuery):
    _, _, inv_id_s, page_s = callback.data.split(":")
    inv_id, page = int(inv_id_s), int(page_s)
    item = await db.get_inv_item(inv_id)
    if not item or item["user_id"] != callback.from_user.id:
        await callback.answer("Карта не найдена.", show_alert=True)
        return
    if item["level"] >= 20:
        await callback.answer("Достигнут максимальный 20 уровень!", show_alert=True)
        return

    cost = 120 * item["level"]
    user = await db.get_user(callback.from_user.id)
    if user["coins"] < cost:
        await callback.answer(f"Не хватает монет! Нужно {cost} 💰.", show_alert=True)
        return

    await db.add_coins(user["user_id"], -cost)
    await db.upgrade_inv_card(inv_id)
    await callback.answer(f"⬆️ Карта улучшена до Ур.{item['level'] + 1}!", show_alert=True)
    callback.data = f"inv:view:{inv_id}:{page}"
    await cb_inv_view(callback)


@router.callback_query(F.data.startswith("inv:sell:"))
async def cb_inv_sell(callback: CallbackQuery, state: FSMContext):
    inv_id = int(callback.data.split(":")[2])
    item = await db.get_inv_item(inv_id)
    if not item or item["user_id"] != callback.from_user.id:
        await callback.answer("Карта не найдена.", show_alert=True)
        return
    if item.get("market_id"):
        await callback.answer("Уже на рынке!", show_alert=True)
        return

    await state.set_state(PlayerFSM.market_price)
    await state.update_data(sell_inv_id=inv_id)
    await callback.message.answer(
        f"🏷 Введите цену в монетах для продажи карты <b>{esc(item['name'])}</b> (от 50 до 100000):"
    )
    await callback.answer()


@router.message(PlayerFSM.market_price)
async def fsm_market_price(message: Message, state: FSMContext):
    data = await state.get_data()
    inv_id = data.get("sell_inv_id")
    await state.clear()
    try:
        price = int((message.text or "").strip())
        if not (50 <= price <= 100000):
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите целое число от 50 до 100000.")
        return

    item = await db.get_inv_item(inv_id)
    if not item or item["user_id"] != message.from_user.id or item.get("market_id"):
        await message.answer("❌ Карта больше недоступна для выставления.")
        return

    await db.create_market_lot(message.from_user.id, inv_id, price)
    await message.answer(
        f"✅ Карта <b>{esc(item['name'])}</b> выставлена на P2P-рынок за <b>{price} 💰</b>!\n"
        f"<i>(Она временно убрана из вашей боевой колоды.)</i>"
    )


# -------------------- РЕЙДЫ БОССОВ И МЕХАНИКА ЗАРАЖЕНИЯ --------------------

@router.message(F.text == "👹 Рейды Боссов")
async def menu_raids(message: Message, state: FSMContext):
    await state.clear()
    bosses = await db.list_cards(only_bosses=True)
    if not bosses:
        await message.answer("👹 Пока нет доступных боссов. Админ может создать их в Админ-панели!")
        return

    user = await db.get_user(message.from_user.id)
    text = (
        f"👹 <b>РЕЙДЫ НА БОССОВ (PvE + ЗАРАЖЕНИЕ)</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Победи босса своей колодой, чтобы открыть <b>Фазу Заражения</b> и запустить паразита!\n"
        f"🎯 Твой текущий бонус <b>Усталости брони (Пити)</b>: <b>+{user['pity_bonus']}%</b>\n\n"
        f"Выбери цель для охоты:"
    )
    rows = []
    for b in bosses:
        r_ico = RARITIES.get(b["rarity"], ("", "⚪️", 1))[1]
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{r_ico} {b['name']} (HP {b['boss_hp']} | 🦠 {b['infect_chance']}%)",
                    callback_data=f"raid:start:{b['id']}",
                )
            ]
        )
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


def raid_combat_kb(special_ready: bool) -> InlineKeyboardMarkup:
    spec_text = "💥 Спец-атака (ГОТОВО)" if special_ready else "💥 Спец-атака (КД)"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⚔️ Атаковать", callback_data="raid:act:atk"),
                InlineKeyboardButton(text=spec_text, callback_data="raid:act:spec"),
            ],
            [
                InlineKeyboardButton(text="🛡 Щит + Хил", callback_data="raid:act:heal"),
                InlineKeyboardButton(text="🏃 Сбежать", callback_data="raid:act:flee"),
            ],
        ]
    )


def format_raid_state(raid: Dict[str, Any], log_line: str) -> str:
    return (
        f"👹 <b>РЕЙД: {esc(raid['boss_name'])}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👹 Босс: {make_hp_bar(raid['b_hp'], raid['b_max_hp'])}\n"
        f"   ❤️ <b>{raid['b_hp']} / {raid['b_max_hp']}</b> | ⚔️ {raid['b_atk']}\n\n"
        f"🛡 Твоя колода: {make_hp_bar(raid['p_hp'], raid['p_max_hp'])}\n"
        f"   ❤️ <b>{raid['p_hp']} / {raid['p_max_hp']}</b> | ⚔️ {raid['p_atk']}\n\n"
        f"📜 <i>{log_line}</i>"
    )


@router.callback_query(F.data.startswith("raid:start:"))
async def cb_raid_start(callback: CallbackQuery):
    boss_id = int(callback.data.split(":")[2])
    boss = await db.get_card(boss_id)
    if not boss or not boss["is_boss"]:
        await callback.answer("Босс не найден!", show_alert=True)
        return

    deck = await db.get_inventory(callback.from_user.id, only_deck=True)
    if not deck:
        await callback.answer("Сначала добавьте хотя бы 1 карту в колоду!", show_alert=True)
        return

    s = calc_deck_summary(deck)
    raid = {
        "boss_id": boss["id"],
        "boss_name": boss["name"],
        "boss_image": boss.get("image_id") or "",
        "b_hp": max(100, boss["boss_hp"]),
        "b_max_hp": max(100, boss["boss_hp"]),
        "b_atk": max(15, boss["boss_atk"]),
        "infect_chance": boss["infect_chance"],
        "infected_card_id": boss["infected_card_id"],
        "p_hp": max(100, s["hp"]),
        "p_max_hp": max(100, s["hp"]),
        "p_atk": max(20, s["atk"]),
        "spec_cd": 0,
        "phase": "combat",
    }
    ACTIVE_RAIDS[callback.from_user.id] = raid
    await render_view(
        callback,
        format_raid_state(raid, "Бой начался! Выбери действие."),
        raid_combat_kb(True),
        photo=raid["boss_image"] or None,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("raid:act:"))
async def cb_raid_action(callback: CallbackQuery):
    uid = callback.from_user.id
    raid = ACTIVE_RAIDS.get(uid)
    if not raid or raid["phase"] != "combat":
        await callback.answer("Нет активного боя.", show_alert=True)
        return

    action = callback.data.split(":")[2]
    if action == "flee":
        ACTIVE_RAIDS.pop(uid, None)
        await render_view(callback, "🏃 Вы отступили с поля боя. Босс скрылся в тумане.")
        await callback.answer()
        return

    shield = False
    log_parts = []

    if action == "atk":
        dmg = int(raid["p_atk"] * random.uniform(0.9, 1.15))
        if random.random() < 0.2:
            dmg = int(dmg * 1.45)
            log_parts.append(f"💥 КРИТ! Вы нанесли {dmg} урона!")
        else:
            log_parts.append(f"⚔️ Вы нанесли {dmg} урона.")
        raid["b_hp"] = max(0, raid["b_hp"] - dmg)
        raid["spec_cd"] = max(0, raid["spec_cd"] - 1)

    elif action == "spec":
        if raid["spec_cd"] > 0:
            await callback.answer(f"Спец-атака перезаряжается ещё {raid['spec_cd']} ход(а)!", show_alert=True)
            return
        dmg = int(raid["p_atk"] * random.uniform(1.65, 2.0))
        raid["b_hp"] = max(0, raid["b_hp"] - dmg)
        raid["spec_cd"] = 2
        log_parts.append(f"🔥 СПЕЦ-УДАР! Оглушительные {dmg} урона!")

    elif action == "heal":
        heal = int(raid["p_max_hp"] * 0.26)
        raid["p_hp"] = min(raid["p_max_hp"], raid["p_hp"] + heal)
        shield = True
        raid["spec_cd"] = max(0, raid["spec_cd"] - 1)
        log_parts.append(f"🛡 Щит поднят (-50% урона) и восстановлено +{heal} HP!")

    # Проверка победы над боссом -> ПЕРЕХОД В ФАЗУ ЗАРАЖЕНИЯ!
    if raid["b_hp"] <= 0:
        raid["phase"] = "infect"
        user = await db.get_user(uid)
        coin_reward = max(80, raid["b_max_hp"] // 4)
        await db.add_coins(uid, coin_reward)
        await db.update_user(uid, bosses_killed=user["bosses_killed"] + 1)

        base_c = raid["infect_chance"]
        pity = user["pity_bonus"]
        kb_rows = []
        for p_key, (p_name, p_col, p_bonus, _, _) in PARASITES.items():
            cnt = user[p_col]
            total_ch = min(95, base_c + p_bonus + pity)
            kb_rows.append(
                [
                    InlineKeyboardButton(
                        text=f"{p_name} ({cnt} шт.) — Шанс {total_ch}%",
                        callback_data=f"raid:inf:{p_key}",
                    )
                ]
            )
        kb_rows.append([InlineKeyboardButton(text="❌ Пропустить заражение", callback_data="raid:inf:skip")])

        win_text = (
            f"🏆 <b>БОСС ПОВЕРЖЕН: {esc(raid['boss_name'])}!</b>\n"
            f"💰 Награда за победу: <b>+{coin_reward} монет</b>\n\n"
            f"🦠 <b>ФАЗА ЗАРАЖЕНИЯ ОТКРЫТА!</b>\n"
            f"Броня босса пробита! Выбери паразита, чтобы попытаться взять его под контроль:\n"
            f"<i>Базовый шанс: {base_c}% + Пити: +{pity}% + Бонус паразита</i>"
        )
        await render_view(callback, win_text, InlineKeyboardMarkup(inline_keyboard=kb_rows), photo=raid["boss_image"] or None)
        await callback.answer("🏆 Победа! Запускай паразита!")
        return

    # Ответный удар босса
    b_dmg = int(raid["b_atk"] * random.uniform(0.85, 1.15))
    if shield:
        b_dmg = b_dmg // 2
    raid["p_hp"] = max(0, raid["p_hp"] - b_dmg)
    log_parts.append(f"👹 Босс ответил на {b_dmg} урона!")

    if raid["p_hp"] <= 0:
        ACTIVE_RAIDS.pop(uid, None)
        await render_view(
            callback,
            f"💀 <b>ПОРАЖЕНИЕ!</b>\n{esc(raid['boss_name'])} разгромил вашу колоду.\n\n"
            f"💡 Прокачайте карты в инвентаре или соберите синергию фракций!",
        )
        await callback.answer("Поражение...")
        return

    await render_view(
        callback,
        format_raid_state(raid, " ".join(log_parts)),
        raid_combat_kb(raid["spec_cd"] == 0),
        photo=raid["boss_image"] or None,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("raid:inf:"))
async def cb_raid_infect(callback: CallbackQuery):
    uid = callback.from_user.id
    raid = ACTIVE_RAIDS.get(uid)
    if not raid or raid["phase"] != "infect":
        await callback.answer("Фаза заражения уже завершена.", show_alert=True)
        return

    p_key = callback.data.split(":")[2]
    if p_key == "skip":
        ACTIVE_RAIDS.pop(uid, None)
        await render_view(callback, "💨 Вы решили не тратить паразитов и забрали только монеты.")
        await callback.answer()
        return

    if p_key not in PARASITES:
        await callback.answer("Неизвестный паразит.", show_alert=True)
        return

    p_name, p_col, p_bonus, _, mut_chance = PARASITES[p_key]
    user = await db.get_user(uid)
    if user[p_col] <= 0:
        await callback.answer(f"У вас нет «{p_name}»! Купите или скрафтите в Лаборатории.", show_alert=True)
        return

    ACTIVE_RAIDS.pop(uid, None)
    await db.add_parasite(uid, p_key, -1)

    total_chance = min(95, raid["infect_chance"] + p_bonus + user["pity_bonus"])
    roll = random.randint(1, 100)

    if roll <= total_chance:
        # УСПЕШНОЕ ЗАРАЖЕНИЕ!
        target_card_id = raid["infected_card_id"]
        reward_card = await db.get_card(target_card_id) if target_card_id else None
        if not reward_card:
            reward_card = await db.get_card(raid["boss_id"])

        # Ролл штамма мутации
        mutation = "none"
        if random.randint(1, 100) <= mut_chance:
            mutation = random.choice(["toxic", "armored", "astro", "alpha"])

        await db.give_card(uid, reward_card["id"], mutation=mutation)
        await db.update_user(
            uid,
            infections_success=user["infections_success"] + 1,
            pity_bonus=0,
        )
        mut_label = MUTATIONS[mutation][0]
        text = (
            f"🦠💥 <b>УСПЕШНОЕ ЗАРАЖЕНИЕ!</b> (Шанс был {total_chance}%)\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Паразит пробил защиту и подчинил босса вашей воле!\n\n"
            f"🎁 В инвентарь добавлена карта:\n"
            f"⭐️ <b>{esc(reward_card['name'])}</b>\n"
            f"🧬 Штамм: <b>{mut_label}</b>\n\n"
            f"<i>Зайдите в «🃏 Колода и Карты», чтобы поставить его в строй!</i>"
        )
        await render_view(callback, text, photo=reward_card.get("image_id") or None)
        await callback.answer("🦠 ЗАРАЖЁН!", show_alert=True)
    else:
        # НЕУДАЧА -> Копим Пити (Усталость брони)
        new_pity = min(30, user["pity_bonus"] + 3)
        await db.update_user(
            uid,
            infections_fail=user["infections_fail"] + 1,
            pity_bonus=new_pity,
        )
        text = (
            f"💔 <b>ЗАРАЖЕНИЕ ПРОВАЛИЛОСЬ...</b> (Шанс был {total_chance}%, выпало {roll})\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{esc(raid['boss_name'])} сбросил паразита в последний момент!\n\n"
            f"🎯 <b>Усталость брони (Пити)</b> увеличена до <b>+{new_pity}%</b> на следующую попытку!"
        )
        await render_view(callback, text)
        await callback.answer("Не повезло, но Пити вырос!")


# -------------------- МУЛЬТИПЛЕЕР (МИРОВОЙ БОСС, PVP, P2P РЫНОК) --------------------

def mp_hub_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌍 Мировой Босс (Общий рейд)", callback_data="mp:wb")],
            [InlineKeyboardButton(text="⚔️ PvP Арена (Дуэли и Ставки)", callback_data="mp:pvp")],
            [InlineKeyboardButton(text="🏪 P2P Рынок игроков", callback_data="mp:market:0")],
        ]
    )


@router.message(F.text == "🌐 Мультиплеер")
async def menu_multiplayer(message: Message, state: FSMContext):
    await state.clear()
    wb = await db.get_active_world_boss()
    wb_status = f"🟢 АКТИВЕН ({wb['name']} — {wb['current_hp']} HP)" if wb else "⚪️ Сейчас спит"
    text = (
        f"🌐 <b>МУЛЬТИПЛЕЕР ХАБ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Взаимодействуй с другими игроками в реальном времени:\n\n"
        f"🌍 <b>Мировой Босс:</b> {wb_status}\n"
        f"⚔️ <b>PvP Арена:</b> Бросай открытые вызовы или дуэли конкретным игрокам по @username со ставками.\n"
        f"🏪 <b>P2P Рынок:</b> Покупай редких заражённых титанов и продавай свои карты другим игрокам."
    )
    await message.answer(text, reply_markup=mp_hub_kb())


@router.callback_query(F.data == "mp:hub")
async def cb_mp_hub(callback: CallbackQuery):
    wb = await db.get_active_world_boss()
    wb_status = f"🟢 АКТИВЕН ({wb['name']} — {wb['current_hp']} HP)" if wb else "⚪️ Сейчас спит"
    text = (
        f"🌐 <b>МУЛЬТИПЛЕЕР ХАБ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🌍 <b>Мировой Босс:</b> {wb_status}\n"
        f"⚔️ <b>PvP Арена</b> и 🏪 <b>P2P Рынок</b> ждут тебя!"
    )
    await render_view(callback, text, mp_hub_kb())
    await callback.answer()


# --- МИРОВОЙ БОСС ---

async def render_world_boss(target: Message | CallbackQuery):
    wb = await db.get_active_world_boss()
    if not wb:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 В Мультиплеер", callback_data="mp:hub")]]
        )
        await render_view(
            target,
            "🌍 <b>МИРОВОЙ БОСС</b>\n\nСейчас ни один Мировой Босс не активен.\n"
            "Администрация запускает его во время ивентов!",
            kb,
        )
        return

    top = await db.get_world_boss_top(wb["id"], limit=5)
    top_lines = [
        f"{i}. {format_user_link(t)} — <b>{t['damage']}</b> урона" for i, t in enumerate(top, 1)
    ]
    text = (
        f"🌍 <b>МИРОВОЙ БОСС: {esc(wb['name'])}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{make_hp_bar(wb['current_hp'], wb['max_hp'], 12)}\n"
        f"❤️ HP: <b>{wb['current_hp']} / {wb['max_hp']}</b>\n\n"
        f"🏆 <b>Топ-5 по урону:</b>\n"
        + ("\n".join(top_lines) if top_lines else "<i>Пока никто не нанёс удар! Будь первым!</i>")
        + f"\n\n🎁 Когда босс падёт, <b>Топ-3</b> получат крупные монеты и шанс заражения!"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚔️ Ударить колодой!", callback_data="mp:wb:hit")],
            [
                InlineKeyboardButton(text="🔄 Обновить", callback_data="mp:wb"),
                InlineKeyboardButton(text="🔙 Назад", callback_data="mp:hub"),
            ],
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
    if prev and (now - prev["last_hit"]) < WORLD_BOSS_COOLDOWN:
        rem = WORLD_BOSS_COOLDOWN - (now - prev["last_hit"])
        await callback.answer(f"⏳ Перезарядка удара: {rem} сек.", show_alert=True)
        return

    deck = await db.get_inventory(uid, only_deck=True)
    if not deck:
        await callback.answer("Поставьте карты в колоду!", show_alert=True)
        return

    s = calc_deck_summary(deck)
    dmg = int(s["atk"] * random.uniform(1.1, 1.5))
    rem_hp = await db.hit_world_boss(wb["id"], uid, dmg)

    if rem_hp <= 0:
        # Босс повержен! Раздаём награды Топ-5 и заражение Топ-3
        top = await db.get_world_boss_top(wb["id"], limit=10)
        reward_card = (
            await db.get_card(wb["infected_card_id"]) if wb.get("infected_card_id") else None
        ) or await db.get_card(wb["card_id"])

        for idx, participant in enumerate(top, 1):
            p_uid = participant["user_id"]
            coins = max(150, 900 - (idx - 1) * 150)
            await db.add_coins(p_uid, coins)
            extra = ""
            if idx <= 3 and random.randint(1, 100) <= min(75, wb["infect_chance"] + 30):
                mut = random.choice(["toxic", "armored", "astro", "alpha"])
                await db.give_card(p_uid, reward_card["id"], mutation=mut)
                extra = f"\n🦠 <b>ВЫ ЗАРАЗИЛИ МИРОВОГО БОССА!</b> Получена карта: <b>{esc(reward_card['name'])}</b> ({MUTATIONS[mut][0]})!"
            try:
                await bot.send_message(
                    p_uid,
                    f"🌍🏆 <b>МИРОВОЙ БОСС {esc(wb['name'])} ПОВЕРЖЕН!</b>\n"
                    f"Вы заняли <b>#{idx} место</b> (урон: {participant['damage']}).\n"
                    f"💰 Награда: <b>+{coins} монет</b>{extra}",
                )
            except Exception:
                pass

        await callback.answer(f"💥 ФИНАЛЬНЫЙ УДАР -{dmg}! Босс повержен!", show_alert=True)
    else:
        await callback.answer(f"⚔️ Вы нанесли {dmg} урона! Осталось {rem_hp} HP.", show_alert=True)

    await render_world_boss(callback)


# --- PVP АРЕНА ---

async def render_pvp_lobby(target: Message | CallbackQuery, user_id: int):
    challenges = await db.list_open_pvp(user_id)
    text = (
        f"⚔️ <b>PvP АРЕНА (ДУЭЛИ ИГРОКОВ)</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Прими открытый вызов или создай свой (открытый для всех или личный по @username).\n"
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
        bet_str = f"💰{ch['bet']}" if ch["bet"] > 0 else "Без ставки"
        tag = "🎯Личный " if ch["target_id"] else ""
        if is_mine:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"❌ Отменить свой вызов ({tag}{bet_str})",
                        callback_data=f"pvp:cancel:{ch['id']}",
                    )
                ]
            )
        else:
            cname = ch["full_name"] or "Игрок"
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"⚔️ {tag}{cname} ({ch['pvp_wins']}W) | {bet_str}",
                        callback_data=f"pvp:accept:{ch['id']}",
                    )
                ]
            )
    rows.append(
        [
            InlineKeyboardButton(text="🔄 Обновить", callback_data="mp:pvp"),
            InlineKeyboardButton(text="🔙 Назад", callback_data="mp:hub"),
        ]
    )
    await render_view(target, text, InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "mp:pvp")
async def cb_pvp_lobby(callback: CallbackQuery):
    await render_pvp_lobby(callback, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data.startswith("pvp:new:"))
async def cb_pvp_new(callback: CallbackQuery, state: FSMContext):
    mode = callback.data.split(":")[2]
    deck = await db.get_inventory(callback.from_user.id, only_deck=True)
    if not deck:
        await callback.answer("Сначала соберите колоду!", show_alert=True)
        return
    await state.update_data(pvp_mode=mode, pvp_target_id=0)
    if mode == "direct":
        await state.set_state(PlayerFSM.pvp_target)
        await callback.message.answer("🎯 Введите <b>@username</b> или <b>ID</b> соперника для дуэли:")
    else:
        await state.set_state(PlayerFSM.pvp_bet)
        await callback.message.answer("💰 Введите ставку в монетах (или <b>0</b> для дружеского боя):")
    await callback.answer()


@router.message(PlayerFSM.pvp_target)
async def fsm_pvp_target(message: Message, state: FSMContext):
    target = await db.find_user(message.text or "")
    if not target or target["user_id"] == message.from_user.id:
        await state.clear()
        await message.answer("❌ Соперник не найден (или вы указали себя).")
        return
    await state.update_data(pvp_target_id=target["user_id"])
    await state.set_state(PlayerFSM.pvp_bet)
    await message.answer(
        f"🎯 Соперник: {format_user_link(target)}.\n💰 Введите ставку в монетах (или <b>0</b>):"
    )


@router.message(PlayerFSM.pvp_bet)
async def fsm_pvp_bet(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    try:
        bet = int((message.text or "").strip())
        if bet < 0 or bet > 50000:
            raise ValueError
    except ValueError:
        await message.answer("❌ Укажите число от 0 до 50000.")
        return

    user = await db.get_user(message.from_user.id)
    if user["coins"] < bet:
        await message.answer(f"❌ У вас недостаточно монет (есть {user['coins']} 💰).")
        return

    target_id = data.get("pvp_target_id", 0)
    ch_id = await db.create_pvp_challenge(user["user_id"], target_id, bet)

    if target_id:
        try:
            await bot.send_message(
                target_id,
                f"⚔️ <b>ВАМ БРОСИЛИ ВЫЗОВ НА PvP-ДУЭЛЬ!</b>\n"
                f"Соперник: {format_user_link(user)}\n"
                f"💰 Ставка: <b>{bet} монет</b>",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="⚔️ Принять бой!", callback_data=f"pvp:accept:{ch_id}")]
                    ]
                ),
            )
        except Exception:
            pass
        await message.answer(f"✅ Личный вызов отправлен! Ставка: <b>{bet} 💰</b>.")
    else:
        await message.answer(f"✅ Открытый PvP-вызов создан! Ставка: <b>{bet} 💰</b>. Ждём соперника!")


@router.callback_query(F.data.startswith("pvp:cancel:"))
async def cb_pvp_cancel(callback: CallbackQuery):
    ch_id = int(callback.data.split(":")[2])
    ch = await db.get_pvp_challenge(ch_id)
    if ch and ch["creator_id"] == callback.from_user.id and ch["status"] == "open":
        await db.close_pvp_challenge(ch_id, "cancelled")
        await callback.answer("❌ Вызов отменён.")
    await render_pvp_lobby(callback, callback.from_user.id)


@router.callback_query(F.data.startswith("pvp:accept:"))
async def cb_pvp_accept(callback: CallbackQuery, bot: Bot):
    ch_id = int(callback.data.split(":")[2])
    ch = await db.get_pvp_challenge(ch_id)
    uid = callback.from_user.id

    if not ch or ch["status"] != "open":
        await callback.answer("Вызов уже неактуален.", show_alert=True)
        return
    if ch["creator_id"] == uid:
        await callback.answer("Нельзя принять свой вызов!", show_alert=True)
        return
    if ch["target_id"] and ch["target_id"] != uid:
        await callback.answer("Этот вызов адресован другому игроку.", show_alert=True)
        return

    u1 = await db.get_user(ch["creator_id"])
    u2 = await db.get_user(uid)
    deck1 = await db.get_inventory(u1["user_id"], only_deck=True)
    deck2 = await db.get_inventory(u2["user_id"], only_deck=True)

    if not deck1 or not deck2:
        await callback.answer("У одного из игроков пустая колода!", show_alert=True)
        return
    if u1["coins"] < ch["bet"] or u2["coins"] < ch["bet"]:
        await callback.answer("У одного из игроков не хватает монет на ставку!", show_alert=True)
        return

    await db.close_pvp_challenge(ch_id, "done")
    winner_num, battle_log = simulate_pvp_battle(deck1, deck2, u1["full_name"], u2["full_name"])

    win_u = u1 if winner_num == 1 else u2
    lose_u = u2 if winner_num == 1 else u1

    reward_bonus = 40  # Базовая награда арены за победу
    await db.update_user(win_u["user_id"], pvp_wins=win_u["pvp_wins"] + 1)
    await db.update_user(lose_u["user_id"], pvp_losses=lose_u["pvp_losses"] + 1)
    await db.add_coins(win_u["user_id"], ch["bet"] + reward_bonus)
    if ch["bet"] > 0:
        await db.add_coins(lose_u["user_id"], -ch["bet"])

    battle_log += f"\n💰 Приз победителю: <b>+{ch['bet'] + reward_bonus} монет</b>"

    # Отправляем отчёт обоим участникам
    await render_view(callback, battle_log)
    try:
        await bot.send_message(u1["user_id"], battle_log)
    except Exception:
        pass
    await callback.answer("⚔️ Бой завершён!")


# --- P2P РЫНОК ИГРОКОВ ---

async def render_market_page(target: Message | CallbackQuery, user_id: int, page: int = 0):
    lots = await db.list_market()
    per_page = 6
    total_pages = max(1, (len(lots) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    chunk = lots[page * per_page : (page + 1) * per_page]

    text = (
        f"🏪 <b>P2P РЫНОК ИГРОКОВ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Покупай карты напрямую у других игроков. Чтобы продать свою карту — открой её в «🃏 Колода и Карты».\n"
        f"Всего лотов: <b>{len(lots)}</b> | Страница {page + 1}/{total_pages}"
    )

    rows = []
    for lot in chunk:
        r_ico = RARITIES.get(lot["rarity"], ("", "⚪️", 1))[1]
        mut = "🧬" if lot["mutation"] != "none" else ""
        mine = " (Мой)" if lot["seller_id"] == user_id else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{r_ico}{mut} {lot['name']} Ур.{lot['level']} — {lot['price']}💰{mine}",
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
    page = int(callback.data.split(":")[2])
    await render_market_page(callback, callback.from_user.id, page)
    await callback.answer()


@router.callback_query(F.data.startswith("mkt:view:"))
async def cb_market_view(callback: CallbackQuery):
    _, _, lot_id_s, page_s = callback.data.split(":")
    lot_id, page = int(lot_id_s), int(page_s)
    lots = await db.list_market()
    lot = next((x for x in lots if x["market_id"] == lot_id), None)
    if not lot:
        await callback.answer("Лот больше не существует.", show_alert=True)
        await render_market_page(callback, callback.from_user.id, page)
        return

    hp, atk = calc_card_stats(lot)
    mut_name = MUTATIONS.get(lot["mutation"], ("Без штамма", 1.0, 1.0))[0]
    seller = lot["seller_name"] or "Игрок"
    text = (
        f"🏷 <b>ЛОТ #{lot['market_id']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🃏 <b>{esc(lot['name'])}</b> (Ур. {lot['level']})\n"
        f"🧬 Штамм: <b>{mut_name}</b>\n"
        f"❤️ HP: <b>{hp}</b> | ⚔️ Атака: <b>{atk}</b>\n"
        f"👤 Продавец: <b>{esc(seller)}</b>\n"
        f"💰 Цена: <b>{lot['price']} монет</b>"
    )
    if lot["seller_id"] == callback.from_user.id:
        act_btn = InlineKeyboardButton(text="❌ Снять с продажи", callback_data=f"mkt:cancel:{lot_id}:{page}")
    else:
        act_btn = InlineKeyboardButton(text=f"✅ Купить за {lot['price']} 💰", callback_data=f"mkt:buy:{lot_id}:{page}")

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [act_btn],
            [InlineKeyboardButton(text="🔙 Назад к рынку", callback_data=f"mp:market:{page}")],
        ]
    )
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
                f"💰 <b>ВАШУ КАРТУ КУПИЛИ НА РЫНКЕ!</b>\n"
                f"Карта: <b>{esc(lot['name'])}</b>\n"
                f"Зачислено: <b>+{lot['price']} монет</b>!",
            )
        except Exception:
            pass
    await render_market_page(callback, callback.from_user.id, int(page_s))


@router.callback_query(F.data.startswith("mkt:cancel:"))
async def cb_market_cancel(callback: CallbackQuery):
    _, _, lot_id_s, page_s = callback.data.split(":")
    ok = await db.cancel_market_lot(int(lot_id_s), callback.from_user.id)
    await callback.answer("Лот снят с продажи!" if ok else "Ошибка.", show_alert=True)
    await render_market_page(callback, callback.from_user.id, int(page_s))


# -------------------- ЛАБОРАТОРИЯ ПАРАЗИТОВ И МАГАЗИН --------------------

def lab_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🦠 Обыч. паразит (150💰)", callback_data="shop:buy:common"),
                InlineKeyboardButton(text="☣️ Улучш. паразит (450💰)", callback_data="shop:buy:upgraded"),
            ],
            [InlineKeyboardButton(text="🌌 Астро-паразит (1200💰)", callback_data="shop:buy:astro")],
            [
                InlineKeyboardButton(text="⚗️ 3🦠 ➔ 1☣️ Крафт", callback_data="shop:craft:upgraded"),
                InlineKeyboardButton(text="⚗️ 3☣️ ➔ 1🌌 Крафт", callback_data="shop:craft:astro"),
            ],
            [
                InlineKeyboardButton(text="📦 Обычный Кейс (250💰)", callback_data="shop:crate:std"),
                InlineKeyboardButton(text="💎 Элитный Кейс (750💰)", callback_data="shop:crate:elite"),
            ],
        ]
    )


async def render_lab(target: Message | CallbackQuery, user_id: int):
    user = await db.get_user(user_id)
    text = (
        f"🧪 <b>ЛАБОРАТОРИЯ СКИБИДИ-УЧЁНОГО И МАГАЗИН</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Твои монеты: <b>{user['coins']}</b>\n"
        f"🦠 Паразиты: Обыч. <b>{user['p_common']}</b> | Улучш. <b>{user['p_upgraded']}</b> | Астро <b>{user['p_astro']}</b>\n\n"
        f"• <b>Паразиты</b> повышают шанс заражения боссов и шанс редкого штамма мутации.\n"
        f"• <b>Крафт</b> позволяет скрестить 3 слабых паразита в 1 более мощного.\n"
        f"• <b>Кейсы</b> выбивают новых юнитов в твою коллекцию!"
    )
    await render_view(target, text, lab_kb())


@router.message(F.text == "🧪 Лаборатория и Магазин")
async def menu_lab(message: Message, state: FSMContext):
    await state.clear()
    await render_lab(message, message.from_user.id)


@router.callback_query(F.data.startswith("shop:buy:"))
async def cb_shop_buy(callback: CallbackQuery):
    p_key = callback.data.split(":")[2]
    p_name, _, _, price, _ = PARASITES[p_key]
    user = await db.get_user(callback.from_user.id)
    if user["coins"] < price:
        await callback.answer(f"Не хватает монет! Нужно {price} 💰.", show_alert=True)
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
    src_col = PARASITES[src_p][1]
    if user[src_col] < 3:
        await callback.answer(f"Нужно минимум 3 шт. «{PARASITES[src_p][0]}»!", show_alert=True)
        return
    await db.add_parasite(user["user_id"], src_p, -3)
    await db.add_parasite(user["user_id"], target_p, 1)
    await callback.answer(f"⚗️ Успешно скрафчен: {PARASITES[target_p][0]}!", show_alert=True)
    await render_lab(callback, user["user_id"])


@router.callback_query(F.data.startswith("shop:crate:"))
async def cb_shop_crate(callback: CallbackQuery):
    tier = callback.data.split(":")[2]
    price = 250 if tier == "std" else 750
    user = await db.get_user(callback.from_user.id)
    if user["coins"] < price:
        await callback.answer(f"Нужно {price} 💰!", show_alert=True)
        return

    all_cards = [c for c in await db.list_cards() if not c["is_boss"]]
    if not all_cards:
        await callback.answer("В базе нет обычных карточек для кейса.", show_alert=True)
        return

    weights = []
    for c in all_cards:
        w = RARITIES.get(c["rarity"], ("", "", 10))[2]
        if tier == "elite":
            # В элитном кейсе редкие карты падают гораздо чаще
            w = w if c["rarity"] in ("common", "rare") else w * 5
        weights.append(w)

    dropped = random.choices(all_cards, weights=weights, k=1)[0]
    await db.add_coins(user["user_id"], -price)
    await db.give_card(user["user_id"], dropped["id"])

    r_name, r_ico, _ = RARITIES.get(dropped["rarity"], ("Обычная", "⚪️", 1))
    await callback.answer(f"🎉 Выпало: {dropped['name']}!", show_alert=True)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад в Лабораторию", callback_data="shop:back")]]
    )
    await render_view(
        callback,
        f"📦 <b>ОТКРЫТИЕ КЕЙСА!</b>\n\n"
        f"Тебе выпала карта:\n{r_ico} <b>{esc(dropped['name'])}</b> ({r_name})\n"
        f"❤️ HP: {dropped['hp']} | ⚔️ Атака: {dropped['atk']}",
        kb,
        photo=dropped.get("image_id") or None,
    )


@router.callback_query(F.data == "shop:back")
async def cb_shop_back(callback: CallbackQuery):
    await render_lab(callback, callback.from_user.id)
    await callback.answer()


# -------------------- РЕЙТИНГИ (ТОП ИГРОКОВ) --------------------

async def render_top(target: Message | CallbackQuery, mode: str = "pvp_wins"):
    titles = {
        "pvp_wins": ("⚔️ Топ по PvP победам", "побед"),
        "infections_success": ("🦠 Топ по Заражениям", "заражений"),
        "coins": ("💰 Топ Богачей", "монет"),
        "bosses_killed": ("👹 Топ Охотников на Боссов", "боссов"),
    }
    title, unit = titles.get(mode, titles["pvp_wins"])
    rows = await db.get_leaderboard(mode, limit=10)

    medals = ["🥇", "🥈", "🥉"]
    lines = [f"🏆 <b>{title}</b>\n━━━━━━━━━━━━━━━━━━"]
    for idx, r in enumerate(rows, 1):
        prefix = medals[idx - 1] if idx <= 3 else f"<b>{idx}.</b>"
        lines.append(f"{prefix} {format_user_link(r)} — <b>{r['val']}</b> {unit}")

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⚔️ PvP", callback_data="top:pvp_wins"),
                InlineKeyboardButton(text="🦠 Заражения", callback_data="top:infections_success"),
            ],
            [
                InlineKeyboardButton(text="💰 Монеты", callback_data="top:coins"),
                InlineKeyboardButton(text="👹 Боссы", callback_data="top:bosses_killed"),
            ],
        ]
    )
    await render_view(target, "\n".join(lines), kb)


@router.message(F.text == "🏆 Рейтинг")
async def menu_top(message: Message, state: FSMContext):
    await state.clear()
    await render_top(message, "pvp_wins")


@router.callback_query(F.data.startswith("top:"))
async def cb_top(callback: CallbackQuery):
    await render_top(callback, callback.data.split(":")[1])
    await callback.answer()


# ==============================================================================
# 8. РАСШИРЕННАЯ АДМИН-ПАНЕЛЬ (ПРАВА, КОНСТРУКТОР И РЕДАКТОР КАРТ, БОССЫ, ЛОГИ)
# ==============================================================================

async def render_admin_home(target: Message | CallbackQuery, user_id: int):
    perms = await db.get_admin_perms(user_id)
    stats = await db.get_global_stats()
    maint = await db.get_setting("maintenance", "0")
    role_str = "👑 Владелец (Все права)" if user_id == OWNER_ID else "🛡 Администратор"

    text = (
        f"⚙️ <b>РАСШИРЕННАЯ АДМИН-ПАНЕЛЬ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Статус: <b>{role_str}</b>\n"
        f"👥 Игроков: <b>{stats['users']}</b> | 🃏 Карт в БД: <b>{stats['cards']}</b>\n"
        f"🎒 В инвентарях: <b>{stats['inventory']}</b> | 🏪 На рынке: <b>{stats['market']}</b>\n"
        f"🛠 Техработы: <b>{'ВКЛ 🔴' if maint == '1' else 'ВЫКЛ 🟢'}</b>"
    )

    rows = []
    if perms["manage_cards"]:
        rows.append(
            [
                InlineKeyboardButton(text="➕ Создать карту", callback_data="adm:card:new"),
                InlineKeyboardButton(text="✏️ Редактор карт", callback_data="adm:card:list:0"),
            ]
        )
    if perms["manage_bosses"]:
        rows.append([InlineKeyboardButton(text="🌍 Управление Мировым Боссом", callback_data="adm:wb")])
    if perms["manage_users"] or perms["manage_economy"]:
        rows.append([InlineKeyboardButton(text="👥 Игроки и Экономика", callback_data="adm:users")])
    if perms["manage_admins"]:
        rows.append([InlineKeyboardButton(text="👮 Управление Админами и Правами", callback_data="adm:admins")])
    if perms["broadcast"]:
        rows.append([InlineKeyboardButton(text="📢 Рассылка всем игрокам", callback_data="adm:broadcast")])

    # Служебные кнопки (техработы, бэкап, логи)
    util_row = [InlineKeyboardButton(text="📜 Логи", callback_data="adm:logs")]
    if user_id == OWNER_ID or perms["manage_admins"]:
        util_row.append(
            InlineKeyboardButton(
                text=f"🛠 Техработы: {'ВКЛ' if maint == '1' else 'ВЫКЛ'}",
                callback_data="adm:maint",
            )
        )
        util_row.append(InlineKeyboardButton(text="💾 Бэкап БД", callback_data="adm:backup"))
    rows.append(util_row)

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
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await state.clear()
    await render_admin_home(callback, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "adm:maint")
async def cb_adm_maint(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID and not await db.has_perm(callback.from_user.id, "manage_admins"):
        await callback.answer("Нет прав!", show_alert=True)
        return
    cur = await db.get_setting("maintenance", "0")
    nxt = "0" if cur == "1" else "1"
    await db.set_setting("maintenance", nxt)
    await db.log_admin(callback.from_user.id, f"Режим техработ -> {'ВКЛ' if nxt == '1' else 'ВЫКЛ'}")
    await callback.answer("Режим техработ переключён!", show_alert=True)
    await render_admin_home(callback, callback.from_user.id)


@router.callback_query(F.data == "adm:backup")
async def cb_adm_backup(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID and not await db.has_perm(callback.from_user.id, "manage_admins"):
        await callback.answer("Нет прав!", show_alert=True)
        return
    await callback.message.answer_document(
        FSInputFile(DB_PATH),
        caption=f"💾 Резервная копия БД от {datetime.now().strftime('%d.%m.%Y %H:%M')}",
    )
    await callback.answer("Бэкап отправлен!")


@router.callback_query(F.data == "adm:logs")
async def cb_adm_logs(callback: CallbackQuery):
    if not await db.is_admin(callback.from_user.id):
        return
    logs = await db.get_admin_logs(15)
    lines = ["📜 <b>ПОСЛЕДНИЕ ДЕЙСТВИЯ АДМИНОВ</b>\n━━━━━━━━━━━━━━━━━━"]
    for lg in logs:
        ts = datetime.fromtimestamp(lg["created_at"]).strftime("%d.%m %H:%M")
        who = lg["username"] or str(lg["admin_id"])
        lines.append(f"<code>[{ts}]</code> <b>@{esc(who)}</b>: {esc(lg['action'])}")
    if len(lines) == 1:
        lines.append("<i>Логов пока нет.</i>")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")]])
    await render_view(callback, "\n".join(lines), kb)
    await callback.answer()


# --- КОНСТРУКТОР КАРТОЧЕК (ПОШАГОВЫЙ FSM) ---

@router.callback_query(F.data == "adm:card:new")
async def cb_card_new(callback: CallbackQuery, state: FSMContext):
    if not await db.has_perm(callback.from_user.id, "manage_cards"):
        await callback.answer("Нет права manage_cards!", show_alert=True)
        return
    await state.clear()
    await state.set_state(CardCreateFSM.name)
    await callback.message.answer(
        "🛠 <b>КОНСТРУКТОР КАРТЫ — Шаг 1/8</b>\nВведите <b>название</b> новой карты (например, <i>G-Man 4.0</i>):"
    )
    await callback.answer()


@router.message(CardCreateFSM.name)
async def fsm_cc_name(message: Message, state: FSMContext):
    await state.update_data(name=(message.text or "Новая карта").strip())
    await state.set_state(CardCreateFSM.faction)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=v, callback_data=f"cc:fac:{k}")] for k, v in FACTIONS.items()
        ]
    )
    await message.answer("🛠 <b>Шаг 2/8:</b> Выберите <b>фракцию</b> карты:", reply_markup=kb)


@router.callback_query(CardCreateFSM.faction, F.data.startswith("cc:fac:"))
async def fsm_cc_faction(callback: CallbackQuery, state: FSMContext):
    await state.update_data(faction=callback.data.split(":")[2])
    await state.set_state(CardCreateFSM.rarity)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{ico} {name}", callback_data=f"cc:rar:{k}")]
            for k, (name, ico, _) in RARITIES.items()
        ]
    )
    await render_view(callback, "🛠 <b>Шаг 3/8:</b> Выберите <b>редкость</b>:", kb)
    await callback.answer()


@router.callback_query(CardCreateFSM.rarity, F.data.startswith("cc:rar:"))
async def fsm_cc_rarity(callback: CallbackQuery, state: FSMContext):
    await state.update_data(rarity=callback.data.split(":")[2])
    await state.set_state(CardCreateFSM.hp)
    await render_view(callback, "🛠 <b>Шаг 4/8:</b> Введите базовое <b>HP</b> карты (целое число, например <code>250</code>):")
    await callback.answer()


@router.message(CardCreateFSM.hp)
async def fsm_cc_hp(message: Message, state: FSMContext):
    if not (message.text or "").strip().isdigit():
        await message.answer("❌ Введите положительное число!")
        return
    await state.update_data(hp=int(message.text.strip()))
    await state.set_state(CardCreateFSM.atk)
    await message.answer("🛠 <b>Шаг 5/8:</b> Введите базовую <b>Атаку (ATK)</b> карты (например <code>65</code>):")


@router.message(CardCreateFSM.atk)
async def fsm_cc_atk(message: Message, state: FSMContext):
    if not (message.text or "").strip().isdigit():
        await message.answer("❌ Введите положительное число!")
        return
    await state.update_data(atk=int(message.text.strip()))
    await state.set_state(CardCreateFSM.description)
    await message.answer("🛠 <b>Шаг 6/8:</b> Введите <b>описание/способность</b> карты (или напишите <code>-</code> чтобы пропустить):")


@router.message(CardCreateFSM.description)
async def fsm_cc_desc(message: Message, state: FSMContext):
    txt = (message.text or "").strip()
    await state.update_data(description="" if txt == "-" else txt)
    await state.set_state(CardCreateFSM.image)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⏭ Пропустить без фото", callback_data="cc:img:skip")]]
    )
    await message.answer("🛠 <b>Шаг 7/8:</b> Отправьте <b>фотографию</b> для карточки (или нажмите «Пропустить»):", reply_markup=kb)


@router.callback_query(CardCreateFSM.image, F.data == "cc:img:skip")
async def fsm_cc_img_skip(callback: CallbackQuery, state: FSMContext):
    await state.update_data(image_id="")
    await ask_is_boss(callback, state)
    await callback.answer()


@router.message(CardCreateFSM.image, F.photo)
async def fsm_cc_img_photo(message: Message, state: FSMContext):
    await state.update_data(image_id=message.photo[-1].file_id)
    await ask_is_boss(message, state)


async def ask_is_boss(target: Message | CallbackQuery, state: FSMContext):
    await state.set_state(CardCreateFSM.is_boss)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👹 Да, это Босс Рейда", callback_data="cc:boss:1"),
                InlineKeyboardButton(text="🃏 Нет, обычный юнит", callback_data="cc:boss:0"),
            ]
        ]
    )
    await render_view(target, "🛠 <b>Шаг 8/8:</b> Будет ли эта карта <b>Боссом для рейдов</b> (с заражением)?", kb)


@router.callback_query(CardCreateFSM.is_boss, F.data.startswith("cc:boss:"))
async def fsm_cc_boss(callback: CallbackQuery, state: FSMContext):
    is_boss = int(callback.data.split(":")[2])
    await state.update_data(is_boss=is_boss)
    if is_boss:
        await state.set_state(CardCreateFSM.boss_hp)
        await render_view(callback, "👹 Введите <b>HP Босса в рейде</b> (например <code>800</code>):")
    else:
        await state.update_data(boss_hp=0, boss_atk=0, infect_chance=0, infected_card_id=0)
        await show_card_preview(callback, state)
    await callback.answer()


@router.message(CardCreateFSM.boss_hp)
async def fsm_cc_boss_hp(message: Message, state: FSMContext):
    if not (message.text or "").strip().isdigit():
        await message.answer("❌ Введите число!")
        return
    await state.update_data(boss_hp=int(message.text.strip()))
    await state.set_state(CardCreateFSM.boss_atk)
    await message.answer("👹 Введите <b>Атаку Босса в рейде</b> (например <code>65</code>):")


@router.message(CardCreateFSM.boss_atk)
async def fsm_cc_boss_atk(message: Message, state: FSMContext):
    if not (message.text or "").strip().isdigit():
        await message.answer("❌ Введите число!")
        return
    await state.update_data(boss_atk=int(message.text.strip()))
    await state.set_state(CardCreateFSM.infect_chance)
    await message.answer("🦠 Введите <b>базовый шанс заражения %</b> (от 1 до 100, например <code>15</code>):")


@router.message(CardCreateFSM.infect_chance)
async def fsm_cc_inf_chance(message: Message, state: FSMContext):
    if not (message.text or "").strip().isdigit():
        await message.answer("❌ Введите число от 1 до 100!")
        return
    await state.update_data(infect_chance=max(1, min(100, int(message.text.strip()))))
    await state.set_state(CardCreateFSM.infected_card_id)
    await message.answer(
        "🔗 Введите <b>ID карты</b>, в которую превратится босс при успешном заражении\n"
        "(или <code>0</code> — тогда при заражении выдастся сама карта босса с мутацией):"
    )


@router.message(CardCreateFSM.infected_card_id)
async def fsm_cc_inf_id(message: Message, state: FSMContext):
    if not (message.text or "").strip().isdigit():
        await message.answer("❌ Введите числовой ID (или 0)!")
        return
    await state.update_data(infected_card_id=int(message.text.strip()))
    await show_card_preview(message, state)


async def show_card_preview(target: Message | CallbackQuery, state: FSMContext):
    await state.set_state(CardCreateFSM.confirm)
    d = await state.get_data()
    preview = dict(d, id="NEW")
    text = "👁 <b>ПРЕВЬЮ НОВОЙ КАРТЫ:</b>\n━━━━━━━━━━━━━━━━━━\n" + format_card_text(preview)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Сохранить в БД", callback_data="cc:save"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="adm:home"),
            ]
        ]
    )
    await render_view(target, text, kb, photo=d.get("image_id") or None)


@router.callback_query(CardCreateFSM.confirm, F.data == "cc:save")
async def fsm_cc_save(callback: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    new_id = await db.create_card(d)
    await db.log_admin(callback.from_user.id, f"Создал карту #{new_id} ({d['name']})")
    await state.clear()
    await callback.answer(f"✅ Карта #{new_id} сохранена!", show_alert=True)
    await render_admin_home(callback, callback.from_user.id)


# --- ТОЧЕЧНЫЙ РЕДАКТОР И УДАЛЕНИЕ КАРТ ---

async def render_admin_cards_list(target: Message | CallbackQuery, page: int = 0):
    cards = await db.list_cards()
    per_page = 7
    total_pages = max(1, (len(cards) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    chunk = cards[page * per_page : (page + 1) * per_page]

    text = f"✏️ <b>РЕДАКТОР КАРТОЧЕК</b> (Всего: {len(cards)})\nВыберите карту для точечного изменения или удаления:"
    rows = []
    for c in chunk:
        r_ico = RARITIES.get(c["rarity"], ("", "⚪️", 1))[1]
        b_tag = "👹 " if c["is_boss"] else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"#{c['id']} {b_tag}{r_ico} {c['name']}",
                    callback_data=f"adm:ce:view:{c['id']}:{page}",
                )
            ]
        )

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"adm:card:list:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"adm:card:list:{page + 1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")])
    await render_view(target, text, InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("adm:card:list:"))
async def cb_adm_card_list(callback: CallbackQuery):
    if not await db.has_perm(callback.from_user.id, "manage_cards"):
        await callback.answer("Нет прав!", show_alert=True)
        return
    await render_admin_cards_list(callback, int(callback.data.split(":")[3]))
    await callback.answer()


async def render_card_editor(target: Message | CallbackQuery, card_id: int, page: int = 0):
    card = await db.get_card(card_id)
    if not card:
        await render_admin_cards_list(target, page)
        return

    text = "✏️ <b>РЕДАКТИРОВАНИЕ КАРТЫ</b>\n━━━━━━━━━━━━━━━━━━\n" + format_card_text(card)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✏️ Название", callback_data=f"ce:f:name:{card_id}:{page}"),
                InlineKeyboardButton(text="📝 Описание", callback_data=f"ce:f:description:{card_id}:{page}"),
            ],
            [
                InlineKeyboardButton(text="❤️ HP", callback_data=f"ce:f:hp:{card_id}:{page}"),
                InlineKeyboardButton(text="⚔️ Атака", callback_data=f"ce:f:atk:{card_id}:{page}"),
            ],
            [
                InlineKeyboardButton(text="🏷 Фракция", callback_data=f"ce:pick:faction:{card_id}:{page}"),
                InlineKeyboardButton(text="🌟 Редкость", callback_data=f"ce:pick:rarity:{card_id}:{page}"),
            ],
            [
                InlineKeyboardButton(text="🖼 Изменить фото", callback_data=f"ce:f:image_id:{card_id}:{page}"),
                InlineKeyboardButton(
                    text=f"👹 Босс: {'ДА' if card['is_boss'] else 'НЕТ'}",
                    callback_data=f"ce:boss_t:{card_id}:{page}",
                ),
            ],
            [
                InlineKeyboardButton(text="👹 HP Босса", callback_data=f"ce:f:boss_hp:{card_id}:{page}"),
                InlineKeyboardButton(text="👹 ATK Босса", callback_data=f"ce:f:boss_atk:{card_id}:{page}"),
            ],
            [
                InlineKeyboardButton(text="🦠 Шанс зараж. %", callback_data=f"ce:f:infect_chance:{card_id}:{page}"),
                InlineKeyboardButton(text="🔗 ID зараж. карты", callback_data=f"ce:f:infected_card_id:{card_id}:{page}"),
            ],
            [InlineKeyboardButton(text="🗑 УДАЛИТЬ КАРТУ", callback_data=f"ce:delask:{card_id}:{page}")],
            [InlineKeyboardButton(text="🔙 К списку карт", callback_data=f"adm:card:list:{page}")],
        ]
    )
    await render_view(target, text, kb, photo=card.get("image_id") or None)


@router.callback_query(F.data.startswith("adm:ce:view:"))
async def cb_ce_view(callback: CallbackQuery):
    if not await db.has_perm(callback.from_user.id, "manage_cards"):
        return
    _, _, _, cid, pg = callback.data.split(":")
    await render_card_editor(callback, int(cid), int(pg))
    await callback.answer()


@router.callback_query(F.data.startswith("ce:boss_t:"))
async def cb_ce_boss_toggle(callback: CallbackQuery):
    if not await db.has_perm(callback.from_user.id, "manage_cards"):
        return
    _, _, cid_s, pg_s = callback.data.split(":")
    cid, pg = int(cid_s), int(pg_s)
    card = await db.get_card(cid)
    if card:
        nxt = 0 if card["is_boss"] else 1
        await db.update_card(cid, is_boss=nxt)
        await db.log_admin(callback.from_user.id, f"Карта #{cid}: is_boss -> {nxt}")
    await render_card_editor(callback, cid, pg)
    await callback.answer("Обновлено!")


@router.callback_query(F.data.startswith("ce:pick:"))
async def cb_ce_pick(callback: CallbackQuery):
    if not await db.has_perm(callback.from_user.id, "manage_cards"):
        return
    _, _, field, cid, pg = callback.data.split(":")
    rows = []
    if field == "faction":
        for k, v in FACTIONS.items():
            rows.append([InlineKeyboardButton(text=v, callback_data=f"ce:set:faction:{k}:{cid}:{pg}")])
    elif field == "rarity":
        for k, (n, ico, _) in RARITIES.items():
            rows.append([InlineKeyboardButton(text=f"{ico} {n}", callback_data=f"ce:set:rarity:{k}:{cid}:{pg}")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"adm:ce:view:{cid}:{pg}")])
    await render_view(callback, f"Выберите новое значение для поля <b>{field}</b>:", InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith("ce:set:"))
async def cb_ce_set_choice(callback: CallbackQuery):
    if not await db.has_perm(callback.from_user.id, "manage_cards"):
        return
    _, _, field, val, cid_s, pg_s = callback.data.split(":")
    cid, pg = int(cid_s), int(pg_s)
    await db.update_card(cid, **{field: val})
    await db.log_admin(callback.from_user.id, f"Карта #{cid}: {field} -> {val}")
    await callback.answer("✅ Сохранено!")
    await render_card_editor(callback, cid, pg)


@router.callback_query(F.data.startswith("ce:f:"))
async def cb_ce_field_prompt(callback: CallbackQuery, state: FSMContext):
    if not await db.has_perm(callback.from_user.id, "manage_cards"):
        return
    _, _, field, cid_s, pg_s = callback.data.split(":")
    await state.set_state(CardEditFSM.waiting_value)
    await state.update_data(edit_field=field, edit_cid=int(cid_s), edit_pg=int(pg_s))
    hint = "Отправьте новое фото (или <code>-</code> чтобы удалить фото):" if field == "image_id" else f"Введите новое значение для <b>{field}</b>:"
    await callback.message.answer(f"✏️ {hint}")
    await callback.answer()


@router.message(CardEditFSM.waiting_value)
async def fsm_ce_save_value(message: Message, state: FSMContext):
    d = await state.get_data()
    field, cid, pg = d["edit_field"], d["edit_cid"], d["edit_pg"]
    await state.clear()

    int_fields = {"hp", "atk", "boss_hp", "boss_atk", "infect_chance", "infected_card_id"}
    if field == "image_id":
        if message.photo:
            val: Any = message.photo[-1].file_id
        elif (message.text or "").strip() == "-":
            val = ""
        else:
            await message.answer("❌ Пришлите фото или знак <code>-</code>.")
            return
    elif field in int_fields:
        if not (message.text or "").strip().isdigit():
            await message.answer("❌ Требуется целое число!")
            return
        val = int(message.text.strip())
    else:
        val = (message.text or "").strip()

    await db.update_card(cid, **{field: val})
    await db.log_admin(message.from_user.id, f"Изменил карту #{cid}: {field}")
    await message.answer("✅ Параметр успешно обновлён!")
    await render_card_editor(message, cid, pg)


@router.callback_query(F.data.startswith("ce:delask:"))
async def cb_ce_del_ask(callback: CallbackQuery):
    if not await db.has_perm(callback.from_user.id, "manage_cards"):
        return
    _, _, cid, pg = callback.data.split(":")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🗑 ДА, УДАЛИТЬ НАВСЕГДА", callback_data=f"ce:delok:{cid}:{pg}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data=f"adm:ce:view:{cid}:{pg}"),
            ]
        ]
    )
    await render_view(callback, f"⚠️ <b>Точно удалить карту #{cid}?</b>\nОна также пропадёт из инвентарей игроков!", kb)
    await callback.answer()


@router.callback_query(F.data.startswith("ce:delok:"))
async def cb_ce_del_ok(callback: CallbackQuery):
    if not await db.has_perm(callback.from_user.id, "manage_cards"):
        return
    _, _, cid_s, pg_s = callback.data.split(":")
    await db.delete_card(int(cid_s))
    await db.log_admin(callback.from_user.id, f"Удалил карту #{cid_s}")
    await callback.answer("🗑 Карта удалена!", show_alert=True)
    await render_admin_cards_list(callback, int(pg_s))


# --- УПРАВЛЕНИЕ АДМИНАМИ И ГИБКИМИ ПРАВАМИ ---

async def render_admins_list(target: Message | CallbackQuery):
    admins = await db.list_admins()
    text = (
        f"👮 <b>УПРАВЛЕНИЕ АДМИНИСТРАТОРАМИ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👑 Владелец: <code>{OWNER_ID}</code> (неизменяемые права)\n"
        f"Назначено админов: <b>{len(admins)}</b>\n\n"
        f"Выберите админа, чтобы переключить его права:"
    )
    rows = [[InlineKeyboardButton(text="➕ Добавить админа", callback_data="adm:add_admin")]]
    for a in admins:
        label = f"@{a['username']}" if a["username"] else f"{a['full_name'] or 'ID'} ({a['user_id']})"
        rows.append([InlineKeyboardButton(text=f"🛡 {label}", callback_data=f"adm:perms:{a['user_id']}")])
    rows.append([InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")])
    await render_view(target, text, InlineKeyboardMarkup(inline_keyboard=rows))


async def render_admin_perms_editor(target: Message | CallbackQuery, target_id: int):
    perms = await db.get_admin_perms(target_id)
    u = await db.get_user(target_id)
    who = format_user_link(u) if u else f"<code>{target_id}</code>"
    text = f"🔐 <b>ПРАВА АДМИНА:</b> {who}\nНажимайте на кнопки, чтобы выдавать/забирать права:"

    rows = []
    for key, desc in ADMIN_PERMS.items():
        ico = "✅" if perms.get(key) else "❌"
        rows.append([InlineKeyboardButton(text=f"{ico} {desc}", callback_data=f"ap:t:{target_id}:{key}")])
    rows.append([InlineKeyboardButton(text="🗑 Снять с админки", callback_data=f"ap:rm:{target_id}")])
    rows.append([InlineKeyboardButton(text="🔙 К списку админов", callback_data="adm:admins")])
    await render_view(target, text, InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "adm:admins")
async def cb_adm_admins(callback: CallbackQuery):
    if not await db.has_perm(callback.from_user.id, "manage_admins"):
        await callback.answer("Нет прав manage_admins!", show_alert=True)
        return
    await render_admins_list(callback)
    await callback.answer()


@router.callback_query(F.data == "adm:add_admin")
async def cb_adm_add_prompt(callback: CallbackQuery, state: FSMContext):
    if not await db.has_perm(callback.from_user.id, "manage_admins"):
        return
    await state.set_state(AdminFSM.add_admin)
    await callback.message.answer("👮 Введите <b>Telegram ID</b> или <b>@username</b> игрока для назначения админом:")
    await callback.answer()


@router.message(AdminFSM.add_admin)
async def fsm_adm_add(message: Message, state: FSMContext):
    await state.clear()
    q = (message.text or "").strip()
    user = await db.find_user(q)
    target_id = user["user_id"] if user else (int(q) if q.isdigit() else 0)
    if not target_id or target_id == OWNER_ID:
        await message.answer("❌ Некорректный пользователь (или это Владелец).")
        return
    await db.add_admin(target_id, message.from_user.id)
    await db.log_admin(message.from_user.id, f"Назначил админом ID {target_id}")
    await message.answer(f"✅ Пользователь <code>{target_id}</code> добавлен в админы! Настройте права ниже:")
    await render_admin_perms_editor(message, target_id)


@router.callback_query(F.data.startswith("adm:perms:"))
async def cb_adm_perms(callback: CallbackQuery):
    if not await db.has_perm(callback.from_user.id, "manage_admins"):
        return
    await render_admin_perms_editor(callback, int(callback.data.split(":")[2]))
    await callback.answer()


@router.callback_query(F.data.startswith("ap:t:"))
async def cb_ap_toggle(callback: CallbackQuery):
    if not await db.has_perm(callback.from_user.id, "manage_admins"):
        return
    _, _, tid_s, perm = callback.data.split(":")
    tid = int(tid_s)
    await db.toggle_admin_perm(tid, perm)
    await db.log_admin(callback.from_user.id, f"Переключил право {perm} для админа {tid}")
    await render_admin_perms_editor(callback, tid)
    await callback.answer("Право обновлено!")


@router.callback_query(F.data.startswith("ap:rm:"))
async def cb_ap_remove(callback: CallbackQuery):
    if not await db.has_perm(callback.from_user.id, "manage_admins"):
        return
    tid = int(callback.data.split(":")[2])
    await db.remove_admin(tid)
    await db.log_admin(callback.from_user.id, f"Снял админа ID {tid}")
    await callback.answer("Админ удалён!", show_alert=True)
    await render_admins_list(callback)


# --- УПРАВЛЕНИЕ МИРОВЫМ БОССОМ ---

@router.callback_query(F.data == "adm:wb")
async def cb_adm_wb(callback: CallbackQuery):
    if not await db.has_perm(callback.from_user.id, "manage_bosses"):
        await callback.answer("Нет права manage_bosses!", show_alert=True)
        return
    wb = await db.get_active_world_boss()
    bosses = await db.list_cards(only_bosses=True)
    status = f"🟢 Активен: <b>{wb['name']}</b> ({wb['current_hp']}/{wb['max_hp']} HP)" if wb else "⚪️ Не запущен"
    text = f"🌍 <b>УПРАВЛЕНИЕ МИРОВЫМ БОССОМ</b>\nСтатус: {status}\n\nВыберите босса для запуска:"
    rows = []
    for b in bosses:
        rows.append([InlineKeyboardButton(text=f"🚀 Запустить: {b['name']}", callback_data=f"adm:wb:pick:{b['id']}")])
    if wb:
        rows.append([InlineKeyboardButton(text="🛑 Принудительно остановить босса", callback_data="adm:wb:stop")])
    rows.append([InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")])
    await render_view(callback, text, InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:wb:pick:"))
async def cb_adm_wb_pick(callback: CallbackQuery, state: FSMContext):
    if not await db.has_perm(callback.from_user.id, "manage_bosses"):
        return
    cid = int(callback.data.split(":")[3])
    await state.set_state(AdminFSM.world_boss_hp)
    await state.update_data(wb_card_id=cid)
    await callback.message.answer("🌍 Введите общее <b>HP для Мирового Босса</b> (например <code>15000</code>):")
    await callback.answer()


@router.message(AdminFSM.world_boss_hp)
async def fsm_adm_wb_hp(message: Message, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    if not (message.text or "").strip().isdigit():
        await message.answer("❌ Введите целое число!")
        return
    hp = max(500, int(message.text.strip()))
    card = await db.get_card(d["wb_card_id"])
    if not card:
        await message.answer("❌ Карта босса не найдена.")
        return
    await db.spawn_world_boss(card["id"], hp, max(50, card["boss_atk"]))
    await db.log_admin(message.from_user.id, f"Запустил Мирового Босса {card['name']} ({hp} HP)")
    await message.answer(f"🚀 Мировой Босс <b>{esc(card['name'])}</b> ({hp} HP) запущен! Игроки уже могут его атаковать в «🌐 Мультиплеер».")


@router.callback_query(F.data == "adm:wb:stop")
async def cb_adm_wb_stop(callback: CallbackQuery):
    if not await db.has_perm(callback.from_user.id, "manage_bosses"):
        return
    await db.stop_world_boss()
    await db.log_admin(callback.from_user.id, "Остановил Мирового Босса")
    await callback.answer("🛑 Мировой Босс остановлен!", show_alert=True)
    await render_admin_home(callback, callback.from_user.id)


# --- ИГРОКИ, ЭКОНОМИКА, ВЫДАЧА КАРТ И БАНЫ ---

@router.callback_query(F.data == "adm:users")
async def cb_adm_users(callback: CallbackQuery, state: FSMContext):
    if not (await db.has_perm(callback.from_user.id, "manage_users") or await db.has_perm(callback.from_user.id, "manage_economy")):
        await callback.answer("Нет прав!", show_alert=True)
        return
    await state.set_state(AdminFSM.find_user)
    await callback.message.answer("👥 Введите <b>@username</b> или <b>ID</b> игрока для управления его профилем:")
    await callback.answer()


async def render_admin_user_card(target: Message | CallbackQuery, admin_id: int, target_uid: int):
    u = await db.get_user(target_uid)
    if not u:
        await render_view(target, "❌ Игрок не найден.")
        return
    perms = await db.get_admin_perms(admin_id)
    text = (
        f"👤 <b>УПРАВЛЕНИЕ ИГРОКОМ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{format_user_link(u)} | ID: <code>{u['user_id']}</code>\n"
        f"💰 Монеты: <b>{u['coins']}</b> | 🚫 Бан: <b>{'ДА' if u['is_banned'] else 'НЕТ'}</b>\n"
        f"🦠 Паразиты: {u['p_common']} / {u['p_upgraded']} / {u['p_astro']}"
    )
    rows = []
    if perms["manage_economy"]:
        rows.append(
            [
                InlineKeyboardButton(text="💰 +/- Монеты", callback_data=f"au:coins:{target_uid}"),
                InlineKeyboardButton(text="🦠 +1 Астро-паразит", callback_data=f"au:para:{target_uid}"),
            ]
        )
        rows.append([InlineKeyboardButton(text="🃏 Выдать карту из БД", callback_data=f"au:gcard:{target_uid}:0")])
    if perms["manage_users"]:
        ban_lbl = "🔓 Разбанить" if u["is_banned"] else "🚫 Забанить"
        rows.append([InlineKeyboardButton(text=ban_lbl, callback_data=f"au:ban:{target_uid}")])
    rows.append([InlineKeyboardButton(text="🔙 В Админку", callback_data="adm:home")])
    await render_view(target, text, InlineKeyboardMarkup(inline_keyboard=rows))


@router.message(AdminFSM.find_user)
async def fsm_adm_find_user(message: Message, state: FSMContext):
    await state.clear()
    u = await db.find_user(message.text or "")
    if not u:
        await message.answer("❌ Игрок не найден.")
        return
    await render_admin_user_card(message, message.from_user.id, u["user_id"])


@router.callback_query(F.data.startswith("au:coins:"))
async def cb_au_coins(callback: CallbackQuery, state: FSMContext):
    if not await db.has_perm(callback.from_user.id, "manage_economy"):
        return
    tid = int(callback.data.split(":")[2])
    await state.set_state(AdminFSM.user_coins)
    await state.update_data(target_uid=tid)
    await callback.message.answer("💰 Введите сумму для выдачи/списания (например <code>500</code> или <code>-200</code>):")
    await callback.answer()


@router.message(AdminFSM.user_coins)
async def fsm_au_coins(message: Message, state: FSMContext):
    d = await state.get_data()
    tid = d["target_uid"]
    await state.clear()
    try:
        delta = int((message.text or "").strip())
    except ValueError:
        await message.answer("❌ Введите целое число (можно с минусом).")
        return
    await db.add_coins(tid, delta)
    await db.log_admin(message.from_user.id, f"Изменил баланс игрока {tid} на {delta:+d}")
    await message.answer(f"✅ Баланс обновлён ({delta:+d} 💰).")
    await render_admin_user_card(message, message.from_user.id, tid)


@router.callback_query(F.data.startswith("au:para:"))
async def cb_au_para(callback: CallbackQuery):
    if not await db.has_perm(callback.from_user.id, "manage_economy"):
        return
    tid = int(callback.data.split(":")[2])
    await db.add_parasite(tid, "astro", 1)
    await db.log_admin(callback.from_user.id, f"Выдал Астро-паразита игроку {tid}")
    await callback.answer("✅ Выдан 1 Астро-паразит!", show_alert=True)
    await render_admin_user_card(callback, callback.from_user.id, tid)


@router.callback_query(F.data.startswith("au:ban:"))
async def cb_au_ban(callback: CallbackQuery):
    if not await db.has_perm(callback.from_user.id, "manage_users"):
        return
    tid = int(callback.data.split(":")[2])
    if tid == OWNER_ID:
        await callback.answer("Нельзя забанить владельца!", show_alert=True)
        return
    u = await db.get_user(tid)
    if u:
        nxt = 0 if u["is_banned"] else 1
        await db.update_user(tid, is_banned=nxt)
        await db.log_admin(callback.from_user.id, f"{'Забанил' if nxt else 'Разбанил'} игрока {tid}")
        await callback.answer("Статус бана изменён!", show_alert=True)
    await render_admin_user_card(callback, callback.from_user.id, tid)


@router.callback_query(F.data.startswith("au:gcard:"))
async def cb_au_gcard_list(callback: CallbackQuery):
    if not await db.has_perm(callback.from_user.id, "manage_economy"):
        return
    _, _, tid_s, pg_s = callback.data.split(":")
    tid, page = int(tid_s), int(pg_s)
    cards = await db.list_cards()
    per_page = 6
    total_pages = max(1, (len(cards) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    chunk = cards[page * per_page : (page + 1) * per_page]

    rows = []
    for c in chunk:
        rows.append([InlineKeyboardButton(text=f"➕ #{c['id']} {c['name']}", callback_data=f"au:give:{tid}:{c['id']}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"au:gcard:{tid}:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"au:gcard:{tid}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"au:back:{tid}")])
    await render_view(callback, f"🃏 Выберите карту для выдачи игроку <code>{tid}</code>:", InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith("au:give:"))
async def cb_au_give(callback: CallbackQuery, bot: Bot):
    if not await db.has_perm(callback.from_user.id, "manage_economy"):
        return
    _, _, tid_s, cid_s = callback.data.split(":")
    tid, cid = int(tid_s), int(cid_s)
    card = await db.get_card(cid)
    if card:
        await db.give_card(tid, cid)
        await db.log_admin(callback.from_user.id, f"Выдал карту #{cid} ({card['name']}) игроку {tid}")
        try:
            await bot.send_message(tid, f"🎁 <b>Администрация выдала вам карту:</b> <b>{esc(card['name'])}</b>!")
        except Exception:
            pass
        await callback.answer(f"✅ Карта «{card['name']}» выдана!", show_alert=True)
    await render_admin_user_card(callback, callback.from_user.id, tid)


@router.callback_query(F.data.startswith("au:back:"))
async def cb_au_back(callback: CallbackQuery):
    await render_admin_user_card(callback, callback.from_user.id, int(callback.data.split(":")[2]))
    await callback.answer()


# --- РАССЫЛКА ---

@router.callback_query(F.data == "adm:broadcast")
async def cb_adm_broadcast(callback: CallbackQuery, state: FSMContext):
    if not await db.has_perm(callback.from_user.id, "broadcast"):
        await callback.answer("Нет права broadcast!", show_alert=True)
        return
    await state.set_state(AdminFSM.broadcast)
    await callback.message.answer("📢 Отправьте <b>текст или фото с подписью</b> для рассылки всем игрокам (или <code>отмена</code>):")
    await callback.answer()


@router.message(AdminFSM.broadcast)
async def fsm_adm_broadcast(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    if (message.text or "").strip().lower() == "отмена":
        await message.answer("❌ Рассылка отменена.")
        return

    user_ids = await db.get_all_active_user_ids()
    sent, failed = 0, 0
    status_msg = await message.answer(f"⏳ Начинаю рассылку на {len(user_ids)} игроков...")

    for uid in user_ids:
        try:
            await message.copy_to(chat_id=uid)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)

    await db.log_admin(message.from_user.id, f"Сделал рассылку: доставлено {sent}, ошибок {failed}")
    await status_msg.edit_text(f"✅ <b>Рассылка завершена!</b>\nДоставлено: <b>{sent}</b> | Не доставлено: <b>{failed}</b>")


# Пустышка для неактивных кнопок-индикаторов страниц
@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    await callback.answer()


# ==============================================================================
# 9. ТОЧКА ВХОДА
# ==============================================================================

async def main() -> None:
    if BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
        logger.warning("⚠️ Укажите реальный BOT_TOKEN и OWNER_ID перед запуском!")

    await db.init()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    dp.update.outer_middleware(AccessMiddleware())
    dp.include_router(router)

    logger.info("🚀 Skibidi Verse Tower Defense Bot успешно запущен!")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
