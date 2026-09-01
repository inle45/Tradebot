"""Backtest : rejoue la stratégie sur l'historique pour mesurer ce qu'elle
aurait réellement rapporté, frais compris, et la compare au fait de simplement
acheter et ne rien faire ("buy & hold").

Le buy & hold est le seul juge de paix : une stratégie qui ne le bat pas est
inutile, aussi sophistiquée soit-elle.
"""

import argparse
import itertools
import json
import logging
import time

from tradebot.client import RevxClient
from tradebot.config import Config
from tradebot.strategy import Position, Signal, SmaCrossoverStrategy, StrategyConfig

logger = logging.getLogger("tradebot.backtest")

TAKER_FEE = 0.0009  # 0,09% sur Revolut X (ordre au marché)
MAKER_FEE = 0.0  # 0% sur Revolut X (ordre limite post-only)


def _max_drawdown(equity_curve):
    """Pire chute depuis un sommet, en % : mesure du stress subi."""
    peak = float("-inf")
    worst = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, (value - peak) / peak * 100)
    return worst


def run_backtest(candles, strategy_config=None, initial_eur=100.0, fee=TAKER_FEE):
    """Rejoue la stratégie bougie par bougie. Retourne les métriques, la courbe
    de capital et la liste des trades."""
    strategy = SmaCrossoverStrategy(strategy_config or StrategyConfig())
    warmup = strategy.config.warmup

    cash = initial_eur
    position = None
    trades = []
    equity_curve = []
    entry_index = 0

    for i in range(warmup, len(candles)):
        window = candles[: i + 1]
        price = float(window[-1]["close"])
        decision = strategy.decide(window, position)

        if decision.signal == Signal.BUY and position is None:
            size = (cash * (1 - fee)) / price
            position = Position(entry_price=price, size=size, peak_price=price)
            cash = 0.0
            entry_index = i

        elif decision.signal == Signal.SELL and position is not None:
            proceeds = position.size * price * (1 - fee)
            profit_pct = (price / position.entry_price - 1) * 100
            trades.append(
                {
                    "entry_price": position.entry_price,
                    "exit_price": price,
                    "profit_pct": profit_pct,
                    "reason": decision.reason,
                    "bars_held": i - entry_index,
                    "entry_time": candles[entry_index].get("start"),
                    "exit_time": window[-1].get("start"),
                }
            )
            cash = proceeds
            position = None

        value = cash + (position.size * price if position else 0.0)
        equity_curve.append({"time": window[-1].get("start"), "value": value, "price": price})

    final_price = float(candles[-1]["close"])
    final_value = cash + (position.size * final_price if position else 0.0)

    # Référence : acheter au début de la période testée et ne rien faire
    start_price = float(candles[warmup]["close"])
    hold_value = (initial_eur * (1 - fee) / start_price) * final_price

    wins = [t for t in trades if t["profit_pct"] > 0]
    values = [point["value"] for point in equity_curve]

    return {
        "initial_eur": initial_eur,
        "final_value": final_value,
        "return_pct": (final_value / initial_eur - 1) * 100,
        "hold_value": hold_value,
        "hold_return_pct": (hold_value / initial_eur - 1) * 100,
        "beats_hold": final_value > hold_value,
        "trades": len(trades),
        "win_rate": (len(wins) / len(trades) * 100) if trades else 0.0,
        "best_trade_pct": max((t["profit_pct"] for t in trades), default=0.0),
        "worst_trade_pct": min((t["profit_pct"] for t in trades), default=0.0),
        "max_drawdown_pct": _max_drawdown(values),
        "hold_max_drawdown_pct": _max_drawdown([p["price"] for p in equity_curve]),
        "candles_tested": len(candles) - warmup,
        "still_in_position": position is not None,
        "trade_list": trades,
        "equity_curve": equity_curve,
    }


def grid_search(candles, initial_eur=100.0, fee=TAKER_FEE, limit=10):
    """Teste plusieurs jeux de paramètres et les classe par performance.

    ATTENTION : le meilleur jeu de paramètres *sur le passé* n'est presque
    jamais le meilleur sur le futur (surapprentissage). À utiliser pour
    vérifier qu'une stratégie n'est pas rentable *uniquement* par chance sur
    un réglage précis, pas pour choisir aveuglément le sommet du classement.
    """
    results = []
    for short, long, trend_filter in itertools.product(
        [5, 10, 20], [30, 50, 100], [True, False]
    ):
        if short >= long:
            continue
        cfg = StrategyConfig(sma_short=short, sma_long=long, use_trend_filter=trend_filter)
        if cfg.warmup >= len(candles):
            continue
        outcome = run_backtest(candles, cfg, initial_eur, fee)
        results.append(
            {
                "sma_short": short,
                "sma_long": long,
                "trend_filter": trend_filter,
                "return_pct": outcome["return_pct"],
                "hold_return_pct": outcome["hold_return_pct"],
                "beats_hold": outcome["beats_hold"],
                "trades": outcome["trades"],
                "win_rate": outcome["win_rate"],
                "max_drawdown_pct": outcome["max_drawdown_pct"],
            }
        )
    results.sort(key=lambda r: r["return_pct"], reverse=True)
    return results[:limit]


def fetch_candles(config=Config, client=None, symbol=None, interval=None):
    client = client or RevxClient(config)
    data = client.get_candles(symbol or config.symbol, interval or config.candle_interval)
    return data.get("data", [])


def liquid_pairs(quote="EUR", top=20, client=None):
    """Les paires les plus échangées : les moins liquides ont des prix erratiques
    qui faussent complètement un backtest."""
    client = client or RevxClient(Config)
    tickers = client._request("GET", "/1.0/public/tickers", authenticated=False)["data"]
    rows = [t for t in tickers if t["symbol"].endswith("/" + quote)
            and not t["symbol"].startswith(("USDC", "USDT"))]
    rows.sort(key=lambda t: float(t["quote_volume_24h"]), reverse=True)
    seen, out = set(), []
    for row in rows:
        if row["symbol"] not in seen:
            seen.add(row["symbol"])
            out.append(row["symbol"])
    return out[:top]


def multi_pair_backtest(symbols, interval, strategy_config=None, initial_eur=100.0,
                        fee=TAKER_FEE, client=None):
    """Teste la même stratégie sur plusieurs paires.

    Tester sur une seule paire ne prouve rien : un bon résultat peut n'être que
    de la chance. Ce qui compte, c'est la proportion de paires où la stratégie
    bat le buy & hold.
    """
    client = client or RevxClient(Config)
    rows = []
    for index, symbol in enumerate(symbols):
        if index:
            time.sleep(1.1)  # l'API publique tolère ~1 requête par seconde
        try:
            candles = fetch_candles(client=client, symbol=symbol, interval=interval)
        except Exception as exc:
            logger.warning("%s ignorée (%s)", symbol, exc)
            continue

        config = strategy_config or StrategyConfig()
        if len(candles) <= config.warmup + 10:
            logger.warning("%s ignorée : pas assez d'historique", symbol)
            continue

        outcome = run_backtest(candles, config, initial_eur, fee)
        rows.append(
            {
                "symbol": symbol,
                "return_pct": outcome["return_pct"],
                "hold_return_pct": outcome["hold_return_pct"],
                "edge": outcome["return_pct"] - outcome["hold_return_pct"],
                "beats_hold": outcome["beats_hold"],
                "trades": outcome["trades"],
                "win_rate": outcome["win_rate"],
                "max_drawdown_pct": outcome["max_drawdown_pct"],
            }
        )

    wins = [r for r in rows if r["beats_hold"]]
    return {
        "rows": sorted(rows, key=lambda r: r["edge"], reverse=True),
        "pairs_tested": len(rows),
        "pairs_beating_hold": len(wins),
        "share_beating_hold": (len(wins) / len(rows) * 100) if rows else 0.0,
        "median_edge": (
            sorted(r["edge"] for r in rows)[len(rows) // 2] if rows else 0.0
        ),
        "average_edge": (sum(r["edge"] for r in rows) / len(rows)) if rows else 0.0,
    }


def _print_report(result, symbol, interval):
    hours = result["candles_tested"] * int(interval) / 60
    print()
    print(f"  BACKTEST {symbol} — {result['candles_tested']} bougies (~{hours / 24:.0f} jours)")
    print("  " + "-" * 52)
    print(f"  Capital de départ      : {result['initial_eur']:.2f} EUR")
    print(f"  Résultat du bot        : {result['final_value']:.2f} EUR "
          f"({result['return_pct']:+.2f}%)")
    print(f"  Acheter et ne rien faire: {result['hold_value']:.2f} EUR "
          f"({result['hold_return_pct']:+.2f}%)")
    print()
    verdict = "LE BOT FAIT MIEUX" if result["beats_hold"] else "LE BOT FAIT MOINS BIEN"
    difference = result["return_pct"] - result["hold_return_pct"]
    print(f"  >>> {verdict} que de ne rien faire ({difference:+.2f} points)")
    print()
    print(f"  Nombre de trades       : {result['trades']}")
    print(f"  Trades gagnants        : {result['win_rate']:.0f}%")
    print(f"  Meilleur / pire trade  : {result['best_trade_pct']:+.2f}% / "
          f"{result['worst_trade_pct']:+.2f}%")
    print(f"  Pire chute (bot)       : {result['max_drawdown_pct']:.2f}%")
    print(f"  Pire chute (hold)      : {result['hold_max_drawdown_pct']:.2f}%")
    print()


def main():
    parser = argparse.ArgumentParser(description="Backtest de la stratégie sur l'historique")
    parser.add_argument("--capital", type=float, default=None)
    parser.add_argument("--maker", action="store_true",
                        help="simuler des ordres limites post-only (frais 0%%)")
    parser.add_argument("--grid", action="store_true",
                        help="tester plusieurs jeux de paramètres")
    parser.add_argument("--multi", action="store_true",
                        help="tester la stratégie sur les paires les plus liquides")
    parser.add_argument("--pairs", type=int, default=20,
                        help="nombre de paires à tester avec --multi")
    parser.add_argument("--interval", default=None,
                        help="intervalle des bougies en minutes (1440 = journalier, "
                             "beaucoup plus d'historique)")
    parser.add_argument("--json", action="store_true", help="sortie brute en JSON")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    capital = args.capital or Config.max_position_eur
    fee = MAKER_FEE if args.maker else TAKER_FEE
    interval = args.interval or Config.candle_interval

    if args.multi:
        symbols = liquid_pairs(top=args.pairs)
        print(f"\n  TEST SUR {len(symbols)} PAIRES — bougies de {interval} min")
        print("  " + "-" * 64)
        outcome = multi_pair_backtest(
            symbols, interval, Config.strategy_config(), capital, fee
        )
        print(f"  {'paire':<12} {'bot':>9} {'sans rien faire':>16} {'écart':>9} {'trades':>7}")
        for row in outcome["rows"]:
            mark = "+" if row["beats_hold"] else " "
            print(f"{mark} {row['symbol']:<12} {row['return_pct']:>8.1f}% "
                  f"{row['hold_return_pct']:>15.1f}% {row['edge']:>+8.1f} {row['trades']:>7}")
        print("  " + "-" * 64)
        print(f"  Paires où le bot bat l'inaction : "
              f"{outcome['pairs_beating_hold']}/{outcome['pairs_tested']} "
              f"({outcome['share_beating_hold']:.0f}%)")
        print(f"  Écart médian : {outcome['median_edge']:+.1f} points")
        print(f"  Écart moyen  : {outcome['average_edge']:+.1f} points\n")
        return

    candles = fetch_candles(interval=interval)

    if args.grid:
        rows = grid_search(candles, capital, fee)
        print(f"\n  CLASSEMENT DES PARAMÈTRES — {Config.symbol}")
        print("  " + "-" * 68)
        print(f"  {'court':>5} {'long':>5} {'filtre':>7} {'résultat':>10} "
              f"{'vs hold':>9} {'trades':>7} {'gagnants':>9}")
        for row in rows:
            print(f"  {row['sma_short']:>5} {row['sma_long']:>5} "
                  f"{'oui' if row['trend_filter'] else 'non':>7} "
                  f"{row['return_pct']:>9.2f}% "
                  f"{row['return_pct'] - row['hold_return_pct']:>+8.2f} "
                  f"{row['trades']:>7} {row['win_rate']:>8.0f}%")
        print("\n  Rappel : le meilleur réglage sur le passé n'est pas forcément")
        print("  le meilleur sur le futur. Se méfier du surapprentissage.\n")
        return

    config = StrategyConfig(sma_short=Config.sma_short, sma_long=Config.sma_long)
    result = run_backtest(candles, config, capital, fee)

    if args.json:
        result.pop("equity_curve")
        print(json.dumps(result, indent=2))
    else:
        _print_report(result, Config.symbol, Config.candle_interval)


if __name__ == "__main__":
    main()
