"""Sauvegarde de l'état sur disque, pour qu'un redémarrage ne fasse pas
oublier au bot qu'il a une position ouverte."""

import json
import logging
import os

from tradebot.strategy import Position

logger = logging.getLogger("tradebot.state")

DEFAULT_PATH = "state.json"


def save(position, cash_eur, path=DEFAULT_PATH):
    payload = {
        "cash_eur": cash_eur,
        "position": (
            {
                "entry_price": position.entry_price,
                "size": position.size,
                "peak_price": position.peak_price,
            }
            if position
            else None
        ),
    }
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp_path, path)  # écriture atomique : pas de fichier à moitié écrit


def load(path=DEFAULT_PATH):
    """Retourne (position, cash_eur) ou (None, None) si rien de sauvegardé."""
    if not os.path.isfile(path):
        return None, None
    try:
        with open(path) as f:
            payload = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("État illisible (%s), on repart de zéro", exc)
        return None, None

    raw = payload.get("position")
    position = (
        Position(
            entry_price=raw["entry_price"],
            size=raw["size"],
            peak_price=raw.get("peak_price", raw["entry_price"]),
        )
        if raw
        else None
    )
    return position, payload.get("cash_eur")


def clear(path=DEFAULT_PATH):
    if os.path.isfile(path):
        os.remove(path)
