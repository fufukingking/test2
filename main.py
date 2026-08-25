import os

from flask import Flask, redirect, render_template, session


def create_app(test_config=None):
    app = Flask(__name__)

    if test_config is not None:
        app.config.from_mapping(test_config)

    app.config["SECRET_KEY"] = os.environ.get(
        "SECRET_KEY", "dev-only-change-this-secret-key"
    )
    app.config["SESSION_PERMANENT"] = False
    app.config["SESSION_TYPE"] = "null"

    from routes import bp

    app.register_blueprint(bp)

    @app.route("/")
    def index():
        from help import login_required

        if session.get("user_id") is None:
            return redirect("/login")
        if session.get("role") == "teacher":
            return redirect("/admin")
        return render_template("index.html")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)
