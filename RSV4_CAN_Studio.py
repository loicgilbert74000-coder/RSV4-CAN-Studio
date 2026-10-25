import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import re, time, math, queue, threading, os, sys
from collections import Counter, deque
try: import serial
except ImportError: serial=None

# Palette inspirée de la maquette : fond très sombre, cartes, accents par grandeur
BG="#070d16"; SIDE="#0b1220"; CARD="#111a2a"; CARD2="#1c2739"; BORDER="#23314b"; HOVER="#1f2e47"
TEXT="#eef3fb"; SUB="#9fb0c8"; MUTED="#5d7090"
RED="#e52028"; GREEN="#2fe39a"; CYAN="#3cc0ff"; YELLOW="#ffb938"; ORANGE="#ff8a3d"; VIOLET="#a98bff"; PINK="#ff5fa2"; LIME="#a3e635"
FONT="Segoe UI"
SPEEDS=[0.25,0.5,1,2,4,8]

# (libellé, clé, couleur, échelle maximale) ; régime à gauche, gaz à droite, le reste normalisé
SERIES=[("Régime moteur","rpm",RED,16000),("Vitesse","speed",CYAN,320),("Position gaz","thr",GREEN,100),
        ("Temp. moteur","temp",ORANGE,150),("Roue AV","front",VIOLET,300),("Roue AR","rear",PINK,300)]

# Exports USB-CAN: NUL between columns; frame ID 8-digit hex, DLC, bytes.
LINE=re.compile(r"Receive\s+(\d{2}:\d{2}:\d{2}:\d{3}).*?(?:Standard|Extended)\s+frame\s+([0-9a-fA-F]{8})\s+([0-8])\s+((?:[0-9a-fA-F]{2}\s*){1,8})",re.I)
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
  self.port=tk.StringVar(value="COM7");self.baud=tk.StringVar(value="2000000");self.experimental=tk.BooleanVar(value=True)
  self.filter_on=tk.BooleanVar(value=True)
  self.visible={key:tk.BooleanVar(value=True) for _,key,_,_ in SERIES}
  self.count=Counter();self.first_t={};self.last_t={};self.decode_txt={}
  self.series=deque(maxlen=6000);self.window=60
  self.recent=deque();self.ingested=0;self.t_last=0;self.t0=0;self.last_row=None
  self.sv={"rpm":None,"speed":None,"thr":None,"temp":None,"front":None,"rear":None}
  self.start_wall=0;self.start_frame=0;self.q=queue.Queue();self.live=False;self.stop_event=threading.Event()
  self.cards={};self.pages={};self.nav={};self.flushables=[];self.srow={};self.fl={}
  self.set_styles()
  self.build_footer()
  self.build_sidebar()
  self.build_main()
  self.show_page("dash")
  self.set_conn_ui(False,"Déconnecté")
  self.set_state("Prêt · ouvrez une capture",MUTED)
  self.root.after(40,self.tick);self.root.after(180,self.paint_chart)
  base=getattr(sys,"_MEIPASS",os.path.dirname(os.path.abspath(__file__)))
  bundled=os.path.join(base,"CAPTURE_GAZ_RSV4.txt")
  if os.path.exists(bundled):self.load(bundled)

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
              relief="flat",bd=0,highlightthickness=0,padx=10,pady=6,font=(FONT,font,"bold"),cursor="hand2",anchor=anchor)
  b.bind("<Enter>",lambda e:b.config(bg=HOVER));b.bind("<Leave>",lambda e:b.config(bg=bg))
  return b

 def transport(self,parent,kind,cmd,color):
  c=tk.Canvas(parent,width=62,height=40,bg=CARD2,highlightthickness=0,cursor="hand2")
  if kind=="play":c.create_polygon(24,12,24,28,40,20,fill=color,outline="")
  elif kind=="pause":
   c.create_rectangle(23,12,28,28,fill=color,outline="");c.create_rectangle(34,12,39,28,fill=color,outline="")
  else:c.create_rectangle(23,12,39,28,fill=color,outline="")
  c.bind("<Button-1>",lambda e:cmd())
  return c

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

 # ---------- structure ----------
 def build_footer(self):
  foot=tk.Frame(self.root,bg=SIDE,highlightbackground=BORDER,highlightthickness=1);foot.pack(side="bottom",fill="x")
  self.fl["dot"]=make_dot(foot,MUTED,SIDE,10);self.fl["dot"].pack(side="left",padx=(16,8),pady=10)
  tk.Label(foot,textvariable=self.status,fg=SUB,bg=SIDE,font=(FONT,9,"bold")).pack(side="left")
  tk.Label(foot,text="   Seule la poignée de gaz est validée · TPS1 / TPS2 non identifiés dans vos captures",fg=YELLOW,bg=SIDE,font=(FONT,9)).pack(side="left")
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

  self.section(side,"NAVIGATION")
  self.nav_item(side,"dash","Tableau de bord")
  self.nav_item(side,"graph","Graphiques")
  self.nav_item(side,"frames","Trames CAN")
  self.nav_item(side,"settings","Paramètres")

  self.section(side,"CONNEXION CAN")
  card=self.card(side);card.pack(fill="x",padx=14,pady=2)
  inner=tk.Frame(card,bg=CARD);inner.pack(fill="x",padx=12,pady=8)
  def field(label,widget):
   row=tk.Frame(inner,bg=CARD);row.pack(fill="x",pady=2)
   tk.Label(row,text=label,bg=CARD,fg=SUB,font=(FONT,9),anchor="w",width=12).pack(side="left")
   widget(row).pack(side="right")
  field("Port COM",lambda p:ttk.Combobox(p,textvariable=self.port,values=[f"COM{i}" for i in range(1,21)],width=13))
  field("Vitesse",lambda p:ttk.Combobox(p,textvariable=self.baud,values=["2000000","1000000","500000","250000"],width=13))
  field("Mode CAN",lambda p:self.ro_combo(p,["Silent (écoute)"]))
  field("Type trame",lambda p:self.ro_combo(p,["Standard 11 bits"]))
  field("CAN bitrate",lambda p:self.ro_combo(p,["250 kbit/s"]))
  st=tk.Frame(inner,bg=CARD);st.pack(fill="x",pady=(8,6))
  self.conn_dot=make_dot(st,MUTED,CARD,10);self.conn_dot.pack(side="left",padx=(2,6))
  self.conn_lbl=tk.Label(st,text="Déconnecté",bg=CARD,fg=SUB,font=(FONT,10,"bold"));self.conn_lbl.pack(side="left")
  self.conn_btn=tk.Button(inner,text="Connecter",command=self.toggle_connect,bg=RED,fg="#ffffff",activebackground="#ff3b44",
                          activeforeground="#ffffff",relief="flat",bd=0,highlightthickness=0,font=(FONT,10,"bold"),cursor="hand2",pady=6)
  self.conn_btn.pack(fill="x")

  self.section(side,"FICHIER DE LECTURE")
  card2=self.card(side);card2.pack(fill="x",padx=14,pady=2)
  in2=tk.Frame(card2,bg=CARD);in2.pack(fill="x",padx=12,pady=8)
  self.button(in2,"Ouvrir un fichier .txt",self.open_file,TEXT,CARD2).pack(fill="x")
  tk.Label(in2,textvariable=self.file_name,bg=CARD,fg=SUB,font=(FONT,8),anchor="w",wraplength=190,justify="left").pack(fill="x",pady=(6,4))
  tr=tk.Frame(in2,bg=CARD);tr.pack(fill="x",pady=2)
  self.transport(tr,"play",self.play,GREEN).pack(side="left",expand=True,fill="x",padx=2)
  self.transport(tr,"pause",self.pause,YELLOW).pack(side="left",expand=True,fill="x",padx=2)
  self.transport(tr,"stop",self.reset,SUB).pack(side="left",expand=True,fill="x",padx=2)
  sp=tk.Frame(in2,bg=CARD);sp.pack(fill="x",pady=(8,0))
  self.speed_lbl=tk.Label(sp,text="Vitesse x1.0",bg=CARD,fg=SUB,font=(FONT,9));self.speed_lbl.pack(side="left")
  slider=tk.Scale(in2,from_=0,to=len(SPEEDS)-1,resolution=1,orient="horizontal",showvalue=False,command=self.on_speed,
                  bg=CARD,troughcolor=CARD2,highlightthickness=0,activebackground=RED,bd=0,sliderlength=14,width=10)
  slider.set(SPEEDS.index(1)); slider.pack(fill="x")
  tk.Label(in2,text="Progression",bg=CARD,fg=MUTED,font=(FONT,8)).pack(anchor="w",pady=(6,0))
  ttk.Progressbar(in2,variable=self.progress,maximum=100,style="Rsv.Horizontal.TProgressbar").pack(fill="x",pady=(2,2))
  tk.Label(in2,textvariable=self.clock,bg=CARD,fg=TEXT,font=(FONT,9,"bold")).pack(anchor="e")

 def ro_combo(self,parent,values):
  c=ttk.Combobox(parent,values=values,state="readonly",width=15);c.current(0);return c

 def on_speed(self,v):
  val=SPEEDS[int(float(v))];self.speed.set(val);self.speed_lbl.config(text=f"Vitesse x{val:g}")

 def build_main(self):
  main=tk.Frame(self.root,bg=BG);main.pack(side="left",fill="both",expand=True)
  head=tk.Frame(main,bg=BG);head.pack(fill="x",padx=22,pady=(16,6))
  tk.Label(head,text="Diagnostic & Télémétrie CAN",fg=TEXT,bg=BG,font=(FONT,20,"bold")).pack(anchor="w")
  tk.Label(head,text="Aprilia RSV4 Factory 2024",fg=SUB,bg=BG,font=(FONT,11)).pack(anchor="w")
  self.area=tk.Frame(main,bg=BG);self.area.pack(fill="both",expand=True,padx=18,pady=(0,10))
  self.top=tk.Frame(self.area,bg=BG)
  self.mid=tk.Frame(self.area,bg=BG)
  self.bot=tk.Frame(self.area,bg=BG)
  self.build_top(self.top)
  self.build_graph(self.mid)
  self.build_table(self.bot)

 def show_page(self,key):
  for w in (self.top,self.mid,self.bot):w.pack_forget()
  if key=="dash":
   self.top.pack(fill="x")
   self.bot.pack(side="bottom",fill="x",pady=(8,0))
   self.mid.pack(fill="both",expand=True,pady=(0,0))
  elif key=="graph":self.mid.pack(fill="both",expand=True)
  elif key=="frames":self.bot.pack(fill="both",expand=True)
  for k,(row,bar,lbl) in self.nav.items():
   on=(k==key)
   row.config(bg=HOVER if on else SIDE);bar.config(bg=RED if on else SIDE)
   lbl.config(bg=HOVER if on else SIDE,fg=TEXT if on else SUB)

 # ---------- tableau de bord ----------
 def mcard(self,parent,key,label,unit,color,lo,hi,validated,big=False):
  f=self.card(parent)
  tk.Label(f,text=label,fg=SUB,bg=CARD,font=(FONT,8,"bold"),anchor="w").pack(fill="x",padx=12,pady=(10,0))
  row=tk.Frame(f,bg=CARD);row.pack(anchor="w",padx=12,pady=(2,4))
  val=tk.Label(row,text="—",fg=TEXT,bg=CARD,font=(FONT,30 if big else 18,"bold"));val.pack(side="left")
  if unit:tk.Label(row,text=unit,fg=MUTED,bg=CARD,font=(FONT,10)).pack(side="left",padx=(4,0),pady=(8,0))
  tk.Label(f,text="VALIDÉ" if validated else "À VALIDER",fg=GREEN if validated else YELLOW,bg=CARD,font=(FONT,7,"bold"),anchor="w").pack(fill="x",padx=12)
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
  # colonne de gauche : grille 7 colonnes ; colonne de droite : statut système
  right=tk.Frame(parent,bg=BG,width=270);right.pack(side="right",fill="y",padx=(10,0));right.pack_propagate(False)
  left=tk.Frame(parent,bg=BG);left.pack(side="left",fill="both",expand=True)
  for c in range(7):left.columnconfigure(c,weight=1,uniform="c")
  left.rowconfigure(0,minsize=240);left.rowconfigure(1,minsize=150)

  g=self.card(left);g.grid(row=0,column=0,columnspan=2,rowspan=2,sticky="nsew",padx=4,pady=4)
  tk.Label(g,text="Régime moteur",fg=SUB,bg=CARD,font=(FONT,9,"bold")).pack(anchor="w",padx=14,pady=(10,0))
  tk.Label(g,text="À VALIDER · 0x100",fg=YELLOW,bg=CARD,font=(FONT,7,"bold")).pack(anchor="w",padx=14)
  self.rpm=self.reg(Gauge(g,16000,"tr/min",[(v/16,str(v)) for v in range(0,17,2)],
                          lambda f:GREEN if f<.5 else (YELLOW if f<.8 else RED)))
  self.rpm.pack(fill="both",expand=True,padx=6,pady=(0,6))

  s=self.card(left);s.grid(row=0,column=2,columnspan=2,sticky="nsew",padx=4,pady=4)
  tk.Label(s,text="Vitesse moto",fg=SUB,bg=CARD,font=(FONT,9,"bold")).pack(anchor="w",padx=14,pady=(10,0))
  tk.Label(s,text="À VALIDER · 0x100",fg=YELLOW,bg=CARD,font=(FONT,7,"bold")).pack(anchor="w",padx=14)
  self.speedg=self.reg(Gauge(s,320,"km/h",[(i/4,str(80*i)) for i in range(5)],lambda f:CYAN))
  self.speedg.pack(fill="both",expand=True,padx=6,pady=(0,6))

  gc=self.card(left);gc.grid(row=0,column=4,sticky="nsew",padx=4,pady=4)
  tk.Label(gc,text="Rapport engagé",fg=SUB,bg=CARD,font=(FONT,8,"bold"),anchor="w").pack(fill="x",padx=12,pady=(10,0))
  gt=tk.Frame(gc,bg=CARD);gt.pack(fill="x",padx=12,pady=(0,4))
  self.gear_val=tk.Label(gt,text="—",fg=TEXT,bg=CARD,font=(FONT,30,"bold"));self.gear_val.pack(side="left")
  tk.Label(gt,text="À VALIDER",fg=YELLOW,bg=CARD,font=(FONT,7,"bold")).pack(side="left",anchor="s",padx=(8,0),pady=(0,10))
  self.gear=self.reg(GearBox(gc,height=36));self.gear.pack(fill="x",padx=8,pady=(0,10))

  gz=self.card(left);gz.grid(row=0,column=5,columnspan=2,sticky="nsew",padx=4,pady=4)
  zt=tk.Frame(gz,bg=CARD);zt.pack(fill="x",padx=12,pady=(10,0))
  tk.Label(zt,text="Position gaz",fg=SUB,bg=CARD,font=(FONT,8,"bold")).pack(side="left")
  tk.Label(zt,text="VALIDÉ · 0x601",fg=GREEN,bg=CARD,font=(FONT,7,"bold")).pack(side="right")
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
   self.mcard(left,key,label,unit,color,lo,hi,False).grid(row=1,column=2+i,sticky="nsew",padx=4,pady=4)

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

 # ---------- graphique ----------
 def build_graph(self,parent):
  card=self.card(parent);card.pack(fill="both",expand=True,padx=4,pady=4)
  hdr=tk.Frame(card,bg=CARD);hdr.pack(fill="x",padx=14,pady=(10,2))
  tk.Label(hdr,text="Graphiques temps réel",fg=TEXT,bg=CARD,font=(FONT,12,"bold")).pack(side="left")
  for label,key,color,_ in SERIES:
   tk.Checkbutton(hdr,text=label,variable=self.visible[key],bg=CARD,fg=color,selectcolor=CARD2,
                  activebackground=CARD,activeforeground=color,font=(FONT,9,"bold"),bd=0,highlightthickness=0).pack(side="left",padx=6)
  self.chart=tk.Canvas(card,bg=CARD,highlightthickness=0)
  self.chart.pack(fill="both",expand=True,padx=10,pady=(4,10))

 def paint_chart(self):
  c=self.chart;c.delete("all");w=c.winfo_width();h=c.winfo_height()
  if w>200 and h>60:
   L,R,T,B=64,62,10,26;pw=w-L-R;ph=h-T-B
   for i in range(5):
    y=T+ph*i/4
    c.create_line(L,y,w-R,y,fill=BORDER)
    c.create_text(L-8,y,text=f"{16000-4000*i:,}".replace(","," "),anchor="e",fill=MUTED,font=(FONT,8))
    c.create_text(w-R+8,y,text=f"{100-25*i} %",anchor="w",fill=GREEN,font=(FONT,8))
   for i,label in enumerate([f"-{self.window}s",f"-{self.window//2}s","0s"]):
    c.create_text(L+pw*i/2,h-10,text=label,anchor=["w","center","e"][i],fill=MUTED,font=(FONT,8))
   pts=list(self.series)
   if len(pts)>1:
    t_end=pts[-1]["t"];start=max(0,t_end-self.window);span=max(1,t_end-start)
    for label,key,color,maximum in SERIES:
     if not self.visible[key].get():continue
     coords=[]
     for p in pts:
      v=p.get(key)
      if p["t"]<start or v is None:continue
      coords.extend([L+pw*(p["t"]-start)/span, T+ph*(1-max(0,min(1,v/maximum)))])
     if len(coords)>=4:c.create_line(*coords,fill=color,width=2)
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
  cols=[("n","#",60,"e"),("time","Temps",100,"w"),("id","ID",80,"w"),("dlc","DLC",50,"center"),
        ("data","Données (hex)",230,"w"),("freq","Fréq. (Hz)",90,"e"),("dec","Décodage / signaux",520,"w")]
  self.table=ttk.Treeview(tw,columns=[c[0] for c in cols],show="headings",height=6)
  for key,label,width,anchor in cols:
   self.table.heading(key,text=label,anchor=anchor);self.table.column(key,width=width,anchor=anchor,stretch=(key=="dec"))
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
  self.count.clear();self.first_t.clear();self.last_t.clear();self.decode_txt.clear()
  self.series.clear();self.recent.clear();self.ingested=0;self.t_last=0
  self.sv={k:None for k in self.sv}
  self.clear_table()
  for key in self.cards:self.show(key,None)
  self.gear.set(None);self.gear_val.config(text="—");self.rpm.set(None);self.speedg.set(None)
  self.tps_lbl.config(text="TPS1 —  ·  TPS2 —")

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

 # ---------- décodage (logique inchangée, seul l'affichage a été repensé) ----------
 def ingest(self,t,cid,data):
  self.count[cid]+=1;self.ingested+=1;self.t_last=t;self.recent.append(t)
  self.first_t.setdefault(cid,t);self.last_t[cid]=t
  sv=self.sv;dec="—"
  if cid==0x7F2 and len(data)>=5:
   # Définition AiM RSV4 EU5: TPS1 sBit=8, TPS2 sBit=24, 16 bits, facteur .119.
   # Hypothèse d'ordre des octets little-endian à valider.
   a=int.from_bytes(data[1:3],'little')*.119;b=int.from_bytes(data[3:5],'little')*.119
   self.tps_lbl.config(text=f"TPS1 {a:.1f}*  ·  TPS2 {b:.1f}*")
   dec=f"Papillon TPS1 {a:.1f} % | TPS2 {b:.1f} %  (hypothèse)"
  if cid==0x601 and data:
   sv["thr"]=data[0];self.show("throttle",data[0],text=f"{data[0]}")
   dec=f"Position gaz : {data[0]} %"
   self.series.append({"t":t/1000,**sv})
  if self.experimental.get():
   if cid==0x100 and len(data)>=5:
    rpm=(data[3]<<8)|data[4];sv["rpm"]=rpm;self.rpm.set(rpm)
    parts=[f"Régime {rpm} tr/min*"]
    if len(data)>=2:
     gear=data[0]&15;self.gear.set(gear);self.gear_val.config(text=str(gear));parts.append(f"Rapport {gear}*")
     if len(data)>=3:
      spd=round((((data[1]<<8)|data[2])&4095)*.25,1);sv["speed"]=spd;self.speedg.set(spd);parts.append(f"Vitesse {spd} km/h*")
    dec=" | ".join(parts)
   if cid==0x200 and len(data)>=2:
    tmp=data[0]-40;oil=data[1]-40;sv["temp"]=tmp
    self.show("temp",tmp);self.show("oil",oil)
    parts=[f"Temp. moteur {tmp} °C*",f"Temp. huile {oil} °C*"]
    if len(data)>=6:
     v=data[5]/10;self.show("battery",v,text=f"{v:.1f}");parts.append(f"Batterie {v:.1f} V*")
    dec=" | ".join(parts)
   if cid==0x260 and len(data)>=5:
    f=round(int.from_bytes(data[1:3],'big')*.01,1);r=round(int.from_bytes(data[3:5],'big')*.01,1)
    sv["front"]=f;sv["rear"]=r
    self.show("front",f,text=f"{f:.1f}");self.show("rear",r,text=f"{r:.1f}")
    dec=f"Roue AV {f:.1f} km/h | Roue AR {r:.1f} km/h*"
  n=self.count[cid];freq="—"
  if n>1 and self.last_t[cid]>self.first_t[cid]:freq=f"{(n-1)*1000/(self.last_t[cid]-self.first_t[cid]):.0f}"
  if not (self.filter_on.get() and dec=="—"):
   try:
    if self.last_row is not None:self.table.item(self.last_row,tags=())
   except tk.TclError:self.last_row=None
   self.last_row=self.table.insert("",0,values=(self.ingested,fmt_ms(t),f"0x{cid:03X}",len(data),
                                                data.hex(" ").upper(),freq,dec),tags=("new",))
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
  self.set_srow("val","Seule la poignée",YELLOW)

 def tick(self):
  if self.playing and self.frames:
   elapsed=(time.monotonic()-self.start_wall)*1000*self.speed.get()
   limit=self.start_frame+elapsed
   batch=0
   while self.idx<len(self.frames) and self.frames[self.idx][0]<=limit and batch<1200:
    self.ingest(*self.frames[self.idx]);self.idx+=1;batch+=1
   if self.idx>=len(self.frames):
    self.playing=False;self.set_state("Lecture terminée",CYAN)
  for _ in range(100):
   try:cid,data=self.q.get_nowait()
   except queue.Empty:break
   if cid=="error":self.disconnect();messagebox.showerror("Connexion série",data)
   else:self.ingest(int(time.monotonic()*1000),cid,data)
  for w in self.flushables:w.flush()
  self.update_status()
  self.root.after(40,self.tick)

 def settings(self):
  win=tk.Toplevel(self.root);win.title("Paramètres");win.configure(bg=CARD);win.geometry("460x310");win.resizable(False,False)
  tk.Label(win,text="Paramètres",fg=TEXT,bg=CARD,font=(FONT,14,"bold")).pack(anchor="w",padx=24,pady=(18,6))
  for label,var in [("Port série",self.port),("Vitesse série (bauds)",self.baud)]:
   tk.Label(win,text=label,bg=CARD,fg=SUB,font=(FONT,9,"bold")).pack(anchor="w",padx=24,pady=(10,3))
   tk.Entry(win,textvariable=var,width=28,bg=CARD2,fg=TEXT,insertbackground=TEXT,relief="flat",highlightbackground=BORDER,highlightthickness=1).pack(anchor="w",padx=24,ipady=4)
  tk.Checkbutton(win,text="Afficher les décodages expérimentaux (non validés)",variable=self.experimental,
                 bg=CARD,fg=TEXT,selectcolor=CARD2,activebackground=CARD,activeforeground=TEXT).pack(anchor="w",padx=20,pady=(14,6))
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
  if serial is None:messagebox.showerror("Dépendance","pyserial manquant");return
  if not messagebox.askokcancel("Sécurité CAN","Configurer l'adaptateur en mode Silent et CAN 250 kbit/s avec USBCAN, puis fermer USBCAN.\n\nCette application n'envoie aucune commande, et ne peut pas vérifier que le mode Silent reste actif.\n\nContinuer ?"):return
  self.disconnect();self.stop_event=threading.Event();stop=self.stop_event;self.live=True
  self.clear_data();self.t0=int(time.monotonic()*1000)
  self.set_conn_ui(True,"Connecté")
  self.set_state(f"USB-CAN · écoute sur {self.port.get()}",GREEN)
  def worker():
   try:
    with serial.Serial(self.port.get(),int(self.baud.get()),timeout=.2) as port:
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
         self.q.put((int.from_bytes(p[5:9],"little"),p[10:10+p[9]]))
        continue
       if typ&0xc0!=0xc0 or (typ&15)>8:del buf[0];continue
       idlen=4 if typ&0x20 else 2;total=3+idlen+(typ&15)
       if len(buf)<total:break
       if buf[total-1]!=0x55:del buf[0];continue
       p=bytes(buf[:total]);del buf[:total]
       if not typ&0x10:self.q.put((int.from_bytes(p[2:2+idlen],"little"),p[2+idlen:-1]))
   except Exception as e:self.q.put(("error",str(e)))
  threading.Thread(target=worker,daemon=True).start()

 def run(self):self.root.mainloop()

if __name__=="__main__":App().run()
