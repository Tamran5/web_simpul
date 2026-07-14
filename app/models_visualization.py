from datetime import datetime
from app.extensions import db


class ExternalTrendData(db.Model):
    __tablename__ = 'external_trend_data'

    id            = db.Column(db.Integer, primary_key=True)
    keyword       = db.Column(db.String(100), nullable=False)
    region        = db.Column(db.String(100), nullable=False)
    period_date   = db.Column(db.Date, nullable=False)
    interest_score = db.Column(db.Integer, nullable=False)
    fetched_at    = db.Column(db.DateTime, default=datetime.utcnow)


class CategoryInsight(db.Model):
    __tablename__ = 'category_insight'

    id                       = db.Column(db.Integer, primary_key=True)
    category                 = db.Column(db.String(50), nullable=False)
    external_score_avg       = db.Column(db.Float, nullable=False)
    external_score_change_pct = db.Column(db.Float, nullable=False)
    internal_activity_count  = db.Column(db.Integer, nullable=False)
    internal_change_pct      = db.Column(db.Float, nullable=False)
    correlation_score        = db.Column(db.Float, nullable=True)
    vendor_count             = db.Column(db.Integer, nullable=False)
    insight_text             = db.Column(db.Text, nullable=False)
    generated_at             = db.Column(db.DateTime, default=datetime.utcnow)