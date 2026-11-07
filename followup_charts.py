"""Gráficos descriptivos compartidos por pantalla y PDF."""
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from longitudinal_insights import trend_series, date_label, finite
from longitudinal_review import visit_review_rows


def followup_figure(comparisons, records, reference_id, mode="reference", size=(10, 6)):
    fig = Figure(figsize=size, facecolor="white", constrained_layout=True)
    FigureCanvasAgg(fig)
    axes = fig.subplots(2, 2)
    for ax, metric, title, unit in ((axes[0, 0], "index", "Índice descriptivo", "/ 100"),
                                    (axes[0, 1], "area", "Área aparente", "%")):
        series = trend_series(comparisons, records, reference_id, metric, mode=mode)
        points = {p["target"]: p for p in series["points"]}
        captures = [c for c in series["captures"] if c["target"] != reference_id]
        values = [points[c["target"]]["value"] if c["target"] in points else float("nan") for c in captures]
        ax.bar(range(len(captures)), values, color="#635bdb")
        ax.set_xticks(range(len(captures)), [date_label(c["date"].isoformat()) for c in captures], rotation=25, ha="right", fontsize=7)
        ax.set_title(title, fontsize=10)
        ax.set_ylabel(unit)
        if not points:
            ax.text(.5, .5, "Sin mediciones válidas", transform=ax.transAxes, ha="center", fontsize=9)
        for i, value in enumerate(values):
            if finite(value):
                ax.annotate(f"{value:.1f}", (i, value), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=8)
    rows = visit_review_rows(comparisons, records, mode)
    names = ["Disponible", "Pendiente", "No evaluable", "Recalcular"]
    counts = [sum(r["state"] == state for r in rows) for state in ("available", "pending", "invalid", "stale")]
    axes[1, 0].bar(names, counts, color=["#39876a", "#d6a341", "#bb655e", "#8b94a3"])
    axes[1, 0].set_title("Estado de visitas", fontsize=10)
    axes[1, 0].tick_params(axis="x", labelrotation=15, labelsize=7)
    latest = next((r for r in reversed(rows) if r["state"] == "available"), None)
    components = latest["comparison"]["result"].get("index_components", {}) if latest else {}
    keys = ("area", "shape", "asymmetry", "border", "color", "texture")
    labels = ("Área", "Forma", "Asimetría", "Borde", "Color", "Textura")
    values = [components.get(k) for k in keys]
    if any(finite(v) for v in values):
        axes[1, 1].bar(labels, [v if finite(v) else float("nan") for v in values], color="#9288df")
    else:
        axes[1, 1].text(.5, .5, "Sin componentes disponibles", transform=axes[1, 1].transAxes, ha="center", fontsize=9)
    axes[1, 1].set_title("Componentes · último par válido", fontsize=10)
    axes[1, 1].set_ylabel("Escala normalizada 0–1")
    axes[1, 1].set_ylim(0, 1)
    axes[1, 1].tick_params(axis="x", labelrotation=25, labelsize=7)
    for ax in axes.flat:
        ax.grid(axis="y", alpha=.2)
        ax.set_axisbelow(True)
    return fig
