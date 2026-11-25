"""Read-only, permission-scoped data for the store manager's overview."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta

import jdatetime
from django.db.models import Count, Q, Sum
from django.urls import reverse
from django.utils import timezone

from .models import Account, Order, Post, Product, SourceProduct, Ticket


PERIODS = (('today', 'امروز', 1), ('week', '۷ روز', 7), ('month', '۳۰ روز', 30), ('year', 'یک سال', 365))
MONTHS = 'فروردین اردیبهشت خرداد تیر مرداد شهریور مهر آبان آذر دی بهمن اسفند'.split()
WEEKDAYS = 'دوشنبه سه‌شنبه چهارشنبه پنجشنبه جمعه شنبه یکشنبه'.split()
DIGITS = str.maketrans('0123456789,', '۰۱۲۳۴۵۶۷۸۹٬')
IN_PROGRESS = ('pending', 'confirmed', 'approved', 'processing')


def date_label(day, *, monthly=False, year=True):
    jalali = jdatetime.date.fromgregorian(date=day)
    parts = ([] if monthly else [str(jalali.day)]) + [MONTHS[jalali.month - 1]]
    if year:
        parts.append(str(jalali.year))
    return ' '.join(parts).translate(DIGITS)


def midnight(day):
    return timezone.make_aware(datetime.combine(day, time.min))


def sales_report(params, today):
    durations = {key: days for key, _, days in PERIODS}
    period = params.get('period', 'week')
    end, error = today, ''
    if period == 'custom':
        try:
            start, end = (date.fromisoformat(params.get(field, '')) for field in ('start', 'end'))
            if not date(2000, 1, 1) <= start <= end <= today or (end - start).days > 365:
                raise ValueError
        except ValueError:
            period, end = 'week', today
            error = 'بازه معتبر نیست. حداکثر ۳۶۶ روز تا امروز را انتخاب کن. گزارش ۷ روز گذشته نمایش داده شده است.'
    elif period not in durations:
        period = 'week'
    if period != 'custom':
        start = today - timedelta(days=durations[period] - 1)
    monthly = (end - start).days > 60

    # Local days do not require MariaDB named-timezone tables. For long ranges,
    # use actual Solar Hijri month boundaries, including the transition at Nowruz.
    buckets = {}
    day = start
    while day <= end:
        buckets[day] = jdatetime.date.fromgregorian(date=day).replace(day=1).togregorian() if monthly else day
        day += timedelta(days=1)
    amounts = defaultdict(int)
    orders = Order.objects.filter(status='completed', completed_at__gte=midnight(start),
                                  completed_at__lt=midnight(end + timedelta(days=1)))
    count = 0
    for when, amount in orders.order_by().values_list('completed_at', 'total_price').iterator():
        amounts[buckets[timezone.localtime(when).date()]] += amount
        count += 1
    chart = [{'label': key.isoformat(), 'display': date_label(key, monthly=monthly),
              'tick': date_label(key, monthly=monthly, year=False), 'amount': amounts[key]}
             for key in dict.fromkeys(buckets.values())]
    return {'periods': PERIODS, 'report_start': start, 'report_end': end, 'report_period': period,
            'report_error': error, 'range_sales': sum(amounts.values()), 'range_order_count': count,
            'monthly_buckets': monthly, 'sales_chart': chart,
            'report_caption': date_label(start) if start == end else f'{date_label(start)} تا {date_label(end)}'}


def dashboard_context(request):
    today = timezone.localdate()
    first, after = midnight(today), midnight(today + timedelta(days=1))
    metrics, tasks = [], []
    context = {'dashboard_date': today, 'today_caption': WEEKDAYS[today.weekday()] + '، ' + date_label(today),
               'dashboard_metrics': metrics, 'desk_tasks': tasks}
    can = request.user.has_perm

    def metric(label, value, unit, icon, tone, href):
        metrics.append(dict(label=label, value=value, unit=unit, icon=icon, tone=tone, href=href))

    def task(label, count, icon, tone, route, query):
        tasks.append(dict(label=label, count=count, icon=icon, tone=tone, href=reverse(route) + '?' + query))

    if can('portal.view_order'):
        stats = Order.objects.aggregate(
            awaiting=Count('pk', filter=Q(status='pending')),
            ongoing=Count('pk', filter=Q(status__in=IN_PROGRESS)),
            received=Count('pk', filter=Q(created_at__gte=first, created_at__lt=after)),
            total=Sum('total_price', filter=Q(status='completed')),
            today=Sum('total_price', filter=Q(status='completed', completed_at__gte=first, completed_at__lt=after)))
        context.update(sales_report(request.GET, today))
        context.update(recent_orders=Order.objects.only('product_name','created_at','total_price','tracking_code','status')[:6],
                       completed_revenue=stats['total'] or 0, pending_orders_count=stats['ongoing'],
                       today_sales=stats['today'] or 0)
        metric('فروش امروز', stats['today'] or 0, 'تومان', 'wallet', 'green', '?period=today#sales')
        metric('سفارش‌های امروز', stats['received'], 'سفارش', 'bag', 'indigo', '#orders')
        task('سفارش در انتظار بررسی', stats['awaiting'], 'bag', 'amber', 'admin:portal_order_changelist', 'status__exact=pending')
    if can('portal.view_product'):
        metric('محصولات ثبت‌شده', Product.objects.count(), 'محصول', 'box', 'blue', reverse('admin:portal_product_changelist'))
    if can('portal.view_account'):
        new = Account.objects.filter(created_at__gte=first, created_at__lt=after).count()
        metric('ثبت‌نام امروز', new, 'نفر', 'user', 'rose', reverse('admin:portal_account_changelist'))
    if can('portal.view_ticket'):
        tickets = Ticket.objects.exclude(status='closed')
        context['recent_tickets'] = tickets.only('subject','priority','status','updated_at')[:5]
        task('تیکت در انتظار پاسخ', tickets.filter(status='open').count(), 'chat', 'indigo',
             'admin:portal_ticket_changelist', 'status__exact=open')
        if not can('portal.view_order'):
            metric('تیکت‌های فعال', tickets.count(), 'تیکت', 'headset', 'green', '#tickets')
    if can('portal.view_sourceproduct'):
        counts = SourceProduct.objects.aggregate(pending=Count('pk', filter=Q(review_status='pending')),
                                                 conflict=Count('pk', filter=Q(review_status='conflict')))
        task('قیمت پیشنهادی منبع', counts['pending'], 'tag', 'green',
             'admin:portal_sourceproduct_changelist', 'review_status__exact=pending')
        task('تعارض قیمت منبع', counts['conflict'], 'layers', 'rose',
             'admin:portal_sourceproduct_changelist', 'review_status__exact=conflict')
    if not metrics and can('portal.view_post'):
        metric('مقاله‌های منتشرشده', Post.objects.filter(published=True).count(), 'مقاله', 'book', 'blue',
               reverse('admin:portal_post_changelist') + '?published__exact=1')
    context['task_count'] = sum(task['count'] for task in tasks)
    return context
