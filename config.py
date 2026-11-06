"""Configuration for the controller.
"""
import os

from dotenv import load_dotenv

load_dotenv()

SIM_BASE_URL = os.getenv("SIM_BASE_URL", "http://localhost:8700")
TICK_MINUTES = int(os.getenv("TICK_MINUTES", "15"))
DB_PATH = os.getenv("DB_PATH", "./controller.db")
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "30"))
IDLE_SLEEP_SECONDS = float(os.getenv("IDLE_SLEEP_SECONDS", "1.0"))