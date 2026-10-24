import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import re, time, math, queue, threading, os, sys
from collections import Counter, deque
try: import serial
except ImportError: serial=None

BG="#0a101b"; PANEL="#151e2d"; PANEL2="#1b283b"; TEXT="#eff4fb"; SUB="#9caec5"; RED="#ff4d59"; GREEN="#46e3a0"; CYAN="#3fc9ff"; YELLOW="#ffbf58"
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

class Gauge(tk.Canvas):
 def __init__(self,parent,title,maximum,color,unit,width=310,height=245):
  super().__init__(parent,width=width,height=height,bg=PANEL,highlightthickness=0)
  self.title=title;self.maximum=maximum;self.color=color;self.unit=unit;self.value=None
  self.bind("<Configure>",lambda e:self.render())
 def set(self,value):self.value=value;self.render()
 def render(self):
  self.delete("all");w=max(240,self.winfo_width());h=max(190,self.winfo_height())
  cx=w/2;cy=h*.60;r=min(w*.33,h*.43)
  self.create_text(20,22,text=self.title,anchor="w",fill=SUB,font=(FONT,11,"bold"))
  self.create_arc(cx-r,cy-r,cx+r,cy+r,start=210,extent=-240,style="arc",outline="#334157",width=14)
  if self.value is not None:
   frac=max(0,min(1,float(self.value)/self.maximum))
   self.create_arc(cx-r,cy-r,cx+r,cy+r,start=210,extent=-240*frac,style="arc",outline=self.color,width=14)
  for i in range(9):
   ang=math.radians(210-240*i/8);r1=r-19;r2=r-10
   self.create_line(cx+r1*math.cos(ang),cy-r1*math.sin(ang),cx+r2*math.cos(ang),cy-r2*math.sin(ang),fill="#64758b",width=2)
  val="—" if self.value is None else f"{self.value:,.0f}".replace(","," ")
  self.create_text(cx,cy-7,text=val,fill=TEXT,font=(FONT,32,"bold"))
  self.create_text(cx,cy+28,text=self.unit,fill=SUB,font=(FONT,12))
  self.create_text(cx,h-19,text="MESURE À VALIDER" if self.title!="POIGNÉE DE GAZ" else "SIGNAL VALIDÉ · CAN 0x601",fill=YELLOW if self.title!="POIGNÉE DE GAZ" else GREEN,font=(FONT,9,"bold"))

class App:
 def __init__(self):
  self.root=tk.Tk();self.root.title("RSV4 CAN STUDIO | Telemetry Lab");self.root.geometry("1420x920");self.root.minsize(1040,730);self.root.configure(bg=BG)
  self.frames=[];self.idx=0;self.playing=False;self.speed=tk.DoubleVar(value=1.0);self.status=tk.StringVar(value="PRÊT · OUVRIR UNE CAPTURE")
  self.port=tk.StringVar(value="COM7");self.baud=tk.StringVar(value="2000000");self.experimental=tk.BooleanVar(value=True)
  self.last={};self.count=Counter();self.rows={};self.series=deque(maxlen=500);self.start_wall=0;self.start_frame=0;self.q=queue.Queue();self.live=False;self.stop_event=threading.Event()
  header=tk.Frame(self.root,bg=BG);header.pack(fill="x",padx=26,pady=(18,10))
  tk.Label(header,text="RSV4",fg=RED,bg=BG,font=(FONT,28,"bold")).pack(side="left")
  tk.Label(header,text="  CAN STUDIO",fg=TEXT,bg=BG,font=(FONT,26,"bold")).pack(side="left")
  tk.Label(header,textvariable=self.status,fg=GREEN,bg=BG,font=(FONT,11,"bold")).pack(side="right")
  bar=tk.Frame(self.root,bg=PANEL);bar.pack(fill="x",padx=24,pady=(0,10))
  for label,fn in [("IMPORTER .TXT",self.open_file),("▶ LECTURE",self.play),("Ⅱ PAUSE",self.pause),("↺ DÉBUT",self.reset),("USB-CAN DIRECT",self.connect),("DÉCONNECTER",self.disconnect)]:
   tk.Button(bar,text=label,command=fn,bg=PANEL2,fg=TEXT,activebackground="#32465f",activeforeground=TEXT,relief="flat",padx=12,pady=10,font=(FONT,10,"bold")).pack(side="left",padx=3,pady=7)
  tk.Label(bar,text="VITESSE",bg=PANEL,fg=SUB).pack(side="left",padx=8)
  ttk.Combobox(bar,textvariable=self.speed,values=[0.25,0.5,1,2,4,8],state="readonly",width=5).pack(side="left")
  tk.Button(bar,text="⚙ PARAMÈTRES",command=self.settings,bg=PANEL2,fg=TEXT,relief="flat",padx=12,pady=10).pack(side="right",padx=6)
  body=tk.Frame(self.root,bg=BG);body.pack(fill="both",expand=True,padx=24)
  top=tk.Frame(body,bg=BG);top.pack(fill="x")
  self.rpm=Gauge(top,"RÉGIME MOTEUR",15000,RED,"tr/min");self.rpm.pack(side="left",fill="both",expand=True,padx=4)
  self.speedg=Gauge(top,"VITESSE MOTO",320,CYAN,"km/h");self.speedg.pack(side="left",fill="both",expand=True,padx=4)
  self.throttle=Gauge(top,"POIGNÉE DE GAZ",100,GREEN,"%");self.throttle.pack(side="left",fill="both",expand=True,padx=4)
  cards=tk.Frame(body,bg=BG);cards.pack(fill="x",pady=8)
  self.cards={}
  for i,(key,label,unit) in enumerate([("gear","RAPPORT",""),("temp","TEMP. MOTEUR","°C"),("oil","TEMP. HUILE","°C"),("front","ROUE AVANT","km/h"),("rear","ROUE ARRIÈRE","km/h"),("battery","BATTERIE","V")]):
   c=tk.Frame(cards,bg=PANEL,height=90);c.grid(row=i//3,column=i%3,padx=4,pady=4,sticky="nsew");c.grid_propagate(False)
   tk.Label(c,text=label,fg=SUB,bg=PANEL,font=(FONT,10,"bold")).pack(anchor="w",padx=16,pady=(9,0))
   value=tk.Label(c,text="—",fg=TEXT,bg=PANEL,font=(FONT,23,"bold"));value.pack(anchor="w",padx=16)
   self.cards[key]=(value,unit)
  for i in range(3):cards.columnconfigure(i,weight=1)
  bottom=tk.Frame(body,bg=BG);bottom.pack(fill="both",expand=True,pady=(4,8))
  left=tk.Frame(bottom,bg=PANEL);left.pack(side="left",fill="both",expand=True,padx=(4,7))
  tk.Label(left,text="ÉVOLUTION POIGNÉE DE GAZ  ·  CAN 0x601",fg=TEXT,bg=PANEL,font=(FONT,11,"bold")).pack(anchor="w",padx=16,pady=(12,3))
  self.chart=tk.Canvas(left,bg=PANEL,highlightthickness=0,height=210);self.chart.pack(fill="both",expand=True,padx=12,pady=5)
  right=tk.Frame(bottom,bg=PANEL);right.pack(side="left",fill="both",expand=True,padx=(0,4))
  tk.Label(right,text="MONITEUR CAN  ·  TRAMES BRUTES",fg=TEXT,bg=PANEL,font=(FONT,11,"bold")).pack(anchor="w",padx=14,pady=(12,4))
  self.table=ttk.Treeview(right,columns=("id","n","data"),show="headings",height=10)
  for col,label,width in [("id","ID",85),("n","NB",60),("data","DONNÉES HEX",260)]:
   self.table.heading(col,text=label);self.table.column(col,width=width)
  self.table.pack(fill="both",expand=True,padx=8,pady=8)
  style=ttk.Style();style.theme_use("clam");style.configure("Treeview",background=PANEL2,foreground=TEXT,fieldbackground=PANEL2,rowheight=24);style.configure("Treeview.Heading",background="#2a3b52",foreground=TEXT)
  footer=tk.Label(self.root,text="IMPORTANT : Seule la poignée de gaz est validée sur cette moto. Les autres canaux sont expérimentaux et affichés à titre indicatif.",bg=BG,fg=YELLOW,font=(FONT,10))
  footer.pack(fill="x",pady=(0,10))
  self.root.after(40,self.tick);self.root.after(180,self.paint_chart)
  # bundled test log, if present
  base=getattr(sys,"_MEIPASS",os.path.dirname(os.path.abspath(__file__)))
  bundled=os.path.join(base,"CAPTURE_GAZ_RSV4.txt")
  if os.path.exists(bundled):self.load(bundled)
 def set_card(self,key,val):
  widget,unit=self.cards[key];widget.config(text=str(val)+(" "+unit if unit else ""))
 def open_file(self):
  p=filedialog.askopenfilename(title="Choisir une capture USB-CAN",filetypes=[("Fichiers texte","*.txt *.log"),("Tous fichiers","*.*")])
  if p:self.load(p)
 def load(self,path):
  try:frames=load_capture(path)
  except Exception as exc:messagebox.showerror("Erreur de lecture",str(exc));return
  self.pause();self.frames=frames;self.idx=0;self.last.clear();self.count.clear();self.series.clear()
  for row in self.table.get_children():self.table.delete(row)
  self.rows.clear()
  if not frames:
   self.status.set("0 TRAME · FORMAT NON RECONNU")
   messagebox.showwarning("0 trame","Le fichier ne contient pas de trames USB-CAN reconnaissables. Vérifiez qu'il s'agit d'un export TXT du logiciel USBCAN.")
  else:self.status.set(f"{len(frames):,} TRAMES · {len(set(c for _,c,_ in frames))} IDENTIFIANTS · {os.path.basename(path)}")
 def play(self):
  if not self.frames:messagebox.showinfo("Capture","Importez d'abord une capture TXT.");return
  self.playing=True;self.start_wall=time.monotonic();self.start_frame=self.frames[self.idx][0] if self.idx<len(self.frames) else 0
 def pause(self):self.playing=False
 def reset(self):
  self.pause();self.idx=0;self.series.clear()
  for key in self.cards:self.set_card(key,"—")
  self.rpm.set(None);self.speedg.set(None);self.throttle.set(None)
 def ingest(self,t,cid,data):
  self.last[cid]=data;self.count[cid]+=1
  if cid==0x601 and data:
   self.throttle.set(data[0]);self.series.append((t/1000,data[0]))
  if self.experimental.get():
   if cid==0x100 and len(data)>=5:
    self.rpm.set((data[3]<<8)|data[4])
    if len(data)>=2:
     self.set_card("gear",data[0]&15)
     if len(data)>=3:self.speedg.set(round((((data[1]<<8)|data[2])&4095)*.25,1))
   if cid==0x200 and len(data)>=2:
    self.set_card("temp",data[0]-40);self.set_card("oil",data[1]-40)
    if len(data)>=5:self.set_card("battery",round(data[4]*.1,1))
   if cid==0x260 and len(data)>=5:
    self.set_card("front",round(int.from_bytes(data[1:3],"big")*.01,1))
    self.set_card("rear",round(int.from_bytes(data[3:5],"big")*.01,1))
  if cid not in self.rows:self.rows[cid]=self.table.insert("","end",values=(f"0x{cid:03X}",0,""))
  self.table.item(self.rows[cid],values=(f"0x{cid:03X}",self.count[cid],data.hex(" ").upper()))
 def paint_chart(self):
  c=self.chart;c.delete("all");w=c.winfo_width();h=c.winfo_height()
  if w>30 and h>30:
   for i in range(5):
    y=15+(h-35)*i/4;c.create_line(45,y,w-12,y,fill="#29384b");c.create_text(8,y,text=str(100-25*i),anchor="w",fill=SUB,font=(FONT,9))
   pts=list(self.series)
   if len(pts)>1:
    start=max(0,pts[-1][0]-30);end=max(start+1,pts[-1][0])
    coords=[]
    for t,v in pts:
     if t<start:continue
     x=45+(w-60)*(t-start)/(end-start);y=15+(h-35)*(1-v/100);coords.extend([x,y])
    if len(coords)>=4:c.create_line(*coords,fill=GREEN,width=3,smooth=False)
  self.root.after(180,self.paint_chart)
 def tick(self):
  if self.playing and self.frames:
   elapsed=(time.monotonic()-self.start_wall)*1000*self.speed.get()
   limit=self.start_frame+elapsed
   batch=0
   while self.idx<len(self.frames) and self.frames[self.idx][0]<=limit and batch<1200:
    self.ingest(*self.frames[self.idx]);self.idx+=1;batch+=1
   if self.idx>=len(self.frames):self.pause()
  for _ in range(100):
   try:cid,data=self.q.get_nowait()
   except queue.Empty:break
   if cid=="error":self.disconnect();messagebox.showerror("Connexion série",data)
   else:self.ingest(int(time.monotonic()*1000),cid,data)
  self.root.after(40,self.tick)
 def settings(self):
  win=tk.Toplevel(self.root);win.title("Paramètres");win.configure(bg=PANEL);win.geometry("430x280")
  for label,var in [("Port série",self.port),("Vitesse série (bauds)",self.baud)]:
   tk.Label(win,text=label,bg=PANEL,fg=TEXT).pack(anchor="w",padx=22,pady=(15,3));tk.Entry(win,textvariable=var,width=26).pack(anchor="w",padx=22)
  tk.Checkbutton(win,text="Afficher les décodages expérimentaux (non validés)",variable=self.experimental,bg=PANEL,fg=TEXT,selectcolor=PANEL2,activebackground=PANEL).pack(anchor="w",padx=18,pady=15)
  tk.Label(win,text="Connexion USB-CAN : réception uniquement.\nMode Silent à configurer avec le logiciel officiel.",bg=PANEL,fg=YELLOW,justify="left").pack(anchor="w",padx=22)
 def disconnect(self):self.live=False;self.stop_event.set()
 def connect(self):
  if serial is None:messagebox.showerror("Dépendance","pyserial manquant");return
  if not messagebox.askokcancel("Sécurité CAN","Configurer l'adaptateur en mode Silent et CAN 250 kbit/s avec USBCAN, puis fermer USBCAN.\n\nCette application n'envoie aucune commande, et ne peut pas vérifier que le mode Silent reste actif.\n\nContinuer ?"):return
  self.disconnect();self.stop_event=threading.Event();stop=self.stop_event;self.live=True
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
