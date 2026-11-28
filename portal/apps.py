from django.apps import AppConfig
class PortalConfig(AppConfig):
    default_auto_field='django.db.models.BigAutoField'
    name='portal'
    verbose_name='دان پنل'
    def ready(self):
        from . import ops_activity, chat_notices  # transactional notice receivers
