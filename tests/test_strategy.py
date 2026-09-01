"""Tests de la stratégie et du backtest, exécutables sans dépendance :

    python -m tests.test_strategy
"""

from tradebot.backtest import run_backtest
from tradebot.strategy import Position, Signal, SmaCrossoverStrategy, StrategyConfig, atr, sma


def candles_from(prices):
    """Fabrique des bougies à partir d'une simple liste de prix de clôture."""
    return [
        {"start": i * 3600000, "open": p, "high": p * 1.01, "low": p * 0.99, "close": p}
        for i, p in enumerate(prices)
    ]


def bare_config(**kwargs):
    """Config sans filtres : pour tester le croisement seul."""
    defaults = dict(
        sma_short=3, sma_long=5, use_trend_filter=False,
        use_volatility_filter=False, stop_loss_pct=0, trailing_stop_pct=0,
        atr_period=2,
    )
    defaults.update(kwargs)
    return StrategyConfig(**defaults)


def test_sma():
    assert sma([1, 2, 3], 3) == 2
    assert sma([1, 2], 3) is None
    print("  ok  sma")


def test_atr_positive():
    value = atr(candles_from([10, 11, 12, 13]), 2)
    assert value and value > 0
    print("  ok  atr")


def test_buy_on_upward_crossover():
    strategy = SmaCrossoverStrategy(bare_config())
    # Prix plats puis nette hausse : la moyenne courte passe au-dessus de la longue
    decision = strategy.decide(candles_from([10] * 5 + [11]))
    assert decision.signal == Signal.BUY, decision.reason
    print("  ok  achat sur croisement haussier")


def test_sell_on_downward_crossover():
    strategy = SmaCrossoverStrategy(bare_config())
    prices = [10] * 5 + [11, 12, 13, 14, 15, 14, 13, 12, 11, 10, 9]
    position = Position(entry_price=11, size=1, peak_price=15)
    signals = [strategy.decide(candles_from(prices[: i + 1]), position).signal
               for i in range(6, len(prices))]
    assert Signal.SELL in signals
    print("  ok  vente sur croisement baissier")


def test_stop_loss_fires():
    strategy = SmaCrossoverStrategy(bare_config(stop_loss_pct=5))
    position = Position(entry_price=100, size=1, peak_price=100)
    decision = strategy.decide(candles_from([100] * 5 + [94]), position)
    assert decision.signal == Signal.SELL
    assert "Stop-loss" in decision.reason
    print("  ok  stop-loss")


def test_trailing_stop_fires():
    strategy = SmaCrossoverStrategy(bare_config(trailing_stop_pct=10))
    position = Position(entry_price=100, size=1, peak_price=120)
    decision = strategy.decide(candles_from([100] * 5 + [105]), position)
    assert decision.signal == Signal.SELL
    assert "Trailing" in decision.reason
    print("  ok  trailing stop")


def test_trend_filter_blocks_buy():
    """Sous la tendance de fond, un croisement haussier doit être ignoré."""
    config = bare_config(use_trend_filter=True, trend_period=15)
    strategy = SmaCrossoverStrategy(config)
    # Longue descente : la tendance de fond reste haute. Le rebond final croise
    # bien vers le haut, mais le prix est toujours loin sous la tendance.
    prices = [100, 95, 90, 85, 80, 75, 70, 65, 60, 55, 50, 45, 40, 35, 30, 33, 38, 44]
    decision = strategy.decide(candles_from(prices))
    # On vérifie d'abord que le croisement a bien lieu (sinon le test ne teste rien)
    assert SmaCrossoverStrategy(bare_config()).decide(candles_from(prices)).signal == Signal.BUY
    assert decision.signal == Signal.HOLD
    assert "tendance de fond" in decision.reason
    print("  ok  filtre de tendance")


def test_crossover_is_stateless():
    """Deux instances distinctes doivent décider pareil sur les mêmes données :
    la détection ne doit dépendre d'aucun état interne accumulé."""
    prices = [10] * 5 + [11, 12, 13, 12, 11, 10, 12, 14]
    candles = candles_from(prices)

    fed_progressively = SmaCrossoverStrategy(bare_config())
    for i in range(6, len(prices)):
        fed_progressively.decide(candles_from(prices[: i + 1]))
    last_progressive = fed_progressively.decide(candles)

    fresh = SmaCrossoverStrategy(bare_config()).decide(candles)
    assert last_progressive.signal == fresh.signal
    print("  ok  détection sans état")


def test_backtest_runs_and_compares_to_hold():
    prices = [10] * 10 + [11, 12, 13, 14, 15, 14, 13, 14, 15, 16, 17, 16, 15, 16, 18]
    result = run_backtest(candles_from(prices), bare_config(), initial_eur=100.0)
    assert result["final_value"] > 0
    assert "hold_value" in result and result["hold_value"] > 0
    assert result["beats_hold"] == (result["final_value"] > result["hold_value"])
    assert len(result["equity_curve"]) == len(prices) - bare_config().warmup
    print("  ok  backtest et comparaison au buy & hold")


def test_backtest_fees_reduce_return():
    prices = [10] * 10 + [11, 12, 13, 12, 11, 12, 13, 14, 13, 12, 13, 14, 15]
    candles = candles_from(prices)
    free = run_backtest(candles, bare_config(), 100.0, fee=0.0)
    costly = run_backtest(candles, bare_config(), 100.0, fee=0.01)
    if free["trades"] > 0:
        assert costly["final_value"] < free["final_value"]
    print("  ok  les frais réduisent bien le résultat")


def test_walk_forward_only_scores_unseen_data():
    """La validation walk-forward ne doit jamais noter une période qui a servi
    à choisir les paramètres : les fenêtres de test doivent suivre les fenêtres
    d'entraînement, sans chevauchement."""
    from tradebot.walkforward import walk_forward

    prices = [10 + (i % 17) * 0.5 + i * 0.05 for i in range(400)]
    outcome = walk_forward(
        candles_from(prices),
        param_sets=[bare_config(), bare_config(sma_short=5, sma_long=20)],
        train=150, test=50,
    )
    assert outcome["fold_count"] >= 2
    for fold in outcome["folds"]:
        train_start, train_end = fold["train_range"]
        test_start, test_end = fold["test_range"]
        assert test_start >= train_end, "la validation empiète sur l'entraînement"
        assert test_end > test_start
    # Le capital se transmet bien d'une fenêtre à la suivante
    for previous, following in zip(outcome["folds"], outcome["folds"][1:]):
        assert following["capital_before"] == previous["capital_after"]
    print("  ok  walk-forward n'évalue que des données inconnues")


if __name__ == "__main__":
    print("\nTests de la stratégie\n")
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("\nTous les tests passent.\n")
