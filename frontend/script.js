// ===== API CONFIG =====
const API_BASE_URL = 'http://localhost:5000';
// ===== CURRENT USER STATE =====
let currentUser = null;   // { id, name, role } for display purposes
let currentRole = null;
let authToken = null;     // real JWT from /api/auth/login, used for every backend call

// ===== EXPIRED SESSIONS =====
// Every API call goes through fetch. If the server answers 401 to a call that
// carried our token, the token has expired or is invalid, so send the user back
// to the login page with a message instead of leaving them on a dead screen.
// The login request itself is skipped: its 401 just means a wrong password.
const originalFetch = window.fetch.bind(window);
window.fetch = async function (input, init) {
    const response = await originalFetch(input, init);
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    if (response.status === 401 && authToken && !url.includes('/api/auth/login')) {
        handleLogout('Your session has expired. Please log in again.');
    }
    return response;
};

// ===== SIDEBAR =====
// Each link lists the roles that may use it in data-roles. The server still
// enforces permissions; this only stops people seeing links that go nowhere.
function updateSidebar(pageId) {
    const dashboardLabel = currentRole === 'patient' ? 'Appointments' : 'Dashboard';
    // Pages that belong to a link even though they have a different id.
    const owner = {
        providerDashboard: 'patientDashboard',
        appointmentScheduling: 'patientDashboard'
    };
    const activePage = owner[pageId] || pageId;
    // Patients reach Manage Appointments from their dashboard, so highlight
    // "Appointments" while they are on it.
    const highlight = (currentRole === 'patient' && activePage === 'appointmentManager')
        ? 'patientDashboard' : activePage;

    document.querySelectorAll('#sidebar .nav-link[data-roles]').forEach(link => {
        const allowed = link.dataset.roles.split(',').includes(currentRole);
        link.classList.toggle('hidden', !allowed);
        link.classList.toggle('active', allowed && link.dataset.page === highlight);
        if (link.dataset.page === 'patientDashboard') {
            link.textContent = dashboardLabel;
        }
    });
}

// ===== DATES =====
// "2026-10-30T09:00" -> "Fri, Oct 30, 2026, 9:00 AM". Falls back to the raw
// text if it is not in that format.
function formatWhen(text) {
    const date = bookingParseTime(text);
    if (!date) return text || 'N/A';
    return `${bookingDateLabel(date)}, ${bookingTimeLabel(date)}`;
}

// ===== PAGE MANAGER =====
function showPage(pageId) {
    const allPages = document.querySelectorAll('.page');
    allPages.forEach(page => page.classList.add('hidden'));

    const selectedPage = document.getElementById(pageId);
    if (selectedPage) {
        selectedPage.classList.remove('hidden');
    }

    const sidebar = document.getElementById('sidebar');
    if (currentUser && pageId !== 'loginPage') {
        sidebar.classList.remove('hidden');
        updateSidebar(pageId);
    } else {
        sidebar.classList.add('hidden');
    }

    // Always show a patient's current appointments, whichever button led here.
    if (pageId === 'patientDashboard' && currentRole === 'patient') {
        loadPatientDashboard();
    }
}

// ===== LOGIN LOGIC (real backend call -- replaces the old mockUsers check) =====
async function handleLogin(event) {
    event.preventDefault();

    const emailInput = document.getElementById('email').value;
    const passwordInput = document.getElementById('password').value;
    const errorMessage = document.getElementById('errorMessage');
    errorMessage.textContent = '';

    try {
        const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: emailInput, password: passwordInput })
        });

        const data = await response.json();

        if (!response.ok) {
            errorMessage.textContent = data.error || 'Invalid email or password.';
            return;
        }

        // Successful login
        authToken = data.token;
        currentRole = data.role;
        // The login response has no name, so ask for the profile to greet
        // people by name. If that fails, fall back to what they typed.
        let displayName = emailInput;
        try {
            const me = await fetch(`${API_BASE_URL}/api/users/me`, {
                headers: { 'Authorization': `Bearer ${authToken}` }
            });
            if (me.ok) {
                const profile = await me.json();
                displayName = profile.name || emailInput;
            }
        } catch (err) {
            // keep the fallback name
        }
        currentUser = { id: data.userId, role: data.role, name: displayName };
        sessionStorage.setItem('authToken', authToken);
        sessionStorage.setItem('currentRole', currentRole);
        sessionStorage.setItem('currentUser', JSON.stringify(currentUser));

        if (data.role === 'patient') {
            showPage('patientDashboard');
        } else if (data.role === 'doctor' || data.role === 'nurse') {
            await loadProviderDashboard();
            showPage('providerDashboard');
        }
    } catch (err) {
        errorMessage.textContent = 'Could not reach the server. Is the backend running?';
    }
}

function handleLogout(message) {
    currentUser = null;
    currentRole = null;
    authToken = null;
    sessionStorage.removeItem('authToken');
    sessionStorage.removeItem('currentRole');
    sessionStorage.removeItem('currentUser');
    document.getElementById('loginForm').reset();
    document.getElementById('errorMessage').textContent =
        typeof message === 'string' ? message : '';
    // Clear anything the last user left on screen so the next person to log in
    // on this browser never sees it, even for a moment.
    ['appointmentsList', 'providerAppointmentsList', 'providerPatientsList',
     'providerRecordsList', 'medicalRecordsList', 'medicationsList',
     'appointmentReport', 'patientReport', 'medicalReport', 'amBody']
        .forEach(id => {
            const node = document.getElementById(id);
            if (node) node.replaceChildren();
        });
    const amMsg = document.getElementById('amMsg');
    if (amMsg) amMsg.textContent = '';
    returnToContacts();
    showPage('loginPage');
}

// ===== PATIENT DASHBOARD + BOOKING LOGIC -- REAL BACKEND =====
// Appointments come from /api/appointments, doctors from /api/providers and
// free times from /api/appointments/availability. The server decides what this
// patient may see and enforces every booking rule; this code only displays.

// Small fetch helper for the calls below. Never throws on a bad status: the
// caller looks at .ok and .status.
async function bookingApi(path, method, body) {
    const response = await fetch(`${API_BASE_URL}${path}`, {
        method: method || 'GET',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${authToken}`
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

function bookingErrorText(result, fallback) {
    if (result.status === 401) {
        return 'Your session has expired. Please log out and log in again.';
    }
    return (result.data && result.data.error) || fallback;
}

// "2026-10-15T09:30" -> local Date (no timezone shifting), or null.
function bookingParseTime(text) {
    const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(text || '');
    if (!m) return null;
    return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
}

function bookingDateLabel(date) {
    return date.toLocaleDateString(undefined, {
        weekday: 'short', month: 'short', day: 'numeric', year: 'numeric'
    });
}

function bookingTimeLabel(date) {
    return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

function bookingDayString(date) {
    const mm = String(date.getMonth() + 1).padStart(2, '0');
    const dd = String(date.getDate()).padStart(2, '0');
    return `${date.getFullYear()}-${mm}-${dd}`;
}

let patientDashboardRequest = 0;

async function loadPatientDashboard() {
    const welcome = document.getElementById('patientWelcome');
    const appointmentsList = document.getElementById('appointmentsList');

    // Show the logged-in patient's name.
    welcome.textContent = `Welcome, ${currentUser.name}`;

    // Clear cards from the previous display.
    appointmentsList.replaceChildren();
    renderEmpty(appointmentsList, 'Loading appointments...');

    // If this runs twice in a row, only the newest answer is drawn.
    const ticket = ++patientDashboardRequest;

    let result;
    try {
        result = await bookingApi('/api/appointments');
    } catch (err) {
        if (ticket !== patientDashboardRequest) return;
        appointmentsList.replaceChildren();
        renderEmpty(appointmentsList, 'Could not reach the server.');
        return;
    }
    if (ticket !== patientDashboardRequest) return;
    appointmentsList.replaceChildren();

    if (!result.ok) {
        renderEmpty(appointmentsList, bookingErrorText(result, 'Could not load appointments.'));
        return;
    }

    // Keep scheduled appointments that have not started yet, soonest first.
    const now = new Date();
    const upcomingAppointments = result.data
        .filter(appointment => {
            const start = bookingParseTime(appointment.appointment_time);
            return appointment.status === 'scheduled' && start !== null && start >= now;
        })
        .sort((a, b) => a.appointment_time.localeCompare(b.appointment_time));

    // Show a helpful message if there are no upcoming appointments.
    if (upcomingAppointments.length === 0) {
        renderEmpty(appointmentsList, 'No upcoming appointments');
        return;
    }

    // Make one card for every upcoming appointment.
    upcomingAppointments.forEach(appointment => {
        const start = bookingParseTime(appointment.appointment_time);

        const card = document.createElement('div');
        card.className = 'appointment-card';

        const doctorName = document.createElement('h3');
        doctorName.textContent = appointment.provider_name || `Provider #${appointment.provider_id}`;

        const date = document.createElement('p');
        date.textContent = `Date: ${bookingDateLabel(start)}`;

        const time = document.createElement('p');
        time.textContent = `Time: ${bookingTimeLabel(start)}`;

        const reason = document.createElement('p');
        reason.textContent = `Reason: ${appointment.reason || 'Not given'}`;

        const status = document.createElement('p');
        status.textContent = `Status: ${appointment.status}`;

        card.append(doctorName, date, time, reason, status);

        // Rescheduling and cancelling live on the Manage Appointments page.
        const manageButton = document.createElement('button');
        manageButton.type = 'button';
        manageButton.className = 'btn-secondary';
        manageButton.textContent = 'Reschedule / Cancel';
        manageButton.addEventListener('click', () => {
            const link = document.querySelector('.nav-link[data-page="appointmentManager"]');
            if (link) link.click();
        });

        card.appendChild(manageButton);
        appointmentsList.appendChild(card);
    });
}

function setBookingMessage(text) {
    document.getElementById('appointmentFormMsg').textContent = text;
}

function bookingHint(container, text) {
    container.replaceChildren();
    const hint = document.createElement('p');
    hint.className = 'no-data';
    hint.textContent = text;
    container.appendChild(hint);
}

async function loadAppointmentForm() {
    document.getElementById('appointmentForm').reset();
    document.getElementById('selectedTime').value = '';
    setBookingMessage('');

    const doctorSelect = document.getElementById('doctorSelect');
    const dateInput = document.getElementById('appointmentDate');
    const timeSlots = document.getElementById('timeSlots');

    // Today is the earliest date offered. The server still rejects past times.
    dateInput.min = bookingDayString(new Date());
    bookingHint(timeSlots, 'Choose a doctor and a date to see free times.');

    // Assigning onchange (not addEventListener) keeps this safe to run every
    // time the page opens.
    doctorSelect.onchange = refreshBookingSlots;
    dateInput.onchange = refreshBookingSlots;

    doctorSelect.replaceChildren(new Option('-- Choose a Doctor --', ''));
    try {
        const result = await bookingApi('/api/providers');
        if (!result.ok) {
            setBookingMessage(bookingErrorText(result, 'Could not load the list of doctors.'));
            return;
        }
        if (result.data.length === 0) {
            setBookingMessage('No doctors are available to book yet.');
            return;
        }
        result.data.forEach(doctor => {
            const label = doctor.specialty ? `${doctor.name} (${doctor.specialty})` : doctor.name;
            doctorSelect.appendChild(new Option(label, doctor.id));
        });

        // Nurses are optional, so a failure here must not block booking.
        const nurseSelect = document.getElementById('nurseSelect');
        nurseSelect.replaceChildren(
            new Option('Any available nurse', 'any'),
            new Option('No nurse', '')
        );
        const nurses = await bookingApi('/api/providers?role_type=nurse');
        if (nurses.ok) {
            nurses.data.forEach(nurse => {
                nurseSelect.appendChild(new Option(nurse.name, nurse.id));
            });
        }
    } catch (err) {
        setBookingMessage('Could not reach the server.');
    }
}

let bookingSlotRequest = 0;

async function refreshBookingSlots() {
    const doctorId = document.getElementById('doctorSelect').value;
    const day = document.getElementById('appointmentDate').value;
    const timeSlots = document.getElementById('timeSlots');

    document.getElementById('selectedTime').value = '';

    if (!doctorId || !day) {
        bookingHint(timeSlots, 'Choose a doctor and a date to see free times.');
        return;
    }

    // If the doctor or date changes mid-request, drop the stale answer.
    const ticket = ++bookingSlotRequest;
    bookingHint(timeSlots, 'Loading times...');

    let result;
    try {
        result = await bookingApi(
            `/api/appointments/availability?provider_id=${encodeURIComponent(doctorId)}&date=${encodeURIComponent(day)}`
        );
    } catch (err) {
        if (ticket !== bookingSlotRequest) return;
        bookingHint(timeSlots, 'Could not reach the server.');
        return;
    }
    if (ticket !== bookingSlotRequest) return;

    if (!result.ok) {
        bookingHint(timeSlots, bookingErrorText(result, 'Could not load free times.'));
        return;
    }
    if (result.data.available.length === 0) {
        bookingHint(timeSlots, 'No free times on this date. Try another day.');
        return;
    }

    timeSlots.replaceChildren();
    result.data.available.forEach(value => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'time-slot-btn';
        button.textContent = bookingTimeLabel(bookingParseTime(value));
        button.dataset.time = value;
        button.setAttribute('aria-pressed', 'false');
        button.addEventListener('click', function (e) {
            e.preventDefault();
            timeSlots.querySelectorAll('.time-slot-btn').forEach(b => {
                b.classList.remove('active');
                b.setAttribute('aria-pressed', 'false');
            });
            this.classList.add('active');
            this.setAttribute('aria-pressed', 'true');
            document.getElementById('selectedTime').value = this.dataset.time;
        });
        timeSlots.appendChild(button);
    });
}

async function handleScheduleAppointment(event) {
    event.preventDefault();

    const doctorId = document.getElementById('doctorSelect').value;
    const date = document.getElementById('appointmentDate').value;
    const time = document.getElementById('selectedTime').value;
    const reason = document.getElementById('appointmentReason').value.trim();
    const nurseValue = document.getElementById('nurseSelect').value;

    if (!doctorId || !date || !time) {
        setBookingMessage('Please select a doctor, a date, and a time.');
        return;
    }

    const submitButton = document.querySelector('#appointmentForm button[type="submit"]');
    submitButton.disabled = true;      // no double bookings from a double click
    setBookingMessage('Booking...');

    try {
        // The booking route wants the patient's id in the patients table,
        // which is not the same number as the user id kept at login.
        const me = await bookingApi('/api/users/me');
        if (!me.ok || !me.data.patient) {
            setBookingMessage(bookingErrorText(me, 'Could not look up your patient record.'));
            return;
        }

        const result = await bookingApi('/api/appointments', 'POST', {
            patient_id: me.data.patient.id,
            provider_id: Number(doctorId),
            appointment_time: time,
            reason: reason || null,
            // "any" lets the server pick a free nurse; "" means none.
            assisting_nurse_id: nurseValue === 'any' ? 'any'
                : (nurseValue === '' ? null : Number(nurseValue))
        });

        if (!result.ok) {
            if (result.status === 409) {
                // Someone else got there first: refresh the times so the
                // taken one disappears, then explain.
                await refreshBookingSlots();
                const clash = result.data && /^Patient/.test(result.data.error || '');
                setBookingMessage(clash
                    ? 'You already have an appointment at that time. Please pick another time.'
                    : 'That time was just taken. Please pick another.');
                return;
            }
            setBookingMessage(bookingErrorText(result, 'Could not book the appointment.'));
            return;
        }

        document.getElementById('appointmentForm').reset();
        setBookingMessage('');
        showPage('patientDashboard');   // reloads the list, so the new one shows
    } catch (err) {
        setBookingMessage('Could not reach the server.');
    } finally {
        submitButton.disabled = false;
    }
}

// ===== PROVIDER (DOCTOR/NURSE) DASHBOARD LOGIC -- REAL BACKEND =====
// One function serves both roles: /api/dashboard/ already returns the
// correctly scoped data for whichever role is in the JWT.
async function loadProviderDashboard() {
    const welcome = document.getElementById('providerWelcome');
    welcome.textContent = `Welcome, ${currentRole === 'doctor' ? 'Dr. ' : 'Nurse '}${currentUser.name}`;

    const appointmentsList = document.getElementById('providerAppointmentsList');
    const patientsList = document.getElementById('providerPatientsList');
    const recordsList = document.getElementById('providerRecordsList');

    appointmentsList.replaceChildren();
    patientsList.replaceChildren();
    recordsList.replaceChildren();

    try {
        const response = await fetch(`${API_BASE_URL}/api/dashboard/`, {
            headers: { 'Authorization': `Bearer ${authToken}` }
        });
        const data = await response.json();

        if (!response.ok) {
            renderEmpty(appointmentsList, data.error || 'Could not load dashboard');
            renderEmpty(patientsList, '');
            renderEmpty(recordsList, '');
            return;
        }

        renderAppointments(appointmentsList, data.appointments);
        renderPatients(patientsList, data.patients);
        renderRecords(recordsList, data.medical_records);
    } catch (err) {
        renderEmpty(appointmentsList, 'Could not reach the server.');
    }
}

// ===== REPORTS LOGIC (Sprint 4 - Task 4.3) =====
async function loadReports() {
    const appointmentReport = document.getElementById('appointmentReport');
    const patientReport = document.getElementById('patientReport');
    const medicalReport = document.getElementById('medicalReport');

    appointmentReport.replaceChildren();
    patientReport.replaceChildren();
    medicalReport.replaceChildren();

    try {
        const response = await fetch(`${API_BASE_URL}/api/reports/`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        const data = await response.json();

        if (!response.ok) {
            renderEmpty(appointmentReport, data.error || 'Could not load reports.');
            return;
        }

        // Appointment Report
        if (!data.appointments.length) {
            renderEmpty(appointmentReport, 'No appointment data available.');
        } else {
            data.appointments.forEach(appt => {
                const card = document.createElement('div');
                card.className = 'appointment-card';
                card.textContent =
                    `${appt.patient_name} | ${formatWhen(appt.appointment_time)} | ${appt.status}`;
                appointmentReport.appendChild(card);
            });
        }

        // Patient Report
        if (!data.patients.length) {
            renderEmpty(patientReport, 'No assigned patients found.');
        } else {
            data.patients.forEach(patient => {
                const card = document.createElement('div');
                card.className = 'appointment-card';
                card.textContent =
                    `${patient.name} | ${patient.email} | ${patient.phone || 'N/A'}`;
                patientReport.appendChild(card);
            });
        }

        // Medical Records Report
        if (!data.medical_records.length) {
            renderEmpty(medicalReport, 'No medical records available.');
        } else {
            data.medical_records.forEach(record => {
                const card = document.createElement('div');
                card.className = 'appointment-card';
                card.textContent =
                    `${record.patient_name} | Diagnosis: ${record.diagnosis || 'N/A'} | Prescription: ${record.prescription || 'N/A'} | Date: ${record.record_date}`;
                medicalReport.appendChild(card);
            });
        }

    } catch (error) {
        renderEmpty(appointmentReport, 'Could not connect to the server.');
    }
}

function renderEmpty(container, message) {
    if (!message) return;
    const emptyMessage = document.createElement('p');
    emptyMessage.className = 'no-data';
    emptyMessage.textContent = message;
    container.appendChild(emptyMessage);
}
/* This function loads and displays the patient's records
   and medications from Alex's API. */
async function loadMedicalHistory() {
    const recordsList = document.getElementById('medicalRecordsList');
    const medicationsList = document.getElementById('medicationsList');

    recordsList.replaceChildren();
    medicationsList.replaceChildren();

    

    try {
        const headers = {
            'Authorization': `Bearer ${authToken}`
        };

        const [recordsResponse, medicationsResponse] = await Promise.all([
            fetch(
                `${API_BASE_URL}/api/medical-records/me`,   
                { headers }
            ),
            fetch(
                `${API_BASE_URL}/api/medical-records/me/medications`,  
                { headers }
            )
        ]);

        const records = await recordsResponse.json();
        const medications = await medicationsResponse.json();

        if (!recordsResponse.ok) {
            renderEmpty(recordsList, records.error || 'Could not load medical records.');
        } else if (!Array.isArray(records) || records.length === 0) {
            renderEmpty(recordsList, 'No medical records found.');
        } else {
            records.forEach(record => {
                const card = document.createElement('div');
                card.className = 'appointment-card';

                const provider = document.createElement('h3');
                provider.textContent = record.provider_name || 'Provider';

                const diagnosis = document.createElement('p');
                diagnosis.textContent = `Diagnosis: ${record.diagnosis || 'N/A'}`;

                const prescription = document.createElement('p');
                prescription.textContent = `Prescription: ${record.prescription || 'N/A'}`;

                const date = document.createElement('p');
                date.textContent = `Date: ${record.record_date || 'N/A'}`;

                card.append(provider, diagnosis, prescription, date);
                recordsList.appendChild(card);
            });
        }

        if (!medicationsResponse.ok) {
            renderEmpty(
                medicationsList,
                medications.error || 'Could not load medications.'
            );
        } else if (!Array.isArray(medications) || medications.length === 0) {
            renderEmpty(medicationsList, 'No medications found.');
        } else {
            medications.forEach(medication => {
                const card = document.createElement('div');
                card.className = 'appointment-card';

                const name = document.createElement('h3');
                name.textContent = medication.medication || 'Medication';

                const reason = document.createElement('p');
                reason.textContent = `For: ${medication.prescribed_for || 'N/A'}`;

                const provider = document.createElement('p');
                provider.textContent = `Prescribed by: ${medication.prescribed_by || 'N/A'}`;

                const date = document.createElement('p');
                date.textContent = `Date: ${medication.prescribed_on || 'N/A'}`;

                card.append(name, reason, provider, date);
                medicationsList.appendChild(card);
            });
        }
    } catch (error) {
        renderEmpty(recordsList, 'Could not reach the server.');
        renderEmpty(medicationsList, 'Could not reach the server.');
    }
}

function renderAppointments(container, appointments) {
    if (!appointments || appointments.length === 0) {
        renderEmpty(container, 'No appointments');
        return;
    }
    appointments.forEach(appt => {
        const card = document.createElement('div');
        card.className = 'appointment-card';

        const name = document.createElement('h3');
        name.textContent = appt.patient_name;

        const time = document.createElement('p');
        time.textContent = `Time: ${formatWhen(appt.appointment_time)}`;

        const status = document.createElement('p');
        status.textContent = `Status: ${appt.status}`;

        card.append(name, time, status);
        container.appendChild(card);
    });
}

function renderPatients(container, patients) {
    if (!patients || patients.length === 0) {
        renderEmpty(container, 'No assigned patients');
        return;
    }
    patients.forEach(patient => {
        const card = document.createElement('div');
        card.className = 'appointment-card';

        const name = document.createElement('h3');
        name.textContent = patient.name;

        const email = document.createElement('p');
        email.textContent = `Email: ${patient.email}`;

        const phone = document.createElement('p');
        phone.textContent = `Phone: ${patient.phone || 'N/A'}`;

        card.append(name, email, phone);
        const viewButton = document.createElement('button');
        viewButton.type = 'button';
        viewButton.className = 'btn-secondary';
        viewButton.textContent = currentRole === 'doctor' ? 'View / Edit' : 'View / Record Vitals';
        viewButton.addEventListener('click', () => openPatientDetail(patient.id));
        card.appendChild(viewButton);
        container.appendChild(card);
    });
}

function renderRecords(container, records) {
    if (!records || records.length === 0) {
        renderEmpty(container, 'No recent medical records');
        return;
    }
    records.forEach(record => {
        const card = document.createElement('div');
        card.className = 'appointment-card';

        const name = document.createElement('h3');
        name.textContent = record.patient_name;

        const diagnosis = document.createElement('p');
        diagnosis.textContent = `Diagnosis: ${record.diagnosis || 'N/A'}`;

        const prescription = document.createElement('p');
        prescription.textContent = `Prescription: ${record.prescription || 'N/A'}`;

        const date = document.createElement('p');
        date.textContent = `Date: ${record.record_date}`;

        card.append(name, diagnosis, prescription, date);
        container.appendChild(card);
    });
}

// ===== EVENT LISTENERS =====
document.addEventListener('DOMContentLoaded', function () {
    document.getElementById('loginForm').addEventListener('submit', handleLogin);

    document.querySelector('.forgot-password').addEventListener('click', function (e) {
        e.preventDefault();
        const errorMessage = document.getElementById('errorMessage');
        errorMessage.textContent =
            'Password reset by email is not available yet. Please contact your clinic to reset your password.';
    });

    document.getElementById('scheduleNewBtn').addEventListener('click', function () {
        loadAppointmentForm();
        showPage('appointmentScheduling');
    });

    document.getElementById('appointmentForm').addEventListener('submit', handleScheduleAppointment);
    document.getElementById('cancelAppointmentBtn').addEventListener('click', function () {
        showPage('patientDashboard');
    });
document.querySelectorAll('.nav-link').forEach(link => {
    link.addEventListener('click', function (e) {
        e.preventDefault();
        let pageId = this.getAttribute('data-page');
        if (!pageId) return;

        // Keep doctor/nurse users on their own dashboard.
        if (
            pageId === 'patientDashboard' &&
            (currentRole === 'doctor' || currentRole === 'nurse')
        ) {
            pageId = 'providerDashboard';
        }

        // Reports are only available to doctors and nurses.
        if (pageId === 'reports') {
            if (currentRole === 'doctor' || currentRole === 'nurse') {
                loadReports();
            } else {
                showPage('patientDashboard');
                return;
            }
        }

        showPage(pageId);

        // Load permitted contacts whenever Messages is opened.
        if (pageId === 'messages') {
            loadContacts();
        }

        if (pageId === 'medicalHistory' && currentRole === 'patient') {
            loadMedicalHistory();
        }
    });
});
document.getElementById('backToDashboardBtn').addEventListener('click', function () {
    showPage('providerDashboard');
});




    document.getElementById('logoutLink').addEventListener('click', function (e) {
        e.preventDefault();
        handleLogout();
    });

    document.getElementById('backBtn1').addEventListener('click', function () {
        showPage('patientDashboard');
    });
   document.getElementById('backBtn2').addEventListener('click', function () {
    returnToContacts();
    showPage(currentRole === 'doctor' || currentRole === 'nurse'
        ? 'providerDashboard'
        : 'patientDashboard');
});

document.getElementById('messageForm').addEventListener('submit', sendMessage);

document.getElementById('backToContactsBtn').addEventListener('click', returnToContacts);
    
    document.getElementById('backBtn3').addEventListener('click', function () {
        showPage('patientDashboard');
    });

    const savedToken = sessionStorage.getItem('authToken');
const savedRole = sessionStorage.getItem('currentRole');
const savedUser = sessionStorage.getItem('currentUser');

if (savedToken && savedRole && savedUser) {
    try {
        authToken = savedToken;
        currentRole = savedRole;
        currentUser = JSON.parse(savedUser);

        if (currentRole === 'patient') {
            showPage('patientDashboard');
        } else if (currentRole === 'doctor' || currentRole === 'nurse') {
            loadProviderDashboard().then(() => showPage('providerDashboard'));
        } else {
            handleLogout();
        }
    } catch (error) {
        handleLogout();
    }
} else {
    showPage('loginPage');
}
});
// ===== MESSAGING LOGIC =====

let activeConversationUserId = null;

async function openConversation(otherUserId, otherUserName) {
    activeConversationUserId = otherUserId;

    document.getElementById('messagesContacts').classList.add('hidden');
    document.getElementById('messagesConversation').classList.remove('hidden');
    document.getElementById('conversationTitle').textContent = otherUserName;

    await loadMessages();
}

async function loadMessages() {
    const messagesList = document.getElementById('messagesList');
    const messageStatus = document.getElementById('messageStatus');

    messagesList.replaceChildren();
    messageStatus.textContent = 'Loading messages...';

    try {
        const response = await fetch(
            `${API_BASE_URL}/api/messages?with_user_id=${activeConversationUserId}`,
            {
                headers: {
                    'Authorization': `Bearer ${authToken}`
                }
            }
        );

        const data = await response.json();

        if (!response.ok) {
            messageStatus.textContent = data.error || 'Could not load messages.';
            return;
        }

        if (data.length === 0) {
            messageStatus.textContent = 'No messages yet. Start the conversation!';
            return;
        }

        data.forEach(message => {
            const item = document.createElement('p');
            item.textContent =
                `${message.sender_id === currentUser.id ? 'You' : 'Them'}: ${message.message}`;
            messagesList.appendChild(item);
        });

        messageStatus.textContent = '';
    } catch (error) {
        messageStatus.textContent = 'Could not connect to the server.';
    }
}

async function sendMessage(event) {
    event.preventDefault();

    const messageInput = document.getElementById('messageInput');
    const messageStatus = document.getElementById('messageStatus');
    const message = messageInput.value.trim();

    if (!message || !activeConversationUserId) {
        return;
    }

    messageStatus.textContent = 'Sending...';

    try {
        const response = await fetch(`${API_BASE_URL}/api/messages`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({
                recipient_id: activeConversationUserId,
                message: message
            })
        });

        const data = await response.json();

        if (!response.ok) {
            messageStatus.textContent = data.error || 'Could not send message.';
            return;
        }

  
        messageInput.value = '';
        await loadMessages();

        messageStatus.textContent = 'Message sent successfully.';
    } catch (error) {
        messageStatus.textContent = 'Could not connect to the server.';
    }
    
}



function returnToContacts() {
    activeConversationUserId = null;

    document.getElementById('messagesConversation').classList.add('hidden');
    document.getElementById('messagesContacts').classList.remove('hidden');
    document.getElementById('messageStatus').textContent = '';
}
async function loadContacts() {
    const contactsContainer = document.getElementById('messagesContacts');
    const messagesStatus = document.getElementById('messagesStatus');

    messagesStatus.textContent = 'Loading conversations...';

    try {
        const response = await fetch(`${API_BASE_URL}/api/messages/contacts`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        const data = await response.json();

        if (!response.ok) {
            messagesStatus.textContent =
                data.error || 'Could not load conversations.';
            return;
        }

        contactsContainer.querySelectorAll('.contact-button').forEach(button => {
            button.remove();
        });

        if (data.length === 0) {
            messagesStatus.textContent =
                'No available contacts found. You need an assigned patient-staff relationship to message someone.';
            return;
        }

        messagesStatus.textContent = '';

        data.forEach(contact => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'contact-button btn-secondary';
            button.textContent = `${contact.role} (User ID: ${contact.id})`;

            button.addEventListener('click', () => {
                openConversation(
                    contact.id,
                    `${contact.role} (User ID: ${contact.id})`
                );
            });

            contactsContainer.appendChild(button);
        });
    } catch (error) {
        messagesStatus.textContent = 'Could not connect to the server.';
    }
}