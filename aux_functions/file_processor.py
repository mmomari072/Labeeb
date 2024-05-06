#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun May  5 22:42:00 2024

@author: omari
"""
import os

from copy import deepcopy

class File:
    def __init__(self,file_path="",mode="r",keep_path_struct=False,**kwd):
        self.file_path = file_path
        self.mode = mode
        self.__db__ = []
        self.__replaced__=[]
        self.search_index = {}
        self.force_read = False
        self.__process_functions__=[]
        self.processed =[]
        self.refresh_read_before_write=False
        
        self.fname_is_file_path=False
        #
        self.__kwargs__(**kwd)
        
    def read(self,file_path=None,force_read=False):
        if file_path is not None:
            self.file_pathe=file_path
        if len(self)>0 and not self.force_read:
            return self
        with open(self.file_path) as fid:
            self.__db__ = [l.strip('\n') for l in fid]
        return self
    
    def search(self,*kw):
        if len(kw) ==0:
            print("Warning!, nothing has been entered")
            return self
        self.search_index = {x:[] for x in kw}
        for i,line in enumerate(self.__db__):
            for k in kw:
                #print(k)
                if line.find(k)>=0:
                    self.search_index[k]+=[i]
        return self
    def replace(self,rep_dict={},**kw):
        if not all([x in self.search_index for x in rep_dict]):    
            self.search(*list(rep_dict.keys()))
        self.__replaced__ = deepcopy(self.__db__)
        for word,line_id in self.search_index.items():
            for i in line_id:
                if rep_dict[word] is None:
                    continue
                self.__replaced__[i]=self.__replaced__[i].replace(word,rep_dict[word])      
        return self
    
    def write(self,filename,mode="w"):
        if self.refresh_read_before_write:
            self.read()
        head,tail = os.path.split(filename)
        if not os.path.exists(head):
            os.makedirs(head)
        with open(filename,mode) as fid:
            _=[print(line,file=fid) for line in self]
        return self
    def __iter__(self):
        self.current_index = 0
        return self
    def __next__(self):
        if self.current_index < len(self):
            self.current_index += 1
            return self[self.current_index-1]
        raise StopIteration
    def __getitem__(self,i):
        return self.__replaced__[i] if len(self.__replaced__)>0 else self.__db__[i]
    def __len__(self):
        return len(self.__db__)
    
    def __getattr__(self,name):
        if name.lower() in ["filename","fname"]:
            if self.fname_is_file_path:
                return self.file_path
            head,tail = os.path.split(self.file_path)
            return tail
        elif name.lower() in ["dir_path","dir","location"]:
            head,tail = os.path.split(self.file_path)
            return head
    
    def clear(self):
        self.__init__()
    def add_processing_func(self,*fun):
        for f in fun:
            if f not in self.__process_functions__:
                self.__process_functions__.append(f)
                pass
            pass
        return self
    def process(self,**kw):
        for f in self.__process_functions__:
            f(self,**kw)
        return self
    
    def __kwargs__(self,**kw):
        for att,val in kw.items():
            if att.lower() in self.__dict__:
                self.__setattr__(att.lower(), val)
            elif att.lower() in ["refresh"]:
                self.__setattr__("refresh_read_before_write", val)
            elif att.lower() in ["fname_is_path"]:
                self.__setattr__("fname_is_file_path", val)
                pass
        return self
    
    def set_args(self,**kwargs):
        self.__kwargs__(**kwargs)
        return self
    
if __name__=="__main__":
    f=File("../test/Case.py")
