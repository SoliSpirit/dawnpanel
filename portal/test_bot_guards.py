"""Exercise actual bot handler bodies without importing the live bot/config."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from django.conf import settings
from django.test import SimpleTestCase


class BotProductPhotoTests(SimpleTestCase):
    def run_photo_handler(self, photo):
        from unittest.mock import Mock
        tree=ast.parse((Path(settings.BASE_DIR)/'telegram/dawnpanel.py').read_text(encoding='utf-8'))
        handler=next(node for node in tree.body if isinstance(node,ast.AsyncFunctionDef) and node.name=='show_product_photo')
        cleanup=AsyncMock()
        namespace={'asyncio':asyncio,'integration':SimpleNamespace(product_photo=Mock(return_value=photo)),
                   'discard_product_message':cleanup,'logger':Mock()}
        exec(compile(ast.Module(body=[handler],type_ignores=[]),'<bot-product-photo>','exec'),namespace)
        message=SimpleNamespace(reply_photo=AsyncMock(),reply_text=AsyncMock())
        query=SimpleNamespace(message=message,edit_message_text=AsyncMock())
        asyncio.run(namespace['show_product_photo'](query,4,'Suno','Product details','keyboard'))
        return query, cleanup

    def test_product_shows_photo_and_purchase_keyboard(self):
        query,cleanup=self.run_photo_handler(b'image')
        query.message.reply_photo.assert_awaited_once_with(photo=b'image',caption='Product details',
                                                           parse_mode='HTML',reply_markup='keyboard')
        cleanup.assert_awaited_once_with(query.message)
        query.edit_message_text.assert_not_awaited()

    def test_missing_photo_falls_back_to_usable_text(self):
        query,cleanup=self.run_photo_handler(None)
        query.edit_message_text.assert_awaited_once_with('Product details',reply_markup='keyboard',parse_mode='HTML')
        cleanup.assert_not_awaited()


class BotInvoiceTests(SimpleTestCase):
    def test_legacy_bot_rates_use_selling_for_products_buying_for_deposits(self):
        import html
        from decimal import Decimal,InvalidOperation
        from django.utils import timezone
        from portal.exchange_rates import resolve,RateError
        tree=ast.parse((settings.BASE_DIR/'telegram/integration.py').read_text(encoding='utf-8'))
        adapter=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='bot_currency_record')
        ns={'resolve':resolve,'RateError':RateError,'Decimal':Decimal,'InvalidOperation':InvalidOperation,'html':html,'format_amount':str}
        exec(compile(ast.Module(body=[adapter],type_ignores=[]),'<bot-currency>', 'exec'),ns)
        row=ns['bot_currency_record']({'code':'USDT','type':'crypto','name':'تتر','rate':85000,'observed_at':timezone.now().replace(tzinfo=None),
            'fx_source':'nobitex','quote_key':'nobitex:USDT','market_bid':Decimal(280000),'market_ask':Decimal(280000),
            'candidate_key':'nobitex:USDT','candidate_at':timezone.now(),'published_at':timezone.now(),
            'sell_extra':5000,'buy_less':10000,'spread_mode':'fixed'})
        self.assertEqual((row['rate'],row['buy_rate']),(285000,270000))
        tree=ast.parse((settings.BASE_DIR/'telegram/dawnpanel.py').read_text(encoding='utf-8'))
        funcs=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('currency_quote_line','get_star_rate_toman')]
        exec(compile(ast.Module(body=funcs,type_ignores=[]),'<bot-currency-presentation>','exec'),ns)
        message=ns['currency_quote_line'](row)
        self.assertIn('خرید از شما: 270000',message)
        self.assertIn('فروش به شما: 285000',message)
        manual={'code':'STAR','type':'telegram','rate':3000,'fx_source':'manual','quote_key':'','market_bid':None,
                'market_ask':None,'spread_mode':'fixed','sell_extra':100,'buy_less':200}
        ns['get_currency']=lambda code: ns['bot_currency_record'](manual.copy())
        self.assertEqual(ns['get_star_rate_toman'](),2800)
        manual['buy_less']=0
        self.assertIsNone(ns['get_star_rate_toman']())

    def test_final_review_discloses_order_tax_and_pins_the_breakdown(self):
        import html
        from .pricing import Pricing
        tree=ast.parse((Path(settings.BASE_DIR)/'telegram/dawnpanel.py').read_text(encoding='utf-8'))
        handler=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='finalize_order')
        for arg in handler.args.args: arg.annotation=None
        namespace={'html':html,'is_user_banned':lambda _: (False,None),'get_product':lambda _: (15,1,'Product'),
                   'order_pricing':AsyncMock(return_value=Pricing(1183,100,10,1000,950)),
                   'get_user_data':lambda _: {'balance':1000},'format_amount':str,
                   'InlineKeyboardMarkup':lambda rows: rows,'InlineKeyboardButton':lambda *a,**kw: kw}
        exec(compile(ast.Module(body=[handler],type_ignores=[]),'<bot-invoice>','exec'),namespace)
        update=SimpleNamespace(effective_user=SimpleNamespace(id=123),effective_message=SimpleNamespace(reply_text=AsyncMock()))
        context=SimpleNamespace(user_data={'product_id':15,'order_quantity':11})
        asyncio.run(namespace['finalize_order'](update,context,'test'))
        review=update.effective_message.reply_text.await_args.args[0]
        for line in ('مبلغ پیش از مالیات: 131 تومان','مالیات (9.5٪): 13 تومان','144 تومان'):
            self.assertIn(line,review)
        self.assertEqual(context.user_data['pending_order_breakdown'],{'subtotal':131,'tax_bps':950})
        self.assertEqual(context.user_data['pending_order_total_price'],144)

    def test_star_invoice_quotes_discount_before_payment_and_precheckout_rejects_a_changed_rate(self):
        import re
        from datetime import timedelta
        from decimal import Decimal,InvalidOperation
        from unittest.mock import MagicMock,Mock
        from django.utils import timezone
        from .exchange_rates import resolve,RateError
        tree=ast.parse((settings.BASE_DIR/'telegram/dawnpanel.py').read_text(encoding='utf-8'))
        factory=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='create_charge_handler')
        invoice=next(n for n in factory.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='receive_stars_amount')
        check=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='precheckout_star_payment')
        settle=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='successful_star_payment')
        rate_reader=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='get_star_rate_toman')
        adapter_tree=ast.parse((settings.BASE_DIR/'telegram/integration.py').read_text(encoding='utf-8'))
        adapter=next(n for n in adapter_tree.body if isinstance(n,ast.FunctionDef) and n.name=='bot_currency_record')
        for fn in (invoice,check,settle):
            for arg in fn.args.args:arg.annotation=None
        db=MagicMock()
        at=timezone.now().replace(tzinfo=None)
        record={'code':'STAR','type':'telegram','rate':3000,'fx_source':'denapanel','quote_key':'denapanel:STAR',
                'market_bid':Decimal(4560),'market_ask':Decimal(4560),'candidate_key':'denapanel:STAR',
                'observed_at':at,'candidate_at':at,'published_at':at,'spread_mode':'percent','buy_less':10,'sell_extra':0}
        ns={'Decimal':Decimal,'InvalidOperation':InvalidOperation,'MIN_STARS':1,'MAX_STARS':10000,
            'get_setting':lambda key,default:default,'STARS_AMOUNT_INPUT':5,'ConversationHandler':SimpleNamespace(END=-1),
            'resolve':resolve,'RateError':RateError,'get_currency':lambda code:ns['bot_currency_record'](record.copy()),
            'get_payment_method_status':lambda k:(True,''),'get_main_menu':lambda:None,'add_commission_to_referrer':lambda *a:None,
            'generate_payment_tracking':lambda:'abcde12345','get_db_connection':lambda:db,'format_amount':str,
            're':re,'logger':Mock(),'LabeledPrice':lambda label,n:n,'InlineKeyboardMarkup':lambda v:v,
            'InlineKeyboardButton':lambda *args,**kwargs:None}
        exec(compile(ast.Module(body=[adapter,rate_reader,invoice,check,settle],type_ignores=[]),'<star-invoice>','exec'),ns)
        uid=SimpleNamespace(id=123)
        msg=SimpleNamespace(text='10',reply_text=AsyncMock())
        ctx=SimpleNamespace(user_data={'star_rate':'3000'},bot=SimpleNamespace(send_invoice=AsyncMock()))
        update=SimpleNamespace(message=msg,effective_user=uid)
        asyncio.run(ns['receive_stars_amount'](update,ctx))
        self.assertIn('4104',msg.reply_text.await_args.args[0]);ctx.bot.send_invoice.assert_not_called()
        asyncio.run(ns['receive_stars_amount'](update,ctx))
        sent=ctx.bot.send_invoice.await_args.kwargs
        self.assertEqual((sent['currency'],sent['prices'],sent['payload']),('XTR',[10],'STAR:123:10:4104:abcde12345'))
        self.assertIn('41040',sent['description'])
        self.assertEqual(db.cursor.return_value.execute.call_args.args[1],(123,10,4104,41040,'abcde12345'))
        query=SimpleNamespace(from_user=uid,invoice_payload=sent['payload'],currency='XTR',total_amount=10,answer=AsyncMock())
        update.pre_checkout_query=query
        payment={'id':7,'user_id':123,'status':'pending','stars_count':10,'star_rate':4104,'amount_toman':41040}
        cur=db.cursor.return_value;cur.fetchone.return_value=payment.copy()
        asyncio.run(ns['precheckout_star_payment'](update,ctx));query.answer.assert_awaited_with(ok=True)
        record.update(published_at=at-timedelta(hours=25))
        self.assertIsNone(ns['get_star_rate_toman']())
        asyncio.run(ns['precheckout_star_payment'](update,ctx));self.assertFalse(query.answer.await_args.kwargs['ok'])
        record.update(published_at=at,buy_less=20)
        self.assertEqual(ns['get_star_rate_toman'](),3648)
        asyncio.run(ns['precheckout_star_payment'](update,ctx));self.assertFalse(query.answer.await_args.kwargs['ok'])
        # A success delivered by Telegram after a rate change settles the original
        # invoice amount. A replay of an already credited payment adds nothing.
        cur.rowcount=1
        msg.successful_payment=SimpleNamespace(invoice_payload=sent['payload'],currency='XTR',total_amount=10,
                                               telegram_payment_charge_id='charge',provider_payment_charge_id='')
        cur.execute.reset_mock()
        asyncio.run(ns['successful_star_payment'](update,ctx))
        cur.fetchone.return_value={**payment,'status':'credited'}
        asyncio.run(ns['successful_star_payment'](update,ctx))
        self.assertEqual([call.args[1] for call in cur.execute.call_args_list if 'UPDATE users SET balance=' in call.args[0]],
                         [(41040,41040,123)])

class BotReceiptAuthorizationTests(SimpleTestCase):
    def test_receipt_handlers_deny_non_admin_before_any_mutation(self):
        tree=ast.parse((Path(settings.BASE_DIR)/'telegram/dawnpanel.py').read_text(encoding='utf-8'))
        factory=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='create_admin_handler')
        handlers=[node for node in factory.body if isinstance(node,ast.AsyncFunctionDef)]
        self.assertEqual(len(handlers),5)
        for handler in handlers:
            with self.subTest(handler=handler.name):
                handler.returns=None
                for arg in handler.args.args:arg.annotation=None
                namespace={'ADMIN_IDS':[1],'ConversationHandler':SimpleNamespace(END=-1)}
                exec(compile(ast.fix_missing_locations(ast.Module(body=[handler],type_ignores=[])),
                             '<isolated-bot-guard>','exec'),namespace)
                update=SimpleNamespace(effective_user=SimpleNamespace(id=2),
                                       callback_query=SimpleNamespace(answer=AsyncMock()))
                # No DB, Telegram bot, context data or mutation functions are supplied:
                # reaching any of them would fail this test.
                result=asyncio.run(namespace[handler.name](update,SimpleNamespace()))
                self.assertEqual(result,-1)
