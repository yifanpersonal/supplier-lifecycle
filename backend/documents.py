"""受控文件工作区与文档解析。只处理上传目录，禁止模型访问工程文件和密钥。"""
import base64
import hashlib
import io
import json
import math
import re
import uuid
from pathlib import Path
from zipfile import ZipFile, BadZipFile
from .workbook import read_sheets
from .qwen import ProviderError

MAX_FILE = 24 * 1024 * 1024
EXTENSIONS = {'.xlsx', '.pdf', '.png', '.jpg', '.jpeg', '.webp', '.txt', '.md', '.json', '.csv'}


def validate_archive(path):
    try:
        with ZipFile(path) as z:
            info=z.infolist()
            if len(info)>10000 or sum(x.file_size for x in info)>120*1024*1024:
                raise ValueError('工作簿解压大小或文件数超出限制')
            if any(x.file_size>40*1024*1024 for x in info):
                raise ValueError('工作簿单个内部文件过大')
            if 'xl/workbook.xml' not in z.namelist():
                raise ValueError('文件不是有效 XLSX 工作簿')
    except BadZipFile:
        raise ValueError('XLSX 文件已损坏') from None


def image_bytes(path):
    try:
        from PIL import Image, ImageOps
        Image.MAX_IMAGE_PIXELS = 40_000_000
        with Image.open(path) as im:
            if im.width*im.height > 40_000_000:
                raise ValueError('图片像素数量超过限制')
            im=ImageOps.exif_transpose(im).convert('RGB')
            im.thumbnail((2600,2600))
            buf=io.BytesIO();im.save(buf,format='JPEG',quality=88)
            return buf.getvalue(), im.size
    except ImportError:
        raise ValueError('图片功能需要安装 requirements.txt 中的 Pillow') from None


class DocumentStore:
    def __init__(self, root, kb, client):
        self.root=Path(root).resolve();self.kb=kb;self.client=client
        for name in ('uploads','reports','jobs','cache'):
            (self.root/name).mkdir(parents=True,exist_ok=True)

    def safe_path(self, area, name):
        if area not in ('uploads','reports','jobs','cache') or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,100}',name):
            raise ValueError('只允许访问受控工作区内的文件 ID')
        base=(self.root/area).resolve()
        if base.parent!=self.root:raise ValueError('工作区目录不能指向外部位置')
        path=base/name
        if path.is_symlink() or path.resolve().parent!=base:
            raise ValueError('禁止符号链接和目录穿越')
        return path

    def save_upload(self, filename, encoded):
        if not isinstance(filename,str) or Path(filename).name!=filename or '\\' in filename or len(filename)>180:
            raise ValueError('文件名无效')
        suffix=Path(filename).suffix.lower()
        if suffix not in EXTENSIONS:
            raise ValueError('支持 XLSX、PDF、图片、TXT、MD、JSON、CSV')
        try: raw=base64.b64decode(encoded,validate=True)
        except (ValueError,TypeError): raise ValueError('文件编码无效') from None
        if not raw or len(raw)>MAX_FILE:
            raise ValueError('文件大小须为 1 字节～24 MB')
        fid=uuid.uuid4().hex+suffix
        path=self.safe_path('uploads',fid);path.write_bytes(raw)
        try:
            if suffix=='.xlsx':validate_archive(path)
            if suffix in ('.png','.jpg','.jpeg','.webp'):image_bytes(path)
            if suffix=='.pdf' and not raw.startswith(b'%PDF-'):raise ValueError('PDF 文件头无效')
        except Exception:
            path.unlink(missing_ok=True);raise
        return fid

    def excel(self, file_id, sheet=None, start=1, limit=40):
        path=self.safe_path('uploads',file_id)
        if path.suffix!='.xlsx':raise ValueError('工具需要 XLSX 文件')
        validate_archive(path);sheets=read_sheets(path)
        names=list(sheets)
        sheet=sheet or names[0]
        if sheet not in sheets:raise ValueError('工作表不存在，可用：'+', '.join(names))
        start=max(1,int(start));limit=min(100,max(1,int(limit)))
        rows=[{'row':n,'cells':v[:60]} for n,v in sheets[sheet]['rows'] if n>=start][:limit]
        return {'sheets':names,'sheet':sheet,'total_rows':len(sheets[sheet]['rows']),
                'rows':rows,'note':'原始单元格值，不执行公式，不推断单台用量。'}

    def extract(self, file_id, progress=lambda x:None):
        path=self.safe_path('uploads',file_id);ext=path.suffix
        if ext=='.xlsx':
            validate_archive(path);sheets=read_sheets(path);sections=[]
            for name, sheet in sheets.items():
                group=[];first=1;last=1
                for n,values in sheet['rows']:
                    if not any(values):continue
                    line=f'第{n}行：'+' | '.join(f'{i+1}列={v}' for i,v in enumerate(values) if v)
                    if len(line)>12000:raise ValueError('单行内容过长，请拆分工作表')
                    if not group:first=n
                    group.append(line);last=n
                    if sum(map(len,group))>1500:
                        sections.append({'locator':f'{name} 第{first}～{last}行','text':'\n'.join(group)});group=[]
                if group:sections.append({'locator':f'{name} 第{first}～{last}行','text':'\n'.join(group)})
            if sum(len(s['text']) for s in sections)>1_000_000:raise ValueError('工作簿正文超过 100 万字，请分拆后上传')
            return sections, {'parser':'xlsx_xml','status':'parsed'}
        if ext=='.pdf':
            try:import fitz
            except ImportError:raise ValueError('PDF 解析需要安装 requirements.txt 中的 PyMuPDF') from None
            sections=[];ocr_pages=[]
            with fitz.open(path) as doc:
                if doc.needs_pass:raise ValueError('请上传未加密 PDF')
                if len(doc)>60:raise ValueError('PDF 超过 60 页，请拆分上传')
                for i,page in enumerate(doc):
                    text=page.get_text('text').strip()
                    if len(text)<40:
                        if not self.client.enabled:
                            raise ProviderError('此 PDF 含扫描页，需要配置 Qwen 视觉模型后重新解析。原文件已保留。')
                        if page.rect.width*page.rect.height>4_000_000:raise ValueError('PDF 页面尺寸过大')
                        progress(f'识别扫描页 {i+1} / {len(doc)}')
                        text=self.client.ocr(page.get_pixmap(matrix=fitz.Matrix(1.5,1.5)).tobytes('png'));ocr_pages.append(i+1)
                    sections.append({'locator':f'第{i+1}页'+(' OCR' if i+1 in ocr_pages else ''),'text':text})
            return sections,{'parser':'pdf_text_and_qwen_ocr','ocr_pages':ocr_pages,'status':'parsed'}
        if ext in ('.jpg','.jpeg','.png','.webp'):
            raw,size=image_bytes(path)
            progress('Qwen 视觉模型正在识别图片文字')
            text=self.client.ocr(raw,'image/jpeg')
            return [{'locator':'图片 OCR','text':text}],{'parser':'qwen_vision','dimensions':size,'status':'ocr_unreviewed'}
        raw=path.read_bytes()
        try:text=raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            try:text=raw.decode('gb18030')
            except UnicodeDecodeError:raise ValueError('文本编码不支持，请转为 UTF-8') from None
        if len(text)>1_000_000:raise ValueError('正文超过 100 万字，请分拆上传')
        return [{'locator':'全文','text':text}],{'parser':'text','status':'parsed'}

    def ingest(self, file_id, name, kind, product_id, confirmed=False, progress=lambda x:None):
        sections,meta=self.extract(file_id,progress)
        meta.update({'file_id':file_id,'source_sha256':hashlib.sha256(self.safe_path('uploads',file_id).read_bytes()).hexdigest()})
        # JSON 采购规则是可计算的补充；普通文本要求仍以大模型辅助审核展示。
        if kind=='buyer_requirement' and file_id.endswith('.json'):
            data=json.loads(self.safe_path('uploads',file_id).read_text('utf-8-sig'))
            rules=data.get('rules',[])
            if not isinstance(rules,list) or len(rules)>100:raise ValueError('rules 必须是至多 100 条规则的数组')
            for rule in rules:
                if not isinstance(rule,dict) or not isinstance(rule.get('project'),str) or not rule.get('unit'):
                    raise ValueError('每条规则必须提供 project 和 unit')
                if not any(k in rule for k in ('min','max')):raise ValueError('规则须提供 min 或 max')
                for k in ('min','max'):
                    if k in rule and (isinstance(rule[k],bool) or not isinstance(rule[k],(int,float)) or not math.isfinite(rule[k])):raise ValueError('规则边界须为数值')
                if 'min' in rule and 'max' in rule and rule['min']>rule['max']:raise ValueError('规则最小值不能大于最大值')
            meta['rules']=rules
        doc_id=self.kb.add(name,sections,kind,product_id,confirmed,meta)
        return {'document_id':doc_id,'file_id':file_id,'sections':len(sections),'status':'关键词索引已就绪，语义索引可单独构建'}

    def write_report(self, name, text):
        if not isinstance(text,str) or len(text)>100000:raise ValueError('报告文本过长')
        if not name.endswith(('.md','.txt','.json')):raise ValueError('只允许写入 MD、TXT、JSON 报告')
        path=self.safe_path('reports',name)
        # 工具不覆盖已有文件；模型可提交新文件名。
        with path.open('x',encoding='utf-8') as f:f.write(text)
        return {'file':name,'download':'/api/reports/'+name}


def seed_catalog(kb,catalog):
    """以真实结构化事实建立初始知识库，不把附件索引当成附件正文。"""
    pid=catalog['product']['id'];sections=[]
    sections.append({'locator':'产品概况','text':json.dumps(catalog['product'],ensure_ascii=False)+'\n'+json.dumps(catalog['stats'],ensure_ascii=False)+'\n'+'\n'.join(catalog['warnings'])})
    seen=set()
    for n in catalog['nodes']:
        key=(n['code'],n['batch'])
        if key in seen:continue
        seen.add(key)
        sections.append({'locator':f"材料构成 第{n['source_row']}行",'text':f"部件 {n['name']} 编码 {n['code']} 批次 {n['batch']} 规格 {n['spec']} 供应商 {n['supplier']}。无单台用量与寿命标定。"})
    kb.add(catalog['product']['source_file']+' 产品档案',sections,'product_data',pid,doc_id='seed-product')
    sections=[]
    for q in catalog['inspections']:
        sections.append({'locator':f"质量明细 第{q['source_row']}行",'text':f"{q['name']} 编码{q['code']} 批次{q['batch']} {q['date']} 检验项目：{q['project']}；要求：{q['requirement']}；实测原文：{q['measured_raw']}；原表结论：{q['result']}。仅证明该检验时点，不证明长期寿命。"})
    kb.add(catalog['product']['source_file']+' 检验记录',sections,'supplier_evidence',pid,doc_id='seed-quality')
