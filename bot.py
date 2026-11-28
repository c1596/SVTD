"""
Skibidi Verse: Cards & Infection — Telegram Card RPG Bot (Thanksgiving Event, Часть 1 из 3)
Стек: Python 3.10+, aiogram 3.x, aiosqlite (автоматическая установка при запуске).

Сборка файла:
Просто скопируй подряд Часть 1 + Часть 2 + Часть 3 в один файл bot.py.

Что нового в обновлении:
1. Вкладка «🦃 Ивент» (Thanksgiving Event) с переключением нижнего меню на 2×3 + выход:
   ⚔️ Играть | 📦 Крейты | 👤 Профиль
   🛡 Колода | ⚙️ Админ-панель | 🎒 Инвентарь
   🔙 Выйти из ивента
2. В ивентовых боях только 3 мода (Easy / Medium / Hard) с ручным выбором врагов
   в админке, без модификаторов и с наградой в новой валюте 🍗 Turkey Legs.
3. В ивентовых крейтах показывается только выбранный админом крейт.
4. Честный Luck: шанс 0.3% при x2 становится ровно 0.6% (перераспределение с частых карт).
5. Казуальный скейлинг ИИ (вражеский Strider в Hard больше не улетает в 1000 HP)
   + прокачка карт даёт и ATK, и HP за каждый уровень.
6. Расширенная Админ-панель: отдельный редактор Thanksgiving Event и 31 настройка баланса.
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
# 1. КОНФИГУРАЦИЯ, 31 РАНГ, НАСТРОЙКИ БАЛАНСА И THANKSGIVING EVENT
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
DAILY_COOLDOWN = 86400
MAX_CHILD_BOTS_PER_USER = 2
INITIAL_COINS = 100

DEFAULT_SETTINGS: Dict[str, str] = {
    "maintenance": "0",
    "allow_child_bots": "1",
    "starter_card_id": "0",
    # Основные модификаторы и паразиты
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
    # Казуальный баланс боёв, прокачки и экономики
    "ai_easy_mult": "0.70",
    "ai_med_mult": "0.88",
    "ai_hard_mult": "1.08",
    "ai_nightmare_mult": "1.35",
    "ai_crazy_mult": "1.75",
    "ai_rank_exp": "0.22",
    "lvl_atk_pct": "1.0",
    "lvl_hp_pct": "1.0",
    "xp_per_damage": "0.15",
    "single_dmg_mult": "1.15",
    "splash_side_pct": "35",
    "aoe_dmg_pct": "70",
    "battle_coins_mult": "1.0",
    "battle_trophies_mult": "1.0",
    "market_comm_pct": "20",
    "daily_base_coins": "150",
    "pity_step": "2",
    "pity_max": "50",
    # Глобальные ивенты Luck / Coins
    "luck_event_mult": "1.0",
    "luck_event_end": "0",
    "coin_event_mult": "1.0",
    "coin_event_end": "0",
    # Thanksgiving Event
    "tg_enabled": "1",
    "tg_name": "🦃 Thanksgiving Event",
    "tg_currency_id": "0",
    "tg_crate_id": "0",
    "tg_enemies_easy": "[]",
    "tg_enemies_med": "[]",
    "tg_enemies_hard": "[]",
    "tg_mult_easy": "0.70",
    "tg_mult_med": "0.90",
    "tg_mult_hard": "1.10",
    "tg_team_easy": "2",
    "tg_team_med": "3",
    "tg_team_hard": "4",
    "tg_rew_easy_min": "15",
    "tg_rew_easy_max": "25",
    "tg_rew_med_min": "30",
    "tg_rew_med_max": "45",
    "tg_rew_hard_min": "50",
    "tg_rew_hard_max": "75",
    "tg_allow_infect": "1",
}

GAME_SETTINGS: Dict[str, str] = dict(DEFAULT_SETTINGS)

# 31 настраиваемый параметр в разделе «🎛 Баланс» Админ-панели
SETTING_META: Dict[str, Tuple[str, str, float, float]] = {
    "ai_easy_mult": ("🟢 Статы ИИ: Easy (x)", "float", 0.3, 5.0),
    "ai_med_mult": ("🟡 Статы ИИ: Medium (x)", "float", 0.3, 5.0),
    "ai_hard_mult": ("🔴 Статы ИИ: Hard (x)", "float", 0.3, 5.0),
    "ai_nightmare_mult": ("☠️ Статы ИИ: Nightmare (x)", "float", 0.5, 8.0),
    "ai_crazy_mult": ("🤯 Статы ИИ: Crazy (x)", "float", 0.5, 10.0),
    "ai_rank_exp": ("📈 Степень роста ИИ от ранга", "float", 0.0, 1.0),
    "lvl_atk_pct": ("⚔️ +ATK за уровень карты (%)", "float", 0.0, 20.0),
    "lvl_hp_pct": ("❤️ +HP за уровень карты (%)", "float", 0.0, 20.0),
    "xp_per_damage": ("⭐ XP за 1 урон", "float", 0.01, 5.0),
    "single_dmg_mult": ("🎯 Бонус урона Single (x)", "float", 0.5, 3.0),
    "splash_side_pct": ("🌊 Боковой урон Splash (%)", "float", 10.0, 100.0),
    "aoe_dmg_pct": ("🌪 Урон AOE (%)", "float", 20.0, 150.0),
    "battle_coins_mult": ("💰 Множитель монет в боях", "float", 0.1, 10.0),
    "battle_trophies_mult": ("🏆 Множитель кубков в боях", "float", 0.1, 10.0),
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
    "pity_step": ("🎯 Шаг пити за бой (%)", "int", 0, 25),
    "pity_max": ("🎯 Максимум пити (%)", "int", 0, 200),
    "daily_base_coins": ("🎁 База ежедневки (💰)", "int", 10, 50000),
    "market_comm_pct": ("🏪 Комиссия P2P-рынка (%)", "int", 0, 50),
    "battle_delay_sec": ("⏱ Пауза хода в бою (сек)", "float", 0.5, 4.0),
    "wb_cooldown_sec": ("🌍 КД Мирового Босса (сек)", "int", 5, 600),
}

# Базовые редкости (сидятся только в пустую таблицу rarities)
DEFAULT_RARITIES: List[Tuple[str, str, str, int, float, int]] = [
    ("common", "Common", "⚪️", 1, 1.0, 0),
    ("uncommon", "Uncommon", "🟢", 2, 0.5, 0),
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
    "Single": ("🎯", "Усиленный удар по 1 цели"),
    "AOE": ("🌪", "Удар по всем живым врагам"),
    "Splash": ("🌊", "100% по цели + боковой урон остальным"),
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

# Обычные сложности: (название, ключ настройки множителя статов, множитель награды, сдвиг тира, +инфект%)
DIFFICULTIES: Dict[str, Tuple[str, str, float, int, int]] = {
    "easy": ("🟢 Easy", "ai_easy_mult", 0.65, -1, 0),
    "med": ("🟡 Medium", "ai_med_mult", 1.0, 0, 5),
    "hard": ("🔴 Hard", "ai_hard_mult", 1.4, 1, 12),
    "nightmare": ("☠️ Nightmare", "ai_nightmare_mult", 1.8, 2, 22),
    "crazy": ("🤯 Crazy", "ai_crazy_mult", 2.5, 3, 35),
}

TG_MODES: Dict[str, str] = {
    "easy": "🟢 Easy",
    "med": "🟡 Medium",
    "hard": "🔴 Hard",
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
    "manage_events": "🎉 Ивенты (Luck / Coins / Thanksgiving)",
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


def cfg_id_list(k: str) -> List[int]:
    """Читает JSON-список ID карт из GAME_SETTINGS (для врагов Thanksgiving Event)."""
    raw = GAME_SETTINGS.get(k, DEFAULT_SETTINGS.get(k, "[]"))
    try:
        arr = json.loads(raw)
        if isinstance(arr, list):
            return [int(x) for x in arr]
    except Exception:
        pass
    return []


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


def calc_crate_probs(
    cards_map: Dict[str, Any],
    all_cards_by_id: Dict[str, Dict[str, Any]],
    luck_mult: float = 1.0,
) -> List[Tuple[Dict[str, Any], float]]:
    """
    ЧЕСТНЫЙ РАСЧЁТ ШАНСОВ КРЕЙТА С УЧЁТОМ LUCK!
    Пример: если у Мифика базовый шанс 0.3% и включён Luck x2,
    то его новый шанс становится РОВНО 0.6% (лишние проценты забираются
    пропорционально у самых частых карт крейта, сумма всегда ровно 100%).
    """
    raw: List[Tuple[Dict[str, Any], float]] = []
    tot_w = 0.0
    for k, w in cards_map.items():
        co = all_cards_by_id.get(str(k))
        wf = float(w)
        if co and wf > 0:
            raw.append((co, wf))
            tot_w += wf
    if not raw or tot_w <= 0:
        return []

    base_entries: List[Tuple[Dict[str, Any], float]] = [
        (co, (wf / tot_w) * 100.0) for co, wf in raw
    ]
    if luck_mult <= 1.0 or len(base_entries) <= 1:
        return base_entries

    # Определяем «частые» карты крейта (минимальная редкость внутри этого крейта)
    # и «редкие» (все карты более высоких редкостей).
    min_rw = min(get_rarity(co["rarity"])["weight"] for co, _ in base_entries)
    rare_items = [(co, p) for co, p in base_entries if get_rarity(co["rarity"])["weight"] > min_rw]
    common_items = [(co, p) for co, p in base_entries if get_rarity(co["rarity"])["weight"] <= min_rw]

    # Если все карты одной редкости — бустим те, у которых шанс ниже среднего (напр. крафтовые)
    if not rare_items or not common_items:
        avg_p = 100.0 / len(base_entries)
        rare_items = [(co, p) for co, p in base_entries if p < avg_p]
        common_items = [(co, p) for co, p in base_entries if p >= avg_p]

    if not rare_items or not common_items:
        return base_entries

    # Умножаем редкие шансы ровно на luck_mult (0.3% * 2 = 0.6%)
    boosted_rare = [(co, p * luck_mult) for co, p in rare_items]
    rare_sum = sum(p for _, p in boosted_rare)

    # Защита от переполнения 100% при экстремально высоком Luck (напр. x20)
    if rare_sum > 95.0:
        scale = 95.0 / rare_sum
        boosted_rare = [(co, p * scale) for co, p in boosted_rare]
        rare_sum = 95.0

    rem_for_common = max(0.0, 100.0 - rare_sum)
    common_base_sum = sum(p for _, p in common_items)
    adjusted_common = [
        (co, (p / common_base_sum) * rem_for_common if common_base_sum > 0 else 0.0)
        for co, p in common_items
    ]
    return boosted_rare + adjusted_common


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
# 2. БАЗА ДАННЫХ (AIOSQLITE) — АВТОМИГРАЦИЯ, TURKEY LEGS, БЭКАП И СТАРТ-ЮНИТ
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
                    mod_player_crit INTEGER DEFAULT 0,
                    in_event_mode INTEGER DEFAULT 0
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

            # Автоматически создаём валюту «🍗 Turkey Legs» и привязываем к Thanksgiving Event
            cur_row = await (await conn.execute(
                "SELECT id FROM currencies WHERE LOWER(name) LIKE '%turkey legs%' LIMIT 1"
            )).fetchone()
            if not cur_row:
                c_ins = await conn.execute(
                    "INSERT INTO currencies (name, drop_in_battles, drop_chance, drop_min, drop_max) VALUES (?, 0, 0.0, 1, 1)",
                    ("🍗 Turkey Legs",),
                )
                tg_cur_id = c_ins.lastrowid
            else:
                tg_cur_id = cur_row[0]

            saved_tg_cur = await (await conn.execute("SELECT value FROM settings WHERE key = 'tg_currency_id'")).fetchone()
            if not saved_tg_cur or str(saved_tg_cur[0]) in ("0", ""):
                await conn.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES ('tg_currency_id', ?)",
                    (str(tg_cur_id),),
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
                ("in_event_mode", "INTEGER DEFAULT 0"),
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

    async def reset_all_event_modes(self) -> None:
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute("UPDATE users SET in_event_mode = 0")
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

    # -------------------- P2P Рынок (комиссия из market_comm_pct) --------------------

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
        comm_pct = max(0, min(50, cfg_int("market_comm_pct")))
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
            payout = int(price * (100 - comm_pct) / 100)
            comm = price - payout
            await conn.execute("UPDATE users SET coins = coins - ? WHERE user_id = ?", (price, buyer_id))
            await conn.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (payout, lot["seller_id"]))
            if comm > 0:
                await conn.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (comm, OWNER_ID))
            await conn.execute("UPDATE inventory SET user_id = ?, equip_slot = 0 WHERE id = ?", (buyer_id, lot["inv_id"]))
            await conn.execute("INSERT OR IGNORE INTO user_discovered (user_id, card_id) VALUES (?, ?)", (buyer_id, lot["card_id"]))
            await conn.execute("DELETE FROM market WHERE id = ?", (market_id,))
            await conn.commit()
            res = dict(lot)
            res["payout"] = payout
            res["seller_pct"] = 100 - comm_pct
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
