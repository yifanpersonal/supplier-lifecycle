"""异步任务、分析快照与报告归档；同一场景的五模块共享计算事实。"""
import hashlib
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime, timezone
from .qwen import QwenClient, load_env, ProviderError
from .knowledge import KnowledgeBase, KINDS
from .documents import DocumentStore, seed_catalog
from .simulation import simulate
from .analysis import LocalRuleAnalysis
from .agent import Analyst, STAGES, fingerprint, json_text
from .logging_setup import get_logger

log=get_logger('runtime')


class Runtime:
    def __init__(self,root,catalog,client=None):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.catalog=catalog;self.client=client or QwenClient()
        self.kb=KnowledgeBase(self.root/'knowledge.sqlite3',self.client)
        self.store=DocumentStore(self.root,self.kb,self.client)
        seed_catalog(self.kb,catalog)
        self.pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='analysis')
        self.slots=threading.BoundedSemaphore(8);self.lock=threading.RLock()
        self.jobs={};self.active=set()
        # 重启后保留历史，但不能将上次未完成的工作标成成功。
        for path in (self.root/'jobs').glob('*.json'):
            try:
                job=json.loads(path.read_text('utf-8'))
                if job['status'] in ('queued','running'):
                    job.update(status='interrupted',error='服务重启中断任务，请重新运行')
                self.jobs[job['id']]=job
            except (ValueError,KeyError):pass

    def shutdown(self):
        log.info('关闭运行池')
        # cancel_futures 为 3.9+ 参数，3.8 下退化为直接关闭。
        try:self.pool.shutdown(wait=False,cancel_futures=True)
        except TypeError:self.pool.shutdown(wait=False)

    def save_job(self,job):
        with self.lock:
            path=self.store.safe_path('jobs',job['id']+'.json');tmp=path.with_suffix('.tmp')
            tmp.write_text(json_text(job),'utf-8');tmp.replace(path)

    def submit(self,label,fn,key=None):
        with self.lock:
            if key and key in self.active:raise ValueError('相同分析任务正在运行，请等待完成')
            if not self.slots.acquire(blocking=False):raise ValueError('任务队列已满，请稍后重试')
            if key:self.active.add(key)
            jid=uuid.uuid4().hex
            job={'id':jid,'label':label,'status':'queued','message':'等待执行','events':[],
                 'created_at':datetime.now(timezone.utc).isoformat()}
            self.jobs[jid]=job;self.save_job(job)
        def progress(message):
            with self.lock:
                job['message']=message;job['events'].append({'message':message,'time':datetime.now(timezone.utc).isoformat()})
                job['events']=job['events'][-70:];self.save_job(job)
        def execute():
            try:
                job['status']='running';progress(label)
                result=fn(progress)
                with self.lock:job.update(status='completed',result=result,message='已完成')
                log.info('任务完成 %s：%s', jid, label)
            except Exception as exc:
                # 页面只显示一行错误，完整堆栈写入 log/ 便于排查。
                log.exception('任务失败 %s：%s', jid, label)
                with self.lock:job.update(status='failed',error=str(exc)[:500],message='任务未完成')
            finally:
                with self.lock:
                    self.save_job(job)
                    if key:self.active.discard(key)
                self.slots.release()
        self.pool.submit(execute)
        log.info('提交任务 %s：%s', jid, label)
        return {'job_id':jid,'status':job['status']}

    def calculate(self,settings):
        result=simulate(self.catalog,settings)
        result['analysis']=LocalRuleAnalysis().explain(self.catalog,result)
        result['analysis_key']=fingerprint(self.catalog,result,self.kb.revision())
        return result

    def snapshot(self,key):
        path=self.store.safe_path('reports','snapshot-'+key+'.json')
        return json.loads(path.read_text('utf-8')) if path.exists() else {'analysis_key':key,'modules':{}}

    def save_snapshot(self,key,stage,output):
        with self.lock:
            snapshot=self.snapshot(key);snapshot['modules'][stage]=output
            path=self.store.safe_path('reports','snapshot-'+key+'.json');tmp=path.with_suffix('.tmp')
            tmp.write_text(json_text(snapshot),'utf-8');tmp.replace(path)
        return snapshot

    def analyze(self,payload):
        stage=payload.get('stage','report')
        if stage not in STAGES:raise ValueError('未知分析阶段')
        if not self.client.enabled:raise ProviderError('尚未配置 Qwen API。请填写项目 .env 并重启。')
        question=payload.get('question','')
        if not isinstance(question,str) or len(question)>1000:raise ValueError('补充问题最多 1000 字')
        result=self.calculate(payload.get('settings',{}));key=result['analysis_key']
        revision=self.kb.revision()
        def work(progress):
            stages=['quality','lifetime','cost','visual','report'] if stage=='report' else [stage]
            errors={}
            for current in stages:
                previous=self.snapshot(key)['modules']
                analyst=Analyst(self.catalog,result,self.kb,self.store,self.client,progress)
                log.info('分析阶段开始 stage=%s key=%s revision=%s', current, key, revision)
                try:
                    output=analyst.run(current,previous,question)
                    output['analysis_key']=key
                    output['knowledge_revision']=revision
                    if errors:output['limitations'] += ['前置分析未完成：'+json_text(errors)]
                    self.save_snapshot(key,current,output)
                except ProviderError as exc:
                    if current=='report' or stage!='report':raise
                    log.warning('分析阶段降级 stage=%s：%s', current, exc)
                    errors[current]=str(exc)
                    # 本轮失败时移除旧模块结果，报告不得把上一次输出当成本轮已完成。
                    with self.lock:
                        snapshot=self.snapshot(key);snapshot['modules'].pop(current,None)
                        path=self.store.safe_path('reports','snapshot-'+key+'.json')
                        path.write_text(json_text(snapshot),'utf-8')
                    progress(STAGES[current]+' 未完成，将在报告中披露')
            snapshot=self.snapshot(key)
            if stage=='report':
                report=snapshot['modules']['report'];text=self.report_markdown(report,result,errors)
                name='decision-'+key+'-'+uuid.uuid4().hex[:8]+'.md'
                artifact=self.store.write_report(name,text)
                report['download']=artifact['download'];report['partial']=bool(errors)
                self.save_snapshot(key,'report',report)
            return {'analysis_key':key,'modules':self.snapshot(key)['modules'],'partial':bool(errors)}
        # 同一快照串行运行，避免报告读取被并行覆盖的上游模块。
        return self.submit(STAGES[stage],work,key='analysis-'+key)

    def report_markdown(self,report,result,errors):
        s=result['settings']
        lines=['# 产品全周期分析决策报告','',f"产品：{self.catalog['product']['name']}；型号：{self.catalog['product']['model']}",
               f"场景：{s['location']}，{s['years']} 年，{s['quantity']} 台。",f"分析编号：{report['analysis_key']}",
               f"生成时间：{report['created_at']}；模型：{report['model']}",'',
               '## 分析摘要','',report['summary'],'','## 程序计算结果','']
        for p in result['policies']:lines.append(f"- {p['name']}：总费用 {p['total']:.2f} 元，单台 {p['per_unit']:.2f} 元。")
        lines+=['','费用和健康指数基于当前可编辑假设，未经现场寿命数据校准。','', '## 主要发现','']
        for f in report.get('findings',[]):
            lines += ['### '+str(f.get('title','')),str(f.get('detail','')),
                      '来源：'+', '.join(f.get('source_ids',[])),'']
        lines+=['## 选择建议','',str(report.get('recommendation','未形成建议')),'','## 数据缺口与限制','']
        lines += ['- '+str(l) for l in report.get('limitations',[])]
        lines+=['','## 分模块分析','']
        for stage,item in self.snapshot(report['analysis_key'])['modules'].items():
            if stage=='report':continue
            lines+=['### '+STAGES[stage],item['summary'],'']
        if errors:lines += ['未完成模块：'+json_text(errors)]
        lines+=['','## 来源清单','']
        for source in report['sources']:
            lines.append(f"- [{source['id']}] {source['title']}；{source.get('locator','')} {source.get('url','')}")
        return '\n'.join(lines)

    def upload(self,payload):
        name=payload.get('name','');kind=payload.get('kind','supplier_evidence')
        if kind not in KINDS or kind=='product_data':raise ValueError('请选择支持的资料类别')
        confirmed=payload.get('confirmed',False)
        if not isinstance(confirmed,bool):raise ValueError('确认状态必须为布尔值')
        file_id=self.store.save_upload(name,payload.get('content_base64',''))
        pid=self.catalog['product']['id']
        def work(progress):
            # 全景/产品照片即使未配置视觉 API，也可用于浏览，不能伪造 OCR 结果。
            if kind=='visual' and file_id.endswith(('.png','.jpg','.jpeg','.webp')):
                result=self.kb.add(name,[{'locator':'图片资源','text':'用户上传产品图片 '+name+'。图像观察尚未运行，不能据此判定产品质量。'}],
                    kind,pid,False,{'file_id':file_id,'status':'image_ready','panorama':bool(payload.get('panorama',False)),'source_sha256':hashlib.sha256(self.store.safe_path('uploads',file_id).read_bytes()).hexdigest()})
                return {'document_id':result,'file_id':file_id,'status':'图片已保存，可在产品可视化中浏览'}
            return self.store.ingest(file_id,name,kind,pid,confirmed,progress)
        return self.submit('解析 '+name,work)
