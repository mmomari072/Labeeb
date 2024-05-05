#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun May  5 22:42:43 2024

@author: omari
"""

import time


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