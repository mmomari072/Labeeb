#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun May  5 23:37:31 2024

@author: omari
"""
import numpy as np
import pylab as plt
import pandas as pd

def eular(X,fun,Y0=0,**kw):
    A=[Y0]
    for i in range(0,len(X)-1):
        dx=X[i+1]-X[i]
        A.append(A[-1]+dx*fun(X[i],A[-1],**kw))
    return A
xx=np.linspace(0, 1000,10000)
def f(x,y,**kw):
    #print(kw)
    rho=kw["rho"]
    return -0.01*(rho/10)*y

df=pd.DataFrame(data=dict(thickness=xx,I=eular(xx, f, Y0=1,rho=#RHO@@#)))
df.to_csv("./omari.csv")
plt.plot(xx,eular(xx, f, 10,rho=5))
RHO=#RHO@@#
print(f"Density Value {RHO}")
