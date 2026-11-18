"""DeepSeek-only discovery, public document downloads and local evidence retrieval."""
import hashlib
import html
from html.parser import HTMLParser
import ipaddress
import json
from pathlib import Path
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
import uuid

API_HOSTS = {'api.crossref.org','api.openalex.org','api.unpaywall.org','api.semanticscholar.org','eutils.ncbi.nlm.nih.gov','export.arxiv.org','api.elsevier.com'}
MAX_BYTES = 25 * 1024 * 1024


def safe_url(url, resolve=True):
    p = urllib.parse.urlsplit(str(url))
    host = (p.hostname or '').lower()
    if p.scheme not in ['http','https'] or not host or p.username or p.password or p.port not in [None,80,443] or host in API_HOSTS or host.startswith('api.'):
        raise ValueError('只允许普通公开论文网页或文件，不调用其他平台API')
    if host in ['localhost'] or host.endswith('.local'):
        raise ValueError('不允许读取本地或内网地址')
    try:
        if not ipaddress.ip_address(host).is_global:raise ValueError('不允许读取内网地址')
    except ValueError as error:
        if '内网' in str(error):raise
    if re.search(r'/(api|rest|graphql|entrez)/',p.path,re.I):
        raise ValueError('不调用外部平台API路径')
    if resolve:
        for item in socket.getaddrinfo(host, p.port or (443 if p.scheme == 'https' else 80), type=socket.SOCK_STREAM):
            if not ipaddress.ip_address(item[4][0]).is_global:
                raise ValueError('下载地址不是公网地址')
    return urllib.parse.urlunsplit((p.scheme,p.netloc,p.path,p.query,''))


class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        safe_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url):
    url = safe_url(url)
    opener = urllib.request.build_opener(Redirects())
    req = urllib.request.Request(url, headers={'User-Agent':'ResearchHarness/0.3 (academic fulltext library)', 'Accept':'application/pdf,text/html,text/plain;q=0.9'})
    with opener.open(req, timeout=30) as response:
        if int(response.headers.get('Content-Length','0')) > MAX_BYTES:
            raise ValueError('文献超过25MB，请手动下载上传')
        raw = response.read(MAX_BYTES+1)
        if len(raw) > MAX_BYTES:
            raise ValueError('文献超过25MB')
        return raw, response.headers.get('Content-Type',''), safe_url(response.url)


class ArticleHTML(HTMLParser):
    def __init__(self, base):
        super().__init__(); self.base=base; self.parts=[]; self.links=[]; self.skip=0; self.title=''; self.in_title=False
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag in ['script','style','nav','footer','noscript']:
            self.skip+=1
        if tag=='title': self.in_title=True
        if tag=='meta' and a.get('name','').lower() in ['citation_pdf_url','dc.identifier'] and a.get('content','').lower().split('?')[0].endswith('.pdf'):
            self.links.append(urllib.parse.urljoin(self.base,a['content']))
        if tag=='a' and a.get('href') and re.search(r'\.pdf(?:[?#]|$)|/pdf(?:/|$)|/epdf/|download',a['href'],re.I):
            self.links.append(urllib.parse.urljoin(self.base,a['href']))
        if tag in ['p','div','section','article','br','h1','h2','h3','li']:
            self.parts.append('\n')
        if tag in ['h1','h2','h3']:
            self.parts.append('## ')
    def handle_endtag(self,tag):
        if tag in ['script','style','nav','footer','noscript'] and self.skip:self.skip-=1
        if tag=='title':self.in_title=False
        if tag in ['p','h1','h2','h3','section']:self.parts.append('\n')
    def handle_data(self,data):
        if self.in_title:self.title+=data
        if not self.skip:self.parts.append(data)
    def text(self):
        return re.sub(r'\n[ \t]*\n+', '\n\n', ''.join(self.parts)).strip()


def terms(value):
    out=set(re.findall(r'[a-z][a-z0-9-]{2,}',value.lower()))-{'the','and','for','with','from','using','research','study','paper'}
    for run in re.findall(r'[\u4e00-\u9fff]{2,}',value):
        out.update(run[i:i+2] for i in range(len(run)-1))
    return out


def identity(paper,text):
    header=re.sub(r'\s+',' ',text[:7000]).lower()
    doi=paper.get('doi','').lower().strip()
    if doi and doi in header:return True
    tokens=terms(paper['title'])
    return len(tokens)>=3 and sum(t in header for t in tokens)/len(tokens)>=0.8


def body_quality(paper,text,pdf=False):
    if len(text.strip())<2500 or not identity(paper,text):return False
    if pdf:return True
    groups=[r'\bintroduction\b|引言|绪论',r'\bmethods?\b|methodology|材料与方法|研究方法',r'\bresults?\b|实验结果|结果与分析',r'discussion|conclusion|讨论|结论',r'references|参考文献']
    count=sum(bool(re.search(g,text,re.I)) for g in groups)
    return len(text)>5000 and count>=3 and bool(re.search(groups[1]+'|'+groups[2],text,re.I))


def deepseek_fetch(root,url):
    import harness_runtime
    safe_url(url)
    key=harness_runtime.environment(root).get('DEEPSEEK_API_KEY','')
    if not key:raise ValueError('DeepSeek API Key未配置')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args):return None
    request=urllib.request.Request('https://api.deepseek.com/v1/tools/fetch',data=json.dumps({'url':url}).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    with urllib.request.build_opener(NoRedirect()).open(request,timeout=45) as response:
        result=json.loads(response.read(3*1024*1024))
    if not isinstance(result.get('content'),str):raise ValueError('DeepSeek阅读未返回正文')
    return result['content']


def deepseek_search(root,query):
    import harness_runtime
    key=harness_runtime.environment(root).get('DEEPSEEK_API_KEY','')
    if not key:raise ValueError('DeepSeek API Key未配置')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args):return None
    request=urllib.request.Request('https://api.deepseek.com/v1/tools/search',data=json.dumps({'query':query,'count':5,'need_content':False}).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    with urllib.request.build_opener(NoRedirect()).open(request,timeout=35) as response:
        data=json.loads(response.read(2*1024*1024))
    if not isinstance(data.get('results'),list):raise ValueError('DeepSeek搜索响应无效')
    return data['results']


def store_document(ws,pid,paper,text,raw,extension,url,provider,jid=None):
    digest=hashlib.sha256(raw).hexdigest()
    with ws.LOCK:
        p=ws.load(pid)
        if jid and next(j for j in p['jobs'] if j['id']==jid)['status']!='running':
            raise RuntimeError('任务已取消，不保存晚到的下载')
        existing=next((f for f in p['files'] if f.get('sha256')==digest and f.get('paperId')==paper['id']),None)
        if existing:return existing
        fid=uuid.uuid4().hex[:12]
        directory=ws.folder(pid)/'literature'
        (directory/(fid+extension)).write_bytes(raw)
        (directory/(fid+'.body.txt')).write_text(text,encoding='utf-8')
        record={'id':fid,'name':paper['title']+extension,'kind':'literature','paperId':paper['id'],'stored':fid+extension,'textFile':fid+'.body.txt',
                'text':text[:1200],'characters':len(text),'sha256':digest,'textSha256':hashlib.sha256(text.encode('utf-8')).hexdigest(),'sourceUrl':url,'provider':provider,'added':ws.now(),'identityVerified':True,'evidenceType':'fulltext'}
        p['files'].append(record)
        current=next(x for x in p['papers'] if x['id']==paper['id'])
        current.update(fulltextStatus='parsed',fulltextFile=fid,fulltextSource=url)
        import research_experiments as rx
        rx.invalidate(p);p['resultsInvalidated']=True
        for output in p['outputs'].values():output['stale']=True
        ws.save(p)
        return record


def file_text(p,file):
    if file.get('textFile'):
        name=file['textFile']
        if re.fullmatch(r'[a-f0-9]{12}\.body\.txt',name):
            path=Path(__file__).resolve().parent.parent/'data'/p['id']/'literature'/name
            # Use workspace.DATA too, so isolated tests and custom data roots retain boundaries.
            import workspace
            path=workspace.folder(p['id'])/'literature'/name
            try:text=path.read_text(encoding='utf-8')
            except (OSError,UnicodeError):return ''
            if file.get('textSha256') and hashlib.sha256(text.encode('utf-8')).hexdigest()!=file['textSha256']:
                return ''
            return text
        return ''
    return file.get('text','')


def acquire(ws,root,pid,paper,jid,alternate=True):
    p=ws.load(pid)
    if any(f.get('paperId')==paper['id'] and f.get('kind')=='literature' and len(file_text(p,f))>2500 for f in p['files']):
        return True
    queue=list(dict.fromkeys([paper.get('pdfUrl',''),paper.get('url','')]))
    queue=[u for u in queue if u]
    visited=set();failures=[]
    while queue and len(visited)<3:
        if next(j for j in ws.load(pid)['jobs'] if j['id']==jid)['status']!='running':raise RuntimeError('任务已取消')
        url=queue.pop(0)
        if url in visited:continue
        visited.add(url)
        try:
            ws.event(pid,jid,'获取全文：'+paper['title'][:70])
            raw,ctype,final=download(url)
            if raw.lstrip().startswith(b'%PDF-'):
                from pypdf import PdfReader
                import io
                pages=PdfReader(io.BytesIO(raw)).pages
                text='\n\n'.join(f'[第{i+1}页]\n'+(page.extract_text() or '') for i,page in enumerate(pages))
                if not body_quality(paper,text,True):raise ValueError('PDF文字不足或论文身份未匹配，可能需OCR或人工核对')
                store_document(ws,pid,paper,text,raw,'.pdf',final,'public-download',jid);return True
            if 'html' in ctype or raw.lstrip().startswith(b'<'):
                parser=ArticleHTML(final);parser.feed(raw.decode('utf-8',errors='replace'))
                queue=[u for u in parser.links if u not in visited][:2]+queue
                text=parser.title+'\n'+parser.text()
                if body_quality(paper,text):
                    store_document(ws,pid,paper,text,raw,'.html',final,'public-download',jid);return True
                raise ValueError('网页不是可核实的完整正文，继续寻找公开全文')
        except Exception as error:
            failures.append(ws.clean_error(error))
    # Read the actual page through DeepSeek; do not use model-generated summaries as full text.
    try:
        if next(j for j in ws.load(pid)['jobs'] if j['id']==jid)['status']!='running':raise RuntimeError('任务已取消')
        ws.event(pid,jid,'通过DeepSeek阅读论文正文：'+paper['title'][:60])
        text=deepseek_fetch(root,paper['url'])
        if not body_quality(paper,text):raise ValueError('DeepSeek返回内容不足以确认完整正文')
        store_document(ws,pid,paper,text,text.encode(),'.md',paper['url'],'deepseek-fetch',jid);return True
    except Exception as error:failures.append(ws.clean_error(error))
    if alternate:
        try:
            if next(j for j in ws.load(pid)['jobs'] if j['id']==jid)['status']!='running':raise RuntimeError('任务已取消')
            ws.event(pid,jid,'通过DeepSeek寻找其他公开全文版本：'+paper['title'][:55])
            results=deepseek_search(root,'"'+paper['title']+'" full text PDF')
            receipt=ws.folder(pid)/'runs'/(jid+'-'+paper['id']+'-alternate-search.json')
            receipt.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
            candidates=sorted(results,key=lambda r:0 if '.pdf' in r.get('url','').lower() else 1)
            tried=0
            for item in candidates:
                url=item.get('url','')
                if url in visited or not url:continue
                try:safe_url(url)
                except ValueError:continue
                # Only actual search URLs are tried, and downloaded identity is checked again.
                if len(terms(paper['title']) & terms(item.get('title','')+' '+item.get('snippet','')))<3:continue
                replacement={**paper,'url':url,'pdfUrl':''}
                if acquire(ws,root,pid,replacement,jid,alternate=False):return True
                tried+=1
                if tried>=2:break
        except Exception as error:failures.append(ws.clean_error(error))
    with ws.LOCK:
        p=ws.load(pid);current=next(x for x in p['papers'] if x['id']==paper['id'])
        if next(j for j in p['jobs'] if j['id']==jid)['status']!='running':raise RuntimeError('任务已取消')
        current.update(fulltextStatus='needs_upload',fulltextError='；'.join(failures)[-1200:])
        ws.save(p)
    return False


def segments(p):
    core={x['id'] for x in p['papers'] if x.get('core')}
    result=[]
    for file in p['files']:
        if file.get('kind')!='literature' or file.get('paperId') not in core:continue
        text=file_text(p,file)
        if file.get('contentLevel')=='fragment' or len(text.strip())<2500:continue
        page=None;section='正文';counter=0
        for block in re.split(r'\n\s*\n|(?=\[第\d+页\])',text):
            match=re.match(r'\[第(\d+)页\]',block)
            if match:page=int(match[1]);block=block[match.end():]
            heading=re.search(r'^#{1,6}\s*(.+)',block,re.M)
            if heading:section=heading[1][:100]
            for start in range(0,len(block),1000):
                quote=block[start:start+1200].strip()
                if len(quote)<100:continue
                counter+=1
                result.append({'id':file['id']+':'+str(counter),'segmentId':file['id']+':'+str(counter),'documentId':file['id'],'paperId':file['paperId'],'page':page,'section':section,'quote':quote,'filename':file['name'],'sourceUrl':file.get('sourceUrl','用户上传')})
    return result


def select(p,query,limit=24):
    words=terms(query)
    # Actual bilingual search queries bridge Chinese research topics to English bodies.
    search_terms=' '.join(p.get('search',{}).get('queries',[]))
    if not search_terms:search_terms=' '.join(x['title'] for x in p['papers'] if x.get('core'))
    secondary=terms(search_terms)-words
    rows=[r for r in segments(p) if not re.search(r'references|bibliography|参考文献|cited by|related articles',r['section'],re.I)]
    for r in rows:
        text=r['quote'].lower()
        r['_score']=5*sum(min(3,text.count(w)) for w in words)+sum(min(3,text.count(w)) for w in secondary)+2*bool(re.search('limitation|however|challenge|不足|局限|受限',text,re.I))
    rows.sort(key=lambda x:x['_score'],reverse=True)
    selected=[];counts={}
    # Reserve one relevant passage for every available paper before filling the rest.
    first=[];seen=set()
    for row in rows:
        if row['paperId'] not in seen:first.append(row);seen.add(row['paperId'])
    first_ids={row['id'] for row in first}
    for row in first+[r for r in rows if r['id'] not in first_ids]:
        if counts.get(row['paperId'],0)>=4:continue
        counts[row['paperId']]=counts.get(row['paperId'],0)+1
        selected.append({k:v for k,v in row.items() if k!='_score'})
        if len(selected)>=limit:break
    return selected


def coverage(p):
    rows=segments(p);papers={r['paperId'] for r in rows}
    return {'corePapers':sum(bool(x.get('core')) for x in p['papers']),'fulltextPapers':len(papers),'segments':len(rows),'documents':len({r['documentId'] for r in rows})}


def evidence(p,query):
    rows=select(p,query)
    if not rows:raise ValueError('当前项目没有可引用的全文正文。请先获取全文，或上传PDF并同步全文库，再生成问题或痛点。')
    allowed={r['paperId'] for r in rows}
    metadata=[{k:v for k,v in x.items() if k not in ['abstract','searchSnippet']} for x in p['papers'] if x['id'] in allowed]
    return json.dumps({'coverage':coverage(p),'papers':metadata,'fulltextSegments':rows,'notice':'只引用以下全文片段；搜索片段与题录不构成全文证据。'},ensure_ascii=False)


def verify_reference(p,reference):
    sid=reference.get('segmentId')
    row=next((r for r in segments(p) if r['id']==sid and r['paperId']==reference.get('paperId')),None)
    quote=reference.get('quote','').strip()
    normalize=lambda s:re.sub(r'\s+','',s).lower()
    if not row or len(quote)<15 or normalize(quote) not in normalize(row['quote']):
        raise ValueError('全文引文缺少有效segmentId或未通过逐字核对')
    reference.update(level='fulltext',documentId=row['documentId'],page=row['page'],section=row['section'],filename=row['filename'],sourceUrl=row['sourceUrl'])


def discover(ws,root,pid,jid):
    p=ws.load(pid)
    prompt='你是工作台文献检索代理。必须先使用skill工具加载deep-research，再使用web_search执行最多3组针对研究领域的中英文学术检索，优先公开全文和原始研究，避免聚合目录和纯综述。只用DeepSeek搜索与阅读，禁止其他API。当前仅完成文献发现，不执行技能的整篇综述流水线。网页读取最多2次，下载正文由后端负责，完成检索后立即返回。最多返回8篇最相关论文，优先同时提供公开正文或PDF的原始页面，不能编造论文、作者、DOI或下载链接。sourceUrl必须来自本次工具实际返回的链接；pdfUrl只有明确观察到才填写。最终只输出JSON {"papers":[{"title":"真实题名","url":"已观察网页URL","pdfUrl":"明确PDF链接或空","doi":"已核实DOI或空","year":2024,"authors":[],"venue":"未知则空"}],"reason":"相关性和证据覆盖说明"}。研究领域：'+p['field']
    trace=[]
    text=ws.model(root,prompt,pid,jid,web=True,trace=trace)
    called={e.get('tool') for e in trace if e.get('type')=='tool_call'}
    if not {'skill','web_search'}.issubset(called):raise ValueError('本次未实际调用学术技能和DeepSeek搜索，不接受模型凭记忆生成的题录')
    web_calls={e.get('callId') for e in trace if e.get('type')=='tool_call' and e.get('tool') in ['web_search','web_fetch']}
    observed='\n'.join(str(e.get('result','')) for e in trace if e.get('type')=='tool_result' and e.get('status')=='completed' and e.get('callId') in web_calls)
    data=ws.parse_json(text);papers=data.get('papers',[])
    if not isinstance(papers,list) or not 1<=len(papers)<=8:raise ValueError('文献检索未返回有效候选')
    accepted=[]
    for candidate in papers:
        url=safe_url(candidate.get('url',''),resolve=False)
        if url not in observed and html.unescape(url) not in html.unescape(observed):continue
        pdf=candidate.get('pdfUrl','')
        if pdf and pdf not in observed:pdf=''
        authors=candidate.get('authors',[])
        authors=[a[:100] for a in authors if isinstance(a,str)][:10] if isinstance(authors,list) else []
        title=str(candidate.get('title','')).strip()[:400]
        if len(title)<5:continue
        year=candidate.get('year');year=year if isinstance(year,int) and not isinstance(year,bool) and 1500<year<2100 else None
        doi=str(candidate.get('doi','')).strip()[:150]
        if not re.fullmatch(r'10\.\d{4,9}/\S+',doi):doi=''
        accepted.append({'id':'D'+uuid.uuid4().hex[:8],'title':title,'url':url,'pdfUrl':pdf,'doi':doi,'year':year,'authors':authors,'venue':str(candidate.get('venue',''))[:200],'core':True,'citations':0,'abstract':'','source':'DeepSeek Search + academic skills','fulltextStatus':'pending'})
    if not accepted:raise ValueError('没有能够与实际搜索来源核对的论文链接')
    with ws.LOCK:
        p=ws.load(pid)
        # Retain previously uploaded papers and their stable document associations.
        existing={x['url']:x for x in p['papers'] if x.get('url')}
        for paper in accepted:
            if paper['url'] in existing:paper['id']=existing[paper['url']]['id']
        ids={x['id'] for x in accepted}
        p['papers']=[x for x in p['papers'] if x['id'] not in ids]+accepted
        queries=[q for e in trace if e.get('type')=='tool_call' and e.get('tool')=='web_search' for q in e.get('input',{}).get('queries',[]) if isinstance(q,str)]
        p['search']={'provider':'DeepSeek','reason':data.get('reason',''),'time':ws.now(),'skills':['deep-research'],'query':p['field'],'queries':queries}
        ws.save(p)
    return accepted


def start_fetch(ws,root,pid,paper_id=None):
    with ws.LOCK:
        p=ws.load(pid)
        if any(j['status']=='running' for j in p['jobs']):raise ValueError('请等待当前任务完成')
        if paper_id and not any(x['id']==paper_id for x in p['papers']):raise ValueError('文献不存在')
        jid=uuid.uuid4().hex[:12]
        p['jobs'].append({'id':jid,'stage':'fulltext','status':'running','started':ws.now(),'events':[]})
        ws.save(p)
    def run():
        try:
            current=ws.load(pid)
            if not paper_id and (not current['papers'] or current.get('search',{}).get('provider')!='DeepSeek'):
                discover(ws,root,pid,jid)
            papers=[x for x in ws.load(pid)['papers'] if x.get('core') and (not paper_id or x['id']==paper_id) and x.get('url')]
            for paper in papers:acquire(ws,root,pid,paper,jid)
            with ws.LOCK:
                p=ws.load(pid);j=next(x for x in p['jobs'] if x['id']==jid)
                if j['status']=='running':j.update(status='completed',ended=ws.now())
                ws.save(p)
            ws.event(pid,jid,'全文任务结束，覆盖情况：'+json.dumps(coverage(p),ensure_ascii=False))
        except Exception as error:
            with ws.LOCK:
                p=ws.load(pid);j=next(x for x in p['jobs'] if x['id']==jid)
                if j['status']=='running':j.update(status='failed',error=ws.clean_error(error),ended=ws.now())
                ws.save(p)
    import threading
    threading.Thread(target=run,daemon=True).start()
    return {'jobId':jid}


def sync_folder(ws,pid):
    p=ws.load(pid)
    if any(j['status']=='running' for j in p['jobs']):raise ValueError('请等待任务完成后同步文件夹')
    known={f.get('stored') for f in p['files']}|{f.get('textFile') for f in p['files']}
    imported=[];errors=[]
    import base64
    for path in (ws.folder(pid)/'literature').iterdir():
        if not path.is_file() or path.name in known or path.suffix.lower() not in ['.pdf','.txt','.md'] or path.name.endswith('.body.txt'):continue
        if any(f.get('syncName')==path.name for f in ws.load(pid)['files']):continue
        try:
            if path.stat().st_size>15*1024*1024:raise ValueError('超过15MB')
            updated=ws.mutate(pid,'upload',{'kind':'literature','name':path.name,'base64':base64.b64encode(path.read_bytes()).decode()})
            with ws.LOCK:
                updated=ws.load(pid);updated['files'][-1]['syncName']=path.name;ws.save(updated)
            imported.append(path.name)
        except Exception as error:errors.append({'name':path.name,'error':ws.clean_error(error)})
    return {'imported':imported,'errors':errors}
