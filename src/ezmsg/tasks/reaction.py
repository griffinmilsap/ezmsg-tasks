import typing
import asyncio
import datetime
import random
import time

import ezmsg.core as ez
import panel as pn

from ezmsg.sigproc.sampler import SampleTriggerMessage

from .task import (
    Task,
    TaskComplete,
    TaskImplementation,
    TaskImplementationState,
)
    

class ReactionTaskImplementationState(TaskImplementationState):
    task_area: pn.layout.Card
    button: pn.widgets.Button
    pre_run_duration: pn.widgets.FloatInput
    post_run_duration: pn.widgets.FloatInput
    num_trials: pn.widgets.IntInput

    timeout: pn.widgets.FloatInput
    intertrial_min_dur: pn.widgets.FloatInput
    intertrial_max_dur: pn.widgets.FloatInput
    task_controls: pn.layout.WidgetBox

    decode_class: pn.widgets.TextInput
    cur_class: typing.Optional[str] = None
    button_event: asyncio.Event
    decode_event: asyncio.Event

class ReactionTaskImplementation(TaskImplementation):
    STATE: ReactionTaskImplementationState

    INPUT_DECODE = ez.InputStream(str)
    
    @property
    def slug(self) -> str:
        """ Short-name used to identify recorded files """
        return 'RXN'
    
    @property
    def title(self) -> str:
        """ Title of task used in header of page """
        return 'Reaction Time Task'
    
    async def initialize(self) -> None:
        await super().initialize()

        self.STATE.button = pn.widgets.Button(width = 100, height = 100, button_type = 'primary', disabled = True)
        self.STATE.button.on_click(lambda _: self.STATE.button_event.set())

        self.STATE.task_area = pn.Card(
            pn.Column(
                pn.layout.VSpacer(),
                pn.Row(
                    pn.layout.HSpacer(),
                    self.STATE.button,
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

        self.STATE.decode_class = pn.widgets.TextInput(name = 'Decode Class', placeholder = 'GO', **sw)
        self.STATE.num_trials = pn.widgets.IntInput(name = 'Num Trials', value = 5, start = 1, **sw)
        self.STATE.pre_run_duration = pn.widgets.FloatInput(name = 'Pre-run (sec)', value = 3, start = 0, **sw)
        self.STATE.post_run_duration = pn.widgets.FloatInput(name = 'Post-run (sec)', value = 3, start = 0, **sw)

        self.STATE.timeout = pn.widgets.FloatInput(name = 'Trial Timeout (sec)', value = 4.0, step = 0.1, start = 0.1, end = self.SETTINGS.buffer_dur, **sw)
        self.STATE.intertrial_min_dur = pn.widgets.FloatInput(name = 'ITI Min (sec)', value = 1.0, start = 0, step = 0.1, **sw)
        self.STATE.intertrial_max_dur = pn.widgets.FloatInput(name = 'ITI Max (sec)', value = 2.0, start = self.STATE.intertrial_min_dur.param.value, step = 0.1, **sw)

        @pn.depends(
                self.STATE.num_trials, 
                self.STATE.timeout,
                self.STATE.intertrial_min_dur,
                self.STATE.intertrial_max_dur,
                self.STATE.pre_run_duration,
                self.STATE.post_run_duration,
                watch = True )
        def update_run_calc(
            num_trials: int,
            timeout: float,
            iti_min: float,
            iti_max: float,
            pre_run: float,
            post_run: float
        ):
            avg_iti = iti_min + (iti_max - iti_min) / 2
            run_len = (avg_iti + timeout) * num_trials
            run_len = pre_run + run_len + post_run
            run_dur = str(datetime.timedelta(seconds = run_len))
            self.STATE.run_info.value = f'{num_trials} trial(s), ~{run_dur}'

        # This is done here to kick the calculation for run_calc
        self.STATE.num_trials.param.update(value = 10)

        self.STATE.task_controls = pn.WidgetBox(
            pn.Row(
                self.STATE.num_trials,
                self.STATE.timeout,
            ),
            pn.Row(
                self.STATE.pre_run_duration,
                self.STATE.post_run_duration,
            ), 
            pn.Row(
                self.STATE.intertrial_min_dur, 
                self.STATE.intertrial_max_dur,
            ),
            self.STATE.decode_class,
            sizing_mode = 'stretch_both'
        )

        self.STATE.button_event = asyncio.Event()
        self.STATE.decode_event = asyncio.Event()

    @ez.subscriber(INPUT_DECODE)
    async def on_decode(self, msg: str) -> None:
        if self.STATE.cur_class != msg:
            self.STATE.cur_class = msg
            if self.STATE.cur_class == self.STATE.decode_class.value:
                self.STATE.decode_event.set()

    async def task_implementation(self) -> typing.AsyncIterator[typing.Optional[SampleTriggerMessage]]:

        self.STATE.task_controls.disabled = True

        try:
            # Grab all widget values so they can't be changed during run
            num_trials: int = int(self.STATE.num_trials.value) # type: ignore
            timeout_sec: float = float(self.STATE.timeout.value) # type: ignore
            iti_min: float = float(self.STATE.intertrial_min_dur.value) # type: ignore
            iti_max: float = float(self.STATE.intertrial_max_dur.value) # type: ignore
            pre_run_duration: float = float(self.STATE.pre_run_duration.value) # type: ignore
            post_run_duration: float = float(self.STATE.post_run_duration.value) # type: ignore

            self.STATE.progress.max = num_trials
            self.STATE.progress.value = 0
            self.STATE.progress.bar_color = 'primary'
            self.STATE.progress.disabled = False

            self.STATE.status.value = 'Pre Run'
            await asyncio.sleep(pre_run_duration)

            for trial_idx in range(num_trials):

                trial_id = f'Trial {trial_idx + 1} / {num_trials}'
                
                self.STATE.status.value = f'{trial_id}: Intertrial Interval'
                iti = random.uniform(iti_min, iti_max)
                self.STATE.button.disabled = True
                await asyncio.sleep(iti)

                self.STATE.button_event.clear()
                self.STATE.decode_event.clear()

                self.STATE.status.value = f'{trial_id}: GO)'
                self.STATE.button.disabled = False

                start_time = time.time()
                timeout = False
                done, _ = await asyncio.wait(
                    (
                        self.STATE.button_event.wait(), 
                        self.STATE.decode_event.wait(),
                    ), 
                    timeout = timeout_sec,
                    return_when = 'FIRST_COMPLETED',
                )

                # asyncio.wait doesn't raise TimeoutErrors. Huh.
                if len(done) == 0:
                    timeout = True

                delta = time.time() - start_time

                yield SampleTriggerMessage(period = (-delta, 0), value = 'TIMEOUT' if timeout else 'RXN')
                self.STATE.progress.value = trial_idx + 1

            self.STATE.status.value = 'Post Run'
            self.STATE.button.disabled = True
            await asyncio.sleep(post_run_duration)

            raise TaskComplete

        finally:
            self.STATE.button.disabled = True
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


class ReactionTask(Task):
    # Has to be INPUT_CLASS for compatibility with task directory
    INPUT_CLASS = ez.InputStream(typing.Optional[str])

    TASK:ReactionTaskImplementation = ReactionTaskImplementation()

    def network(self) -> ez.NetworkDefinition:
        return list(super().network()) + [
            (self.INPUT_CLASS, self.TASK.INPUT_DECODE),
        ]
    