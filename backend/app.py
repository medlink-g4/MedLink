from flask import Flask
from routes.appointments import appointments_bp
from routes.auth import auth_bp

app = Flask(__name__)

app.register_blueprint(auth_bp, url_prefix="/api/auth")
app.register_blueprint(appointments_bp, url_prefix="/api/appointments")


@app.route("/")
def home():
    return {"message": "MedLink API is running"}


if __name__ == "__main__":
    app.run(debug=True)
