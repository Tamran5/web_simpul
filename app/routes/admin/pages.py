import os
from datetime import datetime, date

from flask import (
    Blueprint, render_template, request,
    redirect, url_for, session, flash, current_app, jsonify
)
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import Admin, Article, User, Vendor, JourneyStepProgress
from app.utils.helpers import allowed_file
from .decorators import login_required
from app.services import pair_service
from dateutil.relativedelta import relativedelta
from sqlalchemy import func, extract, case

pages_bp = Blueprint('admin_pages', __name__)


# ── Dashboard ─────────────────────────────────────────────────────────────────

@pages_bp.route('/dashboard')
@login_required
def dashboard():
    total_users = User.query.count()
    total_vendors = Vendor.query.count()
    total_articles = Article.query.count()

    recent_vendors = (
        Vendor.query
        .order_by(Vendor.id.desc())
        .limit(5)
        .all()
    )

    STEP_DOCS = [
        ("rt_rw", "Surat Pengantar RT/RW"),
        ("kelurahan_n1234", "Dokumen Kelurahan"),
        ("kua_daftar", "Pendaftaran KUA"),
        ("kua_bimbingan", "Bimbingan Pranikah"),
        ("kua_akad", "Akad Nikah"),
    ]

    doc_progress = []
    percentages = []

    for step_key, label in STEP_DOCS:
        done_count = (
            JourneyStepProgress.query.filter_by(
                step_key=step_key,
                is_done=True
            ).count()
        )

        pct = round((done_count / total_users) * 100, 1) if total_users else 0

        percentages.append(pct)

        doc_progress.append({
            "label": label,
            "count": done_count,
            "pct": pct
        })

    avg_done = round(sum(percentages) / len(percentages), 1) if percentages else 0

    return render_template(
        "admin/dashboard.html",
        total_users=total_users,
        total_vendors=total_vendors,
        total_articles=total_articles,
        recent_vendors=recent_vendors,
        avg_done=avg_done,
        doc_progress=doc_progress,
    )


# ── Vendor ────────────────────────────────────────────────────────────────────

@pages_bp.route('/vendor')
@login_required
def vendor_page():
    vendors = Vendor.query.all()
    return render_template('admin/katalog_vendor.html', vendors=vendors)


# ── Manajemen Pengguna ────────────────────────────────────────────────────────

@pages_bp.route('/manajemen-pengguna')
@login_required
def manajemen_pengguna():
    users            = User.query.all()
    total_users      = User.query.count()
    verified_users   = User.query.filter_by(is_verified=True).count()
    unverified_users = User.query.filter_by(is_verified=False).count()
    new_users        = User.query.order_by(User.id.desc()).limit(5).count()

    
    for u in users:
        pair_info = pair_service.get_pair_info(u)
        if not u.partner_name:
            u.partner_name = '-'
        if u.is_synced and pair_info.get('partner'):
            u.partner_name = pair_info['partner'].get('name', '')

    return render_template(
        'admin/manajemen_pengguna.html',
        users            = users,
        total_users      = total_users,
        verified_users   = verified_users,
        unverified_users = unverified_users,
        new_users        = new_users,
    )

# ── Edukasi ───────────────────────────────────────────────────────────────────

@pages_bp.route('/edukasi')
@login_required
def edukasi():
    articles = Article.query.order_by(Article.id.desc()).all()
    return render_template('admin/edukasi.html', articles=articles)


# ── Pengaturan ────────────────────────────────────────────────────────────────

@pages_bp.route('/pengaturan')
@login_required
def pengaturan():
    admin = Admin.query.get(session['admin_id'])
    return render_template('admin/pengaturan.html', admin=admin)


@pages_bp.route('/pengaturan/update-profil', methods=['POST'])
@login_required
def update_profil():
    admin     = Admin.query.get(session['admin_id'])
    nama_baru = request.form.get('nama_lengkap', '').strip()
    file_foto = request.files.get('foto_profil')

    if nama_baru:
        admin.name             = nama_baru
        session['admin_name']  = nama_baru

    if file_foto and file_foto.filename:
        if not allowed_file(file_foto.filename, {'jpg', 'jpeg', 'png', 'gif'}):
            return jsonify({
                'status': 'fail',
                'message': 'Format file tidak didukung! Gunakan JPG, JPEG, PNG, atau GIF.',
            }), 400

        folder = os.path.join(current_app.root_path, 'static', 'img', 'avatars')
        os.makedirs(folder, exist_ok=True)

        ext      = os.path.splitext(file_foto.filename)[1].lower()
        filename = secure_filename(f"avatar_{admin.id}{ext}")
        file_foto.save(os.path.join(folder, filename))
        admin.foto_profil = filename

    db.session.commit()
    return jsonify({
        'status':  'success',
        'message': 'Profil berhasil diperbarui.',
        'data': {
            'nama': admin.name,
            'foto_url': url_for('static', filename=f'img/avatars/{admin.foto_profil}') if admin.foto_profil else None,
        },
    }), 200


@pages_bp.route('/pengaturan/ubah-password', methods=['POST'])
@login_required
def ubah_password():
    admin               = Admin.query.get(session['admin_id'])
    password_lama       = request.form.get('password_lama', '')
    password_baru       = request.form.get('password_baru', '')
    konfirmasi_password = request.form.get('konfirmasi_password', '')

    if not admin.check_password(password_lama):
        flash('Kata sandi saat ini salah!', 'error')
        return redirect(url_for('admin_pages.pengaturan'))

    if password_baru != konfirmasi_password:
        flash('Konfirmasi kata sandi baru tidak cocok!', 'error')
        return redirect(url_for('admin_pages.pengaturan'))

    admin.set_password(password_baru)
    db.session.commit()
    flash('Kata sandi berhasil diperbarui!', 'success')
    return redirect(url_for('admin_pages.pengaturan'))


# ── Helper: ambil range bulan ────────────────────────────────────────────────

def _month_range(n_months: int = 6):
    """
    Kembalikan list (year, month, label) untuk n_months ke belakang,
    urut dari terlama ke terbaru (cocok untuk chart).
    """
    today = date.today()
    months = []
    for i in range(n_months - 1, -1, -1):
        d = today - relativedelta(months=i)
        months.append((d.year, d.month, d.strftime('%b %Y')))
    return months


def _analytics_data(n_months: int = 6) -> dict:
    """
    Tarik semua data analitik dari database.
    Dipanggil oleh dashboard_bisnis (render) dan endpoint API (JSON).
    """
    months = _month_range(n_months)
    labels = [m[2] for m in months]

    # ── 1. Pendaftaran baru per bulan ────────────────────────────────────────
    reg_rows = (
        db.session.query(
            extract('year', User.created_at).label('yr'),   
            extract('month', User.created_at).label('mo'),
            func.count(User.id).label('cnt'),
        )
        .group_by(
            extract('year', User.created_at),
            extract('month', User.created_at)
        )
        .all()
    )

    # ── Versi benar: User.created_at (tambahkan kolom ini ke model jika belum ada)
    # Untuk sementara kita query per bulan dari field yang tersedia.
    # Karena User belum punya created_at, kita buat versi yang robust:

    registration_by_month = []
    synced_by_month       = []
    pending_by_month      = []

    for year, month, label in months:
        # Filter pengguna yang dibuat pada bulan tersebut
        # Jika User.created_at belum ada, query ini tetap jalan tapi return 0
        try:
            new_users = (
                db.session.query(func.count(User.id))
                .filter(
                    extract('year',  User.created_at) == year,
                    extract('month', User.created_at) == month,
                )
                .scalar() or 0
            )
        except Exception:
            new_users = 0

        synced = (
            db.session.query(func.count(User.id))
            .filter(
                User.sync_status == 'synced',
                extract('year',  User.created_at) == year,
                extract('month', User.created_at) == month,
            )
            .scalar() or 0
        ) if hasattr(User, 'created_at') else 0

        pending = (
            db.session.query(func.count(User.id))
            .filter(
                User.sync_status.in_(['pending_sent', 'pending_received']),
                extract('year',  User.created_at) == year,
                extract('month', User.created_at) == month,
            )
            .scalar() or 0
        ) if hasattr(User, 'created_at') else 0

        registration_by_month.append(new_users)
        synced_by_month.append(synced)
        pending_by_month.append(pending)

    # ── 2. KPI keseluruhan ───────────────────────────────────────────────────
    total_users    = User.query.count()
    synced_pairs   = User.query.filter_by(sync_status='synced').count()
    adoption_rate  = round(synced_pairs / total_users * 100, 1) if total_users else 0

    # ── 3. Funnel legalitas — dari JourneyStepProgress ───────────────────────
    STEP_FUNNEL = [
        ('rt_rw',            'Pengajuan RT/RW',         'Surat pengantar lingkungan',          'kelurahan'),
        ('kelurahan_n1234',  'Kelurahan — N1/N2/N3/N4', 'Surat keterangan status & domisili',  'kelurahan'),
        ('kua_daftar',       'KUA — Daftar Nikah',      'Formulir N1–N4 diterima KUA',         'kua'),
        ('kua_bimbingan',    'KUA — Bimbingan Pranikah','Suscatin / KPP selesai',              'kua'),
        ('kua_akad',         'KUA — Akad Disetujui',    'Seluruh berkas dinyatakan lengkap',   'done'),
    ]

    funnel_data = []
    for step_key, label, sub, tier in STEP_FUNNEL:
        done_count = (
            db.session.query(func.count(JourneyStepProgress.id))
            .filter(
                JourneyStepProgress.step_key == step_key,
                JourneyStepProgress.is_done  == True,
            )
            .scalar() or 0
        )
        pct = round(done_count / total_users * 100, 1) if total_users else 0
        funnel_data.append({
            'label': label,
            'sub':   sub,
            'pct':   pct,
            'tier':  tier,
            'count': done_count,
        })

    # ── 4. Distribusi donut (tahap terakhir aktif) ───────────────────────────
    # Hitung berdasarkan step terakhir yang is_done = True per user
    # Kategori: Belum mulai | Kelurahan aktif | KUA aktif | Selesai

    kelurahan_steps = ['rt_rw', 'kelurahan_n1234']
    kua_steps       = ['kua_daftar', 'kua_bimbingan']
    done_step       = 'kua_akad'

    selesai = (
        db.session.query(func.count(func.distinct(JourneyStepProgress.user_id)))
        .filter(JourneyStepProgress.step_key == done_step, JourneyStepProgress.is_done == True)
        .scalar() or 0
    )

    kua_aktif = (
        db.session.query(func.count(func.distinct(JourneyStepProgress.user_id)))
        .filter(JourneyStepProgress.step_key.in_(kua_steps), JourneyStepProgress.is_done == True)
        .scalar() or 0
    ) - selesai

    kelurahan_aktif = (
        db.session.query(func.count(func.distinct(JourneyStepProgress.user_id)))
        .filter(JourneyStepProgress.step_key.in_(kelurahan_steps), JourneyStepProgress.is_done == True)
        .scalar() or 0
    ) - kua_aktif - selesai

    belum_mulai = total_users - kelurahan_aktif - max(kua_aktif, 0) - selesai
    belum_mulai = max(belum_mulai, 0)

    legal_done_rate = round(selesai / total_users * 100, 1) if total_users else 0

    donut_data = [
        belum_mulai,
        max(kelurahan_aktif, 0),
        max(kua_aktif, 0),
        selesai,
    ]
    donut_pct = [
        round(v / total_users * 100, 1) if total_users else 0
        for v in donut_data
    ]

    # ── 5. Riwayat data — simpan snapshot bulanan ke dict ────────────────────
    # Kita return semua data time-series agar frontend bisa render riwayat
    history = []
    for i, (year, month, label) in enumerate(months):
        history.append({
            'label':         label,
            'registrations': registration_by_month[i],
            'synced':        synced_by_month[i],
            'pending':       pending_by_month[i],
        })

    return {
        # KPI tile
        'total_users':     total_users,
        'synced_pairs':    synced_pairs,
        'adoption_rate':   adoption_rate,
        'legal_done_rate': legal_done_rate,

        # Chart data
        'chart': {
            'labels':         labels,
            'registrations':  registration_by_month,
            'synced':         synced_by_month,
            'pending':        pending_by_month,
        },

        # Funnel
        'funnel': funnel_data,

        # Donut
        'donut': {
            'labels': ['Belum mulai', 'Kelurahan aktif', 'KUA aktif', 'Selesai'],
            'values': donut_pct,
            'counts': donut_data,
            'colors': ['#C8C5BB', '#5B7CF6', '#34C985', '#F5A623'],
        },

        # Riwayat bulanan (untuk tabel riwayat di bawah chart)
        'history': history,

        # Meta
        'n_months':     n_months,
        'generated_at': datetime.now().strftime('%d %B %Y, %H:%M'),
    }


# ── Route: halaman dashboard bisnis ─────────────────────────────────────────

@pages_bp.route('/dashboard-bisnis')
@login_required
def dashboard_bisnis():
    n_months = int(request.args.get('bulan', 6))
    n_months = max(3, min(n_months, 12))   # clamp 3–12

    data = _analytics_data(n_months)

    # Format angka Indonesia untuk template
    def fmt(n):
        return f'{int(n):,}'.replace(',', '.')

    return render_template(
        'admin/dashboard_bisnis.html',
        now=datetime.now(),
        total_users=fmt(data['total_users']),
        synced_pairs=fmt(data['synced_pairs']),
        adoption_rate=str(data['adoption_rate']).replace('.', ','),
        legal_done_rate=str(data['legal_done_rate']).replace('.', ','),
        analytics=data,
        n_months=n_months,
    )


# ── API: refresh data real-time (dipanggil JS setiap N menit) ───────────────

@pages_bp.route('/api/analytics')
@login_required
def api_analytics():
    n_months = int(request.args.get('bulan', 6))
    n_months = max(3, min(n_months, 12))
    return jsonify(_analytics_data(n_months))