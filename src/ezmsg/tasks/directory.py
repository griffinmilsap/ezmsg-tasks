import typing
from pathlib import Path

import ezmsg.core as ez

from ezmsg.panel.tabbedapp import TabbedApp, Tab

from ezmsg.sigproc.synth import EEGSynth, EEGSynthSettings
from ezmsg.sigproc.signalinjector import SignalInjector, SignalInjectorSettings
from ezmsg.sigproc.sampler import SampleMessage
from ezmsg.util.messages.axisarray import AxisArray

from ezmsg.panel.application import Application, ApplicationSettings
from ezmsg.panel.timeseriesplot import TimeSeriesPlot, TimeSeriesPlotSettings

from .task import Task, TaskSettings
from .cuedactiontask import CuedActionTask
from .ssvep.task import SSVEPTask
from .frequencymapper import FrequencyMapper, FrequencyMapperSettings
from .reaction import ReactionTask
from .ssaep import SSAEPTask


class TaskDirectory(ez.Collection, TabbedApp):

    CAT = CuedActionTask()
    SSVEP  = SSVEPTask()
    RXN = ReactionTask()
    SSAEP = SSAEPTask()

    @property
    def all_tasks(self) -> typing.List[Task]:
        return [
            self.CAT,
            self.SSVEP,
            self.RXN,
            self.SSAEP
        ]
    
    SETTINGS = TaskSettings

    SOURCE_PLOT = TimeSeriesPlot()

    INPUT_SIGNAL = ez.InputStream(AxisArray)
    OUTPUT_SAMPLE = ez.OutputStream(SampleMessage)

    OUTPUT_TARGET_CLASS = ez.OutputStream(typing.Optional[str])
    INPUT_CLASS = ez.InputStream(typing.Optional[str])

    def configure(self) -> None:
        self.SOURCE_PLOT.apply_settings(
            TimeSeriesPlotSettings(
                name = 'Signal Source',
            )
        )
        for task in self.all_tasks:
            task.apply_settings(self.SETTINGS)

    @property
    def title(self) -> str:
        return 'Task Directory'
    
    @property
    def tabs(self) -> typing.List[Tab]:
        return [
            self.SOURCE_PLOT, 
        ] + self.all_tasks
    
    def network(self) -> ez.NetworkDefinition:
        network = [
            (self.INPUT_SIGNAL, self.SOURCE_PLOT.INPUT_SIGNAL),
        ]

        network += [ 
            (self.INPUT_SIGNAL, task.INPUT_SIGNAL) 
            for task in self.all_tasks
        ]

        network += [
            (task.OUTPUT_SAMPLE, self.OUTPUT_SAMPLE)
            for task in self.all_tasks
        ]

        network += [
            (task.OUTPUT_TARGET_CLASS, self.OUTPUT_TARGET_CLASS)
            for task in self.all_tasks
            if hasattr(task, 'OUTPUT_TARGET_CLASS')
        ]

        network += [
            (self.INPUT_CLASS, task.INPUT_CLASS)
            for task in self.all_tasks
            if hasattr(task, 'INPUT_CLASS')
        ]

        return network
    

if __name__ == '__main__':

    import argparse

    parser = argparse.ArgumentParser(
        description = 'FBCSP Dashboard'
    )

    parser.add_argument( 
        '--data-dir',
        type = lambda x: Path(x).expanduser(),
        help = "Directory to store samples and models",
        default = Path.home() / 'ezmsg-tasks'
    )

    parser.add_argument(
        '--port',
        type = int,
        help = 'Port to run Panel dashboard server on (default: pick a random open port)',
        default = 0
    )

    class Args:
        data_dir: Path
        port: int

    args = parser.parse_args(namespace=Args)

    app = Application(
        ApplicationSettings(port = args.port)
    )

    synth = EEGSynth(
        EEGSynthSettings(
            fs = 250, 
            n_time = 50, 
            n_ch = 8
        )
    )

    freq_map = FrequencyMapper(
        FrequencyMapperSettings(
            mapping = {
                # CAT
                'GO': 15.0,
                'UP': 18.0,
                'DOWN': 20.0,
                'LEFT': 23.0,
                'RIGHT': 25.0,

                # SSVEP
                '7.14 Hz': 7.14,
                '8.33 Hz': 8.33,
                '10.00 Hz': 10.0,
                '12.50 Hz': 12.5,
                '16.67 Hz': 16.67,
                '25.00 Hz': 25.0,
            },
        )
    )

    injector = SignalInjector(
        SignalInjectorSettings(
            amplitude = 6.0,
            mixing_seed = 0xDEADBEEF,
        )
    )

    task_directory = TaskDirectory(
        TaskSettings(
            data_dir = args.data_dir,
            buffer_dur = 10.0,
        )
    )

    app.panels = {
        'task_directory': task_directory.app,
    }

    ez.run( 
        SYNTH = synth,
        FREQ_MAP = freq_map,
        INJECTOR = injector,
        TASK_DIRECTORY = task_directory,
        APP = app,
        connections = (
            (synth.OUTPUT_SIGNAL, injector.INPUT_SIGNAL),
            (injector.OUTPUT_SIGNAL, task_directory.INPUT_SIGNAL),
            (task_directory.OUTPUT_TARGET_CLASS, freq_map.INPUT_CLASS),
            (freq_map.OUTPUT_FREQUENCY, injector.INPUT_FREQUENCY)
        )
    )
