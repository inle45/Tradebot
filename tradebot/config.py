import os

from dotenv import load_dotenv

load_dotenv()


def _flag(name, default="yes"):
    return os.environ.get(name, default).strip().lower() == "yes"


class Config:
    private_key_path = os.environ.get("REVX_PRIVATE_KEY_PATH", "./private.pem")
    api_key = os.environ.get("REVX_API_KEY", "")

    symbol = os.environ.get("TRADEBOT_SYMBOL", "SOL/EUR")
    max_position_eur = float(os.environ.get("TRADEBOT_MAX_POSITION_EUR", "100"))

    sma_short = int(os.environ.get("TRADEBOT_SMA_SHORT", "10"))
    sma_long = int(os.environ.get("TRADEBOT_SMA_LONG", "50"))
    # Intervalle des bougies en minutes. Valeurs acceptées par l'API Revolut X:
    # 1, 5, 15, 30, 60, 240, 1440, 2880, 5760, 10080, 20160, 40320
    candle_interval = os.environ.get("TRADEBOT_CANDLE_INTERVAL", "60")

    # Filtres et protections
    use_trend_filter = _flag("TRADEBOT_TREND_FILTER")
    trend_period = int(os.environ.get("TRADEBOT_TREND_PERIOD", "200"))
    use_volatility_filter = _flag("TRADEBOT_VOLATILITY_FILTER")
    min_atr_pct = float(os.environ.get("TRADEBOT_MIN_ATR_PCT", "0.15"))
    stop_loss_pct = float(os.environ.get("TRADEBOT_STOP_LOSS_PCT", "5"))
    trailing_stop_pct = float(os.environ.get("TRADEBOT_TRAILING_STOP_PCT", "0"))

    # Ordres limites post-only : 0% de frais au lieu de 0,09%
    use_limit_orders = _flag("TRADEBOT_LIMIT_ORDERS")

    confirm_live = os.environ.get("TRADEBOT_CONFIRM_LIVE", "no").strip().lower() == "yes"

    base_url = "https://revx.revolut.com/api"

    @classmethod
    def strategy_config(cls):
        from tradebot.strategy import StrategyConfig

        return StrategyConfig(
            sma_short=cls.sma_short,
            sma_long=cls.sma_long,
            use_trend_filter=cls.use_trend_filter,
            trend_period=cls.trend_period,
            use_volatility_filter=cls.use_volatility_filter,
            min_atr_pct=cls.min_atr_pct,
            stop_loss_pct=cls.stop_loss_pct,
            trailing_stop_pct=cls.trailing_stop_pct,
        )

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
