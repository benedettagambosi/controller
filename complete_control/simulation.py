import numpy as np
import nest
import os
import matplotlib.pyplot as plt
# Adjust env vars to be able to import the NESTML-generated module
ld_lib_path = os.environ.get('LD_LIBRARY_PATH', '')
new_path = ld_lib_path + ":"+"../nestml/target"
os.environ['LD_LIBRARY_PATH'] = new_path

import json

####### NETWORK SETUP
# Load parameters from file
f = open('new_params.json')
params = json.load(f)
f.close()

mc_params = params["modules"]["motor_cortex"]
plan_params = params["modules"]["planner"]
pops_params = params["pops"]
conn_params = params["connections"]

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

### Install NESTML-generated module
nest.Install("controller_module")

### PLANNER: create and initialize the Planner population
# Input: target --> minimum jerk trajectory
# Output: spikes (firing rate proportional to elbow angle)
for i in range(njt):
    planner_p = nest.Create("tracking_neuron_nestml", n=N, params={"kp": plan_params["kp"], "base_rate": plan_params["base_rate"], "pos": True, "traj": trj, "simulation_steps": len(trj)})

    planner_n = nest.Create("tracking_neuron_nestml", n=N, params={"kp": plan_params["kp"], "base_rate": plan_params["base_rate"], "pos": False, "traj": trj, "simulation_steps": len(trj)})


### FEEDFORWARD MOTOR CORTEX: create and initialize the Motor cortex populationù
# Input: target --> double derivative + inverse dynamics --> torque to be applied to elbow joint (motor command)
# Output: spikes (firing rate proportional to torque)
for i in range(njt):
    motor_p = nest.Create("tracking_neuron_nestml", n=N, params={"kp":mc_params["ffwd_kp"], 'base_rate':mc_params['ffwd_base_rate'], 'pos': True, 'traj': motorCommands, 'simulation_steps': len(motorCommands)})

    motor_n = nest.Create("tracking_neuron_nestml", n=N, params={'kp':mc_params["ffwd_kp"], 'base_rate':mc_params['ffwd_base_rate'], 'pos': False, 'traj': motorCommands, 'simulation_steps': len(motorCommands)})

### BRAINSTEM
# Input: spikes from FFWD motor cortex
# Output: smoothed profile of firing rate over time
for j in range(njt):
    # Positive neurons
    brainstem_p = nest.Create ("basic_neuron_nestml", N)
    nest.SetStatus(brainstem_p, {"kp": pops_params["brain_stem"]["kp"], "pos": True, "buffer_size": pops_params["brain_stem"]["buffer_size"], "base_rate": pops_params["brain_stem"]["base_rate"], "simulation_steps": len(time_vect)})
    # Negative neurons
    brainstem_n = nest.Create ("basic_neuron_nestml", N)
    nest.SetStatus(brainstem_n, {"kp": pops_params["brain_stem"]["kp"], "pos": False, "buffer_size": pops_params["brain_stem"]["buffer_size"], "base_rate": pops_params["brain_stem"]["base_rate"], "simulation_steps": len(time_vect)})

### Connections between FFWD MC and brainstem
for j in range(njt):
    nest.Connect(motor_p, brainstem_p, "all_to_all", {"weight": conn_params["mc_out_brain_stem"]["weight"], "delay": conn_params["mc_out_brain_stem"]["delay"]})

    nest.Connect(motor_n ,brainstem_n, "all_to_all", {"weight": -conn_params["mc_out_brain_stem"]["weight"], "delay": conn_params["mc_out_brain_stem"]["delay"]})

### DEVICES
spikedetector_planner_pos = nest.Create("spike_recorder", params={"label": "Planner pos"})
spikedetector_planner_neg = nest.Create("spike_recorder", params={"label": "Planner neg"})

spikedetector_brain_stem_pos = nest.Create("spike_recorder", params={"label": "Brain stem pos"})
spikedetector_brain_stem_neg = nest.Create("spike_recorder", params={"label": "Brain stem neg"})

spikedetector_motor_cortex_pos = nest.Create("spike_recorder", params={"label": "Motor cortex pos"})
spikedetector_motor_cortex_neg = nest.Create("spike_recorder", params={"label": "Motor cortex neg"})

nest.Connect(planner_p, spikedetector_planner_pos)
nest.Connect(planner_n, spikedetector_planner_neg)

nest.Connect(brainstem_p, spikedetector_brain_stem_pos)
nest.Connect(brainstem_n, spikedetector_brain_stem_neg)

nest.Connect(motor_p, spikedetector_motor_cortex_pos)
nest.Connect(motor_n, spikedetector_motor_cortex_neg)

########## SIMULATION #############
for trial in range(n_trial):
   nest.Simulate(time_span)

########## COMPUTE OUTPUT (net firing rate)
bs_data_p = nest.GetStatus(spikedetector_brain_stem_pos, keys= "events")[0]
spikes_p = bs_data_p["times"]
bs_data_n = nest.GetStatus(spikedetector_brain_stem_neg, keys= "events")[0]
spikes_n = bs_data_n["times"]
w = 1.0625540740843757
buffer_size = 10 #[ms]
scale   = 350.0
def computeRate(spikes, w, nNeurons, time_vector, buffer_size):
    rates = []
    for t in time_vector: 
        count = 0
        rate  = 0
        timeSt = t - buffer_size
        timeEnd = t
        if len(spikes)>0:
            tmp = np.array(spikes)
            idx = np.bitwise_and(tmp>=timeSt, tmp<timeEnd)
            count = w*np.sum(idx)
            rate = (count/((timeEnd-timeSt)*nNeurons))
        rates.append(rate)
    return np.array(rates)

spkRate_pos = computeRate(spikes_p, w, N, time_vect, buffer_size)
spkRate_neg = computeRate(spikes_n, w, N, time_vect, buffer_size)
spkRate_net = spkRate_pos - spkRate_neg
inputCmd = spkRate_net/ scale

np.savetxt('output_firing_rate.txt', inputCmd)
