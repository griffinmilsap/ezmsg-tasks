import typing
import asyncio
import datetime
import random

import ezmsg.core as ez
import panel as pn

from ezmsg.sigproc.sampler import SampleTriggerMessage, SampleMessage
from ezmsg.util.messages.axisarray import AxisArray
from ezmsg.panel.tabbedapp import TabbedApp, Tab

from param.parameterized import Event

from .task import (
    Task,
    TaskSettings,
    TaskComplete,
    TaskImplementation,
    TaskImplementationState,
)
    

class CuedActionTaskImplementationState(TaskImplementationState):
    stimulus: pn.widgets.StaticText
    task_area: pn.layout.Card
    classes: pn.widgets.MultiChoice
    new_class: pn.widgets.TextInput
    add_new_class: pn.widgets.Button
    pre_run_duration: pn.widgets.FloatInput
    post_run_duration: pn.widgets.FloatInput
    trials_per_class: pn.widgets.IntInput
    trial_duration: pn.widgets.FloatInput
    intertrial_stimulus: pn.widgets.TextInput
    intertrial_min_dur: pn.widgets.FloatInput
    intertrial_max_dur: pn.widgets.FloatInput
    task_controls: pn.layout.WidgetBox

    input_class: asyncio.Queue[typing.Optional[str]]
    output_class: asyncio.Queue[typing.Optional[str]]

class CuedActionTaskImplementation(TaskImplementation):
    STATE = CuedActionTaskImplementationState

    INPUT_CLASS = ez.InputStream(typing.Optional[str])
    OUTPUT_TARGET_CLASS = ez.OutputStream(typing.Optional[str])
    
    @property
    def slug(self) -> str:
        """ Short-name used to identify recorded files """
        return 'CAT'
    
    @property
    def title(self) -> str:
        """ Title of task used in header of page """
        return 'Cued Action Task'
    
    async def initialize(self) -> None:
        await super().initialize()
        self.STATE.stimulus = pn.widgets.StaticText(
            styles = {
                'color': 'black',
                'font-family': 'Arial, sans-serif',
                'font-size': '5em',
                'font-weight': 'bold'
            },
        )

        self.STATE.task_area = pn.Card(
            pn.Column(
                pn.layout.VSpacer(),
                pn.Row(
                    pn.layout.HSpacer(),
                    self.STATE.stimulus,
                    pn.layout.HSpacer()
                ),
                pn.layout.VSpacer(),
                min_height = 600,
            ),
            styles = {'background': 'lightgray'},
            hide_header = True,
            sizing_mode = 'stretch_both'
        )

        sw = dict(sizing_mode = 'stretch_width')
        self.STATE.classes = pn.widgets.MultiChoice(name = 'Classes', **sw)
        self.STATE.new_class = pn.widgets.TextInput(value = 'GO', placeholder = 'New Class Name...', **sw)
        self.STATE.add_new_class = pn.widgets.Button(name = '+', width = 50, align = ('end', 'end'))
        def add_class(_: Event) -> None:
            new_class: typing.Optional[str] = self.STATE.new_class.value # type: ignore
            classes: typing.List[str] = self.STATE.classes.value # type: ignore
            classes_set = set(classes)
            if new_class:
                classes_set.add(new_class)
                classes = list(classes_set)
                self.STATE.classes.param.update(
                    value = classes, 
                    options = classes
                )
                
            self.STATE.new_class.value = ''
        self.STATE.add_new_class.on_click(add_class)

        self.STATE.trials_per_class = pn.widgets.IntInput(name = 'Trials per-class', value = 10, start = 1, **sw)
        self.STATE.pre_run_duration = pn.widgets.FloatInput(name = 'Pre-run (sec)', value = 3, start = 0, **sw)
        self.STATE.post_run_duration = pn.widgets.FloatInput(name = 'Post-run (sec)', value = 3, start = 0, **sw)

        self.STATE.trial_duration = pn.widgets.FloatInput(name = 'Trial dur. (sec)', value = 4.0, step = 0.1, start = 0.1, end = self.SETTINGS.buffer_dur, **sw)
        self.STATE.intertrial_min_dur = pn.widgets.FloatInput(name = 'ITI Min (sec)', value = 1.0, start = 0, step = 0.1, **sw)
        self.STATE.intertrial_max_dur = pn.widgets.FloatInput(name = 'ITI Max (sec)', value = 2.0, start = self.STATE.intertrial_min_dur.param.value, step = 0.1, **sw)
        self.STATE.intertrial_stimulus = pn.widgets.TextInput(name = 'ITI Stimulus', value = '+', **sw)

        @pn.depends(
                self.STATE.classes, 
                self.STATE.trials_per_class, 
                self.STATE.trial_duration,
                self.STATE.intertrial_min_dur,
                self.STATE.intertrial_max_dur,
                self.STATE.pre_run_duration,
                self.STATE.post_run_duration,
                watch = True )
        def update_run_calc(
            classes: typing.List[str], 
            trials_per_class: int,
            trial_dur: float,
            iti_min: float,
            iti_max: float,
            pre_run: float,
            post_run: float
        ):
            n_trials = len(classes) * trials_per_class
            avg_iti = iti_min + (iti_max - iti_min) / 2
            run_len = (avg_iti + trial_dur) * n_trials
            run_len = pre_run + run_len + post_run
            run_dur = str(datetime.timedelta(seconds = run_len))
            self.STATE.run_info.value = f'{len(classes)} class(es), {n_trials} trial(s), ~{run_dur}'

        # This is done here to kick the calculation for run_calc
        default_classes = ['REST']
        self.STATE.classes.param.update(
            value = default_classes, 
            options = default_classes
        )

        self.STATE.task_controls = pn.WidgetBox(
            self.STATE.classes,
            pn.Row(
                self.STATE.new_class,
                self.STATE.add_new_class
            ),
            pn.Row(
                self.STATE.trials_per_class,
                self.STATE.trial_duration,
            ),
            pn.Row(
                self.STATE.pre_run_duration,
                self.STATE.post_run_duration,
            ), 
            pn.Row(
                self.STATE.intertrial_min_dur, 
                self.STATE.intertrial_max_dur, 
                self.STATE.intertrial_stimulus
            ),
            sizing_mode = 'stretch_both'
        )

        self.STATE.output_class = asyncio.Queue()
        self.STATE.input_class = asyncio.Queue()
    
    @ez.subscriber(INPUT_CLASS)
    async def on_class_input(self, msg: typing.Optional[str]) -> None:
        self.STATE.input_class.put_nowait(msg)

    @ez.publisher(OUTPUT_TARGET_CLASS)
    async def output_class(self) -> typing.AsyncGenerator:
        while True:
            out_class = await self.STATE.output_class.get()
            yield self.OUTPUT_TARGET_CLASS, out_class

    async def task_implementation(self) -> typing.AsyncIterator[typing.Optional[SampleTriggerMessage]]:

        self.STATE.task_controls.disabled = True

        try:
            # Grab all widget values so they can't be changed during run
            classes: typing.List[str] = self.STATE.classes.value # type: ignore
            trials_per_class: int = self.STATE.trials_per_class.value # type: ignore
            trial_dur: float = self.STATE.trial_duration.value # type: ignore
            iti_min: float = self.STATE.intertrial_min_dur.value # type: ignore
            iti_max: float = self.STATE.intertrial_max_dur.value # type: ignore
            iti_stim: str = self.STATE.intertrial_stimulus.value # type: ignore
            pre_run_duration: float = self.STATE.pre_run_duration.value # type: ignore
            post_run_duration: float = self.STATE.post_run_duration.value # type: ignore

            # Create trial order (blockwise randomized)
            trials: typing.List[str] = []
            for _ in range(trials_per_class):
                random.shuffle(classes)
                trials += classes

            self.STATE.progress.max = len(trials)
            self.STATE.progress.value = 0
            self.STATE.progress.bar_color = 'primary'
            self.STATE.progress.disabled = False

            self.STATE.status.value = 'Pre Run'
            await asyncio.sleep(pre_run_duration)

            for trial_idx, trial_class in enumerate(trials):

                trial_id = f'Trial {trial_idx + 1} / {len(trials)}'
                
                self.STATE.status.value = f'{trial_id}: Intertrial Interval'
                iti = random.uniform(iti_min, iti_max)
                self.STATE.stimulus.value = iti_stim
                self.STATE.output_class.put_nowait(None)
                await asyncio.sleep(iti)

                self.STATE.status.value = f'{trial_id}: Action ({trial_class})'
                self.STATE.stimulus.value = trial_class
                self.STATE.output_class.put_nowait(trial_class)
                yield SampleTriggerMessage(
                    period = (0.0, trial_dur), 
                    value = trial_class
                )
                await asyncio.sleep(trial_dur)
                self.STATE.progress.value = trial_idx + 1

            self.STATE.status.value = 'Post Run'
            self.STATE.stimulus.value = ''
            self.STATE.output_class.put_nowait(None)
            await asyncio.sleep(post_run_duration)

            raise TaskComplete

        finally:
            self.STATE.stimulus.value = ''
            self.STATE.task_controls.disabled = False
    
    def content(self) -> pn.viewable.Viewable:
        return self.STATE.task_area
    
    def sidebar(self) -> pn.viewable.Viewable:
        sidebar = super().sidebar()
        sidebar.extend([
            pn.Card(
                self.STATE.task_controls, 
                title = 'Cued Action Task'
            )
        ])
        return sidebar


class CuedActionTask(Task):
    INPUT_CLASS = ez.InputStream(typing.Optional[str])
    OUTPUT_TARGET_CLASS = ez.OutputStream(typing.Optional[str])

    TASK:CuedActionTaskImplementation = CuedActionTaskImplementation()

    def network(self) -> ez.NetworkDefinition:
        return list(super().network()) + [
            (self.INPUT_CLASS, self.TASK.INPUT_CLASS),
            (self.TASK.OUTPUT_TARGET_CLASS, self.OUTPUT_TARGET_CLASS)
        ]
    