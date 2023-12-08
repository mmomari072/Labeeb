# -*- coding: utf-8 -*-
"""
Created on Tue Nov 28 10:41:38 2023

@author: mohammed.omari
"""
import pandas as pd
import numpy as np
from random import random


def uniform_sample(start,end,size=1):
    return np.random.uniform(start,end,size)

def normal_sample(mean,std, size=1):
    return np.random.normal(mean,std,size)

def sample(size=0):
    return list(range(size))

def product(X=[]):
    P=1
    for xx in X:
        P=P*xx
    return P if len(X)>0 else None

class Discreate_Sampling:
    def __init__(self):
        self.name = "OMARI"
        self.values = []
        self.props  = []
        self.cdf    = []
    def define_sample(self,values=["A","B","C","D"],props=[0.2,.3,.4,.1]):
        self.values=values
        self.props=props
        self.cdf=[0]
        for i in props:
            self.cdf.append(self.cdf[-1]+i)
        self.cdf = [c/self.cdf[-1] for c in self.cdf]
        return self
    def get_randon_sample(self,n=1):
        if n>1:
            return [self.get_randon_sample() for i in range(n)]
        r = random()
        for i in range(1,len(self.cdf)):
            if self.cdf[i-1]<=r<self.cdf[i]:
                return self.values[i-1]
        if r==1:
            return self.values[-1]
        return None
    def Stat(self,m=100):
        x = self.get_randon_sample(m)
        A={}
        for a in self.values:
            #print(len(x))
            #print(a)
            A[a]=sum([1 for i in x if a==i])/len(x)
        print(A)

class FOAT_constructer:
    def __init__(self,case_name=None,cases=None):
        self.name = case_name
        self.description = """"""
        self.cases = {}
        self.samples ={}
        pass
    def add_case(self,*cases):
        for c in cases:
            for att,val in c.items():
                self.cases[att]=val
                pass
    def construct(self):
        self.samples={}
        Att = [x for x in self.cases]
        LEN =[len(x) for _,x in self.cases.items()]
        size = product(LEN)
        INDEX={x:[] for x in Att}
        MULTIPLIER = {x:int(size/product(LEN[:i+1])) for i,x in enumerate(Att)}
        for i in range(len(LEN)-1,-1,-1):
            att=Att[i]
            tmp =sample(LEN[i])
            tmp2=[]
            for j in tmp:
                tmp2+=[j]*MULTIPLIER[att]
                INDEX[att]=tmp2*int(size/len(tmp2))
        for att,index in INDEX.items():
            self.samples[f"__{att}_index__"]=[]
            self.samples[att]=[]
            for i,j in enumerate(index):
                self.samples[f"__{att}_index__"].append(j)
                self.samples[att].append(self.cases[att][j])
                pass
        return self.samples
                

if __name__=="__main__":
    A=FOAT_constructer()
    A.add_case(dict(
            a=["a","b","c","d"],
            b=["aaa","bb","cc","dd"],
            c=["#","$"],
            #d=sample(6),
            #e=sample(1)
    ),
        dict(
               f=sample(2),
                #b=sample(4),
                #c=sample(4),
                #d=sample(6),
                #e=sample(1)
        ))
    v = A.construct()     
    df=pd.DataFrame(v)   
    df.to_excel("OAT_INDEX_TEST.xlsx")

if __name__=="__main__":
    cases = {x:0 for x in ["A","B","C","D"]}
    N = 1000000;
    C = Discreate_Sampling()
    C.define_sample()
    CC=C.get_randon_sample(N)
    
    for i in range(N):
        #cc = C.get_randon_sample()
        cc=CC[i]
        cases[cc]+=1
    
    P = {x:v/N for x,v in cases.items()}
        