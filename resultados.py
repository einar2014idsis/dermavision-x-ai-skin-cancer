"""Gráficos de un experimento guardado; nunca vuelve a entrenar el modelo."""

import csv
import json
from collections import Counter
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    roc_curve,
    roc_auc_score,
)
from PIL import Image, ImageOps


def read_experiment(folder):
    folder = Path(folder)

    def table(name):
        with (folder / name).open(encoding="utf-8", newline="") as stream:
            return list(csv.DictReader(stream))

    config = json.loads((folder / "config.json").read_text(encoding="utf-8"))
    if config.get("class_mapping") != {"benign": 0, "malignant": 1}:
        raise ValueError(
            "Mapeo de clases incompatible: requiere benign=0 y malignant=1."
        )
    threshold = float(config["threshold"])
    if not 0 <= threshold <= 1:
        raise ValueError("Umbral inválido.")
    predictions, history, manifest = (
        table("test_predictions.csv"),
        table("history.csv"),
        table("manifest.csv"),
    )
    labels = np.array([int(r["label"]) for r in predictions])
    scores = np.array([float(r["score"]) for r in predictions])
    if (
        set(labels) != {0, 1}
        or not np.isfinite(scores).all()
        or np.any((scores < 0) | (scores > 1))
    ):
        raise ValueError(
            "Se necesitan ambas clases y puntuaciones finitas entre 0 y 1."
        )
    expected = {r["path"]: int(r["label"]) for r in manifest if r["split"] == "test"}
    actual = {r["path"]: int(r["label"]) for r in predictions}
    if expected != actual or len(actual) != len(predictions):
        raise ValueError("Las predicciones no coinciden con el test del manifiesto.")
    if not history:
        raise ValueError("Historial de entrenamiento vacío.")
    return dict(
        folder=folder,
        config=config,
        threshold=threshold,
        predictions=predictions,
        history=history,
        manifest=manifest,
        labels=labels,
        scores=scores,
        classes=(scores >= threshold).astype(int),
    )


def make_figures(data):
    figures = {}
    colors = ["#168e85", "#bd4666"]
    names = ["Benigna (0)", "Maligna (1)"]

    def figure(title):
        f = Figure(figsize=(10, 5.5), dpi=100, layout="constrained")
        f.suptitle(title, fontsize=14, fontweight="bold")
        return f

    f = figure("Datos utilizados · imágenes, no pacientes")
    ax, pie = f.subplots(1, 2)
    splits = ["train", "validation", "test"]
    counts = Counter((r["split"], int(r["label"])) for r in data["manifest"])
    for label in (0, 1):
        bars = ax.bar(
            np.arange(3) + (label - 0.5) * 0.35,
            [counts[s, label] for s in splits],
            0.35,
            label=names[label],
            color=colors[label],
        )
        ax.bar_label(bars)
    ax.set_xticks(range(3), ["Entrenamiento", "Validación", "Test"])
    ax.set_ylabel("Número de imágenes")
    ax.legend()
    totals = [sum(counts[s, label] for s in splits) for label in (0, 1)]
    pie.pie(totals, labels=names, autopct="%1.1f%%", colors=colors)
    pie.set_title(f"Etiquetas del conjunto · n={sum(totals)}")
    figures["Datos"] = f

    f = figure("Evolución real del entrenamiento")
    axes = f.subplots(1, 2)
    epochs = [int(r["epoch"]) + 1 for r in data["history"]]
    for ax, key, title in zip(
        axes,
        ["loss", "auc"],
        ["Pérdida (entropía cruzada)", "AUC registrada por Keras"],
    ):
        for prefix, label, color in [
            ("", "Entrenamiento", colors[0]),
            ("val_", "Validación", colors[1]),
        ]:
            ax.plot(
                epochs,
                [float(r[prefix + key]) for r in data["history"]],
                "o-",
                label=label,
                color=color,
            )
        ax.set(xlabel="Época", ylabel=title, xticks=epochs)
        ax.grid(alpha=0.2)
        ax.legend()
    figures["Entrenamiento"] = f

    f = figure(
        f'Evaluación en test · n={len(data["labels"])} · umbral {data["threshold"]:.2f}'
    )
    ax, roc = f.subplots(1, 2)
    matrix = confusion_matrix(data["labels"], data["classes"], labels=[0, 1])
    ax.imshow(matrix, cmap="Blues")
    ax.set(
        xticks=[0, 1],
        yticks=[0, 1],
        xticklabels=names,
        yticklabels=names,
        xlabel="Clase predicha",
        ylabel="Etiqueta del conjunto",
        title="Matriz de confusión",
    )
    for row in (0, 1):
        for col in (0, 1):
            ax.text(
                col,
                row,
                str(matrix[row, col]),
                ha="center",
                va="center",
                fontsize=22,
                color="white" if matrix[row, col] > matrix.max() / 2 else "black",
            )
    fpr, tpr, _ = roc_curve(data["labels"], data["scores"])
    roc.plot(
        fpr,
        tpr,
        color=colors[0],
        label=f'AUC = {roc_auc_score(data["labels"], data["scores"]):.3f}',
    )
    roc.plot([0, 1], [0, 1], "--", color="gray")
    roc.set(
        xlabel="Tasa de falsos positivos",
        ylabel="Sensibilidad",
        title="Curva ROC · positiva: maligna",
        xlim=(0, 1),
        ylim=(0, 1.02),
    )
    roc.legend()
    figures["Evaluación"] = f

    f = figure("Predicciones del test · no representan prevalencia clínica")
    ax, pie = f.subplots(1, 2)
    for label in (0, 1):
        ax.hist(
            data["scores"][data["labels"] == label],
            bins=np.linspace(0, 1, 16),
            alpha=0.6,
            label=names[label],
            color=colors[label],
        )
    ax.axvline(data["threshold"], color="black", linestyle="--", label="Umbral fijo")
    ax.set(
        xlabel="Puntuación de malignidad (no calibrada)",
        ylabel="Número de imágenes",
        title="Agrupadas por etiqueta del conjunto",
    )
    ax.legend()
    pie.pie(
        np.bincount(data["classes"], minlength=2),
        labels=names,
        autopct="%1.1f%%",
        colors=colors,
    )
    pie.set_title("Distribución de clases PREDICHAS")
    figures["Predicciones"] = f
    return figures


def show_results(parent, folder):
    data = read_experiment(folder)
    figures = make_figures(data)
    window = tk.Toplevel(parent)
    window.title(f'DermaVision-X · Resultados · {data["folder"].name}')
    window.geometry("1120x800")
    window.minsize(900, 650)
    tk.Label(
        window,
        text=f'RESULTADOS DEL EXPERIMENTO  |  {data["folder"].name}',
        font=("Segoe UI", 16, "bold"),
    ).pack(pady=12)
    tk.Label(
        window,
        text="Exploratorio · Sin independencia por paciente verificada · No validado para cámara ni diagnóstico",
    ).pack()
    notebook = ttk.Notebook(window)
    notebook.pack(fill="both", expand=True, padx=12, pady=12)
    canvases = []

    def add_figure(title, fig):
        page = ttk.Frame(notebook)
        notebook.add(page, text=title)
        canvas = FigureCanvasTkAgg(fig, master=page)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        canvases.append(canvas)

    for title, fig in figures.items():
        add_figure(title, fig)
    page = ttk.Frame(notebook)
    notebook.add(page, text="Reporte")
    report = tk.Text(page, font=("Consolas", 11), wrap="word")
    report.pack(fill="both", expand=True)
    tn, fp, fn, tp = confusion_matrix(data["labels"], data["classes"]).ravel()
    report.insert(
        "end",
        classification_report(
            data["labels"],
            data["classes"],
            target_names=["Benigna (0)", "Maligna (1)"],
            digits=3,
            zero_division=0,
        ),
    )
    report.insert(
        "end",
        f'\nSensibilidad (maligna): {tp/(tp+fn):.3f}\nEspecificidad: {tn/(tn+fp):.3f}\nAUC: {roc_auc_score(data["labels"], data["scores"]):.3f}\n\nFalsos negativos: {fn} lesiones etiquetadas como malignas clasificadas como benignas.\nFalsos positivos: {fp}.\n\nPrecision = valor predictivo positivo; no es lo mismo que exactitud.\nEstas métricas se recalculan de test_predictions.csv, no de la imagen de cámara.\nEl test no se utiliza para ajustar el umbral. Los gráficos no demuestran eficacia clínica.\n\nFuentes: manifest.csv, history.csv, test_predictions.csv y config.json.\nCarpeta: {data["folder"]}',
    )
    report.configure(state="disabled")

    example = ttk.Frame(notebook)
    notebook.add(example, text="Ejemplo individual")
    ttk.Label(
        example,
        text="Selecciona una muestra del test guardado. No se vuelve a predecir ni se elige solo un acierto.",
    ).pack(pady=10)
    selected = tk.StringVar()
    choices = [
        f'{i+1}: {Path(r["path"]).name} · etiqueta {names}'
        for i, (r, names) in enumerate(
            zip(
                data["predictions"],
                ["benigna" if y == 0 else "maligna" for y in data["labels"]],
            )
        )
    ]
    combo = ttk.Combobox(
        example, textvariable=selected, values=choices, state="readonly", width=70
    )
    combo.pack()
    ef = Figure(figsize=(9, 4.5), layout="constrained")
    ec = FigureCanvasTkAgg(ef, master=example)
    ec.get_tk_widget().pack(fill="both", expand=True)
    canvases.append(ec)

    def select(event=None):
        i = combo.current()
        row = data["predictions"][i]
        ef.clear()
        try:
            with Image.open(row["path"]) as im:
                rgb = ImageOps.exif_transpose(im).convert("RGB")
            a, b = ef.subplots(1, 2)
            a.imshow(rgb)
            a.set_title(f"Original · {rgb.width} × {rgb.height}")
            b.imshow(rgb.resize((224, 224), Image.Resampling.BILINEAR))
            b.set_title("Entrada RGB · 224 × 224 · escala 0–255")
            a.axis("off")
            b.axis("off")
            pred = "maligna" if data["classes"][i] else "benigna"
            real = "maligna" if data["labels"][i] else "benigna"
            ef.suptitle(
                f'Etiqueta: {real} | Predicción guardada: {pred} | Puntuación: {data["scores"][i]:.3f}\nNo es diagnóstico. MobileNetV3 incluye su transformación de escala.'
            )
        except (OSError, ValueError) as exc:
            ef.text(0.1, 0.5, f"No se pudo abrir la imagen original:\n{exc}", wrap=True)
        ec.draw()

    combo.bind("<<ComboboxSelected>>", select)
    combo.current(0)
    select()

    def export():
        directory = filedialog.askdirectory(
            parent=window, title="Carpeta para exportar gráficos PNG"
        )
        if not directory:
            return
        from datetime import datetime

        target = Path(directory) / (
            "dermavision-graficos-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        )
        try:
            target.mkdir()
            for index, (title, fig) in enumerate(figures.items(), 1):
                fig.savefig(target / f"{index:02d}-{title}.png", dpi=180)
            messagebox.showinfo("Exportación completada", str(target), parent=window)
        except OSError as exc:
            messagebox.showerror("No se pudo exportar", str(exc), parent=window)

    ttk.Button(window, text="Exportar los cuatro gráficos a PNG", command=export).pack(
        pady=(0, 10)
    )
    window._canvases = canvases
    return window
