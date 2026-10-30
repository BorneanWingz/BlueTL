import sys, json, os, re, base64, ctypes, shutil, tempfile, zipfile
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
from PySide6.QtWidgets import QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QComboBox,QPushButton,QFileDialog,QTableWidget,QTableWidgetItem,QMessageBox,QLabel,QHeaderView,QTabWidget,QProgressBar,QSizePolicy,QStyle,QStyleOptionButton
from PySide6.QtCore import Qt,QSize
from PySide6.QtGui import QIcon,QPainter,QPalette

CFG=Path(os.getenv('APPDATA',Path.home()))/'BlueTL'/'config.json'
LANGS=['English','Bahasa Melayu','Simplified Chinese','Traditional Chinese']
FREE_MODELS=['asai/freemodel-1-GLM','asai/freemodel-2-MiniMax','asai/freemodel-3-deepseekpro','asai/freemodel-4-ds-v4.1flash','asai/freemodel-5-kimi']
MODELS=FREE_MODELS+['asai/minimax-m3','asai/deepseek-v4.1-flash','asai/glm-5.3-flash','asai/qwen3.8-flash','asai/claude-haiku-5.5','asai/claude-haiku-4.5','asai/kimi-k2.7']
@dataclass
class Row: page:int; panel:int; jp:str; tr:str=''; crop:str=''; review:str=''; reason:str=''

# //remarks: A compact push button that wraps its label onto a second line instead of eliding it with
# //remarks: "...". This keeps every action readable while the whole action row still fits one line.
class WrapButton(QPushButton):
 def __init__(self,text='',parent=None):
  super().__init__(text,parent)
  self.setSizePolicy(QSizePolicy.Fixed,QSizePolicy.Fixed)
  self.setMinimumWidth(62); self.setMaximumWidth(105)
 def sizeHint(self):
  return QSize(105,40)
 def minimumSizeHint(self):
  return QSize(62,40)
 def paintEvent(self,event):
  # //remarks: Draw the normal button frame, then the label on top of it with word wrap so a long
  # //remarks: label reflows inside the fixed width instead of being clipped.
  opt=QStyleOptionButton(); self.initStyleOption(opt); opt.text=''
  painter=QPainter(self); painter.setRenderHint(QPainter.TextAntialiasing)
  self.style().drawControl(QStyle.CE_PushButton,opt,painter,self)
  group=QPalette.Active if self.isEnabled() else QPalette.Disabled
  painter.setPen(self.palette().color(group,QPalette.ButtonText))
  rect=self.rect().adjusted(5,3,-5,-3)
  painter.drawText(rect,Qt.TextWordWrap|Qt.AlignCenter|Qt.AlignVCenter,self.text())
  painter.end()

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

def _name_key(value):
  # //remarks: Natural sort key for file names: "p9" must come before "p10", whereas plain text
  # //remarks: sorting put "p10" between "p1" and "p2". Splitting on runs of digits keeps strings at
  # //remarks: even positions and integers at odd ones, so every comparison stays type-safe.
  return [int(p) if p.isascii() and p.isdigit() else p for p in re.split(r'(\d+)',str(value).lower())]

class Window(QMainWindow):
 def __init__(self):
   super().__init__(); self.setWindowTitle('BlueTL - Manga Translator'); self.resize(1050,650); self.rows=[]; self.paths=[]
   # //remarks: Tracks whether the OCR step has run for the current batch. Manual row insertion waits for
   # //remarks: that step, because a new row takes its page and panel number from the recognised rows.
   self.recognized=False
   # //remarks: Remember the last folder used by the import dialog across application restarts.
   self.last_dir=''
   # //remarks: Folder holding the crop of every recognised region, so a flagged line can be compared with
   # //remarks: the region it came from, and later exported as review material.
   self.review_dir=''
   # //remarks: Tracks the model that last answered a request; used in the API status tooltip.
   self.last_model=''
   icon_path=asset_path('bluetl.ico')
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
  self.set_api_status(None); self.set_image_status(None)
  # //remarks: All actions sit in one row so every action is visible at once: OCR work first, then
  # //remarks: provider and export work.
  # //remarks: The labels are kept short and every button gets a capped width, so the whole row fits
  # //remarks: the window without the window having to grow. A label that is still too wide wraps onto
  # //remarks: a second line inside its own button instead of being clipped.
  b=QHBoxLayout()
  for text,fn in [('Import',self.images),('Recognize OCR',self.recognize),('Add row',self.add),('Delete row',self.delete),('Translate all',self.all),('Test API',self.test_api),('Export TXT',self.txt),('Export DOCX',self.docx)]:
   q=WrapButton(text); q.clicked.connect(fn); b.addWidget(q)
   # //remarks: Keep the step-specific buttons addressable: recognition is its own action and manual
   # //remarks: row insertion waits for it.
   if text=='Recognize OCR': self.ocr_button=q
   elif text=='Add row': self.add_button=q
   elif text=='Delete row': self.delete_button=q
  v.addLayout(b)
  self.ocr_button.setToolTip('Recognise every text region on the imported images with the local OCR model. This spends no API tokens.')
  self.add_button.setToolTip('Insert an empty row directly below the selected line so you can type the text yourself. Enabled once OCR has run.')
  self.delete_button.setToolTip('Remove the selected row, for example a line the recogniser invented on a textless region.')
  # //remarks: Long OCR/translation lines used to be clipped to one line and hidden behind "...".
  # //remarks: Word wrap on the table plus wrapping items and computed row heights lets the text
  # //remarks: reflow onto multiple lines so nothing is cut off horizontally.
  # //remarks: The Review column shows the suspicion check result, so an invented line is visible in the
  # //remarks: table instead of being trusted silently.
  self.table=QTableWidget(0,5); self.table.setHorizontalHeaderLabels(['Page','Panel','Recognized text','Translation','Review'])
  self.table.setWordWrap(True)
  self.table.setAlternatingRowColors(True)
  self.table.horizontalHeader().setSectionResizeMode(2,QHeaderView.Stretch); self.table.horizontalHeader().setSectionResizeMode(3,QHeaderView.Stretch); self.table.horizontalHeader().setSectionResizeMode(4,QHeaderView.ResizeToContents)
  # //remarks: Re-run height calculation after the user resizes columns, because the amount of
  # //remarks: wrapping depends on the current column width.
  self.table.horizontalHeader().sectionResized.connect(lambda *_: self._fit_rows())
  v.addWidget(self.table)
  # //remarks: Progress row: a determinate bar for batches plus a busy bar for single requests, so a
  # //remarks: long API call never looks like the app has frozen.
  self.progress=QProgressBar(); self.progress.setRange(0,1); self.progress.setValue(0)
  self.progress.setTextVisible(True); self.progress.setFormat('%v/%m'); self.progress.setMaximumHeight(18)
  self.progress.setVisible(False); v.addWidget(self.progress)
  self.status=QLabel('Import images, then click Recognize OCR to load the text lines.')
  # //remarks: Filenames are echoed in status messages, so keep this label plain text: a file named
  # //remarks: with '<' or '&' must never be parsed as rich text markup.
  self.status.setTextFormat(Qt.PlainText); v.addWidget(self.status)
  tabs=QTabWidget(); tabs.addTab(w,'Translator'); about=QWidget(); av=QVBoxLayout(about); av.addWidget(QLabel('<h2>BlueTL</h2><p>Version v1.0</p><p>Published by borneanwingz.fl</p><p>Author: Blue-Wingz @ facedesk</p>')); av.addStretch(); tabs.addTab(about,'About'); self.setCentralWidget(tabs)
  # //remarks: Apply the starting button state once the widgets exist.
  self.update_actions()
 def load(self):
  try:
   d=json.loads(CFG.read_text()); self.url.setText(d.get('url','https://serveras.click/v1')); self.model.setCurrentText(d.get('model',MODELS[0])); self.lang.setCurrentText(d.get('language',LANGS[0])); self.key.setText(unprotect(d.get('api_key','')))
   # //remarks: Keep the remembered path even when the folder is temporarily unavailable: QFileDialog falls
   # //remarks: back safely on its own, while clearing it here made BlueTL forget the last import directory
   # //remarks: after a network drive was disconnected or a removable drive was briefly unavailable.
   saved=str(d.get('last_dir','')).strip()
   self.last_dir=saved
  except (FileNotFoundError,json.JSONDecodeError,OSError): pass
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
  data={'url':self.url.text().strip(),'model':self.model.currentText().strip(),'language':self.lang.currentText(),'api_key':protect(self.key.text()),'last_dir':self.last_dir}
  # //remarks: Write to a temporary file first and then replace the real one, so an interrupted write can
  # //remarks: never leave a truncated config behind. A damaged config would lose the remembered folder
  # //remarks: and every other setting, which is exactly what this backup-and-swap prevents.
  tmp=CFG.with_suffix('.json.tmp')
  tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
  tmp.replace(CFG)
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
 def update_actions(self):
  # //remarks: Single place that decides whether a manually typed row is possible. It stays disabled until
  # //remarks: OCR has run for the current batch, because a new row takes its page and panel number from the
  # //remarks: recognised rows around it, and it is enabled even when recognition found nothing so a batch
  # //remarks: can still be completed by hand. Deleting only needs a row that exists.
  self.add_button.setEnabled(self.recognized)
  self.delete_button.setEnabled(bool(self.rows))
 def ranked(self,selected):
  all_free=[m for m in FREE_MODELS if m != selected]
  return ([selected] if selected else [])+all_free+[m for m in MODELS if m not in FREE_MODELS and m != selected]

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

 def images(self):
  # //remarks: Pass the remembered folder as the dialog's starting directory and remember the folder of the
  # //remarks: selection immediately, so the next import reopens where the user left off.
  selected,_=QFileDialog.getOpenFileNames(self,'Select manga images or archives',self.dialog_dir(),'Manga files (*.jpg *.jpeg *.png *.webp *.zip *.rar)')
  if not selected:return
  # //remarks: Remember the folder of the last imported file, not the first one. A selection can span several
  # //remarks: folders (for example a chapter and its archive in another directory) and the last file is the
  # //remarks: one the user worked with most recently.
  self.last_dir=str(Path(selected[-1]).parent)
  # //remarks: Persist at once so the remembered folder survives an abrupt exit, and never let an unwritable
  # //remarks: settings file abort the import.
  note=''
  try: self.save()
  except Exception as e: note=f' (Settings not saved: {e})'
  self.paths=self.expand_inputs(selected)
  # //remarks: A new import starts a fresh batch. Clear the previous project's OCR and translation rows
  # //remarks: so Translate all runs OCR for the newly selected images instead of reusing old rows.
  self.rows=[]
  # //remarks: The new batch has not been recognised yet, so manual row insertion waits for that step.
  self.recognized=False
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
   self.status.setText(f'Import produced no usable images. Choose JPG, JPEG, PNG, WebP, ZIP, or RAR files.{note}')
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
   engine=MangaOcr(str(model_dir))
   self.rows=[]
   # //remarks: Every recognised region is stored as an image so a suspicious line can be compared with the
   # //remarks: region it came from, and so the pair can be exported later as review material.
   self.review_dir=tempfile.mkdtemp(prefix='bluetl_review_')
   from PIL import Image
   # //remarks: OCR can take a long time per page; a busy bar makes it clear the app is working. Both the
   # //remarks: detector and Manga OCR run on the first page, so the label names both steps.
   self.begin_busy('Detecting text and running OCR...')
   # //remarks: Pages where the detector found no text are collected, so a page that produced no rows
   # //remarks: is reported in the status line instead of looking like a silent success.
   empty_pages=[]
   for page,path in enumerate(self.paths,1):
    # //remarks: Detect every text block on the page with comic-text-detector and recognise each one,
    # //remarks: instead of the old single whole-page call that returned only one line per image.
    try:
     img=Image.open(path); img.load()
     crops=_text_crops(img)
     if not crops: empty_pages.append(Path(path).name)
     self.set_progress(page-1,len(self.paths),f'OCR page {page}/{len(self.paths)}: {Path(path).name} ({len(crops)} region(s))')
     panel=0
     for index,(box,crop) in enumerate(crops,1):
      self.set_progress(page-1,len(self.paths),f'OCR page {page}/{len(self.paths)}, region {index}/{len(crops)}')
      # //remarks: Skip textless crops so the model cannot answer them with invented dialogue.
      if _is_blank(crop): continue
      text=engine(crop).strip()
      if text:
       panel+=1
       # //remarks: Keep the crop beside the text and flag a suspicious result instead of trusting it. A
       # //remarks: flagged row is visible in the Review column and is held back from translation until the
       # //remarks: user approves it by clearing that cell.
       crop_path=str(Path(self.review_dir)/f'p{page:03d}_n{panel:03d}.png')
       try: crop.save(crop_path)
       except (OSError,ValueError): crop_path=''
       reason=_suspicion(crop,text)
       self.rows.append(Row(page,panel,text,crop=crop_path,review='CHECK' if reason else '',reason=reason))
    except (OSError,ValueError) as e:
     # //remarks: One damaged image must not discard OCR results from every other page in the batch.
     empty_pages.append(f'{Path(path).name} (unreadable: {e})')
     continue
   skipped=', '.join(empty_pages)
   note=f' No text detected on page(s): {skipped}.' if empty_pages else ''
   self.refresh(); self.end_progress(f'OCR completed: {len(self.rows)} text region(s) across {len(self.paths)} page(s). Review before translating.{note}')
  except ImportError as e:
   # //remarks: Do not hide the actual dependency that failed. The old generic message said only
   # //remarks: "OCR is not installed", even when one detector dependency failed inside a frozen build.
   self.end_progress('OCR dependency error.')
   QMessageBox.critical(self,'OCR dependency error',f'{type(e).__name__}: {e}\n\n{self.ocr_dependency_hint()}')
  except OSError as e:
   # //remarks: Native DLL load failures are reported separately because Windows often raises OSError,
   # //remarks: not ImportError, when a compiled dependency such as OpenCV or Torch cannot load.
   self.end_progress('OCR native dependency error.')
   QMessageBox.critical(self,'OCR native dependency error',f'{type(e).__name__}: {e}\n\nA compiled component of the local OCR could not load.\n\n{self.ocr_dependency_hint()}')
  # //remarks: Report the resolved model path plus any dictionary path so failures are diagnosable.
  except Exception as e:
   self.end_progress('OCR failed.')
   QMessageBox.critical(self,'OCR failed',f'{type(e).__name__}: {e}\n\nOCR model path: {model_dir}\nDetector model path: {detector_path}')
  finally:
   # //remarks: The OCR step has now run for this batch whatever the outcome, so a batch that found no
   # //remarks: text - or whose model failed to load - can still be finished by typing rows manually.
   self.recognized=True; self.update_actions()
 def region_lines(self,text):
  return [line.strip() for line in text.replace('\\r','').split('\\n') if line.strip()]
 def add(self):
  if not self.recognized:
   return
  # //remarks: Flush cell edits into the model first. Without this, the refresh below rebuilds the table
  # //remarks: from stale rows and silently discards text the user just typed.
  self.sync()
  # //remarks: Insert below the selected line so manual text keeps the surrounding page/panel order.
  selected=self.table.currentRow()
  if selected<0 or selected>=len(self.rows):
   QMessageBox.information(self,'Select a line','Select a recognized line first, then click Add OCR row.')
   return
  source=self.rows[selected]
  row=Row(source.page,source.panel+1,'')
  self.rows.insert(selected+1,row)
  # //remarks: Renumber later rows on the same page so Page/Panel remains ordered after insertion.
  for index in range(selected+2,len(self.rows)):
   if self.rows[index].page==source.page: self.rows[index].panel+=1
  self.refresh(); self.table.setCurrentCell(selected+1,2); self.table.editItem(self.table.item(selected+1,2)); self.update_actions()
 def delete(self):
  # //remarks: Removes the selected line, which is how noise is cleared when the recogniser answers a
  # //remarks: region that holds no text. Page/Panel numbering on the affected page is closed up afterwards.
  self.sync()
  selected=self.table.currentRow()
  if selected<0 or selected>=len(self.rows):
   QMessageBox.information(self,'Select a line','Select the row you want to delete, then click Delete row.')
   return
  page=self.rows.pop(selected).page
  panel=0
  for r in self.rows:
   if r.page==page:
    panel+=1; r.panel=panel
  self.refresh(); self.update_actions()
  if self.rows: self.table.setCurrentCell(min(selected,len(self.rows)-1),0)
  self.status.setText(f'Row deleted. {len(self.rows)} row(s) left in the table.')
 def show_crop(self):
  # //remarks: Opens the source region stored for the selected row, so a flagged line can be compared with
  # //remarks: the image it came from before it is corrected, approved or deleted.
  self.sync()
  selected=self.table.currentRow()
  if selected<0 or selected>=len(self.rows):
   QMessageBox.information(self,'Select a line','Select the row whose source crop you want to inspect.')
   return
  crop=self.rows[selected].crop
  if not crop or not Path(crop).is_file():
   QMessageBox.information(self,'No source crop','This row has no saved source crop. Rows typed by hand have none, and crops are recreated by the next Recognize OCR run.')
   return
  # //remarks: os.startfile hands the image to the user's normal Windows image viewer.
  try: os.startfile(crop)
  except OSError as e: QMessageBox.warning(self,'Cannot open crop',str(e))
 def review_export(self):
  # //remarks: Writes the material needed to measure OCR quality later: the recognized text, the stored crop
  # //remarks: and the review state per row. Correcting the recognized column turns this into a small
  # //remarks: evaluation set, which is what a future detector or model change must be judged against.
  self.sync()
  if not self.rows:
   QMessageBox.information(self,'Nothing to export','Import images and click Recognize OCR first.'); return
  folder=QFileDialog.getExistingDirectory(self,'Export OCR review dataset',self.dialog_dir())
  if not folder:return
  out=Path(folder); crops=out/'crops'; crops.mkdir(parents=True,exist_ok=True)
  records=[]; copied=0
  for index,r in enumerate(self.rows,1):
   name=''
   if r.crop and Path(r.crop).is_file():
    name=f'crop-{index:04d}.png'
    try:
     shutil.copy2(r.crop,crops/name); copied+=1
    except OSError: name=''
   records.append(json.dumps({'page':r.page,'panel':r.panel,'crop':f'crops/{name}' if name else '','recognized':r.jp,'translation':r.tr,'review':r.review,'reason':r.reason},ensure_ascii=False))
  (out/'ocr_review.jsonl').write_text('\n'.join(records)+'\n',encoding='utf-8')
  self.status.setText(f'OCR review set written to {out}: {len(records)} row(s) and {copied} crop image(s).')
 def refresh(self):
  self.table.setRowCount(len(self.rows))
  for i,r in enumerate(self.rows):
   for j,x in enumerate((r.page,r.panel,r.jp,r.tr,r.review)):
    item=QTableWidgetItem(str(x))
    # //remarks: Page/Panel are numeric and stay single-line and centred; text columns wrap. The Review
    # //remarks: column is a marker, so it stays centred and short.
    if j<2 or j==4:
     item.setTextAlignment(Qt.AlignCenter)
    else:
     # //remarks: Long lines must reflow, so allow multi-line layout instead of eliding with "...".
     item.setTextAlignment(Qt.AlignLeft|Qt.AlignTop)
    # //remarks: The reason a row was flagged is shown on hover, so the check is explainable.
    if j==4 and r.reason: item.setToolTip(r.reason)
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
   r.page=int(self.table.item(i,0).text() or 1); r.panel=int(self.table.item(i,1).text() or 1); r.jp=self.table.item(i,2).text(); r.tr=self.table.item(i,3).text(); r.review=self.table.item(i,4).text()
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
  # //remarks: Translate all stays a single click: when nothing has been recognised for the imported batch
  # //remarks: yet, local OCR runs first. Recognizing manually beforehand is therefore optional, and the
  # //remarks: reviewed or edited rows are reused here without repeating OCR: useful when recognition needs
  # //remarks: fixing, or when the user wants to approve the lines before spending translation tokens.
  if self.paths and not self.rows:
   self.ocr()
  self.sync()
  if not self.rows:
   QMessageBox.information(self,'No OCR text','Import images first, or click Recognize OCR to load the recognized lines.'); return
  c=self.client()
  if not c:return
  # //remarks: Do not send rows that already have a translation. Clear a Translation cell to request
  # //remarks: that row again deliberately.
  # //remarks: Suspicious rows are held back until the user reviews and clears the CHECK marker. This is
  # //remarks: the rejection mechanism: uncertain OCR never reaches the paid translation API automatically.
  todo=[r for r in self.rows if r.jp and not r.tr.strip() and not r.review.strip()]
  held=len([r for r in self.rows if r.jp and not r.tr.strip() and r.review.strip()])
  if not todo:
   if held:
    QMessageBox.information(self,'Review needed',f'{held} row(s) are flagged for review and were left untranslated. Compare them with the source region, correct the text, then clear the Review cell to approve a row.')
   else:
    QMessageBox.information(self,'No OCR text','There are no recognised text rows to translate.')
   return
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
   flagged=len([r for r in self.rows if r.jp and not r.tr.strip() and r.review.strip()])
   note=f' {flagged} flagged row(s) still need review.' if flagged else ''
   self.end_progress(f'Translation completed for {len(todo)} row(s).{note}')
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
