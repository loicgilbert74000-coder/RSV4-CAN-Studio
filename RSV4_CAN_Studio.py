import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import re, time, math, queue, threading, os, sys, socket
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
SPEEDS=[0.25,0.5,1,2,4,8]
TILE_W=186; TILE_COLS=5

# Profils de moto. "decoder" : décodages CAN définis pour ce modèle (None = trames brutes seulement).
# Les échelles (rpm_max, speed_max) sont des valeurs d'affichage ; à confirmer pour chaque moto.
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

# Index de la définition : signaux par identifiant CAN et clés uniques (identifiant, nom)
BY_CID={}
for _s in SIGNALS: BY_CID.setdefault(_s[0],[]).append(_s)
SIG_KEYS=list(dict.fromkeys((s[0],s[1]) for s in SIGNALS))

# Groupes d'affichage des signaux sur la page « Bus en direct »
GROUP_OF={0x100:"Moteur",0x114:"Moteur",0x601:"Gaz",0x7F2:"Gaz",0x7F6:"Gaz",0x260:"Roues",
          0x102:"Freins & sécurité",0x261:"Freins & sécurité",0x104:"Modes & aides",0x230:"Modes & aides",
          0x106:"Couple",0x108:"Commandes",0x300:"Commandes",0x174:"Centrale inertielle",
          0x178:"Centrale inertielle",0x262:"Centrale inertielle",0x200:"Températures & électrique",
          0x222:"Carburant & air",0x226:"Clignotants",0x220:"Divers",0x224:"Divers",0x228:"Divers",
          0x382:"Non identifié"}
GROUP_ORDER=["Moteur","Gaz","Roues","Freins & sécurité","Modes & aides","Couple","Centrale inertielle",
             "Températures & électrique","Carburant & air","Clignotants","Commandes","Divers","Non identifié","Autres"]

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

def make_dot(parent,color,bg,size=10):
 c=tk.Canvas(parent,width=size,height=size,bg=bg,highlightthickness=0)
 c.create_oval(1,1,size-1,size-1,fill=color,outline="",tags="d")
 return c
def set_dot(c,color):c.itemconfig("d",fill=color)

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
  self.window=tk.IntVar(value=60)
  self.curve_vars={k:tk.BooleanVar(value=k in DEFAULT_CURVES) for k in SIG_KEYS}
  self.count=Counter();self.first_t={};self.last_t={}
  self.vals={};self.hist={};self.dirty=set();self.flash_until={};self.tiles={}
  self.t_now=0;self.recent=deque();self.ingested=0;self.t_last=0;self.t0=0;self.last_row=None
  self.start_wall=0;self.start_frame=0;self.q=queue.Queue();self.live=False;self.stop_event=threading.Event()
  self.cards={};self.pages={};self.nav={};self.flushables=[];self.srow={};self.fl={};self.badge={}
  self.decoder=None;self.model_key="rsv4"
  self.set_styles()
  self.build_footer()
  self.build_sidebar()
  self.build_main()
  self.apply_model("rsv4")
  self.show_page("bus")
  self.set_conn_ui(False,"Déconnecté")
  self.set_state("Prêt · ouvrez une capture",MUTED)
  self.root.after(40,self.tick);self.root.after(180,self.paint_chart)
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
  logo=tk.Frame(side,bg=SIDE);logo.pack(fill="x",padx=20,pady=(20,6))
  tk.Label(logo,text="RSV4",fg=RED,bg=SIDE,font=(FONT,30,"bold italic")).pack(anchor="w")
  tk.Label(logo,text="CAN STUDIO",fg=TEXT,bg=SIDE,font=(FONT,11,"bold")).pack(anchor="w")

  self.section(side,"MOTO")
  mc=tk.Frame(side,bg=SIDE);mc.pack(fill="x",padx=14,pady=2)
  self.model_cb=ttk.Combobox(mc,values=[m["label"] for m in MODELS.values()],state="readonly",font=(FONT,9))
  self.model_cb.pack(fill="x");self.model_cb.bind("<<ComboboxSelected>>",self.on_model)

  self.section(side,"NAVIGATION")
  self.nav_item(side,"bus","Bus en direct")
  self.nav_item(side,"graph","Analyse")
  self.nav_item(side,"frames","Trames CAN")
  self.nav_item(side,"settings","Paramètres")

  self.section(side,"CONNEXION CAN")
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
  # Lignes propres au port série USB-CAN
  r_port=row("Port COM",lambda p:ttk.Combobox(p,textvariable=self.port,values=[f"COM{i}" for i in range(1,21)],width=13))
  r_baud=row("Vitesse",lambda p:ttk.Combobox(p,textvariable=self.baud,values=["2000000","1000000","500000","250000"],width=13))
  r_br=tk.Frame(inner,bg=CARD)
  tk.Label(r_br,text="CAN bitrate",bg=CARD,fg=SUB,font=(FONT,9),anchor="w",width=12).pack(side="left")
  self.bitrate_cb=ttk.Combobox(r_br,state="readonly",width=13);self.bitrate_cb.pack(side="right")
  self.serial_rows=[r_port,r_baud,r_br]
  # Lignes propres à la connexion Wi-Fi vers l'ESP32
  r_host=row("Adresse ESP32",lambda p:tk.Entry(p,textvariable=self.host,width=14,bg=CARD2,fg=TEXT,insertbackground=TEXT,relief="flat",highlightbackground=BORDER,highlightthickness=1))
  r_tcp=row("Port TCP",lambda p:tk.Entry(p,textvariable=self.tcp_port,width=14,bg=CARD2,fg=TEXT,insertbackground=TEXT,relief="flat",highlightbackground=BORDER,highlightthickness=1))
  self.wifi_rows=[r_host,r_tcp]
  st=tk.Frame(inner,bg=CARD);st.pack(fill="x",pady=(8,6))
  self.conn_status=st
  self.conn_dot=make_dot(st,MUTED,CARD,10);self.conn_dot.pack(side="left",padx=(2,6))
  self.conn_lbl=tk.Label(st,text="Déconnecté",bg=CARD,fg=SUB,font=(FONT,10,"bold"));self.conn_lbl.pack(side="left")
  self.conn_btn=tk.Button(inner,text="Connecter",command=self.toggle_connect,bg=RED,fg="#ffffff",activebackground="#ff3b44",
                          activeforeground="#ffffff",relief="flat",bd=0,highlightthickness=0,font=(FONT,10,"bold"),cursor="hand2",pady=6)
  self.conn_btn.pack(fill="x")
  self.on_transport()

  self.section(side,"FICHIER DE LECTURE")
  card2=self.card(side);card2.pack(fill="x",padx=14,pady=2)
  in2=tk.Frame(card2,bg=CARD);in2.pack(fill="x",padx=12,pady=8)
  self.button(in2,"Ouvrir un fichier .txt",self.open_file,TEXT,CARD2).pack(fill="x")
  tk.Label(in2,textvariable=self.file_name,bg=CARD,fg=SUB,font=(FONT,8),anchor="w",wraplength=190,justify="left").pack(fill="x",pady=(6,4))
  tr=tk.Frame(in2,bg=CARD);tr.pack(fill="x",pady=2)
  self.button(tr,"Lecture",self.play,GREEN,CARD2,font=9).pack(side="left",expand=True,fill="x",padx=2)
  self.button(tr,"Pause",self.pause,YELLOW,CARD2,font=9).pack(side="left",expand=True,fill="x",padx=2)
  self.button(tr,"Début",self.reset,SUB,CARD2,font=9).pack(side="left",expand=True,fill="x",padx=2)
  sp=tk.Frame(in2,bg=CARD);sp.pack(fill="x",pady=(8,0))
  self.speed_lbl=tk.Label(sp,text="Vitesse x1",bg=CARD,fg=SUB,font=(FONT,9));self.speed_lbl.pack(side="left")
  slider=tk.Scale(in2,from_=0,to=len(SPEEDS)-1,resolution=1,orient="horizontal",showvalue=False,command=self.on_speed,
                  bg=CARD,troughcolor=CARD2,highlightthickness=0,activebackground=RED,bd=0,sliderlength=14,width=10)
  slider.set(SPEEDS.index(1)); slider.pack(fill="x")
  tk.Label(in2,text="Progression",bg=CARD,fg=MUTED,font=(FONT,8)).pack(anchor="w",pady=(6,0))
  ttk.Progressbar(in2,variable=self.progress,maximum=100,style="Rsv.Horizontal.TProgressbar").pack(fill="x",pady=(2,2))
  tk.Label(in2,textvariable=self.clock,bg=CARD,fg=TEXT,font=(FONT,9,"bold")).pack(anchor="e")

 def on_transport(self,e=None):
  wifi=self.transport.get().startswith("Wi-Fi")
  for r in self.serial_rows+self.wifi_rows:r.pack_forget()
  for r in (self.wifi_rows if wifi else self.serial_rows):r.pack(fill="x",pady=2,before=self.conn_status)

 def ro_combo(self,parent,values):
  c=ttk.Combobox(parent,values=values,state="readonly",width=15);c.current(0);return c

 def on_speed(self,v):
  val=SPEEDS[int(float(v))];self.speed.set(val);self.speed_lbl.config(text=f"Vitesse x{val:g}")

 def build_main(self):
  main=tk.Frame(self.root,bg=BG);main.pack(side="left",fill="both",expand=True)
  head=tk.Frame(main,bg=BG);head.pack(fill="x",padx=22,pady=(16,6))
  tk.Label(head,text="Diagnostic & Télémétrie CAN",fg=TEXT,bg=BG,font=(FONT,20,"bold")).pack(anchor="w")
  self.subtitle=tk.Label(head,text="",fg=SUB,bg=BG,font=(FONT,11));self.subtitle.pack(anchor="w")
  self.area=tk.Frame(main,bg=BG);self.area.pack(fill="both",expand=True,padx=18,pady=(0,10))
  self.page_bus=tk.Frame(self.area,bg=BG)
  self.page_graph=tk.Frame(self.area,bg=BG)
  self.page_frames=tk.Frame(self.area,bg=BG)
  self.pages={"bus":self.page_bus,"graph":self.page_graph,"frames":self.page_frames}
  self.build_bus(self.page_bus)
  self.build_graph(self.page_graph)
  self.build_table(self.page_frames)

 def show_page(self,key):
  for p in self.pages.values():p.pack_forget()
  self.pages[key].pack(fill="both",expand=True)
  for k,(row,bar,lbl) in self.nav.items():
   on=(k==key)
   row.config(bg=HOVER if on else SIDE);bar.config(bg=RED if on else SIDE)
   lbl.config(bg=HOVER if on else SIDE,fg=TEXT if on else SUB)

 # ---------- page 1 : bus en direct ----------
 def build_bus(self,parent):
  top=tk.Frame(parent,bg=BG);top.pack(fill="x")
  self.build_top(top)
  head=tk.Frame(parent,bg=BG);head.pack(fill="x",pady=(10,2))
  tk.Label(head,text="Tous les paramètres du bus",fg=TEXT,bg=BG,font=(FONT,13,"bold")).pack(side="left")
  self.bus_note=tk.Label(head,text="",fg=SUB,bg=BG,font=(FONT,9));self.bus_note.pack(side="left",padx=12)
  wrap,inner=self.scroll_area(parent,BG)
  wrap.pack(fill="both",expand=True,pady=(2,0))
  groups={}
  for s in SIGNALS:groups.setdefault(GROUP_OF.get(s[0],"Autres"),[]).append(s)
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
  tk.Label(f,text=name.replace("_"," "),fg=SUB,bg=CARD,font=(FONT,8,"bold"),anchor="w").pack(fill="x",padx=10,pady=(8,0))
  row=tk.Frame(f,bg=CARD);row.pack(anchor="w",padx=10)
  vl=tk.Label(row,text="—",fg=TEXT,bg=CARD,font=(FONT,18,"bold"));vl.pack(side="left")
  if unit:tk.Label(row,text=disp_unit(unit),fg=MUTED,bg=CARD,font=(FONT,9)).pack(side="left",padx=(5,0),pady=(9,0))
  sl=tk.Label(f,text=f"0x{cid:03X}",fg=MUTED,bg=CARD,font=(FONT,7,"bold"),anchor="w")
  sl.pack(side="bottom",fill="x",padx=10,pady=(0,6))
  self.tiles[(cid,name)]=(f,vl,sl)
  return f

 def put(self,cid,name,val,t,src):
  """Enregistre une valeur décodée : valeur courante, historique pour les courbes, mise à jour de la tuile."""
  key=(cid,name);self.vals[key]=(val,src)
  h=self.hist.get(key)
  if h is None:h=self.hist[key]=deque(maxlen=8000)
  h.append((t,val));self.dirty.add(key)

 def refresh_tile(self,key):
  f,vl,sl=self.tiles[key];val,src=self.vals[key]
  vl.config(text=fmt_val(val))
  if src=="def":sl.config(text=f"0x{key[0]:03X} · définition",fg=MUTED)
  elif src=="valid":sl.config(text=f"0x{key[0]:03X} · validé",fg=GREEN)
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

 # ---------- page 2 : analyse (courbes) ----------
 def build_graph(self,parent):
  side=self.card(parent);side.pack(side="left",fill="y",padx=4,pady=4)
  tk.Label(side,text="Signaux tracés",fg=TEXT,bg=CARD,font=(FONT,11,"bold")).pack(anchor="w",padx=12,pady=(10,4))
  bt=tk.Frame(side,bg=CARD);bt.pack(fill="x",padx=10)
  self.button(bt,"Défaut",lambda:self.set_curves(DEFAULT_CURVES),SUB,CARD2,font=9).pack(side="left",expand=True,fill="x",padx=2)
  self.button(bt,"Aucun",lambda:self.set_curves([]),SUB,CARD2,font=9).pack(side="left",expand=True,fill="x",padx=2)
  wrap,inner=self.scroll_area(side,CARD,width=250)
  wrap.pack(fill="both",expand=True,padx=6,pady=6)
  for i,key in enumerate(SIG_KEYS):
   cid,name=key;color=PALETTE[i%len(PALETTE)]
   tk.Checkbutton(inner,text=f"{name.replace('_',' ')}  ·  0x{cid:03X}",variable=self.curve_vars[key],bg=CARD,fg=color,
                  selectcolor=CARD2,activebackground=CARD,activeforeground=color,font=(FONT,9),bd=0,highlightthickness=0,
                  anchor="w").pack(fill="x",padx=4,pady=0)
  main=self.card(parent);main.pack(fill="both",expand=True,padx=4,pady=4)
  hdr=tk.Frame(main,bg=CARD);hdr.pack(fill="x",padx=14,pady=(10,2))
  tk.Label(hdr,text="Analyse des courbes",fg=TEXT,bg=CARD,font=(FONT,12,"bold")).pack(side="left")
  wc=ttk.Combobox(hdr,values=["30 s","60 s","120 s","300 s"],state="readonly",width=7)
  wc.current(1);wc.pack(side="right")
  wc.bind("<<ComboboxSelected>>",lambda e:self.window.set(int(wc.get().split()[0])))
  tk.Label(hdr,text="Fenêtre",fg=SUB,bg=CARD,font=(FONT,9)).pack(side="right",padx=(0,6))
  self.chart=tk.Canvas(main,bg=CARD,highlightthickness=0)
  self.chart.pack(fill="both",expand=True,padx=10,pady=(4,10))

 def set_curves(self,keys):
  for k,v in self.curve_vars.items():v.set(k in keys)

 def paint_chart(self):
  c=self.chart;c.delete("all");w=c.winfo_width();h=c.winfo_height()
  if w>300 and h>120:
   win=self.window.get();L,R,T,B=56,300,16,30;pw=w-L-R;ph=h-T-B
   span=win*1000;start=self.t_now-span
   for i in range(5):
    y=T+ph*i/4;c.create_line(L,y,L+pw,y,fill=BORDER)
   for frac,label,anc in [(0,f"-{win} s","w"),(.5,f"-{win//2} s","center"),(1,"maintenant","e")]:
    c.create_text(L+pw*frac,h-12,text=label,fill=MUTED,font=(FONT,8),anchor=anc)
   lx=L+pw+14;ly=T+4
   c.create_text(lx,ly,text="Signal · min · max · actuel",anchor="nw",fill=SUB,font=(FONT,8,"bold"))
   row=0
   for i,key in enumerate(SIG_KEYS):
    if not self.curve_vars[key].get():continue
    color=PALETTE[i%len(PALETTE)];cid,name=key
    pts=[]
    for t,v in reversed(self.hist.get(key,())):
     if t<start:break
     pts.append((t,v))
    pts.reverse()
    y0=ly+26+row*38;row+=1
    c.create_line(lx,y0+7,lx+18,y0+7,fill=color,width=3)
    c.create_text(lx+26,y0,text=f"{name.replace('_',' ')} · 0x{cid:03X}",anchor="nw",fill=TEXT,font=(FONT,8,"bold"))
    if len(pts)<2:
     c.create_text(lx+26,y0+14,text="pas de donnée",anchor="nw",fill=MUTED,font=(FONT,8))
     continue
    vals=[v for _,v in pts];mn=min(vals);mx=max(vals);rng=mx-mn
    coords=[]
    for t,v in pts:
     x=L+pw*(t-start)/span
     y=T+ph/2 if rng==0 else T+ph*(1-(v-mn)/rng)
     coords.extend((x,y))
    c.create_line(*coords,fill=color,width=2)
    c.create_text(lx+26,y0+14,text=f"min {fmt_val(mn)} · max {fmt_val(mx)} · {fmt_val(vals[-1])}",anchor="nw",fill=SUB,font=(FONT,8))
  self.root.after(180,self.paint_chart)

 # ---------- trames ----------
 def build_table(self,parent):
  card=self.card(parent);card.pack(fill="both",expand=True,padx=4,pady=4)
  hdr=tk.Frame(card,bg=CARD);hdr.pack(fill="x",padx=14,pady=(10,4))
  tk.Label(hdr,text="Trames CAN en direct",fg=TEXT,bg=CARD,font=(FONT,12,"bold")).pack(side="left")
  self.button(hdr,"Vider",self.clear_table,SUB,CARD2,font=9).pack(side="right")
  tk.Checkbutton(hdr,text="Filtrage activé (trames décodées seulement)",variable=self.filter_on,bg=CARD,fg=SUB,
                 selectcolor=CARD2,activebackground=CARD,font=(FONT,9),bd=0,highlightthickness=0).pack(side="right",padx=12)
  tw=tk.Frame(card,bg=CARD);tw.pack(fill="both",expand=True,padx=10,pady=(0,10))
  cols=[("n","#",55,"e"),("time","Temps",95,"w"),("id","ID",75,"w"),("dlc","DLC",45,"center"),
        ("hex","Hex",190,"w"),("dec","Décimal",190,"w"),("freq","Fréq. (Hz)",85,"e"),("txt","Décodage / signaux",440,"w")]
  self.table=ttk.Treeview(tw,columns=[c[0] for c in cols],show="headings",height=6)
  for key,label,width,anchor in cols:
   self.table.heading(key,text=label,anchor=anchor);self.table.column(key,width=width,anchor=anchor,stretch=(key=="txt"))
  self.table.tag_configure("new",background="#174a36",foreground=TEXT)
  sb=ttk.Scrollbar(tw,orient="vertical",command=self.table.yview);self.table.configure(yscrollcommand=sb.set)
  self.table.pack(side="left",fill="both",expand=True);sb.pack(side="right",fill="y")

 def clear_table(self):
  for row in self.table.get_children():self.table.delete(row)
  self.last_row=None

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
  self.vals.clear();self.hist.clear();self.dirty.clear();self.flash_until.clear()
  self.clear_table()
  for key in self.cards:self.show(key,None)
  self.gear.set(None);self.gear_val.config(text="—");self.rpm.set(None);self.speedg.set(None)
  self.tps_lbl.config(text="TPS1 —  ·  TPS2 —")
  for key,(f,vl,sl) in self.tiles.items():vl.config(text="—",fg=TEXT)

 def load(self,path):
  try:frames=load_capture(path)
  except Exception as exc:messagebox.showerror("Erreur de lecture",str(exc));return
  self.pause();self.frames=frames;self.idx=0;self.clear_data()
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

 def ingest(self,t,cid,data):
  self.t_now=t
  self.count[cid]+=1;self.ingested+=1;self.t_last=t;self.recent.append(t)
  self.first_t.setdefault(cid,t);self.last_t[cid]=t
  dec="—"
  if self.decoder=="aprilia":
   dec=self.decode_aprilia(t,cid,data)
   parts=self.decode_generic(t,cid,data)
   if parts:dec=" | ".join(parts) if dec=="—" else dec+" | "+" | ".join(parts)
  n=self.count[cid];freq="—"
  if n>1 and self.last_t[cid]>self.first_t[cid]:freq=f"{(n-1)*1000/(self.last_t[cid]-self.first_t[cid]):.0f}"
  hide=self.filter_on.get() and self.decoder is not None and dec=="—"
  if not hide:
   try:
    if self.last_row is not None:self.table.item(self.last_row,tags=())
   except tk.TclError:self.last_row=None
   self.last_row=self.table.insert("",0,values=(self.ingested,fmt_ms(t),f"0x{cid:03X}",len(data),
                                                data.hex(" ").upper()," ".join(str(b) for b in data),freq,dec),tags=("new",))
   kids=self.table.get_children()
   if len(kids)>400:self.table.delete(kids[-1])

 # ---------- boucle ----------
 def update_status(self):
  now=int(time.monotonic()*1000) if self.live else self.t_last
  while self.recent and self.recent[0]<now-1000:self.recent.popleft()
  rate=len(self.recent) if (self.live or self.frames) else 0
  if self.frames:
   total=self.frames[-1][0];cur=self.frames[self.idx-1][0] if self.idx>0 else 0
   self.progress.set(100*self.idx/len(self.frames));self.clock.set(f"{fmt_time(cur)} / {fmt_time(total)}")
   dur=cur
  else:dur=(now-self.t0) if self.live else 0
  self.fl["dur"].config(text=fmt_time(dur))
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
  self.set_srow("gps","Non connecté",MUTED)
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
