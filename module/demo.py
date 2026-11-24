"""Demo tab handlers moved out of main.py to keep the entry point logic-free."""

from pathlib import Path

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from bridge import expose, image, show

ROOT = Path(__file__).resolve().parent.parent
CHART_PATH = ROOT / "assets" / "numbers_chart.png"


@expose
def sum_numbers(numbers):
    """Sum the ten demo inputs and redraw the sample bar chart."""
    total = 0
    for n in numbers:
        total = total + n

    show(result=total, status="جمع محاسبه شد ✔")

    fig = Figure(figsize=(10, 6), dpi=150)
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    bars = ax.bar(range(1, 11), numbers, color="steelblue", edgecolor="black")
    for bar, num in zip(bars, numbers):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            f"{num:g}",
            ha="center",
            va="bottom",
            fontsize=10,
        )

    ax.set_xlabel("شماره عدد")
    ax.set_ylabel("مقدار")
    ax.set_title("نمودار اندازه ۱۰ عدد ورودی")
    ax.set_xticks(range(1, 11))
    ax.axhline(0, color="black", linewidth=0.8)
    fig.savefig(CHART_PATH, dpi=150, bbox_inches="tight")
    fig.clear()
    show(logo=image(str(CHART_PATH)))


@expose
def p3(val):
    """Return the demo number plus three."""
    show(p3e=int(val) + 3)


_initial = {
    "title": "HI, 👋",
    "description": "این متن و عکس از پایتون فرستاده شده است.",
}
if CHART_PATH.exists():
    _initial["logo"] = image(str(CHART_PATH))
show(**_initial)
