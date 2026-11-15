"""Exercise actual bot handler bodies without importing the live bot/config."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from django.conf import settings
from django.test import SimpleTestCase


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
