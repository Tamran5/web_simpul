# app/routes/auth.py

import os
import random
import string
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import (
    create_access_token, create_refresh_token,
    jwt_required, get_jwt_identity,
    get_jwt,
)
from werkzeug.security import generate_password_hash, check_password_hash
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from app.extensions import db
from app.models import User
from app.services.mail_service import send_otp_email

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')


# ── POST /api/auth/register ───────────────────────────────────────────────────
#
# Registrasi sekarang mengirim kode OTP 6 digit ke email (bukan link
# verifikasi). User memasukkan kode itu di halaman OTP verification
# di Flutter, lalu lanjut ke pendaftaran Face Recognition.

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json() or {}

    required = ['name', 'email', 'password', 'gender', 'religion']
    if not all(f in data for f in required):
        return jsonify({'status': 'fail', 'message': 'Data pendaftaran tidak lengkap.'}), 400

    email = data['email'].strip().lower()
    if User.query.filter_by(email=email).first():
        return jsonify({'status': 'fail', 'message': 'Email sudah terdaftar.'}), 409

    user = User(
        name           = data['name'],
        email          = email,
        password       = generate_password_hash(data['password']),
        gender         = data['gender'],
        religion       = data['religion'],
        phone          = data.get('phone', ''),
        ktp_city       = data.get('ktp_city', ''),
        wedding_city   = data.get('wedding_city', ''),
        is_out_of_town = bool(data.get('is_out_of_town', False)),
        is_foreigner   = bool(data.get('is_foreigner', False)),
        is_verified    = False,
    )
    user.generate_unique_code()

    # ── Buat kode OTP registrasi (pakai kolom yang sama dgn forgot-password) ──
    otp = ''.join(random.choices(string.digits, k=6))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    user.otp_code   = otp
    user.otp_expiry = now + timedelta(minutes=5)

    db.session.add(user)
    db.session.commit()

    sent = send_otp_email(user.name, user.email, otp)
    if not sent:
        current_app.logger.error(f'Gagal mengirim OTP registrasi ke {user.email}')

    return jsonify({
        'status':            'success',
        'message':           'Registrasi berhasil! Masukkan kode OTP yang dikirim ke email Anda.',
        'email':             user.email,
        'remaining_seconds': 300,
    }), 201


# ── POST /api/auth/verify-register-otp ────────────────────────────────────────
#
# Verifikasi kode OTP registrasi. Jika benar, akun jadi aktif dan langsung
# dapat access_token + refresh_token (auto-login), lalu Flutter mengarahkan
# ke halaman pendaftaran Face Recognition.

@auth_bp.route('/verify-register-otp', methods=['POST'])
def verify_register_otp():
    data      = request.get_json() or {}
    email     = data.get('email', '').strip().lower()
    otp_input = data.get('otp', '')

    if not email or not otp_input:
        return jsonify({'status': 'fail', 'message': 'Email dan kode OTP wajib diisi.'}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({'status': 'fail', 'message': 'Akun tidak ditemukan.'}), 404

    if user.is_verified:
        # Sudah pernah diverifikasi sebelumnya — tetap kembalikan token
        # supaya Flutter bisa lanjut tanpa error membingungkan.
        return jsonify({
            'status':          'success',
            'message':         'Akun sudah terverifikasi sebelumnya.',
            'access_token':    create_access_token(identity=str(user.id)),
            'refresh_token':   create_refresh_token(identity=str(user.id)),
            'face_registered': user.face_registered,
        }), 200

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if not user.otp_code or not user.otp_expiry or now > user.otp_expiry:
        return jsonify({'status': 'fail', 'message': 'Kode OTP sudah kedaluwarsa. Silakan kirim ulang.'}), 400

    if user.otp_code != otp_input:
        return jsonify({'status': 'fail', 'message': 'Kode OTP salah.'}), 400

    user.is_verified = True
    user.otp_code    = None
    user.otp_expiry  = None
    db.session.commit()

    return jsonify({
        'status':          'success',
        'message':         'Verifikasi berhasil! Selamat datang di Simpul.',
        'access_token':    create_access_token(identity=str(user.id)),
        'refresh_token':   create_refresh_token(identity=str(user.id)),
        'face_registered': user.face_registered,
    }), 200


# ── POST /api/auth/resend-register-otp ────────────────────────────────────────

@auth_bp.route('/resend-register-otp', methods=['POST'])
def resend_register_otp():
    data  = request.get_json() or {}
    email = data.get('email', '').strip().lower()

    if not email:
        return jsonify({'status': 'fail', 'message': 'Email wajib diisi.'}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({'status': 'fail', 'message': 'Akun tidak ditemukan.'}), 404

    if user.is_verified:
        return jsonify({'status': 'fail', 'message': 'Akun sudah terverifikasi. Silakan login.'}), 400

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    if user.otp_code and user.otp_expiry and user.otp_expiry > now:
        sisa = int((user.otp_expiry - now).total_seconds())
        return jsonify({
            'status':            'success',
            'message':           f'Kode OTP sebelumnya masih aktif (tersisa {max(1, round(sisa/60))} menit).',
            'remaining_seconds': sisa,
        }), 200

    otp = ''.join(random.choices(string.digits, k=6))
    user.otp_code   = otp
    user.otp_expiry = now + timedelta(minutes=5)
    db.session.commit()

    success = send_otp_email(user.name, user.email, otp)
    if not success:
        return jsonify({'status': 'fail', 'message': 'Gagal mengirim ulang kode OTP.'}), 500

    return jsonify({
        'status':            'success',
        'message':           'Kode OTP baru telah dikirim ke email Anda.',
        'remaining_seconds': 300,
    }), 200


# ── POST /api/auth/login ──────────────────────────────────────────────────────

@auth_bp.route('/login', methods=['POST'])
def login():
    data     = request.get_json() or {}
    email    = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not email or not password:
        return jsonify({'status': 'fail', 'message': 'Email dan password wajib diisi.'}), 400

    user = User.query.filter_by(email=email).first()

    if not user or not check_password_hash(user.password, password):
        return jsonify({'status': 'fail', 'message': 'Email atau kata sandi salah.'}), 401

    if not user.is_verified:
        return jsonify({
            'status':  'fail',
            'message': 'Akun belum aktif. Silakan verifikasi email terlebih dahulu.',
        }), 403

    return jsonify({
        'status':          'success',
        'message':         'Login berhasil!',
        'access_token':    create_access_token(identity=str(user.id)),
        'refresh_token':   create_refresh_token(identity=str(user.id)),
        'face_registered': user.face_registered,
    }), 200


# ── POST /api/auth/logout ─────────────────────────────────────────────────────
#
# Endpoint ini menerima access token yang masih valid dan menandainya
# sebagai "sudah dicabut" menggunakan JWT blocklist.
# Flutter tetap menghapus token lokal meski endpoint ini gagal —
# ini hanya untuk keamanan sisi server.

@auth_bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    jti      = get_jwt()['jti']          # JWT ID unik dari token ini
    user_id  = get_jwt_identity()

    # Simpan jti ke blocklist agar token tidak bisa dipakai lagi
    # meskipun belum expired
    _add_to_blocklist(jti)

    return jsonify({
        'status':  'success',
        'message': 'Berhasil keluar. Sampai jumpa!',
    }), 200


def _add_to_blocklist(jti: str) -> None:
    """
    Simpan JTI ke tabel TokenBlocklist.
    Jika tabel belum ada, fallback gracefully (logout tetap berhasil di sisi klien).
    """
    try:
        from app.models import TokenBlocklist          # import lokal hindari circular
        entry = TokenBlocklist(jti=jti)
        db.session.add(entry)
        db.session.commit()
    except Exception:
        db.session.rollback()   # jangan sampai crash, klien tetap bisa logout


# ── POST /api/auth/refresh ────────────────────────────────────────────────────

@auth_bp.route('/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    new_token = create_access_token(identity=get_jwt_identity())
    return jsonify({'status': 'success', 'access_token': new_token}), 200


# ── POST /api/auth/google-login ───────────────────────────────────────────────

@auth_bp.route('/google-login', methods=['POST'])
def google_login():
    data  = request.get_json() or {}
    token = data.get('google_id_token')

    if not token:
        return jsonify({'status': 'fail', 'message': 'Token Google tidak ditemukan.'}), 400

    client_id = current_app.config.get('GOOGLE_CLIENT_ID')
    if not client_id:
        # Ini menandakan masalah KONFIGURASI SERVER (GOOGLE_CLIENT_ID belum
        # terbaca dari .env saat startup), bukan kesalahan dari Flutter/user.
        # Lihat app/__init__.py — pastikan load_dotenv() dipanggil & file
        # .env ditemukan di lokasi yang benar.
        current_app.logger.error(
            'GOOGLE_CLIENT_ID kosong di app.config — Google Sign-In tidak '
            'bisa diverifikasi. Cek pesan peringatan di terminal saat '
            'server pertama kali dijalankan.'
        )
        return jsonify({
            'status':  'error',
            'message': 'Konfigurasi Google Sign-In belum lengkap di server.',
        }), 500

    try:
        idinfo = id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            client_id,
        )
        email = idinfo['email']
    except ValueError as e:
        # Log detail asli ke server (jangan dikirim ke client demi keamanan).
        # Pesan ValueError dari library ini biasanya menyebutkan dengan jelas
        # sebab spesifiknya, contoh:
        #   "Token expired" → token kedaluwarsa, minta user login ulang
        #   "Wrong recipient, payload audience != client_id" → CLIENT_ID di
        #     server tidak sama dengan yang dipakai Flutter saat initialize()
        #   "Could not verify token signature" → token rusak/dipalsukan
        current_app.logger.warning(f'Verifikasi Google ID token gagal: {e}')
        return jsonify({'status': 'fail', 'message': 'Token Google tidak valid atau kedaluwarsa.'}), 401
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Kesalahan server: {str(e)}'}), 500

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({
            'status':  'fail',
            'message': 'Email belum terdaftar. Silakan daftar manual terlebih dahulu.',
        }), 404

    if not user.is_verified:
        user.is_verified = True
        db.session.commit()

    return jsonify({
        'status':          'success',
        'message':         'Login Google berhasil.',
        'access_token':    create_access_token(identity=str(user.id)),
        'refresh_token':   create_refresh_token(identity=str(user.id)),
        'face_registered': user.face_registered,
    }), 200


# ── POST /api/auth/forgot-password ───────────────────────────────────────────

@auth_bp.route('/forgot-password', methods=['POST'])
def forgot_password():
    data  = request.get_json() or {}
    email = data.get('email', '').strip().lower()

    if not email:
        return jsonify({'status': 'fail', 'message': 'Email wajib diisi.'}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({'status': 'fail', 'message': 'Email tidak terdaftar.'}), 404

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    if user.otp_code and user.otp_expiry and user.otp_expiry > now:
        sisa = int((user.otp_expiry - now).total_seconds())
        return jsonify({
            'status':            'success',
            'message':           f'OTP sebelumnya masih aktif (tersisa {max(1, round(sisa/60))} menit).',
            'remaining_seconds': sisa,
        }), 200

    otp = ''.join(random.choices(string.digits, k=6))
    user.otp_code   = otp
    user.otp_expiry = now + timedelta(minutes=5)
    db.session.commit()

    success = send_otp_email(user.name, user.email, otp)
    if not success:
        return jsonify({'status': 'fail', 'message': 'Gagal mengirim OTP. Coba lagi nanti.'}), 500

    return jsonify({
        'status':            'success',
        'message':           'Kode OTP dikirim ke email Anda.',
        'remaining_seconds': 300,
    }), 200


# ── POST /api/auth/reset-password ────────────────────────────────────────────

@auth_bp.route('/reset-password', methods=['POST'])
def reset_password():
    data         = request.get_json() or {}
    email        = data.get('email', '').strip().lower()
    otp_input    = data.get('otp', '')
    new_password = data.get('new_password', '')

    if not all([email, otp_input, new_password]):
        return jsonify({'status': 'fail', 'message': 'Semua field wajib diisi.'}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({'status': 'fail', 'message': 'Permintaan tidak valid.'}), 404

    if user.otp_code != otp_input or datetime.utcnow() > user.otp_expiry:
        return jsonify({'status': 'fail', 'message': 'OTP salah atau sudah kedaluwarsa.'}), 400

    user.password   = generate_password_hash(new_password)
    user.otp_code   = None
    user.otp_expiry = None
    db.session.commit()

    return jsonify({'status': 'success', 'message': 'Kata sandi berhasil diperbarui!'}), 200