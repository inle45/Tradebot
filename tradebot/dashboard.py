"""Tableau de bord web local pour piloter le bot depuis un navigateur.

Volontairement construit avec la bibliothèque standard uniquement (http.server)
et du JavaScript sans dépendance — y compris le graphique, dessiné en SVG à la
main — pour éviter toute installation supplémentaire sur mobile (Termux).

Lancement :
    python -m tradebot.dashboard
puis ouvrir http://127.0.0.1:8000 dans le navigateur du téléphone.
"""

import argparse
import json
import logging
import threading
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from tradebot.backtest import MAKER_FEE, TAKER_FEE, run_backtest
from tradebot.client import RevxClient
from tradebot.config import Config
from tradebot.live_engine import LiveTradingEngine
from tradebot.paper_engine import PaperTradingEngine
from tradebot.strategy import SmaCrossoverStrategy, sma

logger = logging.getLogger("tradebot.dashboard")


class BotRunner:
    """Fait tourner le moteur de trading dans un thread séparé et conserve
    l'état courant pour que le dashboard puisse l'afficher."""

    def __init__(self, config=Config, poll_seconds=60):
        self.config = config
        self.poll_seconds = poll_seconds
        self._thread = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self.mode = None
        self.last = None
        self.error = None
        self.started_at = None
        self.events = deque(maxlen=50)

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, mode):
        if self.running:
            return False, "Le bot tourne déjà."
        if mode == "live":
            try:
                self.config.validate_for_live()
            except RuntimeError as exc:
                return False, str(exc)

        client = RevxClient(self.config)
        strategy = SmaCrossoverStrategy(self.config.strategy_config())
        if mode == "live":
            engine = LiveTradingEngine(
                client, strategy, self.config, self.poll_seconds,
                use_limit_orders=self.config.use_limit_orders,
            )
        else:
            engine = PaperTradingEngine(client, strategy, self.config, self.poll_seconds)

        with self._lock:
            self.mode = mode
            self.error = None
            self.started_at = datetime.now().isoformat(timespec="seconds")

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, args=(engine,), daemon=True)
        self._thread.start()
        return True, f"Bot démarré en mode {'RÉEL' if mode == 'live' else 'simulation'}."

    def stop(self):
        if not self.running:
            return False, "Le bot ne tourne pas."
        self._stop_event.set()
        return True, "Arrêt demandé."

    def _loop(self, engine):
        while not self._stop_event.is_set():
            try:
                result = engine.step()
                if result:
                    with self._lock:
                        self.last = result
                        self.error = None
                        if result["signal"] != "HOLD":
                            self.events.appendleft(
                                {
                                    "time": datetime.now().isoformat(timespec="seconds"),
                                    "signal": result["signal"],
                                    "price": result["price"],
                                    "reason": result["reason"],
                                    "value_eur": result["value_eur"],
                                }
                            )
            except Exception as exc:
                logger.exception("Erreur pendant le cycle")
                with self._lock:
                    self.error = str(exc)

            self._stop_event.wait(self.poll_seconds)

    def status(self):
        with self._lock:
            return {
                "running": self.running,
                "mode": self.mode,
                "started_at": self.started_at,
                "last": self.last,
                "error": self.error,
                "events": list(self.events),
                "live_allowed": self.config.confirm_live,
                "symbol": self.config.symbol,
                "max_position_eur": self.config.max_position_eur,
            }


class MarketData:
    """Petit cache des bougies : évite de retélécharger l'historique à chaque
    rafraîchissement de la page."""

    def __init__(self, config=Config, ttl_seconds=60):
        self.config = config
        self.ttl = ttl_seconds
        self._candles = []
        self._fetched_at = None
        self._lock = threading.Lock()

    def candles(self, force=False):
        with self._lock:
            fresh = (
                self._fetched_at
                and (datetime.now() - self._fetched_at).total_seconds() < self.ttl
            )
            if self._candles and fresh and not force:
                return self._candles
            data = RevxClient(self.config).get_candles(
                self.config.symbol, self.config.candle_interval
            )
            self._candles = data.get("data", [])
            self._fetched_at = datetime.now()
            return self._candles

    def chart(self, points=180):
        """Prix et moyennes mobiles sur les N dernières bougies."""
        candles = self.candles()
        cfg = self.config.strategy_config()
        closes = [float(c["close"]) for c in candles]

        series = []
        start = max(0, len(candles) - points)
        for i in range(start, len(candles)):
            window = closes[: i + 1]
            series.append(
                {
                    "t": candles[i].get("start"),
                    "price": closes[i],
                    "short": sma(window, cfg.sma_short),
                    "long": sma(window, cfg.sma_long),
                    "trend": sma(window, cfg.trend_period) if cfg.use_trend_filter else None,
                }
            )
        return {"symbol": self.config.symbol, "series": series}

    def backtest(self, maker=False):
        candles = self.candles()
        result = run_backtest(
            candles,
            self.config.strategy_config(),
            self.config.max_position_eur,
            MAKER_FEE if maker else TAKER_FEE,
        )
        curve = result.pop("equity_curve")
        step = max(1, len(curve) // 180)
        result["curve"] = curve[::step]
        result["trade_list"] = result["trade_list"][-10:]
        return result


PAGE = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tradebot</title>
<style>
  :root {
    color-scheme: dark;
    --bg: #0b0f16; --card: #141a24; --line: #232c3b;
    --txt: #e8edf5; --dim: #8b98ad;
    --green: #34d17d; --red: #f0616d; --amber: #e0a33e; --blue: #5aa9f5;
  }
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  body {
    margin: 0; padding: 14px 14px 40px;
    font-family: -apple-system, system-ui, "Segoe UI", Roboto, sans-serif;
    background: var(--bg); color: var(--txt);
  }
  header { display: flex; align-items: baseline; gap: 10px; margin-bottom: 3px; }
  h1 { font-size: 19px; margin: 0; letter-spacing: -.3px; }
  .sub { color: var(--dim); font-size: 12.5px; margin-bottom: 14px; }
  .card {
    background: var(--card); border: 1px solid var(--line); border-radius: 14px;
    padding: 15px; margin-bottom: 11px;
  }
  .label { color: var(--dim); font-size: 11px; text-transform: uppercase; letter-spacing: .7px; }
  .price { font-size: 38px; font-weight: 650; letter-spacing: -1.4px; margin: 2px 0 8px; }
  .row { display: flex; gap: 11px; }
  .row > .card { flex: 1; margin-bottom: 11px; }
  .badge { display: inline-block; padding: 5px 13px; border-radius: 999px; font-weight: 650; font-size: 14px; }
  .mini { font-size: 11.5px; padding: 2px 9px; }
  .BUY { background: rgba(52,209,125,.14); color: var(--green); border: 1px solid rgba(52,209,125,.4); }
  .SELL { background: rgba(240,97,109,.14); color: var(--red); border: 1px solid rgba(240,97,109,.4); }
  .HOLD { background: rgba(139,152,173,.12); color: var(--dim); border: 1px solid var(--line); }
  .big { font-size: 21px; font-weight: 650; margin-top: 2px; }
  .pos { color: var(--green); } .neg { color: var(--red); }
  .reason { color: var(--dim); font-size: 12.5px; margin-top: 9px; line-height: 1.45; }
  button {
    width: 100%; padding: 13px; font-size: 15px; font-weight: 650;
    border-radius: 11px; border: none; margin-top: 8px; cursor: pointer; color: #fff;
  }
  .start { background: #1f9d57; } .stop { background: #d0454f; } .live { background: #a2761f; }
  .ghost { background: transparent; border: 1px solid var(--line); color: var(--txt); }
  button:disabled { opacity: .35; }
  table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  th { text-align: left; color: var(--dim); font-weight: 500; padding: 5px 0; font-size: 11px;
       text-transform: uppercase; letter-spacing: .5px; }
  td { padding: 7px 0; border-top: 1px solid var(--line); vertical-align: top; }
  .dot { height: 8px; width: 8px; border-radius: 50%; display: inline-block; margin-right: 6px; }
  .on { background: var(--green); } .off { background: #5b6675; }
  .err { background: rgba(240,97,109,.1); border-color: rgba(240,97,109,.45); color: var(--red); font-size: 12.5px; }
  .tabs { display: flex; gap: 7px; margin-bottom: 11px; }
  .tab { flex: 1; padding: 9px; text-align: center; border-radius: 10px; font-size: 13.5px;
         font-weight: 600; background: var(--card); border: 1px solid var(--line); color: var(--dim); }
  .tab.sel { background: #1e2938; color: var(--txt); border-color: #33425a; }
  svg { display: block; width: 100%; height: auto; }
  .legend { display: flex; gap: 14px; font-size: 11.5px; color: var(--dim); margin-top: 9px; flex-wrap: wrap; }
  .key { width: 15px; height: 2.5px; display: inline-block; vertical-align: middle; margin-right: 5px; border-radius: 2px; }
  .kv { display: flex; justify-content: space-between; padding: 7px 0; border-top: 1px solid var(--line); font-size: 13.5px; }
  .kv:first-of-type { border-top: none; }
  .kv span:first-child { color: var(--dim); }
  .verdict { padding: 13px; border-radius: 11px; font-weight: 650; text-align: center; margin: 4px 0 12px; font-size: 14px; }
  .vgood { background: rgba(52,209,125,.13); color: var(--green); border: 1px solid rgba(52,209,125,.4); }
  .vbad { background: rgba(240,97,109,.13); color: var(--red); border: 1px solid rgba(240,97,109,.4); }
  .note { color: var(--dim); font-size: 11.5px; line-height: 1.5; margin-top: 10px; }
  .spin { color: var(--dim); font-size: 13px; text-align: center; padding: 22px 0; }
</style>
</head>
<body>
  <header><h1>Tradebot</h1><span id="pair" class="label"></span></header>
  <div class="sub"><span id="statusDot" class="dot off"></span><span id="statusText">chargement…</span></div>

  <div class="tabs">
    <div class="tab sel" data-tab="live">En direct</div>
    <div class="tab" data-tab="test">Backtest</div>
  </div>

  <div id="errBox" class="card err" hidden></div>

  <!-- ---------- ONGLET DIRECT ---------- -->
  <section id="tab-live">
    <div class="card">
      <div class="label">Prix actuel</div>
      <div class="price" id="price">—</div>
      <span id="signal" class="badge HOLD">—</span>
      <div class="reason" id="reason"></div>
    </div>

    <div class="card">
      <div class="label" style="margin-bottom:9px">Prix et moyennes mobiles</div>
      <div id="chart"><div class="spin">chargement du graphique…</div></div>
      <div class="legend">
        <span><i class="key" style="background:#5aa9f5"></i>prix</span>
        <span><i class="key" style="background:#34d17d"></i>moyenne courte</span>
        <span><i class="key" style="background:#e0a33e"></i>moyenne longue</span>
        <span><i class="key" style="background:#7d8798"></i>tendance de fond</span>
      </div>
    </div>

    <div class="row">
      <div class="card">
        <div class="label">Portefeuille</div>
        <div class="big" id="value">—</div>
        <div id="pnl" style="font-size:12.5px">—</div>
      </div>
      <div class="card">
        <div class="label">Position</div>
        <div class="big" id="position">—</div>
        <div id="cash" style="font-size:12.5px; color:var(--dim)">—</div>
      </div>
    </div>

    <div class="card">
      <button class="start" id="btnPaper">▶ Démarrer en simulation</button>
      <button class="live" id="btnLive">▶ Démarrer en mode RÉEL</button>
      <button class="stop" id="btnStop">■ Arrêter</button>
      <div id="msg" style="font-size:12.5px; color:var(--dim); margin-top:10px"></div>
    </div>

    <div class="card">
      <div class="label" style="margin-bottom:6px">Dernières décisions</div>
      <table>
        <tbody id="events"><tr><td style="color:var(--dim); border:none">Aucune pour l'instant</td></tr></tbody>
      </table>
    </div>
  </section>

  <!-- ---------- ONGLET BACKTEST ---------- -->
  <section id="tab-test" hidden>
    <div class="card">
      <div class="label">Test sur l'historique réel</div>
      <div class="note">Rejoue la stratégie sur les dernières semaines et compare
        le résultat au fait d'acheter puis de ne rien faire. Frais inclus.</div>
      <button class="ghost" id="btnTest">Lancer le backtest</button>
    </div>
    <div id="testOut"></div>
  </section>

<script>
const $ = id => document.getElementById(id);
const eur = n => (n == null ? '—' : n.toLocaleString('fr-FR',
  {minimumFractionDigits: 2, maximumFractionDigits: 2}) + ' €');
const pct = n => (n >= 0 ? '+' : '') + n.toFixed(2) + '%';

document.querySelectorAll('.tab').forEach(t => t.onclick = () => {
  document.querySelectorAll('.tab').forEach(x => x.classList.toggle('sel', x === t));
  $('tab-live').hidden = t.dataset.tab !== 'live';
  $('tab-test').hidden = t.dataset.tab !== 'test';
});

async function post(path) {
  $('msg').textContent = '…';
  const d = await (await fetch(path, {method: 'POST'})).json();
  $('msg').textContent = d.message;
  refresh();
}
$('btnPaper').onclick = () => post('/api/start?mode=paper');
$('btnLive').onclick = () => {
  if (confirm("ATTENTION : le mode RÉEL engage de l'argent réel sur ton compte Revolut X.\n\nConfirmer ?"))
    post('/api/start?mode=live');
};
$('btnStop').onclick = () => post('/api/stop');

/* ---------- graphique SVG dessiné à la main ---------- */
function drawChart(series) {
  if (!series.length) return;
  const W = 340, H = 170, P = 4;
  const vals = [];
  series.forEach(p => ['price','short','long','trend'].forEach(k => {
    if (p[k] != null) vals.push(p[k]);
  }));
  const lo = Math.min(...vals), hi = Math.max(...vals), span = (hi - lo) || 1;
  const x = i => P + i * (W - 2 * P) / Math.max(1, series.length - 1);
  const y = v => H - P - (v - lo) / span * (H - 2 * P);

  const line = (key, color, width, dash) => {
    const pts = series.map((p, i) => p[key] == null ? null : `${x(i).toFixed(1)},${y(p[key]).toFixed(1)}`)
                      .filter(Boolean).join(' ');
    if (!pts) return '';
    return `<polyline points="${pts}" fill="none" stroke="${color}" stroke-width="${width}"
            stroke-linejoin="round" stroke-linecap="round"${dash ? ` stroke-dasharray="${dash}"` : ''}/>`;
  };

  const area = series.map((p, i) => `${x(i).toFixed(1)},${y(p.price).toFixed(1)}`).join(' ');
  $('chart').innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" style="height:170px">
      <defs><linearGradient id="g" x1="0" x2="0" y1="0" y2="1">
        <stop offset="0%" stop-color="#5aa9f5" stop-opacity=".22"/>
        <stop offset="100%" stop-color="#5aa9f5" stop-opacity="0"/>
      </linearGradient></defs>
      <polygon points="${x(0).toFixed(1)},${H - P} ${area} ${x(series.length - 1).toFixed(1)},${H - P}" fill="url(#g)"/>
      ${line('trend', '#7d8798', 1, '3 3')}
      ${line('long', '#e0a33e', 1.4)}
      ${line('short', '#34d17d', 1.4)}
      ${line('price', '#5aa9f5', 1.8)}
    </svg>
    <div style="display:flex;justify-content:space-between;color:var(--dim);font-size:11px;margin-top:5px">
      <span>${eur(lo)}</span><span>${eur(hi)}</span></div>`;
}

/* ---------- backtest ---------- */
$('btnTest').onclick = async () => {
  $('testOut').innerHTML = '<div class="card"><div class="spin">calcul en cours…</div></div>';
  let d;
  try { d = await (await fetch('/api/backtest')).json(); }
  catch (e) { $('testOut').innerHTML = '<div class="card err">Erreur pendant le backtest</div>'; return; }
  if (d.error) { $('testOut').innerHTML = `<div class="card err">${d.error}</div>`; return; }

  const diff = d.return_pct - d.hold_return_pct;
  const rows = [
    ['Période testée', Math.round(d.candles_tested / 24) + ' jours'],
    ['Capital de départ', eur(d.initial_eur)],
    ['Résultat du bot', eur(d.final_value) + '  (' + pct(d.return_pct) + ')'],
    ['Sans rien faire', eur(d.hold_value) + '  (' + pct(d.hold_return_pct) + ')'],
    ['Nombre de trades', d.trades],
    ['Trades gagnants', Math.round(d.win_rate) + '%'],
    ['Meilleur trade', pct(d.best_trade_pct)],
    ['Pire trade', pct(d.worst_trade_pct)],
    ['Pire chute du bot', d.max_drawdown_pct.toFixed(2) + '%'],
  ];
  $('testOut').innerHTML = `
    <div class="card">
      <div class="verdict ${d.beats_hold ? 'vgood' : 'vbad'}">
        ${d.beats_hold ? '✓ Le bot bat le fait de ne rien faire' : '✕ Le bot fait MOINS BIEN que ne rien faire'}
        <div style="font-weight:400;font-size:12.5px;margin-top:5px;opacity:.85">
          écart : ${diff >= 0 ? '+' : ''}${diff.toFixed(2)} points</div>
      </div>
      ${rows.map(([k, v]) => `<div class="kv"><span>${k}</span><span>${v}</span></div>`).join('')}
      <div class="note">« Sans rien faire » = acheter au début de la période et garder.
        C'est la vraie référence : un bot qui ne la bat pas fait perdre de l'argent
        par rapport à l'inaction.</div>
    </div>`;
};

/* ---------- rafraîchissement ---------- */
async function refresh() {
  let d;
  try { d = await (await fetch('/api/status')).json(); } catch (e) { return; }

  $('pair').textContent = d.symbol;
  $('statusDot').className = 'dot ' + (d.running ? 'on' : 'off');
  const since = d.started_at ? d.started_at.split('T')[1] : '';
  $('statusText').textContent = d.running
    ? (d.mode === 'live' ? 'En marche — MODE RÉEL' : 'En marche — simulation') + ' depuis ' + since
    : 'À l\'arrêt';

  $('btnPaper').disabled = d.running;
  $('btnLive').disabled = d.running || !d.live_allowed;
  $('btnStop').disabled = !d.running;
  if (!d.live_allowed) $('btnLive').textContent = '▶ Mode réel (désactivé dans .env)';

  $('errBox').hidden = !d.error;
  if (d.error) $('errBox').textContent = 'Erreur : ' + d.error;

  const l = d.last;
  if (l) {
    $('price').textContent = eur(l.price);
    $('signal').textContent = l.signal;
    $('signal').className = 'badge ' + l.signal;
    $('reason').textContent = l.reason || '';
    $('value').textContent = eur(l.value_eur);
    const diff = l.value_eur - l.initial_eur;
    $('pnl').textContent = (diff >= 0 ? '+' : '') + diff.toFixed(2) + ' € ('
      + (diff / l.initial_eur * 100).toFixed(2) + '%)';
    $('pnl').className = diff >= 0 ? 'pos' : 'neg';
    $('position').textContent = l.position_base > 0 ? l.position_base.toFixed(4) : '—';
    $('cash').textContent = l.position_base > 0
      ? 'entrée à ' + eur(l.entry_price) : 'liquide : ' + eur(l.cash_eur);
  }

  if (d.events.length) {
    $('events').innerHTML = d.events.map(e =>
      `<tr><td><span class="badge mini ${e.signal}">${e.signal}</span></td>
       <td>${eur(e.price)}</td>
       <td style="color:var(--dim)">${e.time.split('T')[1]}<br>${e.reason || ''}</td></tr>`).join('');
  }
}

async function loadChart() {
  try {
    const d = await (await fetch('/api/chart')).json();
    drawChart(d.series);
  } catch (e) { $('chart').innerHTML = '<div class="spin">graphique indisponible</div>'; }
}

refresh(); loadChart();
setInterval(refresh, 5000);
setInterval(loadChart, 60000);
</script>
</body>
</html>
"""


def make_handler(runner, market):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # évite de polluer la sortie du bot

        def _json(self, payload, code=200):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            route = urlparse(self.path)
            query = parse_qs(route.query)

            if route.path == "/api/status":
                self._json(runner.status())
            elif route.path == "/api/chart":
                try:
                    self._json(market.chart())
                except Exception as exc:
                    self._json({"error": str(exc)}, 500)
            elif route.path == "/api/backtest":
                try:
                    self._json(market.backtest(maker="maker" in query))
                except Exception as exc:
                    logger.exception("Backtest en échec")
                    self._json({"error": str(exc)}, 500)
            elif route.path in ("/", "/index.html"):
                body = PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self._json({"message": "Not found"}, 404)

        def do_POST(self):
            route = urlparse(self.path)
            query = parse_qs(route.query)
            if route.path == "/api/start":
                mode = "live" if query.get("mode", ["paper"])[0] == "live" else "paper"
                ok, message = runner.start(mode)
                self._json({"ok": ok, "message": message})
            elif route.path == "/api/stop":
                ok, message = runner.stop()
                self._json({"ok": ok, "message": message})
            else:
                self._json({"message": "Not found"}, 404)

    return Handler


def main():
    parser = argparse.ArgumentParser(description="Dashboard web du bot de trading")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="127.0.0.1 par défaut : accessible seulement depuis cet appareil",
    )
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--autostart", action="store_true",
                        help="démarre directement la simulation au lancement")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    runner = BotRunner(Config, poll_seconds=args.poll_seconds)
    market = MarketData(Config)
    if args.autostart:
        runner.start("paper")

    server = ThreadingHTTPServer((args.host, args.port), make_handler(runner, market))
    print(f"\n  Dashboard prêt : http://{args.host}:{args.port}\n  (Ctrl+C pour arrêter)\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        runner.stop()
        print("\nArrêt du dashboard.")


if __name__ == "__main__":
    main()
