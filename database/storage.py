import sqlite3
from pathlib import Path

import settings


DB_PATH = Path(settings.DATABASE_PATH)


def initialize_database():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS print_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                gcode_file TEXT NOT NULL,
                print_status TEXT NOT NULL,
                progress_percent REAL NOT NULL,
                estimated_print_time_seconds REAL,
                total_filament_mm REAL NOT NULL,
                extruded_mass_g REAL NOT NULL,
                retraction_loss_g REAL NOT NULL,
                startup_loss_g REAL NOT NULL,
                shutdown_loss_g REAL NOT NULL,
                total_mass_g REAL NOT NULL,
                waste_mass_g REAL NOT NULL
            )
            """
        )
        _migrate_legacy_failed_prints(connection)
        connection.commit()


def _table_exists(connection, table_name):
    row = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def _migrate_legacy_failed_prints(connection):
    if not _table_exists(connection, "failed_prints"):
        return

    legacy_rows = connection.execute(
        """
        SELECT
            created_at,
            gcode_file,
            progress_percent,
            estimated_print_time_seconds,
            lost_filament_mm,
            lost_filament_g
        FROM failed_prints
        """
    ).fetchall()

    if legacy_rows:
        connection.executemany(
            """
            INSERT INTO print_history (
                created_at,
                gcode_file,
                print_status,
                progress_percent,
                estimated_print_time_seconds,
                total_filament_mm,
                extruded_mass_g,
                retraction_loss_g,
                startup_loss_g,
                shutdown_loss_g,
                total_mass_g,
                waste_mass_g
            )
            VALUES (?, ?, 'failed', ?, ?, ?, 0, 0, 0, 0, ?, ?)
            """,
            [
                (
                    row[0],
                    row[1],
                    row[2],
                    row[3],
                    row[4],
                    row[5],
                    row[5],
                )
                for row in legacy_rows
            ],
        )

    connection.execute("DROP TABLE failed_prints")


def save_print_job(
    gcode_file,
    print_status,
    progress_percent,
    estimated_print_time_seconds,
    total_filament_mm,
    extruded_mass_g,
    retraction_loss_g,
    startup_loss_g,
    shutdown_loss_g,
    total_mass_g,
    waste_mass_g,
):
    initialize_database()

    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            """
            INSERT INTO print_history (
                gcode_file,
                print_status,
                progress_percent,
                estimated_print_time_seconds,
                total_filament_mm,
                extruded_mass_g,
                retraction_loss_g,
                startup_loss_g,
                shutdown_loss_g,
                total_mass_g,
                waste_mass_g
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(gcode_file),
                print_status,
                progress_percent,
                estimated_print_time_seconds,
                total_filament_mm,
                extruded_mass_g,
                retraction_loss_g,
                startup_loss_g,
                shutdown_loss_g,
                total_mass_g,
                waste_mass_g,
            ),
        )
        connection.commit()


def fetch_print_history(limit=100):
    initialize_database()

    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT
                id,
                created_at,
                gcode_file,
                print_status,
                progress_percent,
                estimated_print_time_seconds,
                total_filament_mm,
                extruded_mass_g,
                retraction_loss_g,
                startup_loss_g,
                shutdown_loss_g,
                total_mass_g,
                waste_mass_g
            FROM print_history
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [dict(row) for row in rows]


def fetch_monthly_totals():
    initialize_database()

    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT
                COALESCE(SUM(total_mass_g), 0) AS total_spent_g,
                COALESCE(SUM(waste_mass_g), 0) AS total_waste_g,
                COALESCE(SUM(total_filament_mm), 0) AS total_length_mm,
                COUNT(*) AS total_prints,
                COALESCE(SUM(CASE WHEN print_status = 'successful' THEN 1 ELSE 0 END), 0) AS successful_prints
            FROM print_history
            WHERE datetime(created_at) >= datetime('now', '-30 days')
            """
        ).fetchone()

    totals = dict(row)
    total_prints = totals["total_prints"]
    total_spent = totals["total_spent_g"]

    if total_prints:
        totals["success_rate_percent"] = totals["successful_prints"] / total_prints * 100.0
    else:
        totals["success_rate_percent"] = 0.0

    if total_spent:
        totals["waste_rate_percent"] = totals["total_waste_g"] / total_spent * 100.0
    else:
        totals["waste_rate_percent"] = 0.0

    return totals
