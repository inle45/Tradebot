"""Stratégie de trading : croisement de moyennes mobiles, avec filtres.

La détection du croisement est *sans état* : elle est recalculée à partir des
données à chaque appel. Le bot peut donc redémarrer sans rien oublier.
"""

from dataclasses import dataclass, field
from enum import Enum


class Signal(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class Position:
    """Position ouverte, suivie par le moteur (pas par la stratégie)."""

    entry_price: float
    size: float
    peak_price: float = 0.0

    def update_peak(self, price):
        self.peak_price = max(self.peak_price, price, self.entry_price)


@dataclass
class Decision:
    signal: Signal
    reason: str
    indicators: dict = field(default_factory=dict)


@dataclass
class StrategyConfig:
    sma_short: int = 10
    sma_long: int = 50

    # Filtre de tendance de fond : n'acheter que si le prix est au-dessus de
    # cette moyenne longue. Supprime la plupart des faux signaux.
    use_trend_filter: bool = True
    trend_period: int = 200

    # Filtre de volatilité : ne pas trader quand le marché est trop plat,
    # là où le croisement de moyennes se fait déchiqueter.
    use_volatility_filter: bool = True
    atr_period: int = 14
    min_atr_pct: float = 0.15  # en % du prix

    # Sorties de protection (0 = désactivé)
    stop_loss_pct: float = 5.0
    trailing_stop_pct: float = 0.0

    @property
    def warmup(self):
        """Nombre de bougies nécessaires avant de pouvoir décider."""
        needed = [self.sma_long + 1, self.atr_period + 1]
        if self.use_trend_filter:
            needed.append(self.trend_period)
        return max(needed)


def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def atr(candles, period):
    """Average True Range : mesure de la volatilité récente."""
    if len(candles) < period + 1:
        return None
    true_ranges = []
    for previous, current in zip(candles[-period - 1 : -1], candles[-period:]):
        high, low = float(current["high"]), float(current["low"])
        previous_close = float(previous["close"])
        true_ranges.append(
            max(high - low, abs(high - previous_close), abs(low - previous_close))
        )
    return sum(true_ranges) / len(true_ranges)


class SmaCrossoverStrategy:
    def __init__(self, config=None):
        self.config = config or StrategyConfig()
        if self.config.sma_short >= self.config.sma_long:
            raise ValueError("sma_short doit être inférieur à sma_long")

    def _crossover(self, closes):
        """Retourne 'up', 'down' ou None en comparant l'état actuel au précédent."""
        now_short = sma(closes, self.config.sma_short)
        now_long = sma(closes, self.config.sma_long)
        before_short = sma(closes[:-1], self.config.sma_short)
        before_long = sma(closes[:-1], self.config.sma_long)
        if None in (now_short, now_long, before_short, before_long):
            return None
        if before_short <= before_long and now_short > now_long:
            return "up"
        if before_short >= before_long and now_short < now_long:
            return "down"
        return None

    def decide(self, candles, position=None):
        cfg = self.config
        closes = [float(c["close"]) for c in candles]
        price = closes[-1] if closes else 0.0

        if len(candles) < cfg.warmup:
            return Decision(
                Signal.HOLD,
                f"Pas encore assez de données ({len(candles)}/{cfg.warmup} bougies)",
            )

        short = sma(closes, cfg.sma_short)
        long = sma(closes, cfg.sma_long)
        trend = sma(closes, cfg.trend_period) if cfg.use_trend_filter else None
        current_atr = atr(candles, cfg.atr_period)
        atr_pct = (current_atr / price * 100) if current_atr and price else 0.0

        indicators = {
            "price": price,
            "sma_short": short,
            "sma_long": long,
            "trend": trend,
            "atr_pct": atr_pct,
        }

        crossover = self._crossover(closes)

        # --- Déjà en position : on cherche une raison de sortir ---
        if position is not None:
            position.update_peak(price)

            if cfg.stop_loss_pct > 0:
                floor = position.entry_price * (1 - cfg.stop_loss_pct / 100)
                if price <= floor:
                    return Decision(
                        Signal.SELL,
                        f"Stop-loss déclenché (-{cfg.stop_loss_pct}% depuis l'achat)",
                        indicators,
                    )

            if cfg.trailing_stop_pct > 0:
                floor = position.peak_price * (1 - cfg.trailing_stop_pct / 100)
                if price <= floor:
                    return Decision(
                        Signal.SELL,
                        f"Trailing stop déclenché (-{cfg.trailing_stop_pct}% depuis le plus haut)",
                        indicators,
                    )

            if crossover == "down":
                return Decision(Signal.SELL, "Croisement baissier des moyennes", indicators)

            return Decision(Signal.HOLD, "Position conservée", indicators)

        # --- Hors position : on cherche une raison d'entrer ---
        if crossover != "up":
            return Decision(Signal.HOLD, "Pas de signal d'entrée", indicators)

        if cfg.use_trend_filter and trend is not None and price < trend:
            return Decision(
                Signal.HOLD,
                "Signal ignoré : prix sous la tendance de fond",
                indicators,
            )

        if cfg.use_volatility_filter and atr_pct < cfg.min_atr_pct:
            return Decision(
                Signal.HOLD,
                f"Signal ignoré : marché trop plat ({atr_pct:.2f}% de volatilité)",
                indicators,
            )

        return Decision(Signal.BUY, "Croisement haussier des moyennes", indicators)
