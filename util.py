__authors__ = "Cristiano Alessandro"
__copyright__ = "Copyright 2021"
__credits__ = ["Cristiano Alessandro"]
__license__ = "GPL"
__version__ = "1.0.1"

import numpy as np
import matplotlib.pyplot as plt

# Save pattern into file
def savePattern(pattern, file_bas):

    nj = pattern.shape[1]

    for i in range(nj):
        cmd_file = file_bas + "_" + str(i) + ".dat"
        a_file = open(cmd_file, "w")
        np.savetxt( a_file, pattern[:,i] )
        a_file.close()


# # Plot positive and negative population
# def plotPopulation(time_v, pop_pos, pop_neg, title='',buffer_size=15):
#     evs_p, ts_p = pop_pos.get_events()
#     evs_n, ts_n = pop_neg.get_events()
#
#     y_p =   evs_p - pop_pos.pop[0] + 1
#     y_n = -(evs_n - pop_neg.pop[0] + 1)
#
#     fig, ax = plt.subplots(2,1,sharex=True)
#     ax[0].scatter(ts_p, y_p, marker='.', s=1,c="r")
#     ax[0].scatter(ts_n, y_n, marker='.', s=1)
#     ax[0].set_ylabel("raster")
#     pop_pos.plot_rate(time_v, buffer_size, ax=ax[1],color="r")
#     pop_neg.plot_rate(time_v, buffer_size, ax=ax[1], title='PSTH (Hz)')
#     ax[0].set_title(title)
#     ax[0].set_ylim( bottom=-(len(pop_neg.pop)+1), top=len(pop_pos.pop)+1 )
#
#     return fig, ax

def AddPause(signal, pause_len, res):
    # Add a pause at the end of the signal pattern
    signal_list = list(signal)
    signal_list.extend([0]*int(pause_len/res))

    return np.array(signal_list)

import plotly.graph_objects as go
import plotly.express as ex
import numpy as np
import os

def set_nest_vars_mac():

    nest_install_dir = "/Users/Benedetta/opt/anaconda3/envs/nest"
    os.environ["NEST_DATA_DIR"]=nest_install_dir+"/share/nest"
    os.environ["NEST_DOC_DIR"]=nest_install_dir+"/share/doc/nest"
    os.environ["NEST_MODULE_PATH"]=nest_install_dir+"/lib/nest"
    os.environ["NEST_PYTHON_PREFIX"]=nest_install_dir+"/lib/python3.8/site-packages"
    os.environ["SLI_PATH"]=nest_install_dir+"/share/nest/sli"
    os.environ["DYLD_LIBRARY_PATH"]=nest_install_dir+"/lib/nest:$DYLD_LIBRARY_PATH"
    os.environ["LD_LIBRARY_PATH"]=nest_install_dir+"/lib/nest:$LD_LIBRARY_PATH"
    os.environ["PATH"] += os.pathsep + nest_install_dir
    #os.environ["PATH"]=nest_install_dir+"/bin:$PATH"
    #os.environ["PYTHONPATH"]="$NEST_PYTHON_PREFIX${PYTHONPATH:+:$PYTHONPATH}"
    os.environ["PYTHONPATH"] = nest_install_dir+"/lib/python3.8/site-packages"

#
# class Input_signal:
#     def __init__(self, n, pathData, filename, time_vect, **kwargs):
#         import nest
#         set_nest_vars_mac()
#         self.time_vect = time_vect
#
#         # Path where to save the data file
#         self.pathData = pathData
#
#         # General parameters of neurons
#         params = {
#             "base_rate": 0.0,
#             "kp": 1.0,
#             "repeatable": True,
#             }
#         params.update(kwargs)
#
#         # Initialize population arrays
#         self.pops_p = []
#         self.pops_n = []
#
#         # Create populations
#         file_pattern = self.pathData+filename
#
#         # Positive population (joint i)
#         tmp_pop_p = nest.Create("tracking_neuron", n=n, params=params)
#         nest.SetStatus(tmp_pop_p, {"pos": True, "pattern_file": file_pattern})
#         self.pops_p = PopView(tmp_pop_p,self.time_vect)
#
#         # Negative population (joint i)
#         tmp_pop_n = nest.Create("tracking_neuron", n=n, params=params)
#         nest.SetStatus(tmp_pop_n, {"pos": False, "pattern_file": file_pattern})
#         self.pops_n = PopView(tmp_pop_n,self.time_vect)

def plot_activity_pos_neg(freq_pos, freq_neg, mean_pos, mean_neg, time_vect,label, to_html = False, to_png = True, path=''):

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=time_vect, y=freq_pos, name="positive",mode="lines", line=dict(color="red")))
    fig.add_trace(go.Scatter(x=time_vect, y=freq_neg, name="negative",mode="lines", line=dict(color="blue")))
    fig.add_trace(go.Scatter(x=time_vect, y=mean_pos, name="mean pos",line=dict(color="red", dash="dash")))
    fig.add_trace(go.Scatter(x=time_vect, y=mean_neg, name="mean neg",line=dict(color="blue",dash="dash")))
    fig.update_layout(width=1200,
                    height=800,
                title={
                    'text': label,
                    'font' : {"size":36},
                    'y':0.95,
                    'x':0.5,
                    'xanchor': 'center',
                    'yanchor': 'top'},
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='#fcfcfc',
                font=dict(
                    size=24,
                    color="Black"
            )
        )

    fig.update_xaxes(title = "Time [ms]",
                linecolor="black",
                gridcolor = "#bfbfbf",
                mirror=True,
                ticks='outside',
                showline=True,
                title_standoff = 0
                )
    fig.update_yaxes(title = "Frequency [Hz]",
                    linecolor="black",
                    mirror=True,
                    ticks='outside',
                    showline=True,
                    gridcolor="#bfbfbf"
                    )
    if to_png:
        fig.write_image(path+label+".png")

    if to_html:
        fig.write_html(path+label+".html", include_plotlyjs='cdn')

    return fig

def plot_activity(freq, mean, time_vect, label, to_html = False, to_png = True, path=''):

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=time_vect, y=freq, name = "frequency",mode="lines", line=dict(color="red")))
    fig.add_trace(go.Scatter(x=time_vect, y=mean, name = "mean",line=dict(dash="dash",color="red")))
    fig.update_layout(width=1200,
                    height=800,
                title={
                    'text': label,
                    'font' : {"size":36},
                    'y':0.95,
                    'x':0.5,
                    'xanchor': 'center',
                    'yanchor': 'top'},
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='#fcfcfc',
                font=dict(
                    size=24,
                    color="Black"
            )
        )


    fig.update_xaxes(title = "Time [ms]",
                linecolor="black",
                gridcolor = "#bfbfbf",
                mirror=True,
                ticks='outside',
                showline=True,
                title_standoff = 0
                )
    fig.update_yaxes(title = "Frequency [Hz]",
                    linecolor="black",
                    mirror=True,
                    ticks='outside',
                    showline=True,
                    gridcolor="#bfbfbf"
                    )
    if to_png:
        fig.write_image(path+label+".png")

    if to_html:
        fig.write_html(path+label+".html", include_plotlyjs='cdn')

    return fig

def plot_simple(y, x, label, to_html = False, to_png = True, path=''):

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=y, name = "frequency",mode="lines", line=dict(color="blue")))
    fig.update_layout(width=1200,
                    height=800,
                title={
                    'text': label,
                    'font' : {"size":36},
                    'y':0.95,
                    'x':0.5,
                    'xanchor': 'center',
                    'yanchor': 'top'},
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='#fcfcfc',
                font=dict(
                    size=24,
                    color="Black"
            )
        )


    fig.update_xaxes(title = "Time [ms]",
                linecolor="black",
                gridcolor = "#bfbfbf",
                mirror=True,
                ticks='outside',
                showline=True,
                title_standoff = 0
                )
    fig.update_yaxes(title = "Frequency [Hz]",
                    linecolor="black",
                    mirror=True,
                    ticks='outside',
                    showline=True,
                    gridcolor="#bfbfbf"
                    )
    if to_png:
        fig.write_image(path+label+".png")

    if to_html:
        fig.write_html(path+label+".html", include_plotlyjs='cdn')

    return fig

def plot_activity_old(freq, mean, time_vect, label, show=False, to_html = False, to_png = True, path=''):

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=time_vect, y=freq, name = "frequency",mode="lines", line=dict(color="red")))
    fig.add_trace(go.Scatter(x=time_vect, y=mean, name = "mean",line=dict(dash="dash",color="red")))
    fig.update_layout(width=1200,
                    height=800,
                title={
                    'text': label,
                    'font' : {"size":36},
                    'y':0.95,
                    'x':0.5,
                    'xanchor': 'center',
                    'yanchor': 'top'},
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='#fcfcfc',
                font=dict(
                    size=24,
                    color="Black"
            )
        )

    if to_png:
        fig.update_xaxes(title = "Time [ms]",
                    linecolor="black",
                    gridcolor = "#bfbfbf",
                    mirror=True,
                    ticks='outside',
                    showline=True,
                    title_standoff = 0
                    )
        fig.update_yaxes(title = "Frequency [Hz]",
                        linecolor="black",
                        mirror=True,
                        ticks='outside',
                        showline=True,
                        gridcolor="#bfbfbf"
                        )

        fig.write_image(path+label+".png")

    if to_html or show:
        print("in show")
        fig.update_xaxes(title = "Time [ms]",
                        linecolor="black",
                        gridcolor = "#bfbfbf",
                        mirror=True,
                        ticks='outside',
                        showline=True,
                        title_standoff = 0,
                        rangeslider_visible=True)
        fig.update_yaxes(title = "Frequency [Hz]",
                        linecolor="black",
                        mirror=True,
                        ticks='outside',
                        showline=True,
                        gridcolor="#bfbfbf"
                        )

    if to_html:
        fig.write_html(path+label+".html", include_plotlyjs='cdn')
    if show:
        fig.show()
    return fig

def plot_scatter(evs, ts, type, label, to_html = False, to_png = True, path=''):
    y_min = np.min(evs)
    fig = go.Figure()
    if label in type.keys():
        fig.add_trace(go.Scatter(x=ts, y=evs-y_min, mode="markers",
                    marker=dict(color=["blue" if i in type[label]["positive"] else "red" for i in evs])))
    else:
        fig.add_trace(go.Scatter(x=ts, y=evs-y_min, mode="markers",
                    marker=dict(color="blue")))

    fig.update_layout(width=1200,
                    height=800,
                title={
                    'text': label,
                    'font' : {"size":36},
                    'y':0.95,
                    'x':0.5,
                    'xanchor': 'center',
                    'yanchor': 'top'},
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='#fcfcfc',
                font=dict(
                    size=24,
                    color="Black"
            )
        )

    fig.update_xaxes(title = "Time [ms]",
                linecolor="black",
                gridcolor = "#bfbfbf",
                mirror=True,
                ticks='outside',
                showline=True,
                title_standoff = 0
                )
    fig.update_yaxes(title = "Neuron id",
                    linecolor="black",
                    mirror=True,
                    ticks='outside',
                    showline=True,
                    gridcolor="#bfbfbf"
                    )
    if to_png:
        fig.write_image(path+label+".png")

    if to_html:
        fig.write_html(path+label+".html", include_plotlyjs='cdn')
    return fig

def read_gdf_data(cell_names,data_folder):

    files = [f for f in os.listdir(data_folder) if os.path.isfile(os.path.join(data_folder,f))]
    IDs = {}
    SD = {}
    times = {}
    for cell in cell_names:
        print('Reading:',cell)
        for f in files:
            if f.startswith(cell):
                break
        cell_f = open(data_folder+f,'r').read()
        cell_f = cell_f.split('\n')
        IDs[cell] = {}
        SD[cell] = {'evs': [], 'ts': []}
        for i in range(len(cell_f)-1):
            splitted_string = cell_f[i].split('\t')
            ID_cell = float(splitted_string[0])
            time_cell = float(splitted_string[1])
            SD[cell]['evs'].append(ID_cell)
            SD[cell]['ts'].append(time_cell)
            if str(ID_cell) in IDs[cell].keys():
                IDs[cell][str(ID_cell)].append(time_cell)
            else:
                IDs[cell][str(ID_cell)] = [time_cell]
    return SD, IDs

def collapse_gdf_data(names, pthDat):

    files = [f for f in os.listdir(pthDat) if os.path.isfile(os.path.join(pthDat,f))]
    file_list = []
    for name in names:
        if (name + '_spikes' + '.gdf' not in files):
            for f in files:
                if (f.startswith(name)):
                    file_list.append(f)
            print(file_list)
            with open(pthDat + name + ".gdf", "w") as wfd:
                for f in file_list:
                    with open(pthDat + f, "r") as fd:
                        wfd.write(fd.read())
            for f in file_list:
                os.remove(pthDat+f)
            file_list = []
        else:
            print('Già fatto')



def remove_files(data_folder):
    for f in os.listdir(data_folder):
        if '.gdf' in f or '.dat' in f:
            os.remove(data_folder+f)


def add_rect_pause(fig, len_trial, len_pause, n_trials):
    for i in range(1,1+n_trials):
        fig.add_vrect(x0=i*len_trial+len_pause*(i-1), x1=i*(len_trial+len_pause), line_width=0, fillcolor="grey", opacity=0.2)

def add_slider(fig):
    fig.update_xaxes(rangeslider_visible=True)

class neptune_manager():

    def __init__(self):
        import neptune.new as neptune

        self.run = neptune.init(
            project="",
            api_token="==",
        )
    def set_params(self, params):
        self.run["parameters"] = params

    def save_fig(self, fig, label):
        from neptune.new.types import File

        self.run["visuals/"+label] = File.as_html(fig)

    def save_file(self,data_folder=""):

        self.run["spiking results"].upload_files(data_folder+"*")
    def save_file_fig(self, fig_folder=""):
        self.run["figures"].upload_files(fig_folder+"*.png")

def fig_to_neptune(flag, fig, run, label):

    from neptune.new.types import File
    if flag:
        run["visuals/"+label] = File.as_html(fig)


def plot_errors(real_ee, n_trials, len_trial, len_mov, to_html=False,to_png=True,  path=""):
    lst = []
    ends = np.zeros([n_trials,2])

    pos = np.empty((n_trials,len_mov-1,2))
    fig = go.Figure()
    for i in range(n_trials):
        k_i = len_trial*i
        k_e = k_i+len_mov-1
        pos[i,:,0] = real_ee[k_i:k_e,0]
        pos[i,:,1] = real_ee[k_i:k_e,1]

        ends[i,0] = real_ee[k_e,0]
        ends[i,1] = real_ee[k_e,1]
        lst.append(i)

        fig.add_trace(go.Scatter(x=pos[i,:,0], y=pos[i,:,1],mode="lines", line=dict(color="black"),showlegend=False))
    fig.add_trace(go.Scatter(x=ends[:,0], y=ends[:,1], marker=dict(
                                                        size=10,
                                                        cmax=n_trials,
                                                        cmin=1,
                                                        color=lst,
                                                        colorbar=dict(
                                                            title="# trial"
                                                        ),
                                                        colorscale="Viridis")
                                                    ,mode="markers", name ="real"))

    fig.add_trace(go.Scatter(x=[0,1], y=[0,0.5], mode="lines", line=dict(dash = "dash",color="red"),showlegend=False))

    fig.add_trace(go.Scatter(x=[1], y=[0.5], name = "target",mode="markers", marker=dict(color="red", size = 10)))

    fig.update_traces(textposition='top center')


    fig.update_layout(width=800,
                    height=600,
                title={
                    'text': "Trajectories",
                    'font' : {"size":30},
                    'y':0.95,
                    'x':0.5,
                    'xanchor': 'center',
                    'yanchor': 'top'},
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='#fcfcfc',
                font=dict(
                    size= 18,
                    color="Black"
            ),
            legend=dict(
                    yanchor="top",
                    y=0.99,
                    xanchor="left",
                    x=0.01
)
        )


    fig.update_xaxes(title = "x [m]",
                linecolor="black",
                gridcolor = "#bfbfbf",
                mirror=True,
                ticks='outside',
                showline=True,
                title_standoff = 0
                )
    fig.update_yaxes(title = "y [m]",
                    linecolor="black",
                    mirror=True,
                    ticks='outside',
                    showline=True,
                    gridcolor="#bfbfbf"
                    )
    if to_png:
        fig.write_image(path+"traj.png")

    if to_html:
        fig.write_html(path+"traj.html", include_plotlyjs='cdn')

    return fig

def plot_error_trend(error, n_trials, to_html=False,to_png=True,  path=""):

    fig = go.Figure()

    fig.add_trace(go.Scatter(x=np.arange(1,n_trials+1), y=error, mode="markers+lines", marker=dict(color="red", size=10), line=dict(color="black")))


    fig.update_layout(width=800,
                    height=600,
                title={
                    'text': "Errors",
                    'font' : {"size":36},
                    'y':0.95,
                    'x':0.5,
                    'xanchor': 'center',
                    'yanchor': 'top'},
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='#fcfcfc',
                font=dict(
                    size=24,
                    color="Black"
            )
        )


    fig.update_xaxes(title = "Trial [#]",
                linecolor="black",
                gridcolor = "#bfbfbf",
                mirror=True,
                ticks='outside',
                showline=True,
                title_standoff = 0,
                tickmode = 'linear',
                tick0 = 0,
                dtick = 1
                )
    fig.update_yaxes(title = "Error [m]",
                    linecolor="black",
                    mirror=True,
                    ticks='outside',
                    showline=True,
                    gridcolor="#bfbfbf"
                    )
    if to_png:
        fig.write_image(path+"error.png")

    if to_html:
        fig.write_html(path+"error.html", include_plotlyjs='cdn')

    return fig
