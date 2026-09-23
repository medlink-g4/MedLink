// ===== MOCK DATA =====
const mockUsers = [
    { id: 1, email: 'patient@email.com', password: 'password123', name: 'John Patient', role: 'patient' },
    { id: 2, email: 'doctor@email.com', password: 'password123', name: 'Dr. Sarah', role: 'doctor' },
    { id: 3, email: 'nurse@email.com', password: 'password123', name: 'Nurse Mike', role: 'nurse' }
];

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
let currentUser = null;
let currentRole = null;

// ===== PAGE MANAGER =====
function showPage(pageId) {
    // Hide all pages
    const allPages = document.querySelectorAll('.page');
    allPages.forEach(page => page.classList.add('hidden'));
    
    // Show the selected page
    const selectedPage = document.getElementById(pageId);
    if (selectedPage) {
        selectedPage.classList.remove('hidden');
    }
    
    // Show/hide sidebar based on whether user is logged in
    const sidebar = document.getElementById('sidebar');
    if (currentUser && pageId !== 'loginPage') {
        sidebar.classList.remove('hidden');
    } else {
        sidebar.classList.add('hidden');
    }
}

// ===== LOGIN LOGIC =====
function handleLogin(event) {
    event.preventDefault();
    
    const emailInput = document.getElementById('email').value;
    const passwordInput = document.getElementById('password').value;
    const errorMessage = document.getElementById('errorMessage');
    
    // Check if user exists and password is correct
    const user = mockUsers.find(u => 
        (u.email === emailInput || u.email.split('@')[0] === emailInput) && 
        u.password === passwordInput
    );
    
    if (user) {
        // Successful login
        currentUser = user;
        currentRole = user.role;
        errorMessage.textContent = '';
        
        // Show appropriate dashboard based on role
        if (user.role === 'patient') {
            loadPatientDashboard();
            showPage('patientDashboard');
        } else if (user.role === 'doctor') {
            showPage('doctorDashboard');
        } else if (user.role === 'nurse') {
            showPage('nurseDashboard');
        }
    } else {
        // Failed login
        errorMessage.textContent = 'Invalid email/username or password. Try: patient@email.com / password123';
    }
}

function handleLogout() {
    currentUser = null;
    currentRole = null;
    document.getElementById('loginForm').reset();
    document.getElementById('errorMessage').textContent = '';
    showPage('loginPage');
}

// ===== PATIENT DASHBOARD LOGIC =====
function loadPatientDashboard() {
    // Update welcome message
    document.getElementById('patientWelcome').textContent = `Welcome, ${currentUser.name}`;
    
    // Load appointments for this patient
    const userAppointments = mockAppointments.filter(apt => apt.patientId === currentUser.id);
    const appointmentsList = document.getElementById('appointmentsList');
    
    if (userAppointments.length === 0) {
        appointmentsList.innerHTML = '<p class="no-data">No upcoming appointments</p>';
    } else {
        appointmentsList.innerHTML = userAppointments.map(apt => `
            <div class="appointment-card">
                <h3>${apt.doctorName}</h3>
                <p><strong>Date:</strong> ${apt.date}</p>
                <p><strong>Time:</strong> ${apt.time}</p>
                <p><strong>Status:</strong> ${apt.status}</p>
                <button class="btn-secondary" onclick="cancelAppointment(${apt.id})">Cancel</button>
            </div>
        `).join('');
    }
}

function cancelAppointment(appointmentId) {
    mockAppointments = mockAppointments.filter(apt => apt.id !== appointmentId);
    loadPatientDashboard();
    alert('Appointment cancelled');
}

// ===== APPOINTMENT SCHEDULING LOGIC =====
function loadAppointmentForm() {
    // Populate doctor dropdown
    const doctorSelect = document.getElementById('doctorSelect');
    doctorSelect.innerHTML = '<option value="">-- Choose a Doctor --</option>';
    mockDoctors.forEach(doctor => {
        const option = document.createElement('option');
        option.value = doctor.id;
        option.textContent = `${doctor.name} (${doctor.specialty})`;
        doctorSelect.appendChild(option);
    });
    
    // Load time slots
    const timeSlots = document.getElementById('timeSlots');
    timeSlots.innerHTML = mockTimeSlots.map(time => `
        <button type="button" class="time-slot-btn" data-time="${time}">${time}</button>
    `).join('');
    
    // Add click listeners to time slot buttons
    document.querySelectorAll('.time-slot-btn').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            // Remove active class from all buttons
            document.querySelectorAll('.time-slot-btn').forEach(b => b.classList.remove('active'));
            // Add active class to clicked button
            this.classList.add('active');
            // Store selected time
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
    
    // Find doctor name
    const doctor = mockDoctors.find(d => d.id == doctorId);
    
    // Create new appointment
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

// ===== EVENT LISTENERS =====
document.addEventListener('DOMContentLoaded', function() {
    // Login form
    document.getElementById('loginForm').addEventListener('submit', handleLogin);
    
    // Forgot password link
    document.querySelector('.forgot-password').addEventListener('click', function(e) {
        e.preventDefault();
        alert('Password reset functionality coming soon!');
    });
    
    // Schedule new appointment button
    document.getElementById('scheduleNewBtn').addEventListener('click', function() {
        loadAppointmentForm();
        showPage('appointmentScheduling');
    });
    
    // Appointment form
    document.getElementById('appointmentForm').addEventListener('submit', handleScheduleAppointment);
    document.getElementById('cancelAppointmentBtn').addEventListener('click', function() {
        showPage('patientDashboard');
    });
    
    // Sidebar navigation
    document.querySelectorAll('.nav-link').forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            const pageId = this.getAttribute('data-page');
            if (pageId) {
                showPage(pageId);
            }
        });
    });
    
    // Logout
    document.getElementById('logoutLink').addEventListener('click', function(e) {
        e.preventDefault();
        handleLogout();
    });
    
    // Back buttons
    document.getElementById('backBtn1').addEventListener('click', function() {
        showPage('patientDashboard');
    });
    document.getElementById('backBtn2').addEventListener('click', function() {
        showPage('patientDashboard');
    });
    document.getElementById('backBtn3').addEventListener('click', function() {
        showPage('patientDashboard');
    });
    document.getElementById('backBtn4').addEventListener('click', handleLogout);
    document.getElementById('backBtn5').addEventListener('click', handleLogout);
    
    // Show login page on load
    showPage('loginPage');
});
