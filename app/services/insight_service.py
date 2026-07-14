import logging
from scipy.stats import pearsonr
from app.extensions import db
from app.models_visualization import ExternalTrendData, CategoryInsight
from app.services.trend_service import KEYWORD_CATEGORY_MAP
from app.services.internal_activity_service import get_internal_activity_by_category

logger = logging.getLogger(__name__)


def _pct_change(new, old):
    if old == 0:
        return 100.0 if new > 0 else 0.0
    return round(((new - old) / old) * 100, 2)


def generate_category_insights():
    try:
        current_internal, previous_internal, vendor_counts = get_internal_activity_by_category(days=30)
        CategoryInsight.query.delete()

        for keyword, category in KEYWORD_CATEGORY_MAP.items():
            trend_rows = (
                ExternalTrendData.query
                .filter_by(keyword=keyword)
                .order_by(ExternalTrendData.period_date)
                .all()
            )
            if not trend_rows:
                continue

            scores = [r.interest_score for r in trend_rows]
            half = len(scores) // 2
            prev_avg = sum(scores[:half]) / max(len(scores[:half]), 1)
            curr_avg = sum(scores[half:]) / max(len(scores[half:]), 1)

            internal_curr = current_internal.get(category, 0)
            internal_prev = previous_internal.get(category, 0)
            vendor_count = vendor_counts.get(category, 0)

            correlation = None
            try:
                if len(scores) >= 3:
                    correlation = round(float(correlation), 3)
            except Exception:
                correlation = None

            ext_change = _pct_change(curr_avg, prev_avg)
            internal_change = _pct_change(internal_curr, internal_prev)

            insight_text = _build_insight_text(category, ext_change, internal_change, vendor_count)

            db.session.add(CategoryInsight(
                category=category,
                external_score_avg=float(round(curr_avg, 2)),
                external_score_change_pct=float(ext_change),
                internal_activity_count=int(internal_curr),
                internal_change_pct=float(internal_change),
                correlation_score=float(correlation) if correlation is not None else None,
                vendor_count=int(vendor_count),
                insight_text=insight_text
                ))

        db.session.commit()
        logger.info("Insight kategori berhasil digenerate.")

    except Exception as e:
        db.session.rollback()
        logger.error(f"Gagal generate insight: {e}")


def _build_insight_text(category, ext_change, internal_change, vendor_count):
    if ext_change > 15 and internal_change > 15:
        return (f"Minat kategori '{category}' naik kuat baik di pencarian umum ({ext_change}%) "
                f"maupun di aktivitas favorite user Simpul ({internal_change}%). "
                f"Sinyal valid — pertimbangkan tambah vendor baru di kategori ini.")
    elif ext_change > 15 and internal_change <= 15:
        return (f"Minat kategori '{category}' naik di pencarian umum ({ext_change}%) "
                f"tapi belum terlihat di aktivitas user Simpul. "
                f"Kemungkinan tren musiman/eksternal — pantau dulu.")
    elif ext_change <= 15 and internal_change > 15:
        return (f"Aktivitas favorite user Simpul untuk kategori '{category}' naik ({internal_change}%) "
                f"meski tren pencarian umum stabil. Saat ini {vendor_count} vendor terdaftar — "
                f"pertimbangkan evaluasi kecukupan jumlah vendor.")
    else:
        return (f"Kategori '{category}' relatif stabil "
                f"(eksternal {ext_change}%, internal {internal_change}%).")