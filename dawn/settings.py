import os,json
from pathlib import Path
BASE_DIR=Path(__file__).resolve().parent.parent
CONFIG_PATH=os.environ.get('DAWN_CONFIG','')
BOT_CONFIG=json.loads(Path(CONFIG_PATH).read_text()) if CONFIG_PATH else {}
SECRET_KEY=os.environ.get('DJANGO_SECRET_KEY','local-tests-only-do-not-deploy')
DEBUG=os.environ.get('DAWN_DEBUG','0')=='1'
PRODUCTION=os.environ.get('DAWN_PRODUCTION','0')=='1'
if PRODUCTION and SECRET_KEY=='local-tests-only-do-not-deploy': raise RuntimeError('DJANGO_SECRET_KEY required')
ALLOWED_HOSTS=os.environ.get('ALLOWED_HOSTS','dawnpanel.ir,www.dawnpanel.ir,apibot.dawnpanel.ir,localhost,127.0.0.1,testserver').split(',')
CSRF_TRUSTED_ORIGINS=['https://dawnpanel.ir','https://www.dawnpanel.ir','https://apibot.dawnpanel.ir']
INSTALLED_APPS=['django.contrib.admin','django.contrib.auth','django.contrib.contenttypes','django.contrib.sessions','django.contrib.messages','django.contrib.staticfiles','portal']
MIDDLEWARE=['django.middleware.security.SecurityMiddleware','whitenoise.middleware.WhiteNoiseMiddleware','django.contrib.sessions.middleware.SessionMiddleware','django.middleware.common.CommonMiddleware','django.middleware.csrf.CsrfViewMiddleware','django.contrib.auth.middleware.AuthenticationMiddleware','django.contrib.messages.middleware.MessageMiddleware','django.middleware.clickjacking.XFrameOptionsMiddleware','portal.middleware.SecurityHeaders']
ROOT_URLCONF='dawn.urls'
TEMPLATES=[{'BACKEND':'django.template.backends.django.DjangoTemplates','DIRS':[BASE_DIR/'templates'],'APP_DIRS':True,'OPTIONS':{'context_processors':['django.template.context_processors.request','django.contrib.auth.context_processors.auth','django.contrib.messages.context_processors.messages','portal.context.brand']}}]
WSGI_APPLICATION='dawn.wsgi.application'
if BOT_CONFIG:
 db=BOT_CONFIG['database']
 DATABASES={'default':{'ENGINE':'django.db.backends.mysql','NAME':db['database'],'USER':db['user'],'PASSWORD':db['password'],'HOST':db.get('host','127.0.0.1'),'PORT':db.get('port',3306),'OPTIONS':{'charset':'utf8mb4','init_command':"SET sql_mode='STRICT_TRANS_TABLES'"},'CONN_MAX_AGE':60,'ATOMIC_REQUESTS':False}}
else: DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':BASE_DIR/'local.sqlite3'}}
AUTH_PASSWORD_VALIDATORS=[{'NAME':'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},{'NAME':'django.contrib.auth.password_validation.MinimumLengthValidator','OPTIONS':{'min_length':14}},{'NAME':'django.contrib.auth.password_validation.CommonPasswordValidator'},{'NAME':'django.contrib.auth.password_validation.NumericPasswordValidator'}]
LANGUAGE_CODE='fa-ir'
TIME_ZONE='Asia/Tehran'
USE_I18N=True
USE_TZ=True
STATIC_URL='/static/'
STATIC_ROOT=BASE_DIR/'staticfiles'
STATICFILES_DIRS=[BASE_DIR/'static']
STORAGES={'default':{'BACKEND':'django.core.files.storage.FileSystemStorage'},'staticfiles':{'BACKEND':'whitenoise.storage.CompressedManifestStaticFilesStorage'}}
DEFAULT_AUTO_FIELD='django.db.models.BigAutoField'
LOGIN_URL='/login/'
SESSION_COOKIE_AGE=43200
SESSION_COOKIE_HTTPONLY=True
SESSION_COOKIE_SAMESITE='Lax'
SESSION_COOKIE_SECURE=PRODUCTION
CSRF_COOKIE_SECURE=PRODUCTION
SECURE_SSL_REDIRECT=PRODUCTION
SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO','https')
SECURE_HSTS_SECONDS=31536000 if PRODUCTION else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS=False
SECURE_CONTENT_TYPE_NOSNIFF=True
SECURE_REFERRER_POLICY='same-origin'
X_FRAME_OPTIONS='DENY'
DATA_UPLOAD_MAX_MEMORY_SIZE=262144
DATA_UPLOAD_MAX_NUMBER_FIELDS=150
OWNER_PHONE=os.environ.get('DAWN_OWNER_PHONE','')
LOGGING={'version':1,'disable_existing_loggers':False,'handlers':{'console':{'class':'logging.StreamHandler'}},'root':{'handlers':['console'],'level':'INFO'},'loggers':{'django.security':{'handlers':['console'],'level':'WARNING','propagate':False}}}

# Subdomains may host independent services; do not preload or impose HSTS on them.
SILENCED_SYSTEM_CHECKS=['security.W005','security.W021']

if os.environ.get('DAWN_TEST_MYSQL')=='1':
    if PRODUCTION: raise RuntimeError('Test database mode cannot run in production')
    DATABASES={'default':{'ENGINE':'django.db.backends.mysql','NAME':'dawnpanel_ci','USER':os.environ.get('DAWN_TEST_DB_USER','root'),'PASSWORD':os.environ.get('DAWN_TEST_DB_PASSWORD','ci-test-only'),'HOST':'127.0.0.1','PORT':os.environ.get('DAWN_TEST_DB_PORT','3306'),'OPTIONS':{'charset':'utf8mb4'}}}

# Telegram's token is part of its API URL; never log routine HTTP client URLs.
LOGGING['loggers'].update({'httpx':{'level':'WARNING'},'httpcore':{'level':'WARNING'}})
