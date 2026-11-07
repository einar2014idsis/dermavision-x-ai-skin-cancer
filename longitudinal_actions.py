"""Acciones de mantenimiento, papelera y reportes accesibles desde la interfaz."""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from longitudinal_reports import audit_lesion, export_lesion_pdf


class ManagementMixin:
    def idle_for_management(self):
        if self.running or self.app.busy:
            messagebox.showinfo(
                "Espera",
                "Termina el análisis antes de modificar los datos.",
                parent=self.window,
            )
            return False
        self.cancel_auto_comparison()
        return True

    def delete_photo(self, identifier=None):
        if not self.idle_for_management():
            return
        selected = self.history.selection()
        if identifier is None and not selected:
            messagebox.showinfo(
                "Fotografías",
                "Selecciona una fotografía del historial.",
                parent=self.window,
            )
            return
        identifier = identifier or selected[0]
        row = self.store.record(identifier)
        if row["lesion_id"] != self.lesion_id:
            messagebox.showinfo(
                "Fotografías",
                "Abre la lesión de esta fotografía antes de eliminarla.",
                parent=self.window,
            )
            return
        with self.store.connect() as db:
            count = db.execute(
                "SELECT count(*) FROM comparisons WHERE previous_id=? OR current_id=?",
                (identifier, identifier),
            ).fetchone()[0]
        from datetime import datetime

        date = datetime.fromisoformat(row["captured_at"]).strftime("%d/%m/%Y %H:%M")
        if messagebox.askyesno(
            "Eliminar fotografía",
            f"¿Mover la fotografía del {date} y sus {count} comparaciones a la papelera? Podrás recuperarlas desde Configuración.",
            parent=self.window,
        ):
            self.store.move_to_trash("record", identifier)
            self.after_data_change()

    def delete_comparison(self):
        if not self.idle_for_management():
            return
        selected = self.comparisons.selection()
        if not selected:
            messagebox.showinfo(
                "Comparaciones", "Selecciona una comparación.", parent=self.window
            )
            return
        if messagebox.askyesno(
            "Mover a papelera",
            "¿Retirar las comparaciones seleccionadas? Las fotografías se conservarán.",
            parent=self.window,
        ):
            for identifier in selected:
                self.store.move_to_trash("comparison", identifier)
            self.after_data_change()

    def clear_comparisons(self):
        if not self.idle_for_management() or not self.lesion_id:
            return
        if messagebox.askyesno(
            "Limpiar comparaciones",
            "¿Mover todas las comparaciones de esta lesión a la papelera? Las fotografías se conservarán.",
            parent=self.window,
        ):
            self.store.move_to_trash("history", lesion_id=self.lesion_id)
            self.after_data_change()

    def open_trash(self):
        if not self.idle_for_management():
            return
        window = tk.Toplevel(self.window)
        window.title("Papelera · recuperar registros")
        window.geometry("850x430")
        ttk.Label(
            window,
            text="Las fotografías retiradas conservan sus archivos hasta el borrado definitivo.",
            padding=12,
        ).pack(anchor="w")
        tree = ttk.Treeview(
            window,
            columns=("kind", "description", "deleted"),
            show="headings",
            selectmode="browse",
        )
        for key, title in [
            ("kind", "Elemento"),
            ("description", "Fecha del registro"),
            ("deleted", "Retirado"),
        ]:
            tree.heading(key, text=title)
        tree.pack(fill="both", expand=True, padx=12, pady=8)
        rows = {}

        def refresh():
            tree.delete(*tree.get_children())
            rows.clear()
            for i, row in enumerate(self.store.trash_items()):
                rows[str(i)] = row
                tree.insert(
                    "",
                    "end",
                    iid=str(i),
                    values=(
                        "Fotografía" if row["kind"] == "record" else "Comparación",
                        row["description"],
                        row["deleted_at"],
                    ),
                )

        def selected():
            return rows.get(tree.selection()[0]) if tree.selection() else None

        def restore():
            if not self.idle_for_management():
                return
            row = selected()
            if row:
                try:
                    self.store.restore_trash(row["kind"], row["identifier"])
                    refresh()
                    self.after_data_change()
                except Exception as exc:
                    messagebox.showerror("Restaurar", str(exc), parent=window)

        def purge():
            if not self.idle_for_management():
                return
            row = selected()
            if not row:
                return
            ids, files = self.store.purge_preview(row["kind"], row["identifier"])
            detail = f"Comparaciones afectadas: {len(ids)}\nArchivos: {len(files)}\n"
            detail += "\n".join(str(p.relative_to(self.store.root)) for p in files[:8])
            if messagebox.askyesno(
                "Borrado definitivo",
                detail
                + "\n\n¿Borrar definitivamente? Esta acción no se puede deshacer.",
                parent=window,
            ):
                try:
                    self.store.purge_trash(row["kind"], row["identifier"])
                    refresh()
                    self.after_data_change()
                except Exception as exc:
                    messagebox.showerror("Papelera", str(exc), parent=window)

        bar = ttk.Frame(window)
        bar.pack(fill="x", padx=12, pady=12)
        ttk.Button(bar, text="Restaurar selección", command=restore).pack(side="left")
        ttk.Button(bar, text="Borrar definitivamente", command=purge).pack(side="right")
        refresh()

    def create_backup(self):
        if not self.idle_for_management():
            return
        path = filedialog.asksaveasfilename(
            parent=self.window,
            title="Respaldo completo",
            defaultextension=".zip",
            filetypes=[("Respaldo ZIP", "*.zip")],
        )
        if path:
            try:
                self.store.backup(path)
                messagebox.showinfo(
                    "Respaldo verificado",
                    "Incluye SQLite, fotografías, contornos, explicaciones, mapas y papelera.\n"
                    + path,
                    parent=self.window,
                )
            except Exception as exc:
                messagebox.showerror("Respaldo", str(exc), parent=self.window)

    def restore_full_backup(self):
        if not self.idle_for_management():
            return
        path = filedialog.askopenfilename(
            parent=self.window,
            title="Restaurar respaldo completo",
            filetypes=[("Respaldo ZIP", "*.zip")],
        )
        if not path:
            return
        try:
            self.store.validate_backup(path)
        except Exception as exc:
            messagebox.showerror("Respaldo no válido", str(exc), parent=self.window)
            return
        if messagebox.askyesno(
            "Restaurar datos",
            "Se reemplazarán los datos locales por los del respaldo. Se guardará antes una copia completa de recuperación. ¿Continuar?",
            parent=self.window,
        ):
            try:
                recovery = self.store.restore_backup(path)
                self.lesion_id = None
                self.after_data_change()
                messagebox.showinfo(
                    "Restauración completa",
                    "Copia anterior conservada en:\n" + str(recovery),
                    parent=self.window,
                )
            except Exception as exc:
                messagebox.showerror("Restauración", str(exc), parent=self.window)

    def review_followup(self):
        if not self.lesion_id:
            return
        window = tk.Toplevel(self.window)
        window.title("Revisión técnica del seguimiento")
        window.geometry("780x500")
        box = tk.Text(window, wrap="word", font=("Segoe UI", 11), padx=18, pady=18)
        box.pack(fill="both", expand=True)
        box.insert("1.0", audit_lesion(self.store, self.lesion_id))
        box.configure(state="disabled")

    def export_pdf(self):
        if not self.idle_for_management() or not self.lesion_id:
            return
        if not self.records:
            messagebox.showinfo(
                "Informe",
                "Agrega una fotografía a esta lesión antes de generar el informe.",
                parent=self.window,
            )
            return
        from tkinter import ttk
        from datetime import datetime

        dialog = tk.Toplevel(self.window)
        dialog.title("Contenido del informe PDF")
        dialog.transient(self.window)
        dialog.grab_set()
        ttk.Label(dialog, text=self.context_label.cget("text"), wraplength=570).pack(
            anchor="w", padx=18, pady=12
        )
        selected_ids = self.active_photo_ids()
        if self.tabs.index("current") == 1 and self.history.selection():
            selected_ids = list(self.history.selection())
        selected_ids = [i for i in selected_ids if i in {r["id"] for r in self.records}]
        scope = tk.StringVar(value="all")
        ttk.Radiobutton(
            dialog,
            text=f"Todas las fotografías de esta lesión ({len(self.records)})",
            variable=scope,
            value="all",
        ).pack(anchor="w", padx=18, pady=4)
        ttk.Radiobutton(
            dialog,
            text=f"Solo las fotografías seleccionadas ({len(selected_ids)})",
            variable=scope,
            value="selected",
            state="normal" if selected_ids else "disabled",
        ).pack(anchor="w", padx=18, pady=4)
        ttk.Radiobutton(
            dialog, text="Fotografías de un periodo", variable=scope, value="period"
        ).pack(anchor="w", padx=18, pady=4)
        period = ttk.Frame(dialog)
        period.pack(fill="x", padx=18, pady=4)
        start = tk.StringVar(
            value=datetime.fromisoformat(self.records[0]["captured_at"]).strftime(
                "%d/%m/%Y"
            )
        )
        end = tk.StringVar(
            value=datetime.fromisoformat(self.records[-1]["captured_at"]).strftime(
                "%d/%m/%Y"
            )
        )
        ttk.Label(period, text="Desde:").pack(side="left")
        ttk.Entry(period, textvariable=start, width=12).pack(side="left", padx=6)
        ttk.Label(period, text="Hasta:").pack(side="left")
        ttk.Entry(period, textvariable=end, width=12).pack(side="left", padx=6)
        ttk.Label(period, text="día/mes/año").pack(side="left", padx=6)
        ttk.Label(dialog, text="Comparación que se incluirá:").pack(
            anchor="w", padx=18, pady=(12, 4)
        )
        labels = ["Sin comparación"] + [
            datetime.fromisoformat(c["live_previous_date"]).strftime("%d/%m/%Y %H:%M")
            + " → "
            + datetime.fromisoformat(c["live_current_date"]).strftime("%d/%m/%Y %H:%M")
            + (" · recalcular" if c["stale_dates"] else "")
            for c in self.saved_comparisons
        ]
        comparison = ttk.Combobox(dialog, values=labels, state="readonly", width=57)
        comparison.pack(fill="x", padx=18, pady=4)
        selected = self.comparisons.selection()
        current_id = (
            (selected[0] if selected else None)
            if self.tabs.index("current") == 1
            else (
                self.comparison_result_id if self.workspace_mode == "compare" else None
            )
        )
        comparison.current(
            next(
                (
                    i + 1
                    for i, c in enumerate(self.saved_comparisons)
                    if c["id"] == current_id
                ),
                0,
            )
        )
        detailed = tk.BooleanVar(value=False)
        explanations = tk.BooleanVar(value=False)
        followup = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            dialog,
            text="Incluir mapas de influencia disponibles de cada fotografía",
            variable=explanations,
        ).pack(anchor="w", padx=18, pady=4)
        ttk.Checkbutton(
            dialog,
            text="Incluir tablero temporal, tabla y línea de tiempo",
            variable=followup,
        ).pack(anchor="w", padx=18, pady=4)
        ttk.Checkbutton(
            dialog, text="Informe técnico: añadir controles, puntuaciones y trazabilidad", variable=detailed
        ).pack(anchor="w", padx=18, pady=4)
        from longitudinal_insights import METRICS

        selected_metric = self.selected_trend_metric() if hasattr(self, "selected_trend_metric") else "index"
        selected_mode = self.selected_trend_mode() if hasattr(self, "selected_trend_mode") else "reference"

        ttk.Label(
            dialog,
            text="El informe principal muestra el índice descriptivo cuando hay al menos dos mediciones válidas. El modo elegido en Seguimiento es: "
            + ("primera fotografía de referencia" if selected_mode == "reference" else "visitas consecutivas")
            + ". Los gráficos adicionales se incluyen en el anexo técnico.",
            wraplength=550,
        ).pack(anchor="w", padx=18, pady=(8, 2))
        ttk.Label(
            dialog,
            text="El gráfico usa comparaciones ya guardadas entre las fotos incluidas. La comparación elegida debe tener ambas fotos dentro del alcance.",
            wraplength=550,
        ).pack(anchor="w", padx=18, pady=8)
        ttk.Label(
            dialog,
            text="Informe: resumen formal, visitas y gráficos. Para examinar originales, contornos y mapas, usa la vista de comparación. El resultado no es un diagnóstico.",
            wraplength=550,
        ).pack(anchor="w", padx=18, pady=4)

        def save():
            path = filedialog.asksaveasfilename(
                parent=dialog,
                title="Guardar informe PDF",
                defaultextension=".pdf",
                filetypes=[("Informe PDF", "*.pdf")],
            )
            if not path:
                return
            try:
                index = comparison.current()
                included = (
                    selected_ids
                    if scope.get() == "selected"
                    else [r["id"] for r in self.records]
                )
                if scope.get() == "period":
                    first = datetime.strptime(start.get(), "%d/%m/%Y").date()
                    last = datetime.strptime(end.get(), "%d/%m/%Y").date()
                    if first > last:
                        raise ValueError(
                            "La fecha inicial debe ser anterior o igual a la final."
                        )
                    included = [
                        r["id"]
                        for r in self.records
                        if first
                        <= datetime.fromisoformat(r["captured_at"]).date()
                        <= last
                    ]
                if not included:
                    raise ValueError(
                        "No hay fotografías dentro del alcance seleccionado."
                    )
                selected_reference = min(
                    (r for r in self.records if r["id"] in included),
                    key=lambda r: (r["captured_at"], r["id"]),
                )["id"]
                pages = export_lesion_pdf(
                    self.store,
                    self.lesion_id,
                    path,
                    self.saved_comparisons[index - 1]["id"] if index > 0 else None,
                    record_ids=included,
                    include_explanations=explanations.get(),
                    detailed=detailed.get(),
                    include_followup=followup.get(),
                    reference_id=selected_reference,
                    metric=selected_metric,
                    trend_mode=selected_mode,
                )
                dialog.destroy()
                messagebox.showinfo(
                    "Reporte guardado",
                    f"Informe de {pages} páginas:\n{path}",
                    parent=self.window,
                )
            except Exception as exc:
                messagebox.showerror("Reporte PDF", str(exc), parent=self.window)

        ttk.Button(dialog, text="Guardar informe PDF", command=save).pack(
            anchor="e", padx=18, pady=15
        )
