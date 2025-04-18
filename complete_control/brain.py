#!/usr/bin/env python3

import nest
import numpy as np
import time
import sys
import os
import music
import matplotlib.pyplot as plt

# Just to get the following imports right!
sys.path.insert(1, '../')

import trajectories as tj
from motorcortex import MotorCortex
from planner import Planner
from stateestimator import StateEstimator, StateEstimator_mass
from cerebellum import Cerebellum
from population_view import plotPopulation

from util import plot_activity, plot_activity_pos_neg, plot_scatter, add_rect_pause, add_slider, collapse_gdf_data, read_gdf_data, neptune_manager
from population_view import PopView
from pointMass import PointMass
from settings import Experiment, Simulation, Brain, MusicCfg
import mpi4py
import random
#from plotting import plot_activity, plot_activity_pos_neg

import ctypes
ctypes.CDLL("libmpi.so", mode=ctypes.RTLD_GLOBAL)

nest.Install("util_neurons_module")
nest.Install("cerebmodule")

import json

exp = Experiment()

param_file = exp.param_file
saveFig = True
ScatterPlot = False
SHOW = False
pathFig = exp.pathFig
pthDat   = exp.pathData
pthFig = exp.pathFig
cond = exp.cond

# Opening JSON file
f = open(param_file)
params = json.load(f)
print(params["modules"])
f.close()


mc_params = params["modules"]["motor_cortex"]
plan_params = params["modules"]["planner"]

spine_params = params["modules"]["spine"]
state_params = params["modules"]["state"]
state_se_params = params["modules"]["state_se"]

pops_params = params["pops"]
conn_params = params["connections"]



#%%  SIMULATION

sim = Simulation()

res        = sim.resolution
time_span  = sim.timeMax
time_pause = sim.timePause
n_trial   = sim.n_trials
time_vect  = np.linspace(0, time_span, num=int(np.round(time_span/res)), endpoint=True)

nest.ResetKernel()
nest.SetKernelStatus({"resolution": res})
nest.SetKernelStatus({"overwrite_files": True})

# Randomize
msd = int( time.time() * 1000.0 )
N_vp = nest.GetKernelStatus(['total_num_virtual_procs'])[0]
nest.SetKernelStatus({'rng_seeds' : range(msd+N_vp+1, msd+2*N_vp+1)})


#%%  EXPERIMENT
print("init exp")

if mpi4py.MPI.COMM_WORLD.rank == 0:
    # Remove existing .dat and/or .gdf files generated in previous simulations
    exp.remove_files()

dynSys   = exp.dynSys
njt      = exp.dynSys.numVariables()

# End-effector space
init_pos_ee = exp.init_pos
tgt_pos_ee  = exp.tgt_pos
trj_ee, pol = tj.minimumJerk(init_pos_ee, tgt_pos_ee, time_vect)

# Joint space
init_pos = dynSys.inverseKin( init_pos_ee )
tgt_pos  = dynSys.inverseKin( tgt_pos_ee )
trj      = dynSys.inverseKin( trj_ee )

#%% BRAIN ########################
print("init brain")

brain = Brain()

# Number of neurons
N    = brain.nNeurPop # For each subpopulation positive/negative
nTot = 2*N*njt        # Total number of neurons

# Cerebellum
print("init cerebellum")
# Bug: cerebellum must be loaded before any other neural population
# Otherwise, Nest ids of new neurons coincide with Nest cerebellar neurons ids
filename_h5 = brain.filename_h5
filename_config = brain.filename_config
cereb_controlled_joint = brain.cerebellum_controlled_joint
cerebellum_application_forw = exp.cerebellum_application_forw  # Trial at which the cerebellum si connected to StateEstimator
cerebellum_application_inv = exp.cerebellum_application_inv  # Trial at which the cerebellum si connected to StateEstimator
''
tags = ['forw','inv']
cerebellum_forw = Cerebellum(filename_h5, filename_config, True, tags[0])
cerebellum = Cerebellum(filename_h5, filename_config, True, tags[1])
''
print(brain.filename_config)

#### Planner
print("init planner")

planner = Planner(N, time_vect, tgt_pos_ee, dynSys, plan_params["kpl"], pthDat, time_pause, plan_params["base_rate"],plan_params["kp"])

#### Motor cortex
print("init mc")
preciseControl = brain.precCtrl # Precise or approximated ffwd commands?
# mc_param       = brain.motCtx_param # Motor cortex parameters

mc = MotorCortex(N, time_vect, trj, dynSys, pthDat, preciseControl, time_pause, **mc_params)

#### State Estimator
print("init state")
kpred    = state_se_params["kpred"]
ksens    = state_se_params["ksens"]
se_param = {"out_base_rate":  state_se_params["out_base_rate"],
            "out_kp":         state_se_params["out_kp"],
            "wgt_scale":      state_se_params["wgt_scale"],
            "buf_sz":        state_se_params["buf_sz"]}
se = StateEstimator(N, time_vect, dynSys, kpred, ksens, pthDat, **se_param)


stEst = StateEstimator_mass(N, time_vect, dynSys, state_params)
#%% SPINAL CORD ########################

delay_fbk          = params["modules"]["spine"]["fbk_delay"]
wgt_sensNeur_spine = params["modules"]["spine"]["wgt_sensNeur_spine"]

#### Sensory feedback (Parrot neurons on Sensory neurons)
sn_p=[]
sn_n=[]

for j in range(njt):
    # Positive neurons
    tmp_p = nest.Create ("parrot_neuron", N)
    sn_p.append( PopView(tmp_p, time_vect, to_file=True, label='sens_fbk_'+str(j)+'_p') )
    # Negative neurons
    tmp_n = nest.Create ("parrot_neuron", N)
    sn_n.append( PopView(tmp_n, time_vect, to_file=True, label='sens_fbk_'+str(j)+'_n') )

#%% State estimator #######
# Scale the cerebellar prediction up to 1000 Hz
# in order to have firing rate suitable for the State estimator
# and all the other structures inside the control system
''

prediction_p = nest.Create("diff_neuron", N)
nest.SetStatus(prediction_p, {"kp": pops_params["prediction"]["kp"], "pos": True, "buffer_size": pops_params["prediction"]["buffer_size"], "base_rate": pops_params["prediction"]["base_rate"]}) #5.5
prediction_n = nest.Create("diff_neuron", N)
nest.SetStatus(prediction_n, {"kp": pops_params["prediction"]["kp"], "pos": False, "buffer_size": pops_params["prediction"]["buffer_size"], "base_rate": pops_params["prediction"]["base_rate"]}) #5.5
''
nest.Connect(cerebellum_forw.N_DCNp, prediction_p, 'all_to_all', syn_spec={"weight": conn_params["dcn_forw_prediction"]["weight"], "delay": conn_params["dcn_forw_prediction"]["delay"]})
nest.Connect(cerebellum_forw.N_DCNn, prediction_p, 'all_to_all', syn_spec={"weight": -conn_params["dcn_forw_prediction"]["weight"], "delay": conn_params["dcn_forw_prediction"]["delay"]})
nest.Connect(cerebellum_forw.N_DCNp, prediction_n, 'all_to_all', syn_spec={"weight": conn_params["dcn_forw_prediction"]["weight"], "delay": conn_params["dcn_forw_prediction"]["delay"]})
nest.Connect(cerebellum_forw.N_DCNn, prediction_n, 'all_to_all', syn_spec={"weight": -conn_params["dcn_forw_prediction"]["weight"], "delay": conn_params["dcn_forw_prediction"]["delay"]})
''
pops_params["fbk_smoothed"]["kp"]
# buffer_state = 10 e buffer_fbk_smoothed = 15 sembra decente

# Modify variability sensory feedback ("smoothed")
fbk_smoothed_p = nest.Create("diff_neuron", N)
nest.SetStatus(fbk_smoothed_p, {"kp": pops_params["fbk_smoothed"]["kp"], "pos": True, "buffer_size": pops_params["fbk_smoothed"]["buffer_size"], "base_rate": pops_params["fbk_smoothed"]["base_rate"]})
fbk_smoothed_n = nest.Create("diff_neuron", N)
nest.SetStatus(fbk_smoothed_n, {"kp": pops_params["fbk_smoothed"]["kp"], "pos": False, "buffer_size": pops_params["fbk_smoothed"]["buffer_size"], "base_rate": pops_params["fbk_smoothed"]["base_rate"]})
for j in range(njt):
    ''
    if j == cereb_controlled_joint:

        nest.Connect(sn_p[j].pop, fbk_smoothed_p, "all_to_all", syn_spec={"weight": conn_params["sn_fbk_smoothed"]["weight"], "delay": conn_params["sn_fbk_smoothed"]["delay"]})
        print(conn_params["sn_fbk_smoothed"]["weight"])
        nest.Connect(sn_n[j].pop, fbk_smoothed_n, "all_to_all", syn_spec={"weight": -conn_params["sn_fbk_smoothed"]["weight"], "delay": conn_params["sn_fbk_smoothed"]["delay"]})

        # Positive neurons
        nest.Connect(prediction_p, stEst.pops_p[j].pop, "all_to_all", syn_spec=conn_params["pred_state"])
        nest.Connect(fbk_smoothed_p, stEst.pops_p[j].pop, "all_to_all", syn_spec=conn_params["fbk_smoothed_state"])
        nest.SetStatus(stEst.pops_p[j].pop, {"num_first": float(N), "num_second": float(N)})

        # Negative neurons
        nest.Connect(prediction_n, stEst.pops_n[j].pop, "all_to_all", syn_spec=conn_params["pred_state"])
        nest.Connect(fbk_smoothed_n, stEst.pops_n[j].pop, "all_to_all", syn_spec=conn_params["fbk_smoothed_state"])
        nest.SetStatus(stEst.pops_n[j].pop, {"num_first": float(N), "num_second": float(N)})
    else:

        # Positive neurons
        nest.Connect(sn_p[j].pop, stEst.pops_p[j].pop, "all_to_all", syn_spec=conn_params["sn_state"])
        nest.SetStatus(stEst.pops_p[j].pop, {"num_second": float(N)})
        # Negative neurons
        nest.Connect(sn_n[j].pop, stEst.pops_n[j].pop, "all_to_all", syn_spec=conn_params["sn_state"])
        nest.SetStatus(stEst.pops_n[j].pop, {"num_second": float(N)})

print("init connections feedback")

#%% CONNECTIONS
#### Connection Planner - Motor Cortex feedback (excitatory)
wgt_plnr_mtxFbk   = conn_params["planner_mc_fbk"]["weight"]

# Delay between planner and motor cortex feedback.
# It needs to compensate for the delay introduced by the state estimator
#delay_plnr_mtxFbk = brain.stEst_param["buf_sz"] # USE THIS WITH REAL STATE ESTIMATOR
delay_plnr_mtxFbk = conn_params["planner_mc_fbk"]["delay"]                         # USE THIS WITH "FAKE" STATE ESTIMATOR

for j in range(njt):
    planner.pops_p[j].connect( mc.fbk_p[j], rule='one_to_one', w= wgt_plnr_mtxFbk, d=delay_plnr_mtxFbk )
    planner.pops_p[j].connect( mc.fbk_n[j], rule='one_to_one', w= wgt_plnr_mtxFbk, d=delay_plnr_mtxFbk )
    planner.pops_n[j].connect( mc.fbk_p[j], rule='one_to_one', w=-wgt_plnr_mtxFbk, d=delay_plnr_mtxFbk )
    planner.pops_n[j].connect( mc.fbk_n[j], rule='one_to_one', w=-wgt_plnr_mtxFbk, d=delay_plnr_mtxFbk )

    # planner.pops_p[j].connect( mc.ffwd_p[j], rule='one_to_one', w= wgt_plnr_mtxFbk, d=delay_plnr_mtxFbk )
    # planner.pops_p[j].connect( mc.ffwd_n[j], rule='one_to_one', w= wgt_plnr_mtxFbk, d=delay_plnr_mtxFbk )
    # planner.pops_n[j].connect( mc.ffwd_p[j], rule='one_to_one', w=-wgt_plnr_mtxFbk, d=delay_plnr_mtxFbk )
    # planner.pops_n[j].connect( mc.ffwd_n[j], rule='one_to_one', w=-wgt_plnr_mtxFbk, d=delay_plnr_mtxFbk )

#### Connection State Estimator - Motor Cortex feedback (Inhibitory)
wgt_stEst_mtxFbk = conn_params["state_mc_fbk"]["weight"]

# REAL STATE ESTIMATOR
# To connect the output of the state estimator to the motor cortex feedback
# Io (Massimo) ho disabilitato questo blocco per lo State
'''
for j in range(njt):
    se.out_p[j].connect( mc.fbk_p[j], rule='one_to_one', w= wgt_stEst_mtxFbk, d=res )
    se.out_p[j].connect( mc.fbk_n[j], rule='one_to_one', w= wgt_stEst_mtxFbk, d=res )
    se.out_n[j].connect( mc.fbk_p[j], rule='one_to_one', w=-wgt_stEst_mtxFbk, d=res )
    se.out_n[j].connect( mc.fbk_n[j], rule='one_to_one', w=-wgt_stEst_mtxFbk, d=res )
'''

# FAKE STATE ESTIMATOR
# To connect the actual sensory input of the state estimator to the motor cortex
# for j in range(njt):
#     se.sens_p[j].connect( mc.fbk_p[j], rule='one_to_one', w= wgt_stEst_mtxFbk, d=res )
#     se.sens_p[j].connect( mc.fbk_n[j], rule='one_to_one', w= wgt_stEst_mtxFbk, d=res )
#     se.sens_n[j].connect( mc.fbk_p[j], rule='one_to_one', w=-wgt_stEst_mtxFbk, d=res )
#     se.sens_n[j].connect( mc.fbk_n[j], rule='one_to_one', w=-wgt_stEst_mtxFbk, d=res )

#### Connection Sensory feedback - State estimator (excitatory)
# wgt_spine_stEst = brain.connections["wgt_spine_stEst"]

# for j in range(njt):
#     sn_p[j].connect( se.sens_p[j], rule='one_to_one', w=wgt_spine_stEst, d=res )
#     sn_n[j].connect( se.sens_n[j], rule='one_to_one', w=wgt_spine_stEst, d=res )

### DIRECT FROM SENSORY TO MOTOR CORTEX
# for j in range(njt):
#     sn_p[j].connect( mc.fbk_p[j], rule='one_to_one', w= wgt_stEst_mtxFbk )
#     sn_p[j].connect( mc.fbk_n[j], rule='one_to_one', w= wgt_stEst_mtxFbk )
#     sn_n[j].connect( mc.fbk_p[j], rule='one_to_one', w=-wgt_stEst_mtxFbk )
#     sn_n[j].connect( mc.fbk_n[j], rule='one_to_one', w=-wgt_stEst_mtxFbk )
''
# Cerebellar connections ##############
N_mossy_forw = len(cerebellum_forw.Nest_Mf)

# Motor cortex neurons controlling a certain joint contact also mossy fibers
n_forw = int(N_mossy_forw/2)

# Motor commands relay neurons
motor_commands_p = nest.Create("diff_neuron", n_forw)
nest.SetStatus(motor_commands_p, {"kp": pops_params["motor_commands"]["kp"], "pos": True, "buffer_size": pops_params["motor_commands"]["buffer_size"], "base_rate": pops_params["motor_commands"]["base_rate"]})
motor_commands_n = nest.Create("diff_neuron", n_forw)
nest.SetStatus(motor_commands_n, {"kp": pops_params["motor_commands"]["kp"], "pos": False, "buffer_size": pops_params["motor_commands"]["buffer_size"], "base_rate": pops_params["motor_commands"]["base_rate"]})

''
nest.Connect(mc.out_p[cereb_controlled_joint].pop, motor_commands_p, "all_to_all", syn_spec={"weight": conn_params["mc_out_motor_commands"]["weight"], "delay": conn_params["mc_out_motor_commands"]["delay"]})
nest.Connect(mc.out_n[cereb_controlled_joint].pop, motor_commands_n, "all_to_all", syn_spec={"weight": -conn_params["mc_out_motor_commands"]["weight"], "delay": conn_params["mc_out_motor_commands"]["delay"]})
''
nest.Connect(motor_commands_p, cerebellum_forw.Nest_Mf[-n_forw:], {'rule': 'one_to_one'},syn_spec={'weight':1.0})
nest.Connect(motor_commands_n, cerebellum_forw.Nest_Mf[0:n_forw], {'rule': 'one_to_one'},syn_spec={'weight':1.0})#TODO add weight
''
# Scale the feedback signal to 0-60 Hz in order to be suitable for the cerebellum
feedback_p = nest.Create("diff_neuron", N)
nest.SetStatus(feedback_p, {"kp": pops_params["feedback"]["kp"], "pos": True, "buffer_size": pops_params["feedback"]["buffer_size"], "base_rate": pops_params["feedback"]["base_rate"]})
feedback_n = nest.Create("diff_neuron", N)
nest.SetStatus(feedback_n, {"kp": pops_params["feedback"]["kp"], "pos": False, "buffer_size": pops_params["feedback"]["buffer_size"], "base_rate": pops_params["feedback"]["base_rate"]})
''

nest.Connect(sn_p[cereb_controlled_joint].pop, feedback_p, 'all_to_all', syn_spec={"weight": conn_params["sn_feedback"]["weight"], "delay": conn_params["sn_feedback"]["delay"]})
nest.Connect(sn_n[cereb_controlled_joint].pop, feedback_n, 'all_to_all', syn_spec={"weight": -conn_params["sn_feedback"]["weight"], "delay": conn_params["sn_feedback"]["delay"]})

# Error signal toward IO neurons ############
''
# Positive subpopulation
error_p = nest.Create("diff_neuron", N)
nest.SetStatus(error_p, {"kp": pops_params["error"]["kp"], "pos": True, "buffer_size":pops_params["error"]["buffer_size"], "base_rate": pops_params["error"]["base_rate"]})
# Negative subpopulation
error_n = nest.Create("diff_neuron", N)
nest.SetStatus(error_n, {"kp": pops_params["error"]["kp"], "pos": False, "buffer_size":pops_params["error"]["buffer_size"], "base_rate": pops_params["error"]["base_rate"]})

syn_exc = {"weight": 0.1}  # Synaptic weight of the excitatory synapse
syn_inh = {"weight": -0.1} # Synaptic weight of the inhibitory synapse

''
# Construct the error signal for both positive and negative neurons
nest.Connect(cerebellum_forw.N_DCNp, error_p, {'rule': 'all_to_all'}, syn_spec={"weight":-conn_params["dcn_f_error"]["weight"]})
nest.Connect(cerebellum_forw.N_DCNn, error_p, {'rule': 'all_to_all'}, syn_spec={"weight":conn_params["dcn_f_error"]["weight"]})
nest.Connect(feedback_p, error_p, 'all_to_all', syn_spec={"weight":conn_params["feedback_error"]["weight"]})
nest.Connect(feedback_n, error_p, 'all_to_all', syn_spec={"weight":-conn_params["feedback_error"]["weight"]})

nest.Connect(cerebellum_forw.N_DCNp, error_n, {'rule': 'all_to_all'}, syn_spec={"weight":-conn_params["dcn_f_error"]["weight"]})
nest.Connect(cerebellum_forw.N_DCNn, error_n, {'rule': 'all_to_all'}, syn_spec={"weight":conn_params["dcn_f_error"]["weight"]})
nest.Connect(feedback_p, error_n, 'all_to_all', syn_spec={"weight":-conn_params["feedback_error"]["weight"]})
nest.Connect(feedback_n, error_n, 'all_to_all', syn_spec={"weight":conn_params["feedback_error"]["weight"]})

# Connect error neurons toward IO neurons
nest.Connect(error_p, cerebellum_forw.N_IOp,{'rule': 'all_to_all'}, syn_spec={"weight": conn_params["error_io_f"]["weight"], "delay": conn_params["error_io_f"]["delay"], "receptor_type":conn_params["error_io_f"]["receptor_type"]})
nest.Connect(error_n, cerebellum_forw.N_IOn,{'rule': 'all_to_all'}, syn_spec={"weight": -conn_params["error_io_f"]["weight"], "delay": conn_params["error_io_f"]["delay"], "receptor_type":conn_params["error_io_f"]["receptor_type"]})
''
# Connect state estimator (bayesian) to the Motor Cortex
for j in range(njt):
    nest.Connect(stEst.pops_p[j].pop,mc.fbk_p[j].pop, "one_to_one", {"weight": wgt_stEst_mtxFbk, "delay": res})
    nest.Connect(stEst.pops_p[j].pop,mc.fbk_n[j].pop, "one_to_one", {"weight": wgt_stEst_mtxFbk, "delay": res})
    nest.Connect(stEst.pops_n[j].pop,mc.fbk_p[j].pop, "one_to_one", {"weight": -wgt_stEst_mtxFbk, "delay": res})
    nest.Connect(stEst.pops_n[j].pop,mc.fbk_n[j].pop, "one_to_one", {"weight": -wgt_stEst_mtxFbk, "delay": res})

#########
''
N_mossy = len(cerebellum.Nest_Mf)

# Motor cortex neurons controlling a certain joint contact also mossy fibers
n = int(N_mossy/2)


# Input to inverse neurons
plan_to_inv_p = nest.Create("diff_neuron", n)
nest.SetStatus(plan_to_inv_p, {"kp": pops_params["plan_to_inv"]["kp"], "pos": True, "buffer_size": pops_params["plan_to_inv"]["buffer_size"],  "base_rate": pops_params["plan_to_inv"]["base_rate"]})
plan_to_inv_n = nest.Create("diff_neuron", n)
nest.SetStatus(plan_to_inv_n, {"kp": pops_params["plan_to_inv"]["kp"], "pos": False, "buffer_size": pops_params["plan_to_inv"]["buffer_size"], "base_rate": pops_params["plan_to_inv"]["base_rate"]})
''
# connection planner to inverse through modulators
syn_exc = {"weight": 0.001, "delay": res} # 0.003
syn_inh = {"weight": -0.001, "delay": res} #TODO set from json!!
nest.Connect(planner.pops_p[cereb_controlled_joint].pop, plan_to_inv_p, "all_to_all", syn_spec=syn_exc)
nest.Connect(planner.pops_n[cereb_controlled_joint].pop, plan_to_inv_n, "all_to_all", syn_spec=syn_inh)

nest.Connect(plan_to_inv_p, cerebellum.Nest_Mf[-n:], {'rule': 'one_to_one'}) #TODO weight
nest.Connect(plan_to_inv_n, cerebellum.Nest_Mf[0:n], {'rule': 'one_to_one'})
''


# output from inverse model
motor_prediction_p = nest.Create("diff_neuron", N)
nest.SetStatus(motor_prediction_p, {"kp": pops_params["motor_pred"]["kp"], "pos": True, "buffer_size": pops_params["motor_pred"]["buffer_size"], "base_rate": pops_params["motor_pred"]["base_rate"]})
motor_prediction_n = nest.Create("diff_neuron", N)
nest.SetStatus(motor_prediction_n, {"kp": pops_params["motor_pred"]["kp"], "pos": False, "buffer_size": pops_params["motor_pred"]["buffer_size"], "base_rate": pops_params["motor_pred"]["base_rate"]})

syn_exc = {"weight": 0.3, "delay": res}
syn_inh = {"weight": -0.3, "delay": res}
nest.Connect(cerebellum.N_DCNp, motor_prediction_p, 'all_to_all', syn_spec={"weight": conn_params["dcn_i_motor_pred"]["weight"], "delay": conn_params["dcn_i_motor_pred"]["delay"]})
nest.Connect(cerebellum.N_DCNn, motor_prediction_p, 'all_to_all', syn_spec={"weight": -conn_params["dcn_i_motor_pred"]["weight"], "delay": conn_params["dcn_i_motor_pred"]["delay"]})
nest.Connect(cerebellum.N_DCNp, motor_prediction_n, 'all_to_all', syn_spec={"weight": conn_params["dcn_i_motor_pred"]["weight"], "delay": conn_params["dcn_i_motor_pred"]["delay"]})
nest.Connect(cerebellum.N_DCNn, motor_prediction_n, 'all_to_all', syn_spec={"weight": -conn_params["dcn_i_motor_pred"]["weight"], "delay": conn_params["dcn_i_motor_pred"]["delay"]})

'''
brain_stem_p = nest.Create("basic_neuron", N)
nest.SetStatus(brain_stem_p, {"kp": pops_params["brain_stem"]["kp"], "pos": True, "buffer_size": pops_params["brain_stem"]["buffer_size"], "base_rate": pops_params["brain_stem"]["base_rate"]})
brain_stem_n = nest.Create("basic_neuron", N)
nest.SetStatus(brain_stem_n, {"kp": pops_params["brain_stem"]["kp"], "pos": False, "buffer_size": pops_params["brain_stem"]["buffer_size"], "base_rate": pops_params["brain_stem"]["base_rate"]})
''
# connections to motor cortex # TODO ffwrd??

# connections to motor cortex # TODO ffwrd??
nest.Connect(mc.out_p[cereb_controlled_joint].pop, brain_stem_p, "all_to_all", syn_spec={"weight": conn_params["mc_out_brain_stem"]["weight"], "delay": conn_params["mc_out_brain_stem"]["delay"]})
nest.Connect(mc.out_n[cereb_controlled_joint].pop, brain_stem_n, "all_to_all", syn_spec={"weight": conn_params["mc_out_brain_stem"]["weight"], "delay": conn_params["mc_out_brain_stem"]["delay"]})
'''


brain_stem_new_p=[]
brain_stem_new_n=[]

for j in range(njt):
    # Positive neurons
    tmp_p = nest.Create ("basic_neuron", N)
    nest.SetStatus(tmp_p, {"kp": pops_params["brain_stem"]["kp"], "pos": True, "buffer_size": pops_params["brain_stem"]["buffer_size"], "base_rate": pops_params["brain_stem"]["base_rate"]})
    brain_stem_new_p.append( PopView(tmp_p, time_vect) )
    # Negative neurons
    tmp_n = nest.Create ("basic_neuron", N)
    nest.SetStatus(tmp_n, {"kp": pops_params["brain_stem"]["kp"], "pos": False, "buffer_size": pops_params["brain_stem"]["buffer_size"], "base_rate": pops_params["brain_stem"]["base_rate"]})
    brain_stem_new_n.append( PopView(tmp_n, time_vect) )

# connections to motor cortex # TODO ffwrd??

# connections to motor cortex # TODO ffwrd??
nest.Connect(motor_prediction_p,brain_stem_new_p[cereb_controlled_joint].pop, "all_to_all",  syn_spec={"weight": conn_params["motor_pre_brain_stem"]["weight"], "delay": conn_params["motor_pre_brain_stem"]["delay"]})
nest.Connect(motor_prediction_n,brain_stem_new_n[cereb_controlled_joint].pop, "all_to_all",  syn_spec={"weight": -conn_params["motor_pre_brain_stem"]["weight"], "delay": conn_params["motor_pre_brain_stem"]["delay"]})

for j in range(njt):
    nest.Connect(mc.out_p[j].pop,brain_stem_new_p[j].pop, "all_to_all", {"weight": conn_params["mc_out_brain_stem"]["weight"], "delay": conn_params["mc_out_brain_stem"]["delay"]})
    # nest.Connect(stEst.pops_p[j].pop,mc.fbk_n[j].pop, "one_to_one", {"weight": wgt_stEst_mtxFbk, "delay": res})
    # nest.Connect(stEst.pops_n[j].pop,mc.fbk_p[j].pop, "one_to_one", {"weight": -wgt_stEst_mtxFbk, "delay": res})
    nest.Connect(mc.out_n[j].pop,brain_stem_new_n[j].pop, "all_to_all", {"weight": -conn_params["mc_out_brain_stem"]["weight"], "delay": conn_params["mc_out_brain_stem"]["delay"]})

# # connections to motor cortex # TODO ffwrd??
# nest.Connect(motor_prediction_p,mc.out_p[cereb_controlled_joint].pop, "one_to_one", conn_params["motor_pred_mc_out"])
# #nest.Connect(motor_prediction_p,mc.ffwd_n[j].pop, "all_to_all", {"weight": 0.1, "delay": res })
# #nest.Connect(motor_prediction_n,mc.ffwd_p[j].pop, "all_to_all", {"weight": 0.1, "delay": res })
# nest.Connect(motor_prediction_n,mc.out_n[cereb_controlled_joint].pop, "one_to_one", conn_params["motor_pred_mc_out"])

# feedback from sensory
feedback_inv_p = nest.Create("diff_neuron", N)
nest.SetStatus(feedback_inv_p, {"kp": pops_params["feedback_inv"]["kp"], "pos": True, "buffer_size": pops_params["feedback_inv"]["buffer_size"], "base_rate": pops_params["feedback_inv"]["base_rate"]})
feedback_inv_n = nest.Create("diff_neuron", N)
nest.SetStatus(feedback_inv_n, {"kp": pops_params["feedback_inv"]["kp"], "pos": False, "buffer_size": pops_params["feedback_inv"]["buffer_size"], "base_rate": pops_params["feedback_inv"]["base_rate"]})

''
# TODO differentiate feedback according to joint
# syn_exc = {"weight": 0.001, "delay": res}
# syn_inh = {"weight": -0.001, "delay": res}
nest.Connect(sn_p[cereb_controlled_joint].pop, feedback_inv_p, 'all_to_all', syn_spec={"weight": conn_params["sn_feedback_inv"]["weight"], "delay": conn_params["sn_feedback_inv"]["delay"]})
nest.Connect(sn_n[cereb_controlled_joint].pop, feedback_inv_n, 'all_to_all', syn_spec={"weight": -conn_params["sn_feedback_inv"]["weight"], "delay": conn_params["sn_feedback_inv"]["delay"]})
''

# error to IO

error_inv_p = nest.Create("diff_neuron", N)
nest.SetStatus(error_inv_p, {"kp": pops_params["error_i"]["kp"], "pos": True, "buffer_size":pops_params["error_i"]["buffer_size"], "base_rate": pops_params["error_i"]["base_rate"]})
# Negative subpopulation
error_inv_n = nest.Create("diff_neuron", N)
nest.SetStatus(error_inv_n, {"kp": pops_params["error_i"]["kp"], "pos": False, "buffer_size":pops_params["error_i"]["buffer_size"], "base_rate": pops_params["error_i"]["base_rate"]})

''
j = cereb_controlled_joint
# # Positive neurons #TODO ragionare se feedback o state
# nest.Connect(feedback_inv_p, error_inv_p, "all_to_all", syn_spec={"weight": conn_params["feedback_inv_error_inv"]["weight"], "delay": conn_params["feedback_inv_error_inv"]["delay"]})
# nest.Connect(feedback_inv_p, error_inv_n, "all_to_all", syn_spec={"weight": conn_params["feedback_inv_error_inv"]["weight"], "delay": conn_params["feedback_inv_error_inv"]["delay"]})

# # Negative neurons
# nest.Connect(feedback_inv_n, error_inv_n, "all_to_all", syn_spec={"weight": -conn_params["feedback_inv_error_inv"]["weight"], "delay": conn_params["feedback_inv_error_inv"]["delay"]})
# nest.Connect(feedback_inv_n, error_inv_p, "all_to_all", syn_spec={"weight": -conn_params["feedback_inv_error_inv"]["weight"], "delay": conn_params["feedback_inv_error_inv"]["delay"]})

# Positive neurons #TODO ragionare se feedback o state
nest.Connect(stEst.pops_p[j].pop, error_inv_p, "all_to_all", syn_spec={"weight": -conn_params["state_error_inv"]["weight"], "delay": conn_params["state_error_inv"]["delay"]})
nest.Connect(stEst.pops_p[j].pop, error_inv_n, "all_to_all", syn_spec={"weight": -conn_params["state_error_inv"]["weight"], "delay": conn_params["state_error_inv"]["delay"]})

# Negative neurons
nest.Connect(stEst.pops_n[j].pop, error_inv_n, "all_to_all", syn_spec={"weight": conn_params["state_error_inv"]["weight"], "delay": conn_params["state_error_inv"]["delay"]})
nest.Connect(stEst.pops_n[j].pop, error_inv_p, "all_to_all", syn_spec={"weight": conn_params["state_error_inv"]["weight"], "delay": conn_params["state_error_inv"]["delay"]})



     #else:
syn_exc = {"weight": 0.1, "delay": res}
syn_inh = {"weight": -0.1, "delay": res}
# # Positive neurons
# nest.Connect(sn_p[j].pop, mc.fbk_p[j].pop, "one_to_one", syn_spec=syn_exc)
# # Negative neurons
# nest.Connect(sn_n[j].pop, mc.fbk_n[j].pop, "one_to_one", syn_spec=syn_inh)


# Construct the error signal for both positive and negative neurons
nest.Connect(planner.pops_p[j].pop, error_inv_p, {'rule': 'all_to_all'}, syn_spec={"weight": conn_params["plan_to_inv_error_inv"]["weight"], "delay": conn_params["plan_to_inv_error_inv"]["delay"]})
nest.Connect(planner.pops_n[j].pop, error_inv_p, {'rule': 'all_to_all'}, syn_spec={"weight": -conn_params["plan_to_inv_error_inv"]["weight"], "delay": conn_params["plan_to_inv_error_inv"]["delay"]})
nest.Connect(planner.pops_p[j].pop, error_inv_n, {'rule': 'all_to_all'}, syn_spec={"weight": conn_params["plan_to_inv_error_inv"]["weight"], "delay": conn_params["plan_to_inv_error_inv"]["delay"]})
nest.Connect(planner.pops_n[j].pop, error_inv_n, {'rule': 'all_to_all'}, syn_spec={"weight": -conn_params["plan_to_inv_error_inv"]["weight"], "delay": conn_params["plan_to_inv_error_inv"]["delay"]})
# nest.Connect(plan_to_inv_p, error_inv_p, {'rule': 'all_to_all'}, syn_spec={"weight": conn_params["plan_to_inv_error_inv"]["weight"], "delay": conn_params["plan_to_inv_error_inv"]["delay"]})
# nest.Connect(plan_to_inv_n, error_inv_p, {'rule': 'all_to_all'}, syn_spec={"weight": -conn_params["plan_to_inv_error_inv"]["weight"], "delay": conn_params["plan_to_inv_error_inv"]["delay"]})
# nest.Connect(plan_to_inv_p, error_inv_n, {'rule': 'all_to_all'}, syn_spec={"weight": conn_params["plan_to_inv_error_inv"]["weight"], "delay": conn_params["plan_to_inv_error_inv"]["delay"]})
# nest.Connect(plan_to_inv_n, error_inv_n, {'rule': 'all_to_all'}, syn_spec={"weight": -conn_params["plan_to_inv_error_inv"]["weight"], "delay": conn_params["plan_to_inv_error_inv"]["delay"]})
# nest.Connect(planner.pops_p[cereb_controlled_joint].pop, error_p, {'rule': 'all_to_all'}, syn_spec=syn_exc)
# nest.Connect(planner.pops_n[cereb_controlled_joint].pop, error_p, {'rule': 'all_to_all'}, syn_spec=syn_inh)

# nest.Connect(plan_to_inv_p, error_n, {'rule': 'all_to_all'}, syn_spec=syn_inh)
# nest.Connect(plan_to_inv_n, error_n, {'rule': 'all_to_all'}, syn_spec=syn_exc)

# Connect error neurons toward IO neurons
nest.Connect(error_inv_p, cerebellum.N_IOp,{'rule': 'all_to_all'}, syn_spec={"weight": conn_params["error_inv_io_i"]["weight"], "delay": conn_params["error_inv_io_i"]["delay"], "receptor_type":conn_params["error_inv_io_i"]["receptor_type"]})
nest.Connect(error_inv_n, cerebellum.N_IOn,{'rule': 'all_to_all'}, syn_spec={"weight": -conn_params["error_inv_io_i"]["weight"], "delay": conn_params["error_inv_io_i"]["delay"], "receptor_type":conn_params["error_inv_io_i"]["receptor_type"]})

# Connect feedbakc directly to the Motor Cortex
# for j in range(njt):
#    nest.Connect(sn_p[j].pop,mc.fbk_p[j].pop, "one_to_one", {"weight": 0.1, "delay": res})
#    nest.Connect(sn_p[j].pop,mc.fbk_n[j].pop, "one_to_one", {"weight": 0.1, "delay": res})
#    nest.Connect(sn_n[j].pop,mc.fbk_p[j].pop, "one_to_one", {"weight": -0.1, "delay": res})
#    nest.Connect(sn_n[j].pop,mc.fbk_n[j].pop, "one_to_one", {"weight": -0.1, "delay": res})
''


#%% MUSIC CONFIG

msc = MusicCfg()

#### MUSIC output port (with nTot channels)
proxy_out = nest.Create('music_event_out_proxy', 1, params = {'port_name':'mot_cmd_out'})

# ii=0
# for j in range(njt):
#     for i, n in enumerate(mc.out_p[j].pop):
#         nest.Connect([n], proxy_out, "one_to_one",{'music_channel': ii})
#         ii=ii+1
#     for i, n in enumerate(mc.out_n[j].pop):
#         nest.Connect([n], proxy_out, "one_to_one",{'music_channel': ii})
#         ii=ii+1

# ii=0
# # for j in range(njt):
# for i, n in enumerate(brain_stem_p):
#     nest.Connect([n], proxy_out, "one_to_one",{'music_channel': ii})
#     ii=ii+1
# for i, n in enumerate(mc.out_p[1].pop):
#     nest.Connect([n], proxy_out, "one_to_one",{'music_channel': ii})
#     ii=ii+1
# for i, n in enumerate(brain_stem_n):
#     nest.Connect([n], proxy_out, "one_to_one",{'music_channel': ii})
#     ii=ii+1
# for i, n in enumerate(mc.out_n[1].pop):
#     nest.Connect([n], proxy_out, "one_to_one",{'music_channel': ii})
#     ii=ii+1


ii=0
for j in range(njt):
    for i, n in enumerate(brain_stem_new_p[j].pop):
        nest.Connect([n], proxy_out, "one_to_one",{'music_channel': ii})
        ii=ii+1
    for i, n in enumerate(brain_stem_new_n[j].pop):
        nest.Connect([n], proxy_out, "one_to_one",{'music_channel': ii})
        ii=ii+1


#### MUSIC input ports (nTot ports with one channel each)
proxy_in = nest.Create ('music_event_in_proxy', nTot, params = {'port_name': 'fbk_in'})
for i, n in enumerate(proxy_in):
    nest.SetStatus([n], {'music_channel': i})

# Divide channels based on function (using channel order)
for j in range(njt):
    # Check joint: only joint controlled by the cerebellum can be affected by delay
    if j == cereb_controlled_joint:
        delay = delay_fbk
    else:
        delay = 0.1

    #### Positive channels
    idxSt_p = 2*N*j
    idxEd_p = idxSt_p + N
    nest.Connect( proxy_in[idxSt_p:idxEd_p], sn_p[j].pop, 'one_to_one', {"weight":wgt_sensNeur_spine, "delay":delay} )
    #### Negative channels
    idxSt_n = idxEd_p
    idxEd_n = idxSt_n + N
    nest.Connect( proxy_in[idxSt_n:idxEd_n], sn_n[j].pop, 'one_to_one', {"weight":wgt_sensNeur_spine, "delay":delay} )

# We need to tell MUSIC, through NEST, that it's OK (due to the delay)
# to deliver spikes a bit late. This is what makes the loop possible.
nest.SetAcceptableLatency('fbk_in', 0.1-msc.const)

###################### Extra Spikedetectors ######################
spikedetector_fbk_pos = nest.Create("spike_detector", params={"withgid": True,"withtime": True, "to_file": True, "label": "Feedback pos"})
spikedetector_fbk_neg = nest.Create("spike_detector", params={"withgid": True,"withtime": True, "to_file": True, "label": "Feedback neg"})

spikedetector_fbk_inv_pos = nest.Create("spike_detector", params={"withgid": True,"withtime": True, "to_file": True, "label": "Feedback inv pos"})
spikedetector_fbk_inv_neg = nest.Create("spike_detector", params={"withgid": True,"withtime": True, "to_file": True, "label": "Feedback inv neg"})

spikedetector_fbk_cereb_pos = nest.Create("spike_detector", params={"withgid": True,"withtime": True, "to_file": True, "label": "Feedback cerebellum pos"})
spikedetector_fbk_cereb_neg = nest.Create("spike_detector", params={"withgid": True,"withtime": True, "to_file": True, "label": "Feedback cerebellum neg"})
spikedetector_io_forw_input_pos = nest.Create("spike_detector", params={"withgid": True,"withtime": True, "to_file": True, "label": "Input inferior Olive Forw pos"})
spikedetector_io_forw_input_neg = nest.Create("spike_detector", params={"withgid": True,"withtime": True, "to_file": True, "label": "Input inferior Olive Forw neg"})

spikedetector_io_inv_input_pos = nest.Create("spike_detector", params={"withgid": True,"withtime": True, "to_file": True, "label": "Input inferior Olive Inv pos"})
spikedetector_io_inv_input_neg = nest.Create("spike_detector", params={"withgid": True,"withtime": True, "to_file": True, "label": "Input inferior Olive Inv neg"})

spikedetector_stEst_pos = nest.Create("spike_detector", params={"withgid": True,"withtime": True, "to_file": True, "label": "State estimator pos"})
spikedetector_stEst_neg = nest.Create("spike_detector", params={"withgid": True,"withtime": True, "to_file": True, "label": "State estimator neg"})
spikedetector_planner_pos = nest.Create("spike_detector", params={"withgid": True,"withtime": True, "to_file": True, "label": "Planner pos"})
spikedetector_planner_neg = nest.Create("spike_detector", params={"withgid": True,"withtime": True, "to_file": True, "label": "Planner neg"})
spikedetector_pred_pos = nest.Create("spike_detector", params={"withgid": True,"withtime": True, "to_file": True, "label": "Cereb pred pos"})
spikedetector_pred_neg = nest.Create("spike_detector", params={"withgid": True,"withtime": True, "to_file": True, "label": "Cereb pred neg"})
spikedetector_motor_pred_pos = nest.Create("spike_detector", params={"withgid": True,"withtime": True, "to_file": True, "label": "Cereb motor pred pos"})
spikedetector_motor_pred_neg = nest.Create("spike_detector", params={"withgid": True,"withtime": True, "to_file": True, "label": "Cereb motor pred neg"})
spikedetector_stEst_max_pos = nest.Create("spike_detector", params={"withgid": True,"withtime": True, "to_file": True, "label": "State estimator Max pos"})
spikedetector_stEst_max_neg = nest.Create("spike_detector", params={"withgid": True,"withtime": True, "to_file": True, "label": "State estimator Max neg"})
spikedetector_fbk_smoothed_pos = nest.Create("spike_detector", params={"withgid": True,"withtime": True, "to_file": True, "label": "Feedback smoothed pos"})
spikedetector_fbk_smoothed_neg = nest.Create("spike_detector", params={"withgid": True,"withtime": True, "to_file": True, "label": "Feedback smoothed neg"})

spikedetector_motor_comm_pos = nest.Create("spike_detector", params={"withgid": True,"withtime": True, "to_file": True, "label": "Motor Command pos"})
spikedetector_motor_comm_neg = nest.Create("spike_detector", params={"withgid": True,"withtime": True, "to_file": True, "label": "Motor Command neg"})

spikedetector_plan_to_inv_pos = nest.Create("spike_detector", params={"withgid": True,"withtime": True, "to_file": True, "label": "Plan to inv pos"})
spikedetector_plan_to_inv_neg = nest.Create("spike_detector", params={"withgid": True,"withtime": True, "to_file": True, "label": "Plan to inv neg"})

spikedetector_brain_stem_pos = nest.Create("spike_detector", params={"withgid": True,"withtime": True, "to_file": True, "label": "Brain stem pos"})
spikedetector_brain_stem_neg = nest.Create("spike_detector", params={"withgid": True,"withtime": True, "to_file": True, "label": "Brain stem neg"})

nest.Connect(motor_commands_p, spikedetector_motor_comm_pos)
nest.Connect(motor_commands_n, spikedetector_motor_comm_neg)

nest.Connect(brain_stem_new_p[cereb_controlled_joint].pop, spikedetector_brain_stem_pos)
nest.Connect(brain_stem_new_n[cereb_controlled_joint].pop, spikedetector_brain_stem_neg)

nest.Connect(plan_to_inv_p, spikedetector_plan_to_inv_pos)
nest.Connect(plan_to_inv_n, spikedetector_plan_to_inv_neg)

nest.Connect(sn_p[cereb_controlled_joint].pop, spikedetector_fbk_pos)
nest.Connect(sn_n[cereb_controlled_joint].pop, spikedetector_fbk_neg)
nest.Connect(feedback_p, spikedetector_fbk_cereb_pos)
nest.Connect(feedback_n, spikedetector_fbk_cereb_neg)

nest.Connect(feedback_inv_p, spikedetector_fbk_inv_pos)
nest.Connect(feedback_inv_n, spikedetector_fbk_inv_pos)
''
nest.Connect(error_p, spikedetector_io_forw_input_pos)
nest.Connect(error_n, spikedetector_io_forw_input_neg)

nest.Connect(error_inv_p, spikedetector_io_inv_input_pos)
nest.Connect(error_inv_n, spikedetector_io_inv_input_neg)
''
nest.Connect(se.out_p[cereb_controlled_joint].pop, spikedetector_stEst_pos)
nest.Connect(se.out_n[cereb_controlled_joint].pop, spikedetector_stEst_neg)
nest.Connect(planner.pops_p[cereb_controlled_joint].pop, spikedetector_planner_pos)
nest.Connect(planner.pops_n[cereb_controlled_joint].pop, spikedetector_planner_neg)
''
nest.Connect(prediction_p, spikedetector_pred_pos)
nest.Connect(prediction_n, spikedetector_pred_neg)

nest.Connect(motor_prediction_p, spikedetector_motor_pred_pos)
nest.Connect(motor_prediction_n, spikedetector_motor_pred_neg)
''
nest.Connect(stEst.pops_p[cereb_controlled_joint].pop, spikedetector_stEst_max_pos)
nest.Connect(stEst.pops_n[cereb_controlled_joint].pop, spikedetector_stEst_max_neg)
''
nest.Connect(fbk_smoothed_p, spikedetector_fbk_smoothed_pos)
nest.Connect(fbk_smoothed_n, spikedetector_fbk_smoothed_neg)
''
'''
##### Weight recorder created manually #####
parallel_fiber_to_basket = cerebellum.scaffold_model.get_connectivity_set("parallel_fiber_to_basket")
pf_bc = np.unique(parallel_fiber_to_basket.from_identifiers)[0:5000]
basket = np.unique(parallel_fiber_to_basket.to_identifiers)
bc_nest = cerebellum.tuning_adapter.get_nest_ids(basket)
bc_pos = np.intersect1d(bc_nest, cerebellum.Nest_ids['basket_cell']['positive'])
bc_neg = np.intersect1d(bc_nest, cerebellum.Nest_ids['basket_cell']['negative'])
pf_to_basket_pos = nest.GetConnections(source = cerebellum.tuning_adapter.get_nest_ids(pf_bc), target = list(bc_pos))
print('Number of pf-BC pos: ', len(pf_to_basket_pos))
pf_to_basket_neg = nest.GetConnections(source = cerebellum.tuning_adapter.get_nest_ids(pf_bc), target = list(bc_neg))
print('Number of pf-BC neg: ', len(pf_to_basket_neg))
Nest_pf_to_basket = (pf_to_basket_pos + pf_to_basket_neg)

parallel_fiber_to_stellate = cerebellum.scaffold_model.get_connectivity_set("parallel_fiber_to_stellate")
pf_sc = np.unique(parallel_fiber_to_stellate.from_identifiers)[0:5000]
stellate = np.unique(parallel_fiber_to_stellate.to_identifiers)
sc_nest = cerebellum.tuning_adapter.get_nest_ids(stellate)
sc_pos = np.intersect1d(sc_nest, cerebellum.Nest_ids['stellate_cell']['positive'])
sc_neg = np.intersect1d(sc_nest, cerebellum.Nest_ids['stellate_cell']['negative'])
pf_to_stellate_pos = nest.GetConnections(source = cerebellum.tuning_adapter.get_nest_ids(pf_sc), target = list(sc_pos))
print('Number of pf-SC pos: ', len(pf_to_stellate_pos))
pf_to_stellate_neg = nest.GetConnections(source = cerebellum.tuning_adapter.get_nest_ids(pf_sc), target = list(sc_neg))
print('Number of pf-SC neg: ', len(pf_to_stellate_neg))
Nest_pf_to_stellate = (pf_to_stellate_pos + pf_to_stellate_neg)

parallel_fiber_to_purkinje = cerebellum.scaffold_model.get_connectivity_set("parallel_fiber_to_purkinje")
pf_pc = np.unique(parallel_fiber_to_purkinje.from_identifiers)[0:10000]
purkinje = np.unique(parallel_fiber_to_purkinje.to_identifiers)
pc_nest = cerebellum.tuning_adapter.get_nest_ids(purkinje)
pc_pos = np.intersect1d(pc_nest, cerebellum.Nest_ids['purkinje_cell']['positive'])
pc_neg = np.intersect1d(pc_nest, cerebellum.Nest_ids['purkinje_cell']['negative'])
pf_to_purkinje_pos = nest.GetConnections(source = cerebellum.tuning_adapter.get_nest_ids(pf_pc), target = list(pc_pos))
print('Number of pf-PC pos: ', len(pf_to_purkinje_pos))
pf_to_purkinje_neg = nest.GetConnections(source = cerebellum.tuning_adapter.get_nest_ids(pf_pc), target = list(pc_neg))
print('Number of pf-PC neg: ', len(pf_to_purkinje_neg))
Nest_pf_to_purkinje = (pf_to_purkinje_pos + pf_to_purkinje_neg)

weights = np.array(nest.GetStatus(Nest_pf_to_basket, "weight"))
if mpi4py.MPI.COMM_WORLD.rank == 0:
    print('Number of pf-BC connections: ',weights.shape[0])
    weights_pf_bc = np.empty((weights.shape[0], n_trial+1))
    weights_pf_bc[:,0] = weights

weights = np.array(nest.GetStatus(Nest_pf_to_stellate, "weight"))
if mpi4py.MPI.COMM_WORLD.rank == 0:
    print('Number of pf-SC connections: ',weights.shape[0])
    weights_pf_sc = np.empty((weights.shape[0], n_trial+1))
    weights_pf_sc[:,0] = weights

weights = np.array(nest.GetStatus(Nest_pf_to_purkinje, "weight"))
if mpi4py.MPI.COMM_WORLD.rank == 0:
    print('Number of pf-PC connections: ',weights.shape[0])
    weights_pf_pc = np.empty((weights.shape[0], n_trial+1))
    weights_pf_pc[:,0] = weights
'''

###################### SIMULATE ######################
nest.SetKernelStatus({"data_path": pthDat})
total_len = int(time_span + time_pause)
'''
# Disable Sensory feedback in State estimation (TODO togliere)
conns_pos = nest.GetConnections(source = fbk_smoothed_p, target = stEst.pops_p[cereb_controlled_joint].pop)
conns_neg = nest.GetConnections(source = fbk_smoothed_n, target = stEst.pops_n[cereb_controlled_joint].pop)
nest.SetStatus(conns_pos, {"weight": 0.0})
nest.SetStatus(conns_neg, {"weight": 0.0})
'''
# Disable Cerebellar prediction in State estimation for the first 5 trials
''
conns_pos_forw = nest.GetConnections(source = prediction_p, target = stEst.pops_p[cereb_controlled_joint].pop)
conns_neg_forw = nest.GetConnections(source = prediction_n, target = stEst.pops_n[cereb_controlled_joint].pop)
''
conns_pos_inv = nest.GetConnections(source = motor_prediction_p, target = brain_stem_new_p[cereb_controlled_joint].pop)
conns_neg_inv = nest.GetConnections(source = motor_prediction_n, target = brain_stem_new_n[cereb_controlled_joint].pop)
''
# I can't disconnect cereb-State if the Prediction_error = state - cereb
# I can disconnect the cerebellum only if the error = Feedback - cereb
''
if cerebellum_application_inv != 0:
    nest.SetStatus(conns_pos_inv, {"weight": 0.0})
    nest.SetStatus(conns_neg_inv, {"weight": 0.0})
''
if cerebellum_application_forw != 0:
    nest.SetStatus(conns_pos_forw, {"weight": 0.0})
    nest.SetStatus(conns_neg_forw, {"weight": 0.0})
''
nest.SetKernelStatus({"data_path": pthDat})
total_len = int(time_span + time_pause)
for trial in range(n_trial):
    if mpi4py.MPI.COMM_WORLD.rank == 0:
        print('Simulating trial {} lasting {} ms'.format(trial+1,total_len))

    if trial == cerebellum_application_inv:
        nest.SetStatus(conns_pos_inv, {"weight": -conn_params["motor_pre_brain_stem"]["weight"]})
        nest.SetStatus(conns_neg_inv, {"weight": conn_params["motor_pre_brain_stem"]["weight"]})
    if trial == cerebellum_application_forw:
        nest.SetStatus(conns_pos_forw, {"weight": conn_params["pred_state"]["weight"]})
        nest.SetStatus(conns_neg_forw, {"weight": -conn_params["pred_state"]["weight"]})
    nest.Simulate(total_len)
'''
#%% SIMULATE ######################
nest.SetKernelStatus({"data_path": pthDat})
total_len = int(time_span + time_pause)
for trial in range(n_trial):
    if mpi4py.MPI.COMM_WORLD.rank == 0:
        print('Simulating trial {} lasting {} ms'.format(trial+1,total_len))
    nest.Simulate(total_len)
'''
'''
    # Add weights to weigth_recorder
    # Pf-BC
    weights = np.array(nest.GetStatus(Nest_pf_to_basket, "weight"))
    if mpi4py.MPI.COMM_WORLD.rank == 0:
        weights_pf_bc[:,trial+1] = weights
    # Pf_SC
    weights = np.array(nest.GetStatus(Nest_pf_to_stellate, "weight"))
    if mpi4py.MPI.COMM_WORLD.rank == 0:
        weights_pf_sc[:,trial+1] = weights
    # Pf-PC
    weights = np.array(nest.GetStatus(Nest_pf_to_purkinje, "weight"))
    if mpi4py.MPI.COMM_WORLD.rank == 0:
        weights_pf_pc[:,trial+1] = weights
    '''


#%% PLOTTING
if mpi4py.MPI.COMM_WORLD.rank == 0:
    lgd = ['x','y']
    time_vect_paused = np.linspace(0, total_len*n_trial, num=int(np.round(total_len/res)), endpoint=True)

    # Positive
    fig, ax = plt.subplots(2,1)
    for i in range(njt):
        planner.pops_p[i].plot_rate(time_vect_paused,ax=ax[i],bar=False,color='r',label='planner')
        sn_p[i].plot_rate(time_vect_paused,ax=ax[i],bar=False,title=lgd[i]+" (Hz)",color='b',label='sensory')
        se.out_p[i].plot_rate(time_vect_paused,buffer_sz=5,ax=ax[i],bar=False,title=lgd[i]+" (Hz)",color='b',linestyle=':', label='state pos')
    plt.legend()
    ax[i].set_xlabel("time (ms)")
    plt.suptitle("Positive")
    if saveFig:
        plt.savefig(pathFig+cond+"plan_fbk_pos.png")

    # Negative
    fig, ax = plt.subplots(2,1)
    for i in range(njt):
        planner.pops_n[i].plot_rate(time_vect_paused,ax=ax[i],bar=False,color='r',label='planner')
        sn_n[i].plot_rate(time_vect_paused,ax=ax[i],bar=False,title=lgd[i]+" (Hz)",color='b',label='sensory')
        se.out_n[i].plot_rate(time_vect_paused,buffer_sz=5,ax=ax[i],bar=False,title=lgd[i]+" (Hz)",color='b',linestyle=':', label='state neg')
        plt.legend()
    ax[i].set_xlabel("time (ms)")
    plt.suptitle("Negative")
    if saveFig:
        plt.savefig(pathFig+cond+"plan_fbk_neg.png")

    # # MC fbk
    for i in range(njt):
        plotPopulation(time_vect_paused, mc.fbk_p[i],mc.fbk_n[i], title=lgd[i],buffer_size=10)
        plt.suptitle("MC fbk")
        plt.xlabel("time (ms)")
        if saveFig:
            plt.savefig(pathFig+cond+"mtctx_fbk_"+lgd[i]+".png")

    # # MC ffwd
    for i in range(njt):
        plotPopulation(time_vect_paused, mc.ffwd_p[i],mc.ffwd_n[i], title=lgd[i],buffer_size=10)
        plt.suptitle("MC ffwd")
        plt.xlabel("time (ms)")
        if saveFig:
            plt.savefig(pathFig+cond+"mtctx_ffwd_"+lgd[i]+".png")


    # lgd = ['x','y']
    #
    # for i in range(njt):
    #     plotPopulation(time_vect_paused, planner.pops_p[i],planner.pops_n[i], title=lgd[i],buffer_size=15)
    #     plt.suptitle("Planner")
    #
    # # Sensory feedback
    # for i in range(njt):
    #     plotPopulation(time_vect_paused, sn_p[i], sn_n[i], title=lgd[i],buffer_size=15)
    #     plt.suptitle("Sensory feedback")


    # lgd = ['x','y']
    #
    # # State estimator
    # for i in range(njt):
    #     plotPopulation(time_vect_paused, se.out_p[i],se.out_n[i], title=lgd[i],buffer_size=15)
    #     plt.suptitle("State estimator")
    #
    # # Sensory feedback
    # for i in range(njt):
    #     plotPopulation(time_vect_paused, sn_p[i], sn_n[i], title=lgd[i],buffer_size=15)
    #     plt.suptitle("Sensory feedback")
    #


    # motCmd = mc.getMotorCommands()
    # fig, ax = plt.subplots(2,1)
    # ax[0].plot(time_vect_paused,trj)
    # ax[1].plot(time_vect_paused,motCmd)
    #
    #
    lgd = ['x','y']

    fig, ax = plt.subplots(2,1)
    for i in range(njt):
        mc.out_p[i].plot_rate(time_vect_paused,ax=ax[i],bar=False,color='r',label='out')
        mc.out_n[i].plot_rate(time_vect_paused,ax=ax[i],bar=False,title=lgd[i]+" (Hz)",color='b')

        b,c,pos_r = mc.out_p[i].computePSTH(time_vect_paused,buffer_sz=25)
        b,c,neg_r = mc.out_n[i].computePSTH(time_vect_paused,buffer_sz=25)
        if i==0:
            plt.figure()
        plt.plot(b[:-1],pos_r-neg_r)
        plt.xlabel("time (ms)")
        plt.ylabel("spike rate positive - negative")
        plt.legend(lgd)

    #plt.savefig("mctx_out_pos-neg.png")

######## Plotting Cerebellar neurons ########
## Collapsing data files into one file
names = []
network_neurons = ["Input inferior Olive Forw pos","Input inferior Olive Forw neg","Input inferior Olive Inv pos","Input inferior Olive Inv neg","Feedback pos","Feedback neg","State estimator pos","State estimator neg","Planner pos","Planner neg","Feedback cerebellum pos","Feedback cerebellum neg","mc_out_p_0","mc_out_n_0","mc_out_p_1","mc_out_n_1","sens_fbk_0_p","sens_fbk_0_n","sens_fbk_1_p","sens_fbk_1_n","Cereb motor pred pos","Cereb motor pred neg","Cereb pred pos","Cereb pred neg","State estimator Max pos","State estimator Max neg","Feedback smoothed pos","Feedback smoothed neg","Motor Command pos","Motor Command neg","Plan to inv pos","Plan to inv neg", "Brain stem pos", "Brain stem neg"]
cereb_neurons = ["granule_cell","golgi_cell","dcn_cell_glut_large","purkinje_cell","basket_cell","stellate_cell","dcn_cell_GABA","mossy_fibers",'io_cell',"glomerulus","dcn_cell_Gly-I"]

for t in tags:
    for n in cereb_neurons:
        names.append(t + '_' + n)
    #print(names.append(t + '_' + n))
names.extend(network_neurons)

files = [f for f in os.listdir(pthDat) if os.path.isfile(os.path.join(pthDat,f))]


if mpi4py.MPI.COMM_WORLD.rank == 0:
    collapse_gdf_data(names, pthDat)
    # file_list = []
    # for name in names:
    #     if (name + '_spikes' + '.gdf' not in files):
    #         for f in files:
    #             if (f.startswith(name)):
    #                 file_list.append(f)
    #         print(file_list)
    #         with open(pthDat + name + ".gdf", "w") as wfd:
    #             for f in file_list:
    #                 with open(pthDat + f, "r") as fd:
    #                     wfd.write(fd.read())
    #         for f in file_list:
    #             os.remove(pthDat+f)
    #         file_list = []
    #     else:
    #         print('Già fatto')
    print('Collapsing files ended')


########################### PLOTTING ###########################
cell_numerosity = {
    names[0]: len(cerebellum_forw.S_GR),
    names[1]: len(cerebellum_forw.S_Go),
    names[2]: len(cerebellum_forw.S_DCN),
    names[3]: len(cerebellum_forw.S_BC),
    names[4]: len(cerebellum_forw.S_SC),
    names[5]: len(cerebellum_forw.S_DCN_GABA),
    names[6]: len(cerebellum_forw.S_Mf),
    names[7]: len(cerebellum_forw.S_IO),
    names[8]: len(cerebellum.S_GR),
    names[9]: len(cerebellum.S_Go),
    names[10]: len(cerebellum.S_DCN),
    names[11]: len(cerebellum.S_PC),
    names[12]: len(cerebellum.S_BC),
    names[13]: len(cerebellum.S_SC),
    names[14]: len(cerebellum.S_DCN_GABA),
    names[15]: len(cerebellum.S_Mf),
    names[16]: len(cerebellum.S_IO)}

for i in range(17,len(names)):
    cell_numerosity[names[i]] = N

# print(names)
# print(cell_numerosity)
# print(len(names))
# print(len(cell_numerosity))



if mpi4py.MPI.COMM_WORLD.rank == 0:
    SD, IDs =   read_gdf_data(names,pthDat)
    print('Start reading data')
    # files = [f for f in os.listdir(pthDat) if os.path.isfile(os.path.join(pthDat,f))]
    # IDs = {}
    # SD = {}
    # times = {}
    # for cell in names:
    #     print('Reading:',cell)
    #     for f in files:
    #         if f.startswith(cell):
    #             break
    #     cell_f = open(pthDat+f,'r').read()
    #     cell_f = cell_f.split('\n')
    #     IDs[cell] = {}
    #     SD[cell] = {'evs': [], 'ts': []}
    #     for i in range(len(cell_f)-1):
    #         splitted_string = cell_f[i].split('\t')
    #         ID_cell = float(splitted_string[0])
    #         time_cell = float(splitted_string[1])
    #         SD[cell]['evs'].append(ID_cell)
    #         SD[cell]['ts'].append(time_cell)
    #         if str(ID_cell) in IDs[cell].keys():
    #             IDs[cell][str(ID_cell)].append(time_cell)
    #         else:
    #             IDs[cell][str(ID_cell)] = [time_cell]
    nep = neptune_manager()
    nep.set_params(params)

    print('Start making plots')
    for name_id, cell in enumerate(names):
        list1 = []
        list1 = [tag + '_' + a for tag in tags for a in ["granule_cell","golgi_cell","glomerulus","dcn_cell_Gly-I"]]
        if cell in list1:
            continue
        if (IDs[cell].keys()):
            beginning = 0
            bin_duration = 10
            list2 = []
            list2 = [tag + '_' + a for tag in tags for a in ["dcn_cell_glut_large","purkinje_cell","basket_cell","stellate_cell","io_cell"]]
            # print(list2)
            if cell in list2:
                if cell[0]==tags[0][0]:
                    cereb = cerebellum_forw
                else:
                    cereb = cerebellum
                freq_pos = []
                freq_neg = []
                plt.figure(figsize=(10,8))
                for start in range(beginning, total_len*n_trial, bin_duration):
                    n_spikes_pos = 0
                    n_spikes_neg = 0
                    end = start + bin_duration
                    for key in IDs[cell].keys():
                        times = [i for i in IDs[cell][key] if i>=start and i< end]
                        if float(key) in cereb.Nest_ids[cell]["positive"]:
                            n_spikes_pos += len(times)
                        elif float(key) in cereb.Nest_ids[cell]["negative"]:
                            n_spikes_neg += len(times)
                        else:
                            #print(d)
                            pass
                    freq_bin_pos = n_spikes_pos/(bin_duration/1000*len(cereb.Nest_ids[cell]["positive"]))
                    freq_bin_neg = n_spikes_neg/(bin_duration/1000*len(cereb.Nest_ids[cell]["negative"]))
                    freq_pos.append(freq_bin_pos)
                    freq_neg.append(freq_bin_neg)
                x = range(beginning, total_len*n_trial, bin_duration)
                t = np.arange(beginning, total_len*n_trial, bin_duration)
                plt.plot(x,freq_pos,'b', label='positive')
                plt.plot(x,freq_neg,'r', label='negative')
                plt.title('Spike frequency ' + names[name_id], size =25)
                plt.xlabel('Time [ms]', size =25)
                plt.ylabel('Frequency [Hz]', size =25)
                plt.xlim(0,total_len*n_trial)
                plt.xticks(fontsize=25)
                plt.yticks(fontsize=25)

                start = 0
                end = total_len*n_trial
                n_spikes_pos = 0
                n_spikes_neg = 0
                for key in IDs[cell].keys():
                    times = [i for i in IDs[cell][key] if i>=start and i< end]
                    if float(key) in cereb.Nest_ids[cell]["positive"]:
                        n_spikes_pos += len(times)
                    elif float(key) in cereb.Nest_ids[cell]["negative"]:
                        n_spikes_neg += len(times)
                    else:
                        print('STRANO')
                        pass
                mean_freq_pos = n_spikes_pos/((end-start)/1000*len(cereb.Nest_ids[cell]["positive"]))
                mean_freq_neg = n_spikes_neg/((end-start)/1000*len(cereb.Nest_ids[cell]["negative"]))
                x = [start,end]
                y = [mean_freq_pos]*len(x)
                plt.plot(x,y,'b',linewidth = 3)
                y = [mean_freq_neg]*len(x)
                plt.plot(x,y,'r',linewidth = 3)
                plt.legend()
                plt.savefig(pathFig+cond+'Spike frequency ' + names[name_id]+'.svg')
                fig = plot_activity_pos_neg(freq_pos, freq_neg, [mean_freq_pos]*len(t), [mean_freq_neg]*len(t), t,'Spike frequency ' + names[name_id], to_html = True, to_png = True, path = pathFig+cond)
                add_rect_pause(fig, time_span, time_pause, n_trial)
                add_slider(fig)
                nep.save_fig(fig, 'Spike frequency ' + names[name_id])
                #fig_to_neptune(neptune_flag, fig, run, cell)
                # run["visuals/plotly-fig"+cell] = File.as_html(fig)
                if SHOW:
                    fig.show()
                # Mean frequency computed considering each neuron (not the entire population)
                freq_pos = []
                freq_neg = []
                start = 0
                end = n_trial*total_len
                for key in IDs[cell].keys():
                    times = [i for i in IDs[cell][key] if i>=start and i<= end]
                    if float(key) in cereb.Nest_ids[cell]["positive"]:
                        freq_pos.append(len(times)/((end-start)/1000))
                    elif float(key) in cereb.Nest_ids[cell]["negative"]:
                        freq_neg.append(len(times)/((end-start)/1000))
                    else:
                        print('STRANO')
                        pass
                if len(freq_pos) < len(cereb.Nest_ids[cell]["positive"]):
                    freq_pos.extend([0]*(len(cereb.Nest_ids[cell]["positive"])-len(freq_pos)))
                if len(freq_neg) <  len(cereb.Nest_ids[cell]["negative"]):
                    freq_neg.extend([0]*( len(cereb.Nest_ids[cell]["negative"])-len(freq_neg)))
                print('Population frequency {} POS: {} +- {}'.format(names[name_id],round(np.mean(freq_pos),2),round(np.std(freq_pos),2)))
                print('Population frequency {} NEG: {} +- {}'.format(names[name_id],round(np.mean(freq_neg),2),round(np.std(freq_neg),2)))
                with open(pthDat+"spiking_frequency_log.txt", "a") as f:
                    f.write('Population frequency {} NEG: {} +- {}'.format(names[name_id],round(np.mean(freq_neg),2),round(np.std(freq_neg),2)) +'\n')
                    f.write('Population frequency {} POS: {} +- {}'.format(names[name_id],round(np.mean(freq_pos),2),round(np.std(freq_pos),2)) + '\n')
                with open(pthDat+"spiking_frequency_data.csv", "a") as f:
                    txt = names[name_id]
                    lst = txt.split('_')
                    if lst[0] in {'inv','forw'}:
                        f1 = lst[0]
                        f2 = '_'.join(lst[1:])
                    else:
                        f1 = ''
                        f2 = txt
                    f.write('{}; {}; neg; {}; {}\n'.format(f1,f2,round(np.mean(freq_neg),2),round(np.std(freq_neg),2)))
                    f.write('{}; {}; pos; {}; {}\n'.format(f1,f2,round(np.mean(freq_pos),2),round(np.std(freq_pos),2)))
            else:
                freq = []
                plt.figure(figsize=(10,8))
                for start in range(beginning, total_len*n_trial, bin_duration):
                    n_spikes = 0
                    end = start + bin_duration
                    for key in IDs[cell].keys():
                        times = [i for i in IDs[cell][key] if i>=start and i< end]
                        n_spikes += len(times)
                    freq_bin = n_spikes/(bin_duration/1000*cell_numerosity[cell])
                    freq.append(freq_bin)
                x = range(beginning, total_len*n_trial, bin_duration)
                t = np.arange(beginning, total_len*n_trial, bin_duration)
                plt.plot(x,freq)
                plt.title('Spike frequency ' + names[name_id], size =25)
                plt.xlabel('Time [ms]', size =25)
                plt.ylabel('Frequency [Hz]', size =25)
                plt.xlim(0,total_len*n_trial)
                plt.xticks(fontsize=25)
                plt.yticks(fontsize=25)
                start = 0
                end = total_len*n_trial
                n_spikes = 0
                for key in IDs[cell].keys():
                    times = [i for i in IDs[cell][key] if i>=start and i< end]
                    n_spikes += len(times)
                mean_freq = n_spikes/((end-start)/1000*cell_numerosity[cell])
                x = [start,end]
                y = [mean_freq]*len(x)
                plt.plot(x,y,'r',linewidth = 3)
                plt.savefig(pathFig+cond+'Spike frequency ' + names[name_id]+'.svg')
                fig = plot_activity(freq, [mean_freq]*len(t), t, 'Spike frequency ' + names[name_id], to_html = True, to_png = True, path =pathFig+cond)
                add_rect_pause(fig, time_span, time_pause, n_trial)
                add_slider(fig)
                nep.save_fig(fig, 'Spike frequency ' + names[name_id])
                # Mean frequency computed considering each neuron (not the entire population)
                freq = []
                start = 0
                end = total_len*n_trial
                if len(IDs[cell].keys()) < cell_numerosity[cell]:
                    freq = [0]*(cell_numerosity[cell]-len(IDs[cell].keys()))
                else:
                    freq = []
                for key in IDs[cell].keys():
                    times = [i for i in IDs[cell][key] if i>=start and i<= end]
                    freq.append(len(times)/((end-start)/1000))
                print('Population frequency {}: {} +- {}'.format(names[name_id],round(np.mean(freq),2),round(np.std(freq),2)))
                with open(pthDat+"spiking_frequency_log.txt", "a") as f:
                    f.write('Population frequency {}: {} +- {}'.format(names[name_id],round(np.mean(freq),2),round(np.std(freq),2))+ '\n')

                with open(pthDat+"spiking_frequency_data.csv", "a") as f:
                    txt = names[name_id]
                    lst = txt.split(' ')
                    if len(lst)==1:
                        lst1 = txt.split('_')
                        if lst1[0] in {'inv', 'forw'}:
                            f1 = lst1[0]
                            f2 = '_'.join(lst1[1:])
                        else:
                            f1 = ''
                            f2 = txt
                        f3 = ''
                    elif lst[-1] in {'pos','neg'}:
                        f3 = lst[-1]
                        if lst[-2] in {'Inv', 'Forw'}:
                            f1 = lst[-2].lower()
                            f2 = ' '.join(lst[:-2])
                        else:
                            f1 = ''
                            f2 = ' '.join(lst[:-1])
                    else:
                        f1= ''
                        f3 = ''
                        f2 = txt
                    f.write('{}; {}; {}; {}; {}\n'.format(f1,f2,f3,round(np.mean(freq),2),round(np.std(freq),2)))
                    #f.write('; {}; {}; {}; {} 2\n'.format(f3,f3,round(np.mean(freq_pos),2),round(np.std(freq_pos),2)))

            if ScatterPlot:
                plt.figure(figsize=(10,8))
                y_min = np.min(SD[cell]['evs'])
                plt.scatter(SD[cell]['ts'], SD[cell]['evs']-y_min, marker='.', s = 200)
                plt.title('Scatter plot '+ names[name_id]+ ' neurons', size =25)
                plt.xlabel('Time [ms]', size =25)
                plt.ylabel('Neuron ID', size =25)
                plt.xlim(0,total_len*n_trial)
                plt.xticks(fontsize=25)
                plt.yticks(fontsize=25)
                plt.savefig(pathFig+cond+'Scatter plot '+ names[name_id]+ ' neurons.svg')

        else:
            print('Population '+cell+ ' is NOT spiking')
            with open(pthDat +"spiking_frequency_log.txt", "a") as f:
                f.write('Population '+cell+ ' is NOT spiking'+ '\n')

            with open(pthDat+"spiking_frequency_data.csv", "a") as f:
                txt = names[name_id]
                lst0 = txt.split(' ')
                if len(lst0)==1:
                # if '_' in txt:
                    lst = txt.split('_')
                    f3 = ''
                    if lst[0] in {'inv','forw'}:
                        f1 = lst[0]
                        f2 = '_'.join(lst[1:])
                    else:
                        f1 = ''
                        f2 = txt
                else:
                    lst1 = txt.split(' ')
                    f1 = ''
                    if lst1[-1] in {'pos','neg'}:
                        f3 = lst1[-1]
                        if lst[-2] in {'Inv', 'Forw'}:
                            f1 = lst[-2].lower()
                            f2 = ' '.join(lst[:-2])
                        else:
                            f1 = ''
                            f2 = ' '.join(lst[:-1])
                    else:
                        f3 = ''
                        f2 = txt
                f.write('{}; {}; {}; ;  \n'.format(f1,f2,f3))

    '''
    print(weights_pf_bc)
    print(weights_pf_sc)
    print(weights_pf_pc)
    filename = "weights_pf_bc"
    np.savetxt( pthDat+filename, weights_pf_bc )
    filename = "weights_pf_sc"
    np.savetxt( pthDat+filename, weights_pf_sc )
    filename = "weights_pf_pc"
    np.savetxt( pthDat+filename, weights_pf_pc )
    '''

    # plt.show()
