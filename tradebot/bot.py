import argparse
import logging
import os

from tradebot.client import RevxClient
from tradebot.config import Config
from tradebot.live_engine import LiveTradingEngine
from tradebot.paper_engine import PaperTradingEngine
from tradebot.strategy import SmaCrossoverStrategy


def setup_logging():
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("logs/tradebot.log"),
        ],
    )


def main():
    parser = argparse.ArgumentParser(description="Bot de trading crypto pour Revolut X")
    parser.add_argument(
        "--mode",
        choices=["paper", "live"],
        default="paper",
        help="paper = simulation sans argent réel (défaut) ; live = ordres réels",
    )
    parser.add_argument("--poll-seconds", type=int, default=60)
    args = parser.parse_args()

    setup_logging()

    client = RevxClient(Config)
    strategy = SmaCrossoverStrategy(Config.sma_short, Config.sma_long)

    if args.mode == "live":
        confirmation = input(
            f"Tu es sur le point de lancer le bot en mode RÉEL sur {Config.symbol} "
            f"avec un plafond de {Config.max_position_eur} EUR.\n"
            "Tape exactement OUI pour confirmer : "
        )
        if confirmation.strip() != "OUI":
            print("Confirmation non reçue, arrêt.")
            return
        engine = LiveTradingEngine(client, strategy, Config, poll_seconds=args.poll_seconds)
    else:
        engine = PaperTradingEngine(client, strategy, Config, poll_seconds=args.poll_seconds)

    engine.run_forever()


if __name__ == "__main__":
    main()
