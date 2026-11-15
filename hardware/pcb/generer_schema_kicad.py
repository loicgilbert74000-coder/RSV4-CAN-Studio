"""Schémas KiCad (format 5, connexions par étiquettes) des deux cartes, depuis generer_netlist.py. Import possible dans EasyEDA Standard (zip). Usage : python3 generer_schema_kicad.py [dossier]"""
import sys,os,math,zipfile,uuid
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import generer_netlist as g
BW=600   # demi-largeur du boîtier
PL=200   # longueur de broche
def build(b,name,outdir):
    pins={}
    for net,nodes in b.pins.items():
        for ref,pin,func in nodes: pins.setdefault(ref,[]).append((pin,net,func))
    def key(p):
        try: return (0,int(p[0]))
        except: return (1,p[0])
    lib=["EESchema-LIBRARY Version 2.4","#encoding utf-8"]
    comps=[]; lib2=["EESchema-LIBRARY Version 2.4","#encoding utf-8"]
    placed=[]; 
    # empaquetage par étagères
    X0,Y0=1500,1500; MAXW=26000; cx=X0; cy=Y0; rowh=0
    for ref,(val,fp,desc) in b.comps.items():
        pl=sorted(pins.get(ref,[]),key=key)
        if not pl: continue
        n=len(pl)
        if n==2: L,R=[pl[0]],[pl[1]]
        else:
            h=(n+1)//2; L,R=pl[:h],pl[h:]
        m=max(len(L),len(R)); half=100*(m-1)+200
        def mk(sym):
            o=["#",f"# {sym}","#",f"DEF {sym} {ref[0] if ref[0].isalpha() else 'U'} 0 40 Y N 1 F N",
              f'F0 "{ref[0]}" 0 {half+120} 50 H V C CNN',f'F1 "{sym}" 0 {-half-120} 50 H I C CNN','F2 "" 0 0 50 H I C CNN','F3 "" 0 0 50 H I C CNN',"DRAW",
              f"S {-BW} {half} {BW} {-half} 0 1 10 f"]
            for i,(p,net,f) in enumerate(L):
                y=(m-1)*100-i*200; o.append(f'X "{(f or p)[:14]}" {p} {-BW-PL} {y} {PL} R 50 50 1 1 P')
            for i,(p,net,f) in enumerate(R):
                y=(m-1)*100-i*200; o.append(f'X "{(f or p)[:14]}" {p} {BW+PL} {y} {PL} L 50 50 1 1 P')
            return o+["ENDDRAW","ENDDEF"]
        sym=ref; lib+=mk(f"TL_{ref}"); lib2+=mk(ref)
        w=2*(BW+PL)+2000; hh=2*half+500
        if cx+w>MAXW: cx=X0; cy+=rowh; rowh=0
        px=cx+w//2; py=cy+hh//2
        rowh=max(rowh,hh)
        cx+=w
        comps.append((ref,val,fp,sym,px,py,L,R,m,half))
    # corriger champs F0/F1 dans lib : réécriture simple
    txt="\n".join(lib)
    for ref,val,fp,sym,px,py,L,R,m,half in comps:
        txt=txt.replace(f'F1 "{sym}" 0 ',f'F1 "{sym}" 0 ',1)
    sch=["EESchema Schematic File Version 4","EELAYER 30 0","EELAYER END","$Descr User 30000 22000","encoding utf-8","Sheet 1 1",
         f'Title "TrackLab Electronics - {name}"','Date "2026-11-15"','Rev "5"','Comp ""','Comment1 "Schema genere depuis generer_netlist.py - connexions par etiquettes de reseau"','Comment2 ""','Comment3 ""','Comment4 ""',"$EndDescr"]
    for k,(ref,val,fp,sym,px,py,L,R,m,half) in enumerate(comps):
        u=uuid.uuid5(uuid.NAMESPACE_DNS,f"{name}{ref}").hex[:8].upper()
        sch+=["$Comp",f"L TL:{sym} {ref}",f"U 1 1 {u}",f"P {px} {py}",
              f'F 0 "{ref}" H {px} {py-half-150} 60 0000 C CNN',f'F 1 "{val}" H {px} {py+half+150} 60 0000 C CNN',
              f'F 2 "{fp}" H {px} {py} 50 0001 C CNN','F 3 "~" H '+f"{px} {py} 50 0001 C CNN",
              f"\t1    {px} {py}","\t1    0    0    -1","$EndComp"]
        for i,(p,net,f) in enumerate(L):
            y=py-((m-1)*100-i*200); sch+=[f"Text Label {px-BW-PL} {y} 2 60 ~ 0",net]
        for i,(p,net,f) in enumerate(R):
            y=py-((m-1)*100-i*200); sch+=[f"Text Label {px+BW+PL} {y} 0 60 ~ 0",net]
    sch.append("$EndSCHEMATC")
    d=os.path.join(outdir,name); os.makedirs(d,exist_ok=True)
    open(f"{d}/{name}.sch","w").write("\n".join(sch)+"\n")
    open(f"{d}/{name}-cache.lib","w").write(txt+"\n#\n#End Library\n")
    open(f"{d}/{name}.pro","w").write("update=22/05/2015 07:44:53\nversion=1\nlast_client=kicad\n[eeschema]\nversion=1\nLibDir=\n[eeschema/libraries]\nLibName1=TL\n")
    open(f"{d}/TL.lib","w").write("\n".join(lib2)+"\n#\n#End Library\n")
    with zipfile.ZipFile(f"{outdir}/{name}.zip","w",zipfile.ZIP_DEFLATED) as z:
        for f in os.listdir(d): z.write(f"{d}/{f}",f)
    print(name,len(comps),"composants")
out=sys.argv[1] if len(sys.argv)>1 else os.path.join(os.path.dirname(os.path.abspath(__file__)),"schema_kicad")
for b,n in ((g.etage2(),"TrackLab_etage2"),(g.etage1(),"TrackLab_etage1")): build(b,n,out)
