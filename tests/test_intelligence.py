"""第二版关键链路测试。FakeQwen 仅用于协议与流程验证，不冒充真实 API 联调。"""
import base64
import io
import json
import math
import tempfile
import threading
import time
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from unittest.mock import patch
from backend.qwen import QwenClient,ProviderError
from backend.knowledge import KnowledgeBase
from backend.documents import DocumentStore
from backend.agent import Analyst,rule_check
from backend.runtime import Runtime
from backend.server import make_handler
from backend.workbook import load_catalog

ROOT=Path(__file__).resolve().parents[1]

class FakeQwen:
    enabled=True;model='test-qwen';embedding_model='test-embedding';rerank_model='test-rerank';search_model='test-search'
    def status(self):return {'enabled':True,'model':self.model}
    def embed(self,texts):return [[1.,float('密封' in s),float('电池' in s)] for s in texts]
    def rerank(self,query,documents):return [{'index':i,'relevance_score':1/(1+i)} for i in range(len(documents))]
    def ocr(self,raw,mime='image/png',question=None):return '测试图片 型号 ABC 检验值 0.1 ml/min'
    def web_search(self,query):return {'query':query,'answer':'测试检索响应，不是真实文献结论','verified_search':True,
                                      'sources':[{'title':'测试技术来源','url':'https://example.org/paper','index':'1'}]}
    def chat(self,messages,tools=None,json_mode=False):
        return {'content':json.dumps({'summary':'测试模型摘要','findings':[{'title':'计算依据','detail':'仅为测试输出',
              'status':'假设','source_ids':['F-CALC']}], 'recommendation':'数据不足，补充证据','limitations':['未校准']})}


class IntelligenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.catalog=load_catalog(ROOT/'data/xinhaosi.xlsx')
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT.parent)
        self.client=FakeQwen();self.kb=KnowledgeBase(Path(self.temp.name)/'kb.sqlite',self.client)
        self.store=DocumentStore(Path(self.temp.name)/'files',self.kb,self.client)
        self.pid=self.catalog['product']['id']
    def tearDown(self):self.temp.cleanup()
    def add(self,text,name='证据',pid=None,kind='supplier_evidence',confirmed=False,metadata=None):
        return self.kb.add(name,[{'locator':'第1页','text':text}],kind,pid or self.pid,confirmed,metadata)

    def test_hybrid_retrieval_and_restart_persistence(self):
        target=self.add('密封性能检验 气密性 泄漏量 0.1 ml/min')
        self.add('电池容量测试 800 mAh')
        self.kb.index()
        restarted=KnowledgeBase(self.kb.path,self.client)
        found=restarted.search('密封性能检验',self.pid)
        self.assertEqual(found['hits'][0]['doc_id'],target)
        self.assertEqual(found['mode'],'hybrid_rrf_rerank')
        self.assertEqual(restarted.list()[0]['vector_count'],1)

    def test_no_cross_product_evidence(self):
        self.add('唯一密封记录',pid='another-product')
        self.assertEqual(self.kb.search('唯一密封记录',self.pid)['hits'],[])

    def test_keyword_fallback_when_provider_fails(self):
        self.add('密封检验要求');self.kb.index()
        with patch.object(self.client,'embed',side_effect=ProviderError('模拟故障')):
            result=self.kb.search('密封',self.pid)
        self.assertTrue(result['hits']);self.assertIn('降级',''.join(result['warnings']))

    def test_bad_rerank_keeps_candidates(self):
        self.add('密封检验')
        with patch.object(self.client,'rerank',return_value=[{'index':999}]):result=self.kb.search('密封',self.pid)
        self.assertTrue(result['hits']);self.assertIn('重排序不可用',''.join(result['warnings']))

    def test_path_scope_and_no_overwrite(self):
        for path in ('../.env','/etc/passwd','..\\x','a/b'):
            with self.assertRaises(ValueError):self.store.safe_path('uploads',path)
        self.store.write_report('draft.md','测试内容')
        with self.assertRaises(FileExistsError):self.store.write_report('draft.md','覆盖')
        outside=Path(self.temp.name)/'secret';outside.write_text('secret')
        (self.store.root/'uploads'/'link.txt').symlink_to(outside)
        with self.assertRaises(ValueError):self.store.safe_path('uploads','link.txt')

    def test_text_upload_and_original_content(self):
        fid=self.store.save_upload('检测说明.txt',base64.b64encode('密封检验\n合格'.encode()).decode())
        result=self.store.ingest(fid,'检测说明.txt','supplier_evidence',self.pid)
        doc=self.kb.get_document(result['document_id'])
        self.assertIn('密封检验',doc['sections'][0]['text'])
        with self.assertRaises(ValueError):self.store.save_upload('script.html','QQ==')
        with self.assertRaises(ValueError):self.store.save_upload('../x.txt','QQ==')

    def test_excel_tool_reads_real_rows(self):
        fid=self.store.save_upload('sample.xlsx',base64.b64encode((ROOT/'data/xinhaosi.xlsx').read_bytes()).decode())
        result=self.store.excel(fid,'材料构成',2,1)
        self.assertEqual(result['rows'][0]['cells'][4],'26070113120001')
        self.assertEqual(len(result['rows']),1)

    def test_pdf_text_and_scanned_page_ocr(self):
        import fitz
        document=fitz.open();page=document.new_page();page.insert_text((50,50),'Supplier inspection report. Test result passed. Source sample.')
        path=self.store.safe_path('uploads','text.pdf');document.save(path);document.close()
        sections,meta=self.store.extract('text.pdf');self.assertIn('Supplier',sections[0]['text']);self.assertEqual(meta['ocr_pages'],[])
        document=fitz.open();document.new_page();document.save(self.store.safe_path('uploads','scan.pdf'));document.close()
        sections,meta=self.store.extract('scan.pdf');self.assertEqual(meta['ocr_pages'],[1]);self.assertIn('测试图片',sections[0]['text'])

    def test_image_ocr_tool(self):
        from PIL import Image
        buffer=io.BytesIO();Image.new('RGB',(80,50),'white').save(buffer,format='PNG')
        fid=self.store.save_upload('photo.png',base64.b64encode(buffer.getvalue()).decode())
        sections,meta=self.store.extract(fid);self.assertEqual(meta['status'],'ocr_unreviewed');self.assertIn('ABC',sections[0]['text'])

    def test_requirement_missing_is_not_pass(self):
        check=rule_check(self.kb,self.catalog)
        self.assertEqual(check['status'],'证据不足');self.assertEqual(check['confirmed_documents'],0)

    def test_exact_rule_failure_and_ambiguous_evidence(self):
        self.add('泄漏限制',kind='buyer_requirement',confirmed=True,metadata={'rules':[{'project':'test','unit':'ml/min','max':.25}]})
        cat={**self.catalog,'inspections':[{'code':self.catalog['product']['code'],'project':'test','measured_raw':'0.3 ml/min','id':'qtest'}]}
        self.assertEqual(rule_check(self.kb,cat)['status'],'不符合')
        cat['inspections'][0]['measured_raw']='0.01/0.03'
        self.assertEqual(rule_check(self.kb,cat)['checks'][0]['status'],'证据不足')

    def analyst(self):
        from backend.simulation import simulate
        return Analyst(self.catalog,simulate(self.catalog,{}),self.kb,self.store,self.client)

    def test_unknown_citation_cannot_support_pass(self):
        out=self.analyst().validate({'summary':'测试','findings':[{'status':'符合','source_ids':['invented']}],'limitations':[]},'quality',{})
        self.assertEqual(out['findings'][0]['status'],'证据不足')
        self.assertEqual(out['findings'][0]['source_ids'],[])
        self.assertTrue(out['limitations'])

    def test_tool_call_roundtrip_and_boundaries(self):
        a=self.analyst();responses=[{'content':'','tool_calls':[{'id':'call1','type':'function','function':{'name':'get_product','arguments':'{}'}}]},
                                 {'content':json.dumps({'summary':'测试','findings':[]})}]
        with patch.object(self.client,'chat',side_effect=responses) as chat:out=a.run('quality')
        self.assertEqual(out['tool_trace'][0]['tool'],'get_product')
        second=chat.call_args_list[1].args[0]
        self.assertTrue(any(m.get('role')=='tool' and m.get('tool_call_id')=='call1' for m in second))
        with self.assertRaises(ValueError):a.call_tool('read_file',{'document_id':'../../.env'})
        with self.assertRaises(ValueError):a.call_tool('execute_shell',{})

    def test_web_research_preserves_only_returned_sources_and_cache(self):
        a=self.analyst();first=a.research('lifetime','seal');second=a.research('lifetime','seal')
        self.assertTrue(second['cached']);self.assertEqual(first['sources'][0]['url'],'https://example.org/paper')
        self.assertTrue(first['sources'][0]['source_id'].startswith('W-'))
        with self.assertRaises(ValueError):a.research('secret','APIKEY')

    def test_full_pipeline_persists_report_and_all_modules(self):
        runtime=Runtime(Path(self.temp.name)/'runtime',self.catalog,self.client)
        try:
            start=runtime.analyze({'stage':'report','settings':{'years':2}})
            for _ in range(300):
                job=runtime.jobs[start['job_id']]
                if job['status'] in ('completed','failed'):break
                time.sleep(.03)
            self.assertEqual(job['status'],'completed',job.get('error'))
            self.assertEqual(set(job['result']['modules']),{'quality','lifetime','cost','visual','report'})
            path=job['result']['modules']['report']['download'].split('/')[-1]
            report=runtime.store.safe_path('reports',path).read_text('utf-8')
            self.assertIn('程序计算结果',report);self.assertIn('分模块分析',report)
            old=job['result']['analysis_key'];new=runtime.calculate({'years':3})['analysis_key']
            self.assertNotEqual(old,new)
        finally:runtime.shutdown()


class QwenContractTests(unittest.TestCase):
    def test_payloads_for_search_embedding_and_tools(self):
        c=QwenClient()
        with patch.object(c,'request',return_value={'output':{'choices':[{'message':{'content':'answer'}}],
             'search_info':{'search_results':[{'title':'valid','url':'https://example.org','index':1},{'title':'bad','url':'javascript:alert(1)'}]}}}) as req:
            result=c.web_search('公开检索')
            self.assertEqual(len(result['sources']),1)
            self.assertTrue(req.call_args.args[1]['parameters']['search_options']['forced_search'])
        with patch.object(c,'request',return_value={'data':[{'index':0,'embedding':[.1]*1024}]}) as req:
            self.assertEqual(len(c.embed(['text'])[0]),1024)
            self.assertEqual(req.call_args.args[1]['encoding_format'],'float')
        with patch.object(c,'request',return_value={'choices':[{'message':{'content':'ok'}}]}) as req:
            c.chat([{'role':'user','content':'x'}],tools=[{'type':'function'}]);self.assertIn('tools',req.call_args.args[1])
    def test_missing_credentials_explicit_error(self):
        c=QwenClient();c.key=''
        with self.assertRaises(ProviderError):c.chat([{'role':'user','content':'x'}])


class HttpV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(dir=ROOT.parent);cls.cat=load_catalog(ROOT/'data/xinhaosi.xlsx')
        cls.client=FakeQwen();cls.runtime=Runtime(Path(cls.temp.name),cls.cat,cls.client)
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(cls.cat,cls.runtime))
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start();cls.url=f'http://127.0.0.1:{cls.server.server_port}'
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.runtime.shutdown();cls.temp.cleanup()
    def post(self,path,data,headers=None):return urlopen(Request(self.url+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json',**(headers or {})}))
    def wait_job(self,jid):
        for _ in range(100):
            data=json.load(urlopen(self.url+'/api/jobs/'+jid))
            if data['status'] in ('completed','failed'):return data
            time.sleep(.04)
        self.fail('任务未在测试时限内完成')
    def test_upload_search_api(self):
        data={'name':'evidence.txt','kind':'supplier_evidence','content_base64':base64.b64encode('特殊密封证据XYZ'.encode()).decode()}
        start=json.load(self.post('/api/supplier-data/import',data));job=self.wait_job(start['job_id']);self.assertEqual(job['status'],'completed')
        start=json.load(self.post('/api/knowledge/search',{'query':'特殊密封证据XYZ'}));found=self.wait_job(start['job_id'])
        self.assertTrue(found['result']['hits'])
    def test_cross_origin_paid_call_blocked(self):
        with self.assertRaises(HTTPError) as error:self.post('/api/provider/check',{}, {'Origin':'https://evil.example'})
        self.assertEqual(error.exception.code,403)
    def test_secret_and_unsupported_tool_paths(self):
        for path in ('/.env','/api/media/..%2f.env','/%2e%2e/backend/qwen.py'):
            with self.assertRaises(HTTPError):urlopen(self.url+path)

if __name__=='__main__':unittest.main()
