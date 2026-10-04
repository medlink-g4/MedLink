// ===== API CONFIG =====
const API_BASE_URL = 'http://localhost:5000';

// ===== MOCK DATA (still used by the PATIENT dashboard only -- untouched) =====
const mockDoctors = [
    { id: 1, name: 'Dr. Sarah Johnson', specialty: 'Cardiology' },
    { id: 2, name: 'Dr. Mike Chen', specialty: 'Neurology' },
    { id: 3, name: 'Dr. Emily Brown', specialty: 'Pediatrics' }
];

const mockTimeSlots = ['9:00 AM', '10:00 AM', '11:00 AM', '2:00 PM', '3:00 PM', '4:00 PM'];

let mockAppointments = [
    { id: 1, patientId: 1, doctorId: 1, doctorName: 'Dr. Sarah Johnson', date: '2026-09-10', time: '10:00 AM', status: 'scheduled' },
    { id: 2, patientId: 1, doctorId: 2, doctorName: 'Dr. Mike Chen', date: '2026-09-15', time: '2:00 PM', status: 'scheduled' }
];

// ===== CURRENT USER STATE =====
let currentUser = null;   // { id, name, role } for display purposes
let currentRole = null;
let authToken = null;     // real JWT from /api/auth/login, used for every backend call

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
    } else {
        sidebar.classList.add('hidden');
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
        currentUser = { id: data.userId, role: data.role, name: emailInput };

        if (data.role === 'patient') {
            loadPatientDashboard();
            showPage('patientDashboard');
        } else if (data.role === 'doctor' || data.role === 'nurse') {
            await loadProviderDashboard();
            showPage('providerDashboard');
        }
    } catch (err) {
        errorMessage.textContent = 'Could not reach the server. Is the backend running?';
    }
}

function handleLogout() {
    currentUser = null;
    currentRole = null;
    authToken = null;
    document.getElementById('loginForm').reset();
    document.getElementById('errorMessage').textContent = '';
    showPage('loginPage');
}

// ===== PATIENT DASHBOARD LOGIC (unchanged -- still mock data) =====
function loadPatientDashboard() {
    const welcome = document.getElementById('patientWelcome');
    const appointmentsList = document.getElementById('appointmentsList');

    welcome.textContent = `Welcome, ${currentUser.name}`;
    appointmentsList.replaceChildren();

    const today = new Date();
    today.setHours(0, 0, 0, 0);

    const upcomingAppointments = mockAppointments
        .filter(appointment => {
            if (
                appointment.patientId !== currentUser.id ||
                appointment.status !== 'scheduled'
            ) {
                return false;
            }
            const appointmentDate = new Date(`${appointment.date}T00:00:00`);
            return !Number.isNaN(appointmentDate.getTime()) && appointmentDate >= today;
        })
        .sort((a, b) => a.date.localeCompare(b.date));

    if (upcomingAppointments.length === 0) {
        const emptyMessage = document.createElement('p');
        emptyMessage.className = 'no-data';
        emptyMessage.textContent = 'No upcoming appointments';
        appointmentsList.appendChild(emptyMessage);
        return;
    }

    upcomingAppointments.forEach(appointment => {
        const card = document.createElement('div');
        card.className = 'appointment-card';

        const doctorName = document.createElement('h3');
        doctorName.textContent = appointment.doctorName;

        const date = document.createElement('p');
        date.textContent = `Date: ${appointment.date}`;

        const time = document.createElement('p');
        time.textContent = `Time: ${appointment.time}`;

        const status = document.createElement('p');
        status.textContent = `Status: ${appointment.status}`;

        card.append(doctorName, date, time, status);

        const cancelButton = document.createElement('button');
        cancelButton.type = 'button';
        cancelButton.className = 'btn-secondary';
        cancelButton.textContent = 'Cancel';
        cancelButton.addEventListener('click', () => {
            cancelAppointment(appointment.id);
        });

        card.appendChild(cancelButton);
        appointmentsList.appendChild(card);
    });
}

function cancelAppointment(appointmentId) {
    mockAppointments = mockAppointments.filter(apt => apt.id !== appointmentId);
    loadPatientDashboard();
    alert('Appointment cancelled');
}

// ===== APPOINTMENT SCHEDULING LOGIC (unchanged -- still mock data) =====
function loadAppointmentForm() {
    const doctorSelect = document.getElementById('doctorSelect');
    doctorSelect.innerHTML = '<option value="">-- Choose a Doctor --</option>';
    mockDoctors.forEach(doctor => {
        const option = document.createElement('option');
        option.value = doctor.id;
        option.textContent = `${doctor.name} (${doctor.specialty})`;
        doctorSelect.appendChild(option);
    });

    const timeSlots = document.getElementById('timeSlots');
    timeSlots.innerHTML = mockTimeSlots.map(time => `
        <button type="button" class="time-slot-btn" data-time="${time}">${time}</button>
    `).join('');

    document.querySelectorAll('.time-slot-btn').forEach(btn => {
        btn.addEventListener('click', function (e) {
            e.preventDefault();
            document.querySelectorAll('.time-slot-btn').forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            document.getElementById('selectedTime').value = this.dataset.time;
        });
    });
}

function handleScheduleAppointment(event) {
    event.preventDefault();

    const doctorId = document.getElementById('doctorSelect').value;
    const date = document.getElementById('appointmentDate').value;
    const time = document.getElementById('selectedTime').value;

    if (!doctorId || !date || !time) {
        alert('Please select doctor, date, and time');
        return;
    }

    const doctor = mockDoctors.find(d => d.id == doctorId);

    const newAppointment = {
        id: mockAppointments.length + 1,
        patientId: currentUser.id,
        doctorId: parseInt(doctorId),
        doctorName: doctor.name,
        date: date,
        time: time,
        status: 'scheduled'
    };

    mockAppointments.push(newAppointment);

    alert('Appointment scheduled successfully!');
    document.getElementById('appointmentForm').reset();
    loadPatientDashboard();
    showPage('patientDashboard');
}

// ===== PROVIDER (DOCTOR/NURSE) DASHBOARD LOGIC -- REAL BACKEND =====
// One function serves both roles: /api/dashboard/ already returns the
// correctly scoped data for whichever role is in the JWT.
async function loadProviderDashboard() {
    const welcome = document.getElementById('providerWelcome');
    welcome.textContent = `Welcome, ${currentRole === 'doctor' ? 'Dr.' : 'Nurse'} (${currentUser.name})`;

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

function renderEmpty(container, message) {
    if (!message) return;
    const emptyMessage = document.createElement('p');
    emptyMessage.className = 'no-data';
    emptyMessage.textContent = message;
    container.appendChild(emptyMessage);
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
        time.textContent = `Time: ${appt.appointment_time}`;

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
        alert('Password reset functionality coming soon!');
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
            const pageId = this.getAttribute('data-page');
            if (pageId) {
                showPage(pageId);
            }
        });
    });

    document.getElementById('logoutLink').addEventListener('click', function (e) {
        e.preventDefault();
        handleLogout();
    });

    document.getElementById('backBtn1').addEventListener('click', function () {
        showPage('patientDashboard');
    });
    document.getElementById('backBtn2').addEventListener('click', function () {
        showPage('patientDashboard');
    });
    document.getElementById('backBtn3').addEventListener('click', function () {
        showPage('patientDashboard');
    });

    showPage('loginPage');
});