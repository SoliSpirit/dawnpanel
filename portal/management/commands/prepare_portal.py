from django.core.management.base import BaseCommand
from django.db import connection
from django.contrib.auth.models import Group,Permission,User
from django.conf import settings
from portal.models import Post,MemberRank

class Command(BaseCommand):
    help='Apply additive legacy schema changes and install staff roles.'
    def handle(self,*args,**options):
        if connection.vendor!='mysql': self.stdout.write('Legacy schema changes skipped on SQLite');return
        with connection.cursor() as c:
            c.execute("SHOW COLUMNS FROM phone_verification_codes LIKE 'verification_code'")
            info=c.fetchone()
            if info and info[1]!='varchar(64)':
                c.execute('ALTER TABLE phone_verification_codes MODIFY verification_code VARCHAR(64) NULL')
            c.execute('UPDATE phone_verification_codes SET verification_code=NULL,expires_at=NULL WHERE verification_code IS NOT NULL AND CHAR_LENGTH(verification_code)<64')
            c.execute('UPDATE phone_verification_codes SET last_code=NULL WHERE last_code IS NOT NULL')
            existing={x.name for x in connection.introspection.get_table_description(c,'products')}
            additions={'show_on_website':'TINYINT(1) NOT NULL DEFAULT 0','show_on_telegram':'TINYINT(1) NOT NULL DEFAULT 1','platform':"VARCHAR(20) NOT NULL DEFAULT 'telegram'",'seo_description':"VARCHAR(160) NOT NULL DEFAULT ''"}
            for name,ddl in additions.items():
                if name not in existing: c.execute('ALTER TABLE products ADD COLUMN `'+name+'` '+ddl)
            cols={x.name for x in connection.introspection.get_table_description(c,'gift_code_uses')}
            if 'amount' not in cols: c.execute('ALTER TABLE gift_code_uses ADD COLUMN amount BIGINT NOT NULL DEFAULT 0')
            c.execute("UPDATE products p JOIN categories c ON p.category_id=c.id SET p.platform='rubika',p.show_on_website=1 WHERE c.name LIKE %s AND p.platform='telegram'",['%روبیکا%'])
        roles={'پشتیبان':['view_ticket','change_ticket','view_account','view_chatconversation','change_chatconversation'],'مدیر سفارش':['view_order','change_order','view_ledger','view_legacyuser','view_ticket','change_ticket'],'مدیر محصول':['view_product','add_product','change_product','view_category','add_category','change_category'],'نویسنده':['view_post','add_post','change_post'],'مدیر ارشد':['view_chatconversation','change_chatconversation','view_order','change_order','view_ledger','view_legacyuser','change_legacyuser','view_ticket','change_ticket','view_account','view_product','add_product','change_product','view_category','add_category','change_category','view_post','add_post','change_post','view_audit','view_currency','add_currency','change_currency','view_giftcode','add_giftcode','change_giftcode','view_memberrank','add_memberrank','change_memberrank']}
        for name,permissions in roles.items():
            group,_=Group.objects.get_or_create(name=name)
            group.permissions.set(Permission.objects.filter(content_type__app_label='portal',codename__in=permissions))
        for name,threshold in [('همراه',0),('نقره‌ای',1000000),('طلایی',10000000)]: MemberRank.objects.get_or_create(name=name,defaults={'min_spending':threshold})
        self.stdout.write(self.style.SUCCESS('Schema and role permissions ready'))
