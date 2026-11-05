// =====================================================================
// Manage Appointments page (Sprint 4: task 4.2)
//
// A live view of the caller's real appointments with reschedule and cancel:
//   patient : their own appointments
//   nurse   : appointments they assist on
//   doctor  : the same list, read only (the backend refuses doctor changes)
//
// Talks to /api/appointments (list, PUT /<id>, POST /<id>/cancel) and
// /api/appointments/availability. The backend decides who may do what and
// enforces every booking rule; this page only decides what to show.
//
// Loaded AFTER script.js and relies on its globals:
//   API_BASE_URL, authToken, currentRole, showPage()
// Everything else lives inside this wrapper so it cannot collide with names
// used in script.js, and script.js itself needs no changes.
// =====================================================================
(function () {
    const PAGE_ID = 'appointmentManager';
    const CAN_CHANGE = { patient: true, nurse: true, doctor: false };

    let appointments = [];
    let editingId = null;      // appointment whose reschedule form is open
    let confirmingId = null;   // appointment waiting for "yes, cancel"
    let availabilityRequest = 0;

    // ---------- small helpers ----------
    // All text goes in through textContent / .value, never innerHTML.
    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }
    function byId(id) {
        return document.getElementById(id);
    }
    function button(label, className, onClick) {
        const b = el('button', className, label);
        b.type = 'button';
        b.style.marginRight = '8px';
        b.addEventListener('click', onClick);
        return b;
    }
    function setMessage(node, text, kind) {
        node.textContent = text;
        node.className = 'pd-message' + (kind ? ' ' + kind : '');
    }
    async function api(path, method, body) {
        const response = await fetch(API_BASE_URL + '/api/appointments' + path, {
            method: method || 'GET',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + authToken
            },
            body: body === undefined ? undefined : JSON.stringify(body)
        });
        let data = null;
        try {
            data = await response.json();
        } catch (err) {
            // body was not JSON; leave data null
        }
        return { ok: response.ok, status: response.status, data: data };
    }
    function errorText(result, fallback) {
        if (result.status === 401) return 'Your session has expired. Please log out and log in again.';
        return (result.data && result.data.error) || fallback;
    }

    // "2026-10-15T09:30" -> local Date (no timezone shifting)
    function parseTime(text) {
        const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(text || '');
        if (!m) return null;
        return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
    }
    function dateLabel(date) {
        return date.toLocaleDateString(undefined, {
            weekday: 'short', month: 'short', day: 'numeric', year: 'numeric'
        });
    }
    function timeLabel(date) {
        return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    }
    function dayString(date) {
        const mm = String(date.getMonth() + 1).padStart(2, '0');
        const dd = String(date.getDate()).padStart(2, '0');
        return date.getFullYear() + '-' + mm + '-' + dd;
    }

    // ---------- page ----------
    function body() {
        return byId('amBody');
    }
    function flash(text, kind) {
        setMessage(byId('amMsg'), text, kind);
    }

    function isUpcoming(appt) {
        const start = parseTime(appt.appointment_time);
        return appt.status === 'scheduled' && start !== null && start >= new Date();
    }

    function render() {
        const root = body();
        root.replaceChildren();

        const upcoming = appointments.filter(isUpcoming)
            .sort((a, b) => a.appointment_time.localeCompare(b.appointment_time));
        const history = appointments.filter(a => !isUpcoming(a))
            .sort((a, b) => b.appointment_time.localeCompare(a.appointment_time));

        const upSection = el('section', 'dashboard-section');
        upSection.append(el('h2', '', 'Upcoming'));
        if (upcoming.length === 0) {
            upSection.append(el('p', 'no-data', 'No upcoming appointments'));
        }
        upcoming.forEach(a => upSection.append(card(a, true)));
        root.append(upSection);

        const histSection = el('section', 'dashboard-section');
        histSection.append(el('h2', '', 'Past and cancelled'));
        if (history.length === 0) {
            histSection.append(el('p', 'no-data', 'Nothing here yet'));
        }
        history.forEach(a => histSection.append(card(a, false)));
        root.append(histSection);

        if (!CAN_CHANGE[currentRole]) {
            root.append(el('p', 'pd-note',
                'Doctors can view appointments here. Patients and nurses book and change them.'));
        }
    }

    function card(appt, upcoming) {
        const node = el('div', 'appointment-card');
        node.dataset.id = String(appt.id);
        const start = parseTime(appt.appointment_time);

        node.append(el('h3', '', start ? dateLabel(start) + ' at ' + timeLabel(start)
            : appt.appointment_time));
        if (currentRole === 'patient') {
            node.append(el('p', '', 'With: ' + (appt.provider_name || 'Provider #' + appt.provider_id)));
        } else {
            node.append(el('p', '', 'Patient: ' + (appt.patient_name || 'Patient #' + appt.patient_id)));
            node.append(el('p', '', 'Provider: ' + (appt.provider_name || 'Provider #' + appt.provider_id)));
        }
        node.append(el('p', '', 'Reason: ' + (appt.reason || 'Not given')));
        node.append(el('p', '', 'Status: ' + appt.status));

        if (!upcoming || !CAN_CHANGE[currentRole]) return node;

        if (confirmingId === appt.id) {
            node.append(el('p', 'pd-note', 'Cancel this appointment? This cannot be undone.'));
            node.append(
                button('Yes, cancel it', 'btn-primary', () => doCancel(appt)),
                button('Keep it', 'btn-secondary', () => { confirmingId = null; render(); })
            );
        } else if (editingId === appt.id) {
            node.append(editor(appt));
        } else {
            node.append(
                button('Reschedule', 'btn-secondary', () => {
                    editingId = appt.id; confirmingId = null; flash(''); render();
                    loadSlots(appt, dayString(start));
                }),
                button('Cancel appointment', 'btn-secondary', () => {
                    confirmingId = appt.id; editingId = null; flash(''); render();
                })
            );
        }
        return node;
    }

    // ---------- reschedule editor ----------
    function editor(appt) {
        const start = parseTime(appt.appointment_time);
        const form = el('form', 'pd-form');
        form.dataset.editor = String(appt.id);

        const dateField = el('div', 'pd-field');
        const dateLabelNode = el('label', '', 'New date');
        const dateInput = el('input');
        dateInput.type = 'date';
        dateInput.id = 'amDate';
        dateInput.required = true;
        dateInput.min = dayString(new Date());
        dateInput.value = dayString(start);
        dateLabelNode.htmlFor = 'amDate';
        dateField.append(dateLabelNode, dateInput);

        const slots = el('div', 'time-slots');
        slots.id = 'amSlots';

        const reasonField = el('div', 'pd-field');
        const reasonLabel = el('label', '', 'Reason (optional)');
        const reasonInput = el('input');
        reasonInput.type = 'text';
        reasonInput.id = 'amReason';
        reasonInput.maxLength = 500;
        reasonInput.value = appt.reason || '';
        reasonLabel.htmlFor = 'amReason';
        reasonField.append(reasonLabel, reasonInput);

        const msg = el('p', 'pd-message');
        msg.id = 'amEditMsg';
        msg.setAttribute('role', 'status');

        const save = el('button', 'btn-primary', 'Save changes');
        save.type = 'submit';
        const close = button('Close', 'btn-secondary', () => { editingId = null; render(); });

        form.append(dateField, el('p', 'pd-note', 'Pick a free time:'), slots, reasonField, save, close, msg);
        dateInput.addEventListener('change', () => loadSlots(appt, dateInput.value));
        form.addEventListener('submit', event => { event.preventDefault(); doSave(appt); });
        return form;
    }

    async function loadSlots(appt, day) {
        const slots = byId('amSlots');
        if (!slots) return;
        const ticket = ++availabilityRequest;
        slots.replaceChildren(el('p', 'pd-note', 'Loading times…'));
        delete slots.dataset.selected;
        if (!day) { slots.replaceChildren(); return; }

        const result = await api('/availability?provider_id=' + encodeURIComponent(appt.provider_id)
            + '&date=' + encodeURIComponent(day));
        // A newer request (another date) or a closed editor makes this stale.
        if (ticket !== availabilityRequest || editingId !== appt.id || !byId('amSlots')) return;
        slots.replaceChildren();
        if (!result.ok) {
            setMessage(byId('amEditMsg'), errorText(result, 'Could not load free times.'), 'error');
            return;
        }
        setMessage(byId('amEditMsg'), '');

        // The appointment's own slot reads as "booked" to the availability
        // check, so offer it back on its own date as the current choice.
        const free = result.data.available.slice();
        if ((appt.appointment_time || '').slice(0, 10) === day && !free.includes(appt.appointment_time)) {
            free.push(appt.appointment_time);
            free.sort();
        }
        if (free.length === 0) {
            slots.append(el('p', 'no-data', 'No free times on this date'));
            return;
        }
        free.forEach(value => {
            const when = parseTime(value);
            const isCurrent = value === appt.appointment_time;
            const b = button(timeLabel(when) + (isCurrent ? ' (current)' : ''), 'time-slot-btn', () => {
                slots.querySelectorAll('.time-slot-btn').forEach(x => {
                    x.classList.remove('active');
                    x.setAttribute('aria-pressed', 'false');
                });
                b.classList.add('active');
                b.setAttribute('aria-pressed', 'true');
                slots.dataset.selected = value;
            });
            b.setAttribute('aria-pressed', 'false');
            b.dataset.time = value;
            slots.append(b);
        });
    }

    // ---------- actions ----------
    async function load() {
        const root = body();
        root.replaceChildren(el('p', 'pd-note', 'Loading…'));
        flash('');
        editingId = null;
        confirmingId = null;
        const result = await api('');
        if (!result.ok) {
            root.replaceChildren();
            flash(errorText(result, 'Could not load your appointments.'), 'error');
            return;
        }
        appointments = result.data;
        render();
    }

    async function doSave(appt) {
        const msg = byId('amEditMsg');
        const picked = byId('amSlots').dataset.selected;
        const reasonText = byId('amReason').value.trim();
        const changes = {};
        if (picked && picked !== appt.appointment_time) changes.appointment_time = picked;
        if (reasonText !== (appt.reason || '')) changes.reason = reasonText || null;
        if (Object.keys(changes).length === 0) {
            setMessage(msg, 'Nothing to save. Pick a different time or change the reason.', 'error');
            return;
        }
        setMessage(msg, 'Saving…');
        const result = await api('/' + appt.id, 'PUT', changes);
        if (!result.ok) {
            if (result.status === 409) {
                // Someone else took the time first. Refresh the free times so
                // the stale choice disappears.
                const day = byId('amDate').value;
                await loadSlots(appt, day);
                setMessage(byId('amEditMsg'), 'That time is no longer free. Please pick another.', 'error');
                return;
            }
            setMessage(msg, errorText(result, 'Could not save changes.'), 'error');
            return;
        }
        await load();
        flash('Appointment updated.', 'ok');
    }

    async function doCancel(appt) {
        const result = await api('/' + appt.id + '/cancel', 'POST');
        if (!result.ok) {
            confirmingId = null;
            render();
            flash(errorText(result, 'Could not cancel the appointment.'), 'error');
            return;
        }
        await load();
        flash('Appointment cancelled.', 'ok');
    }

    // ---------- wiring ----------
    function wire() {
        document.querySelectorAll('.nav-link[data-page="' + PAGE_ID + '"]').forEach(link => {
            link.addEventListener('click', load);
        });
        const back = byId('amBackBtn');
        if (back) {
            back.addEventListener('click', () => {
                showPage(currentRole === 'doctor' || currentRole === 'nurse'
                    ? 'providerDashboard' : 'patientDashboard');
            });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', wire);
    } else {
        wire();
    }
})();