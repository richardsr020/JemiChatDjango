from datetime import datetime, timedelta
from django import template

register = template.Library()


@register.filter
def startswith(value, prefix):
    return str(value).startswith(str(prefix))


@register.filter
def firstchar(value):
    text = str(value or '')
    return text[:1].upper() if text else '?'


@register.filter
def filesize(value):
    size = float(value or 0)
    units = ['B', 'KB', 'MB', 'GB']
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    return f"{size:.2f} {units[idx]}"


@register.filter
def to_hm(value):
    return _parse_dt(value).strftime('%H:%M') if value else ''


@register.filter
def to_dmy(value):
    return _parse_dt(value).strftime('%d/%m/%Y') if value else ''


@register.filter
def to_dmy_hm(value):
    return _parse_dt(value).strftime('%d/%m/%Y %H:%M') if value else ''


@register.filter
def day_label(value):
    dt = _parse_dt(value)
    now = datetime.utcnow()
    if dt.date() == now.date():
        return "Aujourd'hui"
    if dt.date() == (now - timedelta(days=1)).date():
        return 'Hier'
    return dt.strftime('%d/%m/%Y')


def _parse_dt(value):
    if isinstance(value, datetime):
        return value
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            continue
    return datetime.utcnow()
