
const box = document.getElementById("inputs");
for (let i = 0; i < 10; i++) {
  const inp = document.createElement("input");
  inp.type = "number";
  inp.value = 0;
  box.appendChild(inp);
}


document.getElementById("sum-btn").onclick = async () => {
  const numbers = [...box.children].map((i) => Number(i.value) || 0);
  console.log(numbers)
  try {
    await py("sum_numbers", numbers);   // جواب را پایتون خودش با show() در صفحه می‌گذارد
  } catch (e) {
    applyChanges({ status: "خطا: " + e.message });
  }
};

document.getElementById("p3").onclick = async() => {
  var val = document.getElementById("p3num").value;
  if (val == ""){
    val = 0
  }
  await py("p3", val);

}

// ---- Wind rose tab -------------------------------------------------------
const wrEls = {
  city: document.getElementById("wr-city"),
  cityStart: document.getElementById("wr-city-start"),
  cityEnd: document.getElementById("wr-city-end"),
  cityBtn: document.getElementById("wr-city-btn"),
  name: document.getElementById("wr-name"),
  lat: document.getElementById("wr-lat"),
  lon: document.getElementById("wr-lon"),
  customStart: document.getElementById("wr-custom-start"),
  customEnd: document.getElementById("wr-custom-end"),
  customBtn: document.getElementById("wr-custom-btn"),
  status: document.querySelector('[data-bind="windrose_status"]'),
  stats: document.getElementById("wr-stats"),
};

const WR_DAY_MS = 24 * 60 * 60 * 1000;
const WR_DIGITS = {
  "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
  "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
  "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
  "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
};

let wrLimits = null;
let wrBusy = false;

function wrNormalizeNumber(value) {
  return String(value)
    .replace(/[۰-۹٠-٩]/g, (digit) => WR_DIGITS[digit])
    .replace(/\u066b/g, ".")
    .replace(/[\u066c,\s]/g, "");
}

function wrSetStatus(text, kind = "info") {
  if (!wrEls.status) return;
  wrEls.status.textContent = text;
  wrEls.status.dataset.kind = kind;
}

function wrSetBusy(busy) {
  wrBusy = busy;
  wrEls.cityBtn.disabled = busy;
  wrEls.customBtn.disabled = busy;
}

function wrValidateDates(start, end) {
  if (!start || !end) return "تاریخ شروع و پایان را وارد کنید.";
  const startMs = Date.parse(start + "T00:00:00Z");
  const endMs = Date.parse(end + "T00:00:00Z");
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) {
    return "تاریخ واردشده معتبر نیست.";
  }
  if (startMs > endMs) return "تاریخ شروع نباید بعد از تاریخ پایان باشد.";
  if (wrLimits) {
    if (startMs < Date.parse(wrLimits.min_date + "T00:00:00Z")) {
      return `تاریخ شروع نباید پیش از ${wrLimits.min_date} باشد.`;
    }
    if (endMs > Date.parse(wrLimits.max_date + "T00:00:00Z")) {
      return `تاریخ پایان نباید بعد از ${wrLimits.max_date} باشد.`;
    }
    if ((endMs - startMs) / WR_DAY_MS > wrLimits.max_range_days) {
      return "بازهٔ زمانی حداکثر ۱۰ سال است.";
    }
  }
  return null;
}

function wrRenderStats(rows) {
  if (!wrEls.stats) return;
  wrEls.stats.replaceChildren();
  if (!Array.isArray(rows) || rows.length === 0) return;

  const title = document.createElement("h3");
  title.textContent = "آمار";
  wrEls.stats.appendChild(title);

  for (const row of rows) {
    const line = document.createElement("div");
    line.className = "stat-row";
    const label = document.createElement("span");
    label.className = "stat-label";
    label.textContent = row.label ?? "";
    const value = document.createElement("span");
    value.className = "stat-value";
    value.textContent = row.value ?? "";
    line.append(label, value);
    wrEls.stats.appendChild(line);
  }
}

async function wrCall(request) {
  if (wrBusy) return;
  wrSetBusy(true);
  wrSetStatus("در حال ارسال درخواست…", "info");
  try {
    await request();
  } catch (error) {
    wrSetStatus("خطای غیرمنتظره: " + error.message, "error");
  } finally {
    wrSetBusy(false);
  }
}

wrEls.cityBtn.addEventListener("click", () => {
  const error = wrValidateDates(wrEls.cityStart.value, wrEls.cityEnd.value);
  if (error) {
    wrSetStatus(error, "error");
    return;
  }
  wrCall(() => py(
    "windrose_city",
    wrEls.city.value,
    wrEls.cityStart.value,
    wrEls.cityEnd.value,
  ));
});

wrEls.customBtn.addEventListener("click", () => {
  const latText = wrNormalizeNumber(wrEls.lat.value);
  const lonText = wrNormalizeNumber(wrEls.lon.value);
  if (!latText || !lonText) {
    wrSetStatus("عرض و طول جغرافیایی را وارد کنید.", "error");
    return;
  }
  const lat = Number(latText);
  const lon = Number(lonText);
  if (!Number.isFinite(lat) || lat < -90 || lat > 90) {
    wrSetStatus("عرض جغرافیایی باید یک عدد بین -90 و 90 باشد.", "error");
    return;
  }
  if (!Number.isFinite(lon) || lon < -180 || lon > 180) {
    wrSetStatus("طول جغرافیایی باید یک عدد بین -180 و 180 باشد.", "error");
    return;
  }
  const error = wrValidateDates(wrEls.customStart.value, wrEls.customEnd.value);
  if (error) {
    wrSetStatus(error, "error");
    return;
  }
  wrCall(() => py(
    "windrose_custom",
    wrEls.name.value,
    lat,
    lon,
    wrEls.customStart.value,
    wrEls.customEnd.value,
  ));
});

on("show", (changes) => {
  if (Array.isArray(changes.windrose_stats)) wrRenderStats(changes.windrose_stats);
  if (changes.windrose_status_kind) {
    wrEls.status.dataset.kind = changes.windrose_status_kind;
  }
});

(async () => {
  try {
    const info = await py("get_cities");
    wrLimits = info.limits || null;

    wrEls.city.replaceChildren();
    for (const city of info.cities || []) {
      const option = document.createElement("option");
      option.value = city.id;
      option.textContent = city.name_fa;
      wrEls.city.appendChild(option);
    }

    const dateInputs = [
      wrEls.cityStart, wrEls.cityEnd, wrEls.customStart, wrEls.customEnd,
    ];
    for (const input of dateInputs) {
      if (wrLimits) {
        input.min = wrLimits.min_date;
        input.max = wrLimits.max_date;
      }
      input.value = input.id.endsWith("-start")
        ? info.defaults.start_date
        : info.defaults.end_date;
    }
  } catch (error) {
    wrSetStatus("خطا در دریافت فهرست شهرها: " + error.message, "error");
  }
})();

// ---- Wind rose full-screen viewer ---------------------------------------
const wrImage = document.querySelector('[data-bind="windrose_image"]');
const wrExpandBtn = document.getElementById("wr-expand");
const wrLightbox = document.getElementById("wr-lightbox");
const wrLightboxImg = document.getElementById("wr-lightbox-img");
const wrLightboxClose = document.getElementById("wr-lightbox-close");

const WR_ZOOM_MIN = 1;
const WR_ZOOM_MAX = 8;
const wrZoom = { scale: 1, x: 0, y: 0 };
let wrDrag = null;

function wrApplyZoom() {
  wrLightboxImg.style.transform =
    `translate(${wrZoom.x}px, ${wrZoom.y}px) scale(${wrZoom.scale})`;
  wrLightboxImg.classList.toggle("is-zoomed", wrZoom.scale > WR_ZOOM_MIN);
}

function wrClampZoom() {
  const maxX = Math.max(0,
    (wrLightboxImg.clientWidth * wrZoom.scale - wrLightbox.clientWidth) / 2);
  const maxY = Math.max(0,
    (wrLightboxImg.clientHeight * wrZoom.scale - wrLightbox.clientHeight) / 2);
  wrZoom.x = Math.min(maxX, Math.max(-maxX, wrZoom.x));
  wrZoom.y = Math.min(maxY, Math.max(-maxY, wrZoom.y));
}

function wrResetZoom() {
  wrZoom.scale = 1;
  wrZoom.x = 0;
  wrZoom.y = 0;
  wrApplyZoom();
}

function wrOpenLightbox() {
  if (!wrImage || !wrImage.getAttribute("src")) return;
  wrLightboxImg.src = wrImage.src;
  wrLightboxImg.alt = wrImage.alt || "گلباد";
  wrLightbox.hidden = false;
  wrResetZoom();
  document.body.classList.add("lightbox-open");
  wrLightboxClose.focus();
}

function wrCloseLightbox() {
  if (!wrLightbox || wrLightbox.hidden) return;
  wrDrag = null;
  wrLightboxImg.classList.remove("is-dragging");
  wrLightbox.hidden = true;
  wrResetZoom();
  document.body.classList.remove("lightbox-open");
  wrExpandBtn.focus();
}

// Wheel zooms toward the pointer; zooming back to 1 recentres the image.
wrLightbox.addEventListener("wheel", (event) => {
  if (wrLightbox.hidden) return;
  event.preventDefault();
  const rect = wrLightbox.getBoundingClientRect();
  const cx = event.clientX - rect.left - rect.width / 2;
  const cy = event.clientY - rect.top - rect.height / 2;
  const next = Math.min(WR_ZOOM_MAX, Math.max(WR_ZOOM_MIN,
    wrZoom.scale * Math.exp(-event.deltaY * 0.0015)));
  const ratio = next / wrZoom.scale;
  wrZoom.x = cx - (cx - wrZoom.x) * ratio;
  wrZoom.y = cy - (cy - wrZoom.y) * ratio;
  wrZoom.scale = next;
  if (next === WR_ZOOM_MIN) {
    wrZoom.x = 0;
    wrZoom.y = 0;
  }
  wrClampZoom();
  wrApplyZoom();
}, { passive: false });

// Drag pans while zoomed.
wrLightboxImg.addEventListener("pointerdown", (event) => {
  if (wrZoom.scale <= WR_ZOOM_MIN) return;
  wrDrag = {
    id: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    originX: wrZoom.x,
    originY: wrZoom.y,
  };
  wrLightboxImg.setPointerCapture(event.pointerId);
  wrLightboxImg.classList.add("is-dragging");
});

wrLightboxImg.addEventListener("pointermove", (event) => {
  if (!wrDrag || event.pointerId !== wrDrag.id) return;
  wrZoom.x = wrDrag.originX + (event.clientX - wrDrag.startX);
  wrZoom.y = wrDrag.originY + (event.clientY - wrDrag.startY);
  wrClampZoom();
  wrApplyZoom();
});

function wrEndDrag(event) {
  if (!wrDrag || (event && event.pointerId !== wrDrag.id)) return;
  wrDrag = null;
  wrLightboxImg.classList.remove("is-dragging");
}

wrLightboxImg.addEventListener("pointerup", wrEndDrag);
wrLightboxImg.addEventListener("pointercancel", wrEndDrag);
wrLightboxImg.addEventListener("dragstart", (event) => event.preventDefault());

// Double click toggles between fit and 2.5x.
wrLightboxImg.addEventListener("dblclick", () => {
  if (wrZoom.scale > WR_ZOOM_MIN) {
    wrResetZoom();
    return;
  }
  wrZoom.scale = 2.5;
  wrZoom.x = 0;
  wrZoom.y = 0;
  wrClampZoom();
  wrApplyZoom();
});

wrExpandBtn.addEventListener("click", wrOpenLightbox);
wrImage.addEventListener("click", wrOpenLightbox);
wrLightboxClose.addEventListener("click", wrCloseLightbox);
wrLightbox.addEventListener("click", (event) => {
  if (event.target === wrLightbox) wrCloseLightbox();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") wrCloseLightbox();
});

