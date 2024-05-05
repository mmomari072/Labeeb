# -*- coding: utf-8 -*-
"""
Created on Sun Nov 26 20:43:36 2023

@author: mohammed.omari
"""
import time
from copy import deepcopy
import os,shutil,glob,subprocess


class Timer:
    def __init__(self,name=None):
        self.name = name
        self.description = None
        self.start = time.time()
        self.end   = None
        self._end_2_ = None
        self.delta = None
        self._deltas_ = [0]
        self._times_ = [0]
        pass
    def tic(self):
        self.start = time.time()
        return self
    def toc(self,Print=False):
        self.end = time.time()
        self.delta = self.end-self.start
        self._deltas_.append(self.delta)
        self._times_.append(self._times_[-1]+1)
        
        return self.delta
    
    def __repr__(self):
        S = "%02i:%02i:%02i:%06.3f"%Timer.convert_sec_to_time(self.delta)
        return f"Elapsed time {S}"
    def __str__(self):
        return "%02i:%02i:%02i:%06.3f"%Timer.convert_sec_to_time(self.delta)

    def convert_sec_to_time(s=100):
        ss=s
        A = []
        for f in [24*3600,3600,60,1]:
            A.append(int(ss/f))
            ss=ss%f
        A[-1]+=ss
        return tuple(A)

class progress_bar:
    def __init__(self,name,start,end,step=1):
        self.name=name
        self.start=start
        self.end = end
        self.step = step
        self.col_len=40
        self.timer=Timer()
        self.is_started =False
        self.__progress__ = 0
        self.__index__    = 0
        pass
    
    def __calculate_progress__(self):
        self.__progress__= (self.__index__-self.start)/(self.end-self.start-1)
        self.__time__remaining= (self.end-self.__index__-1)*self.timer._deltas_[-1]/self.timer._times_[-1]
        pass
    
    def __iter__(self):
        self.__index__ = self.start
        self.__tmp_len_char =-1
        self.timer.tic()
        return self
    
    def __next__(self):
        if self.__index__ < self.end:
            self.timer.toc()
            self.__calculate_progress__()
            self.__index__ += 1
            self.__print_progress__()
            return self.__index__-1
        #self.__index__
        print()
        raise StopIteration
    def __print_progress__(self):
        len_char = int(self.col_len*self.__progress__)
        f="="*len_char
        e=" "*(self.col_len-len_char)
        E_time = str(self.timer)
        R_time = "%02i:%02i:%02i:%06.3f"%Timer.convert_sec_to_time(self.__time__remaining)
        
        if self.__tmp_len_char!=int(self.col_len*self.__progress__):
            #print(self.timer._deltas_[-1])
            print(f"\r({100*self.__progress__:6.2f}%)[{f}{e}] [Et:{E_time}][Rt:{R_time}]",end="")
            #self.__tmp_len_char=int(self.col_len*self.__progress__)
                     
class File:
    def __init__(self,filename="",mode="r"):
        self.filename = filename
        self.mode = mode
        self.__db__ = []
        self.__replaced__=[]
        self.search_index = {}
        self.force_read = False
        self.__process_functions__=[]
        self.processed =[]
        
    def read(self,filename=None,force_read=False):
        if filename is not None:
            self.filename=filename
        if len(self)>0 and not self.force_read:
            return self
        with open(self.filename) as fid:
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
    
    def write(self,filename):
        with open(filename,"w") as fid:
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


class kwargs_handle:
    def __init__(self,instance,**kwd):
        pass



class os_cmd:
    def rmdir(dirctory:str=None): 
        try:
            return shutil.rmtree(dirctory)
        except:
            Warning(f"Failed to remove {dirctory}")
            return 1
        pass
    
    def mkdir(path:str=None):
        try:
            os.mkdir(path)
            return 0 
        except:
            Warning(f"Folder {path} is existed")
            return -123
        pass
    
    def chdir(path:str=None):
        try:
            os.chdir(path)
            return 0
        except:
            os.chdir(path)
            return 1
    
    cd=chdir
    
    def cpdir(src,dst):
        _,tail = os.path.split(src)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, tail))
        else:
            pass
    
    def cpfile(src,dst):
        _,tail = os.path.split(src)
        if os.path.isfile(src):
            shutil.copy(src, os_cmd.set_fullpath(dst, tail))
            return 0
        else:
            pass
        pass
    
    def cp(src,dst):
        _,tail = os.path.split(src)
        if os_cmd.isfile(src):
            os_cmd.cpfile(src, dst)
        elif os_cmd.isdir(src):
            os_cmd.cpdir(src, dst)
        elif tail.find("*")>=0:
            flist=glob.glob(src)
            #print(flist)
            for f in flist:
                os_cmd.cp(f,dst)
            pass
        else:
            print("Copying {} object is not supported")
        pass
    
    def isfile(path:str)->bool:
        return os.path.isfile(path)
        pass
    def isdir(path:str)->bool:
        return os.path.isdir(path)
        pass
    
    def path_type(path:str)->str:#["file","dir","link",None]:
        for case,fun in {"dir":os_cmd.isdir,"file":os_cmd.isfile}.items():
            if fun(path):
                return case
        return None
            
        pass
    #@property
    def set_fullpath(dirctory,file,*r)->str:
        return os.path.join(dirctory, file,*r)
    
    def pwd()->str:
        return os.getcwd()
    
    def execute(command:str=None,wkdir:str=None)->int:
        previous_dirctory=os_cmd.pwd()
        os_cmd.cd(wkdir)
        status= os.system(command)
        os_cmd.cd(previous_dirctory)
        return status
    
if __name__=="__main__":
    A=[]
    for i in progress_bar(name="omari", start=500, end=1000):
        A.append(i)
        time.sleep(.001)
        pass
    
    f=File("LICENSE").read()
    
    def fun(self):
        for ky,line in self.search_index.items():
            for l in line:
                print(f"{ky}|{self[l]}")
        return self
    def fun2(self):
        print("*"*80)
        
    f.add_processing_func(fun,fun2)
    
    f.search("is","of")
    
    f.process()