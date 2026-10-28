import sys, json, os, re, base64, ctypes, tempfile, zipfile
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
from PySide6.QtWidgets import QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QComboBox,QPushButton,QFileDialog,QTableWidget,QTableWidgetItem,QMessageBox,QLabel,QHeaderView,QTabWidget,QProgressBar
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

CFG=Path(os.getenv('APPDATA',Path.home()))/'BlueTL'/'config.json'
LANGS=['English','Bahasa Melayu','Simplified Chinese','Traditional Chinese']
FREE_MODELS=['asai/freemodel-1-GLM','asai/freemodel-2-MiniMax','asai/freemodel-3-deepseekpro','asai/freemodel-4-ds-v4.1flash','asai/freemodel-5-kimi']
MODELS=FREE_MODELS+['asai/minimax-m3','asai/deepseek-v4.1-flash','asai/glm-5.3-flash','asai/qwen3.8-flash','asai/claude-haiku-5.5','asai/claude-haiku-4.5','asai/kimi-k2.7']
@dataclass
class Row: page:int; panel:int; jp:str; tr:str=''

# //remarks: Page level OCR helpers. Manga OCR only accepts one text strip per call and has no
# //remarks: detector in 0.1.x, so calling it on a whole page returned just one line. These helpers
# //remarks: (1) find text line clusters, (2) find speech bubbles geometrically, (3) assign each line
# //remarks: to the bubble that contains it. One page therefore yields one row per bubble.
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

def _bubble_mask(img):
  # //remarks: Dark line art (bubble outlines and strokes) after filling small holes, which turns a
  # //remarks: speech bubble into a closed blob. This lets each text seed be assigned to its own
  # //remarks: bubble, which is far more reliable than guessing box extents from the text mask alone.
  import numpy as np
  grey=np.asarray(img.convert('L'),dtype=np.float32)
  h,w=grey.shape
  local=_box_mean(grey,max(4,min(h,w)//60))
  lines=grey<local*0.72
  # //remarks: Close 1-pixel gaps in the outline so the bubble interior counts as enclosed.
  closed=lines.copy()
  for dy,dx in ((0,1),(0,-1),(1,0),(-1,0)):
    closed|=np.roll(lines,dy,axis=0)&np.roll(lines,dx,axis=1)
  return closed

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
  right=x1; run=0
  while right<w-1:
    if band[:,right].any():
      run=0; right+=1
    else:
      run+=1; right+=1
      if run>gap: right-=run; break
  if (right-left+1)>w*0.55: return None
  return (left,ty0,right,ty1)

def _line_clusters(img):
  # //remarks: Groups glyph components into text lines. A component is treated as a glyph when it is
  # //remarks: small and dense; large thin components are line art (bubble borders, panel frames) and
  # //remarks: are dropped. Glyphs on the same baseline and close together form one line cluster.
  import numpy as np
  mask=_text_mask(img)
  h,w=mask.shape
  labels,comps=_components(mask)
  glyphs=[]
  for c in comps:
    x0,y0,x1,y1=c['box']; cw=x1-x0+1; ch=y1-y0+1
    if ch<4 or cw<2: continue
    # //remarks: Fill ratio separates solid glyphs from long thin outlines.
    if c['area']/(cw*ch)<0.18: continue
    if cw>w*0.5 or ch>h*0.5: continue
    glyphs.append(c['box'])
  # //remarks: Union glyph boxes that share a baseline and are horizontally adjacent.
  lines=[list(b) for b in glyphs]
  changed=True
  while changed:
    changed=False
    for i in range(len(lines)):
      for j in range(i+1,len(lines)):
        a=lines[i]; b=lines[j]
        ah=a[3]-a[1]+1; bh=b[3]-b[1]+1
        gap_x=max(0,max(a[0],b[0])-min(a[2],b[2]))
        overlap_y=min(a[3],b[3])-max(a[1],b[1])
        if overlap_y>0.35*min(ah,bh) and gap_x<=max(6,int(0.5*min(ah,bh))):
          lines[i]=[min(a[0],b[0]),min(a[1],b[1]),max(a[2],b[2]),max(a[3],b[3])]
          lines.pop(j); changed=True; break
      if changed: break
  return [tuple(l) for l in lines], mask

def _bubble_boxes(img,lines):
  # //remarks: Detects speech bubbles from line art instead of from text: dark pixels form a filled
  # //remarks: blob, and blobs roughly circular-rectangular (bubbles) are returned as candidate boxes.
  # //remarks: Each detected text line is then assigned to the bubble that contains it, which avoids
  # //remarks: the fragile "grow the text box" heuristics that merged or truncated bubbles.
  import numpy as np
  grey=np.asarray(img.convert('L'),dtype=np.float32)
  h,w=grey.shape
  dark=grey<np.clip(_box_mean(grey,1)*0.90,0,255)
  # //remarks: Downsample before labelling: full-resolution component labelling in Python is slow and
  # //remarks: bubble outlines remain clearly visible at this scale.
  step=max(1,int(min(h,w)/700))
  small=dark[::step,::step]
  _,comps=_components(small)
  bubbles=[]
  for c in comps:
    x0,y0,x1,y1=c['box']; cw=(x1-x0+1)*step; ch=(y1-y0+1)*step
    if cw<30 or ch<30: continue
    if cw>w*0.7 or ch>h*0.7: continue
    ratio=cw/ch
    if not (0.4<=ratio<=2.5): continue
    # //remarks: Keep blobs that actually contain text lines, otherwise panel frames are included.
    inside=[l for l in lines if x0*step<=l[0]<=x1*step and y0*step<=l[1]<=y1*step]
    if inside: bubbles.append((x0*step,y0*step,x1*step,y1*step))
  return bubbles

def detect_text_regions(img):
  # //remarks: Public entry point. Each text line is expanded to its speech bubble when one contains it,
  # //remarks: so a bubble's text becomes one region; lines outside bubbles keep their own box.
  import numpy as np
  lines,mask=_line_clusters(img)
  bubbles=_bubble_boxes(img,lines)
  w,h=img.size
  regions=[]
  used=set()
  for lx0,ly0,lx1,ly1 in lines:
    host=None
    for bidx,b in enumerate(bubbles):
      if b[0]-4<=lx0 and lx1<=b[2]+4 and b[1]-4<=ly0 and ly1<=b[3]+4:
        host=bidx; break
    if host is None: regions.append((lx0,ly0,lx1,ly1))
  # //remarks: One region per bubble, covering the union of all lines it contains.
  for bidx,b in enumerate(bubbles):
    members=[l for l in lines if b[0]-4<=l[0]<=b[2]+4 and b[1]-4<=l[1]<=b[3]+4]
    if members:
      regions.append((min(l[0] for l in members),min(l[1] for l in members),
                      max(l[2] for l in members),max(l[3] for l in members)))
  # //remarks: Union overlapping regions so a bubble cannot be emitted twice.
  regions=_merge_boxes(regions,max(8,int(min(w,h)*0.015)))
  # //remarks: Manga reading order: top-to-bottom, and right-to-left within one band.
  row_h=max(1,int(h*0.04))
  regions.sort(key=lambda b:((b[1]+b[3])//2//row_h,-b[0]))
  boxes=[]
  for x0,y0,x1,y1 in regions:
    if (x1-x0)<6 or (y1-y0)<6: continue
    area=(x1-x0+1)*(y1-y0+1)
    ink_px=int(mask[y0:y1+1,x0:x1+1].sum())
    if ink_px<max(40,int(area*0.02)): continue
    pad=max(6,int(min(w,h)*0.012))
    padx=max(pad,int((y1-y0+1)*0.6))
    boxes.append((max(0,x0-padx),max(0,y0-pad),min(w,x1+padx),min(h,y1+pad)))
  return _merge_boxes(boxes,max(8,int(min(w,h)*0.015)))

def _merge_boxes(boxes,gap=12):
  # //remarks: Union overlapping/near-touching boxes so one text block becomes a single OCR region
  # //remarks: while vertically separated blocks stay separate. Without this, expanded seeds of the
  # //remarks: same line stayed apart and each crop only held part of the text.
  import numpy as np
  if not boxes: return []
  rects=[list(b) for b in boxes]
  changed=True
  while changed:
    changed=False
    for i in range(len(rects)):
      for j in range(i+1,len(rects)):
        a=rects[i]; b=rects[j]
        if a[0]-gap<=b[2] and b[0]-gap<=a[2] and a[1]-gap<=b[3] and b[1]-gap<=a[3]:
          rects[i]=[min(a[0],b[0]),min(a[1],b[1]),max(a[2],b[2]),max(a[3],b[3])]
          rects.pop(j); changed=True; break
      if changed: break
  return [tuple(r) for r in rects]
def _regions_with_fallback(img,engine):
  # //remarks: Safety net: if detection finds nothing, fall back to recognising the whole page
  # //remarks: once (old behaviour), and if the page is very tall also try horizontal thirds, so a
  # //remarks: page never silently returns zero text.
  from PIL import Image
  regions=detect_text_regions(img)
  if regions: return [(b,img.crop(b)) for b in regions]
  w,h=img.size
  crops=[((0,0,w,h),img)]
  if h>w*1.4:
    crops=[((0,0,w,h//2),img.crop((0,0,w,h//2))),((0,h//2,w,h),img.crop((0,h//2,w,h)))]
  return crops

def _name_key(value):
  # //remarks: Natural sort key for file names: "p9" must come before "p10", whereas plain text
  # //remarks: sorting put "p10" between "p1" and "p2". Splitting on runs of digits keeps strings at
  # //remarks: even positions and integers at odd ones, so every comparison stays type-safe.
  return [int(p) if p.isascii() and p.isdigit() else p for p in re.split(r'(\d+)',str(value).lower())]

class Window(QMainWindow):
 def __init__(self):
   super().__init__(); self.setWindowTitle('BlueTL - Manga Translator'); self.resize(1050,650); self.rows=[]; self.paths=[]
   # //remarks: Tracks the model that last answered a request; used in the API status tooltip.
   self.last_model=''
   icon_path=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'assets'/'bluetl.ico'
   if icon_path.is_file(): self.setWindowIcon(QIcon(str(icon_path)))
   self.ui(); self.load()
 def ui(self):
  w=QWidget(); v=QVBoxLayout(w); f=QFormLayout()
  self.url=QLineEdit('https://serveras.click/v1'); self.url.setPlaceholderText('https://serveras.click/v1')
  self.key=QLineEdit(); self.key.setEchoMode(QLineEdit.Password); self.key.setPlaceholderText('API key')
  self.model=QComboBox(); self.model.setEditable(True); self.model.addItems(MODELS); self.model.setCurrentText(MODELS[0]); self.model.setToolTip('The selected model is tried first; remaining models are automatic fallbacks.')
  self.lang=QComboBox(); self.lang.addItems(LANGS)
  for label,x in [('OpenAI-compatible Base URL',self.url),('API key',self.key),('Model',self.model),('Target language',self.lang)]: f.addRow(label,x)
  v.addLayout(f)
  # //remarks: Two always-visible status pills remove the "did it work?" ambiguity:
  # //remarks: tick = verified, cross = failed, dash = not checked yet. They start neutral
  # //remarks: (not checked), so the user can tell "untested" apart from "failed".
  s=QHBoxLayout(); s.addWidget(QLabel('Status:'))
  self.api_status=QLabel(); self.image_status=QLabel()
  for pill in (self.api_status,self.image_status): pill.setTextFormat(Qt.PlainText); s.addWidget(pill)
  s.addStretch(); v.addLayout(s)
  self.set_api_status(None); self.set_image_status(None); b=QHBoxLayout()
  for text,fn in [('Import images',self.images),('Add OCR row',self.add),('Test API',self.test_api),('Translate all',self.all),('Export TXT',self.txt),('Export DOCX',self.docx)]:
   q=QPushButton(text); q.clicked.connect(fn); b.addWidget(q)
  v.addLayout(b)
  # //remarks: Long OCR/translation lines used to be clipped to one line and hidden behind "...".
  # //remarks: Word wrap on the table plus wrapping items and computed row heights lets the text
  # //remarks: reflow onto multiple lines so nothing is cut off horizontally.
  self.table=QTableWidget(0,4); self.table.setHorizontalHeaderLabels(['Page','Panel','Recognized text','Translation'])
  self.table.setWordWrap(True)
  self.table.setAlternatingRowColors(True)
  self.table.horizontalHeader().setSectionResizeMode(2,QHeaderView.Stretch); self.table.horizontalHeader().setSectionResizeMode(3,QHeaderView.Stretch)
  # //remarks: Re-run height calculation after the user resizes columns, because the amount of
  # //remarks: wrapping depends on the current column width.
  self.table.horizontalHeader().sectionResized.connect(lambda *_: self._fit_rows())
  v.addWidget(self.table)
  # //remarks: Progress row: a determinate bar for batches plus a busy bar for single requests, so a
  # //remarks: long API call never looks like the app has frozen.
  self.progress=QProgressBar(); self.progress.setRange(0,1); self.progress.setValue(0)
  self.progress.setTextVisible(True); self.progress.setFormat('%v/%m'); self.progress.setMaximumHeight(18)
  self.progress.setVisible(False); v.addWidget(self.progress)
  self.status=QLabel('Import images, then click Translate all.')
  # //remarks: Filenames are echoed in status messages, so keep this label plain text: a file named
  # //remarks: with '<' or '&' must never be parsed as rich text markup.
  self.status.setTextFormat(Qt.PlainText); v.addWidget(self.status)
  tabs=QTabWidget(); tabs.addTab(w,'Translator'); about=QWidget(); av=QVBoxLayout(about); av.addWidget(QLabel('<h2>BlueTL</h2><p>Version v1.0</p><p>Published by borneanwingz.fl</p><p>Author: Blue-Wingz @ facedesk</p>')); av.addStretch(); tabs.addTab(about,'About'); self.setCentralWidget(tabs)
 def load(self):
  try:
   d=json.loads(CFG.read_text()); self.url.setText(d.get('url','https://serveras.click/v1')); self.model.setCurrentText(d.get('model',MODELS[0])); self.lang.setCurrentText(d.get('language',LANGS[0])); self.key.setText(unprotect(d.get('api_key','')))
  except (FileNotFoundError,json.JSONDecodeError): pass
 def save(self):
  CFG.parent.mkdir(parents=True,exist_ok=True)
  data={'url':self.url.text().strip(),'model':self.model.currentText().strip(),'language':self.lang.currentText(),'api_key':protect(self.key.text())}
  CFG.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
 def closeEvent(self,event):
  try: self.save()
  except Exception as e: self.status.setText(f'Could not save settings: {e}')
  event.accept()
 def candidates(self):
  return self.ranked(self.model.currentText().strip())
 def set_api_status(self,ok,detail=''):
  # //remarks: Single source of truth for the API pill: None=untested, True=verified, False=failed.
  # //remarks: Symbols are built with chr() so the source stays ASCII and cannot be corrupted by
  # //remarks: editors/codepages: U+2714 tick, U+2718 cross, U+2014 dash for "not checked".
  tick,cross,dash_=chr(0x2714),chr(0x2718),chr(0x2014)
  text=f'API: {tick} OK' if ok else (f'API: {cross} Failed' if ok is False else f'API: {dash_} Not tested')
  colour='#1a7f37' if ok else ('#c62828' if ok is False else '#6b7280')
  self.api_status.setText(text); self.api_status.setStyleSheet(f'color:{colour};font-weight:600;padding:2px 8px;')
  self.api_status.setToolTip(detail or 'Run Test API, or use Translate all to verify automatically.')
 def set_image_status(self,ok,detail=''):
  # //remarks: None=no images, True=images/archive expanded, False=import produced no usable images.
  tick,cross,dash_=chr(0x2714),chr(0x2718),chr(0x2014)
  text=f'Images: {tick} Loaded' if ok else (f'Images: {cross} None' if ok is False else f'Images: {dash_} Not imported')
  colour='#1a7f37' if ok else ('#c62828' if ok is False else '#6b7280')
  self.image_status.setText(text); self.image_status.setStyleSheet(f'color:{colour};font-weight:600;padding:2px 8px;')
  self.image_status.setToolTip(detail)
 def ranked(self,selected):
  all_free=[m for m in FREE_MODELS if m != selected]
  return ([selected] if selected else [])+all_free+[m for m in MODELS if m not in FREE_MODELS and m != selected]

 def images(self):
  selected,_=QFileDialog.getOpenFileNames(self,'Select manga images or archives','','Manga files (*.jpg *.jpeg *.png *.webp *.zip *.rar)')
  if not selected:return
  self.paths=self.expand_inputs(selected)
  # //remarks: Import feedback: tick only when usable images were found, cross when the
  # //remarks: selection/archives yielded nothing, so a silent no-op is now visible.
  if self.paths:
   self.set_image_status(True,f'{len(self.paths)} image(s) ready for OCR from {len(selected)} selection(s), ordered by file name.')
   # //remarks: Show the resulting first/last file so the name ordering is verifiable at a glance.
   first,last=Path(self.paths[0]).name,Path(self.paths[-1]).name
   span=first if first==last else f'{first} ... {last}'
   self.status.setText(f'Imported {len(self.paths)} image(s) in file-name order ({span}). Click Translate all to OCR and translate.')
  else:
   self.set_image_status(False,'No supported images were found in the selected files or archives.')
   self.status.setText('Import produced no usable images. Choose JPG, JPEG, PNG, WebP, ZIP, or RAR files.')
 def expand_inputs(self,items):
  # //remarks: Order is taken from the file names, not from the order the file dialog happened to
  # //remarks: return the selection, so the same set of images always becomes page 1..N in name order.
  out=[]; root=Path(tempfile.mkdtemp(prefix='bluetl_'))
  for item in sorted(items,key=lambda x:_name_key(Path(x).name)):
   p=Path(item); suffix=p.suffix.lower()
   if suffix in ('.jpg','.jpeg','.png','.webp'): out.append(str(p)); continue
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
    else: continue
    # //remarks: Same natural name order inside an archive, applied to the relative path so images
    # //remarks: stay grouped by their folder (for example one folder per chapter).
    out.extend(str(x) for x in sorted(dest.rglob('*'),key=_name_key) if x.is_file() and x.suffix.lower() in ('.jpg','.jpeg','.png','.webp'))
   except Exception as e:
    QMessageBox.warning(self,'Archive import failed',f'{p.name}: {e}')
  return out
 def ocr(self):
  if not self.paths:
   QMessageBox.information(self,'No images','Import one or more manga images first.'); return
  # //remarks: Resolve the bundled model path once and keep it in scope for error messages.
  model_dir=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'assets'/'manga-ocr-model'
  try:
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
   engine=MangaOcr(str(model_dir))
   self.rows=[]
   from PIL import Image
   # //remarks: OCR can take a long time per page; a busy bar makes it clear the app is working.
   self.begin_busy('Running OCR...')
   for page,path in enumerate(self.paths,1):
    # //remarks: Detect every text region on the page and recognise each one, instead of the old
    # //remarks: single whole-page call that returned only one line per image.
    img=Image.open(path); img.load()
    crops=_regions_with_fallback(img,engine)
    self.set_progress(page-1,len(self.paths),f'OCR page {page}/{len(self.paths)}: {Path(path).name} ({len(crops)} region(s))')
    panel=0
    for index,(box,crop) in enumerate(crops,1):
     self.set_progress(page-1,len(self.paths),f'OCR page {page}/{len(self.paths)}, region {index}/{len(crops)}')
     text=engine(crop).strip()
     if text:
      panel+=1
      self.rows.append(Row(page,panel,text))
   self.refresh(); self.end_progress(f'OCR completed: {len(self.rows)} text region(s) across {len(self.paths)} page(s). Review before translating.')
  except ImportError:
   self.end_progress('OCR is not installed.')
   QMessageBox.critical(self,'OCR is not installed','Install dependencies with: python -m pip install -r requirements.txt')
  # //remarks: Report the resolved model path plus any dictionary path so failures are diagnosable.
  except Exception as e:
   self.end_progress('OCR failed.')
   QMessageBox.critical(self,'OCR failed',f'{type(e).__name__}: {e}\n\nModel path: {model_dir}')
 def region_lines(self,text):
  return [line.strip() for line in text.replace('\\r','').split('\\n') if line.strip()]
 def add(self):
  page=len(self.paths) if self.paths else 1
  # //remarks: New rows start empty and are immediately editable; jp is required by Row.
  self.rows.append(Row(page,1,'')); self.refresh(); self.table.editItem(self.table.item(len(self.rows)-1,2))
 def refresh(self):
  self.table.setRowCount(len(self.rows))
  for i,r in enumerate(self.rows):
   for j,x in enumerate((r.page,r.panel,r.jp,r.tr)):
    item=QTableWidgetItem(str(x))
    # //remarks: Page/Panel are numeric and stay single-line and centred; text columns wrap.
    if j<2:
     item.setTextAlignment(Qt.AlignCenter)
    else:
     # //remarks: Long lines must reflow, so allow multi-line layout instead of eliding with "...".
     item.setTextAlignment(Qt.AlignLeft|Qt.AlignTop)
    self.table.setItem(i,j,item)
  self._fit_rows()
 def _fit_rows(self):
  # //remarks: QTableWidget does not grow rows on its own. Size each row to the wrapped content so
  # //remarks: long OCR/translation lines are fully visible. The soft cap only prevents a single huge
  # //remarks: paragraph from eating the whole window; text stays readable via the cell tooltip.
  if not hasattr(self,'table') or self.table.rowCount()==0: return
  self.table.resizeRowsToContents()
  cap=max(160,int(self.table.viewport().height()*0.75))
  for i in range(self.table.rowCount()):
   if self.table.rowHeight(i)>cap:
    self.table.setRowHeight(i,cap)
    # //remarks: Full text remains reachable when the row is capped, so nothing is truly lost.
    for j in (2,3):
     item=self.table.item(i,j)
     if item is not None: item.setToolTip(item.text())
 def sync(self):
  for i,r in enumerate(self.rows):
   r.page=int(self.table.item(i,0).text() or 1); r.panel=int(self.table.item(i,1).text() or 1); r.jp=self.table.item(i,2).text(); r.tr=self.table.item(i,3).text()
 def begin_progress(self,total,label=''):
  # //remarks: Batch mode: a determinate bar so the user sees exact progress through N rows.
  self.progress.setRange(0,max(1,total)); self.progress.setValue(0)
  self.progress.setFormat('%v/%m'); self.progress.setVisible(True)
  if label: self.status.setText(label)
  QApplication.processEvents()
 def set_progress(self,done,total,label=''):
  # //remarks: processEvents() forces an immediate repaint; without it the window stays blank while
  # //remarks: the synchronous API call runs, which is what made the app look hung.
  self.progress.setRange(0,max(1,total)); self.progress.setValue(done)
  if label: self.status.setText(label)
  QApplication.processEvents()
 def begin_busy(self,label=''):
  # //remarks: Single request: a busy (indeterminate) bar shows work is happening with no known total.
  self.progress.setRange(0,0); self.progress.setFormat('Working...')
  self.progress.setVisible(True)
  if label: self.status.setText(label)
  QApplication.processEvents()
 def end_progress(self,label=''):
  # //remarks: Hide the bar when idle so it only ever indicates active work.
  self.progress.setVisible(False); self.progress.setRange(0,1); self.progress.setValue(0)
  if label: self.status.setText(label)
  QApplication.processEvents()
 def client(self):
  if not self.url.text() or not self.key.text() or not self.model.currentText(): QMessageBox.warning(self,'API settings required','Enter Base URL, API key, and model name.'); return None
  self.save(); return OpenAI(base_url=self.url.text().rstrip('/'),api_key=self.key.text())
 def translate(self,text,client):
  prof={'English':'natural conversational English','Bahasa Melayu':'natural Malaysian Malay, not Indonesian or textbook Malay','Simplified Chinese':'natural Mainland Chinese Simplified Chinese','Traditional Chinese':'natural Taiwanese Traditional Chinese'}[self.lang.currentText()]
  prompt=f'Translate this Japanese manga text into {prof}. Preserve tone, emotion, politeness, slang, humor, and implied meaning. Return only the translation, with no notes or explanation.\\n\\nJapanese:\\n{text}'
  selected=self.model.currentText(); candidates=self.candidates(); last=None; self.last_model=''
  for model in candidates:
   try:
    r=client.chat.completions.create(model=model,messages=[{'role':'system','content':'You are a professional manga translator.'},{'role':'user','content':prompt}]); result=(r.choices[0].message.content or '').strip()
    # //remarks: Remember which model actually answered so the API pill tooltip is accurate.
    self.last_model=model
    if model != selected: self.status.setText(f'Fallback model used: {model}')
    return result
   except Exception as e: last=e
  raise RuntimeError(f'All configured models failed. Last error: {last}')
 def test_api(self):
  c=self.client()
  if not c:return
  last=None
  for model in self.candidates():
   try:
    # //remarks: Busy bar for the probe request; a slow provider previously looked like a dead button.
    self.begin_busy(f'Testing API model: {model}...')
    r=c.chat.completions.create(model=model,messages=[{'role':'user','content':'Reply with OK.'}]); reply=(r.choices[0].message.content or '').strip()
    self.end_progress('API test succeeded.')
    # //remarks: A successful probe flips the API pill to a green tick and records which model answered.
    self.set_api_status(True,f'Verified with model: {model}')
    QMessageBox.information(self,'API connection',f'Connection succeeded.\nModel: {model}\nResponse: {reply}')
    return
   except Exception as e: last=e
  self.end_progress('API test failed.')
  # //remarks: Every candidate failed, so the pill shows a red cross with the last real provider error.
  self.set_api_status(False,str(last))
  QMessageBox.critical(self,'API connection failed',f'All configured models failed.\n\nLast error: {last}')
 def one(self):
  i=self.table.currentRow(); self.sync(); c=self.client()
  if c and i>=0 and self.rows[i].jp:
   # //remarks: Busy bar while the single request is in flight, so a slow model does not look frozen.
   self.begin_busy(f'Translating page {self.rows[i].page}, panel {self.rows[i].panel}...')
   try:
    self.rows[i].tr=self.translate(self.rows[i].jp,c); self.refresh()
    # //remarks: Translate-selected proves the API works, so the pill ticks itself too.
    self.set_api_status(True,f'Verified by translation with model: {self.last_model or self.model.currentText()}')
    self.end_progress('Row translated.')
   except Exception as e:
    self.end_progress('Translation failed.')
    self.set_api_status(False,str(e))
    QMessageBox.critical(self,'Translation failed',str(e))
 def all(self):
  if self.paths and not self.rows:
   self.ocr()
  self.sync(); c=self.client()
  if not c:return
  if not self.rows:
   QMessageBox.information(self,'No OCR text','Import images first. OCR runs automatically when Translate all is clicked.'); return
  todo=[r for r in self.rows if r.jp]
  if not todo:
   QMessageBox.information(self,'No OCR text','There are no recognised text rows to translate.'); return
  # //remarks: Report batch size up front so the progress bar has a meaningful denominator.
  self.begin_progress(len(todo),f'Translating 0/{len(todo)} rows...')
  try:
   for i,r in enumerate(todo,1):
    self.set_progress(i-1,len(todo),f'Translating row {i}/{len(todo)} (page {r.page}, panel {r.panel})...')
    r.tr=self.translate(r.jp,c)
    # //remarks: Update the table as each row completes so finished translations are visible during
    # //remarks: the run, and the bar advances even when an individual call is slow.
    self.set_progress(i,len(todo),f'Translated {i}/{len(todo)} rows...')
    self.refresh()
   self.end_progress('OCR and sequential translation completed.')
   # //remarks: If the API was never tested, a successful batch translation is itself proof
   # //remarks: the API works, so tick the pill automatically instead of leaving it as "not tested".
   self.set_api_status(True,f'Verified automatically by Translate all (model: {self.last_model or self.model.currentText()})')
   self.save()
  except Exception as e:
   # //remarks: Hide the bar on failure too, otherwise a stalled bar looks like a hang.
   self.end_progress(f'Translation stopped: {e}')
   # //remarks: A failed batch still tells us the API is not usable with these settings.
   self.set_api_status(False,str(e))
   QMessageBox.critical(self,'Translation failed',str(e))
 def txt(self):
  self.sync(); p,_=QFileDialog.getSaveFileName(self,'Export TXT','translation.txt','Text (*.txt)')
  if p: Path(p).write_text('Page\tPanel\tRecognized text\tTranslation\n'+'\n'.join(f'{r.page}\t{r.panel}\t{r.jp}\t{r.tr}' for r in self.rows),encoding='utf-8')
 def docx(self):
  self.sync(); p,_=QFileDialog.getSaveFileName(self,'Export DOCX','translation.docx','Word (*.docx)')
  if p:
   d=Document(); t=d.add_table(rows=1,cols=4)
   for c,x in zip(t.rows[0].cells,['Page','Panel','Recognized text','Translation']): c.text=x
   for r in self.rows:
    cells=t.add_row().cells
    for c,x in zip(cells,[r.page,r.panel,r.jp,r.tr]): c.text=str(x)
   d.save(p)
if __name__=='__main__':
 a=QApplication(sys.argv); w=Window(); w.show(); sys.exit(a.exec())
