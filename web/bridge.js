// ---- ماژول ارتباط (معمولاً لازم نیست دستش بزنی) ----

// صدا زدن تابع پایتون:  const r = await py("sum_numbers", [1,2,3]);
async function py(name, ...args) {
  const res = await fetch("/_call", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, args }),
  });
  const data = await res.json();
  if (!data.ok) throw new Error(data.error);
  return data.result;
}

// گرفتن پیام دلخواه از پایتون:  on("my_event", data => {...})
const _listeners = {};
function on(event, fn) {
  (_listeners[event] = _listeners[event] || []).push(fn);
}

// اعمال تغییرات: فقط کلیدهایی که پایتون فرستاده عوض می‌شوند
function applyChanges(values) {
  for (const [key, val] of Object.entries(values)) {
    document.querySelectorAll(`[data-bind="${CSS.escape(key)}"]`).forEach((el) => {
      if (el.tagName === "IMG") el.src = val;
      else if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") el.value = val;
      else el.textContent = typeof val === "object" ? JSON.stringify(val) : val;
    });
  }
}
on("show", applyChanges);

// خواندن فایل عکس کاربر برای فرستادن به پایتون:  const url = await fileToDataURL(input.files[0]);
function fileToDataURL(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = reject;
    r.readAsDataURL(file);
  });
}

// اتصال زنده به پایتون
const _events = new EventSource("/_events");
_events.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  (_listeners[msg.event] || []).forEach((fn) => fn(msg.data));
};
