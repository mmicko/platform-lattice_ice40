# -*- coding: utf-8 -*-
# Copyright 2014-present PlatformIO <contact@platformio.org>
# Copyright 2016-present Juan González <juan@iearobotics.com>
#                        Jesús Arroyo Torrens <jesus.jkhlg@gmail.com>
# Copyright 2019-present Miodrag Milanovic <mmicko@gmail.com>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
    Build script for Lattice iCE40 FPGAs
"""

import os
from os.path import join
from platform import system

from SCons.Script import (COMMAND_LINE_TARGETS, AlwaysBuild, Builder, Default,
                          DefaultEnvironment, Exit, GetOption,
                          Glob)

env = DefaultEnvironment()
board = env.BoardConfig()

pioPlatform = env.PioPlatform()

env.Replace(
    PROGNAME='hardware',
    UPLOADER='iceprog',
    UPLOADERFLAGS=[],
    UPLOADBINCMD='$UPLOADER $UPLOADERFLAGS $SOURCES')

env.Append(SIMULNAME='simulation')

# -- Target name for synthesis
TARGET = join(env['BUILD_DIR'], env['PROGNAME'])

# -- Resources paths
IVL_PATH = join(
    pioPlatform.get_package_dir('toolchain-iverilog'), 'lib', 'ivl')
VLIB_PATH = join(
    pioPlatform.get_package_dir('toolchain-iverilog'), 'vlib')
YOSYS_PATH = join(
    pioPlatform.get_package_dir('toolchain-yosys'), 'share', 'yosys')
VLIB_FILES = ' '.join([
    '"{}"'.format(f) for f in Glob(join(VLIB_PATH, '*.v'))
    ]) if VLIB_PATH else ''

CHIPDB_PATH = join(
    pioPlatform.get_package_dir('toolchain-ice40'), 'share', 'icebox',
    'chipdb-{0}.txt'.format(env.BoardConfig().get('build.size', '1k')))

isWindows = 'Windows' == system()
VVP_PATH = '' if isWindows else '-M "{0}"'.format(IVL_PATH)
IVER_PATH = '' if isWindows else '-B "{0}"'.format(IVL_PATH)

# -- Get a list of all the verilog files in the src folfer, in ASCII, with
# -- the full path. All these files are used for the simulation
v_nodes = Glob(join(env['PROJECT_SRC_DIR'], '*.v'))
src_sim = [str(f) for f in v_nodes]

# --- Get the Testbench file (there should be only 1)
# -- Create a list with all the files finished in _tb.v. It should contain
# -- the test bench
list_tb = [f for f in src_sim if f[-5:].upper() == '_TB.V']

if len(list_tb) > 1:
    print('---> WARNING: More than one testbenches used')

# -- Error checking
try:
    testbench = list_tb[0]

# -- there is no testbench
except IndexError:
    testbench = None

SIMULNAME = ''
TARGET_SIM = ''

# clean
if len(COMMAND_LINE_TARGETS) == 0:
    if testbench is not None:
        # -- Simulation name
        testbench_file = os.path.split(testbench)[-1]
        SIMULNAME, ext = os.path.splitext(testbench_file)
# sim
elif 'sim' in COMMAND_LINE_TARGETS:
    if testbench is None:
        print('---> ERROR: NO testbench found for simulation')
        Exit(1)

    # -- Simulation name
    testbench_file = os.path.split(testbench)[-1]
    SIMULNAME, ext = os.path.splitext(testbench_file)

# -- Target sim name
if SIMULNAME:
    TARGET_SIM = join(env.subst('$BUILD_DIR'), SIMULNAME).replace('\\', '\\\\')

# --- Get the synthesis files. They are ALL the files except the testbench
src_synth = [f for f in src_sim if f not in list_tb]

# -- Get the PCF file
src_dir = env.subst('$PROJECT_SRC_DIR')

if (env.subst("$BUILD_FLAGS")):
    PCF = join(src_dir, env.subst("$BUILD_FLAGS"))
else:
    PCFs = join(src_dir, '*.pcf')
    PCF_list = env.Glob(PCFs)
    PCF = ''

    try:
        PCF = PCF_list[0]
    except IndexError:
        print('---> WARNING: no .pcf file found')

#
# Builder: Yosys (.v --> .json)
#
builder_synth = Builder(
    action=env.VerboseAction(" ".join([
        "yosys",
        "-p", "\"synth_ice40 -json $TARGET\"",
        "-q",
        env.subst("$SRC_BUILD_FLAGS"),
        "$SOURCES"
        ]), "Running Yosys..."),
    suffix='.json',
    src_suffix='.v')

#
# Builder: nextpnr-ice40 (.json --> .asc)
#
builder_pnr = Builder(
    action=env.VerboseAction(" ".join([
        "nextpnr-ice40",
        "--{0}{1}".format(board.get('build.type', 'hx'),board.get('build.size', '1k')),
        "--package", board.get('build.pack', 'tq144'),
        "--json", "$SOURCE",
        "--pcf {0}".format(PCF),
        "--asc", "$TARGET",
        "--quiet"
        ]), "Running NextPnR..."),
    suffix='.asc',
    src_suffix='.json')

# Builder: Icepack (.asc --> .bin)
#
builder_bitstream = Builder(
    action=env.VerboseAction('icepack $SOURCE $TARGET', "Running icepack..."),
    suffix='.bin',
    src_suffix='.asc')


env.Append(BUILDERS={
    'Synth': builder_synth, 
    'PnR': builder_pnr, 
    'Bin': builder_bitstream
})

generate_json = env.Synth(TARGET, [src_synth])
generate_asc = env.PnR(TARGET, [generate_json, PCF])
generate_bin = env.Bin(TARGET, generate_asc)

#
# Builder: Icetime (.asc --> .rpt)
#
builder_time_rpt = Builder(
    action=env.VerboseAction(" ".join([
            "icetime",
            "-d", "{0}{1}".format(board.get('build.type', 'hx'),board.get('build.size', '1k')),
            "-P", board.get('build.pack', 'tq144'),
            "-C", CHIPDB_PATH,
            "$SOURCE"        
        ]), "Running icetime..."),
    suffix='.rpt', # builder must have distinct suffix
    src_suffix='.asc')

env.Append(BUILDERS={'TimeReport': builder_time_rpt})

#
# Builders: Icarus Verilog
#
builder_iverilog = Builder(
    action=env.VerboseAction(" ".join([
            "iverilog",
            IVER_PATH,
            "-o", "$TARGET",
            "-D VCD_OUTPUT={0}".format(TARGET_SIM + '.vcd' if TARGET_SIM else '', VLIB_FILES),
            "$SOURCES"
        ]), "Running iverilog..."),
    suffix='.out',
    src_suffix='.v')

builder_verify = Builder(
    action=env.VerboseAction(" ".join([
            "iverilog",
            IVER_PATH,
            "$SOURCES"
        ]), "Running iverilog (verify)..."),
    suffix='.verify', # builder must have distinct suffix
    src_suffix='.v')

builder_vcd = Builder(
    action=env.VerboseAction(" ".join([
            "vvp", 
            VVP_PATH,
            "$SOURCE"
        ]), "Running simulation..."),
    suffix='.vcd',
    src_suffix='.out')
# NOTE: output file name is defined in the
#       iverilog call using VCD_OUTPUT macro

env.Append(BUILDERS={
    'IVerilog': builder_iverilog, 
    'Verify': builder_verify, 
    'VCD': builder_vcd
})

#
# Builders: Verilator
#
builder_verilator = Builder(
    action=env.VerboseAction(" ".join([
            "verilator",
            "--lint-only",
            "-v", "{0}/ice40/cells_sim.v".format(YOSYS_PATH),
            "-Wall",
            "-Wno-style",
            "$SOURCES"        
        ]),  "Running Verilator..."),
    suffix='.lint', # builder must have distinct suffix
    src_suffix='.v')

env.Append(BUILDERS={'Verilator': builder_verilator})

#
# Targets
#
# Upload bitstream
AlwaysBuild(env.Alias('upload', generate_bin, '$UPLOADBINCMD'))
#
# Time analysis (.rpt)
AlwaysBuild(env.Alias('time', env.TimeReport(TARGET, generate_asc)))
#
# Verify verilog code
AlwaysBuild(env.Alias('verify', env.Verify(TARGET, src_synth)))
#
# Simulate testbench
vcd_file = env.VCD(env.IVerilog(TARGET_SIM, src_sim))

AlwaysBuild(env.Alias('sim', vcd_file, 'gtkwave {0} {1}.gtkw'.format(
    vcd_file[0], join(env['PROJECT_SRC_DIR'], SIMULNAME))))
#
# Lint
AlwaysBuild(env.Alias('lint', env.Verilator(TARGET, src_synth)))
#
# Default: Generate bitstream
Default([generate_bin])

