from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

import settings
from core.calculate import calculate_failed_print_usage, calculate_usage_snapshot, default_gcode_dir, format_duration
from core.config import CONFIG_FIELDS, current_runtime_settings, load_runtime_settings, reset_runtime_settings, save_runtime_settings
from database.storage import fetch_monthly_totals, fetch_print_history, initialize_database, save_print_job


WEIGHT_UNITS = {
    "г": ("g", 1.0),
    "кг": ("kg", 1000.0),
}

LENGTH_UNITS = {
    "мм": ("mm", 1.0),
    "см": ("cm", 10.0),
    "м": ("m", 1000.0),
}

SETTINGS_LABELS = {
    "PLA_FILAMENT_DIAMETER_MM": "Діаметр філаменту за замовчуванням, мм",
    "PLA_DENSITY_G_CM3": "Густина матеріалу, г/см³",
    "LOSS_PER_RETRACTION_G": "Втрати на один відкат, г",
    "STARTUP_LOSS_G": "Втрати на старті, г",
    "SHUTDOWN_LOSS_G": "Втрати на зупинці, г",
}


class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, parent, on_save):
        super().__init__(parent)
        self.title("Налаштування констант")
        self.geometry("760x420")
        self.minsize(700, 380)
        self.transient(parent)
        self.grab_set()

        self.on_save = on_save
        self.entries = {}

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Редагування констант",
            font=ctk.CTkFont(size=24, weight="bold"),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text="Зміни зберігаються у локальний конфіг і застосовуються одразу.",
            text_color="gray70",
        ).grid(row=1, column=0, pady=(6, 0), sticky="w")

        form = ctk.CTkFrame(self, corner_radius=12)
        form.grid(row=1, column=0, padx=20, pady=10, sticky="nsew")
        form.grid_columnconfigure(0, weight=1)
        form.grid_columnconfigure(1, weight=1)

        current_values = current_runtime_settings()
        keys = list(CONFIG_FIELDS.keys())
        rows_per_column = (len(keys) + 1) // 2

        for index, key in enumerate(keys):
            column = index // rows_per_column
            row = (index % rows_per_column) * 2

            ctk.CTkLabel(form, text=SETTINGS_LABELS[key], anchor="w").grid(
                row=row,
                column=column,
                padx=16,
                pady=(16 if row == 0 else 10, 4),
                sticky="ew",
            )

            entry = ctk.CTkEntry(form, height=38, border_width=2)
            entry.insert(0, self._format_compact_number(current_values[key]))
            entry.grid(row=row + 1, column=column, padx=16, pady=(0, 4), sticky="ew")
            self.entries[key] = entry

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, padx=20, pady=(10, 20), sticky="ew")
        footer.grid_columnconfigure(0, weight=1)
        footer.grid_columnconfigure(1, weight=1)
        footer.grid_columnconfigure(2, weight=1)

        ctk.CTkButton(footer, text="Скинути", command=self._reset).grid(row=0, column=0, padx=(0, 8), sticky="ew")
        ctk.CTkButton(footer, text="Скасувати", command=self.destroy, fg_color="gray55", hover_color="gray40").grid(
            row=0,
            column=1,
            padx=8,
            sticky="ew",
        )
        ctk.CTkButton(footer, text="Зберегти", command=self._save, fg_color="#2f8f4e", hover_color="#256f3d").grid(
            row=0,
            column=2,
            padx=(8, 0),
            sticky="ew",
        )

    def _save(self):
        try:
            values = {}
            for key, entry in self.entries.items():
                value = float(entry.get().replace(",", "."))
                if value <= 0:
                    raise ValueError(f"Поле '{SETTINGS_LABELS[key]}' має бути більшим за нуль.")
                values[key] = value
            save_runtime_settings(values)
        except ValueError as error:
            messagebox.showerror("Помилка", str(error), parent=self)
            return

        self.on_save()
        self.destroy()

    def _reset(self):
        values = reset_runtime_settings()
        for key, entry in self.entries.items():
            entry.delete(0, "end")
            entry.insert(0, self._format_compact_number(values[key]))

    @staticmethod
    def _format_compact_number(value):
        return f"{value:.6f}".rstrip("0").rstrip(".")


class FilamentUsageApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        load_runtime_settings()
        initialize_database()

        self.title("Калькулятор витрат філаменту")
        self.geometry("1180x860")
        self.minsize(920, 680)

        self.selected_file = ctk.StringVar()
        self.filament_diameter = ctk.StringVar(value=f"{settings.PLA_FILAMENT_DIAMETER_MM:.2f}")
        self.failed_percent = ctk.StringVar(value="50")
        self.weight_unit = ctk.StringVar(value="г")
        self.length_unit = ctk.StringVar(value="мм")

        self.summary_vars = {
            "length": ctk.StringVar(value="0.00 мм"),
            "extruded_mass": ctk.StringVar(value="0.0000 г"),
            "retractions": ctk.StringVar(value="0"),
            "retraction_loss": ctk.StringVar(value="0.0000 г"),
            "startup_loss": ctk.StringVar(value="0.0000 г"),
            "shutdown_loss": ctk.StringVar(value="0.0000 г"),
            "waste_mass": ctk.StringVar(value="0.0000 г"),
            "total_mass": ctk.StringVar(value="0.0000 г"),
            "progress": ctk.StringVar(value="100.0 %"),
            "time": ctk.StringVar(value="Немає даних у G-code"),
        }
        self.monthly_vars = {
            "spent": ctk.StringVar(value="0 г"),
            "waste": ctk.StringVar(value="0 г"),
            "length": ctk.StringVar(value="0 мм"),
            "prints": ctk.StringVar(value="0"),
            "success_rate": ctk.StringVar(value="0 %"),
            "waste_rate": ctk.StringVar(value="0 %"),
        }

        self._resize_job = None
        self._last_snapshot = None

        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        self._build_style()
        self._build_layout()
        self.bind("<Configure>", self._schedule_resize_update)
        self.after(100, self._refresh_dashboard)

    def _build_style(self):
        style = ttk.Style()
        style.configure("History.Treeview", rowheight=26, font=("Segoe UI", 10))
        style.configure("History.Treeview.Heading", font=("Segoe UI", 10, "bold"))

    def _build_layout(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.scrollable = ctk.CTkScrollableFrame(self, corner_radius=10)
        self.scrollable.grid(row=0, column=0, padx=12, pady=12, sticky="nsew")
        self.scrollable.grid_columnconfigure(0, weight=1)
        self.scrollable.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self.scrollable, fg_color="transparent")
        header.grid(row=0, column=0, padx=14, pady=(14, 10), sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Контроль витрат пластику для G-code",
            font=ctk.CTkFont(size=28, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        self.header_subtitle = ctk.CTkLabel(
            header,
            text="Вдалі й невдалі друки, втрати на старті, зупинці та відкатах — все в одному місці.",
            text_color="gray70",
            justify="left",
        )
        self.header_subtitle.grid(row=1, column=0, pady=(6, 0), sticky="w")

        ctk.CTkButton(header, text="Налаштування", command=self._open_settings_dialog, width=140).grid(
            row=0,
            column=1,
            rowspan=2,
            sticky="e",
        )

        self.content = ctk.CTkFrame(self.scrollable, corner_radius=10)
        self.content.grid(row=1, column=0, padx=14, pady=(0, 14), sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_columnconfigure(1, weight=1)

        left_panel = ctk.CTkFrame(self.content, corner_radius=10)
        left_panel.grid(row=0, column=0, padx=(0, 8), pady=0, sticky="nsew")
        left_panel.grid_columnconfigure(0, weight=1)

        right_panel = ctk.CTkFrame(self.content, corner_radius=10)
        right_panel.grid(row=0, column=1, padx=(8, 0), pady=0, sticky="nsew")
        right_panel.grid_columnconfigure(0, weight=1)

        self._build_file_panel(left_panel)
        self._build_results_panel(left_panel)
        self._build_monthly_panel(right_panel)
        self._build_print_actions_panel(right_panel)
        self._build_history_panel(right_panel)

    def _build_file_panel(self, parent):
        panel = ctk.CTkFrame(parent, corner_radius=8)
        panel.grid(row=0, column=0, padx=14, pady=(14, 10), sticky="ew")
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_columnconfigure(1, weight=0)

        ctk.CTkLabel(panel, text="Вхідні дані", font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=0,
            column=0,
            columnspan=2,
            padx=16,
            pady=(16, 12),
            sticky="w",
        )

        ctk.CTkLabel(panel, text="Шлях до G-code").grid(row=1, column=0, columnspan=2, padx=16, pady=(0, 6), sticky="w")

        self.file_entry = ctk.CTkEntry(panel, textvariable=self.selected_file, height=40, border_width=2)
        self.file_entry.grid(row=2, column=0, padx=(16, 8), pady=(0, 12), sticky="ew")

        ctk.CTkButton(panel, text="Обрати", command=self._choose_file, width=140, height=40).grid(
            row=2,
            column=1,
            padx=(8, 16),
            pady=(0, 12),
            sticky="ew",
        )

        ctk.CTkLabel(panel, text="Діаметр філаменту, мм").grid(row=3, column=0, padx=16, pady=(0, 6), sticky="w")

        lower_row = ctk.CTkFrame(panel, fg_color="transparent")
        lower_row.grid(row=4, column=0, columnspan=2, padx=16, pady=(0, 16), sticky="ew")
        lower_row.grid_columnconfigure(0, weight=1)
        lower_row.grid_columnconfigure(1, weight=0)

        self.diameter_entry = ctk.CTkEntry(
            lower_row,
            textvariable=self.filament_diameter,
            height=40,
            width=0,
            border_width=2,
        )
        self.diameter_entry.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        ctk.CTkButton(lower_row, text="Розрахувати", command=self._calculate_full_print, width=140, height=40).grid(
            row=0,
            column=1,
            padx=(8, 0),
            sticky="ew",
        )

    def _build_results_panel(self, parent):
        panel = ctk.CTkFrame(parent, corner_radius=8)
        panel.grid(row=1, column=0, padx=14, pady=(10, 14), sticky="ew")
        panel.grid_columnconfigure(0, weight=3)
        panel.grid_columnconfigure(1, weight=2)

        ctk.CTkLabel(panel, text="Результат розрахунку", font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=0,
            column=0,
            columnspan=2,
            padx=16,
            pady=(16, 12),
            sticky="w",
        )

        rows = [
            ("Використано філаменту", "length"),
            ("Корисна маса екструзії", "extruded_mass"),
            ("Кількість відкатів", "retractions"),
            ("Втрати на відкати", "retraction_loss"),
            ("Втрати на старті", "startup_loss"),
            ("Втрати на зупинці", "shutdown_loss"),
            ("Неефективні втрати", "waste_mass"),
            ("Загальні витрати", "total_mass"),
            ("Прогрес", "progress"),
            ("Оцінка часу друку", "time"),
        ]

        for index, (label, key) in enumerate(rows, start=1):
            ctk.CTkLabel(
                panel,
                text=label,
                text_color="gray70",
                justify="left",
                wraplength=320,
            ).grid(row=index, column=0, padx=(16, 8), pady=7, sticky="w")

            ctk.CTkLabel(
                panel,
                textvariable=self.summary_vars[key],
                font=ctk.CTkFont(size=15, weight="bold"),
                anchor="e",
                justify="right",
            ).grid(row=index, column=1, padx=(8, 16), pady=7, sticky="e")

    def _build_monthly_panel(self, parent):
        panel = ctk.CTkFrame(parent, corner_radius=8)
        panel.grid(row=0, column=0, padx=14, pady=(14, 10), sticky="ew")
        for column in range(3):
            panel.grid_columnconfigure(column, weight=1)

        header = ctk.CTkFrame(panel, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=3, padx=16, pady=(16, 8), sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        header.grid_columnconfigure(1, weight=0)
        header.grid_columnconfigure(2, weight=0)

        ctk.CTkLabel(header, text="Останні 30 днів", font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=0,
            column=0,
            sticky="w",
        )

        self.weight_unit_menu = ctk.CTkOptionMenu(
            header,
            values=list(WEIGHT_UNITS.keys()),
            variable=self.weight_unit,
            width=90,
            command=lambda _: self._populate_monthly_totals(),
        )
        self.weight_unit_menu.grid(row=0, column=1, padx=(8, 8), sticky="e")

        self.length_unit_menu = ctk.CTkOptionMenu(
            header,
            values=list(LENGTH_UNITS.keys()),
            variable=self.length_unit,
            width=90,
            command=lambda _: self._populate_monthly_totals(),
        )
        self.length_unit_menu.grid(row=0, column=2, sticky="e")

        cards = [
            ("Загальні витрати", "spent"),
            ("Загальні втрати", "waste"),
            ("Використано філаменту", "length"),
            ("Кількість друків", "prints"),
            ("% успішних друків", "success_rate"),
            ("% втраченого пластику", "waste_rate"),
        ]

        for index, (label, key) in enumerate(cards):
            row = index // 3 + 1
            column = index % 3
            block = ctk.CTkFrame(panel, corner_radius=8, fg_color=("gray93", "gray19"))
            block.grid(row=row, column=column, padx=8, pady=8, sticky="nsew")
            ctk.CTkLabel(block, text=label, text_color="gray70", wraplength=170, justify="left").pack(
                anchor="w",
                padx=12,
                pady=(10, 4),
            )
            ctk.CTkLabel(block, textvariable=self.monthly_vars[key], font=ctk.CTkFont(size=18, weight="bold")).pack(
                anchor="w",
                padx=12,
                pady=(0, 10),
            )

    def _build_print_actions_panel(self, parent):
        panel = ctk.CTkFrame(parent, corner_radius=8)
        panel.grid(row=1, column=0, padx=14, pady=(10, 10), sticky="ew")
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(panel, text="Запис друку", font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=0,
            column=0,
            columnspan=2,
            padx=16,
            pady=(16, 10),
            sticky="w",
        )

        self.actions_help = ctk.CTkLabel(
            panel,
            text="Для невдалого друку вкажи відсоток зупинки. Для вдалого друку зберігається повний результат на 100%.",
            justify="left",
            text_color="gray70",
        )
        self.actions_help.grid(row=1, column=0, columnspan=2, padx=16, pady=(0, 10), sticky="w")

        ctk.CTkLabel(panel, text="Зупинка на, %").grid(row=2, column=0, padx=16, pady=(0, 6), sticky="w")
        ctk.CTkEntry(panel, textvariable=self.failed_percent, width=140, height=40, border_width=2).grid(
            row=2,
            column=1,
            padx=16,
            pady=(0, 6),
            sticky="w",
        )

        ctk.CTkButton(
            panel,
            text="Невдалий друк",
            command=self._register_failed_print,
            fg_color="#b84d3b",
            hover_color="#963b2c",
            height=40,
        ).grid(row=3, column=0, padx=(16, 8), pady=(8, 16), sticky="ew")

        ctk.CTkButton(
            panel,
            text="Вдалий друк",
            command=self._register_successful_print,
            fg_color="#2f8f4e",
            hover_color="#256f3d",
            height=40,
        ).grid(row=3, column=1, padx=(8, 16), pady=(8, 16), sticky="ew")

    def _build_history_panel(self, parent):
        panel = ctk.CTkFrame(parent, corner_radius=8)
        panel.grid(row=2, column=0, padx=14, pady=(10, 14), sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(panel, fg_color="transparent")
        header.grid(row=0, column=0, padx=16, pady=(16, 10), sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(header, text="Історія друків", font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=0,
            column=0,
            sticky="w",
        )
        ctk.CTkButton(header, text="Оновити", command=self._refresh_dashboard, width=100).grid(row=0, column=1, sticky="e")

        tree_frame = ctk.CTkFrame(panel, fg_color="transparent")
        tree_frame.grid(row=1, column=0, padx=16, pady=(0, 16), sticky="nsew")
        tree_frame.grid_columnconfigure(0, weight=1)
        tree_frame.grid_rowconfigure(0, weight=1)

        columns = ("created_at", "status", "file", "progress", "time", "spent", "waste")
        self.history_tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            height=11,
            style="History.Treeview",
        )
        self.history_tree.heading("created_at", text="Час")
        self.history_tree.heading("status", text="Статус")
        self.history_tree.heading("file", text="Файл")
        self.history_tree.heading("progress", text="Прогрес, %")
        self.history_tree.heading("time", text="Друкувалося")
        self.history_tree.heading("spent", text="Витрати")
        self.history_tree.heading("waste", text="Втрати")

        self.history_tree.column("created_at", width=145, minwidth=130, anchor="center")
        self.history_tree.column("status", width=90, minwidth=80, anchor="center")
        self.history_tree.column("file", width=190, minwidth=150, anchor="w")
        self.history_tree.column("progress", width=90, minwidth=80, anchor="center")
        self.history_tree.column("time", width=110, minwidth=90, anchor="center")
        self.history_tree.column("spent", width=95, minwidth=85, anchor="center")
        self.history_tree.column("waste", width=95, minwidth=85, anchor="center")

        self.history_tree.tag_configure("successful", background="#e7f6ea", foreground="#1f5f32")
        self.history_tree.tag_configure("failed", background="#fbe8e5", foreground="#7f2f24")

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.history_tree.yview)
        self.history_tree.configure(yscrollcommand=scrollbar.set)

        self.history_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

    def _schedule_resize_update(self, event):
        if event.widget is not self:
            return
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(90, self._apply_responsive_layout)

    def _apply_responsive_layout(self):
        self._resize_job = None
        width = max(self.winfo_width(), 920)
        self.header_subtitle.configure(wraplength=max(320, width // 2))
        self.actions_help.configure(wraplength=max(300, width // 3))

    def _open_settings_dialog(self):
        SettingsDialog(self, self._apply_runtime_settings)

    def _apply_runtime_settings(self):
        load_runtime_settings()
        self.filament_diameter.set(f"{settings.PLA_FILAMENT_DIAMETER_MM:.2f}")
        if self._last_snapshot is not None:
            self._calculate_full_print()
        self._populate_monthly_totals()

    def _choose_file(self):
        initial_dir = default_gcode_dir()
        if not initial_dir.exists():
            initial_dir = Path.cwd()

        file_path = filedialog.askopenfilename(
            title="Оберіть G-code файл",
            initialdir=str(initial_dir),
            filetypes=[("G-code", "*.gcode"), ("Усі файли", "*.*")],
        )
        if file_path:
            self.selected_file.set(file_path)

    def _parse_diameter(self):
        try:
            diameter = float(self.filament_diameter.get().replace(",", "."))
        except ValueError as error:
            raise ValueError("Діаметр філаменту має бути числом.") from error

        if diameter <= 0:
            raise ValueError("Діаметр філаменту має бути більшим за нуль.")

        return diameter

    def _selected_path(self):
        raw_path = self.selected_file.get().strip()
        if not raw_path:
            raise ValueError("Спочатку обери G-code файл.")

        file_path = Path(raw_path)
        if not file_path.exists():
            raise ValueError("Вказаний G-code файл не знайдено.")

        return file_path

    def _build_snapshot_for_progress(self, progress_percent):
        file_path = self._selected_path()
        diameter = self._parse_diameter()
        snapshot = calculate_usage_snapshot(
            str(file_path),
            progress_percent=progress_percent,
            filament_diameter_mm=diameter,
        )
        return file_path, snapshot

    def _apply_snapshot(self, snapshot):
        self._last_snapshot = snapshot
        self.summary_vars["length"].set(f"{snapshot.total_filament_mm:.2f} мм")
        self.summary_vars["extruded_mass"].set(f"{snapshot.extruded_mass_g:.4f} г")
        self.summary_vars["retractions"].set(str(snapshot.retraction_count))
        self.summary_vars["retraction_loss"].set(f"{snapshot.retraction_loss_g:.4f} г")
        self.summary_vars["startup_loss"].set(f"{snapshot.startup_loss_g:.4f} г")
        self.summary_vars["shutdown_loss"].set(f"{snapshot.shutdown_loss_g:.4f} г")
        self.summary_vars["waste_mass"].set(f"{snapshot.inefficient_mass_g:.4f} г")
        self.summary_vars["total_mass"].set(f"{snapshot.total_mass_g:.4f} г")
        self.summary_vars["progress"].set(f"{snapshot.progress_percent:.1f} %")
        self.summary_vars["time"].set(format_duration(snapshot.estimated_print_time_seconds))

    def _save_snapshot(self, file_path, snapshot, print_status):
        waste_mass = snapshot.total_mass_g if print_status == "failed" else snapshot.inefficient_mass_g
        save_print_job(
            gcode_file=file_path,
            print_status=print_status,
            progress_percent=snapshot.progress_percent,
            estimated_print_time_seconds=snapshot.estimated_print_time_seconds,
            total_filament_mm=snapshot.total_filament_mm,
            extruded_mass_g=snapshot.extruded_mass_g,
            retraction_loss_g=snapshot.retraction_loss_g,
            startup_loss_g=snapshot.startup_loss_g,
            shutdown_loss_g=snapshot.shutdown_loss_g,
            total_mass_g=snapshot.total_mass_g,
            waste_mass_g=waste_mass,
        )

    def _calculate_full_print(self):
        try:
            _, snapshot = self._build_snapshot_for_progress(100.0)
        except Exception as error:
            messagebox.showerror("Помилка", str(error))
            return
        self._apply_snapshot(snapshot)

    def _register_failed_print(self):
        try:
            failed_percent = float(self.failed_percent.get().replace(",", "."))
            if failed_percent <= 0 or failed_percent > 100:
                raise ValueError("Відсоток невдалого друку має бути в межах від 0 до 100.")

            file_path = self._selected_path()
            diameter = self._parse_diameter()
            snapshot = calculate_failed_print_usage(
                str(file_path),
                failed_at_percent=failed_percent,
                filament_diameter_mm=diameter,
            )
            self._save_snapshot(file_path, snapshot, "failed")
        except Exception as error:
            messagebox.showerror("Помилка", str(error))
            return

        self._apply_snapshot(snapshot)
        self._refresh_dashboard()
        messagebox.showinfo(
            "Збережено",
            (
                "Невдалий друк записано в базу.\n"
                f"Втрачено: {snapshot.total_mass_g:.4f} г, {snapshot.total_filament_mm:.2f} мм."
            ),
        )

    def _register_successful_print(self):
        try:
            file_path, snapshot = self._build_snapshot_for_progress(100.0)
            self._save_snapshot(file_path, snapshot, "successful")
        except Exception as error:
            messagebox.showerror("Помилка", str(error))
            return

        self._apply_snapshot(snapshot)
        self._refresh_dashboard()
        messagebox.showinfo(
            "Збережено",
            (
                "Вдалий друк записано в базу.\n"
                f"Загальні витрати: {snapshot.total_mass_g:.4f} г.\n"
                f"Неефективні втрати: {snapshot.inefficient_mass_g:.4f} г."
            ),
        )

    def _refresh_dashboard(self):
        self._populate_history()
        self._populate_monthly_totals()

    def _populate_history(self):
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)

        for row in fetch_print_history():
            status = "Вдалий" if row["print_status"] == "successful" else "Невдалий"
            tag = "successful" if row["print_status"] == "successful" else "failed"
            self.history_tree.insert(
                "",
                "end",
                values=(
                    row["created_at"],
                    status,
                    Path(row["gcode_file"]).name,
                    f"{row['progress_percent']:.1f}",
                    format_duration(row["estimated_print_time_seconds"]),
                    self._format_weight(row["total_mass_g"]),
                    self._format_weight(row["waste_mass_g"]),
                ),
                tags=(tag,),
            )

    def _populate_monthly_totals(self):
        totals = fetch_monthly_totals()
        self.monthly_vars["spent"].set(self._format_weight(totals["total_spent_g"]))
        self.monthly_vars["waste"].set(self._format_weight(totals["total_waste_g"]))
        self.monthly_vars["length"].set(self._format_length(totals["total_length_mm"]))
        self.monthly_vars["prints"].set(str(totals["total_prints"]))
        self.monthly_vars["success_rate"].set(self._format_percent(totals["success_rate_percent"]))
        self.monthly_vars["waste_rate"].set(self._format_percent(totals["waste_rate_percent"]))

    def _format_weight(self, grams_value):
        _, divisor = WEIGHT_UNITS[self.weight_unit.get()]
        return f"{self._format_compact_number(grams_value / divisor)} {self.weight_unit.get()}"

    def _format_length(self, millimeters_value):
        _, divisor = LENGTH_UNITS[self.length_unit.get()]
        return f"{self._format_compact_number(millimeters_value / divisor)} {self.length_unit.get()}"

    @staticmethod
    def _format_percent(value):
        return f"{FilamentUsageApp._format_compact_number(value)} %"

    @staticmethod
    def _format_compact_number(value):
        if abs(value) < 0.000001:
            return "0"
        return f"{value:.4f}".rstrip("0").rstrip(".")


def run():
    app = FilamentUsageApp()
    app.mainloop()


if __name__ == "__main__":
    run()
