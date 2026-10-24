import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import re, time, math, queue, threading, os, sys
from collections import Counter, deque
try: import serial
except ImportError: serial=None

# Palette sombre : fonds en couches, accents par grandeur mesurée
BG="#0a0f18"; CARD="#131b29"; CARD2="#1c2739"; BORDER="#26344c"; HOVER="#2a3b57"
TEXT="#eef3fb"; SUB="#93a4bd"; MUTED="#63748d"
RED="#ff5b67"; GREEN="#3ddc97"; CYAN="#38bdf8"; YELLOW="#fbbf24"; ORANGE="#fb923c"
VIOLET="#a78bfa"; LIME="#a3e635"; PINK="#f472b6"
FONT="Segoe UI"

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

class Gauge(tk.Canvas):
 def __init__(self,parent,title,maximum,color,unit,badge,badge_color,height=190):
  super().__init__(parent,height=height,bg=CARD,highlightthickness=0)
  self.title=title;self.maximum=maximum;self.color=color;self.unit=unit
  self.badge=badge;self.badge_color=badge_color;self.value=None
  self.bind("<Configure>",lambda e:self.render())
 def set(self,value):self.value=value;self.render()
 def render(self):
  self.delete("all");w=max(200,self.winfo_width());h=max(170,self.winfo_height())
  cx=w/2;cy=h*.57;r=min(w*.36,h*.40);thick=13
  self.create_text(18,18,text=self.title,anchor="w",fill=SUB,font=(FONT,10,"bold"))
  self.create_arc(cx-r,cy-r,cx+r,cy+r,start=210,extent=-240,style="arc",outline=CARD2,width=thick)
  if self.value is not None:
   frac=max(0,min(1,float(self.value)/self.maximum))
   if frac>0:
    self.create_arc(cx-r,cy-r,cx+r,cy+r,start=210,extent=-240*frac,style="arc",outline=self.color,width=thick)
  for i in range(9):
   ang=math.radians(210-240*i/8);r1=r-22;r2=r-12
   self.create_line(cx+r1*math.cos(ang),cy-r1*math.sin(ang),cx+r2*math.cos(ang),cy-r2*math.sin(ang),fill=MUTED,width=2)
  val="—" if self.value is None else f"{self.value:,.0f}".replace(","," ")
  self.create_text(cx,cy-6,text=val,fill=TEXT,font=(FONT,30,"bold"))
  self.create_text(cx,cy+26,text=self.unit,fill=SUB,font=(FONT,11))
  self.create_text(cx,h-18,text=self.badge,fill=self.badge_color,font=(FONT,8,"bold"))

class App:
 def __init__(self):
  self.root=tk.Tk();self.root.title("RSV4 CAN Studio · Telemetry Lab")
  self.root.geometry("1360x900");self.root.minsize(1100,760);self.root.configure(bg=BG)
  self.frames=[];self.idx=0;self.playing=False;self.speed=tk.DoubleVar(value=1.0)
  self.status=tk.StringVar(value="Prêt · ouvrez une capture")
  self.file_name=tk.StringVar(value="Aucun fichier chargé")
  self.clock=tk.StringVar(value="00:00 / 00:00")
  self.progress=tk.DoubleVar(value=0)
  self.port=tk.StringVar(value="COM7");self.baud=tk.StringVar(value="2000000");self.experimental=tk.BooleanVar(value=True)
  self.last={};self.count=Counter();self.rows={};self.series=deque(maxlen=500);self.start_wall=0;self.start_frame=0;self.q=queue.Queue();self.live=False;self.stop_event=threading.Event()
  self.cards={}
  self.set_styles()
  self.build_header()
  self.build_toolbar()
  self.build_footer()
  self.build_body()
  self.set_state(self.status.get(),MUTED)
  self.root.after(40,self.tick);self.root.after(180,self.paint_chart)
  # bundled test log, if present
  base=getattr(sys,"_MEIPASS",os.path.dirname(os.path.abspath(__file__)))
  bundled=os.path.join(base,"CAPTURE_GAZ_RSV4.txt")
  if os.path.exists(bundled):self.load(bundled)

 # ---------- style ----------
 def set_styles(self):
  s=ttk.Style();s.theme_use("clam")
  s.configure("Treeview",background=CARD2,foreground=TEXT,fieldbackground=CARD2,rowheight=26,borderwidth=0,relief="flat",bordercolor=CARD2,lightcolor=CARD2,darkcolor=CARD2,font=(FONT,10))
  s.configure("Treeview.Heading",background=BORDER,foreground=SUB,relief="flat",font=(FONT,9,"bold"),padding=6)
  s.map("Treeview",background=[("selected",HOVER)],foreground=[("selected",TEXT)])
  s.map("Treeview.Heading",background=[("active",HOVER)])
  s.configure("Vertical.TScrollbar",background=CARD2,troughcolor=CARD,bordercolor=CARD,arrowcolor=SUB,lightcolor=CARD2,darkcolor=CARD2)
  s.configure("TCombobox",fieldbackground=CARD2,background=CARD2,foreground=TEXT,arrowcolor=SUB,bordercolor=BORDER,lightcolor=CARD2,darkcolor=CARD2,padding=4)
  s.map("TCombobox",fieldbackground=[("readonly",CARD2)],foreground=[("readonly",TEXT)],selectbackground=[("readonly",CARD2)],selectforeground=[("readonly",TEXT)])
  s.configure("Rsv.Horizontal.TProgressbar",troughcolor=CARD2,background=CYAN,bordercolor=CARD2,lightcolor=CYAN,darkcolor=CYAN,thickness=6)

 def card(self,parent):
  return tk.Frame(parent,bg=CARD,highlightbackground=BORDER,highlightthickness=1,bd=0)

 def button(self,parent,text,command,color=TEXT):
  b=tk.Button(parent,text=text,command=command,bg=CARD2,fg=color,activebackground=HOVER,activeforeground=TEXT,
              relief="flat",bd=0,highlightthickness=0,padx=14,pady=8,font=(FONT,10,"bold"),cursor="hand2")
  b.bind("<Enter>",lambda e:b.config(bg=HOVER));b.bind("<Leave>",lambda e:b.config(bg=CARD2))
  return b

 def separator(self,parent):
  tk.Frame(parent,bg=BORDER,width=1).pack(side="left",fill="y",padx=10,pady=4)

 # ---------- layout ----------
 def build_header(self):
  head=tk.Frame(self.root,bg=BG);head.pack(fill="x",padx=28,pady=(18,10))
  brand=tk.Frame(head,bg=BG);brand.pack(side="left")
  tk.Label(brand,text="RSV4",fg=RED,bg=BG,font=(FONT,24,"bold")).pack(side="left")
  tk.Label(brand,text=" CAN Studio",fg=TEXT,bg=BG,font=(FONT,22,"bold")).pack(side="left")
  tk.Label(brand,text="   Telemetry Lab",fg=MUTED,bg=BG,font=(FONT,11)).pack(side="left",pady=(8,0))
  right=tk.Frame(head,bg=BG);right.pack(side="right")
  self.dot=tk.Label(right,text="●",fg=MUTED,bg=BG,font=(FONT,14));self.dot.pack(side="left")
  tk.Label(right,textvariable=self.status,fg=SUB,bg=BG,font=(FONT,10,"bold")).pack(side="left",padx=(6,0))

 def build_toolbar(self):
  bar=self.card(self.root);bar.pack(fill="x",padx=24,pady=(0,12))
  inner=tk.Frame(bar,bg=CARD);inner.pack(fill="x",padx=10,pady=8)
  self.button(inner,"Importer .txt",self.open_file).pack(side="left",padx=3)
  self.separator(inner)
  self.button(inner,"▶  Lecture",self.play,GREEN).pack(side="left",padx=3)
  self.button(inner,"❚❚  Pause",self.pause,YELLOW).pack(side="left",padx=3)
  self.button(inner,"↺  Début",self.reset).pack(side="left",padx=3)
  tk.Label(inner,text="Vitesse",bg=CARD,fg=SUB,font=(FONT,10)).pack(side="left",padx=(12,6))
  ttk.Combobox(inner,textvariable=self.speed,values=[0.25,0.5,1,2,4,8],state="readonly",width=5).pack(side="left")
  self.separator(inner)
  self.button(inner,"USB-CAN direct",self.connect,CYAN).pack(side="left",padx=3)
  self.button(inner,"Déconnecter",self.disconnect).pack(side="left",padx=3)
  self.button(inner,"⚙  Paramètres",self.settings).pack(side="right",padx=3)

 def build_body(self):
  body=tk.Frame(self.root,bg=BG);body.pack(fill="both",expand=True,padx=24)

  # barre de progression de la capture
  prog=tk.Frame(body,bg=BG);prog.pack(fill="x",pady=(0,10))
  tk.Label(prog,textvariable=self.file_name,fg=SUB,bg=BG,font=(FONT,10)).pack(side="left")
  tk.Label(prog,textvariable=self.clock,fg=TEXT,bg=BG,font=(FONT,10,"bold")).pack(side="right")
  ttk.Progressbar(prog,variable=self.progress,maximum=100,style="Rsv.Horizontal.TProgressbar").pack(fill="x",padx=14,pady=(6,0))

  # jauges
  top=tk.Frame(body,bg=BG);top.pack(fill="x")
  def gauge_card(title,maximum,color,unit,badge,badge_color):
   wrap=self.card(top);wrap.pack(side="left",fill="both",expand=True,padx=5)
   g=Gauge(wrap,title,maximum,color,unit,badge,badge_color)
   g.pack(fill="both",expand=True,padx=6,pady=6)
   return g
  self.rpm=gauge_card("RÉGIME MOTEUR",15000,RED,"tr/min","EXPÉRIMENTAL · 0x100",YELLOW)
  self.speedg=gauge_card("VITESSE MOTO",320,CYAN,"km/h","EXPÉRIMENTAL · 0x100",YELLOW)
  self.throttle=gauge_card("POIGNÉE DE GAZ",100,GREEN,"%","VALIDÉ · 0x601",GREEN)

  # cartes de mesures
  cards=tk.Frame(body,bg=BG);cards.pack(fill="x",pady=8)
  items=[("gear","RAPPORT","",VIOLET),("temp","TEMP. MOTEUR","°C",ORANGE),("oil","TEMP. HUILE","°C",YELLOW),
         ("front","ROUE AVANT","km/h",CYAN),("rear","ROUE ARRIÈRE","km/h",CYAN),("battery","BATTERIE","V",LIME),
         ("tps1","PAPILLON TPS1","%",PINK),("tps2","PAPILLON TPS2","%",PINK)]
  for i,(key,label,unit,accent) in enumerate(items):
   c=self.metric(cards,key,label,unit,accent);c.grid(row=i//4,column=i%4,padx=5,pady=5,sticky="nsew")
  for i in range(4):cards.columnconfigure(i,weight=1,uniform="m")

  # graphique + moniteur
  bottom=tk.Frame(body,bg=BG);bottom.pack(fill="both",expand=True,pady=(4,8))

  left=self.card(bottom);left.pack(side="left",fill="both",expand=True,padx=(0,8))
  head=tk.Frame(left,bg=CARD);head.pack(fill="x",padx=16,pady=(12,0))
  tk.Label(head,text="Poignée de gaz",fg=TEXT,bg=CARD,font=(FONT,12,"bold")).pack(side="left")
  tk.Label(head,text="  CAN 0x601 · 30 dernières secondes",fg=MUTED,bg=CARD,font=(FONT,9)).pack(side="left",pady=(3,0))
  self.chart_value=tk.Label(head,text="—",fg=GREEN,bg=CARD,font=(FONT,14,"bold"));self.chart_value.pack(side="right")
  self.chart=tk.Canvas(left,bg=CARD,highlightthickness=0,height=180)
  self.chart.pack(fill="both",expand=True,padx=12,pady=10)

  right=self.card(bottom);right.pack(side="left",fill="both",expand=True,padx=(8,0))
  tk.Label(right,text="Moniteur CAN",fg=TEXT,bg=CARD,font=(FONT,12,"bold")).pack(anchor="w",padx=16,pady=(12,0))
  tk.Label(right,text="Trames brutes, dernière valeur par identifiant",fg=MUTED,bg=CARD,font=(FONT,9)).pack(anchor="w",padx=16,pady=(0,6))
  tw=tk.Frame(right,bg=CARD);tw.pack(fill="both",expand=True,padx=12,pady=(0,12))
  self.table=ttk.Treeview(tw,columns=("id","n","data"),show="headings",height=9)
  for col,label,width,anchor in [("id","ID",90,"w"),("n","NB",70,"e"),("data","DONNÉES HEX",250,"w")]:
   self.table.heading(col,text=label,anchor=anchor);self.table.column(col,width=width,anchor=anchor,stretch=(col=="data"))
  sb=ttk.Scrollbar(tw,orient="vertical",command=self.table.yview)
  self.table.configure(yscrollcommand=sb.set)
  self.table.pack(side="left",fill="both",expand=True);sb.pack(side="right",fill="y")

 def build_footer(self):
  foot=tk.Frame(self.root,bg="#211c0e",highlightbackground="#4a3d18",highlightthickness=1)
  foot.pack(side="bottom",fill="x",padx=24,pady=(0,14))
  tk.Label(foot,text="⚠  Seule la poignée de gaz est validée sur cette moto. TPS1 / TPS2 : identifiés dans la définition AiM (CAN 0x7F2), absents des captures actuelles. « — » signifie non disponible.",
           bg="#211c0e",fg=YELLOW,font=(FONT,9),wraplength=1200,justify="left").pack(anchor="w",padx=14,pady=8)

 def metric(self,parent,key,label,unit,accent):
  f=self.card(parent)
  tk.Frame(f,bg=accent,width=4).pack(side="left",fill="y")
  inner=tk.Frame(f,bg=CARD);inner.pack(side="left",fill="both",expand=True,padx=14,pady=10)
  tk.Label(inner,text=label,fg=SUB,bg=CARD,font=(FONT,9,"bold")).pack(anchor="w")
  row=tk.Frame(inner,bg=CARD);row.pack(anchor="w",pady=(2,0))
  value=tk.Label(row,text="—",fg=TEXT,bg=CARD,font=(FONT,22,"bold"));value.pack(side="left")
  unit_lbl=tk.Label(row,text=unit,fg=MUTED,bg=CARD,font=(FONT,11));unit_lbl.pack(side="left",padx=(6,0),pady=(8,0))
  self.cards[key]=(value,unit_lbl)
  return f

 # ---------- state ----------
 def set_state(self,text,color):
  self.status.set(text);self.dot.config(fg=color)

 def set_card(self,key,val):
  widget,unit_lbl=self.cards[key];widget.config(text=str(val))

 def open_file(self):
  p=filedialog.askopenfilename(title="Choisir une capture USB-CAN",filetypes=[("Fichiers texte","*.txt *.log"),("Tous fichiers","*.*")])
  if p:self.load(p)

 def load(self,path):
  try:frames=load_capture(path)
  except Exception as exc:messagebox.showerror("Erreur de lecture",str(exc));return
  self.pause();self.frames=frames;self.idx=0;self.last.clear();self.count.clear();self.series.clear()
  for row in self.table.get_children():self.table.delete(row)
  self.rows.clear()
  self.file_name.set(os.path.basename(path))
  if not frames:
   self.set_state("0 trame · format non reconnu",RED)
   messagebox.showwarning("0 trame","Le fichier ne contient pas de trames USB-CAN reconnaissables. Vérifiez qu'il s'agit d'un export TXT du logiciel USBCAN.")
  else:
   n_ids=len(set(c for _,c,_ in frames))
   self.set_state(f"{len(frames):,} trames · {n_ids} identifiants".replace(","," "),SUB)

 def play(self):
  if not self.frames:messagebox.showinfo("Capture","Importez d'abord une capture TXT.");return
  self.playing=True;self.start_wall=time.monotonic();self.start_frame=self.frames[self.idx][0] if self.idx<len(self.frames) else 0
  self.set_state("Lecture en cours",GREEN)

 def pause(self):
  was=self.playing;self.playing=False
  if was and self.frames and self.idx<len(self.frames):self.set_state("En pause",YELLOW)

 def reset(self):
  self.pause();self.idx=0;self.series.clear()
  for key in self.cards:self.set_card(key,"—")
  self.rpm.set(None);self.speedg.set(None);self.throttle.set(None)
  self.chart_value.config(text="—")
  if self.frames:self.set_state("Début de capture",SUB)

 # ---------- décodage (inchangé) ----------
 def ingest(self,t,cid,data):
  self.last[cid]=data;self.count[cid]+=1
  if cid==0x7F2 and len(data)>=5:
   # Définition AiM RSV4 EU5: TPS1 sBit=8, TPS2 sBit=24, 16 bits, facteur .119.
   # Hypothèse d'ordre des octets little-endian à valider.
   self.set_card("tps1",f"{int.from_bytes(data[1:3], 'little') * .119:.1f}*")
   self.set_card("tps2",f"{int.from_bytes(data[3:5], 'little') * .119:.1f}*")
  if cid==0x601 and data:
   self.throttle.set(data[0]);self.series.append((t/1000,data[0]))
  if self.experimental.get():
   if cid==0x100 and len(data)>=5:
    self.rpm.set((data[3]<<8)|data[4])
    if len(data)>=2:
     self.set_card("gear",data[0]&15)
     if len(data)>=3:self.speedg.set(round((((data[1]<<8)|data[2])&4095)*.25,1))
   if cid==0x200 and len(data)>=2:
    self.set_card("temp",f"{data[0]-40}");self.set_card("oil",f"{data[1]-40}")
    if len(data)>=6:self.set_card("battery",f"{data[5] / 10:.1f}*")
   if cid==0x260 and len(data)>=5:
    self.set_card("front",f"{round(int.from_bytes(data[1:3],'big')*.01,1)}")
    self.set_card("rear",f"{round(int.from_bytes(data[3:5],'big')*.01,1)}")
  if cid not in self.rows:self.rows[cid]=self.table.insert("","end",values=(f"0x{cid:03X}",0,""))
  self.table.item(self.rows[cid],values=(f"0x{cid:03X}",self.count[cid],data.hex(" ").upper()))

 # ---------- graphique ----------
 def paint_chart(self):
  c=self.chart;c.delete("all");w=c.winfo_width();h=c.winfo_height()
  if w>80 and h>80:
   left,right,top,bottom=42,14,10,26
   pw=w-left-right;ph=h-top-bottom
   for i in range(5):
    y=top+ph*i/4
    c.create_line(left,y,w-right,y,fill=BORDER)
    c.create_text(left-8,y,text=str(100-25*i),anchor="e",fill=MUTED,font=(FONT,9))
   for i,label in enumerate(["-30 s","-15 s","0"]):
    anchor=["w","center","e"][i]
    c.create_text(left+pw*i/2,h-10,text=label,anchor=anchor,fill=MUTED,font=(FONT,9))
   pts=list(self.series)
   if len(pts)>1:
    t_end=pts[-1][0];start=max(0,t_end-30);span=max(1,t_end-start)
    coords=[]
    for t,v in pts:
     if t<start:continue
     x=left+pw*(t-start)/span;y=top+ph*(1-v/100);coords.extend([x,y])
    if len(coords)>=4:
     bottom_y=top+ph
     c.create_polygon(coords[0],bottom_y,*coords,coords[-2],bottom_y,fill="#0f2c28",outline="")
     c.create_line(*coords,fill=GREEN,width=2.5)
     x,y=coords[-2],coords[-1]
     c.create_oval(x-5,y-5,x+5,y+5,fill=GREEN,outline=CARD,width=2)
    self.chart_value.config(text=f"{pts[-1][1]:.0f} %")
  self.root.after(180,self.paint_chart)

 # ---------- boucle ----------
 def update_progress(self):
  if not self.frames:
   self.progress.set(0);self.clock.set("00:00 / 00:00");return
  total=self.frames[-1][0]
  cur=self.frames[self.idx-1][0] if self.idx>0 else 0
  self.progress.set(100*self.idx/len(self.frames))
  self.clock.set(f"{fmt_time(cur)} / {fmt_time(total)}")

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
  self.update_progress()
  self.root.after(40,self.tick)

 def settings(self):
  win=tk.Toplevel(self.root);win.title("Paramètres");win.configure(bg=CARD);win.geometry("460x300");win.resizable(False,False)
  tk.Label(win,text="Paramètres",fg=TEXT,bg=CARD,font=(FONT,14,"bold")).pack(anchor="w",padx=24,pady=(18,6))
  for label,var in [("Port série",self.port),("Vitesse série (bauds)",self.baud)]:
   tk.Label(win,text=label,bg=CARD,fg=SUB,font=(FONT,9,"bold")).pack(anchor="w",padx=24,pady=(10,3))
   tk.Entry(win,textvariable=var,width=28,bg=CARD2,fg=TEXT,insertbackground=TEXT,relief="flat",highlightbackground=BORDER,highlightthickness=1).pack(anchor="w",padx=24,ipady=4)
  tk.Checkbutton(win,text="Afficher les décodages expérimentaux (non validés)",variable=self.experimental,
                 bg=CARD,fg=TEXT,selectcolor=CARD2,activebackground=CARD,activeforeground=TEXT).pack(anchor="w",padx=20,pady=(14,6))
  tk.Label(win,text="Connexion USB-CAN : réception uniquement.\nMode Silent à configurer avec le logiciel officiel.",
           bg=CARD,fg=YELLOW,justify="left",font=(FONT,9)).pack(anchor="w",padx=24)

 def disconnect(self):
  was_live=self.live
  self.live=False;self.stop_event.set()
  if was_live:self.set_state("Déconnecté",MUTED)

 def connect(self):
  if serial is None:messagebox.showerror("Dépendance","pyserial manquant");return
  if not messagebox.askokcancel("Sécurité CAN","Configurer l'adaptateur en mode Silent et CAN 250 kbit/s avec USBCAN, puis fermer USBCAN.\n\nCette application n'envoie aucune commande, et ne peut pas vérifier que le mode Silent reste actif.\n\nContinuer ?"):return
  self.disconnect();self.stop_event=threading.Event();stop=self.stop_event;self.live=True
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
