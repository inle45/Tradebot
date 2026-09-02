"""Étude comparative : passe toutes les stratégies au même test rigoureux.

Chaque stratégie est évaluée en walk-forward (paramètres figés, mais fenêtres
de test successives jamais vues) sur plusieurs paires, puis classée sur son
écart moyen face au buy & hold — la seule mesure qui compte.

Le résultat inclut un test de significativité : sans lui, on prendrait du bruit
pour un avantage.
"""

import argparse
import json
import logging
import math
import time

from tradebot.backtest import MAKER_FEE, TAKER_FEE, fetch_candles, liquid_pairs, run_backtest
from tradebot.config import Config
from tradebot.strategies import registry

logger = logging.getLogger("tradebot.study")


def rolling_evaluation(candles, strategy, window, initial_eur, fee):
    """Découpe l'historique en fenêtres successives et évalue la stratégie sur
    chacune. Les paramètres ne sont pas ré-optimisés : on mesure la stabilité
    d'un réglage fixe, pas la capacité à sur-apprendre."""
    warmup = strategy.warmup
    folds = []
    start = warmup

    while start + window <= len(candles):
        lead_in = max(0, start - warmup)
        segment = candles[lead_in : start + window]
        if len(segment) <= warmup + 5:
            break
        outcome = run_backtest(segment, strategy, initial_eur, fee)
        folds.append(
            {
                "return_pct": outcome["return_pct"],
                "hold_return_pct": outcome["hold_return_pct"],
                "edge": outcome["return_pct"] - outcome["hold_return_pct"],
                "trades": outcome["trades"],
                "max_drawdown_pct": outcome["max_drawdown_pct"],
                # Part du temps réellement exposé au marché. Une stratégie qui
                # reste en liquide "bat" mécaniquement le buy & hold quand le
                # marché baisse — ce n'est pas une compétence, c'est une absence.
                "exposure": outcome["exposure"],
            }
        )
        start += window

    return folds


def significance(edges):
    """Un écart moyen positif ne veut rien dire s'il tient dans le bruit.
    Retourne le t de Student et l'intervalle de confiance à 95%."""
    n = len(edges)
    if n < 2:
        return {"n": n, "mean": 0.0, "t": 0.0, "low": 0.0, "high": 0.0, "significant": False}
    mean = sum(edges) / n
    variance = sum((e - mean) ** 2 for e in edges) / (n - 1)
    standard_error = math.sqrt(variance / n)
    if standard_error == 0:
        return {"n": n, "mean": mean, "t": 0.0, "low": mean, "high": mean,
                "significant": False}
    t = mean / standard_error
    return {
        "n": n,
        "mean": mean,
        "t": t,
        "low": mean - 1.96 * standard_error,
        "high": mean + 1.96 * standard_error,
        # Significatif seulement si l'intervalle de confiance ne contient pas 0
        "significant": abs(t) > 1.96,
    }


def run_study(symbols, interval, window=150, initial_eur=100.0, fee=TAKER_FEE):
    strategies = registry()
    candles_by_symbol = {}

    for index, symbol in enumerate(symbols):
        if index:
            time.sleep(1.2)  # budget de l'API publique : ~1 requête/seconde
        try:
            candles_by_symbol[symbol] = fetch_candles(symbol=symbol, interval=interval)
        except Exception as exc:
            logger.warning("%s ignorée (%s)", symbol, exc)

    results = []
    for strategy in strategies:
        edges, all_folds, wins = [], 0, 0
        trades_total = 0
        drawdowns, returns, hold_returns, exposures = [], [], [], []
        per_pair_edges = []

        for symbol, candles in candles_by_symbol.items():
            folds = rolling_evaluation(candles, strategy, window, initial_eur, fee)
            pair_edges = []
            for fold in folds:
                edges.append(fold["edge"])
                pair_edges.append(fold["edge"])
                all_folds += 1
                wins += 1 if fold["edge"] > 0 else 0
                trades_total += fold["trades"]
                drawdowns.append(fold["max_drawdown_pct"])
                returns.append(fold["return_pct"])
                hold_returns.append(fold["hold_return_pct"])
                exposures.append(fold["exposure"])
            if pair_edges:
                per_pair_edges.append(sum(pair_edges) / len(pair_edges))

        stats = significance(edges)
        # Les périodes d'une même paire, et les paires entre elles, sont très
        # corrélées : le test par période surestime largement la significativité.
        # Agréger d'abord par paire donne une estimation plus prudente.
        pair_stats = significance(per_pair_edges)

        results.append(
            {
                "name": strategy.name,
                "periods": all_folds,
                "win_rate": (wins / all_folds * 100) if all_folds else 0.0,
                "mean_edge": stats["mean"],
                "ci_low": stats["low"],
                "ci_high": stats["high"],
                "t": stats["t"],
                "significant": stats["significant"],
                "pair_ci_low": pair_stats["low"],
                "pair_ci_high": pair_stats["high"],
                "pair_significant": pair_stats["significant"],
                "avg_trades": (trades_total / all_folds) if all_folds else 0.0,
                "avg_drawdown": (sum(drawdowns) / len(drawdowns)) if drawdowns else 0.0,
                "avg_return": (sum(returns) / len(returns)) if returns else 0.0,
                "avg_hold_return": (sum(hold_returns) / len(hold_returns)) if hold_returns else 0.0,
                "avg_exposure": (sum(exposures) / len(exposures) * 100) if exposures else 0.0,
            }
        )

    results.sort(key=lambda r: r["mean_edge"], reverse=True)
    return {"results": results, "pairs": list(candles_by_symbol), "interval": interval,
            "window": window}


def _print_report(study):
    print()
    print(f"  ÉTUDE COMPARATIVE — {len(study['pairs'])} paires, "
          f"bougies de {study['interval']} min")
    print("  Chaque stratégie est mesurée sur son écart face au buy & hold.")
    print("  " + "=" * 74)
    print(f"  {'stratégie':<28} {'périodes':>9} {'gagnées':>8} {'écart moyen':>13} "
          f"{'trades':>7}")
    print("  " + "-" * 74)
    for row in study["results"]:
        mark = "*" if row["significant"] else " "
        print(f"{mark} {row['name']:<28} {row['periods']:>9} "
              f"{row['win_rate']:>7.0f}% {row['mean_edge']:>+12.2f} "
              f"{row['avg_trades']:>7.1f}")
    print("  " + "-" * 74)

    # Le contrôle décisif : une stratégie peu exposée bat mécaniquement le
    # buy & hold quand le marché baisse, sans le moindre talent.
    print(f"  {'stratégie':<28} {'rendement':>10} {'buy&hold':>10} "
          f"{'exposition':>11} {'marché':>9}")
    for row in study["results"]:
        market = "baissier" if row["avg_hold_return"] < 0 else "haussier"
        print(f"  {row['name']:<28} {row['avg_return']:>+9.1f}% "
              f"{row['avg_hold_return']:>+9.1f}% {row['avg_exposure']:>10.0f}% "
              f"{market:>9}")
    print("  " + "-" * 74)

    print(f"  {'stratégie':<28} {'IC par période':>22} {'IC par paire':>22}")
    for row in study["results"]:
        per_period = f"{row['ci_low']:+.1f} à {row['ci_high']:+.1f}"
        per_pair = f"{row['pair_ci_low']:+.1f} à {row['pair_ci_high']:+.1f}"
        flag = "*" if row["pair_significant"] else " "
        print(f"{flag} {row['name']:<28} {per_period:>22} {per_pair:>22}")
    print("  " + "=" * 74)

    winners = [r for r in study["results"] if r["pair_significant"] and r["mean_edge"] > 0]
    if winners:
        print(f"\n  {len(winners)} stratégie(s) résistant au test le plus prudent :")
        for row in winners:
            print(f"    - {row['name']} : {row['mean_edge']:+.2f} points en moyenne")
    else:
        print("\n  Aucune stratégie ne résiste au test agrégé par paire.")
        print("  Les intervalles de confiance par période paraissent flatteurs, mais")
        print("  ils supposent des mesures indépendantes — or les cryptos bougent")
        print("  ensemble. En agrégeant d'abord par paire, l'avantage disparaît.")

    low_exposure = [r for r in study["results"]
                    if r["avg_exposure"] < 50 and r["avg_hold_return"] < 0]
    if low_exposure:
        print("\n  ATTENTION — biais de marché baissier détecté :")
        print("  Sur cette période le buy & hold est négatif, et ces stratégies sont")
        print("  restées hors du marché la plupart du temps. Leur « avantage » vient")
        print("  surtout de leur absence, pas de la qualité de leurs décisions :")
        for row in low_exposure:
            print(f"    - {row['name']} : exposé {row['avg_exposure']:.0f}% du temps")
    print()


def main():
    parser = argparse.ArgumentParser(description="Compare toutes les stratégies")
    parser.add_argument("--pairs", type=int, default=15)
    parser.add_argument("--interval", default="240")
    parser.add_argument("--window", type=int, default=150,
                        help="taille de chaque période d'évaluation, en bougies")
    parser.add_argument("--capital", type=float, default=100.0)
    parser.add_argument("--maker", action="store_true", help="frais à 0%%")
    parser.add_argument("--json", default=None, help="écrire le résultat dans un fichier")
    args = parser.parse_args()

    logging.basicConfig(level=logging.ERROR)
    symbols = liquid_pairs(top=args.pairs)
    study = run_study(
        symbols, args.interval, args.window, args.capital,
        MAKER_FEE if args.maker else TAKER_FEE,
    )
    _print_report(study)

    if args.json:
        with open(args.json, "w") as f:
            json.dump(study, f, indent=2)
        print(f"  Résultat détaillé écrit dans {args.json}\n")


if __name__ == "__main__":
    main()
