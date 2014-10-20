"""mandelbrot.py => madelbrot set in PGM format to stdout.

This code writes out a Mandelbrot set to stdout based on the parameters x_center, 
y_center, etc .defined below. This code isn't particularly sophisticated, rather it's
meant to be used for speed comparisons with mandelbrot.mach, which is runs on the 
bytecode interpreter machine.py, and which operates similarly.

This runs using 
    * Python2 (tested with 2.7.7):
        $ python mandelbrot.py > m.pgm
    * PyPy (tested with 2.3.1):
        $ pypy mandelbrot.py > m.pgm
    * Translated using RPython (tested with version from PyPy 2.3.1). You'll need the
      source distribution for RPython and you'll need to adjust the paths appropriately. 
        $ pypy rpython/bin/rpython mandelbrot.py 
        $ ./mandelbrot-c > m.pgm

"""
import os
import sys
from math import hypot


# Parameters defining the Mandelbrot set

x_center = -0.5
y_center = 0.0
width = 4.0
i_max = 1600
j_max = 1200
n = 100
r_max = 2.0
colour_max = 255

scale = float(colour_max) / n
pixel_size = width / i_max
x_offset = x_center - (0.5 * pixel_size * (i_max + 1))
y_offset = y_center - (0.5 * pixel_size * (j_max + 1))


# Write our own print-like function that RPython likes.

stdout_fd = sys.stdout.fileno()

def write(text):
    os.write(stdout_fd, text)


# This is the core of the program. Not much too it

def iterate_z(re0, im0, re, im, n):
    for i in range(n):
        temp = re*re - im*im + re0
        im = 2*re*im + im0
        re = temp
        if hypot(re, im) > r_max:
            return i
    return n
    
def grey_value(re, im):
    return int(scale * iterate_z(re, im, 0, 0, n))
 		 
def pixel(i, j):
    return grey_value((x_offset + pixel_size * i), (y_offset + pixel_size * j))
  
def generate_pgm():
    write("P2\n")
    write("%s\n" % i_max)
    write("%s\n" % j_max)
    write("%s\n" % colour_max)
    for j in range(j_max):
        for i in range(i_max):
            write("%s\n" % pixel(i,j))


# Startup boilerplate. 'target' is so that RPython knows where to start translating.
    
def main(argv):
    generate_pgm()
    return 0
   
def target(*args):
    return main, None
        
if __name__ == "__main__":
    main(sys.argv)
