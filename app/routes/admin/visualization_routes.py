from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request
from sqlalchemy import func

from app.extensions import db
from typing import Dict, Optional
from app.models_visualization import CategoryInsight, ExternalTrendData

visualization_bp = Blueprint("visualization", __name__, url_prefix="/api/visualization")


# ── Helper: hitung batas bawah tanggal berdasarkan param range ───────────
_RANGE_DAYS: Dict[str, Optional[int]] = {
    "week":   7,
    "month":  30,
    "3month": 90,
    "year":   365,
    "all":    None,          # None = tanpa filter tanggal
}

def _date_cutoff(range_param: str) -> Optional[datetime]:
    """
    Kembalikan datetime batas bawah (UTC, naive) sesuai range_param.
    Kembalikan None jika range = 'all' atau tidak dikenali.
    """
    days = _RANGE_DAYS.get(range_param)
    if days is None:
        return None
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)


def _get_range() -> str:
    """Baca & validasi query-param ?range=. Default: '3month'."""
    raw = request.args.get("range", "3month").strip().lower()
    return raw if raw in _RANGE_DAYS else "3month"


# ── GET /api/visualization/trend-line ────────────────────────────────────
@visualization_bp.route("/trend-line", methods=["GET"])
def get_trend_line_data():
    """
    Kembalikan data time-series per keyword untuk Line Chart.

    Response shape:
        {
          "chart_type": "line",
          "range": "month",
          "series": {
            "Dekorasi Pernikahan": {"x": ["2025-01-01", ...], "y": [72, ...]},
            ...
          }
        }
    """
    range_key = _get_range()
    cutoff    = _date_cutoff(range_key)

    query = ExternalTrendData.query.order_by(ExternalTrendData.period_date)
    if cutoff:
        query = query.filter(ExternalTrendData.period_date >= cutoff)

    rows: list[ExternalTrendData] = query.all()

    series: dict = {}
    for row in rows:
        bucket = series.setdefault(row.keyword, {"x": [], "y": []})
        bucket["x"].append(row.period_date.isoformat())
        bucket["y"].append(row.interest_score)

    return jsonify({"chart_type": "line", "range": range_key, "series": series})


# ── GET /api/visualization/keyword-comparison ─────────────────────────────
@visualization_bp.route("/keyword-comparison", methods=["GET"])
def get_keyword_comparison_data():
    """
    Kembalikan rata-rata skor per keyword dalam rentang yang dipilih.

    Response shape:
        {
          "chart_type": "bar",
          "range": "month",
          "labels": ["Dekorasi Pernikahan", "Fotografer", ...],
          "values": [68.4, 54.1, ...]
        }
    """
    range_key = _get_range()
    cutoff    = _date_cutoff(range_key)

    query = db.session.query(
        ExternalTrendData.keyword,
        func.avg(ExternalTrendData.interest_score).label("avg_score"),
    ).group_by(ExternalTrendData.keyword)

    if cutoff:
        query = query.filter(ExternalTrendData.period_date >= cutoff)

    results = query.order_by(func.avg(ExternalTrendData.interest_score).desc()).all()

    return jsonify({
        "chart_type": "bar",
        "range":      range_key,
        "labels":     [r.keyword    for r in results],
        "values":     [round(r.avg_score, 2) for r in results],
    })


# ── GET /api/visualization/insights ──────────────────────────────────────
@visualization_bp.route("/insights", methods=["GET"])
def get_category_insights():
    """
    Kembalikan insight otomatis per kategori yang di-generate dalam
    rentang waktu yang dipilih.

    Response shape:
        [
          {
            "category": "Fotografer",
            "external_change_pct": 12,
            "internal_change_pct": 8,
            "vendor_count": 14,
            "insight": "...",
            "generated_at": "2025-06-01T10:00:00"
          },
          ...
        ]
    """
    range_key = _get_range()
    cutoff    = _date_cutoff(range_key)

    query = CategoryInsight.query.order_by(CategoryInsight.generated_at.desc())
    if cutoff:
        query = query.filter(CategoryInsight.generated_at >= cutoff)

    insights: list[CategoryInsight] = query.all()

    return jsonify([
        {
            "category":             i.category,
            "external_change_pct":  i.external_score_change_pct,
            "internal_change_pct":  i.internal_change_pct,
            "vendor_count":         i.vendor_count,
            "insight":              i.insight_text,
            "generated_at":         i.generated_at.isoformat(),
        }
        for i in insights
    ])