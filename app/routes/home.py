# app/routes/home.py

from datetime import datetime, date

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.extensions import db
from app.models import User, WeddingPlan, Task, LegalDocument, Notification, JourneyStepProgress
from app.services import pair_service, journey_service
from app.services.mail_service import send_wedding_date_update_email
from app.utils.helpers import format_date_display, date_to_epoch

home_bp = Blueprint('home', __name__, url_prefix='/api')


# ── GET /api/home ─────────────────────────────────────────────────────────────

@home_bp.route('/home', methods=['GET'])
@jwt_required()
def get_home():
    user      = User.query.get_or_404(get_jwt_identity())
    pair_info = pair_service.get_pair_info(user)

    return jsonify({
        'data': {
            'user':                  _user_dict(user),
            'pair':                  pair_info,
            'wedding_date_display':  _get_wedding_display(user, pair_info),
            'wedding_date_epoch':    _get_wedding_epoch(user, pair_info),
            'progress':              _get_progress(user, pair_info),
            'legal':                 _get_legal_status(user, pair_info),
        }
    }), 200


# ── PATCH /api/wedding-date ───────────────────────────────────────────────────

@home_bp.route('/wedding-date', methods=['PATCH'])
@jwt_required()
def update_wedding_date():
    user     = User.query.get_or_404(get_jwt_identity())
    data     = request.get_json() or {}
    date_str = data.get('date', '').strip()

    if not date_str:
        return jsonify({'status': 'fail', 'message': 'Field "date" wajib diisi (YYYY-MM-DD).'}), 400

    try:
        parsed = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'status': 'fail', 'message': 'Format tanggal tidak valid. Gunakan YYYY-MM-DD.'}), 422

    if parsed < date.today():
        return jsonify({'status': 'fail', 'message': 'Tanggal tidak boleh di masa lalu.'}), 422

    # FIX: Tanggal pernikahan adalah data BERSAMA pasangan, bukan per-user.
    # Sebelumnya hanya WeddingPlan milik user yang request di-upsert, sehingga
    # jika partner sudah punya WeddingPlan sendiri dengan tanggal berbeda,
    # keduanya akan "tidak pernah ketemu" — partner tetap melihat tanggal lama.
    # Sekarang: upsert WeddingPlan milik SEMUA anggota pasangan (kalau synced)
    # sekaligus, di satu transaksi, supaya datanya selalu identik untuk berdua.
    pair_info = pair_service.get_pair_info(user)
    partner   = None
    if pair_info['is_synced'] and pair_info.get('partner'):
        partner = User.query.get(pair_info['partner']['id'])

    target_user_ids = [user.id]
    if partner:
        target_user_ids.append(partner.id)

    for uid in target_user_ids:
        plan = WeddingPlan.query.filter_by(user_id=uid).first()
        if plan:
            plan.wedding_date = parsed
        else:
            plan = WeddingPlan(user_id=uid, wedding_date=parsed)
            db.session.add(plan)

    db.session.commit()

    # Notif + email ke partner (tetap dipertahankan dari versi sebelumnya)
    if partner:
        display = format_date_display(parsed)
        send_wedding_date_update_email(partner.name, partner.email, user.name, display)
        db.session.add(Notification(
            user_id    = partner.id,
            title      = 'Tanggal pernikahan diperbarui 📅',
            body       = f'{user.name} mengubah tanggal pernikahan menjadi {display}.',
            notif_type = 'info',
        ))
        db.session.commit()

    return jsonify({
        'status':  'success',
        'message': 'Tanggal pernikahan berhasil disimpan.',
        'data': {
            'display': format_date_display(parsed),
            'epoch':   date_to_epoch(parsed),
        },
    }), 200


# ── Private helpers ───────────────────────────────────────────────────────────

def _user_dict(user: User) -> dict:
    return {
        'id':          user.id,
        'name':        user.name,
        'photo_url':   user.photo_url or '',
        'unique_code': user.unique_code,
    }


def _get_wedding_display(user: User, pair_info: dict) -> str:
    plan = WeddingPlan.query.filter_by(user_id=user.id).first()
    if plan and plan.wedding_date:
        return format_date_display(plan.wedding_date)
    # Fallback ke tanggal pasangan (jaga-jaga untuk data lama / belum sinkron
    # saat fitur ini ditambahkan — setelah PATCH di atas berjalan, kedua
    # WeddingPlan akan selalu identik sehingga baris ini jadi safety-net saja)
    if pair_info['is_synced'] and pair_info.get('partner'):
        p_plan = WeddingPlan.query.filter_by(user_id=pair_info['partner']['id']).first()
        if p_plan and p_plan.wedding_date:
            return format_date_display(p_plan.wedding_date)
    return ''


def _get_wedding_epoch(user: User, pair_info: dict) -> int:
    plan = WeddingPlan.query.filter_by(user_id=user.id).first()
    if plan and plan.wedding_date:
        return date_to_epoch(plan.wedding_date)
    if pair_info['is_synced'] and pair_info.get('partner'):
        p_plan = WeddingPlan.query.filter_by(user_id=pair_info['partner']['id']).first()
        if p_plan and p_plan.wedding_date:
            return date_to_epoch(p_plan.wedding_date)
    return 0


def _get_progress(user: User, pair_info: dict) -> dict:
    ids = [user.id]
    if pair_info['is_synced'] and pair_info.get('partner'):
        ids.append(pair_info['partner']['id'])

    # Tugas umum (non-legal) — tetap dari tabel Task jika ada
    task_total = Task.query.filter(Task.user_id.in_(ids)).count()
    task_done  = Task.query.filter(Task.user_id.in_(ids), Task.is_done == True).count()

    # Checklist legal sekarang berbasis JourneyStepProgress (sama seperti
    # halaman To Do), bukan tabel Task lagi — hitung dari sana agar
    # angka di Home konsisten dengan halaman Todo.
    legal_total = 0
    legal_done = 0
    for uid in ids:
        u = User.query.get(uid)
        if not u:
            continue
        steps = journey_service.get_steps_for_user(u)
        progress_rows = JourneyStepProgress.query.filter_by(user_id=uid).all()
        merged = journey_service.merge_with_progress(steps, progress_rows)
        legal_total += len(merged)
        legal_done += sum(1 for s in merged if s['is_done'])

    total = task_total + legal_total
    done  = task_done + legal_done

    return {
        'total':         total,
        'completed':     done,
        'legal_percent': round(legal_done / legal_total * 100) if legal_total else 0,
        'task_percent':  round(task_done / task_total * 100) if task_total else 0,
    }


def _get_legal_status(user: User, pair_info: dict) -> dict:
    ids = [user.id]
    if pair_info['is_synced'] and pair_info.get('partner'):
        ids.append(pair_info['partner']['id'])

    # Ambil journey milik SETIAP anggota pasangan, gabungkan progresnya.
    # Definisi step sama untuk profil yang identik, tapi kita ambil per-user
    # untuk berjaga-jaga jika religion/gender partner berbeda.
    all_current_steps = []
    total_steps = 0
    done_steps = 0

    for uid in ids:
        u = User.query.get(uid)
        if not u:
            continue
        steps = journey_service.get_steps_for_user(u)
        progress_rows = JourneyStepProgress.query.filter_by(user_id=uid).all()
        merged = journey_service.merge_with_progress(steps, progress_rows)

        total_steps += len(merged)
        done_steps += sum(1 for s in merged if s['is_done'])

        # Step pertama yang belum selesai = "sedang berjalan" untuk user ini
        current = next((s for s in merged if not s['is_done']), None)
        if current:
            all_current_steps.append(current)

    if total_steps == 0:
        return {'current_doc': '', 'level': '', 'percent': 0}

    percent = round(done_steps / total_steps * 100)

    if not all_current_steps:
        # Semua step selesai untuk semua anggota pasangan
        return {'current_doc': 'Selesai', 'level': 'Semua Tahap', 'percent': 100}

    # Ambil step dengan step_order terkecil sebagai yang ditampilkan
    current_step = min(all_current_steps, key=lambda s: s['step_order'])

    return {
        'current_doc': current_step['title'],       # mis. "Formulir N1 - N4 Kelurahan"
        'level':       current_step['category'],     # mis. "Kantor Kelurahan / Desa"
        'percent':     percent,
    }