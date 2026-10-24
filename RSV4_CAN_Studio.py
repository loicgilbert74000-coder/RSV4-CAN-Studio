import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import re, time, math, queue, threading, os, sys
from collections import Counter, deque
try: import serial
except ImportError: serial=None

# Palette : fond sombre en couches, rouge RSV4 comme couleur de marque
BG="#0b1018"; SIDE="#0f1622"; CARD="#141c2a"; CARD2="#1d2739"; BORDER="#263349"; HOVER="#26364f"
TEXT="#eef3fb"; SUB="#93a4bd"; MUTED="#5f7089"
RED="#e8202a"; GREEN="#2ee59d"; CYAN="#3ab8ff"; YELLOW="#ffb938"; ORANGE="#ff8a3d"
VIOLET="#a78bfa"; PINK="#f472b6"; LIME="#a3e635"
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
 """Jauge circulaire 270° avec graduations et repères textuels."""
 def __init__(self,parent,maximum,color,unit,labels,height=250):
  super().__init__(parent,height=height,bg=CARD,highlightthickness=0)
  self.maximum=maximum;self.color=color;self.unit=unit;self.labels=labels;self.value=None
  self.bind("<Configure>",lambda e:self.render())
 def set(self,value):self.value=value;self.render()
 def render(self):
  self.delete("all");w=max(220,self.winfo_width());h=max(200,self.winfo_height())
  cx=w/2;cy=h*.55;r=min(w*.40,h*.44);thick=14;start=225;sweep=-270
  self.create_arc(cx-r,cy-r,cx+r,cy+r,start=start,extent=sweep,style="arc",outline=CARD2,width=thick)
  if self.value is not None:
   frac=max(0,min(1,float(self.value)/self.maximum))
   if frac>0:self.create_arc(cx-r,cy-r,cx+r,cy+r,start=start,extent=sweep*frac,style="arc",outline=self.color,width=thick)
  ri=r-thick/2-4
  for i in range(41):
   ang=math.radians(start+sweep*i/40);major=(i%5==0)
   r_out=ri-(12 if major else 6)
   self.create_line(cx+ri*math.cos(ang),cy-ri*math.sin(ang),cx+r_out*math.cos(ang),cy-r_out*math.sin(ang),fill=MUTED if major else BORDER,width=2 if major else 1)
  for frac,text in self.labels:
   ang=math.radians(start+sweep*frac);lr=ri-26
   self.create_text(cx+lr*math.cos(ang),cy-lr*math.sin(ang),text=text,fill=SUB,font=(FONT,9,"bold"))
  val="—" if self.value is None else f"{self.value:,.0f}".replace(","," ")
  self.create_text(cx,cy-4,text=val,fill=TEXT,font=(FONT,34,"bold"))
  self.create_text(cx,cy+30,text=self.unit,fill=SUB,font=(FONT,11))

class Bar(tk.Canvas):
 """Barre de progression fine pour une mesure bornée."""
 def __init__(self,parent,color,lo,hi):
  super().__init__(parent,height=10,bg=CARD,highlightthickness=0)
  self.color=color;self.lo=lo;self.hi=hi;self.frac=None
  self.bind("<Configure>",lambda e:self.render())
 def set(self,value):
  self.frac=None if value is None else max(0,min(1,(float(value)-self.lo)/(self.hi-self.lo)))
  self.render()
 def render(self):
  self.delete("all");w=max(20,self.winfo_width())
  self.create_rectangle(0,3,w,8,fill=CARD2,outline="")
  if self.frac is not None:self.create_rectangle(0,3,w*self.frac,8,fill=self.color,outline="")

SERIES=[("Régime","rpm",RED,15000),("Vitesse","speed",CYAN,320),("Gaz","thr",GREEN,100),("Temp. moteur","temp",ORANGE,150)]

class App:
 def __init__(self):
  self.root=tk.Tk();self.root.title("RSV4 CAN Studio · Diagnostic & Télémétrie")
  self.root.geometry("1440x900");self.root.minsize(1200,780);self.root.configure(bg=BG)
  self.frames=[];self.idx=0;self.playing=False;self.speed=tk.DoubleVar(value=1.0)
  self.status=tk.StringVar(value="Prêt · ouvrez une capture")
  self.file_name=tk.StringVar(value="Aucun fichier chargé")
  self.clock=tk.StringVar(value="00:00 / 00:00");self.progress=tk.DoubleVar(value=0)
  self.port=tk.StringVar(value="COM7");self.baud=tk.StringVar(value="2000000");self.experimental=tk.BooleanVar(value=True)
  self.count=Counter();self.first_t={};self.last_t={};self.rows={};self.decode_txt={}
  self.series=deque(maxlen=6000);self.window=60;self.ingested=0;self.t_last=0
  self.state_vals={"rpm":None,"speed":None,"thr":None,"temp":None}
  self.start_wall=0;self.start_frame=0;self.q=queue.Queue();self.live=False;self.stop_event=threading.Event()
  self.cards={};self.pages={};self.nav={}
  self.set_styles()
  self.build_footer()
  self.build_sidebar()
  self.build_main()
  self.show_page("dash")
  self.set_state("Prêt · ouvrez une capture",MUTED)
  self.root.after(40,self.tick);self.root.after(180,self.paint_chart)
  base=getattr(sys,"_MEIPASS",os.path.dirname(os.path.abspath(__file__)))
  bundled=os.path.join(base,"CAPTURE_GAZ_RSV4.txt")
  if os.path.exists(bundled):self.load(bundled)

 # ---------- style & widgets ----------
 def set_styles(self):
  s=ttk.Style();s.theme_use("clam")
  s.configure("Treeview",background=CARD2,foreground=TEXT,fieldbackground=CARD2,rowheight=26,borderwidth=0,relief="flat",bordercolor=CARD2,lightcolor=CARD2,darkcolor=CARD2,font=(FONT,10))
  s.configure("Treeview.Heading",background=BORDER,foreground=SUB,relief="flat",font=(FONT,9,"bold"),padding=6)
  s.map("Treeview",background=[("selected",HOVER)],foreground=[("selected",TEXT)])
  s.map("Treeview.Heading",background=[("active",HOVER)])
  s.configure("Vertical.TScrollbar",background=CARD2,troughcolor=CARD,bordercolor=CARD,arrowcolor=SUB,lightcolor=CARD2,darkcolor=CARD2)
  s.configure("TCombobox",fieldbackground=CARD2,background=CARD2,foreground=TEXT,arrowcolor=SUB,bordercolor=BORDER,lightcolor=CARD2,darkcolor=CARD2,padding=4)
  s.map("TCombobox",fieldbackground=[("readonly",CARD2)],foreground=[("readonly",TEXT)],selectbackground=[("readonly",CARD2)],selectforeground=[("readonly",TEXT)])
  s.configure("Rsv.Horizontal.TProgressbar",troughcolor=CARD2,background=RED,bordercolor=CARD2,lightcolor=RED,darkcolor=RED,thickness=5)

 def card(self,parent):
  return tk.Frame(parent,bg=CARD,highlightbackground=BORDER,highlightthickness=1,bd=0)

 def button(self,parent,text,command,color=TEXT,bg=CARD2,anchor="center"):
  b=tk.Button(parent,text=text,command=command,bg=bg,fg=color,activebackground=HOVER,activeforeground=TEXT,
              relief="flat",bd=0,highlightthickness=0,padx=12,pady=8,font=(FONT,10,"bold"),cursor="hand2",anchor=anchor)
  b.bind("<Enter>",lambda e:b.config(bg=HOVER));b.bind("<Leave>",lambda e:b.config(bg=bg))
  return b

 def section(self,parent,text):
  tk.Label(parent,text=text,fg=MUTED,bg=SIDE,font=(FONT,8,"bold")).pack(anchor="w",padx=20,pady=(16,4))

 # ---------- layout ----------
 def build_footer(self):
  foot=tk.Frame(self.root,bg=SIDE,highlightbackground=BORDER,highlightthickness=1);foot.pack(side="bottom",fill="x")
  self.dot=tk.Label(foot,text="●",fg=MUTED,bg=SIDE,font=(FONT,12));self.dot.pack(side="left",padx=(16,6),pady=6)
  tk.Label(foot,textvariable=self.status,fg=SUB,bg=SIDE,font=(FONT,9,"bold")).pack(side="left")
  tk.Label(foot,text="   Seule la poignée de gaz est validée · TPS1/TPS2 non identifiés dans vos captures",fg=YELLOW,bg=SIDE,font=(FONT,9)).pack(side="left")
  self.dur_lbl=self.stat(foot,"Position","00:00");self.rate_lbl=self.stat(foot,"Trames/s","—")
  self.frames_lbl=self.stat(foot,"Trames","0");self.ids_lbl=self.stat(foot,"Identifiants","0")

 def stat(self,parent,label,value):
  box=tk.Frame(parent,bg=SIDE);box.pack(side="right",padx=14,pady=6)
  tk.Label(box,text=label.upper(),fg=MUTED,bg=SIDE,font=(FONT,7,"bold")).pack(anchor="e")
  lbl=tk.Label(box,text=value,fg=TEXT,bg=SIDE,font=(FONT,10,"bold"));lbl.pack(anchor="e")
  return lbl

 def build_sidebar(self):
  side=tk.Frame(self.root,bg=SIDE,width=240,highlightbackground=BORDER,highlightthickness=1);side.pack(side="left",fill="y")
  side.pack_propagate(False)
  brand=tk.Frame(side,bg=SIDE);brand.pack(fill="x",padx=20,pady=(22,6))
  tk.Label(brand,text="RSV4",fg=RED,bg=SIDE,font=(FONT,26,"bold")).pack(anchor="w")
  tk.Label(brand,text="CAN STUDIO",fg=TEXT,bg=SIDE,font=(FONT,11,"bold")).pack(anchor="w")
  tk.Label(brand,text="Télémétrie · Diagnostic CAN",fg=MUTED,bg=SIDE,font=(FONT,8)).pack(anchor="w",pady=(2,0))
  self.section(side,"NAVIGATION")
  for key,label in [("dash","Tableau de bord"),("graph","Graphiques"),("frames","Trames CAN")]:
   b=self.button(side,"   "+label,lambda k=key:self.show_page(k),TEXT,SIDE,"w")
   b.pack(fill="x",padx=12,pady=2);self.nav[key]=b
  self.button(side,"   Paramètres",self.settings,TEXT,SIDE,"w").pack(fill="x",padx=12,pady=2)
  self.section(side,"SOURCE")
  self.button(side,"   Importer .txt",self.open_file,TEXT,SIDE,"w").pack(fill="x",padx=12,pady=2)
  self.button(side,"   USB-CAN direct",self.connect,CYAN,SIDE,"w").pack(fill="x",padx=12,pady=2)
  self.button(side,"   Déconnecter",self.disconnect,SUB,SIDE,"w").pack(fill="x",padx=12,pady=2)
  self.section(side,"LECTURE")
  self.button(side,"   Lecture",self.play,GREEN,SIDE,"w").pack(fill="x",padx=12,pady=2)
  self.button(side,"   Pause",self.pause,YELLOW,SIDE,"w").pack(fill="x",padx=12,pady=2)
  self.button(side,"   Début",self.reset,SUB,SIDE,"w").pack(fill="x",padx=12,pady=2)
  sp=tk.Frame(side,bg=SIDE);sp.pack(fill="x",padx=20,pady=(10,0))
  tk.Label(sp,text="Vitesse",fg=SUB,bg=SIDE,font=(FONT,9)).pack(side="left")
  ttk.Combobox(sp,textvariable=self.speed,values=[0.25,0.5,1,2,4,8],state="readonly",width=6).pack(side="right")
  pr=tk.Frame(side,bg=SIDE);pr.pack(fill="x",padx=20,pady=(16,0))
  tk.Label(pr,textvariable=self.file_name,fg=SUB,bg=SIDE,font=(FONT,8),anchor="w",wraplength=190,justify="left").pack(fill="x")
  ttk.Progressbar(pr,variable=self.progress,maximum=100,style="Rsv.Horizontal.TProgressbar").pack(fill="x",pady=(6,2))
  tk.Label(pr,textvariable=self.clock,fg=TEXT,bg=SIDE,font=(FONT,9,"bold")).pack(anchor="e")

 def build_main(self):
  main=tk.Frame(self.root,bg=BG);main.pack(side="left",fill="both",expand=True)
  head=tk.Frame(main,bg=BG);head.pack(fill="x",padx=26,pady=(20,10))
  self.page_title=tk.Label(head,text="",fg=TEXT,bg=BG,font=(FONT,20,"bold"));self.page_title.pack(anchor="w")
  self.page_sub=tk.Label(head,text="",fg=MUTED,bg=BG,font=(FONT,10));self.page_sub.pack(anchor="w")
  self.area=tk.Frame(main,bg=BG);self.area.pack(fill="both",expand=True,padx=26,pady=(0,14))
  self.build_dashboard(self.area)
  self.build_graph(self.area)
  self.build_frames(self.area)

 def show_page(self,key):
  titles={"dash":("Tableau de bord","Mesures CAN · jauges et valeurs"),
          "graph":("Graphiques","Évolution des mesures sur les 60 dernières secondes"),
          "frames":("Trames CAN","Trames brutes par identifiant, fréquence et décodage")}
  for p in self.pages.values():p.pack_forget()
  self.pages[key].pack(fill="both",expand=True)
  self.page_title.config(text=titles[key][0]);self.page_sub.config(text=titles[key][1])
  for k,b in self.nav.items():b.config(fg=RED if k==key else TEXT,bg=HOVER if k==key else SIDE)

 # ---------- tableau de bord ----------
 def metric(self,parent,key,label,unit,accent,lo,hi,validated):
  f=self.card(parent)
  tk.Frame(f,bg=accent,width=4).pack(side="left",fill="y")
  inner=tk.Frame(f,bg=CARD);inner.pack(side="left",fill="both",expand=True,padx=14,pady=10)
  top=tk.Frame(inner,bg=CARD);top.pack(fill="x")
  tk.Label(top,text=label,fg=SUB,bg=CARD,font=(FONT,9,"bold")).pack(side="left")
  badge,bcolor=("VALIDÉ",GREEN) if validated else ("À VALIDER",YELLOW)
  tk.Label(top,text=badge,fg=bcolor,bg=CARD,font=(FONT,8,"bold")).pack(side="right")
  row=tk.Frame(inner,bg=CARD);row.pack(anchor="w",pady=(4,6))
  value=tk.Label(row,text="—",fg=TEXT,bg=CARD,font=(FONT,22,"bold"));value.pack(side="left")
  unit_lbl=tk.Label(row,text=unit,fg=MUTED,bg=CARD,font=(FONT,11));unit_lbl.pack(side="left",padx=(6,0),pady=(8,0))
  bar=Bar(inner,accent,lo,hi);bar.pack(fill="x")
  rng=tk.Frame(inner,bg=CARD);rng.pack(fill="x",pady=(3,0))
  tk.Label(rng,text=str(lo),fg=MUTED,bg=CARD,font=(FONT,8)).pack(side="left")
  tk.Label(rng,text=str(hi),fg=MUTED,bg=CARD,font=(FONT,8)).pack(side="right")
  self.cards[key]=(value,bar)
  return f

 def show(self,key,num,text=None,fmt="{:.0f}"):
  value,bar=self.cards[key]
  if num is None:value.config(text="—")
  else:value.config(text=text if text is not None else fmt.format(num))
  bar.set(num)

 def build_dashboard(self,parent):
  page=tk.Frame(parent,bg=BG);self.pages["dash"]=page
  for c in range(4):page.columnconfigure(c,weight=1,uniform="col")
  for r,wt in [(0,3),(1,2),(2,2),(3,2)]:page.rowconfigure(r,weight=wt)

  g1=self.card(page);g1.grid(row=0,column=0,columnspan=2,sticky="nsew",padx=5,pady=5)
  tk.Label(g1,text="Régime moteur",fg=SUB,bg=CARD,font=(FONT,10,"bold")).pack(anchor="w",padx=16,pady=(12,0))
  self.rpm=Gauge(g1,15000,RED,"tr/min",[(0,"0"),(0.2,"3"),(0.4,"6"),(0.6,"9"),(0.8,"12"),(1,"15")])
  self.rpm.pack(fill="both",expand=True,padx=8,pady=6)

  g2=self.card(page);g2.grid(row=0,column=2,columnspan=2,sticky="nsew",padx=5,pady=5)
  tk.Label(g2,text="Vitesse moto",fg=SUB,bg=CARD,font=(FONT,10,"bold")).pack(anchor="w",padx=16,pady=(12,0))
  self.speedg=Gauge(g2,320,CYAN,"km/h",[(0,"0"),(0.25,"80"),(0.5,"160"),(0.75,"240"),(1,"320")])
  self.speedg.pack(fill="both",expand=True,padx=8,pady=6)

  # (clé, libellé, unité, couleur, min, max, validé)
  specs=[("gear","Rapport engagé","",VIOLET,0,6,False),
         ("throttle","Position gaz","%",GREEN,0,100,True),
         ("temp","Temp. moteur","°C",ORANGE,50,150,False),
         ("oil","Temp. huile","°C",YELLOW,50,150,False),
         ("battery","Tension batterie","V",LIME,10,16,False),
         ("front","Roue avant","km/h",CYAN,0,300,False),
         ("rear","Roue arrière","km/h",CYAN,0,300,False),
         ("tps1","Papillon TPS1","%",PINK,0,100,False),
         ("tps2","Papillon TPS2","%",PINK,0,100,False)]
  for i,(key,label,unit,accent,lo,hi,val) in enumerate(specs):
   r=1+i//4;c=i%4
   self.metric(page,key,label,unit,accent,lo,hi,val).grid(row=r,column=c,sticky="nsew",padx=5,pady=5)

  st=self.card(page);st.grid(row=3,column=1,columnspan=3,sticky="nsew",padx=5,pady=5)
  tk.Label(st,text="Statut du système",fg=SUB,bg=CARD,font=(FONT,10,"bold")).pack(anchor="w",padx=16,pady=(12,6))
  self.status_rows={}
  for key,label in [("src","Source"),("exp","Décodages expérimentaux"),("note","Validation")]:
   row=tk.Frame(st,bg=CARD);row.pack(fill="x",padx=16,pady=3)
   tk.Label(row,text=label,fg=MUTED,bg=CARD,font=(FONT,9)).pack(side="left")
   v=tk.Label(row,text="—",fg=TEXT,bg=CARD,font=(FONT,9,"bold"));v.pack(side="right")
   self.status_rows[key]=v
  self.status_rows["src"].config(text="Aucune")
  self.status_rows["exp"].config(text="Activés" if self.experimental.get() else "Désactivés")
  self.status_rows["note"].config(text="Régime, vitesse, tension : à valider",fg=YELLOW)

 # ---------- graphiques ----------
 def build_graph(self,parent):
  page=tk.Frame(parent,bg=BG);self.pages["graph"]=page
  card=self.card(page);card.pack(fill="both",expand=True,padx=5,pady=5)
  self.chart=tk.Canvas(card,bg=CARD,highlightthickness=0)
  self.chart.pack(fill="both",expand=True,padx=14,pady=14)

 def paint_chart(self):
  c=self.chart;c.delete("all");w=c.winfo_width();h=c.winfo_height()
  if w>200 and h>120:
   left,right,top,bottom=52,20,46,30
   pw=w-left-right;ph=h-top-bottom
   for i,(label,_,color,_) in enumerate(SERIES):
    x=left+i*150;c.create_rectangle(x,14,x+12,26,fill=color,outline="");c.create_text(x+18,20,text=label,anchor="w",fill=SUB,font=(FONT,9,"bold"))
   for i in range(5):
    y=top+ph*i/4;c.create_line(left,y,w-right,y,fill=BORDER)
    c.create_text(left-8,y,text=f"{100-25*i} %",anchor="e",fill=MUTED,font=(FONT,9))
   for i,label in enumerate([f"-{self.window} s",f"-{self.window//2} s","0"]):
    c.create_text(left+pw*i/2,h-12,text=label,anchor=["w","center","e"][i],fill=MUTED,font=(FONT,9))
   pts=list(self.series)
   if len(pts)>1:
    t_end=pts[-1]["t"];start=max(0,t_end-self.window);span=max(1,t_end-start)
    for label,key,color,maximum in SERIES:
     coords=[]
     for p in pts:
      if p["t"]<start or p.get(key) is None:continue
      v=max(0,min(1,p[key]/maximum))
      coords.extend([left+pw*(p["t"]-start)/span, top+ph*(1-v)])
     if len(coords)>=4:c.create_line(*coords,fill=color,width=2)
  self.root.after(180,self.paint_chart)

 # ---------- trames ----------
 def build_frames(self,parent):
  page=tk.Frame(parent,bg=BG);self.pages["frames"]=page
  card=self.card(page);card.pack(fill="both",expand=True,padx=5,pady=5)
  tw=tk.Frame(card,bg=CARD);tw.pack(fill="both",expand=True,padx=12,pady=12)
  self.table=ttk.Treeview(tw,columns=("id","n","freq","data","decode"),show="headings")
  for col,label,width,anchor in [("id","ID",80,"w"),("n","NB",80,"e"),("freq","FRÉQ. (Hz)",100,"e"),("data","DONNÉES HEX",230,"w"),("decode","DÉCODAGE",520,"w")]:
   self.table.heading(col,text=label,anchor=anchor);self.table.column(col,width=width,anchor=anchor,stretch=(col=="decode"))
  sb=ttk.Scrollbar(tw,orient="vertical",command=self.table.yview);self.table.configure(yscrollcommand=sb.set)
  self.table.pack(side="left",fill="both",expand=True);sb.pack(side="right",fill="y")

 # ---------- état ----------
 def set_state(self,text,color):
  self.status.set(text);self.dot.config(fg=color)

 def open_file(self):
  p=filedialog.askopenfilename(title="Choisir une capture USB-CAN",filetypes=[("Fichiers texte","*.txt *.log"),("Tous fichiers","*.*")])
  if p:self.load(p)

 def clear_data(self):
  self.count.clear();self.first_t.clear();self.last_t.clear();self.rows.clear();self.decode_txt.clear()
  self.series.clear();self.ingested=0;self.t_last=0
  self.state_vals={"rpm":None,"speed":None,"thr":None,"temp":None}
  for row in self.table.get_children():self.table.delete(row)
  for key in self.cards:self.show(key,None)
  self.rpm.set(None);self.speedg.set(None)

 def load(self,path):
  try:frames=load_capture(path)
  except Exception as exc:messagebox.showerror("Erreur de lecture",str(exc));return
  self.pause();self.frames=frames;self.idx=0;self.clear_data()
  self.file_name.set(os.path.basename(path))
  self.status_rows["src"].config(text=os.path.basename(path))
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
  self.count[cid]+=1;self.ingested+=1;self.t_last=t
  self.first_t.setdefault(cid,t);self.last_t[cid]=t
  sv=self.state_vals
  if cid==0x7F2 and len(data)>=5:
   # Définition AiM RSV4 EU5: TPS1 sBit=8, TPS2 sBit=24, 16 bits, facteur .119.
   # Hypothèse d'ordre des octets little-endian à valider.
   a=int.from_bytes(data[1:3],'little')*.119;b=int.from_bytes(data[3:5],'little')*.119
   self.show("tps1",a,text=f"{a:.1f}*");self.show("tps2",b,text=f"{b:.1f}*")
   self.decode_txt[cid]=f"TPS1 {a:.1f} % | TPS2 {b:.1f} %  (hypothèse)"
  if cid==0x601 and data:
   sv["thr"]=data[0];self.show("throttle",data[0])
   self.decode_txt[cid]=f"Poignée gaz : {data[0]} %"
   self.series.append({"t":t/1000,"rpm":sv["rpm"],"speed":sv["speed"],"thr":sv["thr"],"temp":sv["temp"]})
  if self.experimental.get():
   if cid==0x100 and len(data)>=5:
    rpm=(data[3]<<8)|data[4];sv["rpm"]=rpm;self.rpm.set(rpm)
    parts=[f"Régime {rpm} tr/min*"]
    if len(data)>=2:
     gear=data[0]&15;self.show("gear",gear);parts.append(f"Rapport {gear}*")
     if len(data)>=3:
      spd=round((((data[1]<<8)|data[2])&4095)*.25,1);sv["speed"]=spd;self.speedg.set(spd);parts.append(f"Vitesse {spd} km/h*")
    self.decode_txt[cid]=" | ".join(parts)
   if cid==0x200 and len(data)>=2:
    tmp=data[0]-40;oil=data[1]-40;sv["temp"]=tmp
    self.show("temp",tmp);self.show("oil",oil)
    txt=f"Temp. moteur {tmp} °C | Temp. huile {oil} °C*"
    if len(data)>=6:
     v=data[5]/10;self.show("battery",v,text=f"{v:.1f}*");txt+=f" | Batterie {v:.1f} V*"
    self.decode_txt[cid]=txt
   if cid==0x260 and len(data)>=5:
    f=round(int.from_bytes(data[1:3],'big')*.01,1);r=round(int.from_bytes(data[3:5],'big')*.01,1)
    self.show("front",f,text=f"{f:.1f}");self.show("rear",r,text=f"{r:.1f}")
    self.decode_txt[cid]=f"Roue AV {f:.1f} km/h | Roue AR {r:.1f} km/h*"
  n=self.count[cid]
  freq="—"
  if n>1 and self.last_t[cid]>self.first_t[cid]:freq=f"{(n-1)*1000/(self.last_t[cid]-self.first_t[cid]):.0f}"
  vals=(f"0x{cid:03X}",n,freq,data.hex(" ").upper(),self.decode_txt.get(cid,"—"))
  if cid not in self.rows:self.rows[cid]=self.table.insert("","end",values=vals)
  else:self.table.item(self.rows[cid],values=vals)

 # ---------- boucle ----------
 def update_status(self):
  if self.frames:
   total=self.frames[-1][0];cur=self.frames[self.idx-1][0] if self.idx>0 else 0
   self.progress.set(100*self.idx/len(self.frames));self.clock.set(f"{fmt_time(cur)} / {fmt_time(total)}")
   self.dur_lbl.config(text=fmt_time(cur))
  if self.live or not self.frames:self.rate_lbl.config(text="—")
  else:self.rate_lbl.config(text=f"{self.ingested/max(1,self.t_last/1000):.0f}")
  self.frames_lbl.config(text=f"{self.ingested:,}".replace(","," "))
  self.ids_lbl.config(text=str(len(self.count)))

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

 def disconnect(self):
  was_live=self.live
  self.live=False;self.stop_event.set()
  if was_live:
   self.set_state("Déconnecté",MUTED);self.status_rows["src"].config(text="USB-CAN déconnecté")

 def connect(self):
  if serial is None:messagebox.showerror("Dépendance","pyserial manquant");return
  if not messagebox.askokcancel("Sécurité CAN","Configurer l'adaptateur en mode Silent et CAN 250 kbit/s avec USBCAN, puis fermer USBCAN.\n\nCette application n'envoie aucune commande, et ne peut pas vérifier que le mode Silent reste actif.\n\nContinuer ?"):return
  self.disconnect();self.stop_event=threading.Event();stop=self.stop_event;self.live=True
  self.clear_data()
  self.set_state(f"USB-CAN · écoute sur {self.port.get()}",GREEN)
  self.status_rows["src"].config(text=f"USB-CAN · {self.port.get()}")
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
