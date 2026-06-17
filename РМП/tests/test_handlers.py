import asyncio
import handlers
from handlers import SearchStates


def test_kb_deal_type_has_two_buttons():
    kb = handlers.kb_deal_type()
    row = kb.inline_keyboard[0]
    assert len(row) == 2
    assert row[0].text == "Аренда"
    assert row[0].callback_data == "deal_rent"
    assert row[1].text == "Покупка"
    assert row[1].callback_data == "deal_buy"


def test_kb_skip_price_has_skip_button():
    kb = handlers.kb_skip_price()
    btn = kb.inline_keyboard[0][0]
    assert btn.text == "Пропустить"
    assert btn.callback_data == "price_skip"


def test_kb_listing_callbacks_include_index():
    kb = handlers.kb_listing(3, 10, "https://example.com")
    row = kb.inline_keyboard[0]
    assert row[0].callback_data == "like_3"
    assert row[1].callback_data == "dislike_3"


class FakeMessage:
    def __init__(self):
        self.calls = []

    async def answer(self, text, parse_mode=None, **kwargs):
        self.calls.append((text, parse_mode, kwargs))


class FakeState:
    def __init__(self):
        self.data = {}
        self.state_value = None

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def set_state(self, state):
        self.state_value = state


def test_handle_price_rejects_negative_value():
    msg = FakeMessage()
    msg.from_user = type("U", (), {"id": 123})()
    msg.text = "-50000"
    state = FakeState()

    asyncio.run(handlers.handle_price(msg, state))

    assert len(msg.calls) == 1
    text, parse_mode, kwargs = msg.calls[0]
    assert "только положительным числом" in text
    assert parse_mode == "HTML"
    assert "reply_markup" in kwargs
    assert state.data == {}


def test_handle_city_rejects_digits():
    msg = FakeMessage()
    msg.from_user = type("U", (), {"id": 321})()
    msg.text = "М0сква"
    state = FakeState()

    asyncio.run(handlers.handle_city(msg, state))

    assert len(msg.calls) == 1
    text, parse_mode, _ = msg.calls[0]
    assert "Введите корректное название города" in text
    assert parse_mode == "HTML"
    assert state.data == {}
