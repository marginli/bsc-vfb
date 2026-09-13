# -*- coding: utf-8 -*-
"""稽核 inline SVG：所有元素是否落在 viewBox 內。"""
import io,re,sys,unicodedata

def textw(t, fs):
    w=0
    for ch in re.sub(r'<[^>]+>','',t):
        w += fs*(1.0 if unicodedata.east_asian_width(ch) in 'WF' else 0.55)
    return w

def audit(path):
    s=io.open(path,encoding='utf-8').read()
    for i,m in enumerate(re.finditer(r'<svg\b[^>]*viewBox="([^"]+)"[^>]*>(.*?)</svg>',s,flags=re.S),1):
        vx,vy,vw,vh=[float(x) for x in m.group(1).split()]
        body=m.group(2)
        # 巢狀 <g> 用堆疊掃描，累加 translate 位移
        chunks=[]; stack=[(0.0,0.0)]; pos=0
        for tok in re.finditer(r'<g\b([^>]*)>|</g>|<(text|circle|rect|ellipse|path)\b[^>]*(?:/>|>.*?</\2>)',body,flags=re.S):
            t=tok.group(0)
            if t.startswith('</g'):
                if len(stack)>1: stack.pop()
            elif t.startswith('<g'):
                mm=re.search(r'translate\(([-\d.]+)[, ]\s*([-\d.]+)\)',tok.group(1) or '')
                dx,dy=stack[-1]
                if mm: dx+=float(mm.group(1)); dy+=float(mm.group(2))
                stack.append((dx,dy))
            else:
                chunks.append((stack[-1][0],stack[-1][1],t))
        # 預設字級
        fsmap={}
        for c in re.finditer(r'\.(\w+)\{[^}]*font-size:([\d.]+)px',body): fsmap[c.group(1)]=float(c.group(2))
        bad=[]
        for dx,dy,ck in chunks:
            for t in re.finditer(r'<text([^>]*)>(.*?)</text>',ck,flags=re.S):
                at,inner=t.group(1),t.group(2)
                x=float(re.search(r'\bx="([-\d.]+)"',at).group(1)) if re.search(r'\bx="([-\d.]+)"',at) else 0
                y=float(re.search(r'\by="([-\d.]+)"',at).group(1)) if re.search(r'\by="([-\d.]+)"',at) else 0
                cls=re.search(r'class="(\w+)"',at); fs=fsmap.get(cls.group(1) if cls else '',13.0)
                fsa=re.search(r'font-size="([\d.]+)"',at)
                if fsa: fs=float(fsa.group(1))
                anc=re.search(r'text-anchor="(\w+)"',at); w=textw(inner,fs)
                x0=x-w/2 if (anc and anc.group(1)=='middle') else (x-w if (anc and anc.group(1)=='end') else x)
                box=(dx+x0, dy+y-fs*0.8, dx+x0+w, dy+y+fs*0.25)
                lbl=re.sub(r'<[^>]+>','',inner)[:22]
                if box[0]<vx-.5 or box[1]<vy-.5 or box[2]>vx+vw+.5 or box[3]>vy+vh+.5:
                    bad.append(('text',lbl,[round(v,1) for v in box]))
            for c in re.finditer(r'<circle[^>]*\bcx="([-\d.]+)"[^>]*\bcy="([-\d.]+)"[^>]*\br="([\d.]+)"',ck):
                cx,cy,r=map(float,c.groups())
                box=(dx+cx-r,dy+cy-r,dx+cx+r,dy+cy+r)
                if box[0]<vx-.5 or box[1]<vy-.5 or box[2]>vx+vw+.5 or box[3]>vy+vh+.5:
                    bad.append(('circle','',[round(v,1) for v in box]))
            for r_ in re.finditer(r'<rect[^>]*\bx="([-\d.]+)"[^>]*\by="([-\d.]+)"[^>]*\bwidth="([\d.]+)"[^>]*\bheight="([\d.]+)"',ck):
                x,y,w,h=map(float,r_.groups())
                box=(dx+x,dy+y,dx+x+w,dy+y+h)
                if box[0]<vx-.5 or box[1]<vy-.5 or box[2]>vx+vw+.5 or box[3]>vy+vh+.5:
                    bad.append(('rect','',[round(v,1) for v in box]))
            for e in re.finditer(r'<ellipse[^>]*\bcx="([-\d.]+)"[^>]*\bcy="([-\d.]+)"[^>]*\brx="([\d.]+)"[^>]*\bry="([\d.]+)"',ck):
                cx,cy,rx,ry=map(float,e.groups())
                box=(dx+cx-rx,dy+cy-ry,dx+cx+rx,dy+cy+ry)
                if box[0]<vx-.5 or box[1]<vy-.5 or box[2]>vx+vw+.5 or box[3]>vy+vh+.5:
                    bad.append(('ellipse','',[round(v,1) for v in box]))
            for p_ in re.finditer(r'<path[^>]*\bd="([^"]+)"',ck):
                d=p_.group(1)
                # 只處理純絕對座標的路徑；含相對指令（h/v/l/c/s/q/t/a）的略過，避免誤判
                if re.search(r'[hvlcsqta]', d): continue
                nums=[float(v) for v in re.findall(r'-?\d+\.?\d*',d)]
                xs,ys=nums[0::2],nums[1::2]
                if not xs or not ys: continue
                box=(dx+min(xs),dy+min(ys),dx+max(xs),dy+max(ys))
                if box[0]<vx-2 or box[1]<vy-2 or box[2]>vx+vw+2 or box[3]>vy+vh+2:
                    bad.append(('path','',[round(v,1) for v in box]))
        print(f"  SVG {i}  viewBox {vx:.0f} {vy:.0f} {vw:.0f} {vh:.0f}  →  {'OK' if not bad else str(len(bad))+' 個元素超出'}")
        for k,l,b in bad: print(f"      {k:8s} {l:24s} bbox {b}")

for f in sys.argv[1:]: print(f); audit(f)
