// =====================================================================
// My Profile page (Sprint 4: task 4.1)
//
// Fills in the placeholder #profile page for every role:
//   everyone  : name, email, change password
//   patient   : + date of birth, phone, insurance
//   doctor / nurse : + specialty
//
// Talks to /api/users/me and /api/users/me/password. The backend decides what
// each role may change; this page only decides what to show.
//
// Loaded AFTER script.js and relies on its globals:
//   API_BASE_URL, authToken, currentRole, currentUser, showPage()
// Everything else lives inside this wrapper, so nothing here can collide with
// names used in script.js, and script.js itself needs no changes: this file
// listens for the same sidebar "Profile" click and the same Back button.
// =====================================================================
(function () {
    const PAGE_ID = 'profile';
    let built = false;

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
    function field(id, labelText, type, extra) {
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
    function setMessage(id, text, kind) {
        const node = byId(id);
        node.textContent = text;
        node.className = 'pd-message' + (kind ? ' ' + kind : '');
    }
    function show(id, visible) {
        byId(id).classList.toggle('hidden', !visible);
    }
    async function api(path, method, body) {
        const response = await fetch(API_BASE_URL + '/api/users/' + path, {
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

    // ---------- page construction (runs once) ----------
    function build() {
        if (built) return;
        const container = document.querySelector('#' + PAGE_ID + ' .dashboard-container');
        const backButton = byId('backBtn3');
        if (!container || !backButton) return;
        built = true;

        // Remove the "(In development)" placeholder text.
        container.querySelectorAll('p').forEach(function (p) { p.remove(); });

        // --- account details ---
        const infoSection = el('section', 'dashboard-section pd-section');
        infoSection.append(el('h2', '', 'My Account'));
        const roleLine = el('p', 'pd-note', '');
        roleLine.id = 'pfRole';
        roleLine.style.marginBottom = '12px';

        const form = el('form', 'pd-form');
        form.id = 'pfForm';
        const grid = el('div', 'pd-grid');
        grid.append(
            field('pfName', 'Name', 'text', { maxLength: 100, required: true }),
            field('pfEmail', 'Email', 'email', { maxLength: 254, required: true })
        );
        const patientGrid = el('div', 'pd-grid');
        patientGrid.id = 'pfPatientFields';
        patientGrid.append(
            field('pfDob', 'Date of birth', 'date'),
            field('pfPhone', 'Phone', 'text', { maxLength: 30 }),
            field('pfInsurance', 'Insurance', 'text', { maxLength: 200 })
        );
        const providerGrid = el('div', 'pd-grid');
        providerGrid.id = 'pfProviderFields';
        providerGrid.append(field('pfSpecialty', 'Specialty', 'text', { maxLength: 100 }));

        const save = el('button', 'btn-primary', 'Save changes');
        save.type = 'submit';
        const message = el('p', 'pd-message');
        message.id = 'pfMsg';
        message.setAttribute('role', 'status');
        form.append(grid, patientGrid, providerGrid, save, message);
        infoSection.append(roleLine, form);

        // --- password ---
        const passwordSection = el('section', 'dashboard-section pd-section');
        passwordSection.append(el('h2', '', 'Change Password'));
        const pwForm = el('form', 'pd-form');
        pwForm.id = 'pfPwForm';
        const pwGrid = el('div', 'pd-grid');
        pwGrid.append(
            field('pfCurrentPw', 'Current password', 'password', { autocomplete: 'current-password', required: true }),
            field('pfNewPw', 'New password (8+ characters)', 'password', { autocomplete: 'new-password', required: true, minLength: 8, maxLength: 128 }),
            field('pfConfirmPw', 'Confirm new password', 'password', { autocomplete: 'new-password', required: true })
        );
        const pwButton = el('button', 'btn-primary', 'Change password');
        pwButton.type = 'submit';
        const pwMessage = el('p', 'pd-message');
        pwMessage.id = 'pfPwMsg';
        pwMessage.setAttribute('role', 'status');
        pwForm.append(pwGrid, pwButton, pwMessage);
        passwordSection.append(pwForm);

        container.insertBefore(infoSection, backButton);
        container.insertBefore(passwordSection, backButton);

        form.addEventListener('submit', onSaveProfile);
        pwForm.addEventListener('submit', onChangePassword);
    }

    // ---------- rendering ----------
    function render(profile) {
        byId('pfName').value = profile.name || '';
        byId('pfEmail').value = profile.email || '';
        byId('pfRole').textContent = 'Signed in as ' + profile.role + '.';

        const isPatient = profile.role === 'patient';
        show('pfPatientFields', isPatient);
        show('pfProviderFields', !isPatient);
        if (isPatient) {
            const patient = profile.patient || {};
            byId('pfDob').value = patient.date_of_birth || '';
            byId('pfPhone').value = patient.phone || '';
            byId('pfInsurance').value = patient.insurance_info || '';
        } else {
            const provider = profile.provider || {};
            byId('pfSpecialty').value = provider.specialty || '';
        }
    }

    // ---------- actions ----------
    async function openProfile() {
        build();
        if (!built) return;
        setMessage('pfMsg', '');
        setMessage('pfPwMsg', '');
        byId('pfPwForm').reset();
        setMessage('pfMsg', 'Loading…');
        const result = await api('me');
        if (!result.ok) {
            setMessage('pfMsg', errorText(result, 'Could not load your profile.'), 'error');
            return;
        }
        render(result.data);
        setMessage('pfMsg', '');
    }

    async function onSaveProfile(event) {
        event.preventDefault();
        const body = {
            name: byId('pfName').value.trim(),
            email: byId('pfEmail').value.trim()
        };
        if (currentRole === 'patient') {
            body.date_of_birth = byId('pfDob').value || null;
            body.phone = byId('pfPhone').value.trim() || null;
            body.insurance_info = byId('pfInsurance').value.trim() || null;
        } else {
            body.specialty = byId('pfSpecialty').value.trim() || null;
        }
        setMessage('pfMsg', 'Saving…');
        const result = await api('me', 'PUT', body);
        if (!result.ok) {
            setMessage('pfMsg', errorText(result, 'Could not save changes.'), 'error');
            return;
        }
        render(result.data);
        // The welcome banners show currentUser.name, which login set to the
        // email address, so keep it in step with an email change.
        if (typeof currentUser !== 'undefined' && currentUser) {
            currentUser.name = result.data.email;
        }
        setMessage('pfMsg', 'Saved.', 'ok');
    }

    async function onChangePassword(event) {
        event.preventDefault();
        const current = byId('pfCurrentPw').value;
        const next = byId('pfNewPw').value;
        const confirm = byId('pfConfirmPw').value;
        if (next !== confirm) {
            setMessage('pfPwMsg', 'The new passwords do not match.', 'error');
            return;
        }
        setMessage('pfPwMsg', 'Saving…');
        const result = await api('me/password', 'POST', {
            current_password: current,
            new_password: next
        });
        if (!result.ok) {
            setMessage('pfPwMsg', errorText(result, 'Could not change the password.'), 'error');
            return;
        }
        byId('pfPwForm').reset(); // never leave passwords sitting in the fields
        setMessage('pfPwMsg', 'Password changed.', 'ok');
    }

    // ---------- wiring ----------
    function wire() {
        // Sidebar "Profile" link: script.js already shows the page; we load it.
        document.querySelectorAll('.nav-link[data-page="' + PAGE_ID + '"]').forEach(function (link) {
            link.addEventListener('click', openProfile);
        });

        // script.js sends this Back button to the patient dashboard for every
        // role, which would strand a doctor or nurse on a stale patient page.
        // Our listener runs after script.js's, so for providers it wins.
        byId('backBtn3').addEventListener('click', function () {
            if (currentRole === 'doctor' || currentRole === 'nurse') {
                showPage('providerDashboard');
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', wire);
    } else {
        wire();
    }
})();