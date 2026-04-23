import math
from dataclasses import dataclass
from pathlib import Path

import settings


@dataclass
class UsageSnapshot:
    total_filament_mm: float
    extruded_mass_g: float
    retraction_count: int
    retraction_loss_g: float
    startup_loss_g: float
    shutdown_loss_g: float
    total_mass_g: float
    progress_percent: float
    estimated_print_time_seconds: float | None

    @property
    def inefficient_mass_g(self):
        return self.retraction_loss_g + self.startup_loss_g + self.shutdown_loss_g


def _parse_gcode_line(line):
    clean_line = line.split(";", 1)[0].strip()
    if not clean_line:
        return None, {}

    parts = clean_line.split()
    command = parts[0].upper()
    params = {}

    for part in parts[1:]:
        if len(part) < 2:
            continue

        params[part[0].upper()] = part[1:]

    return command, params


def _extract_total_time_seconds(line):
    if not line.startswith(";TIME:"):
        return None

    try:
        return float(line.split(":", 1)[1].strip())
    except ValueError:
        return None


def _calculate_mass_from_length(length_mm, diameter_mm, density_g_cm3):
    radius_mm = diameter_mm / 2
    filament_area_mm2 = math.pi * (radius_mm ** 2)
    volume_mm3 = filament_area_mm2 * length_mm
    volume_cm3 = volume_mm3 / settings.MM3_PER_CM3
    return volume_cm3 * density_g_cm3


def _collect_extrusion_events(gcode_file_path, filament_diameter_mm):
    extrusion_mode = "absolute"
    volumetric_extrusion = False
    volumetric_filament_diameter_mm = filament_diameter_mm
    max_e = 0.0
    total_time_seconds = None
    events = []

    with open(gcode_file_path, "r", encoding="utf-8", errors="ignore") as file:
        for raw_line in file:
            if total_time_seconds is None:
                total_time_seconds = _extract_total_time_seconds(raw_line.strip())

            command, params = _parse_gcode_line(raw_line)
            if not command:
                continue

            if command == "M82":
                extrusion_mode = "absolute"
                continue

            if command == "M83":
                extrusion_mode = "relative"
                continue

            if command == "M200":
                if "D" in params:
                    try:
                        diameter_value = float(params["D"])
                    except ValueError:
                        diameter_value = volumetric_filament_diameter_mm

                    if diameter_value > 0:
                        volumetric_extrusion = True
                        volumetric_filament_diameter_mm = diameter_value
                    else:
                        volumetric_extrusion = False
                elif "S" in params:
                    try:
                        volumetric_extrusion = float(params["S"]) != 0.0
                    except ValueError:
                        pass
                continue

            if command == "G92" and "E" in params:
                try:
                    max_e = float(params["E"])
                except ValueError:
                    max_e = 0.0
                continue

            if "E" not in params:
                continue

            try:
                current_e = float(params["E"])
            except ValueError:
                continue

            if extrusion_mode == "relative":
                delta_e = current_e
            else:
                delta_e = current_e - max_e
                if current_e > max_e:
                    max_e = current_e

            if delta_e > 0:
                if volumetric_extrusion:
                    radius_mm = volumetric_filament_diameter_mm / 2
                    filament_area_mm2 = math.pi * (radius_mm ** 2)
                    extrusion_mm = delta_e / filament_area_mm2
                else:
                    extrusion_mm = delta_e

                events.append(("extrusion", extrusion_mm))
            elif delta_e < 0:
                events.append(("retraction", abs(delta_e)))

    return events, total_time_seconds


def _build_snapshot(
    events,
    target_extrusion_mm,
    progress_percent,
    filament_diameter_mm,
    density_g_cm3,
    total_time_seconds,
):
    consumed_filament_mm = 0.0
    retraction_count = 0

    for event_type, value_mm in events:
        if event_type == "extrusion":
            if consumed_filament_mm >= target_extrusion_mm:
                break

            remaining_mm = target_extrusion_mm - consumed_filament_mm
            consumed_filament_mm += min(value_mm, remaining_mm)
            continue

        if consumed_filament_mm >= target_extrusion_mm:
            break

        retraction_count += 1

    extruded_mass_g = _calculate_mass_from_length(
        consumed_filament_mm,
        filament_diameter_mm,
        density_g_cm3,
    )
    retraction_loss_g = retraction_count * settings.LOSS_PER_RETRACTION_G
    startup_loss_g = settings.STARTUP_LOSS_G if consumed_filament_mm > 0 else 0.0
    shutdown_loss_g = settings.SHUTDOWN_LOSS_G if consumed_filament_mm > 0 else 0.0
    total_mass_g = extruded_mass_g + retraction_loss_g + startup_loss_g + shutdown_loss_g

    estimated_time = None
    if total_time_seconds is not None:
        estimated_time = total_time_seconds * (progress_percent / 100.0)

    return UsageSnapshot(
        total_filament_mm=consumed_filament_mm,
        extruded_mass_g=extruded_mass_g,
        retraction_count=retraction_count,
        retraction_loss_g=retraction_loss_g,
        startup_loss_g=startup_loss_g,
        shutdown_loss_g=shutdown_loss_g,
        total_mass_g=total_mass_g,
        progress_percent=progress_percent,
        estimated_print_time_seconds=estimated_time,
    )


def calculate_usage_snapshot(
    gcode_file_path,
    progress_percent=100.0,
    filament_diameter_mm=None,
    density_g_cm3=None,
):
    if filament_diameter_mm is None:
        filament_diameter_mm = settings.PLA_FILAMENT_DIAMETER_MM

    if density_g_cm3 is None:
        density_g_cm3 = settings.PLA_DENSITY_G_CM3

    progress_percent = max(0.0, min(100.0, float(progress_percent)))

    events, total_time_seconds = _collect_extrusion_events(
        gcode_file_path,
        filament_diameter_mm,
    )

    total_extrusion_mm = sum(value for event_type, value in events if event_type == "extrusion")
    target_extrusion_mm = total_extrusion_mm * (progress_percent / 100.0)

    return _build_snapshot(
        events,
        target_extrusion_mm,
        progress_percent,
        filament_diameter_mm,
        density_g_cm3,
        total_time_seconds,
    )


def calculate_filament_usage(
    gcode_file_path,
    filament_diameter_mm=None,
    density_g_cm3=None,
):
    snapshot = calculate_usage_snapshot(
        gcode_file_path,
        progress_percent=100.0,
        filament_diameter_mm=filament_diameter_mm,
        density_g_cm3=density_g_cm3,
    )
    return (
        snapshot.total_filament_mm,
        snapshot.total_mass_g,
        snapshot.retraction_count,
        snapshot.retraction_loss_g,
    )


def calculate_failed_print_usage(
    gcode_file_path,
    failed_at_percent,
    filament_diameter_mm=None,
    density_g_cm3=None,
):
    return calculate_usage_snapshot(
        gcode_file_path,
        progress_percent=failed_at_percent,
        filament_diameter_mm=filament_diameter_mm,
        density_g_cm3=density_g_cm3,
    )


def calculate_extrusion(gcode_file_path):
    total_filament_mm, _, _, _ = calculate_filament_usage(gcode_file_path)
    return total_filament_mm


def calculate_weight(length_mm, diameter_mm=None, density=None):
    if diameter_mm is None:
        diameter_mm = settings.PLA_FILAMENT_DIAMETER_MM

    if density is None:
        density = settings.PLA_DENSITY_G_CM3

    return _calculate_mass_from_length(length_mm, diameter_mm, density)


def format_duration(total_seconds):
    if total_seconds is None:
        return "Немає даних у G-code"

    seconds = int(round(total_seconds))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def default_gcode_dir():
    return Path(settings.TEST_FOLDER)
