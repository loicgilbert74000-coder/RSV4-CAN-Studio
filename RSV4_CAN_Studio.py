import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import re, time, math, queue, threading, os, sys, socket, json, bisect
from collections import Counter, deque
try: import serial
except ImportError: serial=None
from rsv4_signals import SIGNALS

# Palette inspirée de la maquette : fond très sombre, cartes, accents par grandeur
BG="#070d16"; SIDE="#0b1220"; CARD="#111a2a"; CARD2="#1c2739"; BORDER="#23314b"; HOVER="#1f2e47"
TEXT="#eef3fb"; SUB="#9fb0c8"; MUTED="#5d7090"
RED="#e52028"; GREEN="#2fe39a"; CYAN="#3cc0ff"; YELLOW="#ffb938"; ORANGE="#ff8a3d"; VIOLET="#a98bff"; PINK="#ff5fa2"; LIME="#a3e635"
PALETTE=[CYAN,GREEN,YELLOW,ORANGE,VIOLET,PINK,LIME,RED,"#60a5fa","#f472b6","#34d399","#fbbf24"]
FONT="Segoe UI"
SPEEDS={"x0.25":0.25,"x0.5":0.5,"x1":1,"x2":2,"x4":4,"x8":8}
TILE_W=186; TILE_COLS=5
BAND_MIN=56;BAND_MAX=700        # hauteur mini et maxi d'une bande en mode empilé (px)
WINDOWS=[10,30,60,120,300,600]  # fenêtres temporelles des courbes (s)
SEEK_BACK=20000                 # trames rejouées avant l'instant visé quand on clique dans la barre de progression

# Profils de moto. "decoder" : décodages CAN définis pour ce modèle (None = trames brutes seulement).
MODELS={
 "rsv4":{"label":"Aprilia RSV4 Factory 2024","subtitle":"Aprilia RSV4 Factory 2024",
         "decoder":"aprilia","rpm_max":16000,"speed_max":320,"validated":("throttle",),
         "bitrates":["250 kbit/s"],"bitrate":"250 kbit/s",
         "short":"Poignée seule",
         "note":"Seule la poignée de gaz est validée · TPS1 / TPS2 non identifiés dans vos captures"},
 "cbr1000rr_r_2021":{"label":"Honda CBR1000RR-R Fireblade 2021",
         "subtitle":"Honda CBR1000RR-R Fireblade 2021 · 999 cm³ · 217 ch",
         "decoder":None,"rpm_max":15000,"speed_max":300,"validated":(),
         "bitrates":["Non défini"],"bitrate":None,
         "short":"Trames brutes",
         "note":"Aucun décodage CAN défini pour ce modèle · trames brutes uniquement, valeurs non interprétées"},
}

# Signaux générés depuis can1.xml, plus les données de l'ESP32 (GPS et entrées/sorties).
# Les identifiants 0x7F0, 0x7F8 et 0x7F9 ne sont pas dans la définition : ce sont des trames de l'ESP32.
VIRTUAL=[(0x7F0,"GPS Latitude",0,0,0,0,"°"),(0x7F0,"GPS Longitude",0,0,0,0,"°"),
         (0x7F8,"GPS Vitesse",0,0,0,0,"km/h"),(0x7F8,"GPS Cap",0,0,0,0,"°"),
         (0x7F8,"Satellites",0,0,0,0,""),(0x7F8,"Qualité fix",0,0,0,0,"")]+\
        [(0x7F9,f"Entrée {i+1}",0,0,0,0,"") for i in range(8)]+\
        [(0x7F9,f"ADC {j+1}",0,0,0,0,"") for j in range(3)]
TILE_DEFS=list(SIGNALS)+VIRTUAL
BY_CID={}
for _s in SIGNALS: BY_CID.setdefault(_s[0],[]).append(_s)
CURVE_KEYS=list(dict.fromkeys((s[0],s[1]) for s in TILE_DEFS))
CURVE_INDEX={k:i for i,k in enumerate(CURVE_KEYS)}
UNIT_OF={(s[0],s[1]):s[6] for s in TILE_DEFS}

# Groupes d'affichage sur la page Télémétrie
GROUP_OF={0x100:"Moteur",0x114:"Moteur",0x601:"Gaz",0x7F2:"Gaz",0x7F6:"Gaz",0x260:"Roues",
          0x102:"Freins & sécurité",0x261:"Freins & sécurité",0x104:"Modes & aides",0x230:"Modes & aides",
          0x106:"Couple",0x108:"Commandes",0x300:"Commandes",0x174:"IMU · centrale inertielle",
          0x178:"IMU · centrale inertielle",0x262:"IMU · centrale inertielle",0x200:"Températures & électrique",
          0x222:"Carburant & air",0x226:"Clignotants",0x220:"Divers",0x224:"Divers",0x228:"Divers",
          0x382:"Non identifié",0x7F0:"GPS",0x7F8:"GPS",0x7F9:"E/S ESP32"}
GROUP_ORDER=["Moteur","Gaz","Roues","Freins & sécurité","Modes & aides","Couple","IMU · centrale inertielle","GPS",
             "E/S ESP32","Températures & électrique","Carburant & air","Clignotants","Commandes","Divers","Non identifié","Autres"]

# Signaux décodés à la main (décodage de l'appli). Ils remplacent la définition pour ces trames.
HAND_ALWAYS={(0x601,"Hand_Throttle"),(0x7F2,"RSV4_TPS1"),(0x7F2,"RSV4_TPS2")}
HAND_EXPERIMENTAL={(0x100,"RPM"),(0x100,"Gear"),(0x100,"Bike_Speed"),(0x200,"Engine_Temp"),(0x200,"Oil_Temp"),
                   (0x200,"Battery_Volt"),(0x260,"Speed_Front"),(0x260,"Speed_Rear")}
DEFAULT_CURVES=[(0x100,"RPM"),(0x100,"Bike_Speed"),(0x601,"Hand_Throttle"),(0x200,"Engine_Temp"),
                (0x260,"Speed_Front"),(0x260,"Speed_Rear")]

# Exports USB-CAN: NUL between columns; frame ID 8-digit hex, DLC, bytes.
LINE=re.compile(r"Receive\s+(\d{2}:\d{2}:\d{2}:\d{3}).*?(?:Standard|Extended)\s+frame\s+([0-9a-fA-F]{8})\s+([0-8])\s+((?:[0-9a-fA-F]{2}\s*){1,8})",re.I)

# Trame Wi-Fi (ESP32) : 0xA5 0x5A | temps ms (4, LE) | identifiant (4, LE) | DLC (1) | 8 octets | XOR des octets 2 à 18
WIFI_MAGIC=b"\xa5\x5a";WIFI_FRAME_LEN=20

# Paramétrage ESP32 : valeurs par défaut (broches d'un ESP32 DevKit)
DIG_DEFAULT=[(13,"Entrée 1",False),(14,"Entrée 2",False),(27,"Entrée 3",False),(26,"Entrée 4",False),
             (25,"Entrée 5",False),(33,"Entrée 6",False),(18,"Entrée 7",False),(19,"Entrée 8",False)]
ANA_DEFAULT=[(32,"ADC 1",False),(34,"ADC 2",False),(35,"ADC 3",False)]
OUT_DEFAULT=[(2,"Sortie 1","Bas",False),(23,"Sortie 2","Bas",False)]

def load_capture(path):
 out=[]
 with open(path,"r",encoding="latin1",errors="replace") as f:
  for line in f:
   m=LINE.search(line.replace("\x00"," "))
   if not m: continue
   try:
    hh,mm,ss,ms=map(int,m.group(1).split(":"))
    stamp=((hh*60+mm)*60+ss)*1000+ms
    dlc=int(m.group(3)); data=bytes.fromhex(m.group(4))[:dlc]
    if len(data)==dlc:out.append((stamp,int(m.group(2),16),data))
   except ValueError:pass
 if out:
  base=out[0][0]
  out=[((t-base)%86400000,c,d) for t,c,d in out]
 return out

def extract_bits(data,sbit,blen):
 """Lit blen bits à partir de sbit (bit de poids fort en premier, comme la définition AiM)."""
 v=0
 for k in range(blen):
  pos=sbit+k;byte=pos//8
  if byte>=len(data):return None
  v=(v<<1)|((data[byte]>>(7-pos%8))&1)
 return v

def xor_sum(b):
 x=0
 for v in b:x^=v
 return x

def fmt_val(v):
 if v is None:return "—"
 if isinstance(v,int) or float(v).is_integer():return f"{int(round(v)):,}".replace(","," ")
 return f"{v:.2f}".rstrip("0").rstrip(".")

def disp_unit(u):
 return {"C":"°C","gear":""}.get(u,u)

def fmt_time(ms):
 s=max(0,int(ms/1000));return f"{s//60:02d}:{s%60:02d}"
def fmt_ms(ms):
 ms=max(0,int(ms));return f"{ms//60000:02d}:{(ms//1000)%60:02d}.{ms%1000:03d}"

def parse_ids(text):
 """Filtre d'identifiants en hexadécimal : '100, 200-20F'. Renvoie (liste de bornes ou None, valide)."""
 text=text.strip()
 if not text:return None,True
 out=[];ok=True
 for tok in re.split(r"[,;\s]+",text):
  if not tok:continue
  tok=tok.lower().replace("0x","")
  try:
   if "-" in tok:
    a,b=tok.split("-",1);a=int(a,16);b=int(b,16);out.append((min(a,b),max(a,b)))
   else:
    v=int(tok,16);out.append((v,v))
  except ValueError:ok=False
 return (out or None),ok

def nice_ticks(lo,hi,n):
 """Graduations « rondes » entre lo et hi (environ n)."""
 if hi<=lo:return [lo]
 raw=(hi-lo)/max(1,n)
 mag=10**math.floor(math.log10(raw))
 step=next(m*mag for m in (1,2,2.5,5,10) if m*mag>=raw)
 first=math.ceil(lo/step-1e-9);out=[];i=0
 while True:
  v=(first+i)*step
  if v>hi+step*1e-9:break
  out.append(round(v,10));i+=1
 return out

def make_dot(parent,color,bg,size=10):
 c=tk.Canvas(parent,width=size,height=size,bg=bg,highlightthickness=0)
 c.create_oval(1,1,size-1,size-1,fill=color,outline="",tags="d")
 return c
def set_dot(c,color):c.itemconfig("d",fill=color)

def c_str(s):
 return '"'+str(s).replace("\\","\\\\").replace('"','\\"')+'"'

def validate_cfg(cfg):
 """Vérifie la configuration ESP32 ; lève ValueError avec un message lisible."""
 w=cfg["wifi"]
 if not 1<=len(w["ssid"])<=32:raise ValueError("Le nom du réseau (SSID) doit faire entre 1 et 32 caractères.")
 if w["password"] and not 8<=len(w["password"])<=63:raise ValueError("Le mot de passe Wi-Fi doit faire 8 à 63 caractères.")
 if not 1<=w["channel"]<=13:raise ValueError("Le canal Wi-Fi doit être compris entre 1 et 13.")
 if not 1<=w["tcp_port"]<=65535:raise ValueError("Le port TCP doit être compris entre 1 et 65535.")
 pins=[cfg["can"]["tx_pin"],cfg["can"]["rx_pin"]]
 if cfg["gps"]["enabled"]:pins.append(cfg["gps"]["rx_pin"])
 for grp in ("digital_inputs","analog_inputs","outputs"):
  for e in cfg[grp]:
   if e["enabled"]:pins.append(e["pin"])
 for p in pins:
  if not 0<=p<=39:raise ValueError(f"Broche {p} hors plage (0 à 39).")
 if cfg["can"]["bitrate_kbps"] not in (250,500):raise ValueError("Le débit CAN doit être 250 ou 500 kbit/s.")

def make_header(cfg):
 """Fichier rsv4_config.h lu par le firmware ESP32 à la compilation."""
 w,c,g=cfg["wifi"],cfg["can"],cfg["gps"]
 dig,ana,out=cfg["digital_inputs"],cfg["analog_inputs"],cfg["outputs"]
 def arr(vals,ctype):
  return "{"+", ".join(str(v) for v in vals)+"}"
 lines=[
  "// Fichier généré par RSV4 CAN Studio (Paramétrage ESP32). Ne pas modifier à la main.",
  "#pragma once",
  f"#define AP_SSID {c_str(w['ssid'])}",
  f"#define AP_PASS {c_str(w['password'])}",
  f"#define AP_CHANNEL {int(w['channel'])}",
  f"#define TCP_PORT {int(w['tcp_port'])}",
  f"#define CAN_TX_PIN {int(c['tx_pin'])}",
  f"#define CAN_RX_PIN {int(c['rx_pin'])}",
  f"#define CAN_BITRATE_KBPS {int(c['bitrate_kbps'])}",
  f"#define GPS_ENABLED {1 if g['enabled'] else 0}",
  f"#define GPS_RX_PIN {int(g['rx_pin'])}",
  f"#define GPS_BAUD {int(g['baud'])}",
  f"#define DIG_COUNT {len(dig)}",
  f"static const int DIG_PIN[DIG_COUNT] = {arr([e['pin'] for e in dig],'int')};",
  f"static const bool DIG_ON[DIG_COUNT] = {arr([1 if e['enabled'] else 0 for e in dig],'bool')};",
  f"#define ANA_COUNT {len(ana)}",
  f"static const int ANA_PIN[ANA_COUNT] = {arr([e['pin'] for e in ana],'int')};",
  f"static const bool ANA_ON[ANA_COUNT] = {arr([1 if e['enabled'] else 0 for e in ana],'bool')};",
  f"#define OUT_COUNT {len(out)}",
  f"static const int OUT_PIN[OUT_COUNT] = {arr([e['pin'] for e in out],'int')};",
  f"static const bool OUT_ON[OUT_COUNT] = {arr([1 if e['enabled'] else 0 for e in out],'bool')};",
  f"static const bool OUT_HIGH[OUT_COUNT] = {arr([1 if e['level']=='Haut' else 0 for e in out],'bool')};",
 ]
 return "\n".join(lines)+"\n"

class Gauge(tk.Canvas):
 """Jauge circulaire 270° : arc coloré par zone, graduations et valeur au centre."""
 def __init__(self,parent,maximum,unit,ticks,color_fn):
  super().__init__(parent,bg=CARD,highlightthickness=0,height=210)
  self.maximum=maximum;self.unit=unit;self.ticks=ticks;self.color_fn=color_fn
  self.value=None;self.dirty=True
  self.bind("<Configure>",lambda e:self.render())
 def set(self,value):self.value=value;self.dirty=True
 def set_scale(self,maximum,ticks):self.maximum=maximum;self.ticks=ticks;self.dirty=True
 def flush(self):
  if self.dirty:self.dirty=False;self.render()
 def render(self):
  self.delete("all");w=max(160,self.winfo_width());h=max(140,self.winfo_height())
  r=min(w*.42,h*.62);cx=w/2;cy=h/2+r*.12;th=max(8,int(r*.12))
  start=225;sweep=-270;box=(cx-r,cy-r,cx+r,cy+r)
  self.create_arc(*box,start=start,extent=sweep,style="arc",outline=CARD2,width=th)
  if self.value is not None:
   frac=max(0,min(1,float(self.value)/self.maximum));n=int(frac*60)+1
   for i in range(n):
    f0=i/60;f1=min(frac,(i+1)/60)
    if f1<=f0+1e-9:continue
    self.create_arc(*box,start=start+sweep*f0,extent=sweep*(f1-f0),style="arc",outline=self.color_fn((f0+f1)/2),width=th)
  ri=r-th/2-3
  for i in range(41):
   a=math.radians(start+sweep*i/40);major=(i%5==0)
   r2=ri-(th*.9 if major else th*.4)
   self.create_line(cx+ri*math.cos(a),cy-ri*math.sin(a),cx+r2*math.cos(a),cy-r2*math.sin(a),fill=SUB if major else MUTED,width=2 if major else 1)
  for frac,label in self.ticks:
   a=math.radians(start+sweep*frac);lr=ri-th*2.2
   self.create_text(cx+lr*math.cos(a),cy-lr*math.sin(a),text=label,fill=SUB,font=(FONT,max(8,int(r*.08)),"bold"))
  val="—" if self.value is None else f"{self.value:,.0f}".replace(","," ")
  self.create_text(cx,cy-r*.08,text=val,fill=TEXT,font=(FONT,max(14,int(r*.24)),"bold"))
  self.create_text(cx,cy+r*.22,text=self.unit,fill=SUB,font=(FONT,max(8,int(r*.1))))

class Bar(tk.Canvas):
 """Barre fine proportionnelle à la valeur entre lo et hi."""
 def __init__(self,parent,color,lo,hi,height=8):
  super().__init__(parent,height=height,bg=CARD,highlightthickness=0)
  self.color=color;self.lo=lo;self.hi=hi;self.frac=None;self.dirty=True
  self.bind("<Configure>",lambda e:self.render())
 def set(self,value):
  self.frac=None if value is None else max(0,min(1,(float(value)-self.lo)/(self.hi-self.lo)))
  self.dirty=True
 def flush(self):
  if self.dirty:self.dirty=False;self.render()
 def render(self):
  self.delete("all");w=max(20,self.winfo_width());h=int(self.cget("height"))
  self.create_rectangle(0,0,w,h,fill=CARD2,outline="")
  if self.frac is not None:self.create_rectangle(0,0,w*self.frac,h,fill=self.color,outline="")

class GearBox(tk.Canvas):
 """Rangée N 1 2 3 4 5 6 avec le rapport engagé en surbrillance."""
 LABELS=["N","1","2","3","4","5","6"]
 def __init__(self,parent,height=40):
  super().__init__(parent,height=height,bg=CARD,highlightthickness=0)
  self.gear=None;self.dirty=True
  self.bind("<Configure>",lambda e:self.render())
 def set(self,gear):self.gear=gear;self.dirty=True
 def flush(self):
  if self.dirty:self.dirty=False;self.render()
 def render(self):
  self.delete("all");w=max(60,self.winfo_width());h=int(self.cget("height"));cw=w/len(self.LABELS)
  for i,label in enumerate(self.LABELS):
   x0=i*cw+2;x1=(i+1)*cw-2;on=(self.gear==i)
   self.create_rectangle(x0,3,x1,h-3,fill=RED if on else CARD2,outline="")
   self.create_text((x0+x1)/2,h/2,text=label,fill=TEXT if on else MUTED,font=(FONT,10,"bold"))

class SeekBar(tk.Canvas):
 """Barre de progression cliquable : un clic ou un glissement choisit l'instant de lecture."""
 def __init__(self,parent,on_seek,on_drag=None,width=300,height=22):
  super().__init__(parent,width=width,height=height,bg=CARD,highlightthickness=0,cursor="hand2")
  self.frac=0;self.on_seek=on_seek;self.on_drag=on_drag;self.dragging=False
  self.bind("<Configure>",lambda e:self.render())
  self.bind("<ButtonPress-1>",self.press);self.bind("<B1-Motion>",self.move);self.bind("<ButtonRelease-1>",self.release)
 def set(self,frac):
  if not self.dragging:self.frac=max(0,min(1,frac));self.render()
 def _f(self,e):
  return max(0,min(1,(e.x-8)/max(1,self.winfo_width()-16)))
 def press(self,e):
  self.dragging=True;self.frac=self._f(e);self.render()
  if self.on_drag:self.on_drag(self.frac)
 def move(self,e):
  if self.dragging:
   self.frac=self._f(e);self.render()
   if self.on_drag:self.on_drag(self.frac)
 def release(self,e):
  if self.dragging:
   self.dragging=False;self.frac=self._f(e);self.render();self.on_seek(self.frac)
 def render(self):
  self.delete("all");w=max(40,self.winfo_width());h=max(10,self.winfo_height());cy=h/2
  x0=8;x1=w-8;xf=x0+(x1-x0)*self.frac
  self.create_rectangle(x0,cy-3,x1,cy+3,fill=CARD2,outline="")
  self.create_rectangle(x0,cy-3,xf,cy+3,fill=RED,outline="")
  self.create_oval(xf-7,cy-7,xf+7,cy+7,fill=TEXT,outline=RED,width=2)

class App:
 def __init__(self):
  self.root=tk.Tk();self.root.title("RSV4 CAN Studio · Diagnostic & Télémétrie CAN")
  self.root.geometry("1536x960");self.root.minsize(1280,860);self.root.configure(bg=BG)
  self.frames=[];self.idx=0;self.playing=False;self.speed=tk.DoubleVar(value=1.0)
  self.status=tk.StringVar(value="Prêt · ouvrez une capture")
  self.file_name=tk.StringVar(value="Aucun fichier")
  self.clock=tk.StringVar(value="00:00 / 00:00");self.progress=tk.DoubleVar(value=0)
  self.transport=tk.StringVar(value="USB-CAN (série)")
  self.port=tk.StringVar(value="COM7");self.baud=tk.StringVar(value="2000000")
  self.host=tk.StringVar(value="192.168.4.1");self.tcp_port=tk.StringVar(value="2323")
  self.experimental=tk.BooleanVar(value=True);self.filter_on=tk.BooleanVar(value=True)
  self.window=tk.IntVar(value=60);self.stack=tk.BooleanVar(value=False)
  self.sel=set(DEFAULT_CURVES);self.curve_btns={}
  self.count=Counter();self.first_t={};self.last_t={}
  self.vals={};self.hist={};self.dirty=set();self.flash_until={};self.tiles={}
  self.track=deque(maxlen=30000)
  self.t_now=0;self.recent=deque();self.ingested=0;self.t_last=0;self.t0=0;self.last_row=None
  self.start_wall=0;self.start_frame=0;self.q=queue.Queue();self.live=False;self.stop_event=threading.Event()
  self.cards={};self.pages={};self.nav={};self.flushables=[];self.srow={};self.fl={};self.badge={}
  self.decoder=None;self.model_key="rsv4"
  self.rows=deque(maxlen=8000);self.matched=0;self.bulk=False
  self.f_show=tk.StringVar();self.f_hide=tk.StringVar();self.f_text=tk.StringVar()
  self.id_show=None;self.id_hide=None;self.ftext="";self._fid=None;self.count_text=""
  self.frame_times=[];self.seek_target=None;self.seek_resume=False
  self.view_end=None;self.ref_key=None;self.band_h={};self.grips=[];self.layout=[];self.legend_hits=[];self.drag=None
  self.default_band=120;self.current_page="tele"
  self.side_collapsed=False;self.auto_collapsed=False
  self.cv={};self.build_esp_vars()
  self.set_styles()
  self.build_footer()
  self.build_sidebar()
  self.build_main()
  self.apply_model("rsv4")
  self.show_page("tele")
  self.set_conn_ui(False,"Déconnecté")
  self.set_state("Prêt · ouvrez une capture",MUTED)
  self.root.after(40,self.tick);self.root.after(180,self.paint_chart);self.root.after(400,self.paint_map)
  base=getattr(sys,"_MEIPASS",os.path.dirname(os.path.abspath(__file__)))
  bundled=os.path.join(base,"CAPTURE_GAZ_RSV4.txt")
  if os.path.exists(bundled):self.load(bundled)

 # ---------- modèle ----------
 @property
 def model(self):return MODELS[self.model_key]

 def apply_model(self,key):
  self.model_key=key;m=MODELS[key];self.decoder=m["decoder"]
  self.subtitle.config(text=m["subtitle"]);self.footnote.config(text="   "+m["note"])
  n=m["rpm_max"]//1000
  self.rpm.set_scale(m["rpm_max"],[(k/n,str(k)) for k in range(0,n+1,2)])
  self.speedg.set_scale(m["speed_max"],[(i/4,str(int(m["speed_max"]*i/4))) for i in range(5)])
  for k in ("front","rear"):self.cards[k][1].hi=m["speed_max"];self.cards[k][1].dirty=True
  for k in self.badge:
   state,color=self.badge_state(k);self.badge[k].config(text=state,fg=color)
  self.bitrate_cb.config(values=m["bitrates"]);self.bitrate_cb.current(0)
  self.model_cb.current(list(MODELS).index(key))
  self.bus_note.config(text=("Décodage : définition can1.xml · valeurs à valider" if self.decoder
                             else "Aucun décodage pour cette moto · voir « Trames CAN »"))
  self.clear_data()

 def badge_state(self,key):
  if self.decoder is None:return "NON DÉCODÉ",MUTED
  if key in self.model["validated"]:return "VALIDÉ",GREEN
  return "À VALIDER",YELLOW

 def on_model(self,e=None):
  key=list(MODELS)[self.model_cb.current()]
  if self.live:self.disconnect()
  self.pause();self.apply_model(key)
  if self.frames:self.set_state(f"Modèle : {self.model['label']}",SUB)

 # ---------- style & widgets ----------
 def set_styles(self):
  s=ttk.Style();s.theme_use("clam")
  s.configure("Treeview",background=CARD,foreground=TEXT,fieldbackground=CARD,rowheight=24,borderwidth=0,relief="flat",bordercolor=CARD,lightcolor=CARD,darkcolor=CARD,font=(FONT,9))
  s.configure("Treeview.Heading",background=CARD2,foreground=SUB,relief="flat",font=(FONT,8,"bold"),padding=5)
  s.map("Treeview",background=[("selected",HOVER)],foreground=[("selected",TEXT)])
  s.map("Treeview.Heading",background=[("active",HOVER)])
  s.configure("Vertical.TScrollbar",background=CARD2,troughcolor=CARD,bordercolor=CARD,arrowcolor=SUB,lightcolor=CARD2,darkcolor=CARD2)
  s.configure("Horizontal.TScrollbar",background=CARD2,troughcolor=CARD,bordercolor=CARD,arrowcolor=SUB,lightcolor=CARD2,darkcolor=CARD2)
  s.configure("TCombobox",fieldbackground=CARD2,background=CARD2,foreground=TEXT,arrowcolor=SUB,bordercolor=BORDER,lightcolor=CARD2,darkcolor=CARD2,padding=3)
  s.map("TCombobox",fieldbackground=[("readonly",CARD2)],foreground=[("readonly",TEXT)],selectbackground=[("readonly",CARD2)],selectforeground=[("readonly",TEXT)])
  s.configure("Rsv.Horizontal.TProgressbar",troughcolor=CARD2,background=RED,bordercolor=CARD2,lightcolor=RED,darkcolor=RED,thickness=5)

 def card(self,parent):
  return tk.Frame(parent,bg=CARD,highlightbackground=BORDER,highlightthickness=1,bd=0)

 def reg(self,widget):
  self.flushables.append(widget);return widget

 def button(self,parent,text,command,color=TEXT,bg=CARD2,anchor="center",font=10):
  b=tk.Button(parent,text=text,command=command,bg=bg,fg=color,activebackground=HOVER,activeforeground=TEXT,
              relief="flat",bd=0,highlightthickness=0,padx=10,pady=7,font=(FONT,font,"bold"),cursor="hand2",anchor=anchor)
  b.bind("<Enter>",lambda e:b.config(bg=HOVER));b.bind("<Leave>",lambda e:b.config(bg=bg))
  return b

 def section(self,parent,text):
  tk.Label(parent,text=text,fg=MUTED,bg=SIDE,font=(FONT,8,"bold")).pack(anchor="w",padx=20,pady=(14,4))

 def nav_item(self,parent,key,label):
  row=tk.Frame(parent,bg=SIDE,cursor="hand2");row.pack(fill="x",padx=10,pady=1)
  bar=tk.Frame(row,bg=SIDE,width=4);bar.pack(side="left",fill="y")
  lbl=tk.Label(row,text=label,bg=SIDE,fg=TEXT,font=(FONT,11,"bold"),anchor="w",padx=16,pady=9,cursor="hand2")
  lbl.pack(side="left",fill="x",expand=True)
  def go(e=None,k=key):
   if k=="settings":self.settings()
   else:self.show_page(k)
  for w in (row,bar,lbl):w.bind("<Button-1>",go)
  self.nav[key]=(row,bar,lbl)

 def scroll_area(self,parent,bg,width=None):
  """Zone défilable verticalement : renvoie (conteneur à placer, cadre intérieur à remplir)."""
  wrap=tk.Frame(parent,bg=bg)
  canvas=tk.Canvas(wrap,bg=bg,highlightthickness=0,width=width or 300)
  sb=ttk.Scrollbar(wrap,orient="vertical",command=canvas.yview)
  canvas.configure(yscrollcommand=sb.set)
  inner=tk.Frame(canvas,bg=bg)
  win=canvas.create_window((0,0),window=inner,anchor="nw")
  inner.bind("<Configure>",lambda e:canvas.configure(scrollregion=canvas.bbox("all")))
  canvas.bind("<Configure>",lambda e:canvas.itemconfigure(win,width=e.width))
  def wheel(e):canvas.yview_scroll(int(-e.delta/120),"units")
  canvas.bind("<Enter>",lambda e:canvas.bind_all("<MouseWheel>",wheel))
  canvas.bind("<Leave>",lambda e:canvas.unbind_all("<MouseWheel>"))
  canvas.pack(side="left",fill="both",expand=True);sb.pack(side="right",fill="y")
  return wrap,inner

 # ---------- structure ----------
 def build_footer(self):
  foot=tk.Frame(self.root,bg=SIDE,highlightbackground=BORDER,highlightthickness=1);foot.pack(side="bottom",fill="x")
  self.fl["dot"]=make_dot(foot,MUTED,SIDE,10);self.fl["dot"].pack(side="left",padx=(16,8),pady=10)
  tk.Label(foot,textvariable=self.status,fg=SUB,bg=SIDE,font=(FONT,9,"bold")).pack(side="left")
  self.footnote=tk.Label(foot,text="",fg=YELLOW,bg=SIDE,font=(FONT,9));self.footnote.pack(side="left")
  self.fl["dur"]=self.stat(foot,"Durée","00:00")
  self.fl["ids"]=self.stat(foot,"ID actifs","0")
  self.fl["rate"]=self.stat(foot,"Trames/s","—")
  self.fl["frames"]=self.stat(foot,"Trames reçues","0")
  rec=tk.Frame(foot,bg=SIDE);rec.pack(side="right",padx=14)
  make_dot(rec,MUTED,SIDE,10).pack(side="left",padx=(0,6))
  tk.Label(rec,text="Enregistrement : non disponible",fg=MUTED,bg=SIDE,font=(FONT,9,"bold")).pack(side="left")

 def stat(self,parent,label,value):
  box=tk.Frame(parent,bg=SIDE);box.pack(side="right",padx=14,pady=6)
  tk.Label(box,text=label.upper(),fg=MUTED,bg=SIDE,font=(FONT,7,"bold")).pack(anchor="e")
  lbl=tk.Label(box,text=value,fg=TEXT,bg=SIDE,font=(FONT,10,"bold"));lbl.pack(anchor="e")
  return lbl

 def build_sidebar(self):
  side=tk.Frame(self.root,bg=SIDE,width=250,highlightbackground=BORDER,highlightthickness=1)
  side.pack(side="left",fill="y");side.pack_propagate(False)
  self.side=side
  strip=tk.Frame(self.root,bg=SIDE,width=36,highlightbackground=BORDER,highlightthickness=1);strip.pack_propagate(False)
  tk.Button(strip,text="»",command=self.toggle_side,bg=SIDE,fg=TEXT,activebackground=HOVER,activeforeground=TEXT,relief="flat",bd=0,
            highlightthickness=0,font=(FONT,14,"bold"),cursor="hand2").pack(pady=(12,0),fill="x")
  self.side_strip=strip
  tk.Button(side,text="«",command=self.toggle_side,bg=SIDE,fg=SUB,activebackground=HOVER,activeforeground=TEXT,relief="flat",bd=0,
            highlightthickness=0,font=(FONT,13,"bold"),cursor="hand2").place(relx=1.0,x=-8,y=10,anchor="ne")
  logo=tk.Frame(side,bg=SIDE);logo.pack(fill="x",padx=20,pady=(20,6))
  tk.Label(logo,text="RSV4",fg=RED,bg=SIDE,font=(FONT,30,"bold italic")).pack(anchor="w")
  tk.Label(logo,text="CAN STUDIO",fg=TEXT,bg=SIDE,font=(FONT,11,"bold")).pack(anchor="w")

  self.section(side,"MOTO")
  mc=tk.Frame(side,bg=SIDE);mc.pack(fill="x",padx=14,pady=2)
  self.model_cb=ttk.Combobox(mc,values=[m["label"] for m in MODELS.values()],state="readonly",font=(FONT,9))
  self.model_cb.pack(fill="x");self.model_cb.bind("<<ComboboxSelected>>",self.on_model)

  self.section(side,"NAVIGATION")
  self.nav_item(side,"tele","Télémétrie")
  self.nav_item(side,"graph","Courbes")
  self.nav_item(side,"frames","Trames CAN")
  self.nav_item(side,"esp","Paramétrage ESP32")
  self.nav_item(side,"settings","Paramètres")

  self.section(side,"CONNEXION")
  card=self.card(side);card.pack(fill="x",padx=14,pady=2)
  inner=tk.Frame(card,bg=CARD);inner.pack(fill="x",padx=12,pady=8)
  def row(label,widget):
   r=tk.Frame(inner,bg=CARD)
   tk.Label(r,text=label,bg=CARD,fg=SUB,font=(FONT,9),anchor="w",width=12).pack(side="left")
   widget(r).pack(side="right")
   return r
  tr=tk.Frame(inner,bg=CARD);tr.pack(fill="x",pady=2)
  tk.Label(tr,text="Source",bg=CARD,fg=SUB,font=(FONT,9),anchor="w",width=12).pack(side="left")
  self.transport_cb=ttk.Combobox(tr,textvariable=self.transport,values=["USB-CAN (série)","Wi-Fi ESP32"],state="readonly",width=15)
  self.transport_cb.pack(side="right");self.transport_cb.bind("<<ComboboxSelected>>",self.on_transport)
  row("Mode CAN",lambda p:self.ro_combo(p,["Silent (écoute)"])).pack(fill="x",pady=2)
  row("Type trame",lambda p:self.ro_combo(p,["Standard 11 bits"])).pack(fill="x",pady=2)
  r_port=row("Port COM",lambda p:ttk.Combobox(p,textvariable=self.port,values=[f"COM{i}" for i in range(1,21)],width=13))
  r_baud=row("Vitesse",lambda p:ttk.Combobox(p,textvariable=self.baud,values=["2000000","1000000","500000","250000"],width=13))
  r_br=tk.Frame(inner,bg=CARD)
  tk.Label(r_br,text="CAN bitrate",bg=CARD,fg=SUB,font=(FONT,9),anchor="w",width=12).pack(side="left")
  self.bitrate_cb=ttk.Combobox(r_br,state="readonly",width=13);self.bitrate_cb.pack(side="right")
  self.serial_rows=[r_port,r_baud,r_br]
  entry=lambda p,var:tk.Entry(p,textvariable=var,width=14,bg=CARD2,fg=TEXT,insertbackground=TEXT,relief="flat",highlightbackground=BORDER,highlightthickness=1)
  r_host=row("Adresse ESP32",lambda p:entry(p,self.host))
  r_tcp=row("Port TCP",lambda p:entry(p,self.tcp_port))
  self.wifi_rows=[r_host,r_tcp]
  st=tk.Frame(inner,bg=CARD);st.pack(fill="x",pady=(8,6))
  self.conn_status=st
  self.conn_dot=make_dot(st,MUTED,CARD,10);self.conn_dot.pack(side="left",padx=(2,6))
  self.conn_lbl=tk.Label(st,text="Déconnecté",bg=CARD,fg=SUB,font=(FONT,10,"bold"));self.conn_lbl.pack(side="left")
  self.conn_btn=tk.Button(inner,text="Connecter",command=self.toggle_connect,bg=RED,fg="#ffffff",activebackground="#ff3b44",
                          activeforeground="#ffffff",relief="flat",bd=0,highlightthickness=0,font=(FONT,10,"bold"),cursor="hand2",pady=6)
  self.conn_btn.pack(fill="x")
  self.on_transport()

 def on_transport(self,e=None):
  wifi=self.transport.get().startswith("Wi-Fi")
  for r in self.serial_rows+self.wifi_rows:r.pack_forget()
  for r in (self.wifi_rows if wifi else self.serial_rows):r.pack(fill="x",pady=2,before=self.conn_status)

 def ro_combo(self,parent,values):
  c=ttk.Combobox(parent,values=values,state="readonly",width=15);c.current(0);return c

 def build_main(self):
  main=tk.Frame(self.root,bg=BG);main.pack(side="left",fill="both",expand=True)
  self.main=main
  head=tk.Frame(main,bg=BG);head.pack(fill="x",padx=22,pady=(14,4))
  tabs=tk.Frame(head,bg=BG);tabs.pack(side="right")
  self.tabs={}
  for key,label in [("tele","Télémétrie"),("graph","Courbes"),("frames","Trames CAN"),("esp","ESP32")]:
   b=tk.Button(tabs,text=label,command=lambda k=key:self.show_page(k),relief="flat",bd=0,highlightthickness=0,
               padx=12,pady=6,font=(FONT,9,"bold"),cursor="hand2");b.pack(side="left",padx=2);self.tabs[key]=b
  tk.Label(head,text="Diagnostic & Télémétrie CAN",fg=TEXT,bg=BG,font=(FONT,18,"bold")).pack(side="left")
  self.subtitle=tk.Label(head,text="",fg=SUB,bg=BG,font=(FONT,11));self.subtitle.pack(side="left",padx=(14,0),pady=(6,0))
  self.build_playbar(main)
  self.area=tk.Frame(main,bg=BG);self.area.pack(fill="both",expand=True,padx=18,pady=(0,10))
  self.page_tele=tk.Frame(self.area,bg=BG)
  self.page_graph=tk.Frame(self.area,bg=BG)
  self.page_frames=tk.Frame(self.area,bg=BG)
  self.page_esp=tk.Frame(self.area,bg=BG)
  self.pages={"tele":self.page_tele,"graph":self.page_graph,"frames":self.page_frames,"esp":self.page_esp}
  self.build_tele(self.page_tele)
  self.build_graph(self.page_graph)
  self.build_table(self.page_frames)
  self.build_esp(self.page_esp)

 def build_playbar(self,main):
  bar=tk.Frame(main,bg=CARD,highlightbackground=BORDER,highlightthickness=1);bar.pack(fill="x",padx=18,pady=(4,8))
  inner=tk.Frame(bar,bg=CARD);inner.pack(fill="x",padx=12,pady=8)
  self.button(inner,"Ouvrir un fichier .txt",self.open_file,TEXT,CARD2,font=9).pack(side="left",padx=2)
  self.button(inner,"Lecture",self.play,GREEN,CARD2,font=9).pack(side="left",padx=2)
  self.button(inner,"Pause",self.pause,YELLOW,CARD2,font=9).pack(side="left",padx=2)
  self.button(inner,"Début",self.reset,SUB,CARD2,font=9).pack(side="left",padx=2)
  tk.Label(inner,text="Vitesse",bg=CARD,fg=SUB,font=(FONT,9)).pack(side="left",padx=(14,4))
  cb=ttk.Combobox(inner,values=list(SPEEDS),state="readonly",width=6);cb.set("x1");cb.pack(side="left")
  cb.bind("<<ComboboxSelected>>",lambda e:self.speed.set(SPEEDS[cb.get()]))
  tk.Label(inner,textvariable=self.file_name,bg=CARD,fg=SUB,font=(FONT,9),anchor="w").pack(side="left",padx=(14,0))
  tk.Label(inner,textvariable=self.clock,bg=CARD,fg=TEXT,font=(FONT,9,"bold")).pack(side="right",padx=(8,0))
  self.seekbar=SeekBar(inner,on_seek=self.seek,on_drag=self.on_seek_drag,width=360);self.seekbar.pack(side="right",padx=8)

 def show_page(self,key):
  for p in self.pages.values():p.pack_forget()
  self.pages[key].pack(fill="both",expand=True)
  self.current_page=key
  for k,(row,bar,lbl) in self.nav.items():
   on=(k==key)
   row.config(bg=HOVER if on else SIDE);bar.config(bg=RED if on else SIDE)
   lbl.config(bg=HOVER if on else SIDE,fg=TEXT if on else SUB)
  for k,b in self.tabs.items():
   b.config(bg=RED if k==key else CARD2,fg="#ffffff" if k==key else SUB,activebackground=HOVER,activeforeground=TEXT)
  if key=="graph":self.collapse_side(auto=True)
  elif self.auto_collapsed:self.expand_side()

 def collapse_side(self,auto=False):
  if self.side_collapsed:return
  self.side.pack_forget();self.side_strip.pack(side="left",fill="y",before=self.main)
  self.side_collapsed=True;self.auto_collapsed=auto

 def expand_side(self):
  if not self.side_collapsed:return
  self.side_strip.pack_forget();self.side.pack(side="left",fill="y",before=self.main)
  self.side_collapsed=False;self.auto_collapsed=False

 def toggle_side(self):
  if self.side_collapsed:self.expand_side()
  else:self.collapse_side(auto=False)

 # ---------- page Télémétrie ----------
 def build_tele(self,parent):
  top=tk.Frame(parent,bg=BG);top.pack(fill="x")
  self.build_top(top)
  head=tk.Frame(parent,bg=BG);head.pack(fill="x",pady=(10,2))
  tk.Label(head,text="Toutes les données de télémétrie",fg=TEXT,bg=BG,font=(FONT,13,"bold")).pack(side="left")
  self.bus_note=tk.Label(head,text="",fg=SUB,bg=BG,font=(FONT,9));self.bus_note.pack(side="left",padx=12)
  wrap,inner=self.scroll_area(parent,BG)
  wrap.pack(fill="both",expand=True,pady=(2,0))
  groups={}
  for s in TILE_DEFS:groups.setdefault(GROUP_OF.get(s[0],"Autres"),[]).append(s)
  for g in dict.fromkeys(GROUP_ORDER+list(groups)):
   if g not in groups:continue
   tk.Label(inner,text=g.upper(),fg=MUTED,bg=BG,font=(FONT,8,"bold"),anchor="w").pack(fill="x",pady=(12,2))
   grid=tk.Frame(inner,bg=BG);grid.pack(fill="x")
   for i,s in enumerate(groups[g]):
    self.make_tile(grid,s).grid(row=i//TILE_COLS,column=i%TILE_COLS,padx=5,pady=5,sticky="nw")

 def make_tile(self,parent,s):
  cid,name,_,_,_,_,unit=s
  f=tk.Frame(parent,bg=CARD,highlightbackground=BORDER,highlightthickness=1,width=TILE_W,height=96)
  f.pack_propagate(False)
  nl=tk.Label(f,text=name.replace("_"," "),fg=SUB,bg=CARD,font=(FONT,8,"bold"),anchor="w");nl.pack(fill="x",padx=10,pady=(8,0))
  row=tk.Frame(f,bg=CARD);row.pack(anchor="w",padx=10)
  vl=tk.Label(row,text="—",fg=TEXT,bg=CARD,font=(FONT,18,"bold"));vl.pack(side="left")
  if unit:tk.Label(row,text=disp_unit(unit),fg=MUTED,bg=CARD,font=(FONT,9)).pack(side="left",padx=(5,0),pady=(9,0))
  sl=tk.Label(f,text=f"0x{cid:03X}",fg=MUTED,bg=CARD,font=(FONT,7,"bold"),anchor="w")
  sl.pack(side="bottom",fill="x",padx=10,pady=(0,6))
  self.tiles[(cid,name)]=(f,vl,sl,nl)
  return f

 def put(self,cid,name,val,t,src):
  """Enregistre une valeur : valeur courante, historique pour les courbes, mise à jour de la tuile."""
  key=(cid,name);self.vals[key]=(val,src)
  h=self.hist.get(key)
  if h is None:h=self.hist[key]=deque(maxlen=20000)
  h.append((t,val));self.dirty.add(key)

 def refresh_tile(self,key):
  f,vl,sl,nl=self.tiles[key];val,src=self.vals[key]
  vl.config(text=fmt_val(val))
  if src=="def":sl.config(text=f"0x{key[0]:03X} · définition",fg=MUTED)
  elif src=="valid":sl.config(text=f"0x{key[0]:03X} · validé",fg=GREEN)
  elif src=="esp":sl.config(text=f"0x{key[0]:03X} · ESP32",fg=CYAN)
  else:sl.config(text=f"0x{key[0]:03X} · app · à valider",fg=YELLOW)
  vl.config(fg=CYAN);self.flash_until[key]=time.monotonic()+.3

 def mcard(self,parent,key,label,unit,color,lo,hi):
  f=self.card(parent)
  tk.Label(f,text=label,fg=SUB,bg=CARD,font=(FONT,8,"bold"),anchor="w").pack(fill="x",padx=12,pady=(10,0))
  row=tk.Frame(f,bg=CARD);row.pack(anchor="w",padx=12,pady=(2,4))
  val=tk.Label(row,text="—",fg=TEXT,bg=CARD,font=(FONT,18,"bold"));val.pack(side="left")
  if unit:tk.Label(row,text=unit,fg=MUTED,bg=CARD,font=(FONT,10)).pack(side="left",padx=(4,0),pady=(8,0))
  self.badge[key]=tk.Label(f,text="",fg=YELLOW,bg=CARD,font=(FONT,7,"bold"),anchor="w");self.badge[key].pack(fill="x",padx=12)
  bar=self.reg(Bar(f,color,lo,hi));bar.pack(fill="x",padx=12)
  sc=tk.Frame(f,bg=CARD);sc.pack(fill="x",padx=12,pady=(3,8))
  tk.Label(sc,text=str(lo),fg=MUTED,bg=CARD,font=(FONT,7)).pack(side="left")
  tk.Label(sc,text=str(hi),fg=MUTED,bg=CARD,font=(FONT,7)).pack(side="right")
  self.cards[key]=(val,bar)
  return f

 def show(self,key,num,text=None):
  val,bar=self.cards[key]
  if num is None:val.config(text="—")
  else:val.config(text=text if text is not None else f"{num:.0f}")
  bar.set(num)

 def build_top(self,parent):
  right=tk.Frame(parent,bg=BG,width=270);right.pack(side="right",fill="y",padx=(10,0));right.pack_propagate(False)
  left=tk.Frame(parent,bg=BG);left.pack(side="left",fill="both",expand=True)
  for c in range(7):left.columnconfigure(c,weight=1,uniform="c")
  left.rowconfigure(0,minsize=240);left.rowconfigure(1,minsize=150)

  g=self.card(left);g.grid(row=0,column=0,columnspan=2,rowspan=2,sticky="nsew",padx=4,pady=4)
  tk.Label(g,text="Régime moteur",fg=SUB,bg=CARD,font=(FONT,9,"bold")).pack(anchor="w",padx=14,pady=(10,0))
  self.badge["rpm"]=tk.Label(g,text="",fg=YELLOW,bg=CARD,font=(FONT,7,"bold"));self.badge["rpm"].pack(anchor="w",padx=14)
  self.rpm=self.reg(Gauge(g,16000,"tr/min",[],lambda f:GREEN if f<.5 else (YELLOW if f<.8 else RED)))
  self.rpm.pack(fill="both",expand=True,padx=6,pady=(0,6))

  s=self.card(left);s.grid(row=0,column=2,columnspan=2,sticky="nsew",padx=4,pady=4)
  tk.Label(s,text="Vitesse moto",fg=SUB,bg=CARD,font=(FONT,9,"bold")).pack(anchor="w",padx=14,pady=(10,0))
  self.badge["speed"]=tk.Label(s,text="",fg=YELLOW,bg=CARD,font=(FONT,7,"bold"));self.badge["speed"].pack(anchor="w",padx=14)
  self.speedg=self.reg(Gauge(s,320,"km/h",[],lambda f:CYAN))
  self.speedg.pack(fill="both",expand=True,padx=6,pady=(0,6))

  gc=self.card(left);gc.grid(row=0,column=4,sticky="nsew",padx=4,pady=4)
  tk.Label(gc,text="Rapport engagé",fg=SUB,bg=CARD,font=(FONT,8,"bold"),anchor="w").pack(fill="x",padx=12,pady=(10,0))
  gt=tk.Frame(gc,bg=CARD);gt.pack(fill="x",padx=12,pady=(0,4))
  self.gear_val=tk.Label(gt,text="—",fg=TEXT,bg=CARD,font=(FONT,30,"bold"));self.gear_val.pack(side="left")
  self.badge["gear"]=tk.Label(gt,text="",fg=YELLOW,bg=CARD,font=(FONT,7,"bold"));self.badge["gear"].pack(side="left",anchor="s",padx=(8,0),pady=(0,10))
  self.gear=self.reg(GearBox(gc,height=36));self.gear.pack(fill="x",padx=8,pady=(0,10))

  gz=self.card(left);gz.grid(row=0,column=5,columnspan=2,sticky="nsew",padx=4,pady=4)
  zt=tk.Frame(gz,bg=CARD);zt.pack(fill="x",padx=12,pady=(10,0))
  tk.Label(zt,text="Position gaz",fg=SUB,bg=CARD,font=(FONT,8,"bold")).pack(side="left")
  self.badge["throttle"]=tk.Label(zt,text="",fg=GREEN,bg=CARD,font=(FONT,7,"bold"));self.badge["throttle"].pack(side="right")
  self.throttle_val=tk.Label(gz,text="—",fg=TEXT,bg=CARD,font=(FONT,30,"bold"));self.throttle_val.pack(anchor="w",padx=12,pady=(0,2))
  self.gaz_bar=self.reg(Bar(gz,GREEN,0,100,height=10));self.gaz_bar.pack(fill="x",padx=12)
  sc=tk.Frame(gz,bg=CARD);sc.pack(fill="x",padx=12,pady=(2,0))
  for t in ["0","50","100"]:
   tk.Label(sc,text=t,fg=MUTED,bg=CARD,font=(FONT,7)).pack(side="left",expand=True)
  self.tps_lbl=tk.Label(gz,text="TPS1 —  ·  TPS2 —",fg=PINK,bg=CARD,font=(FONT,8,"bold"));self.tps_lbl.pack(anchor="w",padx=12,pady=(6,8))
  self.cards["throttle"]=(self.throttle_val,self.gaz_bar)

  small=[("temp","Temp. moteur","°C",ORANGE,50,150),("oil","Temp. huile","°C",YELLOW,50,150),
         ("battery","Tension batterie","V",LIME,10,16),("front","Roue AV","km/h",CYAN,0,300),("rear","Roue AR","km/h",CYAN,0,300)]
  for i,(key,label,unit,color,lo,hi) in enumerate(small):
   self.mcard(left,key,label,unit,color,lo,hi).grid(row=1,column=2+i,sticky="nsew",padx=4,pady=4)

  st=self.card(right);st.pack(fill="both",expand=True,padx=4,pady=4)
  tk.Label(st,text="Statut système",fg=TEXT,bg=CARD,font=(FONT,11,"bold")).pack(anchor="w",padx=16,pady=(14,8))
  for key,label in [("can","CAN"),("rx","Réception trames"),("gps","GPS"),("rec","Enregistrement"),("qual","Qualité signal CAN"),("val","Validation")]:
   row=tk.Frame(st,bg=CARD);row.pack(fill="x",padx=16,pady=5)
   dot=make_dot(row,MUTED,CARD,9);dot.pack(side="left",padx=(0,8))
   tk.Label(row,text=label,fg=SUB,bg=CARD,font=(FONT,9)).pack(side="left")
   v=tk.Label(row,text="—",fg=TEXT,bg=CARD,font=(FONT,9,"bold"));v.pack(side="right")
   self.srow[key]=(dot,v)
  tk.Label(st,text="Les décodages marqués « à valider »\nsont des hypothèses non confirmées.",fg=MUTED,bg=CARD,font=(FONT,8),justify="left").pack(anchor="w",padx=16,pady=(12,10))

 def set_srow(self,key,text,color):
  dot,v=self.srow[key];set_dot(dot,color);v.config(text=text)

 # ---------- page Courbes ----------

 def build_graph(self,parent):
  left=tk.Frame(parent,bg=BG,width=260);left.pack(side="left",fill="y",padx=(0,6));left.pack_propagate(False)
  mapc=self.card(left);mapc.pack(fill="x",pady=(0,6))
  self.map=tk.Canvas(mapc,bg=CARD,height=210,highlightthickness=0);self.map.pack(fill="x",padx=6,pady=6)
  selc=self.card(left);selc.pack(fill="both",expand=True)
  tk.Label(selc,text="Signaux tracés · cliquer pour ajouter",fg=SUB,bg=CARD,font=(FONT,9,"bold")).pack(anchor="w",padx=10,pady=(8,4))
  wrap,inner=self.scroll_area(selc,CARD)
  wrap.pack(fill="both",expand=True,padx=6,pady=(0,6))
  for key in CURVE_KEYS:
   cid,name=key
   b=tk.Button(inner,text=f"{name.replace('_',' ')}  ·  0x{cid:03X}",anchor="w",relief="flat",bd=0,highlightthickness=0,
               font=(FONT,9,"bold"),padx=8,pady=3,cursor="hand2",command=lambda k=key:self.toggle_curve(k))
   b.pack(fill="x",padx=2,pady=1)
   self.curve_btns[key]=b
  self.refresh_curve_buttons()

  right=self.card(parent);right.pack(side="left",fill="both",expand=True)
  bar=tk.Frame(right,bg=CARD);bar.pack(fill="x",padx=12,pady=(8,4))
  tk.Label(bar,text="Courbes",fg=TEXT,bg=CARD,font=(FONT,12,"bold")).pack(side="left",padx=(0,14))
  self.btn_ov=self.button(bar,"Superposées",lambda:self.set_stack(False),SUB,CARD2,font=9);self.btn_ov.pack(side="left",padx=2)
  self.btn_st=self.button(bar,"Empilées",lambda:self.set_stack(True),SUB,CARD2,font=9);self.btn_st.pack(side="left",padx=2)
  self.hint=tk.Label(bar,text="",fg=MUTED,bg=CARD,font=(FONT,8));self.hint.pack(side="left",padx=12)
  wc=ttk.Combobox(bar,values=[f"{w} s" for w in WINDOWS],state="readonly",width=7)
  wc.set(f"{self.window.get()} s");wc.pack(side="right")
  wc.bind("<<ComboboxSelected>>",lambda e:(self.window.set(int(wc.get().split()[0])),self.draw_chart()))
  tk.Label(bar,text="Fenêtre",fg=SUB,bg=CARD,font=(FONT,9)).pack(side="right",padx=(10,6))
  self.button(bar,"Suivre le direct ▸▸",self.follow,GREEN,CARD2,font=9).pack(side="right",padx=6)
  cw=tk.Frame(right,bg=CARD);cw.pack(fill="both",expand=True,padx=6,pady=(0,6))
  cw.rowconfigure(0,weight=1);cw.columnconfigure(0,weight=1)
  self.chart=tk.Canvas(cw,bg=CARD,highlightthickness=0)
  self.chart_sb=ttk.Scrollbar(cw,orient="vertical",command=self.chart.yview)
  self.chart.configure(yscrollcommand=self.chart_sb.set)
  self.chart.grid(row=0,column=0,sticky="nsew");self.chart_sb.grid(row=0,column=1,sticky="ns")
  self.taxis=tk.Canvas(cw,bg=CARD,height=26,highlightthickness=0);self.taxis.grid(row=1,column=0,sticky="ew")
  self.chart_hsb=ttk.Scrollbar(cw,orient="horizontal",command=self.on_hscroll);self.chart_hsb.grid(row=2,column=0,sticky="ew")
  def wheel(e):self.chart.yview_scroll(int(-e.delta/120),"units")
  def hwheel(e):self.on_hscroll("scroll",str(int(-e.delta/120)),"units")
  def enter(e):self.chart.bind_all("<MouseWheel>",wheel);self.chart.bind_all("<Shift-MouseWheel>",hwheel)
  def leave(e):self.chart.unbind_all("<MouseWheel>");self.chart.unbind_all("<Shift-MouseWheel>")
  self.chart.bind("<Enter>",enter);self.chart.bind("<Leave>",leave)
  self.chart.bind("<ButtonPress-1>",self.chart_press);self.chart.bind("<B1-Motion>",self.chart_drag)
  self.chart.bind("<ButtonRelease-1>",self.chart_release);self.chart.bind("<Motion>",self.chart_motion)
  self.chart.bind("<Configure>",lambda e:self.draw_chart())
  self.refresh_mode_buttons()
 def toggle_curve(self,key):
  if key in self.sel:self.sel.discard(key)
  else:self.sel.add(key)
  self.refresh_curve_buttons()

 def refresh_curve_buttons(self):
  for key,b in self.curve_btns.items():
   on=key in self.sel;color=PALETTE[CURVE_INDEX[key]%len(PALETTE)]
   b.config(bg=color if on else CARD2,fg=BG if on else SUB,activebackground=color if on else HOVER,activeforeground=BG if on else TEXT)

 def set_stack(self,stacked):
  self.stack.set(stacked);self.refresh_mode_buttons();self.chart.yview_moveto(0);self.draw_chart()

 def follow(self):
  self.view_end=None;self.draw_chart()

 def refresh_mode_buttons(self):
  for b,on in ((self.btn_ov,not self.stack.get()),(self.btn_st,self.stack.get())):
   b.config(bg=CYAN if on else CARD2,fg=BG if on else SUB)
  self.hint.config(text="Glisser les séparateurs entre fenêtres pour régler leur hauteur" if self.stack.get()
                   else "Cliquer un signal de la légende pour en faire l'axe de gauche")

 def paint_map(self):
  c=self.map;c.delete("all");w=c.winfo_width();h=c.winfo_height()
  if w>60 and h>60:
   c.create_text(10,8,text="Circuit",anchor="nw",fill=SUB,font=(FONT,9,"bold"))
   pts=list(self.track)
   if len(pts)<2:
    c.create_text(w/2,h/2,text="Pas de données GPS dans cette source",fill=MUTED,font=(FONT,9))
   else:
    lats=[p[0] for p in pts];lons=[p[1] for p in pts]
    mnla,mxla,mnlo,mxlo=min(lats),max(lats),min(lons),max(lons)
    lat0=(mnla+mxla)/2;kx=math.cos(math.radians(lat0))
    dx=max((mxlo-mnlo)*kx,1e-7);dy=max(mxla-mnla,1e-7)
    s=min((w-30)/dx,(h-40)/dy)
    ox=(w-dx*s)/2;oy=20+((h-40)-dy*s)/2
    def xy(la,lo):return ox+(lo-mnlo)*kx*s, oy+(mxla-la)*s
    step=max(1,len(pts)//1500);sample=pts[::step]
    if sample[-1]!=pts[-1]:sample.append(pts[-1])
    coords=[]
    for la,lo in sample:coords.extend(xy(la,lo))
    c.create_line(*coords,fill=CYAN,width=2)
    x,y=xy(*pts[-1]);c.create_oval(x-5,y-5,x+5,y+5,fill=GREEN,outline="")
  self.root.after(400,self.paint_map)

 # ---- gestion de la fenêtre temporelle (ascenseur horizontal)
 def data_start(self):
  ts=[self.hist[k][0][0] for k in self.sel if k in self.hist and self.hist[k]]
  return min(ts) if ts else 0

 def on_hscroll(self,*a):
  span=self.window.get()*1000;tmax=self.t_now;t0=self.data_start()
  if tmax-t0<=span:return
  cur=self.view_end if self.view_end is not None else tmax
  if a[0]=="moveto":end=t0+float(a[1])*(tmax-t0)+span
  else:
   step=span*(0.9 if a[2]=="pages" else 0.1);end=cur+int(a[1])*step
  end=min(tmax,max(t0+span,end))
  self.view_end=None if end>=tmax-1 else end
  self.draw_chart()

 def axis_for(self,mn,mx):
  """Bornes « rondes » et graduations pour un signal."""
  if mx-mn<1e-9:mn-=1;mx+=1
  tks=nice_ticks(mn,mx,4)
  step=(tks[1]-tks[0]) if len(tks)>1 else (mx-mn)
  lo=math.floor(mn/step+1e-9)*step;hi=math.ceil(mx/step-1e-9)*step
  if hi<=lo:hi=lo+step
  n=int(round((hi-lo)/step))
  return lo,hi,[round(lo+i*step,10) for i in range(n+1)]

 def tlabel(self,sec,step):
  if step<1:
   m=int(sec//60);return f"{m:02d}:{sec-60*m:04.1f}"
  sec=int(round(sec));return f"{sec//60:02d}:{sec%60:02d}"

 def draw_chart(self):
  c=self.chart;ta=self.taxis;c.delete("all");ta.delete("all")
  self.grips=[];self.legend_hits=[]
  w=c.winfo_width();h=c.winfo_height()
  if w<=300 or h<=100:return
  win=self.window.get();span=win*1000;tmax=self.t_now
  end=self.view_end if self.view_end is not None else tmax;start=end-span
  sel=[k for k in CURVE_KEYS if k in self.sel]
  L,R,T=70,250,10;pw=w-L-R
  # ascenseur horizontal
  t0=self.data_start();tot=tmax-t0
  if tot>span:self.chart_hsb.set(max(0,(start-t0)/tot),min(1,(end-t0)/tot))
  else:self.chart_hsb.set(0,1)
  # axe du temps (fixe, sous la zone de courbes)
  ticks=nice_ticks(start/1000,end/1000,max(2,pw//110))
  tstep=(ticks[1]-ticks[0]) if len(ticks)>1 else 1
  xs=[]
  ta.create_line(L,0,L+pw,0,fill=BORDER)
  for sec in ticks:
   x=L+pw*(sec*1000-start)/span;xs.append(x)
   ta.create_line(x,0,x,5,fill=SUB)
   ta.create_text(x,7,text=self.tlabel(sec,tstep),fill=SUB,font=(FONT,8),anchor="n")
  ta.create_text(L+pw+16,7,text=("◂ historique" if self.view_end is not None else "en direct"),fill=YELLOW if self.view_end is not None else GREEN,font=(FONT,8,"bold"),anchor="nw")

  def window_pts(key):
   pts=[]
   for tt,v in reversed(self.hist.get(key,())):
    if tt>end:continue
    if tt<start:break
    pts.append((tt,v))
   pts.reverse()
   st=len(pts)//(2*max(pw,1))+1
   return pts[::st] if st>1 else pts
  def poly(pts,ymap,color):
   co=[]
   for tt,v in pts:co.extend((L+pw*(tt-start)/span,ymap(v)))
   if len(co)>=4:c.create_line(*co,fill=color,width=2)
  def unit_of(key):return disp_unit(UNIT_OF.get(key,""))
  def vgrid(y0,y1):
   for x in xs:c.create_line(x,y0,x,y1,fill=BORDER,dash=(2,5))

  if not sel:
   c.configure(scrollregion=(0,0,w,h))
   c.create_text(L+pw/2,h/2,text="Choisissez des signaux dans la liste de gauche",fill=MUTED,font=(FONT,11))
   return

  if not self.stack.get():
   total=max(h,T+34+len(sel)*48+10);c.configure(scrollregion=(0,0,w,total))
   ph=max(80,h-T-10)
   data={}
   for key in sel:
    pts=window_pts(key)
    if len(pts)>=2:
     vals=[v for _,v in pts];data[key]=(pts,min(vals),max(vals),vals[-1])
   ref=self.ref_key if self.ref_key in sel else next((k for k in sel if k in data and data[k][2]>data[k][1]),sel[0]);self.ref_key=ref
   rcol=PALETTE[CURVE_INDEX[ref]%len(PALETTE)]
   c.create_rectangle(L,T,L+pw,T+ph,outline=BORDER)
   if ref in data:
    lo,hi,tks=self.axis_for(data[ref][1],data[ref][2])
    for v in tks:
     y=T+ph*(1-(v-lo)/(hi-lo));c.create_line(L,y,L+pw,y,fill=BORDER)
     c.create_text(L-8,y,text=fmt_val(v),fill=rcol,font=(FONT,8),anchor="e")
    u=unit_of(ref)
    if u:c.create_text(L-8,T-1,text=u,fill=rcol,font=(FONT,8,"bold"),anchor="se")
   else:
    for i in range(1,4):
     y=T+ph*i/4;c.create_line(L,y,L+pw,y,fill=BORDER)
   vgrid(T,T+ph)
   for key in sel:
    if key not in data:continue
    pts,mn,mx,_=data[key];lo,hi,_t=self.axis_for(mn,mx)
    poly(pts,lambda v,lo=lo,hi=hi:T+ph*(1-(v-lo)/(hi-lo)),PALETTE[CURVE_INDEX[key]%len(PALETTE)])
   lx=L+pw+16
   c.create_text(lx,T,text="Signal · min · max · actuel",anchor="nw",fill=SUB,font=(FONT,8,"bold"))
   for i,key in enumerate(sel):
    color=PALETTE[CURVE_INDEX[key]%len(PALETTE)];cid,name=key;y0=T+22+i*48
    if key==ref:c.create_rectangle(lx-6,y0-4,w-6,y0+42,outline=color)
    self.legend_hits.append((lx-6,y0-4,w-6,y0+42,key))
    c.create_line(lx,y0+7,lx+18,y0+7,fill=color,width=3)
    c.create_text(lx+26,y0,text=f"{name.replace('_',' ')} · 0x{cid:03X}",anchor="nw",fill=TEXT,font=(FONT,8,"bold"))
    if key in data:
     _p,mn,mx,cur=data[key]
     c.create_text(lx+26,y0+14,text=f"{fmt_val(mn)} … {fmt_val(mx)} {unit_of(key)}",anchor="nw",fill=SUB,font=(FONT,8))
     c.create_text(lx+26,y0+27,text=f"actuel {fmt_val(cur)}"+("   ◂ axe de gauche" if key==ref else ""),anchor="nw",fill=color if key==ref else TEXT,font=(FONT,8,"bold"))
    else:
     c.create_text(lx+26,y0+14,text="pas de donnée",anchor="nw",fill=MUTED,font=(FONT,8))
   return

  # ---- empilées
  dflt=int(max(90,min(400,(h-T-8)/len(sel))))
  for key in sel:self.band_h.setdefault(key,dflt)
  total=max(h,T+sum(self.band_h[k] for k in sel)+8);c.configure(scrollregion=(0,0,w,total))
  y=T
  for i,key in enumerate(sel):
   bh=self.band_h[key];y0=y;y1=y+bh-8;color=PALETTE[CURVE_INDEX[key]%len(PALETTE)];cid,name=key
   c.create_rectangle(L,y0,L+pw,y1,outline=BORDER,fill=BG)
   vgrid(y0,y1)
   lx=L+pw+16
   c.create_text(lx,y0+2,text=f"{name.replace('_',' ')} · 0x{cid:03X}",anchor="nw",fill=color,font=(FONT,9,"bold"))
   pts=window_pts(key)
   if len(pts)<2:
    c.create_text(L+pw/2,(y0+y1)/2,text="pas de donnée",fill=MUTED,font=(FONT,8))
   else:
    vals=[v for _,v in pts];mn=min(vals);mx=max(vals)
    lo,hi,tks=self.axis_for(mn,mx);top=y0+6;bot=y1-6
    ym=lambda v,lo=lo,hi=hi,top=top,bot=bot:bot-(bot-top)*(v-lo)/(hi-lo)
    for v in tks:
     yy=ym(v);c.create_line(L,yy,L+pw,yy,fill=BORDER)
     c.create_text(L-8,yy,text=fmt_val(v),fill=SUB,font=(FONT,8),anchor="e")
    poly(pts,ym,color)
    c.create_text(lx,y0+17,text=f"{fmt_val(mn)} … {fmt_val(mx)} {unit_of(key)}",anchor="nw",fill=SUB,font=(FONT,8))
    c.create_text(lx,y0+30,text=f"actuel {fmt_val(vals[-1])}",anchor="nw",fill=TEXT,font=(FONT,8,"bold"))
   gy=y1+4;self.grips.append((i,gy))
   active=self.drag is not None and self.drag[0]==i
   c.create_rectangle(L,gy-3,L+pw,gy+3,fill=CYAN if active else CARD2,outline="")
   cx=L+pw/2;c.create_line(cx-16,gy,cx+16,gy,fill=BG if active else SUB,width=2)
   y+=bh

 def paint_chart(self):
  try:
   if self.current_page=="graph":self.draw_chart()
  finally:
   self.root.after(180,self.paint_chart)

 # ---- souris sur le graphique : séparateurs et légende
 def grip_at(self,e):
  if not self.stack.get():return None
  y=self.chart.canvasy(e.y)
  for i,gy in self.grips:
   if abs(y-gy)<=6:return i
  return None

 def chart_motion(self,e):
  self.chart.config(cursor="sb_v_double_arrow" if self.grip_at(e) is not None else "")

 def chart_press(self,e):
  i=self.grip_at(e)
  if i is not None:
   self.drag=(i,self.chart.canvasy(e.y),dict(self.band_h));return
  x=self.chart.canvasx(e.x);y=self.chart.canvasy(e.y)
  for x0,y0,x1,y1,key in self.legend_hits:
   if x0<=x<=x1 and y0<=y<=y1:
    self.ref_key=key;self.draw_chart();return

 def chart_drag(self,e):
  if not self.drag:return
  i,y0,start=self.drag;dy=self.chart.canvasy(e.y)-y0
  sel=[k for k in CURVE_KEYS if k in self.sel]
  if i>=len(sel):return
  k=sel[i];hh=start[k]
  if i<len(sel)-1:
   k2=sel[i+1];h2=start[k2]
   dy=max(BAND_MIN-hh,h2-BAND_MAX,min(h2-BAND_MIN,BAND_MAX-hh,dy))
   self.band_h[k]=int(hh+dy);self.band_h[k2]=int(h2-dy)
  else:
   self.band_h[k]=int(max(BAND_MIN,min(BAND_MAX,hh+dy)))
  self.draw_chart()

 def chart_release(self,e):
  self.drag=None;self.draw_chart()

 # ---------- page Paramétrage ESP32 ----------
 def build_esp_vars(self):
  sv=lambda k,v:self.cv.__setitem__(k,tk.StringVar(value=str(v)))
  bv=lambda k,v:self.cv.__setitem__(k,tk.BooleanVar(value=v))
  sv("ssid","RSV4-CAN");sv("password","rsv4-can-2026");sv("channel",6)
  self.cv["tcp_port"]=self.tcp_port
  sv("can_bitrate",250);sv("can_tx",5);sv("can_rx",4)
  bv("gps_on",True);sv("gps_rx",16);sv("gps_baud",115200)
  for i,(pin,name,on) in enumerate(DIG_DEFAULT):sv(f"dig{i}_pin",pin);sv(f"dig{i}_name",name);bv(f"dig{i}_on",on)
  for i,(pin,name,on) in enumerate(ANA_DEFAULT):sv(f"ana{i}_pin",pin);sv(f"ana{i}_name",name);bv(f"ana{i}_on",on)
  for i,(pin,name,level,on) in enumerate(OUT_DEFAULT):sv(f"out{i}_pin",pin);sv(f"out{i}_name",name);sv(f"out{i}_level",level);bv(f"out{i}_on",on)

 def cfg_from_vars(self):
  """Construit la configuration ESP32 à partir des champs ; lève ValueError si un champ est invalide."""
  v=self.cv;i=lambda k:int(str(v[k].get()).strip())
  return {"wifi":{"ssid":v["ssid"].get().strip(),"password":v["password"].get(),"channel":i("channel"),"tcp_port":int(self.tcp_port.get().strip())},
          "can":{"bitrate_kbps":i("can_bitrate"),"tx_pin":i("can_tx"),"rx_pin":i("can_rx")},
          "gps":{"enabled":v["gps_on"].get(),"rx_pin":i("gps_rx"),"baud":i("gps_baud")},
          "digital_inputs":[{"pin":i(f"dig{n}_pin"),"name":v[f"dig{n}_name"].get(),"enabled":v[f"dig{n}_on"].get()} for n in range(8)],
          "analog_inputs":[{"pin":i(f"ana{n}_pin"),"name":v[f"ana{n}_name"].get(),"enabled":v[f"ana{n}_on"].get()} for n in range(3)],
          "outputs":[{"pin":i(f"out{n}_pin"),"name":v[f"out{n}_name"].get(),"level":v[f"out{n}_level"].get(),"enabled":v[f"out{n}_on"].get()} for n in range(2)]}

 def cfg_to_vars(self,cfg):
  v=self.cv
  w,c,g=cfg["wifi"],cfg["can"],cfg["gps"]
  v["ssid"].set(w["ssid"]);v["password"].set(w["password"]);v["channel"].set(w["channel"]);self.tcp_port.set(str(w["tcp_port"]))
  v["can_bitrate"].set(c["bitrate_kbps"]);v["can_tx"].set(c["tx_pin"]);v["can_rx"].set(c["rx_pin"])
  v["gps_on"].set(bool(g["enabled"]));v["gps_rx"].set(g["rx_pin"]);v["gps_baud"].set(g["baud"])
  for n,e in enumerate(cfg["digital_inputs"]):v[f"dig{n}_pin"].set(e["pin"]);v[f"dig{n}_name"].set(e["name"]);v[f"dig{n}_on"].set(bool(e["enabled"]))
  for n,e in enumerate(cfg["analog_inputs"]):v[f"ana{n}_pin"].set(e["pin"]);v[f"ana{n}_name"].set(e["name"]);v[f"ana{n}_on"].set(bool(e["enabled"]))
  for n,e in enumerate(cfg["outputs"]):
   v[f"out{n}_pin"].set(e["pin"]);v[f"out{n}_name"].set(e["name"]);v[f"out{n}_level"].set(e["level"]);v[f"out{n}_on"].set(bool(e["enabled"]))

 def esp_card(self,parent,title):
  c=self.card(parent);c.pack(fill="x",padx=6,pady=6)
  tk.Label(c,text=title,fg=TEXT,bg=CARD,font=(FONT,10,"bold")).pack(anchor="w",padx=14,pady=(10,6))
  inner=tk.Frame(c,bg=CARD);inner.pack(fill="x",padx=14,pady=(0,12))
  return inner

 def efield(self,parent,label,key,width=16):
  r=tk.Frame(parent,bg=CARD);r.pack(fill="x",pady=2)
  tk.Label(r,text=label,bg=CARD,fg=SUB,font=(FONT,9),anchor="w",width=38).pack(side="left")
  tk.Entry(r,textvariable=self.cv[key],width=width,bg=CARD2,fg=TEXT,insertbackground=TEXT,relief="flat",
           highlightbackground=BORDER,highlightthickness=1).pack(side="left")

 def ecombo(self,parent,label,key,values):
  r=tk.Frame(parent,bg=CARD);r.pack(fill="x",pady=2)
  tk.Label(r,text=label,bg=CARD,fg=SUB,font=(FONT,9),anchor="w",width=38).pack(side="left")
  ttk.Combobox(r,textvariable=self.cv[key],values=values,state="readonly",width=12).pack(side="left")

 def echeck(self,parent,label,key):
  tk.Checkbutton(parent,text=label,variable=self.cv[key],bg=CARD,fg=TEXT,selectcolor=CARD2,activebackground=CARD,
                 activeforeground=TEXT,font=(FONT,9),bd=0,highlightthickness=0).pack(anchor="w",pady=2)

 def build_esp(self,parent):
  bar=tk.Frame(parent,bg=BG);bar.pack(fill="x",pady=(0,6))
  tk.Label(bar,text="Paramétrage de l'ESP32",fg=TEXT,bg=BG,font=(FONT,13,"bold")).pack(side="left")
  tk.Label(bar,text="Réseau, bus CAN, GPS et entrées/sorties",fg=SUB,bg=BG,font=(FONT,9)).pack(side="left",padx=12)
  self.button(bar,"Appliquer à l'application",self.apply_esp,TEXT,CARD2,font=9).pack(side="right",padx=3)
  self.button(bar,"Générer rsv4_config.h",self.export_header,TEXT,CARD2,font=9).pack(side="right",padx=3)
  self.button(bar,"Enregistrer (JSON)",self.save_esp,TEXT,CARD2,font=9).pack(side="right",padx=3)
  self.button(bar,"Charger (JSON)",self.load_esp,TEXT,CARD2,font=9).pack(side="right",padx=3)
  wrap,inner=self.scroll_area(parent,BG)
  wrap.pack(fill="both",expand=True)
  left=tk.Frame(inner,bg=BG);left.pack(side="left",fill="y",anchor="n")
  right=tk.Frame(inner,bg=BG);right.pack(side="left",fill="both",expand=True,anchor="n")
  c=self.esp_card(left,"Réseau Wi-Fi (point d'accès de l'ESP32)")
  self.efield(c,"Nom du réseau (SSID)","ssid",22)
  self.efield(c,"Mot de passe (8 caractères min.)","password",22)
  self.ecombo(c,"Canal Wi-Fi","channel",[str(n) for n in range(1,14)])
  self.efield(c,"Port TCP (applications)","tcp_port",10)
  c=self.esp_card(left,"Bus CAN")
  self.ecombo(c,"Débit (kbit/s)","can_bitrate",["250","500"])
  self.efield(c,"Broche TX (vers le transceiver)","can_tx",8)
  self.efield(c,"Broche RX (vers le transceiver)","can_rx",8)
  c=self.esp_card(left,"GPS (UART)")
  self.echeck(c,"GPS activé (trames 0x7F0 et 0x7F8)","gps_on")
  self.efield(c,"Broche RX (depuis le module GPS)","gps_rx",8)
  self.ecombo(c,"Débit (bauds)","gps_baud",["9600","38400","115200"])
  c=self.esp_card(right,"Entrées numériques (trame 0x7F9, bit par entrée)")
  self.io_header(c,["Entrée","Broche","Nom","Active"])
  for n in range(8):
   r=tk.Frame(c,bg=CARD);r.pack(fill="x",pady=1)
   tk.Label(r,text=f"E{n+1}",bg=CARD,fg=SUB,font=(FONT,9),width=8,anchor="w").pack(side="left")
   self.io_entry(r,f"dig{n}_pin",6);self.io_entry(r,f"dig{n}_name",18)
   tk.Checkbutton(r,variable=self.cv[f"dig{n}_on"],bg=CARD,selectcolor=CARD2,activebackground=CARD,bd=0,highlightthickness=0).pack(side="left",padx=12)
  c=self.esp_card(right,"Entrées analogiques ADC (trame 0x7F9, 0 à 4095)")
  self.io_header(c,["Entrée","Broche","Nom","Active"])
  for n in range(3):
   r=tk.Frame(c,bg=CARD);r.pack(fill="x",pady=1)
   tk.Label(r,text=f"ADC{n+1}",bg=CARD,fg=SUB,font=(FONT,9),width=8,anchor="w").pack(side="left")
   self.io_entry(r,f"ana{n}_pin",6);self.io_entry(r,f"ana{n}_name",18)
   tk.Checkbutton(r,variable=self.cv[f"ana{n}_on"],bg=CARD,selectcolor=CARD2,activebackground=CARD,bd=0,highlightthickness=0).pack(side="left",padx=12)
  c=self.esp_card(right,"Sorties (niveau appliqué au démarrage)")
  self.io_header(c,["Sortie","Broche","Nom","Niveau","Active"])
  for n in range(2):
   r=tk.Frame(c,bg=CARD);r.pack(fill="x",pady=1)
   tk.Label(r,text=f"S{n+1}",bg=CARD,fg=SUB,font=(FONT,9),width=8,anchor="w").pack(side="left")
   self.io_entry(r,f"out{n}_pin",6);self.io_entry(r,f"out{n}_name",18)
   ttk.Combobox(r,textvariable=self.cv[f"out{n}_level"],values=["Haut","Bas"],state="readonly",width=6).pack(side="left",padx=6)
   tk.Checkbutton(r,variable=self.cv[f"out{n}_on"],bg=CARD,selectcolor=CARD2,activebackground=CARD,bd=0,highlightthickness=0).pack(side="left",padx=12)
  tk.Label(right,text="Les broches et réglages sont appliqués au firmware par « Générer rsv4_config.h » puis recompilation du firmware.\n"
                      "Les entrées/sorties sont lues par le firmware ; les sorties ne sont pas pilotées depuis l'application.",
           fg=MUTED,bg=BG,font=(FONT,8),justify="left").pack(anchor="w",padx=8,pady=(4,10))

 def io_header(self,parent,labels):
  r=tk.Frame(parent,bg=CARD);r.pack(fill="x",pady=(0,4))
  widths=[8,6,18,6,6]
  for i,l in enumerate(labels):
   tk.Label(r,text=l,bg=CARD,fg=MUTED,font=(FONT,8,"bold"),width=widths[i] if i<len(widths) else 8,anchor="w").pack(side="left")

 def io_entry(self,parent,key,width):
  tk.Entry(parent,textvariable=self.cv[key],width=width,bg=CARD2,fg=TEXT,insertbackground=TEXT,relief="flat",
           highlightbackground=BORDER,highlightthickness=1).pack(side="left",padx=(0,6))

 def apply_esp(self):
  try:cfg=self.cfg_from_vars();validate_cfg(cfg)
  except ValueError as e:messagebox.showerror("Paramétrage ESP32",str(e));return
  names={(0x7F9,f"Entrée {n+1}"):e["name"] for n,e in enumerate(cfg["digital_inputs"])}
  names.update({(0x7F9,f"ADC {n+1}"):e["name"] for n,e in enumerate(cfg["analog_inputs"])})
  for key,(f,vl,sl,nl) in self.tiles.items():
   if key in names:nl.config(text=names[key] or key[1])
  self.set_state("Paramétrage appliqué · recompiler le firmware pour les broches",CYAN)

 def save_esp(self):
  try:cfg=self.cfg_from_vars();validate_cfg(cfg)
  except ValueError as e:messagebox.showerror("Paramétrage ESP32",str(e));return
  p=filedialog.asksaveasfilename(title="Enregistrer le paramétrage",defaultextension=".json",initialfile="rsv4_esp32.json",
                                 filetypes=[("Paramétrage JSON","*.json")])
  if p:
   with open(p,"w",encoding="utf-8") as f:json.dump(cfg,f,ensure_ascii=False,indent=2)
   self.set_state(f"Paramétrage enregistré : {os.path.basename(p)}",GREEN)

 def load_esp(self):
  p=filedialog.askopenfilename(title="Charger un paramétrage",filetypes=[("Paramétrage JSON","*.json")])
  if not p:return
  try:
   with open(p,encoding="utf-8") as f:cfg=json.load(f)
   validate_cfg(cfg);self.cfg_to_vars(cfg)
  except (OSError,ValueError,KeyError) as e:messagebox.showerror("Paramétrage ESP32",f"Fichier invalide : {e}");return
  self.set_state(f"Paramétrage chargé : {os.path.basename(p)}",SUB)

 def export_header(self):
  try:cfg=self.cfg_from_vars();validate_cfg(cfg)
  except ValueError as e:messagebox.showerror("Paramétrage ESP32",str(e));return
  base=getattr(sys,"_MEIPASS",os.path.dirname(os.path.abspath(__file__)))
  default_dir=os.path.join(base,"firmware","esp32_can_wifi")
  p=filedialog.asksaveasfilename(title="Enregistrer rsv4_config.h dans le dossier du firmware",defaultextension=".h",
                                 initialfile="rsv4_config.h",initialdir=default_dir if os.path.isdir(default_dir) else None,
                                 filetypes=[("En-tête C","*.h")])
  if p:
   with open(p,"w",encoding="utf-8") as f:f.write(make_header(cfg))
   self.set_state(f"Fichier firmware généré : {os.path.basename(p)}",GREEN)

 # ---------- trames ----------
 def build_table(self,parent):
  card=self.card(parent);card.pack(fill="both",expand=True,padx=4,pady=4)
  hdr=tk.Frame(card,bg=CARD);hdr.pack(fill="x",padx=14,pady=(10,4))
  tk.Label(hdr,text="Trames CAN en direct",fg=TEXT,bg=CARD,font=(FONT,12,"bold")).pack(side="left")
  self.button(hdr,"Vider",self.clear_table,SUB,CARD2,font=9).pack(side="right")
  tk.Checkbutton(hdr,text="Trames décodées seulement",variable=self.filter_on,command=self.rebuild_table,bg=CARD,fg=SUB,
                 selectcolor=CARD2,activebackground=CARD,font=(FONT,9),bd=0,highlightthickness=0).pack(side="right",padx=12)
  fl=tk.Frame(card,bg=CARD);fl.pack(fill="x",padx=14,pady=(0,6))
  def field(label,var,width):
   tk.Label(fl,text=label,fg=SUB,bg=CARD,font=(FONT,9)).pack(side="left",padx=(0,4))
   e=tk.Entry(fl,textvariable=var,width=width,bg=CARD2,fg=TEXT,insertbackground=TEXT,relief="flat",highlightthickness=1,
              highlightbackground=BORDER,highlightcolor=CYAN,font=(FONT,9))
   e.pack(side="left",padx=(0,14),ipady=3);return e
  self.e_show=field("Afficher les ID (hex)",self.f_show,18)
  self.e_hide=field("Masquer les ID",self.f_hide,18)
  self.e_text=field("Contient",self.f_text,18)
  self.button(fl,"Réinitialiser",self.reset_filters,SUB,CARD2,font=9).pack(side="left")
  self.count_lbl=tk.Label(fl,text="",fg=SUB,bg=CARD,font=(FONT,9));self.count_lbl.pack(side="right")
  tk.Label(card,text="ID en hexadécimal, séparés par des virgules, plages avec un tiret : 100, 2A0-2FF.   « Contient » cherche dans l'ID, les octets et le décodage.",
           fg=MUTED,bg=CARD,font=(FONT,8),anchor="w").pack(fill="x",padx=14,pady=(0,6))
  for v in (self.f_show,self.f_hide,self.f_text):v.trace_add("write",lambda *a:self.schedule_filter())
  tw=tk.Frame(card,bg=CARD);tw.pack(fill="both",expand=True,padx=10,pady=(0,10))
  cols=[("n","#",55,"e"),("time","Temps",95,"w"),("id","ID",75,"w"),("dlc","DLC",45,"center"),
        ("hex","Hex",190,"w"),("dec","Décimal",190,"w"),("freq","Fréq. (Hz)",85,"e"),("txt","Décodage / signaux",440,"w")]
  self.table=ttk.Treeview(tw,columns=[c[0] for c in cols],show="headings",height=6)
  for key,label,width,anchor in cols:
   self.table.heading(key,text=label,anchor=anchor);self.table.column(key,width=width,anchor=anchor,stretch=(key=="txt"))
  self.table.tag_configure("new",background="#174a36",foreground=TEXT)
  sb=ttk.Scrollbar(tw,orient="vertical",command=self.table.yview);self.table.configure(yscrollcommand=sb.set)
  self.table.pack(side="left",fill="both",expand=True);sb.pack(side="right",fill="y")

 # filtrage : les trames récentes sont gardées en mémoire (self.rows), le tableau n'en montre que 400 qui correspondent
 def schedule_filter(self):
  if self._fid:
   try:self.root.after_cancel(self._fid)
   except Exception:pass
  self._fid=self.root.after(250,self.on_filter_change)

 def on_filter_change(self):
  self._fid=None
  self.id_show,ok1=parse_ids(self.f_show.get());self.id_hide,ok2=parse_ids(self.f_hide.get())
  self.ftext=self.f_text.get().strip().lower()
  self.e_show.config(fg=TEXT if ok1 else RED);self.e_hide.config(fg=TEXT if ok2 else RED)
  self.rebuild_table()

 def reset_filters(self):
  self.f_show.set("");self.f_hide.set("");self.f_text.set("");self.filter_on.set(False)
  self.on_filter_change()

 def row_match(self,row):
  cid=row[2]
  if self.id_show and not any(a<=cid<=b for a,b in self.id_show):return False
  if self.id_hide and any(a<=cid<=b for a,b in self.id_hide):return False
  if self.filter_on.get() and self.decoder is not None and row[7]=="—":return False
  if self.ftext and self.ftext not in f"{cid:03x} 0x{cid:03x} {row[4]} {row[7]}".lower():return False
  return True

 def table_insert(self,row,where=0):
  vals=(row[0],row[1],f"0x{row[2]:03X}",row[3],row[4],row[5],row[6],row[7])
  return self.table.insert("",where,values=vals,tags=("new",) if where==0 else ())

 def rebuild_table(self):
  for it in self.table.get_children():self.table.delete(it)
  shown=0;self.matched=0
  for row in reversed(self.rows):
   if self.row_match(row):
    self.matched+=1
    if shown<400:self.table_insert(row,"end");shown+=1
  self.last_row=None;self.refresh_count()

 def refresh_count(self):
  self.count_lbl.config(text=f"{self.matched} trames correspondent · {len(self.rows)} en mémoire")

 def clear_table(self):
  for row in self.table.get_children():self.table.delete(row)
  self.rows.clear();self.matched=0;self.last_row=None;self.refresh_count()

 # ---------- état ----------
 def set_state(self,text,color):
  self.status.set(text);set_dot(self.fl["dot"],color)

 def set_conn_ui(self,live,text):
  set_dot(self.conn_dot,GREEN if live else MUTED)
  self.conn_lbl.config(text=text,fg=GREEN if live else SUB)
  self.conn_btn.config(text="Déconnecter" if live else "Connecter",bg=CARD2 if live else RED,
                       activebackground=HOVER if live else "#ff3b44")

 def open_file(self):
  p=filedialog.askopenfilename(title="Choisir une capture USB-CAN",filetypes=[("Fichiers texte","*.txt *.log"),("Tous fichiers","*.*")])
  if p:self.load(p)

 def clear_data(self):
  self.count.clear();self.first_t.clear();self.last_t.clear()
  self.recent.clear();self.ingested=0;self.t_last=0;self.t_now=0
  self.vals.clear();self.hist.clear();self.dirty.clear();self.flash_until.clear();self.track.clear();self.view_end=None
  self.clear_table()
  for key in self.cards:self.show(key,None)
  self.gear.set(None);self.gear_val.config(text="—");self.rpm.set(None);self.speedg.set(None)
  self.tps_lbl.config(text="TPS1 —  ·  TPS2 —")
  for key,(f,vl,sl,nl) in self.tiles.items():vl.config(text="—",fg=TEXT)

 def load(self,path):
  try:frames=load_capture(path)
  except Exception as exc:messagebox.showerror("Erreur de lecture",str(exc));return
  self.pause();self.frames=frames;self.frame_times=[f[0] for f in frames];self.idx=0;self.clear_data()
  self.file_name.set(os.path.basename(path))
  if not frames:
   self.set_state("0 trame · format non reconnu",RED)
   messagebox.showwarning("0 trame","Le fichier ne contient pas de trames USB-CAN reconnaissables. Vérifiez qu'il s'agit d'un export TXT du logiciel USBCAN.")
  else:
   self.set_state(f"{len(frames):,} trames chargées".replace(","," "),SUB)

 def play(self):
  if not self.frames:messagebox.showinfo("Capture","Importez d'abord une capture TXT.");return
  self.playing=True;self.start_wall=time.monotonic();self.start_frame=self.frames[self.idx][0] if self.idx<len(self.frames) else 0
  self.set_state("Lecture en cours",GREEN)

 def pause(self):
  was=self.playing;self.playing=False
  if was and self.frames and self.idx<len(self.frames):self.set_state("En pause",YELLOW)

 def on_seek_drag(self,frac):
  if self.frames:
   total=self.frames[-1][0];self.clock.set(f"{fmt_time(frac*total)} / {fmt_time(total)}")

 def seek(self,frac):
  """Saute à un instant de la capture : on rejoue les trames qui précèdent pour reconstituer les valeurs et les courbes."""
  if not self.frames:return
  was=self.playing;self.playing=False
  total=self.frames[-1][0]
  target=bisect.bisect_right(self.frame_times,frac*total)
  target=max(0,min(len(self.frames),target))
  begin=max(0,target-SEEK_BACK)
  self.clear_data()
  for fr in self.frames[:begin]:                         # le tracé du circuit est reconstitué sur toute la partie sautée
   if fr[1]==0x7F0 and len(fr[2])>=8:
    la=int.from_bytes(fr[2][0:4],'little',signed=True)/1e7;lo=int.from_bytes(fr[2][4:8],'little',signed=True)/1e7
    if la or lo:self.track.append((la,lo))
  self.bulk=True
  try:
   for i in range(begin,target):self.ingest(*self.frames[i])
  finally:
   self.bulk=False
  self.idx=target;self.ingested=target
  self.rebuild_table()
  if target>0:self.t_now=self.frames[target-1][0]
  if was and target<len(self.frames):
   self.start_wall=time.monotonic();self.start_frame=self.frames[target][0];self.playing=True
   self.set_state("Lecture en cours",GREEN)
  else:
   self.set_state(f"En pause · {fmt_time(self.t_now)}",YELLOW)

 def reset(self):
  self.pause();self.idx=0;self.clear_data()
  if self.frames:self.set_state("Début de capture",SUB)

 # ---------- décodage ----------
 def decode_aprilia(self,t,cid,data):
  """Décodages faits à la main (poignée, TPS, et décodages expérimentaux). Renvoie le texte affiché dans le tableau."""
  dec="—";exp=self.experimental.get()
  if cid==0x7F2 and len(data)>=5:
   # Définition AiM RSV4 EU5: TPS1 sBit=8, TPS2 sBit=24, 16 bits, facteur .119.
   # Hypothèse d'ordre des octets little-endian à valider (la définition indique big-endian).
   a=int.from_bytes(data[1:3],'little')*.119;b=int.from_bytes(data[3:5],'little')*.119
   self.tps_lbl.config(text=f"TPS1 {a:.1f}*  ·  TPS2 {b:.1f}*")
   self.put(cid,"RSV4_TPS1",a,t,"app");self.put(cid,"RSV4_TPS2",b,t,"app")
   dec=f"Papillon TPS1 {a:.1f} % | TPS2 {b:.1f} %  (hypothèse)"
  if cid==0x601 and data:
   self.show("throttle",data[0],text=f"{data[0]}")
   self.put(cid,"Hand_Throttle",data[0],t,"valid")
   dec=f"Position gaz : {data[0]} %"
  if exp:
   if cid==0x100 and len(data)>=5:
    rpm=(data[3]<<8)|data[4];self.rpm.set(rpm);self.put(cid,"RPM",rpm,t,"app")
    parts=[f"Régime {rpm} tr/min*"]
    if len(data)>=2:
     gear=data[0]&15;self.gear.set(gear);self.gear_val.config(text=str(gear))
     self.put(cid,"Gear",gear,t,"app");parts.append(f"Rapport {gear}*")
     if len(data)>=3:
      spd=round((((data[1]<<8)|data[2])&4095)*.25,1);self.speedg.set(spd)
      self.put(cid,"Bike_Speed",spd,t,"app");parts.append(f"Vitesse {spd} km/h*")
    dec=" | ".join(parts)
   if cid==0x200 and len(data)>=2:
    tmp=data[0]-40;oil=data[1]-40
    self.show("temp",tmp);self.show("oil",oil)
    self.put(cid,"Engine_Temp",tmp,t,"app");self.put(cid,"Oil_Temp",oil,t,"app")
    parts=[f"Temp. moteur {tmp} °C*",f"Temp. huile {oil} °C*"]
    if len(data)>=6:
     v=data[5]/10;self.show("battery",v,text=f"{v:.1f}");self.put(cid,"Battery_Volt",v,t,"app")
     parts.append(f"Batterie {v:.1f} V*")
    dec=" | ".join(parts)
   if cid==0x260 and len(data)>=5:
    f=round(int.from_bytes(data[1:3],'big')*.01,1);r=round(int.from_bytes(data[3:5],'big')*.01,1)
    self.show("front",f,text=f"{f:.1f}");self.show("rear",r,text=f"{r:.1f}")
    self.put(cid,"Speed_Front",f,t,"app");self.put(cid,"Speed_Rear",r,t,"app")
    dec=f"Roue AV {f:.1f} km/h | Roue AR {r:.1f} km/h*"
  return dec

 def decode_generic(self,t,cid,data):
  """Tous les autres signaux de la définition can1.xml. Renvoie la liste des textes affichés."""
  parts=[]
  for _,name,sbit,blen,p0,p1,unit in BY_CID.get(cid,()):
   if (cid,name) in HAND_ALWAYS or (self.experimental.get() and (cid,name) in HAND_EXPERIMENTAL):continue
   raw=extract_bits(data,sbit,blen)
   if raw is None:continue
   val=p0+p1*raw
   self.put(cid,name,val,t,"def")
   parts.append(f"{name.replace('_',' ')} {fmt_val(val)}{(' '+disp_unit(unit)) if unit else ''}")
  return parts

 def decode_virtual(self,t,cid,data):
  """Trames de l'ESP32 : GPS (0x7F0, 0x7F8) et entrées/sorties (0x7F9). Renvoie le texte affiché, ou None."""
  if cid==0x7F0 and len(data)>=8:
   lat=int.from_bytes(data[0:4],'little',signed=True)/1e7;lon=int.from_bytes(data[4:8],'little',signed=True)/1e7
   self.put(cid,"GPS Latitude",lat,t,"esp");self.put(cid,"GPS Longitude",lon,t,"esp")
   if lat or lon:self.track.append((lat,lon))
   return f"GPS {lat:.6f} ; {lon:.6f}"
  if cid==0x7F8 and len(data)>=6:
   sp=int.from_bytes(data[0:2],'little')/100;co=int.from_bytes(data[2:4],'little')/100;sats=data[4];fix=data[5]
   self.put(cid,"GPS Vitesse",sp,t,"esp");self.put(cid,"GPS Cap",co,t,"esp")
   self.put(cid,"Satellites",sats,t,"esp");self.put(cid,"Qualité fix",fix,t,"esp")
   return f"GPS {sp:.1f} km/h · cap {co:.0f}° · {sats} satellites · fix {fix}"
  if cid==0x7F9 and len(data)>=7:
   mask=data[0]
   for n in range(8):self.put(cid,f"Entrée {n+1}",(mask>>n)&1,t,"esp")
   adc=[int.from_bytes(data[1+2*j:3+2*j],'little') for j in range(3)]
   for j in range(3):self.put(cid,f"ADC {j+1}",adc[j],t,"esp")
   return f"E/S {mask:08b} · ADC {adc[0]} / {adc[1]} / {adc[2]}"
  return None

 def ingest(self,t,cid,data):
  self.t_now=t
  self.count[cid]+=1;self.ingested+=1;self.t_last=t;self.recent.append(t)
  self.first_t.setdefault(cid,t);self.last_t[cid]=t
  dec="—"
  if self.decoder=="aprilia":
   dec=self.decode_aprilia(t,cid,data)
   parts=self.decode_generic(t,cid,data)
   if parts:dec=" | ".join(parts) if dec=="—" else dec+" | "+" | ".join(parts)
  v=self.decode_virtual(t,cid,data)
  if v:dec=v if dec=="—" else dec+" | "+v
  n=self.count[cid];freq="—"
  if n>1 and self.last_t[cid]>self.first_t[cid]:freq=f"{(n-1)*1000/(self.last_t[cid]-self.first_t[cid]):.0f}"
  row=(self.ingested,fmt_ms(t),cid,len(data),data.hex(" ").upper()," ".join(str(b) for b in data),freq,dec)
  self.rows.append(row)
  if not self.bulk and self.row_match(row):
   self.matched+=1
   try:
    if self.last_row is not None:self.table.item(self.last_row,tags=())
   except tk.TclError:self.last_row=None
   self.last_row=self.table_insert(row,0)
   kids=self.table.get_children()
   if len(kids)>400:self.table.delete(kids[-1])

 # ---------- boucle ----------
 def update_status(self):
  now=int(time.monotonic()*1000) if self.live else self.t_last
  while self.recent and self.recent[0]<now-1000:self.recent.popleft()
  rate=len(self.recent) if (self.live or self.frames) else 0
  if self.frames:
   total=self.frames[-1][0];cur=self.frames[self.idx-1][0] if self.idx>0 else 0
   self.progress.set(100*self.idx/len(self.frames));self.seekbar.set(cur/total if total else 0);self.clock.set(f"{fmt_time(cur)} / {fmt_time(total)}")
   dur=cur
  else:dur=(now-self.t0) if self.live else 0
  self.fl["dur"].config(text=fmt_time(dur))
  if self.current_page=="frames":self.refresh_count()
  self.fl["ids"].config(text=str(len(self.count)))
  self.fl["rate"].config(text=str(rate) if rate else "—")
  self.fl["frames"].config(text=f"{self.ingested:,}".replace(","," "))
  if self.live:
   self.set_srow("can","Connecté",GREEN)
   if rate:self.set_srow("rx",f"OK · {rate}/s",GREEN)
   else:self.set_srow("rx","Aucune trame",RED)
   self.set_srow("qual","Bonne" if rate else "—",GREEN if rate else MUTED)
  else:
   self.set_srow("can","Déconnecté",MUTED)
   self.set_srow("rx","Aucune" if not self.frames else f"Fichier · {len(self.count)} IDs",MUTED)
   self.set_srow("qual","—",MUTED)
  if self.track:self.set_srow("gps",f"{len(self.track)} points",GREEN)
  else:self.set_srow("gps","Aucun fix" if self.live else "Non disponible",MUTED)
  self.set_srow("rec","Non disponible",MUTED)
  self.set_srow("val",self.model["short"],YELLOW if self.decoder else MUTED)

 def tick(self):
  if self.playing and self.frames:
   elapsed=(time.monotonic()-self.start_wall)*1000*self.speed.get()
   limit=self.start_frame+elapsed
   batch=0
   while self.idx<len(self.frames) and self.frames[self.idx][0]<=limit and batch<1200:
    self.ingest(*self.frames[self.idx]);self.idx+=1;batch+=1
   if self.idx>=len(self.frames):
    self.playing=False;self.set_state("Lecture terminée",CYAN)
  for _ in range(400):
   try:cid,data=self.q.get_nowait()
   except queue.Empty:break
   if cid=="error":self.disconnect();messagebox.showerror("Connexion",data)
   else:self.ingest(int(time.monotonic()*1000),cid,data)
  if self.dirty:
   keys=list(self.dirty);self.dirty.clear()
   for k in keys:
    if k in self.tiles:self.refresh_tile(k)
  now=time.monotonic()
  for k,until in list(self.flash_until.items()):
   if now>=until:
    if k in self.tiles:self.tiles[k][1].config(fg=TEXT)
    del self.flash_until[k]
  for w in self.flushables:w.flush()
  self.update_status()
  self.root.after(40,self.tick)

 def settings(self):
  win=tk.Toplevel(self.root);win.title("Paramètres");win.configure(bg=CARD);win.geometry("460x330");win.resizable(False,False)
  tk.Label(win,text="Paramètres",fg=TEXT,bg=CARD,font=(FONT,14,"bold")).pack(anchor="w",padx=24,pady=(18,6))
  for label,var in [("Port série",self.port),("Vitesse série (bauds)",self.baud)]:
   tk.Label(win,text=label,bg=CARD,fg=SUB,font=(FONT,9,"bold")).pack(anchor="w",padx=24,pady=(10,3))
   tk.Entry(win,textvariable=var,width=28,bg=CARD2,fg=TEXT,insertbackground=TEXT,relief="flat",highlightbackground=BORDER,highlightthickness=1).pack(anchor="w",padx=24,ipady=4)
  tk.Checkbutton(win,text="Afficher les décodages expérimentaux (non validés)",variable=self.experimental,
                 bg=CARD,fg=TEXT,selectcolor=CARD2,activebackground=CARD,activeforeground=TEXT).pack(anchor="w",padx=20,pady=(14,6))
  tk.Label(win,text=f"Moto sélectionnée : {self.model['label']}",bg=CARD,fg=SUB,font=(FONT,9,"bold")).pack(anchor="w",padx=24,pady=(4,2))
  tk.Label(win,text="Connexion USB-CAN : réception uniquement.\nMode Silent à configurer avec le logiciel officiel.",
           bg=CARD,fg=YELLOW,justify="left",font=(FONT,9)).pack(anchor="w",padx=24)

 def toggle_connect(self):
  self.disconnect() if self.live else self.connect()

 def disconnect(self):
  was_live=self.live
  self.live=False;self.stop_event.set()
  if was_live:
   self.set_conn_ui(False,"Déconnecté");self.set_state("Déconnecté",MUTED)

 def connect(self):
  wifi=self.transport.get().startswith("Wi-Fi")
  if wifi:
   try:tcp=int(self.tcp_port.get())
   except ValueError:messagebox.showerror("Connexion Wi-Fi","Port TCP invalide.");return
   host=self.host.get().strip();target=f"{host}:{tcp}"
   msg=(f"Connexion Wi-Fi à l'ESP32 ({target}).\n"
        "L'ESP32 doit être en écoute seule (listen-only), comme le mode Silent.\n\n")
  else:
   if serial is None:messagebox.showerror("Dépendance","pyserial manquant");return
   br=self.model["bitrate"]
   if br is None:
    msg=("Le débit CAN de cette moto n'est pas défini dans l'application.\n"
         "Réglez le débit du véhicule dans USBCAN avant de continuer, puis fermer USBCAN.\n\n")
   else:
    msg=f"Configurer l'adaptateur en mode Silent et CAN {br} avec USBCAN, puis fermer USBCAN.\n\n"
  if not messagebox.askokcancel("Sécurité CAN",msg+"Cette application n'envoie aucune commande, et ne peut pas vérifier que le mode Silent reste actif.\n\nContinuer ?"):return
  self.disconnect();self.stop_event=threading.Event();stop=self.stop_event;self.live=True
  self.clear_data();self.t0=int(time.monotonic()*1000)
  self.set_conn_ui(True,"Connecté")
  if wifi:
   self.set_state(f"Wi-Fi · ESP32 {target}",GREEN)
   worker=self.make_wifi_worker(host,tcp,stop)
  else:
   self.set_state(f"USB-CAN · écoute sur {self.port.get()}",GREEN)
   worker=self.make_serial_worker(self.port.get(),self.baud.get(),stop)
  threading.Thread(target=worker,daemon=True).start()

 def make_serial_worker(self,port_name,baud,stop):
  q=self.q
  def worker():
   try:
    with serial.Serial(port_name,int(baud),timeout=.2) as port:
     buf=bytearray()
     while not stop.is_set():
      buf.extend(port.read(512))
      while len(buf)>3:
       ix=buf.find(b"\xaa")
       if ix<0:buf.clear();break
       del buf[:ix]
       if len(buf)<3:break
       typ=buf[1]
       if typ==0x55:
        if len(buf)<20:break
        p=bytes(buf[:20]);del buf[:20]
        if p[2]==1 and p[3] in (1,2) and p[4]==1 and p[9]<=8 and (sum(p[2:19])&255)==p[19]:
         q.put((int.from_bytes(p[5:9],"little"),p[10:10+p[9]]))
        continue
       if typ&0xc0!=0xc0 or (typ&15)>8:del buf[0];continue
       idlen=4 if typ&0x20 else 2;total=3+idlen+(typ&15)
       if len(buf)<total:break
       if buf[total-1]!=0x55:del buf[0];continue
       p=bytes(buf[:total]);del buf[:total]
       if not typ&0x10:q.put((int.from_bytes(p[2:2+idlen],"little"),p[2+idlen:-1]))
   except Exception as e:q.put(("error",str(e)))
  return worker

 def make_wifi_worker(self,host,port,stop):
  q=self.q
  def worker():
   try:
    with socket.create_connection((host,port),timeout=3) as sock:
     sock.settimeout(.3)
     buf=bytearray()
     while not stop.is_set():
      try:chunk=sock.recv(4096)
      except socket.timeout:continue
      if not chunk:raise ConnectionError("l'ESP32 a fermé la connexion")
      buf.extend(chunk)
      while len(buf)>=WIFI_FRAME_LEN:
       ix=buf.find(WIFI_MAGIC)
       if ix<0:del buf[:-1];break
       if ix>0:del buf[:ix]
       if len(buf)<WIFI_FRAME_LEN:break
       p=bytes(buf[:WIFI_FRAME_LEN])
       if xor_sum(p[2:19])!=p[19]:del buf[:1];continue
       del buf[:WIFI_FRAME_LEN]
       cid=int.from_bytes(p[6:10],"little");dlc=min(p[10],8)
       q.put((cid,p[11:11+dlc]))
   except Exception as e:q.put(("error",str(e)))
  return worker

 def run(self):self.root.mainloop()

if __name__=="__main__":App().run()
