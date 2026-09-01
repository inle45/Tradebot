import logging
import time

from tradebot.strategy import Signal

logger = logging.getLogger("tradebot.paper")


class PaperPortfolio:
    """Portefeuille virtuel : aucune requête d'ordre réelle n'est jamais envoyée."""

    def __init__(self, starting_cash_eur):
        self.cash_eur = starting_cash_eur
        self.position_base = 0.0

    def buy(self, price):
        if self.cash_eur <= 0:
            return
        self.position_base = self.cash_eur / price
        logger.info("[SIMULATION] Achat de %.6f à %.4f EUR", self.position_base, price)
        self.cash_eur = 0.0

    def sell(self, price):
        if self.position_base <= 0:
            return
        self.cash_eur = self.position_base * price
        logger.info("[SIMULATION] Vente de %.6f à %.4f EUR -> %.2f EUR", self.position_base, price, self.cash_eur)
        self.position_base = 0.0

    def value(self, price):
        return self.cash_eur + self.position_base * price


class PaperTradingEngine:
    """Boucle qui utilise les vraies données de marché (endpoints publics)
    mais ne place jamais d'ordre réel : toute décision est simulée."""

    def __init__(self, client, strategy, config, poll_seconds=60):
        self.client = client
        self.strategy = strategy
        self.config = config
        self.poll_seconds = poll_seconds
        self.portfolio = PaperPortfolio(config.max_position_eur)

    def _closing_prices(self):
        candles = self.client.get_candles(self.config.symbol, self.config.candle_interval)
        rows = candles.get("candles", candles if isinstance(candles, list) else [])
        return [float(c["close"]) for c in rows]

    def step(self):
        prices = self._closing_prices()
        if not prices:
            logger.warning("Aucune donnée de prix reçue, on attend le prochain cycle")
            return
        current_price = prices[-1]
        signal = self.strategy.next_signal(prices)

        if signal == Signal.BUY:
            self.portfolio.buy(current_price)
        elif signal == Signal.SELL:
            self.portfolio.sell(current_price)

        logger.info(
            "Prix=%.4f Signal=%s ValeurPortefeuille=%.2f EUR",
            current_price,
            signal.value,
            self.portfolio.value(current_price),
        )

    def run_forever(self):
        logger.info(
            "Démarrage du mode SIMULATION sur %s (capital virtuel: %.2f EUR)",
            self.config.symbol,
            self.config.max_position_eur,
        )
        while True:
            try:
                self.step()
            except Exception:
                logger.exception("Erreur pendant le cycle de simulation")
            time.sleep(self.poll_seconds)
