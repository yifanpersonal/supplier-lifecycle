"""本地持久化 RAG：分块、BM25 与向量召回、RRF 融合、重排、邻块扩展。"""
import hashlib
import json
import math
import re
import sqlite3
import threading
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from .qwen import ProviderError

KINDS = {'product_data', 'supplier_evidence', 'buyer_requirement', 'quote', 'reference', 'visual'}


def tokens(text):
    parts = re.findall(r'[a-z0-9_.-]+|[\u4e00-\u9fff]+', text.lower())
    return [token for part in parts for token in ([part] if not re.match(r'[\u4e00-\u9fff]', part) else
            ([part] if len(part) == 1 else [part[i:i+2] for i in range(len(part)-1)]))]


def chunks(text, size=1000, overlap=120):
    text = text.replace('\x00', '').strip()
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            cut = text.rfind('\n', start + size//2, end)
            if cut > start:
                end = cut
        yield text[start:end]
        if end == len(text):
            break
        start = max(start + 1, end - overlap)


class KnowledgeBase:
    def __init__(self, path, client):
        self.path, self.client = str(path), client
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,name TEXT,kind TEXT,product_id TEXT,confirmed INTEGER,
                sha TEXT,created TEXT,metadata TEXT);
                CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY,doc_id TEXT,position INTEGER,locator TEXT,text TEXT,
                vector TEXT,embedding_model TEXT,FOREIGN KEY(doc_id) REFERENCES documents(id));
                CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc_id);''')

    @contextmanager
    def connect(self):
        # sqlite3 的 with 只提交事务、不关闭连接；这里补上关闭，
        # 否则连接会累积，Windows 上还表现为数据库文件被占用。
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def revision(self):
        with self.connect() as db:
            rows = db.execute('SELECT id,sha,confirmed FROM documents ORDER BY id').fetchall()
        return hashlib.sha256(json.dumps([list(r) for r in rows]).encode()).hexdigest()[:16]

    def add(self, name, sections, kind, product_id, confirmed=False, metadata=None, doc_id=None):
        if kind not in KINDS:
            raise ValueError('未知资料类别')
        serialized = json.dumps([sections, (metadata or {}).get('source_sha256'), (metadata or {}).get('panorama')], ensure_ascii=False)
        sha = hashlib.sha256(serialized.encode()).hexdigest()
        doc_id = doc_id or hashlib.sha256((sha+kind+product_id+str(confirmed)).encode()).hexdigest()[:24]
        items = []
        for section in sections:
            for part in chunks(section['text']):
                if part.strip():
                    i = len(items)
                    items.append((f'{doc_id}:{i}', doc_id, i, section['locator'], part, None, None))
        if not items:
            raise ValueError('没有可检索正文，资料未入库')
        with self.lock, self.connect() as db:
            existing = db.execute('SELECT sha FROM documents WHERE id=?', (doc_id,)).fetchone()
            if existing and existing['sha'] == sha:
                return doc_id
            db.execute('INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?,?,?,?)',
                       (doc_id, name, kind, product_id, int(bool(confirmed)), sha,
                        datetime.now(timezone.utc).isoformat(), json.dumps(metadata or {}, ensure_ascii=False)))
            db.execute('DELETE FROM chunks WHERE doc_id=?', (doc_id,))
            db.executemany('INSERT INTO chunks VALUES (?,?,?,?,?,?,?)', items)
        return doc_id

    def list(self, product_id=None):
        with self.connect() as db:
            rows = db.execute('''SELECT d.*,count(c.id) chunk_count,
                sum(CASE WHEN c.vector IS NOT NULL AND c.embedding_model=? THEN 1 ELSE 0 END) vector_count
                FROM documents d LEFT JOIN chunks c ON d.id=c.doc_id GROUP BY d.id ORDER BY d.created DESC''',
                (self.client.embedding_model,)).fetchall()
        return [dict(r, metadata=json.loads(r['metadata'])) for r in rows
                if product_id is None or r['product_id'] in (product_id, '*')]

    def get_document(self, doc_id):
        with self.connect() as db:
            doc = db.execute('SELECT * FROM documents WHERE id=?', (doc_id,)).fetchone()
            if not doc:
                raise ValueError('资料不存在')
            rows = db.execute('SELECT id,locator,text FROM chunks WHERE doc_id=? ORDER BY position', (doc_id,)).fetchall()
        return {**dict(doc), 'metadata': json.loads(doc['metadata']), 'sections': [dict(r) for r in rows]}

    def index(self, progress=lambda x: None):
        if not self.client.enabled:
            raise ProviderError('语义索引需要配置 Qwen API 密钥；当前关键词检索仍可使用。')
        with self.connect() as db:
            pending = db.execute('SELECT id,text FROM chunks WHERE vector IS NULL OR embedding_model!=?',
                                 (self.client.embedding_model,)).fetchall()
        for start in range(0, len(pending), 10):
            batch = pending[start:start+10]
            vectors = self.client.embed([r['text'] for r in batch])
            with self.lock, self.connect() as db:
                db.executemany('UPDATE chunks SET vector=?,embedding_model=? WHERE id=?',
                               [(json.dumps(v), self.client.embedding_model, r['id']) for r,v in zip(batch,vectors)])
            progress(f'向量化 {min(start+10,len(pending))} / {len(pending)} 个片段')
        return {'indexed': len(pending), 'model': self.client.embedding_model}

    def search(self, query, product_id, kind=None, limit=6):
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 500:
            raise ValueError('检索问题须为 1～500 字')
        if kind and kind not in KINDS:
            raise ValueError('未知资料类别')
        with self.connect() as db:
            rows = db.execute('''SELECT c.*,d.name,d.kind,d.product_id,d.confirmed FROM chunks c
                JOIN documents d ON d.id=c.doc_id WHERE d.product_id IN (?, '*')''', (product_id,)).fetchall()
        rows = [dict(r) for r in rows if not kind or r['kind'] == kind]
        if not rows:
            return {'hits': [], 'mode': 'empty', 'warnings': ['当前产品没有匹配类别的资料']}
        terms = set(tokens(query)); counts = [Counter(tokens(r['text'])) for r in rows]
        lengths = [sum(c.values()) for c in counts]; avg = sum(lengths)/max(1,len(lengths))
        dfs = {t: sum(t in c for c in counts) for t in terms}
        bm = []
        for i,c in enumerate(counts):
            score = sum(math.log(1+(len(rows)-dfs[t]+.5)/(dfs[t]+.5))*c[t]*2.5 /
                        (c[t]+1.5*(.25+.75*lengths[i]/max(avg,1))) for t in terms if c[t])
            if score > 0: bm.append((i, score))
        bm.sort(key=lambda x:x[1], reverse=True)
        lists = [[i for i,_ in bm[:30]]]; warnings=[]; mode='bm25'
        vector_rows = [(i,json.loads(r['vector'])) for i,r in enumerate(rows)
                       if r['vector'] and r['embedding_model'] == self.client.embedding_model]
        if self.client.enabled and vector_rows:
            try:
                q = self.client.embed([query])[0]; qn=math.sqrt(sum(x*x for x in q))
                dense = [(i,sum(a*b for a,b in zip(q,v))/(max(qn*math.sqrt(sum(x*x for x in v)),1e-12)))
                         for i,v in vector_rows if len(v)==len(q)]
                dense.sort(key=lambda x:x[1], reverse=True)
                lists.append([i for i,score in dense[:30] if score > .15]);mode='hybrid_rrf'
                if len(vector_rows) < len(rows): warnings.append('部分新资料尚未向量化，已参与关键词检索')
            except ProviderError as exc: warnings.append(str(exc)+'；本次降级为关键词检索')
        else: warnings.append('语义索引尚未就绪，当前使用 BM25 关键词检索')
        scores = Counter()
        for ranking in lists:
            for rank,i in enumerate(ranking): scores[i] += 1/(60+rank+1)
        candidates=[i for i,_ in scores.most_common(16)]
        if self.client.enabled and candidates and self.client.rerank_model:
            try:
                rr=self.client.rerank(query,[rows[i]['text'] for i in candidates])
                order=[int(r['index']) for r in rr]
                if not order or len(set(order))!=len(order) or any(i<0 or i>=len(candidates) for i in order):
                    raise ProviderError('重排序响应无效')
                candidates=[candidates[i] for i in order];mode+='_rerank'
            except (ProviderError,KeyError,TypeError,ValueError) as exc: warnings.append('重排序不可用，保留召回顺序')
        hits=[]
        lookup={(r['doc_id'],r['position']):r for r in rows}
        for i in candidates[:min(10,max(1,int(limit)))]:
            r=rows[i]
            # 返回邻块 ID 和定位，引用不会把邻块内容误归到中心块。
            neighbors=[lookup[(r['doc_id'],pos)] for pos in [r['position']-1,r['position']+1] if (r['doc_id'],pos) in lookup]
            # 用 {**a, **b} 而非 3.9+ 的字典合并运算符，保持 3.8 兼容。
            hits.append({**{k:r[k] for k in ['id','doc_id','name','kind','confirmed','locator','text']},
                'neighbors':[{k:n[k] for k in ['id','locator','text']} for n in neighbors], 'rrf_score':scores[i]})
        return {'hits':hits,'mode':mode,'warnings':warnings}
