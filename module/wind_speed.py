import math
import os

import matplotlib.pyplot as plt
import numpy as np


def main(elevation, speed, gap, start_range, end_range):

    elevates = list(range(start_range, end_range + 1, gap))

    if elevates[-1] != end_range:
        elevates.append(end_range)

    speeds = [calc(speed, elevation, e) for e in elevates]
    nemoodar(
        speed, elevation, elevates, speeds, "first.png", gap, start_range, end_range
    )
    elevates = list(map(math.log10, elevates))
    speeds = list(map(math.log10, speeds))
    nemoodar(
        math.log10(speed),
        math.log10(elevation),
        elevates,
        speeds,
        "second.png",
        gap,
        start_range,
        end_range,
    )


def nemoodar(
    initial_speed,
    initial_elevation,
    elevates,
    speeds,
    name,
    gap,
    start_range,
    end_range,
):

    save_dir = os.path.abspath("assets/speeds")
    # ساخت پوشه در صورت نبودن
    os.makedirs(save_dir, exist_ok=True)

    x = np.array(elevates)
    y = np.array(speeds)

    plt.figure(figsize=(10, 6))

    # رسم خط اصلی
    plt.plot(x, y, color="blue", linestyle="-", label="خط سرعت باد")

    # نمایش نقاط اصلی
    plt.scatter(x, y, color="blue", s=35, zorder=3)

    # نمایش فقط مقدار Y بالای هر نقطه
    for xi, yi in zip(x, y):
        plt.annotate(
            f"{yi:.2f}",
            (xi, yi),
            xytext=(0, 7),
            textcoords="offset points",
            ha="center",
            fontsize=8,
        )

    # نمایش نقطه دلخواه
    plt.scatter(
        initial_elevation,
        initial_speed,
        color="red",
        s=100,
        marker="o",
        label="نقطه‌ی اولیه",
        zorder=10,
    )

    # نمایش مقدار Y نقطه دلخواه
    plt.annotate(
        f"{initial_speed}",
        (initial_elevation, initial_speed),
        xytext=(0, 10),
        textcoords="offset points",
        ha="center",
        color="red",
        fontsize=9,
    )

    # تنظیم محور X
    plt.xlim(start_range - gap * 0.3, end_range + gap * 0.3)

    ticks = list(plt.xticks()[0])
    ticks.extend([start_range, end_range])
    plt.xticks(sorted(set(ticks)))  # pyright: ignore[reportArgumentType]

    # تنظیم خودکار محور Y با توجه به تمام نقاط
    all_y = np.append(y, initial_speed)
    y_min = np.min(all_y)
    y_max = np.max(all_y)

    margin = (y_max - y_min) * 0.1

    if margin == 0:
        margin = 1

    plt.ylim(y_min - margin, y_max + margin)

    # تنظیمات نهایی
    plt.xlabel("Elevation")
    plt.ylabel("Speed")
    plt.title("سرعت باد")

    plt.grid(True, linestyle="--", alpha=0.5)
    plt.legend()
    plt.tight_layout()

    # مسیر فایل
    save_path = os.path.join(save_dir, name)

    # ذخیره نمودار
    plt.savefig(save_path, dpi=300, bbox_inches="tight")


def calc(initial_speed, initial_elevation, second_elevation) -> int:
    return initial_speed / ((initial_elevation / second_elevation) ** 0.14)


if __name__ == "__main__":
    main(10, 5, 10, 10, 100)
