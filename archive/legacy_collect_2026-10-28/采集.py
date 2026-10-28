#!/usr/bin/env python3
"""小规模景区路线与游记采集：标准库实现，尊重 robots.txt。"""
import csv, json, random, re, ssl, time, urllib.parse, urllib.request, urllib.robotparser, urllib.error
from http.cookiejar import CookieJar
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

OUT = Path(__file__).resolve().parent / '数据'
BASE = Path(__file__).resolve().parent
XHS_INPUT = BASE / '小红书公开笔记链接.csv'
UA = 'ScenicResearchBot/1.0 (educational research)'
MIN_INTERVAL = 3.0                 # 同一来源站点两次请求的最短间隔（秒）
MAX_INTERVAL = 6.0
MAX_RETRIES = 2                    # 仅重试临时性错误，不重试访问拦截
last_request_at = {}
cookie_jar = CookieJar()
try:
 import certifi
 ssl_context = ssl.create_default_context(cafile=certifi.where())
except ImportError:
 ssl_context = ssl.create_default_context()
opener = urllib.request.build_opener(
 urllib.request.HTTPCookieProcessor(cookie_jar),
 urllib.request.HTTPSHandler(context=ssl_context),
)
SEEDS = [
 ('广州白云山','官方路线','https://www.baiyunshan.com.cn/bys/jqzn/jqzn.shtml'),
 ('萍乡武功山','官方路线','https://www.wugongshan.cn/page/strategyList%21info.htm?id=1228'),
 ('广州长隆欢乐世界','官方资料','https://bk.chimelong.com/gz/chimelongparadise/notice/'),
 # 去哪儿的公开攻略页。它们标记为“游客攻略”，不与真实个人游记混淆。
 ('广州白云山','游客攻略（去哪儿）','https://travelnews.qunar.com/qa_strategy/guangzhou-baiyunshan-travel-avoid-pitfalls-guide'),
 ('广州白云山','游客攻略（去哪儿）','https://travelnews.qunar.com/qa_strategy/guangzhou-first-trip-travel-guide'),
 ('广州长隆欢乐世界','游客攻略（去哪儿）','https://travelnews.qunar.com/qa_strategy/guangzhou-chimelong-paradise-travel-guide'),
 ('广州长隆欢乐世界','游客攻略（去哪儿）','https://travelnews.qunar.com/qa_strategy/guangzhou-chimelong-paradise-travel-guide-2'),
 ('广州长隆欢乐世界','游客攻略（去哪儿）','https://travelnews.qunar.com/qa_strategy/guangzhou-chimelong-paradise-travel-guide-11'),
 ('广州长隆欢乐世界','游客攻略（去哪儿）','https://travelnews.qunar.com/qa_strategy/guangzhou-chimelong-halloween-day-night-travel-guide'),
 ('广州长隆欢乐世界','游客攻略（去哪儿）','https://travelnews.qunar.com/qa_strategy/guangzhou-chimelong-2026-halloween-travel-guide'),
 ('萍乡武功山','游客攻略（去哪儿）','https://travelnews.qunar.com/qa_strategy/pingxiang-wugongshan-one-day-travel-guide'),
 ('萍乡武功山','游客攻略（去哪儿）','https://travelnews.qunar.com/qa_strategy/pingxiang-wugongshan-summer-travel-guide'),
 ('萍乡武功山','游客攻略（去哪儿）','https://travelnews.qunar.com/qa_strategy/wugongshan-night-hiking-travel-guide'),
 ('萍乡武功山','游客攻略（去哪儿）','https://travelnews.qunar.com/qa_strategy/wugongshan-lazy-night-hiking-travel-guide'),
 ('广州白云山','游客游记','https://you.ctrip.com/travels/guangzhou152/3991867.html'),
 ('广州长隆欢乐世界','游客游记','https://you.ctrip.com/travels/guangdong100051/4132637.html'),
 ('广州长隆欢乐世界','游客游记','https://you.ctrip.com/travels/PanyuDistrict120096/4011531.html'),
 ('广州长隆欢乐世界','游客游记','https://you.ctrip.com/travels/2020086/4004148.html'),
 ('广州长隆欢乐世界','游客游记','https://you.ctrip.com/travels/2044800/4123269.html'),
 ('萍乡武功山','游客游记','https://you.ctrip.com/travels/wugongshan1445145/4095641.html'),
 ('萍乡武功山','游客游记','https://you.ctrip.com/travels/WugongMountain1445145/4012298.html'),
 ('萍乡武功山','游客游记','https://you.ctrip.com/travels/wugongshan1445145/3975240.html'),
 ('萍乡武功山','游客游记','https://you.ctrip.com/travels/wugongshan1445145/4032753.html'),
 ('萍乡武功山','游客游记','https://you.ctrip.com/travels/Pingxiang714/4142760.html'),
]

def load_xiaohongshu_links():
 """读取人工从小红书“分享”复制的公开笔记链接。

 小红书笔记一般依赖登录态和动态加载，程序不搜索账户内容、不登录，
 仅处理使用者明确提供的公开分享链接。
 """
 if not XHS_INPUT.exists():
  return []
 result=[]
 with XHS_INPUT.open(encoding='utf-8-sig', newline='') as f:
  for row in csv.DictReader(f):
   attraction=(row.get('景区') or '').strip()
   url=(row.get('公开分享链接') or '').strip()
   if attraction and url.startswith(('https://www.xiaohongshu.com/', 'https://xhslink.com/')):
    result.append((attraction, '游客游记（小红书）', url))
 return result
class Parser(HTMLParser):
 def __init__(self):
  super().__init__(convert_charrefs=True); self.skip=0; self.title=False; self.titles=[]; self.parts=[]
 def handle_starttag(self,tag,attrs):
  if tag in ('script','style','nav','footer','header','noscript'): self.skip+=1
  if tag=='title': self.title=True
  if tag in ('p','div','br','li','h1','h2','h3','article'): self.parts.append('\n')
 def handle_endtag(self,tag):
  if tag in ('script','style','nav','footer','header','noscript') and self.skip: self.skip-=1
  if tag=='title': self.title=False
  if tag in ('p','div','li','h1','h2','h3','article'): self.parts.append('\n')
 def handle_data(self,data):
  if self.title: self.titles.append(data)
  if not self.skip and not self.title: self.parts.append(data)
def wait_for_site(url):
 """按域名限速，避免在短时间内连续请求同一网站。"""
 host=urllib.parse.urlsplit(url).netloc
 elapsed=time.monotonic()-last_request_at.get(host, 0)
 delay=random.uniform(MIN_INTERVAL, MAX_INTERVAL)
 if elapsed < delay:
  time.sleep(delay-elapsed)
 last_request_at[host]=time.monotonic()

def fetch(url):
 """使用普通会话请求；只为处理短暂网络故障进行有限重试。"""
 headers={
  'User-Agent': UA,
  'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
  'Accept-Language': 'zh-CN,zh;q=0.9',
 }
 for attempt in range(MAX_RETRIES + 1):
  wait_for_site(url)
  req=urllib.request.Request(url,headers=headers)
  try:
   with opener.open(req,timeout=20) as r:
    raw=r.read(4_000_000); encoding=r.headers.get_content_charset() or 'utf-8'
    return raw.decode(encoding,errors='replace'),r.url
  except urllib.error.HTTPError as e:
   # 401/403/432 等意味着站点明确拒绝访问，不能靠反复请求解决。
   if e.code not in (408, 429, 500, 502, 503, 504) or attempt == MAX_RETRIES:
    raise
   time.sleep((2 ** attempt) * 5 + random.uniform(0, 2))
  except urllib.error.URLError:
   if attempt == MAX_RETRIES:
    raise
   time.sleep((2 ** attempt) * 5 + random.uniform(0, 2))
robots={}
def allowed(url):
 p=urllib.parse.urlsplit(url); root=f'{p.scheme}://{p.netloc}'
 if root not in robots:
  rp=urllib.robotparser.RobotFileParser(); rp.set_url(root+'/robots.txt')
  try:
   content,_=fetch(root+'/robots.txt'); rp.parse(content.splitlines()); robots[root]=rp
  except urllib.error.HTTPError as e:
   if e.code in (404, 410): rp.parse([]); robots[root]=rp
   else: robots[root]=str(e)
  except Exception as e:
   robots[root]=str(e)
 result=robots[root]
 if isinstance(result,str): return False,'robots.txt 无法读取：'+result
 return result.can_fetch(UA,url),'robots.txt 禁止采集'
def main():
 OUT.mkdir(exist_ok=True); records=[]; failures=[]
 for attraction,kind,url in [*SEEDS, *load_xiaohongshu_links()]:
  ok,reason=allowed(url)
  if not ok: failures.append({'景区':attraction,'类型':kind,'链接':url,'原因':reason}); continue
  try:
   html,final=fetch(url); parser=Parser(); parser.feed(html)
   body='\n'.join(line.strip() for line in ''.join(parser.parts).splitlines() if line.strip())
   body=re.sub(r'\n{3,}','\n\n',body)
   if len(body)<150 or any(x in body[:500] for x in ['访问验证','安全验证','验证码']): raise ValueError('页面正文不足或需要验证')
   records.append({'景区':attraction,'类型':kind,'标题':''.join(parser.titles).strip(),'来源链接':final,'采集时间':datetime.now(timezone.utc).isoformat(),'正文':body})
   print('成功',attraction,kind,url)
  except Exception as e: failures.append({'景区':attraction,'类型':kind,'链接':url,'原因':str(e)}); print('失败',url,str(e))
 with (OUT/'采集结果.json').open('w',encoding='utf-8') as f: json.dump(records,f,ensure_ascii=False,indent=2)
 with (OUT/'采集结果.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=['景区','类型','标题','来源链接','采集时间','正文']);w.writeheader();w.writerows(records)
 with (OUT/'失败记录.json').open('w',encoding='utf-8') as f: json.dump(failures,f,ensure_ascii=False,indent=2)
 print('成功',len(records),'条；未采集',len(failures),'条。')
if __name__=='__main__': main()
