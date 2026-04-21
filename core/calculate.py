import json
import math
from pathlib import Path

import settings


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

        key = part[0].upper()
        value = part[1:]
        params[key] = value

    return command, params


def _calculate_mass_from_length(length_mm, diameter_mm, density_g_cm3):
    radius_mm = diameter_mm / 2
    filament_area_mm2 = math.pi * (radius_mm ** 2)

    volume_mm3 = filament_area_mm2 * length_mm
    volume_cm3 = volume_mm3 / settings.MM3_PER_CM3
    return volume_cm3 * density_g_cm3


def calculate_filament_usage(
    gcode_file_path,
    filament_diameter_mm=None,
    density_g_cm3=None,
):
    if filament_diameter_mm is None:
        filament_diameter_mm = settings.PLA_FILAMENT_DIAMETER_MM

    if density_g_cm3 is None:
        density_g_cm3 = settings.PLA_DENSITY_G_CM3

    total_filament_mm = 0.0
    last_e = 0.0
    max_e = 0.0
    extrusion_mode = "absolute"
    volumetric_extrusion = False
    volumetric_filament_diameter_mm = filament_diameter_mm
    retraction_count = 0

    with open(gcode_file_path, "r", encoding="utf-8", errors="ignore") as file:
        for line in file:
            command, params = _parse_gcode_line(line)
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
                    last_e = float(params["E"])
                    max_e = last_e
                except ValueError:
                    last_e = 0.0
                    max_e = 0.0
                continue

            if "E" not in params:
                continue

            try:
                current_e = float(params["E"])
            except ValueError:
                continue

            if command == "G1" and current_e < 0:
                retraction_count += 1

            if extrusion_mode == "relative":
                delta_e = current_e if current_e > 0 else 0.0
                last_e += current_e
            else:
                delta_e = current_e - max_e if current_e > max_e else 0.0
                if current_e > max_e:
                    max_e = current_e
                last_e = current_e

            if delta_e <= 0:
                continue

            if volumetric_extrusion:
                radius_mm = volumetric_filament_diameter_mm / 2
                filament_area_mm2 = math.pi * (radius_mm ** 2)
                total_filament_mm += delta_e / filament_area_mm2
            else:
                total_filament_mm += delta_e

    retraction_loss_g = retraction_count * settings.LOSS_PER_RETRACTION
    total_mass_g = _calculate_mass_from_length(
        total_filament_mm,
        filament_diameter_mm,
        density_g_cm3,
    ) + retraction_loss_g
    return total_filament_mm, total_mass_g, retraction_count, retraction_loss_g


def calculate_extrusion(gcode_file_path):
    total_filament_mm, _, _, _ = calculate_filament_usage(gcode_file_path)
    return total_filament_mm


def calculate_weight(length_mm, diameter_mm=None, density=None):
    if diameter_mm is None:
        diameter_mm = settings.PLA_FILAMENT_DIAMETER_MM

    if density is None:
        density = settings.PLA_DENSITY_G_CM3

    return _calculate_mass_from_length(length_mm, diameter_mm, density)


def _parse_length_value(value):
    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        stripped_value = value.strip().lower().replace(",", ".")
        if stripped_value.endswith("mm"):
            stripped_value = stripped_value[:-2].strip()
            return float(stripped_value)
        if stripped_value.endswith("m"):
            stripped_value = stripped_value[:-1].strip()
            return float(stripped_value) * 1000.0
        return float(stripped_value)

    raise ValueError("Unsupported length value")


def _parse_mass_value(value):
    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        stripped_value = value.strip().lower().replace(",", ".")
        if stripped_value.endswith("kg"):
            stripped_value = stripped_value[:-2].strip()
            return float(stripped_value) * 1000.0
        if stripped_value.endswith("g"):
            stripped_value = stripped_value[:-1].strip()
        return float(stripped_value)

    raise ValueError("Unsupported mass value")


def _load_expected_values(expected_file_path):
    with open(expected_file_path, "r", encoding="utf-8-sig") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError("Expected JSON file must contain an object")

    length_value = None
    mass_value = None

    for key in (
        "filament_length_mm",
        "length_mm",
        "filament_used_mm",
        "filament_length",
    ):
        if key in data:
            length_value = _parse_length_value(data[key])
            break

    for key in (
        "filament_mass_g",
        "mass_g",
        "weight_g",
        "filament_weight_g",
    ):
        if key in data:
            mass_value = _parse_mass_value(data[key])
            break

    if length_value is None and "filament_used" in data:
        length_value = _parse_length_value(data["filament_used"])

    if mass_value is None and "filament_used_weight" in data:
        mass_value = _parse_mass_value(data["filament_used_weight"])

    if length_value is None or mass_value is None:
        raise ValueError("Expected JSON file must provide filament length and mass values")

    return length_value, mass_value


def _percent_difference(actual_value, expected_value):
    if expected_value == 0:
        return 0.0 if actual_value == 0 else float("inf")

    return (actual_value - expected_value) / expected_value * 100.0


def compare_result(gcode_file_path, expected_file_path=None, filament_diameter_mm=None):
    actual_length_mm, actual_mass_g, retraction_count, retraction_loss_g = calculate_filament_usage(
        gcode_file_path,
        filament_diameter_mm=filament_diameter_mm,
    )

    if expected_file_path is None:
        expected_file_path = str(Path(gcode_file_path).with_suffix(".json"))

    expected_length_mm, expected_mass_g = _load_expected_values(expected_file_path)

    return {
        "actual": {
            "length_mm": actual_length_mm,
            "mass_g": actual_mass_g,
            "retractions": retraction_count,
            "retraction_loss_g": retraction_loss_g,
        },
        "expected": {
            "length_mm": expected_length_mm,
            "mass_g": expected_mass_g,
        },
        "percent": {
            "length": _percent_difference(actual_length_mm, expected_length_mm),
            "mass": _percent_difference(actual_mass_g, expected_mass_g),
        },
    }
