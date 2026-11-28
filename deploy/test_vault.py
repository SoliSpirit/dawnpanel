from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import hashlib
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from . import vault


class BackupUploadTests(TestCase):
    def test_outage_resumes_acknowledged_parts_then_sends_signed_recovery_index(self):
        with TemporaryDirectory() as tmp,patch.object(vault,'VAULT',Path(tmp)),patch.object(vault,'KEYS',Path(tmp)):
            root=Path(tmp);date='20261128T000000000000Z';run=root/date;run.mkdir()
            key=b'\x11'*32;(root/'signing.key').write_bytes(key);sign=Ed25519PrivateKey.from_private_bytes(key)
            (root/'verify.pub').write_bytes(sign.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw))
            data={'version':1,'id':date,'release':'a'*40,'sections':{}}
            for s in vault.SECTIONS:
                name=f'{date}-{s}-0001.age';(run/name).write_bytes(b'ciphertext')
                data['sections'][s]=[{'name':name,'size':10,'sha256':hashlib.sha256(b'ciphertext').hexdigest()}]
            vault.save(run/'index.json',{'manifest':data,'signature':sign.sign(vault.canonical(data)).hex()})
            calls=[];topics={};indexes=[]
            class Fake:
                def validate_group(self,gid):assert gid==-10012345
                def call(self,method,params,files=None):
                    if method=='createForumTopic':
                        name=params['name'];assert name not in topics;topics[name]=len(topics)+2
                        return {'message_thread_id':topics[name]}
                    if len(calls)==1 and not self.failed:self.failed=True;raise vault.RemoteError(429,wait=120)
                    name,raw,_=files['document'];calls.append(name)
                    if name.endswith('.json'):indexes.append(raw)
                    return {'chat':{'id':-10012345},'message_thread_id':params['message_thread_id'],'message_id':len(calls),'document':{'file_id':'test'+str(len(calls))}}
            bot=Fake();bot.failed=False;vault.upload(bot=bot);self.assertFalse(calls)
            vault.save(root/'destination.json',{'chat_id':-10012345})
            with self.assertRaises(vault.RemoteError):vault.upload(bot=bot)
            vault.upload(bot=bot);self.assertEqual(len(calls),1)
            self.assertGreaterEqual(vault.read(root/'.retry.json')['after'],120)
            vault.save(root/'.retry.json',{});vault.upload(bot=bot);vault.upload(bot=bot)
            self.assertEqual(len(set(calls)),len(calls));self.assertEqual(len(calls),len(vault.SECTIONS)+1)
            self.assertEqual(len(topics),len(calls));self.assertTrue(vault.read(run/'delivery.json')['complete'])
            (root/'remote.json').write_bytes(indexes[0]);self.assertEqual(vault.verified(root/'remote.json'),data)
            part=data['sections']['media'][0];(run/part['name']).write_bytes(b'0123456789')
            with self.assertRaisesRegex(ValueError,'hash'):vault.part_bytes(run,part)
