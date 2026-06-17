import asyncio
import parser


def test_parse_item_happy_path():
    item = {
        "title": "1-к квартира",
        "price": "45000",
        "price_metric": "руб./мес.",
        "description": "Отличная квартира рядом с метро",
        "url": "https://example.com/listing/1",
        "city1": "Москва",
        "address": "ул. Пушкина, 1",
        "images": [
            {"imgurl": "https://img/1.jpg"},
            {"imgurl": "https://img/2.jpg"}
        ],
    }

    listing = parser._parse_item(item)

    assert listing is not None
    assert listing.title == "1-к квартира"
    assert listing.price == "45 000 руб./мес."
    assert listing.url == "https://example.com/listing/1"
    assert listing.location == "Москва, ул. Пушкина, 1"
    assert len(listing.images) == 2


def test_parse_item_missing_fields_defaults():
    listing = parser._parse_item({})

    assert listing is not None
    assert listing.title == "Без названия"
    assert listing.price == "Цена не указана"
    assert listing.url == ""
    assert listing.location == ""
    assert listing.images == []


class _DummyResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


class _DummyClient:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None):
        return self._response


def test_search_avito_success:
    payload = {
        "data": [
            {
                "title": "Тест",
                "price": "12345",
                "price_metric": "руб.",
                "description": "desc",
                "url": "https://example.com/ok",
                "city1": "Казань",
                "address": "центр",
                "images": [{"imgurl": "https://img/1.jpg"}],
            }
        ]
    }

    def _factory(*args, **kwargs):
        return _DummyClient(_DummyResponse(200, payload))

    monkeypatch.setattr(parser.httpx, "AsyncClient", _factory)

    result = asyncio.run(parser.search_avito("Казань", "rent", 50000))

    assert len(result) == 1
    assert result[0].title == "Тест"
    assert result[0].url == "https://example.com/ok"


def test_search_avito_non_200(monkeypatch):
    def _factory(*args, **kwargs):
        return _DummyClient(_DummyResponse(500, {"error": "server"}))

    monkeypatch.setattr(parser.httpx, "AsyncClient", _factory)

    result = asyncio.run(parser.search_avito("Москва", "buy", None))
    assert result == []
