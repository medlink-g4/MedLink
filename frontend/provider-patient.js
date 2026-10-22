// =====================================================================
// Patient detail page for doctors and nurses (Sprint 3: tasks 3.3 / 3.4)
//
//   Doctor : view patient info, edit it, record + view vitals
//   Nurse  : view patient info, edit it, record + view vitals
//
// Who may edit or record is decided by the backend (permissions.py); this
// page only shows the forms. A request the server refuses comes back as a
// 403 and the message is shown.
//
// Loaded AFTER script.js and relies on its globals:
//   API_BASE_URL, authToken, currentRole, showPage(), loadProviderDashboard()
// Everything else lives inside this wrapper, so nothing here can collide with
// names used in script.js. The only global it adds is openPatientDetail().
// =====================================================================
(function () {
    const PAGE_ID = 'providerPatientDetail';
    let currentPatientId = null;

    const VITAL_FIELDS = [
        ['temperature_f', 'Temperature (°F)', '0.1'],
        ['systolic_bp', 'Systolic BP (mmHg)', '1'],
        ['diastolic_bp', 'Diastolic BP (mmHg)', '1'],
        ['heart_rate', 'Heart rate (bpm)', '1'],
        ['respiratory_rate', 'Respiratory rate (/min)', '1'],
        ['oxygen_saturation', 'Oxygen saturation (%)', '1'],
        ['weight_lb', 'Weight (lb)', '0.1'],
        ['height_in', 'Height (in)', '0.1']
    ];

    // ---------- small helpers ----------
    // All text goes in through textContent, never innerHTML, so nothing a user
    // typed into the database can turn into markup on this page.
    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function byId(id) {
        return document.getElementById(id);
    }

    function setMessage(id, text, kind) {
        const node = byId(id);
        node.textContent = text;
        node.className = 'pd-message' + (kind ? ' ' + kind : '');
    }

    function show(id, visible) {
        byId(id).classList.toggle('hidden', !visible);
    }

    function dash(value, suffix) {
        return value === null || value === undefined ? '—' : value + (suffix || '');
    }

    function localTime(utcString) {
        // The server stores UTC as 'YYYY-MM-DD HH:MM:SS'; show it in the viewer's time.
        const parsed = new Date(String(utcString).replace(' ', 'T') + 'Z');
        return Number.isNaN(parsed.getTime()) ? utcString : parsed.toLocaleString();
    }

    function bloodPressure(reading) {
        if (reading.systolic_bp === null || reading.diastolic_bp === null) return '—';
        return reading.systolic_bp + '/' + reading.diastolic_bp + ' mmHg';
    }

    async function api(path, method, body) {
        const response = await fetch(API_BASE_URL + '/api/patients/' + path, {
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
        return (result.data && result.data.error) || fallback;
    }

    // ---------- page construction (runs once) ----------
    function labelledInput(id, labelText, type, extra) {
        const wrapper = el('div', 'pd-field');
        const label = el('label', '', labelText);
        label.htmlFor = id;
        const input = el('input');
        input.id = id;
        input.type = type;
        Object.assign(input, extra || {});
        wrapper.append(label, input);
        return wrapper;
    }

    function buildPage() {
        if (byId(PAGE_ID)) return;

        const page = el('div', 'page hidden');
        page.id = PAGE_ID;
        const container = el('div', 'dashboard-container');

        const title = el('h1', '', 'Patient');
        title.id = 'pdTitle';

        // --- patient information ---
        const infoSection = el('section', 'dashboard-section pd-section');
        infoSection.id = 'pdInfoSection';
        infoSection.append(el('h2', '', 'Patient Information'));

        const info = el('dl', 'pd-info');
        info.id = 'pdInfo';

        const nurseNote = el('p', 'pd-note', 'Only doctors can edit patient information. You can record vitals below.');
        nurseNote.id = 'pdNurseNote';

        const editForm = el('form', 'pd-form');
        editForm.id = 'pdEditForm';
        const editGrid = el('div', 'pd-grid');
        editGrid.append(
            labelledInput('pdDob', 'Date of birth', 'date'),
            labelledInput('pdPhone', 'Phone', 'text', { maxLength: 30 }),
            labelledInput('pdInsurance', 'Insurance', 'text', { maxLength: 200 })
        );
        const saveButton = el('button', 'btn-primary', 'Save changes');
        saveButton.type = 'submit';
        const editMessage = el('p', 'pd-message');
        editMessage.id = 'pdInfoMsg';
        editMessage.setAttribute('role', 'status');
        editForm.append(el('h3', '', 'Edit information'), editGrid, saveButton, editMessage);

        infoSection.append(info, nurseNote, editForm);

        // --- vitals ---
        const vitalsSection = el('section', 'dashboard-section pd-section');
        vitalsSection.id = 'pdVitalsSection';
        vitalsSection.append(el('h2', '', 'Vitals'));

        const latest = el('div', 'pd-latest');
        latest.id = 'pdLatest';

        const vitalsForm = el('form', 'pd-form');
        vitalsForm.id = 'pdVitalsForm';
        vitalsForm.append(el('h3', '', 'Record new vitals'));
        const vitalsGrid = el('div', 'pd-grid');
        VITAL_FIELDS.forEach(function (spec) {
            vitalsGrid.append(labelledInput('pdv_' + spec[0], spec[1], 'number', { step: spec[2] }));
        });
        vitalsGrid.append(labelledInput('pdv_notes', 'Notes', 'text', { maxLength: 500 }));
        const vitalsButton = el('button', 'btn-primary', 'Record vitals');
        vitalsButton.type = 'submit';
        const vitalsMessage = el('p', 'pd-message');
        vitalsMessage.id = 'pdVitalsMsg';
        vitalsMessage.setAttribute('role', 'status');
        vitalsForm.append(vitalsGrid, vitalsButton, vitalsMessage);

        const history = el('div', 'pd-table-wrap');
        history.id = 'pdHistory';

        vitalsSection.append(latest, vitalsForm, el('h3', 'pd-history-title', 'History'), history);

        const back = el('button', 'btn-secondary', 'Back to dashboard');
        back.type = 'button';
        back.id = 'pdBack';

        container.append(title, infoSection, vitalsSection, back);
        page.append(container);
        document.body.append(page);

        editForm.addEventListener('submit', onSaveInfo);
        vitalsForm.addEventListener('submit', onRecordVitals);
        back.addEventListener('click', async function () {
            await loadProviderDashboard(); // pick up anything just edited
            showPage('providerDashboard');
        });
    }

    // ---------- rendering ----------
    function renderInfo(patient) {
        byId('pdTitle').textContent = patient.name;

        const info = byId('pdInfo');
        info.replaceChildren();
        [
            ['Name', patient.name],
            ['Email', patient.email],
            ['Date of birth', dash(patient.date_of_birth)],
            ['Phone', dash(patient.phone)],
            ['Insurance', dash(patient.insurance_info)]
        ].forEach(function (pair) {
            info.append(el('dt', '', pair[0]), el('dd', '', pair[1]));
        });

        byId('pdDob').value = patient.date_of_birth || '';
        byId('pdPhone').value = patient.phone || '';
        byId('pdInsurance').value = patient.insurance_info || '';
    }

    function renderVitals(data) {
        const latest = byId('pdLatest');
        const history = byId('pdHistory');
        latest.replaceChildren();
        history.replaceChildren();

        if (!data || !data.latest) {
            latest.append(el('p', 'no-data', 'No vitals recorded yet'));
            return;
        }

        const reading = data.latest;
        const card = el('div', 'appointment-card');
        card.append(el('h3', '', 'Latest reading'));
        card.append(el('p', '', 'Recorded ' + localTime(reading.recorded_at) +
            ' by ' + reading.recorded_by_name + ' (' + reading.recorded_by_role + ')'));
        card.append(el('p', '', 'Temperature: ' + dash(reading.temperature_f, ' °F') +
            '  |  BP: ' + bloodPressure(reading) +
            '  |  Heart rate: ' + dash(reading.heart_rate, ' bpm')));
        card.append(el('p', '', 'Respiratory rate: ' + dash(reading.respiratory_rate, '/min') +
            '  |  SpO₂: ' + dash(reading.oxygen_saturation, '%') +
            '  |  Weight: ' + dash(reading.weight_lb, ' lb') +
            '  |  Height: ' + dash(reading.height_in, ' in')));
        if (reading.notes) card.append(el('p', '', 'Notes: ' + reading.notes));
        latest.append(card);

        const table = el('table', 'pd-table');
        const headRow = el('tr');
        ['Recorded', 'By', 'Temp °F', 'BP', 'HR', 'RR', 'SpO₂ %', 'Weight lb', 'Height in', 'Notes']
            .forEach(function (heading) { headRow.append(el('th', '', heading)); });
        const thead = el('thead');
        thead.append(headRow);
        table.append(thead);
        const body = el('tbody');
        data.history.forEach(function (row) {
            const tr = el('tr');
            [
                localTime(row.recorded_at),
                row.recorded_by_name,
                dash(row.temperature_f),
                bloodPressure(row).replace(' mmHg', ''),
                dash(row.heart_rate),
                dash(row.respiratory_rate),
                dash(row.oxygen_saturation),
                dash(row.weight_lb),
                dash(row.height_in),
                row.notes || ''
            ].forEach(function (cell) { tr.append(el('td', '', cell)); });
            body.append(tr);
        });
        table.append(body);
        history.append(table);
    }

    // ---------- actions ----------
    async function onSaveInfo(event) {
        event.preventDefault();
        setMessage('pdInfoMsg', 'Saving…');
        const result = await api(String(currentPatientId), 'PUT', {
            date_of_birth: byId('pdDob').value || null,
            phone: byId('pdPhone').value.trim() || null,
            insurance_info: byId('pdInsurance').value.trim() || null
        });
        if (result.ok) {
            renderInfo(result.data);
            setMessage('pdInfoMsg', 'Saved.', 'ok');
        } else {
            setMessage('pdInfoMsg', errorText(result, 'Could not save changes.'), 'error');
        }
    }

    async function loadVitals() {
        const result = await api(currentPatientId + '/vitals');
        renderVitals(result.ok ? result.data : null);
        return result;
    }

    async function onRecordVitals(event) {
        event.preventDefault();
        const body = {};
        VITAL_FIELDS.forEach(function (spec) {
            const raw = byId('pdv_' + spec[0]).value.trim();
            if (raw !== '') body[spec[0]] = Number(raw);
        });
        if (Object.keys(body).length === 0) {
            setMessage('pdVitalsMsg', 'Enter at least one measurement.', 'error');
            return;
        }
        const notes = byId('pdv_notes').value.trim();
        if (notes) body.notes = notes;

        setMessage('pdVitalsMsg', 'Saving…');
        const result = await api(currentPatientId + '/vitals', 'POST', body);
        if (result.ok) {
            byId('pdVitalsForm').reset();
            await loadVitals();
            setMessage('pdVitalsMsg', 'Vitals recorded.', 'ok');
        } else {
            setMessage('pdVitalsMsg', errorText(result, 'Could not record vitals.'), 'error');
        }
    }

    // ---------- entry point (called from the patient cards in script.js) ----------
    async function openPatientDetail(patientId) {
        buildPage();
        currentPatientId = patientId;


        show('pdEditForm', true);
        show('pdNurseNote', false);
        show('pdVitalsSection', true);
        show('pdInfoSection', true);
        setMessage('pdInfoMsg', '');
        setMessage('pdVitalsMsg', '');
        byId('pdVitalsForm').reset();
        byId('pdTitle').textContent = 'Loading…';
        byId('pdInfo').replaceChildren();
        byId('pdLatest').replaceChildren();
        byId('pdHistory').replaceChildren();
        showPage(PAGE_ID);

        const results = await Promise.all([
            api(String(patientId)),
            api(patientId + '/vitals')
        ]);
        if (currentPatientId !== patientId) return; // user already opened another patient

        const patient = results[0];
        const vitals = results[1];
        if (!patient.ok) {
            byId('pdTitle').textContent = 'Patient';
            show('pdEditForm', false);
            show('pdNurseNote', false);
            show('pdVitalsSection', false);
            byId('pdInfo').replaceChildren(el('dd', 'no-data', errorText(patient, 'Could not load this patient.')));
            return;
        }
        renderInfo(patient.data);
        renderVitals(vitals.ok ? vitals.data : null);
    }

    window.openPatientDetail = openPatientDetail;
})();
