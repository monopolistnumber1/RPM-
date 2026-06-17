import asyncio
import logging
import re
from aiogram import Router, Bot, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardButton,
    InlineKeyboardMarkup, InputMediaPhoto
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import CommandStart
from parser import search_avito, AvitoListing

router = Router()
logger = logging.getLogger(__name__)

# -- FSM ----------------------------------------------------------------------

class SearchStates(StatesGroup):
    waiting_city = State()
    waiting_deal_type = State()
    waiting_price = State()
    waiting_custom_filters = State()
    browsing = State()

# -- Хранилище ----------------------------------------------------------------

user_sessions: dict[int, dict] = {}
user_action_count: dict[int, int] = {}

async def maybe_send_watermark(message: Message, uid: int):

    user_action_count[uid] = user_action_count.get(uid, 0) + 1
    if user_action_count[uid] % 3 == 0 and WATERMARK.strip():
        await message.answer(WATERMARK, parse_mode="HTML")

# -- Клавиатуры ---------------------------------------------------------------

def kb_deal_type() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Аренда", callback_data="deal_rent"),
            InlineKeyboardButton(text="Покупка", callback_data="deal_buy"),
        ]
    ])

def kb_skip_price() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пропустить", callback_data="price_skip")]
    ])

def kb_listing(index: int, total: int, url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Интересно!", callback_data=f"like_{index}"),
            InlineKeyboardButton(text="Следующее", callback_data=f"dislike_{index}"),
        ]
    ])

def kb_new_search() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Новый поиск", callback_data="new_search")]
    ])


def default_custom_filters() -> dict:
    return {
        "anti_agency": True,
        "anti_suspicious": True,
        "min_photos_3": False,
        "no_edge_floor": False,
        "balcony_only": False,
    }


def kb_custom_filters(filters: dict) -> InlineKeyboardMarkup:
    def mark(flag: bool) -> str:
        return "ON" if flag else "OFF"

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Анти-агент: {mark(filters['anti_agency'])}", callback_data="cf_toggle_anti_agency")],
        [InlineKeyboardButton(text=f"Анти-подозрительные: {mark(filters['anti_suspicious'])}", callback_data="cf_toggle_anti_suspicious")],
        [InlineKeyboardButton(text=f"Мин. 3 фото: {mark(filters['min_photos_3'])}", callback_data="cf_toggle_min_photos_3")],
        [InlineKeyboardButton(text=f"Не 1/последний этаж: {mark(filters['no_edge_floor'])}", callback_data="cf_toggle_no_edge_floor")],
        [InlineKeyboardButton(text=f"Только с балконом: {mark(filters['balcony_only'])}", callback_data="cf_toggle_balcony_only")],
        [InlineKeyboardButton(text="Применить фильтры и искать", callback_data="cf_apply")],
        [InlineKeyboardButton(text="Пропустить фильтры", callback_data="cf_skip")],
    ])

# -- Handlers -----------------------------------------------------------------

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    user_action_count[uid] = 0

    await message.answer(
        "Привет! Я помогу найти квартиру на Авито.\n\n"
        "Введите название города (например: <b>Москва</b>, <b>Казань</b>, <b>Краснодар</b>):\n\n"
        + WATERMARK,
        parse_mode="HTML"
    )
    await state.set_state(SearchStates.waiting_city)


@router.message(SearchStates.waiting_city)
async def handle_city(message: Message, state: FSMContext):
    uid = message.from_user.id
    city = message.text.strip()
    city_normalized = city.replace("–", "-").replace("—", "-").replace("‑", "-")

    # Город должен состоять из букв, пробелов и дефисов (без цифр)
    if not re.fullmatch(r"[A-Za-zА-Яа-яЁё\s-]{2,}", city_normalized):
        await message.answer(
            "Введите корректное название города буквами.\n"
            "Цифры и специальные символы использовать нельзя.\n\n"
            "Пример: <b>Москва</b>, <b>Ростов-на-Дону</b>",
            parse_mode="HTML"
        )
        return

    await state.update_data(city=city_normalized)
    await maybe_send_watermark(message, uid)

    await message.answer(
        "Что вас интересует?",
        reply_markup=kb_deal_type()
    )
    await state.set_state(SearchStates.waiting_deal_type)


@router.callback_query(F.data.in_({"deal_rent", "deal_buy"}), SearchStates.waiting_deal_type)
async def handle_deal_type(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    deal = "rent" if callback.data == "deal_rent" else "buy"
    deal_label = "аренду" if deal == "rent" else "покупку"
    await state.update_data(deal_type=deal)
    await maybe_send_watermark(callback.message, uid)

    await callback.message.edit_text(
        f"Ищем квартиры на <b>{deal_label}</b>.\n\n"
        "Укажите максимальную цену (в рублях, только цифры):\n"
        "Например: <code>50000</code> или нажмите «Пропустить»",
        parse_mode="HTML",
        reply_markup=kb_skip_price()
    )
    await state.set_state(SearchStates.waiting_price)


@router.message(SearchStates.waiting_price)
async def handle_price(message: Message, state: FSMContext):
    uid = message.from_user.id
    text = message.text.strip().replace(" ", "").replace(",", "")

    if not text.isdigit():
        await message.answer(
            "Введите цену только положительным числом (без букв и минуса),\n"
            "например: <code>45000</code>",
            parse_mode="HTML",
            reply_markup=kb_skip_price()
        )
        return

    max_price = int(text)
    await state.update_data(max_price=max_price)
    await maybe_send_watermark(message, uid)
    await ask_custom_filters(message, state)


@router.callback_query(F.data == "price_skip", SearchStates.waiting_price)
async def handle_price_skip(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    await state.update_data(max_price=None)
    await callback.message.delete()
    await maybe_send_watermark(callback.message, uid)
    await ask_custom_filters(callback.message, state)


async def ask_custom_filters(message: Message, state: FSMContext):
    data = await state.get_data()
    filters = data.get("custom_filters") or default_custom_filters()
    await state.update_data(custom_filters=filters)
    await message.answer(
        "Дополнительные фильтры (не как на Авито):\n"
        "Можно включить/выключить и потом запустить поиск.\n\n"
        "Расшифровка:\n"
        "• Анти-агент: скрывает посредников и объявления с комиссией.\n"
        "• Анти-подозрительные: скрывает рискованные формулировки (предоплата, без просмотра и т.п.).\n"
        "• Мин. 3 фото: оставляет варианты минимум с 3 фото.\n"
        "• Не 1/последний этаж: убирает первый и последний этаж.\n"
        "• Только с балконом: оставляет объявления, где есть балкон/лоджия.",
        reply_markup=kb_custom_filters(filters)
    )
    await state.set_state(SearchStates.waiting_custom_filters)


@router.callback_query(F.data.startswith("cf_toggle_"), SearchStates.waiting_custom_filters)
async def handle_custom_filter_toggle(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    filters = data.get("custom_filters") or default_custom_filters()
    key = callback.data.replace("cf_toggle_", "", 1)

    if key in filters:
        filters[key] = not filters[key]
        await state.update_data(custom_filters=filters)

    await callback.answer("Фильтр обновлен")
    await callback.message.edit_reply_markup(reply_markup=kb_custom_filters(filters))


@router.callback_query(F.data == "cf_skip", SearchStates.waiting_custom_filters)
async def handle_custom_filter_skip(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await start_search(callback.message, state, user_id=callback.from_user.id)


@router.callback_query(F.data == "cf_apply", SearchStates.waiting_custom_filters)
async def handle_custom_filter_apply(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await start_search(callback.message, state, user_id=callback.from_user.id)


async def start_search(message: Message, state: FSMContext, user_id: int = None):
    data = await state.get_data()
    city = data["city"]
    deal_type = data["deal_type"]
    max_price = data.get("max_price")
    custom_filters = data.get("custom_filters") or default_custom_filters()
    uid = user_id or message.chat.id

    deal_label = "аренду" if deal_type == "rent" else "покупку"
    price_text = f"до {max_price:,} р.".replace(",", " ") if max_price else "без ограничений"

    search_msg = await message.answer(
        f"Ищу квартиры в <b>{city}</b> на {deal_label} ({price_text})...",
        parse_mode="HTML"
    )

    try:
        listings = await search_avito(city, deal_type, max_price)
    except Exception as e:
        logger.error(f"Ошибка поиска: {e}")
        listings = []

    raw_listings = listings
    filtered_count = 0
    if listings:
        raw_count = len(listings)
        listings = apply_custom_filters(listings, custom_filters)
        filtered_count = raw_count - len(listings)

        if raw_count > 0 and len(listings) == 0:
            listings = raw_listings
            filtered_count = raw_count

    await search_msg.delete()

    if not listings:
        await message.answer(
            "Ничего не найдено по вашему запросу.\n"
            "Возможно, город указан с ошибкой или для него нет объявлений.\n\n"
            "Введите название города заново:"
        )
        await state.clear()
        await state.set_state(SearchStates.waiting_city)
        return

    if filtered_count > 0:
        if filtered_count == len(listings):
            await message.answer(
                "Кастомные фильтры скрыли все объявления.\n"
                "Показываю результаты без кастомных фильтров."
            )
        else:
            await message.answer(
                f"Кастомные фильтры скрыли {filtered_count} объявл.\n"
                f"Показываю {len(listings)} подходящих вариантов."
            )

    user_sessions[uid] = {
        "listings": listings,
        "index": 0,
        "city": city,
        "deal_type": deal_type,
        "max_price": max_price,
        "custom_filters": custom_filters,
    }

    await state.set_state(SearchStates.browsing)
    await send_listing(message, uid, 0, listings)


def apply_custom_filters(listings: list[AvitoListing], filters: dict) -> list[AvitoListing]:
    result: list[AvitoListing] = []

    agency_keywords = {
        "агент", "риелтор", "риэлтор", "агентство", "посредник", "комиссия", "услуги агента",
        "broker", "realtor",
    }
    suspicious_keywords = {
        "предоплата", "только whatsapp", "только вацап", "без просмотра", "срочно перевести",
        "залог на карту", "оплата вперед",
    }
    balcony_keywords = {"балкон", "лоджия"}

    for listing in listings:
        text = f"{listing.title} {listing.description}".lower()

        if filters.get("anti_agency") and any(k in text for k in agency_keywords):
            continue

        if filters.get("anti_suspicious") and any(k in text for k in suspicious_keywords):
            continue

        if filters.get("min_photos_3") and len(listing.images) < 3:
            continue

        if filters.get("balcony_only") and not any(k in text for k in balcony_keywords):
            continue

        if filters.get("no_edge_floor"):
            # Ищем шаблон "этаж/этажей", например "3/9 эт."
            m = re.search(r"(\\d+)\\s*/\\s*(\\d+)\\s*эт", text)
            if m:
                floor = int(m.group(1))
                total = int(m.group(2))
                if floor == 1 or floor == total:
                    continue

        result.append(listing)

    return result


async def send_listing(message: Message, uid: int, index: int, listings: list[AvitoListing]):
    if index >= len(listings):
        await message.answer(
            "Все объявления просмотрены!\n"
            "Начните новый поиск или скорректируйте параметры.",
            reply_markup=kb_new_search()
        )
        return

    listing = listings[index]
    remaining = len(listings) - (index + 1)

    caption = f"<b>{listing.title}</b>\n\n"

    if listing.location:
        caption += f"Адрес: {listing.location}\n\n"

    if listing.description:
        desc = listing.description[:600]
        if len(listing.description) > 600:
            desc += "..."
        caption += f"{desc}\n\n"

    caption += f"Цена: <b>{listing.price}</b>"
    caption += f"\n\nОбъявление {index + 1} из {len(listings)}"
    caption += f"\nОсталось после этого: {remaining}"

    kb = kb_listing(index, len(listings), listing.url)

    try:
        if listing.images:
            if len(listing.images) == 1:
                await message.answer_photo(
                    photo=listing.images[0],
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=kb
                )
            else:
                media_group = []
                for i, img_url in enumerate(listing.images[:9]):
                    if i == 0:
                        media_group.append(InputMediaPhoto(media=img_url, caption=caption, parse_mode="HTML"))
                    else:
                        media_group.append(InputMediaPhoto(media=img_url))

                await message.answer_media_group(media=media_group)
                await message.answer(
                    f"Цена: <b>{listing.price}</b> | Объявление {index + 1}/{len(listings)} | Осталось: {remaining}",
                    parse_mode="HTML",
                    reply_markup=kb
                )
                return
        else:
            await message.answer(caption, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        logger.warning(f"Ошибка отправки фото: {e}")
        await message.answer(caption, parse_mode="HTML", reply_markup=kb)


# -- Лайк / Дизлайк ----------------------------------------------------------

@router.callback_query(F.data.startswith("like_"))
async def handle_like(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    session = user_sessions.get(uid)

    if not session:
        await callback.answer("Сессия истекла. Начните новый поиск /start", show_alert=True)
        return

    index = int(callback.data.split("_")[1])
    listings = session["listings"]

    if index >= len(listings):
        await callback.answer("Объявление не найдено", show_alert=True)
        return

    listing = listings[index]
    remaining = len(listings) - (index + 1)
    await callback.answer("Открываю объявление!")

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await maybe_send_watermark(callback.message, uid)

    await callback.message.answer(
        f"Ссылка на объявление:\n{listing.url}\n\n"
        f"<b>{listing.title}</b>\nЦена: {listing.price}\nОсталось после этого: {remaining}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Следующее объявление", callback_data=f"dislike_{index}")],
            [InlineKeyboardButton(text="Новый поиск", callback_data="new_search")],
        ])
    )


@router.callback_query(F.data.startswith("dislike_"))
async def handle_dislike(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    session = user_sessions.get(uid)

    if not session:
        await callback.answer("Сессия истекла. Начните новый поиск /start", show_alert=True)
        return

    current_index = int(callback.data.split("_")[1])
    next_index = current_index + 1
    session["index"] = next_index
    listings = session["listings"]

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await callback.answer("Загружаю следующее...")
    await maybe_send_watermark(callback.message, uid)
    await send_listing(callback.message, uid, next_index, listings)


@router.callback_query(F.data == "new_search")
async def handle_new_search(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    uid = callback.from_user.id
    if uid in user_sessions:
        del user_sessions[uid]

    await callback.answer()
    await callback.message.answer(
        "Начинаем новый поиск!\n\n"
        "Введите название города:",
    )
    await state.set_state(SearchStates.waiting_city)
