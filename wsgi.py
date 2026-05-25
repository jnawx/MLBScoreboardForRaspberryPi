import os
import shutil
from pathlib import Path

from waitress import serve

from app import (
    APP_ROOT,
    DATABASE_PATH,
    KIOSK_LAYOUT_FILE,
    KIOSK_TEMPLATE_FILE,
    VISUAL_SCENE_TEMPLATE_FILE,
    app,
    env_int,
    start_background_data_updater,
)


def resolve_app_path(raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate
    return APP_ROOT / candidate


def seed_config_file(target_path: str, source_name: str) -> None:
    target = resolve_app_path(target_path)
    source = APP_ROOT / "static" / source_name
    if target.exists() or not source.exists():
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def prepare_runtime_paths() -> None:
    resolve_app_path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    seed_config_file(KIOSK_LAYOUT_FILE, "kiosk-slides.json")
    seed_config_file(KIOSK_TEMPLATE_FILE, "kiosk-templates.json")
    seed_config_file(VISUAL_SCENE_TEMPLATE_FILE, "visual-scene-templates.json")


def main() -> None:
    prepare_runtime_paths()
    start_background_data_updater()
    serve(
        app,
        host=os.getenv("HOST", "0.0.0.0"),
        port=env_int("PORT", 8080),
        threads=env_int("WAITRESS_THREADS", 6),
    )


if __name__ == "__main__":
    main()
