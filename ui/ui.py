from pathlib import Path

import core.calculate as cal
import settings


class FilamentUsageApp:
    def __init__(self):
        self.filament_diameter_mm = settings.PLA_FILAMENT_DIAMETER_MM

    def run(self):
        self._print_header()
        self._configure_filament_diameter()

        while True:
            choice = self._prompt_menu_choice()
            if choice == "1":
                self._run_comparison()
            elif choice == "2":
                print("Вихід.")
                break
            else:
                print("Ця опція поки що не підтримується.")

    def _print_header(self):
        print("Калькулятор витрати філаменту")
        print(f"Поточний діаметр філаменту: {self.filament_diameter_mm:.2f} мм")

    def _configure_filament_diameter(self):
        value = input(
            "Вкажіть реальний діаметр філаменту в мм або натисніть Enter, щоб лишити стандартний: "
        ).strip()

        if not value:
            return

        try:
            diameter_mm = float(value.replace(",", "."))
        except ValueError:
            print("Некоректний діаметр. Залишаю стандартне значення.")
            return

        if diameter_mm <= 0:
            print("Діаметр має бути більшим за нуль. Залишаю стандартне значення.")
            return

        self.filament_diameter_mm = diameter_mm
        settings.PLA_FILAMENT_DIAMETER_MM = diameter_mm
        print(f"Використовую діаметр філаменту: {self.filament_diameter_mm:.2f} мм")

    def _prompt_menu_choice(self):
        print()
        print("1. Порахувати результат")
        print("2. Вийти")
        return input("Оберіть пункт меню: ").strip()

    def _run_comparison(self):
        file_name = input("Вкажіть назву G-code файлу без розширення: ").strip()
        if not file_name:
            print("Потрібно вказати назву файлу.")
            return

        gcode_path = Path(settings.TEST_FOLDER) / f"{file_name}.gcode"
        results = cal.compare_result(
            str(gcode_path),
            filament_diameter_mm=self.filament_diameter_mm,
        )

        print("Результати порівняння:")
        print(f"Фактична довжина (мм): {results['actual']['length_mm']:.2f}")
        print(f"Очікувана довжина (мм): {results['expected']['length_mm']:.2f}")
        print(f"Фактична маса (г): {results['actual']['mass_g']:.4f}")
        print(f"Очікувана маса (г): {results['expected']['mass_g']:.4f}")
        print(f"Кількість ретракцій: {results['actual']['retractions']}")
        print(f"Втрата на ретракції (г): {results['actual']['retraction_loss_g']:.4f}")
        print(f"Різниця довжини: {results['percent']['length']:.2f}%")
        print(f"Різниця маси: {results['percent']['mass']:.2f}%")


def run():
    FilamentUsageApp().run()


if __name__ == "__main__":
    run()
