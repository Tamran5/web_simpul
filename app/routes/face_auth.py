from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, create_access_token, create_refresh_token
# from scipy.spatial import distance
import math
from datetime import datetime

from app.extensions import db, limiter
from app.models import User

face_bp = Blueprint('face', __name__, url_prefix='/api/face')

EMBEDDING_DIM = 192      
THRESHOLD = 0.5074        


@face_bp.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({
        'status': 'fail',
        'message': 'Terlalu banyak percobaan. Silakan coba lagi beberapa saat lagi.',
    }), 429

def calculate_cosine_distance(vec1, vec2):
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    mag1 = math.sqrt(sum(a * a for a in vec1))
    mag2 = math.sqrt(sum(b * b for b in vec2))
    if mag1 == 0 or mag2 == 0:
        return 1.0 
    return 1.0 - (dot_product / (mag1 * mag2))


def _validate_embedding(data):
    if not data:
        raise ValueError("Body request kosong atau bukan JSON.")

    embedding = data.get('embedding')
    if not embedding or not isinstance(embedding, list):
        raise ValueError("Embedding tidak valid atau tidak ditemukan.")
    if len(embedding) != EMBEDDING_DIM:
        raise ValueError(f"Dimensi embedding salah (harus {EMBEDDING_DIM}).")
    if not all(isinstance(v, (int, float)) for v in embedding):
        raise ValueError("Embedding mengandung nilai non-numerik.")
    return embedding


@face_bp.route('/register', methods=['POST'])
@jwt_required()
def register_face():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        return jsonify({'status': 'fail', 'message': 'User tidak ditemukan.'}), 404

    try:
        embedding = _validate_embedding(request.get_json(silent=True))
    except ValueError as e:
        return jsonify({'status': 'fail', 'message': str(e)}), 400

    user.face_embedding = embedding
    user.face_registered = True
    user.face_registered_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        'status': 'success',
        'message': 'Wajah berhasil didaftarkan.',
        'vector_dimensions': len(embedding)
    }), 200


@face_bp.route('/login', methods=['POST'])
@limiter.limit("10 per minute")
def login_with_face():
    try:
        embedding_login = _validate_embedding(request.get_json(silent=True))
    except ValueError as e:
        return jsonify({'status': 'fail', 'message': str(e)}), 400

    candidates = User.query.filter(
        User.face_registered == True,
        User.face_embedding.isnot(None)
    ).all()

    if not candidates:
        return jsonify({'status': 'fail', 'message': 'Belum ada pengguna yang mendaftarkan wajah.'}), 401

    best_user, best_distance = None, None
    for candidate in candidates:
        try:
            cosine_dist = calculate_cosine_distance(candidate.face_embedding, embedding_login)
        except Exception:
            # Lewati data embedding yang rusak/format tidak sesuai, jangan
            # sampai satu data korup menggagalkan seluruh proses login.
            continue
        if best_distance is None or cosine_dist < best_distance:
            best_distance, best_user = cosine_dist, candidate

    if best_user is None or best_distance >= THRESHOLD:
        return jsonify({
            'status': 'fail',
            'message': 'Wajah tidak dikenali. Silakan gunakan email & password.',
            'distance': round(float(best_distance), 4) if best_distance is not None else None,
        }), 401

    if not best_user.is_verified:
        return jsonify({'status': 'fail', 'message': 'Akun belum aktif. Silakan verifikasi email terlebih dahulu.'}), 403

    return jsonify({
        'status': 'success',
        'message': 'Login dengan Face Recognition berhasil!',
        'access_token': create_access_token(identity=str(best_user.id)),
        'refresh_token': create_refresh_token(identity=str(best_user.id)),
        'distance': round(float(best_distance), 4),
    }), 200


@face_bp.route('/update', methods=['POST'])
@jwt_required()
def update_face():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        return jsonify({'status': 'fail', 'message': 'User tidak ditemukan.'}), 404

    try:
        embedding = _validate_embedding(request.get_json(silent=True))
    except ValueError as e:
        return jsonify({'status': 'fail', 'message': str(e)}), 400

    user.face_embedding = embedding
    user.face_registered_at = datetime.utcnow()
    db.session.commit()

    return jsonify({'status': 'success', 'message': 'Data wajah berhasil diperbarui.'}), 200