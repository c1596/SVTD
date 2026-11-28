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
# ==============================================================================
# 4. СТАТЫ КАРТ, КАЗУАЛЬНЫЙ ПОДБОР ВРАГОВ, THANKSGIVING-ВРАГИ, 4×4 БОЙ И UI
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
    """Считает боевые статы карты с учётом уровня (+ATK% и +HP% за уровень), Shiny, Infected и Сигны."""
    lvl = max(1, min(MAX_CARD_LEVEL, int(item.get("level", 1))))
    atk_step = cfg_float("lvl_atk_pct")
    hp_step = cfg_float("lvl_hp_pct")
    lvl_atk_mult = 1.0 + ((lvl - 1) * atk_step / 100.0)
    lvl_hp_mult = 1.0 + ((lvl - 1) * hp_step / 100.0)

    sh_mult = (1.0 + cfg_float("shiny_bonus_pct") / 100.0) if item.get("is_shiny") else 1.0
    inf_mult = cfg_float("infected_mult") if item.get("is_infected") else 1.0
    st = item.get("sign_type", "none")
    sgn_mult = 1.0 + (
        cfg_float("admin_sign_pct") / 100.0
        if st == "admin"
        else (cfg_float("partner_sign_pct") / 100.0 if st == "partner" else 0.0)
    )

    hp = max(1, int(round(item["hp"] * lvl_hp_mult * sh_mult * inf_mult * sgn_mult)))
    atk = max(1, int(round(item["atk"] * lvl_atk_mult * sh_mult * inf_mult * sgn_mult)))
    b_bonus = (1.05 if item.get("is_shiny") else 1.0) * (1.05 if item.get("is_infected") else 1.0)
    b_dmg = round(float(item.get("booster_dmg_mult", 1.15)) * b_bonus, 2)
    b_hp = round(float(item.get("booster_hp_mult", 1.15)) * b_bonus, 2)
    return {
        "hp": hp,
        "atk": atk,
        "power": hp + atk * 4,
        "b_dmg": b_dmg,
        "b_hp": b_hp,
        "lvl_atk_pct": round((lvl - 1) * atk_step, 1),
        "lvl_hp_pct": round((lvl - 1) * hp_step, 1),
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
    xp_rate = cfg_float("xp_per_damage")

    lvl_bonus_txt = f"+{fmt_pct(st['lvl_atk_pct'])}% ATK / +{fmt_pct(st['lvl_hp_pct'])}% HP"
    xp_txt = (
        f"⭐ Lvl <b>{lvl}/{MAX_CARD_LEVEL}</b> (MAX | <b>{lvl_bonus_txt}</b>)"
        if lvl >= MAX_CARD_LEVEL
        else f"⭐ Lvl <b>{lvl}/{MAX_CARD_LEVEL}</b> (<b>{lvl_bonus_txt}</b>)\n   {make_bar(xp, need, 8)} {xp:.1f}/{need:.0f} XP"
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
        f"📈 <b>УРОВЕНЬ (1 урон = {fmt_pct(xp_rate)} XP):</b>",
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
    """Базовое распределение тиров редкостей (0..6) для Medium по таблице 31 ранга."""
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
    sec_w = min(65.0, 25.0 + (rank_idx - 24) * 6.5)
    return {5: round(100.0 - sec_w, 1), 6: round(sec_w, 1)}


def _apply_difficulty_to_tiers(base_tiers: Dict[int, float], diff_key: str) -> Dict[int, float]:
    """Сдвигает базовые тиры таблицы рангов в зависимости от сложности."""
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
    """На Skibidi Rookie I–III у врага от 1 до 3 юнитов, с Rookie IV — полная команда из 4."""
    if rank_idx == 0:
        return random.randint(1, 2)
    if rank_idx == 1:
        return 2
    if rank_idx == 2:
        return random.randint(2, 3)
    return 4


def _make_enemy_unit(chosen: Dict[str, Any], stat_scale: float, enemy_shiny_ch: float = 0.0) -> Dict[str, Any]:
    is_sh = 1 if (enemy_shiny_ch > 0 and random.random() < enemy_shiny_ch) else 0
    sh_m = (1.0 + cfg_float("shiny_bonus_pct") / 100.0) if is_sh else 1.0
    hp = max(30, int(round(chosen["hp"] * stat_scale * sh_m)))
    atk = max(8, int(round(chosen["atk"] * stat_scale * sh_m)))
    return {
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
    }


async def generate_enemy_team(rank_idx: int, diff_key: str) -> List[Dict[str, Any]]:
    """
    Подбирает отряд врагов для обычных боёв с казуальным скейлингом ИИ:
    stat_scale = (r_diff_mult ** ai_rank_exp) * ai_{diff}_mult.
    Больше никаких 1000 HP у Strider в Hard!
    """
    _, d_mult_key, _, _, _ = DIFFICULTIES[diff_key]
    d_mult = cfg_float(d_mult_key)
    rank_exp = cfg_float("ai_rank_exp")
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

    mapped_weights: Dict[int, float] = {}
    for std_tier, weight in raw_dist.items():
        idx = min(max_idx, max(0, int(round(std_tier * max_idx / 6.0)))) if max_idx > 0 else 0
        mapped_weights[idx] = mapped_weights.get(idx, 0.0) + float(weight)

    avail_allowed = {idx: w for idx, w in mapped_weights.items() if by_rar.get(rar_keys[idx])}
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

    stat_scale = max(0.55, (r_diff_mult ** rank_exp) * d_mult)
    league = min(6, max(0, rank_idx // 4))
    enemy_shiny_ch = 0.0 if (diff_key == "easy" and league < 3) else min(0.08, 0.01 * d_mult)
    team_size = _enemy_team_size(rank_idx)

    team: List[Dict[str, Any]] = []
    used: Set[int] = set()
    for _ in range(team_size):
        pick_idx = random.choices(allowed_indices, weights=allowed_weights, k=1)[0]
        tier_cards = by_rar.get(rar_keys[pick_idx]) or all_ai
        fresh = [c for c in tier_cards if c["id"] not in used]
        chosen = dict(random.choice(fresh if fresh else tier_cards))
        used.add(chosen["id"])
        team.append(_make_enemy_unit(chosen, stat_scale, enemy_shiny_ch))
    return team


async def generate_tg_enemy_team(mode_key: str) -> List[Dict[str, Any]]:
    """Генерирует отряд врагов для Thanksgiving Event строго из списка карт, выбранных админом."""
    enemy_ids = cfg_id_list(f"tg_enemies_{mode_key}")
    if not enemy_ids:
        return []
    all_by_id = {c["id"]: c for c in await db.list_cards()}
    pool = [all_by_id[cid] for cid in enemy_ids if cid in all_by_id]
    if not pool:
        return []

    team_size = max(1, min(MAX_DECK_SIZE, cfg_int(f"tg_team_{mode_key}")))
    stat_scale = max(0.30, cfg_float(f"tg_mult_{mode_key}"))
    team: List[Dict[str, Any]] = []
    used: Set[int] = set()
    for _ in range(team_size):
        fresh = [c for c in pool if c["id"] not in used]
        chosen = dict(random.choice(fresh if fresh else pool))
        used.add(chosen["id"])
        team.append(_make_enemy_unit(chosen, stat_scale, 0.0))
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
    enemy_side_label: str = "Alliance",
) -> str:
    p_txt = "\n".join(fmt_combat_unit(i, u) for i, u in enumerate(t1, 1))
    e_txt = "\n".join(fmt_combat_unit(i, u) for i, u in enumerate(t2, 1))
    ev = "\n".join(f"• {l}" for l in logs[-3:]) if logs else "• <i>Бой начинается...</i>"
    inf_tag = f" | 🦠 Infected: <b>{inf_cnt}</b>" if inf_cnt else ""
    return (
        f"{title} | <b>Раунд {rnd}</b>{inf_tag}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔵 <b>{esc(p_name)} (Skibidi):</b>\n{p_txt}\n\n"
        f"🔴 <b>{esc(e_name)} ({esc(enemy_side_label)} — {len(t2)}):</b>\n{e_txt}\n"
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
    allow_infect: bool = True,
) -> None:
    for u in atk_team:
        if u["hp"] > 0 and u["burn"] > 0:
            bd = u["burn"]
            u["hp"] = max(0, u["hp"] - bd)
            u["burn"] = 0
            if u["hp"] <= 0:
                logs.append(f"🔥 <b>{esc(u['name'])}</b> сгорел (-{bd}) ☠️")
                if not is_player and allow_infect:
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
            if is_player and allow_infect:
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
        aoe_d = max(1, int(base_dmg * (cfg_float("aoe_dmg_pct") / 100.0)))
        kills = sum(1 for t in def_alive if hit_target(t, aoe_d))
        logs.append(f"🌪 <b>{esc(actor['name'])}</b> ➔ -{aoe_d} по всем!{crit_tag}" + (f" (☠️x{kills})" if kills else ""))
    elif cls == "Splash":
        main_t = random.choice(def_alive)
        sp_d = max(1, int(base_dmg * (cfg_float("splash_side_pct") / 100.0)))
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
        sing_d = max(1, int(base_dmg * cfg_float("single_dmg_mult")))
        ko = " ☠️" if hit_target(t, sing_d) else ""
        logs.append(f"🎯 <b>{esc(actor['name'])}</b> ➔ {esc(t['name'])} (-{sing_d}){crit_tag}{ko}")


async def render_view(
    target: Message | CallbackQuery,
    text: str,
    kb: Optional[InlineKeyboardMarkup] = None,
    photo: Optional[str] = None,
) -> None:
    """Безопасная отрисовка экрана с защитой от Flood Control (TelegramRetryAfter)."""
    try:
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
    except TelegramRetryAfter as e:
        logger.warning("Flood control in render_view: retry after %ss", e.retry_after)
        if isinstance(target, CallbackQuery):
            try:
                await target.answer(f"⏳ Слишком часто! Подождите {e.retry_after} сек.", show_alert=False)
            except Exception:
                pass


def main_reply_kb(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """
    Основное меню 3×3 + строка вкладки Thanksgiving Event (если ивент включён):
    колода      играть        инвентарь
    профиль     крейты        индекс
    лидерборд   админ панель  мультиплеер
    [🦃 Ивент]
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
    if GAME_SETTINGS.get("tg_enabled", "1") == "1":
        rows.append([KeyboardButton(text="🦃 Ивент")])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=False,
        input_field_placeholder="Меню Skibidi Verse...",
    )


def event_reply_kb(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """
    Ивентовое меню Thanksgiving Event:
    играть    крейты        профиль
    колода    админ панель  инвентарь
    🔙 Выйти из ивента
    """
    row2 = [KeyboardButton(text="🛡 Колода")]
    if is_admin:
        row2.append(KeyboardButton(text="⚙️ Админ-панель"))
    row2.append(KeyboardButton(text="🎒 Инвентарь"))

    rows = [
        [KeyboardButton(text="⚔️ Играть"), KeyboardButton(text="📦 Крейты"), KeyboardButton(text="👤 Профиль")],
        row2,
        [KeyboardButton(text="🔙 Выйти из ивента")],
    ]
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=False,
        input_field_placeholder="🦃 Thanksgiving Event...",
    )


def is_user_in_event(u: Optional[Dict[str, Any]]) -> bool:
    return bool(u and u.get("in_event_mode") and GAME_SETTINGS.get("tg_enabled", "1") == "1")


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
            if user.get("in_event_mode") and GAME_SETTINGS.get("tg_enabled", "1") != "1":
                await db.update_user(tg_user.id, in_event_mode=0)
                user["in_event_mode"] = 0
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


class EventAdminFSM(StatesGroup):
    edit_name = State()
    edit_rewards = State()
    edit_mult = State()
    edit_team_size = State()


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
# 6. ОСНОВНОЙ РОУТЕР: /start, ВКЛАДКА «🦃 ИВЕНТ», /linkbot, ПРОФИЛЬ, КОЛОДА, ИНВЕНТАРЬ, ИНДЕКС
# ==============================================================================

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, is_admin: bool):
    await state.clear()
    _, is_new = await db.ensure_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    await db.update_user(message.from_user.id, in_event_mode=0)
    gift = ""
    if is_new:
        st_id = cfg_int("starter_card_id")
        st_card = await db.get_card(st_id) if st_id > 0 else None
        st_txt = f" и стартовый юнит <b>{esc(st_card['name'])}</b> (уже в слоте #1)!" if st_card else "!"
        gift = f"\n\n🎁 <b>Стартовый набор:</b> {INITIAL_COINS} 💰, 2 🦠 паразита{st_txt}"
    tg_note = (
        f"\n• 🦃 Активен <b>{esc(GAME_SETTINGS.get('tg_name', 'Thanksgiving Event'))}</b> — нажми «🦃 Ивент» снизу!"
        if GAME_SETTINGS.get("tg_enabled", "1") == "1"
        else ""
    )
    kb_inline = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔽 Скрыть нижнее меню", callback_data="ui:hide_menu")]])
    await message.answer(
        f"🚽 <b>Skibidi Verse: Cards & Infection</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"• Играй за <b>Скибиди-Туалетов</b>, сражайся 4×4 и поднимайся по <b>31 рангу</b>!\n"
        f"• При убийстве врага в бою есть шанс его <b>🦠 заразить</b> (чем выше ранг и паразит — тем выше шанс!).\n"
        f"• Качай карты в боях: <b>+{fmt_pct(cfg_float('lvl_atk_pct'))}% ATK</b> и <b>+{fmt_pct(cfg_float('lvl_hp_pct'))}% HP</b> за каждый уровень (до 50 ур.)."
        f"{tg_note}{gift}\n\n"
        f"👇 Используй меню снизу (вернуть меню в любой момент — /start).",
        reply_markup=main_reply_kb(is_admin),
    )
    await message.answer("⚙️ <i>Управление видимостью меню:</i>", reply_markup=kb_inline)


@router.callback_query(F.data == "ui:hide_menu")
async def cb_hide_menu(cb: CallbackQuery):
    await cb.message.answer("🔽 Нижнее меню скрыто. Чтобы вернуть его обратно — нажмите /start.", reply_markup=ReplyKeyboardRemove())
    await cb.answer("Меню скрыто!")


# -------------------- ВКЛАДКА «🦃 ИВЕНТ» (THANKSGIVING EVENT) --------------------

@router.message(F.text == "🦃 Ивент")
async def menu_enter_event(message: Message, state: FSMContext, is_admin: bool):
    await state.clear()
    if GAME_SETTINGS.get("tg_enabled", "1") != "1":
        await message.answer("🔒 Ивент сейчас не активен.", reply_markup=main_reply_kb(is_admin))
        return
    uid = message.from_user.id
    await db.update_user(uid, in_event_mode=1)

    tg_name = GAME_SETTINGS.get("tg_name", "🦃 Thanksgiving Event")
    tg_cur_id = cfg_int("tg_currency_id")
    cur_obj = await db.get_currency(tg_cur_id) if tg_cur_id else None
    cur_name = cur_obj["name"] if cur_obj else "🍗 Turkey Legs"
    bal = await db.get_user_currency_bal(uid, tg_cur_id) if tg_cur_id else 0

    tg_cr_id = cfg_int("tg_crate_id")
    cr_obj = await db.get_crate(tg_cr_id) if tg_cr_id else None
    cr_txt = f"<b>{esc(cr_obj['name'])}</b> ({cr_obj['price']} {esc(cur_name)})" if cr_obj else "<i>Скоро появится</i>"

    await message.answer(
        f"<b>{esc(tg_name)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🍂 Добро пожаловать в ивентовый режим!\n\n"
        f"• ⚔️ В «<b>Играть</b>» доступны 3 ивентовых мода (<b>Easy / Medium / Hard</b>) с особыми врагами (модификаторы отключены).\n"
        f"• 🍗 За победы вы получаете <b>{esc(cur_name)}</b> — ваш баланс: <b>{bal}</b>.\n"
        f"• 📦 В «<b>Крейты</b>» доступен эксклюзивный крейт: {cr_txt}.\n\n"
        f"👇 Нижнее меню переключено на ивентовое. Вернуться обратно — «<b>🔙 Выйти из ивента</b>».",
        reply_markup=event_reply_kb(is_admin),
    )


@router.message(F.text == "🔙 Выйти из ивента")
async def menu_exit_event(message: Message, state: FSMContext, is_admin: bool):
    await state.clear()
    await db.update_user(message.from_user.id, in_event_mode=0)
    await message.answer(
        "🏠 Вы вернулись в обычный режим <b>Skibidi Verse</b>!",
        reply_markup=main_reply_kb(is_admin),
    )


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
        "<i>Пример: <code>1234567890:AAF_...</code></i>"
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
    mode_tag = f"\n🦃 Режим: <b>{esc(GAME_SETTINGS.get('tg_name', 'Thanksgiving Event'))}</b>" if is_user_in_event(u) else ""

    return (
        f"{'👤 <b>ВАШ ПРОФИЛЬ</b>' if is_self else '🔎 <b>ПРОФИЛЬ ИГРОКА</b>'}{mode_tag}\n"
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
    base_d = cfg_int("daily_base_coins")
    coins = int((base_d + min(streak, 10) * 35) * c_mult)
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
        f"🧬 <b>МОДИФИКАТОРЫ БОЯ (обычный режим)</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"🔴 Дебаффы увеличивают монеты, кубки и <b>шанс заражения</b>.\n"
        f"🟢 Баффы упрощают бой, но режут монеты.\n"
        f"<i>⚠️ В режиме Thanksgiving Event модификаторы отключены.</i>\n\n"
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


# -------------------- ИНДЕКС КАРТ (ДО 8 ЮНИТОВ НА СТРАНИЦУ + ЧЕСТНЫЙ LUCK) --------------------

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

    all_c_by_id = {str(c["id"]): c for c in all_cards}
    crates = await db.list_crates(active_only=True)
    crate_sources: Dict[int, List[str]] = {}
    for cr in crates:
        probs = calc_crate_probs(cr["cards"], all_c_by_id, l_mult)
        for co, pct in probs:
            if pct > 0:
                crate_sources.setdefault(co["id"], []).append(f"{cr['name']} ({fmt_pct(round(pct, 4))}%)")

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
        lines.append(f"🍀 <b>LUCK EVENT x{l_mult}!</b> Редкие шансы умножены на x{l_mult}!\n")

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
    comm = max(0, min(50, cfg_int("market_comm_pct")))
    await state.set_state(PlayerFSM.market_price)
    await state.update_data(sell_id=iid)
    await cb.message.answer(
        f"🏷 Введите цену для <b>{esc(it['name'])}</b> (50–500000 💰).\n"
        f"<i>Вы получите <b>{100 - comm}%</b>, комиссия рынка — <b>{comm}%</b>.</i>"
    )
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
    comm = max(0, min(50, cfg_int("market_comm_pct")))
    await db.create_market_lot(m.from_user.id, iid, pr)
    await m.answer(f"✅ <b>{esc(it['name'])}</b> выставлена за <b>{pr} 💰</b> (получите {int(pr * (100 - comm) / 100)} 💰).")


# ==============================================================================
# 7. БОИ 4×4: ОБЫЧНЫЙ РЕЖИМ И THANKSGIVING EVENT (БЕЗ ЗАВИСАНИЙ И БЕЗ МОДОВ)
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
        + "\n👇 Выберите сложность отряда:"
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


async def render_tg_battle_hub(target: Message | CallbackQuery, uid: int):
    """Экран выбора сложности внутри Thanksgiving Event (только Easy / Medium / Hard, без модов)."""
    u = await db.get_user(uid)
    tg_name = GAME_SETTINGS.get("tg_name", "🦃 Thanksgiving Event")
    tg_cur_id = cfg_int("tg_currency_id")
    cur_obj = await db.get_currency(tg_cur_id) if tg_cur_id else None
    cur_name = cur_obj["name"] if cur_obj else "🍗 Turkey Legs"
    bal = await db.get_user_currency_bal(uid, tg_cur_id) if tg_cur_id else 0
    allow_inf = GAME_SETTINGS.get("tg_allow_infect", "1") == "1"

    armed = u["armed_parasite"]
    if armed in PARASITES and u[PARASITES[armed][1]] <= 0:
        armed = "none"
        await db.update_user(uid, armed_parasite="none")
    p_bonus = cfg_float(f"p_{armed}_bonus") if armed in PARASITES else 0.0
    p_label = f"{PARASITES[armed][0]} (+{fmt_pct(p_bonus)}%)" if armed in PARASITES else "Без паразита (+0%)"

    all_c = {c["id"]: c for c in await db.list_cards()}
    lines = [
        f"⚔️ <b>{esc(tg_name)} — БОИ</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"🍗 Ваш баланс: <b>{bal} {esc(cur_name)}</b>",
        "🚫 Модификаторы боя: <b>отключены</b>",
    ]
    if allow_inf:
        lines.append(f"🦠 Паразит на бой: <b>{p_label}</b>")
    lines.append("")

    rows: List[List[InlineKeyboardButton]] = []
    for mk, mlabel in TG_MODES.items():
        e_ids = cfg_id_list(f"tg_enemies_{mk}")
        e_names = [all_c[i]["name"] for i in e_ids if i in all_c]
        r_min = cfg_int(f"tg_rew_{mk}_min")
        r_max = max(r_min, cfg_int(f"tg_rew_{mk}_max"))
        t_sz = cfg_int(f"tg_team_{mk}")
        mult = cfg_float(f"tg_mult_{mk}")
        e_preview = ", ".join(esc(x) for x in e_names[:4]) + ("..." if len(e_names) > 4 else "") if e_names else "<i>не настроены админом</i>"
        lines.append(f"• <b>{mlabel}</b> (👾 {t_sz} шт., x{fmt_pct(mult)} | 🍗 {r_min}–{r_max})\n   └ Враги: {e_preview}")
        rows.append([InlineKeyboardButton(text=f"{mlabel} — {r_min}–{r_max} 🍗", callback_data=f"tg:go:{mk}")])

    if allow_inf:
        rows.append([InlineKeyboardButton(text="🦠 Выбрать паразита", callback_data="tg:par")])
    await render_view(target, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows))


@router.message(F.text == "⚔️ Играть")
async def menu_battle(m: Message, state: FSMContext, db_user: Dict[str, Any]):
    await state.clear()
    if is_user_in_event(db_user):
        await render_tg_battle_hub(m, m.from_user.id)
    else:
        await render_battle_hub(m, m.from_user.id)


@router.callback_query(F.data == "btl:hub")
async def cb_btl_hub(cb: CallbackQuery):
    await render_battle_hub(cb, cb.from_user.id)
    await cb.answer()


@router.callback_query(F.data == "tg:hub")
async def cb_tg_hub(cb: CallbackQuery):
    await render_tg_battle_hub(cb, cb.from_user.id)
    await cb.answer()


@router.callback_query(F.data == "btl:mods")
async def cb_btl_mods(cb: CallbackQuery):
    await render_mods(cb, cb.from_user.id, "btl:hub")
    await cb.answer()


@router.callback_query(F.data.in_({"btl:par", "tg:par"}))
async def cb_btl_par(cb: CallbackQuery):
    is_tg = cb.data == "tg:par"
    back_cb = "tg:hub" if is_tg else "btl:hub"
    set_pref = "tg:setp:" if is_tg else "btl:setp:"
    u = await db.get_user(cb.from_user.id)
    cur = u["armed_parasite"]
    rows = [[InlineKeyboardButton(text=("✅ " if cur == "none" else "") + "Без паразита (+0%)", callback_data=f"{set_pref}none")]]
    for k in ("common", "upgraded", "elite"):
        name, col, _, bon = get_parasite_info(k)
        cnt = u[col]
        rows.append([InlineKeyboardButton(text=f"{'✅ ' if cur == k else ''}{name} (+{fmt_pct(bon)}%) — {cnt} шт.", callback_data=f"{set_pref}{k}")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data=back_cb)])
    await render_view(cb, "🦠 <b>ВЫБОР ПАРАЗИТА НА БОЙ</b>\n1 паразит тратится в начале боя и усиливает шанс заражения всех врагов.", InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer()


@router.callback_query(F.data.startswith(("btl:setp:", "tg:setp:")))
async def cb_btl_setp(cb: CallbackQuery):
    pref, _, pk = cb.data.split(":")
    u = await db.get_user(cb.from_user.id)
    if pk != "none" and u[PARASITES[pk][1]] <= 0:
        await cb.answer("У вас нет этого паразита! Купите в обычной вкладке «📦 Крейты».", show_alert=True)
        return
    await db.update_user(cb.from_user.id, armed_parasite=pk)
    if pref == "tg":
        await render_tg_battle_hub(cb, cb.from_user.id)
    else:
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


@router.callback_query(F.data.startswith("tg:go:"))
async def cb_tg_go(cb: CallbackQuery):
    uid = cb.from_user.id
    if GAME_SETTINGS.get("tg_enabled", "1") != "1":
        await cb.answer("Ивент сейчас не активен!", show_alert=True)
        return
    _cleanup_stale_user_battle(uid)
    if uid in USERS_IN_BATTLE:
        await cb.answer("Вы уже в бою!", show_alert=True)
        return
    deck = await db.get_inventory(uid, only_equipped=True)
    if not deck:
        await cb.answer("Сначала наденьте карты в «🛡 Колода»!", show_alert=True)
        return
    mode_key = cb.data.split(":")[2]
    if mode_key not in TG_MODES:
        return
    if not cfg_id_list(f"tg_enemies_{mode_key}"):
        await cb.answer("Админ ещё не выбрал врагов для этой сложности ивента!", show_alert=True)
        return

    USERS_IN_BATTLE.add(uid)
    try:
        await cb.answer("🦃 Входим в ивентовый бой!")
    except Exception:
        pass
    asyncio.create_task(run_tg_battle_task(cb.message, uid, mode_key, deck))


async def run_4v4_battle_task(origin: Message, uid: int, diff_key: str, deck: List[Dict[str, Any]]) -> None:
    bid = uuid.uuid4().hex[:10]
    ACTIVE_BATTLES[bid] = {"uid": uid, "surrendered": False, "started_at": time.monotonic()}
    try:
        u = await db.get_user(uid)
        rank_idx, r_name, _, r_rew_mult, r_inf_bonus = get_rank_info(u["trophies"])
        d_name, _, d_rew_scale, _, d_inf_bonus = DIFFICULTIES[diff_key]
        l_mult, _, c_event_mult, _ = get_active_events()

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

            perform_combat_turn(t1, t2, True, logs, dmg_tracker, infected_drops, total_inf_bonus, l_mult, crit_ch, True)
            if not any(x["hp"] > 0 for x in t2):
                winner = 1
                break

            if mods.get("mod_enemy_regen"):
                for e in t2:
                    if e["hp"] > 0 and e["hp"] < e["max_hp"]:
                        e["hp"] = min(e["max_hp"], e["hp"] + max(1, int(e["max_hp"] * 0.05)))
            perform_combat_turn(t2, t1, False, logs, dmg_tracker, infected_drops, total_inf_bonus, l_mult, 0.0, True)
            if not any(x["hp"] > 0 for x in t1):
                winner = 2
                break

            now_t = time.monotonic()
            min_edit_gap = 1.5 if edits_count == 0 else max(delay, 3.2)
            if msg is not None and now_t >= flood_until and (now_t - last_edit_ts) >= min_edit_gap:
                screen = render_battle_screen(title, u["full_name"], t1, d_name, t2, logs, rnd, len(infected_drops))
                try:
                    await asyncio.wait_for(msg.edit_text(screen, reply_markup=kb), timeout=10.0)
                    last_edit_ts = time.monotonic()
                    edits_count += 1
                except TelegramRetryAfter as e:
                    flood_until = time.monotonic() + e.retry_after + 1.0
                except Exception:
                    pass

            await _battle_sleep(st, delay)

        if winner == 0:
            r1 = sum(x["hp"] for x in t1) / max(1, sum(x["max_hp"] for x in t1))
            r2 = sum(x["hp"] for x in t2) / max(1, sum(x["max_hp"] for x in t2))
            winner = 1 if r1 >= r2 else 2

        xp_rate = cfg_float("xp_per_damage")
        total_dmg = sum(dmg_tracker.values())
        lvl_ups: List[str] = []
        for iid, dmg in dmg_tracker.items():
            it = await db.get_inv_item(iid)
            if not it:
                continue
            nl, nx, ups = apply_card_xp(it["level"], it["xp"], round(dmg * xp_rate, 2))
            await db.update_inv_xp(iid, nl, nx)
            if ups > 0:
                lvl_ups.append(f"⭐ {esc(it['name'])} ➔ Lvl.{nl}!")

        fresh_u = await db.get_user(uid)
        coin_mod_mult = max(0.2, 1.0 + mod_coin_d)
        tr_mod_mult = max(0.5, 1.0 + mod_tr_d)

        if winner == 1:
            coins_won = max(
                20,
                int(random.randint(35, 85) * r_rew_mult * d_rew_scale * coin_mod_mult * c_event_mult * cfg_float("battle_coins_mult")),
            )
            base_tr = random.randint(1, 2) if rank_idx >= 29 else max(5, 18 - int((rank_idx / 28) * 11))
            tr_won = max(1, int(base_tr * d_rew_scale * tr_mod_mult * cfg_float("battle_trophies_mult")))

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

            p_step = cfg_int("pity_step")
            p_max = cfg_int("pity_max")
            new_pity = 0 if infected_drops else min(p_max, fresh_u["pity_bonus"] + p_step)
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
                f"💥 Урон: <b>{int(total_dmg)}</b> (+{round(total_dmg * xp_rate, 1)} XP картам)",
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


async def run_tg_battle_task(origin: Message, uid: int, mode_key: str, deck: List[Dict[str, Any]]) -> None:
    """Бой внутри Thanksgiving Event: выбранные админом враги, без модификаторов, награда Turkey Legs."""
    bid = uuid.uuid4().hex[:10]
    ACTIVE_BATTLES[bid] = {"uid": uid, "surrendered": False, "started_at": time.monotonic()}
    try:
        u = await db.get_user(uid)
        _, _, _, _, r_inf_bonus = get_rank_info(u["trophies"])
        m_name = TG_MODES[mode_key]
        tg_name = GAME_SETTINGS.get("tg_name", "🦃 Thanksgiving Event")
        allow_inf = GAME_SETTINGS.get("tg_allow_infect", "1") == "1"
        l_mult, _, _, _ = get_active_events()

        # Паразит расходуется, только если в ивенте разрешено заражение
        armed = u["armed_parasite"]
        p_bonus = 0.0
        p_used_label = ""
        if allow_inf and armed in PARASITES and u[PARASITES[armed][1]] > 0:
            await db.add_parasite(uid, armed, -1)
            p_bonus = cfg_float(f"p_{armed}_bonus")
            p_used_label = f" | {PARASITES[armed][0]}"
            if u[PARASITES[armed][1]] - 1 <= 0:
                await db.update_user(uid, armed_parasite="none")

        mode_inf_bonus = {"easy": 0, "med": 5, "hard": 12}.get(mode_key, 0)
        total_inf_bonus = r_inf_bonus + mode_inf_bonus + p_bonus + u["pity_bonus"]

        # Модификаторы боя НЕ работают в ивентовом режиме!
        t1 = [build_player_unit(c, 1.0) for c in deck]
        t2 = await generate_tg_enemy_team(mode_key)
        if not t2:
            await origin.answer("❌ Для этой сложности Thanksgiving Event не выбраны враги!")
            return

        logs: List[str] = []
        apply_boosters_team(t1, u["full_name"], logs)
        apply_boosters_team(t2, f"Event {m_name}", logs)

        dmg_tracker: Dict[int, float] = {}
        infected_drops: List[Dict[str, Any]] = []
        delay = max(1.0, cfg_float("battle_delay_sec"))
        title = f"🦃 {m_name}{p_used_label}"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏳️ Сдаться", callback_data=f"btl:surr:{bid}")]])

        msg: Optional[Message] = None
        flood_until = 0.0
        init_text = render_battle_screen(title, u["full_name"], t1, m_name, t2, logs, 0, 0, enemy_side_label="Event")
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

            perform_combat_turn(t1, t2, True, logs, dmg_tracker, infected_drops, total_inf_bonus, l_mult, 0.0, allow_inf)
            if not any(x["hp"] > 0 for x in t2):
                winner = 1
                break

            perform_combat_turn(t2, t1, False, logs, dmg_tracker, infected_drops, total_inf_bonus, l_mult, 0.0, allow_inf)
            if not any(x["hp"] > 0 for x in t1):
                winner = 2
                break

            now_t = time.monotonic()
            min_edit_gap = 1.5 if edits_count == 0 else max(delay, 3.2)
            if msg is not None and now_t >= flood_until and (now_t - last_edit_ts) >= min_edit_gap:
                screen = render_battle_screen(title, u["full_name"], t1, m_name, t2, logs, rnd, len(infected_drops), enemy_side_label="Event")
                try:
                    await asyncio.wait_for(msg.edit_text(screen, reply_markup=kb), timeout=10.0)
                    last_edit_ts = time.monotonic()
                    edits_count += 1
                except TelegramRetryAfter as e:
                    flood_until = time.monotonic() + e.retry_after + 1.0
                except Exception:
                    pass

            await _battle_sleep(st, delay)

        if winner == 0:
            r1 = sum(x["hp"] for x in t1) / max(1, sum(x["max_hp"] for x in t1))
            r2 = sum(x["hp"] for x in t2) / max(1, sum(x["max_hp"] for x in t2))
            winner = 1 if r1 >= r2 else 2

        xp_rate = cfg_float("xp_per_damage")
        total_dmg = sum(dmg_tracker.values())
        lvl_ups: List[str] = []
        for iid, dmg in dmg_tracker.items():
            it = await db.get_inv_item(iid)
            if not it:
                continue
            nl, nx, ups = apply_card_xp(it["level"], it["xp"], round(dmg * xp_rate, 2))
            await db.update_inv_xp(iid, nl, nx)
            if ups > 0:
                lvl_ups.append(f"⭐ {esc(it['name'])} ➔ Lvl.{nl}!")

        fresh_u = await db.get_user(uid)
        tg_cur_id = cfg_int("tg_currency_id")
        cur_obj = await db.get_currency(tg_cur_id) if tg_cur_id else None
        cur_name = cur_obj["name"] if cur_obj else "🍗 Turkey Legs"

        if winner == 1:
            r_min = max(1, cfg_int(f"tg_rew_{mode_key}_min"))
            r_max = max(r_min, cfg_int(f"tg_rew_{mode_key}_max"))
            legs_won = random.randint(r_min, r_max)
            if tg_cur_id > 0:
                await db.add_user_currency(uid, tg_cur_id, legs_won)
            new_bal = await db.get_user_currency_bal(uid, tg_cur_id) if tg_cur_id > 0 else 0

            inf_lines: List[str] = []
            for d in infected_drops:
                sh = roll_shiny()
                _, sn = await db.give_card(uid, d["card_id"], is_shiny=sh, is_infected=1)
                sn_s = f" <b>[#{sn:04d}]</b>" if sn else ""
                sh_s = " ✨<b>SHINY!</b>" if sh else ""
                inf_lines.append(f"🦠 <b>{esc(d['name'])}</b>{sn_s}{sh_s} ({fmt_pct(d['chance'])}%)")

            await db.update_user(
                uid,
                wins=fresh_u["wins"] + 1,
                total_damage=round(fresh_u["total_damage"] + total_dmg, 1),
                infections_success=fresh_u["infections_success"] + len(infected_drops),
            )

            res_lines = [
                f"🦃🏆 <b>ПОБЕДА В {esc(tg_name.upper())}!</b> ({m_name})",
                "━━━━━━━━━━━━━━━━━━",
                f"🍗 Награда: <b>+{legs_won} {esc(cur_name)}</b> (Всего: <b>{new_bal}</b>)",
                f"💥 Урон: <b>{int(total_dmg)}</b> (+{round(total_dmg * xp_rate, 1)} XP картам)",
            ]
            if lvl_ups:
                res_lines.append("📈 Прокачка: " + ", ".join(lvl_ups[:3]))
            if inf_lines:
                res_lines.append("\n🦠💥 <b>ЗАРАЖЁННЫЕ ТРОФЕИ:</b>\n" + "\n".join(inf_lines))
        else:
            await db.update_user(uid, losses=fresh_u["losses"] + 1, total_damage=round(fresh_u["total_damage"] + total_dmg, 1))
            res_lines = [
                f"💀 <b>ПОРАЖЕНИЕ В ИВЕНТЕ ({m_name})</b>",
                "━━━━━━━━━━━━━━━━━━",
                f"🛡 Кубки в ивенте не снимаются!",
                f"💥 Урон: <b>{int(total_dmg)}</b> (карты получили опыт!)",
            ]
            if infected_drops:
                res_lines.append("<i>⚠️ Заражённые в бою враги сбежали, т.к. отряд проиграл.</i>")

        fin_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⚔️ Ещё бой", callback_data=f"tg:go:{mode_key}"), InlineKeyboardButton(text="🔙 К ивент-боям", callback_data="tg:hub")]])
        await _deliver_battle_final(msg, origin, "\n".join(res_lines), fin_kb, flood_until)
    except Exception as exc:
        logger.exception("Event battle error: %s", exc)
    finally:
        ACTIVE_BATTLES.pop(bid, None)
        USERS_IN_BATTLE.discard(uid)
