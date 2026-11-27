"""Single-record switches for explicitly editable admin list columns."""
import re

from django.contrib import admin, messages
from django.core.exceptions import NON_FIELD_ERRORS, PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404, HttpResponseRedirect, JsonResponse
from django.template.loader import render_to_string
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect

from .models import Audit


class StateListMixin:
    change_list_template = 'admin/portal/state_list.html'
    state_fields = ()
    # These columns convey a status but must never accept a list mutation.
    indicator_fields = ()
    state_words = {}  # field -> (on label, off label)
    state_labels = {}
    state_ordering = {}
    list_hint = 'برای تغییر وضعیت، روی دکمهٔ همان ردیف بزن. تغییر همان لحظه ذخیره می‌شود.'

    def state_block(self, obj, field):
        """Optional (short label, explanation) when this control is inapplicable."""
        return None

    def validate_activation(self, obj, field):
        obj.full_clean()

    def _column(self, request, name):
        label = self.state_labels.get(name, self.opts.get_field(name).verbose_name)

        @admin.display(description=label, ordering=self.state_ordering.get(name, name))
        def column(obj):
            lock = self.state_block(obj, name)
            editable = (not lock and name in self.state_fields and '_popup' not in request.GET
                        and self.has_change_permission(request, obj)
                        and name not in self.get_readonly_fields(request, obj))
            on, off = self.state_words.get(name, ('فعال', 'غیرفعال'))
            checked = getattr(obj, name)
            return render_to_string('admin/portal/state_cell.html', {
                'editable': editable, 'lock':lock, 'checked':checked, 'on':on, 'off':off,
                'label':label, 'record':str(obj), 'pk':obj.pk, 'field':name,
            })

        column.__name__ = 'state_' + name
        return column

    def get_list_display(self, request):
        return [self._column(request, name) if name in (*self.state_fields, *self.indicator_fields) else name
                for name in super().get_list_display(request)]

    def get_sortable_by(self, request):
        # None allows Django to use each request-local column's ordering metadata.
        return self.sortable_by

    def _reply(self, request, message, *, status=200, checked=None):
        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({'message':message, 'checked':checked}, status=status)
        self.message_user(request, message, messages.SUCCESS if status == 200 else messages.ERROR)
        return HttpResponseRedirect(request.get_full_path())

    @transaction.atomic
    def _set_state(self, request):
        if not self.has_change_permission(request) or '_popup' in request.GET:
            raise PermissionDenied
        values = request.POST.getlist('_dp_state')
        match = re.fullmatch(r'([1-9][0-9]{0,18}):([a-z_]+):([01])', values[0]) if len(values) == 1 else None
        if not match or match[2] not in self.state_fields or int(match[1]) > 2**63-1:
            return self._reply(request, 'دکمهٔ وضعیت معتبر نیست.', status=400)
        pk, field, desired = int(match[1]), match[2], match[3] == '1'
        # Respect any ModelAdmin row scoping without locking joined/annotated rows.
        scope = self.get_queryset(request).filter(pk=pk).order_by().values('pk')
        obj = self.model._default_manager.select_for_update().filter(pk=pk, pk__in=scope).first()
        if obj is None:
            raise Http404
        if not self.has_change_permission(request, obj) or field in self.get_readonly_fields(request, obj):
            raise PermissionDenied
        old = getattr(obj, field)
        lock = self.state_block(obj, field)
        if lock:
            return self._reply(request, lock[1], status=422)
        if old != desired:
            setattr(obj, field, desired)
            if desired:
                # Always allow switching an invalid/obsolete record off.
                try:
                    self.validate_activation(obj, field)
                except ValidationError as error:
                    errors = error.message_dict if hasattr(error, 'error_dict') else {NON_FIELD_ERRORS:error.messages}
                    reasons = [
                        (f'{self.opts.get_field(key).verbose_name}: ' if key != NON_FIELD_ERRORS else '') + text
                        for key, texts in errors.items() for text in texts
                    ]
                    return self._reply(request, ' · '.join(reasons), status=422, checked=old)
            updated = [f.name for f in self.opts.fields if getattr(f, 'auto_now', False)]
            obj.save(update_fields=[field, *updated])
            Audit.objects.create(actor=request.user, action=self.opts.model_name+'.update', object_ref=str(obj.pk),
                                 details={'fields':[field], 'old':old, 'new':desired})
            self.log_change(request, obj, [{'changed':{'fields':[str(self.opts.get_field(field).verbose_name)]}}])
        on, off = self.state_words.get(field, ('فعال', 'غیرفعال'))
        label = self.state_labels.get(field, self.opts.get_field(field).verbose_name)
        return self._reply(request, f'{obj} — {label}: {on if desired else off}. ذخیره شد.',
                           checked=desired)

    @method_decorator(csrf_protect)
    def changelist_view(self, request, extra_context=None):
        if request.method == 'POST' and '_dp_state' in request.POST:
            return self._set_state(request)
        context = {'state_list_editable':self.has_change_permission(request), 'state_list_hint':self.list_hint}
        return super().changelist_view(request, {**context, **(extra_context or {})})
