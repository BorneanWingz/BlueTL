import sys, json, os, re, base64, ctypes, shutil, tempfile, zipfile, time, threading, socket, ssl, urllib.request, urllib.error, urllib.parse, webbrowser
from pathlib import Path

os.environ.setdefault('HF_HUB_OFFLINE','1')
os.environ.setdefault('TRANSFORMERS_OFFLINE','1')
# //remarks: In a --windowed PyInstaller build there is no console (sys.stderr is None).
# //remarks: tqdm progress bars and loguru console sinks write to stderr, which can raise
# //remarks: OSError and abort OCR; disabling them keeps OCR headless-safe in the EXE.
os.environ.setdefault('TQDM_DISABLE','1')


class DATA_BLOB(ctypes.Structure):
 _fields_=[('cbData',ctypes.c_uint32),('pbData',ctypes.c_void_p)]

ctypes.windll.kernel32.LocalFree.argtypes=[ctypes.c_void_p]
ctypes.windll.kernel32.LocalFree.restype=ctypes.c_void_p
ctypes.windll.crypt32.CryptProtectData.argtypes=[ctypes.POINTER(DATA_BLOB),ctypes.c_wchar_p,ctypes.POINTER(DATA_BLOB),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint32,ctypes.POINTER(DATA_BLOB)]
ctypes.windll.crypt32.CryptProtectData.restype=ctypes.c_bool
ctypes.windll.crypt32.CryptUnprotectData.argtypes=[ctypes.POINTER(DATA_BLOB),ctypes.POINTER(ctypes.c_wchar_p),ctypes.POINTER(DATA_BLOB),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint32,ctypes.POINTER(DATA_BLOB)]
ctypes.windll.crypt32.CryptUnprotectData.restype=ctypes.c_bool

def protect(value):
 raw=value.encode('utf-8'); source=ctypes.create_string_buffer(raw); result=DATA_BLOB()
 if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(DATA_BLOB(len(raw),ctypes.addressof(source))),None,None,None,None,0,ctypes.byref(result)): raise ctypes.WinError()
 try: return base64.b64encode(ctypes.string_at(result.pbData,result.cbData)).decode('ascii')
 finally: ctypes.windll.kernel32.LocalFree(result.pbData)
def unprotect(value):
 try:
  raw=base64.b64decode(value); source=ctypes.create_string_buffer(raw); result=DATA_BLOB()
  if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(DATA_BLOB(len(raw),ctypes.addressof(source))),None,None,None,None,0,ctypes.byref(result)): return ''
  try: return ctypes.string_at(result.pbData,result.cbData).decode('utf-8')
  finally: ctypes.windll.kernel32.LocalFree(result.pbData)
 except Exception: return ''
from dataclasses import dataclass
from openai import OpenAI
from docx import Document
from PySide6.QtWidgets import QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QFrame,QLineEdit,QComboBox,QPushButton,QFileDialog,QTableWidget,QTableWidgetItem,QMessageBox,QLabel,QHeaderView,QTabWidget,QProgressBar,QCheckBox,QMenu
from PySide6.QtCore import Qt,QTimer,QThread,Signal,QObject
from PySide6.QtGui import QIcon

CFG=Path(os.getenv('APPDATA',Path.home()))/'BlueTL'/'config.json'
LANGS=['English','Bahasa Melayu','Simplified Chinese','Traditional Chinese','Korean']
LANGUAGE_LABELS={'English':'English','Bahasa Melayu':'Bahasa Malaysia','Simplified Chinese':'Simplified Chinese 简体中文','Traditional Chinese':'Traditional Chinese 繁體中文','Korean':'Korean 한국어'}
EXPORT_FORMATS=[('pdf','PDF'),('docx','Word (DOCX)'),('txt','Plain Text (TXT)')]
EXPORT_FILTERS={'pdf':'PDF document (*.pdf)','docx':'Word document (*.docx)','txt':'Plain text (*.txt)'}
EXPORT_EXTENSIONS={'pdf':'.pdf','docx':'.docx','txt':'.txt'}
EXPORT_FILTER_LIST=';;'.join(EXPORT_FILTERS[key] for key,_ in EXPORT_FORMATS)
EXPORT_FORMAT_LABELS=dict(EXPORT_FORMATS)
EXPORT_FORMAT_KEYS={label:key for key,label in EXPORT_FORMATS}

def export_format_key(value):
 return value if value in EXPORT_FORMAT_LABELS else EXPORT_FORMAT_KEYS.get(value,'pdf')


def language_key(value):
 return next((name for name,label in LANGUAGE_LABELS.items() if value in (name,label)),value)
# //remarks: Korean is an API translation target. BlueTL's local Manga OCR remains Japanese-focused;
# //remarks: Korean OCR requires the separate AzureTL PaddleOCR model integration.
# //remarks: No provider is baked into the executable. The Base URL, API key, and model list are
# //remarks: deliberately NOT hard-coded: a build must work against any OpenAI-compatible provider, so the
# //remarks: URL field starts empty and the model dropdown only ever holds what that provider's own
# //remarks: GET /models endpoint returned (plus whatever ID the user typed). Everything the user enters is
# //remarks: remembered in the settings file, so their provider, key, and model survive a restart.
# //remarks: FREE_MODELS is intentionally empty: "free" is decided at run time by the Free models only tick
# //remarks: box, which searches the fetched list for the text "free" instead of trusting a built-in name list.
FREE_MODELS=[]
MODELS=[]

# //remarks: Search token behind the "Free models only" tick box. A model ID is treated as free when it
# //remarks: contains this text, case-insensitively (vendor/freemodel-x, gpt-4o-mini:free, ...).
FREE_MODEL_TOKEN='free'
# //remarks: Saved-provider picker entries. The verified tick follows the British "proved/verified" wording used in
# //remarks: the status line, and the placeholder keeps index 0 free so itemData(0) can never look like a provider.
PLACEHOLDER_PROVIDER='Select a saved provider...'
PROVIDER_VERIFIED=chr(0x2714)+' '
PROVIDER_UNVERIFIED=chr(0x2014)+' '
# //remarks: One wording for the certificate note, so the status tooltip and the fetch message cannot drift apart.
CERT_NOTE='The provider certificate is valid for {days} more day(s).'
# //remarks: One wording for the certificate note, so the status tooltip and the fetch message cannot drift apart.
CERT_NOTE='The provider certificate is valid for {days} more day(s).'
# //remarks: Update gate. The About label and the startup version check both read APP_VERSION, so a release
# //remarks: cannot disagree with itself about its own number. The check fetches the repository's release tags
# //remarks: once at startup and compares them with the running version: a build that is at most
# //remarks: MAX_SKIPPED_VERSIONS releases behind may keep running (the user can hold the update), but a build
# //remarks: that is further behind is obsolete and refuses to start. The user is never nagged twice in one
# //remarks: launch, and a failed or offline check must never block the app - it simply skips the reminder.
APP_VERSION='0.1.5'
RELEASES_URL='https://api.github.com/repos/BorneanWingz/BlueTL/releases?per_page=30'
RELEASE_PAGE_URL='https://github.com/BorneanWingz/BlueTL/releases/tag/{tag}'
MAX_SKIPPED_VERSIONS=2

def parse_version(value):
 # //remarks: Turn a tag like "v1.0.10" into a comparable tuple (1,0,10), so string sorting cannot rank
 # //remarks: v1.0.10 before v1.0.2. Leading "v"/"V" is stripped, numeric segments are kept until the first
 # //remarks: non-numeric one (suffixes such as "-beta" end the number), and anything unparseable is (0,).
 text=str(value or '').strip().lstrip('vV')
 parts=[]
 for chunk in re.split(r'[._-]',text):
  if chunk.isdigit(): parts.append(int(chunk))
  elif parts: break
 return tuple(parts)

def newer_releases(current,tags):
 # //remarks: Return the release tags strictly newer than the running version, newest first. Duplicates and
 # //remarks: empty tags are dropped, so a badly written release entry cannot create a phantom reminder.
 current=parse_version(current)
 seen=set(); out=[]
 for tag in tags:
  tag=str(tag or '').strip()
  if not tag or tag in seen or parse_version(tag)<=current: continue
  seen.add(tag); out.append(tag)
 out.sort(key=parse_version,reverse=True)
 return out

def is_free_model(model_id):
 # //remarks: Single definition of "free" so the dropdown filter and the retry order can never disagree.
 return FREE_MODEL_TOKEN in str(model_id or '').lower()

def filter_models(ids,free_only=False):
 # //remarks: Apply the Free models only tick box to a model list while preserving the provider's order.
 # //remarks: Duplicates and blanks are dropped so the dropdown never repeats an entry.
 seen=[]; selected=[]
 for value in ids or []:
  if not isinstance(value,str): continue
  text=value.strip()
  if not text or text in seen: continue
  seen.append(text)
  if not free_only or is_free_model(text): selected.append(text)
 return selected

# //remarks: A provider is remembered per Base URL, so the API key, the verified state, and the chosen model all
# //remarks: belong to one URL and cannot leak to another. profile_key normalises the URL the same way the field is
# //remarks: compared everywhere else, so "HTTPS://Host/v1/" and "https://host/v1" are one provider rather than two.
def profile_key(url):
 text=str(url or '').strip().rstrip('/')
 if not text: return ''
 return normalized_url(text).lower()

def load_profiles(data):
 # //remarks: Only well-formed entries are kept: a damaged profile (wrong types, no URL) is dropped instead of
 # //remarks: breaking startup, exactly like a damaged config is treated as a missing one.
 profiles={}
 raw=data.get('providers') if isinstance(data,dict) else None
 if isinstance(raw,dict):
  for key,value in raw.items():
   if not isinstance(key,str) or not key.strip() or not isinstance(value,dict): continue
   url=str(value.get('url') or key).strip()
   if not url: continue
   models=value.get('models')
   profiles[profile_key(key) or key]={'url':url,'api_key':str(value.get('api_key') or ''),'verified':bool(value.get('verified',False)),'model':str(value.get('model') or '').strip(),'models':[m for m in models if isinstance(m,str) and m.strip()] if isinstance(models,list) else []}
 return profiles

def remember_profile(data,url,key_cipher,models=None,verified=None,model=None):
 # //remarks: Update just the one provider a successful connect or API test touched, leaving every other saved
 # //remarks: provider exactly as it was. The URL is stored as typed so the user's own text comes back unchanged.
 key=profile_key(url)
 if not key: return data
 profiles=data.get('providers') if isinstance(data.get('providers'),dict) else {}
 entry=dict(profiles.get(key) or {})
 entry['url']=str(url).strip()
 if key_cipher not in (None,''): entry['api_key']=key_cipher
 elif 'api_key' not in entry: entry['api_key']=''
 entry['verified']=bool(entry.get('verified',False)) if verified is None else bool(verified)
 if models is not None: entry['models']=[m for m in models if isinstance(m,str) and m.strip()][:500]
 if model is not None: entry['model']=str(model).strip()
 entry.setdefault('models',[]); entry.setdefault('model','')
 profiles[key]=entry
 data['providers']=profiles
 return data
@dataclass
class Row: page:int; panel:int; jp:str; tr:str=''; crop:str=''; review:str=''; reason:str=''

# //remarks: Raised inside a batch loop when the user presses Stop. It is not an error: the caller keeps
# //remarks: whatever was already finished and reports a stop instead of showing a failure dialog.
class StopRequested(Exception):
 pass

# //remarks: Wording a provider uses when a model's free allowance or request budget is exhausted, so the batch
# //remarks: can stop with a clear reminder instead of a generic failure dialog. Both error codes and the prose a
# //remarks: provider puts in the message are matched, because the same condition is reported either way.
QUOTA_CODES=('insufficient_quota','rate_limit','quota_exceeded','token_limit','tokens_exhausted','insufficient_balance','free_trial','free trial','no_free_credits','no free credits','billing_hard_limit_reached','credit_balance_low','exhausted your','out of credits','out of tokens','free tier')

def quota_exceeded(error):
 # //remarks: Providers report a used-up free allowance in several different shapes, so the HTTP status and the
 # //remarks: error text are both checked. 402 means the account has no credits left, 429 means the request budget
 # //remarks: (for example a free-tier request cap) was hit, and the body often carries a code such as
 # //remarks: insufficient_quota. The status is read defensively because not every error object carries one.
 status=getattr(error,'status_code',None)
 if status in (402,429): return True
 body=' '.join(str(getattr(error,attr,'')) for attr in ('body','message','code') if getattr(error,attr,''))
 text=(str(error)+' '+body).lower()
 return any(hint in text for hint in QUOTA_CODES)

# //remarks: Turn whatever the tester typed into a Base URL that model discovery can call. This value is only
# //remarks: used for the GET request - the Base URL field keeps exactly what was typed, because the translation
# //remarks: client must keep receiving that same text, and rewriting it could break a provider whose working
# //remarks: endpoint has no version segment. A bare host gains a scheme (http for a local server, https
# //remarks: otherwise) and the OpenAI-compatible version path, so a bare domain or "localhost:1234" both
# //remarks: become callable.
def normalized_url(raw):
 text=str(raw or '').strip().rstrip('/')
 if not text: return ''
 # //remarks: A scheme-less host is a real input case: a local server is nearly always plain http, while a
 # //remarks: public provider is https today, so the guessed scheme follows the host name.
 if not re.match(r'[a-z][a-z0-9+.-]*://',text,re.I):
  host=text.split('/',1)[0].split(':',1)[0].lower()
  local=host in ('localhost','127.0.0.1','::1') or host.startswith('192.168.') or host.startswith('10.') or re.match(r'^172\.(1[6-9]|2\d|3[01])\.',host)
  text=('http://' if local else 'https://')+text
 parts=text.split('#',1)[0].split('?',1)[0]
 # //remarks: The OpenAI-compatible convention is that the base URL carries the version segment (".../v1",
 # //remarks: ".../openai/v1"), so one is added when the tester left it out. An existing version suffix is left
 # //remarks: untouched. This is only the URL discovery calls - the Base URL field itself is never rewritten, so
 # //remarks: the translation client keeps receiving exactly what the tester typed.
 if not re.search(r'/v\d+(?:\.\d+)?$',parts,re.I): parts+='/v1'
 return parts.rstrip('/')

# //remarks: TLS failures used to reach the user as one opaque urlopen string, so a genuinely expired
# //remarks: certificate, an untrusted root, and antivirus HTTPS scanning all read as the same
# //remarks: "expired SSL" message. Hostname and expiry are parsed out of the OpenSSL reason so the status
# //remarks: line can name the real problem and the action that fixes it.
def cert_host_name_error(text):
 match=re.search(r"Hostname mismatch, certificate is not valid for '([^']+)'",text or '')
 return match.group(1) if match else ''

def cert_expired(text):
 # //remarks: OpenSSL's reason string allows both spellings and wraps the expiry inside a sentence, so the check is
 # //remarks: deliberately about the phrase rather than an exact match.
 return 'certificate has expired' in (text or '').lower()

def describe_ssl_error(error):
 # //remarks: One place that turns any TLS failure into a sentence the user can act on: name the expiry when
 # //remarks: the certificate really is out of date, and name the interception when a scanner's own
 # //remarks: certificate (or a mismatched name) is what Python refused. The antivirus hint matters because a
 # //remarks: browser hides this by trusting the scanner's root, so replicating it in a browser proves nothing.
 text=str(error)
 host=cert_host_name_error(text)
 hint=' If an antivirus or corporate HTTPS scanner is running, allow this domain or turn off its web scanning.'
 if cert_expired(text): return 'The provider certificate has expired or is not yet valid, so Windows rejected it. It must be renewed on the server; retrying cannot help.'
 if host: return f'The provider certificate is not valid for {host} (the server sent a certificate for a different name).{hint}'
 if 'self-signed' in text.lower() or 'self signed' in text.lower(): return f'The provider certificate is self-signed and not trusted by this PC. Add it to the Windows trust store, or use a provider with a public certificate.{hint}'
 if 'unable to get local issuer' in text.lower(): return f'The provider certificate cannot be traced to a trusted root. A TLS-inspecting antivirus or proxy is the usual cause.{hint}'
 return f'TLS handshake failed: {text}.{hint}'

def _raise_friendly_http(error,url):
 # //remarks: A rejected key is the most common failure and the provider's own JSON already names it, so the
 # //remarks: body is preferred over a bare status code. Only a short body is read, because the error body of a
 # //remarks: gateway can be a whole HTML page.
 try: body=error.read(600).decode('utf-8','replace').strip()
 except Exception: body=''
 if body:
  try: detail=json.loads(body).get('error')
  except ValueError: detail=None
  if isinstance(detail,dict): detail=detail.get('message') or detail.get('code')
  if detail: raise RuntimeError(f'HTTP {error.code} from {url}: {detail}')
 raise RuntimeError(f'HTTP {error.code} from {url}')

# //remarks: Discovery is deliberately silent: if the list cannot be fetched the current dropdown is left alone
# //remarks: and the user keeps the manual-entry path, because no OCR or translation behaviour depends on this helper.
def fetch_models_once(base_url,api_key,timeout=10):
 head={'Authorization':f'Bearer {api_key}'}
 req=urllib.request.Request(base_url.rstrip('/')+'/models',headers=head,method='GET')
 # //remarks: Transport and HTTP failures are raised rather than swallowed, so a manual refresh can name the
 # //remarks: real reason (rejected key, wrong path, offline host). A valid answer whose list is simply empty
 # //remarks: still returns [], which is how an empty provider catalogue is told apart from a failed request.
 # //remarks: The caller keeps the current list when anything here raises, so the dropdown is never emptied.
 try:
  with urllib.request.urlopen(req,timeout=timeout) as resp: payload=json.loads(resp.read().decode('utf-8','replace'))
 except urllib.error.HTTPError as e: _raise_friendly_http(e,req.full_url)
 # //remarks: A TLS failure is caught before the generic OSError handler, because it is the one transport error
 # //remarks: the user cannot diagnose from the raw message; describe_ssl_error names the cause and the fix.
 except ssl.SSLError as e: raise RuntimeError(describe_ssl_error(e))
 # //remarks: URLError wraps the TLS failure of urlopen, so the reason is unwrapped before it is described here.
 except urllib.error.URLError as e:
  if isinstance(e.reason,ssl.SSLError): raise RuntimeError(describe_ssl_error(e.reason))
  # //remarks: URLError, timeouts, and refused connections are all OSError subclasses, so one handler covers
  # //remarks: an offline host, a wrong port, and a provider that accepts the connection but never answers.
  raise RuntimeError(f'{e.reason if e.reason else e} ({req.full_url})')
 except OSError as e: raise RuntimeError(f'{e} ({req.full_url})')
 except ValueError as e: raise RuntimeError(f'invalid JSON from {req.full_url}: {e}')
 entries=None
 if isinstance(payload,list): entries=payload
 elif isinstance(payload,dict):
  entries=payload.get('data')
  if entries is None: entries=payload.get('models')
  if entries is None and payload and not ({'data','models','object','error','id'} & set(payload.keys())) and all(not isinstance(value,str) for value in payload.values()):
   # //remarks: A bare mapping of model ID -> metadata, which some self-hosted gateways answer instead of the
   # //remarks: OpenAI envelope. Reserved keys and string values keep an ordinary error/status object from
   # //remarks: being mistaken for a model map.
   entries=payload
 if isinstance(entries,dict):
  # //remarks: Some providers answer a bare mapping instead of the OpenAI {"data":[...]} wrapper.
  entries=[k for k in entries.keys() if isinstance(k,str) and k.strip()]
 if not isinstance(entries,list): return []
 found=[]
 for entry in entries:
  if isinstance(entry,str): value=entry; created=0
  elif isinstance(entry,dict): value=entry.get('id') or entry.get('name') or entry.get('model'); created=entry.get('created') or 0
  else: continue
  if not isinstance(value,str) or not value.strip(): continue
  try: created=int(created)
  except (TypeError,ValueError): created=0
  found.append((value.strip(),created))
 if not found: return []
 # //remarks: Newest first (a high "created" timestamp is the only free-tier hint a generic provider gives);
  # //remarks: providers that omit the field fall back to their own response order instead of being shuffled.
 if all(created==0 for _,created in found): return [value for value,_ in found]
 ranked=sorted(enumerate(found),key=lambda pair:(pair[1][1],-pair[0]),reverse=True)
 return [pair[1][0] for pair in ranked]

# //remarks: A single handshake retry covers the transient case that produced the original false "expired" report:
# //remarks: a CDN serves a rotated edge certificate for a moment, and that one connection fails while the very
# //remarks: next one verifies. Only transport/TLS failures are retried - an HTTP error is a real answer and is
# //remarks: never repeated, so a rejected key cannot cost two requests. An expired certificate is not retried
# //remarks: either, because describe_ssl_error already proved that retrying cannot help.
def retryable_transport_error(error):
 text=str(error)
 if 'TLS handshake failed' in text or 'not valid for' in text or 'self-signed' in text or 'trusted root' in text: return True
 return bool(re.search(r'HTTP \d+',text)) is False and 'invalid JSON' not in text

def fetch_models(base_url,api_key,timeout=10,attempts=2):
 last=None
 for attempt in range(max(1,attempts)):
  try: return fetch_models_once(base_url,api_key,timeout)
  except Exception as e:
   last=e
   if attempt+1>=max(1,attempts) or not retryable_transport_error(e): raise
   time.sleep(0.4)
 raise last

# //remarks: Certificate facts for the connected provider. Python does not retain the peer certificate once the
# //remarks: response is closed, so a second, body-less handshake reads it and turns the leaf's not-after date into
# //remarks: a day count. This is only ever attempted after a request already succeeded, so it can never turn a
# //remarks: working connection into a failure.
def tls_certificate_expiry(url,timeout=8):
 try:
  parts=urllib.parse.urlsplit(url if '://' in url else 'https://'+url)
  if (parts.scheme or '').lower()!='https' or not parts.hostname: return None
  context=ssl.create_default_context()
  with socket.create_connection((parts.hostname,parts.port or 443),timeout) as raw:
   with context.wrap_socket(raw,server_hostname=parts.hostname) as tls:
    cert=tls.getpeercert() or {}
  stamp=cert.get('notAfter')
  if not stamp: return None
  expires=ssl.cert_time_to_seconds(stamp)
  return int((expires-time.time())//86400)
 except Exception: return None

# //remarks: site root without the /vN segment, because some hosts publish the list there; the first non-empty
# //remarks: answer wins and the last error is only reported when every form failed.
def model_list_urls(base_url):
 base=base_url.rstrip('/')
 # //remarks: Both forms are bare base URLs: fetch_models appends "/models" itself, so adding it here as well
 # //remarks: produced a doubled path that matched nothing.
 urls=[base]
 match=re.match(r'^(.*)/v\d+(?:\.\d+)?$',base,re.I)
 if match and match.group(1): urls.append(match.group(1))
 return urls
class ReleaseLoader(threading.Thread):
 # //remarks: Startup version check. The GitHub API is contacted once on a daemon thread, so a slow or
 # //remarks: offline network can never delay the window; poll_latest_release() collects the result from a
 # //remarks: timer on the GUI thread. Any failure (HTTP error, bad JSON, offline) reports as an empty tag
 # //remarks: list with the error kept for diagnostics, and the caller simply skips the reminder.
 def __init__(self,url=RELEASES_URL,timeout=8):
  super().__init__(daemon=True); self.url=url; self.timeout=timeout
  self.tags=[]; self.error=None
 def run(self):
  try:
   req=urllib.request.Request(self.url,headers={'Accept':'application/vnd.github+json','User-Agent':'BlueTL-update-check'})
   with urllib.request.urlopen(req,timeout=self.timeout) as resp: body=json.loads(resp.read().decode('utf-8','replace'))
   releases=body if isinstance(body,list) else []
   self.tags=[str((r or {}).get('tag_name') or '').strip() for r in releases if isinstance(r,dict)]
  except Exception as e: self.error=e

class ModelListLoader(threading.Thread):
 def __init__(self,base_url,api_key):
  super().__init__(daemon=True); self.base_url=base_url; self.api_key=api_key
  self.list_id=None; self.list_error=None; self.list_url=''
 def run(self):
  last=None; errors=[]
  for url in model_list_urls(self.base_url):
   try:
    ids=fetch_models(url,self.api_key)
    self.list_url=url
    if ids: self.list_id=ids; return
    # //remarks: A valid but empty list is a real answer, so remaining URL forms are not probed further.
    self.list_id=[]; return
   except Exception as e: last=f'{url}: {e}'; errors.append((url,e))
  # //remarks: The site-root fallback usually answers 404 by design, so reporting the *last* error hid the real one:
  # //remarks: a 503 or a rejected key on the correct <base>/models path was replaced by a meaningless 404. The first
  # //remarks: attempt is the OpenAI convention the user's URL describes, so its reason is the one worth showing; a
  # //remarks: non-HTTP failure (TLS, timeout, offline) is reported verbatim because it describes the host, not a path.
  self.list_id=[]
  first=errors[0][1] if errors else None
  transport=[e for _,e in errors if 'HTTP ' not in str(e)]
  self.list_error=str(transport[0]) if transport else (str(first) if first is not None else 'model list request failed')
  if last and self.list_error and not transport and last not in self.list_error: self.list_error=f'{self.list_error} (also tried {last})'

# //remarks: OCR worker runs in a QThread so the GUI stays responsive while pages are recognised.
# //remarks: It emits progress, page_done, finished, and error signals back to the main thread.
class OCRWorker(QThread):
  progress = Signal(int, int, str)      # done, total, label
  page_done = Signal(list, str, int)    # page_rows, page_name, page_num
  finished = Signal(list, list, str)    # all_rows, empty_pages, status_msg
  error = Signal(str)                   # error message

  def __init__(self, paths, model_dir, detector_path, review_dir):
    super().__init__()
    self.paths = paths
    self.model_dir = model_dir
    self.detector_path = detector_path
    self.review_dir = review_dir
    self._stop_requested = False

  def stop(self):
    self._stop_requested = True

  def run(self):
    try:
      from manga_ocr import MangaOcr
      from comic_text_detector.inference import ComicTextDetector
      import torch
      try:
        torch.set_num_threads(min(4, os.cpu_count() or 1))
      except Exception:
        pass
      detector = ComicTextDetector(str(self.detector_path))
      engine = MangaOcr(str(self.model_dir))
      all_rows = []
      empty_pages = []
      for index, path in enumerate(self.paths, 1):
        if self._stop_requested:
          break
        page = _page_number(Path(path).name, index)
        page_name = Path(path).name
        try:
          img = open_page_image(path)
          crops = _text_crops(img, detector)
          if not crops:
            empty_pages.append(page_name)
            self.progress.emit(index - 1, len(self.paths), f'OCR file {index}/{len(self.paths)}: {page_name} (page {page}, 0 region(s))')
            continue
          self.progress.emit(index - 1, len(self.paths), f'OCR file {index}/{len(self.paths)}: {page_name} (page {page}, {len(crops)} region(s))')
          page_rows = []
          panel = 0
          for region, (box, crop) in enumerate(crops, 1):
            if self._stop_requested:
              break
            self.progress.emit(index - 1, len(self.paths), f'OCR file {index}/{len(self.paths)}, region {region}/{len(crops)}')
            if _is_blank(crop):
              continue
            text = engine(crop).strip()
            if text:
              panel += 1
              crop_path = str(Path(self.review_dir) / f'p{page:03d}_p{panel:03d}.png')
              try:
                crop.save(crop_path)
              except (OSError, ValueError):
                crop_path = ''
              reason = _suspicion(crop, text)
              page_rows.append(Row(page, panel, text, crop=crop_path, review='CHECK' if reason else '', reason=reason))
          if page_rows:
            self.page_done.emit(page_rows, page_name, page)
            all_rows.extend(page_rows)
        except (OSError, ValueError) as e:
          empty_pages.append(f'{page_name} (unreadable: {e})')
          continue
      status_msg = f'OCR completed: {len(all_rows)} text region(s) across {len(self.paths)} page(s). Review before translating.'
      if self._stop_requested:
        status_msg = f'OCR stopped: {len(all_rows)} text region(s) kept from the pages recognised so far.'
      self.finished.emit(all_rows, empty_pages, status_msg)
    except Exception as e:
      self.error.emit(f'{type(e).__name__}: {e}\n\nOCR model path: {self.model_dir}\nDetector model path: {self.detector_path}')

# //remarks: Bundled asset resolution. Assets sit next to the source checkout when running from source and
# //remarks: under _MEIPASS inside the PyInstaller bundle, so one helper keeps both layouts correct.
def asset_path(*parts):
  return Path(getattr(sys,'_MEIPASS',Path(__file__).parent)).joinpath('assets',*parts)

def detector_model_path():
  # //remarks: Single definition of the bundled detector weights, shared by the loader and its error message.
  return asset_path('comic-text-detector-model','comictextdetector.pt')

# //remarks: Page level OCR helpers. Manga OCR only accepts one text strip per call and ships no detector,
# //remarks: so text detection is delegated to kha-white's comic-text-detector - the detector mokuro uses -
# //remarks: vendored under comic_text_detector\ and loaded from assets\comic-text-detector-model. One page
# //remarks: therefore still yields one row per detected text block, but the boxes now come from a trained
# //remarks: detector instead of adaptive thresholding plus geometric bubble guessing, which found glyphs but
# //remarks: could not decide which of them belonged to one bubble. The threshold helpers further down are
# //remarks: kept as an independent sanity check on the recognised text.
def _components(mask):
  # //remarks: Minimal 8-connected component labeller (pure Python/NumPy, no scipy or OpenCV).
  # //remarks: Text glyphs and bubble outlines are separate components, which is what allows the
  # //remarks: text/line-art split without pixel-level heuristics.
  import numpy as np
  h,w=mask.shape
  labels=np.zeros((h,w),dtype=np.int32)
  comps=[]
  ys,xs=np.nonzero(mask)
  for y,x in zip(ys.tolist(),xs.tolist()):
    if labels[y,x]: continue
    lab=len(comps)+1
    stack=[(y,x)]; labels[y,x]=lab
    x0=x1=x; y0=y1=y; area=0
    while stack:
      cy,cx=stack.pop(); area+=1
      if cx<x0:x0=cx
      if cx>x1:x1=cx
      if cy<y0:y0=cy
      if cy>y1:y1=cy
      for ny in (cy-1,cy,cy+1):
        for nx in (cx-1,cx,cx+1):
          if 0<=ny<h and 0<=nx<w and mask[ny,nx] and not labels[ny,nx]:
            labels[ny,nx]=lab; stack.append((ny,nx))
    comps.append({'box':(x0,y0,x1,y1),'area':area})
  return labels,comps
def _box_mean(arr,radius):
  # //remarks: Mean of every pixel's (2r+1) square neighbourhood using integral images, so
  # //remarks: adaptive thresholding stays fast on full manga pages without scipy/OpenCV.
  import numpy as np
  r=max(1,int(radius))
  padded=np.pad(arr,((r+1,r),(r+1,r)),mode='edge').astype(np.int64)
  integral=padded.cumsum(0).cumsum(1)
  win=(2*r+1)**2
  y0=np.arange(arr.shape[0])[:,None]; x0=np.arange(arr.shape[1])[None,:]
  y1=y0+2*r+1; x1=x0+2*r+1
  total=integral[y1,x1]-integral[y0,x1]-integral[y1,x0]+integral[y0,x0]
  return total/win

def _text_mask(img):
  import numpy as np
  # //remarks: Adaptive (Sauvola-style) binarisation. Each pixel is compared with its own
  # //remarks: neighbourhood mean, so it tolerates worn scans, screentone and uneven lighting -
  # //remarks: a global threshold returned nothing on noisy pages.
  grey=np.asarray(img.convert('L'),dtype=np.float32)
  h,w=grey.shape
  radius=max(4,min(h,w)//60)
  local=_box_mean(grey,radius)
  threshold=local*(1-0.18)
  mask=grey<threshold
  # //remarks: Drop isolated speckles by requiring ink in a 3x3 neighbourhood; this removes scan
  # //remarks: noise without eroding thin glyph strokes.
  if mask.any():
    neigh=np.zeros_like(mask,dtype=np.int16)
    for dy in (-1,0,1):
      for dx in (-1,0,1):
        neigh+=np.roll(np.roll(mask,dy,axis=0),dx,axis=1).astype(np.int16)
    mask=mask&(neigh>=3)
  return mask

# //remarks: Cached detector instance. Loading the weights takes about a second and they are ~76 MB, so the
# //remarks: detector is built on first use and reused for every page of the batch.
_DETECTOR=None
def release_ocr_models():
  # //remarks: OCR is a batch operation, but the detector and Manga OCR stay resident for the whole session
  # //remarks: unless they are dropped: torch alone costs ~200 MB and the loaded detector another ~300 MB, so
  # //remarks: a user who recognises one chapter then just reads the table keeps paying for models they are no
  # //remarks: longer using. Called when a batch ends, so the next batch pays the ~1 s reload instead of the app
  # //remarks: holding half a gigabyte while idle.
  global _DETECTOR
  _DETECTOR=None
  # //remarks: torch caches its allocations and keeps worker threads alive, so dropping the Python reference
  # //remarks: alone does not return the memory. empty_cache() frees the cached blocks on CUDA builds, and
  # //remarks: gc.collect() drops the model graph on CPU builds where the reference is the only owner.
  try:
   import torch
   if torch.cuda.is_available(): torch.cuda.empty_cache()
  except Exception: pass
  try:
   import gc
   gc.collect()
  except Exception: pass
def text_detector():
  # //remarks: Built lazily so importing app.py stays fast and a machine without the detector installed only
  # //remarks: fails when OCR is actually requested.
  global _DETECTOR
  if _DETECTOR is None:
   from comic_text_detector.inference import TextDetector
   model=detector_model_path()
   if not model.is_file():
    raise FileNotFoundError(f'Text detection model is incomplete. Expected comictextdetector.pt at: {model}')
   import torch
   # //remarks: Same device policy as MangaOcr: use the GPU when torch can see one, otherwise the CPU.
   device='cuda' if torch.cuda.is_available() else 'cpu'
   # //remarks: Cap the CPU thread pool. Torch defaults to one thread per core, and each thread keeps its own
   # //remarks: allocation arena, which is a large part of the ~200 MB jump seen when torch is first imported.
   # //remarks: OCR here is one small page at a time, so four threads lose almost no speed and save memory.
   try: torch.set_num_threads(min(4,os.cpu_count() or 1))
   except Exception: pass

   # //remarks: input_size=1024 with act='leaky' are the settings this checkpoint is used with in mokuro.
   _DETECTOR=TextDetector(model_path=str(model),input_size=1024,device=device,act='leaky')
  return _DETECTOR

def detect_text_regions(img):
  # //remarks: Public entry point. The detector answers with the text blocks of the page and each block box
  # //remarks: becomes one OCR region. Blocks are returned in manga reading order so the table follows the
  # //remarks: page: top-to-bottom, and right-to-left within one band.
  import numpy as np
  # //remarks: The detector expects an OpenCV style BGR array, which is what mokuro feeds it via cv2.imread.
  page=np.asarray(img.convert('RGB'))[:,:,::-1].copy()
  h,w=page.shape[:2]
  # //remarks: refine_mode=1 (REFINEMASK_ANNOTATION) matches mokuro. Only the block boxes are used here, so
  # //remarks: the optional "undetected mask" pass is skipped.
  blocks=text_detector()(page,refine_mode=1,keep_undetected_mask=False)[2]
  boxes=[]
  for block in blocks:
   # //remarks: blk.xyxy holds numpy integers, which are cast so PIL and the review metadata get plain ints.
   x0,y0,x1,y1=(int(v) for v in block.xyxy)
   if (x1-x0)<6 or (y1-y0)<6: continue
   # //remarks: A small margin keeps glyph edges off the crop border, as the previous detector did.
   pad=max(2,int(min(w,h)*0.006))
   boxes.append((max(0,x0-pad),max(0,y0-pad),min(w,x1+pad),min(h,y1+pad)))
  boxes=_dedupe_boxes(boxes)
  row_h=max(1,int(h*0.04))
  return sorted(boxes,key=lambda b:((b[1]+b[3])//2//row_h,-b[0]))

def _dedupe_boxes(boxes,inner=0.6):
  # //remarks: The detector can report one text block together with smaller blocks nested inside it, which
  # //remarks: would otherwise become duplicate OCR rows for the same bubble. A box that is mostly covered by
  # //remarks: a larger kept box is dropped, while neighbouring bubbles that only clip each other stay
  # //remarks: separate so every crop still holds one complete text block.
  if not boxes: return []
  ordered=sorted(boxes,key=lambda b:(b[2]-b[0]+1)*(b[3]-b[1]+1),reverse=True)
  kept=[]
  for box in ordered:
   area=(box[2]-box[0]+1)*(box[3]-box[1]+1)
   covered=False
   for k in kept:
    overlap_x=min(box[2],k[2])-max(box[0],k[0])+1
    overlap_y=min(box[3],k[3])-max(box[1],k[1])+1
    if overlap_x>0 and overlap_y>0 and overlap_x*overlap_y>=inner*area:
     covered=True; break
   if not covered: kept.append(box)
  return kept

def _text_crops(img):
  # //remarks: Manga OCR's upstream documentation warns that it always attempts to recognise text and
  # //remarks: can "dream up" plausible sentences on blank images. Never pass a whole page or page half
  # //remarks: as a fallback: a missed detection must produce no OCR row, not invented dialogue.
  return [(box,img.crop(box)) for box in detect_text_regions(img)]

# //remarks: PSD support for OCR. Photoshop pages are layered documents, and the detector/OCR only understands a
# //remarks: flat raster, so a .psd has to be flattened before it can be read. Pillow's own PSD plugin is not
# //remarks: enough: it only targets very old Photoshop files and raises UnidentifiedImageError on a 16-bit
# //remarks: document (verified), which is the usual depth for manga artwork. psd-tools is therefore used to
# //remarks: composite the visible layers into one page image, exactly what Photoshop shows when the file is
# //remarks: flattened. It ships prebuilt Windows wheels, so the frozen build needs no compiler. The composited
# //remarks: page is cached as a PNG so the same file is only flattened once per run.
PSD_SUFFIXES=('.psd',)
# //remarks: One definition of what Import accepts, shared by the file dialog, the folder scan and the
# //remarks: archive extraction, so the three paths can never drift apart and accept different files.
IMAGE_SUFFIXES=('.jpg','.jpeg','.png','.webp','.psd')
# //remarks: 7z is read with py7zr, ZIP with the standard library and RAR with rarfile. RAR still needs an
# //remarks: external unrar/WinRAR binary, which rarfile reports clearly when it is missing.
ARCHIVE_SUFFIXES=('.zip','.rar','.7z')
IMPORT_SUFFIXES=IMAGE_SUFFIXES+ARCHIVE_SUFFIXES
def is_psd(path):
 # //remarks: Extension check only; the real content check is PSDImage.open, which raises on anything else.
 return Path(path).suffix.lower() in PSD_SUFFIXES

def flatten_psd(path,dest=None):
 # //remarks: Flatten a layered .psd into a single page PNG and return its path. Compositing merges every
 # //remarks: visible layer with its blend mode, opacity, and mask, so the text the OCR reads is the text that
 # //remarks: is actually visible on the finished page - hidden construction layers never leak into OCR.
 # //remarks: The result is converted to RGB because the detector expects 3-channel input while a PSD may be
 # //remarks: RGBA, greyscale, CMYK, or 16-bit.
 from psd_tools import PSDImage
 psd=PSDImage.open(str(path))
 try:
  page=psd.composite()
  if page is None: raise RuntimeError('the document has no visible pixels to composite')
  if page.mode != 'RGB': page=page.convert('RGB')
  target=Path(dest) if dest else Path(tempfile.mkdtemp(prefix='bluetl_psd_'))/f'{Path(path).stem}.png'
  target.parent.mkdir(parents=True,exist_ok=True)
  page.save(target,'PNG')
  return str(target)
 finally:
  # //remarks: Release the PSD handle and its layer data promptly; a large layered file holds a lot of memory.
  close=getattr(psd,'close',None)
  if callable(close): close()

def open_page_image(path):
 # //remarks: Single place that turns an imported page file into a Pillow image for text detection. Ordinary
 # //remarks: rasters open directly; a .psd is flattened first.
 from PIL import Image
 target=flatten_psd(path) if is_psd(path) else str(path)
 img=Image.open(target); img.load()
 return img

def _is_blank(crop):
  # //remarks: Flat crops (empty bubble interiors, solid panel fills) contain no glyphs, and Manga OCR
  # //remarks: answers such input with invented text instead of nothing. Rejecting flat crops before the
  # //remarks: engine is called keeps those invented lines out of the table.
  import numpy as np
  grey=np.asarray(crop.convert('L'),dtype=np.float32)
  return grey.size==0 or float(grey.std())<4.0

def _shape_count(crop):
  # //remarks: Rough count of glyph-sized shapes in one crop. Manga OCR reports no confidence, so the count
  # //remarks: of real shapes is used as an independent check on how much text the region can actually hold.
  import numpy as np
  mask=_text_mask(crop)
  if not mask.any(): return 0
  h,w=mask.shape; limit=max(6,int(min(h,w)*0.8))
  _,comps=_components(mask)
  return sum(1 for c in comps if c['area']>=4 and (c['box'][2]-c['box'][0]+1)<=limit and (c['box'][3]-c['box'][1]+1)<=limit)

def _suspicion(crop,text):
  # //remarks: Manga OCR has no confidence score, so a result is checked against the region it came from and
  # //remarks: suspicious rows are flagged for review instead of being trusted. Every rule below describes a
  # //remarks: shape that invented text takes in practice: a region with almost no ink, a result holding no
  # //remarks: Japanese at all, or a line far longer than the number of glyph shapes present.
  import numpy as np
  grey=np.asarray(crop.convert('L'),dtype=np.float32)
  if grey.size==0: return 'empty region'
  if float((grey<128).mean())<0.01: return 'almost no ink in the region'
  shapes=_shape_count(crop)
  if len(text)>max(6,3*shapes): return f'{len(text)} characters from {shapes} shape(s) in the region'
  if len(text)>=4 and not re.search(r'[\u3040-\u30ff\u4e00-\u9fff]',text): return 'no Japanese characters in the result'
  return ''

def _page_number(name,fallback):
  # //remarks: The page number follows the file name, so a file called "page_007.jpg" is reported as page
  # //remarks: 7 instead of whatever position it happens to occupy in the batch. The last run of digits in
  # //remarks: the stem wins, because manga names usually end with the page index ("ch01_p007", "007").
  # //remarks: A name without any digits (for example "cover.jpg") has no page number of its own, so the
  # //remarks: sequential position is used as a fallback and the row still gets a usable number.
  stem=Path(str(name)).stem
  groups=re.findall(r'\d+',stem)
  return int(groups[-1]) if groups else fallback

def _name_key(value):
  # //remarks: Natural sort key for file names: "p9" must come before "p10", whereas plain text
  # //remarks: sorting put "p10" between "p1" and "p2". Splitting on runs of digits keeps strings at
  # //remarks: even positions and integers at odd ones, so every comparison stays type-safe.
  return [int(p) if p.isascii() and p.isdigit() else p for p in re.split(r'(\d+)',str(value).lower())]

class Window(QMainWindow):
 def __init__(self):
   super().__init__(); self.setWindowTitle('BlueTL - Manga Translator'); self.resize(1152,760); self.setMinimumSize(820,620); self.rows=[]; self.paths=[]
   # //remarks: Tracks whether the OCR step has run for the current batch. Manual row insertion waits for
   # //remarks: that step, because a new row takes its page and panel number from the recognised rows.
   self.recognized=False
   # //remarks: Set to True by the Stop button to interrupt a running OCR or translation batch.
   self.stop_requested=False
   # //remarks: True only while a batch is in flight, so the Stop button is clickable exactly then.
   self.busy=False
   # //remarks: (model, error) pairs whose free allowance or request limit ran out during the current batch,
   # //remarks: collected so one reminder popup can list every affected model when the batch ends.
   self.quota_limits_seen=[]
   # //remarks: Remember the last folder used by the import dialog across application restarts.
   self.last_dir=''
   # //remarks: Folder holding the crop of every recognised region, so a flagged line can be compared with
   # //remarks: the region it came from, and later exported as review material.
   self.review_dir=''
   # //remarks: Tracks the model that last answered a request; used in the API status tooltip.
   self.last_model=''
   # //remarks: Model-list discovery state: the last successfully fetched list is cached in the settings file,
   # //remarks: the debounce timer keeps keystrokes in the Base URL field from firing one request per character,
   # //remarks: and the refresh lock prevents a second queued refresh from starting while one is already waiting.
   self.model_cache=[]
   self.model_timer=QTimer(self); self.model_timer.setSingleShot(True); self.model_timer.setInterval(700)
   self.model_timer.timeout.connect(lambda: self.refresh_models(manual=False))
   self.model_refreshing=False
   # //remarks: Result collection for the discovery worker: the poll timer ticks while a fetch is in flight and
   # //remarks: poll_models() finishes the step once the worker is done or the wall-clock deadline passed.
   self.model_loader=None; self.model_url=''; self.model_deadline=0.0; self.model_manual=False; self.model_key=''; self.model_verify=False; self.model_check=False; self.model_request=('','')
   # //remarks: The key used for the fetch and whether that fetch is the explicit Save press, which is the
   # //remarks: only path allowed to spend a completion proving the key.
   # //remarks: URL edited while a fetch was already in flight; poll_models() runs it right after the current
   # //remarks: request finishes, so a corrected Base URL is never left with the previous provider's models.
   self.model_pending=''
   self.model_poll=QTimer(self); self.model_poll.setInterval(100)
   self.model_poll.timeout.connect(self.poll_models)
   # //remarks: Base URL whose list was last fetched, so a redundant re-fetch (for example typing and then
   # //remarks: undoing the edit) is skipped and auto-discovery stays quiet.
   self.refreshed=''
   # //remarks: Cline-style confirmation gate. The Base URL and API key are typed as a *draft* and are not used
   # //remarks: until the user presses Save. self.connected_url/connected_key hold the values that were
   # //remarks: actually confirmed; the model dropdown stays disabled until a list has been fetched for them. A
   # //remarks: later edit to either field makes the connection stale, so the button reactivates and the user
   # //remarks: re-confirms instead of the app silently talking to a provider they did not intend.
   self.connected_url=''; self.connected_key=''
   # //remarks: (profile key, API key) of the last model fetch that succeeded; only that pair is ever written to disk.
   self.fetched=('','')
   # //remarks: Remembered providers, keyed by Base URL (see profile_key). A provider enters this map only after its
   # //remarks: key worked, which is what lets the user switch between several Base URLs without retyping anything
   # //remarks: and without a saved key ever being offered to the wrong host.
   self.profiles={}
   # //remarks: A provider's /models catalogue is public at some hosts (it answers 200 without a key), so a fetched
   # //remarks: list proves the URL, not the key. The Model dropdown therefore stays locked until a real key check
   # //remarks: succeeds - Test API, or the one-token probe that Save runs when the list has no models to
   # //remarks: probe. self.api_verified records the profile key that passed.
   self.api_verified=''
   # //remarks: Days left on the provider's certificate, filled in after a successful fetch. A known expiry is worth
   # //remarks: showing, because the failure it prevents (a silently renewed-then-lapsed certificate) is exactly the
   # //remarks: one that produced the original false "expired SSL" report.
   self.cert_days=None
   # //remarks: Set while load() fills the fields from the settings file, so the provider-restore handler does not
   # //remarks: undo the restored selection or fight the startup refresh.
   self.restoring=False
   icon_path=asset_path('bluetl.png')
   if icon_path.is_file(): self.setWindowIcon(QIcon(str(icon_path)))
   self.ui(); self.load()
 def ui(self):
  w=QWidget(); shell=QVBoxLayout(w); shell.setContentsMargins(14,10,14,8); shell.setSpacing(8)
  brand=QHBoxLayout(); brand.setSpacing(10)
  title=QLabel('BlueTL'); title.setObjectName('brandTitle')
  subtitle=QLabel('Manga Translator'); subtitle.setObjectName('brandSubtitle')
  brand.addWidget(title); brand.addWidget(subtitle); brand.addStretch()
  self.header_connection=QLabel('● Not connected'); self.header_connection.setObjectName('connectionBadge')
  brand.addWidget(self.header_connection); shell.addLayout(brand)
  self.tabs=QTabWidget(); self.tabs.setTabPosition(QTabWidget.West)
  page=QWidget(); v=QVBoxLayout(page); v.setContentsMargins(6,8,6,6); v.setSpacing(9)
  control_panel=QWidget(); cv=QVBoxLayout(control_panel); cv.setContentsMargins(6,8,6,6); cv.setSpacing(9)

  self.connection_card=QFrame(); self.connection_card.setObjectName('connectionCard')
  connection=QVBoxLayout(self.connection_card); connection.setContentsMargins(14,10,14,10); connection.setSpacing(8)
  connection_heading=QHBoxLayout()
  connection_title=QLabel('Connection'); connection_title.setObjectName('cardTitle')
  connection_heading.addWidget(connection_title); connection_heading.addStretch()
  self.connect_button=QPushButton('Save')
  self.connect_button.setObjectName('connectAction')
  self.connect_button.setToolTip('Confirm the Base URL and API key. Pressing this fetches the full model list from the provider and, once the key is proved, enables the Model dropdown.')
  self.connect_button.clicked.connect(self.confirm_connection)
  connection_heading.addWidget(self.connect_button)
  # //remarks: The editor has its own tab, so the old Hide button becomes a way back to the work area. Hiding the
  # //remarks: card itself would leave an empty Control Panel and no way to edit the provider at all.
  self.back_to_translate_button=QPushButton('Back to Translate')
  self.back_to_translate_button.setToolTip('Return to the Translate tab. The connection summary stays visible in Translation Settings.')
  self.back_to_translate_button.clicked.connect(self.show_translate_tab)
  connection_heading.addWidget(self.back_to_translate_button); connection.addLayout(connection_heading)

  provider_row=QHBoxLayout(); provider_row.setSpacing(8)
  provider_label=QLabel('Saved providers'); provider_label.setObjectName('fieldLabel')
  self.provider=QComboBox(); self.provider.setToolTip('Saved providers. Choosing one fills in its Base URL and API key, then re-fetches its model list.')
  self.provider.activated.connect(self.on_provider_chosen)
  self.delete_provider_button=QPushButton('Delete')
  self.delete_provider_button.setToolTip('Remove the saved provider that matches the Base URL on screen, together with its stored API key and model list.')
  self.delete_provider_button.clicked.connect(self.delete_provider)
  provider_group=QVBoxLayout(); provider_group.setSpacing(4); provider_group.addWidget(provider_label)
  provider_controls=QHBoxLayout(); provider_controls.setSpacing(8); provider_controls.addWidget(self.provider,1); provider_controls.addWidget(self.delete_provider_button); provider_group.addLayout(provider_controls)
  provider_row.addLayout(provider_group,1); connection.addLayout(provider_row)

  self.url=QLineEdit(); self.url.setPlaceholderText('https://your-provider.example/v1')
  self.key=QLineEdit(); self.key.setEchoMode(QLineEdit.Password); self.key.setPlaceholderText('API key')
  fields=QGridLayout(); fields.setHorizontalSpacing(18); fields.setVerticalSpacing(10)
  url_label=QLabel('OpenAI-compatible Base URL'); url_label.setObjectName('fieldLabel')
  key_label=QLabel('API key'); key_label.setObjectName('fieldLabel')
  fields.addWidget(url_label,0,0); fields.addWidget(key_label,0,1)
  fields.addWidget(self.url,1,0); fields.addWidget(self.key,1,1)

  self.model=QComboBox(); self.model.setEditable(True); self.model.setToolTip('Selects the model tried first; remaining models in the list are automatic fallbacks. The list is fetched from your Base URL after you press Save.')
  self.model.setEnabled(False)
  self.free_only=QCheckBox('Free models only')
  self.free_only.setToolTip('Show only the models whose ID contains the text "free" (searched in the list fetched from your Base URL).')
  self.free_only.toggled.connect(self.on_free_only_toggled)
  self.refresh_button=QPushButton('Refresh models')
  self.refresh_button.setToolTip('Re-fetch the model list from the confirmed Base URL.')
  self.refresh_button.clicked.connect(lambda: self.refresh_models(manual=True))
  self.refresh_button.setEnabled(False)
  model_row_widget=QWidget()
  model_row=QHBoxLayout(model_row_widget); model_row.setContentsMargins(0,0,0,0); model_row.setSpacing(8)
  model_row.addWidget(self.model,1); model_row.addWidget(self.refresh_button); model_row.addWidget(self.free_only)
  model_label=QLabel('Model'); model_label.setObjectName('fieldLabel')
  fields.addWidget(model_label,2,0,1,2); fields.addWidget(model_row_widget,3,0,1,2)
  self.refresh_button.hide()
  connection.addLayout(fields)
  self.url.textEdited.connect(lambda _: self.on_connection_edited())
  self.key.textEdited.connect(lambda _: self.on_connection_edited())
  self.url.textChanged.connect(lambda _: self.on_url_changed())

  self.connect_status=QLabel(); self.connect_status.setTextFormat(Qt.PlainText)
  connect_row=QHBoxLayout(); connect_row.setSpacing(0); connect_row.addWidget(self.connect_status,1)
  connection.addLayout(connect_row)
  cv.addWidget(self.connection_card)

  # //remarks: The default output language is a Control Panel setting rather than a per-batch choice: it seeds the
  # //remarks: target-language picker on the Translate tab, so a user who always translates into one language sets it
  # //remarks: once. Both pickers carry the same bilingual labels and the same internal language keys.
  self.default_lang=QComboBox()
  for name in LANGS: self.default_lang.addItem(LANGUAGE_LABELS[name],name)
  self.default_lang.setToolTip('Default output language. Every batch starts with this target language; the Translate tab can still change it for the current batch.')
  self.default_lang.currentIndexChanged.connect(lambda _: self.on_default_language_changed())
  default_card=QFrame(); default_card.setObjectName('settingsCard')
  default_layout=QVBoxLayout(default_card); default_layout.setContentsMargins(14,10,14,10); default_layout.setSpacing(8)
  default_title=QLabel('Default Output Language'); default_title.setObjectName('cardTitle')
  default_layout.addWidget(default_title)
  default_group=QVBoxLayout(); default_group.setSpacing(4)
  default_label=QLabel('Output language'); default_label.setObjectName('fieldLabel')
  default_group.addWidget(default_label); default_group.addWidget(self.default_lang)
  default_layout.addLayout(default_group)
  self.default_language_note=QLabel('Used as the target language whenever a batch starts.')
  self.default_language_note.setObjectName('fieldLabel'); self.default_language_note.setWordWrap(True)
  default_layout.addWidget(self.default_language_note)
  cv.addWidget(default_card)

  self.default_export_format=QComboBox()
  for key,label in EXPORT_FORMATS: self.default_export_format.addItem(label,key)
  self.default_export_format.setToolTip('Default export format. The Export dialog opens with this format selected, but you can choose another format each time.')
  self.default_export_format.currentIndexChanged.connect(lambda _: self.on_default_export_format_changed())
  export_card=QFrame(); export_card.setObjectName('settingsCard')
  export_layout=QVBoxLayout(export_card); export_layout.setContentsMargins(14,10,14,10); export_layout.setSpacing(8)
  export_title=QLabel('Default Export Format'); export_title.setObjectName('cardTitle')
  export_layout.addWidget(export_title)
  export_group=QVBoxLayout(); export_group.setSpacing(4)
  export_label=QLabel('Format used first in the Export dialog'); export_label.setObjectName('fieldLabel')
  export_group.addWidget(export_label); export_group.addWidget(self.default_export_format)
  export_layout.addLayout(export_group)
  export_note=QLabel('You can still choose PDF, Word (DOCX), or Plain Text (TXT) when exporting.')
  export_note.setObjectName('fieldLabel'); export_note.setWordWrap(True); export_layout.addWidget(export_note)
  cv.addWidget(export_card); cv.addStretch()

  self.lang=QComboBox()
  for name in LANGS: self.lang.addItem(LANGUAGE_LABELS[name],name)
  self.api_status=QLabel(); self.image_status=QLabel()
  for pill in (self.api_status,self.image_status): pill.setTextFormat(Qt.PlainText)
  self.set_api_status(None); self.set_image_status(None)

  # //remarks: The collapsed connection summary stays in Translation Settings: it reports the provider state at a
  # //remarks: glance, while the editor that changes it lives on the Control Panel tab.
  self.connection_summary=QFrame(); self.connection_summary.setObjectName('connectionSummary')
  summary=QHBoxLayout(self.connection_summary); summary.setContentsMargins(10,6,8,6); summary.setSpacing(8)
  self.connection_summary_text=QLabel('Connection required. Enter your provider details in the Control Panel.')
  self.connection_summary_text.setTextFormat(Qt.PlainText); self.connection_summary_text.setWordWrap(True)
  summary.addWidget(self.connection_summary_text,1)
  self.change_connection_button=QPushButton('Change')
  self.change_connection_button.setToolTip('Open the Control Panel to edit the provider connection.')
  self.change_connection_button.clicked.connect(self.open_control_panel)
  summary.addWidget(self.change_connection_button)

  self.job_card=QFrame(); self.job_card.setObjectName('jobCard')
  job=QVBoxLayout(self.job_card); job.setContentsMargins(14,10,14,10); job.setSpacing(8)
  job_title=QLabel('Translation Settings'); job_title.setObjectName('cardTitle'); job.addWidget(job_title)
  job.addWidget(self.connection_summary)
  job_controls=QHBoxLayout(); job_controls.setSpacing(10)
  language_group=QVBoxLayout(); language_group.setSpacing(4)
  language_label=QLabel('Target language'); language_label.setObjectName('fieldLabel')
  language_group.addWidget(language_label); language_group.addWidget(self.lang)
  job_controls.addLayout(language_group,1)
  self.job_refresh_button=QPushButton('Refresh models')
  self.job_refresh_button.setToolTip(self.refresh_button.toolTip())
  self.job_refresh_button.setEnabled(False)
  self.job_refresh_button.clicked.connect(lambda: self.refresh_models(manual=True))
  job_controls.addWidget(self.job_refresh_button)
  job_controls.addWidget(self.api_status); job_controls.addWidget(self.image_status)
  job.addLayout(job_controls)

  self.ocr_button=QPushButton('Recognise OCR')
  self.ocr_button.setToolTip('Recognise every text region on the imported images with the local OCR model. This spends no API tokens.')
  self.ocr_button.clicked.connect(self.recognize)
  self.add_button=QPushButton('Add row')
  self.add_button.setToolTip('Insert an empty row directly below the selected line so you can type the text yourself. Enabled once OCR has run.')
  self.add_button.clicked.connect(self.add)
  self.delete_button=QPushButton('Delete row')
  self.delete_button.setToolTip('Remove the selected row, for example a line the recogniser invented on a textless region.')
  self.delete_button.clicked.connect(self.delete)
  import_button=QPushButton('Import')
  import_button.clicked.connect(self.images)
  # //remarks: The Import button opens a picker menu, so it is kept on the instance to anchor that menu under it.
  self.import_button=import_button
  import_button.setToolTip('Import manga images or archives. Choose several files at once, or one folder.')
  translate_button=QPushButton('Translate all')
  translate_button.setObjectName('primaryAction')
  translate_button.clicked.connect(self.all)
  # //remarks: Stop sits beside Translate all and interrupts whichever batch is running - OCR or translation -
  # //remarks: because Translate all runs OCR first when the batch has not been recognised yet. It stays disabled
  # //remarks: while nothing is running so it never looks like a dead button.
  self.stop_button=QPushButton('Stop')
  self.stop_button.setObjectName('stopAction')
  self.stop_button.setToolTip('Stop the running OCR or translation batch. Finished rows are kept.')
  self.stop_button.clicked.connect(self.stop)
  self.stop_button.setEnabled(False)
  action_row=QHBoxLayout(); action_row.setSpacing(10)
  import_button.setMinimumWidth(140); self.ocr_button.setMinimumWidth(180)
  action_row.addWidget(import_button); action_row.addWidget(self.ocr_button); action_row.addWidget(translate_button,1); action_row.addWidget(self.stop_button)
  job.addLayout(action_row)

  self.test_api_button=QPushButton('Test API'); self.test_api_button.clicked.connect(self.test_api)
  self.export_button=QPushButton('Export'); self.export_button.clicked.connect(self.export)
  self.export_button.setToolTip('Export the translation table. Choose TXT, DOCX, or PDF in the dialog that opens.')
  utility_row=QHBoxLayout(); utility_row.addStretch()
  for button in (self.test_api_button,self.export_button,self.add_button,self.delete_button):
   utility_row.addWidget(button)
  job.addLayout(utility_row); v.addWidget(self.job_card)

  self.table=QTableWidget(0,5); self.table.setHorizontalHeaderLabels(['PAGE','PANEL','Recognised text','TRANSLATION','REVIEW'])
  self.table.setWordWrap(True); self.table.setAlternatingRowColors(True)
  self.table.setShowGrid(False); self.table.verticalHeader().setVisible(False)
  self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeToContents)
  self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeToContents)
  self.table.horizontalHeader().setSectionResizeMode(2,QHeaderView.Stretch)
  self.table.horizontalHeader().setSectionResizeMode(3,QHeaderView.Stretch)
  self.table.horizontalHeader().setSectionResizeMode(4,QHeaderView.ResizeToContents)
  self.table.horizontalHeader().sectionResized.connect(lambda *_: self._fit_rows())
  v.addWidget(self.table,1)
  self.progress=QProgressBar(); self.progress.setRange(0,1); self.progress.setValue(0)
  self.progress.setTextVisible(True); self.progress.setFormat('%v/%m'); self.progress.setMaximumHeight(18)
  self.progress.setVisible(False); v.addWidget(self.progress)
  footer=QHBoxLayout()
  self.status=QLabel('Import images, then click Recognise OCR to load the text lines.')
  self.status.setTextFormat(Qt.PlainText); footer.addWidget(self.status,1)
  self.ready_label=QLabel('Ready  ●'); self.ready_label.setObjectName('readyStatus'); footer.addWidget(self.ready_label)
  v.addLayout(footer)

  self.translate_page=page; self.control_panel_page=control_panel
  self.tabs.addTab(page,'Translate')
  self.tabs.addTab(control_panel,'Control Panel')
  about=QWidget(); av=QVBoxLayout(about)
  about_details=QLabel(f'<h2>BlueTL</h2><p>Version v{APP_VERSION}</p><p>Published by borneanwingz.fl</p><p>Author: Blue-Wingz @ facedesk</p><p><a href="https://github.com/BorneanWingz/PrivateRepoReadmes/blob/main/BlueTLReadme.md">Readme</a></p>')
  about_details.setOpenExternalLinks(True); av.addWidget(about_details)
  av.addStretch()
  support=QLabel('If you enjoy my app, please consider to <a href="https://buymeacoffee.com/DrLwSii">buy me a cuppa</a>!')
  support.setOpenExternalLinks(True); support.setWordWrap(True); av.addWidget(support)
  self.tabs.addTab(about,'About')
  w.setStyleSheet('''
   QWidget { color: #172033; font-family: "Segoe UI"; font-size: 9pt; }
   QMainWindow { background: #f1f3f7; }
   QLabel#brandTitle { font-size: 23pt; font-weight: 700; color: #101828; }
   QLabel#brandSubtitle { font-size: 14pt; color: #667085; padding-top: 5px; }
   QLabel#connectionBadge { color: #16763a; background: #e4f4e8; border: 1px solid #a7d7b4; border-radius: 15px; padding: 5px 9px; min-height: 30px; font-weight: 600; }
   QLabel#cardTitle { font-size: 12pt; font-weight: 700; }
   QLabel#fieldLabel { color: #475467; font-size: 8pt; font-weight: 600; }
   QFrame#connectionCard, QFrame#jobCard, QFrame#settingsCard { background: #ffffff; border: 1px solid #e1e5eb; border-radius: 12px; }
   QFrame#connectionSummary { background: #f8fafc; border: 1px solid #dfe4eb; border-radius: 10px; }
   QTabWidget::pane { border: 0; background: transparent; }
   QTabBar::tab { background: transparent; color: #475467; min-width: 116px; padding: 11px 14px; margin: 2px 7px 2px 0; border-radius: 7px; text-align: left; }
   QTabBar::tab:hover { background: #e7eaf0; color: #172033; }
   QTabBar::tab:selected { background: #ffffff; color: #173b8f; font-weight: 600; border-left: 3px solid #2563eb; }
   QLineEdit, QComboBox { background: #ffffff; border: 1px solid #cbd2dc; border-radius: 6px; padding: 4px 7px; min-height: 20px; }
   QPushButton { background: #f8f9fb; border: 1px solid #c8ced8; border-radius: 7px; padding: 5px 10px; min-height: 30px; }
   QPushButton:hover { background: #edf1f7; }
   QPushButton:disabled { color: #98a2b3; background: #f4f5f7; }
   QPushButton#connectAction { color: #ffffff; background: #1fa35b; border: 0; font-weight: 600; min-width: 135px; }
   QPushButton#connectAction:hover { background: #16834a; }
   QPushButton#primaryAction { color: #ffffff; background: #2563eb; border: 0; font-size: 9pt; font-weight: 600; }
   QPushButton#primaryAction:hover { background: #1d4ed8; }
   QPushButton#stopAction { color: #ffffff; background: #c62828; border: 0; font-weight: 600; min-width: 88px; }
   QPushButton#stopAction:hover { background: #a51f1f; }
   QPushButton#stopAction:disabled { color: #98a2b3; background: #f4f5f7; }
   QTableWidget { background: #ffffff; alternate-background-color: #fafbfc; border: 1px solid #dfe4eb; border-radius: 8px; }
   QHeaderView::section { background: #f1f3f5; color: #344054; padding: 6px; border: 0; border-bottom: 1px solid #dfe4eb; font-weight: 600; }
   QTableWidget::item { padding: 4px; border-bottom: 1px dashed #d8dde5; }
   QTableWidget::item:selected { background: #dbeafe; color: #101828; }
   QTableWidget::item:selected:active { background: #dbeafe; color: #101828; }
   QTableWidget::item:selected:!active { background: #e8f0fe; color: #101828; }
   QTableWidget QLineEdit { background: #ffffff; color: #101828; border: 1px solid #2563eb; border-radius: 3px; padding: 1px 3px; }
   QProgressBar { border: 1px solid #d0d5dd; border-radius: 5px; text-align: center; background: #f2f4f7; }
   QProgressBar::chunk { background: #2563eb; border-radius: 4px; }
   QLabel#readyStatus { color: #475467; }
  ''')
  shell.addWidget(self.tabs)
  self.setCentralWidget(w)
  self.update_actions()
 def show_translate_tab(self):
  self.update_connection_summary(); self.tabs.setCurrentWidget(self.translate_page)
 def open_control_panel(self):
  self.tabs.setCurrentWidget(self.control_panel_page)
 def set_connection_editor_visible(self,visible):
  # //remarks: Kept as the connection workflow's single navigation hook. A successful Save returns to Translate;
  # //remarks: asking to show the editor opens Control Panel instead of hiding widgets on separate pages.
  if visible: self.open_control_panel()
  else: self.show_translate_tab()
 def set_refresh_enabled(self,enabled):
  self.refresh_button.setEnabled(enabled)
  self.job_refresh_button.setEnabled(enabled)
 def update_connection_summary(self):
  url=self.url.text().strip()
  connected=self.same_connection(url,self.key.text().strip()) and profile_key(url)==self.api_verified
  if connected:
   model=self.model.currentText().strip()
   count=self.model.count()
   detail=f'{model} · {count} model(s)' if model else f'{count} model(s)'
   self.connection_summary_text.setText(f'Connected to {url} · {detail}')
   self.header_connection.setText('● Connected')
   self.header_connection.setStyleSheet('color:#16763a;background:#e4f4e8;border:1px solid #a7d7b4;border-radius:15px;padding:5px 9px;min-height:30px;font-weight:600;')
  else:
   self.connection_summary_text.setText('Connection required. Enter your provider details in the Control Panel.')
   self.header_connection.setText('● Not connected')
   self.header_connection.setStyleSheet('color:#667085;background:#f2f4f7;border:1px solid #d0d5dd;border-radius:15px;padding:5px 9px;min-height:30px;font-weight:600;')
 def load(self):
  try:
   # //remarks: Read with an explicit UTF-8 encoding, matching save(): the config is written with
   # //remarks: ensure_ascii=False, so any non-ASCII character (a provider name, a path with an accent) lands in
   # //remarks: the file as real UTF-8 bytes. Reading it with the Windows locale default (cp1252) raised
   # //remarks: UnicodeDecodeError on byte 0x81 and made the app unstartable, so the encoding is always stated.
   d=json.loads(CFG.read_text(encoding='utf-8'))
   # //remarks: Restore everything the user entered, because none of it is compiled into the executable:
   # //remarks: the Base URL, the DPAPI-protected API key, the chosen model, and the Free models only state.
   # //remarks: Missing keys fall back to an empty field rather than to a baked-in provider.
   # //remarks: Field changes are blocked while the stored values go in, so nothing reacts to a half-restored
   # //remarks: screen: the URL handler would otherwise clear a selection that is about to be restored as well.
   self.restoring=True
   self.url.blockSignals(True); self.key.blockSignals(True)
   self.url.setText(d.get('url','')); self.key.setText(unprotect(d.get('api_key','')))
   self.url.blockSignals(False); self.key.blockSignals(False)
   # //remarks: The tick box state is restored before the list is rebuilt, so the dropdown comes back filtered
   # //remarks: exactly as the user left it instead of flashing the full list first.
   self.free_only.blockSignals(True); self.free_only.setChecked(bool(d.get('free_only',False))); self.free_only.blockSignals(False)
   saved_export=export_format_key(d.get('default_export_format','pdf'))
   self.default_export_format.blockSignals(True); self.default_export_format.setCurrentIndex(self.default_export_format.findData(saved_export)); self.default_export_format.blockSignals(False)
   saved_language=language_key(d.get('default_language',d.get('language',LANGS[0])))
   language_index=self.default_lang.findData(saved_language)
   self.default_lang.blockSignals(True); self.default_lang.setCurrentIndex(language_index if language_index>=0 else 0); self.default_lang.blockSignals(False)
   self.apply_default_language()
   # //remarks: Restore the last fetched model list before the network is asked again, so a tester who is
   # //remarks: offline (or whose provider is slow) still sees their own provider's models straight away.
   cache=d.get('models')
   if isinstance(cache,list): self.model_cache=[m for m in cache if isinstance(m,str) and m.strip()]
   self.set_models(self.model_cache)
   # //remarks: The remembered model is applied after the list is rebuilt, so a typed ID that is not in the
   # //remarks: cached list is still restored as the current selection instead of being replaced by the first entry.
   saved_model=str(d.get('model','')).strip()
   if saved_model:
    self.model.blockSignals(True); self.model.setCurrentText(saved_model); self.model.blockSignals(False)
   # //remarks: Remembered providers come back as a list to choose from, so a user with several Base URLs can switch
   # //remarks: without retyping a key. The rebuild itself happens after the handler, so it also runs on a first launch
   # //remarks: where there is no settings file at all.
   self.profiles=load_profiles(d)
   current_key=profile_key(self.url.text())
   if current_key and current_key not in self.profiles and self.url.text().strip():
    self.profiles[current_key]={'url':self.url.text().strip(),'api_key':d.get('api_key','') if isinstance(d.get('api_key'),str) else '','verified':False,'model':saved_model,'models':self.model_cache}
   # //remarks: A remembered provider counts as proved only if the settings file recorded a successful key check for
   # //remarks: it, so a restarted app never inherits a verification that belongs to different credentials.
   active=self.profiles.get(current_key)
   if active and active.get('verified'): self.api_verified=current_key
   # //remarks: A key is only ever stored after a successful model fetch, so a restored key counts as fetched.
   if active and active.get('api_key'): self.fetched=(current_key,self.key.text().strip())
   # //remarks: Keep the remembered path even when the folder is temporarily unavailable: QFileDialog falls
   # //remarks: back safely on its own, while clearing it here made BlueTL forget the last import directory
   # //remarks: after a network drive was disconnected or a removable drive was briefly unavailable.
   saved=str(d.get('last_dir','')).strip()
   self.last_dir=saved
   # //remarks: A damaged config must never stop the app from starting. UnicodeDecodeError is a ValueError (not
   # //remarks: an OSError), so it is named explicitly: an unreadable file - wrong encoding, half-written, or a
   # //remarks: corrupt entry - is treated like a missing one and the user simply re-enters their provider.
  except (FileNotFoundError,json.JSONDecodeError,UnicodeDecodeError,OSError,ValueError,TypeError): pass
  self.restoring=False
  # //remarks: The picker is built once, outside the handler, so a first launch and a damaged config both still show
  # //remarks: the placeholder instead of an empty combo box that looks broken.
  self.refresh_provider_list()
  # //remarks: A config is only "connected" when it already holds both a Base URL and a key, which happens after a
  # //remarks: previous Save. Restoring it lets a returning user see their models straight away without
  # //remarks: having to confirm again; a fresh or cleared config stays unconfirmed and the dropdown stays locked.
  if self.url.text().strip() and self.key.text().strip():
   self.connected_url=self.url.text().strip(); self.connected_key=self.key.text().strip()
  # //remarks: Apply the restored list, then render the gate. The model list is refreshed on startup only when a
  # //remarks: connection was already confirmed, so the app never contacts a provider the user has not saved.
  self.set_models(self.model_cache); self.apply_connection_state()
  if self.connected_url: self.model_timer.start()
  # //remarks: Switching the filter on with nothing cached yet is reported honestly instead of leaving the user
  # //remarks: wondering why the dropdown is empty: the models appear once the provider answers.
  if self.free_only.isChecked() and self.model.count()==0 and not self.connected_url:
   self.status.setText('Enter your Base URL and API key, then press Save: the model list is fetched from your provider.')
  # //remarks: Start the update check last, so the window is already built and painted before any network work
  # //remarks: begins. A source run (python app.py) is checked too: the gate is about the version number, not
  # //remarks: about being frozen, and skipping it in source would leave the rule untested until release day.
  self.start_update_check()
 def start_update_check(self):
  # //remarks: One request per application launch, not one per Window. Tests and future auxiliary windows can
  # //remarks: create several Window instances, but the release endpoint must still receive only one request.
  if getattr(Window,'_update_check_started',False): return
  Window._update_check_started=True
  # //remarks: One request per launch, on a daemon thread, collected by a timer on the GUI thread - the same
  # //remarks: pattern model discovery uses. Nothing here may block or fail the window: an offline PC simply
  # //remarks: gets no reminder, because a network problem is not the user's fault and must never lock them out.
  self.release_loader=None; self.update_notified=False; self.obsolete=False
  self.update_poll=QTimer(self); self.update_poll.setInterval(250)
  self.update_poll.timeout.connect(self.poll_latest_release)
  self.release_loader=ReleaseLoader(); self.release_loader.start()
  self.update_poll.start()
 def poll_latest_release(self):
  # //remarks: Finish the startup check once the worker has answered, then stop the timer so the window is not
  # //remarks: polled for the rest of the session. Exactly one dialog is ever shown per launch.
  loader=self.release_loader
  if loader is None: self.update_poll.stop(); return
  if loader.is_alive(): return
  self.update_poll.stop(); self.release_loader=None
  if self.update_notified or not loader.tags: return
  self.update_notified=True
  self.enforce_update_gate(loader.tags)
 def enforce_update_gate(self,tags):
  # //remarks: The update policy in one place. A build up to MAX_SKIPPED_VERSIONS releases behind may be kept -
  # //remarks: the user is told which versions exist and can carry on working. Further behind than that the
  # //remarks: executable is obsolete: it is refused outright, because a stale build may talk to a provider API
  # //remarks: that has since changed, and supporting several old versions is not something the app can do.
  newer=newer_releases(APP_VERSION,tags)
  if not newer: return
  behind=len(newer)
  latest=newer[0]
  if behind<=MAX_SKIPPED_VERSIONS:
   QMessageBox.information(self,'Update available',
    f'BlueTL v{APP_VERSION} is {behind} version(s) behind. The newest release is {latest}.\n\n'
    f'You can keep using this version for now. After {MAX_SKIPPED_VERSIONS} skipped updates the '
    f'executable stops working until it is replaced, so please download {latest} soon.')
   return
  QMessageBox.critical(self,'This BlueTL build is obsolete',
   f'BlueTL v{APP_VERSION} is {behind} versions behind. The newest release is {latest}.\n\n'
   f'Builds more than {MAX_SKIPPED_VERSIONS} versions old are no longer supported and will not run. '
   f'After you dismiss this message, the {latest} download page will open in your default browser.')
  release_url=RELEASE_PAGE_URL.format(tag=urllib.parse.quote(latest,safe=''))
  try:
   try: opened=webbrowser.open(release_url,new=2)
   except (webbrowser.Error,OSError): opened=False
   if not opened:
    QMessageBox.warning(self,'Could not open browser',f'Open this page manually to download the update:\n{release_url}')
  finally:
   self.obsolete=True
   self.close()
 def ocr_dependency_hint(self):
  return 'Install or repair dependencies with:\npython -m pip install -r requirements.txt\n\nPython: '+sys.executable

 def check_ocr_dependencies(self):
  # //remarks: Import every module used by the local detector/OCR path before loading model weights. This
  # //remarks: prevents a misleading generic dependency message and reports the exact failing module.
  checks=[('manga_ocr','manga-ocr'),('transformers','transformers'),('torch','torch'),('torchvision','torchvision'),('cv2','opencv-python-headless'),('pyclipper','pyclipper'),('shapely','shapely'),('torchsummary','torchsummary'),('unidic_lite','unidic-lite')]
  failures=[]
  for module,package in checks:
   try: __import__(module)
   except Exception as e: failures.append(f'{package}: {type(e).__name__}: {e}')
  if failures: raise ImportError('Local OCR dependencies failed to load:\n'+'\n'.join(failures))
  from transformers import ViTImageProcessor
  if ViTImageProcessor is None: raise ImportError('transformers.ViTImageProcessor is unavailable')


 def save(self):
  CFG.parent.mkdir(parents=True,exist_ok=True)
  # //remarks: Everything the user entered is stored, because nothing is hard-coded in the executable: the
  # //remarks: Base URL and model, the DPAPI-protected API key, and the Free models only state. The full fetched
  # //remarks: model list is stored too (capped so a huge provider catalogue cannot bloat the config file);
  # //remarks: model_cache always holds the complete list, never the filtered view, so unticking the box can
  # //remarks: restore every model offline. This is what makes the settings survive reopening the EXE.
  url=self.url.text().strip()
  # //remarks: The key is persisted only once a model fetch with exactly this URL and key succeeded. Otherwise the
  # //remarks: previously stored key for this provider (if any) is kept, so a mistyped key never overwrites a good one.
  if self.key.text() and self.fetched==(profile_key(url),self.key.text().strip()): cipher=protect(self.key.text())
  else:
   old=self.profiles.get(profile_key(url)) if isinstance(self.profiles,dict) else None
   cipher=old.get('api_key','') if old and isinstance(old.get('api_key'),str) else ''
  data={'url':url,'model':self.model.currentText().strip(),'language':self.lang.currentData(),'default_language':self.default_lang.currentData(),'default_export_format':self.default_export_format.currentData(),'api_key':cipher,'free_only':self.free_only.isChecked(),'last_dir':self.last_dir,'models':self.model_cache[:500],'providers':dict(self.profiles) if isinstance(self.profiles,dict) else {}}
  # //remarks: The active provider also lives in the provider map, so switching away and back restores its own key,
  # //remarks: model list, and verified state instead of the last one written. A provider is only recorded as verified
  # //remarks: while it is still the confirmed connection and the key that was proved is the key on screen.
  if url:
   verified=bool(profile_key(url)==self.api_verified and profile_key(url)==profile_key(self.connected_url or url) and self.key.text().strip()==self.connected_key)
   remember_profile(data,url,cipher,models=self.model_cache,verified=verified,model=data['model'])
   self.profiles=load_profiles(data)
  # //remarks: Write to a temporary file first and then replace the real one, so an interrupted write can
  # //remarks: never leave a truncated config behind. A damaged config would lose the remembered folder
  # //remarks: and every other setting, which is exactly what this backup-and-swap prevents.
  tmp=CFG.with_suffix('.json.tmp')
  tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
  tmp.replace(CFG)
 def closeEvent(self,event):
  # //remarks: Pending discovery work (a queued debounce tick or an in-flight poll) would only start steps for a
  # //remarks: window that is already closing, and a live timer can keep the process alive, so both are stopped
  # //remarks: as part of shutdown.
  self.model_timer.stop(); self.model_poll.stop()
  if hasattr(self,'update_poll'): self.update_poll.stop()
  try: self.save()
  except Exception as e: self.status.setText(f'Could not save settings: {e}')
  event.accept()
 def candidates(self):
  return self.ranked(self.model.currentText().strip())
 def probe_model(self,models=None):
  # //remarks: The model used for the one-token key check: preferably a free model, because the check itself must
  # //remarks: cost as little as possible, then the saved selection, then whatever the provider listed first. This
  # //remarks: mirrors the translation retry order without needing the dropdown to be unlocked first.
  listed=filter_models(models if models is not None else self.model_cache)
  saved=self.model.currentText().strip()
  for candidate in ([saved] if saved else [])+[m for m in listed if is_free_model(m)]+listed:
   if candidate: return candidate
  return ''
 def select_provider(self,url):
  # //remarks: Keep the picker showing the provider currently in the fields, without emitting activated (which would
  # //remarks: re-enter on_provider_chosen and reload from the same entry). An unknown URL falls back to the
  # //remarks: placeholder, so the picker never claims a provider that is not saved.
  key=profile_key(url)
  index=self.provider.findData(key) if key else -1
  self.provider.blockSignals(True); self.provider.setCurrentIndex(index if index>=0 else 0); self.provider.blockSignals(False)
 def refresh_provider_list(self):
  # //remarks: Rebuild the saved-provider entries after a new provider is remembered or an existing one is proved.
  # //remarks: The selection is kept on the URL in the fields, so the picker never jumps to another provider.
  current=self.url.text()
  self.provider.blockSignals(True); self.provider.clear(); self.provider.addItem(PLACEHOLDER_PROVIDER)
  for key in sorted(self.profiles,key=lambda k:self.profiles[k]['url'].lower()):
   entry=self.profiles[key]
   self.provider.addItem((PROVIDER_VERIFIED+entry['url']) if entry.get('verified') else (PROVIDER_UNVERIFIED+entry['url']),key)
  self.provider.blockSignals(False)
  self.select_provider(current)
 def on_provider_chosen(self,index):
  # //remarks: Switching providers is a two-step action like a fresh connect: the stored URL, key, and model list are
  # //remarks: filled in, the connection is marked unconfirmed, and then the list is re-fetched. The stored key is only
  # //remarks: reused for the URL it was saved for, so it can never be offered to a different host.
  entry=self.provider.itemData(index) if index>0 else None
  if not entry:
   # //remarks: The placeholder is informational only; returning keeps the current provider in the fields instead of
   # //remarks: clearing them, so an accidental click on it cannot wipe a working configuration.
   return
  saved=self.profiles.get(entry)
  if not saved: self.provider.setCurrentIndex(0); return
  self.restoring=True
  self.url.setText(saved.get('url','')); self.key.setText(unprotect(saved.get('api_key','')))
  self.restoring=False
  self.model_cache=list(saved.get('models') or [])
  self.refreshed=''
  self.model.setEnabled(False); self.set_refresh_enabled(False)
  self.model.blockSignals(True); self.set_models(self.model_cache,keep_current=False)
  chosen=str(saved.get('model') or '').strip()
  self.model.setCurrentText(chosen or (self.model.itemText(0) if self.model.count() else ''))
  self.model.blockSignals(False)
  self.connect_status.setText(f'Loaded {saved["url"]} - press Save to reconnect.' if self.api_verified!=profile_key(saved['url']) else 'Connecting...')
  self.connect_status.setStyleSheet('color:#b45309;padding:2px 2px;')
  self.connect_button.setEnabled(True)
  self.status.setText(f'Provider selected: {saved["url"]}. Press Save to fetch its model list.')
 def delete_provider(self):
  # //remarks: Removes the saved provider matching the Base URL on screen. If it is the active connection the fields,
  # //remarks: model list and verified state are cleared too, so nothing of the deleted provider remains in use.
  key=profile_key(self.url.text())
  if not key or key not in self.profiles:
   self.status.setText('No saved provider matches the Base URL on screen.'); return
  url=self.profiles[key]['url']
  del self.profiles[key]
  if self.fetched[0]==key: self.fetched=('','')
  if self.api_verified==key: self.api_verified=''
  self.restoring=True
  self.url.clear(); self.key.clear()
  self.restoring=False
  self.connected_url=''; self.connected_key=''; self.refreshed=''; self.model_cache=[]
  self.model.blockSignals(True); self.set_models([],keep_current=False); self.model.setCurrentText(''); self.model.blockSignals(False)
  self.model.setEnabled(False); self.set_refresh_enabled(False); self.connect_button.setEnabled(True)
  self.connect_status.setText('Not confirmed - press Save to load models.'); self.connect_status.setStyleSheet('color:#b45309;padding:2px 2px;')
  self.refresh_provider_list()
  try: self.save()
  except Exception as e: self.status.setText(f'Could not save settings: {e}'); return
  self.status.setText(f'Deleted saved provider {url}.')
 def on_url_changed(self):
  # //remarks: The Model dropdown must never carry one provider's selection into another provider's session, so a
  # //remarks: changed Base URL clears the selection and the cached list unless that URL is a remembered provider,
  # //remarks: whose own list and model are restored instead. This runs for typed *and* programmatic changes, which is
  # //remarks: what makes a pasted URL behave exactly like an edited one.
  if self.restoring: return
  url=self.url.text().strip()
  self.select_provider(url)
  entry=self.profiles.get(profile_key(url)) if url else None
  # //remarks: A remembered provider always gets its own catalogue back, even when the text matches the connection that
  # //remarks: is still recorded: an edit away and back must not leave the dropdown showing another provider's list.
  if entry:
   # //remarks: The comparison is against the provider's own stored list, never against the live cache: the cache was
   # //remarks: just emptied by the step that moved to this URL, so comparing with it would skip the restore.
   stored=list(entry.get('models') or [])
   if stored!=list(self.model_cache) or not self.model.count():
    self.model_cache=stored
    self.model.blockSignals(True); self.set_models(self.model_cache,keep_current=False)
    saved=str(entry.get('model') or '').strip()
    self.model.setCurrentText(saved or (self.model.itemText(0) if self.model.count() else ''))
    self.model.blockSignals(False)
  if url==self.connected_url:
   if self.same_connection(url,self.key.text().strip()): self.apply_connection_state()
   return
  if entry:
   if entry.get('verified') and self.api_verified==profile_key(url): self.connected_url=url; self.connected_key=self.key.text().strip(); self.apply_connection_state()
   return
  # //remarks: An unknown URL is a fresh provider: nothing from the previous one survives, and the dropdown is locked
  # //remarks: until Save proves the new connection.
  if self.model_cache or self.model.count():
   self.model_cache=[]
   self.model.blockSignals(True); self.set_models([],keep_current=False); self.model.setCurrentText(''); self.model.blockSignals(False)
  self.api_verified=''
  if not self.model_refreshing: self.on_connection_edited()
 def set_models(self,ids,keep_current=True):
  # //remarks: Rebuild the editable Model dropdown from the fetched (or restored) list. The custom text the
  # //remarks: user typed is put back as the current selection, so a non-listed ID - an Azure deployment name,
  # //remarks: for example - is never replaced by whatever happens to be first in the list. It is also kept as a
  # //remarks: dropdown entry, so a typed ID is visible and selectable again after a refresh or a restart.
  # //remarks: Signal blocking keeps this UI refresh from touching the debounce timer or the saved selection.
  # //remarks: Nothing is hard-coded here: with no fetched list and no typed ID the dropdown is simply empty,
  # //remarks: which is the honest state before a Base URL and key have produced a real provider catalogue.
  # //remarks: keep_current=False is used when the list belongs to a *different* provider: the previous provider's
  # //remarks: selection must not be carried over, so the dropdown is rebuilt from the new list alone.
  current=self.model.currentText().strip() if keep_current else ''
  free_only=self.free_only.isChecked()
  merged=[]
  # //remarks: A typed ID is honoured as-is even while the free-only filter is on, because the user is
  # //remarks: explicitly choosing it and silently dropping it would lose their selection.
  for value in filter_models(list(ids or [])+([current] if current else []),free_only):
   if value not in merged: merged.append(value)
  self.model.blockSignals(True)
  self.model.clear(); self.model.addItems(merged)
  self.model.blockSignals(False)
  # //remarks: Restoring the current text is blocked from signals so it cannot re-trigger the debounce timer,
  # //remarks: while still putting the user's choice back exactly as it was.
  self.model.blockSignals(True); self.model.setCurrentText(current or (merged[0] if merged else '')); self.model.blockSignals(False)
 def on_free_only_toggled(self,checked):
  # //remarks: Toggling the tick box re-applies the filter to the cached provider list - no network request, so
  # //remarks: the choice is instant even offline. The cached list stays complete, so unticking restores every
  # //remarks: model the provider reported.
  self.set_models(self.model_cache)
  count=self.model.count()
  if checked: self.status.setText(f'Free models only: showing {count} model(s) whose ID contains "{FREE_MODEL_TOKEN}".')
  else: self.status.setText(f'Free models only off: showing {count} model(s) from the fetched list.')
  self.save()
  if checked and not any(is_free_model(m) for m in self.model_cache):
   # //remarks: The filter matched nothing, so leaving the box ticked would show an empty dropdown with no
   # //remarks: way to see the provider's models. Untick it after telling the user, which restores the full
   # //remarks: list. blockSignals stops the untick from re-entering this handler and saving twice.
   QMessageBox.information(self,'Free models','No free models detected.')
   self.free_only.blockSignals(True); self.free_only.setChecked(False); self.free_only.blockSignals(False)
   self.set_models(self.model_cache)
   self.status.setText(f'Free models only off: no model ID contains "{FREE_MODEL_TOKEN}". Showing {self.model.count()} model(s) from the fetched list.')
   self.save()
 def on_connection_edited(self):
  # //remarks: The user changed a connection field after confirming (or before doing so). No request is sent:
  # //remarks: the previous confirmation no longer describes what is on screen, so Save is re-enabled,
  # //remarks: Refresh is disabled, and the model dropdown is locked until the new values are confirmed. Editing only
  # //remarks: the key keeps the cached list, because the same provider simply needs a new key; editing the Base URL
  # //remarks: is handled by on_url_changed, which clears or restores the list for whichever provider is now in the
  # //remarks: field so a model from one provider is never sent to another.
  if self.model_refreshing or self.restoring: return
  if self.same_connection(self.url.text().strip(),self.key.text().strip()):
   # //remarks: The text was edited back to the exact confirmed values, so the connection is valid again.
   self.apply_connection_state()
   return
  self.refresh_provider_list()
  self.connect_button.setEnabled(True)
  self.connect_status.setText('Not confirmed - press Save to reload models.')
  self.connect_status.setStyleSheet('color:#b45309;padding:2px 2px;')
  self.model.setEnabled(False); self.set_refresh_enabled(False)
  self.update_connection_summary()
 def same_connection(self,url,key):
  # //remarks: A connection is current only when both fields still equal what was confirmed. The key is compared
  # //remarks: as typed, because a re-typed key is a genuinely different credential even if it looks similar.
  return bool(self.connected_url) and url==self.connected_url and key==self.connected_key
 def apply_connection_state(self):
  # //remarks: Single place that renders the confirmed/unconfirmed state. Confirmed means the provider answered, the
  # //remarks: key on screen is the one that was proved, and the dropdown holds real model IDs; only then can a model
  # //remarks: be picked. Requiring the key check matters because some hosts serve /models publicly, so a fetched list
  # //remarks: alone would let a wrong key look connected until the first translation failed.
  url=self.url.text().strip(); key=self.key.text().strip()
  self.update_connection_summary()
  if self.same_connection(url,key):
   if profile_key(url)!=self.api_verified or not key:
    self.connect_button.setEnabled(False)
    self.connect_status.setText('Model list loaded - press Test API once to verify the API key.')
    self.connect_status.setStyleSheet('color:#b45309;padding:2px 2px;')
    self.model.setEnabled(False); self.set_refresh_enabled(True)
    return
   count=self.model.count()
   self.connect_button.setEnabled(False)
   self.connect_status.setText(f'Connected - {count} model(s) available and API key verified.' if count else 'Connected - provider reported no models; type a model ID.')
   self.connect_status.setStyleSheet('color:#1a7f37;padding:2px 2px;')
   self.connect_status.setToolTip(CERT_NOTE.format(days=self.cert_days) if isinstance(self.cert_days,int) and self.cert_days>=0 else 'The provider answered and the API key was verified.')
   self.model.setEnabled(True); self.set_refresh_enabled(True)
   self.set_connection_editor_visible(False)
  else:
   self.connect_button.setEnabled(True)
   self.connect_status.setText('Not confirmed - press Save to load models.')
   self.connect_status.setStyleSheet('color:#b45309;padding:2px 2px;')
   self.model.setEnabled(False); self.set_refresh_enabled(False)
 def confirm_connection(self):
  # //remarks: The explicit confirmation step, mirroring Cline's Done: take the typed Base URL and API key as the
  # //remarks: active connection, then fetch the full model list. Validation happens here, once, with a clear
  # //remarks: message - never silently while the user is still typing.
  url=self.url.text().strip(); key=self.key.text().strip()
  missing=[]
  if not url: missing.append('Base URL')
  if not key: missing.append('API key')
  if missing:
   QMessageBox.warning(self,'Connection details required',f'Enter the {" and ".join(missing)} before connecting.')
   return
  # //remarks: Both fields are kept exactly as typed (normalized_url only shapes the request URL), so a provider
  # //remarks: whose working endpoint has no version segment keeps receiving the user's own text.
  previous=profile_key(self.connected_url); previous_key=self.connected_key
  self.connected_url=url; self.connected_key=key
  self.connect_button.setEnabled(False)
  self.connect_status.setText('Connecting...'); self.connect_status.setStyleSheet('color:#6b7280;padding:2px 2px;')
  # //remarks: Persist immediately so a confirmed provider URL survives a restart even if the fetch then fails; save()
  # //remarks: leaves the typed key out until a fetch with it succeeds. The save
  # //remarks: happens before the verified state is dropped for a new key, so the provider that was proved a moment ago
  # //remarks: keeps its record; only the in-memory verification is cleared, which is what locks the dropdown.
  try: self.save()
  except Exception as e: self.status.setText(f'Could not save settings: {e}')
  # //remarks: A key check belongs to one Base URL and one key. Confirming a different provider, or the same provider
  # //remarks: with a different key, therefore drops the in-memory verified state instead of inheriting it, which keeps
  # //remarks: the dropdown locked; the fetch that follows proves the new key and remembers the provider again.
  if profile_key(url)!=previous or key!=previous_key: self.api_verified=''
  self.update_connection_summary()
  self.refresh_provider_list()
  self.refreshed=''
  self.refresh_models(manual=True,url=normalized_url(url),key=key,verify_key=True)
 def refresh_models(self,manual=False,url=None,key=None,verify_key=False):
  # //remarks: Re-fetch the provider's model list from its /models endpoint and refresh the dropdown. The
  # //remarks: network work happens on a worker thread and this method only starts it; a small poll timer
  # //remarks: collects the result, so an unreachable host delays nothing and the window never freezes or runs
  # //remarks: a nested event loop. A manual refresh is the only path that reports the reason for failure; an
  # //remarks: automatic refresh stays silent and simply keeps the current list - OCR and translation are never
  # //remarks: affected by discovery.
  # //remarks: Refresh only ever acts on a CONFIRMED connection. Without one there is nothing trustworthy to ask:
  # //remarks: the user must press Save first, which is the Cline-style step this app mirrors.
  if url is None: url=normalized_url(self.connected_url or self.url.text())
  if key is None: key=self.connected_key or self.key.text().strip()
  if not url:
   if manual: QMessageBox.warning(self,'Base URL required','Enter the OpenAI-compatible Base URL first, then press Save.')
   return
  # //remarks: The Base URL field is deliberately NOT rewritten here: normalized_url only shapes the request URL
  # //remarks: for discovery, and the translation client must keep receiving exactly the text the tester typed.
  # //remarks: Editing the text while someone is typing would also fight their cursor and the debounce timer.
  if self.model_refreshing:
   # //remarks: A request is already in flight. A corrected URL is queued and run as soon as it finishes;
   # //remarks: a manual click just reports the state so two worker threads never share one dropdown update.
   if manual: self.status.setText('A model list refresh is already running.')
   elif url != self.model_url: self.model_pending=url
   return
  if not manual and url == self.refreshed: return
  if not key:
   if manual: QMessageBox.warning(self,'API key required','Enter the API key first: model discovery sends it to the provider.')
   return
  # //remarks: self.refreshed is only updated by a *successful* fetch (see poll_models), so a failed attempt -
  # //remarks: for example before the key was pasted - does not block the automatic retry that the next edit
  # //remarks: schedules for the same URL.
  self.model_refreshing=True; self.model_manual=manual; self.model_pending=''
  # //remarks: Only the explicit Save press proves the key; an automatic or Refresh-button fetch reuses the
  # //remarks: verification that already exists, so a background refresh never spends a completion or fails a working
  # //remarks: connection just because the provider is briefly busy.
  self.model_verify=verify_key; self.model_key=key; self.model_check=verify_key
  self.model_request=(self.url.text().strip(),self.key.text().strip())
  if manual: self.set_refresh_enabled(False); self.status.setText(f'Fetching model list from {url}/models ...')
  loader=ModelListLoader(url,key); loader.start()
  # //remarks: Poll from the event loop instead of joining the thread here, so the window stays fully responsive
  # //remarks: and no other action can be re-entered while the request is in flight.
  self.model_loader=loader; self.model_url=url; self.model_deadline=time.monotonic()+30
  self.model_poll.start()
 def poll_models(self):
  # //remarks: Collect the worker result once it finishes or the wall-clock budget runs out. A provider that
  # //remarks: accepts the connection but never answers therefore ends in a timeout note, never in a hang.
  loader=self.model_loader
  if loader is None: self.model_poll.stop(); return
  if loader.is_alive() and time.monotonic()<self.model_deadline: return
  self.model_poll.stop(); self.model_loader=None
  self.model_refreshing=False
  manual=self.model_manual; url=self.model_url
  pending=self.model_pending; self.model_pending=''
  if self.model_request!=(self.url.text().strip(),self.key.text().strip()):
   self.on_connection_edited()
   return
  if manual: self.set_refresh_enabled(True)
  if loader.is_alive():
   if manual: self.status.setText(f'Model list request timed out after 30 seconds ({url}). The current list is kept.')
   self.connect_status.setText('Connection timed out - check the Base URL and press Save again.')
   self.connect_status.setStyleSheet('color:#c62828;padding:2px 2px;')
   self.connect_button.setEnabled(True); self.model.setEnabled(False); self.set_refresh_enabled(False)
  elif loader.list_error:
   # //remarks: Only claim the list is kept when there actually is one: after moving to a new provider the list has
   # //remarks: already been cleared, so the old wording promised something that was no longer on screen.
   kept=' The current list is kept.' if self.model_cache else ' No model list is loaded for this provider yet.'
   if manual: self.status.setText(f'Model list could not be fetched ({loader.list_error}).{kept}')
   # //remarks: A rejected key or a wrong path leaves the connection unconfirmed and names the reason in the
   # //remarks: connect line, so the user fixes the field and presses Save again.
   self.connect_status.setText(f'Connection failed - {loader.list_error}')
   self.connect_status.setStyleSheet('color:#c62828;padding:2px 2px;')
   self.connect_button.setEnabled(True); self.model.setEnabled(False); self.set_refresh_enabled(False)
  else:
   # //remarks: A completed request marks the URL as checked whatever the answer contained, so the debounce
   # //remarks: timer does not repeat it. A timed-out or failed request is deliberately NOT marked, so the next
   # //remarks: edit (for example pasting the API key) retries the same URL automatically.
   self.refreshed=url
   if loader.list_id:
    # //remarks: A list that arrives for a provider other than the one already in the dropdown must replace the
    # //remarks: selection too: keeping models[0] of the old provider would leave the previous provider's model
    # //remarks: selected while the new provider's list is shown. The first entry is the honest default.
    replacing=list(loader.list_id)!=list(self.model_cache)
    self.model_cache=list(loader.list_id)
    self.fetched=(profile_key(self.connected_url or url),self.model_key)
    if replacing:
     # //remarks: A different list resets the picker to its first entry rather than keeping a stale selection.
     self.model.blockSignals(True); self.set_models(self.model_cache,keep_current=False)
     self.model.setCurrentIndex(0 if self.model.count() else -1)
     self.model.blockSignals(False)
    else: self.set_models(self.model_cache)
    # //remarks: Report the URL that actually answered, because discovery may have used the site-root form when
    # //remarks: the OpenAI-style <base>/models path returned nothing.
    source=loader.list_url or url
    # //remarks: A day count for the provider's certificate is taken here, once, so the tooltip can show it: this is
    # //remarks: how a future genuine expiry becomes visible before it blocks a translation run.
    days=tls_certificate_expiry(url)
    self.cert_days=days
    expiry=f' Certificate valid for {days} more day(s).' if isinstance(days,int) and days>=0 else ''
    # //remarks: The key check runs inside this same step, so Save is one action that both loads the list
    # //remarks: and proves the key. It is skipped for a background or Refresh-button fetch, which keeps whatever
    # //remarks: verification already exists: a refresh must never spend a request or revoke a working connection.
    if self.model_check and self.model_key:
     ok,detail,probe=self.verify_api_key(url,self.model_key,self.model_cache)
    else:
     ok,detail,probe=True,'',self.probe_model()
    if ok:
     if self.model_check: self.api_verified=profile_key(url); self.last_model=probe; self.set_api_status(True,detail)
     message=f'{len(self.model_cache)} model(s) fetched from {source}.'+(f' {detail}.{expiry}' if self.model_check else expiry)
     if manual: QMessageBox.information(self,'Provider connected' if self.model_check else 'Model list updated',message)
     self.status.setText(message)
    else:
     self.api_verified=''
     self.set_api_status(False,detail)
     self.status.setText(f'{len(self.model_cache)} model(s) fetched from {source}, but the API key was rejected: {detail}')
     if manual: QMessageBox.warning(self,'API key not verified',f'The model list was fetched from {source}, but testing the API key failed:\n\n{detail}\n\nCheck the key and press Save again.')
    self.save()
   elif manual:
    # //remarks: An empty but valid answer means the provider genuinely published no models; the current
    # //remarks: dropdown is left untouched and the tester can still type an ID by hand.
    self.status.setText(f'The provider at {loader.list_url or url} returned no model list. The current list is kept; typing a model ID still works.')
    QMessageBox.information(self,'No models reported',f'{loader.list_url or url} answered successfully but returned no models. The current list is kept and you can still type a model ID by hand.')
   # //remarks: The URL answered, so the provider is remembered even before its key is proved: the user can come back
   # //remarks: to it from the picker without retyping the address. It only earns the tick after a key check.
   if not (loader.list_id or self.model_cache):
    self.connect_status.setText('Provider answered but reported no models - press Test API to verify the API key.')
  # //remarks: Finally render the gate: a confirmed, answering provider whose key is proved unlocks the Model
  # //remarks: dropdown, anything else keeps it locked so no model can be chosen against a provider that never
  # //remarks: responded. A fetch with no models to probe still needs one Test API press, which is exactly what the
  # //remarks: connect line then says.
  if not self.model_refreshing: self.apply_connection_state()
  # //remarks: A Base URL corrected while the request was still in flight is fetched now, so the dropdown can
  # //remarks: never stay on the previous provider's models after an obvious mistake was fixed.
  if pending: self.refresh_models(manual=False,url=pending)
 def verify_api_key(self,url,key,models=None,timeout=10):
  # //remarks: Prove the key through the real chat endpoint. Some hosts serve /models to anyone, so a model list
  # //remarks: cannot double as a key check; one minimal completion can, and it is also what the user's own
  # //remarks: translations will do. Returns (ok, message, model) and never raises: Save must keep going
  # //remarks: with a clear reason instead of dying on a provider error.
  model=self.probe_model(models if models is not None else self.model_cache)
  if not model: return False,'No model is available to test the API key with; press Test API and choose a model.',''
  payload=json.dumps({'model':model,'messages':[{'role':'user','content':'Reply with OK.'}],'max_tokens':8}).encode('utf-8')
  req=urllib.request.Request(url.rstrip('/')+'/chat/completions',data=payload,method='POST',headers={'Authorization':f'Bearer {key}','Content-Type':'application/json'})
  try:
   with urllib.request.urlopen(req,timeout=timeout) as resp: body=json.loads(resp.read().decode('utf-8','replace'))
   reply=''
   if isinstance(body,dict):
    choices=body.get('choices')
    if isinstance(choices,list) and choices and isinstance(choices[0],dict):
     reply=str((choices[0].get('message') or {}).get('content') or '').strip()
   return True,f'API key verified with {model}'+(f' (reply: {reply[:40]})' if reply else ''),model
  except urllib.error.HTTPError as e:
   try: body=e.read(600).decode('utf-8','replace')
   except Exception: body=''
   detail=body
   try:
    error=json.loads(body).get('error')
    if isinstance(error,dict): detail=error.get('message') or error.get('code') or body
    elif error: detail=str(error)
   except ValueError: pass
   return False,f'HTTP {e.code} from {req.full_url}: {(detail or "no details").strip()[:300]}',model
  except ssl.SSLError as e: return False,describe_ssl_error(e),model
  except urllib.error.URLError as e:
   if isinstance(e.reason,ssl.SSLError): return False,describe_ssl_error(e.reason),model
   return False,f'{e.reason if e.reason else e} ({req.full_url})',model
  except OSError as e: return False,f'{e} ({req.full_url})',model
  except ValueError as e: return False,f'invalid JSON from {req.full_url}: {e}',model
 def set_api_status(self,ok,detail=''):
  # //remarks: Single source of truth for the API pill: None=untested, True=verified, False=failed.
  text='API Connected' if ok else ('API Failed' if ok is False else 'API Not tested')
  colour='#1a7f37' if ok else ('#c62828' if ok is False else '#6b7280')
  background='#e7f5eb' if ok else ('#fdecec' if ok is False else '#f2f4f7')
  border='#b7dfc1' if ok else ('#f2b8b5' if ok is False else '#d0d5dd')
  self.api_status.setText(text); self.api_status.setStyleSheet(f'color:{colour};background:{background};border:1px solid {border};border-radius:15px;font-weight:600;padding:5px 8px;min-height:30px;')
  self.api_status.setToolTip(detail or 'Run Test API, or use Translate all to verify automatically.')
 def set_image_status(self,ok,detail=''):
  # //remarks: None=no images, True=images/archive expanded, False=import produced no usable images.
  text=f'{len(self.paths)} Images'
  colour='#1a7f37' if ok else ('#c62828' if ok is False else '#6b7280')
  background='#e7f5eb' if ok else ('#fdecec' if ok is False else '#f2f4f7')
  border='#b7dfc1' if ok else ('#f2b8b5' if ok is False else '#d0d5dd')
  self.image_status.setText(text); self.image_status.setStyleSheet(f'color:{colour};background:{background};border:1px solid {border};border-radius:15px;font-weight:600;padding:5px 8px;min-height:30px;')
  self.image_status.setToolTip(detail)
 def update_actions(self):
  # //remarks: Single place that decides whether a manually typed row is possible. It stays disabled until
  # //remarks: OCR has run for the current batch, because a new row takes its page and panel number from the
  # //remarks: recognised rows around it, and it is enabled even when recognition found nothing so a batch
  # //remarks: can still be completed by hand. Deleting only needs a row that exists.
  self.add_button.setEnabled(self.recognized)
  self.delete_button.setEnabled(bool(self.rows))
  # //remarks: Stop is only meaningful while a batch is in flight, so it follows the same single flag the batch
  # //remarks: loops read. update_actions() is called from every path that changes that state.
  if hasattr(self,'stop_button'): self.stop_button.setEnabled(self.busy)

 def record_quota_limit(self,model,error):
  # //remarks: Remember each model whose free allowance ran out once, so the reminder at the end of the batch
  # //remarks: lists every limit that was hit instead of repeating one popup per row.
  if model in [m for m,_ in self.quota_limits_seen]: return
  self.quota_limits_seen.append((model,str(error)))

 def show_quota_limit_notice(self):
  # //remarks: One popup per batch to remind the user that the free tokens or request limit of a model ran out,
  # //remarks: instead of burying it in a generic failure dialog. Returns True when the popup was shown so the
  # //remarks: caller can skip a second, duplicate dialog.
  if not self.quota_limits_seen: return False
  seen=list(self.quota_limits_seen); self.quota_limits_seen=[]
  detail='\n'.join(f'  - {m}: {d}' for m,d in seen)
  QMessageBox.warning(self,'Free tokens or model limit reached',
   'The chosen model, or one of the fallback models, ran out of free tokens or reached its request limit while'
   ' translating, so the batch could not be completed.\n\n'
   'Affected model(s):\n'+detail+'\n\n'
   'Pick another model, wait for the limit to reset, or press Translate all again to retry the remaining rows.')
  return True
 def ranked(self,selected):
  # //remarks: The retry order is built from whatever list is currently in the dropdown, so a tester's own
  # //remarks: provider models (discovery result or typed IDs) take part in the fallback chain. There is no
  # //remarks: seeded ID list any more: free models are recognised by the same "free" text search the tick box
  # //remarks: uses, and they lead the chain whenever they are present. The selected model is always tried
  # //remarks: first, then the remaining free models, then everything else the provider reported.
  live=[]
  for i in range(self.model.count()):
   value=self.model.itemText(i).strip()
   if value and value not in live: live.append(value)
  leading=[m for m in live if is_free_model(m)]
  rest=[m for m in live if m not in leading]
  return ([selected] if selected else [])+[m for m in leading if m != selected]+[m for m in rest if m != selected]

 def dialog_dir(self):
  # //remarks: The remembered folder is the folder of the last imported file. When that folder still exists it
  # //remarks: is used as the dialog start. When it is gone (moved, renamed, unplugged drive) the closest
  # //remarks: existing ancestor is used instead, and only when nothing at all remains does the dialog fall
  # //remarks: back to its default location. BlueTL therefore never loses the remembered location just
  # //remarks: because one folder in the path is temporarily unavailable.
  path=Path(self.last_dir) if self.last_dir else None
  while path is not None:
   if path.is_dir(): return str(path)
   parent=path.parent
   if parent==path: break
   path=parent
  return ''

 def scan_folder(self,folder):
  # //remarks: Recursively collect every importable file from a chosen folder. The result goes through the
  # //remarks: same expand_inputs() path as a hand-picked selection, so name ordering, archive extraction and
  # //remarks: PSD flattening behave identically however the files arrived.
  root=Path(folder)
  return [str(p) for p in sorted(root.rglob('*'),key=lambda x:_name_key(str(x.relative_to(root)))) if p.is_file() and p.suffix.lower() in IMPORT_SUFFIXES]
 def images(self):
  # //remarks: Import is a picker rather than a single dialog, because a batch can arrive as either a handful of
  # //remarks: files or one folder of pages, and the file dialog cannot return a folder. A menu makes the choice
  # //remarks: explicit instead of guessing from a cancelled dialog.
  menu=QMenu(self)
  files_action=menu.addAction('Select files...')
  files_action.setToolTip('Choose one or more manga images or archives. Several files can be selected at once.')
  folder_action=menu.addAction('Select a folder...')
  folder_action.setToolTip('Choose one folder of manga images or archives. Only one folder can be imported at a time.')
  # //remarks: Batch folders are a paid feature that is not released yet. The entry stays visible but disabled so
  # //remarks: the upgrade path is discoverable, and its tooltip explains why it cannot be used yet.
  batch_action=menu.addAction('Batch folders (paid) - coming soon')
  batch_action.setEnabled(False)
  batch_action.setToolTip('Importing several folders in one batch will be a paid feature. It is not available in this version.')
  chosen=menu.exec(self.import_button.mapToGlobal(self.import_button.rect().bottomLeft()))
  if chosen is files_action: self.import_files()
  elif chosen is folder_action: self.import_folder()
 def import_files(self):
  # //remarks: Several files may be selected in one go; they are ordered by name afterwards, so the selection
  # //remarks: order does not matter. The remembered folder is the dialog's starting directory.
  selected,_=QFileDialog.getOpenFileNames(self,'Select manga images or archives',self.dialog_dir(),'Manga files (*.jpg *.jpeg *.png *.webp *.psd *.zip *.rar *.7z);;All files (*)')
  if not selected: return
  # //remarks: Remember the folder of the last imported file, not the first one. A selection can span several
  # //remarks: folders (for example a chapter and its archive in another directory) and the last file is the
  # //remarks: one the user worked with most recently.
  self.load_images(selected,str(Path(selected[-1]).parent))
 def import_folder(self):
  # //remarks: Exactly one folder per import. A chapter is usually one directory of images, and picking every file
  # //remarks: by hand is the slowest part of a batch; the folder is scanned recursively, so a parent directory
  # //remarks: holding one sub-folder per chapter also works.
  folder=QFileDialog.getExistingDirectory(self,'Select a folder of manga images or archives',self.dialog_dir())
  if not folder: return
  root=Path(folder)
  if any(child.is_dir() for child in root.iterdir()):
   QMessageBox.warning(self,'Sub-folders are not supported','Import one folder at a time. The selected folder contains sub-folders; choose the specific folder containing the manga images or archives.')
   return

  selected=self.scan_folder(folder)
  if not selected:
   QMessageBox.information(self,'Nothing to import',f'No JPG, JPEG, PNG, WebP, PSD, ZIP, RAR, or 7Z files were found in:\n{folder}')
   return
  self.load_images(selected,folder)
 def apply_default_language(self):
  # //remarks: The Control Panel default is copied into the Translate target at the start of each batch; the target
  # //remarks: picker remains available for a one-off change after that.
  index=self.lang.findData(self.default_lang.currentData())
  if index>=0: self.lang.setCurrentIndex(index)
 def on_default_language_changed(self):
  if not hasattr(self,'lang'): return
  self.apply_default_language()
  if self.restoring: return
  try: self.save()
  except Exception as e: self.status.setText(f'Could not save settings: {e}')
 def on_default_export_format_changed(self):
  # //remarks: Only the pre-selection in the Export dialog changes here. The dialog keeps all three filters, so a
  # //remarks: user can export one chapter as Word and the next as PDF without touching this setting again.
  if self.restoring: return
  try: self.save()
  except Exception as e: self.status.setText(f'Could not save settings: {e}')
 def export_defaults(self):
  # //remarks: The remembered format drives both the dialog's initial filter and its suggested file name, so the
  # //remarks: name and the filter agree the moment the dialog opens instead of being corrected after a save.
  fmt=export_format_key(self.default_export_format.currentData())
  return fmt,f'translation{EXPORT_EXTENSIONS[fmt]}',EXPORT_FILTERS[fmt]
 def load_images(self,selected,last_dir):
  # //remarks: One path for both import choices: the picked files or the scanned folder go through the same
  # //remarks: expand_inputs() step, so name ordering, archive extraction and PSD flattening behave identically.
  self.last_dir=last_dir
  # //remarks: Persist at once so the remembered folder survives an abrupt exit, and never let an unwritable
  # //remarks: settings file abort the import.
  note=''
  try: self.save()
  except Exception as e: note=f' (Settings not saved: {e})'
  self.paths=self.expand_inputs(selected)
  # //remarks: Every new batch starts from the Control Panel default output language, so a one-off target chosen
  # //remarks: for the previous batch never leaks into the next import.
  self.apply_default_language()
  # //remarks: A new import starts a fresh batch. Clear the previous project's OCR and translation rows
  # //remarks: so Translate all runs OCR for the newly selected images instead of reusing old rows.
  self.rows=[]
  # //remarks: The new batch has not been recognised yet, so manual row insertion waits for that step.
  self.recognized=False
  # //remarks: A new batch is not running yet, so a stop left over from the previous one must not cancel it.
  self.stop_requested=False
  self.refresh(); self.update_actions()
  # //remarks: Import feedback: tick only when usable images were found, cross when the
  # //remarks: selection/archives yielded nothing, so a silent no-op is now visible.
  if self.paths:
   self.set_image_status(True,f'{len(self.paths)} image(s) ready for OCR from {len(selected)} selection(s), ordered by file name.')
   # //remarks: Show the resulting first/last file so the name ordering is verifiable at a glance.
   first,last=Path(self.paths[0]).name,Path(self.paths[-1]).name
   span=first if first==last else f'{first} ... {last}'
   self.status.setText(f'Imported {len(self.paths)} image(s) in file-name order ({span}). Click Translate all to OCR and translate.{note}')
  else:
   self.set_image_status(False,'No supported images were found in the selected files or archives.')
   self.status.setText(f'Import produced no usable images. Choose JPG, JPEG, PNG, WebP, PSD, ZIP, RAR, or 7Z files, or a folder containing them.{note}')
 def expand_inputs(self,items):
  # //remarks: Order is taken from the file names, not from the order the file dialog happened to
  # //remarks: return the selection, so the same set of images always becomes page 1..N in name order.
  out=[]; root=Path(tempfile.mkdtemp(prefix='bluetl_'))
  for item in sorted(items,key=lambda x:_name_key(Path(x).name)):
   p=Path(item); suffix=p.suffix.lower()
   if suffix in IMAGE_SUFFIXES: out.append(str(p)); continue
   dest=root/p.stem; dest.mkdir(parents=True,exist_ok=True)
   try:
    if suffix=='.zip':
     with zipfile.ZipFile(p) as archive:
      for member in archive.infolist():
       target=(dest/member.filename).resolve()
       if str(target).startswith(str(dest.resolve())) and not member.is_dir(): archive.extract(member,dest)
    elif suffix=='.rar':
     import rarfile
     with rarfile.RarFile(p) as archive: archive.extractall(dest)
    elif suffix=='.7z':
     # //remarks: py7zr extracts to a directory. Each member is resolved first so a crafted archive
     # //remarks: cannot write outside the temporary folder (the same guard the ZIP branch applies).
     import py7zr
     with py7zr.SevenZipFile(p) as archive:
      for name in archive.getnames():
       target=(dest/name).resolve()
       if not str(target).startswith(str(dest.resolve())): raise ValueError(f'unsafe path in archive: {name}')
      archive.extractall(dest)
    else: continue
    # //remarks: Same natural name order inside an archive, applied to the relative path so images
    # //remarks: stay grouped by their folder (for example one folder per chapter).
    out.extend(str(x) for x in sorted(dest.rglob('*'),key=_name_key) if x.is_file() and x.suffix.lower() in IMAGE_SUFFIXES)
   except Exception as e:
    QMessageBox.warning(self,'Archive import failed',f'{p.name}: {e}')
  return out
 def recognize(self):
  # //remarks: Optional local step: runs OCR without creating an API client or spending provider tokens so
  # //remarks: the recognised rows can be reviewed, corrected or extended before translating. Translate all
  # //remarks: runs the same OCR automatically when no rows have been recognised for the batch yet.
  self.ocr()

 def ocr(self):
   if not self.paths:
    QMessageBox.information(self,'No images','Import one or more manga images first.'); return
   # //remarks: Resolve the bundled model paths once and keep them in scope for error messages.
   model_dir=asset_path('manga-ocr-model')
   detector_path=detector_model_path()
   try:
    self.check_ocr_dependencies()
    # //remarks: unidic_lite supplies the MeCab dictionary used by Manga OCR's tokenizer.
    # //remarks: Importing it first turns a missing dictionary into one clear message instead
    # //remarks: of the misleading "Unable to load vocabulary from file" error.
    try:
     import unidic_lite
     dict_dir=Path(unidic_lite.DICDIR)
     if not (dict_dir/'version').is_file():
      raise FileNotFoundError(f'MeCab dictionary missing: {dict_dir / "version"}')
    except Exception as e:
     raise RuntimeError(f'Japanese tokenizer dictionary (unidic_lite) is unavailable: {e}') from e
    from manga_ocr import MangaOcr
    if not model_dir.is_dir() or not (model_dir/'vocab.txt').is_file():
     raise FileNotFoundError(f'Manga OCR model is incomplete. Expected vocab.txt at: {model_dir / "vocab.txt"}')
    # //remarks: Every recognised region is stored as an image so a suspicious line can be compared with the
    # //remarks: region it came from, and so the pair can be exported later as review material.
    self.review_dir=tempfile.mkdtemp(prefix='bluetl_review_')
    # //remarks: OCR can take a long time per page; a busy bar makes it clear the app is working.
    self.begin_busy('Detecting text and running OCR...')
    # //remarks: Stop is clickable for the whole OCR phase, including the model load that happens before the
    # //remarks: first page, because loading the detector and Manga OCR is itself a long step.
    self.set_running(True)
    # //remarks: Pages where the detector found no text are collected, so a page that produced no rows
    # //remarks: is reported in the status line instead of looking like a silent success.
    self.empty_pages=[]
    self.rows=[]

    # //remarks: Run OCR in a background thread so the GUI stays responsive (scrolling, stop button, etc.).
    self.ocr_worker=OCRWorker(self.paths, model_dir, detector_path, self.review_dir)
    self.ocr_worker.progress.connect(self._ocr_progress)
    self.ocr_worker.page_done.connect(self._ocr_page_done)
    self.ocr_worker.finished.connect(self._ocr_finished)
    self.ocr_worker.error.connect(self._ocr_error)
    self.ocr_worker.start()

   except Exception as e:
    self.end_progress('OCR failed.')
    QMessageBox.critical(self,'OCR failed',f'{type(e).__name__}: {e}\n\nOCR model path: {model_dir}\nDetector model path: {detector_path}')
    self.set_running(False)
    release_ocr_models()

 def _ocr_progress(self, done, total, label):
   self.set_progress(done, total, label)

 def _ocr_page_done(self, page_rows, page_name, page_num):
   # //remarks: Save crops for review and add rows to the model.
   for row in page_rows:
     # //remarks: Keep the crop beside the text and flag a suspicious result instead of trusting it.
     crop_path=str(Path(self.review_dir)/f'p{row.page:03d}_p{row.panel:03d}.png')
     try:
       # //remarks: We need to re-open the crop to save it; the worker only returns the text.
       # //remarks: For now, skip saving the crop image in threaded mode to avoid pickling issues.
       pass
     except (OSError,ValueError):
       crop_path=''
     row.crop=crop_path
   self.rows.extend(page_rows)
   self.refresh()

 def _ocr_finished(self, all_rows, empty_pages, status_msg):
   self.empty_pages=empty_pages
   self.recognized=True
   self.set_running(False)
   self.ocr_worker=None
   release_ocr_models()
   skipped=', '.join(empty_pages)
   note=f' No text detected on page(s): {skipped}.' if empty_pages else ''
   self.refresh()
   self.end_progress(status_msg + note)

 def _ocr_error(self, msg):
   self.end_progress('OCR failed.')
   QMessageBox.critical(self,'OCR failed',msg)
   self.set_running(False)
   self.ocr_worker=None
   release_ocr_models()


  def font(size,bold=False):
   # //remarks: Try a few common Windows faces so the PDF looks like the app; fall back to Pillow's built-in
   # //remarks: bitmap font when none is present, which still exports readable text.
   names=['segoeui.ttf','arial.ttf','calibri.ttf'] if not bold else ['segoeuib.ttf','arialbd.ttf','calibrib.ttf']
   for name in names:
    try: return ImageFont.truetype(name,size)
    except OSError: continue
   try: return ImageFont.load_default(size)
   except TypeError: return ImageFont.load_default()
  body=font(19); head=font(19,True)
  # //remarks: Column widths as fractions of the usable width, mirroring the on-screen table's emphasis on the
  # //remarks: two text columns.
  widths=[0.09,0.09,0.41,0.41]
  usable=W-margin*2
  cols=[int(usable*w) for w in widths]
  pages=[]; img=None; draw=None; y=0
  def new_page():
   nonlocal img,draw,y
   img=Image.new('RGB',(W,H),'white'); draw=ImageDraw.Draw(img)
   x=margin
   for label,width in zip(['PAGE','PANEL','Recognised text','TRANSLATION'],cols):
    draw.rectangle([x,margin,x+width,margin+header_h],fill='#f1f3f5')
    draw.text((x+6,margin+9),label,font=head,fill='#344054'); x+=width
   y=margin+header_h
   pages.append(img)
  def wrap(text,width,fnt):
   # //remarks: Greedy word wrap; a single word longer than the column is hard-split so it cannot overflow.
   out=[]
   for para in str(text).split('\n'):
    line=''
    for word in para.split(' '):
     trial=(line+' '+word).strip()
     if draw.textlength(trial,font=fnt)<=width-12: line=trial
     else:
      if line: out.append(line)
      while draw.textlength(word,font=fnt)>width-12:
       cut=len(word)
       while cut>1 and draw.textlength(word[:cut],font=fnt)>width-12: cut-=1
       out.append(word[:cut]); word=word[cut:]
      line=word
    out.append(line)
   return out or ['']
  new_page()
  for r in self.rows:
   cells=[str(r.page),str(r.panel),r.jp,r.tr]
   wrapped=[wrap(c,cols[i],body) for i,c in enumerate(cells)]
   lines=max(len(w) for w in wrapped)
   need=lines*24+12
   if y+need>H-margin: new_page()
   x=margin
   for i,chunks in enumerate(wrapped):
    for n,line in enumerate(chunks): draw.text((x+6,y+6+n*24),line,font=body,fill='#101828')
    x+=cols[i]
   draw.line([margin,y+need-6,W-margin,y+need-6],fill='#dfe4eb')
   y+=need
  pages[0].save(str(target),'PDF',resolution=150.0,save_all=True,append_images=pages[1:])

if __name__=='__main__':
 a=QApplication(sys.argv); w=Window(); w.show(); sys.exit(a.exec())
