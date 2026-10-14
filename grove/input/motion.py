"""Bounded visual motion. No claims about detection or human identity."""
import math
import random

def bezier_path(start,end,dimensions,rng=None):
    rng=rng or random
    width,height=dimensions
    if width<=0 or height<=0: raise ValueError('Invalid motion bounds.')
    dx,dy=end[0]-start[0],end[1]-start[1]
    distance=math.hypot(dx,dy)
    duration=rng.uniform(.22,.55)+min(.25,distance/2500)
    steps=max(12,round(duration/.018))
    bend=rng.uniform(-1,1)*min(80,distance*.22)
    nx,ny=(-dy/distance,dx/distance) if distance else (0,0)
    p1=(start[0]+dx*.3+nx*bend,start[1]+dy*.3+ny*bend)
    p2=(start[0]+dx*.7+nx*bend*.6,start[1]+dy*.7+ny*bend*.6)
    result=[]
    for index in range(1,steps+1):
        t=index/steps
        u=t*t*(3-2*t)
        x=(1-u)**3*start[0]+3*(1-u)**2*u*p1[0]+3*(1-u)*u*u*p2[0]+u**3*end[0]
        y=(1-u)**3*start[1]+3*(1-u)**2*u*p1[1]+3*(1-u)*u*u*p2[1]+u**3*end[1]
        if index<steps:
            x+=rng.uniform(-1,1)*math.sin(math.pi*t)
            y+=rng.uniform(-1,1)*math.sin(math.pi*t)
        else: x,y=end
        result.append(((max(0,min(width-1,round(x))),max(0,min(height-1,round(y)))),max(8,round(duration*1000/steps*rng.uniform(.85,1.15)))))
    return result
