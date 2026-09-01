import logging
import time

from tradebot import state
from tradebot.backtest import TAKER_FEE
from tradebot.strategy import Position, Signal

logger = logging.getLogger("tradebot.paper")


class PaperTradingEngine:
    """Boucle qui utilise les vraies données de marché (endpoints publics)
    mais ne place jamais d'ordre réel : toute décision est simulée.

    Les frais sont simulés eux aussi, sinon la simulation serait trop
    optimiste par rapport à la réalité.
    """

    def __init__(self, client, strategy, config, poll_seconds=60, fee=TAKER_FEE,
                 state_path="state_paper.json"):
        self.client = client
        self.strategy = strategy
        self.config = config
        self.poll_seconds = poll_seconds
        self.fee = fee
        self.state_path = state_path

        saved_position, saved_cash = state.load(state_path)
        self.position = saved_position
        self.cash_eur = saved_cash if saved_cash is not None else config.max_position_eur
        if saved_position or saved_cash is not None:
            logger.info("État précédent restauré (cash: %.2f EUR)", self.cash_eur)

        self.last_decision = None

    def _candles(self):
        data = self.client.get_candles(self.config.symbol, self.config.candle_interval)
        return data.get("data", data if isinstance(data, list) else [])

    def value(self, price):
        return self.cash_eur + (self.position.size * price if self.position else 0.0)

    def _buy(self, price):
        size = (self.cash_eur * (1 - self.fee)) / price
        self.position = Position(entry_price=price, size=size, peak_price=price)
        logger.info("[SIMULATION] Achat de %.6f à %.4f EUR", size, price)
        self.cash_eur = 0.0

    def _sell(self, price):
        proceeds = self.position.size * price * (1 - self.fee)
        profit_pct = (price / self.position.entry_price - 1) * 100
        logger.info(
            "[SIMULATION] Vente de %.6f à %.4f EUR -> %.2f EUR (%+.2f%%)",
            self.position.size, price, proceeds, profit_pct,
        )
        self.cash_eur = proceeds
        self.position = None

    def step(self):
        candles = self._candles()
        if not candles:
            logger.warning("Aucune donnée de prix reçue, on attend le prochain cycle")
            return None

        price = float(candles[-1]["close"])
        decision = self.strategy.decide(candles, self.position)
        self.last_decision = decision

        if decision.signal == Signal.BUY and self.position is None:
            self._buy(price)
        elif decision.signal == Signal.SELL and self.position is not None:
            self._sell(price)

        state.save(self.position, self.cash_eur, self.state_path)

        logger.info(
            "Prix=%.4f Signal=%s (%s) Portefeuille=%.2f EUR",
            price, decision.signal.value, decision.reason, self.value(price),
        )
        return {
            "mode": "paper",
            "symbol": self.config.symbol,
            "price": price,
            "signal": decision.signal.value,
            "reason": decision.reason,
            "indicators": decision.indicators,
            "cash_eur": self.cash_eur,
            "position_base": self.position.size if self.position else 0.0,
            "entry_price": self.position.entry_price if self.position else None,
            "value_eur": self.value(price),
            "initial_eur": self.config.max_position_eur,
        }

    def run_forever(self):
        logger.info(
            "Démarrage du mode SIMULATION sur %s (capital virtuel: %.2f EUR)",
            self.config.symbol, self.config.max_position_eur,
        )
        while True:
            try:
                self.step()
            except Exception:
                logger.exception("Erreur pendant le cycle de simulation")
            time.sleep(self.poll_seconds)
