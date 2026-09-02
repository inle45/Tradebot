"""Bibliothèque de stratégies, toutes derrière la même interface.

Chaque stratégie expose `decide(candles, position) -> Decision` et une propriété
`warmup`, ce qui permet de les passer toutes dans le même backtest et la même
validation walk-forward — donc de les comparer équitablement.
"""

from dataclasses import dataclass

from tradebot.strategy import Decision, Position, Signal, sma

# --------------------------------------------------------------------------
# Indicateurs
# --------------------------------------------------------------------------


def ema(values, period):
    """Moyenne mobile exponentielle : donne plus de poids aux prix récents."""
    if len(values) < period:
        return None
    multiplier = 2 / (period + 1)
    result = sum(values[:period]) / period
    for value in values[period:]:
        result = (value - result) * multiplier + result
    return result


def rsi(closes, period=14):
    """Relative Strength Index : 0-100. Sous 30 = survendu, au-dessus de 70 =
    suracheté."""
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for previous, current in zip(closes[-period - 1 : -1], closes[-period:]):
        change = current - previous
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    average_gain = sum(gains) / period
    average_loss = sum(losses) / period
    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0
    strength = average_gain / average_loss
    return 100 - (100 / (1 + strength))


def macd(closes, fast=12, slow=26, signal_period=9):
    """Retourne (ligne MACD, ligne de signal). Le croisement des deux sert de
    déclencheur."""
    if len(closes) < slow + signal_period:
        return None, None
    macd_series = []
    for i in range(slow, len(closes) + 1):
        window = closes[:i]
        fast_ema, slow_ema = ema(window, fast), ema(window, slow)
        if fast_ema is None or slow_ema is None:
            continue
        macd_series.append(fast_ema - slow_ema)
    if len(macd_series) < signal_period:
        return None, None
    return macd_series[-1], ema(macd_series, signal_period)


def bollinger(closes, period=20, deviations=2.0):
    """Bandes de Bollinger : moyenne ± n écarts-types."""
    if len(closes) < period:
        return None, None, None
    window = closes[-period:]
    middle = sum(window) / period
    variance = sum((value - middle) ** 2 for value in window) / period
    spread = variance**0.5 * deviations
    return middle - spread, middle, middle + spread


def donchian(candles, period=20):
    """Canal de Donchian : plus haut et plus bas des N périodes précédentes
    (la bougie courante exclue, sinon le signal se déclenche sur lui-même)."""
    if len(candles) < period + 1:
        return None, None
    window = candles[-period - 1 : -1]
    return (
        max(float(c["high"]) for c in window),
        min(float(c["low"]) for c in window),
    )


# --------------------------------------------------------------------------
# Stratégies
# --------------------------------------------------------------------------


class BaseStrategy:
    name = "base"

    @property
    def warmup(self):
        raise NotImplementedError

    def decide(self, candles, position=None):
        raise NotImplementedError

    def _exit_checks(self, price, position, indicators):
        """Stop-loss et trailing stop, communs à toutes les stratégies."""
        if self.stop_loss_pct > 0:
            floor = position.entry_price * (1 - self.stop_loss_pct / 100)
            if price <= floor:
                return Decision(Signal.SELL, "Stop-loss déclenché", indicators)
        if self.trailing_stop_pct > 0:
            floor = position.peak_price * (1 - self.trailing_stop_pct / 100)
            if price <= floor:
                return Decision(Signal.SELL, "Trailing stop déclenché", indicators)
        return None


@dataclass
class RsiStrategy(BaseStrategy):
    """Retour à la moyenne : on achète la peur, on vend l'euphorie."""

    period: int = 14
    oversold: float = 30.0
    overbought: float = 70.0
    stop_loss_pct: float = 5.0
    trailing_stop_pct: float = 0.0
    name: str = "RSI"

    @property
    def warmup(self):
        return self.period + 2

    def decide(self, candles, position=None):
        closes = [float(c["close"]) for c in candles]
        price = closes[-1]
        if len(closes) < self.warmup:
            return Decision(Signal.HOLD, "Pas assez de données")

        value = rsi(closes, self.period)
        indicators = {"price": price, "rsi": value}

        if position is not None:
            position.update_peak(price)
            forced = self._exit_checks(price, position, indicators)
            if forced:
                return forced
            if value >= self.overbought:
                return Decision(Signal.SELL, f"RSI suracheté ({value:.0f})", indicators)
            return Decision(Signal.HOLD, "Position conservée", indicators)

        if value <= self.oversold:
            return Decision(Signal.BUY, f"RSI survendu ({value:.0f})", indicators)
        return Decision(Signal.HOLD, f"RSI neutre ({value:.0f})", indicators)


@dataclass
class MacdStrategy(BaseStrategy):
    """Suivi de tendance sur le croisement MACD / ligne de signal."""

    fast: int = 12
    slow: int = 26
    signal_period: int = 9
    stop_loss_pct: float = 5.0
    trailing_stop_pct: float = 0.0
    name: str = "MACD"

    @property
    def warmup(self):
        return self.slow + self.signal_period + 2

    def decide(self, candles, position=None):
        closes = [float(c["close"]) for c in candles]
        price = closes[-1]
        if len(closes) < self.warmup:
            return Decision(Signal.HOLD, "Pas assez de données")

        line, signal_line = macd(closes, self.fast, self.slow, self.signal_period)
        previous_line, previous_signal = macd(
            closes[:-1], self.fast, self.slow, self.signal_period
        )
        if None in (line, signal_line, previous_line, previous_signal):
            return Decision(Signal.HOLD, "Pas assez de données")

        indicators = {"price": price, "macd": line, "macd_signal": signal_line}
        crossed_up = previous_line <= previous_signal and line > signal_line
        crossed_down = previous_line >= previous_signal and line < signal_line

        if position is not None:
            position.update_peak(price)
            forced = self._exit_checks(price, position, indicators)
            if forced:
                return forced
            if crossed_down:
                return Decision(Signal.SELL, "MACD croise vers le bas", indicators)
            return Decision(Signal.HOLD, "Position conservée", indicators)

        if crossed_up:
            return Decision(Signal.BUY, "MACD croise vers le haut", indicators)
        return Decision(Signal.HOLD, "Pas de croisement MACD", indicators)


@dataclass
class BollingerStrategy(BaseStrategy):
    """Retour à la moyenne : achat quand le prix sort sous la bande basse."""

    period: int = 20
    deviations: float = 2.0
    stop_loss_pct: float = 5.0
    trailing_stop_pct: float = 0.0
    name: str = "Bollinger"

    @property
    def warmup(self):
        return self.period + 2

    def decide(self, candles, position=None):
        closes = [float(c["close"]) for c in candles]
        price = closes[-1]
        if len(closes) < self.warmup:
            return Decision(Signal.HOLD, "Pas assez de données")

        lower, middle, upper = bollinger(closes, self.period, self.deviations)
        indicators = {"price": price, "bb_lower": lower, "bb_mid": middle, "bb_upper": upper}

        if position is not None:
            position.update_peak(price)
            forced = self._exit_checks(price, position, indicators)
            if forced:
                return forced
            if price >= middle:
                return Decision(Signal.SELL, "Retour à la moyenne atteint", indicators)
            return Decision(Signal.HOLD, "Position conservée", indicators)

        if price <= lower:
            return Decision(Signal.BUY, "Prix sous la bande basse", indicators)
        return Decision(Signal.HOLD, "Prix dans les bandes", indicators)


@dataclass
class DonchianStrategy(BaseStrategy):
    """Cassure de canal : la méthode « turtle », le suivi de tendance
    historique. Achat sur nouveau plus haut, vente sur nouveau plus bas."""

    entry_period: int = 20
    exit_period: int = 10
    stop_loss_pct: float = 5.0
    trailing_stop_pct: float = 0.0
    name: str = "Donchian"

    @property
    def warmup(self):
        return max(self.entry_period, self.exit_period) + 2

    def decide(self, candles, position=None):
        price = float(candles[-1]["close"])
        if len(candles) < self.warmup:
            return Decision(Signal.HOLD, "Pas assez de données")

        entry_high, _ = donchian(candles, self.entry_period)
        _, exit_low = donchian(candles, self.exit_period)
        indicators = {"price": price, "channel_high": entry_high, "channel_low": exit_low}

        if position is not None:
            position.update_peak(price)
            forced = self._exit_checks(price, position, indicators)
            if forced:
                return forced
            if price < exit_low:
                return Decision(Signal.SELL, "Cassure du plus bas", indicators)
            return Decision(Signal.HOLD, "Position conservée", indicators)

        if price > entry_high:
            return Decision(Signal.BUY, "Cassure du plus haut", indicators)
        return Decision(Signal.HOLD, "Pas de cassure", indicators)


@dataclass
class CashStrategy(BaseStrategy):
    """Référence de contrôle : n'achète jamais, reste 100% en liquide.

    Elle sert à démasquer un piège classique : en marché baissier, n'importe
    quelle stratégie peu exposée « bat » le buy & hold sans aucun mérite. Si une
    stratégie ne bat pas *celle-ci*, son avantage n'est que de l'absence.
    """

    stop_loss_pct: float = 0.0
    trailing_stop_pct: float = 0.0
    name: str = "Ne rien faire (liquide)"

    @property
    def warmup(self):
        return 2

    def decide(self, candles, position=None):
        return Decision(Signal.HOLD, "Reste en liquide", {})


def registry():
    """Toutes les stratégies comparables, avec leurs réglages par défaut."""
    from tradebot.strategy import SmaCrossoverStrategy, StrategyConfig

    return [
        SmaCrossoverStrategy(
            StrategyConfig(sma_short=10, sma_long=50, use_trend_filter=False,
                           use_volatility_filter=False),
            name="Moyennes mobiles",
        ),
        SmaCrossoverStrategy(
            StrategyConfig(sma_short=10, sma_long=50, use_trend_filter=True,
                           trend_period=100, use_volatility_filter=False),
            name="Moyennes + filtre tendance",
        ),
        RsiStrategy(),
        MacdStrategy(),
        BollingerStrategy(),
        DonchianStrategy(),
        CashStrategy(),
    ]
