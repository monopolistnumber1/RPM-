import json
import time
import tracemalloc
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parser import _parse_item


def make_item(i: int) -> dict:
    return {
        "title": f"Квартира {i}",
        "price": str(35000 + i),
        "price_metric": "руб./мес.",
        "description": "Описание " * 20,
        "url": f"https://example.com/{i}",
        "city1": "Москва",
        "address": f"ул. Тестовая, {i}",
        "images": [{"imgurl": "https://img/1.jpg"}, {"imgurl": "https://img/2.jpg"}],
    }


def run_case(n: int) -> dict:
    data = [make_item(i) for i in range(n)]

    tracemalloc.start()
    t0 = time.perf_counter()
    out = [_parse_item(x) for x in data]
    dt = time.perf_counter() - t0
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert len(out) == n

    return {
        "load": n,
        "time_sec": dt,
        "throughput_items_sec": (n / dt) if dt > 0 else 0,
        "peak_memory_mb": peak / (1024 * 1024),
    }


if __name__ == "__main__":
    loads = [10, 100, 1000, 5000, 10000]
    rows = [run_case(n) for n in loads]
    print(json.dumps(rows, ensure_ascii=False, indent=2))
