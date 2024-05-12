# -*- coding: utf-8 -*-
"""
Created on Sat Nov 18 23:06:03 2023

@author: mohammed.omari
"""

import pandas as pd
from copy import deepcopy
import os,shutil,subprocess
import time
from aux_functions import progress_bar,File,os_cmd,Timer
import numpy as np
from database import database, attribute



Warning=print
# *****************************************************************************
"""

"""
# *****************************************************************************

class flag:
    """
    This class is amined to define linkage flag for search and replace 

    """
    def __init__(self,name,attribute,Format=None,**kwd):
        self.name=name
        self.attribute=attribute
        self.format = Format
        self.value = None
        pass
    def __call__(self,val):
        self.set_value(val)
        if self.value is None:
            self.value = "BINGO-->>>NEED TO MODIFY THE CODE"
        return self.format%self.value if self.format is not None else self.value
    def set_value(self,val):
        self.value=val
        return self
    def reset(self):
        self.value=None
        return self
    def get_value(self):
        if self.value is None:
            return None
        #print("BINGO>>>>>>>>",self.value,self.name,self.attribute)
        return self.format%self.value if self.format is not None else self.value
    def __kwargs_hanlder(self,**kwd):
        for item,val in kwd.items():
            if item in self.__dict__:
                self.__setattr__(item, val)
            pass
        


class Flags:
    """
    This class process set of flags class 

    """
    def __init__(self):
        self.__flags__={}
    def add_flag(self,*flags):
        for f in flags:
            if not isinstance(f, flag):
                Warning("Bad Flag")
                return self
            self.__flags__[f.name]=f
        return self
    def __setitem__(self,item,val):
        if item!=val.name:
            Warning("Bad flag name:class")
        self.__flags__[item]=val
    
    def __len__(self):
        return len(self.__flags__)
    
    def __getitem__(self,item):
        return self.__flags__[item]
    
    def __iter__(self):
        self.current_index = 0
        self.__ks = list(self.__flags__.keys())
        return self
    def __next__(self):
        if self.current_index < len(self):
            self.current_index += 1
            return self[self.__ks[self.current_index-1]]
        del self.current_index,self.__ks
        raise StopIteration        
    def set_values_from_attriutes(self,att_vals):
        for att,val in att_vals.items():
            for f,f_class in self.__flags__.items():
                if f_class.attribute == att:
                    f_class.set_value(val)
                    break
        return self
    def get_flags_values(self,att_vals=None):
        if att_vals is not None:
            self.set_values_from_attriutes(att_vals)
        return {f:f_class.get_value() for f,f_class in self.__flags__.items()}
    def __kwargs_hanlder(self,**kwd):
        for item,val in kwd.items():
            if item in self.__dict__:
                self.__setattr__(item, val)
            pass
class Case:
    """
    This class is for define the multi-run case infromation. it needs at least
    proiding it the database of the sampling, the flags map, the input files te
    """
    def __init__(self,name="",
                 output_files=[],**kwd):
        self.name = name
        self.database = None
        #self.attributes = None
        self.FlagsMap= {}
        self.exe_cmd=[]
        #self.input=None
        self.input_files = []
        
        self.__main_dir__ = os.getcwd()
        self.run_case_main_dir = "omari"
        self.run_case_sub_dir="case"
        self.current_case_dir = None
        
        self.objects_to_be_copied=[]
        
        self.new = True
        self.run_type = "read_only"
        
        self.output_files ={"omari.csv":["Time","Pu239"]}
        self.outputs={}
        self.__output__att()
        
        self.__kwargs_hanlder(**kwd)
        
    def import_database(self,filename="omari.xlsx",sheetname="omari"):
        self.database = pd.read_excel(filename,sheet_name=sheetname)
        self.attributes = list(self.database.columns)
        return self
    
    def __output__att(self):
        """
        this function for internal use only!
        it aims to parsing the self.out_files
        to be modified in the future.
        """
        for _,val in self.output_files.items():
            for att in val:
                self.outputs[att]=[]
        self.outputs_db=pd.DataFrame()
        return self
    
    def import_FlagsMap(self,
                        filename="omari.xlsx",
                        sheetname="omari"):
        """
        import flag map from excel file.
        
        Remark: Csv and json files will be supported in future
        
        """
        tmp = pd.read_excel(filename,sheet_name=sheetname)

        self.FlagsMap = {flag:att for flag,att in zip(
            tmp["flag"],tmp["attribute"])}
        return self
    
    def add_file(self,*file:File()):
        for f in file:
            if not isinstance(file,File):
                #Warning("Bad entry",type(file),type(File))
                #return self
                pass
            if f not in self.input_files:
                self.input_files.append(f.read())
                print(f"file {f.fname} has been added to [{self.name}]",len(self.input_files))
            else:
                print("duplicate file!")
        return self
    
    def launch_case(self,case_id:int=None,**kw):
        T = Timer()
        T.tic()
        if case_id is not None:
            self.case_id=case_id

        i=self.case_id
        
        # -----------------------------------------------------------------
        # set/create current working directory 
        self.current_case_dir = os_cmd.set_fullpath(#os.path.join(
            self.__main_dir__, self.run_case_main_dir,
            f"{self.run_case_sub_dir}_{self.case_id}")
        #print(i,"flagsmap:",flagsmap)
        
        # -----------------------------------------------------------------
        # create case subdirectory 
        if self.new:
            # -------------------------------------------------------------
            # Make case subdirectory
            os_cmd.mkdir(self.current_case_dir)
            
            # -------------------------------------------------------------
            # copy objects (files/folders) to the case subdirecory
            for f in self.objects_to_be_copied:
                os_cmd.cp(f,self.current_case_dir)
           
            # --------------------------------------------------------------
            # get_data_from database
            rw ={att:val for att,val in self.database.iloc[i].items()}
            flagsmap = self.FlagsMap.get_flags_values(rw)
            
            # -------------------------------------------------------------
            # write input files in the case subdirecory
            self.__write_input__(flagsmap)
        
            #execute commands
            stat=self.__execute__()
            for s in stat:
                if stat!=0:
                    #raise "Error"
                    pass
            #print(stat)
        
        # read output_files
        self.__read_outputs__()
        
        # execute post execution fucntions
        self.__execute_post_execution_functions__()
        
        T.toc()

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
    
    def launch(self,**kw):
        """
        TO BE ADDED
        """
        self.initialization()
        self.__output__att()
        # try:
        #     nrow,ncol=self.database.size(
        #     )
        # except:
        #     nrow = len(self.database)
        nrow = len(self.database)    
        ProgBar=progress_bar(name=self.name, start=0,end=nrow)
        for i in ProgBar:
            if self.__shall_stop():
                print("Luncher has been stoped by user")
                break
            # -----------------------------------------------------------------
            self.case_id=i    
            self.launch_case(**kw)
            #print(ProgBar.timer)  
        return self
    
    def __shall_stop(self):
        return os_cmd.isfile(os_cmd.set_fullpath(self.__main_dir__,self.run_case_main_dir,"STOP_ALL"))    
    
    def __execute__(self):
        self.__cd__(self.current_case_dir)
        A=[]
        try: 
            A= [os.system(x) for x in self.exe_cmd]
        except:
            pass
        self.__cd__(self.__main_dir__)
        return A
        
        # if isinstance(self.exe_cmd, (tuple,list)):
        #     for cmd in self.exe_cmd:
        #         #print(cmd)
        #         p=subprocess.Popen([cmd],shell=True,cwd=self.current_case_dir,
        #                            )
        #         p.wait()
        #         while p.stdout.readable():
        #             line = p.stdout.readline()
                
        #             if not line:
        #                 break
                
        #             print(line.strip())
        #         #p.errors()
        # elif isinstance(self.exe_cmd, (str,)):
        #     p=subprocess.Popen([self.exe_cmd],shell=True,cwd=self.current_case_dir)
        #     p.wait()

        # return #os.system(self.exe_cmd)

    
    def __cd__(self,Dir):
        os.chdir(Dir)
        return self
    
    def __write_input__(self,flagsmap):
        for f in self.input_files:
            f.replace(flagsmap)
            #print(os.path.join(case_path, f.filename))
            fname=f.filename
            #file_path=os_cmd.set_fullpath(self.current_case_dir, fname)
            f.write(os.path.join(self.current_case_dir, fname))
        return self
    
    def __read_outputs__(self):
        for fname,cols in self.output_files.items():
            fullname=os.path.join(self.current_case_dir, fname)
            df = pd.read_csv(fullname, usecols = cols, low_memory = True)
            pass
            for c in cols: 
                self.outputs[c].append(df[c])
                #self.outputs_db[c][self.case_id]=df[c]
        return self
        
    def __execute_post_execution_functions__(self):
        pass
        
    def __kwargs_hanlder(self,**kwd):
        for item,val in kwd.items():
            if item in self.__dict__:
                self.__setattr__(item, val)
            elif item.lower() in ["root_dir","main_dir"]:
                self.__main_dir__ =val
            else:
                print(f"{item} is not supported")
    
    def set_vars(self,**kwd):
        self.__kwargs_hanlder(**kwd)
        return self
    
    def update_db(self,**kwd):
        print("this is dummpy function [updating database] :",self.name)
                        
        


if __name__=="__main__":
    #from matplotlib import pyplot as plt
  
    
    A=Case()
    N=100
    if 0:
        df=pd.DataFrame(data=dict(RHO=np.random.uniform(18,20,N),
                                  WF=np.random.uniform(0.005,0.050,N)))
        # df.to_excel("omari.xlsx","data",engine="xlsxwriter")
        # A.import_database(sheetname="data")
    else:
        data = dict(RHO=list(np.random.uniform(18,20,N)),
                              WF=list(np.random.uniform(0.005,0.050,N)))
        df=database(data=dict(RHO=list(np.random.uniform(18,20,N)),
                              WF=list(np.random.uniform(0.005,0.050,N))))
    F = Flags().add_flag(flag("#RHO@@#","RHO","%5.2f"),
                         flag("#@wf@#","WF","%10s"),
        
        )
    A.database=df
    A.FlagsMap=F
    f = File(file_path="./dummy_functions/input_file_2.py").set_args(fname_is_path=0).read()
    A.add_file(f)
    #A.__main_dir__ = "/home/omari/Desktop/labeeb_test"
    A.exe_cmd =["python ./input_file_2.py>log"]
    A.objects_to_be_copied=["README.md","test"]
    A.run_type = "new"
    A.run_case_main_dir="pu_simulator_sa"
    A.output_files={}
    A.launch()
    print(F.get_flags_values(dict(RHO=123)))
    
    df.iloc[0]
    # X=[]
    # df2=pd.DataFrame(A.outputs)
    # for i in range(len(A.database)):
    #     X.append([x for x in df2["Pu239"][i]][-1])
    
    # plt.plot(A.database.WF,np.array(X)*239/6.023e23*4907*180/1000,"X")
