#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun May  5 22:43:29 2024

@author: omari
"""
import os,shutil,subprocess,glob

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
            return 0
        elif os_cmd.isdir(src):
            os_cmd.cpdir(src, dst)
            return 0
        elif tail.find("*")>=0:
            flist=glob.glob(src)
            #print(flist)
            for f in flist:
                os_cmd.cp(f,dst)
            return 0
        else:
            print(f"Copying {src} object is not supported",os_cmd.path_type(src))
            return 1
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
    pass