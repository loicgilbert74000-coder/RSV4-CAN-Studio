import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import re, threading, queue, time
from collections import defaultdict
try:
 import serial
except ImportError:
 serial=None
BG="#0d111b"; PANEL="#171e2d"; FG="#e9edf5"; MUTED="#95a2b8"; GREEN="#49db9a"; RED="#fa5e65"
class Studio:
 def __init__(self):
  self.root=tk.Tk(); self.root.title("RSV4 CAN STUDIO — Diagnostic"); self.root.geometry("1220x790"); self.root.configure(bg=BG)
  self.q=queue.Queue(); self.running=False; self.frames=[]; self.idx=0; self.values={}; self.count=defaultdict(int)
  self.port=tk.StringVar(value="COM7"); self.baud=tk.StringVar(value="2000000"); self.status=tk.StringVar(value="PRÊT · Mode fichier")
  self.head=tk.Frame(self.root,bg=BG); self.head.pack(fill="x",padx=25,pady=18)
  tk.Label(self.head,text="RSV4  /  CAN STUDIO",bg=BG,fg=FG,font=("Segoe UI",25,"bold")).pack(side="left")
  tk.Label(self.head,textvariable=self.status,bg=BG,fg=GREEN,font=("Segoe UI",11)).pack(side="right")
  bar=tk.Frame(self.root,bg=PANEL);bar.pack(fill="x",padx=25,pady=5)
  for title,fn in [("OUVRIR CAPTURE",self.open_file),("▶ LECTURE",self.play),("■ ARRÊT",self.stop),("CONNECTER COM",self.connect)]:
   tk.Button(bar,text=title,command=fn,bg="#26334b",fg=FG,relief="flat",font=("Segoe UI",10,"bold"),padx=14,pady=12).pack(side="left",padx=5,pady=7)
  tk.Label(bar,text="Port",bg=PANEL,fg=MUTED).pack(side="left",padx=5)
  tk.Entry(bar,textvariable=self.port,width=7).pack(side="left")
  tk.Label(bar,text="Bauds",bg=PANEL,fg=MUTED).pack(side="left",padx=5)
  tk.Entry(bar,textvariable=self.baud,width=10).pack(side="left")
  self.grid=tk.Frame(self.root,bg=BG);self.grid.pack(fill="x",padx=20,pady=14)
  self.cards={}
  metrics=[("RÉGIME MOTEUR","rpm","tr/min"),("POIGNÉE DE GAZ","aps","%"),("RAPPORT","gear",""),("VITESSE","speed","km/h"),("TEMP. MOTEUR","temp","°C"),("TEMP. HUILE","oil","°C"),("ROUE AVANT","front","km/h"),("ROUE ARRIÈRE","rear","km/h"),("BATTERIE","battery","V")]
  for i,(label,key,unit) in enumerate(metrics):
   box=tk.Frame(self.grid,bg=PANEL,width=365,height=105);box.grid(row=i//3,column=i%3,padx=6,pady=6,sticky="nsew");box.grid_propagate(False)
   tk.Label(box,text=label,bg=PANEL,fg=MUTED,font=("Segoe UI",10,"bold")).pack(anchor="w",padx=16,pady=(11,0))
   v=tk.Label(box,text="— "+unit,bg=PANEL,fg=GREEN if key=="aps" else FG,font=("Segoe UI",25,"bold"));v.pack(anchor="w",padx=16)
   self.cards[key]=(v,unit)
  for i in range(3):self.grid.columnconfigure(i,weight=1)
  tk.Label(self.root,text="TRAMES CAN BRUTES  ·  Décodage APS validé, autres canaux expérimentaux",bg=BG,fg=MUTED,font=("Segoe UI",11,"bold")).pack(anchor="w",padx=27,pady=(8,5))
  frame=tk.Frame(self.root,bg=BG);frame.pack(fill="both",expand=True,padx=26,pady=(0,20))
  self.table=ttk.Treeview(frame,columns=("id","count","data"),show="headings",height=10)
  for col,title,width in [("id","CAN ID",130),("count","TRAMES",120),("data","DERNIERS OCTETS",650)]:
   self.table.heading(col,text=title);self.table.column(col,width=width)
  self.table.pack(fill="both",expand=True)
  self.root.after(40,self.tick)
 def show(self,key,value):
  label,unit=self.cards[key];label.config(text=str(value)+(" "+unit if unit else ""))
 def ingest(self,ident,data):
  self.count[ident]+=1;self.values[ident]=data
  if ident==0x601 and len(data)>=1:self.show("aps",data[0])
  if ident==0x200 and len(data)>=2:
   self.show("temp",str(data[0]-40)+"*");self.show("oil",str(data[1]-40)+"*")
  if ident==0x100 and len(data)>=6:
   self.show("rpm",str((data[3]<<8)|data[4])+"*")
  if ident not in getattr(self,"rows",{}):
   if not hasattr(self,"rows"):self.rows={}
   self.rows[ident]=self.table.insert("","end",values=(f"0x{ident:03X}",0,""))
  self.table.item(self.rows[ident],values=(f"0x{ident:03X}",self.count[ident],data.hex(" ").upper()))
 def open_file(self):
  path=filedialog.askopenfilename(filetypes=[("CAN captures","*.txt *.log"),("Tous fichiers","*.*")])
  if not path:return
  self.stop();self.frames=[];self.idx=0
  rx=re.compile(r"Standard frame\s+([0-9a-fA-F]{8})\s+8\s+((?:[0-9a-fA-F]{2}\s+){7}[0-9a-fA-F]{2})")
  with open(path,encoding="latin1",errors="replace") as f:
   for line in f:
    m=rx.search(line)
    if m:self.frames.append((int(m[1],16),bytes.fromhex(m[2])))
  self.status.set(f"{len(self.frames):,} trames chargées · {path.split('/')[-1]}")
 def play(self):
  if not self.frames:messagebox.showinfo("Capture","Ouvrez d'abord votre fichier CAN .txt");return
  self.running=True;self.status.set("LECTURE DE CAPTURE")
 def stop(self):self.running=False;self.status.set("ARRÊT")
 def connect(self):
  if serial is None:messagebox.showerror("Dépendance","pyserial non disponible");return
  if self.running:self.stop()
  self.status.set("Connexion série (réception uniquement)")
  def worker():
   try:
    with serial.Serial(self.port.get(),int(self.baud.get()),timeout=.2) as ser:
     buf=bytearray()
     while self.running:
      buf.extend(ser.read(512))
      while len(buf)>4:
       start=buf.find(b"\xaa")
       if start<0:buf.clear();break
       del buf[:start]
       if len(buf)<5:break
       # Paquets de longueur variable AA Cx IDlo IDhi DATA... 55
       typ=buf[1]
       if typ&0xf0!=0xc0:del buf[0];continue
       size=typ&0x0f
       if size>8:del buf[0];continue
       total=5+size
       if len(buf)<total:break
       packet=bytes(buf[:total]);del buf[:total]
       if packet[-1]!=0x55:continue
       self.q.put((packet[2]|(packet[3]<<8),packet[4:-1]))
   except Exception as e:self.q.put(("error",str(e)))
  self.running=True;threading.Thread(target=worker,daemon=True).start()
 def tick(self):
  if self.running and self.frames:
   for _ in range(12):
    if self.idx>=len(self.frames):self.stop();break
    self.ingest(*self.frames[self.idx]);self.idx+=1
  for _ in range(50):
   try:item=self.q.get_nowait()
   except queue.Empty:break
   if item[0]=="error":self.stop();messagebox.showerror("Port série",item[1])
   else:self.ingest(*item)
  self.root.after(40,self.tick)
if __name__=="__main__":Studio().root.mainloop()
