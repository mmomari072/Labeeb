#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu May  2 14:15:15 2024

@author: omari
"""
import random
import csv,json,pickle

class str2num:
    def __init__(self,x,type=float):
        self.x=x
        self.type=type
        pass
    def convert(self):
        try:
            return self.type(self.x)
        except:
            if self.x=='':
                return None
            return self.x
        
class _list(list):
    def __init__(self, name, description: str = None, Type=None, unit=None, data=[]):
        super().__init__()


class attribute(list):
    def __init__(self, name, description: str = None, Type=float, unit=None, data=[]):
        super().__init__()
        self.name: str = name
        self.description = description
        self.type = Type
        self.unit = unit
        self.__fun_list = []
        self.__append(data)
        self.__non_entered_value__ = None

    def __operation__failure_check(self, x, operator: str):
        if not isinstance(x, (attribute, list, tuple)):
            raise ValueError("")
        elif len(x) != len(self):
            raise ValueError("")
        else:
            raise ("Unknow Error")

    def __append(self, data):
        [self.append(x) for x in data]

    def __call__(self):
        return "Not Now!!!"

    def __operation__(self, x, op, is_right=False):
        fun = eval(f"lambda x,y:x {op} y")
        if op in ["/", "//"]:
            def fun(x, y):
                try:
                    f = eval(f"lambda x,y:x {op} y")
                    return f(x, y)
                except:
                    return (float("nan") if x == 0 else (float("inf") if x > 0 else float("-inf")))
        _type = self.type if op not in [
            "&", "|", ">", ">=", "<", "<=", "==", "!="] else bool
        if isinstance(x, (int, float)) or x is None:
            xname = str(x)
            name = f"({self.name} {op} {xname})" if not is_right else f"({xname} {op} {self.name})"
            return attribute(name=name, data=[fun(xx, x) for xx in self], Type=_type)
        elif isinstance(x, (attribute, list, tuple)) and len(x) == len(self):
            xname = x.name if isinstance(x, (attribute)) else "X"
            name = f"({self.name} {op} {xname})" if not is_right else f"({xname} {op} {self.name})"
            return attribute(name=name, data=map(fun, self, x),
                             # [fun(xx,yy) for xx,yy in zip(self,x)],
                             Type=_type)
        self.__operation__failure_check(x, "+")

    # *************************************************************************
    #
    #
    #
    # *************************************************************************
    # left hand side operation
    # *************************************************************************

    def __add__(self, x):
        return self.__operation__(x, "+")

    def __sub__(self, x):
        return self.__operation__(x, "-")

    def __mul__(self, x):
        return self.__operation__(x, "*")

    def __truediv__(self, x):
        return self.__operation__(x, "/")

    def __mod__(self, x):
        return self.__operation__(x, "%")

    def __pow__(self, x):
        return self.__operation__(x, "**")

    def __xor__(self, x):
        print("xor")
        return self.__operation__(x, "+")

    def __and__(self, x)->bool:
        """
        test.
        ss.
        """
        print("and")
        return self.__operation__(x, "and")

    def __or__(self, x):
        print("or")
        return self.__operation__(x, "or")

    # *************************************************************************
    # right handside operation
    # *************************************************************************
    def __radd__(self, x):
        return self.__operation__(x, "+", is_right=True)

    def __rsub__(self, x):
        return self.__operation__(x, "-", is_right=True)

    def __rmul__(self, x):
        return self.__operation__(x, "*", is_right=True)

    def __rtruediv__(self, x):
        return self.__operation__(x, "/", is_right=True)

    def __rmod__(self, x):
        return self.__operation__(x, "%", is_right=True)

    def __rpow__(self, x):
        return self.__operation__(x, "**", is_right=True)

    def __rxor__(self, x):
        return self.__operation__(x, "^", is_right=True)

    __iadd__ = __add__
    __isub__ = __sub__
    __imul__ = __mul__
    __itruediv__ = __truediv__
    __imod__ = __mod__
    __ipow__ = __pow__

    def __ixor__(self, x):
        return self.__operation__(x, "^", is_right=True)

    # *************************************************************************
    # comparison operation
    # *************************************************************************

    def __eq__(self, x):
        return self.__operation__(x, "==")

    def __ne__(self, x):
        return self.__operation__(x, "!=")

    def __lt__(self, x):
        return self.__operation__(x, "<")

    def __le__(self, x):
        return self.__operation__(x, "<=")

    def __gt__(self, x):
        return self.__operation__(x, ">")

    def __ge__(self, x):
        return self.__operation__(x, ">=")

    def __getitem__(self, i):
        if type(i) is attribute:
            if i.type is bool:
                return attribute(name=self.name, data=[self[j] for j, k in enumerate(i) if k])
            return attribute(name=self.name, data=[self[j] for j in i])

        if isinstance(i, (int, slice)):
            return super().__getitem__(i)
        if isinstance(i, (list, tuple)):
            return attribute(name=self.name, data=[self[j] for j in i])

    def __setattr__(self, name, value):
        if name.lower() in ["unit0"]:
            return
        super().__setattr__(name, value)

    def __dir__(self):
        return [x for x in super().__dir__() if x.find("__") < 0]

    def __setitem__(self, i, val):
        if self.type is not None:
            value = str2num(val,self.type).convert()
        else:
            value=val
        try:
            super().__setitem__(i, value)
        except:
           # print(type(i),type(value))
            if isinstance(i, int):
                if 0 <= i:
                    for j in range(len(self), i):
                        self.append(self.__non_entered_value__)
                    else:
                        self.append(value)
                elif 0 > i:
                    raise print("negative index has not been develped yet")
                # super().__setitem__(i, value)
            elif isinstance(i, (tuple, set, list)):
                if isinstance(value, (tuple, list, set)):
                    if len(value) == len(i):
                        for ii, vv in zip(i, value):
                            self[ii] = vv
                    else:
                        raise print("Error (bad sizes)")
                elif False:
                    pass
                else:
                    for ii in i:
                        self[ii] = value
            elif isinstance(i, slice):
                # print("slice has not been supported yet!",i)
                start = i.start if i.start is not None else 0
                stop = i.stop if i.stop is not None else len(self)
                step = i.step if i.step is not None else 1

                for ii in range(start, stop, step):
                    self[ii] = value

        return self

    # def __instancecheck__(self,val):
    #     print("Bingo test ",val)
    #     return "omar"

    def __bool__(self):
        # print("__bool__")
        return all(self)

    def add_functions(self, *fun):
        for f in fun:
            if f.__name__ in self.__dict__:
                continue
            self.__dict__[f.__name__] = f.__get__(self)
            self.__fun_list.append(f)
        return self

    def resize(self, newlength: int):
        if len(self) < newlength:
            self[newlength-1] = self.__non_entered_value__
        elif len(self) > newlength:
            [self.pop() for i in range(newlength, len(self))]
        return self

    def sum(self):
        return sum(self)

    def mean(self):
        return self.sum()/len(self)

    def filter(self, function=lambda x: x > 1, return_index=False):
        x = attribute(name="", data=map(function, self))
        if not return_index:
            return x
        return [i for i, x in enumerate(x) if x]

    def __repr__(self):
        return f"""
    NAME:{self.name}
    UNIT:{self.unit}
    TYPE:{self.type}
    LEN :{len(self)}
    VALU:{self[:]}
    """


class database(dict):
    class __get:
        def __init__(self, upper_cls):
            self.object = upper_cls
            pass

        def show(self):
            return self.object.__dict__

        def __getitem__(self, i):
            return self.object.get_data(row=i)

        def row(self, row_id):
            return self.object.get_row(row_id)

        def column(self, column_id):
            return self.object.get_column(column=column_id)

        def __dir__(self):
            return ["col", "row"]

    def __init__(self, name: str = None, description: str = None, data: dict = {}):
        self.name: str = name
        self.description: str = None
        self.db_filepath = "./omari.pkl"

        
        self.get=self.__get(self)
        
        for ky,val in data.items():
            self.auto_refersh = False
            self[ky]=attribute(name=ky,data=val)
        
        self.auto_refersh = True
    
        self["__db_index__"] = attribute("__db_index__", 
                                         data=[i for i in range(self.size()[0])],
                                         Type=int)

        pass

    def add_attribute(self, *att: attribute):
        for a in att:
            if isinstance(a, (attribute)) and type(a) is attribute:
                self[a.name] = a
                #print(a)

    def __setitem__(self, name, value):
        if type(value) is not attribute or not isinstance(value,(list,tuple)):
            if len(self.keys())!=0:
                print(self.keys())
                raise print("Error")
        super().__setitem__(name, value)  # self[name]=value
        # db_len=[len(att) for _,att in self.items()]
        if self.auto_refersh:
            self.refresh_index()
        

    def refresh_index(self):
        #print(super().items(),self.items())
        db_len = [len(att) for _, att in super().items()]
        #print(db_len)
        db_max_len = max(db_len)

        if len(self["__db_index__"]) == db_max_len:
            return self
        if len(self["__db_index__"]) < db_max_len:
            for i in range(len(self["__db_index__"]), db_max_len):
                self["__db_index__"].append(i)
            for a, v in self.items():
                v.resize(db_max_len)
            return self
        if len(self["__db_index__"]) >= db_max_len:
            for a, v in self.items():
                v.resize(db_max_len)
            return self

    def __getitem__(self, name):
        try:
            return super().__getitem__(name)
        except:
            # print(name)
            # if name in self:
            #     return self[name]
            # else:
            #     raise print("Error 000")
            pass

        return

    def __getattr__(self, name):
        #print(name)
        if name in self.keys():
            return self[name]
        mdname = name.lower()
        if mdname in ["columns"]:
            return self.columns()
        if mdname in ["iloc", "irow"]:
            return self.get
        if mdname in ["index"]:
            return self["__db_index__"]
        else:
            return f"{name}->crap"

    def columns(self):
        return attribute("columns", data=list(self.keys()))

    def get_data(self, row: int = None, column: str = None):
        if isinstance(column, str):
            return self[column][row]
        elif isinstance(column, (list, tuple, set)):
            d = {}
            for c in column:
                d[c] = self.get_data(row, c)
            return d
        elif column is None:
            return self.get_data(row, self.columns())

    def get_row(self, row:[int,list,tuple]=[]):
        if isinstance(row,(list,tuple)):
            return database(name="",data={att: val[row] for att, val in self.items()})
        elif isinstance(row, int):
            return {att: val[row] for att, val in self.items()}

    def get_column(self, col_id: str):
        return self[col_id]

    def __dir__(self):
        return list(self.keys())+["iloc", "cols", "rows"]+list(self.__dict__)

    def __setattr__(self, name, value):
        if name == "get" and type(value) is not self.__get:
            raise print("error")
        super().__setattr__(name, value)

    def import_from_file(self, filename="omari_labeel.csv",clear=True,append=False,columns:list=[]):
        if clear:
            self.clear()
        with open(filename,"r") as fid:
            csv_r=csv.DictReader(fid)
            if append:
                self.refresh_index()
                i,_=self.size() 
            else:
                i=0
            for c in csv_r:
                tmp=c
                if len(columns)!=0:
                    #tmp={}
                    # for cc in columns:
                    #     tmp[cc]=c[cc]
                    pass
                
                self.update_row(row_id=i,data=tmp)
                i+=1
        return self
        
        
        
        pass

    def export_to_file(self, filename="omari_labeel.csv"):
        
        self.refresh_index()
        header = [ x for x in self.keys() if x!="__db_index__"] ;header.sort()
        header = ["__db_index__"]+header
        irow,c = self.size()
        with open(filename,"w",newline="") as fid:
            #print(",".join(header),end=",\n",file=fid)
            writer= csv.DictWriter(fid, fieldnames=header)
            writer.writeheader()
            #writer.writerow()
            for i in range(irow):
                #print(i)
                writer.writerow(self.get_row(i))
                #line =",".join([str(tmp[x]) for x in header])
                #print(line,end=",\n",file=fid)
        return self
                
            

    def save(self):
        with open(self.db_filepath, "wb") as fid:
            pickle.dump(self, fid)
        return self

    def __pickle__(self):
        print(" mmm")

    def print(self):
        print(self.__data)
        
    def __call__(self):
        print("see")
    
    def __getstate__(self):
        print("I'm being pickled")
        #self.val *= 2
        return self.__dict__
    def __setstate__(self,d
                     ):
        #d=1
        #print("I'm being unpickled with these values: ",type(d),)
        self.__dict__ = d
        #self.val *= 3
    
    def load(self,filemame):
        from copy import deepcopy
        with open(filemame,"rb") as fid:
            a= pickle.load(fid)
            self.__dict__=a.__dict__
            #print("*"*80,a,"*"*80)
            for i,v in a.items():
                self[i]=v
    def update_row(self,row_id=0,data={},add_new=True):
        for c,v in data.items():
            try:
                self[c][row_id]=v
            except:
                if c not in self and add_new:
                    self[c]=attribute(c,data=[v])
                else:
                    return 
                    raise "Mush 3arf shoo badi a76"
        return self
    
    def show_table(self):
        for i in range(5):
            print(db.get.row(i))
        pass
    
    def size(self):
        db_len = [len(att) for _, att in super().items()]
        #print(db_len)
        db_max_len = max(db_len) if len(db_len) !=0 else 0
        return db_max_len,len(self.keys())
    def append(self,data:dict={}):
        for k,v in data.items():
            self[k].append(v)
        self.refresh_index()
        return self
    def clear(self,attr:list[str]=[]):
        if len(attr)==0 or attr is None:
            attr_list=self.keys()
        else:
            attr_list=attr
        for a in attr_list:
            self[a].clear()
        return self
    def __len__(self):
        db_len = [len(att) for _, att in super().items()]
        #print(db_len)
        db_max_len = max(db_len) if len(db_len) !=0 else 0
        return db_max_len

if __name__=="__main__":
    A = attribute("test", data=[1, 2, 3, 4, 1, 2, 3, 2, 1, 5, 7])
    
    db = database(name="ssss")
    
    db.add_attribute(A, attribute("saja", data=range(22)))
    db.auto_refersh=True
    
    c=database()
