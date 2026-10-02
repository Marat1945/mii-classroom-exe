"""Тести ніколи не пропонують «чистий старт» і не чіпають реальні дані вчителя."""
import os

os.environ.setdefault("POMICHNYK_NO_OFFERS", "1")
