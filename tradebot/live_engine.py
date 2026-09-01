import logging
import time
import uuid

from tradebot.strategy import Signal

logger = logging.getLogger("tradebot.live")


class LiveTradingEngine:
    """Boucle de trading RÉEL : place de vrais ordres sur Revolut X.

    Garde-fous :
    - ne démarre que si Config.validate_for_live() passe (clé API, clé privée,
      et TRADEBOT_CONFIRM_LIVE=yes explicitement présents)
    - n'engage jamais plus que `max_position_eur` sur un achat
    - suppose au démarrage que la position existe déjà (assume_in_position),
      pour gérer une position déjà ouverte plutôt que d'en racheter une par-dessus
    """

    def __init__(self, client, strategy, config, poll_seconds=60, assume_in_position=True):
        self.client = client
        self.strategy = strategy
        self.config = config
        self.poll_seconds = poll_seconds
        if assume_in_position:
            self.strategy._was_above = True

    def _closing_prices(self):
        candles = self.client.get_candles(self.config.symbol, self.config.candle_interval)
        rows = candles.get("candles", candles if isinstance(candles, list) else [])
        return [float(c["close"]) for c in rows]

    def _base_currency(self):
        return self.config.symbol.split("-")[0]

    def _quote_currency(self):
        return self.config.symbol.split("-")[1]

    def _available_balance(self, currency):
        balances = self.client.get_balances()
        rows = balances.get("balances", balances if isinstance(balances, list) else [])
        for b in rows:
            if b.get("currency") == currency:
                return float(b.get("available", 0))
        return 0.0

    def _buy(self):
        cash_available = self._available_balance(self._quote_currency())
        quote_size = min(cash_available, self.config.max_position_eur)
        if quote_size <= 0:
            logger.warning("Pas de solde disponible en %s pour acheter", self._quote_currency())
            return
        order_id = str(uuid.uuid4())
        logger.info("[REEL] Achat de %.2f %s (ordre %s)", quote_size, self._quote_currency(), order_id)
        self.client.place_market_order(
            self.config.symbol, "buy", order_id, quote_size=round(quote_size, 2)
        )

    def _sell(self):
        base_available = self._available_balance(self._base_currency())
        if base_available <= 0:
            logger.warning("Pas de position en %s à vendre", self._base_currency())
            return
        order_id = str(uuid.uuid4())
        logger.info("[REEL] Vente de %.6f %s (ordre %s)", base_available, self._base_currency(), order_id)
        self.client.place_market_order(
            self.config.symbol, "sell", order_id, base_size=base_available
        )

    def step(self):
        prices = self._closing_prices()
        if not prices:
            logger.warning("Aucune donnée de prix reçue, on attend le prochain cycle")
            return
        signal = self.strategy.next_signal(prices)

        if signal == Signal.BUY:
            self._buy()
        elif signal == Signal.SELL:
            self._sell()

        logger.info("Prix=%.4f Signal=%s", prices[-1], signal.value)

    def run_forever(self):
        self.config.validate_for_live()
        logger.info(
            "Démarrage du mode REEL sur %s (plafond: %.2f EUR) -- CECI ENGAGE DE VRAIS FONDS",
            self.config.symbol,
            self.config.max_position_eur,
        )
        while True:
            try:
                self.step()
            except Exception:
                logger.exception("Erreur pendant le cycle de trading réel")
            time.sleep(self.poll_seconds)
