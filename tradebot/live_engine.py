import logging
import time
import uuid

from tradebot import state
from tradebot.strategy import Position, Signal

logger = logging.getLogger("tradebot.live")


class LiveTradingEngine:
    """Boucle de trading RÉEL : place de vrais ordres sur Revolut X.

    Garde-fous :
    - ne démarre que si Config.validate_for_live() passe (clé API, clé privée,
      et TRADEBOT_CONFIRM_LIVE=yes explicitement présents)
    - n'engage jamais plus que `max_position_eur` sur un achat
    - restaure la position connue depuis le disque au démarrage, et sinon
      déduit une position existante du solde réel du compte
    """

    def __init__(self, client, strategy, config, poll_seconds=60,
                 state_path="state_live.json", use_limit_orders=True):
        self.client = client
        self.strategy = strategy
        self.config = config
        self.poll_seconds = poll_seconds
        self.state_path = state_path
        self.use_limit_orders = use_limit_orders
        self.position, _ = state.load(state_path)
        self.last_decision = None

    def _candles(self):
        data = self.client.get_candles(self.config.symbol, self.config.candle_interval)
        return data.get("data", data if isinstance(data, list) else [])

    def _base_currency(self):
        return self.config.symbol.split("/")[0]

    def _quote_currency(self):
        return self.config.symbol.split("/")[1]

    def _available_balance(self, currency):
        balances = self.client.get_balances()
        rows = balances.get("data", balances if isinstance(balances, list) else [])
        for b in rows:
            if b.get("currency") == currency:
                return float(b.get("available", 0))
        return 0.0

    def _best_price(self, side):
        """Meilleur prix du carnet d'ordres, pour placer un ordre limite qui
        reste "maker" (donc à 0% de frais)."""
        book = self.client.get_order_book(self.config.symbol)
        data = book.get("data", book)
        levels = data.get("bids" if side == "buy" else "asks", [])
        if not levels:
            return None
        best = levels[0]
        return float(best["price"] if isinstance(best, dict) else best[0])

    def _place(self, side, base_size, price):
        order_id = str(uuid.uuid4())
        if self.use_limit_orders:
            limit_price = self._best_price(side)
            if limit_price:
                logger.info(
                    "[REEL] Ordre limite %s de %.6f %s à %.4f (post-only, 0%% de frais)",
                    side, base_size, self._base_currency(), limit_price,
                )
                return self.client.place_limit_order(
                    self.config.symbol, side, order_id, limit_price, base_size
                )
            logger.warning("Carnet d'ordres indisponible, repli sur un ordre au marché")

        logger.info("[REEL] Ordre au marché %s de %.6f %s",
                    side, base_size, self._base_currency())
        return self.client.place_market_order(
            self.config.symbol, side, order_id, base_size=base_size
        )

    def _buy(self, price):
        cash = self._available_balance(self._quote_currency())
        budget = min(cash, self.config.max_position_eur)
        if budget <= 0:
            logger.warning("Pas de solde disponible en %s pour acheter",
                           self._quote_currency())
            return
        base_size = round(budget / price, 6)
        self._place("buy", base_size, price)
        self.position = Position(entry_price=price, size=base_size, peak_price=price)
        state.save(self.position, cash - budget, self.state_path)

    def _sell(self, price):
        base_available = self._available_balance(self._base_currency())
        if base_available <= 0:
            logger.warning("Pas de position en %s à vendre", self._base_currency())
            self.position = None
            return
        self._place("sell", base_available, price)
        if self.position:
            profit_pct = (price / self.position.entry_price - 1) * 100
            logger.info("[REEL] Sortie de position (%+.2f%%)", profit_pct)
        self.position = None
        state.save(None, None, self.state_path)

    def _sync_position(self, price):
        """Si aucune position n'est connue mais que le compte détient déjà de
        la crypto, on l'adopte comme position en cours (cas d'un achat fait à
        la main avant de lancer le bot)."""
        if self.position is not None:
            return
        held = self._available_balance(self._base_currency())
        if held * price > 1:  # on ignore les poussières
            logger.info("Position existante détectée : %.6f %s, adoptée par le bot",
                        held, self._base_currency())
            self.position = Position(entry_price=price, size=held, peak_price=price)
            state.save(self.position, None, self.state_path)

    def step(self):
        candles = self._candles()
        if not candles:
            logger.warning("Aucune donnée de prix reçue, on attend le prochain cycle")
            return None

        price = float(candles[-1]["close"])
        self._sync_position(price)

        decision = self.strategy.decide(candles, self.position)
        self.last_decision = decision

        if decision.signal == Signal.BUY and self.position is None:
            self._buy(price)
        elif decision.signal == Signal.SELL and self.position is not None:
            self._sell(price)

        logger.info("Prix=%.4f Signal=%s (%s)",
                    price, decision.signal.value, decision.reason)

        cash = self._available_balance(self._quote_currency())
        base = self._available_balance(self._base_currency())
        return {
            "mode": "live",
            "symbol": self.config.symbol,
            "price": price,
            "signal": decision.signal.value,
            "reason": decision.reason,
            "indicators": decision.indicators,
            "cash_eur": cash,
            "position_base": base,
            "entry_price": self.position.entry_price if self.position else None,
            "value_eur": cash + base * price,
            "initial_eur": self.config.max_position_eur,
        }

    def run_forever(self):
        self.config.validate_for_live()
        logger.info(
            "Démarrage du mode REEL sur %s (plafond: %.2f EUR) -- CECI ENGAGE DE VRAIS FONDS",
            self.config.symbol, self.config.max_position_eur,
        )
        while True:
            try:
                self.step()
            except Exception:
                logger.exception("Erreur pendant le cycle de trading réel")
            time.sleep(self.poll_seconds)
