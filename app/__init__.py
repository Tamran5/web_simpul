import os
from dotenv import load_dotenv

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENV_PATH = os.path.join(_PROJECT_ROOT, '.env')
load_dotenv(_ENV_PATH)

from flask import Flask, jsonify
from app.extensions import db, jwt, migrate, limiter
from flask_migrate import Migrate
from datetime import timedelta
from flask_cors import CORS
from flask_mail import Mail
from app.services.scheduler import init_scheduler

mail = Mail()

def create_app():
    app = Flask(__name__)
    CORS(app)

    app.config['SECRET_KEY'] = os.environ.get(
        'SECRET_KEY',
        'kunci-super-rahasia-simpul'  # fallback untuk development lokal saja
    )

    app.config["UPLOAD_FOLDER"] = "app/static/uploads/profile"
    app.config["ALLOWED_EXTENSIONS"] = {
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp"
    }

    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
        'DATABASE_URL',
        'mysql+pymysql://root:@localhost/db_simpul'  # fallback kalau env var tidak di-set
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    app.config['JWT_SECRET_KEY'] = os.environ.get(
        'JWT_SECRET_KEY',
        'super-secret-key-simpul-wedding-planner-2026-caps'  # fallback dev lokal
    )
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=1)

    app.config['JWT_BLACKLIST_ENABLED'] = True
    app.config['JWT_BLACKLIST_TOKEN_CHECKS'] = ['access', 'refresh']

    # KONFIGURASI SMTP GMAIL
    app.config['MAIL_SERVER'] = 'smtp.gmail.com'
    app.config['MAIL_PORT'] = 587
    app.config['MAIL_USE_TLS'] = True
    app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
    app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
    app.config['MAIL_DEFAULT_SENDER'] = ('Simpul Wedding', os.environ.get('MAIL_DEFAULT_SENDER', 'simpulapp@gmail.com'))
    app.config['GOOGLE_CLIENT_ID'] = os.environ.get('GOOGLE_CLIENT_ID')

    # ── Init extensions ───────────────────────────────────────────────────────
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    mail.init_app(app)
    limiter.init_app(app)

    @jwt.token_in_blocklist_loader
    def check_if_token_revoked(jwt_header, jwt_payload):
        from app.models import TokenBlocklist
        jti = jwt_payload['jti']
        return db.session.query(
            TokenBlocklist.query.filter_by(jti=jti).exists()
        ).scalar()

    @jwt.revoked_token_loader
    def revoked_token_callback(jwt_header, jwt_payload):
        return jsonify({
            'status':  'fail',
            'message': 'Token sudah tidak aktif. Silakan login kembali.',
        }), 401

    _register_blueprints(app)

    with app.app_context():
        db.create_all()

    if os.environ.get("WERKZEUG_RUN_MAIN") != "true" or not app.debug:
        init_scheduler(app)


    return app



def _register_blueprints(app: Flask) -> None:
    from app.routes.auth          import auth_bp
    from app.routes.profile       import profile_bp
    from app.routes.home          import home_bp
    from app.routes.articles      import articles_bp
    from app.routes.vendors       import vendors_bp
    from app.routes.notifications import notifications_bp
    from app.routes.main_routes   import main_bp
    from app.routes.journey       import journey_bp
    from app.routes.face_auth     import face_bp
    from app.routes.pair_routes   import pair_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(home_bp)
    app.register_blueprint(articles_bp)
    app.register_blueprint(face_bp)
    app.register_blueprint(vendors_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(journey_bp)
    app.register_blueprint(pair_bp)

    from app.routes.admin import auth_web_bp, pages_bp, api_articles_bp, api_vendors_bp, api_users_bp, admin_bp, visualization_bp

    app.register_blueprint(auth_web_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(api_articles_bp)
    app.register_blueprint(api_vendors_bp)
    app.register_blueprint(api_users_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(visualization_bp, url_prefix="/api/visualization")