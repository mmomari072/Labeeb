# -*- coding: utf-8 -*-
"""
Created on Tue Nov 28 11:47:15 2023

@author: mohammed.omari
"""
from Case import Case,Flags,flag,File,progress_bar,os_cmd
import pandas as pd
import numpy as np
import os

import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

class coupler:
    def __init__(self,**kwd):
        self.name:str =None
        self.description:str=None 
        self.database:None =None
        
        self.__cases=[]
        self.__coupling_functions=[]
        
        self.__main_dir__ = os.getcwd()
        self.run_case_main_dir = "coupling_omari_test"
        self.run_case_sub_dir="coupling_iteration"
        
        self.objects_to_be_copied=[]
        self.current_case_dir = None
        
        self.new = True
        self.run_type = "new"
        
        self.c_step:int=None
        
    def __kwargs_hanlder(self,**kwd):
        for item,val in kwd.items():
            if item in self.__dict__:
                self.__setattr__(item, val)
            elif item.lower() in ["root_dir","main_dir"]:
                self.__main_dir__ =val
            else:
                print(f"{item} is not supported")
    def add_cases(self,*cases:Case):
        for c in cases:
            if c not in self.__cases:
                self.__cases.append(c)
                pass
            else:
                print(f"same case [{c}] has been entered before!")
        return self
    
    def add_coupling_functions(self,*funs):
        for f in funs:
            print("add function")
            if f not in self.__coupling_functions:
                self.__coupling_functions.append(f)
                pass
            pass
        return self
    
    def __execute_coupling_functions__(self,**kwd):
        #print(self.__coupling_functions)
        return [f(self,**kwd) for f in self.__coupling_functions]
    
    def launch(self,**kw):
        """
        TO BE ADDED
        """
        self.initialization()
        #self.__output__att()
        ProgBar=progress_bar(name=self.name, start=0,end=len(self.database))
        for i in ProgBar:
            if self.__shall_stop():
                print("Luncher has been stoped by user")
                break
            # -----------------------------------------------------------------
            self.c_step=i
            if i>20:
                continue
            self.launch_case(**kw)
            #print(ProgBar.timer)  
        return self
    
    def create_case_main_dir(self):
        return self.initialization()
    
    def initialization(self):
        cases_root_path= os_cmd.set_fullpath(self.__main_dir__, self.run_case_main_dir)
        if self.run_type!="new":
            self.new = False
        else:
            self.new = True
            os_cmd.rmdir(cases_root_path)
        os_cmd.mkdir(cases_root_path)
        return self
    
    
    def launch_case(self,c_step:int=None,**kw):
        if c_step is not None:
            self.c_step=c_step

        i=self.c_step
        
        # -----------------------------------------------------------------
        # set/create current working directory 
        self.current_case_dir = os_cmd.set_fullpath(#os.path.join(
            self.__main_dir__, self.run_case_main_dir,
            f"{self.run_case_sub_dir}_{self.c_step}")
        #print(i,"flagsmap:",flagsmap)
        
        for case in self.__cases:
            case.set_vars(root_dir=self.current_case_dir)
            case.update_db()
            case.launch()
        
        return self
    
    def __shall_stop(self):
        return False

    
    def set_vars(self,**kwd):
        self.__kwargs_hanlder(**kwd)
        return self
    
    def update_db(self):
        pass

if __name__=="__main__":

    df=pd.DataFrame(data=dict(RHO=np.random.uniform(18,20,2),
                              WF=np.random.uniform(0.005,0.050,2)))
    
    A=Case("mcnp")
    df.to_excel("omari_mcnp.xlsx","data",engine="xlsxwriter")
    A.import_database(filename="omari_mcnp.xlsx",sheetname="data")
    F = Flags().add_flag(flag("#RHO@@#","RHO","%5.2f"),
                         flag("#@wf@#","WF","%10s"),
        
        )
    A.FlagsMap=F
    f = File(file_path="./dummy_functions/input_file_2.py").set_args(fname_is_path=0).read()
    A.add_file(f)
    #A.__main_dir__ = "/home/omari/Desktop/labeeb_test"
    A.exe_cmd =["python ./input_file_2.py>log"]
    #A.objects_to_be_copied=["README.md","test"]
    A.run_type = "new"
    A.run_case_main_dir="mcnp"
    A.output_files={}
    
    B=Case("relap")
    df=pd.DataFrame(data=dict(RHO=np.random.uniform(18,20,2),
                              WF=np.random.uniform(0.005,0.050,2)))
    
    df.to_excel("omari_relap.xlsx","data",engine="xlsxwriter")
    B.import_database(sheetname="data",filename="omari_relap.xlsx")
    F2 = Flags().add_flag(flag("#RHO@@#","RHO","%5.2f"),
                         flag("#@wf@#","WF","%10s"),
        
        )
    B.FlagsMap=F2
    f1 = File(file_path="./dummy_functions/input_file_3.py").set_args(fname_is_path=0).read()
    B.add_file(f1)
    #A.__main_dir__ = "/home/omari/Desktop/labeeb_test"
    B.exe_cmd =["python ./input_file_3.py>log"]
    #B.objects_to_be_copied=["README.md","test"]
    B.run_type = "new"
    B.run_case_main_dir="relap"
    B.output_files={}
    
    C=Case("Mccard")
    df=pd.DataFrame(data=dict(RHO=np.random.uniform(18,20,2),
                              WF=np.random.uniform(0.005,0.050,2)))
    F2 = Flags().add_flag(flag("#RHO@@#","RHO","%5.2f"),
                          flag("#@wf@#","WF","%10s"),
        
        )
    C.FlagsMap=F2
    f2 = File(file_path="README.md").set_args(fname_is_path=0).read()
    C.add_file(f2)
    C.import_database(sheetname="data",filename="omari_relap.xlsx")
    #A.__main_dir__ = "/home/omari/Desktop/labeeb_test"
    C.exe_cmd =["echo McCARD>>log2"]
    #B.objects_to_be_copied=["README.md","test"]
    C.run_type = "new"
    C.run_case_main_dir="mccard"
    C.output_files={}
    
    def fun1(self,*k):
        print("fun1",self.title)
        self.name="omari"
    
    def fun2(self,*k):
        print("fun2",self.title)
    
    c=coupler(name="omari",database="None")
    #c.add_coupling_functions(fun1,fun2)
    
    c.add_cases(A,B)
    
    df=pd.DataFrame(data=dict(RHO=np.random.uniform(18,20,3),
                              WF=np.random.uniform(0.005,0.050,3)))
    
    df.to_excel("omari_coupling.xlsx","data",engine="xlsxwriter")
    c.database=df
    c.run_case_main_dir ="mcnp_relap_c"
    
    d=coupler()
    
    d.database=df
    d.add_cases(c,C)
    
    d.launch()
    
    