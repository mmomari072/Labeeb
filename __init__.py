# -*- coding: utf-8 -*-
"""
Created on Tue Nov 28 11:47:37 2023

@author: mohammed.omari

"""
Labeel_Version="0.1"
""" 
Created on Tue Nov 28 11:47:37 2023

@author: mohammed.omari

This is labeeb package, which was made to facitliate the sensitivity analysis studies as well
as coupling codes. the code has serveral subpackages, which are needed for the studies

Packages:
    Sampler:
        Help to construct the sampling matrix and it contains the following capabilites:
        - FOAT_Constructer (One-at-Time samping method):
            you can provide the contructer with list of samples and it can produce the fuel 
            matrix
        - Discreate_Sampling: 
            it is random object generator in which you provide the class with the objcets and 
            corresponding weighting factors
    
    Case:
        this is the main core of the package, which select from sampling matrix and construct the case,
        execute commands, read output and then analysis the output
        
    Coupler:
        it aims to utilze the Case package to couple codes 
        NOT developed yet
        
    """

from . import Case,Sampler
from .aux_functions import File

print("*"*80)
print("""  _           _               _     
 | |         | |             | |    
 | |     __ _| |__   ___  ___| |__  
 | |    / _` | '_ \ / _ \/ _ \ '_ \ 
 | |___| (_| | |_) |  __/  __/ |_) |
 |______\__,_|_.__/ \___|\___|_.__/
""")
print(f"""----------------------------------------------------
CREATED BY: Eng. Mohammad OMARI    
INSTITUTE : Jordan Research and Training Reactor
VERSION   : {Labeel_Version}
DATE      : {'Tue Nov 28 11:47:37 2023'}
""")
print("*"*80)

            
