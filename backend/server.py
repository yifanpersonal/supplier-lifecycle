"""同源网页与 API，默认仅本机访问。Qwen 密钥只在服务端读取。"""
import argparse
import json
import logging
import mimetypes
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote,urlsplit,parse_qs
from .qwen import load_env,ProviderError
from .runtime import Runtime
from .simulation import DEFAULTS,GROUPS,PRESETS
from .workbook import load_catalog
from .logging_setup import get_logger,log_directory,setup_logging

log=get_logger('server')

# 强制修复 Windows 下 MIME 类型识别错误
mimetypes.add_type('text/css; charset=utf-8', '.css')
mimetypes.add_type('application/javascript; charset=utf-8', '.js')
mimetypes.add_type('image/svg+xml', '.svg')

ROOT=Path(__file__).resolve().parents[1]


def make_handler(catalog,runtime=None):
    runtime=runtime or Runtime(ROOT/'var',catalog)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,format,*args):
            # 标准库的请求行包含查询内容，交由 log_response 只记录路径。
            pass

        def log_response(self,status,debug=False):
            # 只记录方法与路径：不写入查询串、请求正文和用户文档正文。
            route=unquote(urlsplit(self.path).path)
            started=getattr(self,'_started',None)
            message='%s %s -> %s'%(self.command,route,status)
            if started is not None:message+='（%.0f ms）'%((time.monotonic()-started)*1000)
            if status>=500:log.error(message)
            elif status>=400:log.warning(message)
            elif debug:log.debug(message)
            else:log.info(message)

        def write_body(self,body):
            try:self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError):self.close_connection=True

        def send_json(self,value,status=200):
            self.log_response(status)
            body=json.dumps(value,ensure_ascii=False,allow_nan=False).encode()
            self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.write_body(body)

        def serve_file(self,path,download=False,api=False):
            if not path.is_file():return self.send_json({'error':'文件不存在'},404)
            # 接口下载记入常规日志；页面静态资源仅在 DEBUG 级别记录。
            self.log_response(200,debug=not api)
            body=path.read_bytes();self.send_response(200)
            self.send_header('Content-Type',mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
            self.send_header('Content-Length',str(len(body)));self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
            if download:self.send_header('Content-Disposition','attachment; filename="'+path.name+'"')
            self.end_headers();self.write_body(body)

        def do_GET(self):
            self._started=time.monotonic()
            route=unquote(urlsplit(self.path).path);params=parse_qs(urlsplit(self.path).query)
            try:
                if route=='/api/health':return self.send_json({'ok':True,'version':'2.0','llm_enabled':runtime.client.enabled})
                if route=='/api/catalog':return self.send_json(catalog)
                if route=='/api/config':return self.send_json({'defaults':DEFAULTS,'groups':GROUPS,'presets':PRESETS,
                    'upload':{'enabled':True,'endpoint':'/api/supplier-data/import'},'llm':runtime.client.status()})
                if route=='/api/documents':return self.send_json({'documents':runtime.kb.list(catalog['product']['id']),
                                                                'revision':runtime.kb.revision()})
                if route.startswith('/api/documents/'):
                    doc=runtime.kb.get_document(route.split('/')[-1])
                    if doc['product_id'] not in (catalog['product']['id'],'*'):raise ValueError('资料不属于当前产品')
                    doc['sections']=doc['sections'][:100]
                    return self.send_json(doc)
                if route.startswith('/api/jobs/'):
                    with runtime.lock:job=runtime.jobs.get(route.split('/')[-1])
                    return self.send_json(job if job else {'error':'任务不存在'},200 if job else 404)
                if route.startswith('/api/analyses/'):
                    return self.send_json(runtime.snapshot(route.split('/')[-1]))
                if route.startswith('/api/reports/'):
                    return self.serve_file(runtime.store.safe_path('reports',route.split('/')[-1]),True,api=True)
                if route.startswith('/api/media/'):
                    fid=route.split('/')[-1]
                    valid=any(d['metadata'].get('file_id')==fid and d['kind']=='visual' for d in runtime.kb.list(catalog['product']['id']))
                    if not valid or not fid.endswith(('.png','.jpg','.jpeg','.webp')):raise ValueError('图片不可访问')
                    return self.serve_file(runtime.store.safe_path('uploads',fid),api=True)
                if route.startswith('/api/'):return self.send_json({'error':'接口不存在'},404)
                directory=(ROOT/'frontend').resolve();file=(directory/(route.lstrip('/') or 'index.html')).resolve()
                if directory not in file.parents or not file.is_file():return self.send_json({'error':'文件不存在'},404)
                return self.serve_file(file)
            except (ValueError,OSError,KeyError) as exc:return self.send_json({'error':str(exc)},400)
            except Exception:
                log.exception('GET %s 未预期异常', route)
                return self.send_json({'error':'服务内部错误，详情见 log 目录'},500)

        def do_POST(self):
            self._started=time.monotonic()
            # 同源校验防止其他网页偷偷触发本机的付费模型调用。
            origin=self.headers.get('Origin')
            if origin and urlsplit(origin).netloc!=self.headers.get('Host'):
                return self.send_json({'error':'仅允许同源请求'},403)
            route=urlsplit(self.path).path
            try:
                size=int(self.headers.get('Content-Length','0'))
                bound=34*1024*1024 if route=='/api/supplier-data/import' else 150000
                if size<=0 or size>bound:
                    self.close_connection=True;return self.send_json({'error':'请求体大小无效'},413)
                payload=json.loads(self.rfile.read(size))
                if not isinstance(payload,dict):raise ValueError('请求必须为 JSON 对象')
                if route=='/api/simulate':return self.send_json(runtime.calculate(payload))
                if route=='/api/analysis/explain':return self.send_json(runtime.calculate(payload)['analysis'])
                if route=='/api/analysis/run':return self.send_json(runtime.analyze(payload),202)
                if route=='/api/supplier-data/import':return self.send_json(runtime.upload(payload),202)
                if route=='/api/knowledge/index':return self.send_json(runtime.submit('构建语义索引',lambda p:runtime.kb.index(p),key='index'),202)
                if route=='/api/knowledge/search':
                    def search(progress):return runtime.kb.search(payload.get('query',''),catalog['product']['id'],payload.get('kind'))
                    return self.send_json(runtime.submit('知识库检索',search),202)
                if route=='/api/provider/check':
                    def check(progress):
                        runtime.client.chat([{'role':'user','content':'只回复 OK'}]);return {'connected':True,'model':runtime.client.model}
                    return self.send_json(runtime.submit('检查 Qwen 连接',check,key='provider-check'),202)
                return self.send_json({'error':'接口不存在'},404)
            except ProviderError as exc:return self.send_json({'error':str(exc)},503)
            except (ValueError,TypeError,KeyError,UnicodeDecodeError) as exc:return self.send_json({'error':str(exc)},400)
            except OSError:return self.send_json({'error':'文件读写失败，请检查工作区权限'},500)
            except Exception:
                log.exception('POST %s 未预期异常', route)
                return self.send_json({'error':'服务内部错误，详情见 log 目录'},500)
    return Handler


def main():
    load_env(ROOT/'.env')
    parser=argparse.ArgumentParser(description='产品全周期分析可信可视平台')
    parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=8000)
    parser.add_argument('--data',type=Path,default=Path(os.getenv('SUPPLIER_DATA_PATH',ROOT/'data/xinhaosi.xlsx')))
    parser.add_argument('--log_level',default=None,help='日志级别，默认 INFO 或环境变量 APP_LOG_LEVEL')
    args=parser.parse_args()
    logger=setup_logging(ROOT,getattr(logging,str(args.log_level).upper(),None) if args.log_level else None)
    log.info('启动，Python %s，日志目录 %s',sys.version.split()[0],log_directory(ROOT).resolve())
    if sys.version_info < (3,10):
        log.warning('项目声明需要 Python 3.10+，当前 %s 缺少部分标准库能力，建议升级解释器。',sys.version.split()[0])
    catalog=load_catalog(args.data)
    runtime=Runtime(Path(os.getenv('APP_DATA_DIR',ROOT/'var')),catalog)
    # 把随工程的真实工作簿作为受控 Excel 工具输入，不开放 data 目录给模型。
    sample=runtime.store.safe_path('uploads','sample-xinhaosi.xlsx')
    if not sample.exists():sample.write_bytes(args.data.read_bytes())
    with runtime.kb.connect() as db:
        db.execute('UPDATE documents SET metadata=? WHERE id=?',(json.dumps({'file_id':sample.name,'status':'parsed'}),'seed-product'))
    server=ThreadingHTTPServer((args.host,args.port),make_handler(catalog,runtime))
    print(f'打开 http://{args.host}:{args.port}  | Qwen '+('已配置' if runtime.client.enabled else '未配置'),flush=True)
    log.info('监听 %s:%s，Qwen %s',args.host,args.port,'已配置' if runtime.client.enabled else '未配置')
    try:server.serve_forever()
    except KeyboardInterrupt:log.info('收到中断信号，正在退出')
    finally:
        server.server_close();runtime.shutdown();log.info('已停止')

if __name__=='__main__':main()
