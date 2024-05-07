#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu May  2 14:15:15 2024

@author: omari
"""
import random

class _list(list):
   def __init__(self,name,description:str=None,Type=None,unit=None,data=[]):
       super().__init__()
        

class attribute(list):
    def __init__(self,name,description:str=None,Type=None,unit=None,data=[]):
        super().__init__()
        self.name:str=name
        self.description=description
        self.type=Type
        self.unit=unit
        self.__fun_list=[]
        self.__append(data)
    
    def __operation__failure_check(self, x,operator:str):
        if not isinstance(x,(attribute,list,tuple)):
            raise ValueError("")
        elif len(x)!=len(self):
            raise ValueError("")
        else:
            raise("Unknow Error")
    def __append(self,data):
        [self.append(x) for x in data]
    
    def __call__(self):
        return "Not Now!!!"

    def __operation__(self,x,op,is_right=False):
        fun=eval(f"lambda x,y:x {op} y")
        if op in ["/","//"]:
            def fun(x,y):
                try:
                    f=eval(f"lambda x,y:x {op} y")
                    return f(x,y)
                except:
                    return (float("nan") if x==0 else (float("inf") if x>0 else float("-inf")))
        _type=self.type if op not in ["&","|",">",">=","<","<=","==","!="] else bool
        if isinstance(x,(int,float)):
            xname=str(x)
            name = f"({self.name} {op} {xname})" if not is_right else f"({xname} {op} {self.name})"
            return attribute(name=name,data=
                             [fun(xx,x) for xx in self],Type=_type)
        elif isinstance(x,(attribute,list,tuple)) and len(x)==len(self):
            xname=x.name if isinstance(x,(attribute)) else "X"
            name = f"({self.name} {op} {xname})" if not is_right else f"({xname} {op} {self.name})"
            return attribute(name=name,data=map(fun,self,x),
                             #[fun(xx,yy) for xx,yy in zip(self,x)],
                             Type=_type)
        
        self.__operation__failure_check(x,"+")
    
    # *************************************************************************
    # 
    # 
    # 
    # *************************************************************************
    # left hand side operation
    # *************************************************************************
    
    def __add__(self,x):
        return self.__operation__(x,"+")
    
    def __sub__(self,x):
        return self.__operation__(x,"-")
    
    def __mul__(self,x):
        return self.__operation__(x,"*")
    
    def __truediv__(self,x):
        return self.__operation__(x,"/")
    
    def __mod__(self,x):
        return self.__operation__(x,"%")
 
    def __pow__(self,x):
        return self.__operation__(x,"**")
    
    def __xor__(self,x):
        print("xor")
        return self.__operation__(x,"+")
    
    def __and__(self,x):
        print("and")
        return self.__operation__(x,"and")
    
    def __or__(self,x):
        print("or")
        return self.__operation__(x,"or")
    
    # *************************************************************************
    # right handside operation
    # *************************************************************************
    def __radd__(self,x):
        return self.__operation__(x,"+",is_right=True)
    
    def __rsub__(self,x):
        return self.__operation__(x,"-",is_right=True)
    
    def __rmul__(self,x):
        return self.__operation__(x,"*",is_right=True)
    
    def __rtruediv__(self,x):
        return self.__operation__(x,"/",is_right=True)
    
    def __rmod__(self,x):
        return self.__operation__(x,"%",is_right=True)
 
    def __rpow__(self,x):
        return self.__operation__(x,"**",is_right=True)
    
    def __rxor__(self,x):
        return self.__operation__(x,"^",is_right=True)
    
    __iadd__=__add__ 
    __isub__=__sub__
    __imul__=__mul__
    __itruediv__=__truediv__
    __imod__=__mod__
    __ipow__=__pow__
    
    def __ixor__(self,x):
        return self.__operation__(x,"^",is_right=True)
    
        
    # *************************************************************************
    # comparison operation
    # *************************************************************************
    def __eq__(self, x):
        return self.__operation__(x,"==")
    
    def __ne__(self, x):
        return self.__operation__(x,"!=")

    def __lt__(self, x):
        return self.__operation__(x,"<")

    def __le__(self, x):
        return self.__operation__(x,"<=")

    def __gt__(self, x):
        return self.__operation__(x,">")
    
    def __ge__(self, x):
        return self.__operation__(x,">=")
    
    def __getitem__(self, i):
        if type(i) is attribute:
            if i.type is bool:
                return attribute(name=self.name,data=[self[j] for j,k in enumerate(i) if k])
            return attribute(name=self.name,data=[self[j] for j in i])
            
        if isinstance(i,(int,slice)):
            return super().__getitem__(i)
        if isinstance(i,(list,tuple)):
            return attribute(name=self.name,data=[self[j] for j in i])
        
    def __setattr__(self,name,value):
        if name.lower() in ["unit0"]:
            return 
        super().__setattr__(name, value)
        
    def __dir__(self):
        return [x for x in super().__dir__() if x.find("__")<0]

           
    # def __instancecheck__(self,val):
    #     print("Bingo test ",val)
    #     return "omar"
        
    
    
    def __bool__(self):
        #print("__bool__")
        return all(self)
    
    def add_functions(self,*fun):
        for f in fun:
            if f.__name__ in self.__dict__:
                continue
            self.__dict__[f.__name__]=f.__get__(self)
            self.__fun_list.append(f)
        return self
    
    def sum(self):
        return sum(self)
    
    def mean(self):
        return self.sum()/len(self)
    
    def filter(self,function=lambda x:x>1,return_index=False):
        x= attribute(name="",data=map(function,self))
        if not return_index:
            return x
        return [i for i,x in enumerate(x) if x]
            
class database:
    def __init__(self,name:str=None,description:str=None):
        self.name:str =name
        pass
    



A=attribute("test",data=[1,2,3,4,1,2,3,2,1,5,7])

c=A+A