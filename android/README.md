# Tradebot — application Android

Application native (Kotlin + Jetpack Compose) qui embarque tout le bot :
données de marché, stratégies, backtest, étude comparative et trading.

## Installation sur le téléphone

1. Récupérer `Tradebot.apk` (à la racine du dépôt) sur le téléphone
2. L'ouvrir — Android demandera d'autoriser l'installation depuis cette source
3. Accepter la notification (nécessaire pour que le bot tourne en fond)

L'APK est signé avec la clé de debug : il s'installe directement, sans passer
par le Play Store. Ce n'est pas une signature de production.

## Écrans

- **Direct** — prix en temps réel, graphique avec les moyennes mobiles,
  position en cours, valeur du portefeuille, démarrage/arrêt, et la raison
  en clair de chaque décision.
- **Stratégies** — rejoue les six stratégies sur plusieurs paires et les
  classe. La référence « Ne rien faire (liquide) » est incluse : si elle
  arrive en tête, c'est que l'avantage des autres n'était qu'une absence
  de marché.
- **Backtest** — teste la stratégie sélectionnée sur l'historique de la
  paire choisie, avec courbe de capital et comparaison au buy & hold.
- **Réglages** — paire, capital/plafond, intervalle, stratégie, clés API,
  activation du mode réel.

## Fonctionnement en continu

Le bot tourne dans un *service en avant-plan* : c'est le mécanisme prévu par
Android pour un travail de longue durée. Une notification permanente affiche
l'état, et le bot continue quand l'app n'est plus au premier plan. Un cycle
par minute, ce qui reste très en dessous du quota de l'API.

## Sécurité des clés

La clé API et la clé privée sont stockées via `EncryptedSharedPreferences`,
adossé au Keystore Android. Elles ne quittent l'appareil que dans les requêtes
signées vers Revolut.

La signature Ed25519 est vérifiée par un test unitaire contre un vecteur de
référence calculé indépendamment en Python — une signature incorrecte ferait
rejeter tous les ordres réels sans message d'erreur explicite.

## Compilation

```bash
export ANDROID_HOME=$HOME/android-sdk
gradle testDebugUnitTest   # 28 tests
gradle assembleRelease     # produit app/build/outputs/apk/release/
```

## Limites connues

- L'interface n'a pas pu être vérifiée sur un appareil ou un émulateur :
  l'environnement de compilation n'a pas de KVM. Le code compile et la
  logique est couverte par des tests, mais le rendu visuel reste à
  confirmer au premier lancement.
- Les endpoints authentifiés (solde, passage d'ordre) n'ont pas été testés
  de bout en bout faute de compte de test. La signature, elle, est vérifiée.
- Le mode réel utilise des ordres au marché (0,09 % de frais). Les ordres
  limites post-only à 0 % existent côté Python mais ne sont pas encore
  câblés dans l'app.
