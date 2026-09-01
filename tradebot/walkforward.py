"""Validation "walk-forward" : la seule façon honnête de tester une stratégie.

Le problème du backtest classique : on choisit les paramètres qui marchent le
mieux *sur les données qu'on a déjà vues*. C'est du surapprentissage — on
trouve les réglages parfaits pour un passé qui ne se reproduira pas.

Le walk-forward corrige ça :
    1. on optimise les paramètres sur une fenêtre d'entraînement
    2. on les applique sur la période SUIVANTE, jamais vue pendant l'optimisation
    3. on avance et on recommence

Seuls les résultats de l'étape 2 comptent. C'est ce qu'aurait vraiment vécu
quelqu'un qui règle son bot avec les données disponibles à l'époque.
"""

import argparse
import itertools
import logging

from tradebot.backtest import MAKER_FEE, TAKER_FEE, fetch_candles, run_backtest
from tradebot.config import Config
from tradebot.strategy import StrategyConfig

logger = logging.getLogger("tradebot.walkforward")


def default_param_sets():
    """Jeux de paramètres candidats testés à chaque ré-optimisation."""
    sets = []
    for short, long, trend in itertools.product([5, 10, 20], [30, 50, 100], [True, False]):
        if short >= long:
            continue
        sets.append(
            StrategyConfig(
                sma_short=short,
                sma_long=long,
                use_trend_filter=trend,
                trend_period=100,
                use_volatility_filter=False,
            )
        )
    return sets


def walk_forward(candles, param_sets=None, train=400, test=150,
                 initial_eur=100.0, fee=TAKER_FEE):
    param_sets = param_sets or default_param_sets()
    folds = []

    capital = initial_eur
    hold_capital = initial_eur
    start = 0

    while start + train + test <= len(candles):
        train_end = start + train
        test_end = train_end + test
        train_slice = candles[start:train_end]

        # --- 1. optimisation sur la fenêtre d'entraînement ---
        best_config, best_return = None, None
        for config in param_sets:
            if config.warmup >= len(train_slice) - 10:
                continue
            outcome = run_backtest(train_slice, config, initial_eur, fee)
            if best_return is None or outcome["return_pct"] > best_return:
                best_config, best_return = config, outcome["return_pct"]

        if best_config is None:
            break

        # --- 2. application sur la période suivante, jamais vue ---
        # On inclut les bougies de "chauffe" avant la fenêtre de test pour que
        # les moyennes mobiles soient déjà calculées à son premier jour.
        lead_in = max(0, train_end - best_config.warmup)
        test_slice = candles[lead_in:test_end]
        result = run_backtest(test_slice, best_config, capital, fee)

        folds.append(
            {
                "train_range": (start, train_end),
                "test_range": (train_end, test_end),
                "params": {
                    "sma_short": best_config.sma_short,
                    "sma_long": best_config.sma_long,
                    "trend_filter": best_config.use_trend_filter,
                },
                "train_return_pct": best_return,
                "test_return_pct": result["return_pct"],
                "test_hold_return_pct": result["hold_return_pct"],
                "edge": result["return_pct"] - result["hold_return_pct"],
                "beats_hold": result["beats_hold"],
                "trades": result["trades"],
                "capital_before": capital,
                "capital_after": result["final_value"],
            }
        )

        # Le capital se cumule d'une fenêtre à l'autre, comme dans la vraie vie
        capital = result["final_value"]
        hold_capital *= result["hold_value"] / result["initial_eur"]
        start += test

    wins = [f for f in folds if f["beats_hold"]]
    honest = [f["test_return_pct"] for f in folds]
    optimistic = [f["train_return_pct"] for f in folds]

    return {
        "folds": folds,
        "fold_count": len(folds),
        "final_capital": capital,
        "total_return_pct": (capital / initial_eur - 1) * 100 if folds else 0.0,
        "hold_capital": hold_capital,
        "hold_return_pct": (hold_capital / initial_eur - 1) * 100 if folds else 0.0,
        "beats_hold": capital > hold_capital,
        "folds_beating_hold": len(wins),
        "avg_test_return": (sum(honest) / len(honest)) if honest else 0.0,
        "avg_train_return": (sum(optimistic) / len(optimistic)) if optimistic else 0.0,
    }


def _print_report(outcome, symbol, interval):
    if not outcome["fold_count"]:
        print("\n  Pas assez d'historique pour une validation walk-forward.\n")
        return

    bars_per_day = 1440 / int(interval)
    print()
    print(f"  VALIDATION WALK-FORWARD — {symbol}, bougies de {interval} min")
    print("  " + "-" * 66)
    print(f"  {'période':>8} {'réglages retenus':>20} {'optimisé':>10} "
          f"{'réel':>8} {'hold':>8} {'écart':>8}")
    for fold in outcome["folds"]:
        params = fold["params"]
        label = f"{params['sma_short']}/{params['sma_long']}" + (
            "+T" if params["trend_filter"] else ""
        )
        days = (fold["test_range"][1] - fold["test_range"][0]) / bars_per_day
        mark = "+" if fold["beats_hold"] else " "
        print(f"{mark} {days:>6.0f}j {label:>20} "
              f"{fold['train_return_pct']:>9.1f}% {fold['test_return_pct']:>7.1f}% "
              f"{fold['test_hold_return_pct']:>7.1f}% {fold['edge']:>+7.1f}")

    print("  " + "-" * 66)
    print(f"  Rendement moyen pendant l'optimisation : "
          f"{outcome['avg_train_return']:+.1f}%   <- ce qu'on croit obtenir")
    print(f"  Rendement moyen sur données inconnues  : "
          f"{outcome['avg_test_return']:+.1f}%   <- ce qu'on obtient vraiment")
    print()
    print(f"  Capital final du bot     : {outcome['final_capital']:.2f} EUR "
          f"({outcome['total_return_pct']:+.1f}%)")
    print(f"  Capital sans rien faire  : {outcome['hold_capital']:.2f} EUR "
          f"({outcome['hold_return_pct']:+.1f}%)")
    verdict = "LE BOT FAIT MIEUX" if outcome["beats_hold"] else "LE BOT FAIT MOINS BIEN"
    print(f"\n  >>> {verdict} ({outcome['folds_beating_hold']}/{outcome['fold_count']} "
          f"périodes gagnées)\n")


def main():
    parser = argparse.ArgumentParser(
        description="Validation walk-forward : optimise sur le passé, teste sur l'inconnu"
    )
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--interval", default=None)
    parser.add_argument("--train", type=int, default=400,
                        help="taille de la fenêtre d'optimisation, en bougies")
    parser.add_argument("--test", type=int, default=150,
                        help="taille de la fenêtre de validation, en bougies")
    parser.add_argument("--capital", type=float, default=None)
    parser.add_argument("--maker", action="store_true", help="frais à 0%% (ordres limites)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    symbol = args.symbol or Config.symbol
    interval = args.interval or Config.candle_interval
    candles = fetch_candles(symbol=symbol, interval=interval)

    outcome = walk_forward(
        candles,
        train=args.train,
        test=args.test,
        initial_eur=args.capital or Config.max_position_eur,
        fee=MAKER_FEE if args.maker else TAKER_FEE,
    )
    _print_report(outcome, symbol, interval)


if __name__ == "__main__":
    main()
