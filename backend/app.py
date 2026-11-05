import logging

from flask import Flask
from flask_cors import CORS
from routes.appointments import appointments_bp
from routes.audit import audit_bp
from routes.auth import auth_bp
from routes.dr_nr_dashboard import dashboard_bp
from routes.messages import messages_bp
from routes.patients import patients_bp
from routes.medical_records import medical_records_bp
from routes.password_reset import password_reset_bp

# Without this the root logger sits at WARNING and every log.info() in the
# project is discarded -- including the task 4.4 line that carries the
# password reset token, which is the only way to get hold of one when the
# development flag is off. Configured here, at the entry point, rather than
# inside a module, so importing a blueprint does not reconfigure logging.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)

app = Flask(__name__)
CORS(app)

app.register_blueprint(auth_bp, url_prefix="/api/auth")
# Task 4.4 shares the /api/auth prefix without editing the task 1.3 module.
app.register_blueprint(password_reset_bp, url_prefix="/api/auth")
app.register_blueprint(audit_bp, url_prefix="/api/audit")
app.register_blueprint(dashboard_bp, url_prefix="/api/dashboard")
app.register_blueprint(appointments_bp, url_prefix="/api/appointments")
app.register_blueprint(messages_bp, url_prefix="/api/messages")
app.register_blueprint(patients_bp, url_prefix="/api/patients")
app.register_blueprint(medical_records_bp, url_prefix="/api/medical-records")


@app.route("/")
def home():
    return {"message": "MedLink API is running"}


if __name__ == "__main__":
    app.run(debug=True)
