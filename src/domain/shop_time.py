"""IST business-day boundaries for shop analytics."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

SHOP_TZ = ZoneInfo("Asia/Kolkata")
UTC = UTC


def business_date_from_utc(timestamp: datetime) -> date:
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(SHOP_TZ).date()


def utc_bounds_for_ist_date(business_date: date) -> tuple[datetime, datetime]:
    start_local = datetime.combine(business_date, time.min, tzinfo=SHOP_TZ)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def utc_bounds_for_ist_range(
    start_date: date,
    end_date: date,
) -> tuple[datetime, datetime]:
    range_start_utc, _ = utc_bounds_for_ist_date(start_date)
    _, range_end_exclusive_utc = utc_bounds_for_ist_date(end_date)
    return range_start_utc, range_end_exclusive_utc


def today_ist() -> date:
    return datetime.now(tz=UTC).astimezone(SHOP_TZ).date()


def rolling_last_n_ist_days(day_count: int = 7) -> tuple[date, date]:
    end_date = today_ist()
    start_date = end_date - timedelta(days=day_count - 1)
    return start_date, end_date
