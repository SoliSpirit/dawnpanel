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
            'sell_extra':5000,'buy_less':10000,'spread_mode':'fixed'})
        self.assertEqual((row['rate'],row['buy_rate']),(285000,270000))
        tree=ast.parse((settings.BASE_DIR/'telegram/dawnpanel.py').read_text(encoding='utf-8'))
        funcs=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('currency_quote_line','get_star_rate_toman')]
        exec(compile(ast.Module(body=funcs,type_ignores=[]),'<bot-currency-presentation>','exec'),ns)
        message=ns['currency_quote_line'](row)
        self.assertIn('خرید از شما: 270000',message)
        self.assertIn('فروش به شما: 285000',message)
        ns['get_currency']=lambda code: {'code':'STAR','rate':3100,'buy_rate':2800}
        self.assertEqual(ns['get_star_rate_toman'](),2800)

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
