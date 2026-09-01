# Tradebot — bot de trading crypto sur Revolut X

Bot simple qui trade automatiquement du SOL (Solana) sur **Revolut X** (la
plateforme crypto de Revolut, avec une vraie API — différente de l'app
bancaire classique).

⚠️ **Ceci n'est pas un conseil financier.** Le trading automatique comporte
un risque de perte. Teste toujours en mode simulation avant de passer en réel.

## Comment ça marche

Le bot suit une stratégie simple : **croisement de moyennes mobiles**.
- Il calcule 2 moyennes de prix (une courte, une longue).
- Quand la courte dépasse la longue → il achète (tendance haussière).
- Quand la courte repasse en dessous → il vend (tendance qui s'essouffle).

Deux modes :
- **`paper`** (par défaut) : simulation avec de vrais prix mais un portefeuille
  virtuel. Aucun argent réel n'est touché.
- **`live`** : place de vrais ordres sur ton compte Revolut X, avec un plafond
  de dépense codé en dur pour limiter le risque.

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
   - `TRADEBOT_SYMBOL` : paire à trader (ex: `SOL-EUR`)
   - `TRADEBOT_MAX_POSITION_EUR` : plafond max engagé en mode réel

## Utilisation

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

## Garde-fous inclus

- Le mode réel refuse de démarrer sans clé API + clé privée + confirmation explicite.
- Un achat en mode réel n'engage jamais plus que `TRADEBOT_MAX_POSITION_EUR`.
- Toutes les décisions (simulation et réel) sont journalisées dans `logs/tradebot.log`.

## Limites connues

- La stratégie moyennes mobiles est volontairement simple — elle ne garantit
  aucun gain, et peut perdre de l'argent en marché sans tendance claire.
- Les noms exacts des champs retournés par l'API Revolut X (`get_candles`,
  `get_balances`) sont basés sur la documentation publique ; un premier essai
  en mode `paper` peut révéler de petits ajustements à faire si le format
  réel diffère légèrement.
