from __future__ import print_function
"""machine.py – a bytecode interpreter to experiment with RPython

This code was part of an attempt to wrap my head around the RPython tool chain. This
code takes as input something resembling assembly language (see mandelbrot.mach as
an example), compiles it to byte code and then executes it. If run on the standard
CPython interpreter, it is quite slow. Performance with PyPy is much better. If this
program is translated with RPython --jit, performance is much, much better. 

This has only really been tested by running mandelbrot.mach, so it probably has a bunch of
buggy edge cases that haven't been exercised. To run mandelbrot.mach using python, for
example, use:
    $ python machine.py mandelbrot.mach
However, be prepared to wait a long time in this case. The commands used to translate the
code using RPython are given below.

The code below would make more sense broken into several files, but I've kept it as one
for ease of download, etc. The sections are:
    * Syntax Tree 
    * Parser and Compiler
    * Operators
    * Main Loop
    * Launching Code / RPython Stuff

 The second section is not very relevant to the RPython aspect of the code, but the first
 section will tell you something about how I had to set up the data structures to make this
 work with RPython. The critical restriction is that a variable may only hold a single 
 type at a given location in the code. This leads to variable in the code getting boxed,
 so that objects, which can hold more than one type as values internally get passed around
 instead of the raw values.

Some useful links for writing an interpreter in PyPy. 
Start Here: http://morepypy.blogspot.com/2011/04/tutorial-writing-interpreter-with-pypy.html
More Info on RPython: http://rpython.readthedocs.org/en/improve-docs/rpython.html
Helpful hints on optimization and such: https://bitly.com/bundles/cfbolz/

These are the commands that I used to translate this. You would likely need to adjust 
the paths. The jit option can be skipped; translation is faster, but performance suffers.
export PYPY_LOCALBASE=~/Code/PyPy/pypy-2.3.1-src
pypy-2.3.1-osx64/bin/pypy pypy-2.3.1-src/rpython/bin/rpython --opt=jit machine.py 

"""
import os
import sys
import math
sys.path.append("~/Code/PyPy/pypy-2.3.1-src")
from rpython.rlib.jit import JitDriver, purefunction, hint

stdin_fd = sys.stdin.fileno()
stdout_fd = sys.stdout.fileno()
stderr_fd =  sys.stderr.fileno()


#-------- Syntax Tree --------

class MValue(object):
    _immutable_fields_ = ["value"]
    def as_text(self):
        return "<VALUE>"    
        
class MSymbol(MValue):
    _immutable_fields_ = ["value"]
    def __init__(self, value):
        self.value = self.name = value
    def as_text(self):
        return self.value 
       
class MLineNo(MValue):
    _immutable_fields_ = ["value"]
    def __init__(self, value):
        self.value = int(value)
    def as_text(self):
        return str(self.value) 
       
class MCode(MValue):
    pass

class MLineNo(MCode):
    _immutable_fields_ = ["value"]
    def __init__(self, value):
        self.value = int(value)
    def as_text(self):
        return str(self.value) 

class MMemLoc(MCode):
    _immutable_fields_ = ["value"]
    def __init__(self, value):
        self.value = int(value)
    def as_text(self):
        return str(self.value) 

class MCmd(MCode):   
    _immutable_fields_ = ["value"]
    count = 0
    def __init__(self, name, size):
        self.name = name
        self.size = size
        self.value = self.count
        self.__class__.count += 1
    def as_text(self):
        return self.name 

class MOpLoc(MCode):
    _immutable_fields_ = ["value"]
    def __init__(self, value):
        self.value = int(value)
    def as_text(self):
        return str(self.value) 

class MLiteral(MValue):
    pass
          
class MString(MLiteral):
    _immutable_fields_ = ["value"]
    def __init__(self, value):
        self.value = value
    def as_text(self):
        return self.value    
          
class MInt(MLiteral):   
    _immutable_fields_ = ["value"]
    def __init__(self, value):
        self.value = int(value)
    def as_text(self):
        return str(self.value)   
                
class MFloat(MLiteral):
    _immutable_fields_ = ["value"]
    def __init__(self, value):
        self.value = float(value)  
    def as_text(self):
        return str(self.value)   

cmd_map = {
      "set":MCmd("set", 3),
      "exec_1" : MCmd("exec_1", 4),
      "exec_2": MCmd("exec_2", 5),
      "branchif": MCmd("branchif", 3),
      "jump": MCmd("jump", 2),
      "display": MCmd("display", 2),
      "end": MCmd("end", 1)
}

for k, v in cmd_map.items():
    globals()["C_" + k.upper()] = v.value


#-------- Parser and Compiler--------

def atomize(token):
    "Numbers become numbers; every other token is a symbol."
    try: 
        return MInt(int(token))
    except ValueError:
        pass
    try: 
        return MFloat(float(token))
    except ValueError:
        pass   
    n = len(token) - 2
    if n >= 0 and token.startswith('"') and token.endswith('"'):
        return MString(token[1:1+n])
    return MSymbol(token)

def split(text):
    raw_split = [x.strip() for x in text.split(' ')]
    return [x for x in raw_split if x]

def preparse(text):
    lines = []
    for l in text.split('\n'):
        l = l.strip()
        if not l or l.startswith('#'):
            continue
        lines.append([atomize(x) for x in split(l)])
    return lines

def extract_labels(lines):
    labels = {}
    program = []
    for x in lines:
        if x[0].name == 'label':
            labels[x[1].name] = len(program)
        elif x[0].name == 'exec':
            if len(x) == 4:
                program.append(MSymbol('exec_1'))
            elif len(x) == 5:
                program.append(MSymbol('exec_2'))
            else:
                raise ValueError('wrong number of args to exec')
            program.extend(x[1:])
        else:
            program.extend(x)
    return program, labels
    
def replace_labels(program, labels):
    pc = 0
    while pc < len(program):
        name = program[pc].name
        if name == 'branchif':
            program[pc+2] = MLineNo(labels[program[pc+2].name])
        elif name == "jump":
            program[pc+1] = MLineNo(labels[program[pc+1].name])
        size = cmd_map[name].size
        assert isinstance(size, int)
        pc += size

def intern_ops(program):
    pc = 0
    while pc < len(program):
        name = program[pc].name
        assert isinstance(name, str)
        cmd = cmd_map[name]
        program[pc] = cmd
        size = cmd.size
        assert isinstance(size, int)
        pc += cmd.size
    
def parse(text):
    lines = preparse(text)
    program, labels = extract_labels(lines)
    replace_labels(program, labels)
    intern_ops(program)
    return program

def attach_to_memory(program):
    # Note that this works on program in place, copy first
    OP_EXEC_1 = cmd_map['exec_1']
    OP_EXEC_2 = cmd_map['exec_2']
    pc = 0
    memory = []
    map = {}
    while pc < len(program):
        op = program[pc]
        n = op.size
        look_at = range(pc+1,  pc+n)
        if op in (OP_EXEC_1, OP_EXEC_2):
            i = look_at[1]
            del look_at[1]
            arg = program[i]
            assert isinstance(arg, MSymbol)
            if op is OP_EXEC_1:
                program[i] = MOpLoc(monop_map[arg.value])
            else:
                program[i] = MOpLoc(binop_map[arg.value])                
        for i in look_at:
            arg = program[i]
            if isinstance(arg, MSymbol):
                if arg.name not in map:
                    map[arg.name] = MMemLoc(len(memory))
                    memory.append(None)
                program[i] = map[arg.name]
            elif isinstance(arg, MLiteral):
                program[i] = MMemLoc(len(memory))
                memory.append(arg)
                pass
            else:
                assert isinstance(arg, MLineNo)
        pc += n
    return memory

def compile(program):
    program = program[:]
    mem = attach_to_memory(program)
    code = []
    for x in program:
        assert isinstance(x, MCode)
        code.append(x.value)
    return code, mem


#-------- Operators --------

def both_ints(a, b):
    return isinstance(a, MInt) and isinstance(b, MInt)

def int_value(x):
    if isinstance(x, MInt):
        return x.value
    if isinstance(x, MFloat):
        return int(x.value)
    raise RuntimeError("illegal value to int_value")
   
def float_value(x):
    if isinstance(x, MInt):
        return float(x.value)
    if isinstance(x, MFloat):
        return x.value
    raise RuntimeError("illegal value to int_value")
    

def o_lt(a, b):
    return MInt(int_value(a) < int_value(b)) if both_ints(a,b) else MInt(float_value(a) < float_value(b))

def o_ge(a, b):
    return MInt(int_value(a) >= int_value(b)) if both_ints(a,b) else MInt(float_value(a) >= float_value(b))

def o_gt(a, b):
    return MInt(int_value(a) > int_value(b)) if both_ints(a,b) else MInt(float_value(a) > float_value(b))

def o_sub(a, b):
    return MInt(int_value(a) - int_value(b)) if both_ints(a,b) else MFloat(float_value(a) - float_value(b))

def o_mul(a, b):
    return MInt(int_value(a) * int_value(b)) if both_ints(a,b) else MFloat(float_value(a) * float_value(b))

def o_add(a, b):
    return MInt(int_value(a) + int_value(b)) if both_ints(a,b) else MFloat(float_value(a) + float_value(b))

def o_div(a, b):
    return MInt(int_value(a) / int_value(b)) if both_ints(a,b) else MFloat(float_value(a) / float_value(b))

def o_hypot(a, b):
    return MFloat(math.hypot(float_value(a), float_value(b)))
            
def o_float(a):
    return MFloat(float_value(a))
    
def o_int(a):
    return MInt(int_value(a))
    

_monops = [('float', o_float), 
           ('int', o_int)]

monop_map = dict((x[0], i) for (i, x) in enumerate(_monops))
for k, v in monop_map.items():
    globals()["O_" + k.upper()] = v
    
_binops = [('lt', o_lt),
           ('ge'   , o_ge),   
           ('gt'   , o_gt),                                                 
           ('sub'  , o_sub),
           ('mul'  , o_mul),
           ('div'  , o_div),
           ('add'  , o_add),
           ('hypot', o_hypot)]
   
binop_map = dict((x[0], i) for (i, x) in enumerate(_binops))
for k, v in binop_map.items():
    globals()["O_" + k.upper()] = v
 
                      
# -------- Main Loop --------

@purefunction
def opcode(code, pc):
    return code[pc]
              
def execute(program):
    code, mem = compile(program)
    pc = 0
    try:
        while pc < len(program):
            jitdriver.jit_merge_point(pc=pc, mem=mem, code=code, program=program)
            op = opcode(code, pc)
            if op == C_SET:
                a = opcode(code, pc+1)
                b = opcode(code, pc+2)
                mem[a] = mem[b]
                pc += 3
            elif op == C_EXEC_1:
                symbol = opcode(code, pc+1)
                op = opcode(code, pc+2)
                a = mem[opcode(code, pc+3)]
                if op == O_FLOAT:
                    mem[symbol] = o_float(a)
                elif op == O_INT:
                    mem[symbol] = o_int(a)
                else:
                    raise ValueError("illegal unary op: %s" % op)
                pc += 4
            elif op == C_EXEC_2:
                symbol = opcode(code, pc+1)
                op = opcode(code, pc+2)
                a = mem[opcode(code, pc+3)]
                b = mem[opcode(code, pc+4)]
                if op == O_LT:
                    mem[symbol] = o_lt(a, b)
                elif op == O_GE:
                    mem[symbol] = o_ge(a, b)
                elif op == O_GT:
                    mem[symbol] = o_gt(a, b)
                elif op == O_SUB:
                    mem[symbol] = o_sub(a, b)
                elif op == O_MUL:
                    mem[symbol] = o_mul(a, b)
                elif op == O_DIV:
                    mem[symbol] = o_div(a, b)
                elif op == O_ADD:
                    mem[symbol] = o_add(a, b)
                elif op == O_HYPOT:
                    mem[symbol] = o_hypot(a, b)
                else:
                    raise ValueError("illegal binary op: %s" % op)
                pc += 5
            elif op == C_BRANCHIF:
                x = opcode(code, pc+1)
                loc = opcode(code, pc+2)
                if int_value(mem[x]): 
                    pc = loc
                else:
                    pc += 3
            elif op == C_JUMP:
                loc = opcode(code, pc+1)
                pc = loc
            elif op == C_DISPLAY:
                arg = opcode(code, pc+1)
                os.write(stdout_fd, '%s\n' % mem[arg].as_text())
                pc += 2
            elif op == C_END:    
                pc = len(code)
            else:
                raise ValueError("unknown command")#: %s(%s) after %s(%s)" % (op.as_text(), pc))       
        return 0
    except:
        os.write(stderr_fd, "ERROR at PC: %s\n" % pc)
        return 1
            

#-------- Launching Code / RPython Stuff

# For RPython, we use the default policy.
def jitpolicy(driver):
    from rpython.jit.codewriter.policy import JitPolicy
    return JitPolicy()
    
# This is for logging, which can be helpful for optimizing.
def get_location(pc, code, program):
    if pc < 0:
        return "<illegal PC>"
    cmd = program[pc]
    return " ".join([x.as_text() for x in program[pc:pc+cmd.size]])
        
    return "PC: %s" % pc

# This tells RPython what stays constant in the main loop (pc, code, program) and what is 
# expected to change (mem). These are mapped to the actual variables inside the main loop
# with the jit_merge_point function.
jitdriver = JitDriver(greens=['pc', 'code', 'program'],
                      reds=['mem'],
                      get_printable_location=get_location)

def main(argv):
    if len(argv) != 2:
        os.write(stderr_fd, 'Usage %s FILENAME\n' % argv[0])
        return 1
    else:
        fp = os.open(argv[1], os.O_RDONLY, 0777)
        program_text = ""
        while True:
            read = os.read(fp, 4096)
            if len(read) == 0:
                break
            program_text += read      
        program = parse(program_text)
        return_code = execute(program)
        return return_code
        
# This tells RPython what to use and entry point for compiling.
def target(*args):
    return main, None
        
if __name__ == "__main__":
    main(sys.argv)

