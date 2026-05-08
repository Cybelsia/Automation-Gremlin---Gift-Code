from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent
COGS_DIR = BASE_DIR / "cogs"

RAILWAY_VOLUME_MOUNT_PATH = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")

if RAILWAY_VOLUME_MOUNT_PATH:
    VOLUME_DIR = Path(RAILWAY_VOLUME_MOUNT_PATH)
    DB_DIR = VOLUME_DIR / "db"
    LOG_DIR = VOLUME_DIR / "log"
    DATA_DIR = VOLUME_DIR / "data"
    OLD_DB_DIR = VOLUME_DIR / "old_db"
    print(f"[PATH] Using Railway volume: {VOLUME_DIR.resolve()}")
else:
    print("[WARN] RAILWAY_VOLUME_MOUNT_PATH not set, using local folders")
    DB_DIR = BASE_DIR / "db"
    LOG_DIR = BASE_DIR / "log"
    DATA_DIR = BASE_DIR / "data"
    OLD_DB_DIR = BASE_DIR / "old_db"

ALLIANCE_DB = DB_DIR / "alliance.sqlite"
BACKUP_DB = DB_DIR / "backup.sqlite"
BEAR_TRAP_DB = DB_DIR / "beartime.sqlite"
CHANGES_DB = DB_DIR / "changes.sqlite"
GIFT_CODE_DB = DB_DIR / "giftcode.sqlite"
GIFT_OPERATIONS_DB = DB_DIR / "gift_operations.sqlite"
ID_CHANNEL_DB = DB_DIR / "id_channel.sqlite"
SETTINGS_DB = DB_DIR / "settings.sqlite"
USERS_DB = DB_DIR / "users.sqlite"

BACKUP_LOG = LOG_DIR / "backuplog.txt"


def ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_path(*parts: str) -> Path:
    return BASE_DIR.joinpath(*parts)


def log_path(label: str, path: Path) -> None:
    print(f"[PATH] {label}: {path.resolve()}")


def log_storage_paths() -> None:
    print(f"[PATH] RAILWAY_VOLUME_MOUNT_PATH: {RAILWAY_VOLUME_MOUNT_PATH or 'Not set'}")
    log_path("DB_DIR", DB_DIR)
    log_path("LOG_DIR", LOG_DIR)
    log_path("DATA_DIR", DATA_DIR)
    log_path("OLD_DB_DIR", OLD_DB_DIR)


def database_path(path: Path, label: str = "sqlite") -> str:
    ensure_parent(path)
    resolved = path.resolve()
    print(f"[PATH] {label}: {resolved}")
    return str(resolved)


def file_path(path: Path, label: str = "file") -> str:
    ensure_parent(path)
    resolved = path.resolve()
    print(f"[PATH] {label}: {resolved}")
    return str(resolved)


def storage_health_report() -> str:
    lines = [
        "Storage Health Report",
        "---------------------",
        f"RAILWAY_VOLUME_MOUNT_PATH: {RAILWAY_VOLUME_MOUNT_PATH or 'NOT SET'}",
        f"DB_DIR:      {DB_DIR.resolve()}",
        f"LOG_DIR:     {LOG_DIR.resolve()}",
        f"DATA_DIR:    {DATA_DIR.resolve()}",
        f"OLD_DB_DIR:  {OLD_DB_DIR.resolve()}",
        "",
        "Database files:",
    ]
    db_files = {
        "ALLIANCE_DB": ALLIANCE_DB,
        "BACKUP_DB": BACKUP_DB,
        "BEAR_TRAP_DB": BEAR_TRAP_DB,
        "CHANGES_DB": CHANGES_DB,
        "GIFT_CODE_DB": GIFT_CODE_DB,
        "GIFT_OPERATIONS_DB": GIFT_OPERATIONS_DB,
        "ID_CHANNEL_DB": ID_CHANNEL_DB,
        "SETTINGS_DB": SETTINGS_DB,
        "USERS_DB": USERS_DB,
    }
    for name, path in db_files.items():
        exists = "exists" if path.exists() else "missing"
        lines.append(f"- {name}: {path.resolve()} ({exists})")
    return "\n".join(lines)
