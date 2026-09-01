import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    private_key_path = os.environ.get("REVX_PRIVATE_KEY_PATH", "./private.pem")
    api_key = os.environ.get("REVX_API_KEY", "")

    symbol = os.environ.get("TRADEBOT_SYMBOL", "SOL-EUR")
    max_position_eur = float(os.environ.get("TRADEBOT_MAX_POSITION_EUR", "100"))

    sma_short = int(os.environ.get("TRADEBOT_SMA_SHORT", "10"))
    sma_long = int(os.environ.get("TRADEBOT_SMA_LONG", "50"))
    candle_interval = os.environ.get("TRADEBOT_CANDLE_INTERVAL", "1h")

    confirm_live = os.environ.get("TRADEBOT_CONFIRM_LIVE", "no").strip().lower() == "yes"

    base_url = "https://revx.revolut.com/api"

    @classmethod
    def validate_for_live(cls):
        missing = []
        if not cls.api_key:
            missing.append("REVX_API_KEY")
        if not os.path.isfile(cls.private_key_path):
            missing.append(f"REVX_PRIVATE_KEY_PATH ({cls.private_key_path} introuvable)")
        if not cls.confirm_live:
            missing.append("TRADEBOT_CONFIRM_LIVE=yes")
        if missing:
            raise RuntimeError(
                "Configuration incomplète pour le mode réel: " + ", ".join(missing)
            )
