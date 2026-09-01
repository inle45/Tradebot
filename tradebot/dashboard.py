"""Tableau de bord web local pour piloter le bot depuis un navigateur.

Volontairement construit avec la bibliothèque standard uniquement (http.server),
pour éviter d'installer des dépendances supplémentaires sur mobile (Termux).

Lancement :
    python -m tradebot.dashboard
puis ouvrir http://127.0.0.1:8000 dans le navigateur du téléphone.
"""

import argparse
import json
import logging
import threading
import time
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tradebot.client import RevxClient
from tradebot.config import Config
from tradebot.live_engine import LiveTradingEngine
from tradebot.paper_engine import PaperTradingEngine
from tradebot.strategy import SmaCrossoverStrategy

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
        strategy = SmaCrossoverStrategy(self.config.sma_short, self.config.sma_long)
        if mode == "live":
            engine = LiveTradingEngine(client, strategy, self.config, self.poll_seconds)
        else:
            engine = PaperTradingEngine(client, strategy, self.config, self.poll_seconds)

        with self._lock:
            self.mode = mode
            self.error = None
            self.started_at = datetime.now().isoformat(timespec="seconds")
            self.events.clear()

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
                                    "value_eur": result["value_eur"],
                                }
                            )
            except Exception as exc:
                logger.exception("Erreur pendant le cycle")
                with self._lock:
                    self.error = str(exc)

            # Sommeil découpé pour que l'arrêt soit réactif
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


PAGE = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tradebot</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 16px;
    font-family: -apple-system, system-ui, "Segoe UI", Roboto, sans-serif;
    background: #0e1117; color: #e6e6e6;
  }
  h1 { font-size: 18px; margin: 0 0 4px; }
  .sub { color: #8b949e; font-size: 13px; margin-bottom: 16px; }
  .card {
    background: #161b22; border: 1px solid #30363d; border-radius: 12px;
    padding: 16px; margin-bottom: 12px;
  }
  .price { font-size: 40px; font-weight: 600; letter-spacing: -1px; }
  .label { color: #8b949e; font-size: 12px; text-transform: uppercase; letter-spacing: .5px; }
  .row { display: flex; gap: 12px; }
  .row > .card { flex: 1; }
  .badge {
    display: inline-block; padding: 6px 14px; border-radius: 999px;
    font-weight: 600; font-size: 15px;
  }
  .BUY { background: #12331f; color: #3fb950; border: 1px solid #238636; }
  .SELL { background: #3d1418; color: #f85149; border: 1px solid #da3633; }
  .HOLD { background: #21262d; color: #8b949e; border: 1px solid #30363d; }
  .big { font-size: 22px; font-weight: 600; }
  .pos { color: #3fb950; } .neg { color: #f85149; }
  button {
    width: 100%; padding: 14px; font-size: 16px; font-weight: 600;
    border-radius: 10px; border: none; margin-top: 8px; cursor: pointer;
  }
  .start { background: #238636; color: white; }
  .stop { background: #da3633; color: white; }
  .live { background: #9e6a03; color: white; }
  button:disabled { opacity: .4; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; color: #8b949e; font-weight: 500; padding: 6px 0; }
  td { padding: 6px 0; border-top: 1px solid #21262d; }
  .dot { height: 8px; width: 8px; border-radius: 50%; display: inline-block; margin-right: 6px; }
  .on { background: #3fb950; } .off { background: #6e7681; }
  .warn { background: #2d2008; border-color: #9e6a03; color: #d29922; font-size: 13px; }
  .err { background: #3d1418; border-color: #da3633; color: #f85149; font-size: 13px; }
</style>
</head>
<body>
  <h1>Tradebot</h1>
  <div class="sub"><span id="statusDot" class="dot off"></span><span id="statusText">chargement…</span></div>

  <div id="errBox" class="card err" hidden></div>

  <div class="card">
    <div class="label" id="symbolLabel">SOL/EUR</div>
    <div class="price" id="price">—</div>
    <div style="margin-top:10px"><span id="signal" class="badge HOLD">—</span></div>
  </div>

  <div class="row">
    <div class="card">
      <div class="label">Portefeuille</div>
      <div class="big" id="value">—</div>
      <div id="pnl" style="font-size:13px">—</div>
    </div>
    <div class="card">
      <div class="label">Position</div>
      <div class="big" id="position">—</div>
      <div id="cash" style="font-size:13px; color:#8b949e">—</div>
    </div>
  </div>

  <div class="card">
    <button class="start" id="btnPaper">▶ Démarrer en simulation</button>
    <button class="live" id="btnLive">▶ Démarrer en mode RÉEL</button>
    <button class="stop" id="btnStop">■ Arrêter</button>
    <div id="msg" style="font-size:13px; color:#8b949e; margin-top:10px"></div>
  </div>

  <div class="card">
    <div class="label" style="margin-bottom:8px">Dernières décisions</div>
    <table>
      <thead><tr><th>Heure</th><th>Signal</th><th>Prix</th></tr></thead>
      <tbody id="events"><tr><td colspan="3" style="color:#8b949e">Aucune pour l'instant</td></tr></tbody>
    </table>
  </div>

<script>
const $ = id => document.getElementById(id);
const eur = n => n.toLocaleString('fr-FR', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + ' €';

async function post(path) {
  $('msg').textContent = '…';
  const r = await fetch(path, {method: 'POST'});
  const d = await r.json();
  $('msg').textContent = d.message;
  refresh();
}

$('btnPaper').onclick = () => post('/api/start?mode=paper');
$('btnLive').onclick = () => {
  if (confirm("ATTENTION : le mode RÉEL engage de vrai argent sur ton compte Revolut X.\\n\\nConfirmer ?")) {
    post('/api/start?mode=live');
  }
};
$('btnStop').onclick = () => post('/api/stop');

async function refresh() {
  let d;
  try { d = await (await fetch('/api/status')).json(); } catch (e) { return; }

  $('statusDot').className = 'dot ' + (d.running ? 'on' : 'off');
  const since = d.started_at ? d.started_at.split('T')[1] : '';
  $('statusText').textContent = d.running
    ? (d.mode === 'live' ? 'En marche — MODE RÉEL' : 'En marche — simulation') + ' depuis ' + since
    : 'À l\\'arrêt';
  $('symbolLabel').textContent = d.symbol;

  $('btnPaper').disabled = d.running;
  $('btnLive').disabled = d.running || !d.live_allowed;
  $('btnStop').disabled = !d.running;
  if (!d.live_allowed) {
    $('btnLive').textContent = '▶ Mode réel (désactivé dans .env)';
  }

  $('errBox').hidden = !d.error;
  if (d.error) $('errBox').textContent = 'Erreur : ' + d.error;

  const l = d.last;
  if (l) {
    $('price').textContent = eur(l.price);
    $('signal').textContent = l.signal;
    $('signal').className = 'badge ' + l.signal;
    $('value').textContent = eur(l.value_eur);
    const diff = l.value_eur - l.initial_eur;
    const pct = (diff / l.initial_eur) * 100;
    $('pnl').textContent = (diff >= 0 ? '+' : '') + diff.toFixed(2) + ' € (' + pct.toFixed(2) + '%)';
    $('pnl').className = diff >= 0 ? 'pos' : 'neg';
    $('position').textContent = l.position_base > 0 ? l.position_base.toFixed(4) : '—';
    $('cash').textContent = l.position_base > 0 ? 'investi' : 'liquide : ' + eur(l.cash_eur);
  }

  const tb = $('events');
  if (d.events.length) {
    tb.innerHTML = d.events.map(e =>
      '<tr><td>' + e.time.replace('T', ' ').slice(5) + '</td>' +
      '<td><span class="badge ' + e.signal + '" style="font-size:12px;padding:2px 8px">' + e.signal + '</span></td>' +
      '<td>' + eur(e.price) + '</td></tr>'
    ).join('');
  }
}

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""


def make_handler(runner):
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
            if self.path.startswith("/api/status"):
                self._json(runner.status())
            elif self.path == "/" or self.path.startswith("/index"):
                body = PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self._json({"message": "Not found"}, 404)

        def do_POST(self):
            if self.path.startswith("/api/start"):
                mode = "live" if "mode=live" in self.path else "paper"
                ok, message = runner.start(mode)
                self._json({"ok": ok, "message": message})
            elif self.path.startswith("/api/stop"):
                ok, message = runner.stop()
                self._json({"ok": ok, "message": message})
            else:
                self._json({"message": "Not found"}, 404)

    return Handler


def main():
    parser = argparse.ArgumentParser(description="Dashboard web du bot de trading")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="127.0.0.1 par défaut : accessible seulement depuis cet appareil",
    )
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument(
        "--autostart",
        action="store_true",
        help="démarre directement la simulation au lancement",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    runner = BotRunner(Config, poll_seconds=args.poll_seconds)
    if args.autostart:
        runner.start("paper")

    server = ThreadingHTTPServer((args.host, args.port), make_handler(runner))
    print(f"\n  Dashboard prêt : http://{args.host}:{args.port}\n  (Ctrl+C pour arrêter)\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        runner.stop()
        print("\nArrêt du dashboard.")


if __name__ == "__main__":
    main()
