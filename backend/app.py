from flask import Flask
from flask_cors import CORS

from routes.appointments import appointments_bp
from routes.auth import auth_bp
from routes.dr_nr_dashboard import dashboard_bp
from routes.medical_records import medical_records_bp

app = Flask(__name__)
CORS(app)

app.register_blueprint(auth_bp, url_prefix="/api/auth")
app.register_blueprint(dashboard_bp, url_prefix="/api/dashboard")
app.register_blueprint(appointments_bp, url_prefix="/api/appointments")
app.register_blueprint(medical_records_bp, url_prefix="/api/medical-records")


@app.route("/")
def home():
    return {"message": "MedLink API is running"}


if __name__ == "__main__":
    app.run(debug=True)
