from enum import Enum


class Signal(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


def sma(prices, period):
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period


class SmaCrossoverStrategy:
    """Achète quand la moyenne mobile courte croise au-dessus de la longue
    (tendance qui accélère), vend quand elle repasse en dessous."""

    def __init__(self, short_period, long_period):
        if short_period >= long_period:
            raise ValueError("short_period doit être inférieur à long_period")
        self.short_period = short_period
        self.long_period = long_period
        self._was_above = None  # état précédent : short au-dessus de long ?

    def next_signal(self, closing_prices):
        short = sma(closing_prices, self.short_period)
        long = sma(closing_prices, self.long_period)
        if short is None or long is None:
            return Signal.HOLD  # pas encore assez de données

        is_above = short > long

        signal = Signal.HOLD
        if self._was_above is not None and is_above != self._was_above:
            signal = Signal.BUY if is_above else Signal.SELL

        self._was_above = is_above
        return signal
