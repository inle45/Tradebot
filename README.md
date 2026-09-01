# Tradebot — bot de trading crypto sur Revolut X

Bot simple qui trade automatiquement du SOL (Solana) sur **Revolut X** (la
plateforme crypto de Revolut, avec une vraie API — différente de l'app
bancaire classique).

⚠️ **Ceci n'est pas un conseil financier.** Le trading automatique comporte
un risque de perte. Teste toujours en mode simulation avant de passer en réel.

## ⚠️ Résultat du backtest : la stratégie ne bat pas l'inaction

Testée sur ~33 jours réels de SOL/EUR, frais inclus :

| | Résultat |
|---|---|
| Bot (moyennes mobiles) | **-0,88 %** |
| Acheter et ne rien faire | **+37,13 %** |

**Aucun** des 15 jeux de paramètres testés (`python -m tradebot.backtest --grid`)
ne bat le buy & hold sur cette période. En clair : sur ces données, laisser le
bot trader aurait fait perdre de l'argent par rapport au fait de simplement
garder ses SOL.

Ce dépôt reste utile comme **outil de mesure** : il permet de tester n'importe
quelle stratégie avant d'y mettre de l'argent. Mais en l'état, il ne faut pas
lancer le mode réel en espérant un gain.

## Comment ça marche

Le bot suit une stratégie simple : **croisement de moyennes mobiles**.
- Il calcule 2 moyennes de prix (une courte, une longue).
- Quand la courte dépasse la longue → il achète (tendance haussière).
- Quand la courte repasse en dessous → il vend (tendance qui s'essouffle).

S'y ajoutent trois protections :
- **Filtre de tendance** : pas d'achat si le prix est sous sa moyenne 200 périodes.
- **Filtre de volatilité (ATR)** : pas de trade en marché trop plat.
- **Stop-loss / trailing stop** : sortie automatique en cas de chute.

Deux modes :
- **`paper`** (par défaut) : simulation avec de vrais prix mais un portefeuille
  virtuel. Aucun argent réel n'est touché. Les frais sont simulés.
- **`live`** : place de vrais ordres sur ton compte Revolut X, avec un plafond
  de dépense pour limiter le risque. Utilise des ordres limites *post-only*
  (0 % de frais au lieu de 0,09 %).

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration (avant de faire quoi que ce soit)

1. **Génère une paire de clés Ed25519** (ça sert à signer tes requêtes de façon sécurisée) :
   ```bash
   openssl genpkey -algorithm ed25519 -out private.pem
   openssl pkey -in private.pem -pubout -out public.pem
   ```
   Le fichier `private.pem` ne doit **jamais** être partagé ou commité.

2. **Crée ta clé API** sur l'app/web Revolut X : uploade `public.pem`, tu
   recevras une clé API (chaîne de 64 caractères).

3. **Copie `.env.example` en `.env`** et remplis :
   ```bash
   cp .env.example .env
   ```
   - `REVX_API_KEY` : ta clé API
   - `REVX_PRIVATE_KEY_PATH` : chemin vers `private.pem`
   - `TRADEBOT_SYMBOL` : paire à trader (ex: `SOL/EUR`)
   - `TRADEBOT_MAX_POSITION_EUR` : plafond max engagé en mode réel

## Utilisation

### Option A — le tableau de bord web (recommandé)

```bash
python -m tradebot.dashboard
```
Puis ouvre **http://127.0.0.1:8000** dans ton navigateur. Tu y trouves le prix
en direct, le signal courant, la valeur du portefeuille et des boutons
Démarrer / Arrêter — plus besoin de terminal au quotidien.

Le dashboard n'écoute que sur `127.0.0.1`, donc il est accessible uniquement
depuis l'appareil qui le fait tourner (personne d'autre sur le réseau ne peut
l'ouvrir). Il n'utilise que la bibliothèque standard de Python : aucune
dépendance supplémentaire à installer, graphique compris.

Il contient deux onglets : **En direct** (prix, graphique, position, contrôles)
et **Backtest** (test de la stratégie sur l'historique, comparé au buy & hold).

### Backtest en ligne de commande

```bash
python -m tradebot.backtest          # test avec les réglages du .env
python -m tradebot.backtest --grid   # classement de plusieurs jeux de paramètres
python -m tradebot.backtest --maker  # en simulant des ordres à 0% de frais
```

### Option B — en ligne de commande

**Étape 1 — toujours commencer par la simulation :**
```bash
python -m tradebot.bot --mode paper
```
Laisse tourner plusieurs jours, regarde `logs/tradebot.log` pour voir les
décisions du bot et l'évolution du portefeuille virtuel.

**Étape 2 — passer en réel seulement quand tu es rassuré·e :**
Mets `TRADEBOT_CONFIRM_LIVE=yes` dans `.env`, puis :
```bash
python -m tradebot.bot --mode live
```
Une confirmation manuelle (taper `OUI`) est aussi demandée avant démarrage.

## Tests

```bash
python -m tests.test_strategy
```

## Garde-fous inclus

- Le mode réel refuse de démarrer sans clé API + clé privée + confirmation explicite.
- Un achat en mode réel n'engage jamais plus que `TRADEBOT_MAX_POSITION_EUR`.
- Stop-loss à -5 % par défaut.
- L'état (position en cours) est sauvegardé sur disque : un redémarrage ne fait
  pas oublier au bot qu'il détient une position.
- Toutes les décisions (simulation et réel) sont journalisées dans `logs/tradebot.log`.

## Limites connues

- **La stratégie ne bat pas le buy & hold** sur les données testées (voir plus haut).
- La détection de croisement est simple et connue de tous ; il ne faut pas
  s'attendre à un avantage sur le marché.
- Les endpoints authentifiés (soldes, passage d'ordres) n'ont pas pu être
  testés de bout en bout faute de compte de test : le premier passage en mode
  réel peut demander de petits ajustements de format, comme il a fallu en faire
  pour les endpoints publics.
- `--grid` sert à vérifier qu'une stratégie n'est pas rentable *uniquement* par
  chance sur un réglage précis. Choisir le meilleur réglage du classement =
  surapprentissage, et ça ne se reproduira pas sur le futur.
