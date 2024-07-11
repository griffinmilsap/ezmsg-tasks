import typing
import asyncio
import datetime
import random

from dataclasses import dataclass, field, replace

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

from .stimulus import RadialCheckerboard, Fixation, Blank, MultiStimulus, Rotation

from ..frequencydecodemessage import FrequencyDecodeMessage

STIMULUS_KWARGS = dict(size = 300)

@dataclass
class SSVEPSampleTriggerMessage(SampleTriggerMessage):
    reversal_period_ms: typing.List[int] = field(default_factory=list)
    target: typing.Optional[int] = None

    @property
    def freqs(self) -> typing.List[float]:
        return [1000.0 / p for p in self.reversal_period_ms]

class SSVEPTaskImplementationState(TaskImplementationState):
    stimulus: pn.pane.HTML
    task_area: pn.layout.Card

    classes: pn.widgets.MultiChoice
    multiclass: pn.widgets.Checkbox
    rotation: pn.widgets.Checkbox

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

    checker_map: typing.Dict[str, RadialCheckerboard]
    rotation_map: typing.Dict[str, Rotation]
    fixation: Fixation
    blank: Blank

class SSVEPTaskImplementation(TaskImplementation):
    STATE: SSVEPTaskImplementationState

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
        self.STATE.stimulus = pn.pane.HTML(sizing_mode = 'stretch_width')

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
        periods_ms = ((np.arange(6) * 20) + 40)[::-1]
        freqs = [f'{(1000.0/p):.02f} Hz' for p in periods_ms]
        self.STATE.checker_map = {f: RadialCheckerboard(duration_ms = p, **STIMULUS_KWARGS) for f, p in zip(freqs, periods_ms)}
        self.STATE.rotation_map = {f: Rotation(duration_ms = p, **STIMULUS_KWARGS) for f, p in zip(freqs, periods_ms)}
        self.STATE.fixation = Fixation(**STIMULUS_KWARGS)
        self.STATE.blank = Blank(**STIMULUS_KWARGS)

        self.STATE.classes = pn.widgets.MultiChoice(name = 'Classes', options = freqs, max_items = 4, **sw)
        self.STATE.multiclass = pn.widgets.Checkbox(name = 'Multiclass Presentation', value = False, **sw)
        self.STATE.rotation = pn.widgets.Checkbox(name = 'Rotation (freq/15) Hz', value = False, **sw)

        self.STATE.trials_per_class = pn.widgets.IntInput(name = 'Trials per-class', value = 10, start = 1, **sw)
        self.STATE.feedback = pn.widgets.Checkbox(name = 'Display Feedback', value = False, **sw)
        self.STATE.pre_run_duration = pn.widgets.FloatInput(name = 'Pre-run (sec)', value = 3, start = 0, **sw)
        self.STATE.post_run_duration = pn.widgets.FloatInput(name = 'Post-run (sec)', value = 3, start = 0, **sw)

        self.STATE.trial_duration = pn.widgets.FloatInput(name = 'Trial dur. (sec)', value = 4.0, step = 0.1, start = 0.1, end = self.SETTINGS.buffer_dur, **sw)
        self.STATE.intertrial_min_dur = pn.widgets.FloatInput(name = 'ITI Min (sec)', value = 1.0, start = 0, step = 0.1, **sw)
        self.STATE.intertrial_max_dur = pn.widgets.FloatInput(name = 'ITI Max (sec)', value = 2.0, start = self.STATE.intertrial_min_dur.param.value, step = 0.1, **sw)

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
        self.STATE.classes.param.update(value = [freqs[(len(freqs)//2)]])
        self.STATE.stimulus.object = self.STATE.fixation

        self.STATE.task_controls = pn.WidgetBox(
            self.STATE.classes,
            self.STATE.multiclass,
            self.STATE.rotation,
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
            classes: typing.List[str] = self.STATE.classes.value # type: ignore
            trials_per_class: int = self.STATE.trials_per_class.value # type: ignore
            trial_dur: float = self.STATE.trial_duration.value # type: ignore
            feedback: bool = self.STATE.feedback.value # type: ignore
            iti_min: float = self.STATE.intertrial_min_dur.value # type: ignore
            iti_max: float = self.STATE.intertrial_max_dur.value # type: ignore
            pre_run_duration: float = self.STATE.pre_run_duration.value # type: ignore
            post_run_duration: float = self.STATE.post_run_duration.value # type: ignore
            multiclass: bool = self.STATE.multiclass.value # type: ignore
            rotation: bool = self.STATE.rotation.value # type: ignore

            stimulus_map = self.STATE.rotation_map if rotation else self.STATE.checker_map
            periods = [round(stimulus_map[c].duration_ms * (7.5 if rotation else 1)) for c in classes]
            target_map = {c: periods.index(per) for c, per in zip(classes, periods)}

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
            self.STATE.input_decode = asyncio.Queue() # clear out the decode queue

            for trial_idx, trial_class in enumerate(trials):

                trial_id = f'Trial {trial_idx + 1} / {len(trials)}'
                
                self.STATE.status.value = f'{trial_id}: Intertrial Interval'
                iti = random.uniform(iti_min, iti_max)
                self.STATE.stimulus.object = self.STATE.fixation
                self.STATE.output_class.put_nowait(None)
                await asyncio.sleep(iti)

                stim = stimulus_map[trial_class]
                if multiclass:
                    stim = replace(stim, border = 5)
                    stim = MultiStimulus([
                        v if k != trial_class else stim 
                        for k, v in stimulus_map.items() 
                        if k in classes
                    ])

                self.STATE.status.value = f'{trial_id}: Action ({trial_class})'
                self.STATE.stimulus.object = stim
                self.STATE.output_class.put_nowait(trial_class)
                yield SSVEPSampleTriggerMessage(
                    period = (0.0, trial_dur), 
                    value = trial_class,
                    reversal_period_ms = periods,
                    target = target_map[trial_class]
                )
                await asyncio.sleep(trial_dur)

                self.STATE.stimulus.object = self.STATE.fixation

                # Deliver Feedback
                if feedback:
                    await asyncio.sleep(0.5)

                    # TODO: Timeout on decode
                    decode = await self.STATE.input_decode.get()
                    focus_idx = np.argmax(decode.data).item()
                    focus_per = round(1000.0 / decode.freqs[focus_idx])
                    correct = focus_per == stimulus_map[trial_class].duration_ms

                    if multiclass:
                        self.STATE.stimulus.object = MultiStimulus([
                            Blank(
                                border = 5 if i == focus_idx else None, 
                                **STIMULUS_KWARGS
                            )
                            for i in range(len(decode.freqs))
                        ])
                    else:
                        self.STATE.stimulus.object = Blank(
                            border = 5 if correct else 0,
                            **STIMULUS_KWARGS
                        )

                    await asyncio.sleep(0.5)                   
                
                self.STATE.progress.value = trial_idx + 1

            self.STATE.status.value = 'Post Run'
            self.STATE.stimulus.object = self.STATE.fixation
            self.STATE.output_class.put_nowait(None)
            await asyncio.sleep(post_run_duration)

            raise TaskComplete

        finally:
            self.STATE.stimulus.object = self.STATE.fixation
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
    