import logging
from datetime import datetime, timedelta
from sqlalchemy import func
from app.extensions import db
from app.models import Vendor, FavoriteVendor

logger = logging.getLogger(__name__)


def get_internal_activity_by_category(days=30):
    """
    Proxy minat internal user Simpul: jumlah FavoriteVendor per kategori
    (karena belum ada log 'view vendor' di Simpul).
    """
    now = datetime.utcnow()
    current_start = now - timedelta(days=days)
    previous_start = now - timedelta(days=days * 2)

    def count_by_category(start, end):
        results = (
            db.session.query(Vendor.category, func.count(FavoriteVendor.id))
            .join(FavoriteVendor, FavoriteVendor.vendor_id == Vendor.id)
            .filter(FavoriteVendor.created_at.between(start, end))
            .group_by(Vendor.category)
            .all()
        )
        return {category: count for category, count in results}

    current = count_by_category(current_start, now)
    previous = count_by_category(previous_start, current_start)

    vendor_counts = dict(
        db.session.query(Vendor.category, func.count(Vendor.id))
        .group_by(Vendor.category).all()
    )

    return current, previous, vendor_counts