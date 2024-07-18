#!/usr/bin/env python3
import sys
import numpy as np
import time
import os
import music
import matplotlib.pyplot as plt

# Adjust env vars to be able to import the NESTML-generated module
ld_lib_path = os.environ.get('LD_LIBRARY_PATH', '')
new_path = ld_lib_path + ":"+"../nestml/target"
os.environ['LD_LIBRARY_PATH'] = new_path

# Import the module
import nest
# Just to get the following imports right!
sys.path.insert(1, '../')

from motorcortex import MotorCortex
from planner import Planner
from stateestimator import StateEstimator, StateEstimator_mass
#from cerebellum import Cerebellum
from population_view import plotPopulation, PopView

from settings import MusicCfg, Experiment
import mpi4py
from mpi4py import MPI
import ctypes
ctypes.CDLL("libmpi.so", mode=ctypes.RTLD_GLOBAL)
import json

saveFig = True
ScatterPlot = False

# Opening JSON file to get parameters
f = open('new_params.json')

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
exp = Experiment()
pathFig = exp.pathFig
res = 0.1 #[ms]
time_span = 500.0 #[ms]
n_trial = 1
time_vect  = np.linspace(0, time_span, num=int(np.round(time_span/res)), endpoint=True)

njt = 1
trj = np.loadtxt('trajectory.txt')
motorCommands=np.loadtxt('motor_commands.txt')

N = 50 # Number of neurons for each (sub-)population
nTot = 2*N*njt # Total number of neurons (one positive and one negative population for each DOF)

nest.ResetKernel()
nest.SetKernelStatus({"resolution": res})

# # Cerebellum
cereb_controlled_joint = 0 # x = 0, y = 1

# Install the module containing neurons for planner and motor cortex
nest.Install("controller_module")
#### Planner
print("init planner")
planner = Planner(N, njt, time_vect, trj, plan_params["kpl"], plan_params["base_rate"], plan_params["kp"])

#### Motor cortex
print("init mc")
preciseControl = False # Precise or approximated ffwd commands?
mc = MotorCortex(N, njt, time_vect, motorCommands, **mc_params)

#### State Estimator
print("init state")
buf_sz = state_params['buffer_size']
additional_state_params = {'N_fbk': N, 'N_pred': N, 'fbk_bf_size': N*int(buf_sz/res), 'pred_bf_size': N*int(buf_sz/res)}
state_params.update(additional_state_params)
stEst = StateEstimator_mass(N, njt, time_vect, **state_params)

#%% SPINAL CORD ########################

delay_fbk          = params["modules"]["spine"]["fbk_delay"]
wgt_sensNeur_spine = params["modules"]["spine"]["wgt_sensNeur_spine"]

#### Sensory feedback (Parrot neurons on Sensory neurons)
sn_p=[]
sn_n=[]

for j in range(njt):
    # Positive neurons
    tmp_p = nest.Create ("parrot_neuron", N)
    sn_p.append( PopView(tmp_p, time_vect, to_file=False, label='sens_fbk_'+str(j)+'_p') )
    # Negative neurons
    tmp_n = nest.Create ("parrot_neuron", N)
    sn_n.append( PopView(tmp_n, time_vect, to_file=False, label='sens_fbk_'+str(j)+'_n') )

#%% State estimator #######
# Scale the cerebellar prediction up to 1000 Hz
# in order to have firing rate suitable for the State estimator
# and all the other structures inside the control system

prediction_p = nest.Create("diff_neuron_nestml", N)
nest.SetStatus(prediction_p, {"kp": pops_params["prediction"]["kp"], "pos": True, "buffer_size": pops_params["prediction"]["buffer_size"], "base_rate": pops_params["prediction"]["base_rate"], "simulation_steps": len(time_vect)}) #5.5
prediction_n = nest.Create("diff_neuron_nestml", N)
nest.SetStatus(prediction_n, {"kp": pops_params["prediction"]["kp"], "pos": False, "buffer_size": pops_params["prediction"]["buffer_size"], "base_rate": pops_params["prediction"]["base_rate"], "simulation_steps": len(time_vect)}) #5.5

pops_params["fbk_smoothed"]["kp"]


for j in range(njt):
    ''
    if j == cereb_controlled_joint:
        # Modify variability sensory feedback ("smoothed")
        fbk_smoothed_p = nest.Create("diff_neuron_nestml", N)
        nest.SetStatus(fbk_smoothed_p, {"kp": pops_params["fbk_smoothed"]["kp"], "pos": True, "buffer_size": pops_params["fbk_smoothed"]["buffer_size"], "base_rate": pops_params["fbk_smoothed"]["base_rate"], "simulation_steps": len(time_vect)})
        fbk_smoothed_n = nest.Create("diff_neuron_nestml", N)
        nest.SetStatus(fbk_smoothed_n, {"kp": pops_params["fbk_smoothed"]["kp"], "pos": False, "buffer_size": pops_params["fbk_smoothed"]["buffer_size"], "base_rate": pops_params["fbk_smoothed"]["base_rate"], "simulation_steps": len(time_vect)})
        
        nest.Connect(sn_p[j].pop, fbk_smoothed_p, "all_to_all", syn_spec={"weight": conn_params["sn_fbk_smoothed"]["weight"], "delay": conn_params["sn_fbk_smoothed"]["delay"]})

        nest.Connect(sn_n[j].pop, fbk_smoothed_n, "all_to_all", syn_spec={"weight": -conn_params["sn_fbk_smoothed"]["weight"], "delay": conn_params["sn_fbk_smoothed"]["delay"]})

        # Positive neurons
        for i, pre in enumerate(fbk_smoothed_p):
            for k, post in enumerate(stEst.pops_p[j].pop):
                nest.Connect(pre, post, "one_to_one", syn_spec = {"weight": 1.0, "receptor_type": i + 1})

        for i, pre in enumerate(prediction_p):
            for k, post in enumerate(stEst.pops_p[j].pop):
                nest.Connect(pre, post, "one_to_one", syn_spec = {"weight": 1.0, "receptor_type": i + 1 + N})
        

        # Negative neurons
        for i, pre in enumerate(fbk_smoothed_n):
            for k, post in enumerate(stEst.pops_n[j].pop):
                nest.Connect(pre, post, "one_to_one", syn_spec = {"weight": 1.0, "receptor_type": i + 1})

        for i, pre in enumerate(prediction_n):
            for k, post in enumerate(stEst.pops_n[j].pop):
                nest.Connect(pre, post, "one_to_one", syn_spec = {"weight": 1.0, "receptor_type": i + 1 + N})
    else:

        # Positive neurons
        #nest.Connect(sn_p[j].pop, stEst.pops_p[j].pop, "all_to_all", syn_spec=conn_params["sn_state"])
        for i, pre in enumerate(sn_p[j].pop):
            for k, post in enumerate(stEst.pops_p[j].pop):
                nest.Connect(pre, post, "one_to_one", syn_spec = {"weight": conn_params["sn_state"]["weight"], "receptor_type": i + 1})
        # Negative neurons
        
        for i, pre in enumerate(sn_n[j].pop):
            for k, post in enumerate(stEst.pops_n[j].pop):
                nest.Connect(pre, post, "one_to_one", syn_spec = {"weight": conn_params["sn_state"]["weight"], "receptor_type": i + 1})
#print(type(stEst.pops_p[0].pop))
#print(nest.GetConnections(target = stEst.pops_p[j].pop))
print("init connections feedback")
'''
#%% CONNECTIONS
'''
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

#### Connection State Estimator - Motor Cortex feedback (Inhibitory)
wgt_stEst_mtxFbk = conn_params["state_mc_fbk"]["weight"]


'''
nest.Connect(mc.out_p[cereb_controlled_joint].pop, motor_commands_p, "all_to_all", syn_spec={"weight": conn_params["mc_out_motor_commands"]["weight"], "delay": conn_params["mc_out_motor_commands"]["delay"]})
nest.Connect(mc.out_n[cereb_controlled_joint].pop, motor_commands_n, "all_to_all", syn_spec={"weight": -conn_params["mc_out_motor_commands"]["weight"], "delay": conn_params["mc_out_motor_commands"]["delay"]})
''
nest.Connect(motor_commands_p, cerebellum_forw.Nest_Mf[-n_forw:], {'rule': 'one_to_one'},syn_spec={'weight':1.0})
nest.Connect(motor_commands_n, cerebellum_forw.Nest_Mf[0:n_forw], {'rule': 'one_to_one'},syn_spec={'weight':1.0})#TODO add weight

# Scale the feedback signal to 0-60 Hz in order to be suitable for the cerebellum
feedback_p = nest.Create("diff_neuron", N)
nest.SetStatus(feedback_p, {"kp": pops_params["feedback"]["kp"], "pos": True, "buffer_size": pops_params["feedback"]["buffer_size"], "base_rate": pops_params["feedback"]["base_rate"]})
feedback_n = nest.Create("diff_neuron", N)
nest.SetStatus(feedback_n, {"kp": pops_params["feedback"]["kp"], "pos": False, "buffer_size": pops_params["feedback"]["buffer_size"], "base_rate": pops_params["feedback"]["base_rate"]})

nest.Connect(sn_p[cereb_controlled_joint].pop, feedback_p, 'all_to_all', syn_spec={"weight": conn_params["sn_fbk_smoothed"]["weight"], "delay": conn_params["sn_fbk_smoothed"]["delay"]})
nest.Connect(sn_n[cereb_controlled_joint].pop, feedback_n, 'all_to_all', syn_spec={"weight": -conn_params["sn_fbk_smoothed"]["weight"], "delay": conn_params["sn_fbk_smoothed"]["delay"]})
'''

# Connect state estimator (bayesian) to the Motor Cortex
for j in range(njt):
    nest.Connect(stEst.pops_p[j].pop,mc.fbk_p[j].pop, "one_to_one", {"weight": wgt_stEst_mtxFbk, "delay": res})
    nest.Connect(stEst.pops_p[j].pop,mc.fbk_n[j].pop, "one_to_one", {"weight": wgt_stEst_mtxFbk, "delay": res})
    nest.Connect(stEst.pops_n[j].pop,mc.fbk_p[j].pop, "one_to_one", {"weight": -wgt_stEst_mtxFbk, "delay": res})
    nest.Connect(stEst.pops_n[j].pop,mc.fbk_n[j].pop, "one_to_one", {"weight": -wgt_stEst_mtxFbk, "delay": res})

# BRAIN STEM
brain_stem_new_p=[]
brain_stem_new_n=[]


for j in range(njt):
    # Positive neurons
    tmp_p = nest.Create ("basic_neuron_nestml", N)
    nest.SetStatus(tmp_p, {"kp": pops_params["brain_stem"]["kp"], "pos": True, "buffer_size": pops_params["brain_stem"]["buffer_size"], "base_rate": pops_params["brain_stem"]["base_rate"], "simulation_steps": len(time_vect)})
    brain_stem_new_p.append( PopView(tmp_p, time_vect) )
    # Negative neurons
    tmp_n = nest.Create ("basic_neuron_nestml", N)
    nest.SetStatus(tmp_n, {"kp": pops_params["brain_stem"]["kp"], "pos": False, "buffer_size": pops_params["brain_stem"]["buffer_size"], "base_rate": pops_params["brain_stem"]["base_rate"], "simulation_steps": len(time_vect)})
    brain_stem_new_n.append( PopView(tmp_n, time_vect) )


for j in range(njt):
    nest.Connect(mc.out_p[j].pop,brain_stem_new_p[j].pop, "all_to_all", {"weight": conn_params["mc_out_brain_stem"]["weight"], "delay": conn_params["mc_out_brain_stem"]["delay"]})
    # nest.Connect(stEst.pops_p[j].pop,mc.fbk_n[j].pop, "one_to_one", {"weight": wgt_stEst_mtxFbk, "delay": res})
    # nest.Connect(stEst.pops_n[j].pop,mc.fbk_p[j].pop, "one_to_one", {"weight": -wgt_stEst_mtxFbk, "delay": res})
    nest.Connect(mc.out_n[j].pop,brain_stem_new_n[j].pop, "all_to_all", {"weight": -conn_params["mc_out_brain_stem"]["weight"], "delay": conn_params["mc_out_brain_stem"]["delay"]})

'''
# feedback from sensory
feedback_inv_p = nest.Create("diff_neuron", N)
nest.SetStatus(feedback_inv_p, {"kp": pops_params["feedback_inv"]["kp"], "pos": True, "buffer_size": pops_params["feedback_inv"]["buffer_size"], "base_rate": pops_params["feedback_inv"]["base_rate"]})
feedback_inv_n = nest.Create("diff_neuron", N)
nest.SetStatus(feedback_inv_n, {"kp": pops_params["feedback_inv"]["kp"], "pos": False, "buffer_size": pops_params["feedback_inv"]["buffer_size"], "base_rate": pops_params["feedback_inv"]["base_rate"]})
'''

#%% MUSIC CONFIG

msc = MusicCfg()

#### MUSIC output port (with nTot channels)
proxy_out = nest.Create('music_event_out_proxy', 1, params = {'port_name':'mot_cmd_out'})

ii=0
for j in range(njt):
    for i, n in enumerate(brain_stem_new_p[j].pop):
        nest.Connect(n, proxy_out, "one_to_one",{'music_channel': ii})
        ii=ii+1
    for i, n in enumerate(brain_stem_new_n[j].pop):
        nest.Connect(n, proxy_out, "one_to_one",{'music_channel': ii})
        ii=ii+1


#### MUSIC input ports (nTot ports with one channel each)
proxy_in = nest.Create ('music_event_in_proxy', nTot, params = {'port_name': 'fbk_in'})
for i, n in enumerate(proxy_in):
    nest.SetStatus(n, {'music_channel': i})

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

spikedetector_fbk_pos = nest.Create("spike_recorder", params={"label": "Feedback pos"})
spikedetector_fbk_neg = nest.Create("spike_recorder", params={"label": "Feedback neg"})

'''
spikedetector_fbk_inv_pos = nest.Create("spike_recorder", params={"withgid": True,"withtime": True, "to_file": True, "label": "Feedback inv pos"})
spikedetector_fbk_inv_neg = nest.Create("spike_recorder", params={"withgid": True,"withtime": True, "to_file": True, "label": "Feedback inv neg"})

spikedetector_fbk_cereb_pos = nest.Create("spike_recorder", params={"withgid": True,"withtime": True, "to_file": True, "label": "Feedback cerebellum pos"})
spikedetector_fbk_cereb_neg = nest.Create("spike_recorder", params={"withgid": True,"withtime": True, "to_file": True, "label": "Feedback cerebellum neg"})
spikedetector_io_forw_input_pos = nest.Create("spike_recorder", params={"withgid": True,"withtime": True, "to_file": True, "label": "Input inferior Olive Forw pos"})
spikedetector_io_forw_input_neg = nest.Create("spike_recorder", params={"withgid": True,"withtime": True, "to_file": True, "label": "Input inferior Olive Forw neg"})

spikedetector_io_inv_input_pos = nest.Create("spike_recorder", params={"withgid": True,"withtime": True, "to_file": True, "label": "Input inferior Olive Inv pos"})
spikedetector_io_inv_input_neg = nest.Create("spike_recorder", params={"withgid": True,"withtime": True, "to_file": True, "label": "Input inferior Olive Inv neg"})
'''
spikedetector_stEst_pos = nest.Create("spike_recorder", params={"label": "State estimator pos"})
spikedetector_stEst_neg = nest.Create("spike_recorder", params={"label": "State estimator neg"})

spikedetector_planner_pos = nest.Create("spike_recorder", params={"label": "Planner pos"})
spikedetector_planner_neg = nest.Create("spike_recorder", params={"label": "Planner neg"})

#spikedetector_pred_pos = nest.Create("spike_recorder", params={"withgid": True,"withtime": True, "to_file": True, "label": "Cereb pred pos"})
#spikedetector_pred_neg = nest.Create("spike_recorder", params={"withgid": True,"withtime": True, "to_file": True, "label": "Cereb pred neg"})
#spikedetector_motor_pred_pos = nest.Create("spike_recorder", params={"withgid": True,"withtime": True, "to_file": True, "label": "Cereb motor pred pos"})
#spikedetector_motor_pred_neg = nest.Create("spike_recorder", params={"withgid": True,"withtime": True, "to_file": True, "label": "Cereb motor pred neg"})
#spikedetector_stEst_max_pos = nest.Create("spike_recorder", params={"withgid": True,"withtime": True, "to_file": True, "label": "State estimator Max pos"})
#spikedetector_stEst_max_neg = nest.Create("spike_recorder", params={"withgid": True,"withtime": True, "to_file": True, "label": "State estimator Max neg"})
spikedetector_fbk_smoothed_pos = nest.Create("spike_recorder", params={"label": "Feedback smoothed pos"})
spikedetector_fbk_smoothed_neg = nest.Create("spike_recorder", params={"label": "Feedback smoothed neg"})

spikedetector_brain_stem_pos = nest.Create("spike_recorder", params={"label": "Brain stem pos"})
spikedetector_brain_stem_neg = nest.Create("spike_recorder", params={"label": "Brain stem neg"})

nest.Connect(brain_stem_new_p[j].pop, spikedetector_brain_stem_pos)
nest.Connect(brain_stem_new_n[j].pop, spikedetector_brain_stem_neg)


nest.Connect(sn_p[cereb_controlled_joint].pop, spikedetector_fbk_pos)
nest.Connect(sn_n[cereb_controlled_joint].pop, spikedetector_fbk_neg)
#nest.Connect(feedback_p, spikedetector_fbk_cereb_pos)
#nest.Connect(feedback_n, spikedetector_fbk_cereb_neg)

nest.Connect(planner.pops_p[cereb_controlled_joint].pop, spikedetector_planner_pos)
nest.Connect(planner.pops_n[cereb_controlled_joint].pop, spikedetector_planner_neg)
'''
nest.Connect(stEst.pops_p[cereb_controlled_joint].pop, spikedetector_stEst_max_pos)
nest.Connect(stEst.pops_n[cereb_controlled_joint].pop, spikedetector_stEst_max_neg)
'''


###################### SIMULATE ######################
'''
# Disable Cerebellar prediction in State estimation 
conns_pos_forw = nest.GetConnections(source = prediction_p, target = stEst.pops_p[cereb_controlled_joint].pop)
conns_neg_forw = nest.GetConnections(source = prediction_n, target = stEst.pops_n[cereb_controlled_joint].pop)

# set connection to zero
if cerebellum_application_forw != 0:
    nest.SetStatus(conns_pos_forw, {"weight": 0.0})
    nest.SetStatus(conns_neg_forw, {"weight": 0.0})
'''

#%% SIMULATE ######################
#nest.SetKernelStatus({"data_path": pthDat})
#total_len = int(time_span + time_pause)
total_len = int(time_span)
for trial in range(n_trial):
    if mpi4py.MPI.COMM_WORLD.rank == 0:
        print('Simulating trial {} lasting {} ms'.format(trial+1,total_len))
    nest.Simulate(total_len)



#%% PLOTTING
if mpi4py.MPI.COMM_WORLD.rank == 0:
    lgd = ['theta']
    time_vect_paused = np.linspace(0, total_len*n_trial, num=int(np.round(total_len/res)), endpoint=True)

    # Positive
    fig, ax = plt.subplots(1,1)
    for i in range(njt):
        planner.pops_p[i].plot_rate(time_vect_paused,ax=ax,bar=True,color='r',label='planner')
        sn_p[i].plot_rate(time_vect_paused,ax=ax,bar=False,title=lgd[i]+" (Hz)",color='b',label='sensory')
        stEst.pops_p[i].plot_rate(time_vect_paused,buffer_sz=5,ax=ax,bar=False,title=lgd[i]+" (Hz)",color='b',linestyle=':', label='state pos')
    ax.legend()
    ax.set_xlabel("time (ms)")
    plt.suptitle("Positive")
    if saveFig:
        plt.savefig(pathFig+"populations_pos.png")

    # Negative
    fig, ax = plt.subplots(1,1)
    for i in range(njt):
        planner.pops_n[i].plot_rate(time_vect_paused,ax=ax,bar=False,color='b',label='planner')
        sn_n[i].plot_rate(time_vect_paused,ax=ax,bar=False,title=lgd[i]+" (Hz)",color='b',label='sensory')
        stEst.pops_n[i].plot_rate(time_vect_paused,buffer_sz=5,ax=ax,bar=False,title=lgd[i]+" (Hz)",color='b',linestyle=':', label='state neg')
        ax.legend()
    ax.set_xlabel("time (ms)")
    plt.suptitle("Negative")
    if saveFig:
        plt.savefig(pathFig+"populations_neg.png")
    
    # # MC fbk
    for i in range(njt):
        plotPopulation(time_vect_paused, mc.fbk_p[i],mc.fbk_n[i], title=lgd[i],buffer_size=10)
        plt.suptitle("MC fbk")
        plt.xlabel("time (ms)")
        if saveFig:
            plt.savefig(pathFig+"mtctx_fbk_"+lgd[i]+".png")
    
    # # MC ffwd
    for i in range(njt):
        plotPopulation(time_vect_paused, mc.ffwd_p[i],mc.ffwd_n[i], title=lgd[i],buffer_size=10)
        plt.suptitle("MC ffwd")
        plt.xlabel("time (ms)")
        if saveFig:
            plt.savefig(pathFig+"mtctx_ffwd_"+lgd[i]+".png")
    # MC out
    for i in range(njt):
        plotPopulation(time_vect_paused, mc.out_p[i],mc.out_n[i], title=lgd[i],buffer_size=10)
        plt.suptitle("MC out")
        plt.xlabel("time (ms)")
        if saveFig:
            plt.savefig(pathFig+"mtctx_out_"+lgd[i]+".png")


    lgd = ['theta']
    
    ## Planner
    for i in range(njt):
        plotPopulation(time_vect_paused, planner.pops_p[i],planner.pops_n[i], title=lgd[i],buffer_size=15)
        plt.suptitle("Planner")
        if saveFig:
            plt.savefig(pathFig+"planner_"+lgd[i]+".png")
    '''      
    ## Brainstem
    fig, ax = plt.subplots(1,1)
    for i in range(njt):
        brain_stem_new_p[i].plot_rate(time_vect_paused,ax=ax,bar=True,color='r',label='brainstem')
        #sn_p[i].plot_rate(time_vect_paused,ax=ax,bar=False,title=lgd[i]+" (Hz)",color='b',label='sensory')
        # stEst.out_p[i].plot_rate(time_vect_paused,buffer_sz=5,ax=ax[i],bar=False,title=lgd[i]+" (Hz)",color='b',linestyle=':', label='state pos')
    ax.legend()
    ax.set_xlabel("time (ms)")
    plt.suptitle("Positive")
    if saveFig:
        plt.savefig(pathFig+"brainstem_pos.png")
    
    fig, ax = plt.subplots(1,1)
    for i in range(njt):
        brain_stem_new_n[i].plot_rate(time_vect_paused,ax=ax,bar=True,color='b',label='brainstem')
        #sn_p[i].plot_rate(time_vect_paused,ax=ax,bar=False,title=lgd[i]+" (Hz)",color='b',label='sensory')
        # stEst.out_p[i].plot_rate(time_vect_paused,buffer_sz=5,ax=ax[i],bar=False,title=lgd[i]+" (Hz)",color='b',linestyle=':', label='state pos')
    ax.legend()
    ax.set_xlabel("time (ms)")
    plt.suptitle("Negative")
    if saveFig:
        plt.savefig(pathFig+"brainstem_neg.png")
    '''
    # Brainstem
    for i in range(njt):
        events_bs_pos = nest.GetStatus(spikedetector_brain_stem_pos, keys="events")[0]
        evs_p = events_bs_pos["senders"]
        ts_p = events_bs_pos["times"]
        
        events_bs_neg = nest.GetStatus(spikedetector_brain_stem_neg, keys="events")[0]
        evs_n = events_bs_neg["senders"]
        ts_n = events_bs_neg["times"]
        
        y_p =   evs_p - brain_stem_new_p[i].pop[0].get("global_id") + 1
        y_n = -(evs_n - brain_stem_new_n[i].pop[0].get("global_id") + 1)
        
        fig, ax = plt.subplots(2,1,sharex=True)
        ax[0].scatter(ts_p, y_p, marker='.', s=1,c="r")
        ax[0].scatter(ts_n, y_n, marker='.', s=1)
        ax[0].set_ylabel("raster")
        brain_stem_new_p[i].plot_rate(time_vect_paused, 15, ax=ax[1],color="r")
        brain_stem_new_n[i].plot_rate(time_vect_paused, 15, ax=ax[1], title='PSTH (Hz)')
        ax[0].set_title(lgd[0])
        ax[0].set_ylim( bottom=-(len(brain_stem_new_n[i].pop)+1), top=len(brain_stem_new_p[i].pop)+1 )
        plt.suptitle("Brainstem")
        if saveFig:
            plt.savefig(pathFig+"brainstem_"+lgd[i]+".png")

    # Sensory feedback
    for i in range(njt):
        plotPopulation(time_vect_paused, sn_p[i], sn_n[i], title=lgd[i],buffer_size=15)
        plt.suptitle("Sensory feedback")
        if saveFig:
            plt.savefig(pathFig+"sensory_"+lgd[i]+".png")
    
    lgd = ['x','y']
    
    # State estimator
    for i in range(njt):
        plotPopulation(time_vect_paused, stEst.pops_p[i],stEst.pops_n[i], title=lgd[i],buffer_size=15)
        plt.suptitle("State estimator")
        if saveFig:
            plt.savefig(pathFig+"stateEst_"+lgd[i]+".png")

    lgd = ['theta']
    for i in range(njt):
        fig, ax = plt.subplots(2,1, figsize=(10,10))
        ax[0].plot(time_vect,trj, linewidth=5)
        ax[0].set_title('Trajectory [theta]')
        ax[0].set_xlabel('Time [ms]')
        ax[1].plot(time_vect,motorCommands, linewidth=5)
        ax[1].set_title('Motor command')
        ax[1].set_xlabel('Time [ms]')
        if saveFig:
            plt.savefig(pathFig+'_'+"motor_commands"+lgd[i]+".png")
    #
    #

'''
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
    '''
    #plt.savefig("mctx_out_pos-neg.png")

# ## Collapsing data files into one file
# names = []
# network_neurons = ["Input inferior Olive Forw pos","Input inferior Olive Forw neg","Input inferior Olive Inv pos","Input inferior Olive Inv neg","Feedback pos","Feedback neg","State estimator pos","State estimator neg","Planner pos","Planner neg","Feedback cerebellum pos","Feedback cerebellum neg","mc_out_p_0","mc_out_n_0","mc_out_p_1","mc_out_n_1","sens_fbk_0_p","sens_fbk_0_n","sens_fbk_1_p","sens_fbk_1_n","Cereb motor pred pos","Cereb motor pred neg","Cereb pred pos","Cereb pred neg","State estimator Max pos","State estimator Max neg","Feedback smoothed pos","Feedback smoothed neg"]
# cereb_neurons = ["granule_cell","golgi_cell","dcn_cell_glut_large","purkinje_cell","basket_cell","stellate_cell","dcn_cell_GABA","mossy_fibers",'io_cell',"glomerulus","dcn_cell_Gly-I"]

# for t in tags:
#     for n in cereb_neurons:
#         names.append(t + '_' + n)
#     #print(names.append(t + '_' + n))
# names.extend(network_neurons)

# files = [f for f in os.listdir(pthDat) if os.path.isfile(os.path.join(pthDat,f))]


# # if mpi4py.MPI.COMM_WORLD.rank == 0:
# #     file_list = []
# #     for name in names:
# #         if (name + '_spikes' + '.gdf' not in files):
# #             for f in files:
# #                 if (f.startswith(name)):
# #                     file_list.append(f)
# #             print(file_list)
# #             with open(pthDat + name + ".gdf", "w") as wfd:
# #                 for f in file_list:
# #                     with open(pthDat + f, "r") as fd:
# #                         wfd.write(fd.read())
# #             for f in file_list:
# #                 os.remove(pthDat+f)
# #             file_list = []
# #         else:
# #             print('Già fatto')
# #     print('Collapsing files ended')
