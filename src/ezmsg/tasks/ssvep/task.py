import math
import time
import param
import typing
import asyncio
import datetime
import random

from dataclasses import dataclass, field

import ezmsg.core as ez
import panel as pn
import numpy as np

from ezmsg.sigproc.sampler import SampleTriggerMessage

from ..task import (
    Task,
    TaskComplete,
    TaskImplementation,
    TaskImplementationState,
)

from .dynamicclasses import DynamicClasses
from .stimulus import SSVEPStimulus, VisualMotionStimulus, IntermodulationSSVEP
from ..frequencydecodemessage import FrequencyDecodeMessage

STIMULUS_KWARGS = dict(width = 300, height = 200)

@dataclass
class SSVEPSampleTriggerMessage(SampleTriggerMessage):
    reversal_period_ms: typing.List[int] = field(default_factory=list)
    target: typing.Optional[int] = None

    @property
    def freqs(self) -> typing.List[float]:
        return [1000.0 / p for p in self.reversal_period_ms]

class SSVEPTaskImplementationState(TaskImplementationState):
    stimulus: pn.layout.Row
    task_area: pn.layout.Card

    classes: pn.Column #DynamicClasses
    multiclass: pn.widgets.Checkbox
    #rotation: pn.widgets.Checkbox
    stimulus_type: pn.widgets.Select
    stimulus_size: pn.widgets.IntInput

    feedback: pn.widgets.Checkbox
    pre_run_duration: pn.widgets.FloatInput
    post_run_duration: pn.widgets.FloatInput
    trials_per_class: pn.widgets.IntInput
    trial_duration: pn.widgets.FloatInput
    intertrial_min_dur: pn.widgets.FloatInput
    intertrial_max_dur: pn.widgets.FloatInput
    task_controls: pn.layout.WidgetBox

    input_decode: asyncio.Queue[FrequencyDecodeMessage]
    output_class: asyncio.Queue[typing.Optional[str]]

class SSVEPTaskImplementation(TaskImplementation):
    STATE = SSVEPTaskImplementationState

    INPUT_DECODE = ez.InputStream(FrequencyDecodeMessage)
    OUTPUT_TARGET_CLASS = ez.OutputStream(typing.Optional[str])
    
    @property
    def slug(self) -> str:
        """ Short-name used to identify recorded files """
        return 'SSVEP'
    
    @property
    def title(self) -> str:
        """ Title of task used in header of page """
        return 'Steady State Visually Evoked Potentials'
    
    async def initialize(self) -> None:
        await super().initialize()
        self.STATE.stimulus = pn.layout.Row(sizing_mode = 'stretch_width')

        self.STATE.task_area = pn.Card(
            pn.Column(
                pn.layout.VSpacer(),
                self.STATE.stimulus,
                pn.layout.VSpacer(),
                min_height = 700
            ),
            styles = {'background': '#808080'},
            hide_header = True,
            sizing_mode = 'stretch_both'
        )

        sw = dict(sizing_mode = 'stretch_width')
        self.STATE.classes = DynamicClasses(intermod=False)#, n_classes=param.Integer(default=0))
        self.STATE.multiclass = pn.widgets.Checkbox(name = 'Multiclass Presentation', value = False, **sw)
        self.STATE.stimulus_type = pn.widgets.Select(name='Stimulus Type', options=['Checkerboard', 'Visual Motion', 'Intermodulation'])
        self.STATE.stimulus_size = pn.widgets.IntInput(name = 'Stimulus Size (pixels)', value = 200, start = 10, **sw)

        self.STATE.trials_per_class = pn.widgets.IntInput(name = 'Trials per-class', value = 10, start = 1, **sw)
        self.STATE.feedback = pn.widgets.Checkbox(name = 'Display Feedback', value = False, **sw)
        self.STATE.pre_run_duration = pn.widgets.FloatInput(name = 'Pre-run (sec)', value = 3, start = 0, **sw)
        self.STATE.post_run_duration = pn.widgets.FloatInput(name = 'Post-run (sec)', value = 3, start = 0, **sw)

        self.STATE.trial_duration = pn.widgets.FloatInput(name = 'Trial dur. (sec)', value = 4.0, step = 0.1, start = 0.1, end = self.SETTINGS.buffer_dur, **sw)
        self.STATE.intertrial_min_dur = pn.widgets.FloatInput(name = 'ITI Min (sec)', value = 1.0, start = 0, step = 0.1, **sw)
        self.STATE.intertrial_max_dur = pn.widgets.FloatInput(name = 'ITI Max (sec)', value = 2.0, start = self.STATE.intertrial_min_dur.param.value, step = 0.1, **sw)

        

        @pn.depends(
                self.STATE.classes.classes.param.params()['objects'],
                self.STATE.trials_per_class, 
                self.STATE.trial_duration,
                self.STATE.intertrial_min_dur,
                self.STATE.intertrial_max_dur,
                self.STATE.pre_run_duration,
                self.STATE.post_run_duration,
                watch = True )
        def update_run_calc(
            classes: typing.List[typing.Any],
            trials_per_class: int,
            trial_dur: float,
            iti_min: float,
            iti_max: float,
            pre_run: float,
            post_run: float
        ):
            num_classes = len(classes)

            n_trials = num_classes * trials_per_class
            avg_iti = iti_min + (iti_max - iti_min) / 2
            run_len = (avg_iti + trial_dur) * n_trials
            run_len = pre_run + run_len + post_run
            run_dur = str(datetime.timedelta(seconds = run_len))
            self.STATE.run_info.value = f'{num_classes} class(es), {n_trials} trial(s), ~{run_dur}'
        # This is done here to kick the calculation for run_calc
        self.STATE.trials_per_class.param.update(value = 20)
        self.STATE.trials_per_class.param.update(value = 10)
        self.STATE.stimulus.clear()

        self.STATE.task_controls = pn.WidgetBox(
            self.STATE.classes,
            self.STATE.stimulus_size,
            self.STATE.multiclass,
            #self.STATE.rotation,
            self.STATE.stimulus_type,
            self.STATE.feedback,
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
            ),
            sizing_mode = 'stretch_both'
        )

        ''' handles ui changes related to different parameters needed for intermodulation and checker/vm'''        
        async def stim_type_callback(event):
            self.STATE.task_controls.remove(self.STATE.classes)
            if event.new == 'Intermodulation':
                print('intermod true')
                self.STATE.classes = DynamicClasses(intermod=True)
            elif event.old == 'Intermodulation':
                self.STATE.classes = DynamicClasses(intermod=False)
            self.STATE.task_controls.insert(0, self.STATE.classes)

        self.STATE.stimulus_type.param.watch(stim_type_callback, 'value')
        
        self.STATE.output_class = asyncio.Queue()
        self.STATE.input_decode = asyncio.Queue()
    
    @ez.subscriber(INPUT_DECODE)
    async def on_class_input(self, msg: FrequencyDecodeMessage) -> None:
        self.STATE.input_decode.put_nowait(msg)

    @ez.publisher(OUTPUT_TARGET_CLASS)
    async def output_class(self) -> typing.AsyncGenerator:
        while True:
            out_class = await self.STATE.output_class.get()
            yield self.OUTPUT_TARGET_CLASS, out_class

    async def task_implementation(self) -> typing.AsyncIterator[typing.Optional[SampleTriggerMessage]]:

        self.STATE.task_controls.disabled = True

        try:
            # Grab all widget values so they can't be changed during run
            stimulus_size: int = self.STATE.stimulus_size.value # type: ignore
            trials_per_class: int = self.STATE.trials_per_class.value # type: ignore
            trial_dur: float = self.STATE.trial_duration.value # type: ignore
            feedback: bool = self.STATE.feedback.value # type: ignore
            iti_min: float = self.STATE.intertrial_min_dur.value # type: ignore
            iti_max: float = self.STATE.intertrial_max_dur.value # type: ignore
            pre_run_duration: float = self.STATE.pre_run_duration.value # type: ignore
            post_run_duration: float = self.STATE.post_run_duration.value # type: ignore
            multiclass: bool = self.STATE.multiclass.value # type: ignore
            stimulus_type: str = self.STATE.stimulus_type.value # type: ignore

            #print(self.STATE.classes)
            #print(self.STATE.classes[0].setting)
            classes = self.STATE.classes.setting
            print(classes)
            for name, freqs in self.STATE.classes.setting.items():
                if(freqs[0] == 0):
                    del classes[name]
                elif(stimulus_type == 'Intermodulation' and freqs[1] == 0):
                    del classes[name]


            # Create trial order (blockwise randomized)
            trials: typing.List[str] = []
            for _ in range(trials_per_class):
                random.shuffle(list(classes.keys()))
                trials += classes

            self.STATE.progress.max = len(trials)
            self.STATE.progress.value = 0
            self.STATE.progress.bar_color = 'primary'
            self.STATE.progress.disabled = False

            self.STATE.status.value = 'Pre Run'
            await asyncio.sleep(pre_run_duration)
            self.STATE.input_decode = asyncio.Queue() # clear out the decode queue

            for trial_idx, trial_class in enumerate(trials):
                trial_id = f'Trial {trial_idx + 1} / {len(trials)}'
                
                self.STATE.status.value = f'{trial_id}: Intertrial Interval'
                iti = random.uniform(iti_min, iti_max)
                self.STATE.stimulus.clear()
                self.STATE.output_class.put_nowait(None)
                trial_str = pn.pane.Markdown("""### Starting {}""".format(trial_id), align=('center'))#pn.pane.Str(f'Starting {trial_id}')
                self.STATE.task_area.insert(0, trial_str)
                await asyncio.sleep(iti)
                self.STATE.task_area.remove(trial_str)

                stimuli = []
                if(stimulus_type == 'Checkerboard'):
                    stimuli = [SSVEPStimulus(
                        period_ms = int(1000/c[0]), 
                        width = stimulus_size, 
                        height = stimulus_size,
                        presented = False,
                        border = 3 if f == trial_class else 0,
                        ) for f, c in classes.items()
                    ]
                elif (stimulus_type == 'Visual Motion'):
                    stimuli = [VisualMotionStimulus(
                        period_ms = int(1000/c[0]), 
                        width = stimulus_size, 
                        height = stimulus_size,
                        presented = False,
                        border = 3 if f == trial_class else 0,
                        ) for f, c in classes.items()
                    ]
                elif(stimulus_type == 'Intermodulation'):
                    stimuli = [IntermodulationSSVEP(
                            period_ms = int(1000/c[0]), 
                            period_ms_2 = int(1000/c[1]),
                            width = stimulus_size, 
                            height = stimulus_size,
                            presented = False,
                            border = 3 if f == trial_class else 0,
                            ) for f, c in classes.items()
                        ] 


                target_stim = next(s for s in stimuli if s.period_ms == int(1000/classes[trial_class][0]))

                self.STATE.stimulus.append(pn.layout.HSpacer())
                if multiclass:
                    for stim in stimuli:
                        self.STATE.stimulus.append(stim)
                        self.STATE.stimulus.append(pn.layout.HSpacer())
                else:
                    self.STATE.stimulus.append(target_stim)
                    self.STATE.stimulus.append(pn.layout.HSpacer())

                await asyncio.sleep(1.0)

                for stim in stimuli:
                    stim.presented = True

                self.STATE.status.value = f'{trial_id}: Action ({classes[trial_class][0]:.02f})'
                self.STATE.output_class.put_nowait(trial_class)
                yield SSVEPSampleTriggerMessage(
                    period = (0.0, trial_dur), 
                    value = trial_class,
                    reversal_period_ms = [stim.period_ms for stim in stimuli], # type: ignore
                    target = stimuli.index(target_stim)
                )
                await asyncio.sleep(trial_dur)

                for stim in stimuli:
                    stim.presented = False
                    stim.border = 0

                # Deliver Feedback
                if feedback:
                    await asyncio.sleep(0.5)

                    try:
                        decode = await asyncio.wait_for(self.STATE.input_decode.get(), timeout = 2.0)
                        focus_idx = np.argmax(decode.data).item()
                        focus_per = round(1000.0 / decode.freqs[focus_idx])
                        correct = focus_per == target_stim.period_ms
                        ez.logger.info(f'{trial_class=}, {decode=}, {correct=}')

                        for stim in stimuli:
                            if stim.period_ms == focus_per:
                                stim.border = 3

                        await asyncio.sleep(0.5)                   
                    except asyncio.TimeoutError:
                        ez.logger.info('Feedback requested, but no decode received')
                
                self.STATE.progress.value = trial_idx + 1

            self.STATE.status.value = 'Post Run'
            self.STATE.stimulus.clear()
            self.STATE.output_class.put_nowait(None)
            await asyncio.sleep(post_run_duration)

            raise TaskComplete

        finally:
            self.STATE.stimulus.clear()
            self.STATE.task_controls.disabled = False
    
    def content(self) -> pn.viewable.Viewable:
        return self.STATE.task_area
    
    def sidebar(self) -> pn.viewable.Viewable:
        sidebar = super().sidebar()
        sidebar.extend([
            pn.Card(
                self.STATE.task_controls, 
                title = 'Steady State Visually Evoked Potentials'
            )
        ])
        return sidebar


class SSVEPTask(Task):
    INPUT_DECODE = ez.InputStream(FrequencyDecodeMessage)
    OUTPUT_TARGET_CLASS = ez.OutputStream(typing.Optional[str])

    TASK: SSVEPTaskImplementation = SSVEPTaskImplementation()

    def network(self) -> ez.NetworkDefinition:
        return list(super().network()) + [
            (self.INPUT_DECODE, self.TASK.INPUT_DECODE),
            (self.TASK.OUTPUT_TARGET_CLASS, self.OUTPUT_TARGET_CLASS)
        ]
    