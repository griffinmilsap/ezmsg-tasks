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

class AsyncButton(pn.widgets.Button):
    """ Extension of button functionality to introduce an async wait method """
    
    _aio_event: asyncio.Event

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._aio_event = asyncio.Event()
        self.on_click(lambda _: self._aio_event.set())

    async def wait(self) -> None:
        self._aio_event.clear()
        await self._aio_event.wait()


DIRECTIONS = ['UP', 'DOWN', 'LEFT', 'RIGHT']   

class ReactionTaskImplementationState(TaskImplementationState):
    task_area: pn.layout.Card
    button: AsyncButton
    pre_run_duration: pn.widgets.FloatInput
    post_run_duration: pn.widgets.FloatInput
    trials_per_class: pn.widgets.IntInput

    center_out: pn.widgets.Checkbox
    timeout: pn.widgets.FloatInput
    intertrial_min_dur: pn.widgets.FloatInput
    intertrial_max_dur: pn.widgets.FloatInput
    task_controls: pn.layout.WidgetBox

    decode_class: pn.widgets.TextInput
    cur_class: typing.Optional[str] = None
    decode_event: asyncio.Event

    direction_button: typing.Dict[str, AsyncButton]

class ReactionTaskImplementation(TaskImplementation):
    STATE = ReactionTaskImplementationState

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

        self.STATE.button = AsyncButton(
            # name = 'center',
            width = 100, 
            height = 100, 
            button_type = 'primary', 
            disabled = True, 
            align = ('center', 'center')
        )

        self.STATE.direction_button = {
            direction: AsyncButton(
                # name = direction, 
                width = 100, 
                height = 100, 
                button_type = 'success',
                disabled = True, 
                align = ('center', 'center')
            ) 
            for direction in DIRECTIONS
        }

        UP = self.STATE.direction_button['UP']
        DOWN = self.STATE.direction_button['DOWN']
        LEFT = self.STATE.direction_button['LEFT']
        RIGHT = self.STATE.direction_button['RIGHT']
        CENTER = self.STATE.button

        self.STATE.task_area = pn.Card(
            pn.Column(
                pn.layout.VSpacer(),
                pn.Row(
                    pn.layout.HSpacer(),
                    pn.layout.GridBox(
                        None, UP,     None, 
                        LEFT, CENTER, RIGHT, 
                        None, DOWN,   None, 
                        ncols = 3, nrows = 3, 
                        width = 600, height = 600
                    ),
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

        self.STATE.center_out = pn.widgets.Checkbox(name = 'Center Out', value = False, **sw)
        self.STATE.decode_class = pn.widgets.TextInput(name = 'Decode Class', placeholder = 'GO', **sw)
        self.STATE.trials_per_class = pn.widgets.IntInput(name = 'Num Trials', value = 5, start = 1, **sw)
        self.STATE.pre_run_duration = pn.widgets.FloatInput(name = 'Pre-run (sec)', value = 3, start = 0, **sw)
        self.STATE.post_run_duration = pn.widgets.FloatInput(name = 'Post-run (sec)', value = 3, start = 0, **sw)

        self.STATE.timeout = pn.widgets.FloatInput(name = 'Trial Timeout (sec)', value = 4.0, step = 0.1, start = 0.1, end = self.SETTINGS.buffer_dur, **sw)
        self.STATE.intertrial_min_dur = pn.widgets.FloatInput(name = 'ITI Min (sec)', value = 1.0, start = 0, step = 0.1, **sw)
        self.STATE.intertrial_max_dur = pn.widgets.FloatInput(name = 'ITI Max (sec)', value = 2.0, start = self.STATE.intertrial_min_dur.param.value, step = 0.1, **sw)

        @pn.depends(
                self.STATE.trials_per_class,
                self.STATE.center_out, 
                self.STATE.timeout,
                self.STATE.intertrial_min_dur,
                self.STATE.intertrial_max_dur,
                self.STATE.pre_run_duration,
                self.STATE.post_run_duration,
                watch = True )
        def update_run_calc(
            trials_per_class: int,
            center_out: bool,
            timeout: float,
            iti_min: float,
            iti_max: float,
            pre_run: float,
            post_run: float
        ):
            n_classes = len(DIRECTIONS) if center_out else 1
            avg_iti = iti_min + (iti_max - iti_min) / 2
            run_len = (avg_iti + timeout) * trials_per_class * n_classes
            run_len = pre_run + run_len + post_run
            run_dur = str(datetime.timedelta(seconds = run_len))
            self.STATE.run_info.value = f'{n_classes} class(es) x {trials_per_class} trial(s), ~{run_dur}'

        # This is done here to kick the calculation for run_calc
        self.STATE.trials_per_class.param.update(value = 10)

        self.STATE.task_controls = pn.WidgetBox(
            self.STATE.center_out,
            pn.Row(
                self.STATE.trials_per_class,
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
            trials_per_class: int = int(self.STATE.trials_per_class.value) # type: ignore
            timeout_sec: float = float(self.STATE.timeout.value) # type: ignore
            iti_min: float = float(self.STATE.intertrial_min_dur.value) # type: ignore
            iti_max: float = float(self.STATE.intertrial_max_dur.value) # type: ignore
            pre_run_duration: float = float(self.STATE.pre_run_duration.value) # type: ignore
            post_run_duration: float = float(self.STATE.post_run_duration.value) # type: ignore
            center_out: bool = bool(self.STATE.center_out.value) # type: ignore

            classes = DIRECTIONS if center_out else ['CENTER']

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
                await asyncio.sleep(iti)

                self.STATE.status.value = f'{trial_id}: {trial_class}'

                start_time = time.time()

                timeout = False
                try:
                    await asyncio.wait_for(
                        self.center_trial() 
                        if trial_class == 'CENTER'
                        else self.direction_trial(trial_class), 
                        timeout = timeout_sec
                    )
                except asyncio.TimeoutError:
                    timeout = True

                delta = time.time() - start_time

                yield SampleTriggerMessage(period = (-delta, 0), value = 'TIMEOUT' if timeout else trial_class)
                self.STATE.progress.value = trial_idx + 1

            self.STATE.status.value = 'Post Run'
            await asyncio.sleep(post_run_duration)

            raise TaskComplete

        finally:
            self.STATE.task_controls.disabled = False

    async def center_trial(self) -> None:
        """ A center trial has no direction component 
        and can be concluded using decode_class"""
        try:
            self.STATE.decode_event.clear()
            self.STATE.button.disabled = False
            await asyncio.wait([
                asyncio.create_task(coro) for coro in [
                    self.STATE.button.wait(),
                    self.STATE.decode_event.wait()
                ]],
                return_when = asyncio.FIRST_COMPLETED
            ) 
            await asyncio.sleep(0.1) # working around race condition in panel
        except asyncio.CancelledError:
            ez.logger.debug('center trial cancelled')
        finally:
            self.STATE.button.disabled = True

    async def direction_trial(self, direction: str) -> None:
        """ A direction class can only be completed using button clicks"""
        direction_button = self.STATE.direction_button[direction]
        try:
            self.STATE.button.disabled = False
            await self.STATE.button.wait()
            await asyncio.sleep(0.1) # working around race condition in panel
            self.STATE.button.disabled = True

            direction_button.disabled = False
            await direction_button.wait()
            await asyncio.sleep(0.1) # working around race condition in panel
            direction_button.disabled = True

            self.STATE.button.disabled = False
            await self.STATE.button.wait()
            await asyncio.sleep(0.1) # working around race condition in panel
            self.STATE.button.disabled = True

        except asyncio.CancelledError:
            ez.logger.debug('trial cancelled')
        
        finally:
            self.STATE.button.disabled = True
            direction_button.disabled = True
    
    def content(self) -> pn.viewable.Viewable:
        return self.STATE.task_area
    
    def sidebar(self) -> pn.viewable.Viewable:
        sidebar = super().sidebar()
        sidebar.extend([
            pn.Card(
                self.STATE.task_controls, 
                title = 'Reaction Task'
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
    