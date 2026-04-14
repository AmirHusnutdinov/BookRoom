/* ============================================================
   Утилиты
   ============================================================ */

/** Запрос к API с обработкой ошибок */
async function apiFetch(url) {
    try {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return await res.json();
    } catch (err) {
        console.error("API error:", err);
        return [];
    }
}

/** Форматирование времени HH:MM */
function formatTime(timeStr) {
    return timeStr; // уже в формате HH:MM из БД
}

/* ============================================================
   Проверка доступности комнаты (на странице бронирования)
   ============================================================ */

async function loadRoomAvailability(roomId, dateStr) {
    const container = document.getElementById("availabilitySlots");
    if (!container) return;

    container.innerHTML = '<p class="text-muted">Загрузка...</p>';

    const bookings = await apiFetch(`/api/bookings/${roomId}`);
    const dayBookings = bookings.filter(b => b.booking_date === dateStr);

    if (dayBookings.length === 0) {
        container.innerHTML = '<div class="slot-item slot-free">✅ Комната свободна весь день</div>';
        return;
    }

    // Генерируем временные слоты с 08:00 до 20:00 с шагом 30 мин
    const slots = [];
    let hour = 8;
    let minute = 0;

    while (hour < 20) {
        const slotStart = `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
        minute += 30;
        if (minute >= 60) { hour++; minute = 0; }
        const slotEnd = `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;

        const isBusy = dayBookings.some(b =>
            slotStart < b.end_time && slotEnd > b.start_time
        );

        slots.push({ start: slotStart, end: slotEnd, isBusy });
    }

    // Группируем смежные слоты одного состояния
    container.innerHTML = '';
    let groups = [];
    let currentGroup = { start: slots[0].start, end: slots[0].end, isBusy: slots[0].isBusy };

    for (let i = 1; i < slots.length; i++) {
        if (slots[i].isBusy === currentGroup.isBusy && slots[i].start === currentGroup.end) {
            currentGroup.end = slots[i].end;
        } else {
            groups.push(currentGroup);
            currentGroup = { start: slots[i].start, end: slots[i].end, isBusy: slots[i].isBusy };
        }
    }
    groups.push(currentGroup);

    groups.forEach(g => {
        const div = document.createElement("div");
        div.className = `slot-item ${g.isBusy ? 'slot-busy' : 'slot-free'}`;
        div.textContent = g.isBusy
            ? `🔴 ${g.start} — ${g.end} (занято)`
            : `🟢 ${g.start} — ${g.end} (свободно)`;
        container.appendChild(div);
    });
}

/* ============================================================
   Валидация формы бронирования на клиенте
   ============================================================ */

document.addEventListener("DOMContentLoaded", function () {
    const form = document.getElementById("bookingForm");
    if (!form) return;

    form.addEventListener("submit", function (e) {
        const start = document.getElementById("start_time").value;
        const end = document.getElementById("end_time").value;

        if (start && end && start >= end) {
            e.preventDefault();
            alert("Время окончания должно быть позже времени начала.");
        }
    });

    // Минимальная дата — сегодня
    const dateInput = document.getElementById("booking_date");
    if (dateInput) {
        const today = new Date().toISOString().split("T")[0];
        dateInput.setAttribute("min", today);
    }
});
