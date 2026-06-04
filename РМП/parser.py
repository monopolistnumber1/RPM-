import httpx
import asyncio
import logging
from typing import Optional
from dataclasses import dataclass, field
from config import ADS_API_TOKEN, ADS_API_USER

logger = logging.getLogger(__name__)

@dataclass
class AvitoListing:
    title: str
    price: str
    description: str
    url: str
    images: list[str] = field(default_factory=list)
    location: str = ""

ADS_API_BASE = "https://ads-api.ru/main/api"

# source: 1 = avito.ru
# category_id: 2 = Квартиры
# nedvigimost_type_id: 1 = Продам, 2 = Сдам

async def search_avito(
    city: str,
    deal_type: str,
    max_price: Optional[int],
) -> list[AvitoListing]:

    nedvigimost_type_id = "2" if deal_type == "rent" else "1"

    params = {
        "user": ADS_API_USER,
        "token": ADS_API_TOKEN,
        "source": "1",                        # 1 = avito.ru
        "category_id": "2",                   # 2 = Квартиры
        "nedvigimost_type": nedvigimost_type_id,
        "city": city,
        "withphone": "0",
        "limit": "50",
    }

    if max_price:
        params["price2"] = str(max_price)

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(ADS_API_BASE, params=params)

        logger.info(f"ads-api статус: {resp.status_code}")

        if resp.status_code != 200:
            logger.error(f"ads-api ошибка {resp.status_code}: {resp.text[:500]}")
            return []

        data = resp.json()

        # Ответ приходит в поле "data"
        items = []
        if isinstance(data, dict) and "data" in data:
            items = data["data"]
        elif isinstance(data, list):
            items = data

        if not items:
            logger.warning(f"ads-api вернул пустой список. Ответ: {str(data)[:300]}")
            return []

        listings = []
        for item in items[:10]:
            listing = _parse_item(item)
            if listing:
                listings.append(listing)

        return listings

    except httpx.TimeoutException:
        logger.error("Таймаут ads-api.ru")
        return []
    except Exception as e:
        logger.error(f"Ошибка ads-api.ru: {e}")
        return []


def _parse_item(item: dict) -> Optional[AvitoListing]:
    try:
        title = item.get("title") or "Без названия"

        # При тестовом доступе price всегда 0
        price_raw = item.get("price", 0)
        price_metric = item.get("price_metric", "")
        try:
            price_num = int(price_raw)
            if price_num == 0:
                price_str = "Цена не указана"
            else:
                price_str = f"{price_num:,} {price_metric}".replace(",", " ").strip()
        except (ValueError, TypeError):
            price_str = "Цена не указана"

        description = (item.get("description") or "").strip()[:700]

        url = item.get("url") or ""

        # Адрес: отдельно есть region, city1, address
        parts = filter(None, [
            item.get("city1") or item.get("city") or "",
            item.get("address") or "",
        ])
        location = ", ".join(parts)

        # Фото: images — массив объектов с полем imgurl
        images = []
        raw_images = item.get("images") or []
        if isinstance(raw_images, list):
            for img in raw_images:
                if isinstance(img, dict):
                    imgurl = img.get("imgurl") or img.get("url") or ""
                    if imgurl.startswith("http"):
                        images.append(imgurl)
                elif isinstance(img, str) and img.startswith("http"):
                    images.append(img)

        return AvitoListing(
            title=title,
            price=price_str,
            description=description,
            url=url,
            images=images[:8],
            location=location,
        )

    except Exception as e:
        logger.warning(f"Ошибка парсинга item: {e}")
        return None