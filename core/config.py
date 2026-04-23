import json
from pathlib import Path

import settings


CONFIG_PATH = Path("database/app_settings.json")

CONFIG_FIELDS = {
    "PLA_FILAMENT_DIAMETER_MM": settings.PLA_FILAMENT_DIAMETER_MM,
    "PLA_DENSITY_G_CM3": settings.PLA_DENSITY_G_CM3,
    "LOSS_PER_RETRACTION_G": settings.LOSS_PER_RETRACTION_G,
    "STARTUP_LOSS_G": settings.STARTUP_LOSS_G,
    "SHUTDOWN_LOSS_G": settings.SHUTDOWN_LOSS_G,
}


def load_runtime_settings():
    values = CONFIG_FIELDS.copy()

    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}

        for key in CONFIG_FIELDS:
            if key in data:
                try:
                    values[key] = float(data[key])
                except (TypeError, ValueError):
                    continue

    _apply_settings(values)
    return values


def save_runtime_settings(values):
    normalized = {}
    for key, default_value in CONFIG_FIELDS.items():
        raw_value = values.get(key, default_value)
        normalized[key] = float(raw_value)

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(normalized, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    _apply_settings(normalized)
    return normalized


def reset_runtime_settings():
    if CONFIG_PATH.exists():
        CONFIG_PATH.unlink()

    _apply_settings(CONFIG_FIELDS)
    return CONFIG_FIELDS.copy()


def current_runtime_settings():
    return {key: getattr(settings, key) for key in CONFIG_FIELDS}


def _apply_settings(values):
    for key, value in values.items():
        setattr(settings, key, float(value))
