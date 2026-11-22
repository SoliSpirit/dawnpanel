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
